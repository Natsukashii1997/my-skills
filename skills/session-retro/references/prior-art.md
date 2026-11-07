# 参考过的同类项目，借鉴了什么

2026-11-05 在云端调研，读了三个项目的 README 和主要源码文件。sheal 的会话解析在外部 npm 包 `@liwala/agent-sessions` 里，这个包没有读；session-intelligence 配套的提取器 `local-session-extractor` 也没有读。

## sheal（github.com/liwala/sheal，TypeScript）

**它做什么**：一套命令行工具（retro / drift / digest / learn / rules 等）。从 `~/.claude`、`~/.codex` 导入会话，在项目里存一份原文副本（`.sheal/sessions/raw/`），再做规则分析。

**信号规则**（`src/retro/analyzers.ts`）：

- 用户纠正：只在句首匹配英文正则 `^(no[,.\s]|not that|instead|wrong|stop|don't|actually|wait|I said|I meant|that's not|let's not)`。
- 失败循环：同一动作连续调用 3 次以上，且输出里有 error 或 `Exit code 1`。Bash 按命令第一段归类，文件工具按「工具 + 文件」归类。
- 反复改同一文件 4 次以上；上下文压缩。

**输出**：学到的东西存成草稿（`status: draft`），不自动生效；`sheal rules` 才把已启用的条目写进 AGENTS.md。`learn lint` 会查重复和近似重复的规则。

**借鉴了**：

- 「先存草稿，人批了才生效」。这和用户「只出提案、批准才写」的规矩一致，本 skill 更进一步：运行期间完全不写规则文件。
- 「句首才算」的弱纠正词判断：「不是」「别」「stop」「wait」只在句首或短句里算。
- 失败按「工具 + 命令前几个词」或「工具 + 文件名」归类，连续 3 次算一组（`--min-streak` 可调）。
- 每个会话用原生 ID 做稳定标识，以此去重。

**没有照搬**：

- 不复制原始会话。sheal 把原文复制进项目目录，有被一起提交进 git 的风险；本 skill 只输出截断、脱敏后的片段，并且拒绝把输出写进 git 仓库。
- 不调用外部 agent 命令（sheal 的 `--enrich` 会 shell out 到 `claude -p` 等），不发 Slack。

## agentsesh（github.com/ateeples/agentsesh，Python，命令 `sesh`）

**它做什么**：给会话打分、画行为画像，找 9 种低效模式（重复搜索、没读就改、连续出错、读写比过低等）。

**解析**（`sesh/parsers/claude_code.py`、`openai_codex.py`）是这次调研里最有用的格式参考：

- Claude：`type`、`message.content[]` 里的 `text` / `tool_use` / `tool_result`，`tool_result.is_error`。
- Codex：`session_meta`、`turn_context`、`response_item`（message / function_call / function_call_output / custom_tool_call / reasoning）、`event_msg`（user_message / agent_message）。失败判断兼容 `Process exited with code N` 和 JSON 包装里的 `metadata.exit_code`。

**输出**：`sesh analyze --fix` / `--feedback` 直接把规则写进 CLAUDE.md，不经审阅。

**借鉴了**：

- 两种格式的字段读取方式，以及 Codex 失败判断的两种写法，见 [session-formats.md](session-formats.md)。
- 连续出错 3 次算「卡住了」的阈值。

**没有照搬**：

- 直接写 CLAUDE.md。这违反用户的规矩。
- 效率类指标（读写比、并行度、出错率打分）。本 skill 要找的是「该沉淀什么」，不是「AI 用得好不好」；后者已经有 codex-usage-retrospective 在做。
- 它没有中文纠正词识别，这部分是本 skill 自己补的。

## Session Intelligence（github.com/tetriz-ai/session-intelligence，Go）

**它做什么**：把整段会话交给大模型（默认 Gemini）判断目标、打分、找浪费的步骤，再标出安全问题（密钥泄露、数据库凭据泄露、注入个人信息）。不读原生会话文件，要先用配套提取器转换格式。不生成规则。

**借鉴了**：

- 「先用确定的规则搭骨架，再让模型判断」的分层：本 skill 的脚本只做确定的规则筛选，判断交给执行 skill 的 agent。
- 它把密钥泄露、凭据泄露当成要专门检查的类别。本 skill 把脱敏做成所有输出都必经的一层，并且有专门的测试。

**没有照搬**：

- 把整段会话发给外部大模型。脚本本身不调用任何模型；agent 只读脱敏后的信号摘要，需要上下文时也只看前后几轮的截断片段。
- 它自己也承认，它的遮盖只是兜底，不能当脱敏用。本 skill 的脱敏同样只是兜底，有漏网的可能，见 PR 里「首次运行前要确认的事」。

## 三者都没有、本 skill 自己补的

- 中文纠正词和决定词（「不对」「重来」「定了」「以后都」等），分强弱两级，并排除常见误报（「特别」「不错」、引号里的引用、代码块里的内容）。
- 被拒绝时用户给的理由单独取出来。这往往就是最好的规则原文。
- 同一句话在不同时间又说了一遍的，合并成一条并标出次数，说明说过一次没管用。
- 拿信号和提案对照用户现有的规则文件（全局 CLAUDE.md / AGENTS.md、agent-kit/LESSONS.md、各项目 LESSONS），标出「已有」「已有但没被遵守」。
- 规则、坑、决定三类分开，各自对应用户已有的沉淀位置。
