# 技能卡片

依据：插件 `mattpocock-skills` 1.3.2（上游 `4ae2317`）各技能 `SKILL.md` 原文。这里只是导航用的摘要，执行时以原文为准。

「调用」一栏：**自动** = Claude 里用 Skill 工具调 `mattpocock-skills:<名字>`；**读原文** = 上游锁成只能手动，按 SKILL.md 第 1 节找到原文照做。Codex 里一律读 `~/.agents/skills/<名字>/SKILL.md`。

## 主流程

| 技能 | 白话作用 | 前一站 → 后一站 | 调用 | 什么时候单独拿出来用 |
|---|---|---|---|---|
| grilling | 一轮轮追问，把想法问透；每轮把现在能问的都问完，每题带推荐答案；事实自己查，决定交给人 | 判档 → tdd（1 档） | 自动 | 想把任何计划、决定压力测试一遍，又不需要留文档时 |
| grill-with-docs | grilling + domain-modeling：边问边把说定的词写进 `GLOSSARY.md`、把难反悔的决定写成 ADR | 判档 / 前置检查 → prototype 或 to-spec | 读原文（原文就是调 grilling 和 domain-modeling 两个技能） | 在项目目录里想把一个想法问透、并留下记录时 |
| prototype | 做个用完即弃的小样，回答一个纸上说不清的问题：逻辑对不对（单个 HTML 可点着玩），或界面长什么样（几版界面一键切换） | grill-with-docs → 回到 grill-with-docs 或 to-spec | 自动 | 任何「得看到才知道」的设计问题；不是做正式功能 |
| to-spec | 不再提问，把已经聊定的内容整理成需求文档，发到任务看板（issue），并先和人确认测试接缝 | grill-with-docs / wayfinder → to-tickets | 读原文 | 想法已经聊清、要落成文档时 |
| to-tickets | 把需求文档拆成一张张能独立验证的任务卡，标明谁挡着谁，确认拆法后发到看板 | to-spec → implement / implement-spec | 读原文 | 手里有需求文档或计划、要拆成能分头做的小块时 |
| implement | 按一张任务卡（或需求文档）写代码：在约定接缝上用 tdd，跑全量测试，做完调 code-review，提交到当前分支 | to-tickets → 下一张卡 / pr | 读原文 | 已有任务卡、只想做其中一张时 |
| implement-spec | 一次跑完整份需求：按任务卡的阻塞关系同时派多个子 agent 各做一张，合到一条集成分支，最后统一 code-review | to-tickets → pr | 读原文 | 卡多、彼此独立、想一次跑完时 |
| tdd | 测试先行：一次一个小切片，先写会失败的测试再写刚好通过的代码；测试只放在事先和人确认过的接缝上 | grilling（1 档）/ implement 内部 → code-review | 自动 | 想把一个具体行为先写测试再实现时，不需要整份需求 |
| code-review | 对比一个固定起点看改动，两个子 agent 分别查：守不守项目规范（含常见坏味道）、做的是不是需求要的 | tdd / implement → pr | 自动（`mattpocock-skills:code-review`，不是 Claude Code 自带的 `code-review`） | 任何时候想审一个分支、一个 PR、或「从某个提交以来的改动」 |
| pr | 写 PR 说明：最小的图或伪代码说明改了什么，前后对比证据，合并风险（能不能反悔、影响多大） | code-review → retro | 自动（项目有 PR 模板时以项目模板为准） | 任何要写 PR 说明的时候 |
| retro | 回看一次会话，提议改进 AI 的工作环境（导航指引、自动检查、审查规则、工具），不改代码；只出提议 | pr / diagnosing-bugs → 流程结束 | 读原文 | 一次开发不顺、或修完 bug 想知道怎样早点防住时。跨很多会话找规律用常浩的 `session-retro` |
| wayfinder | 大雾工程画「地图」：在看板上建一张总图和一串决策卡，一次解决一张（一个会话一张），只出决定、不出成品，路清了就交给 to-spec | 判档（3 档）→ to-spec | 读原文 | 全新项目或一个会话装不下、看不清路的大工程；范围清楚的功能不用 |

## 半路入口和独立技能

| 技能 | 白话作用 | 前一站 → 后一站 | 调用 | 什么时候单独拿出来用 |
|---|---|---|---|---|
| diagnosing-bugs | 修难缠的 bug：先造一个一跑就能复现这个 bug 的检查，再缩小、猜原因、加日志、修、补回归测试 | 出 bug → retro | 自动 | 原因不明、时好时坏、性能变慢的 bug |
| triage | 给别人提的 issue 分流：分类（bug / 新功能）、定状态（待评估、待补信息、可交给 AI、要人来做、不做），给可交给 AI 的写简报 | 反馈积压 → implement | 读原文 | issue 堆积要清理时；to-tickets 产出的卡不用分流 |
| improve-codebase-architecture | 扫代码找「浅模块」（接口和实现一样复杂），出一份带前后对比图的 HTML 报告，挑一个后追问到底 | 代码变乱 / retro → grill-with-docs | 读原文 | 有空时做保养，让代码更好测、AI 更好找 |
| research | 派一个后台子 agent 读一手资料（官方文档、源码、规范），把带出处的结论写成一个 Markdown 文件放进项目 | 需要查资料 → grill-with-docs | 自动 | 任何要查文档、API 事实的时候，边查边干别的 |
| wizard | 生成一个交互式脚本，一步步带人做只有人能做的事（开账号、拿密钥、填 CI 密钥），自动写进 `.env` 和 GitHub 密钥 | 被卡住的站 → 回到那一站 | 自动 | 遇到 AI 做不了、必须人亲手点的配置时 |
| to-questionnaire | 信息在别人脑子里时，替常浩写一份问卷发给那个人填；只问常浩「发给谁、要什么回来」 | 卡住 → grill-with-docs / to-spec | 读原文 | 要从同事、客户、供应商那里拿信息时 |
| wait-what | 刚才那段没看懂，让 AI 用简单英语加项目术语表重讲一遍 | 任何站 → 回到原站 | 读原文 | 任何听不懂的时候。给常浩重讲时用简体中文白话 |
| teach | 把当前目录当学习工作区，多次课学一个概念：使命、课件、参考卡、学习记录 | 想学概念 → 不接开发流程 | 读原文 | 想系统学一样东西时 |
| setup-matt-pocock-skills | 给已有项目配好 Matt 流程要用的三样：任务看板在哪、分流标签、领域文档放哪（写进 `docs/agents/`） | 前置检查 → 流程第一站 | 读原文 | 已有 AGENTS.md、第一次走 2 / 3 档的项目 |
| domain-modeling | 维护项目的「行话」：质疑模糊的词，写 `GLOSSARY.md` 和 ADR | grill-with-docs 内部 | 自动 | 一个词有几种意思、要定下来时 |
| codebase-design | 设计「深模块」的一套词：接口小、背后能力多、接缝清楚、好测 | tdd、improve-codebase-architecture 内部 | 自动 | 讨论一个模块的接口该长什么样时 |
| grill-me | 和 grill-with-docs 一样的追问，但什么都不存 | — | 读原文（原文就是调 grilling） | 不在项目目录里，只想把计划、设计、文章问透时 |
| handoff | 把当前会话压成一份交接文件 | — | 读原文 | **流程里不用**：交接按常浩全局规则第 5 节的交接卡 |
| ask-matt | Matt 自己的路线图：哪种情况用哪个技能 | — | 读原文 | 本 skill 判不准、想对照作者原意时读它和 `PHASE-BOUNDARIES.md` |
| writing-for-agents | 写给 AI 读的文档（skill、AGENTS.md）的写法 | retro 内部 | 自动 | 写或改 skill、AGENTS.md、CLAUDE.md 时 |

## 插件外的上游原版（`~/.claude/skills/`）

不在开发流程里，常浩点名或明确对上时才用，都读原文。

| 技能 | 白话作用 |
|---|---|
| claude-handoff | 把会话交给一个后台新 agent 接着做。流程里不用，交接按常浩规则 |
| git-guardrails-claude-code | 给 Claude Code 装钩子，挡住危险的 git 命令 |
| loop-me | 追问要搭的工作流的规格 |
| migrate-to-shoehorn | 把测试里的 `as` 类型断言换成 shoehorn |
| scaffold-exercises | 生成课程练习的目录骨架 |
| setup-pre-commit | 装 Husky 提交前检查（格式化、类型检查、测试） |
| setup-ts-deep-modules | 给 TypeScript 仓库接 dependency-cruiser，强制每个包只从入口文件访问 |
| writing-fragments / writing-shape / writing-beats | 写文章的三步：挖素材、成段、排节奏。写文章不是开发任务，本 skill 不触发 |
