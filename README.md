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
| [lumiedu-ai-collaboration](skills/lumiedu-ai-collaboration/SKILL.md) | `~/.codex/skills` | 路觅飞书 AI 自动化诊断（只能点名调用） |
| [lumiedu-automation-advisor](skills/lumiedu-automation-advisor/SKILL.md) | `~/.codex/skills` | 同上的另一版（只能点名调用） |
| [thinking-model-capture](skills/thinking-model-capture/SKILL.md) | `~/.codex/skills` | 沉淀思维模型候选 |
| [skill-governance-audit](skills/skill-governance-audit/SKILL.md) | `~/.codex/skills` | Skill 启用前的治理审计 |
| [excel-aura](skills/excel-aura/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「Excel-Aura」表格配色与版式标准：按表型给写法，10 套标准配色 +「底线 + 默认值」版式规则，带写入前预览和表格审查；新建、美化已有表都能用，飞书 / Excel 通用 |
| [hairline-page](skills/hairline-page/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「Hairline 细线」网页风格：方法论、方案讲解做成有网站质感的单文件 HTML；细线分层、识别色串主线、动效只演示真实业务过程 |
| [ai-landing-method](skills/ai-landing-method/SKILL.md) | `~/.claude/skills`、`~/.agents/skills` | 「AI 落地三步法」：访谈提纲 → 技术方案 → 执行规范；先几轮提问把情况和材料问清楚（使用者不用懂方法），像 grill-me 那样把角色、新老、业务线、情境等差异问到底；再判断、填标准提示词槽位，按「从证据到决定」底层框架和数据本体论盘点材料、取证、按读者的论证逻辑排结构，出有网页质感的单页 HTML 报告（默认 hairline-page 风格），对照质量特征自检、机械核对并独立审查；Claude、Codex 通用 |

链接关系以 [links.tsv](links.tsv) 为准。

## 新建一个 skill

1. 按《工程流程》开 issue、在 worktree 分支里写 `skills/<名字>/SKILL.md`（目录名和 frontmatter 里的 `name` 一致，`link.sh` 会核对）。
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
