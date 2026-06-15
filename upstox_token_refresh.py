"""
Upstox daily access-token refresh via the `upstox_totp` package
(TOTP-based login, no browser automation needed).

Reads from .env:
  UPSTOX_USERNAME, UPSTOX_PASSWORD, UPSTOX_PIN_CODE, UPSTOX_TOTP_SECRET,
  UPSTOX_CLIENT_ID, UPSTOX_CLIENT_SECRET, UPSTOX_REDIRECT_URI

On success:
  - Updates UPSTOX_ACCESS_TOKEN= in local .env
  - Updates UPSTOX_ACCESS_TOKEN= in VM .env via ssh
  - Restarts the VM scanner server

Exit code 0 on success, non-zero on any failure. Never logs full secrets/tokens.
"""
import os
import sys
import subprocess
import logging

import requests
from pydantic import SecretStr
from upstox_totp import UpstoxTOTP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [token_refresh] %(levelname)s: %(message)s",
)
log = logging.getLogger("upstox_token_refresh")

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

VM_HOST = "priya141ch@35.184.92.9"
VM_SSH_KEY = os.path.expanduser("~/.ssh/banknifty_vm")
VM_ENV_PATH = "/home/priya141ch/chartink-scanner/.env"
VM_RESTART_CMD = (
    "pkill -f 'python3 server.py'; sleep 2; "
    "cd chartink-scanner && "
    "setsid /home/priya141ch/chartink-venv/bin/python3 server.py "
    ">> server.log 2>&1 < /dev/null & disown"
)


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
    """Replace or append KEY=VALUE line in a .env file."""
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


def verify_token(token):
    resp = requests.get(
        "https://api.upstox.com/v2/user/profile",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    return resp.status_code == 200


def update_vm_env_and_restart(token):
    """Update .env on VM via ssh and restart scanner server."""
    sed_cmd = f"sed -i 's|^UPSTOX_ACCESS_TOKEN=.*|UPSTOX_ACCESS_TOKEN={token}|' {VM_ENV_PATH}"
    result = subprocess.run(
        ["ssh", "-i", VM_SSH_KEY, VM_HOST, sed_cmd],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"VM .env update failed: {result.stderr[:500]}")

    result = subprocess.run(
        ["ssh", "-i", VM_SSH_KEY, VM_HOST,
         'bash -lc "' + VM_RESTART_CMD.replace('"', '\\"') + '"'],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"VM restart failed: {result.stderr[:500]}")
    log.info("VM .env updated and scanner server restarted")


def main():
    env = load_env(ENV_PATH)

    required = ["UPSTOX_USERNAME", "UPSTOX_PIN_CODE", "UPSTOX_TOTP_SECRET",
                "UPSTOX_CLIENT_ID", "UPSTOX_CLIENT_SECRET", "UPSTOX_REDIRECT_URI"]
    missing = [k for k in required if not env.get(k)]
    if missing:
        log.error(f"Missing required .env keys: {missing}")
        sys.exit(1)

    # `password` is a required field for the package's Config model but is
    # not used by the OTP/PIN login flow itself - fall back to pin_code.
    password = env.get("UPSTOX_PASSWORD") or env.get("UPSTOX_PIN_CODE")

    try:
        log.info("Starting Upstox TOTP login flow...")
        upx = UpstoxTOTP(
            username=env["UPSTOX_USERNAME"],
            password=SecretStr(password),
            pin_code=SecretStr(env["UPSTOX_PIN_CODE"]),
            totp_secret=SecretStr(env["UPSTOX_TOTP_SECRET"]),
            client_id=env["UPSTOX_CLIENT_ID"],
            client_secret=SecretStr(env["UPSTOX_CLIENT_SECRET"]),
            redirect_uri=env["UPSTOX_REDIRECT_URI"],
        )

        response = upx.app_token.get_access_token()

        if not (response.success and response.data and response.data.access_token):
            log.error(f"Token generation failed: success={response.success} error={response.error}")
            sys.exit(1)

        token = response.data.access_token
        log.info(f"Access token obtained for user_id={response.data.user_id}")

        if not verify_token(token):
            log.error("New token failed verification against /v2/user/profile")
            sys.exit(1)
        log.info("Token verified OK against /v2/user/profile")

        update_env_file(ENV_PATH, "UPSTOX_ACCESS_TOKEN", token)
        log.info(f"Updated local .env at {ENV_PATH}")

        try:
            update_vm_env_and_restart(token)
        except Exception as e:
            log.error(f"VM update failed: {e}")
            sys.exit(1)

        log.info("Token refresh completed successfully.")
        sys.exit(0)

    except Exception as e:
        log.error(f"Token refresh FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
