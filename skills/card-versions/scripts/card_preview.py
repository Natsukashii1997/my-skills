#!/usr/bin/env python3
"""飞书卡片几版预览：检查卡片 JSON，把几版真卡片以机器人身份发到常浩私聊并回读。

check  只看卡片：有没有标题、正文组件数会不会超飞书上限、按钮有没有回调值。不联网。
send   给每张卡的标题加上【预览 甲】这样的前缀，经 lark-cli 发出，逐张回读核对（是卡片、在这个会话里、标题对得上），
       记一行到 <证据目录>/card-preview.jsonl。同一批重跑时用同一个幂等键，不会重复发。

飞书应用（lark-cli 的 profile）和私聊会话号不写在这里，每次由调用方给：用项目里正式发这张卡的脚本用的那一套。
只用 Python 标准库。
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LIMIT, WARN_AT = 199, 180      # 飞书卡片正文组件上限：2026-11-21 数字分身托管单实测 199
AGENT_ENV = ("HERMES", "OPENCLAW", "LARK_CHANNEL")  # lark-cli 看到这些变量会改读另一套配置，调用前去掉
LARK_TIMEOUT = 60
LABELS = ("甲", "乙", "丙", "丁", "戊")


class SendError(Exception):
    pass


# ---------------------------------------------------------------- 看卡片

def title_of(card):
    header = card.get("header") if isinstance(card.get("header"), dict) else {}
    title = header.get("title") if isinstance(header.get("title"), dict) else {}
    return title.get("content") if isinstance(title.get("content"), str) else None


def body_elements(card):
    body = card.get("body") if isinstance(card.get("body"), dict) else None
    if body is not None and isinstance(body.get("elements"), list):
        return body["elements"]
    return card.get("elements") if isinstance(card.get("elements"), list) else []


def walk(node):
    """正文里每一个组件（带 tag 的对象），含折叠面板、分栏里面的。"""
    if isinstance(node, dict):
        if "tag" in node:
            yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk(item)


def inspect(card):
    """返回 (问题, 提醒)：问题会让 send 拒发，提醒只打印。"""
    problems, notes = [], []
    if not isinstance(card, dict):
        return ["不是 JSON 对象"], notes
    if not title_of(card):
        problems.append("没有标题（header.title.content），预览分不清是哪一版")
    components = [n for n in walk(body_elements(card))]
    count = len(components)
    if count > LIMIT:
        problems.append("正文组件 %d 个，超过飞书上限 %d，发出去会报错或被截断" % (count, LIMIT))
    elif count >= WARN_AT:
        notes.append("正文组件 %d 个，接近上限 %d，内容再多一点就发不出去" % (count, LIMIT))
    buttons = [n for n in components if n.get("tag") == "button"]
    live = [b for b in buttons if b.get("behaviors") or b.get("value")]
    if buttons:
        notes.append("有 %d 个按钮（%d 个带回调值）；预览卡上的按钮点了不会有真实效果，回复里要写明" % (len(buttons), len(live)))
    return problems, notes


def load_card(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SendError("读不了卡片 %s：%s" % (path, error))


def with_label(card, label):
    """标题前加【预览 甲】；已经带了就不重复加。"""
    card = json.loads(json.dumps(card))
    title = title_of(card)
    mark = "【预览 %s】" % label
    if not title.startswith(mark):
        card["header"]["title"]["content"] = mark + title
    return card


# ---------------------------------------------------------------- 发送

def lark(lark_cli, profile, args):
    env = {k: v for k, v in os.environ.items() if not k.lstrip("_").startswith(AGENT_ENV)}
    cmd = [lark_cli, "--profile", profile] + args + ["--as", "bot", "--format", "json"]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=LARK_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        raise SendError("lark-cli 跑不起来（%s）" % type(error).__name__)
    data = None
    for raw in (done.stdout, done.stderr):  # lark-cli 的错误 JSON 走 stderr
        try:
            data = json.loads(raw)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        raise SendError("lark-cli 输出不是 JSON（退出码 %d）" % done.returncode)
    if not data.get("ok", True):
        message = (data.get("error") or {}).get("message", "未知错误") if isinstance(data.get("error"), dict) else data.get("error")
        raise SendError("lark-cli 报错：%s" % str(message)[:200])
    return data.get("data") or {}


def send_one(args, card, label, batch):
    text = json.dumps(card, ensure_ascii=False)
    record = {"label": label, "title": title_of(card), "message_id": None, "read_back": False, "error": None}
    try:
        data = lark(args.lark_cli, args.profile, ["im", "+messages-send", "--chat-id", args.chat_id, "--msg-type", "interactive",
                                                  "--content", text, "--idempotency-key", "card-preview-%s-%s" % (batch, label)])
        record["message_id"] = data.get("message_id")
        if not record["message_id"]:
            raise SendError("发出去了但没拿到消息号")
        got = lark(args.lark_cli, args.profile, ["im", "+messages-mget", "--message-ids", record["message_id"]])
        message = (got.get("messages") or [{}])[0]
        checks = {
            "是卡片": message.get("msg_type") == "interactive",
            "在这个会话里": message.get("chat_id") == args.chat_id,  # 2026-11-28 实测回读结果带 chat_id
            "标题对得上": record["title"] in str(message.get("content")),
        }
        record["read_back"] = all(checks.values())
        if not record["read_back"]:
            record["error"] = "回读对不上：" + "、".join(k for k, ok in checks.items() if not ok)
    except SendError as error:
        record["error"] = str(error)
    return record


def cmd_check(args):
    worst = 0
    for path in args.card:
        try:
            problems, notes = inspect(load_card(path))
        except SendError as error:
            problems, notes = [str(error)], []
        status = "不能发" if problems else "可以发"
        sys.stdout.write("%s：%s\n" % (path, status))
        for line in problems:
            sys.stdout.write("  - 问题：%s\n" % line)
        for line in notes:
            sys.stdout.write("  - 提醒：%s\n" % line)
        worst = max(worst, 1 if problems else 0)
    return worst


def cmd_send(args):
    if len(args.card) > len(LABELS):
        sys.stderr.write("一次最多 %d 版\n" % len(LABELS))
        return 2
    labels = args.label or list(LABELS[: len(args.card)])
    if len(labels) != len(args.card):
        sys.stderr.write("--label 的个数要和 --card 一样多\n")
        return 2
    cards = []
    for path, label in zip(args.card, labels):
        try:
            card = load_card(path)
        except SendError as error:
            sys.stderr.write("%s\n" % error)
            return 2
        problems, _ = inspect(card)
        if problems:
            sys.stderr.write("%s 不能发：%s\n" % (path, "；".join(problems)))
            return 2
        cards.append((path, label, with_label(card, label)))
    digest = hashlib.sha256(json.dumps([c for _, _, c in cards], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    batch = args.batch or digest[:12]
    if args.dry_run:
        for path, label, card in cards:
            sys.stdout.write("会发：%s → %s（幂等键 card-preview-%s-%s）\n" % (path, title_of(card), batch, label))
        return 0
    records = [dict(send_one(args, card, label, batch), card=str(path)) for path, label, card in cards]
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    line = {"at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), "batch": batch, "chat_id": args.chat_id,
            "profile": args.profile, "cards": records}
    with open(str(out / "card-preview.jsonl"), "a", encoding="utf-8") as stream:
        stream.write(json.dumps(line, ensure_ascii=False) + "\n")
    sys.stdout.write(json.dumps({"batch": batch, "cards": records}, ensure_ascii=False, indent=1) + "\n")
    return 0 if all(r["read_back"] for r in records) else 1


def build_parser():
    parser = argparse.ArgumentParser(description="飞书卡片几版预览：检查卡片，发到私聊并回读。")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="只看卡片：标题、组件数、按钮")
    check.add_argument("card", nargs="+", help="卡片 JSON 文件")
    check.set_defaults(func=cmd_check)
    send = sub.add_parser("send", help="给标题加【预览 X】，发到私聊并逐张回读")
    send.add_argument("--card", action="append", required=True, help="卡片 JSON 文件，按甲乙丙的顺序给，可重复")
    send.add_argument("--label", action="append", help="每版的名字，默认甲、乙、丙……")
    send.add_argument("--profile", required=True, help="lark-cli 的 profile：项目正式发这张卡用的那个飞书应用")
    send.add_argument("--chat-id", required=True, help="常浩和这个机器人的私聊会话号（oc_ 开头）")
    send.add_argument("--out", required=True, help="证据目录（项目约定的持久目录），发送记录追加到 card-preview.jsonl")
    send.add_argument("--batch", help="这一批的编号，默认按卡片内容算；同一批重跑不会重复发")
    send.add_argument("--lark-cli", default="lark-cli", help="lark-cli 的路径，默认 lark-cli")
    send.add_argument("--dry-run", action="store_true", help="只打印会发什么，不发")
    send.set_defaults(func=cmd_send)
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
