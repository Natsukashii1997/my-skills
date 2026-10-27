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

链接关系以 [links.tsv](links.tsv) 为准。

## 新建一个 skill

1. 在 `skills/<名字>/` 下写 `SKILL.md`（目录名和 frontmatter 里的 `name` 一致）。
2. 在 `links.tsv` 加行：两边都要用就各加一行 `~/.claude/skills` 和 `~/.agents/skills`；只给 Codex 用就写 `~/.agents/skills` 或 `~/.codex/skills`。
3. 跑 `sh scripts/link.sh`，再按《工程流程》走 PR 合进 main（见 [AGENTS.md](AGENTS.md) 末尾）。

## 换电脑或链接坏了

```sh
git clone https://github.com/Natsukashii1997/my-skills.git ~/Documents/ChatGPT/个人/work/my-skills
sh ~/Documents/ChatGPT/个人/work/my-skills/scripts/link.sh
```

`link.sh` 可重复执行；目标位置已是真实目录时会跳过并提示，不会覆盖。
