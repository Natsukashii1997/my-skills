#!/usr/bin/env python3
"""vault-backup：用 restic 给 Obsidian 知识库和本地项目做加密异地备份，并能演练恢复。

命令：status / init / backup / check / restore-drill / prune / plist
密码只从环境变量 VAULT_BACKUP_PASSWORD 或 macOS 钥匙串读取，不写进任何文件或日志。
只用 Python 标准库，兼容 macOS 自带的 Python 3.9。
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = Path.home() / ".config" / "vault-backup" / "config.txt"
DEFAULT_STATE_DIR = Path.home() / ".local" / "state" / "vault-backup"
PLIST_LABEL = "local.vault-backup"
PASSWORD_ACCOUNT = "restic-password"
S3_ID_ACCOUNT = "s3-access-key-id"
S3_SECRET_ACCOUNT = "s3-secret-access-key"
REMOTE_PREFIXES = ("s3:", "b2:", "sftp:", "rest:", "rclone:", "azure:", "gs:", "swift:")
EXTRA_BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")  # launchd 的 PATH 很短，brew 装的 restic 在这里
SECRET_KEY_HINTS = ("password", "passwd", "secret", "token", "密码", "密钥")


class UserError(Exception):
    """可以直接给用户看的错误（中文、无凭据）。"""


# ---------------------------------------------------------------- 通用小工具

def say(msg: str = "") -> None:
    print(msg, flush=True)


def human_size(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return "?"


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def fmt_time(value) -> str:
    if not value:
        return "从未"
    t = parse_time(value) if isinstance(value, str) else value
    if t is None:
        return str(value)
    return t.astimezone().strftime("%Y-%m-%d %H:%M")


def parse_time(text: str):
    """解析 restic / 本工具写的 ISO 时间。Python 3.9 的 fromisoformat 不认 Z 和 9 位小数，这里自己处理。"""
    if not text:
        return None
    s = text.strip().replace("Z", "+00:00")
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:?\d{2})?$", s)
    if not m:
        return None
    base, frac, tz = m.groups()
    frac = "." + (frac or ".")[1:7].ljust(6, "0")  # 3.9 只认 3 或 6 位小数
    tz = tz or "+00:00"
    if ":" not in tz:
        tz = tz[:3] + ":" + tz[3:]
    try:
        return dt.datetime.fromisoformat(base + frac + tz)
    except ValueError:
        return None


def age_days(value) -> float | None:
    t = parse_time(value) if isinstance(value, str) else value
    if t is None:
        return None
    return (now_local() - t).total_seconds() / 86400


def redact_location(loc: str) -> str:
    """位置里如果带了 用户名:密码@，显示时遮掉。"""
    return re.sub(r"(//)[^/@\s]+@", r"\1***@", loc)


# ---------------------------------------------------------------- 配置

class Target:
    def __init__(self, name: str, location: str):
        self.name = name
        self.location = location

    @property
    def is_remote(self) -> bool:
        return self.location.startswith(REMOTE_PREFIXES)

    @property
    def shown(self) -> str:
        return redact_location(self.location)


class Config:
    def __init__(self, path: Path):
        self.path = path
        self.sources: list[Path] = []
        self.targets: list[Target] = []
        self.excludes: list[str] = []
        self.host = "mac"
        self.keychain_service = "vault-backup"
        self.warn_after_days = 3
        self.git_commit_before_backup = False
        self.keep = {"daily": 7, "weekly": 8, "monthly": 24, "yearly": 5}
        self.schedule = ["12:30", "21:30"]

    def source_label(self, src: Path) -> str:
        return src.name


def expand_path(text: str) -> Path:
    return Path(os.path.expanduser(text.strip())).absolute()


def load_config(path: Path) -> Config:
    if not path.exists():
        raise UserError(
            f"还没有配置文件：{path}\n"
            f"先复制模板再按注释改：\n"
            f"  mkdir -p \"{path.parent}\"\n"
            f"  cp \"{SKILL_DIR / 'assets' / 'config.example.txt'}\" \"{path}\""
        )
    cfg = Config(path)
    errors = []
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if not sep or not value:
            errors.append(f"第 {no} 行看不懂（应为 名称 = 值）：{raw}")
            continue
        if any(h in key for h in SECRET_KEY_HINTS):
            errors.append(f"第 {no} 行：密码 / 密钥不能写在配置文件里，改用钥匙串或环境变量（见 SKILL.md）")
            continue
        if key == "source":
            cfg.sources.append(expand_path(value))
        elif key == "target":
            name, bar, loc = value.partition("|")
            name, loc = name.strip(), loc.strip()
            if not bar or not name or not loc:
                errors.append(f"第 {no} 行：target 要写成 「名字 | 位置」：{raw}")
                continue
            if not re.match(r"^[\w\-一-鿿]+$", name):
                errors.append(f"第 {no} 行：目标名字只用中文、字母、数字、- 或 _：{name}")
                continue
            if not loc.startswith(REMOTE_PREFIXES):
                loc = str(expand_path(loc))
            cfg.targets.append(Target(name, loc))
        elif key == "exclude":
            if "/" in value:
                errors.append(f"第 {no} 行：exclude 只写文件或文件夹名字（可带 *），不写路径：{value}")
                continue
            cfg.excludes.append(value)
        elif key == "host":
            cfg.host = value
        elif key == "keychain_service":
            if not re.match(r"^[A-Za-z0-9._-]+$", value):
                errors.append(f"第 {no} 行：keychain_service 只用字母、数字、. _ -")
                continue
            cfg.keychain_service = value
        elif key == "warn_after_days":
            cfg.warn_after_days = int(value) if value.isdigit() else 3
        elif key == "git_commit_before_backup":
            cfg.git_commit_before_backup = value.lower() in ("yes", "true", "1", "是")
        elif key.startswith("keep_") and key[5:] in cfg.keep:
            if not value.isdigit():
                errors.append(f"第 {no} 行：{key} 要写数字")
                continue
            cfg.keep[key[5:]] = int(value)
        elif key == "schedule":
            times = [t.strip() for t in value.split(",") if t.strip()]
            if not all(re.match(r"^\d{1,2}:\d{2}$", t) for t in times):
                errors.append(f"第 {no} 行：schedule 写成 12:30, 21:30 这样")
                continue
            cfg.schedule = times
        else:
            errors.append(f"第 {no} 行：不认识的设置「{key}」")
    if not cfg.sources:
        errors.append("没有写要备份的目录（source = ...）")
    if not cfg.targets:
        errors.append("没有写备份存到哪（target = 名字 | 位置）")
    labels = [cfg.source_label(s) for s in cfg.sources]
    if len(set(labels)) != len(labels):
        errors.append("有两个 source 的文件夹名字相同，请改名或只留一个")
    names = [t.name for t in cfg.targets]
    if len(set(names)) != len(names):
        errors.append("有两个 target 名字相同")
    for t in cfg.targets:
        if t.is_remote:
            continue
        for s in cfg.sources:
            tp, sp = Path(t.location), s
            if tp == sp or sp in tp.parents:
                errors.append(f"备份位置「{t.name}」在要备份的目录里面，会把备份自己再备份一遍，换个位置")
    if errors:
        raise UserError("配置文件有问题（" + str(path) + "）：\n  - " + "\n  - ".join(errors))
    return cfg


# ---------------------------------------------------------------- 状态记录（只记时间和结果，不含任何密码）

class State:
    def __init__(self, state_dir: Path):
        self.path = state_dir / "state.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("targets", {})

    def target(self, name: str) -> dict:
        return self.data["targets"].setdefault(name, {})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- restic 与凭据

def find_restic() -> str | None:
    explicit = os.environ.get("RESTIC_BIN")
    if explicit:
        return explicit if os.path.isfile(explicit) and os.access(explicit, os.X_OK) else None
    found = shutil.which("restic")
    if found:
        return found
    for d in EXTRA_BIN_DIRS:
        p = os.path.join(d, "restic")
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


def restic_version(binary: str) -> tuple:
    try:
        out = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return (0, 0, 0)
    m = re.search(r"restic (\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def keychain_has(service: str, account: str) -> bool:
    if not shutil.which("security"):
        return False
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account],
        capture_output=True, text=True,
    )
    return r.returncode == 0


def keychain_read(service: str, account: str) -> str | None:
    if not shutil.which("security"):
        return None
    r = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True, text=True,
    )
    value = r.stdout.strip() if r.returncode == 0 else ""
    return value or None


def password_source(cfg: Config) -> str | None:
    if os.environ.get("VAULT_BACKUP_PASSWORD"):
        return "环境变量 VAULT_BACKUP_PASSWORD"
    if keychain_has(cfg.keychain_service, PASSWORD_ACCOUNT):
        return f"钥匙串（服务 {cfg.keychain_service}，账户 {PASSWORD_ACCOUNT}）"
    return None


def setup_hint(cfg: Config) -> str:
    return (
        "没找到备份密码。在终端运行下面这行，按提示输入两次密码（输入时不显示）：\n"
        f"  security add-generic-password -s {cfg.keychain_service} -a {PASSWORD_ACCOUNT} -w\n"
        "然后把同一个密码另抄一份放在电脑以外的地方（密码丢了，备份就永远打不开）。"
    )


def restic_env(cfg: Config, targets: list[Target]) -> dict:
    env = os.environ.copy()
    for k in ("RESTIC_PASSWORD", "RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_REPOSITORY",
              "RESTIC_REPOSITORY_FILE", "VAULT_BACKUP_PASSWORD"):
        env.pop(k, None)
    pw = os.environ.get("VAULT_BACKUP_PASSWORD")
    if pw:
        env["RESTIC_PASSWORD"] = pw
    elif keychain_has(cfg.keychain_service, PASSWORD_ACCOUNT):
        # 让 restic 自己去钥匙串取，密码不经过本脚本
        env["RESTIC_PASSWORD_COMMAND"] = (
            f"security find-generic-password -s {cfg.keychain_service} -a {PASSWORD_ACCOUNT} -w"
        )
    else:
        raise UserError(setup_hint(cfg))
    if any(t.location.startswith("s3:") for t in targets) and not env.get("AWS_ACCESS_KEY_ID"):
        key_id = keychain_read(cfg.keychain_service, S3_ID_ACCOUNT)
        secret = keychain_read(cfg.keychain_service, S3_SECRET_ACCOUNT)
        if key_id and secret:
            env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"] = key_id, secret
    path_parts = env.get("PATH", "").split(os.pathsep)
    env["PATH"] = os.pathsep.join(path_parts + [d for d in EXTRA_BIN_DIRS if d not in path_parts])
    return env


RESTIC_EXIT = {
    3: "有些文件没读到（多半是 macOS 没给读取权限），这次备份不完整",
    10: "这个位置还没有备份库，先运行 init",
    11: "备份库被别的进程锁住了（可能另一次备份正在跑），稍后再试",
    12: "密码不对：钥匙串或环境变量里的密码和这个备份库不匹配",
    130: "被中断了",
}


class Restic:
    def __init__(self, binary: str, env: dict):
        self.binary = binary
        self.env = env
        self.version = restic_version(binary)

    def run(self, target: Target, args: list[str]):
        cmd = [self.binary, "-r", target.location] + args
        return subprocess.run(cmd, env=self.env, capture_output=True, text=True)

    def explain(self, r) -> str:
        if r.returncode in RESTIC_EXIT:
            return RESTIC_EXIT[r.returncode]
        lines = [ln for ln in (r.stderr or "").strip().splitlines() if ln.strip()]
        tail = " / ".join(lines[-3:]) if lines else "（restic 没有给出原因）"
        return f"restic 出错（代码 {r.returncode}）：{tail}"

    def snapshots(self, target: Target, host: str, path: Path | None = None) -> list[dict]:
        args = ["snapshots", "--json", "--host", host]
        if path is not None:
            args += ["--path", str(path)]
        r = self.run(target, args)
        if r.returncode != 0:
            raise UserError(self.explain(r))
        return json.loads(r.stdout or "[]") or []


def target_reachable(t: Target) -> tuple[bool, str]:
    """只看本机能不能到达这个位置，不碰密码。远程位置一律当作可达，由 restic 报错。"""
    if t.is_remote:
        return True, "远程存储"
    p = Path(t.location)
    parts = p.parts
    if len(parts) >= 3 and parts[1] == "Volumes" and not Path("/", "Volumes", parts[2]).exists():
        return False, f"外置盘「{parts[2]}」没有连接"
    if (p / "config").exists():
        return True, "备份库已建好"
    if p.exists():
        return True, "文件夹在，但还不是备份库（先 init）"
    return True, "文件夹还不存在（init 会建）"


def repo_exists(rs: Restic, t: Target) -> bool:
    if not t.is_remote:
        return (Path(t.location) / "config").exists()
    r = rs.run(t, ["cat", "config"])
    if r.returncode == 0:
        return True
    if r.returncode == 10:
        return False
    raise UserError(rs.explain(r))


def prepare(cfg: Config, targets: list[Target]) -> Restic:
    binary = find_restic()
    if not binary:
        raise UserError("没装 restic。在终端运行：brew install restic（没有 brew 的话见 references/approach.md）")
    return Restic(binary, restic_env(cfg, targets))


def pick_targets(cfg: Config, name: str | None, default_first: bool = False) -> list[Target]:
    if name:
        chosen = [t for t in cfg.targets if t.name == name]
        if not chosen:
            raise UserError(f"配置里没有叫「{name}」的备份位置；现有：{', '.join(t.name for t in cfg.targets)}")
        return chosen
    return cfg.targets[:1] if default_first else list(cfg.targets)


# ---------------------------------------------------------------- git

def git_root(src: Path) -> bool:
    if not (src / ".git").exists() or not shutil.which("git"):
        return False
    r = subprocess.run(["git", "-C", str(src), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return r.returncode == 0 and Path(r.stdout.strip()).resolve() == src.resolve()


def git_uncommitted(src: Path) -> int | None:
    if not git_root(src):
        return None
    # --no-optional-locks：只读，不顺手改写 .git/index（否则没改动的仓库也会被当成有变化）
    r = subprocess.run(["git", "--no-optional-locks", "-C", str(src), "status", "--porcelain"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def git_snapshot_commit(src: Path) -> str:
    stamp = now_local().strftime("%Y-%m-%d %H:%M")
    r = subprocess.run(["git", "-C", str(src), "add", "-A"], capture_output=True, text=True)
    if r.returncode != 0:
        return "git add 失败：" + (r.stderr.strip().splitlines() or ["?"])[-1]
    r = subprocess.run(
        ["git", "-C", str(src), "commit", "-q", "-m", f"vault-backup：备份前快照 {stamp}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return "git 提交失败（备份照常进行，未提交的改动也会被备份）：" + (
            (r.stderr or r.stdout).strip().splitlines() or ["?"])[-1]
    return "已提交一次快照"


# ---------------------------------------------------------------- 比对（恢复演练用）

def is_excluded(rel: str, excludes: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(part, pat) for part in rel.split("/") for pat in excludes)


def scan_tree(root: Path, excludes: list[str]) -> dict:
    """返回 相对路径 -> (类型, 信息)。类型：dir / file(大小) / link(指向)。不跟随符号链接。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        keep = []
        for name in dirnames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if is_excluded(rel, excludes):
                continue
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                out[rel] = ("link", os.readlink(full))
            else:
                out[rel] = ("dir", None)
                keep.append(name)
        dirnames[:] = keep
        for name in filenames:
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if is_excluded(rel, excludes):
                continue
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(full))
            elif stat.S_ISREG(st.st_mode):
                out[rel] = ("file", st.st_size)
    return out


def file_hash(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def changed_since(path: Path, cutoff: float) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return max(st.st_mtime, st.st_ctime) > cutoff


def nearest_existing_parent_changed(source: Path, rel: str, cutoff: float) -> bool:
    p = (source / rel).parent
    while True:
        if p.exists():
            return changed_since(p, cutoff)
        if p == source or source not in p.parents:
            return False
        p = p.parent


def compare_trees(source: Path, restored: Path, cutoff: float, excludes: list[str]) -> dict:
    """把恢复出来的目录和当前源目录逐个比对。

    cutoff 是备份快照的时间（时间戳）。源里在快照之后改过 / 新增 / 删除的差异属于正常（expected）；
    快照之后没动过却对不上的，属于异常（unexpected）——那才说明备份有问题。
    """
    src_tree = scan_tree(source, excludes)
    bak_tree = scan_tree(restored, excludes)
    result = {"same": 0, "expected": [], "unexpected": [], "files": 0, "bytes": 0}

    def note(kind: str, rel: str, why: str):
        result[kind].append(f"{why}：{rel}")

    for rel in sorted(set(src_tree) | set(bak_tree)):
        s, b = src_tree.get(rel), bak_tree.get(rel)
        if s and s[0] == "file":
            result["files"] += 1
            result["bytes"] += s[1]
        if s is None:
            if nearest_existing_parent_changed(source, rel, cutoff):
                note("expected", rel, "备份后从源里删掉了")
            else:
                note("unexpected", rel, "备份里有、源里没有")
            continue
        recent = changed_since(source / rel, cutoff)
        if b is None:
            if recent or nearest_existing_parent_changed(source, rel, cutoff):
                note("expected", rel, "备份后新加的")
            else:
                note("unexpected", rel, "源里有、备份里没有")
            continue
        if s[0] != b[0]:
            note("expected" if recent else "unexpected", rel, "类型不同")
            continue
        if s[0] == "dir":
            result["same"] += 1
            continue
        if s[0] == "link":
            same = s[1] == b[1]
        else:
            try:
                same = s[1] == b[1] and file_hash(str(source / rel)) == file_hash(str(restored / rel))
            except OSError as e:
                note("unexpected", rel, f"读不了（{e.strerror}）")
                continue
        if same:
            result["same"] += 1
        else:
            note("expected" if recent else "unexpected", rel,
                 "备份后改过" if recent else "内容不一致")
    return result


# ---------------------------------------------------------------- 通知（定时运行时用）

def notify(message: str) -> None:
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return
    subprocess.run(
        ["osascript", "-e", "on run argv", "-e",
         'display notification (item 1 of argv) with title "知识库备份"', "-e", "end run", message],
        capture_output=True,
    )


# ---------------------------------------------------------------- 命令：status

def schedule_state(plist: Path) -> str:
    """plist 文件在不等于任务在跑：卸下后没装回时文件还在。macOS 上再问一次 launchd。"""
    if not plist.exists():
        return "未安装（见 references/schedule.md）"
    if sys.platform != "darwin" or not shutil.which("launchctl"):
        return f"定时文件在（{plist}），这台电脑上没法确认是否已启用"
    r = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{PLIST_LABEL}"], capture_output=True, text=True)
    if r.returncode == 0:
        return f"已安装并已启用（{plist}）"
    return (f"定时文件在，但没有启用（{plist}）。运行："
            f"launchctl bootstrap gui/{os.getuid()} \"{plist}\"")


def cmd_status(cfg: Config, state: State, args) -> int:
    problems = []
    say(f"配置文件：{cfg.path}")
    binary = find_restic()
    if binary:
        v = restic_version(binary)
        say(f"restic：{binary}（版本 {'.'.join(map(str, v))}）")
        if v < (0, 17, 0):
            problems.append("restic 版本低于 0.17，运行 brew upgrade restic")
    else:
        say("restic：没装（brew install restic）")
        problems.append("没装 restic")
    src = password_source(cfg)
    say(f"备份密码：{'已配置，来自' + src if src else '未配置'}")
    if not src:
        problems.append("没配置备份密码")

    say("\n要备份的目录：")
    for s in cfg.sources:
        if not s.exists():
            say(f"  ✗ {s}（不存在）")
            problems.append(f"源目录不存在：{s}")
            continue
        n = git_uncommitted(s)
        git_note = "不是 git 仓库" if n is None else (f"git 有 {n} 处未提交改动（备份照样包含它们）" if n else "git 无未提交改动")
        say(f"  ✓ {s}（{git_note}）")

    say("\n备份位置：")
    for t in cfg.targets:
        ok, why = target_reachable(t)
        rec = state.target(t.name)
        last_ok = rec.get("last_success")
        last = rec.get("last_backup", {})
        say(f"  [{t.name}] {t.shown}")
        say(f"     现在：{'可用' if ok else '不可用'}，{why}")
        say(f"     上次备份成功：{fmt_time(last_ok)}" +
            (f"；最近一次尝试 {fmt_time(last.get('time'))} 结果：{last.get('summary', '')}"
             if last and last.get("result") != "ok" else ""))
        chk = rec.get("last_check", {})
        drl = rec.get("last_drill", {})
        say(f"     上次检查：{fmt_time(chk.get('time'))} {chk.get('summary', '')}")
        say(f"     上次恢复演练：{fmt_time(drl.get('time'))} {drl.get('summary', '')}")
        days = age_days(last_ok)
        if days is None:
            problems.append(f"「{t.name}」还没有成功备份过")
        elif days > cfg.warn_after_days:
            problems.append(f"「{t.name}」已经 {days:.0f} 天没成功备份了")
        if drl.get("result") != "ok":
            problems.append(f"「{t.name}」还没有通过恢复演练")
        elif (age_days(drl.get("time")) or 0) > 90:
            problems.append(f"「{t.name}」上次恢复演练超过 90 天")

    plist = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"
    say(f"\n定时备份：{schedule_state(plist)}")

    say("")
    if problems:
        say("要处理的事：")
        for p in problems:
            say(f"  - {p}")
        return 1
    say("结论：一切正常。")
    return 0


# ---------------------------------------------------------------- 命令：init

def cmd_init(cfg: Config, state: State, args) -> int:
    targets = pick_targets(cfg, args.target)
    rs = prepare(cfg, targets)
    failed = 0
    for t in targets:
        ok, why = target_reachable(t)
        if not ok:
            say(f"[{t.name}] 跳过：{why}")
            failed += 1
            continue
        if repo_exists(rs, t):
            say(f"[{t.name}] 备份库已经存在，不重复建")
            continue
        r = rs.run(t, ["init"])
        if r.returncode == 0:
            say(f"[{t.name}] 已建好加密备份库：{t.shown}")
        else:
            say(f"[{t.name}] 建库失败：{rs.explain(r)}")
            failed += 1
    say("\n提醒：密码就是钥匙。确认它已另存一份在电脑以外的地方（纸质或密码管理器）。")
    return 1 if failed else 0


# ---------------------------------------------------------------- 命令：backup

def backup_one(rs: Restic, cfg: Config, t: Target, src: Path) -> tuple[str, str]:
    args = ["backup", "--json", "--host", cfg.host, "--tag", "vault-backup"]
    if rs.version >= (0, 17, 0):
        args.append("--skip-if-unchanged")
    for pat in cfg.excludes:
        args += ["--exclude", pat]
    args.append(str(src))
    r = rs.run(t, args)
    summary = None
    for line in (r.stdout or "").splitlines():
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("message_type") == "summary":
            summary = msg
    if r.returncode not in (0, 3):
        return "failed", rs.explain(r)
    if summary:
        changed = summary.get("files_new", 0) + summary.get("files_changed", 0)
        text = (f"{summary.get('total_files_processed', 0)} 个文件，新增/改动 {changed} 个，"
                f"新写入 {human_size(summary.get('data_added', 0))}，用时 {summary.get('total_duration', 0):.0f} 秒")
        if not summary.get("snapshot_id"):
            text += "（和上次完全一样，没有新建快照）"
    else:
        text = "完成"
    if r.returncode == 3:
        errs = []
        for line in (r.stderr or "").splitlines():
            try:
                msg = json.loads(line)
                if msg.get("message_type") == "error":
                    errs.append(str(msg.get("item") or msg.get("error", {}).get("message", "")))
            except ValueError:
                if line.strip():
                    errs.append(line.strip())
        shown = "；".join(errs[:5]) + (f" 等 {len(errs)} 个" if len(errs) > 5 else "")
        return "partial", f"{RESTIC_EXIT[3]}：{shown}。{text}"
    return "ok", text


def cmd_backup(cfg: Config, state: State, args) -> int:
    targets = pick_targets(cfg, args.target)
    rs = prepare(cfg, targets)
    do_commit = args.git_commit or cfg.git_commit_before_backup
    errors, warnings = [], []

    sources = []
    for s in cfg.sources:
        if not s.exists():
            errors.append(f"源目录不存在，跳过：{s}")
            say(f"✗ 源目录不存在：{s}")
            continue
        sources.append(s)
        n = git_uncommitted(s)
        if n is None:
            continue
        if n and do_commit:
            say(f"· {s.name}：git 有 {n} 处未提交改动 → {git_snapshot_commit(s)}")
        elif n:
            say(f"· {s.name}：git 有 {n} 处未提交改动（没提交；这些改动照样会被备份）")
        else:
            say(f"· {s.name}：git 无未提交改动")

    for t in targets:
        rec = state.target(t.name)
        ok, why = target_reachable(t)
        if not ok:
            say(f"\n[{t.name}] 跳过：{why}")
            rec["last_backup"] = {"time": now_local().isoformat(), "result": "offline", "summary": why}
            warnings.append(f"「{t.name}」跳过：{why}")
            continue
        if not repo_exists(rs, t):
            msg = "还没有备份库，先运行 init"
            say(f"\n[{t.name}] {msg}")
            errors.append(f"「{t.name}」{msg}")
            rec["last_backup"] = {"time": now_local().isoformat(), "result": "failed", "summary": msg}
            continue
        say(f"\n[{t.name}] 备份到 {t.shown}")
        results = []
        for s in sources:
            result, text = backup_one(rs, cfg, t, s)
            mark = {"ok": "✓", "partial": "!", "failed": "✗"}[result]
            say(f"  {mark} {s.name}：{text}")
            results.append(result)
            if result != "ok":
                errors.append(f"「{t.name}」{s.name}：{text}")
        if results and all(r == "ok" for r in results) and len(sources) == len(cfg.sources):
            overall = "ok"
        elif results and any(r != "failed" for r in results):
            overall = "partial"
        else:
            overall = "failed"
        stamp = now_local().isoformat()
        rec["last_backup"] = {"time": stamp, "result": overall,
                              "summary": "成功" if overall == "ok" else "有问题，见日志"}
        if overall == "ok":
            rec["last_success"] = stamp
    state.save()

    stale = []
    for t in cfg.targets:
        d = age_days(state.target(t.name).get("last_success"))
        if d is None or d > cfg.warn_after_days:
            stale.append(t.name)
    say("")
    if errors:
        say("结果：有问题 ↓")
        for e in errors:
            say(f"  - {e}")
    else:
        say("结果：备份完成。" + ("（" + "；".join(warnings) + "）" if warnings else ""))
    if stale:
        say(f"注意：{', '.join(stale)} 超过 {cfg.warn_after_days} 天没有成功备份。")
    if args.notify and (errors or stale):
        notify("备份出了问题，对 Claude 说「检查备份」看详情" if errors
               else f"{', '.join(stale)} 已经好几天没备份了（外置盘没插？）")
    return 1 if errors else 0


# ---------------------------------------------------------------- 命令：check

def cmd_check(cfg: Config, state: State, args) -> int:
    targets = pick_targets(cfg, args.target)
    rs = prepare(cfg, targets)
    failed = 0
    for t in targets:
        rec = state.target(t.name)
        say(f"[{t.name}] {t.shown}")
        ok, why = target_reachable(t)
        if not ok:
            say(f"  跳过：{why}")
            failed += 1
            continue
        if not repo_exists(rs, t):
            say("  还没有备份库，先运行 init")
            failed += 1
            continue
        how = "--read-data" if args.full else "--read-data-subset=5%"
        say(f"  校验完整性（{'读取全部数据' if args.full else '结构 + 随机抽 5% 数据'}）…")
        r = rs.run(t, ["check", how])
        passed = r.returncode == 0
        say(f"  {'✓ 完整性校验通过' if passed else '✗ 校验没通过：' + rs.explain(r)}")
        if r.returncode == 12:  # 密码不对，后面的查询也都会失败，不再重复报错
            rec["last_check"] = {"time": now_local().isoformat(), "result": "failed", "summary": "密码不对"}
            failed += 1
            continue
        lines = []
        try:
            for s in cfg.sources:
                snaps = rs.snapshots(t, cfg.host, s)
                if not snaps:
                    lines.append(f"  · {s.name}：还没有备份")
                    continue
                last = snaps[-1]
                st = rs.run(t, ["stats", "--json", last["short_id"]])
                info = json.loads(st.stdout) if st.returncode == 0 else {}
                lines.append(
                    f"  · {s.name}：最近一次 {fmt_time(last['time'])}，共 {len(snaps)} 个版本，"
                    f"最新版本 {info.get('total_file_count', '?')} 个文件和文件夹 / {human_size(info.get('total_size'))}")
            raw = rs.run(t, ["stats", "--json", "--mode", "raw-data"])
            if raw.returncode == 0:
                lines.append(f"  · 备份库实际占用（加密压缩去重后）：{human_size(json.loads(raw.stdout).get('total_size'))}")
        except UserError as e:
            lines.append(f"  · 读取快照失败：{e}")
            passed = False
        for ln in lines:
            say(ln)
        rec["last_check"] = {"time": now_local().isoformat(), "result": "ok" if passed else "failed",
                             "summary": "通过" if passed else "没通过"}
        if not passed:
            failed += 1
    state.save()
    say("\n结论：" + ("全部通过。" if not failed else f"{failed} 个位置有问题，见上面。"))
    return 1 if failed else 0


# ---------------------------------------------------------------- 命令：restore-drill

def drill_one(rs: Restic, cfg: Config, t: Target, s: Path, snap_id: str, label: str,
              cutoff: float, work: Path) -> bool:
    say(f"  · {s.name}：恢复 {label}到 {work} …")
    r = rs.run(t, ["restore", snap_id, "--target", str(work), "--verify"])
    if r.returncode != 0:
        say(f"  ✗ {s.name}：恢复失败：{rs.explain(r)}")
        return False
    restored = work / str(s).lstrip("/")
    if not restored.is_dir():
        say(f"  ✗ {s.name}：恢复出来的目录里找不到 {s}")
        return False
    res = compare_trees(s, restored, cutoff, cfg.excludes)
    say(f"    逐个比对 {res['files']} 个文件（{human_size(res['bytes'])}）："
        f"一致 {res['same']} 项，备份之后正常改动 {len(res['expected'])} 项，"
        f"对不上 {len(res['unexpected'])} 项")
    for line in res["expected"][:5]:
        say(f"      （正常）{line}")
    if len(res["expected"]) > 5:
        say(f"      （正常）…另有 {len(res['expected']) - 5} 项")
    for line in res["unexpected"][:20]:
        say(f"      ✗ {line}")
    if res["unexpected"]:
        return False
    say(f"  ✓ {s.name}：恢复演练通过")
    return True


def cmd_restore_drill(cfg: Config, state: State, args) -> int:
    targets = pick_targets(cfg, args.target, default_first=True)
    rs = prepare(cfg, targets)
    sources = [s for s in cfg.sources if not args.source or s.name == args.source]
    if not sources:
        raise UserError(f"没有叫「{args.source}」的源目录；现有：{', '.join(s.name for s in cfg.sources)}")
    base = Path(args.to).expanduser().absolute() if args.to else Path(tempfile.gettempdir())
    for s in cfg.sources:
        if base == s or s in base.parents:
            raise UserError("演练目录不能放在被备份的目录里面")
    base.mkdir(parents=True, exist_ok=True)

    failed = 0
    for t in targets:
        rec = state.target(t.name)
        say(f"[{t.name}] 从 {t.shown} 恢复演练（只恢复到临时目录，不动原文件）")
        ok, why = target_reachable(t)
        if not ok:
            say(f"  跳过：{why}")
            failed += 1
            continue
        t_failed = 0
        for s in sources:
            try:
                snaps = rs.snapshots(t, cfg.host, s)
            except UserError as e:
                say(f"  ✗ {s.name}：{e}")
                t_failed += 1
                continue
            if not snaps:
                say(f"  ✗ {s.name}：这个位置里还没有它的备份")
                t_failed += 1
                continue
            snap = snaps[-1]
            snap_time = parse_time(snap["time"])
            st = rs.run(t, ["stats", "--json", snap["short_id"]])
            need = json.loads(st.stdout).get("total_size", 0) if st.returncode == 0 else 0
            free = shutil.disk_usage(base).free
            if need and free < need * 1.1 + 100 * 1024 * 1024:
                say(f"  ✗ {s.name}：临时目录所在磁盘空间不够（要 {human_size(need)}，剩 {human_size(free)}），"
                    f"用 --to 换个地方")
                t_failed += 1
                continue
            label = f"{fmt_time(snap['time'])} 的版本（{human_size(need)}）"
            cutoff = snap_time.timestamp() if snap_time else 0
            if args.keep:
                work = Path(tempfile.mkdtemp(prefix="vault-backup-drill-", dir=str(base)))
                passed = drill_one(rs, cfg, t, s, snap["short_id"], label, cutoff, work)
                say(f"    恢复出的文件保留在：{work}（看完自己删）")
            else:
                # 只用本次新建的临时目录，退出时由标准库删掉它本身，不碰别的路径
                with tempfile.TemporaryDirectory(prefix="vault-backup-drill-", dir=str(base)) as d:
                    passed = drill_one(rs, cfg, t, s, snap["short_id"], label, cutoff, Path(d))
            if not passed:
                t_failed += 1
        rec["last_drill"] = {"time": now_local().isoformat(), "result": "ok" if not t_failed else "failed",
                             "summary": "通过" if not t_failed else "没通过"}
        failed += t_failed
    state.save()
    say("\n结论：" + ("恢复演练通过，备份能完整取回。" if not failed else "恢复演练没通过，见上面 ✗ 的行。"))
    return 1 if failed else 0


# ---------------------------------------------------------------- 命令：prune（默认只预演）

def cmd_prune(cfg: Config, state: State, args) -> int:
    targets = pick_targets(cfg, args.target)
    rs = prepare(cfg, targets)
    keep = []
    for k, v in cfg.keep.items():
        keep += [f"--keep-{k}", str(v)]
    failed = 0
    for t in targets:
        ok, why = target_reachable(t)
        if not ok:
            say(f"[{t.name}] 跳过：{why}")
            continue
        extra = ["--prune"] if args.apply else ["--dry-run"]
        for src in cfg.sources:
            # backup_one 每次只备份一个源；共享仓库中的其他标签和源不归本配置清理。
            plan = rs.run(t, ["forget", "--host", cfg.host, "--tag", "vault-backup",
                              "--path", str(src), "--json", "--dry-run"] + keep)
            if plan.returncode != 0:
                say(f"[{t.name}] ✗ " + rs.explain(plan))
                failed += 1
                continue
            # restic 的 --path 是包含匹配，混合了其他源的快照不能归本配置删除。
            # 先用原保留策略生成计划，再只对核实过归属的完整 ID 预演或执行。
            try:
                groups = json.loads(plan.stdout)
                remove = [snap for group in groups for snap in (group.get("remove") or [])]
                ids = [snap["id"] for snap in remove
                       if snap["hostname"] == cfg.host and snap["paths"] == [str(src)]
                       and "vault-backup" in snap.get("tags", [])]
                if any(not re.fullmatch(r"[0-9a-f]{64}", sid) for sid in ids):
                    raise ValueError("invalid snapshot ID")
            except (ValueError, TypeError, KeyError, AttributeError):
                say(f"[{t.name}] ✗ 清理计划无法完整读取，未删除任何快照。")
                failed += 1
                continue
            say(f"[{t.name}] {'已清理' if args.apply else '预演（没删任何东西）'}：")
            if not ids:
                say("  没有需要清理的快照。")
                continue
            r = rs.run(t, ["forget"] + extra + ids)
            out = r.stdout.strip().splitlines()
            for ln in out[-25:]:
                say("  " + ln)
            if r.returncode != 0:
                say("  ✗ " + rs.explain(r))
                failed += 1
    if not args.apply:
        say(f"\n保留规则：每天 {cfg.keep['daily']}、每周 {cfg.keep['weekly']}、每月 {cfg.keep['monthly']}、"
            f"每年 {cfg.keep['yearly']} 个版本。确认没问题再加 --apply 真正清理。")
    return 1 if failed else 0


# ---------------------------------------------------------------- 命令：plist（只打印，不安装）

def cmd_plist(cfg: Config, state: State, args) -> int:
    template = (SKILL_DIR / "assets" / "launchd.plist.template").read_text(encoding="utf-8")
    entries = []
    for t in cfg.schedule:
        h, m = t.split(":")
        entries.append(f"    <dict><key>Hour</key><integer>{int(h)}</integer>"
                       f"<key>Minute</key><integer>{int(m)}</integer></dict>")
    log_file = Path.home() / "Library" / "Logs" / "vault-backup.log"  # launchd 不会替你建文件夹，所以直接放 Logs 下

    def esc(x: str) -> str:
        return x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    out = (template
           .replace("{{LABEL}}", PLIST_LABEL)
           .replace("{{PYTHON}}", esc(sys.executable))
           .replace("{{SCRIPT}}", esc(str(Path(__file__).resolve())))
           .replace("{{CONFIG}}", esc(str(cfg.path)))
           .replace("{{LOG}}", esc(str(log_file)))
           .replace("{{SCHEDULE}}", "\n".join(entries)))
    sys.stdout.write(out)
    return 0


# ---------------------------------------------------------------- 入口

def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vault_backup.py", description="知识库加密异地备份（restic）")
    p.add_argument("--config", help=f"配置文件（默认 {DEFAULT_CONFIG}）")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="看配置、上次备份 / 检查 / 演练时间，不需要密码")
    s = sub.add_parser("init", help="第一次使用：在备份位置建加密备份库")
    s.add_argument("--target")
    s = sub.add_parser("backup", help="备份一次")
    s.add_argument("--target")
    s.add_argument("--git-commit", action="store_true", help="备份前在有未提交改动的 git 目录里提交一次快照")
    s.add_argument("--notify", action="store_true", help="出问题时弹 macOS 通知（定时任务用）")
    s = sub.add_parser("check", help="校验备份完整性，显示最近一次备份时间和大小")
    s.add_argument("--target")
    s.add_argument("--full", action="store_true", help="读取全部数据校验（慢，云端会产生下载流量）")
    s = sub.add_parser("restore-drill", help="恢复到临时目录并与源比对，不覆盖源")
    s.add_argument("--target", help="从哪个位置演练（默认配置里第一个）")
    s.add_argument("--source", help="只演练这个目录（填文件夹名）")
    s.add_argument("--to", help="临时目录放在哪（默认系统临时目录）")
    s.add_argument("--keep", action="store_true", help="演练完保留恢复出来的文件")
    s = sub.add_parser("prune", help="按保留规则清理旧版本（默认只预演）")
    s.add_argument("--target")
    s.add_argument("--apply", action="store_true")
    sub.add_parser("plist", help="打印定时任务文件内容（不安装）")
    args = p.parse_args(argv)

    cfg_path = Path(args.config or os.environ.get("VAULT_BACKUP_CONFIG") or DEFAULT_CONFIG).expanduser()
    state_dir = Path(os.environ.get("VAULT_BACKUP_STATE_DIR") or DEFAULT_STATE_DIR).expanduser()
    handlers = {"status": cmd_status, "init": cmd_init, "backup": cmd_backup, "check": cmd_check,
                "restore-drill": cmd_restore_drill, "prune": cmd_prune, "plist": cmd_plist}
    try:
        cfg = load_config(cfg_path.absolute())
        if args.cmd != "plist":
            say(f"—— vault-backup {args.cmd} · {now_local().strftime('%Y-%m-%d %H:%M')} ——")
        return handlers[args.cmd](cfg, State(state_dir), args)
    except UserError as e:
        say(f"✗ {e}")
        if getattr(args, "notify", False):
            notify("备份没能运行，对 Claude 说「检查备份」看详情")
        return 2
    except KeyboardInterrupt:
        say("已中断。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
