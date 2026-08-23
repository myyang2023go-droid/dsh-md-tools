# Architecture — DSH MD Tools

**中文文档 → [ARCHITECTURE.zh-CN.md](ARCHITECTURE.zh-CN.md)**

DSH MD Tools is the observability layer between a running LAMMPS job and an LLM agent.
Everything is **read-only by default**, built on **files as the single source of truth**,
and runs with **zero third-party dependencies** (Python standard library + vanilla HTML/JS).

## Big picture

```
   LAMMPS run ──▶ run-case dir (RUN_CASE_DIR)        agent kit dir (AGENT_KIT_DIR)
                 log.lammps / thermo / dump          .v3.3_state.json / strategy db
                            │                                  │
                            └───────────┬──────────────────────┘
                                        │ read-only
                    ┌───────────────────┴────────────────────┐
                    │                                        │
          ┌─────────┴──────────┐                  ┌──────────┴─────────┐
          │ web_monitor.py     │                  │ md_mcp.py          │
          │ HTTP server :8080  │                  │ MCP bridge (stdio) │
          └─────────┬──────────┘                  └──────────┬─────────┘
                    │ HTML + JSON API                        │ 8 tools
          ┌─────────┴──────────┐                  ┌──────────┴─────────┐
          │ Browser            │                  │ DSH / LLM agent    │
          │ dashboard+workbench│                  │ queries state      │
          └────────────────────┘                  └────────────────────┘
```

The orchestration core that *writes* those state files (phase machine, physics gates)
is intentionally **not** part of this repository — this toolkit only observes.

## Components

### 1. `dashboard/web_monitor.py` — the server (stdlib `http.server`)

One file, no framework. Responsibilities:

- **Task discovery** — scans `RUN_CASE_DIR` for run cases, parses `log.lammps`
  (step, temperature, energy, pressure, volume, density) and detects live processes
- **State aggregation** — merges simulation data with the agent state files
  (`.v3.3_state.json`, strategy DB) into a single status payload
- **Static pages** — serves the dashboard, workbench and doc pages
- **Theme engine** — rewrites the served HTML per request (see below)
- **JSON API**:

| Endpoint | Purpose |
|---|---|
| `/api/status?task=<id>` | Full status: step/temp/energy/pressure, phase machine, agents, logs, history |
| `/api/tasks` | Task list: active / stopped today / history |
| `/api/theme` | Effective theme name (used by the 0.5 s sync poll) |
| `/api/auto-approve` (GET/POST) | Auto-approve flag for the DSH approval plugin |

### 2. `dashboard/static/index.html` — the dashboard

Vanilla JS, no build step:

- Polls `/api/status` every 5 s and re-renders only what changed (hash-guarded)
- KPI cards → Canvas trend charts → **sparklines** (temp/energy/pressure, sampled
  from server history) → agent pipeline topology → logs → history table
- Theme selector (header) + auto-reload theme sync with scroll preservation
- `simple.html` is a lightweight variant for quick checks

### 3. `dashboard/workbench.html` — the workbench

Split view: MD assistant chat (`:3091`, iframe) on the left, live dashboard on the right.

- Glass top bar: navigation, **auto-approve switch**, theme selector, reload
- Draggable divider with grip; split ratio persisted in `localStorage`
- Same theme cookie and 0.5 s sync as the dashboard — one choice themes everything

### 4. `mcp/md_mcp.py` — the MCP read-only bridge

A stdio MCP server exposing 8 tools to the LLM:

| Tool | What it reads | Permission |
|---|---|---|
| `sim_status` | step / temperature / phase machine state | read-only |
| `sim_context` | task context (force field, data files, dirs) | read-only |
| `sim_strategy_log` | strategy / decision history | read-only |
| `sim_orchestrator_log` | orchestrator log | read-only |
| `sim_recent_ops` | recent operation audit | read-only |
| `read_paper` | literature attachments | read-only |
| `open_monitor` | opens the dashboard | read-only |
| `sim_exec` | executes a command | 🔒 **write gate** |

Connection modes: `local` (direct file reads) or `ssh` (remote host), configured in
`md_config.json` (see `md_config.example.json`).

### 5. The write gate — `sim_exec`

The only write path in the entire toolkit:

```
LLM calls sim_exec(cmd)
        │
        ▼
whitelist filter ── denied: bash / sh / nohup / setsid / ...
        │
        ▼
per-command approval (DSH approval prompt)
        │
        ▼
execution + audit log entry (who / what / when / result)
```

## Theme system

Six themes: `light`, `dark` (matches DSH's neutral gray), `ocean` (deep navy),
`purple`, `forest`, plus `auto` (follow DSH).

```
DSH settings panel ──▶ .dsh/settings.yaml (ui-theme.preference)
                              │
theme selector ──▶ cookie dash-theme (manual choice wins over "auto")
                              │
                              ▼
               web_monitor resolves the effective theme per request
                              │
        ┌─────────────────────┴──────────────────────┐
        │ 1. hex replacement: light palette literals │
        │    in HTML/CSS/JS → target palette         │
        │ 2. inject glass CSS: blur cards, gradient  │
        │    title, animated bottom waves            │
        └─────────────────────┬──────────────────────┘
                              ▼
page polls /api/theme every 0.5 s ── effective theme changed? ──▶ reload
                                                        (scroll position preserved)
```

Server-side replacement (rather than CSS variables) keeps it working on inline-styled,
dynamically generated elements that no stylesheet can reach.

## Security model

- **Read-only first** — every tool except `sim_exec` is read-only
- **Write gate** — whitelist + per-command approval + audit log
- **Localhost by default** — the server binds `127.0.0.1`; LAN exposure requires
  explicitly setting `WEB_HOST`
- **Credential isolation** — `md_config.json` is git-ignored; only a template ships
- **Path safety** — doc pages are served from an allowlisted directory with
  filename validation (no path traversal)

## Repository layout

```
dsh-md-tools/
├── dashboard/
│   ├── web_monitor.py        # HTTP server: pages + JSON API + theme engine
│   ├── static/
│   │   ├── index.html        # dashboard (vanilla JS)
│   │   └── simple.html       # lightweight variant
│   ├── workbench.html        # chat + dashboard split view
│   └── pages/                # static doc pages (architecture, task flow)
├── mcp/
│   ├── md_mcp.py             # MCP stdio bridge (8 tools)
│   └── md_config.example.json
├── docs/
│   ├── ARCHITECTURE.md       # this file
│   ├── ARCHITECTURE.zh-CN.md
│   └── screenshots/
├── LICENSE  (Apache-2.0)
├── NOTICE   (dsh MIT attribution)
└── README.md / README.zh-CN.md
```
