"""
Angel One SmartAPI — real-time NSE 5-minute candle data.
No delay. No Yahoo Finance. Direct from exchange via your Angel One account.

Credentials read from .env:
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_MPIN, ANGEL_TOTP_SECRET
"""
import os
import math
import time
import threading
import requests
import pyotp
import pandas as pd
from datetime import datetime, timedelta, timezone

try:
    from SmartApi import SmartConnect
except ImportError:
    try:
        from smartapi import SmartConnect
    except ImportError:
        SmartConnect = None

_IST      = timezone(timedelta(hours=5, minutes=30))
_obj      = None          # SmartConnect session
_lock     = threading.Lock()
_token_map: dict = {}     # NSE symbol → Angel One instrument token


# ─── Auth ─────────────────────────────────────────────────────────────────────
def login() -> bool:
    global _obj
    if SmartConnect is None:
        print("[angel] smartapi-python not installed — run: pip install smartapi-python")
        return False

    api_key  = os.environ.get("ANGEL_API_KEY", "")
    client   = os.environ.get("ANGEL_CLIENT_CODE", "")
    mpin     = os.environ.get("ANGEL_MPIN", "")
    totp_key = os.environ.get("ANGEL_TOTP_SECRET", "")

    if not all([api_key, client, mpin, totp_key]):
        print("[angel] Missing credentials in .env")
        return False

    try:
        totp = pyotp.TOTP(totp_key).now()
        obj  = SmartConnect(api_key=api_key)
        resp = obj.generateSession(client, mpin, totp)
        if resp and resp.get("status"):
            with _lock:
                _obj = obj
            print(f"[angel] ✅ Logged in — {client}")
            return True
        print(f"[angel] Login failed: {resp.get('message','unknown')}")
        return False
    except Exception as e:
        print(f"[angel] Login error: {e}")
        return False


def _relogin():
    print("[angel] Session expired — re-logging in …")
    return login()


# ─── Instrument token map ─────────────────────────────────────────────────────
# Known NSE equity tokens (fallback if scrip master lookup misses them)
_KNOWN_TOKENS = {
    "RELIANCE": "2885",  "TCS": "11536",    "HDFCBANK": "1333",
    "INFY": "1594",      "ICICIBANK": "4963","SBIN": "3045",
    "LT": "11483",       "AXISBANK": "5900", "MARUTI": "10999",
    "TATAMOTORS": "3456","SUNPHARMA": "3351","CIPLA": "694",
    "ASIANPAINT": "236", "HINDUNILVR": "1394","NTPC": "11630",
    "POWERGRID": "14977","TITAN": "3506",    "BAJFINANCE": "317",
    "ADANIENT": "25",    "JSWSTEEL": "11723","ULTRACEMCO": "2770",
    "GRASIM": "1232",    "WIPRO": "3787",    "HCLTECH": "7229",
    "TECHM": "13538",    "BAJAJFINSV": "16675","KOTAKBANK": "1922",
    "INDUSINDBK": "5258","DRREDDY": "881",   "ONGC": "2475",
    "IOC": "1624",       "COALINDIA": "20374","TATASTEEL": "3499",
    "HINDALCO": "1363",  "BHARTIARTL": "10604","ITC": "1660",
    "HEROMOTOCO": "1348","EICHERMOT": "910", "DIVISLAB": "10940",
    "PIDILITIND": "2664","AMBUJACEM": "1270","UPL": "11287",
    "BRITANNIA": "547",  "IEX": "23650",     "IRCTC": "542358",
}


def build_token_map(universe: list) -> bool:
    """
    Download Angel One scrip master and map our stock symbols to tokens.
    Falls back to hardcoded known tokens for any that are missing.
    """
    global _token_map
    needed = {s["symbol"] for s in universe}
    tmap   = dict(_KNOWN_TOKENS)   # start with known tokens

    try:
        url  = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
        data = requests.get(url, timeout=30).json()
        for item in data:
            if item.get("exch_seg") != "NSE":
                continue
            sym = item.get("symbol", "").replace("-EQ", "").strip()
            if sym in needed:
                tmap[sym] = str(item["token"])   # scrip master overrides hardcoded
    except Exception as e:
        print(f"[angel] Scrip master download failed ({e}) — using hardcoded tokens")

    _token_map = {k: v for k, v in tmap.items() if k in needed}
    missing    = needed - set(_token_map.keys())
    print(f"[angel] Token map: {len(_token_map)}/{len(needed)} symbols "
          f"{'| missing: ' + str(missing) if missing else '✅ all mapped'}")
    return True


# ─── Candle fetch ─────────────────────────────────────────────────────────────
def _fetch_candles(symbol: str, interval: str = "FIVE_MINUTE", days: int = 5):
    """Fetch OHLCV candles from Angel One for one symbol."""
    global _obj
    token = _token_map.get(symbol)
    if not token or _obj is None:
        return None

    now       = datetime.now(_IST).replace(tzinfo=None)
    from_date = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    to_date   = now.strftime("%Y-%m-%d %H:%M")

    params = {
        "exchange":    "NSE",
        "symboltoken": token,
        "interval":    interval,
        "fromdate":    from_date,
        "todate":      to_date,
    }

    try:
        with _lock:
            resp = _obj.getCandleData(params)
    except Exception as e:
        err = str(e).lower()
        if "invalid" in err or "token" in err or "session" in err or "unauthori" in err:
            _relogin()
        print(f"[angel] Candle error {symbol}: {e}")
        return None

    if resp and resp.get("status") and resp.get("data"):
        return resp["data"]  # [[timestamp, O, H, L, C, V], ...]

    # Re-login on invalid session
    if resp and "invalid" in str(resp.get("message", "")).lower():
        _relogin()
    return None


# ─── Technical indicators ─────────────────────────────────────────────────────
def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).round(2)


def _safe(series: pd.Series, idx: int = -1) -> float:
    try:
        v = float(series.iloc[idx])
        return v if not math.isnan(v) else 0.0
    except Exception:
        return 0.0


def _compute(candles: list, sym_info: dict) -> dict | None:
    """Convert raw Angel One candle list → stock dict with all indicators."""
    if not candles or len(candles) < 55:
        return None

    # Angel One: [timestamp_str, open, high, low, close, volume]
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

    # ── Indicators on 5m bars ─────────────────────────────────────────────────
    ema5  = close.ewm(span=5,  adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    rsi   = _rsi(close, 14)

    cur_close  = _safe(close,  -1)
    cur_open   = _safe(df["open"], -1)
    cur_high   = _safe(high,   -1)
    cur_low    = _safe(low,    -1)
    cur_vol    = int(volume.iloc[-1]) if not math.isnan(float(volume.iloc[-1])) else 0
    avg_vol    = int(volume.tail(20).mean())

    ema5_cur   = _safe(ema5,  -1)
    ema5_prv   = _safe(ema5,  -2)
    sma50_cur  = _safe(sma50, -1)
    sma50_prv  = _safe(sma50, -2)
    rsi_cur    = _safe(rsi,   -1) or 50.0
    rsi_prv    = _safe(rsi,   -2) or 50.0

    # Day open = first candle of today
    today_str  = datetime.now(_IST).strftime("%Y-%m-%d")
    today_rows = df[df["ts"].astype(str).str.startswith(today_str)]
    day_open   = float(today_rows["open"].iloc[0]) if not today_rows.empty else cur_open
    change_pct = round((cur_close - day_open) / day_open * 100, 2) if day_open else 0.0

    # Resistance = highest high in dataset
    resistance = round(float(high.max()), 2)

    # Swing trend
    if cur_low > sma50_cur:
        swing_trend = "bullish"
    elif cur_high < sma50_cur:
        swing_trend = "bearish"
    else:
        swing_trend = "mixed"

    delivery = min(85.0, max(20.0, 50.0 + change_pct * 4))

    return {
        "symbol":      sym_info["symbol"],
        "name":        sym_info["name"],
        "sector":      sym_info["sector"],
        "close":       round(cur_close, 2),
        "open":        round(cur_open,  2),
        "high":        round(cur_high,  2),
        "low":         round(cur_low,   2),
        "changePct":   change_pct,
        "volume":      cur_vol,
        "avgVolume":   avg_vol,
        "rsi":         round(rsi_cur,   2),
        "prev_rsi":    round(rsi_prv,   2),
        "ema5":        round(ema5_cur,  2),
        "prev_ema5":   round(ema5_prv,  2),
        "ema20":       round(_safe(ema20, -1), 2),
        "ema50":       round(_safe(ema50, -1), 2),
        "sma20":       round(_safe(sma20, -1), 2),
        "sma50":       round(sma50_cur,  2),
        "prev_sma50":  round(sma50_prv,  2),
        "resistance":  resistance,
        "delivery":    round(delivery, 1),
        "pe":          0,
        "swing_trend": swing_trend,
        "timeframe":   "5m",
        "source":      "angel_one",
    }


# ─── Bulk refresh ─────────────────────────────────────────────────────────────
def refresh_universe(universe: list) -> dict:
    """
    Fetch 5m candles for all symbols, compute indicators.
    Returns dict: symbol → stock dict.
    Rate-limit safe: 0.35s between calls → ~16s for 45 stocks.
    """
    if _obj is None:
        print("[angel] Not logged in")
        return {}

    results = {}
    for i, sym_info in enumerate(universe):
        sym     = sym_info["symbol"]
        candles = _fetch_candles(sym, interval="FIVE_MINUTE", days=5)
        if candles:
            stock = _compute(candles, sym_info)
            if stock:
                results[sym] = stock
        if i < len(universe) - 1:
            time.sleep(0.35)   # stay within rate limit

    print(f"[angel] Refreshed {len(results)}/{len(universe)} symbols "
          f"@ {datetime.now(_IST).strftime('%H:%M:%S')} IST")
    return results


def is_ready() -> bool:
    return _obj is not None and bool(_token_map)
