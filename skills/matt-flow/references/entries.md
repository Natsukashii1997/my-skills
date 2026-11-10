# 半路入口

常浩不是从头开始时，从对应的站接上。每个入口：怎么认出来 → 先决条件 → 做什么 → 做完接哪站。

接上之前先确认前面的站真的有产出（需求文档在哪、任务卡在哪）；找不到就说清缺什么，回到缺的那一站，不假装已经有。

| 入口 | 怎么认出来 | 先决条件 | 做完接哪站 |
|---|---|---|---|
| **to-spec** 想法已聊清 | 本会话或交来的材料里，问题、方案、取舍都已经说定；常浩说「就这么做」「写成需求吧」 | 2 / 3 档的前置检查（SKILL.md 第 4 节）；发 issue 前单独确认 | thinking-review 检查节点 → to-tickets |
| **to-tickets** 已有需求文档 | 常浩给了需求文档、spec issue、PRD 路径 | 前置检查；读全文和评论；发 issue 前单独确认 | implement 或 implement-spec |
| **implement** 已有任务卡 | 有 issue 编号、`.scratch/<功能>/issues/` 下的卡、「做第 3 张」 | 卡是 to-tickets 产出或已被 triage 成 ready-for-agent；按阻塞关系先做没被挡住的 | 下一张卡；全部做完 → pr → retro |
| **code-review → pr → retro** 代码已写完 | 「写完了」「帮我看看能不能提交」「准备合并」 | 问清或找到比较起点（分支起点、main）；需求来源（issue、需求文档、本会话结论） | pr（开 PR 前单独确认）→ retro |
| **diagnosing-bugs** 出 bug | 报错、点了没反应、结果不对、变慢、时好时坏、「昨天还好好的」 | 原因一眼看得出、改一处就好的，按 0 档直接修 | 修好后 retro（问「怎样能早点防住」）；发现是结构问题 → improve-codebase-architecture |
| **triage** 反馈积压 | 一堆别人提的 issue、bug 报告、功能请求没分类 | 前置检查（要分流标签）；只分流**不是** to-tickets 产出的 issue；改标签、发评论前单独确认 | 标成 ready-for-agent 的 → implement |
| **improve-codebase-architecture** 代码越来越乱 | 「越改越乱」「改一处坏一处」「AI 老找不到地方」；或 retro、diagnosing-bugs 指向结构问题 | 无 | 常浩挑中一个改进点 → 当成新想法，从 2 档 grill-with-docs 开始 |
| **wait-what** 听不懂 | 「没看懂」「说人话」「这是什么意思」 | 无 | 回到刚才那一站继续 |
| **wizard** 要人亲手配置 | 要注册服务、拿 API Key、填 CI 密钥、点第三方后台；agent 自己做不了 | agent 能自己做的就自己做，不用它 | 回到被卡住的那一站 |
| **research** 要查资料 | 要读官方文档、第三方 API、源码才能做决定 | 无 | 研究结果带回 grill-with-docs（研究给思考喂料，不代替决定） |
| **to-questionnaire** 信息在别人手里 | 「这个得问财务 / 同事 / 供应商」，常浩自己答不了 | 无；问卷发不发、怎么发由常浩定 | 收回答案后 → grill-with-docs 或 to-spec |
| **teach** 想学概念 | 「我想搞懂 X」「教我 Y」，是要学，不是要做 | 无 | 学完不接开发流程；之后要做东西再判档 |

## 「下一步呢」

1. 查清在哪一站：本会话做过什么；`docs/agents/` 有没有；`.scratch/` 或 GitHub 上有没有需求文档、任务卡，哪些关着；`git status`、`git log`、有没有开着的 PR。
2. 照档位的走法找下一站。查不出档位的，按 SKILL.md 第 2 节重新判。
3. 按 SKILL.md 第 5 节写下一站卡片。确实什么都没在进行：说明「没有进行中的流程」，问常浩想做什么。
