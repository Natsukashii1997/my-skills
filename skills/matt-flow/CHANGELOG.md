# matt-flow 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。升版本规则见 `templates/CHANGELOG.md`；每次升版本后重跑 evals。

## 1.0.0 - 2026-11-10

首次通过准入（闸 2），盲测结果见 evals.md。立项见 my-skills#82：依据常浩 2026-11-10 的直接要求和他确认的骨架，没有满足闸 1「真做过两次」这一条。依据的 Matt 技能版本：插件 `mattpocock-skills` 1.3.2（上游 `4ae2317`）。

- 新增：判档（0 顺手改 / 1 轻量 / 2 标准 / 3 大雾），2 / 3 档先一句话问再走，0 / 1 档直接做。
- 新增：12 个半路入口和「下一步呢」的定位方法。
- 新增：前置检查（第一次走 2 / 3 档看 `docs/agents/`：没有 AGENTS.md 用 project-starter，有的用 setup-matt-pocock-skills）；任务卡按项目放 GitHub Issues 或 `.scratch/`。
- 新增：下一站卡片并入收尾三项。
- 新增：只能手动的 Matt 技能按名字查原文照做，查不到就报错；Codex 读 `~/.agents/skills/`。
- 新增：与常浩规则的分工（交接卡代替 Matt 的 handoff / compact / clear、thinking-review、对外写入确认、已定内容确认、项目约定优先）。
- 新增：references：档位判定及正反例、半路入口表、技能卡片（插件 27 个 + 插件外 10 个）、精简术语表。
