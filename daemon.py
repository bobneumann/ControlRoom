"""
Control Room — Collector Daemon

Runs all CollectorHost threads (same collectors as the desktop app),
persists every poll to SQLite, and serves live data over HTTP/WebSocket.

Endpoints:
  GET  /snapshot          — full current state + baselines (for client cold-start)
  WS   /live              — push stream: {key, health, message, metrics, baselines}
  POST /baseline/compute  — recompute p50/p95 from last 30 days of history
  POST /baseline/set      — pin current readings as manual baseline

Usage:
  python daemon.py [--hosts hosts.json] [--db controlroom.db] [--port 8765]
"""

import os
import sys
import json
import time
import asyncio
import logging
import argparse
import threading

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

import host_registry
import daemon_db as db

log = logging.getLogger(__name__)

app = FastAPI()

# ── shared state ──────────────────────────────────────────────────────────── #

_db_conn  = None
_clients: set             = set()
_bcast_q: asyncio.Queue   = None   # set on startup
_state:   dict            = {}     # {key: {health, message, metrics}} — hot cache


# ── poll loop (sync thread → async broadcast) ─────────────────────────────── #

def _poll_loop(queue, loop):
    """
    Samples host_registry._active every second.  On any change, writes to DB
    and enqueues a broadcast message for connected WebSocket clients.
    """
    prev = {}
    while True:
        for h in host_registry._active:
            key    = h.key
            health = h.health if h.status != "connecting" else "connecting"
            msg    = h.message
            with h._lock:
                metrics = dict(h._metrics)

            snap = {"health": health, "message": msg, "metrics": metrics}
            if snap != prev.get(key):
                prev[key]   = snap
                _state[key] = snap
                db.write_poll(_db_conn, key, health, msg, metrics)
                # Attach current baselines so clients receive them inline
                baselines = _get_baselines(key)
                asyncio.run_coroutine_threadsafe(
                    queue.put({"key": key, **snap, "baselines": baselines}),
                    loop,
                )
        time.sleep(1)


def _get_baselines(key: str) -> dict:
    snap = db.get_snapshot(_db_conn)
    return snap.get(key, {}).get("baselines", {})


async def _broadcaster():
    while True:
        msg  = await _bcast_q.get()
        dead = set()
        for ws in list(_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        _clients.difference_update(dead)


# ── lifecycle ─────────────────────────────────────────────────────────────── #

@app.on_event("startup")
async def _startup():
    global _bcast_q
    _bcast_q = asyncio.Queue()
    loop = asyncio.get_event_loop()

    # Seed hot cache from DB (so /snapshot works immediately even before first poll)
    for key, data in db.get_snapshot(_db_conn).items():
        _state[key] = {k: data[k] for k in ("health", "message", "metrics")}

    threading.Thread(
        target=_poll_loop, args=(_bcast_q, loop),
        daemon=True, name="poll-loop",
    ).start()
    asyncio.create_task(_broadcaster())
    asyncio.create_task(_daily_maintenance())


async def _daily_maintenance():
    while True:
        await asyncio.sleep(86400)
        db.prune(_db_conn)
        db.compute_baselines(_db_conn)
        log.info("Daily maintenance complete (prune + baseline recompute)")


# ── endpoints ─────────────────────────────────────────────────────────────── #

@app.get("/snapshot")
async def snapshot():
    """Full state for all devices including latest metrics and baselines."""
    return db.get_snapshot(_db_conn)


@app.websocket("/live")
async def live(ws: WebSocket):
    await ws.accept()
    _clients.add(ws)
    # Push current state immediately so the new client isn't blank
    for key, data in _state.items():
        baselines = _get_baselines(key)
        try:
            await ws.send_json({"key": key, **data, "baselines": baselines})
        except Exception:
            break
    try:
        while True:
            await ws.receive_text()   # keep-alive; client may send pings
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)


@app.post("/baseline/compute")
async def baseline_compute():
    """Recompute rolling p50/p95 baselines from last 30 days of readings."""
    db.compute_baselines(_db_conn)
    return {"status": "ok", "message": "Baselines recomputed from 30-day history"}


@app.post("/baseline/set")
async def baseline_set():
    """Pin current readings as a manual baseline."""
    db.set_manual_baseline(_db_conn)
    return {"status": "ok", "message": "Manual baseline saved"}


# ── entry point ───────────────────────────────────────────────────────────── #

def _default_path(filename: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s  %(name)s  %(message)s")

    parser = argparse.ArgumentParser(description="Control Room Collector Daemon")
    parser.add_argument("--hosts", default=_default_path("hosts.json"), metavar="PATH",
                        help="Path to hosts.json")
    parser.add_argument("--db",    default=_default_path("controlroom.db"), metavar="PATH",
                        help="Path to SQLite database file")
    parser.add_argument("--port",  type=int, default=8765,
                        help="HTTP/WebSocket port (default 8765)")
    args = parser.parse_args()

    _db_conn = db.open_db(args.db)

    # Load collectors — pass empty source registry (daemon doesn't need gauge metadata)
    host_registry.load(args.hosts, {})

    import atexit
    atexit.register(host_registry.stop_all)
    atexit.register(_db_conn.close)

    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
