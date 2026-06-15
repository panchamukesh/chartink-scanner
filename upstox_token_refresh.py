"""
Upstox daily access-token refresh via headless Playwright OAuth login.

Reads from .env:
  UPSTOX_API_KEY, UPSTOX_API_SECRET
  UPSTOX_LOGIN_USERNAME, UPSTOX_LOGIN_PASSWORD, UPSTOX_LOGIN_TOTP_SECRET

On success, rewrites UPSTOX_ACCESS_TOKEN= line in .env (local), and (if
configured) on the remote VM via ssh, then restarts the VM scanner server.

Exit code 0 on success, non-zero on any failure.
"""
import os
import re
import sys
import time
import subprocess
import logging

import pyotp
import requests
from playwright.sync_api import sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [token_refresh] %(levelname)s: %(message)s",
)
log = logging.getLogger("upstox_token_refresh")

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(ROOT, ".env")

REDIRECT_CANDIDATES = [
    "https://127.0.0.1",
    "https://127.0.0.1/callback",
    "https://localhost",
    "https://127.0.0.1/",
    "https://127.0.0.1:5000",
    "https://localhost/",
    "https://localhost/callback",
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1:3000",
]

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


def get_auth_code(api_key, username, password, totp_secret):
    """Run headless OAuth login flow, return (code, redirect_uri) or raise."""
    last_error = None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for redirect_uri in REDIRECT_CANDIDATES:
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            auth_url = (
                "https://api.upstox.com/v2/login/authorization/dialog"
                f"?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"
            )
            log.info(f"Trying redirect_uri={redirect_uri}")
            try:
                page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                # Navigation may "fail" because it redirects to a non-resolving
                # https://127.0.0.1 / https://localhost — that's actually success.
                final_url = page.url
                if "code=" in final_url:
                    code = re.search(r"code=([^&]+)", final_url).group(1)
                    log.info(f"Got auth code via redirect (after nav error) for {redirect_uri}")
                    browser.close()
                    return code, redirect_uri
                last_error = e
                log.warning(f"Navigation error for {redirect_uri}: {e}")
                context.close()
                continue

            time.sleep(1)
            body_text = page.content().lower()
            if "redirect_uri" in body_text and ("mismatch" in body_text or "invalid" in body_text or "not registered" in body_text):
                log.warning(f"redirect_uri={redirect_uri} rejected by Upstox before login page")
                screenshot_path = os.path.join(ROOT, f"upstox_redirect_error_{redirect_uri.replace('://','_').replace('/','_').replace(':','')}.png")
                page.screenshot(path=screenshot_path)
                log.warning(f"Screenshot saved: {screenshot_path}")
                context.close()
                last_error = RuntimeError(f"redirect_uri mismatch for {redirect_uri}")
                continue

            # We're on the login page. Try to fill credentials.
            try:
                code, final_redirect = _do_login(page, username, password, totp_secret, redirect_uri)
                browser.close()
                return code, final_redirect
            except Exception as e:
                log.warning(f"Login flow failed for redirect_uri={redirect_uri}: {e}")
                screenshot_path = os.path.join(ROOT, "upstox_login_error.png")
                try:
                    page.screenshot(path=screenshot_path)
                    log.warning(f"Screenshot saved: {screenshot_path}")
                except Exception:
                    pass
                last_error = e
                context.close()
                continue
        browser.close()
    raise RuntimeError(f"All redirect_uri candidates failed. Last error: {last_error}")


def _do_login(page, username, password, totp_secret, redirect_uri):
    """Fill the Upstox login form. Returns auth code on success."""
    # Step 1: mobile/username field
    log.info("On login page — filling username/mobile number")
    user_selectors = [
        "input#mobileNum",
        "input[type='text']",
        "input[name='username']",
        "input[id*='mobile']",
    ]
    filled = False
    for sel in user_selectors:
        if page.locator(sel).count() > 0:
            page.locator(sel).first.fill(username)
            filled = True
            break
    if not filled:
        raise RuntimeError("Could not find username/mobile input field")

    # Click "Get OTP" / "Continue"
    _click_first(page, ["button:has-text('Get OTP')", "button:has-text('Continue')", "button[type='submit']"])
    time.sleep(2)

    # Step 2: It might ask for OTP (SMS) here, or go straight to password.
    page_text = page.content().lower()
    if "otp" in page_text and "password" not in page_text:
        raise RuntimeError("BLOCKED: Upstox requires SMS OTP at this step — cannot be scripted headlessly")

    # Step 3: password field
    pw_selectors = ["input[type='password']", "input#password", "input[name='password']"]
    filled = False
    for sel in pw_selectors:
        if page.locator(sel).count() > 0:
            page.locator(sel).first.fill(password)
            filled = True
            break
    if not filled:
        raise RuntimeError("Could not find password input field")

    _click_first(page, ["button:has-text('Continue')", "button:has-text('Login')", "button[type='submit']"])
    time.sleep(2)

    # Step 4: TOTP / 2FA field
    page_text = page.content().lower()
    totp_selectors = ["input[id*='otp']", "input[id*='totp']", "input[name='otp']", "input[type='text']", "input[type='tel']", "input[type='number']"]
    totp_code = pyotp.TOTP(totp_secret).now()
    filled = False
    for sel in totp_selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            # avoid re-filling username field if it's the same selector
            for i in range(loc.count()):
                el = loc.nth(i)
                if el.is_visible():
                    el.fill(totp_code)
                    filled = True
                    break
        if filled:
            break
    if not filled:
        raise RuntimeError("BLOCKED: Could not find TOTP/2FA input field — possible CAPTCHA or unexpected screen")

    _click_first(page, ["button:has-text('Continue')", "button:has-text('Submit')", "button:has-text('Verify')", "button[type='submit']"])

    # Wait for redirect to redirect_uri with ?code=
    for _ in range(20):
        url = page.url
        if "code=" in url:
            code = re.search(r"code=([^&]+)", url).group(1)
            return code, redirect_uri
        time.sleep(1)

    raise RuntimeError(f"Timed out waiting for auth code redirect. Final URL: {page.url}")


def _click_first(page, selectors):
    for sel in selectors:
        loc = page.locator(sel)
        if loc.count() > 0 and loc.first.is_visible():
            loc.first.click()
            return True
    return False


def exchange_code_for_token(code, api_key, api_secret, redirect_uri):
    resp = requests.post(
        "https://api.upstox.com/v2/login/authorization/token",
        headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed: {resp.status_code} {resp.text[:300]}")
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {data}")
    return token


def verify_token(token):
    resp = requests.get(
        "https://api.upstox.com/v2/user/profile",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=15,
    )
    return resp.status_code == 200 and resp.json().get("status") == "success"


def update_vm_env_and_restart(token):
    """Update .env on VM via ssh and restart scanner server."""
    remote_cmd = (
        f"sed -i 's|^UPSTOX_ACCESS_TOKEN=.*|UPSTOX_ACCESS_TOKEN={token}|' {VM_ENV_PATH} && "
        + VM_RESTART_CMD
    )
    result = subprocess.run(
        ["ssh", "-i", VM_SSH_KEY, VM_HOST, remote_cmd],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"VM update/restart failed: {result.stderr[:500]}")
    log.info("VM .env updated and scanner server restarted")


def main():
    env = load_env(ENV_PATH)
    api_key = env.get("UPSTOX_API_KEY")
    api_secret = env.get("UPSTOX_API_SECRET")
    username = env.get("UPSTOX_LOGIN_USERNAME")
    password = env.get("UPSTOX_LOGIN_PASSWORD")
    totp_secret = env.get("UPSTOX_LOGIN_TOTP_SECRET")

    missing = [k for k, v in {
        "UPSTOX_API_KEY": api_key, "UPSTOX_API_SECRET": api_secret,
        "UPSTOX_LOGIN_USERNAME": username, "UPSTOX_LOGIN_PASSWORD": password,
        "UPSTOX_LOGIN_TOTP_SECRET": totp_secret,
    }.items() if not v]
    if missing:
        log.error(f"Missing required .env keys: {missing}")
        sys.exit(1)

    try:
        log.info("Starting headless Upstox OAuth login...")
        code, redirect_uri = get_auth_code(api_key, username, password, totp_secret)
        log.info(f"Got auth code (redirect_uri={redirect_uri})")

        token = exchange_code_for_token(code, api_key, api_secret, redirect_uri)
        log.info("Access token obtained.")

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
