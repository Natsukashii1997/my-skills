#!/usr/bin/env python3
"""合成一台「有各种毛病的 Mac」：假的家目录、LaunchAgents、日志，以及伪造的 launchctl / hermes / crontab 输出。

测试用它；也可以直接跑，生成一份示例报告：
    python3 tests/scenario.py 示例报告.md
"""
from __future__ import annotations

import datetime as dt
import os
import plistlib
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import checkup  # noqa: E402

FIXTURES = HERE / "fixtures"
NOW = dt.datetime(2026, 11, 5, 10, 30)  # 周四上午


class FakeRunner(checkup.CommandRunner):
    """替换真实命令：按 fixtures 返回伪造输出。只读检查仍由父类 run() 执行。"""

    def __init__(self, home: Path, tools: dict[str, str | None]):
        super().__init__()
        self.home = home
        self.tools = tools

    def which(self, name):
        return self.tools.get(name)

    def _fixture(self, rel: str) -> str:
        return (FIXTURES / rel).read_text(encoding="utf-8").replace("/Users/nat", str(self.home))

    def _execute(self, argv, timeout):
        name = os.path.basename(argv[0])
        if name == "launchctl" and argv[1] == "print-disabled":
            return checkup.CmdResult(0, self._fixture("print_disabled.txt"), "")
        if name == "launchctl" and argv[1] == "print":
            label = argv[2].split("/", 2)[2]
            f = FIXTURES / "launchctl" / f"{label}.txt"
            if f.is_file():
                return checkup.CmdResult(0, self._fixture(f"launchctl/{label}.txt"), "")
            return checkup.CmdResult(113, "", f'Bad request.\nCould not find service "{label}" in domain for user gui: 501\n')
        if name == "hermes":
            return checkup.CmdResult(0, self._fixture("hermes_cron_list.txt"), "")
        if name == "crontab":
            return checkup.CmdResult(0, self._fixture("crontab.txt"), "")
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


def _plist(agents: Path, filename: str, data: dict) -> None:
    with open(agents / filename, "wb") as f:
        plistlib.dump(data, f)


def build_scenario(root: Path, now: dt.datetime = NOW, tools: dict | None = None) -> checkup.Context:
    home = root / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    H = str(home)
    ago = lambda **kw: now - dt.timedelta(**kw)  # noqa: E731

    # 程序和脚本
    hermes = _touch(home / ".local/bin/hermes", None, "#!/bin/sh\n", 0o755)
    node = _touch(home / "bin/node", None, "#!/bin/sh\n", 0o755)
    bash = _touch(home / "bin/bash", None, "#!/bin/sh\n", 0o755)
    zsh = _touch(home / "bin/zsh", None, "#!/bin/sh\n", 0o755)
    py = _touch(home / "bin/python3", None, "#!/bin/sh\n", 0o755)
    _touch(home / "projects/lark-bridge/server.js", None)
    _touch(home / "projects/digital-twin/healthcheck.sh", None)
    _touch(home / "projects/niuma/server.js", None)
    _touch(home / "projects/niuma/worker.sh", None)
    _touch(home / "work/campaign/daily.py", None)
    _touch(home / "work/weekly/run.sh", None)
    _touch(home / "scripts/backup.sh", None)
    _touch(home / "scripts/quota_guard.py", None)
    _touch(home / "scripts/ops.sh", None)

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
    _plist(agents, "cn.niuma-home.web.plist", {
        "Label": "cn.niuma-home.web", "ProgramArguments": [str(node), "server.js"],
        "WorkingDirectory": f"{H}/projects/niuma", "KeepAlive": True, "RunAtLoad": True,
        "StandardOutPath": f"{H}/logs/niuma-web.log"})
    _plist(agents, "cn.niuma-home.worker.plist", {
        "Label": "cn.niuma-home.worker", "ProgramArguments": [str(bash), f"{H}/projects/niuma/worker.sh"],
        "StartInterval": 3600, "StandardOutPath": f"{H}/logs/niuma-worker.log"})
    _plist(agents, "cn.lumiedu.campaign-daily.plist", {
        "Label": "cn.lumiedu.campaign-daily", "ProgramArguments": [str(py), f"{H}/work/campaign/daily.py"],
        "StartCalendarInterval": {"Hour": 9, "Minute": 0}, "StandardOutPath": f"{H}/logs/campaign.log"})
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

    if tools is None:
        tools = {"launchctl": "/bin/launchctl", "hermes": str(hermes), "crontab": "/usr/bin/crontab"}
    cfg = checkup.load_config()
    return checkup.Context(agents_dir=agents, home=home, uid=501, now=now,
                           runner=FakeRunner(home, tools), cfg=cfg)


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with tempfile.TemporaryDirectory() as d:
        ctx = build_scenario(Path(d))
        md = checkup.render_markdown(checkup.run_checkup(ctx)).replace(str(ctx.home), "~")
    if out:
        out.write_text(md, encoding="utf-8")
        print(f"示例报告：{out}")
    else:
        print(md)
