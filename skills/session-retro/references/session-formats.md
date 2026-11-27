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
| `origin`、`turnOrigin`、`entrypoint`、`pluginPrompt` | 判断这条 user 记录是不是真人发的，见下面「用户原话的来源」 | 本机实测（2026-11-27） |
| `message.content` | 字符串：真人输入；列表：其中的 `text` 块是输入，`tool_result` 块是工具结果 | 实测、agentsesh |
| assistant 的 `message.content[]` | `text`：AI 的话；`tool_use`：`{id, name, input}`；`thinking` 不用 | 实测、agentsesh |
| `tool_result` 块 | `{tool_use_id, content, is_error}`；`is_error` 为 true 算失败 | 实测、agentsesh |
| `toolUseResult` | 工具结果的附加信息；被拒绝时据报是字符串 `User rejected tool use` | 字段实测；被拒取值是假设 |
| `permissionDecision` | 新版本有，实测为 `{decision: "accept", …}`；脚本把 `reject` / `deny` 等取值当作被拒 | 字段实测；拒绝取值是假设 |

**被拒绝的工具调用**（假设，来自 Claude Code 的公开行为）：`tool_result` 的内容以 `The user doesn't want to proceed with this tool use. The tool use was rejected…` 开头；用户附了理由时，理由跟在 `the user said:` 后面。脚本把这段理由单独取出来。

**被打断**：用户按 Esc 后会记一条内容为 `[Request interrupted by user]` 或 `[Request interrupted by user for tool use]` 的 user 记录。【公开行为，假设】

**用户原话的来源**（2026-11-27 本机实测，窗口 11-13～11-26 的 user 记录，不含工具结果）：

| 记录特征 | 是什么 | 处理 |
|---|---|---|
| `origin.kind=human` | 桌面输入框里打的字或点的回复按钮。其中不少首块是应用注入的 `<system-reminder>`（关联会话状态、钩子提示），真人的话在后面的块里 | 算，记为「输入框」；先剥掉所有 `<system-reminder>…</system-reminder>` 再判断 |
| `origin={kind:plugin, name:agent-hud}` | 驿窗（Agent HUD）侧栏转进来的话。原文在 `pluginPrompt.text`；`message.content` 是 `The agent-hud plugin sent a message:\n…` 包装 | 算，记为「驿窗侧栏」；但以 `ChatGPT 对「…」的` 开头的（ChatGPT 回送：审核意见、思维评审回信）、以 `驿窗接力「…」出错` 开头的（出错通知）、以 `[Agent HUD · 来自 ` 开头的（别的 agent 经驿窗发来的消息）不算。`请把这一轮的工作交给 ChatGPT 审核…（驿窗左滑「审核」发来）` 是常浩左滑触发的固定文案，算他的操作，保留 |
| 没有 `origin`，`turnOrigin=host_synthetic` / `auto_continuation` | 应用代发：side-session 首条任务（`Background (from the session that started this one)`）、`<side-sessions-event>`、`<ci-monitor-event>` | 不算 |
| `entrypoint=sdk-cli`，或 `turnOrigin=sdk` | `claude -p` 派单（Hermes 车间、自动化中台、权限探测） | 不算 |
| `origin.kind` 是 `task-notification`、`peer`，或 `origin` 只有 `body`/`from` | 后台任务通知、别的会话发来的消息 | 不算 |
| `origin`、`turnOrigin` 都没有 | 旧版记录（字段出现之前），以及 `[Request interrupted by user]` | 按真人处理，再走下面的系统包装过滤 |

不算的记录计入覆盖统计 `non_human_messages_skipped`，驿窗回送和出错通知计入 `agent_hud_relays_skipped`。

**按钮文字**：桌面应用里 AI 每轮收尾调 `mcp__ccd_turn__wrap_up`，`input.actions[]` 里每个 `{label}` 是一个回复按钮，第一个是 AI 的推荐；用户点按钮，记录里就是一条内容等于 `label` 的普通 user 消息，没有字段能区分「点的」和「打的」。脚本记下每条用户消息前最近一次 wrap_up 的按钮文字，用来算「等于按钮 / 等于推荐」。

**系统包装的输入**：以 `<command-name>`、`<local-command-stdout>`、`<system-reminder>`、`<task-notification>`、`Caveat: The messages below…`、`This session is being continued from a previous conversation` 开头的，都不算真人发言。

**续接、分叉会话**：`claude --resume` 和桌面应用的分叉会新开一个文件，并把旧消息连同原 `uuid` 一起带过去。脚本对所有用户消息跨文件按 `uuid` 去重（不去重时短话次数会明显多算），纠正 / 决定信号再按「同一文本 + 同一秒」去重。

## Codex

**位置**：`~/.codex/sessions/YYYY/MM/DD/rollout-<本地时间>-<会话ID>.jsonl`，归档的在 `~/.codex/archived_sessions/`。【本仓库】【agentsesh】

每行是 `{timestamp, type, payload}`：

| `type` | `payload` 里用到的 | 来源 |
|---|---|---|
| `session_meta`（首行） | `id`、`cwd`、`timestamp`；`source` 为对象且含 `subagent`，或 `agent_path` 不是 `/root` 的，是子代理会话，整份跳过；`originator=codex_exec`（或 `source=exec`）是 `codex exec` 派单，「用户消息」是派单内容，不算用户原话（计入 `dispatch_messages_skipped`），工具调用照常统计。Codex 桌面版是 `originator=Codex Desktop` | 本仓库、sheal；originator 为本机实测（2026-11-27：窗口内 Codex 会话 19 个是 codex_exec，1 个是 Codex Desktop） |
| `turn_context` | `cwd`（首行没有 cwd 时补用） | 本仓库、agentsesh |
| `event_msg` | `type=user_message` 时用 `message`（用户原话）；`turn_aborted`：被打断；`exec_command_end`：`call_id` + `exit_code`，作为退出码的后备来源 | agentsesh；后两种是假设 |
| `response_item` | `type=message`（`role`，`content[]` 里的 `input_text` / `output_text`）；`function_call`（`name`、`arguments` 是 JSON 字符串、`call_id`）；`function_call_output`（`call_id`、`output`）；`custom_tool_call` / `custom_tool_call_output`（apply_patch）；`local_shell_call`；`reasoning` 不用 | agentsesh、本仓库 |
| `compacted`、`token_count` 等 | 不用；`token_count` 和 `reasoning` 在解析 JSON 前就跳过，以提速 | 本仓库 |

**用户原话取哪一份**：同一句话会同时出现在 `event_msg/user_message` 和 `response_item/message(role=user)` 里，后者还混着 `<environment_context>`、`<user_instructions>`、`# AGENTS.md instructions…` 等注入内容。脚本只要文件里有 `user_message` 事件，就只用事件那份；没有的，才退回用 `response_item`，并去掉注入内容。

**新版本没有 `user_message` 事件**（2026-11-05 在用户本机实测：最近两周的 Codex 记录里一条都没有），所以现在都走退回路线，注入内容必须滤干净，否则 AGENTS.md 里的「不要」「以后都」会冒成大量假信号。实测见到、并由 `codex_user_text()` 处理的几类：

| 消息开头 | 是什么 | 处理 |
|---|---|---|
| `# AGENTS.md instructions`、`<environment_context` | 规则文件、环境信息 | 整条跳过 |
| `<external_codex_apps…`（如 `_open_page`、`_writing_…`）、`<in-app-browser-context`、`<heartbeat`、`<skill`、`<recommended_plugins`、`<codex_delegation` | 应用页面状态、内置浏览器上下文、心跳、技能正文、插件推荐、别的 agent 派来的任务 | 整条跳过 |
| `The following is the Codex agent history…`、`You are working inside Orca…`、`[数字] assistant:` / `[数字] tool …` | 父会话或别的 agent 的历史摘录 | 整条跳过 |
| `PLEASE IMPLEMENT THIS PLAN:` | 计划模式里点「开始实施」时自动生成，不是用户打的字 | 整条跳过 |
| `# Files mentioned by the user:`、`# Files pasted by the user:`、`# Context from my IDE setup:`、`## Referenced ChatGPT conversation:` | 前面是文件清单或对话摘录，用户的话在 `## My request:`（或 `## My request for Codex:`）之后 | 只取那一节之后；没有这一节的整条跳过 |
| `<send_user_message_question_reply>…</…>` | 用户回答 agent 的提问，原话包在标签里 | 去掉标签，保留原话 |

**命令行怎么取**：`shell` 的 `arguments.command` 是数组（如 `["bash","-lc","pytest -q"]`）；`exec_command` 是 `arguments.cmd` 字符串；`apply_patch` 从补丁里的 `*** Update File:` 取文件名。【agentsesh】

**失败怎么判断**，四种写法都兼容：

1. `output` 是 JSON 字符串 `{"output": "...", "metadata": {"exit_code": 1}}`。【agentsesh、旧版本】
2. 纯文本 `Exit code: 1\nWall time: …\nOutput: …`。【本机实测：apply_patch】
3. 纯文本 `Process exited with code 1`。【agentsesh；本机实测：exec_command、write_stdin】
4. `exec` 工具（`custom_tool_call_output`，`output` 是 `[{type: "input_text", text}]` 列表），首行 `Script completed` 算成功、`Script failed` 算失败；`Script running with cell ID …` 记为结果未知。这是新版 Codex 工具输出的大多数（本机一周约 2100 条）。首行优先：`Output:` 里内层命令打印的退出码不覆盖脚本级结论。【本机实测】

仍记为「结果未知」的（本机一周约 1600 条，本来就没有成败可言，不算缺陷）：内置浏览器的 `js` 工具输出（只有 `Wall time` / `Output`）、`spawn_agent` / `send_message` / `followup_task` / `wait_agent` 这类多代理工具、还在运行的 `exec_command`（只有 `Chunk ID`，没有退出码）、`sleep`。`# lark-channel-bridge` 开头的消息是飞书转发进来的，可能是用户本人在飞书说的话，没有过滤。

都没有时，以 `error` / `failed` / `fatal` 开头、或含 `verification failed` 的算失败，否则记为「结果未知」，不计入连续失败。

**被拒绝**（假设）：输出里含 `rejected by user`、`denied by user`、`aborted by user` 等。实际文案随版本可能不同，首次在真实数据上运行后要核对。2026-11-05 本机最近一周的 Codex 记录里，这类文案只出现在 2 行，脚本识别出 1 次拒绝；样本太少，具体文案仍需以后核对。

**旧版格式**（假设）：首行是 `{id, timestamp, instructions}`，没有 `type`；之后每行直接是条目（`{type: "message", …}`），没有逐行时间戳。脚本用首行时间代替。更早的 `.json` 单文件格式不支持。

## 时间与剪枝

- 窗口按本地时区计算，左闭右开（`--end` 那天不含）。
- 文件最后修改时间早于窗口起点的，不可能有窗口内的事件，直接跳过。Codex 文件名里的日期晚于窗口结束日一天以上的，也跳过。这两条是性能的关键：Codex 记录约 26G，但一周窗口通常只需要读其中一小部分。
- 云端用 28 万行、285 MB 的合成 Codex 文件实测，约 8 秒。真实耗时取决于窗口内的文件量。
- 单行超过 8 MB（多为内嵌图片）跳过并计数。
