#!/usr/bin/env python3
"""拍板清单：找出 Claude 桌面应用里停在「等你」的会话，转达前复核，转达后回读。

只读本机文件，只用标准库，不联网，不给任何会话发消息。
子命令：collect（收集）、recheck（转达前复核）、readback（转达后回读）、ignore（忽略名单）。
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import datetime

HOME = os.path.expanduser("~")
META_DIR = HOME + "/Library/Application Support/Claude/claude-code-sessions"
PROJECTS_DIR = HOME + "/.claude/projects"
INBOX_DIR = HOME + "/Library/Application Support/agent-kit/decision-inbox"

WAITING = ("等你决定", "等你操作", "受阻")
STATUS = re.compile(r"当前状态\*{0,2}[：:]\s*\*{0,2}〔(.+?)〕(.*)")
NEXT = re.compile(r"下一步\*{0,2}[：:]\s*(.+)")
# 不是用户本人打的字：宿主注入的提醒、后台任务通知、压缩续接说明等。
NOT_USER = (
    "<system-reminder>",
    "<task-notification>",
    "<side-sessions-event>",
    "<ci-monitor-event>",
    "This session is being continued",
    "[Request interrupted",
    "The app was quit",
)
BUSY_SECONDS = 180
# 别的会话发来的消息：可能是转达的答复，也可能只是通知，不能当作常浩已经回复。
PEER = "Another Claude session sent a message"
# 回复过了这么久还没出新状态，多半是没被接走，要重新列出来。
STALE_REPLY_HOURS = 2


def texts(message):
    content = message.get("content")
    if isinstance(content, str):
        return [content]
    return [
        block.get("text", "")
        for block in content or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]


def user_words(entry):
    """这一行如果是用户本人（或别的会话代转）的话，返回文字；否则返回 None。"""
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("isMeta"):
        return None
    if entry.get("turnOrigin") == "host_synthetic":
        return None
    text = "\n".join(texts(entry.get("message", {}))).strip()
    if not text or text.startswith(NOT_USER):
        return None
    return text


def read_log(path):
    """返回（最后一次带「当前状态」的答复，其后的用户消息，读不了的行数）。"""
    last, after, bad = None, [], 0
    with open(path, errors="replace") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if entry.get("isSidechain"):
                continue
            if entry.get("type") == "assistant":
                for text in texts(entry.get("message", {})):
                    # 取这条答复里最后一次出现的状态行：正文里可能先引用了别的会话的状态。
                    marks = list(STATUS.finditer(text))
                    if not marks:
                        continue
                    found = marks[-1]
                    step = NEXT.search(text, found.end())
                    last = {
                        "at": entry.get("timestamp") or "",
                        "word": found.group(1).strip(),
                        "status": found.group(2).strip()[:300],
                        "next": (step.group(1).strip() if step else "")[:400],
                    }
                    after = []
            else:
                words = user_words(entry)
                if words and last:
                    after.append(
                        {
                            "at": entry.get("timestamp") or "",
                            "text": words[:160],
                            "peer": words.startswith(PEER),
                        }
                    )
    return last, after, bad


def short(session_id):
    return session_id.replace("local_", "")[:8]


def local_time(stamp):
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    return moment.astimezone().strftime("%m-%d %H:%M")


def days_since(stamp, now):
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((now - moment.timestamp()) / 86400, 1)


def load_ignored(inbox_dir):
    path = os.path.join(inbox_dir, "ignore.json")
    if not os.path.exists(path):
        return {}
    with open(path) as handle:
        return {item["id"]: item for item in json.load(handle).get("items", [])}


def listed_before(inbox_dir):
    """最近一份清单里出现过的会话 id（前 8 位）。"""
    # 按修改时间取最新一份：同一天的第二份叫「…-2.md」，按文件名排会排到第一份前面。
    lists = sorted(glob.glob(os.path.join(inbox_dir, "拍板清单-*.md")), key=os.path.getmtime)
    if not lists:
        return None, set()
    with open(lists[-1], errors="replace") as handle:
        body = handle.read()
    return os.path.basename(lists[-1]), set(re.findall(r"local_([0-9a-f]{8})\b", body))


def scan(meta_dir, projects_dir, days, now, only=None):
    """读会话元数据和记录，返回（所有带状态行的会话，跳过的计数）。"""
    logs = {
        os.path.basename(path)[: -len(".jsonl")]: path
        for path in glob.glob(os.path.join(projects_dir, "*", "*.jsonl"))
    }
    metas = []
    for path in glob.glob(os.path.join(meta_dir, "**", "local_*.json"), recursive=True):
        try:
            with open(path) as handle:
                metas.append(json.load(handle))
        except (ValueError, OSError):
            continue
    children = {}
    for meta in metas:
        parent = (meta.get("spawnedFrom") or {}).get("sessionId")
        if parent and not meta.get("isArchived"):
            children.setdefault(parent, []).append(meta)
    rows = []
    skipped = {"已归档": 0, "太久没动": 0, "找不到记录": 0, "没写状态行": 0, "坏行": 0}
    for meta in metas:
        session_id = meta.get("sessionId", "")
        if only is not None and short(session_id) not in only:
            continue
        if meta.get("isArchived"):
            skipped["已归档"] += 1
            continue
        log = next(
            (
                logs[meta[key]]
                for key in ("lastAssistantCliSessionId", "cliSessionId")
                if meta.get(key) in logs
            ),
            None,
        )
        if not log:
            skipped["找不到记录"] += 1
            continue
        written = os.path.getmtime(log)
        if now - written > days * 86400:
            skipped["太久没动"] += 1
            continue
        last, after, bad = read_log(log)
        skipped["坏行"] += bad
        if not last:
            skipped["没写状态行"] += 1
            continue
        cwd = meta.get("cwd") or ""
        rows.append(
            {
                "id": session_id,
                "id8": short(session_id),
                "title": meta.get("title") or "（无标题）",
                "project": "（无文件夹）"
                if "scratch-workspaces" in cwd
                else os.path.basename(cwd.rstrip("/")),
                "word": last["word"],
                "status": last["status"],
                "next": last["next"],
                "statusAt": last["at"],
                "stoppedDays": days_since(last["at"], now),
                "busy": (now - written) < BUSY_SECONDS,
                "userAfter": after[-2:],
                "prs": [
                    {"n": pr.get("prNumber"), "state": pr.get("state")}
                    for pr in meta.get("prs") or []
                ],
                "parent": short((meta.get("spawnedFrom") or {}).get("sessionId") or ""),
                "children": [
                    {"id8": short(child["sessionId"]), "title": child.get("title")}
                    for child in children.get(session_id, [])
                ],
            }
        )
    rows.sort(key=lambda row: row["statusAt"], reverse=True)
    return rows, skipped


def sift(rows, ignored, before, now=None):
    """去假：返回（留下的，筛掉的计数）。"""
    now = now or time.time()
    dropped = {"已交给下游会话": 0, "你已回复、还在做": 0, "在忽略名单里": 0}
    kept = []
    for row in rows:
        if row["word"] not in WAITING:
            continue
        if row["children"]:
            dropped["已交给下游会话"] += 1
            continue
        own = [reply for reply in row["userAfter"] if not reply.get("peer")]
        row["peerAfter"] = len(own) < len(row["userAfter"])
        row["replyUnanswered"] = False
        if own:
            waited = days_since(own[-1]["at"], now)
            if waited is None or waited * 24 < STALE_REPLY_HOURS:
                dropped["你已回复、还在做"] += 1
                continue
            row["replyUnanswered"] = True
        mark = ignored.get(row["id"])
        if mark and mark.get("statusAt") == row["statusAt"]:
            dropped["在忽略名单里"] += 1
            continue
        row["prDone"] = bool(row["prs"]) and all(
            pr["state"] in ("MERGED", "CLOSED") for pr in row["prs"]
        )
        row["listedBefore"] = row["id8"] in before
        kept.append(row)
    return kept, dropped


def render(kept, dropped, skipped, total_waiting, last_list):
    lines = [
        f"# 拍板清单候选（{time.strftime('%Y-%m-%d %H:%M')}）",
        "",
        f"停在「等你」的会话 {total_waiting} 个；筛掉 "
        + "、".join(f"{name} {count}" for name, count in dropped.items())
        + f"；留下 {len(kept)} 个。",
        "没看的：" + "、".join(f"{name} {count}" for name, count in skipped.items()) + "。",
        f"上一份清单：{last_list or '没有'}。",
        "",
        "这是候选，不是清单：下面每条还要人工判断（见 SKILL.md 第 2、3 节）。",
        "",
        "## 上一份清单里没有的",
    ]
    fresh = [row for row in kept if not row["listedBefore"]]
    seen = [row for row in kept if row["listedBefore"]]
    for row in fresh:
        flags = flag_text(row)
        lines += [
            "",
            f"### {row['title']}",
            f"- 会话：`{row['id']}`｜项目：{row['project']}｜〔{row['word']}〕"
            f"｜停在 {local_time(row['statusAt'])}（{row['stoppedDays']} 天）{flags}",
            f"- 状态：{row['status']}",
            f"- 下一步：{row['next']}",
        ]
    lines += ["", "## 上一份清单里已经有的（只列一行）", ""]
    for row in seen:
        lines.append(
            f"- `{row['id']}` {row['title']}｜〔{row['word']}〕｜{row['stoppedDays']} 天"
            f"{flag_text(row)}｜{row['next'][:70]}"
        )
    return "\n".join(lines) + "\n"


def flag_text(row):
    flags = []
    if row.get("prDone"):
        flags.append("PR 都已合并或关闭，可能过期")
    if row["busy"]:
        flags.append("3 分钟内有写入，可能正在跑")
    if row.get("replyUnanswered"):
        flags.append(f"你回过，但超过 {STALE_REPLY_HOURS} 小时没出新状态，可能没被接走")
    if row.get("peerAfter"):
        flags.append("之后收到过别的会话的消息")
    if row["prs"]:
        names = {"OPEN": "开着", "MERGED": "已合并", "CLOSED": "已关闭"}
        flags.append(
            "PR " + "、".join(f"#{pr['n']} {names.get(pr['state'], pr['state'])}" for pr in row["prs"])
        )
    return "｜" + "；".join(flags) if flags else ""


def cmd_collect(args):
    now = time.time()
    rows, skipped = scan(args.meta_dir, args.projects_dir, args.days, now)
    last_list, before = listed_before(args.inbox_dir)
    kept, dropped = sift(rows, load_ignored(args.inbox_dir), before, now)
    total = sum(1 for row in rows if row["word"] in WAITING)
    out = args.out or os.path.join(args.inbox_dir, "runs", time.strftime("%Y-%m-%d-%H%M"))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "waiting.json"), "w") as handle:
        json.dump(
            {"generatedAt": time.strftime("%F %T"), "skipped": skipped, "rows": rows},
            handle,
            ensure_ascii=False,
            indent=1,
        )
    with open(os.path.join(out, "candidates.md"), "w") as handle:
        handle.write(render(kept, dropped, skipped, total, last_list))
    print(f"等你 {total}｜筛掉 {dropped}｜留下 {len(kept)}｜没看 {skipped}")
    print(os.path.join(out, "candidates.md"))
    return 0


def load_snapshot(path):
    with open(path) as handle:
        return {row["id8"]: row for row in json.load(handle)["rows"]}


def compare(args, now):
    before = load_snapshot(args.since)
    ids = [short(item) for item in args.ids]
    unknown = [item for item in ids if item not in before]
    if unknown:
        raise SystemExit("快照里没有这些会话：" + " ".join(unknown))
    rows, _ = scan(args.meta_dir, args.projects_dir, 3650, now, only=set(ids))
    current = {row["id8"]: row for row in rows}
    result = []
    for item in ids:
        old, new = before[item], current.get(item)
        if new is None:
            result.append((item, old, None, "找不到了（可能已归档）"))
        elif new["statusAt"] != old["statusAt"]:
            result.append((item, old, new, "出了新状态"))
        elif new["userAfter"] and new["userAfter"][-1:] != old["userAfter"][-1:]:
            result.append((item, old, new, "收到了新消息，还没出新状态"))
        else:
            result.append((item, old, new, ""))
    return result


def cmd_recheck(args):
    result = compare(args, time.time())
    changed = 0
    for item, old, new, why in result:
        if why:
            changed += 1
            print(f"变了 {old['id']} {old['title']}：{why}")
            if new and new["statusAt"] != old["statusAt"]:
                print(f"    现在〔{new['word']}〕{new['status'][:120]}")
                print(f"    下一步：{new['next'][:200]}")
        else:
            print(f"没变 {old['id']} {old['title']}")
    print(f"共 {len(result)} 个，变了 {changed} 个。变了的不要转达，把新问题报给常浩。")
    return 4 if changed else 0


def cmd_readback(args):
    deadline = time.time() + args.wait
    while True:
        result = compare(args, time.time())
        moved = [entry for entry in result if entry[3] == "出了新状态"]
        if len(moved) == len(result) or time.time() >= deadline:
            break
        time.sleep(30)
    print(f"{time.strftime('%H:%M')} 已出新状态 {len(moved)} / {len(result)}")
    for item, old, new, why in result:
        if why == "出了新状态":
            print(f"\n{old['id']} {old['title']}\n  〔{new['word']}〕{new['status'][:200]}")
            print(f"  下一步：{new['next'][:260]}")
        else:
            note = why or "还没动静"
            busy = "，3 分钟内有写入" if new and new["busy"] else ""
            print(f"\n{old['id']} {old['title']}\n  {note}{busy}")
    return 0


def cmd_ignore(args):
    path = os.path.join(args.inbox_dir, "ignore.json")
    items = list(load_ignored(args.inbox_dir).values())
    if args.action == "list":
        for item in items:
            print(f"{item['id']} {item.get('title')}｜{item.get('addedOn')}｜{item.get('by')}")
        print(f"共 {len(items)} 个")
        return 0
    if not (args.since and args.ids and args.by):
        raise SystemExit("ignore add 需要 --since、--ids 和 --by（常浩哪天、原话是什么）")
    snapshot = load_snapshot(args.since)
    added = 0
    for item in dict.fromkeys(short(value) for value in args.ids):
        if item not in snapshot:
            raise SystemExit(f"快照里没有这个会话：{item}")
        row = snapshot[item]
        items = [entry for entry in items if entry["id"] != row["id"]]
        items.append(
            {
                "id": row["id"],
                "title": row["title"],
                "statusAt": row["statusAt"],
                "addedOn": time.strftime("%Y-%m-%d"),
                "by": args.by,
            }
        )
        added += 1
    os.makedirs(args.inbox_dir, exist_ok=True)
    with open(path, "w") as handle:
        json.dump({"version": 1, "items": items}, handle, ensure_ascii=False, indent=1)
    print(f"记了 {added} 个，名单里共 {len(items)} 个：{path}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--meta-dir", default=META_DIR, help="桌面应用会话元数据目录")
    parser.add_argument("--projects-dir", default=PROJECTS_DIR, help="会话记录目录")
    parser.add_argument("--inbox-dir", default=INBOX_DIR, help="清单和忽略名单存放目录")
    commands = parser.add_subparsers(dest="command", required=True)

    collect = commands.add_parser("collect", help="收集停在「等你」的会话，出候选")
    collect.add_argument("--days", type=float, default=14, help="只看最近几天动过的会话")
    collect.add_argument("--out", help="输出目录，默认 <inbox-dir>/runs/<时间>")
    collect.set_defaults(run=cmd_collect)

    for name, run, text in (
        ("recheck", cmd_recheck, "转达前复核：这些会话的问题变了没有"),
        ("readback", cmd_readback, "转达后回读：这些会话出新状态了没有"),
    ):
        sub = commands.add_parser(name, help=text)
        sub.add_argument("--since", required=True, help="collect 写下的 waiting.json")
        sub.add_argument("--ids", nargs="+", required=True, help="会话 id 或前 8 位")
        if name == "readback":
            sub.add_argument("--wait", type=float, default=0, help="最多等多少秒")
        sub.set_defaults(run=run)

    ignore = commands.add_parser("ignore", help="忽略名单：以后不再列，会话又动了会重新列")
    ignore.add_argument("action", choices=("add", "list"))
    ignore.add_argument("--since", help="collect 写下的 waiting.json")
    ignore.add_argument("--ids", nargs="+", help="会话 id 或前 8 位")
    ignore.add_argument("--by", help="谁、哪天、原话，例如：常浩 2026-11-20 回「F 组记忽略」")
    ignore.set_defaults(run=cmd_ignore)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
