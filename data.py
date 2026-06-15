"""
Live market data — 5-minute OHLCV bars from Yahoo Finance (NSE).

Timeframe: 5m candles  (all indicators: EMA5, SMA50, RSI computed on 5m bars)
Refresh:   every 60 s during market hours
History:   10 trading days of 5m bars (~700 bars per symbol — enough for SMA50)

Why 5m?  User's Pine Script runs on a 5-min chart.  We check every 1 min whether
a new completed 5-min bar has triggered a buy/sell condition.
"""
import os
import math
import threading
from datetime import datetime, timezone, timedelta

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

YF_SUFFIX  = ".NS"
_IST       = timezone(timedelta(hours=5, minutes=30))

_cache:        dict     = {}
_cache_lock             = threading.Lock()
_last_refresh: datetime = None


# ─── Indicators ───────────────────────────────────────────────────────────────
def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range — measures actual stock volatility."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength (0-100). >20 = trending, <20 = choppy."""
    up_move   = high.diff()
    down_move = -low.diff()
    plus_dm  = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    tr  = _atr(high, low, close, period)
    plus_di  = 100 * (plus_dm.ewm(com=period - 1, adjust=False).mean() / tr.replace(0, float("nan")))
    minus_di = 100 * (minus_dm.ewm(com=period - 1, adjust=False).mean() / tr.replace(0, float("nan")))
    dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))
    return dx.ewm(com=period - 1, adjust=False).mean()


def _htf_trend(close: pd.Series) -> str:
    """Resample 5m closes to 15m (groups of 3), EMA5 vs SMA50 trend."""
    try:
        n = len(close) // 3
        if n < 55:
            return "neutral"
        c15 = pd.Series(close.iloc[: n * 3].values.reshape(n, 3)[:, -1])
        ema5_15  = c15.ewm(span=5,  adjust=False).mean()
        sma50_15 = c15.rolling(50).mean()
        if math.isnan(sma50_15.iloc[-1]):
            return "neutral"
        if ema5_15.iloc[-1] > sma50_15.iloc[-1]:
            return "bullish"
        elif ema5_15.iloc[-1] < sma50_15.iloc[-1]:
            return "bearish"
        return "neutral"
    except Exception:
        return "neutral"


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).round(2)


def _safe(series: pd.Series, idx: int = -1) -> float:
    try:
        v = series.iloc[idx]
        return float(v) if not math.isnan(float(v)) else 0.0
    except Exception:
        return 0.0


# ─── Compute indicators from 5-min bars ──────────────────────────────────────
def _compute_5m(hist: pd.DataFrame, sym_info: dict) -> dict | None:
    """
    Compute all technical indicators on 5-minute OHLCV bars.
    Requires at least 55 bars (≈ 275 min ≈ less than 1 trading day).
    """
    hist = hist.dropna(subset=["Close"])
    if len(hist) < 55:
        return None

    close  = hist["Close"]
    high   = hist["High"]
    low    = hist["Low"]
    volume = hist["Volume"]

    # ── Indicators on 5m bars (matches Pine Script chart) ────────────────────
    ema5  = close.ewm(span=5,  adjust=False).mean()
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    rsi   = _rsi(close, 14)
    atr   = _atr(high, low, close, 14)

    # Current and previous completed 5-min bar
    cur_close  = _safe(close,  -1)
    cur_open   = _safe(hist["Open"], -1)
    cur_high   = _safe(high,   -1)
    cur_low    = _safe(low,    -1)
    cur_vol    = int(volume.iloc[-1]) if not math.isnan(volume.iloc[-1]) else 0
    avg_vol    = int(volume.tail(20).mean())

    ema5_cur   = _safe(ema5,  -1)
    ema5_prv   = _safe(ema5,  -2)
    sma50_cur  = _safe(sma50, -1)
    sma50_prv  = _safe(sma50, -2)
    rsi_cur    = _safe(rsi,   -1) or 50.0
    rsi_prv    = _safe(rsi,   -2) or 50.0

    # Today's day-open (first bar of the current trading date)
    ist_now    = datetime.now(_IST)
    today_date = ist_now.date()
    try:
        today_bars = hist[hist.index.tz_convert(_IST).date == today_date]
        day_open   = float(today_bars["Open"].iloc[0]) if not today_bars.empty else cur_open
    except Exception:
        day_open   = cur_open

    change_pct = round((cur_close - day_open) / day_open * 100, 2) if day_open else 0.0

    # Resistance = highest high of all fetched bars (~10 trading days)
    resistance = round(float(high.max()), 2)

    # Swing trend (Pine Script "mycolor" logic on 5m bars)
    if cur_low > sma50_cur:
        swing_trend = "bullish"
    elif cur_high < sma50_cur:
        swing_trend = "bearish"
    else:
        swing_trend = "mixed"

    # Delivery % — not available intraday; estimated from volume ratio
    delivery = min(85.0, max(20.0, 50.0 + change_pct * 4))

    return {
        "symbol":      sym_info["symbol"],
        "name":        sym_info["name"],
        "sector":      sym_info["sector"],
        # OHLCV of latest 5-min bar
        "close":       round(cur_close, 2),
        "open":        round(cur_open,  2),
        "high":        round(cur_high,  2),
        "low":         round(cur_low,   2),
        "changePct":   change_pct,
        "volume":      cur_vol,
        "avgVolume":   avg_vol,
        # Indicators (computed on 5m bars — same as Pine Script chart)
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
        "atr":         round(_safe(atr, -1), 2),
        "adx":         round(_safe(_adx(high, low, close, 14), -1), 2),
        "htf_trend":   _htf_trend(close),
        "timeframe":   "5m",
    }


# ─── Upstox primary refresh ──────────────────────────────────────────────────
def _try_upstox_refresh() -> bool:
    """Try to refresh using Upstox real-time data. Returns True on success."""
    try:
        import upstox_data as _upstox
        if not _upstox.is_ready():
            return False
        results = _upstox.refresh_universe(UNIVERSE)
        if not results:
            return False
        with _cache_lock:
            _cache.update(results)
        global _last_refresh
        _last_refresh = datetime.now()
        print(f"[data] ✅ Upstox: {len(results)} stocks refreshed (real-time)")
        return True
    except Exception as e:
        print(f"[data] Upstox refresh error: {e}")
        return False


# ─── Yahoo Finance fallback refresh ──────────────────────────────────────────
def refresh_5m():
    """
    Download 10 days of 5-minute bars for all universe symbols.
    Compute EMA5, SMA50, RSI (and all other indicators) on 5m bars.
    Called both at market open and every 60 seconds intraday.
    """
    global _last_refresh
    yf_symbols = [s.get("yf", s["symbol"] + YF_SUFFIX) for s in UNIVERSE]

    try:
        raw = yf.download(
            yf_symbols,
            period="10d",        # 10 trading days → ~750 5m bars per symbol
            interval="5m",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        print(f"[data] 5m download error: {e}")
        return

    updated = {}
    for sym_info in UNIVERSE:
        yf_sym = sym_info.get("yf", sym_info["symbol"] + YF_SUFFIX)
        try:
            hist = raw[yf_sym] if len(yf_symbols) > 1 else raw
            if hist is None or hist.empty:
                continue
            result = _compute_5m(hist, sym_info)
            if result:
                updated[sym_info["symbol"]] = result
        except Exception as e:
            print(f"[data] {sym_info['symbol']}: {e}")

    with _cache_lock:
        _cache.update(updated)
        _last_refresh = datetime.now()

    print(f"[data] 5m refresh ✓ {len(updated)}/{len(UNIVERSE)} symbols "
          f"@ {_last_refresh.strftime('%H:%M:%S')} IST")


def smart_refresh():
    """
    Live data only — Upstox real-time 5m data.
    No mock/fallback data is generated; if Upstox is unavailable, the cache
    simply does not get refreshed (stale/empty data is reported as-is).
    """
    if _try_upstox_refresh():
        return   # Upstox succeeded — real-time data
    print("[data] Upstox unavailable — no live data refresh this cycle")


# Aliases
def refresh_all():
    smart_refresh()

def refresh_intraday():
    smart_refresh()


# ─── Accessors ────────────────────────────────────────────────────────────────
def get_nifty_trend() -> str:
    """
    Returns 'bullish' if Nifty 50 is above its 20 EMA on 5m chart, else 'bearish'.
    Used as a market-wide filter — only take BUY signals in bullish market.
    Uses yfinance for ^NSEI (single call, separate from Upstox feed).
    """
    try:
        raw = yf.download("^NSEI", period="5d", interval="5m",
                          auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return "bullish"
        close = raw["Close"].dropna()
        if len(close) < 20:
            return "bullish"
        ema20 = close.ewm(span=20, adjust=False).mean()
        trend = "bullish" if float(close.iloc[-1]) > float(ema20.iloc[-1]) else "bearish"
        print(f"[data] Nifty: {float(close.iloc[-1]):.0f} vs EMA20 {float(ema20.iloc[-1]):.0f} → {trend}")
        return trend
    except Exception as e:
        print(f"[data] Nifty trend error: {e}")
        return "bullish"   # safe default — allow signals if Nifty data unavailable


def get_india_vix() -> float:
    """
    Current India VIX level. Used as a volatility-regime filter:
      VIX < 14            → calm, normal operation
      14 <= VIX <= 20     → elevated, widen stops
      VIX > 20            → high fear, pause new signals
    Returns 0.0 if unavailable (treated as calm/normal downstream).
    Sourced from Upstox (consistent with live candle feed).
    """
    try:
        import upstox_data as _upstox
        return _upstox.get_india_vix()
    except Exception as e:
        print(f"[data] VIX error: {e}")
        return 0.0


def get_all() -> list[dict]:
    with _cache_lock:
        return list(_cache.values())


def get_eod_prices() -> dict:
    with _cache_lock:
        return {sym: s["close"] for sym, s in _cache.items()}


def is_stale(max_minutes: int = 3) -> bool:
    if _last_refresh is None:
        return True
    return (datetime.now() - _last_refresh).seconds > max_minutes * 60
