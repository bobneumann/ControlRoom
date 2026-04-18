"""
Control Room — WebSocket Registry

Drop-in replacement for the local host_registry when connecting to a daemon.

On connect():
  1. Reads hosts.json locally — registers device sources into SOURCE_REGISTRY
     so gauges and ops-board know what metrics exist.
  2. Creates _RemoteHost stubs that implement the same public interface as
     CollectorHost (health, status, message, get(), source()).
  3. Replaces host_registry._active with those stubs.
  4. Seeds state from daemon GET /snapshot (instant; no "connecting" wait).
  5. Starts a background WebSocket listener that keeps stubs current.

All existing code that calls host_registry.get_host_health() / get_host_status()
continues to work without modification.
"""

import json
import time
import asyncio
import threading
import logging
import urllib.request
from typing import Optional

import host_registry

log = logging.getLogger(__name__)

# ── module state ──────────────────────────────────────────────────────────── #

_daemon_url: str  = ""
_stubs:      dict = {}   # {key: _RemoteHost}
_baselines:  dict = {}   # {key: {metric: {p50, p95}}}


# ── remote host stub ─────────────────────────────────────────────────────── #

class _RemoteHost:
    """
    Mirrors the public interface of CollectorHost.
    host_registry._register() and get_host_health/status() all work against it.
    """

    def __init__(self, key: str, label: str):
        self.key     = key
        self.label   = label
        self.health  = "unknown"
        self.message = ""
        self.status  = "disconnected"
        self._metrics: dict = {}
        self._lock   = threading.Lock()

    def get(self, key: str, default: float = 0.0) -> float:
        with self._lock:
            v = self._metrics.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def source(self, key: str):
        return lambda: self.get(key)

    @property
    def metrics(self) -> dict:
        with self._lock:
            return dict(self._metrics)

    def update(self, health: str, message: str, metrics: dict):
        with self._lock:
            self.health   = health
            self.message  = message
            self._metrics = metrics
        self.status = (
            "connecting" if health == "connecting" else
            "connected"  if health in ("good", "warning") else
            "error"
        )


# ── public API ────────────────────────────────────────────────────────────── #

def connect(daemon_url: str, hosts_path: str, source_registry: dict):
    """
    Wire up the ws_registry.  Call this instead of host_registry.load().
    daemon_url example: "http://192.168.1.10:8765"
    """
    global _daemon_url
    _daemon_url = daemon_url.rstrip("/")

    try:
        with open(hosts_path) as f:
            configs = json.load(f)
    except Exception as exc:
        log.error("ws_registry: cannot read %s: %s", hosts_path, exc)
        configs = []

    for cfg in configs:
        if cfg.get("_comment"):
            continue
        key  = cfg.get("key", "?")
        stub = _RemoteHost(key, cfg.get("label", key))
        _stubs[key] = stub
        try:
            host_registry._register(stub, cfg, source_registry)
        except Exception as exc:
            log.warning("ws_registry: source registration failed for %s: %s", key, exc)

    host_registry._active = list(_stubs.values())

    _fetch_snapshot()

    threading.Thread(target=_ws_thread, daemon=True, name="ws-registry").start()
    log.info("ws_registry: connected to %s (%d devices)", _daemon_url, len(_stubs))


def get_baseline(key: str, metric: str) -> dict:
    """Return {p50, p95} for a device metric, or {} if not yet computed."""
    return _baselines.get(key, {}).get(metric, {})


# ── internals ─────────────────────────────────────────────────────────────── #

def _fetch_snapshot():
    try:
        req  = urllib.request.urlopen(f"{_daemon_url}/snapshot", timeout=5)
        data = json.loads(req.read())
        _apply_snapshot(data)
        log.info("ws_registry: snapshot seeded (%d devices)", len(data))
    except Exception as exc:
        log.warning("ws_registry: snapshot fetch failed — %s", exc)


def _apply_snapshot(data: dict):
    for key, info in data.items():
        if key in _stubs:
            _stubs[key].update(
                info.get("health",  "unknown"),
                info.get("message", ""),
                info.get("metrics", {}),
            )
        _baselines[key] = info.get("baselines", {})


def _ws_thread():
    asyncio.run(_ws_listen())


async def _ws_listen():
    try:
        import websockets
    except ImportError:
        log.error("ws_registry: 'websockets' package not installed — live updates disabled")
        return

    ws_url = (
        _daemon_url
        .replace("http://", "ws://")
        .replace("https://", "wss://")
        + "/live"
    )

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                log.info("ws_registry: live feed active")
                async for raw in ws:
                    msg = json.loads(raw)
                    key = msg.get("key")
                    if key and key in _stubs:
                        _stubs[key].update(
                            msg.get("health",  "unknown"),
                            msg.get("message", ""),
                            msg.get("metrics", {}),
                        )
                        if "baselines" in msg:
                            _baselines[key] = msg["baselines"]
        except Exception as exc:
            log.warning("ws_registry: feed lost (%s) — reconnecting in 5s", exc)
            await asyncio.sleep(5)
