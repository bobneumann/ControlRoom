# Control Room

A skeuomorphic live monitoring dashboard for physical AV/IT environments. Built with Python + PySide6.
Pull-only, agentless — no software installed on monitored machines.

Primary use case: church AV/IT ops — audio DSP, video switchers, network switches, cameras, relay panels,
UPS, and compute nodes on a single floor-plan view that non-technical staff can read at a glance.

---

## Views

### Instrument Panel
Live machine metrics as themed analog gauges — CPU, RAM, disk, network. Needles animate at 60 fps.
Built for ops staff who want the satisfying feeling of watching well-tuned machines do their job.

### Ops Board
Spatial floor-plan view. Entities placed at their real-world positions, each showing a health dot
(green / amber / red). Non-technical audience first — one glance confirms "all systems go."
Click any entity for a Detailed View (auto-generated instrument panel for that device).

---

## Architecture

### Roles

| Role | What it does | Key file |
|------|-------------|----------|
| **Collector Daemon** | Polls all devices, stores to SQLite, pushes live data over WebSocket | `daemon.py` |
| **Display Client** | Renders Instrument Panel + Ops Board, connects to daemon | `designer.py` |

In a single-machine setup (dev/test), one machine runs both. In production, a headless machine runs the
daemon 24/7 and each crew member's display connects to it over the LAN.

### Slates
A slate is a named bundle of an Instrument Panel layout + Ops Board layout. Each crew (Sound, Lighting,
Video) has their own slate showing only their relevant devices. The Master slate is the wall display.

---

## Collectors

| Type | Use case |
|------|---------|
| SSH | Linux and Windows hosts — CPU, RAM, disk, load |
| SNMP v2c | Switches, UPS, printers — OID-mapped metrics |
| TCP | Any device — reachability + latency |
| HTTP | Web services — status code + response time |

Health per device: **good / warning / error / connecting / unknown**
Health rules (warn/error thresholds per metric) are editable live from the app.

---

## Launching

### Daemon (run once, headless OK)
```bat
run_daemon.bat
```
Or: `py daemon.py --hosts hosts.json --db controlroom.db --port 8765`

### Designer (standalone, no daemon)
```bat
run_designer.bat
```

### Designer (connected to daemon)
```bat
py designer.py --daemon http://192.168.1.X:8765
```

### Per-slate shortcuts
```bat
run_master.bat       # Master slate (wall display)
run_sound.bat        # Sound team slate
run_lighting.bat     # Lighting crew slate
run_video.bat        # Video crew slate
```

### Kiosk mode (wall display, full-screen, read-only)
```bat
py designer.py --slate "Master" --daemon http://192.168.1.X:8765 --kiosk
```

---

## Setup

See **INSTALL.md** for full setup: dependencies, SNMP, SSH keys, daemon persistence, baseline snapshots.

---

## Files

| File | Purpose |
|------|---------|
| `designer.py` | Main app — Instrument Panel, Ops Board, Slate Manager, Definition editor |
| `gauge.py` | Gauge widget, GaugeConfig, GaugeTheme, theme factories |
| `ops_board.py` | Ops Board canvas, sidebar, entity model |
| `slates.py` | Slate manager — named layout bundles |
| `host_registry.py` | Loads hosts.json, registers collectors, health evaluation |
| `collector_host.py` | Background polling thread for any collector plugin |
| `collectors/` | SSH, SNMP v2c, TCP, HTTP collector plugins |
| `daemon.py` | Standalone collector daemon — FastAPI, WebSocket push, SQLite |
| `daemon_db.py` | SQLite layer — schema, poll writes, snapshots, baselines, pruning |
| `ws_registry.py` | Client WebSocket registry — drop-in replacement for host_registry |
| `datasources.py` | Local psutil metric sources |
| `hosts.json` | **gitignored** — your device definitions |
| `hosts.json.example` | Template — copy to hosts.json and configure |
| `INSTALL.md` | Full setup and deployment guide |

---

## Themes
- WWII Cockpit — olive drab, flat black, cream markings
- F1 Racing — carbon fiber, chrome, vivid orange needle

---

## License
MIT
