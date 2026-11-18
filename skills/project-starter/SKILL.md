---
name: project-starter
description: 「项目起步」：给新项目、或还没有 AGENTS.md / LESSONS 的项目铺 Claude 与 Codex 接力用的两层骨架：协作规矩（AGENTS 入口与导航表、LESSONS 与三级升级、交接模板与格式测试、防伪造五条、通用规则检查脚本、已定内容登记表、网页基线截图对比）和 Matt Pocock 开发流程（GitHub Issues 看板、分流标签、领域文档约定、AGENTS 里的 Agent skills 一节）。仅在用户要求给项目铺协作骨架、或显式调用 project-starter 时使用；先列计划等确认，不覆盖已有文件。
metadata:
  version: "0.3.0"
  governance:
    network: none
    external-writes: required
    destructive-actions: none
    credentials: none
    dependencies:
      - node
---

# 项目起步

把一套中性的两层骨架铺进一个项目。协作规矩这层（agent-kit 管）：AI 读的入口、坑怎么记怎么升级、每轮怎么交接、交接写得对不对由测试查、能机检的规矩由脚本查（含 LESSONS 每条的「升级」行、大改动的改前改后对照）、用户定过的内容登记在哪、网页界面怎么和基线截图比。开发流程这层（Matt Pocock skills 管）：`docs/agents/` 三份约定和 AGENTS 里的「Agent skills」一节，`to-spec`、`to-tickets`、`implement`、`tdd`、`code-review` 等技能都从这里读 issue 看板和标签。骨架在本 skill 的 `skeleton/`，源仓库是 `/Users/nat/Documents/ChatGPT/个人/work/agent-kit/`。

## 先问清（已知的不重复问，一次问完）

1. 项目目录（绝对路径）和项目名。
2. 需求或说明文件是哪份；没有就写「暂无」。
3. 证据目录：验证用的备份、日志放哪（默认 `~/Library/Application Support/<项目英文名>/evidence/`，不放 `/tmp`）。
4. 是不是独立 git 仓库（`git -C <项目> rev-parse --show-toplevel` 是否等于项目目录）；不是的话要不要 `git init`，由用户定。
5. GitHub 仓库：默认 `Natsukashii1997/<项目英文名>`。还没有远端的，问用户要不要建仓库，默认建**公开**仓库（常浩 2026-11-18 定：名下仓库全部公开、新仓库默认公开，省 GitHub Actions 额度）；建仓和推送都是外部写入，用户同意才做；推送前确认没有真密钥、令牌。

## 步骤

1. 记开工：`date '+%F %H:%M'`。
2. 只读预检：`ls -la <项目>`；对 `skeleton/` 里每个文件，看项目里有没有同名文件。已有的一律不覆盖，列为冲突，问用户怎么并。
3. 给用户看计划：将新建的文件清单、每个占位填什么、冲突怎么处理。**等用户确认再写。**
4. 复制：`cp -Rn <本 skill 目录>/skeleton/. <项目>/`（`-n` 不覆盖已有文件）。
5. 填占位，填完 `grep -rn '{{' <本次新建的文件>` 必须为空：
   - `AGENTS.md`：`{{项目名}}`、`{{一句话说明}}`（这是什么、给谁用）、`{{需求文件}}`、`{{证据目录}}`。没有需求文件时，把引用它的那句和那一行改成「暂无需求文件」。
   - `docs/agents/issue-tracker.md`：`{{GitHub仓库}}`。
   - `CURRENT.md`：`{{日期}}`、`{{阶段}}`、`{{下一步}}`、`{{执行方}}`（Claude / Codex）、`{{提交状态}}`、`{{开工时刻}}`、`{{测试结果}}`、`{{检查输出}}`、`{{遗留}}`。
6. 按项目实际改 `AGENTS.md`：「结构」列出项目里已有的目录和文件；「运行」加项目自己的命令；「规则」不适用的条删掉。`scripts/check-rules.mjs` 的 `SCAN` 指向项目源码目录；项目已有依赖要列进 `ALLOWED_DEPS`，并在交接里写明。
   - 网页项目：基线截图要用 `@playwright/test`（已在 `ALLOWED_DEPS` 里）。装依赖、建 `docs/design/pages.json`（格式见 `scripts/ui-baseline.mjs` 开头）列进第 3 步的计划，用户同意再装；第一次拍基线等用户验收界面的那一轮再拍，并登记进 `docs/DECIDED.md`。
   - 不是网页项目：删掉 `scripts/ui-baseline.mjs`、`scripts/ui-baseline.spec.mjs`、`tests/ui-baseline.test.mjs`，`ALLOWED_DEPS` 里的 `@playwright/test` 和 AGENTS.md 里提到它们的几处一起删；`docs/DECIDED.md` 照样留着（文案、交互、数据格式也会定）。
7. 跑 `node --test tests/*.test.mjs` 和 `node scripts/check-rules.mjs`（在项目根目录），把原样结果填进 `CURRENT.md` 顶部那一节，再跑一次测试。
8. 有 GitHub 远端时，把 `docs/agents/triage-labels.md` 里的 5 个标签建上：`gh label create <标签> --description <含义> --force`（外部写入，列进第 3 步的计划，用户确认后再做）。
9. 用户同意提交时才提交，只提交本次新建的文件。

## 不做

- 已经有 AGENTS.md 的项目只缺开发流程这层时，不用本 skill，改用 `setup-matt-pocock-skills`，内容照 `skeleton/docs/agents/` 和 AGENTS 里那一节写。
- 不复制别的项目的业务规则、视觉规矩、发布脚本、巡检或定时任务；项目长出这些需要时，再在它自己的 AGENTS.md / OPERATIONS.md 里加。
- 不改项目已有文件（含需求文件），除非用户本轮点名。
- 不建 launchd 或定时任务，不 `git init`、不提交，除非用户本轮同意。
- 不往骨架里写任何人的私人信息、账号或凭据。

## 骨架怎么进化

在某个项目里发现骨架（模板、测试、检查脚本）该改的，先出提案、用户批准，再改 agent-kit 里的 `skeleton/` 并提交；已经起步的项目不自动同步，需要时按 diff 手工带过去。
