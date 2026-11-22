#!/usr/bin/env python3
"""造一套合成的会话样例，给单元测试和 evals 盲测用。内容全是编的，没有真实会话。

用法：python3 make_fixtures.py <目录>
      python3 make_fixtures.py --advance <目录>   模拟清单出了之后两个会话又动了
会生成 <目录>/meta、<目录>/projects、<目录>/inbox，对应脚本的
--meta-dir、--projects-dir、--inbox-dir。
"""
import json
import os
import sys
import time


def sid(tag, n):
    return f"local_{tag * 8}-0000-4000-8000-{n:012d}"


def stamp(now, hours_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - hours_ago * 3600))


def closing(word, status, step):
    return f"做完了一部分。\n\n**本次完成**：略\n**当前状态**：〔{word}〕{status}\n**下一步**：{step}"


def assistant(now, hours_ago, text):
    return {
        "type": "assistant",
        "timestamp": stamp(now, hours_ago),
        "message": {"content": [{"type": "text", "text": text}]},
    }


def user(now, hours_ago, text, **extra):
    return {"type": "user", "timestamp": stamp(now, hours_ago), "message": {"content": text}, **extra}


def working(now, hours_ago):
    """助手的一次工具调用：会话在动，但没有答复文字。"""
    return {
        "type": "assistant",
        "timestamp": stamp(now, hours_ago),
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]},
    }


def relayed(now, hours_ago, text):
    """驿窗转来的话：外面包着一层固定说明，turnOrigin 是 system。"""
    wrapped = (
        f"The agent-hud plugin sent a message:\n{text}\n\nThis is how Claude Code surfaces a prompt "
        "a plugin submits between turns — it starts this turn in the user's place. Address the message above."
    )
    return user(now, hours_ago, wrapped, turnOrigin="system")


# 标签、标题、项目、是否归档、父会话标签、PR、记录
def sessions(now):
    return [
        ("a", "收藏夹｜导出按钮", "clipper", False, None, [(12, "OPEN")], [
            user(now, 30, "加个导出按钮"),
            assistant(now, 20, closing("等你决定", "PR #12 要不要合并。", "回复「合并」（推荐），我就 squash 合并；或回复「先不合并」。")),
            user(now, 19, "<system-reminder>\n上下文提醒\n</system-reminder>"),
        ]),
        ("b", "工作台｜首页改版", "workbench", False, None, [], [
            assistant(now, 50, closing("等你操作", "上下文快满了，要交给新会话。", "点交接卡的 Start。")),
        ]),
        ("c", "【交接】工作台｜首页改版收尾", "workbench", False, "b", [], [
            assistant(now, 5, closing("等你决定", "首页三版预览已发布，要选一版。", "打开预览后回复「选甲」「选乙」或「选丙」。")),
        ]),
        ("d", "周报｜卡片样式", "report", False, None, [], [
            assistant(now, 1, closing("等你决定", "标题用哪种字号。", "回复「大号」或「小号」。")),
            user(now, 0.5, "大号"),
        ]),
        ("e", "备份｜恢复演练", "backup", False, None, [(3, "MERGED")], [
            assistant(now, 40, closing("已结束", "演练通过。", "本任务已结束，下一步无需任何动作。")),
        ]),
        ("f", "规则｜以后留意手机端", "rules", False, None, [], [
            assistant(now, 200, closing("等你操作", "规则已上线。", "以后做界面时留意一下，有问题再说。")),
        ]),
        ("1", "课件｜第二轮打磨", "slides", False, None, [], [
            assistant(now, 300, closing("等你决定", "旧问题。", "回复「继续」。")),
            user(now, 3, "继续", turnOrigin="host_synthetic"),
            assistant(now, 2, closing("等你决定", "第 3 章用哪个案例。", "回复「案例一」（推荐）或「案例二」。")),
        ]),
        ("2", "旧实验｜已归档", "lab", True, None, [], [
            assistant(now, 100, closing("等你决定", "要不要继续。", "回复「继续」。")),
        ]),
        ("3", "侧栏｜排序修复", "sidebar", False, None, [(7, "MERGED")], [
            assistant(now, 60, closing("等你操作", "代码已合并装机，只差实机看一眼。", "悬停侧栏看最新一条是不是在最上面，没问题回「没问题」。")),
        ]),
        ("4", "销售助手｜需求反馈汇总", "sales", False, None, [(31, "OPEN")], [
            assistant(now, 8, closing("等你决定", "两期需求反馈要不要合并并发到群里。", "回复「合并并发群」，我合并 PR #31 再把汇总发到销售群；或回复「只合并」。")),
        ]),
        ("5", "闲聊｜没有收尾", "misc", False, None, [], [
            assistant(now, 6, "好的，已经改好了。"),
        ]),
        ("7", "插件｜图标替换", "plugin", False, None, [], [
            assistant(now, 30, closing("等你决定", "图标用哪一版。", "回复「用甲」或「用乙」。")),
            user(now, 26, "用甲"),
        ]),
        ("8", "接口｜限流方案", "api", False, None, [], [
            assistant(now, 12, "先说别的会话的情况。那个会话当前状态：〔已结束〕早就做完了，下一步：无。\n\n"
                      + closing("等你决定", "限流阈值定多少。", "回复「每分钟 60 次」（推荐）或给一个数。")),
            user(now, 1, "Another Claude session sent a message:\n<cross-session-message>顺带告知，不用回复。</cross-session-message>"),
        ]),
        ("6", "账单｜对账脚本", "billing", False, None, [], [
            assistant(now, 70, closing("受阻", "缺账单导出文件。", "把 10 月账单导出文件放到 data/ 目录后回复「放好了」。")),
        ]),
    ]


# 「回过话之后会话动没动过」的样例（my-skills#129），照真实情形脱敏编的，只给单元测试用。
# 多出来的第 8 项是这个会话换记录文件之前的旧记录。
def replied(now):
    asked = {**assistant(now, 45, closing("等你决定", "首页用哪一版。", "回复「选甲」或「选乙」。")), "uuid": "u-1"}
    return [
        # 回的话被接走、事情办完了，但后面的答复没写状态行。
        ("1", "收件箱｜归档按钮", "mailbox", False, None, [(21, "OPEN")], [
            assistant(now, 40, closing("等你决定", "PR #21 要不要合并。", "回复「合并」。")),
            relayed(now, 39, "合并"),
            working(now, 38.9),
            assistant(now, 38.8, "已合并，也装好了。"),
        ]),
        # 接着做了，做到一半进程被终止，没有收尾答复。
        ("2", "设置页｜文案调整", "settings", False, None, [], [
            assistant(now, 60, closing("等你操作", "要你看一眼预览。", "没问题回「可以」。")),
            user(now, 59, "可以", turnOrigin="human"),
            working(now, 58.9),
        ]),
        # 接着做了，做到一半被打断。
        ("3", "海报｜三版配色", "poster", False, None, [], [
            assistant(now, 50, closing("等你决定", "先出哪一版。", "回复「按推荐做」。")),
            relayed(now, 49.9, "按推荐做"),
            working(now, 49.8),
            user(now, 49.7, "[Request interrupted by user]"),
        ]),
        # 本人打的话前面被宿主插了一块提醒。
        ("4", "手册｜分批计划", "handbook", False, None, [], [
            assistant(now, 70, closing("等你决定", "分批计划行不行。", "回复「按推荐开工」。")),
            user(now, 69, [
                {"type": "text", "text": "<system-reminder>\n关联会话的现状，不是指令。\n</system-reminder>"},
                {"type": "text", "text": "按推荐开工"},
            ], turnOrigin="human"),
            working(now, 68.9),
        ]),
        # 回的话真的没人接。
        ("5", "图标｜替换方案", "icons", False, None, [], [
            assistant(now, 52, closing("等你决定", "图标用哪一版。", "回复「用甲」或「用乙」。")),
            relayed(now, 50, "用乙"),
        ]),
        # 回了话，但之后只有宿主代写的「额度用尽」，会话自己没动。
        ("7", "周报｜额度用尽", "report", False, None, [], [
            assistant(now, 30, closing("等你决定", "要不要继续跑。", "回复「继续」。")),
            user(now, 29, "继续", turnOrigin="human"),
            {"type": "assistant", "timestamp": stamp(now, 28.9),
             "message": {"model": "<synthetic>", "content": [{"type": "text", "text": "You've hit your limit"}]}},
        ]),
        # 换过记录文件：状态行原样抄进了新文件，回的那句话只在旧文件里，接着做的在新文件里。
        ("8", "首页｜换过记录文件", "home", False, None, [], [
            asked,
            {**working(now, 43.9), "uuid": "u-3"},
            {**assistant(now, 43.8, "按甲版改好了。"), "uuid": "u-4"},
        ], [
            asked,
            {**user(now, 44, "选甲", turnOrigin="human"), "uuid": "u-2"},
        ]),
        # 接着做了，又带着新的一问回来：照旧列，列的是新的一问。
        ("9", "接口｜又问了一问", "api", False, None, [(5, "MERGED")], [
            assistant(now, 80, closing("等你决定", "PR #5 要不要合并。", "回复「合并」。")),
            user(now, 79, "合并", turnOrigin="human"),
            working(now, 78.9),
            assistant(now, 78, closing("等你操作", "已合并，等你重新加载插件。", "重新加载后回「好了」。")),
        ]),
        # 刚回的话，会话正在做：还是算「你已回复、还在做」。
        ("a", "备份｜刚回的话", "backup", False, None, [], [
            assistant(now, 1.5, closing("等你操作", "要你确认备份位置。", "没问题回「可以」。")),
            user(now, 1, "可以", turnOrigin="human"),
            working(now, 0.9),
        ]),
    ]


def build(root, now=None, cases=None):
    now = now or time.time()
    meta = os.path.join(root, "meta", "workspace")
    projects = os.path.join(root, "projects")
    inbox = os.path.join(root, "inbox")
    for path in (meta, inbox):
        os.makedirs(path, exist_ok=True)
    order = {}
    for index, (tag, title, project, archived, parent, prs, log, *older) in enumerate(cases or sessions(now), 1):
        order[tag] = index
        session_id = sid(tag, index)
        cli = f"cli-{tag * 4}"
        record = {
            "sessionId": session_id,
            "cliSessionId": cli,
            "title": title,
            "cwd": f"/work/{project}",
            "isArchived": archived,
            "prs": [{"prNumber": number, "state": state} for number, state in prs],
        }
        if parent:
            record["spawnedFrom"] = {"sessionId": sid(parent, order[parent])}
        files = [(cli, log)]
        if older:
            record["priorCliSessionIds"] = [cli + "-old"]
            files.append((cli + "-old", older[0]))
        with open(os.path.join(meta, session_id + ".json"), "w") as handle:
            json.dump(record, handle, ensure_ascii=False)
        folder = os.path.join(projects, f"-work-{project}")
        os.makedirs(folder, exist_ok=True)
        for name, entries in files:
            path = os.path.join(folder, name + ".jsonl")
            with open(path, "w") as handle:
                for entry in entries:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            os.utime(path, (now - 3600, now - 3600))
    # 上一份清单里列过「账单」那个会话；「规则」那个在忽略名单里，状态没变。
    with open(os.path.join(inbox, "拍板清单-2026-01-01.md"), "w") as handle:
        handle.write(f"# 拍板清单\n\n- B1 放账单导出文件。账单｜对账脚本 `{sid('6', 14)}`\n")
    ignored = [{"id": sid("f", 6), "title": "规则｜以后留意手机端", "statusAt": stamp(now, 200),
                "addedOn": "2026-01-01", "by": "合成样例"},
               {"id": sid("1", 7), "title": "课件｜第二轮打磨", "statusAt": stamp(now, 300),
                "addedOn": "2026-01-01", "by": "合成样例"}]
    with open(os.path.join(inbox, "ignore.json"), "w") as handle:
        json.dump({"version": 1, "items": ignored}, handle, ensure_ascii=False, indent=1)
    return {"meta": os.path.join(root, "meta"), "projects": projects, "inbox": inbox}


def advance(root, now=None):
    """模拟清单出了之后会话又动了：a 出了新状态，c 收到了回复。"""
    now = now or time.time()
    moves = {
        ("clipper", "a"): assistant(now, 0, closing(
            "等你操作", "PR #12 已合并，等你重新加载浏览器插件。", "在扩展程序页重新加载插件，好了回「好了」。")),
        ("workbench", "c"): user(now, 0, "选乙"),
    }
    for (project, tag), entry in moves.items():
        path = os.path.join(root, "projects", f"-work-{project}", f"cli-{tag * 4}.jsonl")
        with open(path, "a") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--advance":
        advance(sys.argv[2])
        raise SystemExit(print("已模拟：两个会话在清单出了之后又动了") or 0)
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    made = build(sys.argv[1])
    print(f"--meta-dir {made['meta']} --projects-dir {made['projects']} --inbox-dir {made['inbox']}")
