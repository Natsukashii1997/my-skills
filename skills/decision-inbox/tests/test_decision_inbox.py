"""python3 -m unittest discover -s skills/decision-inbox/tests（只用合成样例）"""
import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))

import decision_inbox as inbox  # noqa: E402
import make_fixtures  # noqa: E402


def run(dirs, *argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = inbox.main(
            ["--meta-dir", dirs["meta"], "--projects-dir", dirs["projects"],
             "--inbox-dir", dirs["inbox"], *argv]
        )
    return code, out.getvalue()


class Collect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = time.time()
        self.dirs = make_fixtures.build(self.tmp.name, self.now)
        self.out = os.path.join(self.tmp.name, "run")
        self.code, self.said = run(self.dirs, "collect", "--out", self.out)
        with open(os.path.join(self.out, "waiting.json")) as handle:
            self.snapshot = json.load(handle)
        with open(os.path.join(self.out, "candidates.md")) as handle:
            self.candidates = handle.read()

    def tearDown(self):
        self.tmp.cleanup()

    def kept(self):
        rows = self.snapshot["rows"]
        left, _ = inbox.sift(rows, inbox.load_ignored(self.dirs["inbox"]),
                             inbox.listed_before(self.dirs["inbox"])[1])
        return {row["id8"][0]: row for row in left}

    def test_counts(self):
        self.assertEqual(self.code, 0)
        self.assertEqual(self.snapshot["skipped"]["已归档"], 1)
        self.assertEqual(self.snapshot["skipped"]["没写状态行"], 1)
        self.assertIn("等你 9", self.said)
        self.assertIn("留下 6", self.said)

    def test_what_is_dropped(self):
        kept = self.kept()
        self.assertEqual(sorted(kept), ["1", "3", "4", "6", "a", "c"])
        self.assertNotIn("b", kept)  # 交给了下游会话 c
        self.assertNotIn("d", kept)  # 用户已回复
        self.assertNotIn("e", kept)  # 已结束
        self.assertNotIn("f", kept)  # 在忽略名单里，状态没变

    def test_injected_lines_are_not_replies(self):
        # a 后面只有宿主注入的提醒，不算用户回复。
        self.assertEqual(self.kept()["a"]["userAfter"], [])

    def test_ignored_session_comes_back_when_it_moves(self):
        # 「课件」在忽略名单里，但之后又出了新状态，要重新列，而且取的是最新一问。
        self.assertIn("第 3 章用哪个案例", self.kept()["1"]["status"])

    def test_flags(self):
        kept = self.kept()
        self.assertTrue(kept["3"]["prDone"])
        self.assertFalse(kept["a"]["prDone"])
        self.assertTrue(kept["6"]["listedBefore"])
        self.assertFalse(kept["c"]["listedBefore"])
        self.assertEqual(kept["c"]["parent"], "bbbbbbbb")

    def test_candidates_file(self):
        self.assertIn("这是候选，不是清单", self.candidates)
        self.assertIn(make_fixtures.sid("4", 10), self.candidates)
        self.assertIn("PR 都已合并或关闭，可能过期", self.candidates)
        seen = self.candidates.split("## 上一份清单里已经有的")[1]
        self.assertIn("账单｜对账脚本", seen)

    def append(self, tag, entry):
        path = os.path.join(self.dirs["projects"], f"-work-{dict((s[0], s[2]) for s in make_fixtures.sessions(self.now))[tag]}",
                            f"cli-{tag * 4}.jsonl")
        with open(path, "a") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def test_recheck_unchanged(self):
        code, said = run(self.dirs, "recheck", "--since", os.path.join(self.out, "waiting.json"),
                         "--ids", "aaaaaaaa", make_fixtures.sid("c", 3))
        self.assertEqual(code, 0)
        self.assertEqual(said.count("没变"), 2)

    def test_recheck_sees_a_new_question(self):
        self.append("a", make_fixtures.assistant(
            self.now, 0, make_fixtures.closing("等你操作", "已合并，等你重新加载插件。", "重新加载插件。")))
        code, said = run(self.dirs, "recheck", "--since", os.path.join(self.out, "waiting.json"),
                         "--ids", "aaaaaaaa", "cccccccc")
        self.assertEqual(code, 4)
        self.assertIn("出了新状态", said)
        self.assertIn("等你重新加载插件", said)
        self.assertIn("变了 1 个", said)

    def test_recheck_sees_a_reply_in_flight(self):
        self.append("c", make_fixtures.user(self.now, 0, "选乙"))
        code, said = run(self.dirs, "recheck", "--since", os.path.join(self.out, "waiting.json"),
                         "--ids", "cccccccc")
        self.assertEqual(code, 4)
        self.assertIn("收到了新消息", said)

    def test_recheck_rejects_unknown_id(self):
        with self.assertRaises(SystemExit):
            run(self.dirs, "recheck", "--since", os.path.join(self.out, "waiting.json"),
                "--ids", "99999999")

    def test_readback(self):
        self.append("4", make_fixtures.assistant(
            self.now, 0, make_fixtures.closing("已结束", "PR #31 已合并，没有发群。", "本任务已结束，下一步无需任何动作。")))
        code, said = run(self.dirs, "readback", "--since", os.path.join(self.out, "waiting.json"),
                         "--ids", "44444444", "33333333")
        self.assertEqual(code, 0)
        self.assertIn("已出新状态 1 / 2", said)
        self.assertIn("没有发群", said)
        self.assertIn("还没动静", said)

    def test_ignore_add_then_collect(self):
        code, said = run(self.dirs, "ignore", "add", "--since", os.path.join(self.out, "waiting.json"),
                         "--ids", "33333333", "--by", "测试 2026-01-02 回「记忽略」")
        self.assertEqual(code, 0)
        self.assertIn("名单里共 3 个", said)
        _, said = run(self.dirs, "collect", "--out", self.out)
        self.assertIn("留下 5", said)
        _, listed = run(self.dirs, "ignore", "list")
        self.assertIn("侧栏｜排序修复", listed)

    def test_ignore_add_needs_who_said_so(self):
        with self.assertRaises(SystemExit):
            run(self.dirs, "ignore", "add", "--since", os.path.join(self.out, "waiting.json"),
                "--ids", "33333333")


class Parsing(unittest.TestCase):
    def test_status_line_variants(self):
        for line in ("**当前状态**：〔等你决定〕要选版。", "当前状态:〔等你决定〕要选版。",
                     "**当前状态：**〔等你决定〕要选版。"):
            self.assertEqual(inbox.STATUS.search(line).group(1), "等你决定", line)

    def test_listed_before_without_lists(self):
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(inbox.listed_before(empty), (None, set()))


if __name__ == "__main__":
    unittest.main()
