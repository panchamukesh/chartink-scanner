"""
MarketScan Pro — Flask server.
Serves the frontend, exposes /api/* for signals history,
and starts the background auto-scanner on launch.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, send_from_directory, request
from dotenv import load_dotenv

load_dotenv()

import db
import scanner

app = Flask(__name__, static_folder=".", static_url_path="")

_IST = timezone(timedelta(hours=5, minutes=30))


# ─── Static frontend ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ─── API: signals ─────────────────────────────────────────────────────────────
@app.route("/api/signals/today")
def signals_today():
    return jsonify(db.get_signals_today())


@app.route("/api/signals/history")
def signals_history():
    days = int(request.args.get("days", 30))
    return jsonify(db.get_signals_history(days=days))


@app.route("/api/signals/summary")
def signals_summary():
    signals = db.get_signals_today()
    total   = len(signals)
    hits    = sum(1 for s in signals if s.get("target_hit"))
    stops   = sum(1 for s in signals if s.get("sl_hit"))
    pnls    = [s["pnl_pct"] for s in signals if s.get("pnl_pct") is not None]
    return jsonify({
        "date":     datetime.now(_IST).strftime("%Y-%m-%d"),
        "total":    total,
        "hits":     hits,
        "sl_hits":  stops,
        "open":     total - hits - stops,
        "win_rate": round(hits / total * 100) if total else 0,
        "avg_pnl":  round(sum(pnls) / len(pnls), 2) if pnls else 0,
    })


@app.route("/api/eod/trigger", methods=["POST"])
def trigger_eod():
    """Manual EOD trigger (for testing outside market hours)."""
    import threading
    threading.Thread(target=scanner._eod_report, daemon=True).start()
    return jsonify({"ok": True, "msg": "EOD report triggered"})


@app.route("/api/scan/test", methods=["POST"])
def test_scan():
    """
    Force a scan right now regardless of market hours.
    Fetches fresh 5m data, runs all rules, sends matching signals
    to Telegram with [TEST] prefix.  Returns results as JSON.
    """
    import data as _data
    import notify as _notify

    # 1 — fetch live 5m data
    print("[test-scan] Fetching 5m bars …")
    try:
        _data.refresh_5m()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    stocks  = _data.get_all()
    results = []

    # 2 — evaluate every rule against every stock (no cooldown check)
    for rule in scanner.ACTIVE_RULES:
        for stock in stocks:
            try:
                matched = rule["cond"](stock)
            except Exception:
                matched = False
            if not matched:
                continue

            price    = stock["close"]
            is_swing = rule["key"] in scanner.PINE_KEYS
            target, sl = scanner._calc_targets(price, rule["signal"], is_swing=is_swing)

            # Save to DB so EOD report can track it
            sig_id = db.insert_signal(
                symbol      = stock["symbol"],
                name        = stock["name"],
                sector      = stock["sector"],
                signal_type = rule["signal"],
                scan_name   = f"[TEST] {rule['name']}",
                price       = price,
                target      = target,
                sl          = sl,
            )
            sig = dict(
                id          = sig_id,
                symbol      = stock["symbol"],
                name        = stock["name"],
                sector      = stock["sector"],
                signal_type = rule["signal"],
                scan_name   = f"[TEST] {rule['name']}",
                scan_key    = rule["key"],
                price       = price,
                target      = target,
                sl          = sl,
                time        = datetime.now(_IST).strftime("%H:%M"),
                swing_trend = stock.get("swing_trend", ""),
            )
            _notify.send_signal(sig)
            results.append(sig)
            print(f"[test-scan] {rule['signal']} {stock['symbol']} via {rule['name']}")

    # 3 — if nothing matched, still send an info message
    if not results:
        _notify._send(
            "🧪 *MarketScan Pro — Test Scan*\n"
            f"Scanned *{len(stocks)}* stocks on 5-min bars.\n"
            "No stocks matched any scan condition right now.\n"
            "_(Normal outside market hours — data may be from last session)_"
        )

    return jsonify({
        "ok":      True,
        "stocks":  len(stocks),
        "signals": len(results),
        "matches": [{"symbol": r["symbol"], "signal": r["signal_type"], "scan": r["scan_name"]} for r in results],
    })


@app.route("/api/status")
def status():
    import data as _data
    return jsonify({
        "market_open":   scanner._is_market_open(),
        "ist_time":      datetime.now(_IST).strftime("%H:%M:%S"),
        "cache_symbols": len(_data.get_all()),
        "last_refresh":  _data._last_refresh.strftime("%H:%M:%S") if _data._last_refresh else None,
    })


# ─── Start ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5002))
    db.init_db()
    scanner.start()
    print(f"[server] MarketScan Pro → http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
