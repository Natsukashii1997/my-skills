# my-skills 协作约定（Codex / Claude 必读）

常浩自建 skill 的唯一存放处。所有面向用户的文字用简体中文。怎么新建、怎么链接见 [README.md](README.md)。

## 规则

- 自建 skill 一律建在 `skills/<名字>/`，再按 `links.tsv` + `scripts/link.sh` 链接出去；不直接建在 `~/.claude/skills`、`~/.agents/skills`、`~/.codex/skills`。第三方安装的 skill 不放这里。
- `skills/` 下就是正在用的版本，改了马上生效；改动大的先在 `~/Sandbox/` 里试，再改这里。
- 每次增改单独提交，提交说明写改了哪个 skill、为什么。
- Codex 安装、更新或启用 skill 前按 `~/.codex/contracts/skill-admission.md` 审查。
- 仓库是私有的，但仍不写入账号、token 或凭据。

## Skill 生命周期：七站两闸

候选 → 立项（闸 1）→ 编写 → 准入（闸 2）→ 发布 → 观测 → 进化 / 退役。每站做什么、留下什么见 [README.md](README.md)「一个 skill 的一生」。agent 必须守的几条：

- **闸 1 立项**：输入、步骤、判断点、输出没稳定（没真做过两次、两次走法不一致），只记候选 issue，不建 `skills/<名字>/`。立项时在 issue 里写清边界：什么时候用、什么时候不用、和现有 skill 怎么分工。
- **编写时同时写 evals**：按 `templates/evals.md` 写 3–5 条真实请求，其中至少一条是不该用这个 skill 的。
- **闸 2 准入，三件都过才激活**（激活 = 合进 main 并跑 `link.sh`）：
  1. `skill-governance-audit` 的 `pre-install` 0 错误，每条 warning 写明处置；
  2. **盲测**：新开一个 agent（子 agent 或新会话），只给它 skill 目录和 evals 的「请求」「给的材料」，不给当前会话的上下文和额外说明；由出题之外的一方按「判定标准」打分，evals 全部通过。不过就改 skill 后整组重跑。盲测记录写进 evals.md 和 PR；
  3. 常浩在 PR 上批准。
- **发布与进化**：版本写在 SKILL.md frontmatter 的 `metadata.version`（字符串），和 `CHANGELOG.md` 最上面一条一致；首次过闸定 `"1.0.0"`，之后按 `templates/CHANGELOG.md` 的规则升版本，改完重跑 evals。存量 skill 下次改动时先补版本号、evals、CHANGELOG。
- **退役与合并只出提案**：月度体检或审计发现重复、长期 0 调用、已被取代的 skill，写提案给常浩，不自己删目录、改 `links.tsv`。

改动怎么走（issue → 分支 → PR → squash 合并）、分支怎么起名、交接写在哪：见 `/Users/nat/Documents/ChatGPT/个人/work/agent-kit/工程流程.md`。PR 正文按 `.github/pull_request_template.md` 写。
