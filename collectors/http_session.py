"""
HTTP collector with persistent session and optional form login.

Handles the "cheap router" pattern: POST credentials once to create a session,
then GET a status page on each poll.  Session is stored in `state` and reused
across polls.  On auth failure (401/403 or redirect back to login page) the
session is discarded and re-login is attempted next poll.

config.collector fields:
  host        Hostname or IP (and optional port, e.g. "192.168.1.1:8080")
  scheme      "http" or "https" (default "http")
  login_url   Path to POST login form, e.g. "/login"  (omit if no auth needed)
  login_data  {field: value} form POST body, e.g. {"username": "admin", "password": "admin"}
  status_url  Path to GET for health/status data (default "/")
  checks      List of check dicts applied to the status response:
    {"type": "http_ok"}                  — response must be 2xx
    {"type": "text_present", "text": "Running"}   — text must appear in body
    {"type": "text_absent",  "text": "Error"}     — text must NOT appear in body
  verify_ssl  false to skip TLS verification (default true)

Requires: pip install requests
"""

import logging

log = logging.getLogger(__name__)

try:
    import requests
    requests.packages.urllib3.disable_warnings()   # silence InsecureRequestWarning
    _OK = True
except ImportError:
    _OK = False
    log.warning("requests not installed — HTTP collector disabled.  "
                "Run: pip install requests")


def poll(config: dict, state: dict) -> tuple[dict, dict]:
    if not _OK:
        return {"health": "error", "message": "requests not installed", "metrics": {}}, state

    c      = config["collector"]
    scheme = c.get("scheme", "http")
    base   = f"{scheme}://{c['host']}"
    verify = c.get("verify_ssl", True)

    session = state.get("session")
    if session is None:
        session = requests.Session()
        state   = {**state, "session": session, "logged_in": False}

    # ── Login ────────────────────────────────────────────────────────────── #
    login_url = c.get("login_url")
    if login_url and not state.get("logged_in"):
        try:
            r = session.post(
                f"{base}{login_url}",
                data    = c.get("login_data", {}),
                timeout = 10,
                verify  = verify,
                allow_redirects = True,
            )
            if r.ok:
                state = {**state, "logged_in": True}
            else:
                return {
                    "health":  "error",
                    "message": f"Login failed: HTTP {r.status_code}",
                    "metrics": {"up": 0.0},
                }, state
        except Exception as exc:
            return {
                "health":  "error",
                "message": f"Login error: {exc}",
                "metrics": {"up": 0.0},
            }, {**state, "session": None}

    # ── Status fetch ─────────────────────────────────────────────────────── #
    status_url = c.get("status_url", "/")
    try:
        r = session.get(
            f"{base}{status_url}",
            timeout = 10,
            verify  = verify,
        )
    except Exception as exc:
        return {
            "health":  "error",
            "message": f"Request failed: {exc}",
            "metrics": {"up": 0.0},
        }, {**state, "session": None, "logged_in": False}

    # Session expired — force re-login next poll
    if r.status_code in (401, 403):
        state = {**state, "logged_in": False}
        return {
            "health":  "error",
            "message": f"Session expired (HTTP {r.status_code})",
            "metrics": {"up": 0.0},
        }, state

    # ── Checks ───────────────────────────────────────────────────────────── #
    health  = "good"
    message = f"HTTP {r.status_code}"
    metrics = {
        "up":          1.0 if r.ok else 0.0,
        "http_status": float(r.status_code),
    }

    for check in c.get("checks", [{"type": "http_ok"}]):
        kind = check.get("type", "http_ok")
        if kind == "http_ok" and not r.ok:
            health  = "error"
            message = f"HTTP {r.status_code}"
        elif kind == "text_present":
            if check.get("text", "") not in r.text:
                health  = "error"
                message = f"Expected text not found: {check['text']!r}"
        elif kind == "text_absent":
            if check.get("text", "") in r.text:
                health  = "error"
                message = f"Unexpected text found: {check['text']!r}"

    return {"health": health, "message": message, "metrics": metrics}, state
