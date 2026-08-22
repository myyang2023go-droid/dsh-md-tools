# -*- coding: utf-8 -*-
"""
分子模拟助手 只读 MCP 服务器（stdio, 零第三方协议依赖）
========================================================
- 领域: LAMMPS/ReaxFF 分子动力学编排系统(agent_deploy_kit)。本桥读它的真相源:
  .v3.3_state.json / status_bus.json / logs/*.jsonl —— 不杀进程、不碰力场/输入(科研红线)。
- 唯一写门 sim_exec: 经 agent_deploy_kit 的 claude_interface.py exec 审计通道执行
  (可执行文件白名单 + shell=False 防注入 + 逐条写 logs/claude_operations.jsonl);
  是否允许执行由 dsh 审批弹窗决定(dsh-md-ops-gate 插件把该工具路由到 approval seam),
  无应答者(headless)时 fail-closed 拒绝。
- 双模式(通用 Windows/Linux):
  mode=local  直读 local_base 下的文件(dsh 装在跑模拟的机器上,或读本地快照)
  mode=ssh    paramiko 只读拉 remote_base(dsh 在 Windows、真机在远程 Linux)
- 传输: MCP stdio = 换行分隔 JSON-RPC 2.0(每行一条)。日志走 stderr,绝不污染 stdout。
- 工具名对模型呈现为 mcp__mdsim__<name>(namespace 由 dsh-mcp-client 的 serverName=mdsim 决定)。
"""
import sys, os, json, traceback

# 环境免疫:Windows 默认 GBK stdout 编不了中文/⚠ 会崩 —— 启动即锁 UTF-8(病灶 D-04 教训,来自量化役)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "md_config.json"), "r", encoding="utf-8"))
PROTOCOL_VERSION_FALLBACK = "2024-11-05"
MODE = CFG.get("mode", "local")
SRC = ("本地真相源(只读)" if MODE == "local" else "远程Linux真机(SSH只读)")

def log(msg):
    sys.stderr.write("[md_mcp] %s\n" % msg); sys.stderr.flush()

TOOLCALL_LOG = os.path.join(HERE, "_toolcalls.jsonl")
def _toolcall_log(name, args, data):
    try:
        import time
        with open(TOOLCALL_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "tool": name, "args": args,
                                "result_keys": list(data.keys()) if isinstance(data, dict) else str(type(data))},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass

# ---------- 双模式文件读取(local 直读 / ssh 拉) ----------
def _local_path(rel):
    base = CFG.get("local_base", "")
    return os.path.join(base, *rel.split("/"))

def _ssh_client():
    import paramiko
    s = CFG.get("ssh", {})
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = {"hostname": s.get("host"), "username": s.get("user"), "timeout": 20}
    if s.get("key_file"):
        kw["key_filename"] = s["key_file"]
    elif s.get("password"):
        kw["password"] = s["password"]
    cli.connect(**kw)
    return cli

def _ssh_run(cmd, timeout=45):
    cli = _ssh_client()
    try:
        _in, out, err = cli.exec_command(cmd, timeout=timeout)
        return out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")
    finally:
        cli.close()

def read_text(rel):
    """读整个文件文本(不存在返回 None)。"""
    if MODE == "local":
        p = _local_path(rel)
        if not os.path.exists(p):
            return None
        return open(p, "r", encoding="utf-8", errors="replace").read()
    remote = CFG.get("ssh", {}).get("remote_base", "").rstrip("/") + "/" + rel
    o, e = _ssh_run("cat '%s' 2>/dev/null" % remote)
    return o if o.strip() else None

def read_tail(rel, n=15):
    """读文件末 n 行(不存在返回 [])。"""
    if MODE == "local":
        p = _local_path(rel)
        if not os.path.exists(p):
            return []
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()[-n:]
    remote = CFG.get("ssh", {}).get("remote_base", "").rstrip("/") + "/" + rel
    o, e = _ssh_run("tail -n %d '%s' 2>/dev/null" % (n, remote))
    return [ln + "\n" for ln in o.splitlines()]

def read_json(rel):
    t = read_text(rel)
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception as ex:
        log("json parse %s: %s" % (rel, ex))
        return None

DISC_READONLY = ("只读真相源(state/日志文件),数字均为文件真实内容;本工具不写、不杀进程、不改 LAMMPS 输入/力场(科研红线)。"
                 "高危操作(kill_lammps/modify_data/change_forcefield 等)走唯一写门 sim_exec(claude_interface 审计通道+dsh 弹窗确认),非本工具能力。")

DISC_WRITE_GATE = ("唯一写门:命令经 claude_interface.py exec 执行(白名单+shell=False+逐条审计 logs/claude_operations.jsonl)。"
                   "执行前必须已在对话里向用户讲清后果,且用户在 dsh 弹窗里点了批准;用户拒绝即停止、绝不换路径绕过;"
                   "结果数字以本返回为准,不编造。")

def sim_exec(args):
    """唯一写门:把一条命令交给 claude_interface.py exec/exec_bg(审计通道)执行。白名单+shell=False+审计日志。调用前必须已在对话中讲清后果;用户在 dsh 弹窗批准后才真正到达这里。background=true 走 exec_bg 后台启动(LAMMPS/编排器等长任务),立即返回 PID+日志路径。"""
    cmd = str(args.get("cmd", "")).strip()
    desc = str(args.get("description", "")).strip()
    cwd = str(args.get("cwd", "")).strip() or None
    background = bool(args.get("background", False))
    log_path = str(args.get("log", "")).strip() or None
    if not cmd:
        return {"error": "需要 cmd 参数(要执行的命令)", "_discipline": DISC_WRITE_GATE}
    if MODE != "local":
        return {"error": "写门仅在本机真机(local 模式)开放;ssh 模式只读。",
                "_discipline": DISC_WRITE_GATE}
    import subprocess
    ci = _local_path("agents/runtime/v3.3/claude_interface.py")
    if not os.path.exists(ci):
        return {"error": "claude_interface.py 不存在: %s" % ci, "_discipline": DISC_WRITE_GATE}
    argv = [sys.executable, ci, "exec_bg" if background else "exec", cmd, desc or cmd]
    if cwd or (background and log_path):
        argv.append(cwd or ".")
    if background and log_path:
        argv.append(log_path)
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=360)
    except subprocess.TimeoutExpired:
        return {"error": "审计通道执行超时(360s;长任务请用 background=true)", "cmd": cmd,
                "_discipline": DISC_WRITE_GATE}
    # claude_interface stdout 末尾是 JSON(前面有 [CLAUDE_INTERFACE] 提示行)
    out = (r.stdout or "").strip()
    payload = None
    brace = out.find("{")
    if brace >= 0:
        try:
            payload = json.loads(out[brace:])
        except Exception:
            payload = None
    if payload is None:
        payload = {"returncode": r.returncode, "stdout": out, "stderr": (r.stderr or "")[:2000]}
    payload["cmd"] = cmd
    payload["description"] = desc or cmd
    payload["audit_log"] = "logs/claude_operations.jsonl"
    payload["_discipline"] = DISC_WRITE_GATE
    return payload

# ---------- 工具实现 ----------
def sim_status(args):
    """当前各模拟 case 的实时状态(读 status_bus.json):步数/进度/温度/阶段/异常 + 系统负载。判断'模拟跑到哪了/有没有异常'用它。"""
    bus = read_json("status_bus.json")
    if bus is None:
        return {"source": SRC, "error": "status_bus.json 不存在或无法解析(可能模拟未启动/该机无此文件)"}
    cases_out = {}
    for cid, cv in (bus.get("cases") or {}).items():
        if not isinstance(cv, dict):
            cases_out[cid] = cv; continue
        # 状态总线可能是扁平(status/step/...)或含子对象(preflight_v2/monitor 等),两种都兼容
        row = {}
        for k in ("status", "step", "total", "pct", "temp_k", "stage", "speed", "eta_sec", "cores"):
            if k in cv:
                row[k] = cv[k]
        if cv.get("anomalies"):
            row["anomalies"] = cv["anomalies"]
        # 保留子阶段对象的键名(如 preflight_v2 的 issues/fixes_applied)供讲理
        subkeys = [k for k in cv.keys() if isinstance(cv.get(k), dict)]
        if subkeys and not row:
            row["_子阶段"] = {}
            for sk in subkeys:
                sv = cv[sk]
                row["_子阶段"][sk] = {kk: sv[kk] for kk in ("issues", "fixes_applied", "can_rebuild", "missing_elements") if kk in sv}
        cases_out[cid] = row or cv
    return {"source": SRC + " status_bus.json", "timestamp": bus.get("timestamp"),
            "version": bus.get("version"), "cases": cases_out, "case_count": len(cases_out),
            "system": bus.get("system"),
            "_discipline": DISC_READONLY}

def sim_context(args):
    """编排器当前上下文(读 .v3.3_state.json,对齐已有 claude_interface.py 的 context):相位/子相位/任务/恢复次数/最近审计操作。"""
    st = read_json(".v3.3_state.json") or {}
    ops_lines = read_tail("logs/claude_operations.jsonl", int(args.get("n", 10)))
    recent = []
    for ln in ops_lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            recent.append(json.loads(ln))
        except Exception:
            pass
    task = st.get("task") or {}
    return {"source": SRC + " .v3.3_state.json + claude_operations",
            "phase": st.get("phase"), "monitor_subphase": st.get("monitor_subphase"),
            "task": {k: task.get(k) for k in ("case_id", "prod_dir", "total_steps", "cores", "target_elements") if k in task},
            "recovery_count": len(st.get("recovery_history") or []),
            "last_tick": st.get("last_tick"),
            "recent_operations": recent,
            "_discipline": DISC_READONLY}

def sim_strategy_log(args):
    """编排器策略决策链(读 strategy_decisions.jsonl 末 n 条):相位流转 + 触发原因 + 采用的恢复策略(A/B/D/E/F)。看'为什么进 RECOVER/换了什么策略'用它。"""
    n = int(args.get("n", 12))
    rows = []
    for ln in read_tail("logs/strategy_decisions.jsonl", n):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
            det = d.get("details") or {}
            rows.append({"ts": d.get("ts"), "phase": "%s→%s" % (d.get("phase_from"), d.get("phase_to")),
                         "trigger": d.get("trigger"), "decision": d.get("decision"),
                         "strategy": det.get("strategy"), "attempt": det.get("attempt")})
        except Exception:
            pass
    return {"source": SRC + " strategy_decisions.jsonl", "count": len(rows), "decisions": rows,
            "_discipline": DISC_READONLY}

def sim_orchestrator_log(args):
    """编排器运行日志(读 orchestrator_v3.3.jsonl 末 n 条):OBSERVE→ANALYZE→... 状态机流转、存活进程数/是否冻结。看'编排器最近在干嘛'用它。"""
    n = int(args.get("n", 20))
    rows = []
    for ln in read_tail("logs/orchestrator_v3.3.jsonl", n):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
            rows.append({"ts": d.get("ts"), "level": d.get("level"), "msg": d.get("msg")})
        except Exception:
            pass
    return {"source": SRC + " orchestrator_v3.3.jsonl", "count": len(rows), "log": rows,
            "_discipline": DISC_READONLY}

def sim_recent_ops(args):
    """Claude 审计操作流水(读 claude_operations.jsonl 末 n 条):谁在什么相位对哪个目标做了什么(经审计通道)。看'最近动过什么'用它。"""
    n = int(args.get("n", 15))
    rows = []
    for ln in read_tail("logs/claude_operations.jsonl", n):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
            rows.append({"ts": d.get("ts"), "actor": d.get("actor"), "action": d.get("action"),
                         "target": d.get("target")})
        except Exception:
            pass
    return {"source": SRC + " claude_operations.jsonl", "count": len(rows), "operations": rows,
            "_discipline": DISC_READONLY}

def open_monitor(args):
    """打开 Web 看板(web_monitor.py, 默认 8080):各 case 实时进度/温度/异常大屏。用户说'打开看板/看盘/大屏'时用它。只看不改。"""
    import webbrowser
    url = CFG.get("monitor_url", "http://127.0.0.1:8080")
    opened = False
    try:
        opened = webbrowser.open(url)
    except Exception as ex:
        log("open_monitor: %s" % ex)
    return {"action": "open_monitor", "url": url, "opened": bool(opened),
            "note": ("已尝试打开 Web 看板 %s(web_monitor.py)。若空白:local 模式需先在本机跑 web_monitor;"
                     "ssh/远程模式需真机 8080 可达或做端口转发。看板与本桥读同一真相源,数字一致。" % url),
            "_discipline": "只打开只读看板,不改任何状态。"}

def read_paper(args):
    """读一篇文献(PDF/txt/md/docx)返回正文文本，供 Mode B 解读意图、设计建模与动力学方案。只读。参数 path(文件绝对路径)。"""
    path = str(args.get("path", "")).strip().strip('"').strip("'")
    if not path:
        return {"error": "需要 path 参数(文献文件绝对路径，如 E:\\\\papers\\\\aerogel.pdf)"}
    # 双模式:local 读本机路径;ssh 模式先只支持本机路径(文献一般在你操作的机器上)
    if not os.path.exists(path):
        return {"error": "文件不存在: %s" % path}
    ext = os.path.splitext(path)[1].lower()
    max_chars = int(args.get("max_chars", 60000))
    text = ""; meta = {}
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(path)
            meta["pages"] = len(r.pages)
            text = "\n".join((p.extract_text() or "") for p in r.pages)
            if len(text.strip()) < 200:   # 扫描件/抽取为空 → pdfplumber 兜底
                try:
                    import pdfplumber
                    with pdfplumber.open(path) as pdf:
                        text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
                    meta["extractor"] = "pdfplumber"
                except Exception:
                    meta["extractor"] = "pypdf(可能扫描件,文本稀少)"
            else:
                meta["extractor"] = "pypdf"
        elif ext == ".docx":
            import docx
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs)
            meta["extractor"] = "python-docx"
        else:   # txt/md/in/dat/log 等按文本读
            text = open(path, encoding="utf-8", errors="replace").read()
            meta["extractor"] = "text"
    except Exception as ex:
        return {"error": "读取失败(%s): %s" % (ext, str(ex)[:160])}
    total = len(text)
    return {"source": "read_paper " + os.path.basename(path), "path": path, "ext": ext,
            "total_chars": total, "truncated": total > max_chars, "meta": meta,
            "text": text[:max_chars],
            "_discipline": ("只读文献正文，不写、不改。据此给出的建模/动力学是【方案建议】，非既成事实；"
                            "真正建模/跑模拟仍须经编排器+你确认(红线)。文献里的数值以原文为准、引用标注出处；"
                            "与已有 case 参数口径对齐时注明差异。")}

TOOLS = [
    {"name": "sim_status",
     "description": "当前各 LAMMPS 模拟 case 的实时状态(读 status_bus.json):运行状态/步数/进度%/温度K/阶段/异常 + 系统负载。判断'模拟跑到哪了、有没有异常/风险'先用它。只读。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "sim_context",
     "description": "编排器当前上下文(读 .v3.3_state.json,对齐已有 claude_interface.py context):相位(IDLE/PREFLIGHT/LAUNCH/MONITOR/RECOVER)/监控子相位/当前任务(case_id/步数/核数/元素)/恢复次数/最近审计操作。看'现在在哪个阶段、任务是什么'用它。只读。",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "description": "带出的最近审计操作条数(默认10)"}}, "additionalProperties": False}},
    {"name": "sim_strategy_log",
     "description": "编排器策略决策链(读 strategy_decisions.jsonl 末 n 条):相位流转+触发原因+采用的恢复策略(A/B/D/E/F)+第几次尝试。看'为什么进 RECOVER、换了什么策略、试了几次'用它。只读。",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "description": "条数(默认12)"}}, "additionalProperties": False}},
    {"name": "sim_orchestrator_log",
     "description": "编排器运行日志(读 orchestrator_v3.3.jsonl 末 n 条):OBSERVE→ANALYZE→DETECT... 状态机流转、存活进程数(alive)、是否冻结(frozen)。看'编排器最近在做什么'用它。只读。",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "description": "条数(默认20)"}}, "additionalProperties": False}},
    {"name": "sim_recent_ops",
     "description": "Claude 审计操作流水(读 claude_operations.jsonl 末 n 条):经审计通道的操作(相位/目标/动作)。看'最近对模拟动过什么'用它。只读。",
     "inputSchema": {"type": "object", "properties": {"n": {"type": "integer", "description": "条数(默认15)"}}, "additionalProperties": False}},
    {"name": "open_monitor",
     "description": "打开 Web 看板(web_monitor.py, 默认8080):各 case 实时进度/温度/异常大屏。用户说'打开看板/大屏/看盘'时用它。只看不改、不下发操作。",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "sim_exec",
     "description": "【唯一写门·需用户弹窗批准】经 claude_interface.py 审计通道执行一条命令(可执行文件白名单[含 packmol/mpirun/lmp_mpi/python3/cp/mv/rm/kill 等]+shell=False 防注入+逐条写审计日志)。用户确认方案后直接逐步调用执行;每条都会触发 dsh 弹窗,用户批准才执行。纪律:①调用前必须在对话里讲清做什么、有什么后果;②拒绝即终止——绝不换工具/换路径绕过、不重试同一命令;③长任务(LAMMPS 模拟/编排器等超 300s 的)必须 background=true 后台起,拿回 PID+日志路径后用 sim_status/看板盯;④要 cd 的场景用 cwd 参数(shell 元字符 ; | && < 不生效)。参数 cmd(命令)、description(进弹窗和审计日志,写清目的)、可选 cwd(工作目录)、background(后台)、log(后台日志路径)。",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string", "description": "要执行的命令(可执行文件须在白名单内;shell 元字符不生效,重定向/管道/串联不可用)"},
         "description": {"type": "string", "description": "操作说明(进 dsh 确认弹窗和审计日志,写清目的与后果)"},
         "cwd": {"type": "string", "description": "工作目录(可选;需要在某个 case 目录里跑时用它,而非 cd)"},
         "background": {"type": "boolean", "description": "true=后台启动(exec_bg,立即返回 PID+日志路径),LAMMPS/编排器等长任务必须用"},
         "log": {"type": "string", "description": "后台模式的日志文件路径(可选,默认 <cwd>/exec_bg_<时间戳>.log)"}
     }, "required": ["cmd"], "additionalProperties": False}},
    {"name": "read_paper",
     "description": "读一篇文献(PDF/txt/md/docx)返回正文文本，供【Mode B 文献解读】:解读研究意图、设计建模思路(结构/组分/力场/盒子)与动力学思路(系综/温压程序/timestep/平衡与生产)。用户丢来一篇文献要'解读/建模思路/动力学方案'时用它。参数 path(文件绝对路径)、可选 max_chars。只读、不写。",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "文献文件绝对路径(PDF/txt/md/docx)"},
         "max_chars": {"type": "integer", "description": "返回正文最大字符数(默认60000，超出截断)"}
     }, "required": ["path"], "additionalProperties": False}},
]
HANDLERS = {
    "sim_status": sim_status,
    "sim_context": sim_context,
    "sim_strategy_log": sim_strategy_log,
    "sim_orchestrator_log": sim_orchestrator_log,
    "sim_recent_ops": sim_recent_ops,
    "open_monitor": open_monitor,
    "sim_exec": sim_exec,
    "read_paper": read_paper,
}

# ---------- JSON-RPC over stdio ----------
def send(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION_FALLBACK
        send({"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pv,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "mdsim", "version": "0.1.0"}}})
    elif method in ("notifications/initialized", "initialized"):
        pass
    elif method == "ping":
        send({"jsonrpc": "2.0", "id": mid, "result": {}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name"); args = params.get("arguments") or {}
        fn = HANDLERS.get(name)
        if fn is None:
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "未知工具: %s" % name}], "isError": True}})
            return
        try:
            data = fn(args)
            _toolcall_log(name, args, data)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "structuredContent": data}})
        except Exception as ex:
            log("tool error: " + traceback.format_exc())
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text", "text": "工具执行出错: %s" % ex}], "isError": True}})
    else:
        if mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}})

def main():
    log("mdsim MCP server 启动(只读,mode=%s)" % MODE)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception as ex:
            log("bad json: %s" % ex); continue
        try:
            handle(msg)
        except Exception:
            log("handle error: " + traceback.format_exc())

if __name__ == "__main__":
    main()
