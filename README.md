# dsh-md-tools

分子动力学（MD）模拟智能体的**外围工具集**：实时监控看板 + MCP 只读桥。
配合 [dsh (DeepSeek Harness)](https://www.npmjs.com/package/@deepseek-ai/dsh) 使用，让 LLM 智能体安全地观测 LAMMPS 模拟运行状态。

> 本仓库只包含外围工具。多智能体编排内核（相位机、物理门、受控写桥）不在本仓库内。

## 组件

### 1. 看板 Dashboard（`dashboard/`）

零依赖（纯 Python 标准库 + 原生 HTML/JS）的实时监控面板：

- **任务全景**：进行中 / 今日已停 / 历史任务分组，进度条与动力学阶段识别
- **相位机可视化**：主相位流转图 + MONITOR 五子相位（OBSERVE→ANALYZE→DETECT→EVALUATE→DECIDE）循环指示
- **智能体控制中心**：裁决层 / 监控通道 / LAMMPS 进程健康度
- **观测日志流**：严重级别着色的实时日志
- **主题同步**：自动跟随 dsh 侧 `settings.yaml` 的 `ui-theme.preference`（0.5s 轮询，变化即重载，保留滚动位置）
- **工作台** `workbench.html`：左 dsh 对话、右看板的双栏壳，含自动审批开关

### 2. MCP 只读桥（`mcp/md_mcp.py`）

8 个工具让 dsh 智能体读取模拟状态，**只读**（唯一的写门 `sim_exec` 需逐条审批）：

| 工具 | 用途 |
|---|---|
| `sim_status` | 当前 step / 温度 / 相位机状态 |
| `sim_context` | 任务上下文（力场、数据文件、目录） |
| `sim_strategy_log` | 策略/决策历史 |
| `sim_orchestrator_log` | 编排日志 |
| `sim_recent_ops` | 最近操作审计 |
| `read_paper` | 读取文献附件 |
| `open_monitor` | 打开看板 |
| `sim_exec` | 执行命令（写门，白名单 + 逐条审批） |

支持 local（直读目录）和 ssh（远程拉取）两种模式。

## 快速开始

```bash
# 1. 看板
export AGENT_KIT_DIR=/path/to/your/agent_deploy_kit   # 智能体套件目录
export RUN_CASE_DIR=/path/to/your/run-cases           # 可选,默认 $AGENT_KIT_DIR/production
python3 dashboard/web_monitor.py 8080
# 打开 http://127.0.0.1:8080/  或工作台 http://127.0.0.1:8080/workbench

# 2. MCP 桥
cp mcp/md_config.example.json mcp/md_config.json
# 编辑 md_config.json 填入你的路径
```

| 环境变量 | 说明 | 默认 |
|---|---|---|
| `AGENT_KIT_DIR` | 智能体套件目录（含 `.v3.3_state.json`） | `~/agent_deploy_kit` |
| `RUN_CASE_DIR` | 运行案例根目录 | `$AGENT_KIT_DIR/production` |
| `DSH_SETTINGS` | dsh 的 settings.yaml 路径（主题同步用） | `../.dsh/settings.yaml` |
| `WEB_HOST` | 绑定地址 | `127.0.0.1`（LAN 暴露设 `0.0.0.0`） |

## 安全说明

- MCP 桥所有工具只读；`sim_exec` 走白名单 + 审批门
- 看板默认只绑定 `127.0.0.1`
- 真实配置（`md_config.json`）已在 `.gitignore` 排除，请勿提交凭证

## 许可证

Apache-2.0，见 [LICENSE](LICENSE)。第三方声明见 [NOTICE](NOTICE)。
