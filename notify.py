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


_PINE_KEYS = {"pine_swing_buy", "pine_swing_sell", "pine_rsi_reversal_buy", "pine_rsi_reversal_sell"}


def send_signal(signal):
    """Send a single scan signal alert to Telegram."""
    is_buy   = signal["signal_type"] == "BUY"
    is_swing = signal.get("scan_key", "") in _PINE_KEYS or "Swing" in signal.get("scan_name", "")
    emoji    = "🟢" if is_buy else "🔴"
    pnl_dir  = "+" if is_buy else "-"
    price    = signal["price"]
    tgt_pct  = abs(round((signal["target"] - price) / price * 100, 1)) if price else 0
    sl_pct   = abs(round((signal["sl"]     - price) / price * 100, 1)) if price else 0
    rr       = round(tgt_pct / sl_pct, 1) if sl_pct else "?"

    # Swing trend context
    trend = signal.get("swing_trend", "")
    trend_str = ""
    if trend == "bullish":
        trend_str = "  |  📈 Trend: Bullish (price above SMA50)"
    elif trend == "bearish":
        trend_str = "  |  📉 Trend: Bearish (price below SMA50)"

    tag        = "🔄 *SWING CALL*" if is_swing else "📊 *Scan Signal*"
    match_count = signal.get("match_count", 1)
    strength   = f"  |  💪 {match_count} scans confirm" if match_count > 1 else ""

    lines = [
        f"{emoji} {tag} — *{signal['symbol']}*  [{signal['signal_type']}]",
        f"📋 _{signal['scan_name']}_",
        f"🏭 {signal.get('sector', '—')}{trend_str}{strength}",
        f"",
        f"💰 Entry:  ₹{price:,.2f}",
        f"🎯 Target: ₹{signal['target']:,.2f}  ({pnl_dir}{tgt_pct}%)",
        f"🛑 SL:     ₹{signal['sl']:,.2f}  ({'-' if is_buy else '+'}{sl_pct}%)",
        f"",
        f"⚖️ R:R = 1:{rr}  |  ⏰ {signal['time']} IST",
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
