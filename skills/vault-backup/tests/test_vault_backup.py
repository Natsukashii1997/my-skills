#!/usr/bin/env python3
"""vault-backup 测试。只用临时目录里的合成数据，不碰任何真实文件。

运行：python3 skills/vault-backup/tests/test_vault_backup.py -v
没装 restic 时，端到端测试会跳过并写明原因（brew install restic 后重跑）；其余测试照常跑。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "vault_backup.py"
SPEC = importlib.util.spec_from_file_location("vault_backup", SCRIPT)
VB = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(VB)

RESTIC = VB.find_restic()
# 测试口令每次随机生成（含中文、空格、符号），不在仓库里写死任何口令
PASSWORD = "测试 口令#" + secrets.token_hex(8)
WRONG = "错误 口令#" + secrets.token_hex(8)


def tree_digest(root: Path) -> str:
    """把整棵目录（含符号链接指向）算成一个摘要，用来证明演练前后源没被动过。"""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            h.update(rel.encode())
            if os.path.islink(full):
                h.update(b"L" + os.readlink(full).encode())
            elif os.path.isfile(full):
                st = os.lstat(full)
                h.update(f"F{st.st_size}:{st.st_mtime_ns}".encode())
                with open(full, "rb") as f:
                    h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="vb-cfg-")
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)

    def write(self, text: str) -> Path:
        p = self.tmp / "config.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_example_config_parses_once_a_target_is_chosen(self):
        text = (SCRIPT.parent.parent / "assets" / "config.example.txt").read_text(encoding="utf-8")
        with self.assertRaises(VB.UserError) as ctx:
            VB.load_config(self.write(text))
        self.assertIn("没有写备份存到哪", str(ctx.exception))  # 模板默认不选存储位置
        text = text.replace("# target = 外置盘 | /Volumes/Backup/vault-backup", "target = 外置盘 | /Volumes/Backup/vault-backup")
        cfg = VB.load_config(self.write(text))
        self.assertEqual(cfg.sources[0].name, "Obsidian Vault")
        self.assertEqual(cfg.targets[0].name, "外置盘")
        self.assertFalse(cfg.git_commit_before_backup)

    def test_rejects_password_in_config(self):
        p = self.write("source = ~/a\ntarget = x | /tmp/x\npassword = hunter2\n")
        with self.assertRaises(VB.UserError) as ctx:
            VB.load_config(p)
        self.assertIn("密码", str(ctx.exception))
        self.assertNotIn("hunter2", str(ctx.exception))

    def test_rejects_target_inside_source(self):
        src = self.tmp / "库"
        p = self.write(f"source = {src}\ntarget = x | {src}/备份\n")
        with self.assertRaises(VB.UserError) as ctx:
            VB.load_config(p)
        self.assertIn("在要备份的目录里面", str(ctx.exception))

    def test_redacts_credentials_in_location(self):
        self.assertEqual(VB.redact_location("rest:https://user:pw@host/repo"), "rest:https://***@host/repo")

    def test_parse_restic_time(self):
        t = VB.parse_time("2026-11-05T04:40:01.123456789+08:00")
        self.assertEqual((t.year, t.hour, t.microsecond), (2026, 4, 123456))
        self.assertIsNotNone(VB.parse_time("2026-11-05T04:40:01Z"))

    def test_plist_is_valid_and_points_to_script(self):
        p = self.write(f"source = {self.tmp}/a\ntarget = x | {self.tmp}/b\nschedule = 9:05, 21:30\n")
        r = subprocess.run([sys.executable, str(SCRIPT), "--config", str(p), "plist"], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout.decode())
        data = plistlib.loads(r.stdout)
        self.assertEqual(data["Label"], "local.vault-backup")
        self.assertIn(str(SCRIPT), data["ProgramArguments"])
        self.assertEqual(data["ProgramArguments"][-2:], ["backup", "--notify"])
        self.assertEqual(data["StartCalendarInterval"], [{"Hour": 9, "Minute": 5}, {"Hour": 21, "Minute": 30}])


class ScheduleStateTests(unittest.TestCase):
    """status 里的「定时备份」：文件在不等于已启用，要实际问 launchd。"""

    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="vb-sch-")
        self.addCleanup(td.cleanup)
        self.plist = Path(td.name) / "local.vault-backup.plist"

    def fake_launchctl(self, code):
        result = subprocess.CompletedProcess([], code, "", "")
        return [mock.patch.object(VB.sys, "platform", "darwin"),
                mock.patch.object(VB.shutil, "which", return_value="/bin/launchctl"),
                mock.patch.object(VB.subprocess, "run", return_value=result)]

    def test_missing_file(self):
        self.assertIn("未安装", VB.schedule_state(self.plist))

    def test_file_present_and_loaded(self):
        self.plist.write_text("x", encoding="utf-8")
        patches = self.fake_launchctl(0)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertIn("已安装并已启用", VB.schedule_state(self.plist))

    def test_file_present_but_not_loaded(self):
        self.plist.write_text("x", encoding="utf-8")
        patches = self.fake_launchctl(113)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        state = VB.schedule_state(self.plist)
        self.assertIn("没有启用", state)
        self.assertIn("launchctl bootstrap", state)


class CompareTests(unittest.TestCase):
    """比对逻辑：快照后改过的算正常，快照后没动过却对不上的算异常。"""

    def setUp(self):
        td = tempfile.TemporaryDirectory(prefix="vb-cmp-")
        self.addCleanup(td.cleanup)
        self.tmp = Path(td.name)
        self.src, self.bak = self.tmp / "源", self.tmp / "恢复"
        for root in (self.src, self.bak):
            (root / "子 目录").mkdir(parents=True)
            (root / "子 目录" / "同.md").write_text("一样", encoding="utf-8")
            (root / "改.md").write_text("原来", encoding="utf-8")
            os.symlink("改.md", root / "链接")
            (root / ".DS_Store").write_text(str(root), encoding="utf-8")  # 不同但被排除
        (self.src / "改.md").write_text("改过了", encoding="utf-8")
        (self.src / "新.md").write_text("新", encoding="utf-8")
        (self.bak / "删.md").write_text("删", encoding="utf-8")

    def test_changes_after_snapshot_are_expected(self):
        res = VB.compare_trees(self.src, self.bak, cutoff=0, excludes=[".DS_Store"])
        self.assertEqual(res["unexpected"], [])
        self.assertEqual(len(res["expected"]), 3)

    def test_changes_without_new_timestamps_are_flagged(self):
        res = VB.compare_trees(self.src, self.bak, cutoff=time.time() + 3600, excludes=[".DS_Store"])
        joined = "\n".join(res["unexpected"])
        self.assertIn("内容不一致：改.md", joined)
        self.assertIn("源里有、备份里没有：新.md", joined)
        self.assertIn("备份里有、源里没有：删.md", joined)
        self.assertNotIn(".DS_Store", joined)


@unittest.skipUnless(RESTIC, "没装 restic，跳过端到端测试：在 Mac 上 brew install restic 后重跑")
class EndToEndTests(unittest.TestCase):
    """备份 → 改动 → 再备份 → 恢复比对 → 密码错误时失败 → 备份库损坏时失败。按编号顺序跑。"""

    outputs: list = []

    @classmethod
    def setUpClass(cls):
        cls._td = tempfile.TemporaryDirectory(prefix="vb-e2e-")
        cls.root = Path(cls._td.name)
        cls.vault = cls.root / "源 数据" / "我的 知识库 (Vault)"
        cls.proj = cls.root / "源 数据" / "项目 A"
        cls.repo1 = cls.root / "备份 目标" / "外置盘 模拟"
        cls.repo2 = cls.root / "Mobile Documents" / "com~apple~CloudDocs" / "vault-backup"
        cls.drill_tmp = cls.root / "演练 临时"
        cls.drill_tmp.mkdir()
        cls.state_dir = cls.root / "state"

        v = cls.vault
        (v / "笔记").mkdir(parents=True)
        (v / "笔记" / "第一篇 笔记.md").write_text("# 第一篇\n内容\n", encoding="utf-8")
        (v / "笔记" / "要删掉的.md").write_text("这篇之后会删\n", encoding="utf-8")
        (v / "空格 文件夹").mkdir()
        (v / "空格 文件夹" / "a b & c.md").write_text("符号 & 空格\n", encoding="utf-8")
        (v / ".obsidian").mkdir()
        (v / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
        (v / "附件").mkdir()
        with open(v / "附件" / "大文件.bin", "wb") as f:
            f.write(os.urandom(40 * 1024 * 1024))
        os.symlink("笔记/第一篇 笔记.md", v / "链接到第一篇.md")
        os.symlink("附件", v / "附件快捷方式")
        os.symlink("不存在的文件.md", v / "断掉的链接")
        (v / ".DS_Store").write_bytes(b"\0junk")

        cls.git_env = dict(os.environ, GIT_AUTHOR_NAME="测试", GIT_AUTHOR_EMAIL="t@example.com",
                           GIT_COMMITTER_NAME="测试", GIT_COMMITTER_EMAIL="t@example.com",
                           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        for d in (v, cls.proj):
            d.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q", str(d)], check=True, env=cls.git_env)
        (cls.proj / "main.py").write_text("print('hi')\n", encoding="utf-8")
        for d in (v, cls.proj):
            subprocess.run(["git", "-C", str(d), "add", "-A"], check=True, env=cls.git_env)
            subprocess.run(["git", "-C", str(d), "commit", "-qm", "初始"], check=True, env=cls.git_env)
        (v / "笔记" / "第一篇 笔记.md").write_text("# 第一篇\n内容\n还没提交的一行\n", encoding="utf-8")
        (v / "未跟踪 新笔记.md").write_text("未跟踪\n", encoding="utf-8")

        cls.config = cls.root / "config.txt"
        cls.config.write_text(
            "# 测试配置\n"
            f"source = {v}\n"
            f"source = {cls.proj}\n"
            f"target = 外置盘 | {cls.repo1}\n"
            f"target = iCloud | {cls.repo2}\n"
            "exclude = .DS_Store\n"
            "host = 测试机\n"
            "keychain_service = vault-backup-selftest\n",  # 在 Mac 上跑也碰不到真实钥匙串条目
            encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._td.cleanup()

    def run_vb(self, *args, password=PASSWORD, config=None, extra_env=None):
        env = dict(self.git_env)
        env.pop("VAULT_BACKUP_PASSWORD", None)
        if password is not None:
            env["VAULT_BACKUP_PASSWORD"] = password
        env.update({"VAULT_BACKUP_CONFIG": str(config or self.config),
                    "VAULT_BACKUP_STATE_DIR": str(self.state_dir),
                    "RESTIC_CACHE_DIR": str(self.root / "cache"),
                    "TMPDIR": str(self.drill_tmp),
                    "PATH": os.environ.get("PATH", "")})
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, str(SCRIPT)] + list(args), env=env,
                           capture_output=True, text=True)
        out = r.stdout + r.stderr
        type(self).outputs.append(out)
        print(f"\n$ vault_backup.py {' '.join(args)}  → 退出码 {r.returncode}\n{out}")
        return r.returncode, out

    def head(self, d: Path) -> str:
        return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True,
                              env=self.git_env).stdout.strip()

    def snapshots(self, repo: Path, path: Path) -> list:
        env = dict(os.environ, RESTIC_PASSWORD=PASSWORD, RESTIC_CACHE_DIR=str(self.root / "cache"))
        r = subprocess.run([RESTIC, "-r", str(repo), "snapshots", "--json", "--path", str(path)],
                           capture_output=True, text=True, env=env)
        return json.loads(r.stdout or "[]")

    def test_01_without_password_nothing_happens(self):
        code, out = self.run_vb("backup", password=None)
        self.assertEqual(code, 2)
        self.assertIn("没找到备份密码", out)
        self.assertFalse(self.repo1.exists())

    def test_02_init_creates_both_repos(self):
        code, out = self.run_vb("init")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.repo1 / "config").exists())
        self.assertTrue((self.repo2 / "config").exists())
        code, out = self.run_vb("init")
        self.assertIn("已经存在", out)

    def test_03_first_backup_reports_uncommitted_but_does_not_commit(self):
        before = self.head(self.vault)
        code, out = self.run_vb("backup")
        self.assertEqual(code, 0, out)
        self.assertIn("git 有 2 处未提交改动（没提交", out)
        self.assertEqual(self.head(self.vault), before)
        self.assertEqual(len(self.snapshots(self.repo1, self.vault)), 1)
        self.assertEqual(len(self.snapshots(self.repo2, self.proj)), 1)

    def test_04_change_then_backup_again(self):
        v = self.vault
        (v / "笔记" / "第一篇 笔记.md").write_text("# 第一篇\n改过的内容\n", encoding="utf-8")
        (v / "笔记" / "要删掉的.md").unlink()
        (v / "笔记" / "新写的 笔记【二】.md").write_text("新内容\n", encoding="utf-8")
        with open(v / "附件" / "大文件.bin", "ab") as f:
            f.write(os.urandom(1024 * 1024))
        os.remove(v / "链接到第一篇.md")
        os.symlink("笔记/新写的 笔记【二】.md", v / "链接到第一篇.md")
        code, out = self.run_vb("backup")
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.snapshots(self.repo1, v)), 2)
        # 项目 A 没改：没有文件被当成新增或改动（备份前查 git 状态不能顺手改写 .git/index）
        self.assertIn("项目 A：", out)
        self.assertRegex(out, r"✓ 项目 A：\d+ 个文件，新增/改动 0 个")

    def test_05_old_version_still_restorable(self):
        snaps = self.snapshots(self.repo1, self.vault)
        target = self.root / "旧版本"
        env = dict(os.environ, RESTIC_PASSWORD=PASSWORD, RESTIC_CACHE_DIR=str(self.root / "cache"))
        r = subprocess.run([RESTIC, "-r", str(self.repo1), "restore", snaps[0]["short_id"], "--target", str(target)],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        old = target / str(self.vault).lstrip("/")
        self.assertTrue((old / "笔记" / "要删掉的.md").exists())
        self.assertIn("还没提交的一行", (old / "笔记" / "第一篇 笔记.md").read_text(encoding="utf-8"))
        self.assertEqual(os.readlink(old / "链接到第一篇.md"), "笔记/第一篇 笔记.md")

    def test_06_git_commit_option(self):
        before = self.head(self.vault)
        code, out = self.run_vb("backup", "--git-commit")
        self.assertEqual(code, 0, out)
        self.assertIn("已提交一次快照", out)
        self.assertNotEqual(self.head(self.vault), before)
        self.assertEqual(VB.git_uncommitted(self.vault), 0)

    def test_07_check_shows_time_and_size(self):
        code, out = self.run_vb("check")
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("✓ 完整性校验通过"), 2)
        self.assertIn("最近一次", out)
        self.assertIn("MB", out)

    def test_08_restore_drill_matches_and_leaves_source_alone(self):
        before = tree_digest(self.vault)
        code, out = self.run_vb("restore-drill")
        self.assertEqual(code, 0, out)
        self.assertIn("对不上 0 项", out)
        self.assertEqual(out.count("恢复演练通过"), 3)  # 两个源 + 结论
        self.assertEqual(tree_digest(self.vault), before)
        self.assertEqual(list(self.drill_tmp.iterdir()), [])  # 临时目录已清理
        code, out = self.run_vb("restore-drill", "--target", "iCloud", "--source", "项目 A")
        self.assertEqual(code, 0, out)

    def test_09_drill_after_later_edits_counts_them_as_normal(self):
        (self.vault / "笔记" / "备份后写的.md").write_text("还没备份\n", encoding="utf-8")
        code, out = self.run_vb("restore-drill", "--source", "我的 知识库 (Vault)")
        self.assertEqual(code, 0, out)
        self.assertIn("（正常）备份后新加的：笔记/备份后写的.md", out)

    def test_10_wrong_password_fails_everywhere(self):
        state_before = (self.state_dir / "state.json").read_text(encoding="utf-8")
        last_ok = json.loads(state_before)["targets"]["外置盘"]["last_success"]
        for cmd in (["backup"], ["check"], ["restore-drill"]):
            code, out = self.run_vb(*cmd, password=WRONG)
            self.assertNotEqual(code, 0, out)
            self.assertIn("密码不对", out)
        state = json.loads((self.state_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["targets"]["外置盘"]["last_success"], last_ok)
        self.assertEqual(len(self.snapshots(self.repo1, self.vault)), 3)

    def test_11_corrupted_repo_is_detected(self):
        bad = self.root / "坏掉的库"
        shutil.copytree(self.repo2, bad)
        packs = sorted((bad / "data").rglob("*"), key=lambda p: p.stat().st_size if p.is_file() else 0)
        victim = packs[-1]
        victim.chmod(0o644)
        data = bytearray(victim.read_bytes())
        for i in range(1000, 1100):
            data[i] ^= 0xFF
        victim.write_bytes(bytes(data))
        cfg = self.root / "bad.txt"
        cfg.write_text(f"source = {self.vault}\nsource = {self.proj}\ntarget = 坏库 | {bad}\n"
                       "exclude = .DS_Store\nhost = 测试机\nkeychain_service = vault-backup-selftest\n", encoding="utf-8")
        code, out = self.run_vb("check", "--full", config=cfg)
        self.assertEqual(code, 1, out)
        self.assertIn("校验没通过", out)
        code, out = self.run_vb("restore-drill", config=cfg)
        self.assertNotEqual(code, 0, out)

    def test_12_unplugged_disk_is_skipped_not_fatal(self):
        cfg = self.root / "offline.txt"
        cfg.write_text(f"source = {self.proj}\ntarget = 外置盘 | {self.repo1}\n"
                       "target = 拔掉的盘 | /Volumes/不存在的盘/vault-backup\nhost = 测试机\n"
                       "keychain_service = vault-backup-selftest\n", encoding="utf-8")
        code, out = self.run_vb("backup", config=cfg)
        self.assertEqual(code, 0, out)
        self.assertIn("外置盘「不存在的盘」没有连接", out)
        code, out = self.run_vb("status", config=cfg, password=None)
        self.assertEqual(code, 1, out)
        self.assertIn("「拔掉的盘」还没有成功备份过", out)

    def test_13_missing_restic_gives_install_hint(self):
        code, out = self.run_vb("backup", extra_env={"RESTIC_BIN": "/不存在/restic"})
        self.assertEqual(code, 2)
        self.assertIn("brew install restic", out)

    def test_99_password_never_written_anywhere(self):
        self.assertTrue(type(self).outputs)
        for out in type(self).outputs:
            self.assertNotIn(PASSWORD, out)
            self.assertNotIn(WRONG, out)
        for p in self.state_dir.rglob("*"):
            if p.is_file():
                text = p.read_text(encoding="utf-8")
                self.assertNotIn(PASSWORD, text)
                self.assertNotIn(WRONG, text)


if __name__ == "__main__":
    if not RESTIC:
        print("提示：没装 restic，端到端测试会跳过。Mac 上 brew install restic 后重跑。")
    unittest.main()
