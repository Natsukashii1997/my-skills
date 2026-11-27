#!/usr/bin/env python3
"""session-retro 测试：只用 tests/fixtures 里合成的会话样例，不碰任何真实会话。

运行：python3 -m unittest discover -s skills/session-retro/tests -v
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(HERE.parent / "scripts"))

import session_retro as sr  # noqa: E402

# 假密钥在运行时拼出来，仓库里不出现像真密钥的字符串
FAKE = {
    "{{OPENAI_KEY}}": "sk-" + "proj-" + "Ab3Cd4" * 6,
    "{{GH_TOKEN}}": "gh" + "p_" + "a1B2c3D4" * 5,
}
WINDOW = ["--start", "2026-10-30", "--end", "2026-11-01", "--timezone", "Asia/Shanghai"]


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sr.main(argv)
    return code, out.getvalue(), err.getvalue()


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="session-retro-test-"))
        cls.data = cls.tmp / "data"
        shutil.copytree(str(FIXTURES), str(cls.data))
        for path in cls.data.rglob("*.jsonl"):
            text = path.read_text(encoding="utf-8")
            for key, value in FAKE.items():
                text = text.replace(key, value)
            path.write_text(text, encoding="utf-8")
        old = next(cls.data.glob("codex/sessions/2026/09/01/*.jsonl"))
        stamp = 1756684800  # 2025-09-01，早于窗口
        os.utime(str(old), (stamp, stamp))
        cls.claude_root = str(cls.data / "claude" / "projects")
        cls.codex_root = str(cls.data / "codex" / "sessions")
        cls.rules = str(cls.data / "rules")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def scan(self, *extra, name="out"):
        out = self.tmp / name
        argv = ["scan"] + WINDOW + ["--claude-root", self.claude_root, "--codex-root", self.codex_root,
                                    "--no-default-rules", "--rules", self.rules, "--out", str(out)] + list(extra)
        code, stdout, stderr = run_cli(argv)
        result = json.loads((out / "signals.json").read_text(encoding="utf-8"))
        markdown = (out / "signals.md").read_text(encoding="utf-8")
        return code, result, markdown

    def user_texts(self, result):
        return [item["text"] for item in result["signals"]["user_messages"]]


class ParseTests(FixtureCase):
    def test_claude_parsing_keeps_only_real_human_messages(self):
        path = next(Path(self.claude_root).glob("-Users-demo-proj-alpha/*0001.jsonl"))
        session = sr.parse_claude(path, sr.Counter())
        self.assertEqual(session["session_id"], "11111111-aaaa-4aaa-8aaa-000000000001")
        self.assertEqual(session["cwd"], "/Users/demo/proj-alpha")
        users = [e.text for e in session["events"] if e.kind == "user"]
        self.assertIn("帮我把报表脚本改成按周汇总", users)
        joined = "\n".join(users)
        self.assertNotIn("<command-name>", joined)          # 斜杠命令/isMeta
        self.assertNotIn("换一种搜法", joined)              # isSidechain 子代理
        self.assertNotIn("task-notification", joined)      # 非人类来源
        kinds = [e.kind for e in session["events"]]
        self.assertEqual(kinds.count("rejection"), 1)
        self.assertEqual(kinds.count("interrupt"), 1)
        rejection = next(e for e in session["events"] if e.kind == "rejection")
        self.assertEqual(rejection.reason, "别直接推 main，先开分支再提 PR")
        self.assertEqual(rejection.key, "Bash: git push origin")

    def test_codex_parsing_prefers_event_messages_and_reads_exit_codes(self):
        path = next(Path(self.codex_root).glob("2026/10/30/*c0de.jsonl"))
        coverage = sr.Counter()
        session = sr.parse_codex(path, coverage)
        self.assertEqual(session["session_id"], "019a0000-0000-7000-8000-00000000c0de")
        self.assertEqual(session["cwd"], "/Users/demo/proj-alpha")
        users = [e.text for e in session["events"] if e.kind == "user"]
        # response_item 与 event_msg 里同一句话只留一份；环境注入不算用户发言
        self.assertEqual(users.count("这次改动先别合并，定了：所有 PR 都由我来审"), 1)
        self.assertFalse(any("environment_context" in u for u in users))
        results = [e for e in session["events"] if e.kind == "tool_result"]
        self.assertEqual([e.ok for e in results], [False, False, False, False])  # JSON 包装 / Exit code / Process exited / apply_patch 失败
        self.assertEqual(results[0].key, "shell: pytest")
        self.assertEqual(results[2].key, "shell: pytest")                       # 去掉了 cd ... &&
        self.assertEqual(results[3].key, "apply_patch: report.py")
        self.assertEqual([e.kind for e in session["events"]].count("rejection"), 1)
        self.assertEqual(coverage["malformed_lines"], 1)

    def test_codex_new_format_filters_injections_and_reads_script_status(self):
        # 2026-11 本机实测的新版 Codex：没有 event_msg/user_message，用户的话混在大量注入里；
        # exec 工具输出首行是 Script completed / Script failed，没有退出码
        path = next((self.data / "codex_new").glob("*.jsonl"))
        session = sr.parse_codex(path, sr.Counter())
        users = [e.text for e in session["events"] if e.kind == "user"]
        self.assertEqual(users, ["不对，重来。以后都先给计划再动手", "定了，就按方案 B", "别动线上数据，先在副本上试"])
        results = [e.ok for e in session["events"] if e.kind == "tool_result"]
        self.assertEqual(results, [False, False, False, True, None])

    def test_codex_user_text_unit(self):
        self.assertEqual(sr.codex_user_text("<codex_delegation>\n  <source>x</source>\n不对</codex_delegation>"), "")
        self.assertEqual(sr.codex_user_text("<skill>\n以后都这样</skill>"), "")
        self.assertEqual(sr.codex_user_text("You are working inside Orca, a multi-agent IDE"), "")
        self.assertEqual(sr.codex_user_text("# Context from my IDE setup:\n\n## Open tabs:\n- a.py\n\n## My request for Codex:\n重来"), "重来")
        self.assertEqual(sr.codex_user_text("  不是这个意思，按表格来  "), "不是这个意思，按表格来")

    def test_codex_subagent_and_legacy_files(self):
        sub = next(Path(self.codex_root).glob("2026/10/30/*beef.jsonl"))
        self.assertTrue(sr.parse_codex(sub, sr.Counter())["subagent"])
        legacy = next(Path(self.codex_root).glob("2026/10/30/*legacy.jsonl"))
        session = sr.parse_codex(legacy, sr.Counter())
        self.assertEqual([e.text for e in session["events"] if e.kind == "user"], ["重来，按我给的表格格式输出"])

    def test_timestamps(self):
        self.assertEqual(sr.parse_ts("2026-10-30T02:00:05.120Z").microsecond, 120000)
        self.assertIsNotNone(sr.parse_ts("2026-10-30T02:00:05.123456789Z"))
        self.assertIsNone(sr.parse_ts("昨天"))


class SignalTests(unittest.TestCase):
    def check(self, text, tags, strength=None):
        got_tags, got_strength, _ = sr.classify_user_text(text)
        self.assertEqual(got_tags, tags, text)
        if strength:
            self.assertEqual(got_strength, strength, text)

    def test_corrections(self):
        self.check("不对，我说的是按周汇总", ["纠正"], "强")
        self.check("重来", ["纠正"], "强")
        self.check("你又忘了跑测试", ["纠正"], "强")
        self.check("That's not what I asked for", ["纠正"], "强")
        self.check("别动 config 文件", ["纠正"], "弱")
        self.check("不是这个文件", ["纠正"], "弱")

    def test_decisions(self):
        self.check("定了，就用方案二", ["决定"], "强")
        self.check("以后都先出提案再改", ["决定"], "强")
        self.check("From now on, always ask first", ["决定"], "强")
        self.check("选 B", ["决定"], "弱")

    def test_false_positive_guards(self):
        self.check("特别好，就这样", [])
        self.check("不错", [])
        self.check("这里的「不对」两个字只是在引用原文", [])
        self.check("帮我查一下 ```git revert``` 怎么用", [])
        self.check("帮我写一份周报，重点讲本周进展和下周计划，篇幅控制在一页以内，别太长", [])

    def test_both_tags(self):
        tags, strength, keywords = sr.classify_user_text("不对。以后不要直接推 main")
        self.assertEqual(tags, ["纠正", "决定"])
        self.assertIn("以后不要", keywords)


class ScanTests(FixtureCase):
    def test_end_to_end_signals(self):
        code, result, markdown = self.scan()
        self.assertEqual(code, 3)  # 样例里故意放了一行坏 JSON，覆盖状态应如实标为 partial
        self.assertEqual(result["coverage_status"], "partial")
        texts = self.user_texts(result)
        self.assertEqual(len(texts), 7, texts)
        joined = "\n".join(texts)
        for unwanted in ("窗口之前的旧消息", "九月的旧会话", "子代理里的话", "换一种搜法", "特别好", "不错", "引用文档原文"):
            self.assertNotIn(unwanted, joined)
        cov = result["coverage"]
        self.assertEqual(cov["files_skipped_older_than_window"], 1)
        self.assertEqual(cov["subagent_sessions_skipped"], 1)
        rejections = result["signals"]["rejections"]
        self.assertEqual(sorted(r["kind"] for r in rejections), ["中断", "中断", "拒绝", "拒绝"])
        failures = {f["key"]: f for f in result["signals"]["repeated_failures"]}
        self.assertEqual(set(failures), {"Bash: npm test", "shell: pytest"})
        self.assertTrue(failures["Bash: npm test"]["resolved"])
        self.assertFalse(failures["shell: pytest"]["resolved"])
        self.assertEqual(failures["shell: pytest"]["count"], 3)
        self.assertIn("## 三、同一操作连续失败（2 组）", markdown)

    def test_citations_have_file_line_and_local_time(self):
        _, result, _ = self.scan()
        first = next(s for s in result["signals"]["user_messages"] if s["text"].startswith("不对，我说的是"))
        cite = first["citation"]
        self.assertTrue(cite["file"].endswith("11111111-aaaa-4aaa-8aaa-000000000001.jsonl"))
        self.assertEqual(cite["line"], 11)
        self.assertEqual(cite["time"], "2026-10-30 10:02")  # UTC 02:02 → 北京时间 10:02
        self.assertEqual(first["prev_assistant"], "好的，我把它改成按月汇总，然后直接推送到 main。")
        codex = next(s for s in result["signals"]["user_messages"] if s["source"] == "codex" and "PR" in s["text"])
        self.assertIn("rollout-2026-10-30T14-00-00-019a0000-0000-7000-8000-00000000c0de.jsonl", codex["citation"]["file"])

    def test_dedup_resumed_session_and_repeated_complaint(self):
        _, result, markdown = self.scan()
        same = [s for s in result["signals"]["user_messages"] if s["text"].startswith("不对，我说的是按周汇总")]
        self.assertEqual(len(same), 1)                        # 续接会话复制的同 uuid 消息被去掉
        self.assertEqual(len(same[0]["repeats"]), 1)          # 第二天又说一遍，合并成「重复 1 次」
        self.assertEqual(same[0]["repeats"][0]["time"], "2026-10-31 11:00")
        self.assertEqual(result["coverage"]["duplicate_messages_removed"], 1)
        self.assertEqual(result["coverage"]["repeated_messages_merged"], 1)
        self.assertIn("同样的话又说了 1 次", markdown)

    def test_project_filter_and_exclude(self):
        _, result, _ = self.scan("--project", "proj-beta", name="beta")
        self.assertEqual(self.user_texts(result), ["重来，表头要用中文"])
        _, result, _ = self.scan("--source", "codex", "--exclude-session", "019a0000-0000-7000-8000-00000000c0de", name="codex")
        self.assertEqual(self.user_texts(result), ["重来，按我给的表格格式输出"])

    def test_existing_rules_are_flagged(self):
        _, result, markdown = self.scan()
        first = next(s for s in result["signals"]["user_messages"] if s["text"].startswith("不对，我说的是"))
        self.assertTrue(first["rule_matches"])
        self.assertEqual(first["rule_matches"][0]["line"], 4)
        self.assertIn("确认统计口径", first["rule_matches"][0]["text"])
        self.assertIn("现有规则", markdown)

    def test_refuses_output_inside_git_repo(self):
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        argv = ["scan"] + WINDOW + ["--claude-root", self.claude_root, "--codex-root", self.codex_root,
                                    "--no-default-rules", "--out", str(repo / "out")]
        code, _, err = run_cli(argv)
        self.assertEqual(code, 2)
        self.assertIn("拒绝写入", err)
        self.assertFalse((repo / "out").exists())

    def test_default_out_does_not_overwrite_previous_scan(self):
        # 盲测 E2（2026-11-27）实际踩到：同一窗口不带 --out 再跑一次，覆盖了上次复盘的 signals.*
        home = self.tmp / "home"
        home.mkdir()
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        try:
            argv = ["scan"] + WINDOW + ["--claude-root", self.claude_root, "--codex-root", self.codex_root, "--no-default-rules"]
            run_cli(argv)
            first = home / "session-retro" / "2026-10-30_2026-11-01" / "signals.json"
            first.write_text("上次的结果", encoding="utf-8")
            _, _, err = run_cli(argv)
            self.assertEqual(first.read_text(encoding="utf-8"), "上次的结果")
            self.assertTrue((home / "session-retro" / "2026-10-30_2026-11-01-2" / "signals.json").exists())
            self.assertIn("已有上次的扫描结果", err)
            # 别的扫描正占着 -3（占位文件还在），这次跳到 -4；写完交还占位
            busy = home / "session-retro" / "2026-10-30_2026-11-01-3"
            busy.mkdir()
            (busy / sr.RESERVE_MARK).write_text("", encoding="utf-8")
            run_cli(argv)
            self.assertFalse((busy / "signals.json").exists())
            fourth = home / "session-retro" / "2026-10-30_2026-11-01-4"
            self.assertTrue((fourth / "signals.json").exists())
            self.assertFalse((fourth / sr.RESERVE_MARK).exists())
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    def test_output_files_are_private(self):
        self.scan(name="perm")
        mode = os.stat(str(self.tmp / "perm" / "signals.json")).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class RedactionTests(FixtureCase):
    def test_no_secrets_in_any_output(self):
        _, result, markdown = self.scan(name="redact")
        dumped = json.dumps(result, ensure_ascii=False) + markdown
        for secret in FAKE.values():
            self.assertNotIn(secret, dumped)
        self.assertNotIn("demo.user@example.com", dumped)
        self.assertNotIn("13812345678", dumped)
        self.assertIn("OPENAI_API_KEY=[已脱敏]", dumped)
        self.assertIn("[已脱敏:邮箱]", dumped)
        # 出处路径不能被误脱敏
        self.assertIn("rollout-2026-10-30T14-00-00-019a0000-0000-7000-8000-00000000c0de.jsonl", dumped)

    def test_redact_patterns(self):
        samples = {
            "Authorization: Bearer abcdefghijklmnop1234567890": "abcdefghijklmnop1234567890",
            "aws AKIA" + "ABCDEFGHIJKLMNOP": "AKIAABCDEFGHIJKLMNOP",
            "jwt eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlMTIz": "eyJhbGciOiJIUzI1NiJ9",
            "url https://x.example/cb?token=" + "abc123secret&x=1": "abc123secret",
            "git https://bob:" + "hunter2pass@github.com/x.git": "hunter2pass",
            "数据库密码是" + "Pa55word!": "Pa55word!",
            "opaque " + "Qw3rTy" * 8: "Qw3rTy" * 8,
            "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----": "MIIabc",
        }
        for raw, secret in samples.items():
            self.assertNotIn(secret, sr.redact(raw), raw)
        # 不该被误伤的：git 提交号、UUID、普通路径
        keep = "commit 3f2a9c1e4b5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f uuid 11111111-aaaa-4aaa-8aaa-000000000001 /Users/demo/proj-alpha/docs/LESSONS.md"
        self.assertEqual(sr.redact(keep), keep)

    def test_context_command_is_redacted(self):
        path = next((self.data / "codex" / "sessions").glob("2026/10/30/*c0de.jsonl"))
        code, out, _ = run_cli(["context", str(path), "--line", "17", "--before", "2", "--after", "0"])
        self.assertEqual(code, 0)
        self.assertIn("还是不对", out)
        self.assertIn("←", out)
        self.assertNotIn(FAKE["{{GH_TOKEN}}"], out)


class MatchTests(FixtureCase):
    def test_match_flags_existing_and_new(self):
        code, out, _ = run_cli(["match", "--no-default-rules", "--rules", self.rules,
                                "--text", "改代码前先确认统计口径，再动手",
                                "--text", "生成飞书文档前先问清受众"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        existing, new = data["results"]
        self.assertEqual(existing["matches"][0]["level"], "很可能已有")
        self.assertEqual(new["matches"], [])


class OriginTests(FixtureCase):
    """取常浩原话的四个过滤漏洞（my-skills#135）。样例按 2026-11-13～11-26 本机真实记录的结构改写，内容已换成演示文字。"""

    def gamma(self, name):
        return next(Path(self.data / "claude_origin" / "projects" / "-Users-demo-proj-gamma").glob("*%s.jsonl" % name))

    def scan_origin(self, name, *extra):
        out = self.tmp / name
        argv = ["scan"] + WINDOW + ["--claude-root", str(self.data / "claude_origin" / "projects"),
                                    "--codex-root", str(self.data / "codex_exec"),
                                    "--no-default-rules", "--rules", self.rules, "--out", str(out)] + list(extra)
        run_cli(argv)
        result = json.loads((out / "signals.json").read_text(encoding="utf-8"))
        return result, (out / "signals.md").read_text(encoding="utf-8")

    def users(self, name):
        coverage = sr.Counter()
        session = sr.parse_claude(self.gamma(name), coverage)
        return [(e.text, e.channel) for e in session["events"] if e.kind == "user"], coverage

    def test_bug1_reminder_first_block_is_kept(self):
        # 真实样本：origin.kind=human，首块是「Linked sessions now」提醒，第二块是常浩打的「装并重启」一类短话
        users, _ = self.users("0001")
        self.assertEqual(users[0], ("合并", "input"))
        self.assertNotIn("system-reminder", "".join(t for t, _ in users))

    def test_bug2_records_without_origin_are_not_human(self):
        # 真实样本：side-session 首条任务（turnOrigin=host_synthetic）、Hermes 派单（entrypoint=sdk-cli）都没有 origin
        users, coverage = self.users("0001")
        joined = "\n".join(t for t, _ in users)
        self.assertNotIn("Background (from the session", joined)
        self.assertNotIn("Hermes 派来干活", joined)
        self.assertGreaterEqual(coverage["non_human_messages_skipped"], 2)

    def test_bug3_agent_hud_replies_kept_relays_dropped(self):
        # 真实样本：驿窗侧栏回「合并」（pluginPrompt.text）；同一路里的 ChatGPT 审核意见 / 思维评审回信回送、
        # 接力出错通知、别的 agent 经驿窗发来的消息要排除
        users, coverage = self.users("0001")
        self.assertIn(("合并", "agent-hud"), users)
        joined = "\n".join(t for t, _ in users)
        for unwanted in ("审核意见", "思维评审回信", "出错", "Agent HUD · 来自", "The agent-hud plugin sent"):
            self.assertNotIn(unwanted, joined)
        self.assertEqual(coverage["agent_hud_relays_skipped"], 4)

    def test_bug4_codex_exec_is_dispatch_not_user(self):
        # 真实记录里 Codex 的「用户消息」全来自 originator=codex_exec 的派单
        path = next((self.data / "codex_exec").glob("*.jsonl"))
        coverage = sr.Counter()
        session = sr.parse_codex(path, coverage)
        self.assertTrue(session["dispatched"])
        self.assertEqual([e for e in session["events"] if e.kind == "user"], [])
        self.assertEqual(coverage["dispatch_messages_skipped"], 1)
        self.assertEqual([e.ok for e in session["events"] if e.kind == "tool_result"], [False])  # 工具失败照常统计

    def test_fork_copies_counted_once_across_files(self):
        result, _ = self.scan_origin("fork")
        self.assertEqual(result["coverage"]["duplicate_messages_removed"], 1)
        merge = next(s for s in result["signals"]["repeats"]["short_messages"] if s["text"] == "合并")
        self.assertEqual(merge["count"], 5)  # 输入框 4（含「合并。」）+ 驿窗 1，分叉副本不算

    def test_repeat_signal_and_buttons(self):
        result, markdown = self.scan_origin("repeat")
        rep = result["signals"]["repeats"]
        merge = rep["short_messages"][0]
        self.assertEqual((merge["id"], merge["text"]), ("S1", "合并"))
        self.assertEqual(merge["channels"], {"输入框": 4, "驿窗侧栏": 1})
        self.assertEqual(merge["equal_button"], 2)       # 两次都紧跟在给了「合并」按钮的 wrap_up 之后
        self.assertEqual(merge["equal_recommended"], 1)  # 只有第一次「合并」是第一个按钮（推荐）
        self.assertEqual(merge["sessions"], 2)
        self.assertEqual(len(rep["long_paragraphs"]), 1)
        self.assertEqual(rep["long_paragraphs"][0]["count"], 3)
        self.assertIn("AGENTS.md 的工程流程", rep["long_paragraphs"][0]["text"])
        self.assertIn("## 四、重复（短话 1 组，长段 1 段）", markdown)
        self.assertIn("等于按钮 2、等于推荐 1", markdown)
        # 派单和 side-session 任务里的「不对 / 以后都」不再混进纠正信号
        texts = "\n".join(s["text"] for s in result["signals"]["user_messages"])
        self.assertNotIn("以后都", texts)

    def test_short_min_sets_repeat_threshold(self):
        # 盲测 E2 的执行者为了看长尾，另写包装脚本把门槛从 5 改成 2；改成参数
        result, markdown = self.scan_origin("short-min-6", "--short-min", "6")
        rep = result["signals"]["repeats"]
        self.assertEqual(rep["short_min"], 6)
        self.assertEqual(rep["short_messages"], [])  # 「合并」只有 5 次，不够 6
        self.assertIn("出现 ≥ 6 次的列出", markdown)
        low, _ = self.scan_origin("short-min-5", "--short-min", "5")
        self.assertEqual([(x["text"], x["count"]) for x in low["signals"]["repeats"]["short_messages"]], [("合并", 5)])  # 门槛含等于
        self.assertEqual(low["signals"]["repeats"]["short_messages_total"], rep["short_messages_total"])  # 门槛只管列哪些，不改总数
        code, _, err = run_cli(["scan"] + WINDOW + ["--short-min", "0", "--out", str(self.tmp / "bad")])
        self.assertEqual(code, 2)
        self.assertIn("--short-min", err)

    def test_check_proposal_split(self):
        # 盲测 E2 三轮都卡在「合并」次数没带来源拆分；改成机检。样例的写法取自前几轮真实提案
        self.scan_origin("check")
        out = self.tmp / "check"
        cases = {
            "good": ("| 合并类 | S1「合并」5（输入框 4、驿窗侧栏 1） |\n- 后面再提「合并」5 次不用再拆\n", 0, []),
            "bare": ("| 合并 | 合并 5、Merge 2 等，共 7 |\n", 1, ["第 1 行 S1：第一次写全窗口次数没带来源拆分"]),
            "wrong": ("- S1「合并」5 次（输入框 3、驿窗侧栏 2）\n", 1, ["来源拆分和 signals 对不上"]),
            "paren": ("- S1「合并」5 次（2 次等于推荐）\n", 1, ["第一次写全窗口次数没带来源拆分"]),
            # ChatGPT 审查 P2-01：会话数、项目数不是次数
            "sessions": ("- 「合并」在 5 个会话里反复出现\n- 「合并」覆盖 5 个会话\n- 「合并」5 个项目\n", 0, []),
            # P2-02：同一来源写两次、来源名认不出，都要报
            "dup": ("- S1「合并」5 次（输入框 4、驿窗侧栏 1、输入框 4）\n", 1, ["「输入框」写了两次"]),
            "unknown": ("- S1「合并」5 次（输入框 4、侧栏 1）\n", 1, ["认不出的部分「侧栏 1」"]),
            "total": ("- 「合并」共 5 次（输入框 4、驿窗侧栏 1）\n", 0, []),
            # ChatGPT 审查第 2 轮 P2-01：消息数、带空格的百分号也不是次数
            "units": ("- 「合并」5 条消息\n- 「合并」5 %\n- 合并 5 个会话\n", 0, []),
            "forms": ("- 「合并」：5（输入框 4、驿窗侧栏 1）\n- 「合并」合计 5 次\n- 合并 5（输入框 4、驿窗侧栏 1）\n", 0, []),
            # P2-02：一个合法来源都没有的「侧栏 1」，第一次出现和后面再出现都要报
            "pure-unknown-first": ("- S1「合并」5 次（侧栏 5）\n", 1, ["认不出的来源「侧栏 5」"]),
            "pure-unknown-later": ("- S1「合并」5 次（输入框 4、驿窗侧栏 1）\n- 再说一次「合并」5 次（侧栏 5）\n", 1, ["认不出的来源「侧栏 5」"]),
            # 第 3 轮 P2-01：「次」后面跟别的计量也不是全窗口次数；半角括号的拆分照样认
            "freq": ("- 「合并」5次以上\n- 「合并」5次/周\n", 0, []),
            "half-paren": ("- 合并 5 (输入框 4, 驿窗侧栏 1)\n", 0, []),
            "half-paren-wrong": ("- 合并 5 (输入框 3, 驿窗侧栏 2)\n", 1, ["来源拆分和 signals 对不上"]),
            # 第 3 轮 P2-07：没收录的叫法在后面再提时也报；按项目拆、数字对不上的说明不报
            "unlisted-later": ("- S1「合并」5 次（输入框 4、驿窗侧栏 1）\n- 「合并」5 次（ChatGPT 3、网页端 2）\n- 「合并」5 次（浏览器 5）\n", 1,
                               ["认不出的来源「ChatGPT 3、网页端 2」", "认不出的来源「浏览器 5」"]),
            "not-source": ("- S1「合并」5 次（输入框 4、驿窗侧栏 1）\n- 「合并」5 次（proj-gamma 5）\n- 「合并」5 次（输入法 2）\n- 「合并」5 次（插件 2）\n", 0, []),
            "note-paren": ("- S1「合并」5 次（输入框 4、驿窗侧栏 1）\n- 「合并」5 次（等于推荐 1）\n", 0, []),
            "segment": ("- 「合并」段1 2 次、段2 3 次\n- 这组 5% 不算次数\n", 0, []),
        }
        for name, (body, want, needles) in cases.items():
            path = out / ("提案-%s.md" % name)
            path.write_text(body, encoding="utf-8")
            code, stdout, _ = run_cli(["check", str(path)])
            self.assertEqual(code, want, (name, stdout))
            for needle in needles:
                self.assertIn(needle, stdout)
            if want:
                self.assertIn("应写成：「合并」5 次（输入框 4、驿窗侧栏 1）", stdout)
        # 盲测 E2 复测：D 类漏了「落点」、合组只写了等于按钮
        d_text = ("### D1 合并 · 多次\n- 重复信号：S1「合并」5 次（输入框 4、驿窗侧栏 1），等于按钮 2、等于推荐 1\n"
                  "- 常浩在替 AI 做什么：点头\n- 建议做法：〔改规则〕\n- 落点：工程流程\n- 怎么量：下期次数\n\n"
                  "### D2 继续 · 多次\n- 重复信号：S6、S14 合计 7 次，等于按钮 0\n- 常浩在替 AI 做什么：喊醒\n"
                  "- 建议做法：〔做成钩子或定时任务〕\n- 怎么量：下期次数\n\n"
                  "### D3 搬运 · 单次\n- 重复信号：L1 3 条消息、3 个会话\n- 常浩在替 AI 做什么：搬运\n"
                  "- 建议做法：〔做成 skill〕\n- 落点：my-skills\n- 怎么量：下期 L 组\n\n"
                  # 第 2 轮 P2-05：只有关键词没有数字；没列编号
                  "### D4 放行 · 多次\n- 重复信号：S3「都按推荐」5 次（输入框 4、驿窗侧栏 1），等于按钮、等于推荐\n"
                  "- 常浩在替 AI 做什么：点头\n- 建议做法：〔改规则〕\n- 落点：全局指令\n- 怎么量：下期次数\n\n"
                  "### D6 开工 · 多次\n- 重复信号：2 组合计 9 次，等于按钮 3、等于推荐 3\n  - S4「按推荐开工」5 次\n  - S5「按计划开工」4 次\n"
                  "- 常浩在替 AI 做什么：点头\n- 建议做法：〔改规则〕\n- 落点：全局指令\n- 怎么量：下期次数\n\n"
                  "### D7 示例 · 多次\n- 重复信号：\n  - S1「合并」5 次（输入框 4、驿窗侧栏 1），等于按钮 2、等于推荐 1\n  - 落点：这里只是子项说明\n"
                  "- 常浩在替 AI 做什么：点头\n- 建议做法：〔改规则〕\n- 怎么量：下期次数\n\n"
                  "### D5 交接 · 多次\n- 重复信号：3 组合计 9 次，等于按钮 2、等于推荐 2\n"
                  "- 常浩在替 AI 做什么：点头\n- 建议做法：〔改规则〕\n- 落点：全局指令\n- 怎么量：下期次数\n\n## 已覆盖\n- 无\n")
        path = out / "提案-d.md"
        path.write_text(d_text, encoding="utf-8")
        code, stdout, _ = run_cli(["check", str(path)])
        self.assertEqual(code, 1, stdout)
        self.assertIn("D2：缺「落点」", stdout)
        self.assertIn("D2：重复信号没写「等于推荐」几次", stdout)
        self.assertIn("D4：重复信号没写「等于按钮」「等于推荐」几次", stdout)
        self.assertIn("D5：重复信号没列 S / L 编号", stdout)
        self.assertNotIn("D1：", stdout)
        self.assertNotIn("D6：", stdout)  # 编号写在子项里也算列了
        self.assertIn("D7：缺「落点」", stdout)  # 第 3 轮 P2-06：子项里的「落点」不算主字段
        self.assertNotIn("D3：", stdout)  # L 组没有按钮数据，不要求
        code, _, err = run_cli(["check", str(self.tmp / "nowhere" / "提案.md")])
        self.assertEqual(code, 2)

    def test_parse_split_project_names(self):
        # ChatGPT 审查第 4 轮 P2-07：projects 只存前 5 个，第 6 个项目名不能被当成认不出的来源
        names = ["proj-%s" % x for x in "abcdef"]
        item = {"count": 6, "projects": dict((n, 1) for n in names[:5]), "project_names": names}
        paren = "（%s）" % "、".join("%s 1" % n for n in names)
        self.assertEqual(sr.parse_split(paren, item), (None, None))
        self.assertIn("认不出的来源", sr.parse_split("（浏览器 6）", item)[1])
        # 旧版 signals 没有完整名单、前 5 个已满：名单可能不全，不据此报
        old = {"count": 6, "projects": item["projects"]}
        self.assertEqual(sr.parse_split(paren, old), (None, None))
        # 「等于…」是统计说明，不是来源
        self.assertEqual(sr.parse_split("（等于按钮 3、等于推荐 3）", item), (None, None))
        # 第 5 轮 P2-08：只放过这两个确切的统计说明，别的「等于…」叫法照样报
        self.assertIn("认不出的来源", sr.parse_split("（等于浏览器 6）", item)[1])
        self.assertIn("认不出的来源", sr.parse_split("（等于侧栏 6）", item)[1])
        self.assertIn("认不出的来源", sr.parse_split("（等于按钮 3、等于侧栏 3）", item)[1])


class RejectionGuardTests(unittest.TestCase):
    def test_plain_output_mentioning_rejection_is_not_a_rejection(self):
        tmp = Path(tempfile.mkdtemp(prefix="session-retro-guard-"))
        try:
            claude = tmp / "c.jsonl"
            claude.write_text("\n".join(json.dumps(r) for r in [
                {"type": "assistant", "timestamp": "2026-10-30T02:00:00Z", "sessionId": "s", "uuid": "a",
                 "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "grep -r rejected ."}}]}},
                {"type": "user", "timestamp": "2026-10-30T02:00:01Z", "sessionId": "s", "uuid": "b",
                 "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "is_error": False,
                                                          "content": "notes.md: the tool use was rejected by the user last time"}]}},
            ]) + "\n", encoding="utf-8")
            kinds = [e.kind for e in sr.parse_claude(claude, sr.Counter())["events"]]
            self.assertEqual(kinds, ["tool_call", "tool_result"])
            codex = tmp / "rollout-2026-10-30T10-00-00-x.jsonl"
            codex.write_text("\n".join(json.dumps(r) for r in [
                {"timestamp": "2026-10-30T02:00:00Z", "type": "session_meta", "payload": {"id": "x", "cwd": "/d", "source": "cli"}},
                {"timestamp": "2026-10-30T02:00:01Z", "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "{}", "call_id": "c1"}},
                {"timestamp": "2026-10-30T02:00:02Z", "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1",
                 "output": "Exit code: 0\nOutput:\n" + "log line\n" * 60 + "request was rejected by user policy"}},
            ]) + "\n", encoding="utf-8")
            kinds = [e.kind for e in sr.parse_codex(codex, sr.Counter())["events"]]
            self.assertEqual(kinds, ["tool_call", "tool_result"])
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class SafetyTests(unittest.TestCase):
    def test_script_has_no_network_imports(self):
        source = (HERE.parent / "scripts" / "session_retro.py").read_text(encoding="utf-8")
        for module in ("socket", "urllib", "http.client", "requests", "subprocess", "ftplib", "smtplib"):
            self.assertNotIn("import " + module, source)
            self.assertNotIn("from " + module, source)


if __name__ == "__main__":
    unittest.main()
