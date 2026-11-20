# project-starter 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条一致。升版本的规则见仓库 `templates/CHANGELOG.md`：改措辞升修订号，骨架加文件、加检查或步骤升次版本，改骨架文件格式（让已经起步的项目对不上）升主版本。改了 `skeleton/` 的脚本或测试，要把骨架复制到一个空目录、填好占位后跑 `node --test tests/*.test.mjs`（骨架原样跑时 CURRENT.md 还是占位，交接格式那条必然不过）。改完重跑 [evals.md](evals.md)。

还没过闸 2（没做 `skill-governance-audit` 审计，也没经常浩在 PR 上按准入批准），所以停在 0.x。

## 0.4.1 - 2026-11-20

- 修复：`scripts/hooks/pre-push` 从 worktree 推送时会把测试里的 git 操作落到真实仓库上。git 在 worktree 里跑钩子时会带上仓库位置（`GIT_DIR`），测试在临时目录建仓库、提交、推送都继承了它：推送的分支多出测试的提交，主目录被改成裸仓库、不能用，而测试照样全过。钩子现在在跑检查前清掉这些变量（`unset $(git rev-parse --local-env-vars)`）；`tests/hooks.test.mjs` 自己的 git 调用也不再继承。
- 新增测试：从 worktree 真推一次，测试命令里建仓库、提交，核对推送的分支和主目录没被动。旧钩子下这条失败。
- 验证：骨架复制到空目录、`git init` 后 `node --test tests/hooks.test.mjs` 原样 `ℹ pass 4` / `ℹ fail 0`；换回 0.4.0 的 `pre-push` 后 `ℹ pass 3` / `ℹ fail 1`，失败在「测试命令的提交落到了推送的分支上」。
- 已经用 0.4.0 装过钩子的项目要各自补这一处；补之前不要从 worktree 推送，或先 `git config --unset core.hooksPath`。

## 0.4.0 - 2026-11-20

复盘 P4、P5、P6 落到骨架（常浩 11-20 批：P4、P5「批」，P6「批（按改过的）」）。

- 新增：`scripts/hooks/pre-push`（推送前跑 `check-rules.mjs` 和测试，不过就不推；慢项目把 `TESTS` 改成只跑快的部分）、`scripts/hooks/commit-msg` + `commit-msg.mjs`（标题以 fix 或「修」开头的提交，正文没有「同类：」一行就拒绝；「修改」「修订」和 Merge、Revert、fixup!、squash! 不查）；`tests/hooks.test.mjs` 单测加临时仓库真跑，样本含 agent-autoloop #280 的真实提交说明。SKILL.md 加第 7b 步装钩子，骨架 AGENTS「运行」加安装命令。`--no-verify` 由 agent-kit guard-git 拦（agent-kit#97）。
- 改动（格式）：交接模板、PR 模板、OPERATIONS 的「验证」一行拆成「验证环境：真实 / 替身 / 无需」和「外部前提与实测」两行；`tests/handoff-format.test.mjs` 查这两行，验证环境须以真实、替身、无需或「未在真实环境验证」开头（全局第 11 节「替身上通过不算验收」）。已起步的项目手里是旧版测试，不受影响；要跟上就复制新版测试和模板。
- 验证：骨架复制到空目录、填占位、`git init` 后 `node --test tests/*.test.mjs` 原样 `ℹ tests 11` / `ℹ pass 10` / `ℹ fail 0`（ui-baseline 没装 Playwright 跳过 1 条），`check-rules` 通过。验证环境：替身（临时仓库）；evals 没重跑（判定标准不涉及钩子，E1、E2 的计划清单会多出 `scripts/hooks/`，下次重跑时补进期望）。

## 0.3.2 - 2026-11-19

- 改动：骨架 LESSONS「怎么升级」的状态词加「关闭」（坑本身已被代码消除，不再需要升级），写法「〔层级〕关闭（日期，依据）：证据」，同 agent-kit 全局 LESSONS（agent-kit#84，常浩 11-19 批）。只改措辞，`check-rules.mjs` 只查层级词开头，不用改；evals 判定标准不涉及这一句，没重跑。

## 0.3.1 - 2026-11-19

- 改动：骨架 AGENTS「分工」原写「范围外的问题记进交接，不顺手修」，与全局指令「代码库归你」一节（11-10 取消「范围外不顺手修」）相反，0.3.0 两个盲测执行者都报了这处冲突。改为指向全局第 3 节：相关的顺手修并分栏列出，改变已有行为或碰已定内容的先问，不相关的记进交接（常浩 11-19 定）。只改措辞，evals 判定标准不涉及这一句，没重跑。
- 修复：`check-rules.mjs` 的 lessons 规则把标题反引号里的 `<…>`（如剪藏插件 L-02 的 `` `<all_urls>` ``）当成占位，整条不查，漏报。改为先去掉反引号里的内容再判断是不是占位标题；测试加这条真实标题做样本。剪藏插件 chatgpt-clipper#10 补齐升级行时发现。

## 0.3.0 - 2026-11-18（#104）

月度复盘的两条结论落到骨架：教训停在文字层（LESSONS 条目缺「升级」行、升级积压没人发现），已定内容没有基准（认可过的界面被后续提交逐步改偏、大改动丢功能几天后才发现）。

- 新增：`check-rules.mjs` 的 lessons 规则：`docs/LESSONS.md` 每条 L-xx 必须有「- 升级：」一行，开头是〔结构〕〔机检〕〔体检〕〔文字〕〔提醒〕之一（口径同 agent-kit 全局 LESSONS）；代码块里的格式样例不算。测试样本摘自 postpane 的 3 条真实条目。
- 新增：`check-rules.mjs` 的 bigchange 规则：当前分支相对 `origin/main` 改了 100 个文件及以上（含未提交、未跟踪的），CURRENT.md 必须比 `origin/main` 上多一节「改前改后功能对照」；不在 git 仓库、没有 `origin/main` 时跳过。测试按 digiworld 提交 `0f03467` 的规模（760 个文件）造样本。交接模板和 OPERATIONS「交接写法」补上这一节的写法。
- 新增：`docs/DECIDED.md` 已定内容登记表；AGENTS 导航表、结构加指针。
- 新增：`scripts/ui-baseline.mjs`（兼 Playwright 配置）与 `scripts/ui-baseline.spec.mjs`：网页项目拍基线、和基线对比，用 Playwright 自带的 `toHaveScreenshot`，差异图写到证据目录；`tests/ui-baseline.test.mjs` 自测，没装 Playwright 时跳过。`ALLOWED_DEPS` 加 `@playwright/test`。
- 改动：骨架 LESSONS 的格式样例「- 升级：未升级。」改为「- 升级：〔提醒〕未升级。」，「怎么升级」加一条层级词说明；SKILL.md 第 6 步写明网页项目和非网页项目各怎么处理新文件。
- 新增：本文件、evals.md、`metadata.version`（存量 skill 补齐）。
- 修复：过期说法改为指向本 skill 的 `skeleton/`：SKILL.md 开头「源仓库是 agent-kit」、「骨架怎么进化」里的「改 agent-kit 里的 `skeleton/`」，骨架 CURRENT.md 的「agent-kit 的 `skills/project-starter`」（agent-kit 里没有 `skeleton/`）。

## 0.2.1 - 2026-11-18（7e4f99b，#103）

- 改动：建 GitHub 仓库默认建公开仓库（常浩 11-18 定）。

## 0.2.0 - 2026-11-07（59d8a40，#50）

- 新增：骨架 `check-rules.mjs` 加 G-07 来源校验、G-08 `set -u` 可选变量两条规则。

## 0.1.0 - 2026-10-27（48e5ed7）

建立 my-skills 仓库时迁入：协作规矩（AGENTS 入口与导航表、LESSONS、交接模板与格式测试、防伪造五条、通用规则检查）和 Matt Pocock 开发流程两层骨架。
