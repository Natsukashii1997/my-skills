# my-skills

当前阶段目标：常态维护（不设阶段目标）；在途单列（如 #77、#78）。（2026-11-08 常浩确认，digital-twin#114）

常浩自建的 skill 都放这里，只此一份。Claude 和 Codex 读的工具目录里放的是指向这里的软链接，改这里的文件马上生效；更新就是这个仓库的提交。

## 里面有什么

| skill | 链接到 | 说明 |
|---|---|---|
| [project-starter](skills/project-starter/SKILL.md) | `~/.agents/skills`（`~/.claude/skills` 再链到它） | 「项目起步」：给新项目铺 Claude/Codex 协作骨架 |
| [get-notes-retrieval](skills/get-notes-retrieval/SKILL.md) | `~/.agents/skills` | 检索常浩的 GET 笔记 |
| [business-project-router](skills/business-project-router/SKILL.md) | `~/.codex/skills` | 业务项目级思考与推进的总入口 |
| [codex-usage-retrospective](skills/codex-usage-retrospective/SKILL.md) | `~/.codex/skills` | 按时间段复盘 Codex 使用 |
| [lark-doc-refine](skills/lark-doc-refine/SKILL.md) | `~/.codex/skills` | 精修已有飞书文档 |
| [thinking-model-capture](skills/thinking-model-capture/SKILL.md) | `~/.codex/skills` | 沉淀思维模型候选 |
| [skill-governance-audit](skills/skill-governance-audit/SKILL.md) | `~/.codex/skills` | Skill 启用前的治理审计 |
| [excel-aura](skills/excel-aura/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「Excel-Aura」表格配色与版式标准：按表型给写法，10 套标准配色 +「底线 + 默认值」版式规则，带写入前预览和表格审查；新建、美化已有表都能用，飞书 / Excel 通用 |
| [ui-styles](skills/ui-styles/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「UI 风格库」：做任何给人看的网页或界面时优先用；12 种定稿风格（细线默认，另有终端、柔光、精密暗色、文档站、瑞士网格、便当卡片、数据表格、玻璃拟态、Material 层级、色块拼接、大字动效），每种一份 STYLE.md 加单文件参考页面；共用底线、动效只演示真实业务过程、自带截图自检脚本（原 hairline-page） |
| [ai-landing-method](skills/ai-landing-method/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「AI 落地三步法」：访谈提纲 → 技术方案 → 执行规范；先几轮提问把情况和材料问清楚（使用者不用懂方法），像 grill-me 那样把角色、新老、业务线、情境等差异问到底；再判断、填标准提示词槽位，按「从证据到决定」底层框架和数据本体论盘点材料、取证、按读者的论证逻辑排结构，出有网页质感的单页 HTML 报告（页面风格以 ui-styles 为准），对照质量特征自检、机械核对并独立审查；Claude、Codex 通用 |
| [session-retro](skills/session-retro/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「会话复盘」：读本机 Claude Code、Codex 会话记录，筛出纠正、连续失败、被拒绝的调用和明确决定，整理成规则 / 坑 / 决定三类提案；只出提案，不写规则文件和知识库 |
| [automation-checkup](skills/automation-checkup/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「自动化体检」：只读检查本机自建的定时任务和常驻服务（launchd、hermes 定时任务、crontab），出一页报告，分「需要处理 / 注意 / 正常」三档，写清原因和怎么办，并和上次对比；体检本身不动任何任务，点名「处理 N」才动手 |
| [worktree-sweep](skills/worktree-sweep/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「worktree 清理」：扫描各项目堆积的 git worktree，按合并状态、未提交/未推送内容、闲置时长等分成「可安全删除 / 需要看一眼 / 保留」三档并算可回收空间；默认只列清单，确认后才删「可安全删除」档，从不碰远端 |
| [thinking-review](skills/thinking-review/SKILL.md) | `~/.claude/skills` | 「思维评审」：Claude 在任务的关键节点（接手别人的方案、方案成形要动工、前提被证伪、反复返工）判断当前问题是 A 思维评审、B 工程审查、A+B 还是 C 直接执行；A 类按准入判断决定要不要经驿窗交 ChatGPT High，按「全景 → 深化 → 收敛」递进，想清楚就按四种退出交回执行；只对接驿窗现有接力协议，不改驿窗 |
| [vault-backup](skills/vault-backup/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「知识库备份」：给 Obsidian 知识库和只在本机的 Git 项目做加密、增量、可异地的备份（restic），检查完整性、演练恢复 |
| [monthly-user-strategy](skills/monthly-user-strategy/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「月度用户策略」generate 模式：替常浩生成牛马之家某个月的月度用户策略，经 workdesk 工具取事实底稿、按 SCOUT 阶段 01–05 研判、组装 schema 2.1 文档并自检，提交为待确认 submission，常浩在工作台页面确认；缺背景卡按规则降级，提交结果不明不自动重试；Claude、Codex 通用 |
| [matt-flow](skills/matt-flow/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「Matt 流程向导」：常浩要做软件、改代码，或开发流程进行中问「下一步呢」时自动用；先判 0–3 档（顺手改 / 轻量 / 标准 / 大雾）或认出半路入口，按 Matt Pocock 技能的顺序带着走，每站把「下一步回什么」写进收尾三项（只能手动的技能直接给出要回的命令）；分支、issue、PR 照 agent-kit 工程流程，交接、送 GPT、对外写入按常浩规则；Claude、Codex 通用 |
| [decision-inbox](skills/decision-inbox/SKILL.md) | `~/.claude/skills` | 「拍板清单」：把 Claude 桌面应用里停下来等常浩的会话收成一张编号清单（要定什么、推荐、回这句话），常浩一条消息批量回，再把原话逐条转给对应会话并回读；脚本先筛掉已交接、已回复、已忽略的假等待，对外动作和已定内容单独问，转达前复核、问题变了就作废；只在 Claude 桌面应用里用 |

链接关系以 [links.tsv](links.tsv) 为准。

**机器可读索引**：`node scripts/export-skill-index.mjs` 生成 `catalog/skills.json`（不入库，按需生成；`--stdout` 只打印），数码世界等只读消费方从这里取 skill 清单。发布状态、安装状态一律写「未核定」，缺的元数据写 null，口径见脚本开头注释。

## 一个 skill 的一生：七站两闸

skill 是要长期用、给别人用的资产，不是写完就放着的提示词。每个 skill 都按下面七站走，其中两站是闸：过不了闸就停在原地，不往下走。

| 站 | 做什么 | 留下什么 |
|---|---|---|
| 1. 候选 | 同一类事第二次让 AI 从头讲一遍，或者发现一段做法反复在用，就记成候选 | issue，标题「候选：<名字>」，写一两句起因 |
| 2. 立项（**闸 1**） | 输入、步骤、判断点、输出都已经稳定：至少真做过两次，两次走法一致。写清边界：什么时候用、什么时候不用、和现有 skill 怎么分工 | 同一张 issue 补上边界；不稳定就留在候选 |
| 3. 编写 | 在 worktree 分支里写 `skills/<名字>/SKILL.md`；同时按 [templates/evals.md](templates/evals.md) 写 3–5 条真实请求当 evals | SKILL.md、evals.md |
| 4. 准入（**闸 2**） | 三件事都过才算过：① `skill-governance-audit` 的 `pre-install` 0 错误，每条 warning 写明处置；② 盲测：新开一个 agent，只给它 skill 目录和 evals 里的请求，evals 全部通过；③ 常浩在 PR 上批准 | PR 里贴审计结果和盲测记录；盲测记录同时写进 evals.md |
| 5. 发布 | `metadata.version` 定为 `"1.0.0"`，按 [templates/CHANGELOG.md](templates/CHANGELOG.md) 写首版；登记 `links.tsv` 和上面的表，合并后链接（见下） | CHANGELOG.md，README 表格里一行 |
| 6. 观测 | Claude 的调用由 agent-kit 的 hook 记到 `~/Library/Application Support/agent-kit/skill-usage.jsonl`，Codex 的从会话记录里统计；每月跑一次 `node scripts/monthly-health.mjs` 看调用次数、最近使用、版本、有没有 evals 和 CHANGELOG | 月度体检报告 |
| 7. 进化 / 退役 | 进化：按 CHANGELOG 模板的规则升版本，改完重跑 evals。退役：长期 0 调用、和别的 skill 重复、或已被取代的，体检只出提案，常浩同意后才删目录、删 `links.tsv` 的行、从上表移除，并在 CHANGELOG 末尾记一条退役 | CHANGELOG 新条目；退役 PR |

存量 skill（没有版本号、evals、CHANGELOG 的）不用一次补齐：下次改它时先补这三样，再按「进化」走。

frontmatter 里版本号这样写（字符串，带引号）：

```yaml
metadata:
  version: "1.0.0"
```

### 链接的具体步骤

1. 目录名和 frontmatter 里的 `name` 一致，`link.sh` 会核对。
2. 在 `links.tsv` 加行：两边都要用就各加一行 `~/.claude/skills` 和 `~/.agents/skills`；只给 Codex 用就写 `~/.agents/skills` 或 `~/.codex/skills`。
3. 开 PR，合进 main（见 [AGENTS.md](AGENTS.md) 末尾）。
4. 主目录 `git pull --ff-only`，再在主目录跑 `sh scripts/link.sh`。`link.sh` 在 worktree 里会拒绝运行：在那里建的链接会随 worktree 删除一起断掉。

改名或删掉 skill 后，`link.sh` 会提示工具目录里留下的断链，确认不用了手动 `rm` 掉。

## 换电脑或链接坏了

```sh
git clone https://github.com/Natsukashii1997/my-skills.git ~/Documents/ChatGPT/个人/work/my-skills
sh ~/Documents/ChatGPT/个人/work/my-skills/scripts/link.sh
```

`link.sh` 可重复执行；目标位置已是真实目录时会跳过并提示，不会覆盖。
