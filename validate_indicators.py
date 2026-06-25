"""
validate_indicators.py — Upstox indicator validation script.
Logs into Upstox, fetches raw 1min + 5min candles for 5 key stocks,
prints timestamp alignment, candle counts, and all computed indicators.
Run on VM: cd /home/priya141ch/chartink-scanner && source /home/priya141ch/chartink-venv/bin/activate && python3 validate_indicators.py
"""
import os, sys, math
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

_IST = timezone(timedelta(hours=5, minutes=30))

TEST_STOCKS = [
    {"symbol": "RELIANCE",  "name": "Reliance Industries",  "sector": "Energy"},
    {"symbol": "HDFCBANK",  "name": "HDFC Bank",            "sector": "Banking"},
    {"symbol": "INFY",      "name": "Infosys",              "sector": "IT"},
    {"symbol": "TCS",       "name": "Tata Consultancy Services", "sector": "IT"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank",           "sector": "Banking"},
]

print("=" * 70)
print("MarketScan Pro — Indicator Validation")
print(f"Run at: {datetime.now(_IST).strftime('%Y-%m-%d %H:%M:%S')} IST")
print("=" * 70)

# ── Step 1: Login ─────────────────────────────────────────────────────────────
import upstox_data as ud
import data as _data

print("\n[1] Logging in to Upstox...")
if not ud.login():
    print("ERROR: Upstox login failed. Check UPSTOX_ACCESS_TOKEN in .env")
    sys.exit(1)

print("[2] Building token map...")
ud.build_token_map(TEST_STOCKS)

print()

# ── Step 2: Per-stock validation ──────────────────────────────────────────────
for sym_info in TEST_STOCKS:
    sym = sym_info["symbol"]
    print("─" * 70)
    print(f"STOCK: {sym}")

    # A) Raw 1min candles
    print(f"\n  [A] Raw 1-min candles (days=2):")
    try:
        raw1 = ud._fetch_candles(sym, interval="ONE_MINUTE", days=2)
        if raw1:
            print(f"      Total raw 1min candles: {len(raw1)}")
            print(f"      First 3 timestamps: {[c[0] for c in raw1[:3]]}")
            print(f"      Last 3 timestamps:  {[c[0] for c in raw1[-3:]]}")
            # Check for duplicates
            ts_list = [c[0] for c in raw1]
            dups = len(ts_list) - len(set(ts_list))
            print(f"      Duplicate timestamps: {dups}")
        else:
            print("      ERROR: No 1min candles returned")
    except Exception as e:
        print(f"      EXCEPTION: {e}")

    # B) 5min resampled candles
    print(f"\n  [B] 5-min resampled candles (days=5):")
    try:
        raw5 = ud._fetch_candles(sym, interval="FIVE_MINUTE", days=5)
        if raw5:
            print(f"      Total 5min candles: {len(raw5)}")
            # Today's candles
            today_str = datetime.now(_IST).strftime("%Y-%m-%d")
            today_c = [c for c in raw5 if str(c[0]).startswith(today_str)]
            print(f"      Today's candles: {len(today_c)}")
            # Timestamp alignment check
            print(f"      Last 5 timestamps:")
            for c in raw5[-5:]:
                ts = str(c[0])
                # Extract HH:MM
                hhmm = ts[11:16] if len(ts) > 15 else ts
                mins = int(hhmm.split(":")[1]) if ":" in hhmm else -1
                aligned = "✅" if mins % 5 == 0 else "❌ MISALIGNED"
                print(f"        {ts}  {aligned}")
            # Duplicate check
            ts_list5 = [c[0] for c in raw5]
            dups5 = len(ts_list5) - len(set(ts_list5))
            print(f"      Duplicate timestamps: {dups5}")
        else:
            print("      ERROR: No 5min candles returned")
            continue
    except Exception as e:
        print(f"      EXCEPTION: {e}")
        continue

    # C) Compute indicators
    print(f"\n  [C] Computed indicators:")
    try:
        stock = ud._compute(raw5, sym_info)
        if stock:
            print(f"      close:     {stock['close']}")
            print(f"      ema5:      {stock['ema5']}  (prev: {stock['prev_ema5']})")
            print(f"      ema20:     {stock['ema20']}")
            print(f"      ema50:     {stock['ema50']}")
            print(f"      sma20:     {stock['sma20']}")
            print(f"      sma50:     {stock['sma50']}  (prev: {stock['prev_sma50']})")
            print(f"      rsi:       {stock['rsi']}  (prev: {stock['prev_rsi']})")
            rsi_ok = 0 < stock['rsi'] < 100
            print(f"               → RSI in range 0-100: {'✅' if rsi_ok else '❌'}")
            print(f"      adx:       {stock['adx']}")
            adx_ok = stock['adx'] > 0
            print(f"               → ADX > 0: {'✅' if adx_ok else '❌'}")
            print(f"      atr:       {stock['atr']}")
            print(f"      htf_trend: {stock['htf_trend']}")
            htf_ok = stock['htf_trend'] != 'neutral'
            print(f"               → htf_trend not neutral: {'✅' if htf_ok else '⚠️  NEUTRAL (check bar count)'}")
            print(f"      volume:    {stock['volume']:,}")
            print(f"      avgVolume: {stock['avgVolume']:,}")
            print(f"      swing_trend: {stock['swing_trend']}")

            # EMA sanity: EMA5 should be close to current close
            ema5_diff_pct = abs(stock['ema5'] - stock['close']) / stock['close'] * 100
            print(f"\n      EMA5 vs close diff: {ema5_diff_pct:.2f}% {'✅' if ema5_diff_pct < 2 else '⚠️'}")

            # htf_trend debug — print bar count breakdown
            import pandas as pd
            df = pd.DataFrame(raw5, columns=["ts","open","high","low","close","volume"])
            n15 = len(df) // 3
            print(f"\n      5min bars total: {len(df)}")
            print(f"      15min bars (÷3): {n15}")
            print(f"      SMA50 needs 50 15min bars — {'✅ enough' if n15 >= 50 else '❌ insufficient'}")
        else:
            print(f"      ERROR: _compute() returned None (< 55 bars?)")
            print(f"      5min bar count: {len(raw5) if raw5 else 0}")
    except Exception as e:
        import traceback
        print(f"      EXCEPTION: {e}")
        traceback.print_exc()

    print()

# ── Step 3: htf_trend detailed analysis ───────────────────────────────────────
print("=" * 70)
print("HTF TREND ANALYSIS (detailed)")
print("=" * 70)

for sym_info in TEST_STOCKS[:2]:  # just 2 stocks for brevity
    sym = sym_info["symbol"]
    try:
        raw5 = ud._fetch_candles(sym, interval="FIVE_MINUTE", days=5)
        if not raw5:
            continue
        import pandas as pd, math
        df = pd.DataFrame(raw5, columns=["ts","open","high","low","close","volume"])
        close = df["close"].astype(float)
        n = len(close) // 3
        print(f"\n{sym}: {len(close)} 5min bars → {n} 15min bars")
        if n >= 55:
            c15 = pd.Series(close.iloc[:n*3].values.reshape(n, 3)[:, -1])
            ema5_15  = c15.ewm(span=5,  adjust=False).mean()
            sma50_15 = c15.rolling(50).mean()
            print(f"  15min EMA5:  {ema5_15.iloc[-1]:.2f}")
            print(f"  15min SMA50: {sma50_15.iloc[-1]:.2f}")
            print(f"  SMA50 is NaN: {math.isnan(float(sma50_15.iloc[-1]))}")
            trend = "bullish" if ema5_15.iloc[-1] > sma50_15.iloc[-1] else "bearish"
            print(f"  → htf_trend: {trend}")
        else:
            print(f"  ❌ n={n} < 55 — htf_trend returns neutral (not enough 15min bars)")
    except Exception as e:
        print(f"  EXCEPTION for {sym}: {e}")

# ── Step 4: Session window check ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("SESSION WINDOW CHECK")
print("=" * 70)
now_ist = datetime.now(_IST)
from datetime import time as _t
in_window = _t(10, 15) <= now_ist.time() <= _t(15, 0)
print(f"Current time IST: {now_ist.strftime('%H:%M:%S')}")
print(f"_is_market_open window (10:00-15:30): {_t(10,0) <= now_ist.time() <= _t(15,30)}")
print(f"_in_signal_window (10:15-15:00): {in_window}")

# ── Step 5: Resample anchor verification ──────────────────────────────────────
print("\n" + "=" * 70)
print("RESAMPLE ANCHOR VERIFICATION")
print("=" * 70)
sym_info = TEST_STOCKS[0]
sym = sym_info["symbol"]
try:
    raw1 = ud._fetch_candles(sym, interval="ONE_MINUTE", days=2)
    if raw1:
        import pandas as pd
        df = pd.DataFrame(raw1, columns=["ts","open","high","low","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(_IST)
        df = df.set_index("ts")
        today_str = datetime.now(_IST).strftime("%Y-%m-%d")
        today_df = df[df.index.strftime("%Y-%m-%d") == today_str]
        if not today_df.empty:
            first_ts = today_df.index[0]
            print(f"First 1min candle today for {sym}: {first_ts}")
            print(f"  Minute: {first_ts.minute} (expected 15 for 09:15)")
            if first_ts.hour == 9 and first_ts.minute == 15:
                print("  ✅ Starts at 09:15 — resample will anchor correctly")
            elif first_ts.hour == 9 and first_ts.minute == 16:
                print("  ❌ Starts at 09:16 — resample produces 09:16,09:21... MISALIGNED vs TradingView!")
            else:
                print(f"  ⚠️  Unexpected start: {first_ts.hour}:{first_ts.minute:02d}")

            # Show what resample produces
            agg = today_df.resample("5min", label="left", closed="left").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum"
            }).dropna(subset=["open"])
            print(f"  First 3 resampled 5min bars:")
            for ts, row in agg.head(3).iterrows():
                mins = ts.minute
                aligned = "✅" if mins % 5 == 0 else "❌ MISALIGNED"
                print(f"    {ts.strftime('%H:%M')} {aligned}")
        else:
            print(f"  No today candles found for {sym} (market may be closed)")
except Exception as e:
    import traceback
    print(f"EXCEPTION: {e}")
    traceback.print_exc()

print("\n" + "=" * 70)
print("Validation complete.")
print("=" * 70)
