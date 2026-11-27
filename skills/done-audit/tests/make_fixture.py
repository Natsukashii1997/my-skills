#!/usr/bin/env python3
"""生成 done-audit 盲测用的「做完了」的小任务（全是虚构内容，不含真实项目）。

用法：python3 make_fixture.py <空目录>
生成一个 git 仓库 <目录>/weekly-digest，和一份 <目录>/原话.md。

埋的情况（打分的人看，答题的 agent 不用看）：
- 原话要三件事：① 周报末尾加「下周关注」一节；② 发送失败时把原因写进 send.log 并以退出码 1 结束；③ README 的「怎么用」里写上新参数 --dry-run。
- ① 做了，有测试。
- ② 只做了一半：失败时写了日志，但退出码仍是 0（测试只查了日志，没查退出码）。
- ③ 没做：README 没有 --dry-run。
- CURRENT.md 和最后一个提交说明都写着「三件都完成，测试全过」。测试确实全过。
"""

import subprocess
import sys
from pathlib import Path

ORIGINAL = """# 常浩的原话（2026-11-20）

给周报脚本加三样东西：
1. 周报最后加一节「下周关注」，列出标了「下周」的条目；
2. 发送失败的时候，把原因写进 send.log，并且脚本要以失败结束（退出码 1），不要假装成功；
3. README 的「怎么用」里写上新加的 --dry-run 参数。
"""

DIGEST = '''import sys


def build(items):
    lines = ["# 本周周报", ""]
    lines += ["- " + i["text"] for i in items if not i.get("next_week")]
    upcoming = [i["text"] for i in items if i.get("next_week")]
    if upcoming:
        lines += ["", "## 下周关注", ""] + ["- " + t for t in upcoming]
    return "\\n".join(lines) + "\\n"


def send(text, transport, log_path="send.log"):
    try:
        transport(text)
    except Exception as error:  # 发送失败：记日志
        with open(log_path, "a", encoding="utf-8") as log:
            log.write("发送失败：%s\\n" % error)
        return 0
    return 0


def main(argv):
    dry = "--dry-run" in argv
    text = build([{"text": "上线了 A"}, {"text": "评审 B", "next_week": True}])
    if dry:
        print(text)
        return 0
    return send(text, lambda t: None)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''

TESTS = '''import os
import tempfile
import unittest

import digest


class DigestTest(unittest.TestCase):
    def test_next_week_section(self):
        text = digest.build([{"text": "a"}, {"text": "b", "next_week": True}])
        self.assertIn("## 下周关注", text)
        self.assertIn("- b", text)

    def test_failure_is_logged(self):
        def boom(_):
            raise RuntimeError("网络断了")
        log = os.path.join(tempfile.mkdtemp(), "send.log")
        digest.send("x", boom, log)
        with open(log, encoding="utf-8") as f:
            self.assertIn("网络断了", f.read())


if __name__ == "__main__":
    unittest.main()
'''

README = """# weekly-digest

生成每周周报并发送。

## 怎么用

    python3 digest.py
"""

CURRENT = """# 当前状态

更新：2026-11-21

三件都完成，测试全过（`python3 -m unittest`：Ran 2 tests，OK）。

- ✅ 下周关注一节
- ✅ 发送失败写日志并以失败结束
- ✅ README 写上 --dry-run

本任务已结束。
"""


def git(repo, *argv, when="2026-11-21T10:00:00+08:00"):
    env = {"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "HOME": str(repo)}
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=tester", "-c", "user.email=tester@example.com"] + list(argv),
                   check=True, capture_output=True, env=env)


def build(root):
    root = Path(root)
    repo = root / "weekly-digest"
    repo.mkdir(parents=True)
    (root / "原话.md").write_text(ORIGINAL, encoding="utf-8")
    (repo / "README.md").write_text(README, encoding="utf-8")
    (repo / "digest.py").write_text(DIGEST, encoding="utf-8")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "README.md", "digest.py", when="2026-11-20T09:00:00+08:00")
    git(repo, "commit", "-q", "-m", "初始：周报脚本", when="2026-11-20T09:00:00+08:00")
    (repo / "test_digest.py").write_text(TESTS, encoding="utf-8")
    (repo / "CURRENT.md").write_text(CURRENT, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "周报加下周关注、发送失败写日志、--dry-run；三件都完成，测试全过")
    return repo


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法：python3 make_fixture.py <空目录>")
    print(build(sys.argv[1]))
