"""
Upstox API v2 — real-time NSE 5-minute candle data.

Credentials read from .env:
  UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_ACCESS_TOKEN
"""
import os
import math
import time
import gzip
import json
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

_IST       = timezone(timedelta(hours=5, minutes=30))
_BASE      = "https://api.upstox.com/v2"
_lock      = threading.Lock()
_token_map: dict = {}     # NSE symbol -> Upstox instrument key
_ready     = False

# Upstox v2 candle endpoints only accept these intervals now:
#   historical-candle: 1minute, 30minute, day, week, month
#   intraday:          1minute, 30minute
# For anything finer than 30minute we fetch 1minute candles and resample
# locally with pandas. THIRTY_MINUTE can be fetched directly.
_INTERVAL_MAP = {
    "FIVE_MINUTE": "1minute",
    "ONE_MINUTE":  "1minute",
    "FIFTEEN_MINUTE": "1minute",
    "THIRTY_MINUTE": "30minute",
    "ONE_HOUR": "1minute",
    "ONE_DAY": "day",
}

# pandas resample rule for each interval that needs resampling from 1minute
_RESAMPLE_RULE = {
    "FIVE_MINUTE": "5min",
    "FIFTEEN_MINUTE": "15min",
    "ONE_HOUR": "60min",
}


def _headers():
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# ─── Auth ─────────────────────────────────────────────────────────────────────
def login() -> bool:
    """Upstox uses a long-lived access token — just validate it works."""
    global _ready
    token = os.environ.get("UPSTOX_ACCESS_TOKEN", "")
    if not token:
        print("[upstox] Missing UPSTOX_ACCESS_TOKEN in .env")
        return False

    try:
        resp = requests.get(f"{_BASE}/user/profile", headers=_headers(), timeout=15)
        if resp.status_code == 200 and resp.json().get("status") == "success":
            _ready = True
            data = resp.json().get("data", {})
            print(f"[upstox] Logged in — {data.get('user_name', data.get('user_id', ''))}")
            return True
        print(f"[upstox] Login failed: {resp.status_code} {resp.text[:200]}")
        _ready = False
        return False
    except Exception as e:
        print(f"[upstox] Login error: {e}")
        _ready = False
        return False


# ─── Instrument token map ─────────────────────────────────────────────────────
_INDEX_KEYS = {
    "NIFTY 50":   "NSE_INDEX|Nifty 50",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    "INDIA VIX":  "NSE_INDEX|India VIX",
}


def build_token_map(universe: list) -> bool:
    """
    Download Upstox NSE instrument master (gzip JSON) and map our stock
    symbols (trading_symbol) to instrument_key. Also adds index keys.
    """
    global _token_map
    needed = {s["symbol"] for s in universe}
    tmap = {}

    try:
        url = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
        resp = requests.get(url, timeout=60)
        raw = gzip.decompress(resp.content)
        instruments = json.loads(raw)
        for item in instruments:
            sym = item.get("trading_symbol", "")
            seg = item.get("segment", "")
            if sym in needed and seg == "NSE_EQ":
                tmap[sym] = item.get("instrument_key")
            # capture index keys if present in this file
            name = item.get("name", "")
            if seg in ("NSE_INDEX",) or item.get("instrument_type") == "INDEX":
                if name.upper() in _INDEX_KEYS and _INDEX_KEYS[name.upper()] not in tmap.values():
                    tmap[name.upper()] = item.get("instrument_key", _INDEX_KEYS.get(name.upper()))
    except Exception as e:
        print(f"[upstox] NSE instrument master download failed: {e}")

    # Fallback for indices — use known instrument keys if not found above
    for idx_name, idx_key in _INDEX_KEYS.items():
        if idx_name not in tmap:
            tmap[idx_name] = idx_key

    _token_map = tmap
    missing = needed - set(_token_map.keys())
    print(f"[upstox] Token map: {len(_token_map & needed) if False else len([k for k in _token_map if k in needed])}/{len(needed)} symbols "
          f"{'| missing: ' + str(missing) if missing else '— all mapped'}")
    return True


# ─── Candle fetch ─────────────────────────────────────────────────────────────
def _fetch_candles(symbol: str, interval: str = "FIVE_MINUTE", days: int = 7):
    """Fetch OHLCV candles from Upstox for one symbol.
    Returns [[timestamp_IST_isoformat, O, H, L, C, V], ...] sorted oldest->newest.

    FIX (2026-06-25): days default raised 5→7 so that calendar-day lookback
    always captures at least 4 full trading days even across a weekend or holiday.
    FIX: deduplication of candles at the historical/intraday boundary.
    FIX: resample anchored explicitly to 09:15 IST via 'offset' so bars land on
         09:15, 09:20... regardless of the pandas default midnight anchor.
    """
    instrument_key = _token_map.get(symbol)
    if not instrument_key:
        return None

    up_interval = _INTERVAL_MAP.get(interval, "5minute")
    candles = []

    now = datetime.now(_IST)
    from_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    def _get(url):
        for attempt in range(2):
            try:
                resp = requests.get(url, headers=_headers(), timeout=20)
                if resp.status_code == 200:
                    j = resp.json()
                    if j.get("status") == "success":
                        return j.get("data", {}).get("candles", [])
                    return []
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                print(f"[upstox] Candle error {symbol}: {resp.status_code} {resp.text[:150]}")
                return []
            except Exception as e:
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                print(f"[upstox] Candle exception {symbol}: {e}")
                return []
        return []

    # Historical candles (up to yesterday)
    hist_to = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    hist_url = f"{_BASE}/historical-candle/{instrument_key}/{up_interval}/{hist_to}/{from_date}"
    hist_candles = _get(hist_url)
    candles.extend(hist_candles)

    # Intraday candles (today)
    intraday_url = f"{_BASE}/historical-candle/intraday/{instrument_key}/{up_interval}"
    intraday_candles = _get(intraday_url)
    candles.extend(intraday_candles)

    if not candles:
        return None

    # Upstox candle format: [timestamp(ISO), open, high, low, close, volume, oi]
    # Sort oldest→newest, then deduplicate on timestamp (fixes hist/intraday boundary overlap)
    candles.sort(key=lambda c: c[0])
    seen_ts = set()
    deduped = []
    for c in candles:
        if c[0] not in seen_ts:
            seen_ts.add(c[0])
            deduped.append(c)
    out = [[c[0], c[1], c[2], c[3], c[4], c[5]] for c in deduped]

    rule = _RESAMPLE_RULE.get(interval)
    if rule:
        df = pd.DataFrame(out, columns=["ts", "open", "high", "low", "close", "volume"])
        # Parse timestamps — Upstox returns IST ISO strings (+05:30); convert correctly.
        df["ts"] = pd.to_datetime(df["ts"], utc=False)
        # If timestamps are already tz-aware (have +05:30), tz_convert to IST.
        # If tz-naive, localize as IST directly.
        if df["ts"].dt.tz is None:
            df["ts"] = df["ts"].dt.tz_localize(_IST)
        else:
            df["ts"] = df["ts"].dt.tz_convert(_IST)
        df = df.set_index("ts")
        # Anchor resample to 09:15 IST (market open) so bars land on 09:15, 09:20...
        # The offset="15min" shifts the default midnight anchor by 15 minutes,
        # producing boundaries at 09:15, 09:20... for a "5min" rule.
        # For 15min rule, offset="15min" → 09:15, 09:30... which is correct.
        # For 60min rule, offset="15min" → 09:15, 10:15... which is correct.
        agg = df.resample(rule, label="left", closed="left", offset="15min").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open"])
        out = [
            [ts.isoformat(), row.open, row.high, row.low, row.close, row.volume]
            for ts, row in agg.iterrows()
        ]

    return out


# ─── Technical indicators ──────────────────────────────────────────────────────
def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).round(2)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
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
    """
    Resample 5m closes to 15m (groups of 3) and compute EMA5 vs SMA50 trend.
    A 5m crossover signal is only trusted if the 15m trend agrees.
    """
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


def _safe(series: pd.Series, idx: int = -1) -> float:
    try:
        v = float(series.iloc[idx])
        return v if not math.isnan(v) else 0.0
    except Exception:
        return 0.0


def _compute(candles: list, sym_info: dict) -> dict | None:
    """Convert raw Upstox candle list -> stock dict with all indicators."""
    if not candles or len(candles) < 55:
        return None

    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"])

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    volume = df["volume"]

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

    # Day open = first candle of today (IST date)
    # FIX: parse ts column properly before date-filtering; str.startswith works on
    # IST isoformat strings ("2026-06-25T09:15:00+05:30") but is fragile.
    # Use explicit date extraction instead.
    today_str  = datetime.now(_IST).strftime("%Y-%m-%d")
    try:
        ts_parsed = pd.to_datetime(df["ts"], utc=False)
        if ts_parsed.dt.tz is None:
            ts_parsed = ts_parsed.dt.tz_localize(_IST)
        else:
            ts_parsed = ts_parsed.dt.tz_convert(_IST)
        today_mask = ts_parsed.dt.strftime("%Y-%m-%d") == today_str
        today_rows = df[today_mask]
    except Exception:
        today_rows = df[df["ts"].astype(str).str.startswith(today_str)]
    day_open   = float(today_rows["open"].iloc[0]) if not today_rows.empty else cur_open
    change_pct = round((cur_close - day_open) / day_open * 100, 2) if day_open else 0.0

    resistance = round(float(high.max()), 2)

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
        "atr":         round(_safe(_atr(high, low, close, 14), -1), 2),
        "adx":         round(_safe(_adx(high, low, close, 14), -1), 2),
        "htf_trend":   _htf_trend(close),
        "timeframe":   "5m",
        "source":      "upstox",
    }


# ─── Bulk refresh ─────────────────────────────────────────────────────────────
def refresh_universe(universe: list) -> dict:
    """
    Fetch 5m candles for all symbols, compute indicators.
    Upstox allows ~20-25 req/sec for historical/intraday candle APIs,
    but we use ~0.4s between calls to be safe. Simple retry-once on failure.
    """
    if not _ready:
        print("[upstox] Not logged in")
        return {}

    results = {}
    for i, sym_info in enumerate(universe):
        sym = sym_info["symbol"]
        candles = _fetch_candles(sym, interval="FIVE_MINUTE", days=7)
        if not candles:
            time.sleep(0.5)
            candles = _fetch_candles(sym, interval="FIVE_MINUTE", days=7)  # retry once
        if candles:
            stock = _compute(candles, sym_info)
            if stock:
                results[sym] = stock
        if i < len(universe) - 1:
            time.sleep(0.4)

    print(f"[upstox] Refreshed {len(results)}/{len(universe)} symbols "
          f"@ {datetime.now(_IST).strftime('%H:%M:%S')} IST")
    return results


def is_ready() -> bool:
    return _ready and bool(_token_map)


# ─── India VIX ─────────────────────────────────────────────────────────────────
def get_india_vix() -> float:
    """Fetch India VIX LTP via Upstox quote API. Returns 0.0 on failure."""
    try:
        instrument_key = _token_map.get("INDIA VIX", "NSE_INDEX|India VIX")
        url = f"{_BASE}/market-quote/quotes"
        resp = requests.get(url, headers=_headers(), params={"instrument_key": instrument_key}, timeout=15)
        if resp.status_code != 200:
            print(f"[upstox] VIX error: {resp.status_code} {resp.text[:150]}")
            return 0.0
        j = resp.json()
        if j.get("status") != "success":
            return 0.0
        data = j.get("data", {})
        for v in data.values():
            ltp = v.get("last_price")
            if ltp is not None:
                print(f"[upstox] India VIX: {float(ltp):.2f}")
                return round(float(ltp), 2)
        return 0.0
    except Exception as e:
        print(f"[upstox] VIX error: {e}")
        return 0.0
