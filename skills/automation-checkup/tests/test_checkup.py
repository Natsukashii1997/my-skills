#!/usr/bin/env python3
"""自动化体检的测试：解析、判档、只读保证。全部用合成数据，Linux 上也能跑。

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import checkup  # noqa: E402
import scenario  # noqa: E402

FIX = HERE / "fixtures"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class ParseLaunchctlTests(unittest.TestCase):
    def test_running_service_with_restarts(self):
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.hermes.gateway.txt"))
        self.assertTrue(st.loaded)
        self.assertEqual(st.state, "running")
        self.assertEqual(st.pid, 48211)
        self.assertEqual(st.runs, 7)
        self.assertEqual(st.last_exit, 75)
        self.assertEqual(st.last_exit_text, "75: EX_TEMPFAIL")

    def test_nested_blocks_do_not_override_top_level(self):
        # 嵌套的 event triggers 里也有 state = 1，不能覆盖第一层的 state
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.hermes.gateway.txt"))
        self.assertEqual(st.state, "running")
        st2 = checkup.parse_launchctl_print(fixture("launchctl/cn.lumiedu.campaign-daily.txt"))
        self.assertEqual(st2.state, "not running")
        self.assertEqual(st2.last_exit, 0)

    def test_never_exited(self):
        st = checkup.parse_launchctl_print(fixture("launchctl/cn.niuma-home.web.txt"))
        self.assertIsNone(st.last_exit)
        self.assertEqual(st.last_exit_text, "(never exited)")

    def test_spawn_scheduled(self):
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.lark-channel-bridge.server.txt"))
        self.assertEqual(st.state, "spawn scheduled")
        self.assertEqual(st.last_exit, 1)
        self.assertIsNone(st.pid)

    def test_print_disabled_both_formats(self):
        d = checkup.parse_print_disabled(fixture("print_disabled.txt"))
        self.assertIn("cn.personal-ai-workbench.server", d)
        self.assertIn("ai.old.thing", d)  # 旧版 macOS 写 => true
        self.assertNotIn("com.openai.codex-quota-guard", d)  # enabled 不算停用


class ExitCodeTests(unittest.TestCase):
    def test_meanings(self):
        self.assertIn("正常", checkup.explain_exit(0))
        self.assertIn("EX_TEMPFAIL", checkup.explain_exit(75))
        self.assertIn("找不到命令", checkup.explain_exit(127))
        self.assertIn("SIGKILL", checkup.explain_exit(137))
        self.assertIn("SIGTERM", checkup.explain_exit(-15))
        self.assertIn("还没有退出过", checkup.explain_exit(None))

    def test_signal_detection(self):
        self.assertEqual(checkup.exit_signal(143, None), 15)
        self.assertEqual(checkup.exit_signal(None, "Killed: 9"), 9)
        self.assertIsNone(checkup.exit_signal(1, None))


class ScheduleTests(unittest.TestCase):
    def test_describe(self):
        self.assertEqual(checkup.describe_schedule({"StartInterval": 1800}), "每 30 分钟")
        self.assertEqual(checkup.describe_schedule({"StartInterval": 7200, "RunAtLoad": True}), "每 2 小时；登录时运行一次")
        self.assertEqual(checkup.describe_schedule({"StartCalendarInterval": {"Hour": 9, "Minute": 0}}), "每天 09:00")
        self.assertEqual(checkup.describe_schedule({"StartCalendarInterval": [{"Weekday": 1, "Hour": 9, "Minute": 30}]}),
                         "每周一 09:30")
        self.assertEqual(checkup.describe_schedule({"StartCalendarInterval": {"Minute": 5}}), "每小时第 5 分")
        self.assertEqual(checkup.describe_schedule({"StartCalendarInterval": {"Day": 1, "Hour": 8, "Minute": 0}}), "每月 1 日 08:00")
        self.assertEqual(checkup.describe_schedule({"KeepAlive": True, "RunAtLoad": True}), "常驻：登录时启动，退出后自动重启")
        self.assertEqual(checkup.describe_schedule({"KeepAlive": {"SuccessfulExit": False}}), "常驻（异常退出时自动重启）")
        self.assertEqual(checkup.describe_schedule({}), "只在手动触发时运行")

    def test_kind(self):
        self.assertEqual(checkup.schedule_kind({"KeepAlive": True, "StartInterval": 60}), "keepalive")
        self.assertEqual(checkup.schedule_kind({"StartInterval": 60}), "interval")
        self.assertEqual(checkup.schedule_kind({"StartCalendarInterval": {"Hour": 1}}), "calendar")
        self.assertEqual(checkup.schedule_kind({"RunAtLoad": True}), "runatload")

    def test_last_calendar_fire(self):
        now = dt.datetime(2026, 11, 5, 10, 30)  # 周四
        daily = [{"Hour": 9, "Minute": 0}]
        self.assertEqual(checkup.last_calendar_fire(daily, now), dt.datetime(2026, 11, 5, 9, 0))
        self.assertEqual(checkup.last_calendar_fire(daily, dt.datetime(2026, 11, 5, 8, 59)), dt.datetime(2026, 11, 4, 9, 0))
        monday = [{"Weekday": 1, "Hour": 9, "Minute": 0}]
        self.assertEqual(checkup.last_calendar_fire(monday, now), dt.datetime(2026, 11, 2, 9, 0))

    def test_sunday_is_0_and_7(self):
        now = dt.datetime(2026, 11, 5, 10, 30)
        for wd in (0, 7):
            self.assertEqual(checkup.last_calendar_fire([{"Weekday": wd, "Hour": 20, "Minute": 0}], now),
                             dt.datetime(2026, 11, 1, 20, 0))

    def test_count_missed(self):
        now = dt.datetime(2026, 11, 5, 10, 30)
        daily = [{"Hour": 9, "Minute": 0}]
        # 日志停在 11 月 1 日 09:05 → 之后漏了 2、3、4、5 日四次
        self.assertEqual(checkup.count_calendar_fires(daily, dt.datetime(2026, 11, 1, 9, 5), now), 4)
        self.assertEqual(checkup.count_calendar_fires(daily, dt.datetime(2026, 11, 5, 9, 0, 30), now), 0)
        hourly = [{"Minute": 0}]
        self.assertEqual(checkup.count_calendar_fires(hourly, dt.datetime(2026, 11, 5, 7, 30), now), 3)


class ProgramCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "proj").mkdir()
        (self.home / "proj/run.sh").write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def test_script_through_interpreter(self):
        pc = checkup.check_program({"ProgramArguments": ["/bin/bash", f"{self.home}/proj/run.sh"]}, self.home)
        self.assertEqual(pc.script, f"{self.home}/proj/run.sh")
        self.assertTrue(pc.script_exists)
        pc = checkup.check_program({"ProgramArguments": ["/bin/bash", f"{self.home}/gone/run.sh"]}, self.home)
        self.assertFalse(pc.script_exists)

    def test_relative_script_uses_working_directory(self):
        pc = checkup.check_program({"ProgramArguments": ["/usr/bin/python3", "-u", "run.sh"],
                                    "WorkingDirectory": f"{self.home}/proj"}, self.home)
        self.assertTrue(pc.script_exists)
        self.assertTrue(pc.workdir_exists)

    def test_env_and_uv_run(self):
        pc = checkup.check_program({"ProgramArguments": ["/usr/bin/env", "python3", "~/proj/missing.py"]}, self.home)
        self.assertEqual(pc.script, f"{self.home}/proj/missing.py")
        self.assertFalse(pc.script_exists)
        pc = checkup.check_program({"ProgramArguments": ["/opt/homebrew/bin/uv", "run", "~/proj/run.sh"]}, self.home)
        self.assertTrue(pc.script_exists)

    def test_inline_command_paths(self):
        cmd = f"cd {self.home}/proj && ./run.sh >> {self.home}/logs/new.log; {self.home}/gone/tool"
        pc = checkup.check_program({"ProgramArguments": ["/bin/zsh", "-lc", cmd]}, self.home)
        self.assertEqual(pc.inline, cmd)
        # 输出重定向的目标不算缺失；不存在的工具路径要报
        self.assertEqual(pc.inline_missing, [f"{self.home}/gone/tool"])

    def test_python_module_is_not_checked(self):
        pc = checkup.check_program({"ProgramArguments": ["/usr/bin/python3", "-m", "http.server"]}, self.home)
        self.assertIsNone(pc.script)
        self.assertIsNone(pc.inline)

    def test_missing_program(self):
        pc = checkup.check_program({"Program": f"{self.home}/bin/nope"}, self.home)
        self.assertFalse(pc.program_exists)


class RedactTests(unittest.TestCase):
    def test_secrets_hidden(self):
        line = ("app_secret=abc123456 token: xyz987654 Authorization=Basic Bearer abcdefghijklmnop "
                "sk-ABCDEFGHIJKLMNOP ghp_abcdefghijklmnopqrstuvwxyz0123")
        out = checkup.redact(line)
        for secret in ("abc123456", "xyz987654", "abcdefghijklmnop", "sk-ABCDEFGHIJKLMNOP", "ghp_abcdefghij"):
            self.assertNotIn(secret, out)
        self.assertIn("app_secret=[已隐藏]", out)

    def test_normal_text_kept(self):
        self.assertEqual(checkup.redact("sent 120 messages to 3 groups"), "sent 120 messages to 3 groups")


class ReadOnlyTests(unittest.TestCase):
    def test_allowed(self):
        for argv in (["launchctl", "print", "gui/501/x"], ["/bin/launchctl", "print-disabled", "gui/501"],
                     ["/Users/nat/.local/bin/hermes", "cron", "list"], ["crontab", "-l"]):
            checkup.assert_read_only(argv)

    def test_rejected(self):
        for argv in (["launchctl", "bootout", "gui/501/x"], ["launchctl", "kickstart", "-k", "gui/501/x"],
                     ["launchctl", "unload", "x.plist"], ["launchctl", "load", "x.plist"],
                     ["launchctl", "print", "gui/501/x", "extra"], ["kill", "-9", "123"],
                     ["hermes", "cron", "remove", "c-01"], ["crontab", "-r"], ["rm", "-rf", "/"], []):
            with self.assertRaises(checkup.ReadOnlyViolation, msg=str(argv)):
                checkup.assert_read_only(argv)

    def test_runner_enforces_guard_before_executing(self):
        class Spy(checkup.CommandRunner):
            executed = []

            def _execute(self, argv, timeout):
                self.executed.append(argv)
                return checkup.CmdResult(0, "", "")
        r = Spy()
        with self.assertRaises(checkup.ReadOnlyViolation):
            r.run(["launchctl", "bootout", "gui/501/x"])
        self.assertEqual(Spy.executed, [])

    def test_script_contains_no_mutating_calls(self):
        src = (HERE.parent / "scripts" / "checkup.py").read_text(encoding="utf-8")
        for word in ("bootout", "bootstrap", "kickstart", "unload", "os.kill", "os.remove", "os.unlink",
                     ".unlink(", "rmtree", "shutil.move", "os.rename", ".rename(", ".replace(", "os.system", "shell=True"):
            if word == ".replace(":
                # 字符串替换允许；只禁止 Path.replace（挪文件）
                self.assertIsNone(re.search(r"(path|Path|p|out)\.replace\(", src), "出现了 Path.replace")
                continue
            self.assertNotIn(word, src, f"脚本里出现了 {word}")


class ScenarioTests(unittest.TestCase):
    """合成一台有各种毛病的 Mac，检查每个任务分到哪一档。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ctx = scenario.build_scenario(Path(cls.tmp.name))
        cls.report = checkup.run_checkup(cls.ctx)
        cls.md = checkup.render_markdown(cls.report)
        cls.by_file = {Path(it.key).name: it for it in cls.report.items if it.kind == "job"}
        cls.by_kind = {it.kind: it for it in cls.report.items if it.kind != "job"}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def tier(self, filename):
        return self.by_file[filename].tier

    def problems(self, filename):
        return " ".join(f.problem for f in self.by_file[filename].findings)

    def test_tiers(self):
        expected = {
            "ai.lark-channel-bridge.server.plist": checkup.ACT,   # 常驻服务挂了、等待重启
            "com.lumiedu.weekly-report.plist": checkup.ACT,       # 上次退出码 127
            "cn.digital-twin.healthcheck.plist": checkup.ACT,     # 每 30 分钟，日志停了 3 天
            "cn.github-center.pull.plist": checkup.ACT,           # 文件在但没加载
            "local.digitalworld.sync.plist": checkup.ACT,         # 脚本不在了（僵尸）
            "local.digitalworld.sync.backup.plist": checkup.ACT,  # 同 Label 的第二个 plist
            "ai.ops.codex.plist": checkup.ACT,                    # 日志目录不存在
            "broken.plist": checkup.ACT,                          # plist 坏了
            "cn.lumiedu.moved.plist": checkup.ACT,                # 链接指向的 plist 已不存在
            "ai.hermes.gateway.plist": checkup.WARN,              # 在跑，但重启 7 次、上次退出码 75
            "cn.niuma-home.worker.plist": checkup.WARN,           # 每小时，漏了 1 次
            "cn.personal-ai-workbench.server.plist": checkup.WARN,  # 已停用
            "cn.niuma-home.web.plist": checkup.OK,
            "cn.lumiedu.campaign-daily.plist": checkup.OK,
            "com.openai.codex-quota-guard.plist": checkup.OK,     # 没配日志：正常但列入盲区
        }
        got = {name: self.tier(name) for name in expected}
        self.assertEqual(got, expected)
        self.assertEqual(set(self.by_file), set(expected))

    def test_third_party_excluded_and_listed(self):
        self.assertNotIn("com.google.keystone.agent.plist", self.by_file)
        self.assertIn("com.google.keystone.agent.plist", self.report.excluded)
        self.assertIn("com.google.keystone.agent.plist", self.md)

    def test_zombie_reported_once_as_cause(self):
        p = self.problems("local.digitalworld.sync.plist")
        self.assertIn("僵尸任务", p)
        self.assertNotIn("上次运行失败", p)  # 退出码 127 只是症状，不单列

    def test_hermes_restart_explained(self):
        p = self.problems("ai.hermes.gateway.plist")
        self.assertIn("启动了 7 次", p)
        self.assertIn("EX_TEMPFAIL", p)
        self.assertNotIn("退出码正常", p)

    def test_missed_runs_text(self):
        self.assertIn("该跑没跑", self.problems("cn.digital-twin.healthcheck.plist"))
        self.assertIn("应该运行 1 次", self.problems("cn.niuma-home.worker.plist"))

    def test_residue_listed(self):
        res = self.by_kind["residue"]
        self.assertEqual(res.tier, checkup.WARN)
        text = " ".join(res.facts)
        self.assertIn("ai.hermes.gateway.plist.bak", text)
        self.assertIn("是在用任务 `ai.hermes.gateway` 的旧版本或备份", text)
        self.assertIn("cn.old-thing.plist.disabled", text)
        self.assertNotIn(".DS_Store", text)

    def test_broken_symlink_explained(self):
        p = self.problems("cn.lumiedu.moved.plist")
        self.assertIn("是个链接", p)
        self.assertIn("moved-away", p)
        self.assertNotIn("读不出来", p)

    def test_duplicate_label_and_backup_name(self):
        p = self.problems("local.digitalworld.sync.backup.plist")
        self.assertIn("同一个 Label", p)
        self.assertIn("像备份", p)

    def test_hermes_cron_and_crontab(self):
        h = self.by_kind["hermes"]
        self.assertEqual(h.tier, checkup.WARN)
        self.assertIn("paused", h.raw)
        self.assertNotIn("abcd1234efgh5678", h.raw)  # 输出里的 token 被隐藏
        c = self.by_kind["crontab"]
        self.assertEqual(c.tier, checkup.ACT)
        self.assertIn("gone.sh", c.findings[0].problem)

    def test_only_read_only_commands_ran(self):
        self.assertTrue(self.report.commands_run)
        for argv in self.report.commands_run:
            checkup.assert_read_only(argv)

    def test_markdown_layout(self):
        md = self.md
        i_act, i_warn, i_ok = md.index("## 需要处理（"), md.index("## 注意（"), md.index("## 正常（")
        self.assertLess(i_act, i_warn)
        self.assertLess(i_warn, i_ok)
        self.assertIn("**结论：需要处理 10 项，注意 5 项，正常 3 项。**", md)
        self.assertIn("没有启动、停止、重启或修改任何任务", md)
        # 最急的排第一：常驻服务挂了
        first = re.search(r"^### 1\. (.+)$", md, re.M).group(1)
        self.assertIn("ai.lark-channel-bridge.server", first)
        # 日志末尾和密钥隐藏
        self.assertIn("Cannot find module 'ws'", md)
        self.assertNotIn("s3cr3tvalue123", md)
        self.assertIn("app_secret=[已隐藏]", md)
        # 每条问题都带建议
        self.assertEqual(md.count("- **问题**"), md.count("  **建议**"))

    def test_json_output(self):
        import json
        data = json.loads(checkup.report_to_json(self.report))
        tiers = {Path(i["key"]).name: i["tier"] for i in data["items"] if i["kind"] == "job"}
        self.assertEqual(tiers["cn.niuma-home.web.plist"], checkup.OK)


class AssessEdgeCaseTests(unittest.TestCase):
    """直接构造单个任务，检查容易误报的边界。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.prog = self.home / "run.sh"
        self.prog.write_text("")
        self.now = dt.datetime(2026, 11, 5, 10, 30)

    def tearDown(self):
        self.tmp.cleanup()

    def assess(self, plist: dict, state: checkup.LaunchdState) -> checkup.Item:
        plist = {"Label": "x.test", "ProgramArguments": ["/bin/sh", str(self.prog)], **plist}
        ctx = checkup.Context(agents_dir=self.home, home=self.home, uid=501, now=self.now,
                              runner=checkup.CommandRunner(), cfg=checkup.load_config())
        job = checkup.build_job(self.home / "x.test.plist", plist, ctx, set())
        job.launchd = state
        item = checkup.Item(key="x", title="x", kind="job")
        checkup.assess_job(job, ctx, item)
        return item

    def log(self, name: str, hours_ago: float) -> str:
        p = self.home / name
        p.write_text("line\n")
        ts = (self.now - dt.timedelta(hours=hours_ago)).timestamp()
        os.utime(p, (ts, ts))
        return str(p)

    def test_keepalive_down_without_exit_record(self):
        it = self.assess({"KeepAlive": True}, checkup.LaunchdState(loaded=True, state="not running"))
        self.assertEqual(it.tier, checkup.ACT)
        self.assertIn("没有退出记录", it.findings[0].problem)
        self.assertNotIn("None", it.findings[0].problem)

    def test_conditional_keepalive_idle_is_fine(self):
        it = self.assess({"KeepAlive": {"NetworkState": True}},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.OK)
        it = self.assess({"KeepAlive": {"SuccessfulExit": False}},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.OK)
        it = self.assess({"KeepAlive": {"SuccessfulExit": False}},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=1))
        self.assertEqual(it.tier, checkup.ACT)

    def test_stale_error_log_alone_is_not_missed_run(self):
        it = self.assess({"StartInterval": 600, "StandardErrorPath": self.log("err.log", 72)},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.OK)
        self.assertTrue(it.blind)

    def test_stale_output_log_is_missed_run(self):
        it = self.assess({"StartInterval": 600, "StandardOutPath": self.log("out.log", 72),
                          "StandardErrorPath": self.log("err.log", 0.1)},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.ACT)
        self.assertIn("该跑没跑", it.findings[0].problem)

    def test_sigterm_is_only_warning(self):
        it = self.assess({"StartInterval": 600}, checkup.LaunchdState(loaded=True, state="not running", last_exit=143))
        self.assertEqual(it.tier, checkup.WARN)

    def test_keepalive_many_restarts_is_action(self):
        it = self.assess({"KeepAlive": True},
                         checkup.LaunchdState(loaded=True, state="running", pid=9, runs=25, last_exit=1))
        self.assertEqual(it.tier, checkup.ACT)

    def test_keepalive_restarted_by_sigterm_is_not_crash(self):
        # 本机实测：数字世界悬浮窗启动 25 次，上次是 Terminated: 15（发版时主动重启），进程已稳定跑了 7 天
        it = self.assess({"KeepAlive": True},
                         checkup.LaunchdState(loaded=True, state="running", pid=9, runs=25,
                                              last_signal="Terminated: 15"))
        self.assertEqual(it.tier, checkup.WARN)
        self.assertIn("不像崩溃", it.findings[0].problem)
        self.assertNotIn("反复崩溃", it.findings[0].problem)

    def retry_window(self) -> list:
        return [{"Hour": h, "Minute": m} for h in range(6, 23) for m in (0, 30)]

    def test_same_day_retry_window_is_not_missed(self):
        # 本机实测：GitHub 中心每天 09:00 起每 15 分钟一个点，当天成功后后面的点不写日志
        it = self.assess({"StartCalendarInterval": self.retry_window(),
                          "StandardOutPath": self.log("out.log", 4.3)},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.OK)

    def test_retry_window_counts_missed_days(self):
        it = self.assess({"StartCalendarInterval": self.retry_window(),
                          "StandardOutPath": self.log("out.log", 72)},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.ACT)
        self.assertIn("3 天按计划该运行", it.findings[0].problem)

    def test_once_a_day_still_counts_runs(self):
        it = self.assess({"StartCalendarInterval": {"Hour": 9, "Minute": 0},
                          "StandardOutPath": self.log("out.log", 25.5)},
                         checkup.LaunchdState(loaded=True, state="not running", last_exit=0))
        self.assertEqual(it.tier, checkup.WARN)
        self.assertIn("应该运行 1 次", it.findings[0].problem)


class EnvironmentFallbackTests(unittest.TestCase):
    def test_without_launchctl_hermes_crontab(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d), tools={})
            rep = checkup.run_checkup(ctx)
            md = checkup.render_markdown(rep)
        self.assertEqual(rep.commands_run, [])
        self.assertIn("没有 launchctl", md)
        self.assertIn("没找到 hermes 命令", md)
        names = {Path(it.key).name: it for it in rep.items if it.kind == "job"}
        # 没有运行状态时，文件层面的问题照样能查出来
        self.assertEqual(names["local.digitalworld.sync.plist"].tier, checkup.ACT)
        self.assertEqual(names["broken.plist"].tier, checkup.ACT)

    def test_hermes_failure_is_warning(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))

            def failing(argv, timeout, orig=ctx.runner._execute):
                if os.path.basename(argv[0]) == "hermes":
                    return checkup.CmdResult(1, "", "gateway not reachable\n")
                return orig(argv, timeout)
            ctx.runner._execute = failing
            rep = checkup.run_checkup(ctx)
        h = next(it for it in rep.items if it.kind == "hermes")
        self.assertEqual(h.tier, checkup.WARN)
        self.assertIn("gateway not reachable", h.findings[0].problem)

    def test_quiet_label_skips_timing(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            ctx.cfg["quiet_labels"] = ["cn.niuma-home.worker"]
            rep = checkup.run_checkup(ctx)
        it = next(it for it in rep.items if Path(it.key).name == "cn.niuma-home.worker.plist")
        self.assertEqual(it.tier, checkup.OK)

    def test_main_writes_report(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "r.md"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = checkup.main(["--agents-dir", str(Path(d) / "none"), "--out", str(out), "--no-hermes", "--no-crontab"])
            self.assertIn("需要处理 0 项", buf.getvalue())
            self.assertEqual(rc, 0)
            self.assertIn("# 自动化体检报告", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
