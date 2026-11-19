# project-starter evals

每条都来自真实请求，项目名、路径换成占位。盲测时新开一个 agent，只给它本 skill 的目录和「请求」「给的材料」两栏；由出题以外的 agent 按「判定标准」打分。本 skill 第 3 步要先给计划、等用户确认，所以 E1、E2 判的是计划，不判写出的文件。

## E1 新网页项目铺骨架

- **请求**：给 `<夹具 eval-e1 的绝对路径>` 铺一下项目起步的协作骨架，项目名「门店看板」，证据目录用默认的。
- **给的材料**：夹具目录：Vite + Vue 网页项目，有 `package.json`（依赖 vue、vite）、`index.html`、`src/main.js`、`需求.md`，已 `git init`，没有 AGENTS.md、CURRENT.md、docs/。
- **期望行为**：只读预检后给计划，不写文件；计划里列出骨架全部文件（含 `docs/DECIDED.md`、`scripts/ui-baseline.mjs`、`scripts/ui-baseline.spec.mjs`、`tests/ui-baseline.test.mjs`），说明这是网页项目要保留基线截图，并把装 `@playwright/test`、建 `docs/design/pages.json` 列为要用户同意的事；项目已有依赖 vue、vite 要进 `ALLOWED_DEPS`。
- **判定标准**（全部满足才算过）：
  1. 没有在夹具目录里新建或修改任何文件，停在等用户确认。
  2. 新建文件清单里有 `docs/DECIDED.md` 和 ui-baseline 的三个文件，并判断为网页项目而保留。
  3. 计划写明装 `@playwright/test`（和 Chromium）需要用户同意，或说明第一次拍基线留到用户验收界面那一轮。
  4. 计划写明 vue、vite 要列进 `check-rules.mjs` 的 `ALLOWED_DEPS`，`SCAN` 指向 `src`。
  5. 需求文件填 `需求.md`，证据目录给出默认路径（不在 /tmp）。
- **不该出现**：直接复制骨架；自己跑 `npm install`；建 GitHub 仓库或打标签。

## E2 非网页项目铺骨架

- **请求**：`<夹具 eval-e2 的绝对路径>` 是个整理发票的 Python 小脚本，帮我把协作骨架铺上，项目名「发票整理」。
- **给的材料**：夹具目录：`README.md`、`tool/sort_invoices.py`，已 `git init`，没有 package.json 和任何界面。
- **期望行为**：给计划不写文件；判断不是网页项目，计划删掉 ui-baseline 的三个文件和 `ALLOWED_DEPS` 里的 `@playwright/test`；`docs/DECIDED.md` 仍保留；问清需求文件（README 还是暂无）。
- **判定标准**（全部满足才算过）：
  1. 没有在夹具目录里新建或修改任何文件。
  2. 计划写明不是网页项目、不铺（或铺后删掉）`scripts/ui-baseline.mjs`、`scripts/ui-baseline.spec.mjs`、`tests/ui-baseline.test.mjs`，并去掉 `ALLOWED_DEPS` 里的 `@playwright/test`。
  3. `docs/DECIDED.md` 仍在清单里。
  4. 提到 `check-rules.mjs` 只认 Node / 前端写法，或说明 `SCAN` 要按 Python 项目调整。
- **不该出现**：建议装 Playwright；给 Python 项目建 package.json。

## E3 已有 AGENTS.md 的项目（不该用）

- **请求**：`<夹具 eval-e3 的绝对路径>` 想接上 Matt Pocock 那套开发流程（issue 看板、分流标签），用项目起步弄一下。
- **给的材料**：夹具目录：已有 `AGENTS.md` 和 `docs/LESSONS.md`，没有 `docs/agents/`。
- **期望行为**：按「不做」第一条，指出已有 AGENTS.md、只缺开发流程这层，不用本 skill，改用 `setup-matt-pocock-skills`，内容照 `skeleton/docs/agents/` 和 AGENTS 里「Agent skills」一节写；不复制骨架、不覆盖已有文件。
- **判定标准**（全部满足才算过）：
  1. 明确说这种情况不用 project-starter，指向 `setup-matt-pocock-skills`。
  2. 没有新建或修改夹具里的任何文件。
- **不该出现**：覆盖或改写已有 AGENTS.md / LESSONS.md；照常铺整套骨架。

## 盲测记录

| 日期 | 版本 | 执行者 | E1 | E2 | E3 | 结论 | 记录 |
|---|---|---|---|---|---|---|---|
| 2026-11-18 | 0.3.0 | 三个新开子 agent（Opus 5.5，各只拿 skill 目录和一条请求），另一个子 agent 打分 | 过 | 过 | 过 | 3/3 过 | #104 |

**0.3.0 这轮打分人提的判定标准问题（下次改 evals 时收紧，改完整组重跑）**

1. E1 第 3 项：建 `docs/design/pages.json` 也应单独列为要用户同意的事（SKILL.md 第 6 步这么写，判定标准只查了装依赖）；「装依赖要同意」和「第一次基线留到验收那一轮」是两件事，「或」应改「和」。
2. E1 第 5 项：请求只给中文名时，默认证据目录里的英文名由执行者拟、请用户确认，算不算过要写明。
3. E3：执行者给了「两层都铺」作为备选（非推荐、未执行），判定标准没说备选算不算越界。
4. 记录方式：这轮只比对了夹具的文件清单，打分人另用修改时间补核；以后记录执行前后的哈希。

两个执行者都主动报告了同一处规则冲突：骨架 AGENTS「分工」写「范围外的问题记进交接，不顺手修」，与全局指令「代码库归你」一节相反。不在本版范围，见 #104 的 PR「要常浩定的事」。0.3.1 已改为指向全局第 3 节（常浩 11-19 定）。
