"""Telegram notification sender."""
import os
import requests


def _cfg():
    return {
        "token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }


def _send(text):
    cfg = _cfg()
    if not cfg["token"] or not cfg["chat_id"]:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception as e:
        print(f"[notify] Telegram error: {e}")


def send_signal(signal):
    """Send a quality-filtered signal alert to Telegram."""
    is_buy  = signal["signal_type"] == "BUY"
    emoji   = "🟢" if is_buy else "🔴"
    price   = signal["price"]
    target  = signal["target"]
    sl      = signal["sl"]

    tgt_pct = round(abs(target - price) / price * 100, 1) if price else 0
    sl_pct  = round(abs(price  - sl)    / price * 100, 1) if price else 0
    rr      = signal.get("rr") or (round(tgt_pct / sl_pct, 1) if sl_pct else "?")

    atr         = signal.get("atr", 0)
    atr_str     = f"  |  ATR ₹{atr:.1f}" if atr else ""
    nifty_trend = signal.get("nifty_trend", "")
    nifty_str   = "📈 Nifty Bullish" if nifty_trend == "bullish" else "📉 Nifty Bearish"
    rsi         = signal.get("rsi", 0)
    vol         = signal.get("volume", 0)
    avg_vol     = signal.get("avg_volume", 0)
    vol_x       = round(vol / avg_vol, 1) if avg_vol else 0

    lines = [
        f"{emoji} *{'SWING BUY' if is_buy else 'SWING SELL'} — {signal['symbol']}*",
        f"📋 _{signal['scan_name']}_",
        f"🏭 {signal.get('sector','—')}  |  {nifty_str}",
        f"",
        f"💰 *Entry:*  ₹{price:,.2f}",
        f"🎯 *Target:* ₹{target:,.2f}  ({'+' if is_buy else '-'}{tgt_pct}%)",
        f"🛑 *SL:*     ₹{sl:,.2f}  ({'-' if is_buy else '+'}{sl_pct}%){atr_str}",
        f"",
        f"⚖️ R:R = *1:{rr}*  |  RSI {rsi}  |  Vol {vol_x}× avg",
        f"⏰ {signal['time']} IST",
    ]
    _send("\n".join(lines))


def send_eod_report(signals):
    """
    Send consolidated end-of-day report.
    Splits into multiple Telegram messages if content exceeds 4096 chars.
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%d %b %Y")

    if not signals:
        _send(f"📋 *MarketScan Pro — EOD Report*\n📅 {date_str}\n\nNo signals fired today.")
        return

    total    = len(signals)
    hits     = sum(1 for s in signals if s.get("target_hit"))
    stops    = sum(1 for s in signals if s.get("sl_hit"))
    open_    = total - hits - stops
    win_rate = round(hits / total * 100) if total else 0
    pnls     = [s["pnl_pct"] for s in signals if s.get("pnl_pct") is not None]
    avg_pnl  = round(sum(pnls) / len(pnls), 2) if pnls else 0

    # ── Part 1: Summary header (always one message) ───────────────────────────
    header = "\n".join([
        f"📋 *MarketScan Pro — EOD Report*",
        f"📅 {date_str}",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total Signals: *{total}*",
        f"✅ Target Hit: *{hits}*   ❌ SL Hit: *{stops}*   ⏳ Open: *{open_}*",
        f"🏆 Win Rate: *{win_rate}%*   📈 Avg P&L: *{'+' if avg_pnl>=0 else ''}{avg_pnl}%*",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ])
    _send(header)

    # ── Part 2+: Signal rows, chunked to stay under 4096 chars ───────────────
    CHUNK_LIMIT = 3800   # safe buffer below Telegram's 4096

    chunk_lines = []
    chunk_len   = 0

    for s in signals:
        eod = s.get("eod_price")
        pnl = s.get("pnl_pct")

        if s.get("target_hit"):
            status = "✅ HIT"
        elif s.get("sl_hit"):
            status = "❌ SL"
        else:
            status = "⏳"

        eod_str = f"EOD ₹{eod:,.0f} ({'+' if pnl and pnl>=0 else ''}{pnl if pnl else 0:.1f}%)" if eod else "EOD —"
        line = (
            f"{'🟢' if s['signal_type']=='BUY' else '🔴'} *{s['symbol']}* "
            f"[{s['signal_type']}] @₹{s['price']:,.0f} | "
            f"T:₹{s['target']:,.0f} SL:₹{s['sl']:,.0f} | "
            f"{eod_str} {status} | {s['time']}"
        )

        if chunk_len + len(line) + 1 > CHUNK_LIMIT:
            _send("\n".join(chunk_lines))
            chunk_lines = []
            chunk_len   = 0

        chunk_lines.append(line)
        chunk_len += len(line) + 1

    if chunk_lines:
        _send("\n".join(chunk_lines))
