#!/usr/bin/env python3
"""worktree-sweep：找出多个仓库里堆积的 git worktree，分三档给清理建议；确认后只删「可安全删除」档。

用法：
  worktree_sweep.py list [根目录 ...] [--fetch] [--no-gh] [--no-size] [--json]
        默认动作。只读：扫描、分档、算大小，打印报告，并把「可安全删除」清单存成计划文件。
        不给根目录时用 ~/Documents/ChatGPT/个人/work。
  worktree_sweep.py show <worktree 路径>
        看一个 worktree 的细节：哪些文件没提交、哪些提交没推送、哪些 git 不管的本地文件只有它有。
  worktree_sweep.py sweep --confirm [--skip 路径或名字 ...] [--only 路径或名字 ...]
        只删上一次 list 计划里、此刻复核仍属「可安全删除」的 worktree。
        用 `git worktree remove`（不加 --force）；分支只在已合并时删本地分支；从不碰远端。

只用 Python 3.9+ 标准库和系统自带的 git / du / lsof；gh 有就查 PR，没有就跳过。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata

SAFE, LOOK, KEEP = "可安全删除", "需要看一眼", "保留"
TIERS = (SAFE, LOOK, KEEP)
DEFAULT_ROOT = "~/Documents/ChatGPT/个人/work"
DEFAULT_STATE = "~/.cache/worktree-sweep"
PLAN_TTL_HOURS = 24

# 找仓库时不往里走的目录
WALK_SKIP = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", "target", "Library"}
# git 不管的本地文件里，这些是能重新生成的，删了不可惜
REGEN_NAMES = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache", ".vite",
    "coverage", ".nyc_output", "target", ".gradle", ".DS_Store", "Thumbs.db", ".eslintcache",
    "test-results", "playwright-report", "blob-report",  # Playwright 等测试工具每次跑都会重写
}
# 各项目自己声明的「能重新生成」的目录，放在 skill 目录的 regen.json（见 SKILL.md「项目自己的生成目录」）
REGEN_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "regen.json")
REGEN_SUFFIX = (".pyc", ".pyo", ".tsbuildinfo", ".log")
# worktree 里做到一半的操作：工作区可能是干净的，但删了就丢了
IN_PROGRESS = (("rebase-merge", "rebase"), ("rebase-apply", "rebase / am"), ("MERGE_HEAD", "合并"),
               ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"))

# 沿用用户自己的环境：fetch 和 gh 用的是已经登录好的 git / gh，脚本本身不读、不存任何凭据
GIT_ENV = dict(os.environ)
GIT_ENV.update({
    "GIT_OPTIONAL_LOCKS": "0",   # 不让 git status 顺手改 index，免得把「最后改动时间」刷新、也不和别的会话抢锁
    "GIT_TERMINAL_PROMPT": "0",  # fetch 要密码时直接失败，不卡住
    "GIT_PAGER": "cat",
    "LC_ALL": "C",               # git 的提示用英文，方便解析；路径按字节原样输出
})


# ---------- 小工具 ----------

def norm(p):
    """统一路径：展开 ~、解析软链接、Unicode 归一（macOS 的中文路径可能是分解形式）。"""
    return unicodedata.normalize("NFC", os.path.realpath(os.path.expanduser(p)))


def under(path, parent):
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def run(cmd, cwd=None, input_text=None, timeout=120, env=None):
    try:
        p = subprocess.run(
            cmd, cwd=cwd, env=env or GIT_ENV, capture_output=True, timeout=timeout,
            input=input_text.encode("utf-8", "surrogateescape") if input_text is not None else None,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout.decode("utf-8", "surrogateescape"), p.stderr.decode("utf-8", "surrogateescape")


def git(cwd, *args, **kw):
    return run(["git", "-c", "core.quotePath=false", *args], cwd=cwd, **kw)


def ref_exists(cwd, ref):
    return git(cwd, "show-ref", "--verify", "--quiet", ref)[0] == 0


def human_size(kb):
    if kb is None:
        return "?"
    size = float(kb)
    for unit in ("KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("KB", "MB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{kb} KB"


def human_age(seconds):
    if seconds is None:
        return "?"
    seconds = max(0, seconds)
    if seconds < 3600:
        return "1 小时内"
    if seconds < 86400:
        return f"{int(seconds // 3600)} 小时前"
    return f"{int(seconds // 86400)} 天前"


def short_home(p):
    home = norm("~")
    return "~" + p[len(home):] if under(p, home) else p


# ---------- 找仓库 ----------

def common_dir(d):
    """仓库共享的 .git 目录（主工作区和所有 worktree 都指向同一个）。"""
    rc, out, _ = git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc != 0:  # git < 2.31
        rc, out, _ = git(d, "rev-parse", "--git-common-dir")
        if rc != 0:
            return None
        out = os.path.join(d, out.strip())
    return norm(out.strip())


def find_repos(roots, max_depth=4):
    """返回 {共享 .git 目录: 主工作区路径}。worktree 本身不往里走，靠 `git worktree list` 列出来。"""
    repos = {}

    def add(d):
        common = common_dir(d)
        if not common or common in repos:
            return
        entries = parse_worktrees(d)
        if entries and not entries[0]["bare"]:
            repos[common] = norm(entries[0]["path"])
        elif entries:  # 裸仓库：没有主工作区
            repos[common] = None

    for root in roots:
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            print(f"跳过：{root} 不是目录", file=sys.stderr)
            continue
        stack = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            dotgit = os.path.join(d, ".git")
            if os.path.lexists(dotgit):
                add(d)
                if not os.path.isdir(dotgit):
                    continue  # 这是某个 worktree（或子模块），不往里走
            if depth >= max_depth:
                continue
            try:
                with os.scandir(d) as it:
                    subs = [e.path for e in it if e.is_dir(follow_symlinks=False)
                            and not e.name.startswith(".") and e.name not in WALK_SKIP]
            except OSError:
                continue
            stack.extend((s, depth + 1) for s in sorted(subs, reverse=True))
    return repos


def parse_worktrees(cwd):
    rc, out, _ = git(cwd, "worktree", "list", "--porcelain", "-z")
    sep = "\0"
    if rc != 0:  # 老版本 git 没有 -z
        rc, out, _ = git(cwd, "worktree", "list", "--porcelain")
        sep = "\n"
    if rc != 0:
        return []
    entries, cur = [], None
    for line in out.split(sep):
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):], "head": None, "branch": None, "bare": False,
                   "detached": False, "locked": False, "lock_reason": "", "prunable": False}
            entries.append(cur)
        elif cur is None:
            continue
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            ref = line[7:]
            cur["branch"] = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
        elif line == "bare":
            cur["bare"] = True
        elif line == "detached":
            cur["detached"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
            cur["lock_reason"] = line[len("locked"):].strip()
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return entries


# ---------- 仓库级信息 ----------

def default_branch(main):
    name = None
    rc, out, _ = git(main, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if rc == 0 and "/" in out.strip():
        name = out.strip().split("/", 1)[1]
    if not name:
        for cand in ("main", "master"):
            if ref_exists(main, f"refs/remotes/origin/{cand}") or ref_exists(main, f"refs/heads/{cand}"):
                name = cand
                break
    if not name:
        rc, out, _ = git(main, "symbolic-ref", "-q", "--short", "HEAD")
        name = out.strip() if rc == 0 else None
    refs = []
    if name:
        refs = [r for r in (f"refs/remotes/origin/{name}", f"refs/heads/{name}") if ref_exists(main, r)]
    return name, refs


def gh_prs(main):
    """{分支名: {number, state, url}}；gh 不在、没登录、不是 GitHub 仓库时返回 None。"""
    if not shutil.which("gh"):
        return None
    rc, out, _ = run(["gh", "pr", "list", "--state", "all", "--limit", "300",
                      "--json", "number,state,headRefName,url"], cwd=main, timeout=40, env=dict(os.environ))
    if rc != 0:
        return None
    try:
        items = json.loads(out or "[]")
    except ValueError:
        return None
    prs = {}
    for it in sorted(items, key=lambda x: x.get("number", 0)):
        prs[it.get("headRefName")] = {"number": it.get("number"), "state": it.get("state"), "url": it.get("url")}
    return prs


def lsof_unescape(text):
    """lsof 把非 ASCII 字节写成 \\xNN（中文路径会这样），还原成正常字符串。"""
    if "\\" not in text:
        return text
    out, i = bytearray(), 0
    simple = {"n": b"\n", "t": b"\t", "r": b"\r", "b": b"\b", "f": b"\f", "\\": b"\\"}
    while i < len(text):
        c = text[i]
        if c == "\\" and text[i + 1:i + 2] == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", text[i + 2:i + 4] or ""):
            out.append(int(text[i + 2:i + 4], 16))
            i += 4
        elif c == "\\" and text[i + 1:i + 2] in simple:
            out += simple[text[i + 1]]
            i += 2
        else:
            out += c.encode("utf-8", "surrogateescape")
            i += 1
    return out.decode("utf-8", "surrogateescape")


def process_cwds():
    """[(pid, 命令名, 当前目录)]；没有 lsof 时返回 None。"""
    if not shutil.which("lsof"):
        return None
    rc, out, _ = run(["lsof", "-n", "-w", "-d", "cwd", "-Fpcn"], timeout=60)
    if rc not in (0, 1) or not out:
        return None
    res, pid, cmd = [], None, ""
    me = os.getpid()
    for line in out.splitlines():
        if line.startswith("p"):
            pid, cmd = int(line[1:]), ""
        elif line.startswith("c"):
            cmd = line[1:]
        elif line.startswith("n") and pid is not None and pid != me:
            res.append((pid, cmd, unicodedata.normalize("NFC", lsof_unescape(line[1:]))))
    return res


def fetch(main):
    rc, out, _ = git(main, "remote")
    if "origin" not in out.split():
        return "没有 origin，未拉取"
    rc, _, err = git(main, "fetch", "--prune", "--quiet", "origin", timeout=120)
    return None if rc == 0 else f"拉取失败：{err.strip().splitlines()[-1] if err.strip() else rc}"


# ---------- 单个 worktree ----------

def merged_how(cwd, head, refs):
    """分支内容是否已进默认分支。返回说明文字；没合并返回 None。"""
    for d in refs:
        if git(cwd, "merge-base", "--is-ancestor", head, d)[0] == 0:
            return "提交已在默认分支里"
    for d in refs:
        rc, out, _ = git(cwd, "cherry", d, head)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        if rc == 0 and lines and all(ln.startswith("-") for ln in lines):
            return "变基合并（每个提交都已在默认分支）"
        rc, base, _ = git(cwd, "merge-base", d, head)
        if rc != 0:
            continue
        base = base.strip()
        rc, ch, _ = git(cwd, "diff", "--name-only", "-z", "--no-renames", base, head)
        if rc != 0:
            continue
        changed = {p for p in ch.split("\0") if p}
        if not changed:
            return "分支没有净改动"
        rc, df, _ = git(cwd, "diff", "--name-only", "-z", "--no-renames", head, d)
        if rc == 0 and not (changed & {p for p in df.split("\0") if p}):
            return "squash 合并（改过的文件在默认分支里一模一样）"
        rc, patch, _ = git(cwd, "diff", base, head)
        rc2, pid, _ = git(cwd, "patch-id", "--stable", input_text=patch)
        mine = pid.split()[0] if rc == 0 and rc2 == 0 and pid.split() else None
        if mine:
            rc, logp, _ = git(cwd, "log", "-p", "--no-merges", "--max-count=2000", f"{base}..{d}")
            rc2, pids, _ = git(cwd, "patch-id", "--stable", input_text=logp)
            if rc == 0 and rc2 == 0 and any(line.split()[:1] == [mine] for line in pids.splitlines()):
                return "squash 合并（默认分支里有同样改动的提交）"
    return None


def status(wt):
    """返回 (未提交/未跟踪的路径列表, git 忽略的路径列表)。"""
    rc, out, err = git(wt, "status", "--porcelain=v1", "-z", "--untracked-files=normal", "--ignored=traditional")
    if rc != 0:
        raise RuntimeError(f"git status 失败：{err.strip()}")
    dirty, ignored = [], []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        f = fields[i]
        i += 1
        if len(f) < 4:
            continue
        xy, path = f[:2], f[3:]
        if xy == "!!":
            ignored.append(path)
        else:
            dirty.append(path)
            if xy[0] in "RC":
                i += 1  # -z 下改名记录后面跟着旧路径
    return dirty, ignored


def load_regen(path):
    """读项目声明的生成目录。文件不存在就当没有；格式不对直接报错，免得悄悄放宽删除条件。"""
    empty = {"names": set(), "paths": {}}
    if not path or not os.path.exists(path):
        return empty
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    names = data.get("names", [])
    paths = data.get("paths", {})
    if not isinstance(names, list) or not isinstance(paths, dict) \
            or not all(isinstance(v, list) for v in paths.values()):
        raise ValueError(f"{path} 格式不对：names 要是列表，paths 要是「仓库名: [相对路径, …]」")
    clean = {}
    for repo, items in paths.items():
        rels = []
        for raw in items:
            p = str(raw).strip()
            if os.path.isabs(p) or p.startswith("~"):
                raise ValueError(f"{path}：{repo} 里的「{p}」要写成仓库里的相对路径")
            p = p.strip("/")
            if not p or "/../" in f"/{p}/" or p == "..":
                raise ValueError(f"{path}：{repo} 里的「{p}」要写成仓库里的相对路径")
            rels.append(p)
        clean[repo] = rels
    return {"names": {str(n) for n in names}, "paths": clean}


def is_regen(rel, extra_names=()):
    name = rel.rstrip("/").split("/")[-1]
    return name in REGEN_NAMES or name in extra_names or name.endswith(REGEN_SUFFIX)


def declared_regen(rel, declared):
    """rel 是否落在项目声明的生成目录里（等于它或在它下面）。"""
    r = rel.rstrip("/")
    return next((d for d in declared if r == d or r.startswith(d + "/")), None)


def same_content(a, b, budget, extra_names=()):
    if os.path.islink(a):
        return os.path.islink(b) and os.readlink(a) == os.readlink(b)
    if os.path.isfile(a):
        return os.path.isfile(b) and not os.path.islink(b) and filecmp.cmp(a, b, shallow=False)
    if os.path.isdir(a):
        for dp, dns, fns in os.walk(a):
            dns[:] = [x for x in dns if x not in REGEN_NAMES and x not in extra_names]
            for f in fns:
                if is_regen(f, extra_names):
                    continue
                budget[0] -= 1
                if budget[0] < 0:
                    return False
                fa = os.path.join(dp, f)
                if not same_content(fa, os.path.join(b, os.path.relpath(fa, a)), budget, extra_names):
                    return False
        return True
    return True


def ignored_unique(wt, main, ignored, extra_names=(), declared=()):
    """git 不管、又不能重新生成、主工作区里也没有同样一份的本地文件（例如单独改过的 .env）。

    返回 (这类文件, 按项目声明当作可重新生成而略过的目录)。
    """
    res, skipped = [], []
    for rel in ignored:
        if is_regen(rel, extra_names):
            continue
        d = declared_regen(rel, declared)
        if d:
            skipped.append(d)
            continue
        r = rel.rstrip("/")
        if not same_content(os.path.join(wt, r), os.path.join(main, r) if main else "", [500], extra_names):
            res.append(rel)
    return res, sorted(set(skipped))


def last_active(wt, gitdir, head, dirty):
    ts = []
    rc, out, _ = git(wt if os.path.isdir(wt) else gitdir, "log", "-1", "--format=%ct", head)
    if rc == 0 and out.strip().isdigit():
        ts.append(int(out.strip()))
    for f in ("index", "HEAD", os.path.join("logs", "HEAD")):
        try:
            ts.append(os.stat(os.path.join(gitdir, f)).st_mtime)
        except OSError:
            pass
    for rel in dirty[:300]:
        try:
            ts.append(os.lstat(os.path.join(wt, rel.rstrip("/"))).st_mtime)
        except OSError:
            pass
    return max(ts) if ts else None


def remote_state(main, branch):
    if not branch:
        return "无分支（detached）"
    rc, out, _ = git(main, "for-each-ref", "--format=%(upstream:short)%00%(upstream:track)", f"refs/heads/{branch}")
    up, _, track = out.strip().partition("\0")
    if up:
        return "远端分支已删" if "gone" in track else "远端分支还在"
    return "远端有同名分支" if ref_exists(main, f"refs/remotes/origin/{branch}") else "远端没有这个分支"


def analyze(repo, e, ctx):
    """收集一个 worktree 的事实；分档交给 classify。"""
    main, refs = repo["main"], repo["default_refs"]
    path = norm(e["path"])
    w = {
        "repo": repo["name"], "repo_main": main, "common": repo["common"], "path": path,
        "is_main": bool(main) and path == main, "branch": e["branch"], "head": e["head"],
        "locked": e["locked"], "lock_reason": e["lock_reason"],
        "prunable": e["prunable"] or not os.path.isdir(path),
        "dirty": [], "unpushed": 0, "merged": None, "remote": None, "pr": None,
        "occupied": [], "ignored_unique": [], "regen_declared": [], "in_progress": [], "last_active": None,
        "size_kb": None,
        "error": None,
    }
    if w["is_main"]:
        return w
    try:
        cwd = main or repo["common"]
        if e["head"]:
            w["merged"] = merged_how(cwd, e["head"], refs)
            rc, out, _ = git(cwd, "rev-list", "--count", e["head"], "--not", "--remotes", *refs)
            w["unpushed"] = int(out.strip()) if rc == 0 and out.strip().isdigit() else 0
        w["remote"] = remote_state(cwd, e["branch"])
        prs = repo.get("prs")
        if prs is not None and e["branch"]:
            w["pr"] = prs.get(e["branch"])
        if w["prunable"]:
            return w
        gitdir_rc, gitdir, _ = git(path, "rev-parse", "--absolute-git-dir")
        gitdir = gitdir.strip() if gitdir_rc == 0 else ""
        w["in_progress"] = [label for name, label in IN_PROGRESS
                            if gitdir and os.path.exists(os.path.join(gitdir, name))]
        dirty, ignored = status(path)
        w["dirty"] = dirty
        w["last_active"] = last_active(path, gitdir, e["head"], dirty)
        if w["merged"] and not dirty:
            regen = ctx.get("regen") or {"names": set(), "paths": {}}
            w["ignored_unique"], w["regen_declared"] = ignored_unique(
                path, main, ignored, regen["names"], regen["paths"].get(repo["name"], []))
        cwds = ctx.get("cwds")
        if cwds:
            w["occupied"] = sorted({f"{cmd}（pid {pid}）" for pid, cmd, d in cwds if under(d, path)})
    except Exception as ex:  # 查不清的一律不建议删
        w["error"] = str(ex)
    return w


def classify(w, now, grace_hours, stale_days):
    """分档。顺序就是优先级：越靠前的条件越能否决删除。"""
    age = None if w["last_active"] is None else now - w["last_active"]
    recent = age is not None and age < stale_days * 86400
    fresh = age is not None and age < grace_hours * 3600
    idle = f"{int(age // 86400)} 天没动" if age is not None else "查不到最后改动时间"
    br = w["branch"] or "detached"

    if w["is_main"]:
        return KEEP, ["主工作区（仓库本体，不动）"]
    if w["error"]:
        return LOOK, [f"有项没查清：{w['error']}"]
    if w["locked"]:
        return KEEP, ["被锁定" + (f"（{w['lock_reason']}）" if w["lock_reason"] else "")]
    if w["prunable"]:
        note = ["目录已经不在了，只剩 git 里的一条登记"]
        note.append(f"分支 {br} 已合并，会一起删" if w["merged"] and w["branch"] else f"分支 {br} 留着不动")
        return SAFE, note
    if w["occupied"]:
        return KEEP, ["有程序正在这个目录里运行：" + "、".join(w["occupied"][:3])]
    if w.get("in_progress"):
        return LOOK, ["有做到一半的 " + "、".join(w["in_progress"]) + "，删了就丢了"]
    if w["dirty"]:
        r = f"{len(w['dirty'])} 个文件改了没提交"
        return (KEEP, [r, "近期活跃"]) if recent else (LOOK, [r, idle])
    if w["merged"]:
        if w["ignored_unique"]:
            shown = "、".join(w["ignored_unique"][:3]) + (" 等" if len(w["ignored_unique"]) > 3 else "")
            return LOOK, [f"已合并，但有 git 不管、主目录里也没有同样一份的本地文件：{shown}"]
        if fresh:
            return KEEP, [f"已合并，但 {grace_hours} 小时内还有动静，可能有会话在用，先留着"]
        note = [f"已合并：{w['merged']}"]
        if w.get("regen_declared"):
            note.append("按 regen.json 当作可重新生成：" + "、".join(w["regen_declared"][:3]))
        return SAFE, note
    if w["pr"] and w["pr"].get("state") == "MERGED":
        return LOOK, [f"PR #{w['pr']['number']} 已合并，但这里还有没进默认分支的改动（合并后又改过，或该先 --fetch）"]
    if w["unpushed"]:
        r = f"{w['unpushed']} 个提交没推到远端"
        return (KEEP, [r, "近期活跃"]) if recent else (LOOK, [r, idle])
    if recent:
        return KEEP, ["分支没合并，近期活跃"]
    return LOOK, [f"分支没合并，{idle}（提交都已推到远端）"]


def du_kb(path):
    rc, out, _ = run(["du", "-sk", path], timeout=600)
    try:
        return int(out.split()[0])
    except (ValueError, IndexError):
        return None


# ---------- 扫描 ----------

def scan(repos, opts, now):
    cwds = None if opts.no_lsof else process_cwds()
    ctx = {"cwds": cwds, "regen": load_regen(getattr(opts, "regen_config", None) or REGEN_CONFIG)}
    notes = []
    if cwds is None:
        notes.append("没查「是否有程序正在用」（找不到 lsof 或已关闭）")

    repo_infos = []
    for common, main in sorted(repos.items(), key=lambda kv: kv[1] or kv[0]):
        cwd = main or common
        info = {"common": common, "main": main,
                "name": os.path.basename(main) if main else os.path.basename(common.rstrip("/"))}
        if getattr(opts, "fetch", False):
            msg = fetch(cwd)
            if msg:
                notes.append(f"{info['name']}：{msg}")
        info["default_name"], info["default_refs"] = default_branch(cwd)
        if not info["default_refs"]:
            notes.append(f"{info['name']}：找不到默认分支，所有 worktree 都不会判为已合并")
        info["prs"] = None if getattr(opts, "no_gh", True) else gh_prs(cwd)
        info["entries"] = [e for e in parse_worktrees(cwd) if not e["bare"]]
        repo_infos.append(info)
    if not getattr(opts, "no_gh", True) and all(r["prs"] is None for r in repo_infos):
        notes.append("没查 PR（没装 gh、没登录，或不是 GitHub 仓库）")

    jobs = [(r, e) for r in repo_infos for e in r["entries"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda job: analyze(job[0], job[1], ctx), jobs))
    for w in items:
        w["tier"], w["reasons"] = classify(w, now, opts.grace_hours, opts.stale_days)
    if not getattr(opts, "no_size", False):
        todo = [w for w in items if not w["is_main"] and not w["prunable"]]
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            for w, kb in zip(todo, pool.map(lambda x: du_kb(x["path"]), todo)):
                w["size_kb"] = kb
    for w in items:
        if w["prunable"]:
            w["size_kb"] = 0
    return repo_infos, items, notes


# ---------- 报告 ----------

def display_path(w):
    if w["repo_main"] and under(w["path"], w["repo_main"]):
        return os.path.relpath(w["path"], w["repo_main"])
    return short_home(w["path"])


def report(roots, repo_infos, items, notes, now, opts, plan_path):
    lines = []
    stamp = dt.datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")
    linked = [w for w in items if not w["is_main"]]
    lines.append(f"worktree 清理报告　{stamp}")
    lines.append("扫描：" + "、".join(short_home(norm(r)) for r in roots))
    with_wt = [r for r in repo_infos if len(r["entries"]) > 1]
    lines.append(f"找到 {len(repo_infos)} 个仓库，其中 {len(with_wt)} 个有 worktree，共 {len(linked)} 个 worktree（不含主工作区）")
    lines.append("")

    def total(tier):
        ws = [w for w in linked if w["tier"] == tier]
        kb = sum(w["size_kb"] or 0 for w in ws)
        return ws, kb

    for tier in TIERS:
        ws, kb = total(tier)
        extra = f"，可回收 {human_size(kb)}" if tier == SAFE else (f"，占 {human_size(kb)}" if ws else "")
        lines.append(f"  {tier}：{len(ws)} 个{extra if not opts.no_size else ''}")
    lines.append("")

    for tier in TIERS:
        ws = [w for w in items if w["tier"] == tier and (not w["is_main"] or opts.show_main)]
        if not ws:
            continue
        lines.append(f"━━ {tier}（{len(ws)} 个）━━")
        by_repo = {}
        for w in ws:
            by_repo.setdefault(w["repo"], []).append(w)
        for repo, rws in sorted(by_repo.items()):
            lines.append(f"{repo}（{len(rws)} 个）")
            for w in sorted(rws, key=lambda x: -(x["size_kb"] or 0)):
                bits = [display_path(w), f"分支 {w['branch'] or 'detached'}"]
                bits.append("；".join(w["reasons"]))
                if w["pr"]:
                    bits.append(f"PR #{w['pr']['number']} {pr_state_cn(w['pr']['state'])}")
                if w["remote"] and w["branch"] and not w["is_main"]:
                    bits.append(w["remote"])
                if w["last_active"] is not None and not w["prunable"]:
                    bits.append("最后改动 " + human_age(now - w["last_active"]))
                if not opts.no_size and not w["is_main"]:
                    bits.append(human_size(w["size_kb"]))
                lines.append("  · " + "　".join(bits))
        lines.append("")

    if notes:
        lines.append("说明：")
        lines.extend("  - " + n for n in notes)
        lines.append("")
    safe = [w for w in linked if w["tier"] == SAFE]
    if safe and plan_path:
        lines.append(f"清单已存到 {short_home(plan_path)}（{PLAN_TTL_HOURS} 小时内有效）。")
        lines.append(f"确认后执行 sweep --confirm：只删上面「{SAFE}」的 {len(safe)} 个，删前逐个再复核。")
    elif not safe:
        lines.append(f"没有「{SAFE}」的 worktree。")
    return "\n".join(lines)


def pr_state_cn(s):
    return {"MERGED": "已合并", "OPEN": "还开着", "CLOSED": "已关闭未合并"}.get(s or "", s or "")


# ---------- 命令 ----------

def state_dir(opts):
    d = os.path.expanduser(opts.state_dir or DEFAULT_STATE)
    os.makedirs(d, exist_ok=True)
    return d


def cmd_list(opts):
    roots = opts.roots or [DEFAULT_ROOT]
    now = opts.now or time.time()
    repos = find_repos(roots, opts.max_depth)
    repo_infos, items, notes = scan(repos, opts, now)
    safe = [w for w in items if w["tier"] == SAFE and not w["is_main"]]
    plan_path = os.path.join(state_dir(opts), "plan.json")
    plan = {
        "created_at": time.time(), "roots": roots,
        "grace_hours": opts.grace_hours, "stale_days": opts.stale_days, "now_override": opts.now,
        "repos": {w["common"]: w["repo_main"] for w in safe},
        "items": [{"path": w["path"], "repo": w["repo"], "common": w["common"], "branch": w["branch"],
                   "head": w["head"], "kind": "prune" if w["prunable"] else "remove"} for w in safe],
    }
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    if opts.json:
        print(json.dumps({"items": items, "notes": notes, "plan": plan_path}, ensure_ascii=False, indent=2))
    else:
        print(report(roots, repo_infos, items, notes, now, opts, plan_path))
    return 0


def match_any(w, patterns):
    for p in patterns:
        if norm(p) == w["path"] or os.path.basename(w["path"]) == p or display_path(w) == p:
            return True
    return False


def prune_ids(common):
    """{管理目录名: worktree 路径}，用来核对 prune 会清掉哪些登记。"""
    res = {}
    base = os.path.join(common, "worktrees")
    for name in os.listdir(base) if os.path.isdir(base) else []:
        try:
            with open(os.path.join(base, name, "gitdir"), encoding="utf-8", errors="surrogateescape") as f:
                g = f.read().strip()
            res[name] = norm(os.path.dirname(g))
        except OSError:
            res[name] = None
    return res


def cmd_sweep(opts):
    if not opts.confirm:
        print("没加 --confirm，什么都没删。先跑 list 看清单，确认后再 sweep --confirm。", file=sys.stderr)
        return 2
    plan_path = opts.plan or os.path.join(state_dir(opts), "plan.json")
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError):
        print(f"找不到清单 {plan_path}。先跑 list。", file=sys.stderr)
        return 2
    if plan.get("used_at"):
        print("这份清单已经执行过了。重新跑 list 再确认。", file=sys.stderr)
        return 2
    if time.time() - plan.get("created_at", 0) > PLAN_TTL_HOURS * 3600:
        print(f"清单是 {PLAN_TTL_HOURS} 小时以前的，已失效。重新跑 list 再确认。", file=sys.stderr)
        return 2
    if not plan["items"]:
        print("清单里没有可删的 worktree。")
        return 0

    opts.grace_hours, opts.stale_days = plan["grace_hours"], plan["stale_days"]
    now = plan.get("now_override") or time.time()
    planned = {it["path"]: it for it in plan["items"]}
    if opts.only:
        planned = {p: it for p, it in planned.items() if match_any({"path": p, "repo_main": plan["repos"].get(it["common"])}, opts.only)}
    if opts.skip:
        planned = {p: it for p, it in planned.items() if not match_any({"path": p, "repo_main": plan["repos"].get(it["common"])}, opts.skip)}

    # 复核：按此刻的状态重新查一遍这些仓库
    repos = {c: m for c, m in plan["repos"].items() if any(it["common"] == c for it in planned.values())}
    opts.no_gh, opts.no_size, opts.fetch = True, True, False
    _, items, _ = scan(repos, opts, now)
    fresh = {w["path"]: w for w in items}

    removed, skipped, branches, log = [], [], [], []
    for path, it in sorted(planned.items()):
        w = fresh.get(path)
        why = None
        if w is None:
            why = "已经不在 worktree 列表里（可能被别处删了）"
        elif w["tier"] != SAFE:
            why = f"复核后变成「{w['tier']}」：" + "；".join(w["reasons"])
        elif w["head"] != it["head"]:
            why = "list 之后有了新提交"
        elif ("prune" if w["prunable"] else "remove") != it["kind"]:
            why = "目录状态和 list 时不一样"
        if why:
            skipped.append((path, why))
            continue
        main = w["repo_main"] or w["common"]
        if it["kind"] == "remove":
            rc, _, err = git(main, "worktree", "remove", path)  # 不加 --force：有未提交或未跟踪文件 git 会拒绝
            if rc != 0:
                skipped.append((path, "git 拒绝删除：" + (err.strip().splitlines() or ["?"])[-1]))
                continue
            removed.append(path)
            log.append({"action": "worktree remove", "path": path, "head": w["head"]})
        else:
            w["_pending_prune"] = True
        if w["branch"] and w["merged"]:
            branches.append(w)

    # 收尾 prune：清掉目录已丢失的登记。只有当它要清的全是清单里、刚复核过的条目时才跑，
    # 免得顺带清掉用户没看过的登记（例如外接盘没插上的 worktree）。
    pending = [fresh[p] for p in planned if p in fresh and fresh[p].get("_pending_prune")]
    touched = sorted({fresh[p]["common"] for p in removed} | {w["common"] for w in pending})
    for common in touched:
        ws = [w for w in pending if w["common"] == common]
        main = plan["repos"].get(common) or common
        ids = prune_ids(common)
        rc, out, err = git(main, "worktree", "prune", "--dry-run", "-v")
        targets = {ids.get(m.group(1)) for m in re.finditer(r"Removing (?:worktrees/)?([^:\n]+):", out + err)}
        if targets <= {w["path"] for w in ws}:
            if targets:
                rc, _, err = git(main, "worktree", "prune")
            if rc == 0:
                for w in ws:
                    removed.append(w["path"])
                    log.append({"action": "worktree prune", "path": w["path"], "head": w["head"]})
                continue
        for w in ws:
            skipped.append((w["path"], "prune 会顺带清掉清单外的登记，没执行"))

    deleted_branches = []
    for w in branches:
        if w["path"] not in removed:
            continue
        main = w["repo_main"] or w["common"]
        rc, tip, _ = git(main, "rev-parse", "--verify", "-q", f"refs/heads/{w['branch']}")
        if rc != 0 or tip.strip() != w["head"]:
            skipped.append((w["path"], f"分支 {w['branch']} 指向变了，没删分支"))
            continue
        defname, refs = default_branch(main)
        if w["branch"] == defname:
            continue
        if merged_how(main, w["head"], refs) is None:
            skipped.append((w["path"], f"分支 {w['branch']} 复核未合并，没删分支"))
            continue
        rc, _, err = git(main, "branch", "-d", w["branch"])
        if rc != 0:  # squash / 变基合并的分支 git 认不出已合并；内容已核对在默认分支里
            rc, _, err = git(main, "branch", "-D", w["branch"])
        if rc == 0:
            deleted_branches.append((w["repo"], w["branch"], w["head"], main))
            log.append({"action": "branch delete", "repo": main, "branch": w["branch"], "head": w["head"]})
        else:
            skipped.append((w["path"], f"删分支 {w['branch']} 失败：{err.strip()}"))

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(state_dir(opts), f"sweep-{stamp}.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    plan["used_at"] = time.time()  # 一份清单只用一次
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"删掉 {len(removed)} 个 worktree，删掉 {len(deleted_branches)} 个已合并的本地分支；远端没动。")
    for p in removed:
        print(f"  ✓ {short_home(p)}")
    if deleted_branches:
        print("删掉的本地分支（要找回就在仓库里跑右边那条命令）：")
        for repo, b, sha, main in deleted_branches:
            print(f"  {repo}：{b}　→　git -C '{main}' branch '{b}' {sha}")
    if skipped:
        print(f"没删 {len(skipped)} 个：")
        for p, why in skipped:
            print(f"  ✗ {short_home(p)}：{why}")
    print(f"记录：{short_home(log_path)}")
    return 0


def cmd_show(opts):
    path = norm(opts.path)
    probe = path if os.path.isdir(path) else os.path.dirname(path)
    common = common_dir(probe)
    if not common:
        print(f"{path} 不在 git 仓库里", file=sys.stderr)
        return 2
    entries = parse_worktrees(probe)
    main = norm(entries[0]["path"]) if entries and not entries[0]["bare"] else None
    _, items, notes = scan({common: main}, opts, opts.now or time.time())
    w = next((x for x in items if x["path"] == path), None)
    if not w:
        print(f"{path} 不是这个仓库登记的 worktree", file=sys.stderr)
        return 2
    now = opts.now or time.time()
    print(f"{short_home(w['path'])}")
    print(f"  分档：{w['tier']} —— {'；'.join(w['reasons'])}")
    print(f"  分支：{w['branch'] or 'detached'}　{w['remote'] or ''}　HEAD {str(w['head'])[:10]}")
    print(f"  合并：{w['merged'] or '没合并进默认分支'}")
    if w["pr"]:
        print(f"  PR：#{w['pr']['number']} {pr_state_cn(w['pr']['state'])} {w['pr']['url']}")
    if w["last_active"] is not None:
        print(f"  最后改动：{human_age(now - w['last_active'])}")
    print(f"  大小：{human_size(w['size_kb'])}")
    if w["dirty"]:
        print(f"  没提交的文件（{len(w['dirty'])} 个）：")
        for p in w["dirty"][:30]:
            print(f"    {p}")
    if w["unpushed"] and not w["merged"]:
        cwd = w["repo_main"] or common
        _, refs = default_branch(cwd)
        _, out, _ = git(cwd, "log", "--format=%h %ad %s", "--date=short", "-20", w["head"], "--not", "--remotes", *refs)
        print(f"  没推送的提交（{w['unpushed']} 个，最多列 20 个）：")
        for line in out.splitlines():
            print(f"    {line}")
    if w["ignored_unique"]:
        print("  git 不管、只有这里有的本地文件：")
        for p in w["ignored_unique"][:30]:
            print(f"    {p}")
    for n in notes:
        print(f"  说明：{n}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="worktree_sweep.py", description="扫描并清理堆积的 git worktree")
    sub = ap.add_subparsers(dest="cmd")

    def common_opts(p):
        p.add_argument("--grace-hours", type=float, default=24, help="已合并的也先留着的时间窗（小时，默认 24）")
        p.add_argument("--stale-days", type=float, default=7, help="多少天没动算「很久没动」（默认 7）")
        p.add_argument("--no-lsof", action="store_true", help="不查是否有程序正在用")
        p.add_argument("--state-dir", help=f"清单和记录存放目录（默认 {DEFAULT_STATE}）")
        p.add_argument("--max-depth", type=int, default=4, help="往根目录下找仓库的层数（默认 4）")
        p.add_argument("--regen-config", help="项目声明的生成目录（默认 skill 目录里的 regen.json）")
        p.add_argument("--now", type=float, help=argparse.SUPPRESS)  # 测试用：假装现在是这个时间戳

    p = sub.add_parser("list", help="只出报告（默认）")
    p.add_argument("roots", nargs="*", help=f"根目录，默认 {DEFAULT_ROOT}")
    p.add_argument("--fetch", action="store_true", help="先 git fetch --prune origin，让合并和远端状态是最新的")
    p.add_argument("--no-gh", action="store_true", help="不查 PR")
    p.add_argument("--no-size", action="store_true", help="不算大小（快一些）")
    p.add_argument("--show-main", action="store_true", help="报告里也列出主工作区")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    common_opts(p)

    p = sub.add_parser("sweep", help="按上次 list 的清单删「可安全删除」档")
    p.add_argument("--confirm", action="store_true", help="必须加，才会真的删")
    p.add_argument("--plan", help="清单文件（默认取上次 list 存的）")
    p.add_argument("--skip", action="append", default=[], help="这个不删（路径或目录名，可重复）")
    p.add_argument("--only", action="append", default=[], help="只删这几个（路径或目录名，可重复）")
    common_opts(p)

    p = sub.add_parser("show", help="看一个 worktree 的细节")
    p.add_argument("path")
    p.add_argument("--no-gh", action="store_true")
    common_opts(p)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("list", "sweep", "show", "-h", "--help"):
        argv.insert(0, "list")
    opts = ap.parse_args(argv)
    if opts.cmd == "sweep":
        return cmd_sweep(opts)
    if opts.cmd == "show":
        opts.no_size, opts.fetch = False, False
        return cmd_show(opts)
    return cmd_list(opts)


if __name__ == "__main__":
    sys.exit(main())
