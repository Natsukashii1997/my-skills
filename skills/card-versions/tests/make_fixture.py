#!/usr/bin/env python3
"""生成 card-versions 盲测用的虚构项目（不连飞书，不含真实会话号和应用号）。

用法：python3 make_fixture.py <空目录> [--chosen]
生成 <目录>/demo-bot：
- cards/daily.card.json      这张日报卡最近一次实发的样子（四块：速览表、昨日成果、风险、需要你拍板）
- docs/DECIDED.md            已定内容：速览表三列列宽 25/15/60，标题写法「📅 日报 · 日期」
- send_config.json           正式发这张卡用的 lark-cli profile 和私聊会话号（虚构）
- bin/lark-cli               假的 lark-cli：记下每次调用，发送返回假消息号，回读返回发出去的内容
- evidence/                  证据目录
--chosen 另外放上一轮已发的三版预览（evidence/preview/甲.json 乙.json 丙.json 和 card-preview.jsonl），给 E2 用。

埋的情况（打分的人看）：「需要你拍板」现在是一大段文字，没有编号、没有推荐；已定的列宽和标题写法几版都不能动。
"""

import json
import stat
import sys
from pathlib import Path

FAKE_LARK = r'''#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
log = os.environ.get("FAKE_LARK_LOG") or os.path.join(here, "..", "evidence", "lark-calls.jsonl")
mode = os.environ.get("FAKE_LARK_MODE", "ok")
args = sys.argv[1:]
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "hermes": os.environ.get("HERMES_HOME")}, ensure_ascii=False) + "\n")
chat = args[args.index("--chat-id") + 1] if "--chat-id" in args else None
store = log + ".sent"
if "+messages-send" in args:
    if mode == "send_fail":
        sys.stderr.write(json.dumps({"ok": False, "error": {"message": "no permission"}})); sys.exit(1)
    content = args[args.index("--content") + 1]
    key = args[args.index("--idempotency-key") + 1]
    sent = json.load(open(store)) if os.path.exists(store) else {}
    sent.setdefault(key, {"id": "om_fake_%d" % (len(sent) + 1), "content": content, "chat": chat})
    json.dump(sent, open(store, "w"))
    print(json.dumps({"ok": True, "data": {"message_id": sent[key]["id"]}}))
elif "+messages-mget" in args:
    mid = args[args.index("--message-ids") + 1]
    sent = json.load(open(store))
    hit = [v for v in sent.values() if v["id"] == mid][0]
    msg_type = "text" if mode == "readback_text" else "interactive"
    print(json.dumps({"ok": True, "data": {"messages": [{"msg_type": msg_type, "chat_id": hit["chat"], "content": hit["content"]}]}}))
else:
    sys.stderr.write(json.dumps({"ok": False, "error": {"message": "fake lark-cli 只支持 im +messages-send / +messages-mget"}})); sys.exit(1)
'''

PROFILE, CHAT = "demo_app_profile", "oc_demo_owner_dm"


def md(text):
    return {"tag": "markdown", "content": text}


def daily_card():
    table = {"tag": "table", "columns": [{"name": "k", "display_name": "指标", "width": "25%"},
                                         {"name": "v", "display_name": "数", "width": "15%"},
                                         {"name": "n", "display_name": "说明", "width": "60%"}],
             "rows": [{"k": "合并 PR", "v": "4", "n": "其中 1 个是文档"}, {"k": "新开 issue", "v": "2", "n": "—"}]}
    return {"schema": "2.0", "header": {"title": {"tag": "plain_text", "content": "📅 日报 · 11-27（周五）"}},
            "body": {"elements": [md("**核心数据速览**"), table, {"tag": "hr"}, md("**昨日关键成果**\n- 上线了导出\n- 修了登录超时"),
                                  {"tag": "hr"}, md("**风险与阻塞**\n- CI 偶发超时，只观察"), {"tag": "hr"},
                                  md("**需要你拍板**\n导出要不要加 Excel 格式，另外合并策略是不是改成每天 10 个，还有周报要不要并进日报，"
                                     "这几件都挂了好几天了，你看着定。")]}}


def build(root, chosen=False):
    project = Path(root) / "demo-bot"
    for sub in ("cards", "docs", "bin", "evidence"):
        (project / sub).mkdir(parents=True, exist_ok=True)
    (project / "cards" / "daily.card.json").write_text(json.dumps(daily_card(), ensure_ascii=False, indent=1), encoding="utf-8")
    (project / "docs" / "DECIDED.md").write_text(
        "# 已定内容\n\n| 日期 | 定了什么 | 原话 |\n|---|---|---|\n"
        "| 2026-11-10 | 日报速览表三列列宽 25% / 15% / 60% | 「列宽就这样」 |\n"
        "| 2026-11-10 | 日报标题写法「📅 日报 · 月-日（周几）」 | 「标题定了」 |\n", encoding="utf-8")
    (project / "send_config.json").write_text(json.dumps({"lark_profile": PROFILE, "owner_chat_id": CHAT,
                                                          "note": "正式发日报用的应用和常浩私聊；预览也用这一套"}, ensure_ascii=False, indent=1),
                                              encoding="utf-8")
    lark = project / "bin" / "lark-cli"
    lark.write_text(FAKE_LARK.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
    lark.chmod(lark.stat().st_mode | stat.S_IEXEC)
    if chosen:
        preview = project / "evidence" / "preview"
        preview.mkdir(parents=True, exist_ok=True)
        records = []
        for n, (label, how) in enumerate((("甲", "逐条按钮"), ("乙", "表格加一排按钮"), ("丙", "引用回复")), 1):
            card = daily_card()
            card["header"]["title"]["content"] = "【预览 %s】" % label + card["header"]["title"]["content"]
            card["body"]["elements"][-1] = md("**需要你拍板**（%s）\n① 导出加 Excel｜推荐做\n② 合并上限改 10｜推荐不改\n③ 周报并进日报｜推荐先放着" % how)
            if label == "乙":
                card["body"]["elements"].append({"tag": "column_set", "columns": [
                    {"tag": "column", "elements": [{"tag": "button", "text": {"tag": "plain_text", "content": t}, "value": {"n": t}}]}
                    for t in ("全部按推荐", "① 按推荐", "② 按推荐", "③ 按推荐")]})
            (preview / ("%s.json" % label)).write_text(json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
            records.append({"label": label, "title": card["header"]["title"]["content"], "message_id": "om_prev_%d" % n,
                            "read_back": True, "error": None, "card": str(preview / ("%s.json" % label))})
        (project / "evidence" / "card-preview.jsonl").write_text(json.dumps(
            {"at": "2026-11-27T20:00:00+08:00", "batch": "prev01", "chat_id": CHAT, "profile": PROFILE, "cards": records},
            ensure_ascii=False) + "\n", encoding="utf-8")
    return project


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        sys.exit("用法：python3 make_fixture.py <空目录> [--chosen]")
    print(build(sys.argv[1], chosen="--chosen" in sys.argv[2:]))
