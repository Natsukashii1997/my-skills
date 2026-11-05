#!/usr/bin/env python3
"""在临时目录里造合成仓库，覆盖各种 worktree 情况，检查分档和 sweep 只删该删的。

  python3 -m unittest discover -s skills/worktree-sweep/tests -v
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "worktree_sweep.py"
SPEC = importlib.util.spec_from_file_location("worktree_sweep", SCRIPT)
WS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(WS)

ENV = dict(os.environ)
ENV.update({
    "GIT_AUTHOR_NAME": "测试", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "测试", "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
})
LATER = time.time() + 30 * 86400  # 假装「现在」是 30 天后：所有 worktree 都算很久没动


def sh(cwd, *args, check=True):
    p = subprocess.run(list(args), cwd=cwd, env=ENV, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionError(f"{args} 失败：{p.stderr}")
    return p.stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def commit(cwd, rel, text, msg):
    write(os.path.join(cwd, rel), text)
    sh(cwd, "git", "add", rel)
    sh(cwd, "git", "commit", "-q", "-m", msg)


def build(tmp):
    """返回 (根目录, 主仓库路径, {情况名: worktree 路径}, 远端裸仓库路径)。"""
    root = os.path.join(tmp, "工作区")
    os.makedirs(root)
    remote = os.path.join(tmp, "remote.git")
    sh(tmp, "git", "init", "-q", "--bare", "-b", "main", remote)
    seed = os.path.join(tmp, "seed")
    sh(tmp, "git", "clone", "-q", remote, seed)
    sh(seed, "git", "checkout", "-q", "-b", "main")
    write(os.path.join(seed, ".gitignore"), "node_modules/\n.env\n.claude/\n")
    commit(seed, "a.txt", "第一行\n第二行\n第三行\n", "init")
    commit(seed, "b.txt", "b\n", "add b")
    commit(seed, ".gitignore", "node_modules/\n.env\n.claude/\n", "ignore")
    write(os.path.join(seed, ".env"), "KEY=主目录\n")
    sh(seed, "git", "push", "-q", "-u", "origin", "main")
    main = os.path.join(root, "项目甲")
    sh(tmp, "git", "clone", "-q", remote, main)
    write(os.path.join(main, ".env"), "KEY=主目录\n")

    w = {}

    def add(name, branch=None, where=None, detach=False):
        path = where or os.path.join(main, ".claude", "worktrees", name)
        args = ["git", "worktree", "add", "-q"]
        args += ["--detach", path, "main"] if detach else ["-b", branch, path, "main"]
        sh(main, *args)
        w[name] = path
        return path

    # 1. 普通合并（--no-ff），远端分支还在；带 node_modules（能重新生成，不影响）
    p = add("普通合并", "feat/normal")
    commit(p, "n.txt", "n\n", "normal")
    sh(p, "git", "push", "-q", "-u", "origin", "feat/normal")
    write(os.path.join(p, "node_modules", "x", "index.js"), "x\n")
    sh(main, "git", "merge", "-q", "--no-ff", "-m", "merge normal", "feat/normal")

    # 2. squash 合并，之后默认分支又改了别的文件；远端分支已删
    p = add("squash合并", "feat/squash")
    commit(p, "s.txt", "s1\n", "s1")
    commit(p, "s.txt", "s1\ns2\n", "s2")
    sh(p, "git", "push", "-q", "-u", "origin", "feat/squash")
    sh(main, "git", "merge", "-q", "--squash", "feat/squash")
    sh(main, "git", "commit", "-q", "-m", "squash feat/squash")

    # 3. squash 合并，之后默认分支又改了同一个文件（只能靠 patch-id 认出来）
    p = add("squash后又改", "feat/squash2")
    commit(p, "a.txt", "第一行\n第二行改\n第三行\n", "edit a 1")
    commit(p, "a.txt", "第一行\n第二行改\n第三行改\n", "edit a 2")
    sh(main, "git", "merge", "-q", "--squash", "feat/squash2")
    sh(main, "git", "commit", "-q", "-m", "squash feat/squash2")
    commit(main, "a.txt", "第一行\n第二行改\n第三行改\n第四行\n", "main edits a again")

    # 4. 变基合并（提交被 cherry-pick 进默认分支）
    p = add("变基合并", "feat/rebase")
    commit(p, "r.txt", "r\n", "rebase me")
    commit(main, "m.txt", "m\n", "main moves on")  # 先让默认分支往前走，cherry-pick 才会生成新提交
    sh(main, "git", "cherry-pick", "feat/rebase")

    # 5. 有未提交改动
    p = add("有未提交", "feat/dirty")
    write(os.path.join(p, "b.txt"), "改了没提交\n")

    # 6. 有未跟踪的新文件
    p = add("有新文件", "feat/untracked")
    write(os.path.join(p, "新文件.md"), "草稿\n")

    # 7. 有未推送的提交
    p = add("有未推送", "feat/unpushed")
    commit(p, "u.txt", "u\n", "local only")

    # 8. 已推送但没合并
    p = add("没合并", "feat/open")
    commit(p, "o.txt", "o\n", "open work")
    sh(p, "git", "push", "-q", "-u", "origin", "feat/open")

    # 9. 被锁定（内容已合并）
    p = add("锁定", "feat/locked")
    sh(main, "git", "worktree", "lock", "--reason", "放在外接盘", p)

    # 10. 目录已丢失（prunable）
    p = add("目录丢了", "feat/gone")
    shutil.rmtree(p)

    # 11. 中文路径，放在仓库外面，squash 合并
    p = add("中文路径", "功能/中文", where=os.path.join(root, "中文 目录", "功能一"))
    commit(p, "说明.md", "中文内容\n", "中文提交")
    sh(main, "git", "merge", "-q", "--squash", "功能/中文")
    sh(main, "git", "commit", "-q", "-m", "squash 中文")

    # 12. 已合并，但有程序正把它当当前目录
    add("被占用", "feat/busy")

    # 13. 已合并，但 .env 和主目录不一样（git 不管，删了找不回）
    p = add("本地文件", "feat/env")
    write(os.path.join(p, ".env"), "KEY=单独改过\n")

    # 14. 已合并，.env 和主目录一样
    p = add("同样env", "feat/sameenv")
    write(os.path.join(p, ".env"), "KEY=主目录\n")

    # 15. detached HEAD，提交已在默认分支
    add("游离", detach=True)

    # 16. 已合并、工作区干净，但 rebase 停在一半
    p = add("变基中途", "feat/midrebase")
    commit(p, "mr.txt", "mr\n", "mid rebase")
    sh(main, "git", "merge", "-q", "--no-ff", "-m", "merge midrebase", "feat/midrebase")
    sh(p, "git", "rebase", "--exec", "false", "HEAD~1", check=False)
    assert os.path.isdir(os.path.join(sh(p, "git", "rev-parse", "--absolute-git-dir"), "rebase-merge"))

    sh(main, "git", "push", "-q", "origin", "main")
    sh(main, "git", "push", "-q", "origin", "--delete", "feat/squash")
    sh(main, "git", "fetch", "-q", "--prune", "origin")
    return root, main, w, remote


def run_cli(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args], env=ENV, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


EXPECT = {
    "普通合并": WS.SAFE, "squash合并": WS.SAFE, "squash后又改": WS.SAFE, "变基合并": WS.SAFE,
    "有未提交": WS.LOOK, "有新文件": WS.LOOK, "有未推送": WS.LOOK, "没合并": WS.LOOK,
    "锁定": WS.KEEP, "目录丢了": WS.SAFE, "中文路径": WS.SAFE, "被占用": WS.KEEP,
    "本地文件": WS.LOOK, "同样env": WS.SAFE, "游离": WS.SAFE, "变基中途": WS.LOOK,
}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="wt-sweep-")
        self.root, self.main, self.w, self.remote = build(self.tmp)
        self.state = os.path.join(self.tmp, "state")
        self.busy = subprocess.Popen(["sleep", "300"], cwd=self.w["被占用"])

    def tearDown(self):
        self.busy.kill()
        self.busy.wait()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def list_json(self, *extra):
        rc, out, err = run_cli("list", self.root, "--no-gh", "--json", "--state-dir", self.state, *extra)
        self.assertEqual(rc, 0, err)
        data = json.loads(out)
        return {it["path"]: it for it in data["items"]}

    def tiers(self, items):
        return {name: items[WS.norm(p)]["tier"] for name, p in self.w.items()}


class ClassifyTests(Fixture):
    def test_tiers_when_everything_is_old(self):
        items = self.list_json("--now", str(LATER))
        got = self.tiers(items)
        self.assertEqual(got, EXPECT)
        main = items[WS.norm(self.main)]
        self.assertTrue(main["is_main"])
        self.assertEqual(main["tier"], WS.KEEP)
        self.assertEqual(len(items), len(self.w) + 1)

    def test_merge_detection_methods(self):
        items = self.list_json("--now", str(LATER))
        how = {name: items[WS.norm(p)]["merged"] for name, p in self.w.items()}
        self.assertEqual(how["普通合并"], "提交已在默认分支里")
        self.assertTrue(how["squash合并"].startswith("squash 合并（改过的文件"))
        self.assertTrue(how["squash后又改"].startswith("squash 合并（默认分支里有同样改动"))
        self.assertTrue(how["变基合并"].startswith("变基合并"))
        self.assertIsNone(how["有未推送"])
        self.assertIsNone(how["没合并"])
        self.assertEqual(items[WS.norm(self.w["squash合并"])]["remote"], "远端分支已删")
        self.assertEqual(items[WS.norm(self.w["普通合并"])]["remote"], "远端分支还在")
        self.assertEqual(items[WS.norm(self.w["有未推送"])]["unpushed"], 1)

    def test_recent_work_is_kept(self):
        items = self.list_json()  # 用真实的现在：都是刚建的
        got = self.tiers(items)
        for name in ("普通合并", "squash合并", "没合并", "有未提交", "有未推送"):
            self.assertEqual(got[name], WS.KEEP, name)
        self.assertEqual(got["目录丢了"], WS.SAFE)

    def test_list_does_not_touch_timestamps(self):
        gitdir = sh(self.w["有未提交"], "git", "rev-parse", "--absolute-git-dir")
        old = LATER - 40 * 86400
        for f in ("index", "HEAD"):
            os.utime(os.path.join(gitdir, f), (old, old))
        os.utime(os.path.join(self.w["有未提交"], "b.txt"), (old, old))  # 让 index 里的 stat 信息过期
        before = os.stat(os.path.join(gitdir, "index")).st_mtime
        self.list_json("--now", str(LATER))
        self.assertEqual(os.stat(os.path.join(gitdir, "index")).st_mtime, before)

    def test_report_text(self):
        rc, out, err = run_cli("list", self.root, "--no-gh", "--state-dir", self.state, "--now", str(LATER))
        self.assertEqual(rc, 0, err)
        self.assertIn("可安全删除：8 个，可回收", out)
        self.assertIn("需要看一眼：6 个", out)
        self.assertIn("中文 目录/功能一", out)
        self.assertIn("sweep --confirm", out)


class SweepTests(Fixture):
    def git_refs(self, path):
        return sh(path, "git", "for-each-ref", "--format=%(refname) %(objectname)")

    def test_sweep_needs_confirm_and_plan(self):
        rc, _, err = run_cli("sweep", "--state-dir", self.state)
        self.assertEqual(rc, 2)
        self.assertIn("--confirm", err)
        rc, _, err = run_cli("sweep", "--confirm", "--state-dir", self.state)
        self.assertEqual(rc, 2)
        self.assertIn("先跑 list", err)
        for p in self.w.values():
            if "目录丢了" not in p:
                self.assertTrue(os.path.isdir(p), p)

    def test_sweep_removes_only_safe(self):
        self.list_json("--now", str(LATER))
        remote_before = self.git_refs(self.remote)
        # list 之后、sweep 之前，有人在「同样env」里又改了东西：复核时必须跳过
        write(os.path.join(self.w["同样env"], "a.txt"), "list 之后改的\n")

        rc, out, err = run_cli("sweep", "--confirm", "--state-dir", self.state)
        self.assertEqual(rc, 0, err)
        print("\n" + out)

        removed = {n for n, p in self.w.items() if not os.path.isdir(p)}
        should_go = {n for n, t in EXPECT.items() if t == WS.SAFE} - {"同样env"}
        self.assertEqual(removed, should_go)
        self.assertIn("同样env", out.split("没删")[1])

        listed = {WS.norm(e["path"]) for e in WS.parse_worktrees(self.main)}
        for n in should_go:
            self.assertNotIn(WS.norm(self.w[n]), listed, n)
        for n, t in EXPECT.items():
            if n not in should_go:
                self.assertIn(WS.norm(self.w[n]), listed, n)

        branches = set(sh(self.main, "git", "for-each-ref", "--format=%(refname:short)", "refs/heads").split("\n"))
        for b in ("feat/normal", "feat/squash", "feat/squash2", "feat/rebase", "feat/gone", "功能/中文"):
            self.assertNotIn(b, branches)
        for b in ("main", "feat/dirty", "feat/untracked", "feat/unpushed", "feat/open", "feat/locked",
                  "feat/busy", "feat/env", "feat/sameenv", "feat/midrebase"):
            self.assertIn(b, branches)
        # 未提交、未推送的内容原样还在
        with open(os.path.join(self.w["有未提交"], "b.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "改了没提交\n")
        self.assertTrue(os.path.isfile(os.path.join(self.w["有未推送"], "u.txt")))
        # 远端一点没动
        self.assertEqual(self.git_refs(self.remote), remote_before)
        # 清单用一次就作废
        rc, _, _ = run_cli("sweep", "--confirm", "--state-dir", self.state)
        self.assertEqual(rc, 2)

    def test_skip_option(self):
        self.list_json("--now", str(LATER))
        rc, out, err = run_cli("sweep", "--confirm", "--state-dir", self.state, "--skip", "普通合并", "--only", "普通合并", "--only", "功能一")
        self.assertEqual(rc, 0, err)
        self.assertTrue(os.path.isdir(self.w["普通合并"]))
        self.assertFalse(os.path.isdir(self.w["中文路径"]))
        self.assertTrue(os.path.isdir(self.w["squash合并"]))


class UnitTests(unittest.TestCase):
    def test_lsof_unescape(self):
        self.assertEqual(WS.lsof_unescape(r"/tmp/\xe4\xb8\xad\xe6\x96\x87 dir"), "/tmp/中文 dir")
        self.assertEqual(WS.lsof_unescape("/plain/中文"), "/plain/中文")

    def base(self, **kw):
        w = {"is_main": False, "error": None, "locked": False, "lock_reason": "", "prunable": False,
             "occupied": [], "dirty": [], "merged": None, "ignored_unique": [], "pr": None,
             "unpushed": 0, "last_active": 0, "branch": "b", "in_progress": []}
        w.update(kw)
        return w

    def test_dirty_never_safe(self):
        for merged in (None, "提交已在默认分支里"):
            tier, _ = WS.classify(self.base(dirty=["x"], merged=merged), 10**9, 24, 7)
            self.assertNotEqual(tier, WS.SAFE)

    def test_in_progress_needs_look(self):
        tier, why = WS.classify(self.base(merged="x", in_progress=["rebase"]), 10**9, 24, 7)
        self.assertEqual(tier, WS.LOOK)
        self.assertIn("rebase", why[0])

    def test_pr_merged_but_extra_commits_needs_look(self):
        tier, why = WS.classify(self.base(pr={"number": 7, "state": "MERGED"}), 10**9, 24, 7)
        self.assertEqual(tier, WS.LOOK)
        self.assertIn("#7", why[0])

    def test_unknown_error_needs_look(self):
        tier, _ = WS.classify(self.base(error="boom", merged="x"), 10**9, 24, 7)
        self.assertEqual(tier, WS.LOOK)


if __name__ == "__main__":
    unittest.main()
