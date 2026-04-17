"""
CollectorHost — generic background polling thread for any collector plugin.

Each device in hosts.json gets one CollectorHost.  The plugin's poll() function
is called every poll_interval seconds; it receives the device config and a
persistent state dict (for SSH clients, HTTP sessions, rate counters, etc.).

Public interface:
  host.health   → "good" | "warning" | "error" | "unknown"
  host.message  → human-readable status string
  host.status   → "connected" | "connecting" | "error" | "disconnected"
  host.get(key) → float metric value
  host.source(key) → zero-arg callable that returns float (for gauge factories)
"""

import threading
import logging
from typing import Callable

log = logging.getLogger(__name__)


class CollectorHost:
    def __init__(self, config: dict, poll_fn: Callable):
        self.key     = config["key"]
        self.label   = config.get("label", self.key)
        self.health  = "unknown"
        self.message = ""
        self.status  = "disconnected"

        self._config        = config
        self._poll_fn       = poll_fn
        self._state: dict   = {}
        self._metrics: dict = {}
        self._lock          = threading.Lock()
        self._stop          = threading.Event()
        self._thread        = None
        self._poll_interval = float(config.get("poll_interval", 30))

    # ── public API ────────────────────────────────────────────────────────── #

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"collector-{self.key}"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def get(self, key: str, default: float = 0.0) -> float:
        with self._lock:
            v = self._metrics.get(key, default)
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    def source(self, key: str) -> Callable[[], float]:
        """Return a zero-arg callable that reads one metric from the cache."""
        return lambda: self.get(key)

    # ── internals ────────────────────────────────────────────────────────── #

    def _loop(self):
        self.status = "connecting"
        while not self._stop.is_set():
            try:
                result, self._state = self._poll_fn(self._config, self._state)
                h = result.get("health", "unknown")
                with self._lock:
                    self.health  = h
                    self.message = result.get("message", "")
                    raw = result.get("metrics", {})
                    self._metrics = {
                        k: float(v) for k, v in raw.items()
                        if v is not None
                    }
                self.status = "connected" if h in ("good", "warning") else "error"
            except Exception as exc:
                self.health  = "error"
                self.message = str(exc)
                self.status  = "error"
                log.warning("Collector %s error: %s", self.key, exc)

            self._stop.wait(self._poll_interval)

        self.status = "disconnected"
