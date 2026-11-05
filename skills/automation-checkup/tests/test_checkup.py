#!/usr/bin/env python3
"""自动化体检的测试：解析、判档、脱敏、只读保证。全部用合成数据，Linux 上也能跑。

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import ast
import contextlib
import datetime as dt
import io
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "checkup.py"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCRIPT.parent))

import checkup  # noqa: E402
import scenario  # noqa: E402

FIX = HERE / "fixtures"
ACT, WARN, OK = checkup.ACT, checkup.WARN, checkup.OK
NOW = dt.datetime(2026, 11, 5, 10, 30)  # 周四


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

class ParseLaunchctlTests(unittest.TestCase):
    def test_running_service_with_restarts(self):
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.hermes.gateway.txt"))
        self.assertEqual((st.loaded, st.state, st.pid, st.runs, st.last_exit), (True, "running", 48211, 7, 75))
        self.assertEqual(st.last_exit_text, "75: EX_TEMPFAIL")
        self.assertEqual(st.path, "/Users/nat/Library/LaunchAgents/ai.hermes.gateway.plist")

    def test_nested_blocks_do_not_override_top_level(self):
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.hermes.gateway.txt"))
        self.assertEqual(st.state, "running")  # event triggers 里的 state = 1 不算
        st2 = checkup.parse_launchctl_print(fixture("launchctl/cn.lumiedu.campaign-daily.txt"))
        self.assertEqual((st2.state, st2.last_exit), ("not running", 0))

    def test_multiline_inline_argument_does_not_break_parsing(self):
        text = ("gui/501/x = {\n\tstate = spawn scheduled\n\targuments = {\n\t\t/usr/bin/node\n\t\t-e\n"
                "\t\tsetInterval(() => {\nconsole.log(1)\n}, 60000)\n\t}\n\n\truns = 48\n\tlast exit code = 1\n}\n")
        st = checkup.parse_launchctl_print(text)
        self.assertEqual((st.state, st.runs, st.last_exit), ("spawn scheduled", 48, 1))

    def test_brace_fallback_without_tabs(self):
        text = "gui/501/x = {\n    state = running\n    sub = {\n        state = 1\n    }\n    runs = 2\n}\n"
        st = checkup.parse_launchctl_print(text)
        self.assertEqual((st.state, st.runs), ("running", 2))

    def test_never_exited_and_spawn_scheduled(self):
        self.assertIsNone(checkup.parse_launchctl_print(fixture("launchctl/cn.niuma-home.web.txt")).last_exit)
        st = checkup.parse_launchctl_print(fixture("launchctl/ai.lark-channel-bridge.server.txt"))
        self.assertEqual((st.state, st.last_exit, st.pid), ("spawn scheduled", 1, None))

    def test_print_disabled_both_formats(self):
        disabled, enabled = checkup.parse_print_disabled(fixture("print_disabled.txt"))
        self.assertIn("cn.personal-ai-workbench.server", disabled)
        self.assertIn("ai.old.thing", disabled)  # 旧版 macOS 写 => true
        self.assertIn("com.openai.codex-quota-guard", enabled)
        self.assertNotIn("com.openai.codex-quota-guard", disabled)

    def test_only_could_not_find_means_not_loaded(self):
        self.assertTrue(checkup.is_not_found(checkup.CmdResult(113, "", 'Could not find service "x" in domain')))
        self.assertFalse(checkup.is_not_found(checkup.CmdResult(125, "", "Domain does not support specified action")))
        self.assertFalse(checkup.is_not_found(checkup.CmdResult(1, "", "")))


class ExitCodeTests(unittest.TestCase):
    def test_meanings(self):
        self.assertIn("正常", checkup.explain_exit(0))
        self.assertIn("网络", checkup.explain_exit(75))
        self.assertIn("找不到命令", checkup.explain_exit(127))
        self.assertIn("隐私", checkup.explain_exit(126))
        self.assertIn("SIGKILL", checkup.explain_exit(137))
        self.assertIn("SIGTERM", checkup.explain_exit(-15))
        self.assertIn("还没有退出过", checkup.explain_exit(None))
        self.assertNotIn("EX_", checkup.explain_exit(78))

    def test_signal_detection(self):
        self.assertEqual(checkup.exit_signal(143, None), 15)
        self.assertEqual(checkup.exit_signal(None, "Terminated: 15"), 15)
        self.assertIsNone(checkup.exit_signal(1, None))


class ScheduleTests(unittest.TestCase):
    def test_describe(self):
        d = checkup.describe_schedule
        self.assertEqual(d({"StartInterval": 1800}), "每 30 分钟")
        self.assertEqual(d({"StartInterval": 7200, "RunAtLoad": True}), "每 2 小时；登录时运行一次")
        self.assertEqual(d({"StartCalendarInterval": {"Hour": 9, "Minute": 0}}), "每天 09:00")
        self.assertEqual(d({"StartCalendarInterval": [{"Weekday": 1, "Hour": 9, "Minute": 30}]}), "每周一 09:30")
        self.assertEqual(d({"StartCalendarInterval": {"Minute": 5}}), "每小时第 5 分")
        self.assertEqual(d({"StartCalendarInterval": {"Day": 1, "Hour": 8, "Minute": 0}}), "每月 1 日 08:00")
        self.assertEqual(d({"StartCalendarInterval": [{"Hour": 9, "Minute": m} for m in range(0, 60, 5)]}),
                         "每天 09:00–09:55 之间 12 个时间点")
        self.assertEqual(d({"KeepAlive": True, "RunAtLoad": True}), "常驻：登录时启动，退出后自动重启")
        self.assertEqual(d({"KeepAlive": {"SuccessfulExit": False}}), "常驻（异常退出时自动重启）")
        self.assertEqual(d({}), "只在手动触发时运行")

    def test_invalid_calendar_value_raises(self):
        for bad in ({"Weekday": "Mon"}, {"Hour": 24}, {"Minute": 60}, {"Hour": True}):
            with self.assertRaises(checkup.PlistValueError, msg=str(bad)):
                checkup.describe_schedule({"StartCalendarInterval": bad})

    def test_kind(self):
        self.assertEqual(checkup.schedule_kind({"KeepAlive": True, "StartInterval": 60}), "keepalive")
        self.assertEqual(checkup.schedule_kind({"StartInterval": 60}), "interval")
        self.assertEqual(checkup.schedule_kind({"StartCalendarInterval": {"Hour": 1}}), "calendar")
        self.assertEqual(checkup.schedule_kind({"RunAtLoad": True}), "runatload")
        self.assertTrue(checkup.has_timed_schedule({"KeepAlive": {"SuccessfulExit": False}, "StartInterval": 60}))

    def test_last_and_next_fire(self):
        daily = [{"Hour": 9, "Minute": 0}]
        self.assertEqual(checkup.last_calendar_fire(daily, NOW), dt.datetime(2026, 11, 5, 9, 0))
        self.assertEqual(checkup.last_calendar_fire(daily, NOW.replace(hour=8, minute=59)), dt.datetime(2026, 11, 4, 9, 0))
        self.assertEqual(checkup.next_calendar_fire(daily, NOW), dt.datetime(2026, 11, 6, 9, 0))
        monday = [{"Weekday": 1, "Hour": 9, "Minute": 0}]
        self.assertEqual(checkup.last_calendar_fire(monday, NOW), dt.datetime(2026, 11, 2, 9, 0))

    def test_sunday_is_0_and_7(self):
        for wd in (0, 7):
            self.assertEqual(checkup.last_calendar_fire([{"Weekday": wd, "Hour": 20, "Minute": 0}], NOW),
                             dt.datetime(2026, 11, 1, 20, 0))

    def test_count_missed(self):
        daily = [{"Hour": 9, "Minute": 0}]
        self.assertEqual(checkup.count_calendar_fires(daily, dt.datetime(2026, 11, 1, 9, 5), NOW), 4)
        self.assertEqual(checkup.count_calendar_fires(daily, dt.datetime(2026, 11, 5, 9, 0, 30), NOW), 0)
        self.assertEqual(checkup.count_calendar_fires([{"Minute": 0}], dt.datetime(2026, 11, 5, 7, 30), NOW), 3)

    def test_window_detection(self):
        retry = [{"Hour": 9, "Minute": m} for m in range(0, 60)]
        self.assertEqual(checkup.calendar_window_start(retry, NOW), 9 * 60)
        hourly = [{"Minute": 0}]
        self.assertIsNone(checkup.calendar_window_start(hourly, NOW))  # 铺满全天：逐次计数
        once = [{"Hour": 9, "Minute": 0}]
        self.assertIsNone(checkup.calendar_window_start(once, NOW))
        midnight = [{"Hour": 23, "Minute": 0}, {"Hour": 23, "Minute": 30}, {"Hour": 0, "Minute": 0},
                    {"Hour": 0, "Minute": 30}]
        self.assertEqual(checkup.calendar_window_start(midnight, NOW), 23 * 60)

    def test_cross_midnight_window_not_missed(self):
        midnight = [{"Hour": 23, "Minute": 0}, {"Hour": 23, "Minute": 30}, {"Hour": 0, "Minute": 0},
                    {"Hour": 0, "Minute": 30}]
        now = dt.datetime(2026, 11, 5, 18, 0)
        start = checkup.calendar_window_start(midnight, now)
        self.assertEqual(checkup.count_missed_windows(midnight, start, dt.datetime(2026, 11, 4, 23, 0, 5), now), 0)
        self.assertEqual(checkup.count_missed_windows(midnight, start, dt.datetime(2026, 11, 1, 23, 0, 5), now), 3)

    def test_window_still_open_is_not_counted(self):
        retry = [{"Hour": 9, "Minute": m} for m in range(0, 60, 5)]
        start = checkup.calendar_window_start(retry, NOW)
        # 今天 09:20，窗口还没结束：昨天做成了，今天还在补跑窗口里，不算漏
        self.assertEqual(checkup.count_missed_windows(retry, start, dt.datetime(2026, 11, 4, 9, 0, 3),
                                                      dt.datetime(2026, 11, 5, 9, 20)), 0)
        self.assertEqual(checkup.count_missed_windows(retry, start, dt.datetime(2026, 11, 4, 9, 0, 3),
                                                      dt.datetime(2026, 11, 5, 10, 15)), 1)


# ---------------------------------------------------------------------------
# 程序与路径
# ---------------------------------------------------------------------------

class ProgramCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "proj").mkdir()
        (self.home / "proj/run.sh").write_text("")
        (self.home / "proj/server.js").write_text("")
        (self.home / "my scripts").mkdir()
        (self.home / "my scripts/x.sh").write_text("")
        self.h = str(self.home)

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, args, **kw):
        return checkup.check_program({"ProgramArguments": args, **kw}, self.home)

    def test_script_through_interpreter(self):
        self.assertTrue(self.check(["/bin/bash", f"{self.h}/proj/run.sh"]).script_exists)
        pc = self.check(["/bin/bash", f"{self.h}/gone/run.sh"])
        self.assertEqual(pc.script, f"{self.h}/gone/run.sh")
        self.assertFalse(pc.script_exists)

    def test_bash_e_is_a_flag_not_inline(self):
        pc = self.check(["/bin/bash", "-e", f"{self.h}/gone/sync.sh"])
        self.assertIsNone(pc.inline)
        self.assertFalse(pc.script_exists)

    def test_relative_script_uses_working_directory(self):
        pc = self.check(["/usr/bin/python3", "-u", "run.sh"], WorkingDirectory=f"{self.h}/proj")
        self.assertTrue(pc.script_exists)
        self.assertTrue(pc.workdir_exists)

    def test_flag_values_packages_and_urls_are_not_scripts(self):
        self.assertTrue(self.check(["/usr/local/bin/node", "-r", "dotenv/config", "server.js"],
                                   WorkingDirectory=f"{self.h}/proj").script_exists)
        for args in (["/opt/homebrew/bin/npx", "-y", "@larksuite/openclaw-lark", "start"],
                     ["/opt/homebrew/bin/deno", "run", "-A", "https://example.com/x.ts"],
                     ["/usr/bin/python3", "-m", "http.server"],
                     ["/opt/homebrew/bin/uv", "run", "--with", "requests", "mytool"]):
            pc = self.check(args, WorkingDirectory=f"{self.h}/proj")
            self.assertIsNone(pc.script, args)
            self.assertFalse(pc.inline_missing, args)

    def test_env_and_uv_run(self):
        pc = self.check(["/usr/bin/env", "python3", f"{self.h}/proj/missing.py"])
        self.assertFalse(pc.script_exists)
        self.assertTrue(self.check(["/opt/homebrew/bin/uv", "run", f"{self.h}/proj/run.sh"]).script_exists)

    def test_tilde_is_not_expanded_by_launchd(self):
        pc = self.check(["/bin/bash", "~/proj/run.sh"])
        self.assertTrue(pc.tilde)
        self.assertIsNone(pc.script_exists)
        self.assertTrue(self.check(["/bin/bash", "~/proj/run.sh"], EnableGlobbing=True).script_exists)
        self.assertTrue(checkup.check_program({"Program": "~/bin/x"}, self.home).tilde)
        self.assertTrue(self.check(["/bin/bash", "x.sh"], WorkingDirectory="~/proj").tilde)

    def test_program_key_must_be_absolute(self):
        self.assertTrue(checkup.check_program({"Program": "node", "ProgramArguments": ["node", "x.js"]},
                                              self.home).program_relative_key)

    def test_relative_program_uses_only_launchd_std_path(self):
        pc = self.check(["sh", "-c", "true"], EnvironmentVariables={"PATH": "/nowhere"})
        self.assertTrue(pc.program_exists)  # /bin/sh 在标准 PATH 里
        pc = self.check(["definitely-not-a-real-cmd-xyz"], EnvironmentVariables={"PATH": f"{self.h}/proj"})
        self.assertFalse(pc.program_exists)

    def test_inline_command_checks_only_executed_paths(self):
        cmd = (f"mkdir -p {self.h}/out/new && cd {self.h}/proj && ./run.sh >> {self.h}/logs/new.log; "
               f"node --out {self.h}/reports/today.csv {self.h}/proj/server.js")
        pc = self.check(["/bin/zsh", "-lc", cmd])
        self.assertEqual(pc.inline, cmd)
        self.assertEqual(pc.inline_missing, [])
        pc = self.check(["/bin/zsh", "-lc", f"cd {self.h}/gone && ./run.sh"])
        self.assertEqual(pc.inline_missing, [f"{self.h}/gone"])
        pc = self.check(["/bin/bash", "-c", f'"{self.h}/my scripts/x.sh" && {self.h}/gone/tool --flag'])
        self.assertEqual(pc.inline_missing, [f"{self.h}/gone/tool"])

    def test_missing_program(self):
        self.assertFalse(checkup.check_program({"Program": f"{self.h}/bin/nope"}, self.home).program_exists)

    def test_bad_types_raise(self):
        with self.assertRaises(checkup.PlistValueError):
            checkup.check_program({"ProgramArguments": "/bin/bash x"}, self.home)
        with self.assertRaises(checkup.PlistValueError):
            checkup.check_program({"ProgramArguments": ["/bin/sh"], "WorkingDirectory": 3}, self.home)


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------

class RedactTests(unittest.TestCase):
    SECRETS = {
        "app_secret=Q3vXk9PzLm2Rt7Wq": "Q3vXk9PzLm2Rt7Wq",
        "{'app_id': 'cli_a1', 'app_secret': 'Q3vXk9PzLm2Rt7Wq'}": "Q3vXk9PzLm2Rt7Wq",
        "app_secret: 'Q3vXk9PzLm2Rt7Wq'": "Q3vXk9PzLm2Rt7Wq",
        "export LARK_APP_SECRET='Q3vXk9PzLm2Rt7Wq'": "Q3vXk9PzLm2Rt7Wq",
        "LARK_SECRET2=Q3vXk9PzLm2Rt7Wq": "Q3vXk9PzLm2Rt7Wq",
        "飞书 app_secret：Q3vXk9PzLm2Rt7Wq": "Q3vXk9PzLm2Rt7Wq",
        "密码：hunter2pass": "hunter2pass",
        "run --token Q3vXk9PzLm2Rt7Wq --password hunter2pass": "hunter2pass",
        "postgres://admin:S3cretPass@db.local/x": "S3cretPass",
        "https://open.feishu.cn/open-apis/bot/v2/hook/3f2b8c1e-9a7d-4c1e-8f2a-1b2c3d4e5f60":
            "3f2b8c1e-9a7d-4c1e-8f2a-1b2c3d4e5f60",
        "https://hooks.slack.com/services/T000/B000/XXXXXXXX": "B000/XXXXXXXX",
        "GET /x?key=AIzaSyA1234567890abcdefghijklmnopqrstu": "AIzaSyA1234567890",
        "Cookie: session=abc123def; csrftoken=zzz999": "abc123def",
        "Authorization: Basic dXNlcjpwYXNzd29yZA==": "dXNlcjpwYXNz",
        "Bearer abcdefghijklmnop": "abcdefghijklmnop",
        "令牌为sk-proj-AbCdEfGhIjKlMnOpQrSt": "sk-proj-AbCdEf",
        "key sk-ant-api03-AbCdEfGhIjKlMnOpQrSt": "sk-ant-api03",
        "github_pat_11ABCDEFG0123456789_abcdefghijklmnop": "github_pat_11ABCDEFG",
        "AKIAIOSFODNN7EXAMPLE": "AKIAIOSFODNN7EXAMPLE",
        "aws wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY": "wJalrXUtnFEMI/K7MDENG",
        "tenant_access_token t-g1044ab5cdEFGH6789ijklMNOPqrst": "t-g1044ab5cdEFGH",
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcDEF123": "eyJhbGciOiJIUzI1NiJ9",
        "发送给 13812345678": "13812345678",
        "mail zhang.san@lumiedu.cn": "zhang.san@",
    }
    KEPT = [
        "HEAD is now at 3f2b8c1e9a7d4c1e8f2a1b2c3d4e5f6071829304 fix",
        "sha256:" + "a" * 64,
        "/Users/nat/projects/lumiedu-campaign-daily-marketing-automation-v2/run.sh",
        "at _handle_websocket_reconnect_with_exponential_backoff (x.py:12)",
        "invalid token: signature mismatch",
        "refresh token: expired",
        "sent 120 messages to 3 groups",
        "id 3f2b8c1e-9a7d-4c1e-8f2a-1b2c3d4e5f60 done",
    ]

    def test_secrets_hidden(self):
        for line, secret in self.SECRETS.items():
            self.assertNotIn(secret, checkup.redact(line), line)

    def test_normal_text_kept(self):
        for line in self.KEPT:
            self.assertEqual(checkup.redact(line), line)

    def test_private_key_block_and_partial_first_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.log"
            p.write_text("ok\n-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmU=\n"
                         "-----END OPENSSH PRIVATE KEY-----\ndone\n")
            lines = checkup.read_tail(str(p), 10)
            self.assertNotIn("b3BlbnNzaC1rZXktdjEAAAAABG5vbmU=", "\n".join(lines))
            self.assertIn("[已隐藏的私钥]", lines)
            # 只读末尾时，第一行是从中间截断的，要丢掉
            p.write_text('{"app_secret":"Q3vXk9PzLm2Rt7Wq"}\n' + "x\n" * 10)
            lines = checkup.read_tail(str(p), 50, max_bytes=30)
            self.assertNotIn("Q3vXk9PzLm2Rt7Wq", "\n".join(lines))


class CauseTests(unittest.TestCase):
    def test_common_causes(self):
        cases = {
            "zsh:1: command not found: lark-cli": "lark-cli",
            "/bin/bash: lark-cli: command not found": "lark-cli",
            "Error: Cannot find module 'ws'": "缺少依赖 `ws`",
            "ModuleNotFoundError: No module named 'requests'": "requests",
            "bash: /Users/nat/Documents/x.sh: Operation not permitted": "隐私",
            "Error: listen EADDRINUSE: address already in use :::3000": "端口被占用",
            "401 Unauthorized": "凭据",
            "connect ECONNREFUSED 127.0.0.1:8080": "连不上",
        }
        for line, want in cases.items():
            c = checkup.find_cause(["started", line])
            self.assertIsNotNone(c, line)
            self.assertIn(want, c[1], line)
        self.assertIsNone(checkup.find_cause(["all good", "sent 3 messages"]))


# ---------------------------------------------------------------------------
# 只读保证
# ---------------------------------------------------------------------------

class ReadOnlyTests(unittest.TestCase):
    L, C = checkup.LAUNCHCTL, checkup.CRONTAB

    def test_allowed(self):
        for argv in ([self.L, "print", "gui/501/ai.hermes.gateway"], [self.L, "print-disabled", "gui/501"],
                     [self.C, "-l"]):
            checkup.assert_read_only(argv)

    def test_rejected(self):
        for argv in ([self.L, "bootout", "gui/501/x"], [self.L, "kickstart", "-k", "gui/501/x"],
                     [self.L, "unload", "x.plist"], [self.L, "load", "x.plist"], [self.L, "enable", "gui/501/x"],
                     [self.L, "print", "gui/501/x", "extra"], [self.L, "print-disabled", "system"],
                     [self.L, "print", "system/com.apple.x"], [self.L, "print", "gui/501/-x"],
                     ["launchctl", "print", "gui/501/x"], ["/tmp/evil/launchctl", "print", "gui/501/x"],
                     [self.C, "-r"], ["crontab", "-l"], ["hermes", "cron", "list"], ["kill", "-9", "1"], []):
            with self.assertRaises(checkup.ReadOnlyViolation, msg=str(argv)):
                checkup.assert_read_only(argv)

    def test_runner_enforces_guard_before_executing(self):
        executed = []

        class Spy(checkup.CommandRunner):
            def _execute(self, argv, timeout):
                executed.append(argv)
                return checkup.CmdResult(0, "", "")
        with self.assertRaises(checkup.ReadOnlyViolation):
            Spy().run([self.L, "bootout", "gui/501/x"])
        self.assertEqual(executed, [])

    def test_runner_caps_output(self):
        class Big(checkup.CommandRunner):
            def _execute(self, argv, timeout):
                return checkup.CmdResult(0, "x" * (checkup.MAX_OUTPUT + 100), "")
        self.assertEqual(len(Big().run([self.C, "-l"]).out), checkup.MAX_OUTPUT)

    def test_process_calls_only_inside_execute(self):
        """静态检查：subprocess / os 的进程类调用只出现在 CommandRunner._execute 里。"""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and (
                            sub.value.id == "subprocess" and sub.attr in ("run", "Popen", "call", "check_call",
                                                                           "check_output", "getoutput")
                            or sub.value.id == "os" and (sub.attr in ("system", "popen", "posix_spawn", "spawnv",
                                                                       "kill", "remove", "unlink", "rename",
                                                                       "replace", "rmdir", "removedirs", "truncate",
                                                                       "utime", "symlink", "link")
                                                         or sub.attr.startswith("exec"))
                            or sub.value.id == "shutil" and sub.attr in ("rmtree", "move", "copy", "copy2",
                                                                         "copyfile", "copytree")):
                        if not (node.name == "_execute" and sub.value.id == "subprocess"):
                            bad.append(f"{node.name}: {sub.value.id}.{sub.attr}")
        self.assertEqual(bad, [])

    def test_main_has_no_side_effects_besides_report(self):
        """运行时审计：在独立进程里跑一次完整体检，记录所有写文件、改文件、起进程的动作，
        只允许写报告的 .md / .json，以及建报告目录。"""
        with tempfile.TemporaryDirectory() as d:
            ctx_root = Path(d) / "s"
            ctx = scenario.build_scenario(ctx_root)
            out = Path(d) / "reports" / "自动化体检-20261105-1030.md"
            code = textwrap.dedent(f"""
                import sys, os, json
                sys.path.insert(0, {str(SCRIPT.parent)!r})
                events = []
                WRITE = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
                def hook(ev, args):
                    if ev == "open":
                        path, mode, flags = args
                        if isinstance(path, (str, bytes)) and ((isinstance(mode, str) and any(c in mode for c in "wax+"))
                                                              or (flags or 0) & WRITE):
                            events.append(["write", str(path)])
                    elif ev in ("os.remove", "os.rename", "os.replace", "os.rmdir", "os.truncate", "os.utime",
                                "os.symlink", "os.link", "os.chown", "shutil.rmtree", "shutil.move", "os.system",
                                "os.posix_spawn", "os.exec", "os.kill", "os.mkdir", "os.chmod"):
                        events.append([ev, str(args[0]) if args else ""])
                    elif ev == "subprocess.Popen":
                        events.append(["popen", str(args[1])])
                import checkup
                sys.addaudithook(hook)
                checkup.main(["--agents-dir", {str(ctx.agents_dir)!r}, "--out", {str(out)!r}])
                sys.stdout.write("\\nEVENTS=" + json.dumps(events))
            """)
            env = dict(os.environ, HOME=str(ctx.home))
            r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            events = json.loads(r.stdout.split("EVENTS=", 1)[1])
            allowed = {str(out), str(out.with_suffix(".json")), str(out.parent)}
            for ev, target in events:
                if ev == "popen":
                    self.assertIn(target.split("'")[1] if "'" in target else target,
                                  (checkup.LAUNCHCTL, checkup.CRONTAB), target)
                    continue
                if ev in ("os.mkdir", "write", "os.chmod"):
                    self.assertTrue(target in allowed or str(out.parent).startswith(target), (ev, target))
                    continue
                self.fail(f"出现了不该有的动作：{ev} {target}")
            self.assertTrue(any(ev == "write" and t == str(out) for ev, t in events))


# ---------------------------------------------------------------------------
# 合成场景：每项分到哪一档
# ---------------------------------------------------------------------------

class ScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ctx = scenario.build_scenario(Path(cls.tmp.name))
        cls.report = checkup.run_checkup(cls.ctx)
        cls.md = checkup.render_markdown(cls.report)
        cls.by_key = {it.key: it for it in cls.report.items}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def job(self, label):
        return self.by_key[f"job:{label}"]

    def problems(self, key):
        return " ".join(f.problem for f in self.by_key[key].findings)

    def test_tiers(self):
        expected = {
            "job:ai.lark-channel-bridge.server": ACT,   # 常驻服务挂了、等待重启
            "job:com.lumiedu.weekly-report": ACT,       # 上次退出码 127
            "job:cn.digital-twin.healthcheck": ACT,     # 每 30 分钟，日志停了 3 天
            "job:cn.digital-twin.report": ACT,          # 脚本路径写了 ~
            "job:cn.github-center.pull": ACT,           # 文件在但没加载
            "job:local.digitalworld.sync": ACT,         # 脚本不在了 + 两个同名配置文件
            "job:ai.ops.codex": ACT,                    # 日志目录不存在
            "file:broken.plist": ACT,                   # plist 坏了
            "file:cn.lumiedu.moved.plist": ACT,         # 链接断了
            "hermes:默认": ACT,                          # 失败、过点没跑、暂停
            "crontab": ACT,                             # 有一条指向的脚本不在了
            "job:ai.hermes.gateway": WARN,              # 在跑，但重启 7 次、上次退出码 75
            "job:cn.niuma-home.worker": WARN,           # 每小时，漏了 1 次
            "job:cn.personal-ai-workbench.server": WARN,  # 已停用
            "job:local.digitalworld.old": WARN,         # 已停用，脚本也不在了：只算注意
            "residue": WARN,
            "job:cn.niuma-home.web": OK,
            "job:cn.lumiedu.campaign-daily": OK,
            "job:cn.lumiedu.campaign-retry": OK,        # 当天补跑窗口：今天做成了，后面的点不写日志
            "job:cn.lumiedu.openclaw": OK,              # npx 包名不是脚本路径
            "job:com.openai.codex-quota-guard": OK,     # 没配日志：正常但列入盲区
            "hermes:work": OK,
        }
        self.assertEqual({k: self.by_key[k].tier for k in expected}, expected)
        self.assertEqual(set(self.by_key), set(expected))

    def test_third_party_excluded_and_listed(self):
        self.assertIn("com.google.keystone.agent.plist", self.report.excluded)
        self.assertIn("com.google.keystone.agent.plist", self.md)

    def test_duplicate_label_is_one_item_using_loaded_file(self):
        it = self.job("local.digitalworld.sync")
        self.assertEqual(it.files, ["local.digitalworld.sync.plist", "local.digitalworld.sync.backup.plist"])
        dup = next(f for f in it.findings if f.code == "dup_label")
        self.assertIn("系统正在用的是 `local.digitalworld.sync.plist`", dup.problem)
        codes = [f.code for f in it.findings]
        self.assertIn("zombie", codes)
        self.assertNotIn("run_failed", codes)  # 退出码 127 只是症状，不单列

    def test_disabled_zombie_reported_once_as_warning(self):
        it = self.job("local.digitalworld.old")
        self.assertEqual([f.code for f in it.findings], ["zombie"])
        self.assertIn("已停用", it.findings[0].problem)

    def test_hermes_gateway_restart(self):
        p = self.problems("job:ai.hermes.gateway")
        self.assertIn("启动了 7 次", p)
        self.assertIn("网络", p)

    def test_missed_runs_text(self):
        self.assertIn("应该运行 143 次", self.problems("job:cn.digital-twin.healthcheck"))
        self.assertIn("应该运行 1 次", self.problems("job:cn.niuma-home.worker"))
        self.assertIn("合盖", self.problems("job:cn.niuma-home.worker"))

    def test_tilde_explained(self):
        p = self.problems("job:cn.digital-twin.report")
        self.assertIn("~", p)
        self.assertIn("不会把 `~` 换成", p)

    def test_causes_extracted(self):
        self.assertIn("ws", self.job("ai.lark-channel-bridge.server").cause[1])
        self.assertIn("lark-cli", self.job("com.lumiedu.weekly-report").cause[1])

    def test_registered_purpose_shown(self):
        self.assertIn("**做什么**：每周一把上周数据汇总发到飞书群", self.md)
        self.assertIn("**坏了影响**：周一早会没有周报", self.md)
        self.assertIn("下次按计划运行：11 月 9 日 09:00", self.md)

    def test_residue_listed(self):
        res = self.by_key["residue"]
        text = json.dumps(res.facts, ensure_ascii=False)
        self.assertIn("是在用任务 `ai.hermes.gateway` 的旧版本或备份", text)
        self.assertIn("cn.old-thing.plist.disabled", text)
        self.assertNotIn(".DS_Store", text)

    def test_hermes_jobs(self):
        h = self.by_key["hermes:默认"]
        codes = {f.code: f for f in h.findings}
        self.assertEqual(codes["hermes_failed:c03"].severity, ACT)
        self.assertIn("连续失败 3 次", codes["hermes_failed:c03"].problem)
        self.assertEqual(codes["hermes_paused:c02"].severity, WARN)
        self.assertEqual(codes["hermes_overdue:c04"].severity, ACT)
        self.assertNotIn("hermes_failed:c01", codes)
        names = [k for k, _ in h.facts]
        self.assertNotIn("一次性提醒", names)  # 已完成的不列
        self.assertNotIn("abcd1234efgh5678ijkl", self.md)

    def test_crontab_only_real_problems(self):
        c = self.by_key["crontab"]
        self.assertEqual(len(c.findings), 1)
        self.assertIn("gone.sh", c.findings[0].problem)

    def test_exact_commands_run(self):
        L = checkup.LAUNCHCTL
        prints = [c for c in self.report.commands_run if c[:2] == [L, "print"]]
        labels = {c[2].split("/", 2)[2] for c in prints}
        self.assertEqual(len(prints), len(labels))  # 同一个 Label 只查一次
        self.assertEqual(labels, {it.label for it in self.report.items if it.kind == "job"})
        self.assertEqual([c for c in self.report.commands_run if c[1:2] == ["print-disabled"]],
                         [[L, "print-disabled", f"gui/{self.ctx.uid}"]])
        self.assertEqual([c for c in self.report.commands_run if c[0] == checkup.CRONTAB], [[checkup.CRONTAB, "-l"]])
        self.assertEqual(len(self.report.commands_run), len(prints) + 2)

    def test_markdown_layout(self):
        md = self.md
        self.assertLess(md.index("## 需要处理（"), md.index("## 注意（"))
        self.assertLess(md.index("## 注意（"), md.index("## 正常（"))
        self.assertIn("**结论：需要处理 11 项，注意 5 项，其余 6 项正常。**", md)
        self.assertIn("没有启动、停止、重启或修改任何任务", md)
        first = re.search(r"^### 1\. (.+)$", md, re.M).group(1)
        self.assertIn("ai.lark-channel-bridge.server", first)
        self.assertIn("停了，在反复重启", first)
        self.assertIn("app_secret=[已隐藏]", md)
        self.assertNotIn("s3cr3tvalue123", md)
        self.assertNotIn(str(self.ctx.home), md)  # 家目录一律写成 ~
        self.assertIn("## 附录：日志摘录", md)
        self.assertNotIn("worker done", md)  # 没有报错的日志不摘
        for block in re.findall(r"^### \d+\..*?(?=^### |^## )", md, re.M | re.S):
            self.assertEqual(block.count("- **问题**"), block.count("- **怎么办**"), block[:80])

    def test_json_roundtrip(self):
        data = json.loads(checkup.report_to_json(self.report))
        tiers = {i["key"]: i["tier"] for i in data["items"]}
        self.assertEqual(tiers["job:cn.niuma-home.web"], OK)


# ---------------------------------------------------------------------------
# 单个任务的边界
# ---------------------------------------------------------------------------

class AssessEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.prog = self.home / "run.sh"
        self.prog.write_text("")

    def tearDown(self):
        self.tmp.cleanup()

    def assess(self, plist: dict, state: checkup.LaunchdState | None, disabled=False) -> checkup.Item:
        plist = {"Label": "x.test", "ProgramArguments": ["/bin/sh", str(self.prog)], **plist}
        ctx = checkup.Context(agents_dir=self.home, home=self.home, uid=os.getuid(), now=NOW,
                              runner=checkup.CommandRunner(), cfg=checkup.load_config())
        p = self.home / "x.test.plist"
        with open(p, "wb") as f:
            plistlib.dump(plist, f)
        p.chmod(0o644)
        job = checkup.build_job(p, plist, ctx)
        job.launchd = state
        job.disabled_effective = disabled
        item = checkup.Item(key="job:x.test", name="x.test", kind="job", label="x.test")
        checkup.assess_job(job, ctx, item)
        return item

    def log(self, name: str, hours_ago: float, text: str = "line\n") -> str:
        p = self.home / name
        p.write_text(text)
        ts = (NOW - dt.timedelta(hours=hours_ago)).timestamp()
        os.utime(p, (ts, ts))
        return str(p)

    def S(self, **kw):
        return checkup.LaunchdState(loaded=True, **kw)

    def codes(self, it):
        return [f.code for f in it.findings]

    def test_keepalive_down_without_exit_record(self):
        it = self.assess({"KeepAlive": True}, self.S(state="not running"))
        self.assertEqual(it.tier, ACT)
        self.assertIn("没有退出记录", it.findings[0].problem)

    def test_keepalive_conditions_idle_is_fine(self):
        for ka in ({"NetworkState": True}, {"SuccessfulExit": False}):
            self.assertEqual(self.assess({"KeepAlive": ka}, self.S(state="not running", last_exit=0)).tier, OK)
        self.assertEqual(self.assess({"KeepAlive": {"SuccessfulExit": False}},
                                     self.S(state="not running", last_exit=1)).tier, ACT)

    def test_keepalive_restart_variants(self):
        self.assertEqual(self.assess({"KeepAlive": True}, self.S(state="running", runs=25, last_exit=1)).tier, ACT)
        it = self.assess({"KeepAlive": True}, self.S(state="running", runs=25, last_exit=None,
                                                    last_signal="Terminated: 15"))
        self.assertEqual((it.tier, self.codes(it)), (WARN, ["service_sigterm"]))
        it = self.assess({"KeepAlive": True}, self.S(state="running", runs=12, last_exit=0))
        self.assertEqual((it.tier, self.codes(it)), (WARN, ["service_restarted"]))
        it = self.assess({"KeepAlive": True}, self.S(state="running", runs=2, last_exit=1))
        self.assertEqual(it.tier, WARN)
        it = self.assess({"KeepAlive": True}, self.S(state="spawn scheduled", runs=2, last_exit=0))
        self.assertEqual((it.tier, self.codes(it)), (WARN, ["service_gap"]))

    def test_keepalive_on_failure_with_schedule_still_checks_missed_runs(self):
        it = self.assess({"KeepAlive": {"SuccessfulExit": False}, "StartCalendarInterval": {"Hour": 9, "Minute": 0},
                          "StandardOutPath": self.log("out.log", 120)}, self.S(state="not running", last_exit=0))
        self.assertIn("missed", self.codes(it))
        self.assertEqual(it.tier, ACT)

    def test_stale_error_log_alone_is_not_missed_run(self):
        it = self.assess({"StartInterval": 600, "StandardErrorPath": self.log("err.log", 72)},
                         self.S(state="not running", last_exit=0))
        self.assertEqual(it.tier, OK)
        self.assertTrue(it.blind)

    def test_devnull_stdout_is_blind(self):
        it = self.assess({"StartInterval": 600, "StandardOutPath": "/dev/null"}, self.S(state="not running", last_exit=0))
        self.assertEqual(it.tier, OK)
        self.assertTrue(it.blind)

    def test_stale_output_log_is_missed_run(self):
        it = self.assess({"StartInterval": 600, "StandardOutPath": self.log("out.log", 72),
                          "StandardErrorPath": self.log("err.log", 0.1)}, self.S(state="not running", last_exit=0))
        self.assertEqual(it.tier, ACT)
        self.assertEqual(it.findings[0].code, "missed")

    def test_missed_but_recent_is_only_warning(self):
        it = self.assess({"StartInterval": 600, "StandardOutPath": self.log("out.log", 3)},
                         self.S(state="not running", last_exit=0))
        self.assertEqual(it.tier, WARN)

    def test_sigterm_is_only_warning(self):
        self.assertEqual(self.assess({"StartInterval": 600}, self.S(state="not running", last_exit=143)).tier, WARN)

    def test_unknown_launchd_state_is_not_not_loaded(self):
        it = self.assess({"KeepAlive": True}, checkup.LaunchdState(loaded=None, error="Domain does not support"))
        self.assertEqual(it.tier, OK)

    def test_file_problems(self):
        os.chmod(self.prog, 0o644)
        it = self.assess({"Program": str(self.prog), "ProgramArguments": [str(self.prog)], "StartInterval": 60},
                         self.S(state="not running", last_exit=78))
        self.assertEqual(self.codes(it)[0], "no_exec")
        it = self.assess({"StartInterval": 60, "WorkingDirectory": str(self.home / "gone")},
                         self.S(state="not running"))
        self.assertIn("workdir_missing", self.codes(it))
        it = self.assess({"StartInterval": 60, "StandardOutPath": "~/x.log"}, self.S(state="not running"))
        self.assertEqual(self.codes(it), ["tilde"])

    def test_disabled_file_problems_are_warnings(self):
        it = self.assess({"StartInterval": 60, "WorkingDirectory": str(self.home / "gone")},
                         checkup.LaunchdState(loaded=False), disabled=True)
        self.assertEqual(it.tier, WARN)

    def test_recent_error_lines_and_big_log(self):
        it = self.assess({"StartInterval": 600, "StandardOutPath": self.log("out.log", 0.05, "ERROR boom\n")},
                         self.S(state="not running", last_exit=0))
        self.assertEqual(self.codes(it), ["log_errors"])
        big = self.home / "big.log"
        with open(big, "wb") as f:
            f.truncate(201 * 1024 * 1024)
        it = self.assess({"KeepAlive": True, "StandardOutPath": str(big)}, self.S(state="running", runs=1))
        self.assertEqual(self.codes(it), ["log_big"])

    def test_unreadable_log_is_not_an_error_line(self):
        p = self.log("locked.log", 0.1, "fine\n")
        os.chmod(p, 0)
        try:
            if os.access(p, os.R_OK):
                self.skipTest("以 root 运行时无法制造读不了的文件")
            it = self.assess({"KeepAlive": True, "StandardOutPath": p}, self.S(state="running", runs=1))
            self.assertEqual(self.codes(it), ["log_unreadable"])
        finally:
            os.chmod(p, 0o644)

    def test_protected_folder_hint_when_failing(self):
        docs = self.home / "Documents"
        docs.mkdir()
        (docs / "job.sh").write_text("")
        it = checkup.Item(key="k", name="k", kind="job")
        plist = {"Label": "x.test", "ProgramArguments": ["/bin/sh", str(docs / "job.sh")], "StartInterval": 60}
        ctx = checkup.Context(agents_dir=self.home, home=self.home, uid=os.getuid(), now=NOW,
                              runner=checkup.CommandRunner(), cfg=checkup.load_config())
        p = self.home / "x.test.plist"
        p.write_bytes(plistlib.dumps(plist))
        job = checkup.build_job(p, plist, ctx)
        job.launchd = self.S(state="not running", last_exit=126)
        checkup.assess_job(job, ctx, it)
        self.assertIn("隐私", it.cause[1])

    def test_naming_boundaries(self):
        for name, label, flagged in (("cn.lumiedu.official-account.sync", "cn.lumiedu.official-account.sync", False),
                                     ("cn.lumiedu.copywriting.daily", "cn.lumiedu.copywriting.daily", False),
                                     ("x.job.bak", "x.job", True), ("x.job-copy", "x.job", True)):
            job = checkup.Job(path=Path(f"/x/{name}.plist"), label=label, plist={})
            it = checkup.Item(key="k", name="k", kind="job")
            checkup.assess_naming(job, it)
            self.assertEqual(any(f.code == "naming_backup" for f in it.findings), flagged, name)


# ---------------------------------------------------------------------------
# 环境、整体流程
# ---------------------------------------------------------------------------

class FlowTests(unittest.TestCase):
    def test_without_launchctl_and_crontab(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d), tools=set())
            rep = checkup.run_checkup(ctx)
            md = checkup.render_markdown(rep)
        self.assertEqual(rep.commands_run, [])
        self.assertIn("没有 launchctl", md)
        keys = {it.key: it for it in rep.items}
        self.assertEqual(keys["job:local.digitalworld.sync"].tier, ACT)  # 文件层面的问题照样查得出
        self.assertEqual(keys["file:broken.plist"].tier, ACT)
        self.assertEqual(keys["job:cn.github-center.pull"].tier, OK)  # 没有状态时不判「没加载」

    def test_launchctl_unreadable_does_not_mark_everything_not_loaded(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))

            def denied(argv, timeout):
                if argv[1] == "print":
                    return checkup.CmdResult(125, "", "Domain does not support specified action\n")
                return checkup.CmdResult(0, "", "")
            ctx.runner._execute = denied
            rep = checkup.run_checkup(ctx)
        self.assertFalse(any(f.code == "not_loaded" for it in rep.items for f in it.findings))
        self.assertTrue(any("没读到 launchd 状态" in n for n in rep.notes))

    def test_enabled_override_beats_plist_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            pl = ctx.agents_dir / "com.openai.codex-quota-guard.plist"
            data = plistlib.loads(pl.read_bytes())
            data["Disabled"] = True
            pl.write_bytes(plistlib.dumps(data))
            rep = checkup.run_checkup(ctx)
        it = next(i for i in rep.items if i.key == "job:com.openai.codex-quota-guard")
        self.assertNotIn("disabled", [f.code for f in it.findings])

    def test_bad_value_does_not_crash_report(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            pl = ctx.agents_dir / "cn.lumiedu.badvalue.plist"
            pl.write_bytes(plistlib.dumps({"Label": "cn.lumiedu.badvalue", "Program": "/bin/sh",
                                           "StartCalendarInterval": {"Weekday": "Mon", "Hour": 9}}))
            rep = checkup.run_checkup(ctx)
            md = checkup.render_markdown(rep)
        it = next(i for i in rep.items if i.key == "file:cn.lumiedu.badvalue.plist")
        self.assertEqual(it.findings[0].code, "plist_bad_value")
        self.assertIn("Weekday", it.findings[0].problem)
        self.assertIn("# 自动化体检报告", md)

    def test_fifo_in_launchagents_does_not_hang(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("没有 mkfifo")
        code = textwrap.dedent(f"""
            import sys, os, tempfile
            from pathlib import Path
            sys.path.insert(0, {str(HERE)!r}); sys.path.insert(0, {str(SCRIPT.parent)!r})
            import scenario, checkup
            d = tempfile.mkdtemp()
            ctx = scenario.build_scenario(Path(d))
            os.mkfifo(ctx.agents_dir / "y.hang.plist")
            os.mkfifo(ctx.agents_dir / "y.hang.plist.bak")
            rep = checkup.run_checkup(ctx)
            print([i.key for i in rep.items if i.key == "file:y.hang.plist"])
        """)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("file:y.hang.plist", r.stdout)

    def test_plist_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            os.chmod(ctx.agents_dir / "cn.github-center.pull.plist", 0o664)
            os.chmod(ctx.agents_dir / "cn.niuma-home.web.plist", 0o666)
            rep = checkup.run_checkup(ctx)
        keys = {it.key: it for it in rep.items}
        nl = next(f for f in keys["job:cn.github-center.pull"].findings if f.code == "not_loaded")
        self.assertIn("权限", nl.problem)  # 没加载的原因指向权限
        self.assertEqual([f.code for f in keys["job:cn.niuma-home.web"].findings], ["plist_perm"])

    def test_log_fence_injection_stays_in_code_block(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            log = ctx.home / "logs/lark-bridge.err.log"
            log.write_text("Error: boom\n```\n## 伪造标题\n<img src=https://evil.example/x.png>\n```python\nError: x\n")
            md = checkup.render_markdown(checkup.run_checkup(ctx))
        appendix = md.split("## 附录：日志摘录", 1)[1]
        fence = re.search(r"^(`{4,})text$", appendix, re.M).group(1)
        self.assertGreater(len(fence), 3)
        body = appendix.split(fence + "text", 1)[1].split("\n" + fence + "\n", 1)[0]
        self.assertIn("## 伪造标题", body)
        self.assertEqual(md.count("\n## 伪造标题"), 1)

    def test_grouping_same_kind(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            for i in range(3):
                (ctx.agents_dir / f"cn.lumiedu.extra{i}.plist").write_bytes(plistlib.dumps(
                    {"Label": f"cn.lumiedu.extra{i}", "ProgramArguments": ["/bin/sh", "-c", "true"],
                     "StartInterval": 900}))
            md = checkup.render_markdown(checkup.run_checkup(ctx))
        self.assertIn("4 个任务没加载，不会运行", md)
        self.assertEqual(md.count("—— 没加载，不会运行"), 0)

    def test_history_diff_and_private_files(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d) / "s")
            out_dir = Path(d) / "reports"
            first = out_dir / "自动化体检-20261104-1030.md"
            second = out_dir / "自动化体检-20261105-1030.md"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                checkup.main(["--agents-dir", str(ctx.agents_dir), "--out", str(first), "--no-crontab"])
                (ctx.agents_dir / "broken.plist").unlink()  # 修好一项
                (ctx.agents_dir / "cn.lumiedu.new.plist").write_bytes(plistlib.dumps(
                    {"Label": "cn.lumiedu.new", "Program": "/nonexistent/x", "StartInterval": 60}))
                checkup.main(["--agents-dir", str(ctx.agents_dir), "--out", str(second), "--no-crontab"])
            md = second.read_text(encoding="utf-8")
            self.assertIn("比上次体检", md)
            self.assertIn("已恢复 1 个", md)
            self.assertIn("配置文件坏了", md.split("已恢复", 1)[1].split("\n")[0])
            self.assertIn("〔新〕", md)
            for p in (first, second, second.with_suffix(".json")):
                self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
            self.assertIn("需要处理", buf.getvalue())

    def test_stdout_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = checkup.main(["--agents-dir", str(Path(d) / "none"), "--stdout", "--no-hermes", "--no-crontab"])
            self.assertEqual(rc, 0)
            self.assertIn("# 自动化体检报告", buf.getvalue())
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_quiet_label_skips_timing(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = scenario.build_scenario(Path(d))
            ctx.cfg["quiet_labels"] = ["cn.niuma-home.worker"]
            rep = checkup.run_checkup(ctx)
        self.assertEqual(next(i for i in rep.items if i.key == "job:cn.niuma-home.worker").tier, OK)

    def test_config_layering(self):
        with tempfile.TemporaryDirectory() as d:
            extra = Path(d) / "c.json"
            extra.write_text(json.dumps({"missed_runs_act": 9, "_说明": "x"}), encoding="utf-8")
            cfg = checkup.load_config(extra)
        self.assertEqual(cfg["missed_runs_act"], 9)
        self.assertNotIn("_说明", cfg)
        self.assertIn("com.google.*", cfg["exclude_patterns"])  # skill 目录里的 config.json 也生效了


if __name__ == "__main__":
    unittest.main()
