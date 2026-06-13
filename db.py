"""Signal storage — SQLite database."""
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "signals.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                time        TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                name        TEXT,
                sector      TEXT,
                signal_type TEXT NOT NULL,
                scan_name   TEXT,
                price       REAL,
                target      REAL,
                sl          REAL,
                target_hit  INTEGER DEFAULT 0,
                sl_hit      INTEGER DEFAULT 0,
                eod_price   REAL,
                pnl_pct     REAL,
                trailing_sl REAL,
                closed      INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            )
        """)
        # Add columns for DBs created before this migration
        cols = {row["name"] for row in c.execute("PRAGMA table_info(signals)").fetchall()}
        if "trailing_sl" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN trailing_sl REAL")
        if "closed" not in cols:
            c.execute("ALTER TABLE signals ADD COLUMN closed INTEGER DEFAULT 0")
        c.commit()


def count_today() -> int:
    """Total signals fired today (for daily cap check)."""
    date = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM signals WHERE date=?", (date,)
        ).fetchone()[0]


def already_signaled(symbol, scan_name=None, cooldown_min=120):
    """
    Per-STOCK cooldown (not per scan).
    If this stock fired ANY signal in the last cooldown_min minutes → skip.
    This prevents the same stock appearing in 8 different scan alerts at once.
    scan_name param kept for backward compat but ignored.
    """
    cutoff = (datetime.now() - timedelta(minutes=cooldown_min)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        row = c.execute(
            "SELECT id FROM signals WHERE symbol=? AND created_at > ?",
            (symbol, cutoff),
        ).fetchone()
    return row is not None


def insert_signal(symbol, name, sector, signal_type, scan_name, price, target, sl):
    now = datetime.now()
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO signals
               (date, time, symbol, name, sector, signal_type, scan_name, price, target, sl)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M"),
                symbol, name, sector, signal_type, scan_name,
                round(price, 2),
                round(target, 2),
                round(sl, 2),
            ),
        )
        c.commit()
        return cur.lastrowid


def get_signals_today():
    date = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM signals WHERE date=? ORDER BY time ASC", (date,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_signals_history(days=30):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM signals WHERE date>=? ORDER BY created_at DESC", (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def update_eod(symbol, eod_price):
    """Update EOD price + target/SL hit status for today's open signals of a symbol."""
    date = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT id, signal_type, price, target, sl FROM signals WHERE date=? AND symbol=? AND eod_price IS NULL",
            (date, symbol),
        ).fetchall()
        for row in rows:
            sig_type = row["signal_type"]
            entry = row["price"]
            tgt = row["target"]
            stop = row["sl"]
            pnl = round((eod_price - entry) / entry * 100, 2) if entry else 0
            if sig_type == "BUY":
                t_hit = 1 if eod_price >= tgt else 0
                s_hit = 1 if eod_price <= stop else 0
            else:
                t_hit = 1 if eod_price <= tgt else 0
                s_hit = 1 if eod_price >= stop else 0
            c.execute(
                "UPDATE signals SET eod_price=?, pnl_pct=?, target_hit=?, sl_hit=? WHERE id=?",
                (round(eod_price, 2), pnl, t_hit, s_hit, row["id"]),
            )
        c.commit()


def get_open_positions():
    """All today's signals not yet closed (target/SL not hit) — for trailing-SL updates."""
    date = datetime.now().strftime("%Y-%m-%d")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM signals WHERE date=? AND closed=0 AND target_hit=0 AND sl_hit=0",
            (date,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_position(sig_id, sl=None, trailing_sl=None, target_hit=None, sl_hit=None, closed=None):
    """Update SL / trailing-SL / closed status for an open position (live intraday tracking)."""
    fields, vals = [], []
    if sl is not None:
        fields.append("sl=?");          vals.append(round(sl, 2))
    if trailing_sl is not None:
        fields.append("trailing_sl=?"); vals.append(round(trailing_sl, 2))
    if target_hit is not None:
        fields.append("target_hit=?");  vals.append(int(target_hit))
    if sl_hit is not None:
        fields.append("sl_hit=?");      vals.append(int(sl_hit))
    if closed is not None:
        fields.append("closed=?");      vals.append(int(closed))
    if not fields:
        return
    vals.append(sig_id)
    with _conn() as c:
        c.execute(f"UPDATE signals SET {', '.join(fields)} WHERE id=?", vals)
        c.commit()


def recent_signals_by_sector(sector, minutes=30):
    """Signals fired for any stock in this sector within the last N minutes (for correlation gate)."""
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM signals WHERE sector=? AND created_at > ?",
            (sector, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]
