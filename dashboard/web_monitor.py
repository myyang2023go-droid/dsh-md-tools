#!/usr/bin/env python3
"""Web Monitor v3.4 — 全链路状态面板（含 Agent 关系 + 观测日志流）"""
import os, sys, json, time, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 运行前通过环境变量指向你的部署目录(见 README)
BASE = os.environ.get("AGENT_KIT_DIR", os.path.expanduser("~/agent_deploy_kit"))
STATE_FILE = os.path.join(BASE, ".v3.3_state.json")
RUN_CASE_BASE = os.environ.get("RUN_CASE_DIR", os.path.join(BASE, "production"))
DB_FILE = os.path.join(BASE, ".v3.3_strategy_db.json")

# 主题同步:跟随 dsh 侧 .dsh/settings.yaml 的 ui-theme.preference(dark 时对页面做调色板替换)
DSH_SETTINGS = os.environ.get("DSH_SETTINGS", os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.dsh', 'settings.yaml'))

# ── 多主题系统 ─────────────────────────────────────────────
# 浅色系源码 hex(顺序固定,各调色板按同序给出替换目标;顺序敏感:6 位 hex 先于 3 位短形式)
_LIGHT_SRC = [
    '#ffffff', '#f5f6f7', '#0f1115', '#353638', '#61666b', '#81868c', '#43454a',
    '#e1e5ee', '#ebedf0', '#4176e6', '#679efe', '#22c55e', '#f59e0b', '#ef4444',
    '#e6faed', '#fef2f2', '#fef5e7', '#edf3fe', '#e4edfd', '#dcdfe4', '#e5e5e5',
    '#d4d4d4', 'rgba(255,255,255,.92)', 'rgba(255,255,255,.85)', '#7c3aed',
    'rgba(0,0,0,.05)', '#fff}',
]

def _mk_palette(targets):
    return list(zip(_LIGHT_SRC, targets))

_PALETTES = {
    # 深色:对齐 DSH 暗色(中性灰 #151517 底 / #1b1b1c 面板 / rgba(255,255,255,.06) 边)
    'dark': _mk_palette([
        '#1b1b1c', '#151517', '#f9fafb', '#d6d6da', '#a3a3ab', '#7a7a82', '#3a3a3e',
        '#2c2c2e', '#262628', '#6b8afd', '#93adff', '#3fe0a0', '#ffce6b', '#ff6b6b',
        '#12251d', '#2a1616', '#2a2210', '#1a2030', '#232c42', '#3a3a3e', '#3a3a3e',
        '#4a4a50', 'rgba(21,21,23,.92)', 'rgba(27,27,28,.85)', '#a78bfa',
        'rgba(0,0,0,.40)', '#1b1b1c}',
    ]),
    # 深海:深灰蓝(对齐《AI+MD智能体平台_投资介绍》暗色变量)
    'ocean': _mk_palette([
        '#141b2d', '#05070f', '#eaf0fb', '#c6d2e8', '#9aa8c4', '#7d8cab', '#3a4a74',
        '#263152', '#1e2740', '#5ea8ff', '#8fc2ff', '#3fe0a0', '#ffce6b', '#ff6b6b',
        '#0d2b22', '#2e1618', '#2e2410', '#14203c', '#1b2a4e', '#3a4a74', '#3a4a74',
        '#4a5d8f', 'rgba(5,7,15,.92)', 'rgba(20,27,45,.85)', '#b490ff',
        'rgba(0,0,0,.40)', '#141b2d}',
    ]),
    # 暗紫
    'purple': _mk_palette([
        '#1a1426', '#100c1a', '#efe9fa', '#cfc3e4', '#a394c2', '#7f6f9e', '#4a3d6e',
        '#2d2342', '#251c38', '#a78bfa', '#c4b5fd', '#3fe0a0', '#ffce6b', '#ff6b6b',
        '#14251f', '#2b161c', '#2a2113', '#241a3d', '#2f2350', '#4a3d6e', '#4a3d6e',
        '#5d4e85', 'rgba(16,12,26,.92)', 'rgba(26,20,38,.85)', '#c4b5fd',
        'rgba(0,0,0,.40)', '#1a1426}',
    ]),
    # 墨绿
    'forest': _mk_palette([
        '#12211b', '#0a1410', '#e8f4ee', '#c2d8cd', '#93b0a3', '#749184', '#35594a',
        '#1e352b', '#1a2d24', '#34d399', '#6ee7b7', '#3fe0a0', '#ffce6b', '#ff6b6b',
        '#10281e', '#2a1616', '#2a2110', '#122a20', '#18382a', '#35594a', '#35594a',
        '#47735f', 'rgba(10,20,16,.92)', 'rgba(18,33,27,.85)', '#6ee7b7',
        'rgba(0,0,0,.40)', '#12211b}',
    ]),
}

_WAVE_CSS = """body::before,body::after{content:"";position:fixed;left:0;right:0;bottom:0;height:@H@;pointer-events:none;z-index:-1;background-repeat:repeat-x;background-position:bottom;background-size:1440px 100%;}
body::before{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 120'%3E%3Cpath fill='%23@C1@' fill-opacity='@O1@' d='M0,64 C240,96 480,32 720,64 C960,96 1200,32 1440,64 L1440,120 L0,120 Z'/%3E%3C/svg%3E");animation:dsh-wave 24s linear infinite;}
body::after{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 120'%3E%3Cpath fill='%23@C2@' fill-opacity='@O2@' d='M0,72 C260,44 520,100 780,72 C1040,44 1240,96 1440,72 L1440,120 L0,120 Z'/%3E%3C/svg%3E");animation:dsh-wave 34s linear infinite reverse;}
@keyframes dsh-wave{from{background-position-x:0}to{background-position-x:1440px}}
"""

def _waves(c1, o1, c2, o2, h):
    return (_WAVE_CSS.replace('@C1@', c1).replace('@O1@', o1)
                     .replace('@C2@', c2).replace('@O2@', o2).replace('@H@', h))

def _wrap(body_css, wave_css):
    return '<style id="dsh-glass">' + body_css + wave_css + '</style>'

_THEME_CSS = {
    'light': _wrap(
        'html{background:#f4f6fb;}'
        'body{background:radial-gradient(1200px 800px at 20% -10%,#ffffff 0%,#f4f6fb 60%) fixed;}'
        '.card,.progress-wrap,.chart-wrap,.log-wrap,.agent-wrap{background:rgba(255,255,255,.9);'
        'backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-radius:10px;'
        'border-top:1px solid rgba(30,60,120,.12);border-right:1px solid rgba(30,60,120,.12);'
        'border-bottom:1px solid rgba(30,60,120,.12);box-shadow:0 6px 20px rgba(30,60,120,.08);}'
        '.agent-card,.recovery-card{background:rgba(255,255,255,.72);border:1px solid rgba(30,60,120,.10);border-radius:8px;}'
        'h1{background:linear-gradient(92deg,#2563eb,#7c3aed 75%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}'
        '.progress-fill{box-shadow:0 0 8px rgba(37,99,235,.30);}',
        _waves('2563eb', '.13', '7c3aed', '.10', '40vh')),
    'dark': _wrap(
        'html{background:#151517;}'
        'body{background:radial-gradient(1200px 800px at 20% -10%,#1a1a1d 0%,#151517 55%) fixed;}'
        '.card,.progress-wrap,.chart-wrap,.log-wrap,.agent-wrap{background:rgba(27,27,28,.85);'
        'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);'
        'border-top:1px solid rgba(255,255,255,.08);border-right:1px solid rgba(255,255,255,.08);'
        'border-bottom:1px solid rgba(255,255,255,.08);box-shadow:0 8px 24px rgba(0,0,0,.40);}'
        '.agent-card,.recovery-card{background:rgba(18,18,20,.6);border:1px solid rgba(255,255,255,.06);}'
        'h1{background:linear-gradient(92deg,#8fa8ff,#a78bfa 70%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}',
        _waves('6b8afd', '.14', 'a78bfa', '.10', '40vh')),
    'ocean': _wrap(
        'html{background:#05070f;}'
        'body{background:radial-gradient(1200px 800px at 20% -10%,#0d1526 0%,#05070f 55%) fixed;}'
        '.card,.progress-wrap,.chart-wrap,.log-wrap,.agent-wrap{background:rgba(20,27,45,.72);'
        'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);'
        'border-top:1px solid rgba(90,120,200,.22);border-right:1px solid rgba(90,120,200,.22);'
        'border-bottom:1px solid rgba(90,120,200,.22);box-shadow:0 8px 24px rgba(0,0,0,.35);}'
        '.agent-card,.recovery-card{background:rgba(14,20,36,.6);border:1px solid rgba(90,120,200,.16);}'
        'h1{background:linear-gradient(92deg,#7db9ff,#b490ff 70%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}',
        _waves('5ea8ff', '.20', 'b490ff', '.15', '44vh')),
    'purple': _wrap(
        'html{background:#100c1a;}'
        'body{background:radial-gradient(1200px 800px at 20% -10%,#1c1430 0%,#100c1a 55%) fixed;}'
        '.card,.progress-wrap,.chart-wrap,.log-wrap,.agent-wrap{background:rgba(26,20,38,.72);'
        'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);'
        'border-top:1px solid rgba(167,139,250,.20);border-right:1px solid rgba(167,139,250,.20);'
        'border-bottom:1px solid rgba(167,139,250,.20);box-shadow:0 8px 24px rgba(0,0,0,.35);}'
        '.agent-card,.recovery-card{background:rgba(18,13,28,.6);border:1px solid rgba(167,139,250,.14);}'
        'h1{background:linear-gradient(92deg,#c4b5fd,#f0abfc 70%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}',
        _waves('a78bfa', '.18', 'f0abfc', '.13', '42vh')),
    'forest': _wrap(
        'html{background:#0a1410;}'
        'body{background:radial-gradient(1200px 800px at 20% -10%,#10231a 0%,#0a1410 55%) fixed;}'
        '.card,.progress-wrap,.chart-wrap,.log-wrap,.agent-wrap{background:rgba(18,33,27,.72);'
        'backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);'
        'border-top:1px solid rgba(52,211,153,.18);border-right:1px solid rgba(52,211,153,.18);'
        'border-bottom:1px solid rgba(52,211,153,.18);box-shadow:0 8px 24px rgba(0,0,0,.35);}'
        '.agent-card,.recovery-card{background:rgba(12,24,18,.6);border:1px solid rgba(52,211,153,.13);}'
        'h1{background:linear-gradient(92deg,#6ee7b7,#3fd4dc 70%);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}',
        _waves('34d399', '.16', '3fd4dc', '.12', '42vh')),
}

def _dsh_theme():
    try:
        with open(DSH_SETTINGS, encoding='utf-8') as f:
            m = re.search(r'ui-theme:\s*\n\s*preference:\s*(\w+)', f.read())
            return m.group(1).lower() if m else 'light'
    except Exception:
        return 'light'

def _effective_theme(cookie_header=''):
    pref = 'auto'
    if cookie_header:
        m = re.search(r'dash-theme=([\w-]+)', cookie_header)
        if m:
            pref = m.group(1)
    if pref in _THEME_CSS:
        return pref
    return 'dark' if _dsh_theme() == 'dark' else 'light'

def _apply_theme(html, cookie_header=''):
    theme = _effective_theme(cookie_header)
    if '<meta name="dsh-theme"' not in html and '</head>' in html:
        html = html.replace('</head>', '<meta name="dsh-theme" content="%s"></head>' % theme, 1)
    for old, new in _PALETTES.get(theme, []):
        html = html.replace(old, new)
    css = _THEME_CSS.get(theme)
    if css and '</head>' in html and 'id="dsh-glass"' not in html:
        html = html.replace('</head>', css + '</head>', 1)
    return html

def _current_prod_dir():
    """每次从 state 读取当前任务的 prod_dir，实现看板与工作区解耦。"""
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get("task", {}).get("prod_dir", os.path.join(BASE, "production/small_verify_2600"))
    except Exception:
        return os.path.join(BASE, "production/small_verify_2600")

SCHEDULE = [
    (0,       100000,  300.0, 300.0),
    (100000,  400000,  300.0, 600.0),
    (400000,  700000,  600.0, 900.0),
    (700000,  1000000, 900.0, 1200.0),
    (1000000, 1350000, 1200.0, 1200.0),
]
TOTAL_STEPS = 1350000

def parse_kinetic_stages(prod_dir):
    """解析 production.in / production_slow.in 中的阶段注释 (# Stage X: ...) 和对应的 run 步长"""
    for inp_name in ("production_slow.in", "production.in"):
        inp_path = os.path.join(prod_dir, inp_name)
        if os.path.exists(inp_path):
            break
    else:
        return []
    try:
        with open(inp_path) as f:
            lines = f.readlines()
        stages = []
        current_stage = None
        for line in lines:
            line_stripped = line.strip()
            # 匹配阶段注释，如 # Stage 1: NVT equilibration 或 # ==================== Stage 2: NVT hold at 1200K ====================
            m = re.match(r'#+\s*(Stage\s*\d+.*?)(?:\s*=+\s*)?$', line_stripped, re.I)
            if m:
                current_stage = m.group(1).strip()
            if line_stripped.lower().startswith('run ') and current_stage:
                try:
                    nsteps = int(line_stripped.split()[1])
                    stages.append((current_stage, nsteps))
                    current_stage = None
                except Exception:
                    pass
        return stages
    except Exception:
        return []

def current_kinetic_stage(prod_dir, step):
    """根据当前 step 判断处于 production.in 的哪个动力学阶段"""
    stages = parse_kinetic_stages(prod_dir)
    if not stages:
        return {"stage": "UNKNOWN", "stage_desc": "", "stage_progress": "0/0", "stage_target": ""}
    cumulative = 0
    for idx, (name, nsteps) in enumerate(stages):
        cumulative += nsteps
        if step <= cumulative:
            progress = f"{step}/{cumulative}"
            return {
                "stage": name,
                "stage_desc": f"阶段 {idx+1}/{len(stages)}",
                "stage_progress": progress,
                "stage_target": f"run {nsteps}"
            }
    # 超出最后阶段
    return {
        "stage": stages[-1][0],
        "stage_desc": f"阶段 {len(stages)}/{len(stages)}",
        "stage_progress": f"{step}/{cumulative}",
        "stage_target": "completed"
    }

def target_temp(step):
    for s, e, ts, te in SCHEDULE:
        if s <= step <= e:
            return ts if e == s else ts + (step - s) / (e - s) * (te - ts)
    return 1073.0

def parse_log_tail(log_path, n=40):
    if not log_path or not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2); size = f.tell()
            buf = b''
            while size > 0 and len(buf.split(b'\n')) <= n + 5:
                chunk = min(4096, size)
                f.seek(size - chunk); buf = f.read(chunk) + buf; size -= chunk
            lines = buf.decode('utf-8', errors='ignore').split('\n')
            rows = []
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 8 and parts[0].isdigit():
                    try:
                        rows.append({'step': int(parts[0]), 'temp': float(parts[1]),
                                     'etotal': float(parts[2]), 'pe': float(parts[3]),
                                     'ke': float(parts[4]), 'press': float(parts[5]),
                                     'vol': float(parts[6]), 'density': float(parts[7])})
                    except ValueError:
                        pass
            return rows[-n:]
    except Exception:
        return []

def parse_species(species_path):
    """解析 ReaxFF species 文件，返回最新一帧的物种统计。"""
    if not species_path or not os.path.exists(species_path):
        return {}
    try:
        with open(species_path, 'r', errors='ignore') as f:
            lines = f.readlines()
        if not lines:
            return {}
        last_header = None
        last_data = None
        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                last_header = line.strip()
                if i + 1 < len(lines):
                    last_data = lines[i + 1].strip()
        if not last_header or not last_data:
            return {}
        header_parts = last_header.lstrip('#').strip().split()
        data_parts = last_data.split()
        if len(header_parts) != len(data_parts):
            return {}
        result = {}
        for h, d in zip(header_parts, data_parts):
            try:
                result[h] = int(d)
            except Exception:
                try:
                    result[h] = float(d)
                except Exception:
                    result[h] = d
        species_counts = {}
        for k, v in result.items():
            if k not in ('Timestep', 'No_Moles', 'No_Specs') and isinstance(v, int):
                species_counts[k] = v
        top_species = sorted(species_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        return {
            'timestep': result.get('Timestep', 0),
            'no_moles': result.get('No_Moles', 0),
            'no_specs': result.get('No_Specs', 0),
            'top_species': [{'name': k, 'count': v} for k, v in top_species],
        }
    except Exception as e:
        return {'error': str(e)}

def parse_atom_count(log_path):
    """从日志开头解析实际运行原子数（如 'with 2576 atoms'）"""
    if not log_path or not os.path.exists(log_path):
        return 0
    try:
        with open(log_path, 'rb') as f:
            # 只读前 8192 字节找原子数
            buf = f.read(8192).decode('utf-8', errors='ignore')
        # 优先匹配 Loop time 行中的 with X atoms
        m = re.search(r'with\s+(\d+)\s+atoms', buf)
        if m:
            return int(m.group(1))
        # 回退到 reading atoms ...\n  X atoms
        m = re.search(r'reading atoms\s*\.\.\.\s*\n\s*(\d+)\s+atoms', buf)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0

def get_lmp_pids(prod_dir):
    pids = []
    if not prod_dir:
        return pids
    target = os.path.abspath(prod_dir)
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/cmdline", 'rb') as f:
                    cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                if "lmp_mpi" not in cmdline:
                    continue
                cwd = os.readlink(f"/proc/{pid_dir}/cwd")
                if os.path.abspath(cwd) == target:
                    pids.append(int(pid_dir))
            except (PermissionError, FileNotFoundError, OSError):
                pass
    except Exception:
        pass
    return pids

def parse_orchestrator_log(n=30):
    log_path = os.path.join(BASE, "logs", "orchestrator_v3.3.jsonl")
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            buf = b''
            while size > 0 and len(buf.split(b'\n')) <= n + 5:
                chunk = min(8192, size)
                f.seek(size - chunk)
                buf = f.read(chunk) + buf
                size -= chunk
            lines = buf.decode('utf-8', errors='ignore').strip().split('\n')
            logs = []
            for line in lines[-n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    logs.append({
                        'time': entry.get('ts', ''),
                        'level': entry.get('level', 'INFO'),
                        'msg': entry.get('msg', '')
                    })
                except (json.JSONDecodeError, Exception):
                    pass
            return logs
    except Exception:
        return []

def parse_strategy_log(n=20):
    log_path = os.path.join(BASE, "logs", "strategy_decisions.jsonl")
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            buf = b''
            while size > 0 and len(buf.split(b'\n')) <= n + 5:
                chunk = min(8192, size)
                f.seek(size - chunk)
                buf = f.read(chunk) + buf
                size -= chunk
            lines = buf.decode('utf-8', errors='ignore').strip().split('\n')
            logs = []
            for line in lines[-n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    logs.append({
                        'time': entry.get('ts', ''),
                        'phase_from': entry.get('phase_from', ''),
                        'phase_to': entry.get('phase_to', ''),
                        'trigger': entry.get('trigger', ''),
                        'decision': entry.get('decision', ''),
                        'details': entry.get('details', {})
                    })
                except (json.JSONDecodeError, Exception):
                    pass
            return logs
    except Exception:
        return []

def get_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def scan_tasks():
    """扫描运行案例目录(RUN_CASE_DIR)下的所有任务，按时间分组"""
    today = time.strftime('%Y%m%d')
    active = []
    today_stopped = []
    history = []
    if not os.path.exists(RUN_CASE_BASE):
        return {"active": active, "today_stopped": today_stopped, "history": history, "current_case_id": ""}

    # 读取当前 orchestrator 管理的任务
    current_case_id = ""
    try:
        state = get_state()
        current_case_id = state.get("task", {}).get("case_id", "")
    except Exception:
        pass

    try:
        for date_dir in sorted(os.listdir(RUN_CASE_BASE), reverse=True):
            date_path = os.path.join(RUN_CASE_BASE, date_dir)
            if not os.path.isdir(date_path):
                continue
            for task_dir in sorted(os.listdir(date_path), reverse=True):
                task_path = os.path.join(date_path, task_dir)
                if not os.path.isdir(task_path):
                    continue
                # 查找活跃日志
                log_candidates = [
                    os.path.join(task_path, "production.stdout"),
                    os.path.join(task_path, "production_slow.stdout"),
                    os.path.join(task_path, "log.lammps"),
                    os.path.join(task_path, "log_production_slow.lammps"),
                    os.path.join(task_path, "production.log")
                ]
                active_log = None
                for lc in log_candidates:
                    if os.path.exists(lc) and os.path.getsize(lc) > 0:
                        active_log = lc
                        break
                if not active_log:
                    continue
                rows = parse_log_tail(active_log, 5)
                latest = rows[-1] if rows else {}
                pids = get_lmp_pids(task_path)
                task = {
                    'case_id': task_dir,
                    'prod_dir': task_path,
                    'date': date_dir,
                    'step': latest.get('step', 0),
                    'temp': round(latest.get('temp', 0), 1),
                    'etotal': round(latest.get('etotal', 0), 1),
                    'alive': len(pids) > 0,
                    'pids_count': len(pids),
                    'last_modified': time.strftime('%H:%M:%S', time.localtime(os.path.getmtime(active_log))),
                    'is_current': task_dir == current_case_id
                }
                if task['alive']:
                    active.append(task)
                elif date_dir == today:
                    today_stopped.append(task)
                else:
                    history.append(task)
    except Exception:
        pass
    return {"active": active, "today_stopped": today_stopped, "history": history, "current_case_id": current_case_id}

def get_orchestrator_pid():
    """扫描当前运行的 orchestrator 进程"""
    try:
        for pid_dir in os.listdir("/proc"):
            if not pid_dir.isdigit():
                continue
            try:
                with open(f"/proc/{pid_dir}/cmdline", 'rb') as f:
                    cmdline = f.read().replace(b'\x00', b' ').decode('utf-8', errors='ignore')
                if "orchestrator.py" in cmdline and "v3.3" in cmdline:
                    return int(pid_dir)
            except (PermissionError, FileNotFoundError, OSError):
                pass
    except Exception:
        pass
    return None

def get_monitor_daemon_health(daemon_pid, prod_dir):
    """检查 monitor daemon 的健康状态"""
    result = {"pid": daemon_pid, "alive": False, "last_write_sec": None, "healthy": False}
    if daemon_pid:
        result["alive"] = os.path.exists(f"/proc/{daemon_pid}")
    if prod_dir:
        live_file = os.path.join(prod_dir, ".monitor_live.json")
        if os.path.exists(live_file):
            result["last_write_sec"] = int(time.time() - os.path.getmtime(live_file))
            result["healthy"] = result["last_write_sec"] < 120  # 2 min threshold
    return result

def get_dsh_layer_status():
    """真实架构状态:dsh 裁决层(对话服务+审计通道) 与 监控通道(monitor_agent/定时巡检)。
    旧 orchestrator 进程已于 2026-06-30 停心跳,判断职责由 dsh 接管,看板改显此数据。"""
    import socket
    res = {
        'dsh_web_alive': False,
        'dsh_web_port': 3091,
        'last_audit_sec': None,
        'last_monitor_agent_sec': None,
        'push_cron': False,
        'orchestrator_note': '原 orchestrator 已于 2026-06-30 停心跳,判断职责由 dsh 裁决层接管',
    }
    try:
        s = socket.create_connection(('127.0.0.1', 3091), timeout=1)
        s.close()
        res['dsh_web_alive'] = True
    except Exception:
        pass
    audit = os.path.join(BASE, 'logs', 'claude_operations.jsonl')
    if os.path.exists(audit):
        now = time.time()
        res['last_audit_sec'] = int(now - os.path.getmtime(audit))
        try:
            from datetime import datetime
            last_ts = None
            with open(audit, encoding='utf-8', errors='replace') as f:
                for line in f:
                    if 'monitor_agent' in line:
                        try:
                            ts = json.loads(line).get('ts')
                            if ts:
                                last_ts = ts
                        except Exception:
                            pass
            if last_ts:
                s = str(last_ts)
                for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(s[:26], fmt)
                        res['last_monitor_agent_sec'] = int((datetime.now() - dt).total_seconds())
                        break
                    except ValueError:
                        continue
        except Exception:
            pass
    try:
        import subprocess
        out = subprocess.check_output(['crontab', '-l'], stderr=subprocess.DEVNULL, timeout=3).decode('utf-8', 'replace')
        res['push_cron'] = 'md_push_driver' in out
    except Exception:
        pass
    return res

def get_agent_chain(state):
    """构建 agent 执行链，展示每个子智能体的最近运行详情"""
    chain = []
    agent_names = {
        "preflight": "预检 Agent",
        "launch": "启动 Agent",
        "monitor": "监控 Agent",
        "recover": "修复 Agent",
        "preemptive_recover": "预防修复 Agent",
        "analyze": "分析 Agent"
    }
    agents = state.get("agents", {})
    for key, label in agent_names.items():
        data = agents.get(key, {})
        if not data:
            continue
        entry = {
            "name": key,
            "label": label,
            "status": data.get("status", data.get("success", "N/A")),
            "step": data.get("step", "N/A"),
            "error": data.get("error", ""),
            "details": {}
        }
        if key == "preflight":
            entry["details"]["issues"] = data.get("issues", [])
            entry["details"]["fixes"] = data.get("fixes_applied", [])
            entry["details"]["pass"] = data.get("pass", False)
        elif key == "launch":
            entry["details"]["pids"] = data.get("pids", [])
            entry["details"]["prod_dir"] = data.get("prod_dir", "")
        elif key in ("recover", "preemptive_recover"):
            entry["details"]["strategy"] = data.get("strategy", "")
            entry["details"]["strategy_name"] = data.get("strategy_name", "")
            entry["details"]["changes"] = data.get("changes", "")
            entry["details"]["root_cause"] = data.get("root_cause", "")
        elif key == "analyze":
            entry["details"]["char_yield"] = data.get("char_yield", 0)
            entry["details"]["p_retention"] = data.get("p_retention", 0)
        chain.append(entry)
    return chain

def get_status(prod_dir=None):
    state = get_state()
    monitor = state.get('agents', {}).get('monitor', {})
    phase = state.get('phase', 'UNKNOWN')
    analyze_result = state.get('agents', {}).get('analyze', {})

    # 动态读取当前任务工作区，实现 Agent 与 Case 分离
    if prod_dir is None:
        prod_dir = state.get('task', {}).get('prod_dir', _current_prod_dir())
    log_candidates = [
        os.path.join(prod_dir, "production.stdout"),
        os.path.join(prod_dir, "production_slow.stdout"),
        os.path.join(prod_dir, "log.lammps"),
        os.path.join(prod_dir, "log_production_slow.lammps"),
        os.path.join(prod_dir, "production.log")
    ]
    active_log = None
    for lc in log_candidates:
        if os.path.exists(lc) and os.path.getsize(lc) > 0:
            active_log = lc
            break

    rows = parse_log_tail(active_log, 40) if active_log else []
    latest = rows[-1] if rows else {}
    atom_count = parse_atom_count(active_log) if active_log else 0

    # 动力学阶段解析与总步数
    kinetic = current_kinetic_stage(prod_dir, latest.get('step', 0))
    stage_total = sum(n for _, n in parse_kinetic_stages(prod_dir))
    total_steps = stage_total if stage_total > 0 else TOTAL_STEPS

    # Completion override: ignore stale/overwritten log when finished
    if phase in ('DONE', 'FAILED'):
        step = TOTAL_STEPS
        progress_pct = 100.0
        remaining_sec = 0
        alive = False
        pids = []
        speed = 0
        # Use last known monitor values if log is stale/overwritten
        temp = monitor.get('temp', latest.get('temp', 0.0))
        density = monitor.get('density', latest.get('density', 0.0))
    else:
        step = latest.get('step', 0)
        temp = latest.get('temp', 0.0)
        density = latest.get('density', 0.0)
        pids = get_lmp_pids(prod_dir)
        alive = len(pids) > 0

        speed = 0
        remaining_sec = 0
        if len(rows) >= 2 and active_log:
            dt = rows[-1]['step'] - rows[0]['step']
            try:
                stat = os.stat(active_log)
                age = time.time() - stat.st_mtime
                speed = dt / max(age, 1) if age > 0 else 0
            except Exception:
                speed = 0
        if speed > 0 and step < total_steps:
            remaining_sec = (total_steps - step) / speed
        progress_pct = round(step / total_steps * 100, 1)
    
    # 物种分析
    species_file = state.get('task', {}).get('species_file', '')
    species_path = os.path.join(prod_dir, species_file) if species_file else None
    species_data = parse_species(species_path)

    # Agent 全链路状态
    agents = state.get('agents', {})
    agent_states = {}
    for name, data in agents.items():
        agent_states[name] = {
            'success': data.get('success', 'N/A') if isinstance(data, dict) else 'N/A',
            'status': data.get('status', 'N/A') if isinstance(data, dict) else 'N/A',
            'step': data.get('step', 'N/A') if isinstance(data, dict) else 'N/A',
            'error': data.get('error', '') if isinstance(data, dict) else '',
        }
    
    # 观测日志流（最近 monitor 的 anomalies）
    monitor_log = []
    for a in monitor.get('anomalies', []):
        monitor_log.append({
            'time': monitor.get('timestamp', ''),
            'type': a.get('type', ''),
            'severity': a.get('severity', ''),
            'message': a.get('message', '')
        })
    
    # 策略库状态
    db = {}
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE) as f:
                db = json.load(f)
        except Exception:
            pass
    
    # Token usage billing
    token_usage = {}
    token_path = os.path.join(BASE, '.token_usage.json')
    if os.path.exists(token_path):
        try:
            with open(token_path, 'r') as f:
                token_usage = json.load(f)
        except Exception:
            pass

    # Routine / Pipeline status
    routine_data = {}
    routine_path = os.path.join(BASE, '.routine_state.json')
    if os.path.exists(routine_path):
        try:
            with open(routine_path, 'r') as f:
                routine_data = json.load(f)
        except Exception:
            pass

    # Task Queue (upcoming tasks)
    task_queue = []
    queue_path = os.path.join(BASE, '.task_queue.json')
    if os.path.exists(queue_path):
        try:
            with open(queue_path, 'r') as f:
                q = json.load(f)
                task_queue = q.get('queue', [])
        except Exception:
            pass

    # Orchestrator & Daemon health
    orch_pid = get_orchestrator_pid()
    last_tick = state.get('last_tick')
    orch_healthy = False
    if last_tick:
        try:
            from datetime import datetime
            # Python 3.6 compatible parse (no fromisoformat)
            if '.' in last_tick:
                dt = datetime.strptime(last_tick, "%Y-%m-%dT%H:%M:%S.%f")
            else:
                dt = datetime.strptime(last_tick, "%Y-%m-%dT%H:%M:%S")
            orch_healthy = (datetime.now() - dt).total_seconds() < 120
        except Exception:
            pass
    daemon_pid = state.get('_monitor_daemon_pid')
    daemon_health = get_monitor_daemon_health(daemon_pid, prod_dir)
    agent_chain = get_agent_chain(state)

    return {
        'step': step,
        'atom_count': atom_count,
        'temp': round(temp, 1),
        'target_temp': round(target_temp(step), 1),
        'density': round(density, 6),
        'etotal': round(latest.get('etotal', 0), 1),
        'pe': round(latest.get('pe', 0), 1),
        'ke': round(latest.get('ke', 0), 1),
        'press': round(latest.get('press', 0), 1),
        'vol': round(latest.get('vol', 0), 1),
        'phase': phase,
        'kinetic_stage': kinetic['stage'],
        'kinetic_stage_desc': kinetic['stage_desc'],
        'kinetic_stage_progress': kinetic['stage_progress'],
        'kinetic_stage_target': kinetic['stage_target'],
        'monitor_subphase': state.get('monitor_subphase', 'OBSERVE'),
        'monitor_subphase_history': state.get('monitor_subphase_history', [])[-20:],
        'monitor_status': monitor.get('status', 'UNKNOWN'),
        'risk_score': monitor.get('risk_score', 0),
        'anomalies_count': len(monitor.get('anomalies', [])),
        'trends': monitor.get('trends', {}),
        'alive': alive,
        'pids_count': len(pids),
        'monitor_daemon_pid': daemon_pid,
        'total_steps': total_steps,
        'progress_pct': progress_pct,
        'speed': round(speed, 1),
        'remaining_sec': int(remaining_sec),
        'char_yield': round(analyze_result.get('char_yield', 0), 2),
        'p_retention': round(analyze_result.get('p_retention', 0), 2),
        'history': [{'step': r['step'], 'temp': r['temp'], 'etotal': r['etotal'],
                     'pe': r['pe'], 'ke': r['ke'], 'vol': r['vol'], 'press': r['press']} for r in rows],
        'timestamp': time.strftime('%H:%M:%S'),
        'agents': agent_states,
        'monitor_log': monitor_log,
        'recovery_history': state.get('recovery_history', []),
        'strategy_db': db.get('strategies', {}),
        'system_log': parse_orchestrator_log(30),
        'strategy_log': parse_strategy_log(20),
        'task': {
            'case_id': state.get('task', {}).get('case_id', ''),
            'prod_dir': state.get('task', {}).get('prod_dir', ''),
            'data_file': state.get('task', {}).get('data_file', ''),
            'ff_file': state.get('task', {}).get('ff_file', ''),
            'cores': state.get('task', {}).get('cores', 0),
            'species_file': state.get('task', {}).get('species_file', ''),
        },
        'species': species_data,
        'token_usage': token_usage,
        'routine': routine_data,
        'task_queue': task_queue,
        # New agent runtime fields
        'orchestrator_pid': orch_pid,
        'orchestrator_last_tick': last_tick,
        'orchestrator_healthy': orch_healthy,
        'monitor_daemon_healthy': daemon_health.get('healthy', False),
        'monitor_daemon_alive': daemon_health.get('alive', False),
        'monitor_daemon_last_write_sec': daemon_health.get('last_write_sec'),
        'agent_chain': agent_chain,
        'dsh_layer': get_dsh_layer_status(),
    }

# dsh 自动审批开关文件(dsh-md-auto-approve 插件每次审批请求时读它)
AUTO_APPROVE_FLAG = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '.dsh', 'auto-approve.json'))

def _read_auto_approve():
    try:
        with open(AUTO_APPROVE_FLAG, encoding='utf-8') as f:
            return json.load(f).get('enabled') is True
    except Exception:
        return False

def _write_auto_approve(enabled):
    with open(AUTO_APPROVE_FLAG, 'w', encoding='utf-8') as f:
        json.dump({'enabled': bool(enabled)}, f)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        # S4: no wildcard CORS — dashboard is same-origin; internal state stays
        # unreadable cross-origin.
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _auto_approve_response(self, data, status=200):
        # 例外:本机开关,允许 file:// 打开的 workbench 跨域读写
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        if urlparse(self.path).path == '/api/auto-approve':
            self._auto_approve_response({})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/auto-approve':
            try:
                n = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(n) or b'{}')
                enabled = body.get('enabled') is True
            except Exception:
                self._auto_approve_response({'error': 'bad body, want {"enabled": true|false}'}, 400)
                return
            _write_auto_approve(enabled)
            self._auto_approve_response({'enabled': enabled})
            return
        self._json_response({'error': 'not found'}, 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == '/api/auto-approve':
            self._auto_approve_response({'enabled': _read_auto_approve()})
            return

        if path in ('/workbench', '/workbench.html'):
            wb = os.path.join(os.path.dirname(__file__), 'workbench.html')
            if os.path.exists(wb):
                with open(wb, encoding='utf-8') as f:
                    html = _apply_theme(f.read(), self.headers.get('Cookie', ''))
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            else:
                self._json_response({'error': 'workbench.html not found'}, 404)
            return

        # 静态说明页:/pages/<name>.html(仅限 pages 目录下的 .html,防路径穿越)
        if path.startswith('/pages/'):
            name = path[len('/pages/'):]
            if re.fullmatch(r'[A-Za-z0-9_-]+\.html', name):
                fp = os.path.join(os.path.dirname(__file__), 'pages', name)
                if os.path.exists(fp):
                    with open(fp, encoding='utf-8') as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
                else:
                    self._json_response({'error': 'page not found'}, 404)
            else:
                self._json_response({'error': 'invalid page name'}, 400)
            return

        if path == '/api/tasks':
            self._json_response(scan_tasks())
            return

        if path == '/api/theme':
            self._json_response({'theme': _effective_theme(self.headers.get('Cookie', ''))})
            return

        if path == '/api/status':
            task_param = qs.get('task', [''])[0]
            if task_param:
                # 查找对应任务目录
                prod_dir = None
                all_tasks = scan_tasks()
                for group in ['active', 'today_stopped', 'history']:
                    for t in all_tasks.get(group, []):
                        if t['case_id'] == task_param:
                            prod_dir = t['prod_dir']
                            break
                    if prod_dir:
                        break
                if prod_dir:
                    self._json_response(get_status(prod_dir=prod_dir))
                else:
                    self._json_response({'error': 'task not found'}, 404)
            else:
                self._json_response(get_status())
            return

        html_name = 'simple.html' if path in ('/simple', '/simple.html') else 'index.html'
        html_path = os.path.join(os.path.dirname(__file__), 'static', html_name)
        if os.path.exists(html_path):
            with open(html_path, encoding='utf-8') as f:
                html = _apply_theme(f.read(), self.headers.get('Cookie', ''))
        else:
            html = "<h1>" + html_name + " not found</h1>"
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    # S4: bind localhost by default (set WEB_HOST=0.0.0.0 to expose on a LAN).
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    addr = (host, port)
    httpd = HTTPServer(addr, Handler)
    print(f"[WEB] Dashboard at http://{host}:{port}/ (set WEB_HOST=0.0.0.0 to expose on LAN)")
    httpd.serve_forever()
