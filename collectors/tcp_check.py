"""
TCP port connectivity check.

config.collector fields:
  host     Hostname or IP
  port     TCP port to probe
  timeout  Seconds before giving up (default 5)
"""

import socket
import time


def poll(config: dict, state: dict) -> tuple[dict, dict]:
    c = config["collector"]
    host    = c["host"]
    port    = int(c["port"])
    timeout = float(c.get("timeout", 5))

    t0 = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        latency_ms = (time.monotonic() - t0) * 1000
        return {
            "health":  "good",
            "message": f"Port {port} open ({latency_ms:.0f} ms)",
            "metrics": {"up": 1.0, "latency_ms": latency_ms},
        }, state
    except Exception as exc:
        return {
            "health":  "error",
            "message": f"Port {port} unreachable: {exc}",
            "metrics": {"up": 0.0, "latency_ms": 0.0},
        }, state
