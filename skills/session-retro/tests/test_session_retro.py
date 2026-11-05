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
