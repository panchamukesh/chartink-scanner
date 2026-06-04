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
