---
name: get-notes-retrieval
description: Search and read 常浩's complete GET笔记 collection, including meeting content and full audio transcripts, through the GET OpenAPI. Use when a request explicitly asks to search GET笔记 or recordings, or when a 路觅教育 answer has a specific meeting-history or decision-rationale gap that may change the conclusion. Apply the shared Lumiedu permission contract before every GET operation; do not use this Skill by default for ordinary company or methodology questions.
metadata:
  governance:
    network: required
    external-writes: none
    destructive-actions: none
    credentials: required
    dependencies:
      - python3
      - certifi
---

# GET 笔记一手上下文检索

通过 GET OpenAPI 检索全部笔记，并按需读取命中笔记的完整录音转写。凭据只从 macOS Keychain 或进程环境读取；禁止把凭据写入参数、输出、日志、Skill、AGENTS.md 或飞书。

运行需要 Python 3；`certifi` 可选，未安装时脚本使用系统 TLS 信任库。

任何 GET 命令执行前，先读取并执行权限唯一真源：[路觅 Skills 权限合同](/Users/nat/.agents/lumiedu-permission-contract.md)。身份未通过合同校验时，在调用脚本前停止。

## 固定入口

将包含本 `SKILL.md` 的目录解析为 `<skill-root>`，使用其中的只读脚本：

```bash
python3 "<skill-root>/scripts/get_notes.py" <command>
```

## 实时答疑

GET 只补会议原话、历史决策理由或真实运行细节中会改变结论的明确缺口，不是公司题的默认必查源，也不替代飞书正式背景：

1. 先复用当前任务已有的正式背景、用户本轮事实和 GET 证据；已经足够时不调用。
2. 确有缺口时，用对象、项目、角色、会议主题和关键动作开始全库语义检索。
3. 起步先取最相关的 3—5 个片段；需要核对关键原话或上下文时，精读相关笔记并按当前问题抽取片段。
4. 证据不足且会影响结论时，针对具体缺口调整查询或补读；每轮说明要解除什么不确定性。证据足够、剩余缺口不影响结论或新增检索已无有效进展时停止，说明仍需保留的条件。获得授权的离线复盘按任务游标继续检索。
5. 从命中笔记中区分会议事实、常浩明确判断、讨论假设、个人观点与待办，不把同会出现等同于正式结论。
6. 按共享权限合同的最小必要边界，只让与当前问题相关的片段进入上下文。
7. 把实际读到的笔记记录为 `get:<note_id>`，来源等级标记为 `get_reference`。GET 内容不能占用 `stable_context`，也不能覆盖更高等级正式口径。

常用命令：

```bash
# 实时答疑起步：先取有界片段，按证据缺口决定是否补查
python3 "<skill-root>/scripts/get_notes.py" search --query "<自然语言问题>" --top-k 5 --detail-top 0

# 核对关键原话或上下文时读取相关笔记；query 用于抽取相关片段
python3 "<skill-root>/scripts/get_notes.py" detail --id "<note_id>" --query "<当前问题>"
```

输出是有界 JSON；成功与失败路径都会递归脱敏 API Key、Client ID 和 URL 查询参数，不包含音频签名地址或写操作。

## 授权增量复盘

仅在当前任务或已批准自动化合同明确要求 GET 增量复盘时使用；GET API 是主增量源，Obsidian 镜像只作回退：

```bash
python3 "<skill-root>/scripts/get_notes.py" changes --after "<最后成功时间>"
```

- 对返回的新增或更新笔记先看标题、标签和时间，只精读与当前复盘范围相关的笔记。
- 只有返回 `status: ok`、`truncated: false`、`cursor_advance_allowed: true` 且本阶段处理完成时才可推进 GET 游标。`status: partial` 或 `truncated: true` 时提高安全批次上限并补跑，期间不得推进游标。
- GET API 阶段失败时不得推进 GET 游标；可读取 Obsidian 镜像补充本次分析，但必须记录为降级运行。
- API 与 Obsidian 同时不可用时，跳过 GET 阶段并保留游标，不制造“无新增”结论。
- 能否进入任何正式页由目标工作流的来源适用性与共享权限合同共同决定；本 Skill 不执行写入。

## 降级与安全

- API 429、配额或网络失败：最多按脚本内置退避重试；仍失败则使用 Obsidian 只读镜像并标记降级。
- 不调用新建、更新、删除、标签修改、知识库修改、分享或上传接口。即使 Key 拥有这些权限，本工具也没有对应代码路径。
- 不把 GET 原始转写整篇写入飞书；只提炼稳定、相关、最小必要知识。
- 不把私人闲聊、个人评价、绩效、学生隐私、候选人信息、联系方式或密钥带入回答或正式知识库。
- 正式知识与 GET 冲突时，保留冲突并给条件性判断，不静默选边。

连通性检查：

```bash
python3 "<skill-root>/scripts/get_notes.py" doctor --probe-query "管培生"
```

该命令只输出连接、配额和命中数量等安全指标，不输出笔记正文。
