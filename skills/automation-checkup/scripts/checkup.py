#!/usr/bin/env python3
"""自动化体检：只读检查本机用户级 LaunchAgents（以及可选的 hermes cron、crontab），出一页 Markdown 报告。

只读保证：本脚本只会执行 READ_ONLY_COMMANDS 里列出的几种查看命令，其他命令一律拒绝；
不加载、不停止、不重启任何任务，不改、不挪、不删任何文件。唯一会写的是报告文件本身。

用法：
    python3 checkup.py                       # 报告写到 ~/Documents/自动化体检/
    python3 checkup.py --out 报告.md          # 指定位置
    python3 checkup.py --stdout              # 直接打印报告
    python3 checkup.py --json 结果.json       # 另存一份结构化结果，给 agent 读
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ACT = "需要处理"
WARN = "注意"
OK = "正常"
SEVERITY_RANK = {OK: 0, WARN: 1, ACT: 2}

SKILL_DIR = Path(__file__).resolve().parents[1]

DEFAULT_CONFIG = {
    "exclude_patterns": ["com.apple.*"],
    "include_labels": [],
    "quiet_labels": [],
    "aliases": {},
    "tail_lines": 15,
    "grace_minutes": 15,
    "missed_runs_act": 3,
    "stale_hours_act": 24,
    "restart_runs_warn": 5,
    "restart_runs_act": 20,
    "log_size_warn_mb": 200,
    "recent_error_hours": 24,
}

# launchd 启动程序时用的默认 PATH（比终端里的短，这是很多「终端里能跑、定时就失败」的原因）
LAUNCHD_DEFAULT_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# ---------------------------------------------------------------------------
# 命令层：所有外部命令都从这里走，并且只放行查看类命令
# ---------------------------------------------------------------------------

READ_ONLY_COMMANDS = (
    "launchctl print <gui/UID/Label>",
    "launchctl print-disabled <gui/UID>",
    "hermes cron list",
    "crontab -l",
)


class ReadOnlyViolation(RuntimeError):
    pass


def assert_read_only(argv: list[str]) -> None:
    if not argv:
        raise ReadOnlyViolation("空命令")
    name = os.path.basename(argv[0])
    rest = list(argv[1:])
    if name == "launchctl" and len(rest) == 2 and rest[0] in ("print", "print-disabled"):
        return
    if name == "hermes" and rest == ["cron", "list"]:
        return
    if name == "crontab" and rest == ["-l"]:
        return
    raise ReadOnlyViolation(f"拒绝执行非只读命令：{' '.join(argv)}")


@dataclass
class CmdResult:
    rc: int
    out: str
    err: str


class CommandRunner:
    """真实命令层。测试里用子类替换 _execute 和 which，只读检查仍然生效。"""

    def __init__(self, extra_path: list[str] | None = None):
        self.extra_path = extra_path or []
        self.history: list[list[str]] = []

    def which(self, name: str) -> str | None:
        # 先按当前 PATH 找；agent 的 shell 常常没带 ~/.local/bin、/opt/homebrew/bin，再到这些地方找
        found = shutil.which(name)
        if found or not self.extra_path:
            return found
        return shutil.which(name, path=os.pathsep.join(self.extra_path))

    def run(self, argv: list[str], timeout: int = 15) -> CmdResult:
        assert_read_only(argv)
        self.history.append(list(argv))
        return self._execute(argv, timeout)

    def _execute(self, argv: list[str], timeout: int) -> CmdResult:
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL, errors="replace")
            return CmdResult(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired:
            return CmdResult(124, "", f"{timeout} 秒内没有返回，已放弃")
        except OSError as e:
            return CmdResult(127, "", str(e))


# ---------------------------------------------------------------------------
# 解析 launchctl 输出
# ---------------------------------------------------------------------------

@dataclass
class LaunchdState:
    loaded: bool
    state: str | None = None
    pid: int | None = None
    last_exit: int | None = None
    last_exit_text: str | None = None
    runs: int | None = None
    last_signal: str | None = None
    error: str | None = None


def _int_prefix(text: str | None) -> int | None:
    if not text:
        return None
    m = re.match(r"\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


def parse_launchctl_print(text: str) -> LaunchdState:
    """只取第一层的 `键 = 值`，嵌套块（arguments、environment、endpoints 等）里的同名键不算。"""
    top: dict[str, str] = {}
    depth = 0
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.endswith("{"):
            depth += 1
            continue
        if s == "}" or s == "};":
            depth -= 1
            continue
        if depth == 1 and " = " in s:
            k, v = s.split(" = ", 1)
            top.setdefault(k.strip(), v.strip())
    last_exit_text = top.get("last exit code")
    return LaunchdState(
        loaded=True,
        state=top.get("state"),
        pid=_int_prefix(top.get("pid")),
        last_exit=_int_prefix(last_exit_text),
        last_exit_text=last_exit_text,
        runs=_int_prefix(top.get("runs")),
        last_signal=top.get("last terminating signal"),
    )


def parse_print_disabled(text: str) -> set[str]:
    disabled = set()
    for m in re.finditer(r'"([^"]+)"\s*=>\s*(disabled|true|enabled|false)', text):
        if m.group(2) in ("disabled", "true"):
            disabled.add(m.group(1))
    return disabled


# ---------------------------------------------------------------------------
# 退出码的人话解释
# ---------------------------------------------------------------------------

SIGNALS = {
    1: ("SIGHUP", "终端或会话断开"),
    2: ("SIGINT", "被中断"),
    6: ("SIGABRT", "程序自己崩溃中止"),
    9: ("SIGKILL", "被强制结束，可能是内存不够被系统杀掉，或有人强杀"),
    11: ("SIGSEGV", "程序崩溃，内存访问出错"),
    13: ("SIGPIPE", "输出管道断了"),
    15: ("SIGTERM", "被要求退出，手动停止、重启或关机时常见"),
}

SYSEXITS = {
    64: "EX_USAGE：用法错误（参数不对）",
    65: "EX_DATAERR：输入数据有误",
    66: "EX_NOINPUT：找不到输入文件",
    67: "EX_NOUSER：用户不存在",
    68: "EX_NOHOST：主机名不认识",
    69: "EX_UNAVAILABLE：依赖的服务不可用",
    70: "EX_SOFTWARE：程序内部出错",
    71: "EX_OSERR：系统错误",
    72: "EX_OSFILE：系统文件缺失",
    73: "EX_CANTCREAT：无法创建输出文件",
    74: "EX_IOERR：读写出错",
    75: "EX_TEMPFAIL：临时失败，程序自己报告「暂时不行，稍后再试」，常见于网络或连接断开",
    76: "EX_PROTOCOL：通信协议出错",
    77: "EX_NOPERM：没有权限",
    78: "EX_CONFIG：配置错误；launchd 启动不了程序时也常报这个，比如程序路径不对、没有执行权限、日志目录不存在",
}


def explain_exit(code: int | None) -> str:
    if code is None:
        return "还没有退出过"
    if code == 0:
        return "正常结束"
    if code == 1:
        return "一般性错误，程序自己报错退出，具体原因要看日志"
    if code == 2:
        return "用法或参数错误"
    if code in SYSEXITS:
        return SYSEXITS[code]
    if code == 126:
        return "找到了程序但无法执行，多半是没有执行权限"
    if code == 127:
        return "找不到命令：launchd 的 PATH 比终端里短，脚本里用到的命令可能找不到"
    sig = None
    if 128 < code <= 128 + 64:
        sig = code - 128
    elif code < 0:
        sig = -code
    if sig is not None:
        name, meaning = SIGNALS.get(sig, (f"信号 {sig}", "被信号结束"))
        return f"被 {name} 结束：{meaning}"
    return "程序自定义的错误码，具体含义要看日志"


def exit_signal(code: int | None, signal_text: str | None) -> int | None:
    if signal_text:
        m = re.search(r"(\d+)\s*$", signal_text)
        if m:
            return int(m.group(1))
    if code is not None and 128 < code <= 128 + 64:
        return code - 128
    if code is not None and code < 0:
        return -code
    return None


# ---------------------------------------------------------------------------
# 计划：人话描述 + 预期运行时间
# ---------------------------------------------------------------------------

WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _calendar_entries(pl: dict) -> list[dict]:
    raw = pl.get("StartCalendarInterval")
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    return []


def _fmt_interval(sec: int) -> str:
    if sec % 86400 == 0:
        return f"每 {sec // 86400} 天"
    if sec % 3600 == 0:
        return f"每 {sec // 3600} 小时"
    if sec % 60 == 0:
        return f"每 {sec // 60} 分钟"
    return f"每 {sec} 秒"


def _describe_calendar_entry(e: dict) -> str:
    if "Month" in e and "Day" in e:
        date = f"每年 {e['Month']} 月 {e['Day']} 日"
    elif "Month" in e:
        date = f"每年 {e['Month']} 月每天"
    elif "Day" in e:
        date = f"每月 {e['Day']} 日"
    elif "Weekday" in e:
        date = "每" + WEEKDAYS[int(e["Weekday"]) % 8]
    else:
        date = "每天" if "Hour" in e else ""
    if "Hour" in e and "Minute" in e:
        time = f"{int(e['Hour']):02d}:{int(e['Minute']):02d}"
    elif "Hour" in e:
        time = f"{int(e['Hour'])} 点内每分钟"
    elif "Minute" in e:
        time = f"每小时第 {int(e['Minute'])} 分"
    else:
        time = "每分钟"
    return f"{date} {time}".strip()


def schedule_kind(pl: dict) -> str:
    ka = pl.get("KeepAlive")
    if ka is True or (isinstance(ka, dict) and ka):
        return "keepalive"
    if isinstance(pl.get("StartInterval"), int) and pl["StartInterval"] > 0:
        return "interval"
    if _calendar_entries(pl):
        return "calendar"
    if pl.get("WatchPaths") or pl.get("QueueDirectories") or pl.get("StartOnMount"):
        return "watch"
    if pl.get("RunAtLoad"):
        return "runatload"
    return "manual"


def describe_schedule(pl: dict) -> str:
    bits = []
    ka = pl.get("KeepAlive")
    if ka is True:
        bits.append("常驻：登录时启动，退出后自动重启")
    elif isinstance(ka, dict) and ka:
        if ka.get("SuccessfulExit") is False:
            bits.append("常驻（异常退出时自动重启）")
        else:
            bits.append("按条件常驻（" + "、".join(sorted(ka)) + "）")
    if isinstance(pl.get("StartInterval"), int) and pl["StartInterval"] > 0:
        bits.append(_fmt_interval(pl["StartInterval"]))
    entries = _calendar_entries(pl)
    if entries:
        descs = [_describe_calendar_entry(e) for e in entries]
        if len(descs) > 4:
            bits.append("、".join(descs[:3]) + f" 等 {len(descs)} 个时间点")
        else:
            bits.append("、".join(descs))
    if pl.get("WatchPaths") or pl.get("QueueDirectories"):
        bits.append("监视的文件有变动时运行")
    if pl.get("StartOnMount"):
        bits.append("插入磁盘时运行")
    if pl.get("RunAtLoad") and ka is not True:
        bits.append("登录时运行一次")
    return "；".join(bits) if bits else "只在手动触发时运行"


def _fires_on_date(e: dict, day: dt.date) -> list[dt.datetime]:
    if "Month" in e and int(e["Month"]) != day.month:
        return []
    launchd_wd = (day.weekday() + 1) % 7  # launchd：0 和 7 都是周日
    day_ok = "Day" in e and int(e["Day"]) == day.day
    wd_ok = "Weekday" in e and int(e["Weekday"]) % 7 == launchd_wd
    if "Day" in e and "Weekday" in e:
        if not (day_ok or wd_ok):  # 两个都写时按 cron 的「任一满足」
            return []
    elif "Day" in e and not day_ok:
        return []
    elif "Weekday" in e and not wd_ok:
        return []
    hours = [int(e["Hour"])] if "Hour" in e else range(24)
    minutes = [int(e["Minute"])] if "Minute" in e else range(60)
    return [dt.datetime.combine(day, dt.time(h, m)) for h in hours for m in minutes]


def iter_calendar_fires_desc(entries: list[dict], before: dt.datetime, max_days: int = 400):
    """从 before 往回，依次给出按计划应该运行的时间点（含 before 本身）。"""
    for i in range(max_days):
        day = before.date() - dt.timedelta(days=i)
        times = {t for e in entries for t in _fires_on_date(e, day) if t <= before}
        yield from sorted(times, reverse=True)


def last_calendar_fire(entries: list[dict], before: dt.datetime) -> dt.datetime | None:
    return next(iter_calendar_fires_desc(entries, before), None)


def count_calendar_fires(entries: list[dict], after: dt.datetime, until: dt.datetime, cap: int = 99) -> int:
    n = 0
    for t in iter_calendar_fires_desc(entries, until):
        if t <= after or n >= cap:
            break
        n += 1
    return n


def max_fires_per_day(entries: list[dict], around: dt.datetime) -> int:
    """around 前 7 天里，单日最多有几个计划运行点（覆盖按星期排的计划）。"""
    return max(len({t for e in entries for t in _fires_on_date(e, around.date() - dt.timedelta(days=i))})
               for i in range(7))


def count_calendar_days(entries: list[dict], after: dt.datetime, until: dt.datetime, cap: int = 99) -> int:
    """after 那天之后、until 之前，有计划运行点的日子有几天（after 当天不算）。"""
    days: set = set()
    for t in iter_calendar_fires_desc(entries, until):
        if t.date() <= after.date() or len(days) >= cap:
            break
        days.add(t.date())
    return len(days)


# ---------------------------------------------------------------------------
# 程序、日志
# ---------------------------------------------------------------------------

INTERPRETERS = {"bash", "sh", "zsh", "dash", "fish", "python", "python3", "node", "ruby", "perl",
                "osascript", "deno", "bun", "uv", "npx", "php", "pwsh", "tsx"}
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
SCRIPT_EXT = (".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".scpt", ".applescript", ".zsh", ".bash")


def _is_interpreter(path: str) -> bool:
    base = os.path.basename(path)
    return base in INTERPRETERS or re.fullmatch(r"python3(\.\d+)?", base) is not None


@dataclass
class ProgramCheck:
    program: str | None = None
    program_resolved: str | None = None
    program_exists: bool | None = None
    program_executable: bool | None = None
    script: str | None = None
    script_exists: bool | None = None
    inline: str | None = None
    inline_missing: list[str] = field(default_factory=list)
    workdir: str | None = None
    workdir_exists: bool | None = None


def _expand(p: str, home: Path) -> str:
    if p == "~" or p.startswith("~/"):
        return str(home) + p[1:]
    return p


def check_program(pl: dict, home: Path) -> ProgramCheck:
    pc = ProgramCheck()
    args = [str(a) for a in pl.get("ProgramArguments") or []]
    program = pl.get("Program") or (args[0] if args else None)
    rest = args[1:] if args else []
    pc.program = program
    wd = pl.get("WorkingDirectory")
    if wd:
        pc.workdir = wd
        pc.workdir_exists = os.path.isdir(_expand(wd, home))
    if not program:
        return pc
    prog = _expand(str(program), home)
    if os.path.isabs(prog):
        pc.program_resolved = prog
    else:
        env_path = (pl.get("EnvironmentVariables") or {}).get("PATH") or LAUNCHD_DEFAULT_PATH
        pc.program_resolved = shutil.which(prog, path=env_path)
    pc.program_exists = bool(pc.program_resolved) and os.path.exists(pc.program_resolved)
    if pc.program_exists:
        pc.program_executable = os.access(pc.program_resolved, os.X_OK)

    # /usr/bin/env python3 x.py → 把 env 后面的解释器当程序看
    if os.path.basename(prog) == "env":
        while rest and (rest[0].startswith("-") or "=" in rest[0]):
            rest = rest[1:]
        if not rest:
            return pc
        prog, rest = rest[0], rest[1:]
    if not _is_interpreter(prog):
        return pc
    base = os.path.basename(prog)
    i = 0
    while i < len(rest):
        a = rest[i]
        if base in ("uv", "npx", "bun", "deno") and a in ("run", "exec", "x"):
            i += 1
            continue
        if a.startswith("-") and not a.startswith("--"):
            inline_flag = (base in SHELLS and "c" in a[1:]) or a in ("-c", "-e", "-m")
            if inline_flag:
                if a == "-m":
                    return pc  # python -m 模块名，没法按文件核对
                pc.inline = rest[i + 1] if i + 1 < len(rest) else ""
                pc.inline_missing = _missing_paths_in_command(pc.inline, home)
                return pc
            i += 1
            continue
        if a.startswith("--"):
            i += 1
            continue
        if "/" in a or a.endswith(SCRIPT_EXT) or a.startswith("~"):
            p = _expand(a, home)
            if not os.path.isabs(p):
                p = os.path.join(_expand(wd, home) if wd else "/", p)
            pc.script = p
            pc.script_exists = os.path.exists(p)
        return pc
    return pc


_PATH_IN_CMD = re.compile(r"""(?:(?<=^)|(?<=[\s'"=:;(]))(~/[^\s'";|&<>()]+|/[^\s'";|&<>()]+)""")


def _missing_paths_in_command(cmd: str, home: Path) -> list[str]:
    """内联命令里提到的、在家目录下却不存在的路径（输出重定向的目标不算）。"""
    missing = []
    for m in _PATH_IN_CMD.finditer(cmd):
        before = cmd[:m.start()].rstrip()
        if before.endswith(">"):
            continue
        p = _expand(m.group(1), home).rstrip("/")
        if not p.startswith(str(home) + "/"):
            continue
        if "*" in p or "$" in p:
            continue
        if not os.path.exists(p) and p not in missing:
            missing.append(p)
    return missing


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
REDACT_RULES = [
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 [已隐藏]"),
    (re.compile(r"(?i)((?:access|refresh|app|api|tenant|user)?[_-]?(?:token|secret|password|passwd|api[_-]?key|access[_-]?key|authorization))(\"?\s*[:=]\s*\"?)[^\s\"',;&]+"),
     r"\1\2[已隐藏]"),
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9\-]{10,}|[tu]-[A-Za-z0-9]{20,})"), "[已隐藏]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "[已隐藏]"),
]


def redact(line: str) -> str:
    for pat, rep in REDACT_RULES:
        line = pat.sub(rep, line)
    return line


ERROR_WORDS = re.compile(
    r"(?i)\b(error|exception|traceback|fatal|failed|failure|panic|denied|refused|timed out|timeout|"
    r"not found|no such file|unauthorized|forbidden)\b|错误|失败|异常|报错|超时|拒绝")


@dataclass
class LogInfo:
    kind: str
    path: str
    exists: bool = False
    dir_exists: bool = True
    mtime: str | None = None
    size: int = 0
    tail: list[str] = field(default_factory=list)
    error_lines: int = 0


def read_tail(path: str, n: int, max_bytes: int = 256 * 1024) -> list[str]:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    lines = [ANSI.sub("", ln).rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    return [redact(ln)[:300] for ln in lines[-n:]]


def inspect_log(kind: str, path: str, home: Path, n: int) -> LogInfo:
    p = _expand(path, home)
    info = LogInfo(kind=kind, path=path)
    info.dir_exists = os.path.isdir(os.path.dirname(p) or "/")
    if os.path.isfile(p):
        st = os.stat(p)
        info.exists = True
        info.size = st.st_size
        info.mtime = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        try:
            info.tail = read_tail(p, n)
        except OSError as e:
            info.tail = [f"（读不了：{e}）"]
        info.error_lines = sum(1 for ln in info.tail if ERROR_WORDS.search(ln))
    return info


# ---------------------------------------------------------------------------
# 体检项与判档
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str
    problem: str
    advice: str
    rank: int = 50  # 同一档里谁排前面：越小越急


@dataclass
class Item:
    key: str
    title: str
    kind: str  # job / residue / hermes / crontab
    findings: list[Finding] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    logs: list[LogInfo] = field(default_factory=list)
    raw: str | None = None
    blind: bool = False

    @property
    def tier(self) -> str:
        if not self.findings:
            return OK
        return max((f.severity for f in self.findings), key=SEVERITY_RANK.get)

    def add(self, severity: str, problem: str, advice: str, rank: int = 50) -> None:
        self.findings.append(Finding(severity, problem, advice, rank))

    @property
    def urgency(self) -> int:
        return min((f.rank for f in self.findings if f.severity == self.tier), default=99)


@dataclass
class Job:
    path: Path
    label: str
    plist: dict
    alias: str | None = None
    schedule: str = ""
    kind: str = "manual"
    disabled: bool = False
    launchd: LaunchdState | None = None
    program: ProgramCheck | None = None
    logs: list[LogInfo] = field(default_factory=list)


@dataclass
class Context:
    agents_dir: Path
    home: Path
    uid: int
    now: dt.datetime
    runner: CommandRunner
    cfg: dict
    check_hermes: bool = True
    check_crontab: bool = True


@dataclass
class Report:
    now: str
    agents_dir: str
    items: list[Item]
    excluded: list[str]
    notes: list[str]
    hermes_status: str
    crontab_status: str
    commands_run: list[list[str]]


def load_config(path: Path | None = None) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    for p in [SKILL_DIR / "config.json", path]:
        if p and Path(p).is_file():
            with open(p, encoding="utf-8") as f:
                user = json.load(f)
            cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    return cfg


def _match_any(label: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(label, p) for p in patterns)


def alias_for(label: str, aliases: dict) -> str | None:
    hits = [(len(p), name) for p, name in aliases.items() if fnmatch.fnmatchcase(label, p)]
    return max(hits)[1] if hits else None


def fmt_ago(t: dt.datetime, now: dt.datetime) -> str:
    sec = (now - t).total_seconds()
    if sec < 0:
        return "刚刚"
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return f"{int(sec // 60)} 分钟前"
    if sec < 48 * 3600:
        return f"{int(sec // 3600)} 小时前"
    return f"{int(sec // 86400)} 天前"


def fmt_time(t: dt.datetime, now: dt.datetime) -> str:
    if t.date() == now.date():
        day = "今天"
    elif t.date() == (now - dt.timedelta(days=1)).date():
        day = "昨天"
    elif t.year == now.year:
        day = f"{t.month} 月 {t.day} 日"
    else:
        day = f"{t.year} 年 {t.month} 月 {t.day} 日"
    return f"{day} {t:%H:%M}（{fmt_ago(t, now)}）"


RESIDUE_MARKERS = re.compile(r"(?i)(\.bak|\.backup|\.old|\.orig|\.disabled|\.off|\.save|~$|copy|副本|\.\d{8,})")


def scan_agents_dir(ctx: Context):
    """返回 (要体检的 plist 路径, 残留文件路径, 被排除的 Label)。"""
    live, residue, excluded = [], [], []
    if not ctx.agents_dir.is_dir():
        return live, residue, excluded
    for p in sorted(ctx.agents_dir.iterdir()):
        if p.name in (".DS_Store",) or p.is_dir():
            continue
        label_guess = p.name.split(".plist")[0]
        if _match_any(label_guess, ctx.cfg["exclude_patterns"]) and label_guess not in ctx.cfg["include_labels"]:
            excluded.append(p.name)
            continue
        if p.name.endswith(".plist"):
            live.append(p)
        else:
            residue.append(p)
    return live, residue, excluded


def read_plist(path: Path) -> dict:
    with open(path, "rb") as f:
        data = plistlib.load(f)
    if not isinstance(data, dict):
        raise ValueError("最外层不是字典")
    return data


def build_job(path: Path, pl: dict, ctx: Context, disabled_labels: set[str]) -> Job:
    label = str(pl.get("Label") or path.name[:-len(".plist")])
    job = Job(path=path, label=label, plist=pl)
    job.alias = alias_for(label, ctx.cfg["aliases"])
    job.schedule = describe_schedule(pl)
    job.kind = schedule_kind(pl)
    job.disabled = bool(pl.get("Disabled")) or label in disabled_labels
    job.program = check_program(pl, ctx.home)
    out_p, err_p = pl.get("StandardOutPath"), pl.get("StandardErrorPath")
    n = ctx.cfg["tail_lines"]
    if out_p and out_p == err_p:
        job.logs.append(inspect_log("日志", out_p, ctx.home, n))
    else:
        if err_p:
            job.logs.append(inspect_log("错误日志", err_p, ctx.home, n))
        if out_p:
            job.logs.append(inspect_log("输出日志", out_p, ctx.home, n))
    return job


def _last_log_time(job: Job, logs: list[LogInfo] | None = None) -> dt.datetime | None:
    times = [dt.datetime.fromisoformat(l.mtime) for l in (job.logs if logs is None else logs) if l.exists and l.mtime]
    return max(times) if times else None


def assess_job(job: Job, ctx: Context, item: Item) -> None:
    cfg, now = ctx.cfg, ctx.now
    pc = job.program
    ld = job.launchd

    # --- 事实 ---
    item.facts.append(f"计划：{job.schedule}")
    if ld is None:
        item.facts.append("运行状态：未知（这台机器上没有 launchctl）")
    elif not ld.loaded:
        item.facts.append("运行状态：没有加载到 launchd" + ("（已停用）" if job.disabled else ""))
    else:
        st = {"running": "正在运行", "not running": "没在运行", "waiting": "等待中",
              "spawn scheduled": "等待重启"}.get(ld.state or "", ld.state or "未知")
        if ld.state == "not running" and job.kind in ("interval", "calendar", "watch"):
            st = "待命，到点才运行"
        bits = [st]
        if ld.pid:
            bits.append(f"PID {ld.pid}")
        if ld.runs is not None:
            bits.append(f"本次登录以来启动 {ld.runs} 次")
        item.facts.append("运行状态：" + "，".join(bits))
        if ld.last_exit is not None:
            item.facts.append(f"上次退出码：{ld.last_exit}，{explain_exit(ld.last_exit)}")
    if pc and pc.inline is not None:
        item.facts.append(f"命令：`{redact(pc.inline)[:200]}`")
    elif pc and pc.program:
        target = pc.script or pc.program_resolved or pc.program
        exists = pc.script_exists if pc.script else pc.program_exists
        item.facts.append(f"程序：`{target}` " + ("存在" if exists else "**不存在**" if exists is False else ""))
    last_log = _last_log_time(job)
    if job.logs:
        item.facts.append("日志最后更新：" + (fmt_time(last_log, now) if last_log else "日志文件不存在"))
    else:
        item.facts.append("日志：plist 里没配")
    item.logs = job.logs

    # --- 僵尸任务：程序或脚本不在了 ---
    zombie = False
    if pc:
        if pc.program and pc.program_exists is False:
            zombie = True
            item.add(ACT, f"僵尸任务：plist 指向的程序 `{pc.program}` 已经不存在，这个任务每次触发都会失败。",
                     "确认这个任务还要不要：不要了就停用并把 plist 挪出 LaunchAgents；还要的话改成正确的程序路径。", 45)
        elif pc.script and pc.script_exists is False:
            zombie = True
            item.add(ACT, f"僵尸任务：要运行的脚本 `{pc.script}` 已经不存在（多半是项目挪了位置或删了）。",
                     "确认这个任务还要不要：不要了就停用并把 plist 挪出 LaunchAgents；还要的话把路径改到脚本的新位置。", 45)
        elif pc.program_exists and pc.program_executable is False and not pc.script:
            item.add(ACT, f"程序 `{pc.program_resolved}` 没有执行权限，launchd 启动不了它。",
                     "给它加上执行权限，或改成用 bash/python 去运行它。")
        if pc.workdir and pc.workdir_exists is False:
            item.add(ACT, f"工作目录 `{pc.workdir}` 不存在，launchd 会启动失败。",
                     "改成正确的工作目录，或确认项目是否已经挪走。")
        if pc.inline_missing and not zombie:
            item.add(WARN, "命令里提到的路径不存在：" + "、".join(f"`{p}`" for p in pc.inline_missing[:3]) + "。",
                     "看一下是不是项目挪了位置；如果这是任务自己会创建的文件，可以忽略。")

    for lg in job.logs:
        if not lg.dir_exists:
            item.add(ACT, f"{lg.kind}所在的文件夹 `{os.path.dirname(lg.path)}` 不存在，launchd 常因此直接启动失败。",
                     "建好这个文件夹，或把日志路径改到存在的位置。")

    # --- 加载与停用 ---
    if job.disabled:
        item.add(WARN, "这个任务已被停用，不会自动运行，但 plist 文件还在。",
                 "确认不用了就把 plist 挪出 LaunchAgents（先挪到备份文件夹，不要直接删）；还要用就重新启用。", 40)
    elif ld is not None and not ld.loaded and not zombie:
        if job.kind in ("keepalive", "interval", "calendar", "watch"):
            item.add(ACT, "plist 文件在，但 launchd 里没有这个任务：它现在根本不会运行（可能被手动卸载过，或加载时出错）。",
                     "确认还要不要这个任务：要就重新加载，不要就把 plist 挪走（否则下次登录它又会自己回来）。",
                     10 if job.kind == "keepalive" else 40)
        else:
            item.add(WARN, "plist 文件在，但 launchd 里没有这个任务（它只在登录或手动触发时运行，影响可能不大）。",
                     "确认还要不要；不要就把 plist 挪走。")

    # --- 退出码与常驻服务 ---
    exit_flagged = zombie  # 僵尸任务的失败退出只是症状，不再单列
    if ld is not None and ld.loaded and not job.disabled and not zombie:
        sig = exit_signal(ld.last_exit, ld.last_signal)
        nonzero = ld.last_exit not in (None, 0) or sig is not None
        if ld.last_exit is not None:
            exit_desc = f"上次退出码 {ld.last_exit}（{explain_exit(ld.last_exit)}）"
        elif ld.last_signal:
            exit_desc = f"上次被信号结束（{ld.last_signal}）"
        else:
            exit_desc = "没有退出记录"
        if job.kind == "keepalive":
            ka = job.plist.get("KeepAlive")
            only_on_failure = isinstance(ka, dict) and ka.get("SuccessfulExit") is False
            conditional = isinstance(ka, dict) and not only_on_failure
            runs = ld.runs or 0
            if ld.state == "running":
                if sig == 15 and runs >= cfg["restart_runs_warn"]:
                    # 上次是被要求退出（SIGTERM）后重新拉起：发版、手动重启、注销时常见，不像崩溃。
                    # 只看得到最后一次，之前有没有崩溃过不知道，所以仍提醒一句，但不算「需要处理」。
                    exit_flagged = True
                    item.add(WARN, f"常驻服务在跑，本次登录以来启动了 {runs} 次；但上次是被要求退出后重新拉起的，"
                                   f"多半是发版或手动重启，不像崩溃；{exit_desc}。",
                             "目前能用。如果最近没有重启或发版过它，再看日志末尾确认有没有崩溃。", 10)
                elif runs >= cfg["restart_runs_act"]:
                    exit_flagged = True
                    item.add(ACT, f"常驻服务在跑，但本次登录以来已经启动了 {runs} 次，说明在反复崩溃又被拉起；{exit_desc}。",
                             "看日志末尾找崩溃原因；原因修好之前它会一直断断续续。", 15)
                elif nonzero and runs >= cfg["restart_runs_warn"]:
                    exit_flagged = True
                    item.add(WARN, f"常驻服务现在在跑，但本次登录以来启动了 {runs} 次，有过崩溃重启；{exit_desc}。",
                             "目前能用。看一下日志末尾，判断是偶发断线还是反复出错；反复出错再处理。", 10)
                elif nonzero and sig != 15:
                    exit_flagged = True
                    item.add(WARN, f"常驻服务现在在跑，但之前异常退出过一次，已被自动拉起；{exit_desc}。",
                             "目前能用，留意一下；如果下次体检又出现，再查日志。", 15)
            elif (only_on_failure or conditional) and not nonzero:
                pass  # 成功退出后不再拉起，或条件没满足，按设计就不在跑
            else:
                exit_flagged = True
                state_desc = "正在等待重启（多半刚崩溃，被系统限速）" if ld.state in ("spawn scheduled", "waiting") else "没在运行"
                item.add(ACT, f"常驻服务现在{state_desc}；{exit_desc}。"
                         + (f"本次登录以来已启动 {runs} 次。" if runs > 1 else ""),
                         "先看下面的日志末尾找原因；原因清楚后再重启它。", 10)
        elif nonzero:
            exit_flagged = True
            if sig == 15:
                item.add(WARN, f"上次运行被中途停止；{exit_desc}。", "一般是手动停止或关机造成的；下次按计划运行正常就不用管。", 30)
            else:
                item.add(ACT, f"上次运行失败：{exit_desc}。", "看下面的日志末尾找原因；修好后可以手动触发一次确认。", 20)

    # --- 该跑没跑 ---
    # 只用输出日志判断：任务正常时往往不写错误日志，错误日志不更新不代表没跑
    timing_logs = [l for l in job.logs if l.kind in ("输出日志", "日志")]
    timing_last = _last_log_time(job, timing_logs)
    if job.kind in ("interval", "calendar") and not job.disabled and not zombie \
            and ld is not None and ld.loaded and job.label not in cfg["quiet_labels"]:
        if not timing_logs:
            item.blind = True
        elif timing_last is None:
            if all(l.dir_exists for l in timing_logs):
                item.add(WARN, "plist 里配了输出日志，但日志文件一直没生成，可能从来没成功跑过。",
                         "手动触发一次看看会不会生成日志；不会就检查程序路径和权限。", 25)
        else:
            cutoff = now - dt.timedelta(minutes=cfg["grace_minutes"])
            by_day = False
            if job.kind == "interval":
                interval = job.plist["StartInterval"]
                missed = max(0, int((cutoff - timing_last).total_seconds() // interval))
                expected = None
            else:
                entries = _calendar_entries(job.plist)
                expected = last_calendar_fire(entries, cutoff)
                missed = count_calendar_fires(entries, timing_last, cutoff)
                if missed and max_fires_per_day(entries, cutoff) > 1:
                    # 一天排了好几个点的，常见于「当天补跑窗口」：当天做成后，后面的点直接退出、不写日志。
                    # 这类按天判断：日志最后更新那天之后，还有几天该跑却一行日志都没有。
                    by_day = True
                    missed = count_calendar_days(entries, timing_last, cutoff)
            if expected:
                item.facts.append("按计划最近一次应运行：" + fmt_time(expected, now))
            stale_h = (now - timing_last).total_seconds() / 3600
            if missed >= 1:
                times = f" {missed} 次" if (job.kind == "interval" or missed < 99) else "至少 99 次"
                if by_day:
                    text = (f"疑似该跑没跑：日志停在 {fmt_time(timing_last, now)}，"
                            f"之后有 {missed if missed < 99 else '至少 99'} 天按计划该运行，却没有日志。")
                else:
                    text = f"疑似该跑没跑：日志停在 {fmt_time(timing_last, now)}，按计划这之后应该运行{times}。"
                advice = ("先确认电脑那段时间是不是关机了；不是的话看日志末尾和 launchd 状态找原因。"
                          "如果这个任务平时就不写日志，把它加到 config.json 的 quiet_labels 里，以后不再按日志判断。")
                sev = ACT if (missed >= cfg["missed_runs_act"] and stale_h >= cfg["stale_hours_act"]) else WARN
                item.add(sev, text, advice, 30 if sev == ACT else 20)

    # --- 日志内容 ---
    if not exit_flagged:
        recent_err = [l for l in job.logs if l.exists and l.error_lines and l.mtime and
                      (now - dt.datetime.fromisoformat(l.mtime)).total_seconds() < cfg["recent_error_hours"] * 3600]
        if recent_err:
            n = sum(l.error_lines for l in recent_err)
            item.add(WARN, f"日志末尾有 {n} 行带报错字样，是最近 {cfg['recent_error_hours']} 小时内写的。",
                     "看一眼下面的日志末尾：如果是已知的无害提示可以忽略，否则说明任务有一部分没做成。", 30)
    for lg in job.logs:
        if lg.size >= cfg["log_size_warn_mb"] * 1024 * 1024:
            item.add(WARN, f"{lg.kind}已经 {lg.size // (1024 * 1024)} MB，持续增长会占满磁盘。",
                     "清空或轮转这个日志（先确认里面没有要留的内容）。")


def check_duplicates(jobs: list[Job], items: dict[str, Item]) -> None:
    by_label: dict[str, list[Job]] = {}
    for j in jobs:
        by_label.setdefault(j.label, []).append(j)
    for label, js in by_label.items():
        if len(js) > 1:
            names = "、".join(f"`{j.path.name}`" for j in js)
            for j in js:
                items[str(j.path)].add(ACT, f"{names} 用的是同一个 Label，launchd 只会加载其中一个，另一个等于没生效，改配置时很容易改错文件。",
                                       "确认哪个是在用的，把另一个挪出 LaunchAgents。", 70)


def assess_naming(job: Job, item: Item) -> None:
    stem = job.path.name[:-len(".plist")]
    if RESIDUE_MARKERS.search(stem):
        item.add(WARN, f"文件名 `{job.path.name}` 像备份，但仍以 .plist 结尾，launchd 登录时会照样加载它。",
                 "如果它是备份，把它挪出 LaunchAgents；如果在用，改个正经名字。")
    elif stem != job.label:
        item.add(WARN, f"文件名 `{job.path.name}` 和里面的 Label `{job.label}` 不一致，排查时容易找错文件。",
                 "不影响运行；方便的时候把文件名改成和 Label 一致。")


def assess_residue(paths: list[Path], live_labels: set[str]) -> Item | None:
    if not paths:
        return None
    item = Item(key="residue", title="LaunchAgents 里的残留文件", kind="residue")
    lines = []
    for p in paths:
        try:
            pl = read_plist(p)
            label = str(pl.get("Label", "")) or None
        except Exception:
            label = None
        if label and label in live_labels:
            note = f"是在用任务 `{label}` 的旧版本或备份"
        elif label:
            note = f"对应的任务 `{label}` 已经不在用"
        else:
            note = "不是可读的 plist"
        lines.append(f"`{p.name}`：{note}")
    item.facts = lines
    item.add(WARN, f"有 {len(paths)} 个不以 .plist 结尾的残留文件。launchd 一般不会加载它们，但留着容易和在用的配置混淆，改错文件。",
             "确认没用后统一挪到一个备份文件夹（例如 ~/Library/LaunchAgents.retired/），不要直接删。", 60)
    return item


def check_hermes(ctx: Context) -> tuple[Item | None, str]:
    exe = ctx.runner.which("hermes")
    if not exe:
        return None, "没找到 hermes 命令，跳过 hermes 定时任务检查。"
    r = ctx.runner.run([exe, "cron", "list"], timeout=30)
    item = Item(key="hermes-cron", title="hermes 定时任务（hermes cron list）", kind="hermes")
    out = "\n".join(redact(ANSI.sub("", ln.rstrip())) for ln in (r.out or "").splitlines())
    lines = out.splitlines()
    if len(lines) > 80:
        out = "\n".join(lines[:80]) + f"\n……（共 {len(lines)} 行，只显示前 80 行）"
    item.raw = out.strip() or "（没有输出）"
    if r.rc != 0:
        err = (r.err or "").strip().splitlines()
        item.add(WARN, f"`hermes cron list` 运行失败（返回码 {r.rc}）：{redact(err[0]) if err else '没有错误信息'}。",
                 "在终端里手动跑一次 `hermes cron list` 看看；如果 hermes 网关本身挂了，先处理网关。")
        return item, "已读取（失败）"
    bad = [ln.strip() for ln in lines if re.search(r"(?i)\b(error|failed|failing|paused|disabled)\b|失败|错误|暂停|停用", ln)]
    if bad:
        item.add(WARN, f"hermes 定时任务列表里有 {len(bad)} 行带失败、暂停或停用字样："
                 + "；".join(f"`{b[:120]}`" for b in bad[:3]) + "。",
                 "让 agent 对照下面的原始输出逐条解释；确认是故意暂停的就不用管。", 25)
    return item, "已读取"


def check_crontab(ctx: Context) -> tuple[Item | None, str]:
    if not ctx.runner.which("crontab"):
        return None, "没有 crontab 命令，跳过。"
    r = ctx.runner.run(["crontab", "-l"])
    if r.rc != 0:
        return None, "没有 crontab 定时任务。"
    entries = [ln.strip() for ln in r.out.splitlines() if ln.strip() and not ln.strip().startswith("#")
               and not re.match(r"^[A-Z_]+=", ln.strip())]
    if not entries:
        return None, "crontab 里没有生效的条目。"
    item = Item(key="crontab", title=f"crontab 定时任务（{len(entries)} 条）", kind="crontab")
    item.facts = [f"`{redact(e)[:160]}`" for e in entries]
    for e in entries:
        missing = _missing_paths_in_command(e, ctx.home)
        if missing:
            item.add(ACT, f"crontab 这条指向的文件不存在：`{missing[0]}`，每次到点都会失败。",
                     "确认这条还要不要；不要了就从 crontab 里删掉这一行，要就改成正确路径。", 60)
    return item, f"{len(entries)} 条"


def run_checkup(ctx: Context) -> Report:
    notes: list[str] = []
    has_launchctl = ctx.runner.which("launchctl") is not None
    disabled: set[str] = set()
    if has_launchctl:
        r = ctx.runner.run(["launchctl", "print-disabled", f"gui/{ctx.uid}"])
        if r.rc == 0:
            disabled = parse_print_disabled(r.out)
    else:
        notes.append("这台机器上没有 launchctl，只检查了 plist 文件本身，没有运行状态。")

    if not ctx.agents_dir.is_dir():
        notes.append(f"没找到 {ctx.agents_dir}。")
    live, residue, excluded = scan_agents_dir(ctx)
    items: dict[str, Item] = {}
    jobs: list[Job] = []
    for p in live:
        if p.is_symlink() and not p.exists():
            it = Item(key=str(p), title=f"`{p.name}`", kind="job")
            it.add(ACT, f"`{p.name}` 是个链接，指向的 `{os.readlink(p)}` 已经不存在，launchd 加载不了它（多半是项目挪了位置或删了）。",
                   "确认这个任务还要不要：要就把链接改到 plist 的新位置，不要就把这个链接挪出 LaunchAgents。", 45)
            items[str(p)] = it
            continue
        try:
            pl = read_plist(p)
        except Exception as e:
            it = Item(key=str(p), title=f"`{p.name}`", kind="job")
            it.add(ACT, f"plist 文件读不出来（{type(e).__name__}），launchd 也加载不了它。",
                   "让 agent 用 `plutil -lint` 查出具体哪里坏了再修；不用了就挪走。", 70)
            items[str(p)] = it
            continue
        job = build_job(p, pl, ctx, disabled)
        if _match_any(job.label, ctx.cfg["exclude_patterns"]) and job.label not in ctx.cfg["include_labels"]:
            excluded.append(p.name)
            continue
        if has_launchctl:
            r = ctx.runner.run(["launchctl", "print", f"gui/{ctx.uid}/{job.label}"])
            if r.rc == 0:
                job.launchd = parse_launchctl_print(r.out)
            else:
                job.launchd = LaunchdState(loaded=False, error=(r.err or r.out).strip()[:200])
        title = f"{job.alias} `{job.label}`" if job.alias else f"`{job.label}`"
        if p.name != f"{job.label}.plist":
            title += f"（文件 `{p.name}`）"
        it = Item(key=str(p), title=title, kind="job")
        assess_job(job, ctx, it)
        assess_naming(job, it)
        items[str(p)] = it
        jobs.append(job)
    check_duplicates(jobs, items)

    res = assess_residue(residue, {j.label for j in jobs})
    if res:
        items["residue"] = res
    blind = [it for it in items.values() if it.blind]
    if blind:
        notes.append(f"{len(blind)} 个定时任务在 plist 里没配输出日志，没法判断它们有没有按时运行："
                     + "、".join(it.title for it in blind) + "。")

    hermes_status = "未检查"
    if ctx.check_hermes:
        it, hermes_status = check_hermes(ctx)
        if it:
            items["hermes"] = it
    crontab_status = "未检查"
    if ctx.check_crontab:
        it, crontab_status = check_crontab(ctx)
        if it:
            items["crontab"] = it

    return Report(now=ctx.now.isoformat(timespec="minutes"), agents_dir=str(ctx.agents_dir),
                  items=list(items.values()), excluded=sorted(excluded), notes=notes,
                  hermes_status=hermes_status, crontab_status=crontab_status,
                  commands_run=list(ctx.runner.history))


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def _sort_key(it: Item):
    return (it.urgency, {"job": 0, "crontab": 1, "hermes": 2, "residue": 3}.get(it.kind, 9), it.title)


def _log_block(it: Item) -> list[str]:
    out = []
    for lg in it.logs:
        if lg.exists and lg.tail:
            out += ["", f"<details><summary>{lg.kind}末尾 {len(lg.tail)} 行：<code>{lg.path}</code></summary>", "",
                    "```text", *lg.tail, "```", "</details>"]
    return out


def render_markdown(rep: Report) -> str:
    now = dt.datetime.fromisoformat(rep.now)
    tiers = {ACT: [], WARN: [], OK: []}
    for it in sorted(rep.items, key=_sort_key):
        tiers[it.tier].append(it)
    jobs = [it for it in rep.items if it.kind == "job"]
    L = [f"# 自动化体检报告", "",
         f"体检时间：{now:%Y-%m-%d %H:%M}（本机时间）　检查了 {len(jobs)} 个自建后台任务"
         + (f"，按配置跳过 {len(rep.excluded)} 个系统或第三方任务" if rep.excluded else "") + "。", "",
         f"**结论：需要处理 {len(tiers[ACT])} 项，注意 {len(tiers[WARN])} 项，正常 {len(tiers[OK])} 项。**", ""]
    if tiers[ACT]:
        L.append("最该先看的：")
        for it in tiers[ACT][:3]:
            first = min((f for f in it.findings if f.severity == ACT), key=lambda f: f.rank)
            L.append(f"- {it.title}：{first.problem}")
        L.append("")
    L += ["> 这份报告是只读生成的：没有启动、停止、重启或修改任何任务，也没有动任何文件。",
          "> 下面的「建议」都还没做；要处理哪一条，告诉 agent 条目编号，它会先跟你确认再动手。", ""]

    n = 0
    for tier in (ACT, WARN):
        L += [f"## {tier}（{len(tiers[tier])}）", ""]
        if not tiers[tier]:
            L += ["无。", ""]
        for it in tiers[tier]:
            n += 1
            L += [f"### {n}. {it.title}", ""]
            for f in sorted(it.findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.rank)):
                tag = "" if f.severity == tier else f"［{f.severity}］"
                L.append(f"- **问题**{tag}：{f.problem}")
                L.append(f"  **建议**：{f.advice}")
            for fact in it.facts:
                L.append(f"- {fact}")
            if it.raw:
                L += ["", "```text", it.raw, "```"]
            L += _log_block(it)
            L.append("")

    L += [f"## {OK}（{len(tiers[OK])}）", ""]
    ok_jobs = [it for it in tiers[OK] if it.kind == "job"]
    if ok_jobs:
        L += ["| 任务 | 计划 | 状态 | 日志最后更新 |", "|---|---|---|---|"]
        for it in ok_jobs:
            facts = {f.split("：", 1)[0]: f.split("：", 1)[1] for f in it.facts if "：" in f}
            log = facts.get("日志最后更新") or ("没配日志" if "日志" in facts else "")
            L.append(f"| {it.title} | {facts.get('计划', '')} | {facts.get('运行状态', '')} | {log} |")
        L.append("")
    for it in tiers[OK]:
        if it.kind != "job":
            L += [f"**{it.title}**：没发现问题。", ""]
            if it.raw:
                L += ["```text", it.raw, "```", ""]
            for fact in it.facts:
                L.append(f"- {fact}")
            if it.facts:
                L.append("")
    if not tiers[OK]:
        L += ["无。", ""]

    L += ["## 说明与盲区", ""]
    for note in rep.notes:
        L.append(f"- {note}")
    L.append(f"- hermes 定时任务：{rep.hermes_status}")
    L.append(f"- crontab：{rep.crontab_status}")
    L.append(f"- 检查的目录：`{rep.agents_dir}`")
    if rep.excluded:
        L.append(f"- 按配置跳过（系统或第三方）：" + "、".join(f"`{x}`" for x in rep.excluded))
    L.append("- 「该跑没跑」是用日志文件的最后修改时间推断的：任务平时不写日志、或电脑那段时间关机，都会让判断偏严。")
    kinds = sorted({" ".join([os.path.basename(c[0])] + (c[1:2] if os.path.basename(c[0]) == "launchctl" else c[1:]))
                    for c in rep.commands_run})
    L.append("- 本次只执行了这些查看命令：" + "、".join(f"`{k}`" for k in kinds) if kinds else "- 本次没有执行任何外部命令。")
    L.append("")
    return "\n".join(L)


def report_to_json(rep: Report) -> str:
    data = asdict(rep)
    for it, d in zip(rep.items, data["items"]):
        d["tier"] = it.tier
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="自动化体检（只读）：检查本机自建的定时任务和常驻服务，出一页报告。")
    ap.add_argument("--out", help="报告写到哪里（默认 ~/Documents/自动化体检/自动化体检-日期时间.md）")
    ap.add_argument("--stdout", action="store_true", help="把报告直接打印出来，不写文件")
    ap.add_argument("--json", help="另存一份结构化结果（JSON）")
    ap.add_argument("--config", help="额外的配置文件（JSON），覆盖 skill 目录里的 config.json")
    ap.add_argument("--agents-dir", help="要检查的 LaunchAgents 目录（默认 ~/Library/LaunchAgents）")
    ap.add_argument("--no-hermes", action="store_true", help="不读 hermes cron list")
    ap.add_argument("--no-crontab", action="store_true", help="不读 crontab")
    a = ap.parse_args(argv)

    home = Path.home()
    cfg = load_config(Path(a.config).expanduser() if a.config else None)
    extra = [str(home / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", str(home / ".hermes/bin")]
    ctx = Context(
        agents_dir=Path(a.agents_dir).expanduser() if a.agents_dir else home / "Library/LaunchAgents",
        home=home, uid=os.getuid(), now=dt.datetime.now().replace(microsecond=0),
        runner=CommandRunner(extra_path=extra), cfg=cfg,
        check_hermes=not a.no_hermes, check_crontab=not a.no_crontab)
    rep = run_checkup(ctx)
    md = render_markdown(rep)
    if a.json:
        Path(a.json).expanduser().write_text(report_to_json(rep), encoding="utf-8")
    if a.stdout:
        print(md)
        return 0
    out = Path(a.out).expanduser() if a.out else home / "Documents/自动化体检" / f"自动化体检-{ctx.now:%Y%m%d-%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    counts = {t: sum(1 for it in rep.items if it.tier == t) for t in (ACT, WARN, OK)}
    print(f"报告：{out}")
    print(f"需要处理 {counts[ACT]} 项，注意 {counts[WARN]} 项，正常 {counts[OK]} 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
