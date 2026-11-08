# monthly-user-strategy 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。升版本的规则见 `templates/CHANGELOG.md`；规则摘录跟随 niuma-home `docs/策略规则/` 的版本号，规则升版本时先核对 references 再升本 skill。

## 1.0.0 - 2026-11-08

首版，对应 niuma-home#31（批 1·1e）。盲测结果见 evals.md；常浩在 PR 上批准后合并、链接。

- 新增：generate 模式（SCOUT 阶段 01–05、08）：取事实 → 情境 → 需求 → 障碍 → 地区优先级 → 组装与自检 → 提交 → 给预览入口。
- 新增：缺失降级（背景卡整张未填、缺存量用户情况、缺用户观察）；提交结果不明时不自动重试的处理顺序。
- 新增：`scripts/workdesk.mjs`（没接 MCP 时调工作台智能体工具）、`scripts/digest.mjs`（底稿压成按地区的事实表）、`scripts/assemble.mjs`（组装、补机械字段、本地预检、内容决定的幂等键）及单元测试。
- 新增：references 摘录 `docs/策略规则/` 的 scout-v1.1、schema 2.1、barrier-v2.1、lifecycle-v0.2、bizcard-v1、sources-v1.1、quality-v1、cases-v1.1。
