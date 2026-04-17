"""
SNMP v2c collector.

config.collector fields:
  host          Hostname or IP
  port          UDP port (default 161)
  community     Community string (default "public")
  oids          {metric_name: oid_string, ...}
  health_rules  list of rule dicts (optional):
    {"metric": "cpu_pct", "warn_above": 80, "error_above": 95}
    {"metric": "uptime",  "error_if_zero": true}

Requires: pip install pysnmp
  (or the maintained fork: pip install pysnmp-lextudio)
"""

import logging

log = logging.getLogger(__name__)

try:
    from pysnmp.hlapi import (
        getCmd, SnmpEngine, CommunityData, UdpTransportTarget,
        ContextData, ObjectType, ObjectIdentity,
    )
    _OK = True
except ImportError:
    _OK = False
    log.warning("pysnmp not installed — SNMP collector disabled.  "
                "Run: pip install pysnmp-lextudio")


def poll(config: dict, state: dict) -> tuple[dict, dict]:
    if not _OK:
        return {"health": "error", "message": "pysnmp not installed", "metrics": {}}, state

    c         = config["collector"]
    host      = c["host"]
    port      = int(c.get("port", 161))
    community = c.get("community", "public")
    oids      = c.get("oids", {})

    metrics: dict[str, float] = {}
    failed:  list[str]        = []

    for name, oid in oids.items():
        err_ind, err_status, _, var_binds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(community, mpModel=1),   # mpModel=1 → SNMPv2c
                UdpTransportTarget((host, port), timeout=5, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
        )
        if err_ind or err_status:
            failed.append(name)
            log.warning("SNMP %s/%s: %s %s", host, name, err_ind, err_status)
        else:
            for vb in var_binds:
                try:
                    metrics[name] = float(vb[1])
                except (TypeError, ValueError):
                    metrics[name] = 0.0

    health  = "good"
    message = "OK"

    for rule in c.get("health_rules", []):
        metric = rule.get("metric")
        if metric not in metrics:
            continue
        val = metrics[metric]
        if rule.get("error_if_zero") and val == 0:
            health  = "error"
            message = f"{metric} is zero"
        elif "error_above" in rule and val > rule["error_above"]:
            health  = "error"
            message = f"{metric} {val:.1f} > {rule['error_above']}"
        elif "warn_above" in rule and val > rule["warn_above"] and health == "good":
            health  = "warning"
            message = f"{metric} {val:.1f} > {rule['warn_above']}"

    if failed:
        health  = "error"
        message = f"SNMP failed: {', '.join(failed)}"

    return {"health": health, "message": message, "metrics": metrics}, state
