#!/usr/bin/env python3
"""合成一台「有各种毛病的 Mac」：假的家目录、LaunchAgents、日志、hermes 任务文件，
以及伪造的 launchctl / crontab 输出（tests/fixtures/）。

测试用它；也可以直接跑，生成一份示例报告：
    python3 tests/scenario.py examples/sample-report.md
"""
from __future__ import annotations

import datetime as dt
import os
import plistlib
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import checkup  # noqa: E402

FIXTURES = HERE / "fixtures"
NOW = dt.datetime(2026, 11, 5, 10, 30)  # 周四上午
ALL_TOOLS = {checkup.LAUNCHCTL, checkup.CRONTAB}


def print_text(label: str, state: str, runs: int, last_exit: str, pid: int | None = None, home: str = "") -> str:
    """按 launchctl print 的格式（Tab 缩进）拼一段伪造输出，给没有单独 fixture 的任务用。"""
    lines = [f"gui/501/{label} = {{", "\tactive count = 0",
             f"\tpath = {home}/Library/LaunchAgents/{label}.plist", "\ttype = LaunchAgent", f"\tstate = {state}", "",
             "\tdomain = gui/501 [100005]", f"\truns = {runs}"]
    if pid:
        lines.append(f"\tpid = {pid}")
    lines += [f"\tlast exit code = {last_exit}", "}"]
    return "\n".join(lines) + "\n"


class FakeRunner(checkup.CommandRunner):
    """替换真实命令：按 fixtures 返回伪造输出。只读检查仍由父类 run() 执行。"""

    def __init__(self, home: Path, tools: set[str], extra_print: dict[str, str] | None = None, pmset: str = ""):
        super().__init__()
        self.home = home
        self.tools = tools
        self.extra_print = extra_print or {}
        self.pmset = pmset   # 伪造的 pmset -g log 输出（只在 tools 里有 checkup.PMSET 时会被调用）

    def available(self, path):
        return path in self.tools

    def _fixture(self, rel: str) -> str:
        return (FIXTURES / rel).read_text(encoding="utf-8").replace("/Users/nat", str(self.home))

    def _execute(self, argv, timeout):
        if argv[0] == checkup.LAUNCHCTL and argv[1] == "print-disabled":
            return checkup.CmdResult(0, self._fixture("print_disabled.txt"), "")
        if argv[0] == checkup.LAUNCHCTL and argv[1] == "print":
            label = argv[2].split("/", 2)[2]
            if label in self.extra_print:
                return checkup.CmdResult(0, self.extra_print[label], "")
            f = FIXTURES / "launchctl" / f"{label}.txt"
            if f.is_file():
                return checkup.CmdResult(0, self._fixture(f"launchctl/{label}.txt"), "")
            return checkup.CmdResult(113, "", f'Bad request.\nCould not find service "{label}" in domain for user gui: 501\n')
        if argv[0] == checkup.CRONTAB:
            return checkup.CmdResult(0, self._fixture("crontab.txt"), "")
        if argv[0] == checkup.PMSET:
            return checkup.CmdResult(0, self.pmset, "")
        raise AssertionError(f"测试里出现了没预料到的命令：{argv}")


def _touch(path: Path, when: dt.datetime | None, text: str = "", mode: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)
    if when is not None:
        ts = when.timestamp()
        os.utime(path, (ts, ts))
    return path


def _plist(agents: Path, filename: str, data: dict) -> Path:
    p = agents / filename
    with open(p, "wb") as f:
        plistlib.dump(data, f)
    p.chmod(0o644)
    return p


def build_scenario(root: Path, now: dt.datetime = NOW, tools: set[str] | None = None) -> checkup.Context:
    home = root / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    H = str(home)
    ago = lambda **kw: now - dt.timedelta(**kw)  # noqa: E731

    # 程序和脚本
    hermes = _touch(home / ".local/bin/hermes", None, "#!/bin/sh\n", 0o755)
    node = _touch(home / "bin/node", None, "#!/bin/sh\n", 0o755)
    npx = _touch(home / "bin/npx", None, "#!/bin/sh\n", 0o755)
    bash = _touch(home / "bin/bash", None, "#!/bin/sh\n", 0o755)
    zsh = _touch(home / "bin/zsh", None, "#!/bin/sh\n", 0o755)
    py = _touch(home / "bin/python3", None, "#!/bin/sh\n", 0o755)
    for rel in ("projects/lark-bridge/server.js", "projects/digital-twin/healthcheck.sh", "projects/niuma/server.js",
                "projects/niuma/worker.sh", "work/campaign/daily.py", "work/campaign/retry.py", "work/weekly/run.sh",
                "scripts/backup.sh", "scripts/quota_guard.py", "scripts/ops.sh",
                "Library/Mobile Documents/sync/run.sh"):
        _touch(home / rel, None)

    # 日志
    _touch(home / ".hermes/logs/gateway.log", ago(minutes=10), "".join(f"[info] heartbeat {i}\n" for i in range(30)))
    _touch(home / ".hermes/logs/gateway.err.log", ago(hours=3),
           "2026-11-05 07:28:01 WARNING reconnecting\n"
           "2026-11-05 07:29:12 ERROR websocket disconnected: app_secret=s3cr3tvalue123 Bearer abcdefghijklmnop\n"
           "2026-11-05 07:29:13 exiting with EX_TEMPFAIL\n")
    _touch(home / "logs/lark-bridge.err.log", ago(minutes=2),
           "Error: Cannot find module 'ws'\n    at Module._resolveFilename (node:internal/modules/cjs/loader:1145:15)\n")
    _touch(home / "logs/digital-twin.log", ago(days=3), "health ok\n")
    _touch(home / "logs/niuma-web.log", ago(minutes=1), "GET / 200\n")
    _touch(home / "logs/niuma-worker.log", ago(hours=2), "worker done\n")
    _touch(home / "logs/campaign.log", now.replace(hour=9, minute=0, second=40), "sent 120 messages\n")
    _touch(home / "logs/retry.log", now.replace(hour=9, minute=5, second=3), "today done\n")
    _touch(home / "logs/openclaw.log", ago(minutes=3), "listening\n")
    _touch(home / "work/weekly/weekly.log", dt.datetime(2026, 11, 2, 9, 0, 10), "zsh:1: command not found: lark-cli\n")

    _plist(agents, "ai.hermes.gateway.plist", {
        "Label": "ai.hermes.gateway", "ProgramArguments": [str(hermes), "gateway", "run"],
        "KeepAlive": True, "RunAtLoad": True,
        "StandardOutPath": f"{H}/.hermes/logs/gateway.log", "StandardErrorPath": f"{H}/.hermes/logs/gateway.err.log"})
    _plist(agents, "ai.lark-channel-bridge.server.plist", {
        "Label": "ai.lark-channel-bridge.server", "ProgramArguments": [str(node), f"{H}/projects/lark-bridge/server.js"],
        "KeepAlive": True, "StandardErrorPath": f"{H}/logs/lark-bridge.err.log"})
    _plist(agents, "cn.digital-twin.healthcheck.plist", {
        "Label": "cn.digital-twin.healthcheck", "ProgramArguments": [str(bash), f"{H}/projects/digital-twin/healthcheck.sh"],
        "StartInterval": 1800, "RunAtLoad": True,
        "StandardOutPath": f"{H}/logs/digital-twin.log", "StandardErrorPath": f"{H}/logs/digital-twin.log"})
    _plist(agents, "cn.digital-twin.report.plist", {
        "Label": "cn.digital-twin.report", "ProgramArguments": [str(bash), "~/projects/digital-twin/healthcheck.sh"],
        "StartInterval": 3600})
    _plist(agents, "cn.niuma-home.web.plist", {
        "Label": "cn.niuma-home.web", "ProgramArguments": [str(node), "server.js"],
        "WorkingDirectory": f"{H}/projects/niuma", "KeepAlive": True, "RunAtLoad": True,
        "StandardOutPath": f"{H}/logs/niuma-web.log"})
    _plist(agents, "cn.niuma-home.worker.plist", {
        "Label": "cn.niuma-home.worker", "ProgramArguments": [str(bash), f"{H}/projects/niuma/worker.sh"],
        "StartInterval": 3600, "StandardOutPath": f"{H}/logs/niuma-worker.log"})
    _plist(agents, "cn.lumiedu.openclaw.plist", {
        "Label": "cn.lumiedu.openclaw", "ProgramArguments": [str(npx), "-y", "@larksuite/openclaw-lark", "start"],
        "WorkingDirectory": f"{H}/projects/niuma", "KeepAlive": True, "StandardOutPath": f"{H}/logs/openclaw.log"})
    _plist(agents, "cn.lumiedu.campaign-daily.plist", {
        "Label": "cn.lumiedu.campaign-daily", "ProgramArguments": [str(py), f"{H}/work/campaign/daily.py"],
        "StartCalendarInterval": {"Hour": 9, "Minute": 0}, "StandardOutPath": f"{H}/logs/campaign.log"})
    _plist(agents, "cn.lumiedu.campaign-retry.plist", {
        "Label": "cn.lumiedu.campaign-retry", "ProgramArguments": [str(py), f"{H}/work/campaign/retry.py"],
        "StartCalendarInterval": [{"Hour": 9, "Minute": m} for m in range(0, 60, 5)],
        "StandardOutPath": f"{H}/logs/retry.log"})
    _plist(agents, "com.lumiedu.weekly-report.plist", {
        "Label": "com.lumiedu.weekly-report",
        "ProgramArguments": [str(zsh), "-lc", f"cd {H}/work/weekly && ./run.sh > {H}/work/weekly/out.txt"],
        "StartCalendarInterval": [{"Weekday": 1, "Hour": 9, "Minute": 0}],
        "StandardOutPath": f"{H}/work/weekly/weekly.log", "StandardErrorPath": f"{H}/work/weekly/weekly.log"})
    _plist(agents, "local.digitalworld.sync.plist", {
        "Label": "local.digitalworld.sync", "ProgramArguments": [str(bash), f"{H}/projects/digitalworld/sync.sh"],
        "StartInterval": 600})
    _plist(agents, "local.digitalworld.sync.backup.plist", {
        "Label": "local.digitalworld.sync", "ProgramArguments": [str(bash), f"{H}/projects/digitalworld/sync.sh"],
        "StartInterval": 600})
    _plist(agents, "local.digitalworld.old.plist", {
        "Label": "local.digitalworld.old", "ProgramArguments": [str(bash), f"{H}/projects/digitalworld/old.sh"],
        "StartInterval": 600, "WorkingDirectory": f"{H}/projects/digitalworld"})
    _plist(agents, "cn.github-center.pull.plist", {
        "Label": "cn.github-center.pull", "ProgramArguments": [str(bash), f"{H}/scripts/backup.sh"],
        "StartInterval": 900})
    _plist(agents, "cn.personal-ai-workbench.server.plist", {
        "Label": "cn.personal-ai-workbench.server", "ProgramArguments": [str(node), f"{H}/projects/niuma/server.js"],
        "KeepAlive": True})
    _plist(agents, "com.openai.codex-quota-guard.plist", {
        "Label": "com.openai.codex-quota-guard", "ProgramArguments": [str(py), f"{H}/scripts/quota_guard.py"],
        "StartInterval": 600})
    _plist(agents, "ai.ops.codex.plist", {
        "Label": "ai.ops.codex", "ProgramArguments": [str(bash), f"{H}/scripts/ops.sh"],
        "StartInterval": 300, "StandardOutPath": f"{H}/no-such-dir/ops.log"})
    _plist(agents, "com.google.keystone.agent.plist", {
        "Label": "com.google.keystone.agent", "Program": "/nonexistent/google", "StartInterval": 3600})
    _plist(agents, "ai.hermes.gateway.plist.bak", {"Label": "ai.hermes.gateway", "Program": "/old/hermes"})
    _plist(agents, "cn.old-thing.plist.disabled", {"Label": "cn.old-thing", "Program": "/old/thing"})
    (agents / "cn.lumiedu.moved.plist").symlink_to(home / "projects/moved-away/cn.lumiedu.moved.plist")
    (agents / "broken.plist").write_bytes(b"<?xml version='1.0'?><plist><dict><key>Label</key>")
    (agents / ".DS_Store").write_bytes(b"\0\0")

    # hermes 定时任务文件：默认 profile 和一个叫 work 的 profile
    (home / ".hermes/cron").mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "hermes_jobs.json", home / ".hermes/cron/jobs.json")
    (home / ".hermes/profiles/work/cron").mkdir(parents=True)
    shutil.copy(FIXTURES / "hermes_jobs_work.json", home / ".hermes/profiles/work/cron/jobs.json")

    extra = {
        "cn.digital-twin.report": print_text("cn.digital-twin.report", "not running", 4, "78: EX_CONFIG", home=H),
        "cn.lumiedu.openclaw": print_text("cn.lumiedu.openclaw", "running", 1, "(never exited)", 4321, home=H),
        "cn.lumiedu.campaign-retry": print_text("cn.lumiedu.campaign-retry", "not running", 12, "0", home=H),
    }
    cfg = checkup.load_config()
    cfg["tasks"] = {
        "ai.lark-channel-bridge.server": {"名字": "飞书频道桥", "做什么": "把飞书群消息转给各个机器人",
                                          "坏了影响": "飞书群里 @ 机器人没反应"},
        "com.lumiedu.weekly-report": {"名字": "路觅周报推送", "做什么": "每周一把上周数据汇总发到飞书群",
                                      "坏了影响": "周一早会没有周报"},
    }
    return checkup.Context(agents_dir=agents, home=home, uid=os.getuid(), now=now,
                           runner=FakeRunner(home, ALL_TOOLS if tools is None else tools, extra), cfg=cfg)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    # 用 /tmp：macOS 默认临时目录路径很长，示例报告里不该出现本机临时路径
    with tempfile.TemporaryDirectory(dir="/tmp" if os.path.isdir("/tmp") else None) as d:
        ctx = build_scenario(Path(d))
        md = checkup.render_markdown(checkup.run_checkup(ctx))
    if out:
        out.write_text(md, encoding="utf-8")
        print(f"示例报告：{out}")
    else:
        print(md)
