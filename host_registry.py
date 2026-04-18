"""
Host registry — loads hosts.json, starts CollectorHost instances, and injects
their metric sources into the designer's SOURCE_REGISTRY.

hosts.json is the single place to define every monitored device.  Each entry
specifies the device key, label, collector type, polling interval, and all
type-specific connection/health/metric settings.  See hosts.json.example.

After load(), SOURCE_REGISTRY gains entries keyed as "{device_key}:{metric}":

  SSH device "epic_prod":
    epic_prod:cpu, epic_prod:ram, epic_prod:disk,
    epic_prod:net_in, epic_prod:net_out, epic_prod:ctx_rate, epic_prod:load1,
    epic_prod:core_0 … epic_prod:core_7, epic_prod:health

  SNMP device "main_switch" with oids {uptime, cpu_pct}:
    main_switch:uptime, main_switch:cpu_pct, main_switch:health

  HTTP/TCP device "camera_front":
    camera_front:up, camera_front:http_status (or latency_ms), camera_front:health

Gauge label/unit/range overrides come from the optional "gauges" array in each
device config entry.
"""

import os
import json
import logging

log = logging.getLogger(__name__)

_active: list = []


# ── public API ──────────────────────────────────────────────────────────── #

def load(hosts_path: str, source_registry: dict) -> list:
    """
    Read hosts.json, create and start CollectorHost instances, inject sources.
    Returns the list of hosts (keep a reference; call stop_all() on shutdown).
    """
    global _active

    if not os.path.exists(hosts_path):
        return []

    try:
        with open(hosts_path) as f:
            configs = json.load(f)
    except Exception as exc:
        log.error("Cannot read %s: %s", hosts_path, exc)
        return []

    from collector_host import CollectorHost

    hosts = []
    for cfg in configs:
        if cfg.get("_comment"):
            continue
        key = cfg.get("key", "?")
        try:
            poll_fn = _get_poll_fn(cfg["type"])
            if poll_fn is None:
                log.warning("No collector for type %r (%s) — skipped", cfg["type"], key)
                continue
            host = CollectorHost(cfg, poll_fn)
            _register(host, cfg, source_registry)
            host.start()
            hosts.append(host)
            log.info("Loaded %s device: %s", cfg["type"], key)
        except Exception as exc:
            log.error("Bad config for %s: %s", key, exc)

    _active = hosts
    return hosts


def stop_all():
    """Stop all background polling threads.  Call on app exit."""
    for h in _active:
        h.stop()


def get_host_status(key: str) -> str:
    """
    Return connection status for the device with this key.
    Used by DividerWidget status dots.
    Returns: "connected" | "connecting" | "error" | "disconnected"
    """
    for h in _active:
        if h.key == key:
            return h.status
    return "disconnected"


def get_host_health(key: str) -> str:
    """
    Return health-aware status for the device with this key.
    Used by Ops Board entity dots — preserves warning (amber) state.
    Returns: "good" | "warning" | "error" | "connecting" | "unknown"
    """
    for h in _active:
        if h.key == key:
            if h.status == "connecting":
                return "connecting"
            return h.health
    return "unknown"


# ── collector dispatch ───────────────────────────────────────────────────── #

def _get_poll_fn(type_str: str):
    t = type_str.lower()
    try:
        if t == "ssh":
            from collectors import ssh_host
            return ssh_host.poll
        if t == "snmp":
            from collectors import snmp_v2c
            return snmp_v2c.poll
        if t == "http":
            from collectors import http_session
            return http_session.poll
        if t == "tcp":
            from collectors import tcp_check
            return tcp_check.poll
    except ImportError as exc:
        log.error("Cannot load collector %r: %s", t, exc)
    return None


# ── SOURCE_REGISTRY registration ─────────────────────────────────────────── #

def _register(host, cfg: dict, registry: dict):
    device_key  = host.key
    label       = cfg.get("label", device_key)
    c_type      = cfg.get("type", "").lower()

    # Optional per-metric overrides from the "gauges" array
    overrides = {g["source"]: g for g in cfg.get("gauges", []) if "source" in g}

    def _entry(metric_key, default_label, default_unit,
               min_=0.0, max_=100.0, danger=80.0):
        ov = overrides.get(metric_key, {})
        src_key = f"{device_key}:{metric_key}"
        return {
            "label":   ov.get("label",      f"{label} — {default_label}"),
            "unit":    ov.get("unit",        default_unit),
            "min":     ov.get("min",         min_),
            "max":     ov.get("max",         max_),
            "danger":  ov.get("danger_from", danger),
            "group":   label,
            "factory": (lambda h=host, k=metric_key: h.source(k)),
        }

    # Health is registered for every device type (used by Ops Board)
    registry[f"{device_key}:health"] = {
        "label":   f"{label} — Health",
        "unit":    "",
        "group":   label,
        "factory": (lambda h=host: (lambda: 1.0 if h.health == "good" else 0.0)),
    }

    if c_type == "ssh":
        registry[f"{device_key}:cpu"]      = _entry("cpu",      "CPU",      "%",    0,   100,  80)
        registry[f"{device_key}:ram"]      = _entry("ram",      "RAM",      "%",    0,   100,  85)
        registry[f"{device_key}:disk"]     = _entry("disk",     "Disk",     "%",    0,   100,  90)
        registry[f"{device_key}:net_in"]   = _entry("net_in",   "Net In",   "MB/s", 0,   100,  80)
        registry[f"{device_key}:net_out"]  = _entry("net_out",  "Net Out",  "MB/s", 0,   100,  80)
        registry[f"{device_key}:ctx_rate"] = _entry("ctx_rate", "CTX SW",   "×10/s",0,  100,  80)
        registry[f"{device_key}:load1"]    = _entry("load1",    "Load Avg", "×0.05",0,  100,  80)
        for i in range(8):
            registry[f"{device_key}:core_{i}"] = _entry(
                f"core_{i}", f"Core {i}", "%", 0, 100, 80
            )

    elif c_type == "snmp":
        for metric_name in cfg.get("collector", {}).get("oids", {}).keys():
            registry[f"{device_key}:{metric_name}"] = _entry(
                metric_name, metric_name, "", 0, 100, 80
            )

    elif c_type == "http":
        registry[f"{device_key}:up"]          = _entry("up",          "Up",          "",   0, 1,   0.5)
        registry[f"{device_key}:http_status"] = _entry("http_status", "HTTP Status", "",   0, 599, 399)

    elif c_type == "tcp":
        registry[f"{device_key}:up"]         = _entry("up",         "Up",      "",   0, 1,    0.5)
        registry[f"{device_key}:latency_ms"] = _entry("latency_ms", "Latency", "ms", 0, 5000, 1000)
