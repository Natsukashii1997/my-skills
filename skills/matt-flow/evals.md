# matt-flow evals

请求按常浩的说话习惯写，项目名用他真实在做的项目，内部数据没有出现。覆盖：0 档（E1）、1 档（E2）、2 档含前置检查（E3）、3 档（E4）、半路入口（E5a）、不该触发（E5b）。E5 的两条分开跑、分开判，两条都过才算 E5 过。

盲测时，新开一个 agent，只给它 `skills/matt-flow/` 目录和下面的「请求」「给的材料」，不给本会话的上下文和其他说明；让它写出收到请求后**第一轮**会做什么、回什么（含要调用的技能和要读的文件）。由出题以外的 agent 按「判定标准」打分。

## E1 0 档：错字

- **请求**：数码世界首页的标题「数码宝贝世界」打成了「数码宝贝事界」，帮我改一下
- **给的材料**：项目 `~/Documents/ChatGPT/个人/work/digiworld`，已有 AGENTS.md，已接 GitHub；没有 `docs/agents/`。
- **期望行为**：一句话说明是 0 档（一处错字、没有要决定的事），直接改、自己验，收尾三项「下一步」写本任务已结束。
- **判定标准**（全部满足才算过）：
  1. 判为 0 档，并用一句话给出理由。
  2. 不问「开始吗」，直接动手改。
  3. 不调用任何 Matt 技能（不 grilling、不 tdd、不 to-spec），不做前置检查。
  4. 结尾有收尾三项，「下一步」为本任务已结束、无需动作。
- **不该出现**：先追问需求；跑 setup-matt-pocock-skills 或 project-starter；建 issue。

## E2 1 档：加一列

- **请求**：自动化体检的报告里，每个任务再加一列「上次运行时间」
- **给的材料**：项目 `~/Documents/ChatGPT/个人/work/my-skills`，`skills/automation-checkup/` 下有脚本和 `tests/`；已有 AGENTS.md，已接 GitHub；没有 `docs/agents/`。
- **期望行为**：一句话判为 1 档（需求清楚、改动集中、一个会话做得完），不问「开始吗」；记下比较起点；grilling 一轮、最多 3 个关键问题，每题带推荐答案（如时间显示格式、从没运行过显示什么），tdd 的验证位置用白话并进这一轮；之后按 tdd → code-review（Matt 的）走。
- **判定标准**：
  1. 判为 1 档并给理由；不问「开始吗」。
  2. 第一站是 grilling，只问一轮且不超过 3 问，每题有推荐答案，用词是白话。
  3. 写明后面是 tdd → code-review，且 code-review 指 `mattpocock-skills:code-review`（或明确是 Matt 的两轴审查），不是 Claude Code 自带的。
  4. 不做 `docs/agents/` 前置检查，不走 to-spec / to-tickets。
  5. 本轮停在等常浩回答问题处，收尾三项「下一步」写清他要回答什么、下一站是什么。
- **不该出现**：走 2 档流程；要求先跑 setup-matt-pocock-skills；问超过 3 个问题或分多轮问。

## E3 2 档：跨模块新功能（含前置检查）

- **请求**：我想给数码世界加个功能：问一个问题，能同时查我 Obsidian 知识库里的笔记和以前的聊天记录，一起给我答案
- **给的材料**：项目 `~/Documents/ChatGPT/个人/work/digiworld`，已有 AGENTS.md，`git remote -v` 指向 github.com；没有 `docs/agents/`。
- **期望行为**：判为 2 档（要改多处、怎么合并两个来源的答案等还要取舍）；本轮只问一句「我判断这是 2 档……建议走 …… 开始吗？」，路线里第一站是 setup-matt-pocock-skills（已有 AGENTS.md、没有 `docs/agents/`），任务卡放 GitHub Issues；然后停下等回复。
- **判定标准**：
  1. 判为 2 档并给理由。
  2. 只用一句话提问「……开始吗？」，路线包含 grill-with-docs → to-spec → to-tickets → implement（或 implement-spec）→ code-review → pr → retro（prototype 可写成「需要时」）。
  3. 指出第一站是 setup-matt-pocock-skills（不是 project-starter），任务卡放 GitHub Issues。
  4. 本轮没有开始追问需求、没有写代码、没有发 issue。
  5. 收尾三项：状态〔等你决定〕，「下一步」写明回复「好」即开始。
- **不该出现**：直接开始 grill；选 project-starter；不问就跑流程；一次抛出多个问题。

## E4 3 档：方向不清的新项目

- **请求**：我想做一个管家里钱的系统，把几张信用卡、房贷、孩子的教育金都管起来，还没想好要哪些功能、做成网页还是 App
- **给的材料**：还没有项目目录，也没有 GitHub 仓库。
- **期望行为**：判为 3 档（全新项目、方向不清、要先做很多决定）；本轮一句话问「……建议走 wayfinder → to-spec → …… 开始吗？」，提到新项目没有 AGENTS.md 要先走 project-starter（建不建 GitHub 仓库由常浩定，不建则任务卡放 `.scratch/`）；停下等回复。
- **判定标准**：
  1. 判为 3 档并给理由。
  2. 路线是 wayfinder，地图清了并入 2 档、从 to-spec 开始。
  3. 提到前置：没有 AGENTS.md → project-starter；任务卡位置取决于有没有 GitHub。
  4. 本轮只问一句「开始吗」并停下；没有建目录、建仓库、写代码。
- **不该出现**：判成 1 档或直接 grill-me；替常浩建 GitHub 仓库；开始画地图前不问。

## E5 边界

### E5a 半路入口：bug

- **请求**：数码世界的知识库页面，点「同步」就一直转圈，昨天还好好的
- **给的材料**：项目 `~/Documents/ChatGPT/个人/work/digiworld`。
- **期望行为**：认出半路入口「出 bug」，不判档、不走 grill；进 diagnosing-bugs（`mattpocock-skills:diagnosing-bugs`），先建能复现的检查；说明修好后的下一站是 retro。
- **判定标准**：
  1. 认作半路入口（bug），从 diagnosing-bugs 接上，不从 grilling / to-spec 开始。
  2. 不问「开始吗」就开始诊断（这不是 2 / 3 档）。
  3. 提到修好后建议 retro。
- **不该出现**：判成 2 档并走需求流程；直接猜原因改代码而不先复现。

### E5b 不该触发：只跑命令

- **请求**：跑一下 `node --test tests/` 看看过没过
- **给的材料**：项目 `~/Documents/ChatGPT/个人/work/my-skills`。
- **期望行为**：不用本 skill：直接跑命令、报告结果，不判档、不推荐 Matt 技能。
- **判定标准**：
  1. 不判档、不给下一站卡片、不提任何 Matt 技能。
  2. 直接跑命令并报告结果。
- **不该出现**：「我判断这是 0 档」之类的判档话术。

## 盲测记录

| 日期 | 版本 | 执行者 | E1 | E2 | E3 | E4 | E5a | E5b | 结论 | 记录 |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | 1.0.0 草稿（第 1 轮） | 新开子 agent（general-purpose，Opus 5.5）作答；另开子 agent 只读 evals 和答卷打分 | 过 | 过 | 过 | 过 | 不过 | 过 | 不过：E5a 第 3 条，修 bug 停在诊断中途，没提「修好后下一站 retro」 | my-skills#82 的 PR |
| 2026-11-10 | 1.0.0 | 同上，执行者和评分者都换新的 | 过 | 过 | 过 | 过 | 过 | 过 | 全过 | my-skills#82 的 PR |

第 1 轮后的修改（整组重跑）：SKILL.md 第 5 节加「一站没做完就停下时，『下一步』补半句这站做完后的下一站；修 bug 入口的下一站是 retro」；第 1 节加「计划和动作里写 `mattpocock-skills:code-review` 全名」；第 2 节加「2 / 3 档提问那一轮不提前列出后面要追问的问题」。

两轮执行者拿到的都是去掉 evals.md、CHANGELOG.md 的 skill 副本，只有「请求」「给的材料」；评分者只读本文件和答卷。评分者提的非阻断意见（2 / 3 档提问那一轮回复偏长、R4 替常浩先拟了项目名等）记在 PR 里，留待观测期校准。
