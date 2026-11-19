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
            assistant(now, 10, closing("等你决定", "标题用哪种字号。", "回复「大号」或「小号」。")),
            user(now, 9, "大号"),
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
        ("6", "账单｜对账脚本", "billing", False, None, [], [
            assistant(now, 70, closing("受阻", "缺账单导出文件。", "把 10 月账单导出文件放到 data/ 目录后回复「放好了」。")),
        ]),
    ]


def build(root, now=None):
    now = now or time.time()
    meta = os.path.join(root, "meta", "workspace")
    projects = os.path.join(root, "projects")
    inbox = os.path.join(root, "inbox")
    for path in (meta, inbox):
        os.makedirs(path, exist_ok=True)
    order = {}
    for index, (tag, title, project, archived, parent, prs, log) in enumerate(sessions(now), 1):
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
        with open(os.path.join(meta, session_id + ".json"), "w") as handle:
            json.dump(record, handle, ensure_ascii=False)
        folder = os.path.join(projects, f"-work-{project}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, cli + ".jsonl")
        with open(path, "w") as handle:
            for entry in log:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.utime(path, (now - 3600, now - 3600))
    # 上一份清单里列过「账单」那个会话；「规则」那个在忽略名单里，状态没变。
    with open(os.path.join(inbox, "拍板清单-2026-01-01.md"), "w") as handle:
        handle.write(f"# 拍板清单\n\n- B1 放账单导出文件。账单｜对账脚本 `{sid('6', 12)}`\n")
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
