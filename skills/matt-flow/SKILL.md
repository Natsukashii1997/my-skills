---
name: matt-flow
description: 「Matt 流程向导」：常浩提开发任务（做功能、改东西、修 bug、开新项目、「我有个想法」），或做完一步问「下一步呢」时使用。先判 0–3 档（顺手改 / 轻量 / 标准 / 大雾）或认出半路入口，再按 Matt Pocock 技能（grilling、grill-with-docs、to-spec、to-tickets、implement、tdd、code-review、diagnosing-bugs 等）的顺序带着走，每步结束给下一站。只管判档、导航和衔接，具体活交给对应技能。纯问答、非开发任务（写文章、查资料、飞书操作）、只让跑某个命令时不用。
metadata:
  version: "1.0.0"
  governance:
    network: optional
    external-writes: optional
    destructive-actions: none
    credentials: none
    dependencies:
      - git
      - gh
---

# Matt 流程向导

常浩没有技术背景，只会说想做什么。这个 skill 替他选 Matt Pocock 的技能、排好顺序、每步做完告诉他下一站。它只做三件事：**判档、导航、衔接**。每一站具体怎么做，以那个技能的原文为准。

## 1. 怎么调用 Matt 的技能

- **能自动调用的 11 个**（grilling、domain-modeling、codebase-design、tdd、code-review、diagnosing-bugs、research、prototype、pr、wizard、writing-for-agents）：Claude 里用 Skill 工具调 `mattpocock-skills:<名字>`。
- **其余的（上游锁成只能手动）**：读它的 `SKILL.md` 原文，照原文做；不改 Matt 的原文件。按名字找，不写死分类目录：

  ```bash
  find -L ~/.claude/plugins/marketplaces ~/.claude/skills -maxdepth 6 \( -path "*/mattpocock-skills/skills/*/<名字>/SKILL.md" -o -path "$HOME/.claude/skills/<名字>/SKILL.md" \) 2>/dev/null
  ```

  找到两份时用 `~/.claude/skills/` 那份（插件里 `in-progress/` 下的是未发布草稿）。同目录下原文引用的文件（如 `PHASE-BOUNDARIES.md`、模板）一并按需读。**找不到原文就明确告诉常浩「没找到 <名字> 的原文」并停在这一站**，不凭记忆执行。
- 原文写「Call the Skill tool with X」时，X 指 `mattpocock-skills:X`。
- **code-review 一律指 `mattpocock-skills:code-review`**（Standards + Spec 两轴审查）。Claude Code 自带的 `code-review`（找正确性 bug）不是这一站。写计划、写动作时用全名，免得到了这一站调错。
- **在 Codex 里**：一律读 `~/.agents/skills/<名字>/SKILL.md`（Codex 适配版）照做，对常浩称 `$名字`。

每个技能的白话作用、前后衔接、什么时候单独用，见 [references/skills.md](references/skills.md)。

## 2. 第一步：判档

先判是**档位**（从头开始的新任务）还是**半路入口**（第 3 节）。判完用一句话说出档位和理由。

| 档 | 什么样的任务 | 走法 |
|---|---|---|
| 0 档 · 顺手改 | 一两处小改，没有要决定的事（错字、文案、颜色值、配置项） | 直接做，不走流程 |
| 1 档 · 轻量 | 需求清楚、一个会话能做完 | grilling（一轮，最多 3 问）→ tdd → code-review |
| 2 档 · 标准 | 需求还模糊，或要改多处 | grill-with-docs →（需要看实物时）prototype → to-spec → to-tickets → implement 逐张（或 implement-spec 一次跑完）→ code-review → pr → retro |
| 3 档 · 大雾 | 全新项目，或方向不清的大工程 | wayfinder → 并入 2 档，从 to-spec 开始 |

- **0 / 1 档**：说完档位直接做。
- **2 / 3 档**：先只问一句，然后停下等回复：「我判断这是 X 档（理由），建议走 A → B → C，开始吗？」常浩回「好」就走；他改档就按他的。这一轮只说档位、理由、路线（含前置检查）和这一问，不提前列出后面要追问的问题。
- 判据、正反例、拿不准时怎么办、半路升降档：见 [references/tiers.md](references/tiers.md)。

## 3. 半路入口

常浩不是从头开始时，从对应的站接上，不重走前面的站。入口不判档，也不问「开始吗」，说一句「从 X 这站接上」就开始；那一站要对外写入的，照第 6 节第 3 条单独确认。

| 现状 | 从这站接上 |
|---|---|
| 想法已经聊清 | to-spec |
| 已有需求文档 | to-tickets |
| 已有任务卡 | implement |
| 代码已经写完 | code-review → pr → retro |
| 出 bug | diagnosing-bugs |
| 反馈和问题积压 | triage |
| 代码越来越乱 | improve-codebase-architecture |
| 听不懂刚才说的 | wait-what |
| 需要人亲手配置账号、密钥 | wizard |
| 需要查资料 | research |
| 信息卡在别人手里 | to-questionnaire |
| 想学一个概念 | teach |
| 问「下一步呢」 | 先查清现在在哪一站（看本会话、`docs/agents/`、`.scratch/`、issue、`git status` 和 `git log`），再给下一站 |

每个入口的识别信号、先决条件、做完接哪站：见 [references/entries.md](references/entries.md)。

## 4. 前置检查（项目第一次走 2 / 3 档时）

1. 看项目根目录有没有 `docs/agents/`。有就跳过本节。
2. 没有：项目**没有 AGENTS.md** → 先走 `project-starter`；**已有 AGENTS.md** → 先走 `setup-matt-pocock-skills`。这一步放在流程第一站，写进第 2 节那句提问里。
3. 任务卡放哪：已接 GitHub（`git remote -v` 里有 github.com）或铺过 project-starter 的项目用 **GitHub Issues**；没有 GitHub 的小项目用本地 **`.scratch/`**（setup 时选 Local markdown；project-starter 铺完但常浩不建 GitHub 仓库的，把 `docs/agents/issue-tracker.md` 换成 setup-matt-pocock-skills 的 `issue-tracker-local.md` 写法）。

0 / 1 档不做前置检查。

## 5. 每站收尾：下一站卡片

每站做完，下一站卡片并进常浩的「收尾三项」，写在答复最末：

```
**本次完成**：<刚完成的站和产出，附证据（文件、issue、提交号、测试结果）>
**当前状态**：〔状态词〕<X 档 · 第 n/N 站 <技能> 已完成>
**下一步**：下一站 `<技能>`（<白话：它做什么>），因为 <为什么是它>。你要做的：<具体动作，如「回复『好』」；不需要就写「无需动作，我接着做」>
```

- 一站还没做完就停下（等常浩回答、等他操作）时，「下一步」先写本站内他要做的事，再补半句「这站做完后，下一站是 `<技能>`」。修 bug 这类入口，下一站是 retro。
- 默认每站做完就停，等常浩回复再进下一站。常浩说「一口气做完」时连着走，遇到要他拍板、对外写入、或全局规则要求停的地方仍然停。
- 0 档和整个流程走完时：「本任务已结束，下一步无需任何动作。」
- 流程走完后，建议的最后一站是 retro（2 / 3 档）；出过 bug 的也建议 retro。

## 6. 铁律：和常浩现有规则的分工

1. **交接和上下文以常浩规则为准**。不用 Matt 的 `/handoff`、`/compact`、`/clear`。站与站之间默认在本会话继续（Matt `PHASE-BOUNDARIES.md` 第 1 问：下一站要用这一站的原话）。收到「上下文提醒」、要换工具或换目录时，按常浩全局规则第 5 节出交接卡，卡里写明档位、所在站和下一站。wayfinder 原文规定一个会话只解决一张决策卡：解决完一张，用交接卡提议新会话接下一张。原文里让子 agent 做的（implement-spec、code-review、research）照常用子 agent。
2. **要不要送 GPT 评审，按 `thinking-review`**。to-spec 写完、准备拆卡和实现之前，以及接手别人的方案时，是它的检查节点；判成 B / C 的直接继续。
3. **对外写入每次单独确认**：发 issue（to-spec、to-tickets、triage、wayfinder 都会发）、建或改标签、推送、开 PR、合并，做之前各问一次，即使 2 档开头已经回了「好」。写本地文件（含 `.scratch/`）不用问。
4. **改常浩定过的东西**，按全局规则第 15 节单独确认，流程里哪一站都一样。
5. **每轮都有收尾三项**，「下一步」写下一站（第 5 节）。
6. **说人话**：对常浩提到技能名时带一句白话作用；术语第一次出现时附一句白话，查 [references/glossary.md](references/glossary.md)。grilling 的问题里，技术事实自己查，只把要常浩拍板的决定交给他，每题给推荐答案，并用白话说清选不同答案的影响。
7. **项目约定优先于 Matt 的默认**：项目有自己的 PR 模板（`.github/pull_request_template.md`）就按项目模板写，pr 的证据和合并风险写进对应栏；项目有自己的分支、提交约定就照项目的。
8. **本 skill 只管「什么时候用、按什么顺序、谁来确认、怎么交接」**；每一站怎么做，以那个技能的原文为准。
