# 架构说明 — DSH MD Tools

**English → [ARCHITECTURE.md](ARCHITECTURE.md)**

DSH MD Tools 是运行中的 LAMMPS 作业与 LLM 智能体之间的观测层。
整体**默认只读**、以**文件为唯一真相源**，**零第三方依赖**
(Python 标准库 + 原生 HTML/JS)。

## 全景

```
   LAMMPS 运行 ──▶ run-case 目录 (RUN_CASE_DIR)      智能体套件目录 (AGENT_KIT_DIR)
                 log.lammps / thermo / dump          .v3.3_state.json / 策略库
                            │                                  │
                            └───────────┬──────────────────────┘
                                        │ 只读
                    ┌───────────────────┴────────────────────┐
                    │                                        │
          ┌─────────┴──────────┐                  ┌──────────┴─────────┐
          │ web_monitor.py     │                  │ md_mcp.py          │
          │ HTTP 服务 :8080    │                  │ MCP 桥 (stdio)     │
          └─────────┬──────────┘                  └──────────┬─────────┘
                    │ HTML + JSON API                        │ 8 个工具
          ┌─────────┴──────────┐                  ┌──────────┴─────────┐
          │ 浏览器             │                  │ DSH / LLM 智能体   │
          │ 看板 + 工作台      │                  │ 查询状态           │
          └────────────────────┘                  └────────────────────┘
```

负责*写入*这些状态文件的编排内核(相位机、物理门)**刻意不在**本仓库内
—— 本工具包只做观测。

## 组件

### 1. `dashboard/web_monitor.py` — 服务端(标准库 `http.server`)

单文件、无框架。职责:

- **任务发现** — 扫描 `RUN_CASE_DIR` 中的 run case,解析 `log.lammps`
  (step、温度、能量、压强、体积、密度)并探测存活进程
- **状态聚合** — 把模拟数据与智能体状态文件
  (`.v3.3_state.json`、策略库)合并为单一状态载荷
- **静态页面** — 提供看板、工作台与文档页
- **主题引擎** — 每次请求重写返回的 HTML(见下文)
- **JSON API**:

| 端点 | 用途 |
|---|---|
| `/api/status?task=<id>` | 完整状态:step/温度/能量/压强、相位机、智能体、日志、历史 |
| `/api/tasks` | 任务列表:运行中 / 今日已停 / 历史 |
| `/api/theme` | 当前生效主题名(供 0.5 s 同步轮询使用) |
| `/api/auto-approve` (GET/POST) | DSH 审批插件的自动审批开关 |

### 2. `dashboard/static/index.html` — 看板

原生 JS、无构建步骤:

- 每 5 s 轮询 `/api/status`,hash 守卫、只重绘有变化的部分
- KPI 卡片 → Canvas 趋势图 → **迷你趋势图**(温度/能量/压强,由服务端
  历史采样)→ 智能体流水线拓扑 → 日志 → 历史表
- 主题选择器(页头)+ 0.5 s 主题同步自动重载(保留滚动位置)
- `simple.html` 是用于快速查看的轻量变体

### 3. `dashboard/workbench.html` — 工作台

分栏视图:左侧 MD 助手对话(`:3091`,iframe),右侧实时看板。

- 玻璃拟态顶栏:导航、**自动审批开关**、主题选择器、重载
- 可拖拽分隔条(带把手);分栏比例存于 `localStorage`
- 与看板共用同一主题 cookie 与 0.5 s 同步 —— 一次选择,全局生效

### 4. `mcp/md_mcp.py` — MCP 只读桥

一个 stdio MCP 服务器,向 LLM 暴露 8 个工具:

| 工具 | 读取内容 | 权限 |
|---|---|---|
| `sim_status` | step / 温度 / 相位机状态 | 只读 |
| `sim_context` | 任务上下文(力场、数据文件、目录) | 只读 |
| `sim_strategy_log` | 策略 / 决策历史 | 只读 |
| `sim_orchestrator_log` | 编排器日志 | 只读 |
| `sim_recent_ops` | 近期操作审计 | 只读 |
| `read_paper` | 文献附件 | 只读 |
| `open_monitor` | 打开看板 | 只读 |
| `sim_exec` | 执行命令 | 🔒 **写门** |

连接模式:`local`(直接读文件)或 `ssh`(远程主机),在
`md_config.json` 中配置(见 `md_config.example.json`)。

### 5. 写门 — `sim_exec`

整个工具包中唯一的写路径:

```
LLM 调用 sim_exec(cmd)
        │
        ▼
白名单过滤 ── 拒绝:bash / sh / nohup / setsid / ...
        │
        ▼
逐条审批(DSH 审批弹窗)
        │
        ▼
执行 + 审计日志条目(谁 / 做了什么 / 何时 / 结果)
```

## 主题系统

六个主题:`light`、`dark`(对齐 DSH 的中性灰)、`ocean`(深海蓝)、
`purple`、`forest`,以及 `auto`(跟随 DSH)。

```
DSH 设置面板 ──▶ .dsh/settings.yaml (ui-theme.preference)
                              │
主题选择器 ──▶ cookie dash-theme(手动选择优先于 "auto")
                              │
                              ▼
               web_monitor 每次请求解析生效主题
                              │
        ┌─────────────────────┴──────────────────────┐
        │ 1. hex 替换:HTML/CSS/JS 中的浅色系字面量   │
        │    → 目标调色板                            │
        │ 2. 注入玻璃 CSS:模糊卡片、渐变标题、       │
        │    底部动画波浪                            │
        └─────────────────────┬──────────────────────┘
                              ▼
页面每 0.5 s 轮询 /api/theme ── 生效主题变了? ──▶ 重载
                                                   (保留滚动位置)
```

选择服务端替换(而非 CSS 变量)是为了覆盖那些内联样式、动态生成的、
任何样式表都够不到的元素。

## 安全模型

- **只读优先** — 除 `sim_exec` 外的所有工具均为只读
- **写门** — 白名单 + 逐条审批 + 审计日志
- **默认仅本机** — 服务绑定 `127.0.0.1`;要暴露到局域网需显式设置 `WEB_HOST`
- **凭据隔离** — `md_config.json` 被 git 忽略;仓库只带模板
- **路径安全** — 文档页仅从白名单目录提供,文件名严格校验(防路径穿越)

## 仓库结构

```
dsh-md-tools/
├── dashboard/
│   ├── web_monitor.py        # HTTP 服务:页面 + JSON API + 主题引擎
│   ├── static/
│   │   ├── index.html        # 看板(原生 JS)
│   │   └── simple.html       # 轻量变体
│   ├── workbench.html        # 对话 + 看板 分栏视图
│   └── pages/                # 静态文档页(架构、任务流程)
├── mcp/
│   ├── md_mcp.py             # MCP stdio 桥(8 个工具)
│   └── md_config.example.json
├── docs/
│   ├── ARCHITECTURE.md
│   ├── ARCHITECTURE.zh-CN.md # 本文件
│   └── screenshots/
├── LICENSE  (Apache-2.0)
├── NOTICE   (dsh MIT 署名)
└── README.md / README.zh-CN.md
```
