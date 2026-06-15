"""
MarketScan Pro — Telegram bot command interface.

Long-polling bot (background daemon thread) that lets the configured
TELEGRAM_CHAT_ID interact with the live scanner: status, signals, scans,
positions, pause/resume, backtests, watchlist, price alerts, etc.

Started from server.py via telegram_bot.start().
"""
import os
import json
import time
import threading
import difflib
from datetime import datetime, timezone, timedelta

import requests

import data as _data
import db as _db
import scanner as _scanner
import notify as _notify

_IST = timezone(timedelta(hours=5, minutes=30))

_BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
WATCHLIST_FILE = os.path.join(_BASE_DIR, "watchlist.json")
ALERTS_FILE    = os.path.join(_BASE_DIR, "alerts.json")

_session = requests.Session()
_offset  = 0

_watchlist: list = []
_alerts:    list = []   # [{"symbol":.., "dir":"above"/"below", "price":.., "id":..}]


# ───────────────────────── persistence helpers ────────────────────────────
def _load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception as e:
        print(f"[telegram_bot] load {path} error: {e}")
    return default


def _save_json(path, obj):
    try:
        with open(path, "w") as f:
            json.dump(obj, f, indent=2)
    except Exception as e:
        print(f"[telegram_bot] save {path} error: {e}")


def _load_state():
    global _watchlist, _alerts
    _watchlist = _load_json(WATCHLIST_FILE, [])
    _alerts    = _load_json(ALERTS_FILE, [])


# ───────────────────────── telegram api helpers ────────────────────────────
def _cfg():
    return {
        "token":   os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
    }


def _reply(text):
    cfg = _cfg()
    if not cfg["token"] or not cfg["chat_id"]:
        return
    if len(text) > 4000:
        text = text[:3990] + "\n…(truncated)"
    try:
        _session.post(
            f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        print(f"[telegram_bot] send error: {e}")


def _get_updates(token, timeout=30):
    global _offset
    try:
        resp = _session.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": _offset, "timeout": timeout},
            timeout=timeout + 10,
        )
        if resp.status_code != 200:
            print(f"[telegram_bot] getUpdates {resp.status_code}: {resp.text[:200]}")
            return []
        return resp.json().get("result", [])
    except Exception as e:
        print(f"[telegram_bot] getUpdates error: {e}")
        return []


# ───────────────────────── small utils ─────────────────────────────────────
def _ist_now():
    return datetime.now(_IST)


def _find_stock(symbol):
    symbol = symbol.upper().strip()
    for s in _data.get_all():
        if s["symbol"] == symbol:
            return s
    return None


def _closest_symbols(symbol, n=5):
    symbol = symbol.upper().strip()
    all_syms = [u["symbol"] for u in _data.UNIVERSE]
    matches = difflib.get_close_matches(symbol, all_syms, n=n, cutoff=0.3)
    if not matches:
        matches = [s for s in all_syms if symbol in s][:n]
    return matches


def _vix_regime(vix):
    if not vix:
        return "unknown"
    if vix > _scanner.VIX_PAUSE:
        return "pause (signals paused)"
    if vix >= _scanner.VIX_WIDEN:
        return "elevated (SL widened)"
    return "calm"


# ───────────────────────── command handlers ────────────────────────────────
def _cmd_help(args):
    return (
        "🤖 *MarketScan Pro — Telegram Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*📊 Status & Info*\n"
        "/status — health, refresh time, VIX, Nifty bias, today's signal count\n"
        "  _e.g._ `/status`\n"
        "/vix — current India VIX + regime\n"
        "  _e.g._ `/vix`\n\n"
        "*📈 Stock & Scan*\n"
        "/signal SYMBOL — full indicator snapshot + rule status for a stock\n"
        "  _e.g._ `/signal RELIANCE`\n"
        "/explain SYMBOL — which rules match now & which gate blocks them\n"
        "  _e.g._ `/explain TCS`\n"
        "/scan CONDITION — screen the universe for a condition\n"
        "  _e.g._ `/scan rsi70`\n"
        "  conditions: 20ema/above20ema, below20ema, 50sma/above50sma, "
        "below50sma, rsi70/overbought, rsi30/oversold, breakout, "
        "highvolume, bullish_htf, bearish_htf\n\n"
        "*📋 Signals & Positions*\n"
        "/signals or /today — today's fired signals\n"
        "  _e.g._ `/today`\n"
        "/positions — open positions with live P&L%\n"
        "  _e.g._ `/positions`\n"
        "/pnl day|week — aggregate win-rate & P&L stats\n"
        "  _e.g._ `/pnl week`\n\n"
        "*⏸️ Control*\n"
        "/pause — stop new signals (trailing SL still runs)\n"
        "/resume — resume new signal generation\n"
        "/backtest SYMBOL — run a backtest (takes ~10-30s)\n"
        "  _e.g._ `/backtest INFY`\n\n"
        "*⭐ Watchlist*\n"
        "/watchlist — show watchlist\n"
        "/watchlist add SYMBOL — add a symbol\n"
        "/watchlist remove SYMBOL — remove a symbol\n\n"
        "*🔔 Price Alerts*\n"
        "/alertme SYMBOL above|below PRICE — set a price alert\n"
        "  _e.g._ `/alertme INFY above 1600`\n"
        "/alerts — list active alerts\n"
        "/alerts clear — clear all alerts\n\n"
        "/help — show this message"
    )


def _cmd_status(args):
    refreshed = _data._last_refresh.strftime("%H:%M:%S") if _data._last_refresh else "never"
    try:
        import upstox_data as _upstox
        ready = _upstox.is_ready()
    except Exception:
        ready = False
    vix = _scanner._india_vix or _data.get_india_vix()
    nifty_trend = _scanner._nifty_trend
    signals = _db.get_signals_today()
    total = len(signals)
    hits  = sum(1 for s in signals if s.get("target_hit"))
    stops = sum(1 for s in signals if s.get("sl_hit"))
    open_ = total - hits - stops
    paused = getattr(_scanner, "_paused", False)

    lines = [
        "🩺 *MarketScan Pro — Status*",
        f"Market open: {'✅' if _scanner._is_market_open() else '❌'}",
        f"Scanner: {'⏸️ PAUSED' if paused else '▶️ running'}",
        f"Last data refresh: {refreshed} IST",
        f"Cached symbols: {len(_data.get_all())}",
        f"Upstox token: {'✅ ready' if ready else '❌ not ready'}",
        f"India VIX: {vix:.2f} ({_vix_regime(vix)})" if vix else "India VIX: unavailable",
        f"Nifty trend: {nifty_trend}",
        "",
        f"📊 Today's signals: {total}  (✅{hits} 🎯  ❌{stops} SL  ⏳{open_} open)",
    ]
    return "\n".join(lines)


def _cmd_vix(args):
    vix = _scanner._india_vix or _data.get_india_vix()
    if not vix:
        return "⚠️ India VIX unavailable right now."
    return f"📉 *India VIX*: {vix:.2f}\nRegime: {_vix_regime(vix)}"


def _cmd_signal(args):
    if not args:
        return "Usage: `/signal SYMBOL`  e.g. `/signal RELIANCE`"
    symbol = args[0].upper()
    stock = _find_stock(symbol)
    if not stock:
        suggestions = _closest_symbols(symbol)
        msg = f"⚠️ No live data for *{symbol}*."
        if suggestions:
            msg += f"\nDid you mean: {', '.join(suggestions)}?"
        return msg

    lines = [
        f"📈 *{stock['symbol']}* — {stock.get('name','')}",
        f"Sector: {stock.get('sector','—')}  |  Timeframe: {stock.get('timeframe','5m')}",
        "",
        f"💰 Price: ₹{stock['close']:,.2f}  ({'+' if stock['changePct']>=0 else ''}{stock['changePct']}%)",
        f"RSI: {stock['rsi']}  |  ADX: {stock.get('adx',0)}",
        f"EMA5: ₹{stock['ema5']:,.2f}  |  EMA20: ₹{stock.get('ema20',0):,.2f}  |  SMA50: ₹{stock['sma50']:,.2f}",
        f"ATR: ₹{stock.get('atr',0):,.2f}  |  HTF trend: {stock.get('htf_trend','—')}",
        f"Swing trend: {stock.get('swing_trend','—')}",
        f"Resistance: ₹{stock.get('resistance',0):,.2f}",
        f"Volume: {stock['volume']:,}  (avg {stock['avgVolume']:,})",
    ]

    lines.append("")
    lines.append("*Rule status:*")
    for rule in _scanner.ACTIVE_RULES:
        try:
            matched = rule["cond"](stock)
        except Exception:
            matched = False
        if matched:
            passed, reason = _scanner._passes_quality(stock, rule)
            status = "✅ would fire" if passed else f"🟡 matches but blocked — {reason}"
        else:
            status = "—"
        lines.append(f"  • {rule['name']}: {status}")

    # Most recent signal today for this symbol
    today_sigs = [s for s in _db.get_signals_today() if s["symbol"] == symbol]
    if today_sigs:
        s = today_sigs[-1]
        st = "🎯 target hit" if s.get("target_hit") else ("❌ SL hit" if s.get("sl_hit") else "⏳ open")
        lines.append("")
        lines.append(
            f"*Last signal today:* {s['signal_type']} @ ₹{s['price']:,.2f} "
            f"(T ₹{s['target']:,.2f} / SL ₹{s['sl']:,.2f}) — {st} — {s['time']}"
        )

    return "\n".join(lines)


def _cmd_explain(args):
    if not args:
        return "Usage: `/explain SYMBOL`  e.g. `/explain TCS`"
    symbol = args[0].upper()
    stock = _find_stock(symbol)
    if not stock:
        suggestions = _closest_symbols(symbol)
        msg = f"⚠️ No live data for *{symbol}*."
        if suggestions:
            msg += f"\nDid you mean: {', '.join(suggestions)}?"
        return msg

    lines = [f"🔍 *Rule analysis for {symbol}*"]
    any_match = False
    for rule in _scanner.ACTIVE_RULES:
        try:
            matched = rule["cond"](stock)
        except Exception:
            matched = False
        if not matched:
            continue
        any_match = True
        passed, reason = _scanner._passes_quality(stock, rule)
        lines.append(f"\n*{rule['name']}* ({rule['signal']})")
        lines.append(f"  Raw condition: ✅ matches")
        if passed:
            lines.append(f"  Gates: ✅ {reason}")
        else:
            lines.append(f"  Gates: ⛔ {reason}")
        if _db.already_signaled(symbol, cooldown_min=120):
            lines.append(f"  Note: per-stock cooldown active (signaled within last 2h)")

    if not any_match:
        lines.append("\nNo rule's raw condition currently matches for this symbol.")

    return "\n".join(lines)


_SCAN_CONDITIONS = {
    "20ema": "above20ema", "above20ema": "above20ema",
    "below20ema": "below20ema",
    "50sma": "above50sma", "above50sma": "above50sma",
    "below50sma": "below50sma",
    "rsi70": "rsi70", "overbought": "rsi70",
    "rsi30": "rsi30", "oversold": "rsi30",
    "breakout": "breakout",
    "highvolume": "highvolume",
    "bullish_htf": "bullish_htf",
    "bearish_htf": "bearish_htf",
}


def _scan_match(stock, cond):
    if cond == "above20ema":
        return stock["close"] > stock.get("ema20", 0), f"₹{stock['close']:,.2f} (EMA20: ₹{stock.get('ema20',0):,.2f})"
    if cond == "below20ema":
        return stock["close"] < stock.get("ema20", 0), f"₹{stock['close']:,.2f} (EMA20: ₹{stock.get('ema20',0):,.2f})"
    if cond == "above50sma":
        return stock["close"] > stock.get("sma50", 0), f"₹{stock['close']:,.2f} (SMA50: ₹{stock.get('sma50',0):,.2f})"
    if cond == "below50sma":
        return stock["close"] < stock.get("sma50", 0), f"₹{stock['close']:,.2f} (SMA50: ₹{stock.get('sma50',0):,.2f})"
    if cond == "rsi70":
        return stock["rsi"] > 70, f"RSI {stock['rsi']}"
    if cond == "rsi30":
        return stock["rsi"] < 30, f"RSI {stock['rsi']}"
    if cond == "breakout":
        res = stock.get("resistance", 0)
        return res and stock["close"] >= res * 0.995, f"₹{stock['close']:,.2f} (Resistance: ₹{res:,.2f})"
    if cond == "highvolume":
        avg = stock.get("avgVolume", 0)
        return avg and stock["volume"] > avg * 1.5, f"Vol {stock['volume']:,} (avg {avg:,})"
    if cond == "bullish_htf":
        return stock.get("htf_trend") == "bullish", "HTF bullish"
    if cond == "bearish_htf":
        return stock.get("htf_trend") == "bearish", "HTF bearish"
    return False, ""


def _cmd_scan(args):
    if not args:
        return ("Usage: `/scan CONDITION`\nConditions: " +
                ", ".join(sorted(set(_SCAN_CONDITIONS.keys()))))
    key = args[0].lower()
    cond = _SCAN_CONDITIONS.get(key)
    if not cond:
        return ("⚠️ Unknown condition.\nAvailable: " +
                ", ".join(sorted(set(_SCAN_CONDITIONS.keys()))))

    if _data.is_stale(max_minutes=2):
        try:
            _data.smart_refresh()
        except Exception as e:
            print(f"[telegram_bot] scan refresh error: {e}")

    stocks = _data.get_all()
    if not stocks:
        return "⚠️ No live data available right now."

    matches = []
    for stock in stocks:
        try:
            ok, detail = _scan_match(stock, cond)
        except Exception:
            ok, detail = False, ""
        if ok:
            matches.append((stock["symbol"], detail))

    refresh_time = _data._last_refresh.strftime("%H:%M") if _data._last_refresh else "—"
    if not matches:
        return f"🔎 *Scan: {key}* — no matches @ {refresh_time}"

    lines = [f"🔎 *Scan: {key}* — {len(matches)} match(es) @ {refresh_time}"]
    MAX = 30
    for sym, detail in matches[:MAX]:
        lines.append(f"  • {sym} — {detail}")
    if len(matches) > MAX:
        lines.append(f"  …and {len(matches) - MAX} more")
    return "\n".join(lines)


def _cmd_today(args):
    signals = _db.get_signals_today()
    if not signals:
        return "📋 No signals fired today yet."

    lines = [f"📋 *Today's signals ({len(signals)})*"]
    for s in signals[:30]:
        if s.get("target_hit"):
            status = "🎯 target hit"
        elif s.get("sl_hit"):
            status = "❌ SL hit"
        else:
            status = "⏳ open"
        lines.append(
            f"  {'🟢' if s['signal_type']=='BUY' else '🔴'} *{s['symbol']}* "
            f"[{s['signal_type']}] @₹{s['price']:,.2f} → T ₹{s['target']:,.2f} / SL ₹{s['sl']:,.2f} "
            f"— {status} — {s['time']}"
        )
    if len(signals) > 30:
        lines.append(f"  …and {len(signals)-30} more")
    return "\n".join(lines)


def _cmd_positions(args):
    positions = _db.get_open_positions()
    if not positions:
        return "📭 No open positions."

    stocks_by_sym = {s["symbol"]: s for s in _data.get_all()}
    lines = [f"💼 *Open positions ({len(positions)})*"]
    for pos in positions:
        stock = stocks_by_sym.get(pos["symbol"])
        entry = pos["price"]
        is_buy = pos["signal_type"] == "BUY"
        if stock:
            price = stock["close"]
            pnl = (price - entry) / entry * 100 if is_buy else (entry - price) / entry * 100
            pnl_str = f"{'+' if pnl>=0 else ''}{pnl:.2f}%"
            cur_str = f"₹{price:,.2f}"
        else:
            pnl_str, cur_str = "—", "—"
        sl = pos.get("trailing_sl") or pos["sl"]
        lines.append(
            f"  {'🟢' if is_buy else '🔴'} *{pos['symbol']}* [{pos['signal_type']}] "
            f"Entry ₹{entry:,.2f} → Now {cur_str}  P&L {pnl_str}\n"
            f"     Target ₹{pos['target']:,.2f}  SL ₹{sl:,.2f}"
            + ("  (trailing)" if pos.get("trailing_sl") else "")
        )
    return "\n".join(lines)


def _cmd_pnl(args):
    period = (args[0].lower() if args else "day")
    history = _db.get_signals_history(days=7 if period == "week" else 1)

    if period == "day":
        today = _ist_now().strftime("%Y-%m-%d")
        history = [s for s in history if s["date"] == today]
        label = "Today"
    else:
        label = "Last 7 days"

    if not history:
        return f"📊 *P&L — {label}*\nNo signals."

    total = len(history)
    hits  = sum(1 for s in history if s.get("target_hit"))
    stops = sum(1 for s in history if s.get("sl_hit"))
    closed = hits + stops
    win_rate = round(hits / closed * 100, 1) if closed else 0
    pnls = [s["pnl_pct"] for s in history if s.get("pnl_pct") is not None]
    total_pnl = round(sum(pnls), 2) if pnls else 0
    avg_pnl = round(total_pnl / len(pnls), 2) if pnls else 0

    return (
        f"📊 *P&L — {label}*\n"
        f"Total signals: {total}\n"
        f"🎯 Target hit: {hits}   ❌ SL hit: {stops}   ⏳ Open: {total-closed}\n"
        f"🏆 Win rate (closed): {win_rate}%\n"
        f"📈 Total P&L: {'+' if total_pnl>=0 else ''}{total_pnl}%   "
        f"Avg/trade: {'+' if avg_pnl>=0 else ''}{avg_pnl}%"
    )


def _cmd_pause(args):
    _scanner._paused = True
    return "⏸️ New signal generation *paused*. Trailing SL updates continue."


def _cmd_resume(args):
    _scanner._paused = False
    return "▶️ New signal generation *resumed*."


def _cmd_backtest(args):
    if not args:
        return "Usage: `/backtest SYMBOL`  e.g. `/backtest RELIANCE`"
    symbol = args[0].upper()

    def _run():
        try:
            import io, contextlib, backtest as _backtest
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                _backtest.run([symbol])
            out = buf.getvalue()
            idx = out.find("BACKTEST REPORT")
            report = out[idx:] if idx >= 0 else out
            if len(report) > 3500:
                report = report[:3500] + "\n…(truncated)"
            _reply(f"🧪 *Backtest — {symbol}*\n```\n{report}\n```")
        except Exception as e:
            _reply(f"⚠️ Backtest error for {symbol}: {e}")

    threading.Thread(target=_run, daemon=True, name=f"backtest-{symbol}").start()
    return f"⏳ Running backtest for {symbol}… results in ~10-30s."


def _cmd_watchlist(args):
    if not args:
        if not _watchlist:
            return "⭐ Watchlist is empty.\nAdd with `/watchlist add SYMBOL`"
        return "⭐ *Watchlist:*\n" + "\n".join(f"  • {s}" for s in _watchlist)

    action = args[0].lower()
    if action == "add" and len(args) > 1:
        symbol = args[1].upper()
        if symbol in _watchlist:
            return f"{symbol} already in watchlist."
        _watchlist.append(symbol)
        _save_json(WATCHLIST_FILE, _watchlist)
        return f"⭐ Added {symbol} to watchlist."

    if action == "remove" and len(args) > 1:
        symbol = args[1].upper()
        if symbol not in _watchlist:
            return f"{symbol} not in watchlist."
        _watchlist.remove(symbol)
        _save_json(WATCHLIST_FILE, _watchlist)
        return f"🗑️ Removed {symbol} from watchlist."

    return "Usage: `/watchlist`, `/watchlist add SYMBOL`, `/watchlist remove SYMBOL`"


def _cmd_alertme(args):
    if len(args) < 3:
        return "Usage: `/alertme SYMBOL above|below PRICE`  e.g. `/alertme INFY above 1600`"
    symbol = args[0].upper()
    direction = args[1].lower()
    if direction not in ("above", "below"):
        return "Direction must be `above` or `below`."
    try:
        price = float(args[2])
    except ValueError:
        return "Price must be a number."

    alert_id = (max((a["id"] for a in _alerts), default=0)) + 1
    _alerts.append({"id": alert_id, "symbol": symbol, "dir": direction, "price": price})
    _save_json(ALERTS_FILE, _alerts)
    return f"🔔 Alert set: {symbol} {direction} ₹{price:,.2f}"


def _cmd_alerts(args):
    if args and args[0].lower() == "clear":
        _alerts.clear()
        _save_json(ALERTS_FILE, _alerts)
        return "🗑️ All alerts cleared."

    if not _alerts:
        return "🔔 No active alerts."

    lines = ["🔔 *Active alerts:*"]
    for a in _alerts:
        lines.append(f"  • {a['symbol']} {a['dir']} ₹{a['price']:,.2f}")
    return "\n".join(lines)


# ───────────────────────── alert checker ───────────────────────────────────
def _check_alerts():
    if not _alerts:
        return
    stocks_by_sym = {s["symbol"]: s for s in _data.get_all()}
    triggered = []
    for a in _alerts:
        stock = stocks_by_sym.get(a["symbol"])
        if not stock:
            continue
        price = stock["close"]
        hit = (price >= a["price"]) if a["dir"] == "above" else (price <= a["price"])
        if hit:
            triggered.append(a)
            _reply(f"🔔 *Alert triggered!* {a['symbol']} {a['dir']} ₹{a['price']:,.2f} "
                   f"— now ₹{price:,.2f}")
    if triggered:
        for a in triggered:
            _alerts.remove(a)
        _save_json(ALERTS_FILE, _alerts)


# ───────────────────────── command dispatch ─────────────────────────────────
_COMMANDS = {
    "/help":      _cmd_help,
    "/start":     _cmd_help,
    "/status":    _cmd_status,
    "/vix":       _cmd_vix,
    "/signal":    _cmd_signal,
    "/explain":   _cmd_explain,
    "/scan":      _cmd_scan,
    "/signals":   _cmd_today,
    "/today":     _cmd_today,
    "/positions": _cmd_positions,
    "/pnl":       _cmd_pnl,
    "/pause":     _cmd_pause,
    "/resume":    _cmd_resume,
    "/backtest":  _cmd_backtest,
    "/watchlist": _cmd_watchlist,
    "/alertme":   _cmd_alertme,
    "/alerts":    _cmd_alerts,
}


def _handle_message(text):
    parts = text.strip().split()
    if not parts:
        return None
    cmd = parts[0].lower().split("@")[0]   # strip @botname
    args = parts[1:]
    handler = _COMMANDS.get(cmd)
    if not handler:
        return None
    try:
        return handler(args)
    except Exception as e:
        print(f"[telegram_bot] handler error ({cmd}): {e}")
        return f"⚠️ Error running {cmd}: {e}"


# ───────────────────────── main loop ────────────────────────────────────────
def _loop():
    global _offset
    cfg = _cfg()
    token = cfg["token"]
    chat_id = str(cfg["chat_id"])
    if not token or not chat_id:
        print("[telegram_bot] Missing TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID — bot disabled")
        return

    _load_state()
    print("[telegram_bot] started — long polling")

    last_alert_check = 0
    while True:
        try:
            updates = _get_updates(token, timeout=30)
            for upd in updates:
                _offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                text = msg.get("text", "")
                from_chat = str(msg.get("chat", {}).get("id", ""))
                if from_chat != chat_id:
                    print(f"[telegram_bot] ignoring message from unauthorized chat {from_chat}")
                    continue
                if not text.startswith("/"):
                    continue
                print(f"[telegram_bot] cmd: {text}")
                reply = _handle_message(text)
                if reply:
                    _reply(reply)

            now = time.time()
            if now - last_alert_check > 30:
                try:
                    _check_alerts()
                except Exception as e:
                    print(f"[telegram_bot] alert check error: {e}")
                last_alert_check = now

        except Exception as e:
            print(f"[telegram_bot] loop error: {e}")
            time.sleep(5)


def start():
    t = threading.Thread(target=_loop, daemon=True, name="telegram_bot")
    t.start()
    print("[telegram_bot] Started")
