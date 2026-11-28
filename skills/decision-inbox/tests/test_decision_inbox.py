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
        self.assertIn("等你 11", self.said)
        self.assertIn("留下 8", self.said)

    def test_what_is_dropped(self):
        kept = self.kept()
        self.assertEqual(sorted(kept), ["1", "3", "4", "6", "7", "8", "a", "c"])
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

    def test_takes_the_last_status_line_of_a_reply(self):
        row = self.kept()["8"]
        self.assertEqual(row["word"], "等你决定")
        self.assertIn("限流阈值", row["status"])
        self.assertIn("每分钟 60 次", row["next"])

    def test_peer_message_is_not_a_reply(self):
        row = self.kept()["8"]
        self.assertTrue(row["peerAfter"])
        self.assertIn("之后收到过别的会话的消息", self.candidates)

    def test_old_unanswered_reply_is_listed_again(self):
        # 「插件」26 小时前回过，一直没出新状态，要重新列；「周报」半小时前才回，照旧筛掉。
        self.assertTrue(self.kept()["7"]["replyUnanswered"])
        self.assertIn("可能没被接走", self.candidates)

    def test_fresh_reply_is_still_dropped(self):
        self.append("3", make_fixtures.user(self.now, 0.5, "没问题"))
        _, said = run(self.dirs, "collect", "--out", self.out)
        self.assertIn("'你已回复、还在做': 2", said)

    def test_latest_list_is_picked_by_time_not_name(self):
        second = os.path.join(self.dirs["inbox"], "拍板清单-2026-01-01-2.md")
        with open(second, "w") as handle:
            handle.write(f"- `{make_fixtures.sid('c', 3)}`\n")
        os.utime(second, (self.now + 5, self.now + 5))
        name, before = inbox.listed_before(self.dirs["inbox"])
        self.assertEqual(name, "拍板清单-2026-01-01-2.md")
        self.assertEqual(before, {"cccccccc"})

    def test_ignore_add_dedupes_ids(self):
        _, said = run(self.dirs, "ignore", "add", "--since", os.path.join(self.out, "waiting.json"),
                      "--ids", "33333333", make_fixtures.sid("3", 9), "--by", "测试")
        self.assertIn("记了 1 个", said)

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
        self.assertIn("留下 7", said)
        _, listed = run(self.dirs, "ignore", "list")
        self.assertIn("侧栏｜排序修复", listed)

    def test_ignore_add_needs_who_said_so(self):
        with self.assertRaises(SystemExit):
            run(self.dirs, "ignore", "add", "--since", os.path.join(self.out, "waiting.json"),
                "--ids", "33333333")


class Replied(unittest.TestCase):
    """my-skills#129：回过话之后，看会话动没动过，不只看有没有新的状态行。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = time.time()
        self.dirs = make_fixtures.build(self.tmp.name, self.now, make_fixtures.replied(self.now))
        rows, _ = inbox.scan(self.dirs["meta"], self.dirs["projects"], 14, self.now)
        self.rows = {row["id8"][0]: row for row in rows}
        kept, self.dropped = inbox.sift(rows, {}, set(), self.now)
        self.kept = {row["id8"][0]: row for row in kept}

    def tearDown(self):
        self.tmp.cleanup()

    def test_reply_taken_is_not_listed(self):
        # 1 办完了没写状态行；2 做到一半进程没了；3 做到一半被打断：回的话都被接走了。
        for tag in "123":
            self.assertNotIn(tag, self.kept)
        self.assertEqual(self.dropped["你已回复、会话已接着做"], 5)

    def test_words_after_an_injected_reminder_are_his(self):
        self.assertEqual(self.rows["4"]["userAfter"][-1]["text"], "按推荐开工")
        self.assertNotIn("4", self.kept)

    def test_reply_nobody_took_is_still_listed(self):
        self.assertTrue(self.kept["5"]["replyUnanswered"])
        out = os.path.join(self.tmp.name, "run")
        run(self.dirs, "collect", "--out", out)
        with open(os.path.join(out, "candidates.md")) as handle:
            self.assertIn("你 2.1 天前回了「用乙」，之后会话没有动过", handle.read())

    def test_host_written_reply_is_not_the_session_moving(self):
        self.assertTrue(self.kept["7"]["replyUnanswered"])

    def test_all_record_files_of_a_session_are_read(self):
        row = self.rows["8"]
        self.assertEqual([reply["text"] for reply in row["userAfter"]], ["选甲"])
        self.assertIn("首页用哪一版", row["status"])
        self.assertNotIn("8", self.kept)

    def test_new_question_after_the_reply_is_listed(self):
        row = self.kept["9"]
        self.assertFalse(row["replyUnanswered"])
        self.assertIn("重新加载插件", row["status"])

    def test_fresh_reply_keeps_its_old_reason(self):
        self.assertNotIn("a", self.kept)
        self.assertEqual(self.dropped["你已回复、还在做"], 1)
        self.assertEqual(sorted(self.kept), ["5", "7", "9"])


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
