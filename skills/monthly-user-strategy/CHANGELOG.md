# monthly-user-strategy 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。升版本的规则见 `templates/CHANGELOG.md`；规则摘录跟随 niuma-home `docs/策略规则/` 的版本号，规则升版本时先核对 references 再升本 skill。

## 1.1.0 - 2026-11-08

按 GPT 独立深度验收（结论「需修改」，P1-01～05、P2-01/02/04）修订，对应 my-skills#75。GPT 对 1.1.0 的定向验收又指出三处，同版修完：

- 新增：业务证据的适用范围由 `assemble.mjs` 从原文推（国家名、学校名；存量一栏或老学员 / 新签等字样），和情境国家、Claim 人群对不上，或推不出国家，就不能把购买判断、学业需求、痛点提到 weak 以上，也不能撑 observed 痛点和实际商业关系。
- 修复：命令行先删旧产出再读输入；输入不是合法 JSON 时写 assemble-errors.txt、退出码 1，不再留下旧的 submit-args.json。
- 新增：`digest.mjs` 每个地区列「结束日分旬」；SKILL.md 第 5 步与 quality.md 写明上 / 中 / 下旬按 1–10 / 11–20 / 21 起逐校核对；evals E6 加第 6 条判定。

首轮修订：

- 新增：`assemble.mjs` 拦截购买判断（障碍、购买准备度）没有行为证据却超过 inferred + weak、管理判断或校历把购买判断提上去、observed 痛点没引用用户观察、unknown 的强度不是 none、每个情境缺四类需求 Claim 或缺某一人群的 readiness、弱证据主障碍没标「暂定研究重点」、自检「事实与来源核验」缺某个有情境地区的 `regionCheck`（逐校核过哪些学校、例外是哪几所）。
- 新增：研判稿必填 `basedOnFingerprint`；与当前底稿不同又没给 `--prev-facts` 时拦截，不再静默换 refVersions。
- 修复：组装每次先删旧的 document.json、submit-args.json，全部通过才写，失败只写 assemble-errors.txt。
- 改动：SKILL.md 第 3–6 步：行为证据只有事实记录、业务观察、Voice；地区概括逐校核对例外；`brief.external` 只写时间、注意力、排课影响；自检判法统一（有遗留疑点就判待确认）。
- 新增：单元测试 E6–E10 反例与正例（18 项）；evals 加 E6 地区概括、E7 证据充足时不过度保守。

## 1.0.0 - 2026-11-08

首版，对应 niuma-home#31（批 1·1e）。盲测结果见 evals.md；常浩在 PR 上批准后合并、链接。

- 新增：generate 模式（SCOUT 阶段 01–05、08）：取事实 → 情境 → 需求 → 障碍 → 地区优先级 → 组装与自检 → 提交 → 给预览入口。
- 新增：缺失降级（背景卡整张未填、缺存量用户情况、缺用户观察）；提交结果不明时不自动重试的处理顺序。
- 新增：`scripts/workdesk.mjs`（没接 MCP 时调工作台智能体工具）、`scripts/digest.mjs`（底稿压成按地区的事实表）、`scripts/assemble.mjs`（组装、补机械字段、本地预检、内容决定的幂等键）及单元测试。
- 新增：references 摘录 `docs/策略规则/` 的 scout-v1.1、schema 2.1、barrier-v2.1、lifecycle-v0.2、bizcard-v1、sources-v1.1、quality-v1、cases-v1.1。
