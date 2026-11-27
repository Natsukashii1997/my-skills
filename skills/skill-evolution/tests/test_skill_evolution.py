#!/usr/bin/env python3
"""skill-evolution 测试：只用 make_fixture.py 生成的合成会话，不碰任何真实会话。

运行：python3 -m unittest discover -s skills/skill-evolution/tests -v
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import make_fixture  # noqa: E402
import skill_evolution as se  # noqa: E402


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = se.main(argv)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    with_zst = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="skill-evolution-test-"))
        cls.root = make_fixture.build(cls.tmp / "week", with_zst=cls.with_zst)
        cls.out = cls.tmp / "out"
        cls.code, cls.stdout, cls.stderr = run_cli(cls.argv(cls.out))
        cls.result = json.loads((cls.out / "sessions.json").read_text(encoding="utf-8"))
        cls.markdown = (cls.out / "sessions.md").read_text(encoding="utf-8")
        cls.by_sid = {s["session_id"]: s for s in cls.result["sessions"]}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    @classmethod
    def argv(cls, out, *extra):
        return ["scan", "--start", "2026-11-02", "--end", "2026-11-09", "--claude-root", str(cls.root / "claude"),
                "--codex-root", str(cls.root / "codex"), "--skills-root", str(cls.root / "skills"),
                "--own-skills-root", str(cls.root / "skills"), "--out", str(out)] + list(extra)


class ScanCase(Base):
    def test_exit_and_counts(self):
        self.assertEqual(self.code, 0, self.stderr)
        self.assertEqual(len(self.result["sessions"]), 10)
        self.assertEqual(self.result["coverage"]["sessions_claude"], 9)
        self.assertEqual(self.result["coverage"]["sessions_codex"], 1)
        self.assertEqual(self.result["coverage"]["sessions_without_human"], 1)
        self.assertNotIn("dispatch-1", self.by_sid)
        self.assertEqual(self.result["gaps"], [])

    def test_projects_group_worktree_back_to_repo(self):
        self.assertEqual(self.by_sid["push-2"]["project"], "sidebar")
        self.assertEqual(sum(1 for s in self.result["sessions"] if s["project"] == "sidebar"), 3)
        self.assertEqual(self.result["projects"][0], "sidebar")  # 发话最多的项目排最前
        self.assertIn("### sidebar（3 个会话", self.markdown)

    def test_ids_unique_and_ordered(self):
        ids = [s["id"] for s in self.result["sessions"]]
        self.assertEqual(ids, ["S%02d" % n for n in range(1, 11)])

    def test_session_summary_fields(self):
        push = self.by_sid["push-3"]
        self.assertIn("收集这周的需求反馈", push["first"]["text"])
        self.assertEqual(push["user_messages"], 2)
        self.assertEqual(push["tool_calls"], 3)
        self.assertEqual(len(push["strong_corrections"]), 1)
        keys = [k for k, _ in push["footprint"]]
        self.assertIn("Bash: lark-cli im +messages-search", keys)
        self.assertIn("Write: 推进说明.md", keys)

    def test_redaction(self):
        self.assertNotIn(make_fixture.FAKE_KEY, self.markdown)
        self.assertNotIn(make_fixture.FAKE_KEY, json.dumps(self.result, ensure_ascii=False))
        self.assertIn("[已脱敏", self.by_sid["push-3"]["later"][0]["text"])

    def test_session_started_before_window_shows_original_request(self):
        early = self.by_sid["early-1"]
        self.assertTrue(early["began_before"])
        self.assertEqual(early["first"]["text"], "搭一个周报生成器")
        self.assertEqual([m["text"] for m in early["later"]], ["继续"])
        self.assertEqual(early["tool_calls"], 1)  # 只算窗口内的
        self.assertIn("起始请求（会话始于窗口前）：「搭一个周报生成器」", self.markdown)

    def test_skill_usage(self):
        usage = {row["skill"]: row for row in self.result["usage"]}
        self.assertEqual(sorted(usage), ["matt-flow", "ui-styles"])  # /model 不是 skill，不算
        ui = usage["ui-styles"]
        self.assertEqual((ui["calls"], ui["sessions"]), (2, 2))
        self.assertEqual(dict(ui["how"]), {"Skill 工具": 1, "斜杠命令": 1})
        self.assertEqual(len(ui["after_corrections"]), 1)
        self.assertIn("细线", ui["after_corrections"][0]["text"])
        flow = usage["matt-flow"]
        self.assertEqual((flow["calls"], flow["sessions"]), (2, 2))  # 派单会话 1 次 + Codex 同一会话读两遍只算 1 次
        self.assertTrue(ui["own"])
        self.assertEqual(self.by_sid["page-1"]["skills"], ["ui-styles"])

    def test_unused_own_skills(self):
        self.assertEqual(self.result["unused_own"], ["excel-aura", "idle-skill"])
        self.assertIn("`excel-aura`、`idle-skill`", self.markdown)

    def test_output_is_private(self):
        self.assertEqual(os.stat(str(self.out / "sessions.md")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(str(self.out)).st_mode & 0o777, 0o700)

    def test_exclude_and_project_filter(self):
        out = self.tmp / "out-filter"
        code, _, err = run_cli(self.argv(out, "--project", "sidebar", "--exclude-session", "push-1"))
        self.assertEqual(code, 0, err)
        sessions = json.loads((out / "sessions.json").read_text(encoding="utf-8"))["sessions"]
        self.assertEqual(sorted(s["session_id"] for s in sessions), ["push-2", "push-3"])

    def test_refuses_git_repo(self):
        repo = self.tmp / "repo"
        (repo / ".git").mkdir(parents=True)
        code, _, err = run_cli(self.argv(repo / "out"))
        self.assertEqual(code, 2)
        self.assertIn("拒绝写入", err)

    def test_noise_tools_not_in_footprint(self):
        class Event(object):
            def __init__(self, tool, key):
                self.tool, self.key = tool, key
        retro = se.load_retro()
        self.assertIsNone(se.footprint_key(retro, Event("mcp__ccd_turn__update_plan", "mcp__ccd_turn__update_plan")))
        self.assertEqual(se.footprint_key(retro, Event("Bash", "Bash: ")), "Bash（其他）")
        self.assertTrue(se.footprint_key(retro, Event("Bash", "Bash: " + "x" * 200)).endswith("…"))


class ZstGapCase(Base):
    with_zst = True

    def test_compressed_codex_files_reported_as_gap(self):
        self.assertEqual(self.code, 3)
        self.assertEqual(self.result["coverage"]["codex_zst_unread"], 1)
        self.assertIn("codex_zst_unread", self.result["gaps"])
        self.assertIn("codex_zst_unread=1", self.markdown)


class WindowCase(unittest.TestCase):
    def test_last_week_is_previous_monday_to_sunday(self):
        self.assertEqual(se.last_week(date(2026, 11, 30)), (date(2026, 11, 23), date(2026, 11, 30)))  # 周一跑
        self.assertEqual(se.last_week(date(2026, 11, 28)), (date(2026, 11, 16), date(2026, 11, 23)))  # 周六跑
        self.assertEqual(se.last_week(date(2026, 11, 29)), (date(2026, 11, 16), date(2026, 11, 23)))  # 周日跑

    def test_project_of(self):
        self.assertEqual(se.project_of("/Users/x/work/.worktrees/my-skills-77"), "my-skills")
        self.assertEqual(se.project_of("/Users/x/work/a/.claude/worktrees/9-b/sub"), "a")
        self.assertEqual(se.project_of("/Users/x/Library/Application Support/Claude/scratch-workspaces/1/2"), "临时会话")
        self.assertEqual(se.project_of("/Users/x/Sandbox/2026-11-07-try"), "Sandbox（试验）")
        self.assertEqual(se.project_of(None), "(未知目录)")

    def test_default_out_does_not_overwrite(self):
        home = tempfile.mkdtemp(prefix="skill-evolution-home-")
        try:
            old = os.environ.get("HOME")
            os.environ["HOME"] = home
            first = se.default_out(date(2026, 11, 2), date(2026, 11, 9))
            first.mkdir(parents=True)
            (first / "sessions.json").write_text("{}")
            self.assertEqual(se.default_out(date(2026, 11, 2), date(2026, 11, 9)).name, "2026-11-02_2026-11-09-2")
        finally:
            os.environ["HOME"] = old
            shutil.rmtree(home, ignore_errors=True)

    def test_missing_session_retro_says_so(self):
        loaded = sys.modules.pop("session_retro", None)
        try:
            with self.assertRaises(SystemExit) as caught:
                se.load_retro(Path("/nonexistent/session_retro.py"))
            self.assertIn("找不到 session-retro 的脚本", str(caught.exception))
        finally:
            if loaded is not None:
                sys.modules["session_retro"] = loaded


GOOD = """# skill 进化提案

## 二、新 skill 候选

### N1 项目推进说明（project-push）

- **做什么**：收集飞书需求、拉最新进度、按三个维度写推进说明。
- **依据**：S01、S02、S03 三次走法一致。
- **成熟度**：可立项
- **为什么是 skill**：有判断点，不是固定脚本。
- **和现有 skill 的分工**：business-notice 只管成稿语气。
- **怎么做**：先记候选 issue。
- **推荐**：做

## 三、现有 skill 改进

### E1 excel-aura 该触发没触发

- **skill**：excel-aura
- **问题**：该触发没触发
- **依据**：S05、S06
- **改法**：description 加「美化一下」。
- **推荐**：做
"""


class CheckCase(unittest.TestCase):
    IDS = set("S%02d" % n for n in range(1, 11))

    def test_good_proposal_passes(self):
        self.assertEqual(se.check_proposal(GOOD, self.IDS), [])

    def test_unknown_session_id(self):
        problems = se.check_proposal(GOOD.replace("S05、S06", "S05、S77"), self.IDS)
        self.assertTrue(any("S77" in p for p in problems), problems)

    def test_ready_needs_two_sessions(self):
        problems = se.check_proposal(GOOD.replace("S01、S02、S03 三次走法一致", "S01 一次"), self.IDS)
        self.assertTrue(any("至少真做过两次" in p for p in problems), problems)
        self.assertEqual(se.check_proposal(GOOD.replace("S01、S02、S03 三次走法一致", "S01 一次").replace("成熟度**：可立项", "成熟度**：继续观察"), self.IDS), [])

    def test_ready_counts_candidate_issue_as_one(self):
        self.assertEqual(se.check_proposal(GOOD.replace("S01、S02、S03 三次走法一致", "S01，加上候选 #70 里记的那次"), self.IDS), [])

    def test_missing_field_and_bad_maturity(self):
        problems = se.check_proposal(GOOD.replace("- **改法**：description 加「美化一下」。\n", ""), self.IDS)
        self.assertTrue(any("E1：缺「改法」" in p for p in problems), problems)
        problems = se.check_proposal(GOOD.replace("成熟度**：可立项", "成熟度**：很成熟"), self.IDS)
        self.assertTrue(any("只能以「可立项」或「继续观察」开头" in p for p in problems), problems)

    def test_evidence_needs_session_id(self):
        problems = se.check_proposal(GOOD.replace("S05、S06", "上周两次"), self.IDS)
        self.assertTrue(any("E1：「依据」里没有会话编号" in p for p in problems), problems)

    def test_too_many(self):
        extra = "".join("\n### E%d x\n\n- **skill**：a\n- **问题**：b\n- **依据**：S01\n- **改法**：c\n- **推荐**：做\n" % n for n in range(2, 9))
        problems = se.check_proposal(GOOD + extra, self.IDS)
        self.assertTrue(any("超过上限 7 条" in p for p in problems), problems)

    def test_cli(self):
        folder = Path(tempfile.mkdtemp(prefix="skill-evolution-check-"))
        try:
            (folder / "sessions.json").write_text(json.dumps({"sessions": [{"id": i} for i in sorted(self.IDS)]}))
            (folder / "提案.md").write_text(GOOD, encoding="utf-8")
            code, out, _ = run_cli(["check", str(folder / "提案.md")])
            self.assertEqual((code, out.strip()), (0, "通过：2 条提案，会话编号都对得上。"))
            (folder / "提案.md").write_text(GOOD.replace("S05、S06", "S99"), encoding="utf-8")
            self.assertEqual(run_cli(["check", str(folder / "提案.md")])[0], 1)
            self.assertEqual(run_cli(["check", str(folder / "没有.md")])[0], 2)
        finally:
            shutil.rmtree(str(folder), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
