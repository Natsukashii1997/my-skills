#!/usr/bin/env python3
"""生成一周的合成会话样例（2026-11-02 周一 至 2026-11-08 周日），测试和 evals 共用。不含任何真实会话。

用法：python3 make_fixture.py <目录>
生成：<目录>/claude（Claude Code 记录）、<目录>/codex（Codex 记录）、<目录>/skills（四个已装 skill）。

里面埋了这些情况：
- 「项目推进」同一套做法出现在 3 个会话里（收集飞书需求 → 拉最新进度 → 按三个维度写推进说明），第 3 次被纠正；
- 表格美化出现 2 次，都没调用已装的 excel-aura；
- ui-styles 调用后紧跟一句纠正；另一次用斜杠命令调用；
- 一次性的小事 1 件；窗口前就开始的会话 1 个；没有真人发话的派单会话 1 个；Codex 会话 1 个。
"""

import json
import sys
from pathlib import Path

WORK = "/Users/tester/work"
# 假密钥运行时拼出来，仓库里不出现像真密钥的字符串
FAKE_KEY = "sk-" + "proj-" + "Ab3Cd4" * 6
PUSH = "推进一下销售侧边栏项目：先去飞书群收集这周的需求反馈，再拉多维表格里的最新进度，然后按功能、风险、下周计划三个维度写一份推进说明发我"
SKILLS = {
    "excel-aura": "表格配色与版式标准：新建、美化或审查给人看的表格时使用。用户说「美化表格」「配色舒服点」时使用。",
    "ui-styles": "UI 风格库：做给人看的网页时先选风格，默认细线。",
    "matt-flow": "开发流程：issue、分支、PR 怎么走。",
    "idle-skill": "一个很久没人用的 skill。",
}


class Claude(object):
    def __init__(self, sid, cwd, entrypoint=None):
        self.sid, self.cwd, self.entrypoint, self.rows, self.n = sid, cwd, entrypoint, [], 0

    def _row(self, kind, ts, content, human=False):
        self.n += 1
        row = {"type": kind, "sessionId": self.sid, "cwd": self.cwd, "timestamp": ts, "uuid": "%s-%d" % (self.sid, self.n),
               "message": {"role": kind, "content": content}}
        if human:
            row["origin"] = {"kind": "human"}
        if self.entrypoint:
            row["entrypoint"] = self.entrypoint
        self.rows.append(row)

    def say(self, ts, text):
        self._row("user", ts, text, human=True)
        return self

    def tool(self, ts, name, args, ok=True):
        call = "t%d" % (self.n + 1)
        self._row("assistant", ts, [{"type": "text", "text": "好的，我来做。"}, {"type": "tool_use", "id": call, "name": name, "input": args}])
        self._row("user", ts, [{"type": "tool_result", "tool_use_id": call, "content": "ok" if ok else "error: failed", "is_error": not ok}])
        return self

    def write(self, root):
        folder = Path(root) / "claude" / self.cwd.replace("/", "-")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / (self.sid + ".jsonl")).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows), encoding="utf-8")


def push_session(sid, cwd, day, corrected=False):
    s = Claude(sid, cwd).say("%sT02:00:00.000Z" % day, PUSH)
    s.tool("%sT02:01:00.000Z" % day, "Bash", {"command": "lark-cli im +messages-search --chat sidebar-feedback"})
    s.tool("%sT02:03:00.000Z" % day, "Bash", {"command": "lark-cli base +record-list --table progress"})
    s.tool("%sT02:06:00.000Z" % day, "Write", {"file_path": WORK + "/sidebar/推进说明.md", "content": "…"})
    if corrected:
        s.say("%sT02:10:00.000Z" % day, "不对，风险要单独列一节，上次就说过了。另外表格的 token 是 %s 别写进文档" % FAKE_KEY)
    return s


def build(root, with_zst=False):
    root = Path(root)
    sessions = [
        push_session("push-1", WORK + "/sidebar", "2026-11-03"),
        push_session("push-2", WORK + "/sidebar/.claude/worktrees/12-progress", "2026-11-04"),
        push_session("push-3", WORK + "/sidebar", "2026-11-06", corrected=True),
        Claude("oneoff-1", WORK + "/misc").say("2026-11-03T05:00:00.000Z", "把这张截图转成 png")
        .tool("2026-11-03T05:00:30.000Z", "Bash", {"command": "sips -s format png shot.heic"}),
        Claude("sheet-1", WORK + "/reports").say("2026-11-04T06:00:00.000Z", "把这个 Excel 表格美化一下，配色舒服点，表头加粗")
        .tool("2026-11-04T06:01:00.000Z", "Bash", {"command": "python3 beautify.py 月报.xlsx"}),
        Claude("sheet-2", WORK + "/reports").say("2026-11-05T06:00:00.000Z", "这张销售明细表也美化一下，配色别太刺眼")
        .tool("2026-11-05T06:01:00.000Z", "Bash", {"command": "python3 beautify.py 明细.xlsx"}),
        Claude("page-1", WORK + "/site").say("2026-11-05T08:00:00.000Z", "做一个产品介绍页")
        .tool("2026-11-05T08:00:30.000Z", "Skill", {"skill": "ui-styles"})
        .tool("2026-11-05T08:02:00.000Z", "Write", {"file_path": WORK + "/site/intro.html", "content": "…"})
        .say("2026-11-05T08:05:00.000Z", "不对，说了用细线风格，你怎么用了柔光"),
        Claude("page-2", WORK + "/site").say("2026-11-06T08:00:00.000Z", "<command-name>/model</command-name>")
        .say("2026-11-06T08:00:10.000Z", "<command-name>/ui-styles</command-name>")
        .say("2026-11-06T08:00:20.000Z", "按细线做个报告页")
        .tool("2026-11-06T08:01:00.000Z", "Write", {"file_path": WORK + "/site/report.html", "content": "…"}),
        Claude("early-1", WORK + "/weekly").say("2026-10-30T03:00:00.000Z", "搭一个周报生成器")
        .tool("2026-10-30T03:01:00.000Z", "Write", {"file_path": WORK + "/weekly/gen.py", "content": "…"})
        .say("2026-11-02T03:00:00.000Z", "继续")
        .tool("2026-11-02T03:01:00.000Z", "Bash", {"command": "python3 gen.py"}),
        Claude("dispatch-1", WORK + "/site", entrypoint="sdk-cli").say("2026-11-04T09:00:00.000Z", "按 issue 12 修复")
        .tool("2026-11-04T09:00:30.000Z", "Skill", {"skill": "matt-flow"}),
    ]
    for session in sessions:
        session.write(root)
    codex = root / "codex" / "2026" / "11" / "04"
    codex.mkdir(parents=True, exist_ok=True)
    read = json.dumps({"command": ["bash", "-lc", "cat /Users/tester/.codex/skills/matt-flow/SKILL.md"]})
    rows = [
        {"type": "session_meta", "timestamp": "2026-11-04T10:00:00.000Z",
         "payload": {"id": "codex-1", "cwd": WORK + "/tools", "timestamp": "2026-11-04T10:00:00.000Z", "originator": "codex_desktop", "source": "vscode"}},
        {"type": "event_msg", "timestamp": "2026-11-04T10:00:05.000Z", "payload": {"type": "user_message", "message": "按 matt-flow 开一张 issue"}},
        {"type": "response_item", "timestamp": "2026-11-04T10:00:10.000Z", "payload": {"type": "function_call", "name": "shell", "arguments": read, "call_id": "c1"}},
        {"type": "response_item", "timestamp": "2026-11-04T10:00:20.000Z", "payload": {"type": "function_call", "name": "shell", "arguments": read, "call_id": "c2"}},
    ]
    (codex / "rollout-2026-11-04T10-00-00-codex-1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    if with_zst:
        (codex / "rollout-2026-11-04T12-00-00-codex-2.jsonl.zst").write_bytes(b"")
    for name, description in SKILLS.items():
        folder = root / "skills" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "SKILL.md").write_text("---\nname: %s\ndescription: %s\n---\n\n# %s\n" % (name, description, name), encoding="utf-8")
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法：python3 make_fixture.py <目录>")
    print(build(sys.argv[1]))
