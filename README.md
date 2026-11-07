# my-skills

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
| [ai-landing-method](skills/ai-landing-method/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「AI 落地三步法」：访谈提纲 → 技术方案 → 执行规范；先几轮提问把情况和材料问清楚（使用者不用懂方法），像 grill-me 那样把角色、新老、业务线、情境等差异问到底；再判断、填标准提示词槽位，按「从证据到决定」底层框架和数据本体论盘点材料、取证、按读者的论证逻辑排结构，出有网页质感的单页 HTML 报告（默认 hairline-page 风格），对照质量特征自检、机械核对并独立审查；Claude、Codex 通用 |
| [session-retro](skills/session-retro/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「会话复盘」：读本机 Claude Code、Codex 会话记录，筛出纠正、连续失败、被拒绝的调用和明确决定，整理成规则 / 坑 / 决定三类提案；只出提案，不写规则文件和知识库 |
| [automation-checkup](skills/automation-checkup/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「自动化体检」：只读检查本机自建的定时任务和常驻服务（launchd、hermes 定时任务、crontab），出一页报告，分「需要处理 / 注意 / 正常」三档，写清原因和怎么办，并和上次对比；体检本身不动任何任务，点名「处理 N」才动手 |
| [worktree-sweep](skills/worktree-sweep/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「worktree 清理」：扫描各项目堆积的 git worktree，按合并状态、未提交/未推送内容、闲置时长等分成「可安全删除 / 需要看一眼 / 保留」三档并算可回收空间；默认只列清单，确认后才删「可安全删除」档，从不碰远端 |

链接关系以 [links.tsv](links.tsv) 为准。

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
