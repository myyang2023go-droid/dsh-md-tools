<div align="center">

# DSH MD Tools

**Let LLMs safely "see" molecular dynamics simulations — a peripheral toolkit for the MD simulation agent**

Real-time monitoring dashboard · Read-only MCP bridge · Phase-machine visualization · Theme sync

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.6%2B-green.svg)]()
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen.svg)]()
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey.svg)]()

**English | [中文](README.zh-CN.md)**

</div>

---

## What is this

Running long LAMMPS jobs, you probably know the drill: `tail -f log.lammps` until your eyes bleed, a temperature spike goes unnoticed for half an hour, and the wrong force field is discovered only after the run finishes.

**DSH MD Tools** gives an LLM agent (built on [DSH (DeepSeek Harness)](https://www.npmjs.com/package/@deepseek-ai/dsh)) a pair of eyes:

- 📊 **Real-time dashboard**: steps / temperature / energy / pressure / density at a glance, with the agent phase machine and the five MONITOR sub-phases (observe → analyze → detect → evaluate → decide) fully visible
- 🔌 **Read-only MCP bridge**: 8 tools let the LLM query simulation state at any time. **Read-only by design** — the single write gate `sim_exec` is protected by a whitelist + per-command approval
- 🖥️ **Workbench**: chat with the MD assistant on the left, watch the live dashboard on the right — one source of truth
- 🌗 **Theme sync**: the dashboard follows DSH's light/dark theme within 0.5 s, preserving scroll position

Zero dependencies — Python standard library + vanilla HTML/JS only. Copy and run.

## Screenshots

| Dashboard · Light | Dashboard · Dark (follows DSH theme) |
|:---:|:---:|
| ![dashboard light](docs/screenshots/dashboard-light.png) | ![dashboard dark](docs/screenshots/dashboard-dark.png) |

| Workbench: MD assistant chat (left) · live dashboard (right) |
|:---:|
| ![workbench](docs/screenshots/workbench.png) |

> Real run shown: a 5,660-atom polymer precursor system relaxing at 300 K (2,000,000 steps in total) — captured at ~75,000 steps, 1730 K, risk score 0, phase machine in MONITOR/observe.

## Quick start

```bash
# ① Dashboard (:8080)
export AGENT_KIT_DIR=/path/to/your/agent_deploy_kit   # agent kit directory
export RUN_CASE_DIR=/path/to/your/run-cases           # optional, defaults to $AGENT_KIT_DIR/production
python3 dashboard/web_monitor.py 8080

# Open in browser
#   http://127.0.0.1:8080/           Dashboard
#   http://127.0.0.1:8080/workbench  Workbench (chat + dashboard side by side)

# ② Read-only MCP bridge (connect to DSH)
cp mcp/md_config.example.json mcp/md_config.json
# Edit md_config.json with your paths; both local and ssh modes are supported
```

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `AGENT_KIT_DIR` | Agent kit directory (contains `.v3.3_state.json`) | `~/agent_deploy_kit` |
| `RUN_CASE_DIR` | Run-case root directory | `$AGENT_KIT_DIR/production` |
| `DSH_SETTINGS` | Path to DSH's settings.yaml (for theme sync) | `../.dsh/settings.yaml` |
| `WEB_HOST` | Bind address | `127.0.0.1` (set `0.0.0.0` to expose on LAN) |

## MCP tools

| Tool | Purpose | Permission |
|---|---|---|
| `sim_status` | Current step / temperature / phase machine state | read-only |
| `sim_context` | Task context (force field, data files, directories) | read-only |
| `sim_strategy_log` | Strategy / decision history | read-only |
| `sim_orchestrator_log` | Orchestrator log | read-only |
| `sim_recent_ops` | Recent operation audit | read-only |
| `read_paper` | Read literature attachments | read-only |
| `open_monitor` | Open the dashboard | read-only |
| `sim_exec` | Execute a command | 🔒 write gate: whitelist + per-command approval |

## Security design

- **Read-only first**: everything except `sim_exec` is read-only; the write gate filters commands through a whitelist (bash/sh/nohup/setsid banned) and persists an audit log
- **Localhost by default**: the dashboard binds to `127.0.0.1`; LAN exposure requires explicitly setting `WEB_HOST`
- **Credential isolation**: the real config (`md_config.json`) is excluded via `.gitignore`; only a template ships in the repo

## Use cases

- Babysitting long-running MD jobs for thermal/mechanical materials evaluation
- Batch monitoring of bio-pharmaceutical and nanomaterial systems
- Observability layer for AI4Science agent workflows

## License

Apache-2.0, see [LICENSE](LICENSE). Third-party notices in [NOTICE](NOTICE).

> This repo contains the peripheral toolkit only. The multi-agent orchestration core (phase-machine decision logic, physics gates, controlled write bridge) is not part of this repository.
