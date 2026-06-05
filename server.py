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


@app.route("/webhook/tradingview", methods=["POST"])
def tradingview_webhook():
    """
    Receives real-time alerts directly from TradingView Pine Script.
    TradingView POSTs the alert message as JSON body.

    Expected message format (set this in TradingView alert message box):
    {
      "symbol":   "{{ticker}}",
      "signal":   "BUY",
      "price":    {{close}},
      "high":     {{high}},
      "low":      {{low}},
      "volume":   {{volume}},
      "scan":     "Swing BUY — EMA5 x SMA50",
      "tf":       "{{interval}}",
      "time":     "{{timenow}}"
    }
    """
    import data as _data
    import notify as _notify

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload = request.get_json(force=True, silent=True) or {}
        if not payload:
            raw = request.data.decode("utf-8", errors="ignore").strip()
            import json
            payload = json.loads(raw)
    except Exception as e:
        print(f"[webhook] Parse error: {e} | raw: {request.data[:200]}")
        return jsonify({"ok": False, "error": "bad payload"}), 400

    symbol      = str(payload.get("symbol", "")).upper().replace(".NS", "").replace("NSE:", "")
    signal_type = str(payload.get("signal", "BUY")).upper()
    scan_name   = str(payload.get("scan",   "TradingView Signal"))
    tf          = str(payload.get("tf",     "5m"))

    try:
        price = float(payload.get("price", 0))
    except Exception:
        price = 0.0

    if not symbol or price <= 0:
        return jsonify({"ok": False, "error": "missing symbol or price"}), 400

    # ── Targets ───────────────────────────────────────────────────────────────
    is_swing = True   # TradingView signals treated as swing calls
    target, sl = scanner._calc_targets(price, signal_type, is_swing=is_swing)

    # ── Find stock meta (name / sector) from universe ─────────────────────────
    meta = next((s for s in _data.UNIVERSE if s["symbol"] == symbol), None)
    name   = meta["name"]   if meta else symbol
    sector = meta["sector"] if meta else "—"

    # ── Save to DB ────────────────────────────────────────────────────────────
    sig_id = db.insert_signal(
        symbol      = symbol,
        name        = name,
        sector      = sector,
        signal_type = signal_type,
        scan_name   = f"📡 {scan_name}",
        price       = price,
        target      = target,
        sl          = sl,
    )

    # ── Send Telegram immediately ─────────────────────────────────────────────
    sig = dict(
        id          = sig_id,
        symbol      = symbol,
        name        = name,
        sector      = sector,
        signal_type = signal_type,
        scan_name   = f"📡 {scan_name}",
        scan_key    = "tradingview",
        price       = price,
        target      = target,
        sl          = sl,
        time        = datetime.now(_IST).strftime("%H:%M"),
        swing_trend = "",
    )
    _notify.send_signal(sig)

    print(f"[webhook] 📡 LIVE {signal_type} {symbol} @{price} via TradingView")
    return jsonify({"ok": True, "symbol": symbol, "signal": signal_type, "id": sig_id})


@app.route("/webhook/test", methods=["POST"])
def webhook_test():
    """Send a fake TradingView webhook to verify the pipeline works."""
    import notify as _notify
    import data as _data

    test_payload = {
        "symbol": "RELIANCE",
        "signal": "BUY",
        "price": 2937.50,
        "high": 2950.00,
        "low": 2920.00,
        "volume": 8200000,
        "scan": "Swing BUY — EMA5 x SMA50 [LIVE TEST]",
        "tf": "5m",
        "time": datetime.now(_IST).strftime("%Y-%m-%d %H:%M"),
    }

    # Reuse the main webhook handler logic
    with app.test_request_context(
        "/webhook/tradingview",
        method="POST",
        json=test_payload,
        content_type="application/json",
    ):
        from flask import request as _req
        import json
        payload  = test_payload
        symbol   = payload["symbol"]
        signal_type = payload["signal"]
        price    = float(payload["price"])
        scan_name = payload["scan"]
        meta     = next((s for s in _data.UNIVERSE if s["symbol"] == symbol), None)
        name     = meta["name"]   if meta else symbol
        sector   = meta["sector"] if meta else "—"
        target, sl = scanner._calc_targets(price, signal_type, is_swing=True)
        sig_id   = db.insert_signal(symbol, name, sector, signal_type, f"📡 {scan_name}", price, target, sl)
        sig      = dict(id=sig_id, symbol=symbol, name=name, sector=sector,
                        signal_type=signal_type, scan_name=f"📡 {scan_name}",
                        scan_key="tradingview", price=price, target=target, sl=sl,
                        time=datetime.now(_IST).strftime("%H:%M"), swing_trend="")
        _notify.send_signal(sig)

    print("[webhook] ✅ Test webhook fired")
    return jsonify({"ok": True, "msg": "Test signal sent to Telegram", "payload": test_payload})


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
        _data.smart_refresh()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    stocks  = _data.get_all()
    results = []

    # 2 — group all matching scans per stock → ONE alert per stock (same as live scanner)
    matches_by_stock = {}
    for rule in scanner.ACTIVE_RULES:
        for stock in stocks:
            try:
                matched = rule["cond"](stock)
            except Exception:
                matched = False
            if matched:
                matches_by_stock.setdefault(stock["symbol"], {"stock": stock, "rules": []})["rules"].append(rule)

    for symbol, item in matches_by_stock.items():
        stock = item["stock"]
        rules = item["rules"]

        # Sort by priority, pick primary
        def rule_priority(r):
            if r["key"] in scanner.PINE_KEYS: return 0
            if "breakout" in r["key"]:        return 1
            if r["signal"] == "BUY":          return 2
            return 3
        rules.sort(key=rule_priority)
        primary = rules[0]

        price    = stock["close"]
        is_swing = primary["key"] in scanner.PINE_KEYS
        target, sl = scanner._calc_targets(price, primary["signal"], is_swing=is_swing)

        labels = [r["name"] for r in rules[:3]]
        if len(rules) > 3:
            labels.append(f"+{len(rules)-3} more")
        scan_name = "[TEST] " + " · ".join(labels)

        sig_id = db.insert_signal(
            symbol=symbol, name=stock["name"], sector=stock["sector"],
            signal_type=primary["signal"], scan_name=scan_name,
            price=price, target=target, sl=sl,
        )
        sig = dict(
            id=sig_id, symbol=symbol, name=stock["name"], sector=stock["sector"],
            signal_type=primary["signal"], scan_name=scan_name,
            scan_key=primary["key"], price=price, target=target, sl=sl,
            time=datetime.now(_IST).strftime("%H:%M"),
            swing_trend=stock.get("swing_trend", ""),
            match_count=len(rules),
        )
        _notify.send_signal(sig)
        results.append(sig)
        print(f"[test-scan] {primary['signal']} {symbol} ({len(rules)} matches)")

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
