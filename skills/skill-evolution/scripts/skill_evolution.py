#!/usr/bin/env python3
"""skill 进化 · 取数与提案检查。

scan  把一个时间窗口里的会话整理成「会话清单 + skill 使用表」（sessions.md / sessions.json）。
check 查提案：引用的会话编号对不对得上、每条必填项齐不齐、「可立项」有没有两次以上的依据、条数超没超。

只读本机会话记录，只用标准库，不联网。解析会话、脱敏、认真人原话都复用 session-retro 的脚本
（同一个仓库里的 skills/session-retro/scripts/session_retro.py），这里不另写一套。
脚本只整理事实；哪些流程值得做成 skill、现有 skill 该怎么改，由执行 skill 的 agent 判断。
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    sys.stderr.write("需要 Python 3.9 及以上\n")
    raise

SCHEMA_VERSION = 1
HERE = Path(__file__).resolve()
SKILLS_DIR = HERE.parents[2]  # my-skills/skills
MAX_PROPOSALS = 7
FIRST_LIMIT, LATER_LIMIT, LATER_MAX, FOOTPRINT_MAX = 240, 90, 5, 6
COMMAND_NAME = re.compile(r"<command-name>/?([\w:.\-]+)</command-name>")
# 和 scripts/monthly-health.mjs 的 codexHitsInText 同一条规则：Codex 没有「调用 skill」事件，
# 以工具调用读取 skills/<名字>/SKILL.md 为准，同一会话只算一次。
CODEX_SKILL_READ = re.compile(r"skills/([A-Za-z0-9_\-]+)(?:/SKILL\.md|/?(?=\\*[\"']))")
CODEX_TOOL_CALLS = ("function_call", "custom_tool_call", "local_shell_call")
# 宿主自己的记账工具，不算干活的足迹
NOISE_TOOLS = re.compile(r"(?:update_plan|wrap_up|mark_chapter|read_me|ToolSearch|TodoWrite|TaskCreate|TaskUpdate|TaskList)$")
ZST_DATE = re.compile(r"rollout-(\d{4})-(\d{2})-(\d{2})T.*\.jsonl\.zst$")
KEY_LIMIT = 48


def footprint_key(retro, event):
    """工具足迹里的一项：去掉记账工具，命令认不出来的归成「（其他）」，太长的截断。"""
    name = str(event.tool or "tool")
    if NOISE_TOOLS.search(name):
        return None
    key = re.sub(r"\s+", " ", retro.redact(event.key or name)).strip()
    if key.endswith(":") or key == name + ":":
        key = name + "（其他）"
    return key if len(key) <= KEY_LIMIT else key[:KEY_LIMIT].rstrip() + "…"


def codex_zst_in_window(roots, start_day, end_day):
    """Codex 过几天会把记录压成 .jsonl.zst，session-retro 的解析不读压缩文件。数出窗口里有几个没读，当缺口报出来。"""
    count = 0
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for folder, dirs, names in os.walk(str(root), followlinks=False):
            for name in names:
                found = ZST_DATE.search(name)
                if not found:
                    continue
                try:
                    day = date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
                except ValueError:
                    continue
                if start_day - timedelta(days=1) <= day <= end_day:
                    count += 1
    return count


RETRO_SCRIPT = SKILLS_DIR / "session-retro" / "scripts" / "session_retro.py"


def load_retro(path=RETRO_SCRIPT):
    """加载 session-retro 的脚本当模块用。找不到就明说，不退回自己解析。"""
    if "session_retro" in sys.modules:
        return sys.modules["session_retro"]
    path = Path(path)
    if not path.is_file():
        raise SystemExit("找不到 session-retro 的脚本：%s\n本 skill 靠它解析会话和脱敏，请确认 my-skills 里有 skills/session-retro。" % path)
    spec = importlib.util.spec_from_file_location("session_retro", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["session_retro"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- 时间窗口、项目名、已装 skill

def last_week(today):
    """上一个完整的自然周：上周一（含）到本周一（不含）。"""
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday


def resolve_window(args, zone, today=None):
    today = today or datetime.now(zone).date()
    if args.start:
        start_day = date.fromisoformat(args.start)
        end_day = date.fromisoformat(args.end) if args.end else start_day + timedelta(days=7)
    elif args.days:
        end_day = today + timedelta(days=1)
        start_day = end_day - timedelta(days=args.days)
    else:
        start_day, end_day = last_week(today)
    if start_day >= end_day:
        raise ValueError("结束日期必须晚于开始日期")
    start = datetime.combine(start_day, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(end_day, time.min, zone).astimezone(timezone.utc)
    return start, end, start_day, end_day


WORKTREE_INNER = re.compile(r"^(.*?)/\.claude/worktrees/")
WORKTREE_OUTER = re.compile(r"/\.worktrees/([^/]+?)(?:-\d+[^/]*)?(?:/|$)")


def project_of(cwd):
    """把工作目录归到项目：worktree 归回它的仓库，临时目录归成一类。"""
    if not cwd:
        return "(未知目录)"
    text = str(cwd).rstrip("/")
    if "/scratch-workspaces/" in text or re.search(r"/(?:tmp|T)/claude-", text):
        return "临时会话"
    inner = WORKTREE_INNER.match(text)
    if inner:
        return os.path.basename(inner.group(1)) or text
    outer = WORKTREE_OUTER.search(text)
    if outer:
        return outer.group(1)
    if "/Sandbox/" in text:
        return "Sandbox（试验）"
    return os.path.basename(text) or text


def known_skills(roots, own_root=SKILLS_DIR):
    """已装的 skill：名字 -> 是不是自建（真实路径在 own_root 下，默认 my-skills/skills）。"""
    own_root = str(Path(own_root).expanduser().resolve())
    found = {}
    for root in roots:
        root = Path(root).expanduser()
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not (entry / "SKILL.md").is_file():
                continue
            real = str(entry.resolve())
            own = real.startswith(own_root + os.sep)
            found[entry.name] = found.get(entry.name, False) or own
    return found


# ---------------------------------------------------------------- 认 skill 调用

def skill_calls(retro, source, path, known):
    """返回这份记录里的 skill 调用 [{name, ts, line, how}]，按行号排好。"""
    calls, scratch = [], Counter()
    if source == "claude":
        for number, record in retro.iter_jsonl(path, scratch):
            if record.get("isSidechain"):
                continue
            stamp = retro.parse_ts(record.get("timestamp"))
            message = record.get("message") if isinstance(record.get("message"), dict) else {}
            content = message.get("content")
            if stamp is None:
                continue
            if record.get("type") == "assistant" and isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Skill":
                        args = block.get("input") if isinstance(block.get("input"), dict) else {}
                        name = str(args.get("skill") or "").lstrip("/").strip()
                        if name:
                            calls.append({"name": name, "ts": stamp, "line": number, "how": "Skill 工具"})
            elif record.get("type") == "user":
                # 只认用户自己敲的斜杠命令：工具结果里出现同样的标签（比如 grep 到）不算
                blocks = [content] if isinstance(content, str) else (content if isinstance(content, list) else [])
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks):
                    continue
                text = "\n".join(b if isinstance(b, str) else str(b.get("text") or "") for b in blocks if isinstance(b, (str, dict)))
                for found in COMMAND_NAME.finditer(text):
                    name = found.group(1)
                    if name in known or ":" in name:
                        calls.append({"name": name, "ts": stamp, "line": number, "how": "斜杠命令"})
        return calls
    seen = set()
    for number, record in retro.iter_jsonl(path, scratch, lambda raw: b"SKILL.md" not in raw):
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else None
        if record.get("type") != "response_item" or not payload or payload.get("type") not in CODEX_TOOL_CALLS:
            continue
        stamp = retro.parse_ts(record.get("timestamp"))
        if stamp is None:
            continue
        body = json.dumps([payload.get("arguments"), payload.get("input"), payload.get("action")], ensure_ascii=False)
        for found in CODEX_SKILL_READ.finditer(body):
            name = found.group(1)
            if name in known and name not in seen:
                seen.add(name)
                calls.append({"name": name, "ts": stamp, "line": number, "how": "读 SKILL.md"})
    return calls


# ---------------------------------------------------------------- 扫描

class Scan(object):
    def __init__(self, retro, args, start, end, zone, known):
        self.retro, self.args, self.start, self.end, self.zone, self.known = retro, args, start, end, zone, known
        self.coverage = Counter()
        self.coverage["roots_missing"] = []
        self.sessions = []
        self.usage = defaultdict(lambda: {"calls": 0, "sessions": set(), "projects": Counter(), "how": Counter(), "after": []})
        self.seen_uids = set()
        self.exclude = set(s.lower() for s in (args.exclude_session or []))
        self.projects = [p.lower() for p in (args.project or [])]

    def local(self, stamp, fmt="%m-%d %H:%M"):
        return stamp.astimezone(self.zone).strftime(fmt)

    def in_window(self, stamp):
        return self.start <= stamp < self.end

    def wanted(self, session):
        if str(session["session_id"]).lower() in self.exclude:
            self.coverage["sessions_excluded"] += 1
            return False
        if self.projects:
            haystack = ((session["cwd"] or "") + " " + Path(session["path"]).parent.name).lower()
            if not any(p in haystack for p in self.projects):
                self.coverage["sessions_filtered_by_project"] += 1
                return False
        return True

    def run(self):
        retro = self.retro
        for source, path in retro.discover(self.args, self.start, self.end, self.coverage):
            try:
                session = retro.parse_claude(path, self.coverage) if source == "claude" else retro.parse_codex(path, self.coverage)
                calls = [] if session.get("subagent") else skill_calls(retro, source, path, self.known)
            except OSError:
                self.coverage["files_unreadable"] += 1
                continue
            self.coverage["files_scanned"] += 1
            if session.get("subagent"):
                self.coverage["subagent_sessions_skipped"] += 1
                continue
            if not self.wanted(session):
                continue
            events = [e for e in session["events"] if self.in_window(e.ts)]
            if not events:
                continue
            self.one(source, session, events, [c for c in calls if self.in_window(c["ts"])])
        return self.report()

    def one(self, source, session, events, calls):
        retro = self.retro
        file = retro.short_path(session["path"])
        project = project_of(session["cwd"])
        every_user = [e for e in session["events"] if e.kind == "user"]
        users = []
        for event in events:
            if event.kind != "user":
                continue
            if event.uid:
                if event.uid in self.seen_uids:  # 恢复、分叉出来的会话会重复带上之前的消息
                    continue
                self.seen_uids.add(event.uid)
            users.append(event)
        strong = []
        for event in users:
            tags, strength, _ = retro.classify_user_text(event.text)
            if "纠正" in tags and strength == "强":
                strong.append(event)
        calls.sort(key=lambda c: c["line"])
        for index, call in enumerate(calls):
            entry = self.usage[call["name"]]
            entry["calls"] += 1
            entry["sessions"].add(session["session_id"])
            entry["projects"][project] += 1
            entry["how"][call["how"]] += 1
            upper = calls[index + 1]["line"] if index + 1 < len(calls) else float("inf")
            for event in strong:
                if call["line"] < event.line < upper:
                    entry["after"].append({"file": file, "line": event.line, "time": self.local(event.ts, "%Y-%m-%d %H:%M"),
                                           "text": retro.clip(retro.redact(event.text), LATER_LIMIT)})
        if not users:
            self.coverage["sessions_without_human"] += 1
            return
        self.coverage["sessions_" + source] += 1
        tool_calls = [e for e in events if e.kind == "tool_call"]
        footprint = Counter(k for k in (footprint_key(retro, e) for e in tool_calls) if k)
        first = every_user[0]  # 会话的起始请求；窗口前就开始的会话，窗口内第一句往往只是「继续」
        self.sessions.append({
            "source": source, "session_id": session["session_id"], "file": file, "cwd": retro.short_path(session["cwd"] or ""),
            "project": project, "start": events[0].ts, "end": events[-1].ts, "began_before": first.ts < self.start,
            "user_messages": len(users), "tool_calls": len(tool_calls),
            "tool_failures": sum(1 for e in events if e.kind == "tool_result" and e.ok is False),
            "strong_corrections": [{"line": e.line, "text": retro.clip(retro.redact(e.text), LATER_LIMIT)} for e in strong],
            "skills": [c["name"] for c in calls],
            "first": {"line": first.line, "text": retro.clip(retro.redact(first.text), FIRST_LIMIT)},
            "later": [{"line": e.line, "text": retro.clip(retro.redact(e.text), LATER_LIMIT)} for e in users if e is not first][:LATER_MAX],
            "later_more": max(0, len([e for e in users if e is not first]) - LATER_MAX),
            "footprint": footprint.most_common(FOOTPRINT_MAX),
        })

    def report(self):
        per_project = defaultdict(list)
        for item in self.sessions:
            per_project[item["project"]].append(item)
        order = sorted(per_project, key=lambda p: (-sum(i["user_messages"] for i in per_project[p]), p))
        number = 0
        for project in order:
            per_project[project].sort(key=lambda i: i["start"])
            for item in per_project[project]:
                number += 1
                item["id"] = "S%02d" % number
                same_day = self.local(item["start"], "%m-%d") == self.local(item["end"], "%m-%d")
                item["start_local"], item["end_local"] = self.local(item["start"]), self.local(item["end"], "%H:%M" if same_day else "%m-%d %H:%M")
                item["start"], item["end"] = item["start"].isoformat(), item["end"].isoformat()
        usage = []
        for name, entry in sorted(self.usage.items(), key=lambda kv: (-kv[1]["calls"], kv[0])):
            usage.append({"skill": name, "own": bool(self.known.get(name)), "known": name in self.known,
                          "calls": entry["calls"], "sessions": len(entry["sessions"]),
                          "projects": entry["projects"].most_common(), "how": entry["how"].most_common(), "after_corrections": entry["after"]})
        unused = sorted(name for name, own in self.known.items() if own and name not in self.usage)
        coverage = dict(self.coverage)
        gaps = [k for k in ("malformed_lines", "oversized_lines_skipped", "files_unreadable") if coverage.get(k)]
        if coverage.get("roots_missing"):
            gaps.append("roots_missing")
        if coverage.get("codex_zst_unread"):
            gaps.append("codex_zst_unread")
        return {"schema": SCHEMA_VERSION, "projects": order, "sessions": [i for p in order for i in per_project[p]],
                "usage": usage, "unused_own": unused, "coverage": coverage, "gaps": gaps}


def render(result, start_day, end_day):
    cov = result["coverage"]
    sessions = result["sessions"]
    last = end_day - timedelta(days=1)
    lines = ["# skill 进化 · 会话清单（%s 至 %s）" % (start_day.isoformat(), last.isoformat()), "",
             "片段已脱敏并截断，只当线索；要看前后几轮，用 session-retro 的 `context <文件> --line <行号>`。", "",
             "- 有真人发话的会话 %d 个（Claude %d、Codex %d）；没有真人发话的 %d 个（派单、定时任务、应用代发）不列，它们的 skill 调用照算。"
             % (len(sessions), cov.get("sessions_claude", 0), cov.get("sessions_codex", 0), cov.get("sessions_without_human", 0)),
             "- 扫了 %d 个文件。缺口：%s" % (cov.get("files_scanned", 0), "、".join(
                 "%s=%s" % (k, cov[k]) for k in result["gaps"]) if result["gaps"] else "无"),
             "- `codex_zst_unread` 是窗口内已被 Codex 压缩、没读到的记录数（约 8 天以前的会被压缩）；有这一项时，提案开头要写明 Codex 的活没看全。", "",
             "## 一、按项目的会话", ""]
    by_project = defaultdict(list)
    for item in sessions:
        by_project[item["project"]].append(item)
    for project in result["projects"]:
        items = by_project[project]
        lines.append("### %s（%d 个会话，发话 %d 条，强纠正 %d 条）" % (
            project, len(items), sum(i["user_messages"] for i in items), sum(len(i["strong_corrections"]) for i in items)))
        lines.append("")
        for item in items:
            skills = Counter(item["skills"])
            head = "- **%s** %s–%s %s｜发话 %d｜工具 %d｜失败 %d｜强纠正 %d" % (
                item["id"], item["start_local"], item["end_local"], "Claude" if item["source"] == "claude" else "Codex",
                item["user_messages"], item["tool_calls"], item["tool_failures"], len(item["strong_corrections"]))
            if skills:
                head += "｜skill：" + "、".join("%s×%d" % kv for kv in skills.most_common())
            lines.append(head)
            lines.append("  - %s：「%s」（%s:%d）" % ("起始请求（会话始于窗口前）" if item["began_before"] else "首条",
                                                 item["first"]["text"], item["file"], item["first"]["line"]))
            if item["later"]:
                more = "（另有 %d 条）" % item["later_more"] if item["later_more"] else ""
                lines.append("  - 后续：" + " / ".join("「%s」" % m["text"] for m in item["later"]) + more)
            if item["strong_corrections"]:
                lines.append("  - 强纠正：" + " / ".join("「%s」（行 %d）" % (m["text"], m["line"]) for m in item["strong_corrections"][:3]))
            if item["footprint"]:
                lines.append("  - 工具足迹：" + "；".join("%s ×%d" % kv for kv in item["footprint"]))
        lines.append("")
    lines += ["## 二、skill 使用", ""]
    if result["usage"]:
        lines += ["| skill | 归属 | 调用 | 会话 | 项目 | 调用后的强纠正 |", "|---|---|---:|---:|---|---:|"]
        for row in result["usage"]:
            kind = "自建" if row["own"] else ("已装" if row["known"] else "插件或内置")
            lines.append("| %s | %s | %d | %d | %s | %d |" % (
                row["skill"], kind, row["calls"], row["sessions"],
                "、".join("%s×%d" % kv for kv in row["projects"][:4]), len(row["after_corrections"])))
        after = [(row["skill"], item) for row in result["usage"] for item in row["after_corrections"]]
        if after:
            lines += ["", "调用后的强纠正（同一会话里，这次调用之后、下一次 skill 调用之前，用户说的纠正话；不一定是这个 skill 的问题，要看上下文）：", ""]
            lines += ["- `%s`：「%s」（%s:%d，%s）" % (name, item["text"], item["file"], item["line"], item["time"]) for name, item in after]
    else:
        lines.append("窗口内没有认到 skill 调用。")
    lines += ["", "## 三、窗口内没调用的自建 skill", "",
              ("、".join("`%s`" % n for n in result["unused_own"]) if result["unused_own"] else "无"), "",
              "一周没用不说明该退役，去留看月度体检（`node scripts/monthly-health.mjs --days 30`）。这一节只用来对照「该触发没触发」。", ""]
    return "\n".join(lines)


def default_out(start_day, end_day):
    base = Path.home() / "skill-evolution" / ("%s_%s" % (start_day.isoformat(), end_day.isoformat()))
    out, number = base, 1
    while (out / "sessions.json").exists():
        number += 1
        out = base.with_name("%s-%d" % (base.name, number))
    return out


def cmd_scan(args):
    retro = load_retro()
    try:
        zone = ZoneInfo(args.timezone)
        if args.days is not None and args.days < 1:
            raise ValueError("--days 至少 1")
        start, end, start_day, end_day = resolve_window(args, zone)
    except (ValueError, ZoneInfoNotFoundError) as error:
        sys.stderr.write("参数错误：%s\n" % error)
        return 2
    args.claude_root = args.claude_root or [str(Path.home() / ".claude" / "projects")]
    args.codex_root = args.codex_root or [str(Path.home() / ".codex" / "sessions"), str(Path.home() / ".codex" / "archived_sessions")]
    roots = args.skills_root or [SKILLS_DIR, "~/.claude/skills", "~/.agents/skills", "~/.codex/skills"]
    out = Path(args.out).expanduser() if args.out else default_out(start_day, end_day)
    repo = retro.inside_git_repo(out if out.exists() else out.parent)
    if repo and not args.allow_in_repo:
        sys.stderr.write("拒绝写入：%s 在 git 仓库 %s 里，结果可能被误提交。换一个目录，或加 --allow-in-repo。\n" % (out, repo))
        return 2
    scan = Scan(retro, args, start, end, zone, known_skills(roots, args.own_skills_root or SKILLS_DIR))
    if args.source in ("all", "codex"):
        scan.coverage["codex_zst_unread"] = codex_zst_in_window(args.codex_root, start_day, end_day)
    result = scan.run()
    result["window"] = {"start": start_day.isoformat(), "end_exclusive": end_day.isoformat(), "timezone": args.timezone}
    out.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(str(out), 0o700)
    except OSError:
        pass
    retro.write_private(out / "sessions.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    retro.write_private(out / "sessions.md", render(result, start_day, end_day))
    cov = result["coverage"]
    sys.stdout.write("已写入 %s\n窗口 %s 至 %s（不含）；有真人发话的会话 %d 个（Claude %d、Codex %d），没有真人发话的 %d 个；"
                     "skill 调用 %d 次、涉及 %d 个 skill；缺口：%s\n" % (
                         out, start_day, end_day, len(result["sessions"]), cov.get("sessions_claude", 0), cov.get("sessions_codex", 0),
                         cov.get("sessions_without_human", 0), sum(r["calls"] for r in result["usage"]), len(result["usage"]),
                         "、".join(result["gaps"]) or "无"))
    return 3 if result["gaps"] else 0


# ---------------------------------------------------------------- 查提案

ITEM_HEAD = re.compile(r"(?m)^#{2,4}\s*([NE])(\d+)\b.*$")
ANY_HEAD = re.compile(r"(?m)^#{1,4}\s")
SESSION_ID = re.compile(r"\bS\d{2,}\b")
ISSUE_REF = re.compile(r"#\d+")  # 跨周累计：之前记过的候选 issue 顶一次
FIELDS = {"N": ("做什么", "依据", "成熟度", "为什么是 skill", "和现有 skill 的分工", "怎么做", "推荐"),
          "E": ("skill", "问题", "依据", "改法", "推荐")}
MATURITY = ("可立项", "继续观察")


def field_value(block, name):
    found = re.search(r"(?m)^\s*[-*]\s*\*\*%s\*\*\s*[：:]\s*(.*(?:\n(?!\s*[-*]\s*\*\*).*)*)" % re.escape(name), block)
    return found.group(1).strip() if found else None


def check_proposal(text, known_ids):
    problems = []
    heads = list(ITEM_HEAD.finditer(text))
    if len(heads) > MAX_PROPOSALS:
        problems.append("N、E 两类加起来 %d 条，超过上限 %d 条：按「再做一遍的代价 × 出现频率」留最值的，其余写进「筛掉的」。" % (len(heads), MAX_PROPOSALS))
    for head in heads:
        kind, label = head.group(1), head.group(1) + head.group(2)
        following = ANY_HEAD.search(text, head.end())
        block = text[head.end(): following.start() if following else len(text)]
        line = text.count("\n", 0, head.start()) + 1
        values = {}
        for name in FIELDS[kind]:
            values[name] = field_value(block, name)
            if not values[name]:
                problems.append("第 %d 行 %s：缺「%s」，应写成一行「- **%s**：……」。" % (line, label, name, name))
        cited = set(SESSION_ID.findall(values.get("依据") or ""))
        if values.get("依据") and not cited:
            problems.append("第 %d 行 %s：「依据」里没有会话编号，应写出 sessions.md 里的编号（如 S03、S11）。" % (line, label))
        if kind == "N" and values.get("成熟度"):
            level = next((m for m in MATURITY if values["成熟度"].startswith(m)), None)
            if not level:
                problems.append("第 %d 行 %s：「成熟度」只能以「可立项」或「继续观察」开头。" % (line, label))
            elif level == "可立项" and len(cited) + (1 if ISSUE_REF.search(values.get("依据") or "") else 0) < 2:
                problems.append("第 %d 行 %s：写了「可立项」，但依据里只有 %d 个会话。至少真做过两次才能立项（my-skills 闸 1），"
                                "应改成「继续观察」，或补上第二个会话编号、之前记过的候选 issue 号（#123）。" % (line, label, len(cited)))
    for found in SESSION_ID.finditer(text):
        if found.group(0) not in known_ids:
            problems.append("第 %d 行：会话编号 %s 在 sessions.json 里没有。" % (text.count("\n", 0, found.start()) + 1, found.group(0)))
    return problems


def cmd_check(args):
    path = Path(args.proposal).expanduser()
    data = Path(args.sessions).expanduser() if args.sessions else path.parent / "sessions.json"
    try:
        text = path.read_text(encoding="utf-8")
        known_ids = set(item["id"] for item in json.loads(data.read_text(encoding="utf-8"))["sessions"])
    except (OSError, ValueError, KeyError) as error:
        sys.stderr.write("读不了：%s\n" % error)
        return 2
    problems = check_proposal(text, known_ids)
    if not problems:
        sys.stdout.write("通过：%d 条提案，会话编号都对得上。\n" % len(ITEM_HEAD.findall(text)))
        return 0
    sys.stdout.write("\n".join(problems) + "\n")
    return 1


def build_parser():
    parser = argparse.ArgumentParser(description="skill 进化：整理会话清单和 skill 使用表；查提案。")
    sub = parser.add_subparsers(dest="command")
    scan = sub.add_parser("scan", help="整理时间窗口里的会话清单和 skill 使用表，写 sessions.md 与 sessions.json")
    scan.add_argument("--start", help="开始日期 YYYY-MM-DD（含）。不给 --start 和 --days 时，默认上一个完整自然周（周一到周日）")
    scan.add_argument("--end", help="结束日期 YYYY-MM-DD（不含），默认开始日期后 7 天")
    scan.add_argument("--days", type=int, help="最近几天（含今天），和 --start 二选一")
    scan.add_argument("--timezone", default="Asia/Shanghai", help="IANA 时区，默认 Asia/Shanghai")
    scan.add_argument("--source", choices=("all", "claude", "codex"), default="all")
    scan.add_argument("--project", action="append", help="只看工作目录包含这段文字的会话，可重复，不区分大小写")
    scan.add_argument("--claude-root", action="append", help="Claude Code 会话根目录，默认 ~/.claude/projects")
    scan.add_argument("--codex-root", action="append", help="Codex 会话根目录，默认 ~/.codex/sessions 和 ~/.codex/archived_sessions")
    scan.add_argument("--skills-root", action="append", help="已装 skill 的目录，可重复；默认 my-skills/skills、~/.claude/skills、~/.agents/skills、~/.codex/skills")
    scan.add_argument("--own-skills-root", help="自建 skill 的目录，真实路径在它下面的算自建；默认 my-skills/skills")
    scan.add_argument("--exclude-session", action="append", help="排除的会话 ID（比如正在做复盘的这个会话），可重复")
    scan.add_argument("--out", help="输出目录，默认 ~/skill-evolution/<开始>_<结束>/；已有结果时自动写到 -2、-3")
    scan.add_argument("--allow-in-repo", action="store_true", help="允许输出到 git 仓库里（默认拒绝，防止误提交）")
    scan.set_defaults(func=cmd_scan)
    check = sub.add_parser("check", help="查提案：会话编号、必填项、「可立项」的依据、条数上限")
    check.add_argument("proposal", help="提案.md 的路径")
    check.add_argument("--sessions", help="sessions.json 的路径，默认和提案同目录")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
