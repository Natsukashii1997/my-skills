# project-starter 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条一致。升版本的规则见仓库 `templates/CHANGELOG.md`：改措辞升修订号，骨架加文件、加检查或步骤升次版本，改骨架文件格式（让已经起步的项目对不上）升主版本。改了 `skeleton/` 的脚本或测试，要把骨架复制到一个空目录、填好占位后跑 `node --test tests/*.test.mjs`（骨架原样跑时 CURRENT.md 还是占位，交接格式那条必然不过）。改完重跑 [evals.md](evals.md)。

还没过闸 2（没做 `skill-governance-audit` 审计，也没经常浩在 PR 上按准入批准），所以停在 0.x。

## 0.3.0 - 2026-11-18（#104）

月度复盘的两条结论落到骨架：教训停在文字层（LESSONS 条目缺「升级」行、升级积压没人发现），已定内容没有基准（认可过的界面被后续提交逐步改偏、大改动丢功能几天后才发现）。

- 新增：`check-rules.mjs` 的 lessons 规则：`docs/LESSONS.md` 每条 L-xx 必须有「- 升级：」一行，开头是〔结构〕〔机检〕〔体检〕〔文字〕〔提醒〕之一（口径同 agent-kit 全局 LESSONS）；代码块里的格式样例不算。测试样本摘自 postpane 的 3 条真实条目。
- 新增：`check-rules.mjs` 的 bigchange 规则：当前分支相对 `origin/main` 改了 100 个文件及以上（含未提交、未跟踪的），CURRENT.md 必须比 `origin/main` 上多一节「改前改后功能对照」；不在 git 仓库、没有 `origin/main` 时跳过。测试按 digiworld 提交 `0f03467` 的规模（760 个文件）造样本。交接模板和 OPERATIONS「交接写法」补上这一节的写法。
- 新增：`docs/DECIDED.md` 已定内容登记表；AGENTS 导航表、结构加指针。
- 新增：`scripts/ui-baseline.mjs`（兼 Playwright 配置）与 `scripts/ui-baseline.spec.mjs`：网页项目拍基线、和基线对比，用 Playwright 自带的 `toHaveScreenshot`，差异图写到证据目录；`tests/ui-baseline.test.mjs` 自测，没装 Playwright 时跳过。`ALLOWED_DEPS` 加 `@playwright/test`。
- 改动：骨架 LESSONS 的格式样例「- 升级：未升级。」改为「- 升级：〔提醒〕未升级。」，「怎么升级」加一条层级词说明；SKILL.md 第 6 步写明网页项目和非网页项目各怎么处理新文件。
- 新增：本文件、evals.md、`metadata.version`（存量 skill 补齐）。

## 0.2.1 - 2026-11-18（7e4f99b，#103）

- 改动：建 GitHub 仓库默认建公开仓库（常浩 11-18 定）。

## 0.2.0 - 2026-11-07（59d8a40，#50）

- 新增：骨架 `check-rules.mjs` 加 G-07 来源校验、G-08 `set -u` 可选变量两条规则。

## 0.1.0 - 2026-10-27（48e5ed7）

建立 my-skills 仓库时迁入：协作规矩（AGENTS 入口与导航表、LESSONS、交接模板与格式测试、防伪造五条、通用规则检查）和 Matt Pocock 开发流程两层骨架。
