# Control Room — Installation Guide

> **Living document.** Update this when dependencies, steps, or architecture change.

---

## Overview

Control Room has two roles. A machine can play one or both.

| Role | What it does | Key files |
|------|-------------|-----------|
| **Collector / Daemon** | Polls all devices, stores to SQLite, serves live data over HTTP/WebSocket | `daemon.py`, `controlroom.db`, `hosts.json` |
| **Display Client** | Renders the GUI (Instrument Panel + Ops Board), connects to daemon | `designer.py`, slate `.bat` files |

In a single-machine setup (dev/test), one machine runs both. In production, a headless PC runs the daemon 24/7 and each crew member's display connects to it.

---

## Prerequisites (both roles)

- **Python 3.11+** — [python.org](https://python.org)
- **Windows** — all bat files assume Windows. Linux/Mac work with equivalent shell commands.
- **WSL** (Windows only, required for SNMP) — Windows Subsystem for Linux with Ubuntu

---

## 1. Install Python dependencies

```bat
pip install -r requirements.txt
```

This installs everything for both daemon and client. On a headless daemon machine you can skip PySide6 if you prefer, but there's no harm leaving it.

---

## 2. SNMP support (if monitoring SNMP devices)

SNMP polling uses the system `snmpget` binary, not a Python library.

**On Windows (via WSL):**
```bash
# Inside WSL terminal
sudo apt update && sudo apt install snmp
```

In `hosts.json`, set `"snmpget_path": "wsl snmpget"` for any SNMP device. The app runs `wsl snmpget` as a subprocess, which calls into WSL transparently.

**On Linux (native):**
```bash
sudo apt install snmp
```
Set `"snmpget_path": "snmpget"` in hosts.json.

---

## 3. Configure devices — `hosts.json`

Copy the example and edit:
```bat
copy hosts.json.example hosts.json
```

`hosts.json` is gitignored — it contains your local device IPs and SSH key paths. See `hosts.json.example` for all supported device types (SSH, SNMP, TCP, HTTP).

**SSH devices** require a key file:
- Generate once: `ssh-keygen -t ed25519 -f C:\Users\Bob\.ssh\panel.key`
- Copy the public key to each target device: `ssh-copy-id -i panel.key.pub user@device`

---

## 4. Running the Collector Daemon

The daemon must run on a machine with network access to all monitored devices.

```bat
run_daemon.bat
```

Or with explicit options:
```bat
py daemon.py --hosts hosts.json --db controlroom.db --port 8765
```

- `controlroom.db` is created automatically on first run.
- Logs poll results to stdout. Redirect to a file for persistent logging.
- Serves on `0.0.0.0:8765` — accessible from any machine on the LAN.
- **Does not require a display** — safe to run headless.

### Keeping the daemon running (Windows)

**Simple (manual restart):** Run in a terminal window or via Task Scheduler.

**Task Scheduler (recommended for production):**
1. Open Task Scheduler → Create Basic Task
2. Trigger: "When the computer starts"
3. Action: `py C:\path\to\ControlRoom\daemon.py`
4. Check "Run whether user is logged on or not"

**NSSM (run as a Windows service):**
```bat
nssm install ControlRoomDaemon py C:\path\to\ControlRoom\daemon.py
nssm start ControlRoomDaemon
```
Download NSSM from [nssm.cc](https://nssm.cc).

---

## 5. Running the Display Client

### Standalone (local collectors, no daemon)
```bat
run_designer.bat
```
Runs everything locally. Good for dev and single-machine setups.

### Connected to daemon
```bat
py designer.py --daemon http://192.168.1.X:8765
```

### Per-slate shortcuts
Each bat file opens a specific slate. Edit the slate name if you rename slates in the app.

| File | Slate |
|------|-------|
| `run_master.bat` | Master |
| `run_sound.bat` | Sound |
| `run_lighting.bat` | Lighting |
| `run_video.bat` | Video |

To point a slate bat at the daemon, edit the file and add `--daemon`:
```bat
@echo off
py "%~dp0designer.py" --slate "Sound" --daemon http://192.168.1.X:8765
```

---

## 6. Wall Display / Kiosk

For a TV or wall-mounted mini PC showing the Master slate full-screen:

```bat
py designer.py --slate "Master" --daemon http://192.168.1.X:8765 --kiosk
```

`--kiosk` hides all edit controls and goes full-screen. Press `Alt+F4` to exit.

Set this as a startup program on the kiosk machine so it launches automatically.

---

## 7. Baseline Setup

After the system has been running for a while in a known-good state:

```
POST http://192.168.1.X:8765/baseline/set
```

This pins current readings as the manual baseline. The daemon also recomputes rolling p50/p95 baselines nightly from the last 30 days of history.

To trigger a recompute manually:
```
POST http://192.168.1.X:8765/baseline/compute
```

Both endpoints can be hit from a browser via a REST client, or we'll add a toolbar button later.

---

## 8. Data Retention

SQLite database (`controlroom.db`) keeps 90 days of readings by default. Pruning runs automatically every 24 hours while the daemon is running.

Approximate size: ~60 devices × 10 metrics × 1 poll/5s = ~1M rows/day = ~50 MB/day uncompressed. In practice much less (most devices poll every 15–30s).

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| All devices show "connecting" indefinitely | SSH key not authorized on target, or wrong IP/port in hosts.json |
| SNMP device never connects | `wsl snmpget` not in PATH inside WSL, or wrong community string |
| Client shows stale data after switching slates | Normal — daemon data is live; stale only if daemon is unreachable |
| `ModuleNotFoundError: fastapi` | Run `pip install -r requirements.txt` |
| `ModuleNotFoundError: websockets` | Same — `pip install websockets` |
| Kiosk stuck full-screen | `Alt+F4` to exit, or `Win+D` then close the window |
