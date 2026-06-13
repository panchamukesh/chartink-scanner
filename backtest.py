"""
MarketScan Pro — Backtester (v3 gates)

Fetches recent 5m candle history per symbol from Angel One (max ~5 days on
FIVE_MINUTE interval) and replays the 4 Pine Script rules bar-by-bar with
the same gate stack used live in scanner.py (minus things that need live
state only, like Nifty trend / sector cooldown across symbols / VIX —
those are approximated or skipped, see notes below).

Usage:
    python3 backtest.py            # all universe symbols
    python3 backtest.py RELIANCE   # single symbol

Output: per-rule and overall win-rate / expectancy report.
"""
import sys
import math
import pandas as pd

import data as _data
import angel_data as _angel
import scanner as _scanner


def _rsi(close, period=14):
    return _angel._rsi(close, period)


def _build_frame(candles):
    df = pd.DataFrame(candles, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["close"]).reset_index(drop=True)


def _indicators(df):
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]
    df["ema5"]   = close.ewm(span=5, adjust=False).mean()
    df["sma50"]  = close.rolling(50).mean()
    df["rsi"]    = _rsi(close, 14)
    df["atr"]    = _angel._atr(high, low, close, 14)
    df["adx"]    = _angel._adx(high, low, close, 14)
    df["avgvol"] = vol.rolling(20).mean()
    return df


def _row_stock(df, i):
    """Build a stock-dict snapshot at bar i (mimics live data.py output)."""
    r, p = df.iloc[i], df.iloc[i - 1]
    htf = _angel._htf_trend(df["close"].iloc[: i + 1])
    return {
        "close": r["close"], "high": r["high"], "low": r["low"],
        "changePct": (r["close"] - df["open"].iloc[0]) / df["open"].iloc[0] * 100 if df["open"].iloc[0] else 0,
        "volume": r["volume"], "avgVolume": p["avgvol"] if not math.isnan(p["avgvol"]) else 0,
        "rsi": r["rsi"], "prev_rsi": p["rsi"],
        "ema5": r["ema5"], "prev_ema5": p["ema5"],
        "sma50": r["sma50"], "prev_sma50": p["sma50"],
        "adx": r["adx"], "htf_trend": htf, "atr": r["atr"],
    }


def run(symbols=None):
    if not _angel.login():
        print("Angel One login failed — cannot backtest"); return
    universe = [s for s in _data.UNIVERSE if not symbols or s["symbol"] in symbols]
    _angel.build_token_map(universe)

    stats = {r["key"]: {"signals": 0, "wins": 0, "losses": 0, "open": 0, "pnl": []} for r in _scanner.ACTIVE_RULES}
    # confirmation counters per (rule,symbol)
    pend = {}

    for sym_info in universe:
        sym = sym_info["symbol"]
        candles = _angel._fetch_candles(sym, interval="FIVE_MINUTE", days=5)
        if not candles or len(candles) < 60:
            print(f"  {sym}: insufficient data, skip"); continue
        df = _indicators(_build_frame(candles))

        for i in range(55, len(df) - 1):  # leave room to walk forward for outcome
            stock = _row_stock(df, i)
            for rule in _scanner.ACTIVE_RULES:
                rkey = rule["key"]
                try:
                    cond = rule["cond"](stock)
                except Exception:
                    cond = False
                key = (rkey, sym)
                if cond:
                    pend[key] = pend.get(key, 0) + 1
                else:
                    pend[key] = 0
                if pend.get(key, 0) != _scanner.CONFIRM_CYCLES:
                    continue  # only act on the bar confirmation completes

                # ADX + HTF gates (the gates that are purely per-symbol/time)
                if stock["adx"] and stock["adx"] < _scanner.ADX_MIN:
                    continue
                if rule["signal"] == "BUY" and stock["htf_trend"] == "bearish":
                    continue
                if rule["signal"] == "SELL" and stock["htf_trend"] == "bullish":
                    continue
                if rkey in {"pine_swing_buy", "pine_swing_sell"} and stock["avgVolume"]:
                    if stock["volume"] < stock["avgVolume"] * 1.5:
                        continue
                if rkey == "pine_swing_buy" and stock["rsi"] > 70:
                    continue
                if rkey == "pine_swing_sell" and stock["rsi"] < 30:
                    continue

                # Simulate trade: walk forward until target/SL hit or data ends
                price = stock["close"]
                atr   = stock["atr"]
                target, sl = _scanner._calc_targets(price, rule["signal"], atr=atr)
                outcome, pnl = "open", 0.0
                for j in range(i + 1, len(df)):
                    hi, lo = df["high"].iloc[j], df["low"].iloc[j]
                    if rule["signal"] == "BUY":
                        if hi >= target: outcome, pnl = "win", (target - price) / price * 100; break
                        if lo <= sl:     outcome, pnl = "loss", (sl - price) / price * 100; break
                    else:
                        if lo <= target: outcome, pnl = "win", (price - target) / price * 100; break
                        if hi >= sl:     outcome, pnl = "loss", (price - sl) / price * 100; break

                stats[rkey]["signals"] += 1
                stats[rkey]["pnl"].append(pnl)
                if outcome == "win": stats[rkey]["wins"] += 1
                elif outcome == "loss": stats[rkey]["losses"] += 1
                else: stats[rkey]["open"] += 1

    # ── Report ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("BACKTEST REPORT — v3 gate stack (ADX, HTF, volume, RSI, 2-bar confirm)")
    print("=" * 60)
    total_sig = total_win = total_loss = 0
    all_pnl = []
    for rule in _scanner.ACTIVE_RULES:
        s = stats[rule["key"]]
        n = s["signals"]
        closed = s["wins"] + s["losses"]
        wr = round(s["wins"] / closed * 100, 1) if closed else 0
        avg_pnl = round(sum(s["pnl"]) / len(s["pnl"]), 2) if s["pnl"] else 0
        print(f"\n{rule['name']} ({rule['key']})")
        print(f"  Signals: {n}  Wins: {s['wins']}  Losses: {s['losses']}  Open: {s['open']}")
        print(f"  Win rate (closed): {wr}%   Avg PnL/trade: {avg_pnl}%")
        total_sig += n; total_win += s["wins"]; total_loss += s["losses"]
        all_pnl.extend(s["pnl"])

    closed = total_win + total_loss
    overall_wr = round(total_win / closed * 100, 1) if closed else 0
    overall_pnl = round(sum(all_pnl) / len(all_pnl), 2) if all_pnl else 0
    print("\n" + "-" * 60)
    print(f"OVERALL: {total_sig} signals | Win rate (closed): {overall_wr}% | Avg PnL/trade: {overall_pnl}%")
    print("-" * 60)
    print("\nNotes:")
    print("- Nifty-trend, sector-cooldown, daily-cap, India-VIX, session-window")
    print("  gates are NOT applied here (need live cross-symbol/market state).")
    print("  Real live win rate will be <= this backtest number.")
    print(f"- Angel One FIVE_MINUTE history is capped at ~5 days, so sample")
    print(f"  size ({total_sig} signals) is still small. Re-run weekly to build history.")


if __name__ == "__main__":
    syms = sys.argv[1:] or None
    run(syms)
