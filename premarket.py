"""
MarketScan Pro — Pre-market Briefing

Runs automatically ~8:30 AM IST (before market open at 9:15) and sends a
Telegram report covering:
  1. Nifty 50 / Bank Nifty bias for the day — based on prior close,
     overnight US market cues (Dow/Nasdaq/S&P), and recent 5d trend.
  2. Key levels (prior close, EMA20/SMA50 on daily) for both indices.
  3. Stocks to watch — pulled live from a financial-news RSS feed
     (Economic Times Markets), filtered to symbols in our UNIVERSE
     plus top headline mentions generally.

No manual steps — pure data pull + Telegram push.
"""
import re
import math
import urllib.request
import xml.etree.ElementTree as ET

import yfinance as yf
import pandas as pd

import data as _data
import notify as _notify

ETMARKETS_RSS = "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146843.cms"


# ── Index bias ─────────────────────────────────────────────────────────────
def _index_snapshot(ticker: str):
    """Returns (last_close, prev_close, ema20, sma50, pct_chg_1d, pct_chg_5d)."""
    try:
        raw = yf.download(ticker, period="3mo", interval="1d", auto_adjust=True, progress=False)
        if raw is None or raw.empty:
            return None
        close = raw["Close"].dropna()
        last  = float(close.iloc[-1].item() if hasattr(close.iloc[-1], "item") else close.iloc[-1])
        prev  = float(close.iloc[-2].item() if hasattr(close.iloc[-2], "item") else close.iloc[-2]) if len(close) > 1 else last
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float("nan")
        chg1d = (last - prev) / prev * 100 if prev else 0
        chg5d = (last - float(close.iloc[-6].item() if hasattr(close.iloc[-6], "item") else close.iloc[-6])) / float(close.iloc[-6].item() if hasattr(close.iloc[-6], "item") else close.iloc[-6]) * 100 if len(close) > 5 else 0
        return dict(last=last, prev=prev, ema20=ema20, sma50=sma50, chg1d=chg1d, chg5d=chg5d)
    except Exception as e:
        print(f"[premarket] {ticker} snapshot error: {e}")
        return None


def _global_cues():
    """Overnight % change of major US indices — proxy for gap-up/gap-down bias."""
    cues = {}
    for name, ticker in [("Dow", "^DJI"), ("Nasdaq", "^IXIC"), ("S&P 500", "^GSPC")]:
        try:
            raw = yf.download(ticker, period="5d", interval="1d", auto_adjust=True, progress=False)
            close = raw["Close"].dropna()
            if len(close) >= 2:
                chg = (float(close.iloc[-1].item() if hasattr(close.iloc[-1], "item") else close.iloc[-1]) - float(close.iloc[-2].item() if hasattr(close.iloc[-2], "item") else close.iloc[-2])) / float(close.iloc[-2].item() if hasattr(close.iloc[-2], "item") else close.iloc[-2]) * 100
                cues[name] = round(chg, 2)
        except Exception as e:
            print(f"[premarket] {name} cue error: {e}")
    return cues


def _bias_label(index_snap, global_avg):
    """Combine index trend + global cues into a simple bias label."""
    if not index_snap:
        return "NEUTRAL", "—"
    score = 0
    if index_snap["last"] > index_snap["ema20"]:
        score += 1
    if not math.isnan(index_snap["sma50"]) and index_snap["last"] > index_snap["sma50"]:
        score += 1
    if global_avg > 0.3:
        score += 1
    elif global_avg < -0.3:
        score -= 1
    if index_snap["chg5d"] > 0:
        score += 0.5
    else:
        score -= 0.5

    if score >= 1.5:
        return "BULLISH 🟢", "Gap-up bias likely — favor longs on dips toward EMA20"
    elif score <= -1.5:
        return "BEARISH 🔴", "Gap-down bias likely — favor shorts on rallies toward EMA20"
    else:
        return "RANGE-BOUND ⚪", "Mixed cues — expect choppy session, wait for direction"


# ── News-based stocks to watch ───────────────────────────────────────────────
def _trending_stocks(limit=8):
    """
    Pull latest headlines from Economic Times Markets RSS and extract
    stock names that match our universe (or just surface top headlines
    if no universe match found).
    """
    try:
        req = urllib.request.Request(ETMARKETS_RSS, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        root  = ET.fromstring(raw)
        items = root.findall(".//item")[:30]
    except Exception as e:
        print(f"[premarket] RSS error: {e}")
        return [], []

    headlines = []
    matched   = set()
    universe_names = {s["symbol"]: s["name"] for s in _data.UNIVERSE}

    for item in items:
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        headlines.append(title)
        for sym, name in universe_names.items():
            # Match either the symbol or first word of company name in headline
            first_word = name.split()[0]
            if re.search(rf"\b{re.escape(sym)}\b", title, re.I) or re.search(rf"\b{re.escape(first_word)}\b", title, re.I):
                matched.add(sym)

    return list(matched)[:limit], headlines[:8]


# ── Report builder ────────────────────────────────────────────────────────────
def build_report() -> str:
    nifty = _index_snapshot("^NSEI")
    bnf   = _index_snapshot("^NSEBANK")
    cues  = _global_cues()
    global_avg = sum(cues.values()) / len(cues) if cues else 0

    nifty_bias, nifty_note = _bias_label(nifty, global_avg)
    bnf_bias,   bnf_note   = _bias_label(bnf, global_avg)

    lines = [
        "🌅 *MarketScan Pro — Pre-Market Briefing*",
        "━━━━━━━━━━━━━━━━━━━━━",
        "*🌍 Global Cues (overnight)*",
    ]
    if cues:
        lines.append("  " + "  |  ".join(f"{k} {'+' if v>=0 else ''}{v}%" for k, v in cues.items()))
    else:
        lines.append("  _unavailable_")

    lines.append("")
    lines.append("*📊 NIFTY 50*")
    if nifty:
        lines += [
            f"  Prev Close: ₹{nifty['prev']:,.0f}  ({'+' if nifty['chg1d']>=0 else ''}{nifty['chg1d']:.2f}% last session)",
            f"  EMA20: ₹{nifty['ema20']:,.0f}  |  SMA50: ₹{nifty['sma50']:,.0f}" if not math.isnan(nifty['sma50']) else f"  EMA20: ₹{nifty['ema20']:,.0f}",
            f"  5-day trend: {'+' if nifty['chg5d']>=0 else ''}{nifty['chg5d']:.2f}%",
            f"  *Bias: {nifty_bias}* — {nifty_note}",
        ]
    else:
        lines.append("  _data unavailable_")

    lines.append("")
    lines.append("*🏦 BANK NIFTY*")
    if bnf:
        lines += [
            f"  Prev Close: ₹{bnf['prev']:,.0f}  ({'+' if bnf['chg1d']>=0 else ''}{bnf['chg1d']:.2f}% last session)",
            f"  EMA20: ₹{bnf['ema20']:,.0f}" + (f"  |  SMA50: ₹{bnf['sma50']:,.0f}" if not math.isnan(bnf['sma50']) else ""),
            f"  5-day trend: {'+' if bnf['chg5d']>=0 else ''}{bnf['chg5d']:.2f}%",
            f"  *Bias: {bnf_bias}* — {bnf_note}",
        ]
    else:
        lines.append("  _data unavailable_")

    matched, headlines = _trending_stocks()
    lines.append("")
    lines.append("*📰 Stocks to Watch Today (from market news)*")
    if matched:
        for sym in matched:
            meta = next((s for s in _data.UNIVERSE if s["symbol"] == sym), None)
            name = meta["name"] if meta else sym
            lines.append(f"  • {sym} — {name}")
    else:
        lines.append("  _No universe stocks in today's top headlines_")

    if headlines:
        lines.append("")
        lines.append("*🗞 Top Market Headlines*")
        for h in headlines[:5]:
            lines.append(f"  • {h}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("⚡ Scanner active 10:15–15:00 IST | Max 5 signals/day | 10-gate confirmation")

    return "\n".join(lines)


def send_premarket_report():
    try:
        report = build_report()
        _notify._send(report)
        print("[premarket] ✅ Pre-market briefing sent")
    except Exception as e:
        print(f"[premarket] Error: {e}")
