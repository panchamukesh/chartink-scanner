"""
Auto-scanner — runs every 5 minutes during NSE market hours (10:00–15:30 IST, Mon–Fri).
Evaluates each stock against all active scan rules.
Sends Telegram alerts for new signals and an EOD report at 15:35.
"""
import threading
import time as _time
from datetime import datetime, timezone, timedelta

import data as _data
import db as _db
import notify as _notify

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# ─── Scan rule definitions (mirrors INDICATOR_LIBRARY in app.js) ──────────────
SCAN_RULES = [
    {"key": "supertrend_buy",    "name": "SuperTrend — Buy Signal",           "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema20"] and s["changePct"]>0 and s["rsi"]>50 and s["volume"]>s["avgVolume"]},
    {"key": "macd_cross",        "name": "MACD — Bullish Crossover",          "signal": "BUY",
     "cond": lambda s: s["ema20"]>s["ema50"] and s["close"]>s["ema20"] and s["changePct"]>0 and s["rsi"]>45},
    {"key": "rsi_recovery",      "name": "RSI — Oversold Recovery",           "signal": "BUY",
     "cond": lambda s: 40<s["rsi"]<60 and s["close"]>s["sma20"] and s["changePct"]>0},
    {"key": "bollinger_breakout","name": "Bollinger Band — Upper Breakout",   "signal": "BUY",
     "cond": lambda s: s["close"]>s["resistance"] and s["volume"]>s["avgVolume"] and s["changePct"]>1 and s["rsi"]<75},
    {"key": "golden_cross",      "name": "Golden Cross — EMA 20/50",          "signal": "BUY",
     "cond": lambda s: s["ema20"]>s["ema50"] and s["close"]>s["ema20"] and s["rsi"]>50 and s["changePct"]>0},
    {"key": "vwap_breakout",     "name": "VWAP — Intraday Breakout",          "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema20"] and s["volume"]>s["avgVolume"] and s["changePct"]>0.5 and s["rsi"]>50},
    {"key": "ssl_hybrid",        "name": "SSL Hybrid — Buy Zone",             "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema50"] and s["close"]>s["ema20"] and s["rsi"]>50 and s["ema20"]>s["ema50"]},
    {"key": "volume_surge",      "name": "Volume Surge — Momentum Play",      "signal": "BUY",
     "cond": lambda s: s["volume"]>s["avgVolume"] and s["changePct"]>2 and s["close"]>s["resistance"]},
    {"key": "delivery_accum",    "name": "Delivery — Smart Money Accumulation","signal": "BUY",
     "cond": lambda s: s["delivery"]>60 and s["changePct"]>0 and s["volume"]>s["avgVolume"] and s["rsi"]>45},
    {"key": "high_breakout",     "name": "52-Week High — Fresh Breakout",     "signal": "BUY",
     "cond": lambda s: s["close"]>s["resistance"] and s["changePct"]>1 and s["volume"]>s["avgVolume"] and s["rsi"]>55},
    {"key": "ema_pullback",      "name": "EMA 20 — Healthy Pullback Buy",     "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema20"] and 45<s["rsi"]<65 and s["changePct"]>0 and s["ema20"]>s["ema50"]},
    {"key": "stoch_rsi",         "name": "Stochastic RSI — Buy Cross",        "signal": "BUY",
     "cond": lambda s: 50<s["rsi"]<70 and s["close"]>s["ema20"] and s["volume"]>s["avgVolume"] and s["changePct"]>0},
    {"key": "adx_trend",         "name": "ADX — Strong Trend Momentum",       "signal": "BUY",
     "cond": lambda s: s["rsi"]>55 and s["close"]>s["ema20"] and s["close"]>s["ema50"] and s["changePct"]>0.5 and s["volume"]>s["avgVolume"]},
    {"key": "price_action_bull", "name": "Price Action — Strong Bull Candle", "signal": "BUY",
     "cond": lambda s: s["changePct"]>1 and s["delivery"]>50 and s["close"]>s["ema20"] and s["volume"]>s["avgVolume"]},
    {"key": "obv_rising",        "name": "OBV — Rising Volume Trend",         "signal": "BUY",
     "cond": lambda s: s["volume"]>s["avgVolume"] and s["changePct"]>0 and s["close"]>s["ema20"] and s["delivery"]>55 and s["rsi"]>50},
    {"key": "ttm_squeeze",       "name": "TTM Squeeze — Momentum Fire",       "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema20"] and s["rsi"]>52 and s["volume"]>s["avgVolume"] and s["changePct"]>1 and s["ema20"]>s["ema50"]},
    {"key": "ichimoku_buy",      "name": "Ichimoku Cloud — Kumo Breakout",    "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema50"] and s["ema20"]>s["ema50"] and s["rsi"]>52 and s["changePct"]>0},
    {"key": "pivot_breakout",    "name": "Pivot Point — Resistance Break",    "signal": "BUY",
     "cond": lambda s: s["close"]>s["resistance"] and s["changePct"]>1.5 and s["volume"]>s["avgVolume"] and s["rsi"]>55},
    {"key": "cci_bull",          "name": "CCI — Bullish Momentum",            "signal": "BUY",
     "cond": lambda s: s["rsi"]>50 and s["close"]>s["sma20"] and s["volume"]>s["avgVolume"] and s["changePct"]>0},
    {"key": "demand_zone",       "name": "Demand Zone — Supply Reversal",     "signal": "BUY",
     "cond": lambda s: s["close"]>s["ema50"] and 48<s["rsi"]<62 and s["delivery"]>50 and s["changePct"]>0},
    # SELL / Distribution scans
    {"key": "overbought_sell",   "name": "RSI Overbought — Distribution",     "signal": "SELL",
     "cond": lambda s: s["rsi"]>72 and s["changePct"]<0 and s["volume"]>s["avgVolume"]},
    {"key": "breakdown_sell",    "name": "Breakdown — Below Support",         "signal": "SELL",
     "cond": lambda s: s["close"]<s["ema50"] and s["close"]<s["ema20"] and s["changePct"]<-1.5 and s["volume"]>s["avgVolume"]},

    # ── Pine Script: SWING CALLS (nicks1008) ─────────────────────────────────
    # buycall = crossunder(sma2, ema1) and high > sma2
    #   i.e. EMA5 just crossed ABOVE SMA50 AND high is above SMA50
    {"key": "pine_swing_buy",
     "name": "🔵 Swing BUY — EMA5 × SMA50 Bullish Cross",
     "signal": "BUY",
     "cond": lambda s: (
         s.get("prev_sma50", 0) >= s.get("prev_ema5", 0)   # previous: SMA50 was above EMA5
         and s.get("sma50", 0) < s.get("ema5", 0)           # now: EMA5 crossed above SMA50
         and s["high"] > s.get("sma50", 0)                  # high is above SMA50
     )},

    # sellcall = crossover(sma2, ema1) and open > close
    #   i.e. SMA50 just crossed ABOVE EMA5 AND bearish candle (close < open)
    {"key": "pine_swing_sell",
     "name": "🔴 Swing SELL — SMA50 × EMA5 Bearish Cross",
     "signal": "SELL",
     "cond": lambda s: (
         s.get("prev_sma50", 0) <= s.get("prev_ema5", 0)   # previous: EMA5 was above SMA50
         and s.get("sma50", 0) > s.get("ema5", 0)           # now: SMA50 crossed above EMA5
         and s["changePct"] < 0                              # close < open (bearish candle)
     )},

    # sellexit = crossover(rs, ll=20) → RSI crosses above 20 = oversold reversal BUY
    {"key": "pine_rsi_reversal_buy",
     "name": "⬆️ Swing RSI Reversal — Oversold Exit BUY",
     "signal": "BUY",
     "cond": lambda s: s.get("prev_rsi", 50) <= 20 and s["rsi"] > 20},

    # buyexit = crossunder(rs, hl=80) → RSI crosses under 80 = overbought reversal SELL
    {"key": "pine_rsi_reversal_sell",
     "name": "⬇️ Swing RSI Reversal — Overbought Exit SELL",
     "signal": "SELL",
     "cond": lambda s: s.get("prev_rsi", 50) >= 80 and s["rsi"] < 80},
]

# Active rules — all enabled by default; Pine Script rules appended here later
ACTIVE_RULES = list(SCAN_RULES)

# Target/SL percentages — default (indicator library scans)
BUY_TARGET_PCT  =  3.0
BUY_SL_PCT      = -1.5
SELL_TARGET_PCT = -3.0
SELL_SL_PCT     =  1.5

# Swing trade targets (Pine Script: SWING CALLS) — wider as swing holds overnight
SWING_BUY_TARGET_PCT  =  5.0
SWING_BUY_SL_PCT      = -2.0
SWING_SELL_TARGET_PCT = -5.0
SWING_SELL_SL_PCT     =  2.0

PINE_KEYS = {"pine_swing_buy", "pine_swing_sell", "pine_rsi_reversal_buy", "pine_rsi_reversal_sell"}


def _ist_now() -> datetime:
    return datetime.now(_IST)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:          # Saturday / Sunday
        return False
    t = now.time()
    from datetime import time
    return time(10, 0) <= t <= time(15, 30)


def _calc_targets(price, signal_type, is_swing=False):
    if is_swing:
        tgt_pct = SWING_BUY_TARGET_PCT  if signal_type == "BUY" else SWING_SELL_TARGET_PCT
        sl_pct  = SWING_BUY_SL_PCT      if signal_type == "BUY" else SWING_SELL_SL_PCT
    else:
        tgt_pct = BUY_TARGET_PCT  if signal_type == "BUY" else SELL_TARGET_PCT
        sl_pct  = BUY_SL_PCT      if signal_type == "BUY" else SELL_SL_PCT
    return round(price * (1 + tgt_pct / 100), 2), round(price * (1 + sl_pct / 100), 2)


def _run_scan_cycle():
    """Evaluate all active rules against cached stock data and fire new signals."""
    stocks = _data.get_all()
    if not stocks:
        print("[scanner] No cached data — skipping cycle")
        return

    fired = 0
    for rule in ACTIVE_RULES:
        for stock in stocks:
            try:
                if not rule["cond"](stock):
                    continue
            except Exception:
                continue

            if _db.already_signaled(stock["symbol"], rule["name"]):
                continue

            price = stock["close"]
            is_swing = rule["key"] in PINE_KEYS
            target, sl = _calc_targets(price, rule["signal"], is_swing=is_swing)
            sig_id = _db.insert_signal(
                symbol      = stock["symbol"],
                name        = stock["name"],
                sector      = stock["sector"],
                signal_type = rule["signal"],
                scan_name   = rule["name"],
                price       = price,
                target      = target,
                sl          = sl,
            )
            signal = dict(
                id          = sig_id,
                symbol      = stock["symbol"],
                name        = stock["name"],
                sector      = stock["sector"],
                signal_type = rule["signal"],
                scan_name   = rule["name"],
                scan_key    = rule["key"],
                price       = price,
                target      = target,
                sl          = sl,
                time        = _ist_now().strftime("%H:%M"),
                swing_trend = stock.get("swing_trend", ""),
            )
            _notify.send_signal(signal)
            fired += 1
            print(f"[scanner] Signal: {rule['signal']} {stock['symbol']} via '{rule['name']}'")

    if fired:
        print(f"[scanner] Cycle complete — {fired} new signal(s) fired")


def _eod_report():
    """Fetch EOD prices, update DB, send consolidated report."""
    print("[scanner] Running EOD report …")
    try:
        _data.refresh_all()   # get final prices
    except Exception as e:
        print(f"[scanner] EOD refresh error: {e}")

    eod = _data.get_eod_prices()
    for symbol, price in eod.items():
        _db.update_eod(symbol, price)

    signals = _db.get_signals_today()
    _notify.send_eod_report(signals)
    print(f"[scanner] EOD report sent — {len(signals)} signal(s)")


def _loop():
    """Background thread: data refresh at 10 AM, scan every 5 min, EOD at 15:35."""
    opened_today = False
    eod_sent_today = False
    last_scan = None

    print("[scanner] Background loop started")

    while True:
        now = _ist_now()

        # Reset flags at midnight
        if now.hour == 0 and now.minute == 0:
            opened_today = False
            eod_sent_today = False

        # Market open — refresh data once
        if _is_market_open() and not opened_today:
            print("[scanner] Market opened — loading fresh data …")
            try:
                _data.refresh_all()
            except Exception as e:
                print(f"[scanner] Data refresh error: {e}")
            opened_today = True

        # Intraday scan every 5 minutes
        if _is_market_open():
            if last_scan is None or (now - last_scan).seconds >= 300:
                try:
                    if _data.is_stale(max_minutes=10):
                        _data.refresh_all()
                    _run_scan_cycle()
                except Exception as e:
                    print(f"[scanner] Scan error: {e}")
                last_scan = now

        # EOD report at 15:35 IST
        from datetime import time
        if (now.weekday() < 5
                and now.time() >= time(15, 35)
                and not eod_sent_today):
            try:
                _eod_report()
            except Exception as e:
                print(f"[scanner] EOD error: {e}")
            eod_sent_today = True

        _time.sleep(30)   # check every 30 seconds


def start():
    """Start the background scanner thread (call once at app startup)."""
    _db.init_db()
    t = threading.Thread(target=_loop, daemon=True, name="scanner")
    t.start()
    print("[scanner] Started")
