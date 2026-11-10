---
name: monthly-user-strategy
description: 「月度用户策略」generate 模式：替常浩写牛马之家某个月的《月度用户策略报告》。主交付是一份八章、可从头读到尾的经营决策文档（月度总览 → 时间线与需求节奏 → 六地区需求深度分析 → 地区优先级与机会 → SKU 与产品价值 → 营销与促销 → 执行方针 → 关键假设），按五轮生成：完整研究（SCOUT 阶段 01–05，经 workdesk 工具 strategy_facts 取底稿）→ 洞察综合 → 商业策略设计 → 报告写作 → 新上下文独立审核；规格是 niuma-home `docs/策略规则/10-报告内容规格.md`（report-v2.1）。试写期默认不提交，常浩明确要求时才把研究层文档用 strategy_submit 提交为待确认 submission。常浩说「生成 2026-12 的用户策略」「跑一下 12 月的月度策略」「出下个月用户策略报告」「monthly-user-strategy」时使用。不适用：refresh / review / refine 三种模式、确认或拒绝 submission（只在页面做）、旧月份迁移、修改策略规则本身、定具体价格（价格模块）、与牛马之家无关的一般策略分析（用 strategy-master）。
metadata:
  version: "2.1.0"
  governance:
    network: required
    external-writes: optional
    destructive-actions: none
    credentials: required
    dependencies:
      - node
---

# 月度用户策略 · generate

替常浩写一个月的《月度用户策略报告》：既是这个月的说明文档，也是行动方针。工作台本身不调用模型；skill 在 Claude 或 Codex 会话里运行，经 workdesk 工具读事实，在证据目录里产出报告。

**为什么是报告**：1.x 把研究过程（情境、Claim、证据）当成了策略成果，常浩判为「看不懂、拆得太碎、没有结论、推断太浅」（2026-11-09）。2.0 起分三层：研究层（结构化、可追溯）是底座，综合层把零散事实变成相互关联的商业结论，报告层写给人读。**SCOUT-8 是内部研究方法，不是报告的章节；Claim 是中间资产，不是阅读单元。**

规则来源：niuma-home `docs/策略规则/`。报告层以 `10-报告内容规格.md`（report-v2.1）为准；研究层仍以 00–09 为准。`references/` 是摘录，每份写了出处和版本；对不上时以原文为准并提醒常浩更新本 skill；读不到原文时按摘录做，并在答复里说明。

## 1. 边界

**用**：常浩要某个月（`YYYY-MM`）的月度用户策略，本机牛马之家在跑，会话里拿得到 workdesk 凭据。

**不用**（说明原因，不硬套）：

- refresh、review、refine 三种模式：说明当前只支持 generate。对已有报告的复审要求，说明 review 模式还没做，由常浩决定。
- 确认、拒绝、回退 submission：只在页面做；skill 没有、也不找这类接口。
- 改 `docs/策略规则/` 的规则：走方法论修订流程（08 §4），AI 不在单月里自行改规则。
- 定价格、金额：归价格模块。报告写促销机制和条件，不编金额。
- 与牛马之家无关的一般策略分析。

**读写范围**：
- 工作台智能体工具：`strategy_facts`（只读）、`strategy_submission`（查状态）、`strategy_submit`（可选，只能建待确认 submission）。
- 试写期另外允许（常浩 2026-11-09 同意）：经 `scripts/product-context.mjs` 只读 `GET /api/promos`、`/api/plans/<月>/大学辅导`、`/api/v3/price/skus`；读 niuma-home 仓库的 `docs/打法库/`、`docs/策略输入/产品能力卡.md`。
- 不读写数据库、不读 `data/`、不调任何写接口、不碰正式服务的进程。

## 2. 准备

1. **工具接入**：会话接了 workdesk MCP 就直接调同名工具（参数加 `_caller: { "platform": "local-session", "chatType": "p2p", "userId": "changhao" }`）；没接就用 `node scripts/workdesk.mjs <工具> …`，环境变量 `WORKDESK_AGENT_TOKEN` 或 `WORKDESK_ENV` 指向写有它的 `.env`，`WORKDESK_URL` 默认 `http://127.0.0.1:5280`。不读出、不打印凭据内容。
2. **凭据由常浩签发**。没有就停下来请他签发；`401` 凭据无效、`403 TOOL_FORBIDDEN` 没授权，都停下来告诉他，不绕过。
3. **niuma-home 仓库**：常浩本机默认 `~/Documents/ChatGPT/个人/work/niuma-home`（下称 `<niuma-home>`），用来读规则原文、打法库、产品能力卡。
4. **工作目录**：`~/Library/Application Support/NiumaHome/evidence/strategy-<月份>-<YYYYMMDD-HHMM>/`，所有产出放这里，不放 `/tmp`。`WORKDESK_URL` 不是正式 5280 时目录名加 `-test`。

## 3. 流程：五轮

每轮单独完成、单独产出文件。**负责生成大量 Claim 的第 1 轮不同时承担洞察、商业设计和写作**，否则注意力会耗在填字段上。

### 第 0 步 · 月份与输入

- 月份不明确就问一次（推荐：下个月）。
- 取底稿：`strategy_facts { month }` → `facts.json`（`409 TIMELINE_RESYNC` 就停，请常浩先在「策略 → 用户时间」同步）；`node scripts/digest.mjs facts.json --out digest.md`，读摘要，不整份读 `facts.json`。
- 取产品与活动：`node scripts/product-context.mjs --month <月份> --out-dir <工作目录> --card <niuma-home>/docs/策略输入/产品能力卡.md --playbook <niuma-home>/docs/打法库`，读 `products.md`：活动基线、价格档案、能力卡逐项原文（没填的写「未填」）、打法卡索引（卡号、阶段、针对的障碍、机制、定位句）。
- **输入不足时问一次**（常浩说过「直接生成」就不问）：业务背景卡整张没填或缺「用户观察」「存量用户情况」，或产品能力卡大部分没填。推荐「先补再生成」，备选「按降级直接生成」。常浩要先补背景卡，就按 `references/lifecycle-bizcard.md` 第 5 节起草预填稿给他，本轮到此为止。
- **定报告等级**（规格 8.4，`references/report-spec.md` 第 4 节）：按 `digest.md` 的业务背景卡栏和 `products.md` 的能力卡、活动基线，定研究假设版 / 条件性策略版 / 可执行策略版，写进报告头，只能低报不能高报。问输入时顺带告诉常浩：现在的输入只够哪一级、补哪几项能升级。研究假设版：第三章 04–06 层以〔待验证假设〕为主，第五章卖点写「需确认产品能力」，第六章不出正式促销方案（只出「候选待确认」或本月不额外促销），第一章和第八章说明这一点。

### 第 1 轮 · 完整研究

照 `references/research.md`（SCOUT 阶段 01–05，即 1.x 的第 1–6 步）做：情境、四类需求 Claim、新签与续费分开的障碍和准备度、研究层的地区优先级与 `brief`、八项自检，`node scripts/assemble.mjs facts.json draft.json --out-dir <工作目录>` 直到预检通过。规则见 `schema.md`、`barriers.md`、`lifecycle-bizcard.md`、`quality.md`、`scout-generate.md`。

产出：`draft.json`、通过预检的 `document.json`。这是报告的研究底座和附录来源，不是报告。

### 第 2 轮 · 洞察综合

照 `references/insight.md`，只用第 1 轮产出和 `digest.md`，写 `synthesis.md`：

1. 每个地区：院校时间线六维聚合 → 地区规律（多数 / 例外）→ 用户状态与关键任务。
2. 核心场景，建议 3–6 个（证据不足可以少，写明原因；不为凑数拆场景；跨地区共有的场景只写一次，注明涉及哪些地区）：六层分析（事实、约束、动机、决策标准、价值、策略）、需求三问、购买障碍与行动时机（新签、续费分开）、四维（紧迫性、真实性、购买成熟度、服务可行性）。
3. 会影响主推 SKU、促销或资源投入的核心判断，至少比较一个替代解释。
4. 关键洞察清单（每条：核心结论、事实支撑、解释机制、适用范围、经营含义、可信程度）。
5. 策略综合与主线形成：主要需求归纳、跨地区共性与差异、月度核心论点、机会主题候选（建议 2–4 个，证据不足可以少于 2 个并写明原因）。

关键洞察从 I-01 起编号；「适用范围」写到国家和人群（新签 / 续费），不比证据宽：业务证据的范围看 `digest.md` 业务背景卡条目的「适用国家」「适用人群」两列。

缺少真实反馈时，不停在「可能需要辅导」：继续提出合理、可检验的机制假设，标〔待验证假设〕。研究层 `unknown` 或 `inferred + weak` 的购买判断，在这里和报告里只能是〔待验证假设〕。

### 第 3 轮 · 商业策略设计

照 `references/design.md`，只用 `synthesis.md` 和 `products.md`，写 `design.md`：地区决策表（主攻 / 培育 / 观察 + 机会阶段）与机会主题；每个主题的「用户关切 → 产品能力 → 卖点」，主推 SKU，七个 SKU 的角色；营销主张；促销方案（每个写促销目标、适用人群、核心机制、选择依据、商业约束、验证指标；候选从打法库选、过六个匹配条件；或结论为「本月不额外促销」）；现行活动的时间口径；执行方针（时间 × 部门、可执行事项）；3–5 项关键假设。

两张内部表必填（不进报告正文）：
- **候选卡核对表**：`products.md` 的打法卡只是索引。进入候选的卡逐张读原文，写适用人群 / 阶段、期限、产品条件、叠加限制、业务边界、生效 / 失效条件、是否采用及理由。
- **决策追溯表**：每个主推 SKU、核心卖点、正式促销方案都能沿「用户情境 → 需求洞察（I-xx）→ 商业机会 → 产品选择 → 价值主张 → 促销方案（卡号）→ 执行行动 → 验证指标」追回第 2 轮。

需求驱动产品：不先定 SKU 再编理由。卖点必须「用户确实在意 + 产品确实能提供」，能力卡没写的能力不承诺。

### 第 4 轮 · 报告写作

照 `references/report-spec.md` 写 `report.md`：八章 + 附录，二级标题一字不差，比重按规格，**第一章最后写**。正文写段落和必要表格，结论先行，地区分析用「结论 → 论证 → 行动含义」，关键判断标可信程度，边界集中写在节末、第八章和附录。正文不出现 Claim / Evidence 编号、状态码、障碍编码；附录可以有。

写完跑 `node scripts/report-check.mjs report.md --month <月份> --synthesis synthesis.md --design design.md --digest digest.md --products products.md --out report-check.txt`（后四个文件用来核对决策追溯和报告等级）：退出码 2 就按拦截逐条改，直到通过；提示逐条看，能改就改。

### 第 5 轮 · 独立质量审核

照 `references/quality-content.md` 第 3–5 节：开一个**新上下文**的审核方（Claude 用 Agent 工具开子 agent；Codex 开新会话），**不给 `synthesis.md`、`design.md` 和生成过程**，分两次给材料：
1. 视角一（管理者只读）：只给 `report.md` 和规格摘录，审核方复述主线、答五个强制问题、标出看不懂和推导断开的地方。
2. 视角二（回查事实）：视角一写完后，用 SendMessage 续同一个子 agent（Codex 在同一会话发第二条），再给 `report-check.txt`、`digest.md`、`products.md`，抽查事实、核对等级与能力卡，完成六项 30 分和一票否决。

两个视角都写进 `review.md`。

- 一次审核 → 按「必须修改」返修 `report.md`（重跑 `report-check.mjs`）→ 同一审核方定向复核，只核上次的问题。
- 复核后仍未解决的关键问题，写进答复交常浩裁决，不无限循环。
- 开不了独立审核方：`review.md` 写「第 5 轮未执行」及原因，答复里照实说；自评分数标「自评」，不当通过。

### 第 6 步 · 交付

**交付前复核输入有没有变**（写报告要几个小时，期间常浩可能同步了时间线、改了活动或能力卡）：
1. 重取底稿存为 `facts-recheck.json`，比较它和 `facts.json` 的 `inputFingerprint`。
2. 重跑 `product-context.mjs`，`--out-dir` 指向 `<工作目录>/recheck/`（目录不存在会自动建），`diff products.md recheck/products.md`。
3. 都没变：报告头的「资料截至」写复核时间。变了：判断影响哪几章；影响结论的，回到对应轮次改，重跑 `report-check.mjs`；来不及改的，在报告头和答复里写明「交付前输入有变：……，以下章节按旧输入」，不悄悄交付。

答复常浩：
- 报告路径（`<工作目录>/report.md`）、报告等级，以及用一段话转述第一章的主线和关键取舍；
- 交付前复核结果：输入没变，或变了什么、怎么处理的；
- 审核结果：六项分数与合计、五个问题、未解决的问题（审核没执行就照实说）；
- 第八章的 3–5 项关键假设，和最该补的输入（背景卡哪几栏、能力卡哪几个 SKU）；
- 底稿里的时间线疑点（同一格两个日期、跨年日期段被解析成仅月份、列名和内容对不上、先后顺序可疑），请常浩到时间线页核对；
- 工作目录里各轮文件：`digest.md`、`products.md`、`draft.json`、`synthesis.md`、`design.md`（含候选卡核对表、决策追溯表）、`report.md`、`report-check.txt`、`review.md`。

请常浩按 `quality-content.md` 的六项评分和五个问题验收报告（试写期同时给 A–D）。**试写期不提交结构化版本**；常浩明确说「提交结构化版本」时，按 `references/submit.md` 提交第 1 轮的研究层文档（提交前重取底稿比指纹；结果不明先查 submission，不自动重试）。

## 4. 不许做

- 编 Evidence ID、学校、日期、经营数据、收入目标、价格金额、产品能力、负责人；把推测、只有月份、冲突未决的日期当精确日期写。
- 把〔待验证假设〕写成已验证；研究层 `unknown` / `inferred + weak` 的购买判断在报告里被写成确定结论；把覆盖率写成「需求旺盛」「付费意愿强」。
- 先定 SKU 再编需求；写产品能力卡里没有的服务承诺（包过、几小时配到老师、退款）。
- 为填满报告生成促销；不写依据就选机制；把跨月或已过期的活动当成本月激励。
- 跳过 `report-check.mjs`，或把自评当独立审核；报告等级高报；交付前不复核输入，或输入变了不说。
- 只看打法库索引就定促销方案（进候选的卡要读原文）；`design.md` 不写决策追溯表，或追溯表里的洞察编号、主推、方案和报告对不上。
- 研究层：没有行为证据写 `known` 的障碍；从新签复制续费障碍；写 `origin=manual`、改动常浩手写的 Claim；往研究层 `opportunities`、`strategies` 写东西（当前 Schema 只接受空数组）。
- 结果不明时自动重提、换 `idempotencyKey` 绕开 409；调确认、拒绝、回退接口；读写数据库或 `data/`；调写接口；对正式数据目录签发凭据。
- 自行修改 `docs/策略规则/` 或本 skill 的摘录来让检查通过。
