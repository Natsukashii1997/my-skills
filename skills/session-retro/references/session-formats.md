# 两种会话记录的结构：脚本依据了什么，哪些是假设

两家都没有公开的正式格式说明。下面的结构来自四个来源，每条都标了出处。格式随版本会变，所以脚本对认不出的记录一律跳过、计数，不报错退出。

**来源**

- 【实测】云端开发时，Claude Code 2.1.318 在本容器里生成的会话记录。只看了字段结构，没有读真实用户数据。
- 【本仓库】`skills/codex-usage-retrospective/scripts/period_index.py`，用户自己在用的 Codex 索引脚本。
- 【agentsesh】github.com/ateeples/agentsesh 的 `sesh/parsers/claude_code.py` 与 `openai_codex.py`。
- 【sheal】github.com/liwala/sheal 的 `src/sessions/raw-registry.ts`。

## Claude Code

**位置**：`~/.claude/projects/<把工作目录的 / 换成 - 后的名字>/<会话ID>.jsonl`，每行一条 JSON。【实测】【agentsesh】
子代理的记录在 `<会话ID>/subagents/agent-*.jsonl`，脚本只取第一层的 `*.jsonl`，所以不会读到。【实测】

| 字段 | 用途 | 来源 |
|---|---|---|
| `type` | `user` / `assistant` 才处理；`summary`、`attachment`、`queue-operation` 等跳过 | 实测 |
| `timestamp` | ISO 时间，UTC，带 `Z` | 实测 |
| `sessionId`、`cwd`、`uuid` | 会话 ID、工作目录（用于按项目筛选）、单条记录 ID（用于去重） | 实测、sheal |
| `isSidechain` | 为 true 是旧版写法的子代理消息，跳过 | 实测（字段存在） |
| `isMeta`、`isCompactSummary` | 系统注入的消息、压缩摘要，跳过 | 公开行为，假设 |
| `origin.kind` | 新版本有；`human` 才算真人输入，`task-notification` 等跳过 | 实测见到 `human`；其他取值是假设 |
| `message.content` | 字符串：真人输入；列表：其中的 `text` 块是输入，`tool_result` 块是工具结果 | 实测、agentsesh |
| assistant 的 `message.content[]` | `text`：AI 的话；`tool_use`：`{id, name, input}`；`thinking` 不用 | 实测、agentsesh |
| `tool_result` 块 | `{tool_use_id, content, is_error}`；`is_error` 为 true 算失败 | 实测、agentsesh |
| `toolUseResult` | 工具结果的附加信息；被拒绝时据报是字符串 `User rejected tool use` | 字段实测；被拒取值是假设 |
| `permissionDecision` | 新版本有，实测为 `{decision: "accept", …}`；脚本把 `reject` / `deny` 等取值当作被拒 | 字段实测；拒绝取值是假设 |

**被拒绝的工具调用**（假设，来自 Claude Code 的公开行为）：`tool_result` 的内容以 `The user doesn't want to proceed with this tool use. The tool use was rejected…` 开头；用户附了理由时，理由跟在 `the user said:` 后面。脚本把这段理由单独取出来。

**被打断**：用户按 Esc 后会记一条内容为 `[Request interrupted by user]` 或 `[Request interrupted by user for tool use]` 的 user 记录。【公开行为，假设】

**系统包装的输入**：以 `<command-name>`、`<local-command-stdout>`、`<system-reminder>`、`<task-notification>`、`Caveat: The messages below…`、`This session is being continued from a previous conversation` 开头的，都不算真人发言。

**续接会话**：`claude --resume` 会新开一个文件，并把旧消息连同原 `uuid` 一起带过去。脚本先按 `uuid` 去重，再按「同一文本 + 同一秒」去重。

## Codex

**位置**：`~/.codex/sessions/YYYY/MM/DD/rollout-<本地时间>-<会话ID>.jsonl`，归档的在 `~/.codex/archived_sessions/`。【本仓库】【agentsesh】

每行是 `{timestamp, type, payload}`：

| `type` | `payload` 里用到的 | 来源 |
|---|---|---|
| `session_meta`（首行） | `id`、`cwd`、`timestamp`；`source` 为对象且含 `subagent`，或 `agent_path` 不是 `/root` 的，是子代理会话，整份跳过 | 本仓库、sheal |
| `turn_context` | `cwd`（首行没有 cwd 时补用） | 本仓库、agentsesh |
| `event_msg` | `type=user_message` 时用 `message`（用户原话）；`turn_aborted`：被打断；`exec_command_end`：`call_id` + `exit_code`，作为退出码的后备来源 | agentsesh；后两种是假设 |
| `response_item` | `type=message`（`role`，`content[]` 里的 `input_text` / `output_text`）；`function_call`（`name`、`arguments` 是 JSON 字符串、`call_id`）；`function_call_output`（`call_id`、`output`）；`custom_tool_call` / `custom_tool_call_output`（apply_patch）；`local_shell_call`；`reasoning` 不用 | agentsesh、本仓库 |
| `compacted`、`token_count` 等 | 不用；`token_count` 和 `reasoning` 在解析 JSON 前就跳过，以提速 | 本仓库 |

**用户原话取哪一份**：同一句话会同时出现在 `event_msg/user_message` 和 `response_item/message(role=user)` 里，后者还混着 `<environment_context>`、`<user_instructions>`、`# AGENTS.md instructions…` 等注入内容。脚本只要文件里有 `user_message` 事件，就只用事件那份；没有的（旧版本），才退回用 `response_item`，并去掉注入内容。

**命令行怎么取**：`shell` 的 `arguments.command` 是数组（如 `["bash","-lc","pytest -q"]`）；`exec_command` 是 `arguments.cmd` 字符串；`apply_patch` 从补丁里的 `*** Update File:` 取文件名。【agentsesh】

**失败怎么判断**，三种写法都兼容：

1. `output` 是 JSON 字符串 `{"output": "...", "metadata": {"exit_code": 1}}`。【agentsesh、旧版本】
2. 纯文本 `Exit code: 1\nWall time: …\nOutput: …`。【新版本，假设】
3. 纯文本 `Process exited with code 1`。【agentsesh】

都没有时，以 `error` / `failed` / `fatal` 开头、或含 `verification failed` 的算失败，否则记为「结果未知」，不计入连续失败。

**被拒绝**（假设）：输出里含 `rejected by user`、`denied by user`、`aborted by user` 等。实际文案随版本可能不同，首次在真实数据上运行后要核对。

**旧版格式**（假设）：首行是 `{id, timestamp, instructions}`，没有 `type`；之后每行直接是条目（`{type: "message", …}`），没有逐行时间戳。脚本用首行时间代替。更早的 `.json` 单文件格式不支持。

## 时间与剪枝

- 窗口按本地时区计算，左闭右开（`--end` 那天不含）。
- 文件最后修改时间早于窗口起点的，不可能有窗口内的事件，直接跳过。Codex 文件名里的日期晚于窗口结束日一天以上的，也跳过。这两条是性能的关键：Codex 记录约 26G，但一周窗口通常只需要读其中一小部分。
- 云端用 28 万行、285 MB 的合成 Codex 文件实测，约 8 秒。真实耗时取决于窗口内的文件量。
- 单行超过 8 MB（多为内嵌图片）跳过并计数。
