"""
MarketScan Pro — Signal Engine (v2 — Quality over Quantity)

Philosophy:
  - ONLY fire Pine Script crossover signals (4 rules total)
  - Every signal passes 5 quality gates before Telegram
  - ATR-based SL and Target (adapts to each stock's actual volatility)
  - Maximum 5 signals per day — if you're getting more, something is wrong
  - Zero noise tolerated

Pine Script rules (SWING CALLS by nicks1008):
  BUY  — EMA5 crosses above SMA50 AND high > SMA50
  SELL — SMA50 crosses above EMA5 AND bearish candle
  BUY  — RSI crosses above 20 (oversold reversal)
  SELL — RSI crosses below 80 (overbought reversal)

Quality gates (ALL must pass):
  1. Nifty trend   — BUY only when Nifty above EMA20, SELL only when below
  2. Volume        — Signal candle volume > 1.5× 20-bar average
  3. RSI guard     — Swing BUY: RSI < 70  |  Swing SELL: RSI > 30
  4. Session time  — Only 10:15 AM – 3:00 PM IST (skip open/close noise)
  5. Daily cap     — Max 5 signals per day total
"""
import threading
import time as _time
from datetime import datetime, timezone, timedelta, time as _time_t

import data as _data
import db as _db
import notify as _notify

_IST = timezone(timedelta(hours=5, minutes=30))

# ── In-memory state: tracks which stocks currently match each rule ─────────────
_active: dict = {}          # rule_key → set[symbol]
_nifty_trend: str = "bullish"   # updated each refresh cycle


# ── Pine Script rules ONLY (no generic indicator library) ─────────────────────
ACTIVE_RULES = [
    {
        "key":    "pine_swing_buy",
        "name":   "Swing BUY — EMA5 × SMA50 Cross",
        "signal": "BUY",
        # buycall = crossunder(sma2, ema1) and high > sma2
        "cond": lambda s: (
            s.get("prev_sma50", 0) >= s.get("prev_ema5", 0)
            and s.get("sma50", 0) < s.get("ema5", 0)
            and s["high"] > s.get("sma50", 0)
        ),
    },
    {
        "key":    "pine_swing_sell",
        "name":   "Swing SELL — SMA50 × EMA5 Cross",
        "signal": "SELL",
        # sellcall = crossover(sma2, ema1) and open > close
        "cond": lambda s: (
            s.get("prev_sma50", 0) <= s.get("prev_ema5", 0)
            and s.get("sma50", 0) > s.get("ema5", 0)
            and s["changePct"] < 0
        ),
    },
    {
        "key":    "pine_rsi_bull",
        "name":   "RSI Reversal BUY — Oversold Exit",
        "signal": "BUY",
        # sellexit = crossover(rs, ll=20)
        "cond": lambda s: s.get("prev_rsi", 50) <= 20 and s["rsi"] > 20,
    },
    {
        "key":    "pine_rsi_bear",
        "name":   "RSI Reversal SELL — Overbought Exit",
        "signal": "SELL",
        # buyexit = crossunder(rs, hl=80)
        "cond": lambda s: s.get("prev_rsi", 50) >= 80 and s["rsi"] < 80,
    },
]

# Keep for webhook compatibility
PINE_KEYS = {r["key"] for r in ACTIVE_RULES}

MAX_SIGNALS_PER_DAY = 5


# ── Helpers ───────────────────────────────────────────────────────────────────
def _ist_now() -> datetime:
    return datetime.now(_IST)


def _is_market_open() -> bool:
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    return _time_t(10, 0) <= now.time() <= _time_t(15, 30)


def _in_signal_window() -> bool:
    """Only fire signals between 10:15 AM and 3:00 PM IST."""
    t = _ist_now().time()
    return _time_t(10, 15) <= t <= _time_t(15, 0)


def _calc_targets(price: float, signal_type: str, atr: float = 0.0):
    """
    ATR-based SL and Target.
      SL     = 1.5 × ATR  (tight enough to stop early, wide enough for noise)
      Target = 3.0 × ATR  (2:1 R:R minimum — only worth taking quality setups)
    Falls back to fixed 2% / 4% if ATR unavailable.
    """
    if atr and atr > 0:
        sl_dist  = round(1.5 * atr, 2)
        tgt_dist = round(3.0 * atr, 2)
    else:
        sl_dist  = round(price * 0.02, 2)    # 2% fallback
        tgt_dist = round(price * 0.04, 2)    # 4% fallback

    if signal_type == "BUY":
        return round(price + tgt_dist, 2), round(price - sl_dist, 2)
    else:
        return round(price - tgt_dist, 2), round(price + sl_dist, 2)


def _passes_quality(stock: dict, rule: dict) -> tuple[bool, str]:
    """
    5 quality gates — ALL must pass.
    Returns (passed: bool, reason: str).
    """
    signal = rule["signal"]
    rkey   = rule["key"]

    # Gate 1 — Nifty trend
    if signal == "BUY" and _nifty_trend == "bearish":
        return False, "Nifty below EMA20 — no BUY signals in falling market"
    if signal == "SELL" and _nifty_trend == "bullish":
        return False, "Nifty above EMA20 — no SELL signals in rising market"

    # Gate 2 — Volume conviction (RSI reversals exempt — they work on thin volume)
    if rkey in {"pine_swing_buy", "pine_swing_sell"}:
        if stock["volume"] < stock["avgVolume"] * 1.5:
            return False, f"Volume weak ({stock['volume']:,} < 1.5× avg {stock['avgVolume']:,})"

    # Gate 3 — RSI guard (don't chase extended moves)
    if rkey == "pine_swing_buy" and stock["rsi"] > 70:
        return False, f"RSI overbought ({stock['rsi']}) — BUY signal in exhausted move"
    if rkey == "pine_swing_sell" and stock["rsi"] < 30:
        return False, f"RSI oversold ({stock['rsi']}) — SELL signal in exhausted move"

    # Gate 4 — Session time window
    if not _in_signal_window():
        return False, "Outside signal window (10:15–15:00 IST)"

    # Gate 5 — Daily cap
    if _db.count_today() >= MAX_SIGNALS_PER_DAY:
        return False, f"Daily cap of {MAX_SIGNALS_PER_DAY} reached"

    return True, "All gates passed ✅"


# ── Main scan cycle ───────────────────────────────────────────────────────────
def _run_scan_cycle():
    """
    Evaluate 4 Pine Script rules against live 5m data.
    Only fire when a stock NEWLY enters a condition AND all 5 quality gates pass.
    One Telegram message per stock per cooldown window (2h).
    """
    global _nifty_trend

    stocks = _data.get_all()
    if not stocks:
        print("[scanner] No data — skipping")
        return

    # Refresh Nifty trend each cycle
    try:
        _nifty_trend = _data.get_nifty_trend()
        print(f"[scanner] Nifty trend: {_nifty_trend}")
    except Exception as e:
        print(f"[scanner] Nifty trend error: {e}")

    fired = 0

    for rule in ACTIVE_RULES:
        rkey     = rule["key"]
        prev_set = _active.get(rkey, set())
        curr_set = set()

        for stock in stocks:
            try:
                if rule["cond"](stock):
                    curr_set.add(stock["symbol"])
            except Exception:
                continue

        new_entries = curr_set - prev_set   # NEWLY matching stocks only
        _active[rkey] = curr_set

        for symbol in new_entries:
            stock = next((s for s in stocks if s["symbol"] == symbol), None)
            if not stock:
                continue

            # Quality gates
            passed, reason = _passes_quality(stock, rule)
            if not passed:
                print(f"[scanner] ⛔ {symbol} blocked — {reason}")
                continue

            # Per-stock DB cooldown (2h)
            if _db.already_signaled(symbol, cooldown_min=120):
                print(f"[scanner] ⏭  {symbol} — cooldown active")
                continue

            price    = stock["close"]
            atr      = stock.get("atr", 0)
            target, sl = _calc_targets(price, rule["signal"], atr=atr)
            rr = round(abs(target - price) / abs(price - sl), 1) if abs(price - sl) > 0 else 0

            sig_id = _db.insert_signal(
                symbol      = symbol,
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
                symbol      = symbol,
                name        = stock["name"],
                sector      = stock["sector"],
                signal_type = rule["signal"],
                scan_name   = rule["name"],
                scan_key    = rkey,
                price       = price,
                target      = target,
                sl          = sl,
                atr         = atr,
                rr          = rr,
                time        = _ist_now().strftime("%H:%M"),
                swing_trend = stock.get("swing_trend", ""),
                nifty_trend = _nifty_trend,
                rsi         = stock.get("rsi", 0),
                volume      = stock["volume"],
                avg_volume  = stock["avgVolume"],
            )
            _notify.send_signal(signal)
            fired += 1
            print(f"[scanner] ✅ SIGNAL: {rule['signal']} {symbol} "
                  f"| Entry {price} | Target {target} | SL {sl} | R:R 1:{rr}")

    today_count = _db.count_today()
    print(f"[scanner] Cycle done — {fired} new signal(s) | {today_count}/{MAX_SIGNALS_PER_DAY} today")


# ── EOD report ────────────────────────────────────────────────────────────────
def _eod_report():
    print("[scanner] Running EOD report …")
    try:
        _data.smart_refresh()
    except Exception as e:
        print(f"[scanner] EOD refresh error: {e}")

    eod = _data.get_eod_prices()
    for symbol, price in eod.items():
        _db.update_eod(symbol, price)

    signals = _db.get_signals_today()
    _notify.send_eod_report(signals)
    print(f"[scanner] EOD report sent — {len(signals)} signal(s) today")


# ── Main loop ─────────────────────────────────────────────────────────────────
def _loop():
    opened_today   = False
    eod_sent_today = False
    last_scan      = None

    print("[scanner] v2 started — Pine Script signals only, 5 quality gates active")

    while True:
        now = _ist_now()

        # Midnight reset
        if now.hour == 0 and now.minute < 2:
            opened_today = False
            eod_sent_today = False
            _active.clear()

        # Market open — load fresh data
        if _is_market_open() and not opened_today:
            print("[scanner] Market open — loading 5m data …")
            try:
                _data.smart_refresh()
                opened_today = True
                print("[scanner] Data ready ✅")
            except Exception as e:
                print(f"[scanner] Open refresh error: {e}")

        # Every 2 minutes — refresh + scan
        if _is_market_open() and opened_today:
            elapsed = (now - last_scan).seconds if last_scan else 999
            if elapsed >= 120:
                try:
                    _data.smart_refresh()
                except Exception as e:
                    print(f"[scanner] Refresh error: {e}")
                try:
                    _run_scan_cycle()
                except Exception as e:
                    print(f"[scanner] Scan error: {e}")
                last_scan = now

        # EOD at 15:35
        if (now.weekday() < 5
                and now.time() >= _time_t(15, 35)
                and not eod_sent_today):
            try:
                _eod_report()
            except Exception as e:
                print(f"[scanner] EOD error: {e}")
            eod_sent_today = True

        _time.sleep(15)


def start():
    _db.init_db()

    # Angel One init
    try:
        import angel_data as _angel
        print("[scanner] Connecting to Angel One …")
        if _angel.login():
            _angel.build_token_map(_data.UNIVERSE)
            print("[scanner] Angel One ready ✅")
        else:
            print("[scanner] Angel One login failed — using Yahoo Finance fallback")
    except Exception as e:
        print(f"[scanner] Angel One init error: {e}")

    t = threading.Thread(target=_loop, daemon=True, name="scanner")
    t.start()
    print("[scanner] Started")
