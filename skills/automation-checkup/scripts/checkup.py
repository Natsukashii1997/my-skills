#!/usr/bin/env python3
"""自动化体检：只读检查本机用户级 LaunchAgents、hermes 定时任务和 crontab，出一页 Markdown 报告。

只读保证：
- 外部命令只有两个程序、三种用法：/bin/launchctl print、/bin/launchctl print-disabled、/usr/bin/crontab -l。
  命令层按绝对路径和参数格式逐一核对，其他一律拒绝。
- hermes 定时任务直接读它的 jobs.json，不运行 hermes（运行 hermes 会触发它自己的启动维护，会写文件）。
- 不加载、不停止、不重启任何任务，不改、不挪、不删任何文件。唯一会写的是报告本身（.md 和同名 .json）。

用法：
    python3 checkup.py                       # 报告写到 ~/Documents/自动化体检/
    python3 checkup.py --out 报告.md          # 指定位置（同目录另存一份 .json，下次体检用来对比）
    python3 checkup.py --stdout              # 只打印报告，不写文件
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ACT = "需要处理"
WARN = "注意"
OK = "正常"
SEVERITY_RANK = {OK: 0, WARN: 1, ACT: 2}

SKILL_DIR = Path(__file__).resolve().parents[1]
REPORT_PREFIX = "自动化体检-"

DEFAULT_CONFIG = {
    "exclude_patterns": ["com.apple.*"],
    "include_labels": [],
    "quiet_labels": [],
    "aliases": {},
    "tasks": {},
    "hermes_homes": ["~/.hermes"],
    "excerpt_lines": 6,
    "scan_lines": 40,
    "grace_minutes": 15,
    "missed_runs_act": 3,
    "stale_hours_act": 24,
    "restart_runs_warn": 5,
    "restart_runs_act": 20,
    "log_size_warn_mb": 200,
    "recent_error_hours": 24,
    "hermes_overdue_minutes": 15,
}

# launchd 找「只写了名字的程序」时用的固定 PATH（_PATH_STDPATH），和 plist 里自己设的 PATH 无关
LAUNCHD_STD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

# ---------------------------------------------------------------------------
# 命令层：所有外部命令都从这里走，只放行查看类命令
# ---------------------------------------------------------------------------

LAUNCHCTL = "/bin/launchctl"
CRONTAB = "/usr/bin/crontab"
READ_ONLY_COMMANDS = (
    f"{LAUNCHCTL} print gui/<UID>/<Label>",
    f"{LAUNCHCTL} print-disabled gui/<UID>",
    f"{CRONTAB} -l",
)
_PRINT_TARGET = re.compile(r"^(gui|user)/\d+/[^\s/\-][^\s/]*$")
_DOMAIN_TARGET = re.compile(r"^(gui|user)/\d+$")
MAX_OUTPUT = 2 * 1024 * 1024


class ReadOnlyViolation(RuntimeError):
    pass


def assert_read_only(argv: list[str]) -> None:
    if len(argv) == 3 and argv[0] == LAUNCHCTL:
        if argv[1] == "print" and _PRINT_TARGET.match(argv[2]):
            return
        if argv[1] == "print-disabled" and _DOMAIN_TARGET.match(argv[2]):
            return
    if list(argv) == [CRONTAB, "-l"]:
        return
    raise ReadOnlyViolation(f"拒绝执行非只读命令：{' '.join(map(str, argv))}")


@dataclass
class CmdResult:
    rc: int
    out: str
    err: str


class CommandRunner:
    """真实命令层。测试里用子类替换 available 和 _execute，只读检查仍在 run() 里生效。"""

    def __init__(self):
        self.history: list[list[str]] = []

    def available(self, path: str) -> bool:
        return os.path.isfile(path) and os.access(path, os.X_OK)

    def run(self, argv: list[str], timeout: int = 15) -> CmdResult:
        assert_read_only(argv)
        self.history.append(list(argv))
        r = self._execute(argv, timeout)
        if len(r.out) > MAX_OUTPUT:
            r.out = r.out[:MAX_OUTPUT]
        return r

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
    loaded: bool | None  # None：没读到（不是「没加载」）
    state: str | None = None
    pid: int | None = None
    last_exit: int | None = None
    last_exit_text: str | None = None
    runs: int | None = None
    last_signal: str | None = None
    path: str | None = None
    error: str | None = None


def _int_prefix(text: str | None) -> int | None:
    if not text:
        return None
    m = re.match(r"\s*(-?\d+)", text)
    return int(m.group(1)) if m else None


def parse_launchctl_print(text: str) -> LaunchdState:
    """只取第一层的 `键 = 值`。launchctl 用 Tab 缩进：第一层是一个 Tab；嵌套块（arguments、
    environment、event triggers 等）是两个以上。没有 Tab 缩进时退回到按大括号数层级。"""
    top: dict[str, str] = {}
    lines = text.splitlines()
    tab_lines = [ln for ln in lines if ln.startswith("\t") and not ln.startswith("\t\t")]
    if tab_lines:
        for ln in tab_lines:
            s = ln.strip()
            if " = " in s and not s.endswith("{"):
                k, v = s.split(" = ", 1)
                top.setdefault(k.strip(), v.strip())
    else:
        depth = 0
        for ln in lines:
            s = ln.strip()
            if not s:
                continue
            if s.endswith("{"):
                depth += 1
                continue
            if s in ("}", "};"):
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
        path=top.get("path"),
    )


def is_not_found(r: CmdResult) -> bool:
    """只有明确说「找不到这个服务」才算没加载；其他失败（SSH、沙箱、无图形会话）算没读到。"""
    return "could not find service" in (r.err + r.out).lower()


def parse_print_disabled(text: str) -> tuple[set[str], set[str]]:
    """返回 (停用的, 明确启用的)。新版写 => disabled / enabled，旧版写 => true / false。"""
    disabled, enabled = set(), set()
    for m in re.finditer(r'"([^"]+)"\s*=>\s*(disabled|true|enabled|false)', text):
        (disabled if m.group(2) in ("disabled", "true") else enabled).add(m.group(1))
    return disabled, enabled


# ---------------------------------------------------------------------------
# 退出码的人话解释
# ---------------------------------------------------------------------------

SIGNALS = {
    1: ("SIGHUP", "会话断开"),
    2: ("SIGINT", "被中断"),
    6: ("SIGABRT", "程序自己崩溃中止"),
    9: ("SIGKILL", "被强制结束，可能是内存不够被系统杀掉，或有人强杀"),
    11: ("SIGSEGV", "程序崩溃"),
    13: ("SIGPIPE", "输出管道断了"),
    15: ("SIGTERM", "被要求退出，手动停止、重启、发版或关机时常见"),
}

EXIT_TEXT = {
    0: "正常结束",
    1: "一般性错误，具体原因要看日志",
    2: "用法或参数错误",
    64: "用法错误，参数不对",
    65: "输入数据有误",
    66: "找不到输入文件",
    69: "依赖的服务不可用",
    70: "程序内部出错",
    71: "系统错误",
    73: "无法创建输出文件",
    74: "读写出错",
    75: "临时失败，程序自己报告「暂时不行、稍后再试」，常见于网络或连接断开",
    76: "通信协议出错",
    77: "没有权限",
    78: "launchd 启动不了程序，常见于程序路径不对、没有执行权限、脚本第一行 #! 写错、日志或工作目录不存在",
    126: "无法执行，常见于文件放在「文稿」「桌面」「下载」或 iCloud 里被 macOS 隐私权限拦住，或者没有执行权限",
    127: "找不到命令，定时运行时能找到的命令比终端里少，脚本里用到的命令可能找不到",
}


def explain_exit(code: int | None) -> str:
    if code is None:
        return "还没有退出过"
    if code in EXIT_TEXT:
        return EXIT_TEXT[code]
    sig = exit_signal(code, None)
    if sig is not None:
        name, meaning = SIGNALS.get(sig, (f"信号 {sig}", "被信号结束"))
        return f"{meaning}（{name}）"
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
_CAL_RANGES = {"Minute": (0, 59), "Hour": (0, 23), "Day": (1, 31), "Weekday": (0, 7), "Month": (1, 12)}


class PlistValueError(ValueError):
    pass


def _calendar_entries(pl: dict) -> list[dict]:
    raw = pl.get("StartCalendarInterval")
    entries = [raw] if isinstance(raw, dict) else [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []
    clean = []
    for e in entries:
        c = {}
        for k, (lo, hi) in _CAL_RANGES.items():
            if k in e:
                v = e[k]
                if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
                    raise PlistValueError(f"StartCalendarInterval 里 {k} = {v!r} 不是有效值（应为 {lo}–{hi} 的整数）")
                c[k] = v
        clean.append(c)
    return clean


def _interval(pl: dict) -> int | None:
    v = pl.get("StartInterval")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


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
        date = "每" + WEEKDAYS[e["Weekday"]]
    else:
        date = "每天" if "Hour" in e else ""
    if "Hour" in e and "Minute" in e:
        time = f"{e['Hour']:02d}:{e['Minute']:02d}"
    elif "Hour" in e:
        time = f"{e['Hour']} 点内每分钟"
    elif "Minute" in e:
        time = f"每小时第 {e['Minute']} 分"
    else:
        time = "每分钟"
    return f"{date} {time}".strip()


def keepalive_kind(pl: dict) -> str | None:
    ka = pl.get("KeepAlive")
    if ka is True:
        return "always"
    if isinstance(ka, dict) and ka:
        return "on_failure" if ka.get("SuccessfulExit") is False and len(ka) == 1 else "conditional"
    return None


def schedule_kind(pl: dict) -> str:
    if keepalive_kind(pl):
        return "keepalive"
    if _interval(pl):
        return "interval"
    if _calendar_entries(pl):
        return "calendar"
    if pl.get("WatchPaths") or pl.get("QueueDirectories") or pl.get("StartOnMount"):
        return "watch"
    if pl.get("RunAtLoad"):
        return "runatload"
    return "manual"


def has_timed_schedule(pl: dict) -> bool:
    return bool(_interval(pl) or _calendar_entries(pl))


def describe_schedule(pl: dict) -> str:
    bits = []
    ka = keepalive_kind(pl)
    if ka == "always":
        bits.append("常驻：登录时启动，退出后自动重启")
    elif ka == "on_failure":
        bits.append("常驻（异常退出时自动重启）")
    elif ka == "conditional":
        bits.append("按条件常驻（" + "、".join(sorted(pl["KeepAlive"])) + "）")
    iv = _interval(pl)
    if iv:
        bits.append(_fmt_interval(iv))
    entries = _calendar_entries(pl)
    if entries:
        descs = [_describe_calendar_entry(e) for e in entries]
        same_day = {d.split(" ")[0] for d in descs}
        if len(descs) > 4 and len(same_day) == 1 and all(re.fullmatch(r"\S+ \d\d:\d\d", d) for d in descs):
            times = sorted(d.split(" ")[1] for d in descs)
            descs = [f"{next(iter(same_day))} {times[0]}–{times[-1]} 之间 {len(times)} 个时间点"]
        bits.append("、".join(descs[:3]) + f" 等 {len(descs)} 个时间点" if len(descs) > 4 else "、".join(descs))
    if pl.get("WatchPaths") or pl.get("QueueDirectories"):
        bits.append("监视的文件有变动时运行")
    if pl.get("StartOnMount"):
        bits.append("插入磁盘时运行")
    if pl.get("RunAtLoad") and ka != "always":
        bits.append("登录时运行一次")
    return "；".join(bits) if bits else "只在手动触发时运行"


def _fires_on_date(e: dict, day: dt.date) -> list[dt.datetime]:
    if "Month" in e and e["Month"] != day.month:
        return []
    launchd_wd = (day.weekday() + 1) % 7  # launchd：0 和 7 都是周日
    day_ok = "Day" in e and e["Day"] == day.day
    wd_ok = "Weekday" in e and e["Weekday"] % 7 == launchd_wd
    if "Day" in e and "Weekday" in e:
        if not (day_ok or wd_ok):  # 两个都写时按 cron 的「任一满足」（未在本机验证）
            return []
    elif "Day" in e and not day_ok:
        return []
    elif "Weekday" in e and not wd_ok:
        return []
    hours = [e["Hour"]] if "Hour" in e else range(24)
    minutes = [e["Minute"]] if "Minute" in e else range(60)
    return [dt.datetime.combine(day, dt.time(h, m)) for h in hours for m in minutes]


def iter_calendar_fires_desc(entries: list[dict], before: dt.datetime, max_days: int = 400):
    """从 before 往回，依次给出按计划应运行的时间点（含 before 本身）。"""
    for i in range(max_days):
        day = before.date() - dt.timedelta(days=i)
        times = {t for e in entries for t in _fires_on_date(e, day) if t <= before}
        yield from sorted(times, reverse=True)


def next_calendar_fire(entries: list[dict], after: dt.datetime, max_days: int = 400) -> dt.datetime | None:
    for i in range(max_days):
        day = after.date() + dt.timedelta(days=i)
        times = sorted(t for e in entries for t in _fires_on_date(e, day) if t > after)
        if times:
            return times[0]
    return None


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


def calendar_window_start(entries: list[dict], around: dt.datetime) -> int | None:
    """一天里的多个时间点集中在一段窗口里（跨度不超过 12 小时，常见于「当天补跑窗口」）时，
    返回窗口起点距 0 点的分钟数；时间点铺满全天（每小时、每 15 分钟一次）时返回 None。
    窗口可以跨午夜：取相邻时间点之间最大的空档作为一天的分界。"""
    if max_fires_per_day(entries, around) < 2:
        return None
    mins = sorted({t.hour * 60 + t.minute for i in range(7) for e in entries
                   for t in _fires_on_date(e, around.date() - dt.timedelta(days=i))})
    n = len(mins)
    gaps = [((mins[(i + 1) % n] - mins[i]) % 1440 or 1440, mins[(i + 1) % n]) for i in range(n)]
    largest, start = max(gaps)
    return start if 1440 - largest <= 720 else None


def count_missed_windows(entries: list[dict], start_min: int, last_ok: dt.datetime, cutoff: dt.datetime,
                         cap: int = 99) -> int:
    """按「窗口」数漏跑：日志最后更新所在窗口之后，有几个已经整段过去、却一行日志都没有的窗口。"""
    shift = dt.timedelta(minutes=start_min)
    key = lambda t: (t - shift).date()  # noqa: E731
    nxt = next_calendar_fire(entries, cutoff)
    ongoing = key(nxt) if nxt else None
    days: set = set()
    for t in iter_calendar_fires_desc(entries, cutoff):
        k = key(t)
        if k <= key(last_ok) or len(days) >= cap:
            break
        if k != ongoing:
            days.add(k)
    return len(days)


# ---------------------------------------------------------------------------
# 程序与路径
# ---------------------------------------------------------------------------

SHELLS = {"bash", "sh", "zsh", "dash", "fish", "ksh"}
PKG_RUNNERS = {"npx", "bunx", "uvx", "pnpx", "pipx"}
INTERPRETERS = SHELLS | PKG_RUNNERS | {"node", "deno", "bun", "tsx", "ts-node", "ruby", "perl", "php",
                                       "osascript", "uv", "pwsh", "python", "python3"}
SCRIPT_EXT = (".py", ".sh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php", ".scpt", ".applescript",
              ".zsh", ".bash", ".command")
INLINE_FLAGS = {"python": {"-c"}, "node": {"-e", "--eval", "-p", "--print"}, "ruby": {"-e"}, "perl": {"-e", "-E"},
                "osascript": {"-e"}, "php": {"-r"}, "bun": {"-e", "--eval"}, "deno": {"eval"}}
VALUE_FLAGS = {
    "python": {"-W", "-X", "-Q"},
    "node": {"-r", "--require", "--import", "--loader", "--experimental-loader", "--env-file", "-C",
             "--conditions", "--title", "--inspect-port", "--max-old-space-size"},
    "ruby": {"-I", "-r", "-C"},
    "perl": {"-I", "-M", "-m"},
    "uv": {"--with", "--python", "-p", "--project", "--directory", "--env-file", "--with-requirements",
           "--index-url", "--extra", "--group", "--package"},
    "shell": {"-o", "+o", "-O", "+O"},
}


def _family(base: str) -> str:
    if base in SHELLS:
        return "shell"
    if re.fullmatch(r"python(\d+(\.\d+)?)?", base):
        return "python"
    if base in ("node", "tsx", "ts-node"):
        return "node"
    return base


def _is_interpreter(path: str) -> bool:
    base = os.path.basename(path)
    return base in INTERPRETERS or re.fullmatch(r"python\d+(\.\d+)?", base) is not None


def _looks_like_path(a: str) -> bool:
    if "://" in a or a.startswith("@"):
        return False
    return a.startswith(("/", "~", "./", "../")) or a.endswith(SCRIPT_EXT)


def _expand(p: str, home: Path) -> str:
    if p == "~" or p.startswith("~/"):
        return str(home) + p[1:]
    return p


def _protected_dirs(home: Path) -> list[str]:
    return [str(home / d) for d in ("Documents", "Desktop", "Downloads", "Library/Mobile Documents")]


@dataclass
class ProgramCheck:
    program: str | None = None
    program_resolved: str | None = None
    program_exists: bool | None = None
    program_executable: bool | None = None
    program_relative_key: bool = False   # Program 键写了相对路径（launchd 要求绝对路径）
    script: str | None = None
    script_exists: bool | None = None
    inline: str | None = None
    inline_missing: list[str] = field(default_factory=list)
    workdir: str | None = None
    workdir_exists: bool | None = None
    tilde: list[str] = field(default_factory=list)       # launchd 不展开 ~ 的地方
    protected: list[str] = field(default_factory=list)   # 落在「文稿」等受隐私保护的文件夹里


def check_program(pl: dict, home: Path) -> ProgramCheck:
    pc = ProgramCheck()
    raw_args = pl.get("ProgramArguments") or []
    if not isinstance(raw_args, list):
        raise PlistValueError("ProgramArguments 不是列表")
    args = [str(a) for a in raw_args]
    globbing = pl.get("EnableGlobbing") is True
    if "Program" in pl and not isinstance(pl["Program"], str):
        raise PlistValueError("Program 不是文字")
    program = pl.get("Program") or (args[0] if args else None)
    rest = args[1:] if args else []
    pc.program = program
    protected = _protected_dirs(home)

    def note_protected(p: str | None):
        if p and any(p == d or p.startswith(d + "/") for d in protected) and p not in pc.protected:
            pc.protected.append(p)

    wd = pl.get("WorkingDirectory")
    if wd is not None and not isinstance(wd, str):
        raise PlistValueError("WorkingDirectory 不是文字")
    if wd:
        pc.workdir = wd
        if wd.startswith("~"):
            pc.tilde.append(f"工作目录 `{wd}`")
            pc.workdir_exists = None
        else:
            pc.workdir_exists = os.path.isdir(wd)
            note_protected(wd)
    if not program:
        return pc

    if program.startswith("~") and not (globbing and "Program" not in pl):
        pc.tilde.append(f"程序 `{program}`")
        return pc
    prog = _expand(program, home)
    if os.path.isabs(prog):
        pc.program_resolved = prog
    elif "Program" in pl:
        pc.program_relative_key = True
        return pc
    else:
        pc.program_resolved = shutil.which(prog, path=LAUNCHD_STD_PATH)
    pc.program_exists = bool(pc.program_resolved) and os.path.exists(pc.program_resolved)
    if pc.program_exists:
        pc.program_executable = os.access(pc.program_resolved, os.X_OK)
        note_protected(pc.program_resolved)

    # /usr/bin/env [-S] [VAR=x] python3 x.py → 把 env 后面的解释器当程序看
    if os.path.basename(prog) == "env":
        while rest and (rest[0].startswith("-") or "=" in rest[0]):
            rest = rest[1:]
        if not rest:
            return pc
        prog, rest = rest[0], rest[1:]
    if not _is_interpreter(prog):
        return pc
    base = os.path.basename(prog)
    fam = _family(base)
    if base in PKG_RUNNERS:
        return pc  # npx 包名之类，不是文件，没法按文件核对
    value_flags = VALUE_FLAGS.get(fam, set())
    inline_flags = INLINE_FLAGS.get(fam, set())
    i = 0
    while i < len(rest):
        a = rest[i]
        if fam in ("uv", "deno", "bun") and a == "run":
            i += 1
            continue
        if a in inline_flags or (fam == "shell" and re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a)):
            pc.inline = rest[i + 1] if i + 1 < len(rest) else ""
            cwd = _expand(wd, home) if wd and not wd.startswith("~") else None
            pc.inline_missing = missing_in_shell(pc.inline, home, cwd)
            return pc
        if fam == "python" and a == "-m":
            return pc  # python -m 模块名，没法按文件核对
        if a.startswith("-") or a.startswith("+"):
            if a in value_flags and "=" not in a:
                i += 2
            else:
                i += 1
            continue
        if fam != "shell" and not _looks_like_path(a):
            return pc  # 子命令、包名、网址之类，不是脚本文件
        if "://" in a:
            return pc
        if a.startswith("~") and not globbing:
            pc.tilde.append(f"脚本参数 `{a}`")
            return pc
        p = _expand(a, home)
        if not os.path.isabs(p):
            if wd and wd.startswith("~"):
                return pc
            p = os.path.join(wd or "/", p)
        pc.script = p
        pc.script_exists = os.path.exists(p)
        note_protected(p)
        return pc
    return pc


_SHELL_KEYWORDS = {"exec", "nohup", "time", "command", "builtin", "then", "do", "else", "elif", "if", "while",
                   "until", "!", "{", "}", "caffeinate", "env"}
_SHELL_OPS = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&", "\n"}


def _shell_tokens(cmd: str) -> list[str] | None:
    try:
        lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        return None


def missing_in_shell(cmd: str, home: Path, cwd: str | None) -> list[str]:
    """一段 shell 命令里，「要执行的程序」和 `cd` 的目标里不存在的路径。
    只看这两类：输出文件、参数里提到的别的路径可能是任务自己要生成的，不报。"""
    toks = _shell_tokens(cmd)
    if not toks:
        return []
    missing: list[str] = []

    def resolve(w: str) -> str | None:
        if any(ch in w for ch in "$`*?[") or "://" in w:
            return None
        w = _expand(w.replace("$HOME", str(home)), home)
        if os.path.isabs(w):
            return w
        return os.path.join(cwd, w) if cwd else None

    def check(w: str, want_dir: bool = False):
        p = resolve(w)
        if p and not (os.path.isdir(p) if want_dir else os.path.exists(p)) and p not in missing:
            missing.append(p)

    segs, cur = [], []
    for t in toks:
        if t in _SHELL_OPS or set(t) <= set(";&|()"):
            segs.append(cur)
            cur = []
        else:
            cur.append(t)
    segs.append(cur)
    for seg in segs:
        words = []
        skip_next = False
        for t in seg:
            if skip_next:
                skip_next = False
                continue
            if re.fullmatch(r"\d*[<>]+&?\d*", t) or t in ("<", ">", ">>", "2>", "&>"):
                skip_next = not re.search(r"&\d$", t)
                continue
            words.append(t)
        while words and (words[0] in _SHELL_KEYWORDS or re.fullmatch(r"[A-Za-z_]\w*=.*", words[0])
                         or (words[0].startswith("-") and len(words) > 1)):
            words = words[1:]
        if not words:
            continue
        w0 = words[0]
        if w0 == "cd":
            if len(words) > 1:
                check(words[1], want_dir=True)
                p = resolve(words[1])
                cwd = p if p and os.path.isdir(p) else None  # cd 失败后，相对它的路径不再推算
            continue
        if w0 in ("source", "."):
            if len(words) > 1:
                check(words[1])
            continue
        if "/" in w0:
            check(w0)
            continue
        if _is_interpreter(w0) and os.path.basename(w0) not in PKG_RUNNERS:
            shell = os.path.basename(w0) in SHELLS
            for a in words[1:]:
                if a.startswith("-"):
                    if a in ("-c", "-m", "-e") or (shell and re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", a)):
                        break
                    continue
                if shell or a.endswith(SCRIPT_EXT):
                    check(a)
                    break
                # 其他位置参数多半是某个选项的值（输出文件之类），跳过，接着找脚本
    return missing


# ---------------------------------------------------------------------------
# 日志：读末尾、脱敏、提炼原因
# ---------------------------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HIDDEN = "[已隐藏]"
_NOT_SECRET = r"(?!(?:expired|invalid|required|incorrect|missing|none|null|true|false|not|is|was|has|ok|error|" \
              r"failed|empty|mismatch|denied|refused|\[已隐藏\])\b)"
_KEYNAME = (r"(?:[A-Za-z0-9]+[_-])*(?:access|refresh|app|api|tenant|user|client|session|auth|bot|webhook|private)?[_-]?"
            r"(?:token|secret|password|passwd|pwd|api[_-]?key|access[_-]?key|private[_-]?key|authorization|"
            r"credentials?)(?:[_-]?[A-Za-z0-9]+)*")
_B = r"(?<![A-Za-z0-9_])"  # 前边界：不用 \b，中文紧贴时也能匹配


def _generic_secret(m: re.Match) -> str:
    t = m.group(0)
    if t.startswith("/"):
        return t  # 绝对路径
    if "/" in t and all(len(seg) < 16 or re.fullmatch(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", seg) for seg in t.split("/")):
        return t  # 相对路径：每一段都像普通名字
    if re.fullmatch(r"[0-9a-f]{7,64}", t):
        return t  # git / sha 哈希
    if re.fullmatch(r"[a-z0-9]+(?:[-_.][a-z0-9]+)+", t) or re.fullmatch(r"[A-Za-z]+(?:_[A-Za-z0-9]+)+", t):
        return t  # kebab / snake 名字、函数名
    if not (re.search(r"[A-Z]", t) and re.search(r"[a-z]", t) and re.search(r"\d", t)):
        return t
    return HIDDEN


REDACT_RULES = [
    # 带账号密码的 URL：scheme://user:pass@host
    (re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]*):([^/\s@]+)@"), r"\1\2:" + HIDDEN + "@"),
    # 群机器人 webhook：拿到地址就能往群里发消息
    (re.compile(r"(?i)(open\.(?:feishu\.cn|larksuite\.com)/open-apis/bot/v2/hook/)[\w\-]+"), r"\1" + HIDDEN),
    (re.compile(r"(?i)(hooks\.slack\.com/services/)\S+"), r"\1" + HIDDEN),
    (re.compile(r"(?i)(qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=)[\w\-]+"), r"\1" + HIDDEN),
    (re.compile(r"(?i)(oapi\.dingtalk\.com/robot/send\?access_token=)[\w\-]+"), r"\1" + HIDDEN),
    # URL 查询参数
    (re.compile(r"(?i)([?&](?:key|sig|signature|code|auth|token|access_token|secret|password|x-amz-signature|"
                r"x-amz-credential|apikey|api_key)=)[^&\s\"']+"), r"\1" + HIDDEN),
    # 请求头
    (re.compile(r"(?i)\b((?:proxy-)?authorization|set-cookie|cookie)(\s*[:=]\s*).+"), r"\1\2" + HIDDEN),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"), r"\1 " + HIDDEN),
    # 键值：app_secret=x、"token": "x"、LARK_APP_SECRET='x'、密码：x
    (re.compile(rf"(?i){_B}({_KEYNAME}['\"]?\s*[:=：]\s*)(['\"]?){_NOT_SECRET}(?![a-z]{{1,12}}\b)([^\s'\"，,;&]+)"),
     r"\1\2" + HIDDEN),
    (re.compile(r"(密码|口令|密钥|令牌)(\s*[:=：为是]\s*)([^\s，,;]+)"), r"\1\2" + HIDDEN),
    # 命令行参数：--token x、--password=x
    (re.compile(r"(?i)(--?(?:token|secret|password|passwd|pass|api[-_]?key|access[-_]?token|auth|app[-_]?secret)\b)"
                rf"(\s+|=){_NOT_SECRET}(\S+)"), r"\1\2" + HIDDEN),
    # 常见密钥前缀
    (re.compile(_B + r"(sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                r"xox[a-z]-[A-Za-z0-9\-]{10,}|xapp-[A-Za-z0-9\-]{10,}|(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}|"
                r"eyJ[\w\-]+\.[\w\-]+\.[\w\-]*|(?:t|u|ur)-[A-Za-z0-9_\-]{20,})"), HIDDEN),
    # 其他长串（大小写字母加数字混排才算）
    (re.compile(r"(?<![\w/.\-])[A-Za-z0-9_\-+/=]{32,}"), _generic_secret),
    # 手机号、邮箱
    (re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)"), r"\1****\2"),
    (re.compile(r"(?<![\w.%+-])([A-Za-z0-9])[A-Za-z0-9._%+-]*@([\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,})"), r"\1***@\2"),
]


def redact(line: str) -> str:
    for pat, rep in REDACT_RULES:
        line = pat.sub(rep, line)
    return line


ERROR_WORDS = re.compile(
    r"(?i)\b(error|exception|traceback|fatal|failed|failure|panic|denied|refused|timed out|timeout|"
    r"not found|no such file|unauthorized|forbidden|not permitted)\b|错误|失败|异常|报错|超时|拒绝")

# 从日志里提炼原因：（规则，人话）。按顺序优先，越具体越靠前。
CAUSE_RULES = [
    (r"command not found: (\S+)", "定时运行时找不到命令 {0}"),
    (r"(?:^|\s)([\w./-]+): command not found", "定时运行时找不到命令 {0}"),
    (r"Cannot find module '([^']+)'|No module named '?([\w.]+)'?", "项目缺少依赖 {0}，多半是更新后没重新安装"),
    (r"(?i)operation not permitted", "被 macOS 隐私权限拦住了（文件可能在「文稿」「桌面」「下载」或 iCloud 里）"),
    (r"(?i)permission denied", "没有权限"),
    (r"(?i)EADDRINUSE|address already in use", "端口被占用，可能已经有一个同样的进程在跑"),
    (r"(?i)\b401\b|unauthorized|invalid[_ ]?(?:access[_ ]?)?token|token (?:has )?expired|access token.*expired",
     "登录凭据可能过期或失效"),
    (r"(?i)ECONNREFUSED|connection refused", "连不上对方服务（对方没启动，或地址端口不对）"),
    (r"(?i)ENOTFOUND|getaddrinfo|name or service not known|nodename nor servname", "网络断了或域名解析失败"),
    (r"(?i)ETIMEDOUT|timed out|timeout", "连接超时"),
    (r"(?i)no space left on device", "磁盘满了"),
    (r"(?i)out of memory|MemoryError|heap out of memory", "内存不够"),
    (r"(?i)no such file or directory", "找不到某个文件或文件夹"),
    (r"^(\w+(?:Error|Exception))\b", "程序报错（{0}）"),
]
_CAUSE_RES = [(re.compile(p), s) for p, s in CAUSE_RULES]


def find_cause(lines: list[str]) -> tuple[str, str] | None:
    """返回 (日志原文那一行, 人话原因)。"""
    for rx, summary in _CAUSE_RES:
        for ln in reversed(lines):
            m = rx.search(ln.strip())
            if m:
                arg = next((g for g in m.groups() if g), "") if m.groups() else ""
                return ln.strip()[:200], summary.format(f"`{arg}`" if arg else "").replace("  ", " ")
    return None


@dataclass
class LogInfo:
    kind: str
    path: str
    exists: bool = False
    special: bool = False       # /dev/null、管道等，不是普通文件
    tilde: bool = False         # 路径以 ~ 开头，launchd 不展开
    dir_exists: bool = True
    unreadable: bool = False
    mtime: str | None = None
    size: int = 0
    lines: list[str] = field(default_factory=list)
    error_lines: int = 0


def read_tail(path: str, n: int, max_bytes: int = 64 * 1024) -> list[str]:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes))
        data = f.read()
    raw = data.decode("utf-8", errors="replace").splitlines()
    if size > max_bytes and raw:
        raw = raw[1:]  # 第一行是从中间截断的，可能是半个密钥，丢掉
    out, in_key = [], False
    for ln in raw:
        ln = ANSI.sub("", ln).rstrip()
        if re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", ln):
            in_key = True
            out.append("[已隐藏的私钥]")
            continue
        if in_key:
            if re.search(r"-----END [A-Z ]*PRIVATE KEY-----", ln):
                in_key = False
            continue
        if ln.strip():
            out.append(redact(ln)[:300])
    return out[-n:]


def inspect_log(kind: str, path: str, n: int) -> LogInfo:
    info = LogInfo(kind=kind, path=path)
    if not isinstance(path, str):
        raise PlistValueError(f"{kind}路径不是文字")
    if path.startswith("~"):
        info.tilde = True
        return info
    info.dir_exists = os.path.isdir(os.path.dirname(path) or "/")
    if os.path.exists(path) and not os.path.isfile(path):
        info.special = True
        return info
    if os.path.isfile(path):
        st = os.stat(path)
        info.exists = True
        info.size = st.st_size
        info.mtime = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
        try:
            info.lines = read_tail(path, n)
        except OSError:
            info.unreadable = True
        info.error_lines = sum(1 for ln in info.lines if ERROR_WORDS.search(ln))
    return info


def excerpt(logs: list[LogInfo], limit: int, fallback: bool = True) -> list[tuple[str, str, list[str]]]:
    """附录用的日志摘录：有报错行就取最后一处报错前后各 1 行；没有就取最后 3 行。错误日志优先。"""
    out = []
    for lg in sorted(logs, key=lambda l: 0 if l.kind == "错误日志" else 1):
        if not lg.lines:
            continue
        idx = [i for i, ln in enumerate(lg.lines) if ERROR_WORDS.search(ln)]
        if idx:
            last = idx[-1]
            lo = max(0, last - limit + 2)
            chunk = lg.lines[lo:last + 2][-limit:]
        elif lg.kind == "错误日志":
            chunk = lg.lines[-3:]
        else:
            continue
        out.append((lg.kind, lg.path, chunk))
    if not out and fallback:
        for lg in logs:
            if lg.lines:
                out.append((lg.kind, lg.path, lg.lines[-3:]))
                break
    return out


# ---------------------------------------------------------------------------
# 体检项
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str
    code: str        # 稳定的问题类型，用来和上次体检对比、合并同类项
    headline: str    # 不超过十几个字的短标题
    problem: str
    advice: str
    rank: int = 50   # 同一档里谁排前面：越小越急
    new: bool | None = None


@dataclass
class Item:
    key: str
    name: str
    kind: str        # job / file / residue / hermes / crontab
    label: str | None = None
    files: list[str] = field(default_factory=list)
    purpose: str | None = None
    impact: str | None = None
    findings: list[Finding] = field(default_factory=list)
    facts: list[list[str]] = field(default_factory=list)
    cause: list[str] | None = None          # [日志原文, 人话]
    excerpts: list = field(default_factory=list)
    raw: str | None = None
    blind: bool = False
    last_run: str | None = None
    next_run: str | None = None

    @property
    def tier(self) -> str:
        if not self.findings:
            return OK
        return max((f.severity for f in self.findings), key=SEVERITY_RANK.get)

    def add(self, severity: str, code: str, headline: str, problem: str, advice: str, rank: int = 50) -> Finding:
        f = Finding(severity, code, headline, problem, advice, rank)
        self.findings.append(f)
        return f

    def top(self) -> Finding | None:
        hits = [f for f in self.findings if f.severity == self.tier]
        return min(hits, key=lambda f: f.rank) if hits else None

    @property
    def urgency(self) -> int:
        t = self.top()
        return t.rank if t else 99


@dataclass
class Job:
    path: Path
    label: str
    plist: dict
    schedule: str = ""
    kind: str = "manual"
    plist_disabled: bool = False
    disabled_effective: bool = False   # 综合 launchctl 停用记录和 plist 的 Disabled 键之后的结论
    launchd: LaunchdState | None = None
    program: ProgramCheck | None = None
    logs: list[LogInfo] = field(default_factory=list)
    others: list[Path] = field(default_factory=list)  # 同 Label 的其他 plist
    perm_problem: str | None = None


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
    home: str
    agents_dir: str
    items: list[Item]
    excluded: list[str]
    notes: list[str]
    hermes_status: str
    crontab_status: str
    commands_run: list[list[str]]
    launchd_readable: bool = True
    previous: str | None = None
    resolved: list[str] = field(default_factory=list)


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


def task_meta(label: str, cfg: dict) -> tuple[str | None, str | None, str | None]:
    """返回 (中文名, 做什么, 坏了影响)。tasks 里精确登记的优先，其次 aliases 通配。"""
    t = cfg.get("tasks", {}).get(label) or {}
    name = t.get("名字")
    if not name:
        hits = [(len(p), n) for p, n in cfg.get("aliases", {}).items() if fnmatch.fnmatchcase(label, p)]
        name = max(hits)[1] if hits else None
    return name, t.get("做什么"), t.get("坏了影响")


def fmt_ago(t: dt.datetime, now: dt.datetime) -> str:
    sec = (now - t).total_seconds()
    if sec < 60:
        return "刚刚" if sec > -60 else _fmt_ahead(-sec)
    if sec < 3600:
        return f"{int(sec // 60)} 分钟前"
    if sec < 48 * 3600:
        return f"{int(sec // 3600)} 小时前"
    return f"{int(sec // 86400)} 天前"


def _fmt_ahead(sec: float) -> str:
    if sec < 3600:
        return f"{max(1, int(sec // 60))} 分钟后"
    if sec < 48 * 3600:
        return f"{int(sec // 3600)} 小时后"
    return f"{int(sec // 86400)} 天后"


def sp(t: str) -> str:
    """把时间嵌进中文句子：以数字开头的前面留一个空格，「今天」「昨天」开头的不留。"""
    return (" " + t) if t[:1].isdigit() else t


def fmt_time(t: dt.datetime, now: dt.datetime) -> str:
    if t.date() == now.date():
        day = "今天"
    elif t.date() == (now - dt.timedelta(days=1)).date():
        day = "昨天"
    elif t.date() == (now + dt.timedelta(days=1)).date():
        day = "明天"
    elif t.year == now.year:
        day = f"{t.month} 月 {t.day} 日"
    else:
        day = f"{t.year} 年 {t.month} 月 {t.day} 日"
    rel = fmt_ago(t, now) if t <= now + dt.timedelta(seconds=59) else _fmt_ahead((t - now).total_seconds())
    return f"{day} {t:%H:%M}（{rel}）"


RESIDUE_NAME = re.compile(r"(?i)[._-](bak|backup|old|orig|disabled|off|save|copy|tmp)\d*$|副本|~$|[._-]\d{8,}$")


def scan_agents_dir(ctx: Context):
    """返回 (要体检的 plist 路径, 残留文件路径, 被排除的文件名)。"""
    live, residue, excluded = [], [], []
    if not ctx.agents_dir.is_dir():
        return live, residue, excluded
    for p in sorted(ctx.agents_dir.iterdir()):
        if p.name == ".DS_Store" or (p.is_dir() and not p.is_symlink()):
            continue
        label_guess = p.name.split(".plist")[0]
        if _match_any(label_guess, ctx.cfg["exclude_patterns"]) and label_guess not in ctx.cfg["include_labels"]:
            excluded.append(p.name)
            continue
        (live if p.name.endswith(".plist") else residue).append(p)
    return live, residue, excluded


def read_plist(path: Path) -> dict:
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
        raise ValueError("不是普通文件")
    if st.st_size > 1024 * 1024:
        raise ValueError("文件超过 1 MB")
    with open(path, "rb") as f:
        data = plistlib.load(f)
    if not isinstance(data, dict):
        raise ValueError("最外层不是字典")
    return data


def plist_permission_problem(path: Path, uid: int) -> str | None:
    """launchd 拒绝加载属主不对、或组和其他人可写的 plist（登录时静默跳过）。"""
    try:
        st = os.stat(path)
    except OSError:
        return None
    if st.st_uid != uid:
        return "文件属主不是你"
    if st.st_mode & 0o022:
        return "文件权限允许别人改（组或其他人可写）"
    return None


def build_job(path: Path, pl: dict, ctx: Context) -> Job:
    label = pl.get("Label")
    label = label if isinstance(label, str) and label else path.name[:-len(".plist")]
    job = Job(path=path, label=label, plist=pl)
    job.schedule = describe_schedule(pl)
    job.kind = schedule_kind(pl)
    job.plist_disabled = pl.get("Disabled") is True
    job.disabled_effective = job.plist_disabled
    job.program = check_program(pl, ctx.home)
    job.perm_problem = plist_permission_problem(path, ctx.uid)
    out_p, err_p = pl.get("StandardOutPath"), pl.get("StandardErrorPath")
    n = ctx.cfg["scan_lines"]
    if out_p and out_p == err_p:
        job.logs.append(inspect_log("日志", out_p, n))
    else:
        if err_p:
            job.logs.append(inspect_log("错误日志", err_p, n))
        if out_p:
            job.logs.append(inspect_log("输出日志", out_p, n))
    return job


def _last_log_time(logs: list[LogInfo]) -> dt.datetime | None:
    times = [dt.datetime.fromisoformat(l.mtime) for l in logs if l.exists and l.mtime]
    return max(times) if times else None


def _exit_desc(ld: LaunchdState) -> str:
    if ld.last_exit is not None:
        return f"上次退出码 {ld.last_exit}：{explain_exit(ld.last_exit)}"
    if ld.last_signal:
        sig = exit_signal(None, ld.last_signal)
        return f"上次{explain_exit(-sig) if sig else '被信号结束'}"
    return "没有退出记录"


def assess_job(job: Job, ctx: Context, item: Item) -> None:
    cfg, now = ctx.cfg, ctx.now
    pc = job.program or ProgramCheck()
    ld = job.launchd
    loaded = ld.loaded if ld else None
    disabled = job.disabled_effective

    # --- 事实 ---
    item.facts.append(["计划", job.schedule])
    if ld is None:
        item.facts.append(["运行状态", "没读到（launchctl 不可用）"])
    elif loaded is None:
        item.facts.append(["运行状态", "没读到"])
    elif not loaded:
        item.facts.append(["运行状态", "没有加载" + ("（已停用）" if disabled else "")])
    else:
        st = {"running": "正在运行", "not running": "没在运行", "waiting": "等待中", "spawn scheduled": "等待重启",
              "spawning": "正在启动"}.get(ld.state or "", ld.state or "未知")
        if ld.state in ("not running", "waiting") and job.kind in ("interval", "calendar", "watch", "runatload",
                                                                      "manual"):
            st = "待命，到点才运行"
        if ld.runs is not None:
            st += f"，这次加载以来启动 {ld.runs} 次"
        item.facts.append(["运行状态", st])
        if ld.last_exit is not None:
            item.facts.append(["上次退出码", f"{ld.last_exit}，{explain_exit(ld.last_exit)}"])
    if pc.inline is not None:
        item.facts.append(["命令", redact(pc.inline)[:200]])
    elif pc.program:
        target = pc.script or pc.program_resolved or pc.program
        item.facts.append(["程序", target])
    timing_logs = [l for l in job.logs if l.kind in ("输出日志", "日志") and not l.special and not l.tilde]
    last_any = _last_log_time(job.logs)
    if not job.logs:
        item.facts.append(["日志", "没配置"])
    else:
        item.facts.append(["日志最后更新", fmt_time(last_any, now) if last_any else "日志文件不存在"])
    timing_last = _last_log_time(timing_logs)
    item.last_run = fmt_time(timing_last, now) if timing_last else None

    # --- 配置写法：launchd 根本跑不起来的 ---
    broken = False
    off = disabled  # 停用的任务，文件问题只算「注意」
    sev_file = WARN if off else ACT
    if pc.tilde or any(l.tilde for l in job.logs):
        where = pc.tilde + [f"{l.kind} `{l.path}`" for l in job.logs if l.tilde]
        broken = True
        item.add(sev_file, "tilde", "路径写了 ~，跑不起来",
                 f"配置里的路径用了 `~` 开头：{'、'.join(where)}。launchd 不会把 `~` 换成你的家目录，这些路径对它来说不存在，任务起不来。",
                 "把 `~` 改成完整路径（例如 /Users/你的用户名/…）后重新加载。agent 可以处理。", 42)
    if pc.program_relative_key:
        broken = True
        item.add(sev_file, "program_relative", "程序路径不完整",
                 f"配置里 Program 写的是 `{pc.program}`，launchd 要求写完整路径，否则不会运行。",
                 "改成完整路径后重新加载。agent 可以处理。", 44)
    zombie = False
    if pc.program and pc.program_exists is False and not pc.program_relative_key:
        zombie = True
        item.add(sev_file, "zombie", "程序已经不在了",
                 f"要运行的程序 `{pc.program}` 已经不存在（launchd 只在 /usr/bin、/bin 这几个系统目录里找只写了名字的程序）。"
                 + ("任务已停用，只是配置文件还留着。" if off else "这个任务每次触发都会失败。"),
                 "需要你定：这个任务还要吗？不要就挪走配置文件；要就改成正确的程序路径。", 45 if not off else 58)
    elif pc.script and pc.script_exists is False:
        zombie = True
        item.add(sev_file, "zombie", "脚本已经不在了",
                 f"要运行的脚本 `{pc.script}` 已经不存在，多半是项目挪了位置或删了。"
                 + ("任务已停用，只是配置文件还留着。" if off else "这个任务每次触发都会失败。"),
                 "需要你定：这个任务还要吗？不要就挪走配置文件；要就把路径改到脚本的新位置。", 45 if not off else 58)
    elif pc.inline_missing:
        zombie = True
        item.add(sev_file, "zombie", "命令里的路径不在了",
                 "命令要用到的 " + "、".join(f"`{p}`" for p in pc.inline_missing[:3]) + " 不存在，多半是项目挪了位置。",
                 "需要你定：这个任务还要吗？要就把命令里的路径改到新位置。", 45)
    elif pc.program_exists and pc.program_executable is False and not pc.script and pc.inline is None:
        broken = True
        item.add(sev_file, "no_exec", "程序没有执行权限",
                 f"程序 `{pc.program_resolved}` 没有执行权限，launchd 启动不了它。",
                 "给它加上执行权限。agent 可以处理。", 46)
    if pc.workdir and pc.workdir_exists is False and not zombie:
        broken = True
        item.add(sev_file, "workdir_missing", "工作目录不在了",
                 f"工作目录 `{pc.workdir}` 不存在，launchd 会直接启动失败。",
                 "需要你定：项目是不是挪走了？挪到哪就把工作目录改到哪。", 46)
    if not zombie:
        for lg in job.logs:
            if not lg.tilde and not lg.special and not lg.dir_exists:
                broken = True
                item.add(sev_file, "logdir_missing", "日志文件夹不在了",
                         f"{lg.kind}所在的文件夹 `{os.path.dirname(lg.path)}` 不存在，launchd 常因此直接启动失败（退出码 78）。",
                         "建好这个文件夹，或把日志路径改到存在的位置。agent 可以处理。", 46)
    dead = zombie or broken

    # --- 加载与停用 ---
    if disabled and not dead:
        item.add(WARN, "disabled", "已停用，文件还在",
                 "这个任务已被停用，不会自动运行，但配置文件还在。",
                 "需要你定：不用了就把配置文件挪走；还要用就重新启用。", 60)
    elif loaded is False and not dead:
        why = "可能被手动卸载过，或加载时出错"
        if job.perm_problem:
            why = f"原因很可能是{job.perm_problem}，launchd 因此拒绝加载"
        elif job.path.is_symlink():
            why += "；它是个软链接，也可能是登录时 launchd 没有跟随链接"
        if job.kind == "keepalive" or has_timed_schedule(job.plist) or job.kind == "watch":
            item.add(ACT, "not_loaded", "没加载，不会运行",
                     f"配置文件在，但系统里没有这个任务，它现在根本不会运行（{why}）。",
                     "需要你定：还要这个任务吗？要就重新加载（agent 可以处理），不要就挪走配置文件，否则下次登录它可能又回来。",
                     12 if job.kind == "keepalive" else 40)
        else:
            item.add(WARN, "not_loaded", "没加载",
                     f"配置文件在，但系统里没有这个任务（{why}）。它只在登录或手动触发时运行，影响可能不大。",
                     "需要你定：还要吗？不要就挪走配置文件。", 62)
    if job.perm_problem and not (loaded is False and not dead and not disabled):
        item.add(WARN, "plist_perm", "配置文件权限不对",
                 f"配置文件 `{job.path.name}`：{job.perm_problem}。launchd 下次加载时会拒绝它。",
                 "把文件改回只有你能改（agent 可以处理）。", 64)

    # --- 退出码与常驻服务 ---
    exit_flagged = dead  # 僵尸或配置坏了，失败退出只是症状，不再单列
    failing = False
    if ld is not None and loaded and not dead:
        sig = exit_signal(ld.last_exit, ld.last_signal)
        nonzero = ld.last_exit not in (None, 0) or sig is not None
        exit_desc = _exit_desc(ld)
        if job.kind == "keepalive":
            ka = keepalive_kind(job.plist)
            runs = ld.runs or 0
            if ld.state == "running":
                if sig == 15 and runs >= cfg["restart_runs_warn"]:
                    # 上次是被要求退出（SIGTERM）后重新拉起：发版、手动重启、注销时常见，不像崩溃。
                    # 只看得到最后一次，之前有没有崩溃过不知道，所以仍提醒一句，但不算「需要处理」。
                    exit_flagged = True
                    item.add(WARN, "service_sigterm", "重启过多次，不像崩溃",
                             f"常驻服务在跑，这次加载以来启动了 {runs} 次；但上次是被要求退出后重新拉起的，多半是发版或手动重启。",
                             "目前能用。如果最近没有重启或发版过它，再看日志确认有没有崩溃。", 20)
                elif runs >= cfg["restart_runs_act"]:
                    exit_flagged = failing = True
                    item.add(ACT, "service_flapping", "在反复崩溃又被拉起",
                             f"常驻服务在跑，但这次加载以来已经启动了 {runs} 次，说明在反复崩溃；{exit_desc}。",
                             "原因修好之前它会一直断断续续。原因在项目代码或依赖里的，要到项目里修。", 15)
                elif runs >= cfg["restart_runs_warn"]:
                    exit_flagged = failing = nonzero
                    if nonzero:
                        item.add(WARN, "service_restarted", "在跑，但崩溃重启过",
                                 f"常驻服务现在在跑，但这次加载以来启动了 {runs} 次，有过崩溃重启；{exit_desc}。",
                                 "目前能用。判断是偶发断线还是反复出错；反复出错再处理。", 18)
                    else:
                        exit_flagged = True
                        item.add(WARN, "service_restarted", "在反复退出又被拉起",
                                 f"常驻服务现在在跑，但这次加载以来启动了 {runs} 次，每次都是正常退出后被重新拉起。",
                                 "目前能用。如果它本该一直跑着不退出，说明程序在反复退出，值得查一下。", 18)
                elif nonzero and sig != 15:
                    exit_flagged = failing = True
                    item.add(WARN, "service_restarted", "在跑，之前崩过一次",
                             f"常驻服务现在在跑，但之前异常退出过一次，已被自动拉起；{exit_desc}。",
                             "目前能用，留意一下；下次体检又出现再处理。", 22)
            elif ka in ("on_failure", "conditional") and not nonzero:
                pass  # 成功退出后不再拉起，或条件没满足，按设计就不在跑
            elif ld.state in ("spawn scheduled", "waiting", "spawning") and not nonzero and runs < cfg["restart_runs_warn"]:
                exit_flagged = True
                item.add(WARN, "service_gap", "正在重启间隙",
                         "常驻服务此刻不在跑，正等着被重新拉起；上次是正常退出，可能刚好赶上重启间隙。",
                         "过几分钟再体检一次；还是这样再处理。", 24)
            else:
                exit_flagged = failing = True
                if ld.state in ("spawn scheduled", "waiting", "spawning"):
                    headline, state_desc = "停了，在反复重启", "此刻停着，系统正在等着重新拉起它（多半刚崩溃）"
                else:
                    headline, state_desc = "停了", "现在没在运行"
                item.add(ACT, "service_down", headline,
                         f"常驻服务{state_desc}；{exit_desc}。" + (f"这次加载以来已启动 {runs} 次。" if runs > 1 else ""),
                         "原因清楚后再重启它（agent 可以处理）；原因在项目代码或依赖里的，要先到项目里修。", 10)
        elif nonzero:
            exit_flagged = True
            if sig == 15:
                item.add(WARN, "run_stopped", "上次被中途停止",
                         f"上次运行被中途停止；{exit_desc}。",
                         "一般是手动停止或关机造成的；下次按计划运行正常就不用管。", 32)
            else:
                failing = True
                item.add(ACT, "run_failed", "上次运行失败",
                         f"上次运行失败；{exit_desc}。",
                         "原因修好后，等下次按计划运行确认；要马上验证的话，agent 会先说清手动触发会对外做什么。", 20)

    # --- 该跑没跑：只用输出日志判断（任务正常时往往不写错误日志） ---
    timed = has_timed_schedule(job.plist)
    if timed and not disabled and not dead and ld is not None and loaded and job.label not in cfg["quiet_labels"]:
        if not timing_logs:
            item.blind = True
        elif timing_last is None:
            if all(l.dir_exists for l in timing_logs):
                item.add(WARN, "log_never", "日志从没生成",
                         "配置里写了输出日志，但日志文件一直没生成。launchd 拉起任务时就会建这个文件，所以它可能从这次加载以来一次都没运行过。",
                         "等下一个计划时间点后再看；还没有就检查程序路径和权限。", 26)
        else:
            cutoff = now - dt.timedelta(minutes=cfg["grace_minutes"])
            by_window = False
            iv = _interval(job.plist)
            entries = _calendar_entries(job.plist)
            if entries:
                expected = last_calendar_fire(entries, cutoff)
                missed = count_calendar_fires(entries, timing_last, cutoff)
                start = calendar_window_start(entries, cutoff) if missed else None
                if start is not None:
                    by_window = True
                    missed = count_missed_windows(entries, start, timing_last, cutoff)
                if expected:
                    item.facts.append(["按计划最近一次应运行", fmt_time(expected, now)])
            else:
                missed = max(0, int((cutoff - timing_last).total_seconds() // iv))
            stale_h = (now - timing_last).total_seconds() / 3600
            if missed >= 1:
                if by_window:
                    what = f"之后有 {missed if missed < 99 else '至少 99'} 天按计划该运行，却没有日志"
                elif iv:
                    what = f"按计划这之后应该运行 {missed} 次"
                else:
                    what = f"按计划这之后应该运行 {missed if missed < 99 else '至少 99'} 次"
                gap = f"{int(stale_h // 24)} 天" if stale_h >= 48 else f"{int(stale_h)} 小时"
                sev = ACT if (missed >= cfg["missed_runs_act"] and stale_h >= cfg["stale_hours_act"]) else WARN
                sleep_note = ("每隔一段时间跑的任务，电脑睡眠（合盖）期间错过的点不会补跑；关机期间的也不补。"
                              if iv else "电脑关机期间错过的点不会补跑（睡眠期间错过的，醒来后会补跑一次）。")
                item.add(sev, "missed", f"{gap}没跑",
                         f"疑似该跑没跑：日志停在{sp(fmt_time(timing_last, now))}，{what}。{sleep_note}",
                         "agent 会先查那段时间电脑是不是在睡眠或关机；对得上就不用管，对不上再找原因。"
                         "如果这个任务平时就不写日志，可以让 agent 把它记为「不按日志判断」。", 30 if sev == ACT else 34)

    # --- 日志内容 ---
    if not exit_flagged:
        recent = [l for l in job.logs if l.exists and l.error_lines and l.mtime and
                  (now - dt.datetime.fromisoformat(l.mtime)).total_seconds() < cfg["recent_error_hours"] * 3600]
        if recent:
            n = sum(l.error_lines for l in recent)
            item.add(WARN, "log_errors", "日志里有报错",
                     f"退出状态正常，但日志末尾有 {n} 行带报错字样，是最近 {cfg['recent_error_hours']} 小时内写的。",
                     "如果是已知的无害提示可以忽略，否则说明任务有一部分没做成。", 36)
    for lg in job.logs:
        if lg.size >= cfg["log_size_warn_mb"] * 1024 * 1024:
            item.add(WARN, "log_big", "日志文件太大",
                     f"{lg.kind}已经 {lg.size // (1024 * 1024)} MB，持续增长会占满磁盘。",
                     "先压缩备份一份再清空（agent 可以处理，不会丢内容）。", 70)
        if lg.unreadable:
            item.add(WARN, "log_unreadable", "日志读不了",
                     f"{lg.kind} `{lg.path}` 读不了（没有权限），没法据此判断任务情况。",
                     "看一下这个文件的权限。", 72)

    # --- 原因与摘录 ---
    runtime_codes = {"service_down", "service_flapping", "service_restarted", "run_failed", "missed", "log_errors",
                     "service_sigterm", "service_gap", "run_stopped"}
    if any(f.code in runtime_codes for f in item.findings):
        lines = [ln for l in sorted(job.logs, key=lambda l: 0 if l.kind == "错误日志" else 1) for ln in l.lines]
        c = find_cause(lines)
        if c:
            item.cause = list(c)
        if failing and pc.protected and not (c and "隐私" in c[1]):
            hint = "程序或脚本在「文稿」等受 macOS 隐私保护的文件夹里，launchd 拉起的进程可能被拦住"
            item.cause = [item.cause[0], item.cause[1] + "；另外，" + hint] if item.cause else ["", hint]
        item.excerpts = excerpt(job.logs, cfg["excerpt_lines"], fallback=failing)
    # 退出码已经写进「问题」里的，详情里不再重复
    if any("上次退出码" in f.problem for f in item.findings):
        item.facts = [f for f in item.facts if f[0] != "上次退出码"]

    # --- 下次运行 ---
    if timed and loaded and not disabled:
        entries = _calendar_entries(job.plist)
        if entries:
            nxt = next_calendar_fire(entries, now)
            if nxt:
                item.next_run = fmt_time(nxt, now)


def assess_naming(job: Job, item: Item) -> None:
    stem = job.path.name[:-len(".plist")]
    if stem == job.label:
        return
    if RESIDUE_NAME.search(stem) and not job.others:
        item.add(WARN, "naming_backup", "文件名像备份",
                 f"文件名 `{job.path.name}` 像备份，但仍以 .plist 结尾，launchd 登录时会照样加载它。",
                 "需要你定：它是备份就挪走；在用就改成和任务名一致的文件名。", 66)
    elif not job.others:
        item.add(WARN, "naming_mismatch", "文件名和任务名不一致",
                 f"文件名 `{job.path.name}` 和里面的任务名（Label）`{job.label}` 不一致，排查时容易找错文件。",
                 "不影响运行；方便的时候把文件名改成和任务名一致。", 80)


def assess_residue(paths: list[Path], live_labels: set[str]) -> Item | None:
    if not paths:
        return None
    item = Item(key="residue", name="LaunchAgents 里的残留文件", kind="residue")
    for p in paths:
        try:
            if p.is_symlink() and not p.exists():
                label, note = None, f"断掉的软链接，指向 `{os.readlink(p)}`"
            else:
                pl = read_plist(p)
                label = pl.get("Label") if isinstance(pl.get("Label"), str) else None
                note = None
        except Exception:
            label, note = None, "不是可读的配置文件"
        if note is None:
            note = (f"是在用任务 `{label}` 的旧版本或备份" if label in live_labels
                    else f"对应的任务 `{label}` 已经不在用" if label else "不是可读的配置文件")
        item.facts.append([p.name, note])
    item.add(WARN, "residue", f"{len(paths)} 个残留文件",
             f"有 {len(paths)} 个不以 .plist 结尾的残留文件。launchd 一般不会加载它们，但留着容易和在用的配置混淆，改错文件。",
             "可以一次性挪到备份文件夹（agent 列清单给你确认一次就行，不删）。", 68)
    return item


# ---------------------------------------------------------------------------
# hermes 定时任务：直接读 jobs.json，不运行 hermes
# ---------------------------------------------------------------------------

def _parse_iso(s) -> dt.datetime | None:
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except ValueError:
        m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?([+-]\d\d:\d\d)?", s.strip())
        if not m:
            return None
        t = dt.datetime.fromisoformat(m.group(1) + (m.group(2) or ""))
    if t.tzinfo is not None:
        t = t.astimezone().replace(tzinfo=None)
    return t


def hermes_stores(ctx: Context) -> list[tuple[str, Path]]:
    """(profile 名, jobs.json 路径)。默认 profile 在 <home>/cron，其他在 <home>/profiles/<名>/cron。"""
    out = []
    for h in ctx.cfg.get("hermes_homes", []):
        base = Path(_expand(str(h), ctx.home))
        if not base.is_dir():
            continue
        out.append(("默认", base / "cron" / "jobs.json"))
        prof = base / "profiles"
        if prof.is_dir():
            for p in sorted(prof.iterdir()):
                if p.is_dir():
                    out.append((p.name, p / "cron" / "jobs.json"))
    return out


def _hermes_state(job: dict) -> str:
    """和 hermes 的 effective_job_state 一致：enabled=true 时不会显示为暂停。"""
    stored = str(job.get("state") or "").strip()
    if stored in ("completed", "error"):
        return stored
    if not job.get("enabled", True):
        return "paused" if (job.get("paused_at") or stored == "paused" or not stored) else stored
    return stored if stored and stored != "paused" else "scheduled"


def check_hermes(ctx: Context) -> tuple[list[Item], str]:
    stores = hermes_stores(ctx)
    if not stores:
        return [], "没找到 hermes 的数据目录（~/.hermes），跳过。"
    items, seen = [], 0
    for profile, path in stores:
        if not path.is_file():
            continue
        seen += 1
        it = Item(key=f"hermes:{profile}", name=f"hermes 定时任务（{profile}）", kind="hermes")
        try:
            st = os.stat(path)
            if st.st_size > 20 * 1024 * 1024:
                raise ValueError("文件超过 20 MB")
            with open(path, encoding="utf-8-sig") as f:
                raw = f.read()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = json.loads(raw, strict=False)
        except Exception as e:
            it.add(WARN, "hermes_unreadable", "任务文件读不了",
                   f"hermes 的定时任务文件 `{path}` 读不了（{type(e).__name__}），没法检查。",
                   "让 agent 用 hermes 自己的命令看一下（会触发 hermes 的启动维护，先征得你同意）。", 50)
            items.append(it)
            continue
        jobs = data.get("jobs", []) if isinstance(data, dict) else data if isinstance(data, list) else []
        if isinstance(jobs, dict):
            jobs = [dict(v, id=v.get("id", k)) for k, v in jobs.items() if isinstance(v, dict)]
        jobs = [j for j in jobs if isinstance(j, dict)]
        live = 0
        for j in jobs:
            name = str(j.get("name") or j.get("id") or "未命名")
            state = _hermes_state(j)
            if state == "completed" or (not j.get("enabled", True) and state != "paused"):
                continue
            live += 1
            sched = j.get("schedule_display") or (j.get("schedule") or {}).get("value") or "?"
            last = _parse_iso(j.get("last_run_at"))
            nxt = _parse_iso(j.get("next_run_at"))
            status = j.get("last_status")
            bits = [f"计划：{sched}"]
            if state == "paused":
                bits.append("已暂停")
            if last:
                st_cn = {"ok": "成功", "error": "失败", "delivery_failed": "结果没送达",
                         "delivery_queued": "结果发送中"}.get(status, status)
                bits.append(f"上次运行：{fmt_time(last, ctx.now)}" + (f"，{st_cn}" if status else ""))
            if nxt and state != "paused":
                bits.append(f"下次运行：{fmt_time(nxt, ctx.now)}")
            it.facts.append([redact(name), "；".join(bits)])
            jid = str(j.get("id") or name)
            if state == "error" or (status and status not in ("ok", "delivery_queued", "delivery_failed")):
                err = redact(str(j.get("last_error") or "没有错误信息").splitlines()[0])[:160]
                streak = int(j.get("failure_streak") or 0)
                it.add(ACT, f"hermes_failed:{jid}", f"「{name}」上次失败",
                       f"hermes 定时任务「{name}」上次运行失败：{err}" + (f"（已连续失败 {streak} 次）" if streak >= 2 else "") + "。",
                       "看失败原因；凭据过期、对方服务不通这类，要到对应项目或 hermes 配置里修。", 20)
            elif status == "delivery_failed":
                err = redact(str(j.get("last_delivery_error") or "没有错误信息").splitlines()[0])[:160]
                it.add(ACT, f"hermes_undelivered:{jid}", f"「{name}」结果没送达",
                       f"hermes 定时任务「{name}」跑完了，但结果没送到：{err}。",
                       "多半是发送渠道（飞书群、机器人）的配置或权限问题。", 22)
            if state == "paused":
                it.add(WARN, f"hermes_paused:{jid}", f"「{name}」已暂停",
                       f"hermes 定时任务「{name}」已暂停，不会运行。",
                       "需要你定：是故意暂停的吗？不是的话 agent 可以恢复。", 40)
            elif nxt and j.get("enabled", True) and state != "completed" and \
                    (ctx.now - nxt).total_seconds() > ctx.cfg["hermes_overdue_minutes"] * 60:
                it.add(ACT, f"hermes_overdue:{jid}", f"「{name}」过点没跑",
                       f"hermes 定时任务「{name}」本该在{sp(fmt_time(nxt, ctx.now))}运行，到现在还没跑。"
                       "多半是负责调度的 hermes 网关没在运行。",
                       "先看「飞书网关 Hermes」那一项是不是正常；网关恢复后会接着跑。", 14)
        if live == 0:
            continue
        it.name = f"hermes 定时任务（{profile}，{live} 个）"
        items.append(it)
    if seen == 0:
        return [], "hermes 数据目录里没有定时任务文件。"
    return items, f"读了 {seen} 份任务文件（只读，没有运行 hermes）"


# ---------------------------------------------------------------------------
# crontab
# ---------------------------------------------------------------------------

def _cron_command(line: str) -> str | None:
    s = line.strip()
    if s.startswith("@"):
        parts = s.split(None, 1)
        cmd = parts[1] if len(parts) > 1 else ""
    else:
        parts = s.split(None, 5)
        if len(parts) < 6:
            return None
        cmd = parts[5]
    return re.split(r"(?<!\\)%", cmd)[0]


def check_crontab(ctx: Context) -> tuple[Item | None, str]:
    if not ctx.runner.available(CRONTAB):
        return None, "没有 crontab 命令，跳过。"
    r = ctx.runner.run([CRONTAB, "-l"])
    if r.rc != 0:
        return None, "没有 crontab 定时任务。"
    entries = [ln.strip() for ln in r.out.splitlines() if ln.strip() and not ln.strip().startswith("#")
               and not re.match(r"^[A-Za-z_]\w*\s*=", ln.strip())]
    if not entries:
        return None, "crontab 里没有生效的条目。"
    item = Item(key="crontab", name=f"crontab 定时任务（{len(entries)} 条）", kind="crontab")
    for e in entries:
        item.facts.append(["", redact(e)[:160]])
        cmd = _cron_command(e)
        missing = missing_in_shell(cmd, ctx.home, str(ctx.home)) if cmd else []
        if missing:
            item.add(ACT, f"crontab_missing:{hashlib.sha1(e.encode()).hexdigest()[:8]}", "有一条指向的文件不在了",
                     f"crontab 这条要运行的 `{missing[0]}` 不存在，每次到点都会失败：`{redact(e)[:120]}`。",
                     "需要你定：这条还要吗？不要就从 crontab 里去掉（agent 会先备份），要就改成正确路径。", 60)
    return item, f"{len(entries)} 条"


# ---------------------------------------------------------------------------
# 总流程
# ---------------------------------------------------------------------------

def _file_item(p: Path, code: str, headline: str, problem: str, advice: str, rank: int) -> Item:
    it = Item(key=f"file:{p.name}", name=f"`{p.name}`", kind="file", files=[p.name])
    it.add(ACT, code, headline, problem, advice, rank)
    return it


def run_checkup(ctx: Context) -> Report:
    notes: list[str] = []
    has_launchctl = ctx.runner.available(LAUNCHCTL)
    disabled_set: set[str] = set()
    enabled_set: set[str] = set()
    if has_launchctl:
        r = ctx.runner.run([LAUNCHCTL, "print-disabled", f"gui/{ctx.uid}"])
        if r.rc == 0:
            disabled_set, enabled_set = parse_print_disabled(r.out)
    else:
        notes.append("这台机器上没有 launchctl，只检查了配置文件本身，没有运行状态。")

    if not ctx.agents_dir.is_dir():
        notes.append(f"没找到 {ctx.agents_dir}。")
    live, residue, excluded = scan_agents_dir(ctx)
    items: list[Item] = []
    jobs: list[Job] = []
    for p in live:
        if p.is_symlink() and not p.exists():
            items.append(_file_item(p, "link_broken", "链接断了，任务不会运行",
                                    f"`{p.name}` 是个链接，指向的 `{os.readlink(p)}` 已经不存在，launchd 加载不了它（多半是项目挪了位置或删了）。",
                                    "需要你定：这个任务还要吗？要就把链接改到配置文件的新位置，不要就挪走这个链接。", 45))
            continue
        try:
            pl = read_plist(p)
        except Exception as e:
            items.append(_file_item(p, "plist_broken", "配置文件坏了",
                                    f"配置文件读不出来（{type(e).__name__}），launchd 也加载不了它，这个任务不会运行。",
                                    "agent 可以查出具体哪里坏了；不用了就挪走。", 70))
            continue
        try:
            job = build_job(p, pl, ctx)
        except Exception as e:
            items.append(_file_item(p, "plist_bad_value", "配置里有读不懂的值",
                                    f"配置文件 `{p.name}` 里有读不懂的值：{e if isinstance(e, PlistValueError) else type(e).__name__}。"
                                    "launchd 可能也不按预期运行它。", "agent 可以查出具体是哪一项并改正。", 70))
            continue
        if _match_any(job.label, ctx.cfg["exclude_patterns"]) and job.label not in ctx.cfg["include_labels"]:
            excluded.append(p.name)
            continue
        jobs.append(job)

    # 同一个 Label 的多个 plist 合成一项：以 launchd 实际加载的那个为准
    by_label: dict[str, list[Job]] = {}
    for j in jobs:
        by_label.setdefault(j.label, []).append(j)
    launchd_unreadable = 0
    for label, group in by_label.items():
        state = None
        if has_launchctl:
            target = f"gui/{ctx.uid}/{label}"
            if _PRINT_TARGET.match(target):
                r = ctx.runner.run([LAUNCHCTL, "print", target])
                if r.rc == 0:
                    state = parse_launchctl_print(r.out)
                elif is_not_found(r):
                    state = LaunchdState(loaded=False)
                else:
                    state = LaunchdState(loaded=None, error=(r.err or r.out).strip()[:200])
                    launchd_unreadable += 1
            else:
                state = LaunchdState(loaded=None, error="任务名里有特殊字符，没有查询")
        primary = group[0]
        if state and state.path:
            for j in group:
                try:
                    if os.path.realpath(j.path) == os.path.realpath(state.path) or str(j.path) == state.path:
                        primary = j
                except OSError:
                    pass
        elif len(group) > 1:
            primary = next((j for j in group if j.path.name == f"{label}.plist"), group[0])
        primary.others = [j.path for j in group if j is not primary]
        primary.launchd = state
        explicit_on = label in enabled_set
        primary.disabled_effective = (not explicit_on and (label in disabled_set or primary.plist_disabled)
                                       and not (state and state.loaded))
        name, purpose, impact = task_meta(label, ctx.cfg)
        it = Item(key=f"job:{label}", name=name or label, kind="job", label=label,
                  files=[primary.path.name] + [p.name for p in primary.others], purpose=purpose, impact=impact)
        try:
            assess_job(primary, ctx, it)
            assess_naming(primary, it)
        except Exception as e:
            it.findings = []
            it.add(ACT, "plist_bad_value", "配置里有读不懂的值",
                   f"体检这个任务时出错（{e if isinstance(e, PlistValueError) else type(e).__name__}），launchd 可能也不按预期运行它。",
                   "agent 可以查出具体是哪一项并改正。", 70)
        if primary.others:
            names = "、".join(f"`{p.name}`" for p in primary.others)
            sure = state is not None and state.path is not None
            it.add(ACT, "dup_label", "有多余的同名配置文件",
                   f"有 {len(group)} 个配置文件用了同一个任务名：系统{'正在用' if sure else '多半在用'}的是 `{primary.path.name}`，"
                   f"多出来的是 {names}。launchd 只会加载其中一个，改配置时很容易改错文件。",
                   "需要你定：确认多出来的是备份后挪走（agent 可以处理）。", 64)
        items.append(it)

    if launchd_unreadable:
        notes.append(f"有 {launchd_unreadable} 个任务没读到 launchd 状态（常见于在 SSH、沙箱或没有图形登录的环境里体检），"
                     "这些任务只检查了配置文件，没有按「没加载」判档。")
    res = assess_residue(residue, set(by_label))
    if res:
        items.append(res)
    blind = [it for it in items if it.blind]
    if blind:
        notes.append(f"{len(blind)} 个定时任务没配输出日志，看不出有没有按时运行："
                     + "、".join(it.name for it in blind) + "。")

    hermes_status = "未检查"
    if ctx.check_hermes:
        hitems, hermes_status = check_hermes(ctx)
        items.extend(hitems)
    crontab_status = "未检查"
    if ctx.check_crontab:
        it, crontab_status = check_crontab(ctx)
        if it:
            items.append(it)

    return Report(now=ctx.now.isoformat(timespec="minutes"), home=str(ctx.home), agents_dir=str(ctx.agents_dir),
                  items=items, excluded=sorted(excluded), notes=notes, hermes_status=hermes_status,
                  crontab_status=crontab_status, commands_run=list(ctx.runner.history),
                  launchd_readable=launchd_unreadable == 0)


# ---------------------------------------------------------------------------
# 和上次体检对比
# ---------------------------------------------------------------------------

def finding_keys(rep_or_data) -> dict[tuple[str, str], str]:
    if isinstance(rep_or_data, Report):
        return {(it.key, f.code): f"{it.name}：{f.headline}" for it in rep_or_data.items for f in it.findings}
    out = {}
    for it in rep_or_data.get("items", []):
        for f in it.get("findings", []):
            out[(it.get("key"), f.get("code"))] = f"{it.get('name')}：{f.get('headline')}"
    return out


def apply_history(rep: Report, prev_path: Path | None) -> None:
    if not prev_path:
        return
    try:
        prev = json.loads(prev_path.read_text(encoding="utf-8"))
        prev_keys = finding_keys(prev)
        prev_time = dt.datetime.fromisoformat(prev["now"])
    except Exception:
        return
    rep.previous = prev_time.isoformat(timespec="minutes")
    for it in rep.items:
        for f in it.findings:
            f.new = (it.key, f.code) not in prev_keys
    cur = finding_keys(rep)
    rep.resolved = [v for k, v in prev_keys.items() if k not in cur]


def find_previous(out_dir: Path, current_name: str) -> Path | None:
    if not out_dir.is_dir():
        return None
    cands = sorted(p for p in out_dir.glob(f"{REPORT_PREFIX}*.json") if p.name < current_name)
    return cands[-1] if cands else None


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

GROUPABLE = {"not_loaded", "disabled", "naming_mismatch", "plist_perm"}


def _ic(s: str) -> str:
    """行内代码：内容里的反引号换掉，免得把格式撑破。"""
    return "`" + str(s).replace("`", "'").replace("\n", " ") + "`"


def _fence(lines: list[str]) -> str:
    longest = max((len(m) for ln in lines for m in re.findall(r"`+|~+", ln)), default=0)
    return "`" * max(4, longest + 1)


def _sort_key(it: Item):
    return (it.urgency, {"job": 0, "file": 0, "hermes": 1, "crontab": 2, "residue": 3}.get(it.kind, 9), it.name)


def _display(it: Item) -> str:
    if it.kind == "job" and it.label and it.name != it.label:
        return f"{it.name} {_ic(it.label)}"
    if it.kind == "job":
        return _ic(it.name)
    return it.name


def _entries(items: list[Item], tier: str):
    """把一档里的体检项排好序，同类的（≥3 个只有同一种问题的）合成一条。返回 [(标题, [item...], 合并的 code)]。"""
    its = sorted([it for it in items if it.tier == tier], key=_sort_key)
    groups: dict[str, list[Item]] = {}
    for it in its:
        codes = {f.code for f in it.findings}
        if it.kind == "job" and len(codes) == 1 and next(iter(codes)) in GROUPABLE:
            groups.setdefault(next(iter(codes)), []).append(it)
    merged = {c for c, g in groups.items() if len(g) >= 3}
    out, done = [], set()
    for it in its:
        code = it.findings[0].code if it.findings else None
        if code in merged and it.kind == "job" and len({f.code for f in it.findings}) == 1:
            if code in done:
                continue
            done.add(code)
            g = groups[code]
            out.append((f"{len(g)} 个任务{g[0].top().headline}", g, code))
        else:
            head = it.top().headline if it.top() else ""
            if it.kind == "hermes":
                heads = [f.headline for f in sorted(it.findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.rank))]
                head = "；".join(heads[:2]) + (f" 等 {len(heads)} 个问题" if len(heads) > 2 else "")
            out.append((head, [it], None))
    return out


def render_markdown(rep: Report) -> str:
    now = dt.datetime.fromisoformat(rep.now)
    act, warn = _entries(rep.items, ACT), _entries(rep.items, WARN)
    ok = sorted([it for it in rep.items if it.tier == OK], key=_sort_key)
    n_jobs = sum(1 for it in rep.items if it.kind in ("job", "file"))
    new_count = sum(1 for it in rep.items for f in it.findings if f.new)
    extra = [x for x in ("hermes 定时任务" if any(it.kind == "hermes" for it in rep.items) else "",
                         "crontab" if any(it.kind == "crontab" for it in rep.items) else "") if x]
    L = ["# 自动化体检报告", "",
         f"体检时间：{now:%Y-%m-%d %H:%M}（本机时间）。共查 {n_jobs} 个后台任务"
         + (f"，外加 {'、'.join(extra)}" if extra else "")
         + (f"；按配置跳过 {len(rep.excluded)} 个系统或第三方任务" if rep.excluded else "") + "。", "",
         f"**结论：需要处理 {len(act)} 项，注意 {len(warn)} 项，其余 {len(ok)} 项正常。**", ""]
    if rep.previous:
        prev = dt.datetime.fromisoformat(rep.previous)
        L += [f"比上次体检（{fmt_time(prev, now)}）：新出现 {new_count} 个问题，已恢复 {len(rep.resolved)} 个"
              + ("：" + "；".join(rep.resolved[:5]) + ("等" if len(rep.resolved) > 5 else "") if rep.resolved else "")
              + "。", ""]

    num = 0
    index: list[tuple[int, str, list[Item], str | None]] = []
    for tier, entries in ((ACT, act), (WARN, warn)):
        for head, its, code in entries:
            num += 1
            index.append((num, head, its, code))
    if act:
        L.append("要处理的：")
        for n, head, its, code in index[:len(act)]:
            it = its[0]
            who = "、".join(x.name for x in its[:4]) + ("等" if len(its) > 4 else "") if code else it.name
            why = f"（{it.cause[1]}）" if (not code and it.cause and it.cause[1]) else ""
            new = " 〔新〕" if any(f.new for x in its for f in x.findings) else ""
            L.append(f"{n}. {who}：{head}{why}{new}")
        L.append("")
    L += ["> 这份报告是只读生成的：没有启动、停止、重启或修改任何任务，也没有动任何文件。",
          "> 要处理哪一条，告诉 agent 编号；它会先说清楚要做什么、怎么回退，你同意了才动手。", ""]

    appendix: list[tuple[int, str, list]] = []
    pos = 0
    for tier, entries in ((ACT, act), (WARN, warn)):
        L += [f"## {tier}（{len(entries)}）", ""]
        if not entries:
            L += ["无。", ""]
        for head, its, code in entries:
            pos += 1
            if code:
                f0 = its[0].top()
                L += [f"### {pos}. {len(its)} 个任务{f0.headline}", ""]
                for x in its:
                    tag = " 〔新〕" if any(f.new for f in x.findings) else ""
                    L.append(f"- {_display(x)}{tag}")
                L += ["", f"- **问题**：{re.sub(r'这个任务', '这些任务', f0.problem)}",
                      f"- **怎么办**：{f0.advice}可以一次确认、逐个处理。", ""]
                continue
            it = its[0]
            new = " 〔新〕" if any(f.new for f in it.findings) else ""
            L += [f"### {pos}. {_display(it)} —— {head}{new}", ""]
            if it.purpose:
                L.append(f"- **做什么**：{it.purpose}")
            if it.impact:
                L.append(f"- **坏了影响**：{it.impact}")
            for f in sorted(it.findings, key=lambda f: (-SEVERITY_RANK[f.severity], f.rank)):
                tag = "" if f.severity == tier else f"［{f.severity}］"
                L.append(f"- **问题**{tag}：{f.problem}")
                if it.cause and f is it.top():
                    line, why = it.cause
                    L.append(f"- **原因**：{why}" + (f"。日志原文：{_ic(line)}" if line else ""))
                L.append(f"- **怎么办**：{f.advice}")
            details = [f"{k}：{v}" if k else v for k, v in it.facts]
            if it.next_run:
                details.append(f"下次按计划运行：{it.next_run}")
            if it.kind in ("residue", "hermes", "crontab"):
                L += [f"  - {_ic(d) if it.kind == 'crontab' else d}" for d in details]
            elif details:
                L.append("- 详情：" + "｜".join(details))
            if len(it.files) > 1 or (it.kind == "job" and it.files and it.files[0] != f"{it.label}.plist"):
                L.append("- 配置文件：" + "、".join(_ic(x) for x in it.files))
            if it.excerpts:
                appendix.append((pos, it.name, it.excerpts))
                L.append(f"- 日志摘录见文末附录 {pos}。")
            L.append("")

    L += [f"## {OK}（{len(ok)}）", ""]
    ok_jobs = [it for it in ok if it.kind == "job"]
    if ok_jobs:
        L += ["| 任务 | 计划 | 最近一次运行 | 下次运行 |", "|---|---|---|---|"]
        for it in ok_jobs:
            facts = dict((k, v) for k, v in it.facts)
            if it.blind:
                last = "看不出（没配输出日志）"
            elif it.last_run:
                last = it.last_run
            elif "常驻" in facts.get("计划", ""):
                last = facts.get("运行状态", "").split("，")[0]
            else:
                last = "—"
            label = it.name if it.name == it.label else f"{it.name}（{it.label}）"
            L.append(f"| {label.replace('|', '/')} | {facts.get('计划', '').replace('|', '/')} | {last} | "
                     f"{it.next_run or '—'} |")
        L.append("")
    for it in ok:
        if it.kind != "job":
            L += [f"**{it.name}**：没发现问题。", ""]
            L += [f"- {k}：{v}" if k else f"- {_ic(v)}" for k, v in it.facts]
            if it.facts:
                L.append("")
    if not ok:
        L += ["无。", ""]

    L += ["## 说明与盲区", ""]
    for note in rep.notes:
        L.append(f"- {note}")
    L.append(f"- hermes 定时任务：{rep.hermes_status}")
    L.append(f"- crontab：{rep.crontab_status}")
    if rep.excluded:
        L.append("- 按配置跳过（系统或第三方）：" + "、".join(_ic(x) for x in rep.excluded))
    L.append("- 「该跑没跑」是用输出日志的最后修改时间推断的：任务平时不写日志、电脑那段时间睡眠或关机，都会让判断偏严。")
    kinds = sorted({" ".join([os.path.basename(c[0])] + (c[1:2] if os.path.basename(c[0]) == "launchctl" else c[1:]))
                    for c in rep.commands_run})
    L.append("- 本次只执行了这些查看命令：" + "、".join(_ic(k) for k in kinds) if kinds else "- 本次没有执行任何外部命令。")
    L += ["- 名词：配置文件（plist）是每个后台任务的设置；launchd 是 Mac 负责按时启动这些任务的系统程序；"
          "任务名（Label）是任务在系统里的名字；退出码是程序结束时留下的数字，0 表示正常。", ""]

    if appendix:
        L += ["## 附录：日志摘录", ""]
        for pos, name, exs in appendix:
            L.append(f"**{pos}. {name}**")
            L.append("")
            for kind, path, chunk in exs:
                fence = _fence(chunk)
                L += [f"{kind} {_ic(path)}：", "", fence + "text", *chunk, fence, ""]
    md = "\n".join(L)
    if rep.home and rep.home != "/":
        md = re.sub(re.escape(rep.home) + r"(?=/|\b)", "~", md)
    return md


def report_to_json(rep: Report) -> str:
    data = asdict(rep)
    for it, d in zip(rep.items, data["items"]):
        d["tier"] = it.tier
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _write_private(path: Path, text: str) -> None:
    """报告可能含任务和日志信息：只给自己读写。"""
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(path, 0o600)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="自动化体检（只读）：检查本机自建的定时任务和常驻服务，出一页报告。")
    ap.add_argument("--out", help="报告写到哪里（默认 ~/Documents/自动化体检/自动化体检-日期时间.md；同目录另存同名 .json）")
    ap.add_argument("--stdout", action="store_true", help="只把报告打印出来，不写文件")
    ap.add_argument("--config", help="额外的配置文件（JSON），覆盖 skill 目录里的 config.json")
    ap.add_argument("--agents-dir", help="要检查的 LaunchAgents 目录（默认 ~/Library/LaunchAgents）")
    ap.add_argument("--no-hermes", action="store_true", help="不检查 hermes 定时任务")
    ap.add_argument("--no-crontab", action="store_true", help="不检查 crontab")
    a = ap.parse_args(argv)

    home = Path.home()
    cfg = load_config(Path(a.config).expanduser() if a.config else None)
    ctx = Context(
        agents_dir=Path(a.agents_dir).expanduser() if a.agents_dir else home / "Library/LaunchAgents",
        home=home, uid=os.getuid(), now=dt.datetime.now().replace(microsecond=0),
        runner=CommandRunner(), cfg=cfg, check_hermes=not a.no_hermes, check_crontab=not a.no_crontab)
    rep = run_checkup(ctx)
    if a.stdout:
        print(render_markdown(rep))
        return 0
    out = Path(a.out).expanduser() if a.out else home / "Documents/自动化体检" / f"{REPORT_PREFIX}{ctx.now:%Y%m%d-%H%M}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    js = out.with_suffix(".json")
    apply_history(rep, find_previous(out.parent, js.name))
    _write_private(out, render_markdown(rep))
    _write_private(js, report_to_json(rep))
    tiers = [it.tier for it in rep.items]
    print(f"报告：{out}")
    print(f"需要处理 {len(_entries(rep.items, ACT))} 项，注意 {len(_entries(rep.items, WARN))} 项，"
          f"正常 {tiers.count(OK)} 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
