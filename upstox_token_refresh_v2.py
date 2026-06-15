"""
Upstox daily access-token refresh using plain `requests` + `pyotp`
(no `upstox_totp` package dependency - so it can run on Python 3.10 venvs,
e.g. the always-on VM).

Replicates the HTTP flow used by the `upstox_totp` package:
  1. GET  /v2/login/authorization/dialog          -> user_id, client_id, user_type
  2. POST /login/open/v6/auth/1fa/otp/generate     -> validateOTPToken
  3. POST /login/open/v4/auth/1fa/otp-totp/verify  -> verifies pyotp TOTP code
  4. POST /login/open/v3/auth/2fa                  -> PIN submission
  5. POST /login/v2/oauth/authorize                -> redirectUri containing auth code
  6. POST /v2/login/authorization/token            -> access_token

Reads from .env (in CWD):
  UPSTOX_USERNAME, UPSTOX_PIN_CODE, UPSTOX_TOTP_SECRET,
  UPSTOX_CLIENT_ID, UPSTOX_CLIENT_SECRET, UPSTOX_REDIRECT_URI

On success:
  - Verifies token against GET https://api.upstox.com/v2/user/profile
  - Updates UPSTOX_ACCESS_TOKEN= in .env (current directory)
  - On Linux, restarts the scanner server (pkill + setsid relaunch)

Exit code 0 on success, non-zero on any failure.
Never logs full secrets/tokens (masks all but last 4 chars).
"""

import os
import sys
import base64
import random
import string
import subprocess
import logging
import platform
from urllib.parse import urlparse, parse_qs

import requests
import pyotp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [token_refresh_v2] %(levelname)s: %(message)s",
)
log = logging.getLogger("upstox_token_refresh_v2")

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

BASE_API = "https://api.upstox.com"
BASE_SERVICE = "https://service.upstox.com"
BASE_LOGIN = "https://login.upstox.com"
REDIRECT_URI_UPSTOX = "https://api-v2.upstox.com/login/authorization/redirect"

VM_RESTART_CMDS = [
    "pkill -f 'python3 server.py'",
]


def mask(s):
    if not s:
        return "<empty>"
    s = str(s)
    if len(s) <= 4:
        return "*" * len(s)
    return "*" * (len(s) - 4) + s[-4:]


def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def update_env_file(path, key, value):
    lines = []
    found = False
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def gen_request_id():
    return "WPRO-" + "".join(random.choices(string.ascii_letters + string.digits, k=10))


def build_session():
    request_id = gen_request_id()
    headers = {
        "accept": "*/*",
        "accept-language": "en-GB,en;q=0.9",
        "content-type": "application/json",
        "origin": "https://login.upstox.com",
        "priority": "u=1, i",
        "referer": "https://login.upstox.com",
        "sec-ch-ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "x-device-details": (
            "platform=WEB|osName=Mac OS/10.15.7|osVersion=Chrome/140.0.0.0|appVersion=4.0.0|"
            "modelName=Chrome|manufacturer=Apple|uuid=3Z1IVTlV4rUUGbNp8KP0|"
            "userAgent=Upstox 3.0 Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        ),
        "x-request-id": request_id,
    }
    session = requests.Session()
    session.headers.update(headers)
    return session, request_id


def step1_user_id_and_type(session, client_id, redirect_uri):
    url = BASE_API + "/v2/login/authorization/dialog"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    resp = session.get(url, params=params, allow_redirects=True, timeout=20)
    final_url = resp.url
    parsed = urlparse(final_url)
    q = parse_qs(parsed.query)

    user_id = q.get("user_id")
    rclient_id = q.get("client_id")
    user_type = q.get("user_type")

    if not user_id or not rclient_id or not user_type:
        raise RuntimeError(f"Step1 failed - missing params in redirect URL: {final_url} -> {q}")

    return user_id[0], rclient_id[0], user_type[0]


def _check_json_response(resp, step_name):
    if resp.headers.get("Content-Type", "").startswith("application/json"):
        data = resp.json()
        if "success" in data and not data["success"]:
            raise RuntimeError(f"{step_name} failed: {data.get('error')}")
        if isinstance(data.get("data"), dict) and data["data"].get("status") == "error":
            raise RuntimeError(f"{step_name} failed: {data}")
        return data
    raise RuntimeError(f"{step_name}: unexpected content-type {resp.headers.get('Content-Type')}, status {resp.status_code}, body: {resp.text[:300]}")


def step2_generate_otp(session, username, user_id):
    url = BASE_SERVICE + "/login/open/v6/auth/1fa/otp/generate"
    payload = {"data": {"mobileNumber": username, "userId": user_id}}
    resp = session.post(url, json=payload, timeout=20)
    data = _check_json_response(resp, "generate_otp")
    inner = data.get("data", data)
    token = inner.get("validateOTPToken")
    if not token:
        raise RuntimeError(f"generate_otp: no validateOTPToken in response: {data}")
    return token


def step3_verify_otp(session, totp_code, validate_otp_token):
    url = BASE_SERVICE + "/login/open/v4/auth/1fa/otp-totp/verify"
    payload = {"data": {"otp": totp_code, "validateOtpToken": validate_otp_token}}
    resp = session.post(url, json=payload, timeout=20)
    _check_json_response(resp, "verify_otp")


def step4_submit_pin(session, client_id, pin_code):
    url = BASE_SERVICE + "/login/open/v3/auth/2fa"
    pin_encoded = base64.b64encode(pin_code.encode()).decode()
    params = {"client_id": client_id, "redirect_uri": REDIRECT_URI_UPSTOX}
    payload = {"data": {"twoFAMethod": "SECRET_PIN", "inputText": pin_encoded}}
    resp = session.post(url, params=params, json=payload, allow_redirects=True, timeout=20)
    _check_json_response(resp, "submit_pin")


def step5_oauth_authorize(session, client_id, request_id):
    url = BASE_SERVICE + "/login/v2/oauth/authorize"
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI_UPSTOX,
        "requestId": request_id,
        "response_type": "code",
    }
    payload = {"data": {"userOAuthApproval": True}}
    resp = session.post(url, params=params, json=payload, allow_redirects=True, timeout=20)
    data = _check_json_response(resp, "oauth_authorize")
    inner = data.get("data", data)
    redirect_uri = inner.get("redirectUri")
    if not redirect_uri:
        raise RuntimeError(f"oauth_authorize: no redirectUri in response: {data}")

    parsed = urlparse(redirect_uri)
    q = parse_qs(parsed.query)
    code = q.get("code")
    if not code:
        raise RuntimeError(f"oauth_authorize: no code in redirectUri: {redirect_uri}")
    return code[0]


def step6_exchange_token(code, client_id, client_secret, redirect_uri):
    url = BASE_API + "/v2/login/authorization/token"
    headers = {
        "accept": "application/json",
        "content-type": "application/x-www-form-urlencoded",
    }
    data = (
        f"code={code}&client_id={client_id}&client_secret={client_secret}"
        f"&redirect_uri={redirect_uri}&grant_type=authorization_code"
    )
    resp = requests.post(url, data=data, headers=headers, timeout=20)
    payload = resp.json()
    if "data" in payload and isinstance(payload["data"], dict):
        inner = payload["data"]
    else:
        inner = payload

    access_token = inner.get("access_token")
    if not access_token:
        raise RuntimeError(f"token exchange failed: {payload}")
    return access_token, inner.get("user_id")


def verify_token(token):
    resp = requests.get(
        "https://api.upstox.com/v2/user/profile",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    return resp.status_code == 200


def restart_scanner_if_linux():
    if platform.system() != "Linux":
        log.info("Not Linux - skipping scanner restart.")
        return
    try:
        subprocess.run(["pkill", "-f", "python3 server.py"], check=False)
        import time
        time.sleep(2)
        venv_python = "/home/priya141ch/chartink-venv/bin/python3"
        cmd = f"cd {ROOT} && setsid {venv_python} server.py >> server.log 2>&1 < /dev/null &"
        subprocess.Popen(cmd, shell=True, executable="/bin/bash")
        log.info("Scanner server restarted.")
    except Exception as e:
        log.error(f"Failed to restart scanner: {e}")


def main():
    env = load_env(ENV_PATH)
    required = ["UPSTOX_USERNAME", "UPSTOX_PIN_CODE", "UPSTOX_TOTP_SECRET",
                "UPSTOX_CLIENT_ID", "UPSTOX_CLIENT_SECRET", "UPSTOX_REDIRECT_URI"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        log.error(f"Missing required .env keys: {missing}")
        sys.exit(1)

    username = env["UPSTOX_USERNAME"]
    pin_code = env["UPSTOX_PIN_CODE"]
    totp_secret = env["UPSTOX_TOTP_SECRET"]
    client_id_cfg = env["UPSTOX_CLIENT_ID"]
    client_secret = env["UPSTOX_CLIENT_SECRET"]
    redirect_uri = env["UPSTOX_REDIRECT_URI"]

    try:
        session, request_id = build_session()

        log.info("Step 1: authorization dialog -> user_id/client_id/user_type")
        user_id, client_id, user_type = step1_user_id_and_type(session, client_id_cfg, redirect_uri)
        log.info(f"  user_id={mask(user_id)} client_id={mask(client_id)} user_type={user_type}")

        log.info("Step 2: generate OTP")
        validate_otp_token = step2_generate_otp(session, username, user_id)

        log.info("Step 3: verify TOTP code")
        totp_code = pyotp.TOTP(totp_secret).now()
        step3_verify_otp(session, totp_code, validate_otp_token)

        log.info("Step 4: submit PIN (2FA)")
        step4_submit_pin(session, client_id, pin_code)

        log.info("Step 5: OAuth authorize -> auth code")
        code = step5_oauth_authorize(session, client_id, request_id)
        log.info(f"  auth code={mask(code)}")

        log.info("Step 6: exchange code for access token")
        token, returned_user_id = step6_exchange_token(code, client_id_cfg, client_secret, redirect_uri)
        log.info(f"  access_token={mask(token)} user_id={returned_user_id}")

        log.info("Verifying token against /v2/user/profile ...")
        if not verify_token(token):
            log.error("Token verification FAILED")
            sys.exit(1)
        log.info("Token verified OK.")

        update_env_file(ENV_PATH, "UPSTOX_ACCESS_TOKEN", token)
        log.info(f"Updated UPSTOX_ACCESS_TOKEN in {ENV_PATH}")

        restart_scanner_if_linux()

        log.info("Token refresh completed successfully.")
        sys.exit(0)

    except Exception as e:
        log.error(f"Token refresh FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
