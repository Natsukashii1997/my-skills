# my-skills 协作约定（Codex / Claude 必读）

常浩自建 skill 的唯一存放处。所有面向用户的文字用简体中文。怎么新建、怎么链接见 [README.md](README.md)。

## 规则

- 自建 skill 一律建在 `skills/<名字>/`，再按 `links.tsv` + `scripts/link.sh` 链接出去；不直接建在 `~/.claude/skills`、`~/.agents/skills`、`~/.codex/skills`。第三方安装的 skill 不放这里。
- `skills/` 下就是正在用的版本，改了马上生效；改动大的先在 `~/Sandbox/` 里试，再改这里。
- 每次增改单独提交，提交说明写改了哪个 skill、为什么；改完推送到 GitHub。
- Codex 安装、更新或启用 skill 前按 `~/.codex/contracts/skill-admission.md` 审查。
- 仓库是私有的，但仍不写入账号、token 或凭据。
