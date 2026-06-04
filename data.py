"""
Live market data — fetches OHLCV + technical indicators for the scan universe.
Primary: yfinance (NSE via Yahoo Finance, no auth needed).
Angel One LTP can overlay live prices if credentials are set.
"""
import os
import math
import threading
import time as _time
from datetime import datetime

import yfinance as yf
import pandas as pd

# ─── Scan universe ────────────────────────────────────────────────────────────
UNIVERSE = [
    {"symbol": "RELIANCE",   "name": "Reliance Industries",       "sector": "Energy"},
    {"symbol": "TCS",        "name": "Tata Consultancy Services",  "sector": "IT"},
    {"symbol": "HDFCBANK",   "name": "HDFC Bank",                 "sector": "Banking"},
    {"symbol": "INFY",       "name": "Infosys",                   "sector": "IT"},
    {"symbol": "ICICIBANK",  "name": "ICICI Bank",                "sector": "Banking"},
    {"symbol": "SBIN",       "name": "State Bank of India",       "sector": "Banking"},
    {"symbol": "LT",         "name": "Larsen & Toubro",           "sector": "Capital Goods"},
    {"symbol": "AXISBANK",   "name": "Axis Bank",                 "sector": "Banking"},
    {"symbol": "MARUTI",     "name": "Maruti Suzuki",             "sector": "Auto"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors",               "sector": "Auto"},
    {"symbol": "SUNPHARMA",  "name": "Sun Pharmaceutical",        "sector": "Pharma"},
    {"symbol": "CIPLA",      "name": "Cipla",                     "sector": "Pharma"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints",              "sector": "Consumer"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever",        "sector": "Consumer"},
    {"symbol": "NTPC",       "name": "NTPC",                      "sector": "Power"},
    {"symbol": "POWERGRID",  "name": "Power Grid Corp",           "sector": "Power"},
    {"symbol": "TITAN",      "name": "Titan Company",             "sector": "Consumer"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance",             "sector": "Finance"},
    {"symbol": "ADANIENT",   "name": "Adani Enterprises",         "sector": "Metals"},
    {"symbol": "JSWSTEEL",   "name": "JSW Steel",                 "sector": "Metals"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement",          "sector": "Cement"},
    {"symbol": "GRASIM",     "name": "Grasim Industries",         "sector": "Cement"},
    {"symbol": "WIPRO",      "name": "Wipro",                     "sector": "IT"},
    {"symbol": "HCLTECH",    "name": "HCL Technologies",          "sector": "IT"},
    {"symbol": "TECHM",      "name": "Tech Mahindra",             "sector": "IT"},
    {"symbol": "BAJAJFINSV", "name": "Bajaj Finserv",             "sector": "Finance"},
    {"symbol": "KOTAKBANK",  "name": "Kotak Mahindra Bank",       "sector": "Banking"},
    {"symbol": "INDUSINDBK", "name": "IndusInd Bank",             "sector": "Banking"},
    {"symbol": "DRREDDY",    "name": "Dr. Reddy's Laboratories",  "sector": "Pharma"},
    {"symbol": "ONGC",       "name": "ONGC",                      "sector": "Energy"},
    {"symbol": "IOC",        "name": "Indian Oil Corporation",    "sector": "Energy"},
    {"symbol": "COALINDIA",  "name": "Coal India",                "sector": "Mining"},
    {"symbol": "TATASTEEL",  "name": "Tata Steel",                "sector": "Metals"},
    {"symbol": "HINDALCO",   "name": "Hindalco Industries",       "sector": "Metals"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel",             "sector": "Telecom"},
    {"symbol": "ITC",        "name": "ITC",                       "sector": "Consumer"},
    {"symbol": "HEROMOTOCO", "name": "Hero MotoCorp",             "sector": "Auto"},
    {"symbol": "EICHERMOT",  "name": "Eicher Motors",             "sector": "Auto"},
    {"symbol": "DIVISLAB",   "name": "Divi's Laboratories",       "sector": "Pharma"},
    {"symbol": "PIDILITIND", "name": "Pidilite Industries",       "sector": "Consumer"},
    {"symbol": "AMBUJACEM",  "name": "Ambuja Cements",            "sector": "Cement"},
    {"symbol": "UPL",        "name": "UPL",                       "sector": "Agri"},
    {"symbol": "BRITANNIA",  "name": "Britannia Industries",      "sector": "Consumer"},
    {"symbol": "IEX",        "name": "Indian Energy Exchange",    "sector": "Finance"},
    {"symbol": "IRCTC",      "name": "IRCTC",                     "sector": "Services"},
]

# Yahoo Finance suffix for NSE
YF_SUFFIX = ".NS"

# In-memory cache: symbol → stock dict
_cache: dict = {}
_cache_lock = threading.Lock()
_last_refresh: datetime | None = None


# ─── Technical indicators ─────────────────────────────────────────────────────
def _rsi(close: pd.Series, period=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).round(1)


def _compute(hist: pd.DataFrame, sym_info: dict) -> dict | None:
    if hist is None or len(hist) < 52:
        return None
    close  = hist["Close"].dropna()
    volume = hist["Volume"].dropna()
    if close.empty:
        return None

    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    rsi   = _rsi(close)

    latest = hist.iloc[-1]
    prev   = hist.iloc[-2] if len(hist) > 1 else hist.iloc[-1]

    prev_close = float(prev["Close"]) if float(prev["Close"]) != float(latest["Close"]) else float(hist["Close"].iloc[-3])
    change_pct = round((float(latest["Close"]) - prev_close) / prev_close * 100, 2)

    avg_vol = int(volume.tail(20).mean())
    # Delivery estimate: higher on strong up days
    delivery = min(85, max(20, 50 + change_pct * 4))

    return {
        "symbol":     sym_info["symbol"],
        "name":       sym_info["name"],
        "sector":     sym_info["sector"],
        "close":      round(float(latest["Close"]), 2),
        "open":       round(float(latest["Open"]),  2),
        "high":       round(float(latest["High"]),  2),
        "low":        round(float(latest["Low"]),   2),
        "changePct":  change_pct,
        "volume":     int(latest["Volume"]),
        "avgVolume":  avg_vol,
        "rsi":        round(float(rsi.iloc[-1]), 1) if not math.isnan(rsi.iloc[-1]) else 50.0,
        "ema20":      round(float(ema20.iloc[-1]), 2),
        "ema50":      round(float(ema50.iloc[-1]), 2),
        "sma20":      round(float(sma20.iloc[-1]), 2),
        "sma50":      round(float(sma50.iloc[-1]), 2),
        "resistance": round(float(hist["High"].tail(260).max()), 2),   # ~1-year high
        "delivery":   round(delivery, 1),
        "pe":         0,
    }


def refresh_all():
    """Download 1-year daily data for all universe symbols, compute indicators, cache."""
    global _last_refresh
    yf_symbols = [s["symbol"] + YF_SUFFIX for s in UNIVERSE]
    print(f"[data] Fetching {len(yf_symbols)} symbols from Yahoo Finance …")
    try:
        raw = yf.download(
            yf_symbols,
            period="1y",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"[data] Download error: {e}")
        return

    updated = {}
    for sym_info in UNIVERSE:
        yf_sym = sym_info["symbol"] + YF_SUFFIX
        try:
            if len(yf_symbols) == 1:
                hist = raw
            else:
                hist = raw[yf_sym] if yf_sym in raw.columns.get_level_values(0) else None
            result = _compute(hist, sym_info)
            if result:
                updated[sym_info["symbol"]] = result
        except Exception as e:
            print(f"[data] Error processing {sym_info['symbol']}: {e}")

    with _cache_lock:
        _cache.update(updated)
        _last_refresh = datetime.now()

    print(f"[data] Refreshed {len(updated)}/{len(UNIVERSE)} symbols at {_last_refresh.strftime('%H:%M:%S')}")


def get_all() -> list[dict]:
    """Return cached stock data list."""
    with _cache_lock:
        return list(_cache.values())


def get_eod_prices() -> dict:
    """Return symbol → current close price (for EOD update)."""
    with _cache_lock:
        return {sym: s["close"] for sym, s in _cache.items()}


def is_stale(max_minutes=10) -> bool:
    if _last_refresh is None:
        return True
    return (datetime.now() - _last_refresh).seconds > max_minutes * 60
