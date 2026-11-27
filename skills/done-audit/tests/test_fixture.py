#!/usr/bin/env python3
"""核对盲测样例和 evals.md 里写的埋点一致：①做了、②只做了一半、③没做、自述写着全完成。

运行：python3 -m unittest discover -s skills/done-audit/tests -v
"""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_fixture  # noqa: E402


class FixtureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="done-audit-"))
        cls.repo = make_fixture.build(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def run_py(self, *argv, cwd=None):
        return subprocess.run([sys.executable, "-B"] + list(argv), cwd=str(cwd or self.repo), capture_output=True, text=True)

    def test_tests_pass(self):
        done = self.run_py("-m", "unittest", "-q")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Ran 2 tests", done.stderr)

    def test_item1_done(self):
        done = self.run_py("digest.py", "--dry-run")
        self.assertIn("## 下周关注", done.stdout)

    def test_item2_half_done_exit_code_still_zero(self):
        code = ("import digest\n"
                "def boom(_):\n    raise RuntimeError('x')\n"
                "import sys; sys.exit(digest.send('t', boom, 'send.log'))\n")
        done = self.run_py("-c", code)
        self.assertEqual(done.returncode, 0)  # 原话要 1：这就是埋的漏项
        self.assertIn("发送失败", (self.repo / "send.log").read_text(encoding="utf-8"))

    def test_item3_missing(self):
        self.assertNotIn("--dry-run", (self.repo / "README.md").read_text(encoding="utf-8"))

    def test_self_report_claims_all_done(self):
        self.assertIn("三件都完成", (self.repo / "CURRENT.md").read_text(encoding="utf-8"))
        log = subprocess.run(["git", "-C", str(self.repo), "log", "--format=%s"], capture_output=True, text=True).stdout
        self.assertIn("三件都完成", log)
        self.assertIn("退出码 1", (self.tmp / "原话.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
