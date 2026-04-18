"""
Control Room — SQLite persistence layer for the collector daemon.

Schema:
  readings(key, metric, ts, value)    — one row per metric per poll
  device_state(key, health, message, ts) — latest per-device state (fast snapshot)
  baselines(key, metric, p50, p95, sample_count, updated_at, is_manual)
"""

import sqlite3
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    key    TEXT    NOT NULL,
    metric TEXT    NOT NULL,
    ts     INTEGER NOT NULL,
    value  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rdg ON readings(key, metric, ts);

CREATE TABLE IF NOT EXISTS device_state (
    key     TEXT PRIMARY KEY,
    health  TEXT    NOT NULL DEFAULT 'unknown',
    message TEXT    NOT NULL DEFAULT '',
    ts      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS baselines (
    key          TEXT    NOT NULL,
    metric       TEXT    NOT NULL,
    p50          REAL,
    p95          REAL,
    sample_count INTEGER,
    updated_at   INTEGER,
    is_manual    INTEGER DEFAULT 0,
    PRIMARY KEY (key, metric)
);
"""


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    return conn


def write_poll(conn: sqlite3.Connection, key: str,
               health: str, message: str, metrics: dict):
    now = int(time.time())
    conn.execute(
        "INSERT OR REPLACE INTO device_state (key, health, message, ts) VALUES (?,?,?,?)",
        (key, health, message, now),
    )
    if metrics:
        conn.executemany(
            "INSERT INTO readings (key, metric, ts, value) VALUES (?,?,?,?)",
            [(key, m, now, float(v)) for m, v in metrics.items()],
        )
    conn.commit()


def get_snapshot(conn: sqlite3.Connection) -> dict:
    """
    Returns {key: {health, message, ts, metrics, baselines}} for all devices.
    Used by /snapshot endpoint and client cold-start.
    """
    result = {}

    for row in conn.execute(
        "SELECT key, health, message, ts FROM device_state"
    ):
        result[row[0]] = {
            "health":    row[1],
            "message":   row[2],
            "ts":        row[3],
            "metrics":   {},
            "baselines": {},
        }

    # Latest value per (key, metric)
    for row in conn.execute(
        "SELECT r.key, r.metric, r.value "
        "FROM readings r "
        "INNER JOIN ("
        "  SELECT key, metric, MAX(ts) AS mts "
        "  FROM readings GROUP BY key, metric"
        ") latest "
        "ON r.key=latest.key AND r.metric=latest.metric AND r.ts=latest.mts"
    ):
        if row[0] in result:
            result[row[0]]["metrics"][row[1]] = row[2]

    for row in conn.execute(
        "SELECT key, metric, p50, p95 FROM baselines"
    ):
        if row[0] in result:
            result[row[0]]["baselines"][row[1]] = {"p50": row[2], "p95": row[3]}

    return result


def compute_baselines(conn: sqlite3.Connection, days: int = 30):
    """Recompute p50/p95 for every (key, metric) from the last N days of readings."""
    cutoff = int(time.time()) - days * 86400
    rows = conn.execute(
        "SELECT key, metric, value FROM readings "
        "WHERE ts > ? ORDER BY key, metric, value",
        (cutoff,),
    ).fetchall()

    from itertools import groupby
    now = int(time.time())
    for (key, metric), group in groupby(rows, key=lambda r: (r[0], r[1])):
        values = sorted(r[2] for r in group)
        n = len(values)
        if n == 0:
            continue
        p50 = values[n // 2]
        p95 = values[min(int(n * 0.95), n - 1)]
        conn.execute(
            "INSERT OR REPLACE INTO baselines "
            "(key, metric, p50, p95, sample_count, updated_at, is_manual) "
            "VALUES (?,?,?,?,?,?,0)",
            (key, metric, p50, p95, n, now),
        )
    conn.commit()


def set_manual_baseline(conn: sqlite3.Connection):
    """Snapshot current readings as a pinned manual baseline (p50=p95=current value)."""
    now  = int(time.time())
    rows = conn.execute(
        "SELECT r.key, r.metric, r.value "
        "FROM readings r "
        "INNER JOIN ("
        "  SELECT key, metric, MAX(ts) AS mts "
        "  FROM readings GROUP BY key, metric"
        ") latest "
        "ON r.key=latest.key AND r.metric=latest.metric AND r.ts=latest.mts"
    ).fetchall()
    for key, metric, value in rows:
        conn.execute(
            "INSERT OR REPLACE INTO baselines "
            "(key, metric, p50, p95, sample_count, updated_at, is_manual) "
            "VALUES (?,?,?,?,?,?,1)",
            (key, metric, value, value, 1, now),
        )
    conn.commit()


def prune(conn: sqlite3.Connection, keep_days: int = 90):
    cutoff = int(time.time()) - keep_days * 86400
    conn.execute("DELETE FROM readings WHERE ts < ?", (cutoff,))
    conn.commit()
