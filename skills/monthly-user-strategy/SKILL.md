---
name: monthly-user-strategy
description: 「月度用户策略」generate 模式：替常浩生成牛马之家某个月的月度用户策略。按 SCOUT-8 阶段 01–05 和 08，经 workdesk 工具 strategy_facts 取事实底稿，定情境、解需求、判购买障碍、定地区优先级，组装成 schema 2.1 月度文档，自检后用 strategy_submit 提交为待确认 submission，再请常浩去工作台页面预览、确认；缺业务背景时按规则降级，提交结果不明时先查 submission，不自动重试。常浩说「生成 2026-12 的用户策略」「跑一下 12 月的月度策略」「出下个月用户策略」「monthly-user-strategy」时使用。不适用：refresh / review / refine 三种模式、写促销方案或打法（批 2）、确认或拒绝 submission（只在页面做）、旧月份迁移、修改策略规则本身、与牛马之家无关的一般策略分析（用 strategy-master）。
metadata:
  version: "1.1.0"
  governance:
    network: required
    external-writes: required
    destructive-actions: none
    credentials: required
    dependencies:
      - node
---

# 月度用户策略 · generate

替常浩生成一个月的月度用户策略，交到工作台待确认。工作台本身不调用模型：skill 在 Claude 或 Codex 会话里运行，经 workdesk 工具读事实、交 submission；常浩在工作台页面预览、确认后，才成为正式版本。

规则的唯一来源是 niuma-home 仓库 `docs/策略规则/`（批 0 规格）。`references/` 是摘录，每份写了出处和版本号；摘录和原文对不上时以原文为准，并提醒常浩更新本 skill。读不到原文（例如会话不许碰那个仓库）时按摘录做，并在答复里说明没核对原文版本。

## 1. 边界

**用**：常浩要某个月（`YYYY-MM`）的月度用户策略，本机牛马之家在跑，会话里拿得到 workdesk 凭据。

**不用**（说明原因，不硬套）：

- refresh、review、refine 三种模式（批 2、批 3）；常浩要的是这些时，说明当前只支持 generate。
- 促销方案、打法、机会 P0/P1/P2：批 2 才实现，批 1 提交里 `opportunities`、`strategies` 必须为空。
- 确认、拒绝、回退 submission：只在页面做；skill 没有、也不找这类接口。
- 改 `docs/策略规则/` 里的规则：走方法论修订流程（08 §4），AI 不在单月里自行改规则。
- 与牛马之家无关的一般策略分析、问题拆解。牛马之家本身的促销、复审要求不要转去别的 skill 出替代品：说明在批 2，由常浩决定先记下还是他自己处理。

**只经工作台工具读写**：`strategy_facts`（只读）、`strategy_submit`（只能创建待确认 submission）、`strategy_submission`（查状态）。不读写数据库、不读 `data/` 目录、不调页面接口、不碰正式服务的进程。

## 2. 准备

1. **工具接入**，两种都走工作台的智能体接口（授权、留痕在服务端），效果相同：
   - 会话里接了 workdesk MCP（`server/mcp-workdesk.mjs`）：直接调同名工具。每次调用的参数里加 `_caller: { "platform": "local-session", "chatType": "p2p", "userId": "changhao" }`，否则服务端回 `400 CALLER_REQUIRED`。
   - 没接 MCP：用 `node scripts/workdesk.mjs <工具> …`（脚本已带 caller）。环境变量 `WORKDESK_AGENT_TOKEN`，或 `WORKDESK_ENV` 指向写有它的 `.env`；`WORKDESK_URL` 默认 `http://127.0.0.1:5280`。
2. **凭据由常浩签发**（niuma-home `scripts/agent-token.mjs issue <agent> strategy_facts,strategy_submit,strategy_submission`）。没有凭据就停下来请常浩签发，skill 不自己对正式数据目录签发、轮换或撤销凭据。`401`：凭据无效；`403 TOOL_FORBIDDEN`：凭据没授权这个工具。两种都停下来告诉常浩，不换别的路子绕过。
3. **工作目录**：`~/Library/Application Support/NiumaHome/evidence/strategy-<月份>-<YYYYMMDD-HHMM>/`。底稿、摘要、研判稿、文档、提交结果都放这里，不放 `/tmp`。`WORKDESK_URL` 不是正式的 `http://127.0.0.1:5280`（隔离测试工作台）时，目录名末尾加 `-test`，和正式产出分开。

## 3. 流程

### 第 0 步 · 确认月份与背景卡

- 月份不明确就问一次（推荐：下个月）。
- 取完底稿（第 1 步）发现业务背景卡整张没填或缺「存量用户情况」「用户观察」，而常浩没说过「直接生成」：问一次，推荐「先在页面补背景卡再生成」，备选「按降级直接生成」。常浩要先补，就按 `references/lifecycle-bizcard.md` 第 5 节起草预填稿交给他，本轮到此为止；他说直接生成或已经说过不填，就按降级继续，不再追问。

### 第 1 步 · 事实取证（阶段 01）

1. `strategy_facts { month }` → 存为 `facts.json`。
   - `409 TIMELINE_RESYNC`：**停止生成**，请常浩先到工作台「策略 → 用户时间」同步一次时间线。
   - 其他错误：照实报告，不编底稿。
2. `node scripts/digest.mjs facts.json --out digest.md`，读 `digest.md`（不要整份读 `facts.json`，太大）。
3. 记下 `inputFingerprint`、`baseRevision`、各地区覆盖率与默认优先级、背景卡哪些字段有内容、正式版本里有没有常浩手写的 Claim。
4. 列出不确定性：推测、冲突未决、只有月份、锚点不明、`ambiguous`。这些不能当精确日期用。摘要最后一列是原格原文：同一格写了几个日期、跨年日期段被解析成「仅月份」、列名和内容对不上的，记为时间线疑点。
   - `verification=verified` / `ruled` 而原格原文（`source.raw`）写着「推测」「AI推测」、日期还差一两天，是**正常的**：官网核实、人工裁定本来就是来纠正原表推测的，生效日期以核实结果为准，强度照常 strong，不降级、不当疑点。

阶段要求见 `references/scout-generate.md`，窗口与覆盖率怎么读见 `references/lifecycle-bizcard.md`。

### 第 2 步 · 情境定位（阶段 02）

- 每个地区 0–4 个情境（通常 1–3 个），按「地区与学校 + 学业阶段 + 关键任务 + 目标人群」分，任务、困难、时间窗相同的合并。研究生节点明显不同时单列。
- `evidenceRefs` 只从摘要里抄 Evidence ID，至少一个。`schools` 照抄底稿的校名。
- `academicStage`：底稿事件的 `scope` 写了「仅研究生」等限定，或常浩、背景卡给了研究生的不同节点，才单列 `postgraduate` 情境；没有这类信息时按 `undergraduate` 写，并在 `research.assumptions` 记一句「时间线未标学业阶段，按本科处理」。
- `observedRelation`：只有引用 business 类 Evidence 时才能写新签 / 续费，否则 `unknown`。
- 证据不够形成独立情境的地区：`scenarios` 留空，`emptyReason` 写原因和覆盖情况（学校数、可计算数、活跃数、数据不足数），不编学生群体。
- 字段见 `references/schema.md` 第 2 节。

### 第 3 步 · 需求解码（阶段 03）

每个情境至少写 `task`、`academic_need`、`pain`、`need_strength` 各一条：

- `task`：引用的事件是官网核实或人工裁定的（强度上限 strong）才能 `known + strong`；原表日期最高 `inferred + partial`；推测最高 `inferred + weak`。
- `academic_need`：只有时间线证据时一律 `inferred + weak`（潜在需求，考试存在不等于有辅导需求），用克制写法；有业务观察、事实记录或 Voice 支撑时才到 partial 以上。不能写成已验证需求。
- `pain`：`painKind=observed` 必须引用对应的「用户观察」条目（或 Voice），否则只能 `typical`，且最高 `inferred + weak`。不把「有考试」写成「学生缺乏复习能力」。
- `need_strength`：`level` 高 / 中 / 低，`rule` 写窗口规则版本（如 `lifecycle-v0.2/Final`）；覆盖率是日历推断，不是付费需求。
- `text` 不超过 40 字，结论先行，不写编码。

### 第 4 步 · 决策洞察（阶段 04）

按情境的 `targetRelation` 研判：新签情境研判新签，续费情境研判续费，通用情境两边都研判，**分开写**。每组（情境 × 人群）写 1–3 条 `barrier` 和 1 条 `readiness`：

- 编码、判定要点、相近障碍区分见 `references/barriers.md`。
- **没有用户决策行为证据**（背景卡的事实记录、业务观察，或 Voice）时：`BR-M2`、`BR-M5` 只能 `unknown`；其他障碍最高 `inferred + weak`，limitations 写「缺少用户决策行为证据」；任何障碍都不能 `known`（09 #2）。
- **没有「存量用户情况」**时：续费的 barrier、readiness 一律 `unknown`，gap「缺少存量学员下一阶段任务与续报信息」，route `{ status: available, source: SRC-bizcard }`；不从新签复制续费障碍（09 #4）。
- 每组恰好一个 `barrierRole=primary`，理由写进 `rule`。主障碍只有 `inferred + weak` 或 `unknown` 时，`rule` 里写「暂定研究重点」，正文和答复里称它为「待验证的障碍假设」，不说成确定的主导原因（批 2 不能拿它直接定促销方向）。
- `unknown` 的 route 只能指向来源登记表里的 ID：`SRC-bizcard` 可补 → `available`；`SRC-voice`、`SRC-crm` 未接入 → `unavailable`。
- **购买准备度（readiness）和障碍同理**，是购买行为判断：没有用户决策行为证据时写 `unknown`（gap 写缺什么，route 指向 `SRC-bizcard`），最多 `inferred + weak`；有行为证据才往上提。
- **背景卡条目没写学校时**，只套用到它描述的时间和任务对得上的情境（例：「想等 1 月考完再决定」只对 1 月考试的情境成立，不套到 12 月就考完的学校），在 limitations 写明套用理由；对不上的情境照没有证据处理。
- **行为证据只有三种**：背景卡的事实记录（可到 known）、业务观察（最高 inferred + partial）、Voice。学校日历再强（官网核实）也只证明节点存在，不证明购买行为；管理判断是待检验的假设，单独或和校历一起引用都最高 `inferred + weak`。`assemble.mjs` 会按这条拦截。
- **证据要对得上判定要点**：引用的业务证据必须直接说到这个障碍的判定要点（例如「觉得还来得及」要有推迟、观望、问「晚点再报行不行」这类时间判断的行为），只是间接相关的不能把障碍往上提，照「没有行为证据」处理；`evidenceRefs` 只放真正支撑这条判断的证据，不为凑强度多挂。
- 学业需求（第 3 步）和购买需求（本步）不混写。

### 第 5 步 · 地区优先级与一句话判断（阶段 05，批 1 范围）

- 六个地区都给 `priority`：默认矩阵（摘要里已算好）只是参考；与默认不同写 `reason`。覆盖率高不等于付费需求大，样本很小、日期质量差时可以调档。
- 一句话月度判断：不超过 100 字，引用至少一条本稿 Claim。
- **地区概括要核对例外**，范围是所有写地区结论的地方：一句话判断、`brief.diff`、`brief.external`、情境的 `phase` / `keyTask`、Claim 正文，以及给常浩的答复。做法：先按地区写 `brief.diff`，每个地区回到摘要事件表逐校看一遍，把例外写进去；**一句话判断从 `diff` 压缩出来，压缩时保留「多数 / 部分」这类限定词，或带上例外**，不能在压缩时把例外丢掉（例：diff 写了「UNSW 期末至 12 月 10 日」，判断就不能写「澳洲已转入出分与补考」）。用了「均、都、全部、已结束、基本、普遍」这类说法，要么确实没有例外，要么写出例外学校（例：「多数已进入出分与补考阶段，UNSW 期末持续到 12 月 10 日」），要么改成限定说法（「多所学校…，部分持续至下旬」）。引用了真实 Evidence 不等于归纳出的文字就对。
- `brief.common` / `diff` / `external`：共性、地区差异、外部变量。背景卡整张没填时，`common` 第一条写「本月未提供业务背景，用户需求与购买判断均基于学校时间线推断」。`external` 只写节假日、出行、学校放假对学生**可用学习时间、注意力和排课**的影响，以及考试与出分节点怎样交错；不写等优惠、家长参与决策这类消费心理推断（那属于购买研判，要有行为证据或写成明确的待验证假设）。
- 想到的机会方向记进 `research.notes`（批 2 才写 Opportunity），不写进正式字段。

### 第 6 步 · 组装与自检（阶段 08 前半）

1. 按 `references/schema.md` 第 5 节写 `draft.json`：`basedOnFingerprint` 写研判时底稿的 `inputFingerprint`（digest.md 顶部），`declared.executor` 写当前执行方（Claude 或 Codex），`model` 写当前模型。
2. 按 `references/quality.md` 第 1 节逐项自检，结论写进 `research.selfCheck`；逐条对照第 3 节的四个反例。「事实与来源核验」带上 `regionCheck`：每个有情境的地区一句，写核过哪些学校、例外是哪几所、落到了哪句话里（没有例外就写「逐校核过 N 所，无例外」），脚本缺了会拦截。
3. `node scripts/assemble.mjs facts.json draft.json --out-dir <工作目录>`。
   - 脚本每次先删掉目录里旧的 `document.json`、`submit-args.json`；全部通过才写新的，失败只写 `assemble-errors.txt`。所以目录里有 `submit-args.json`，就一定是最近一次通过的那份。
   - 退出码 2：按「拦截」逐条改研判稿，重跑，直到通过。「提示」逐条看，能改就改。拦截项包括：每个情境缺四类需求 Claim 之一、缺该人群的 readiness（判断不了写 unknown）、购买判断没有行为证据却超过 inferred + weak、observed 痛点没引用用户观察、弱证据主障碍没标「暂定研究重点」、自检缺某个有情境地区的 `regionCheck`。
   - 通过后得到 `document.json`、`submit-args.json` 和 `idempotencyKey`（由月份、输入指纹和内容哈希决定：内容不变，键就不变）。
4. 组装通过后、提交前，**重取一次底稿**（`strategy_facts` → `facts-check.json`）比 `inputFingerprint`。没变就提交；变了就按下面「底稿变了」处理。

### 第 7 步 · 提交（阶段 08）

`strategy_submit`，参数就是 `submit-args.json`（MCP 方式再加 `_caller`）；结果存为 `submit-result.json`。

| 结果 | 怎么办 |
|---|---|
| 成功：`{ id, state: "pending", warnings, stale: false }` | 记下 `id`，进第 8 步。`warnings` 原样转告常浩 |
| 成功但 `stale: true` | 已建成，但底稿在研判后变了，常浩确认时会被拒。按下面「底稿变了」处理一次 |
| 成功且 `repeated: true` | 同一内容早已提交过，返回的是原 submission，不是新建；照第 8 步告诉常浩 |
| `422 STRATEGY_INVALID` | 没保存。按服务端列出的原因（规则编号 + 对象 ID）改研判稿，重新组装（内容变了，键自然变），再提交。服务端一次最多列 8 条，可能要几轮；同一原因改两次还过不了，停下来报告 |
| `409 IDEMPOTENCY_CONFLICT` | 同一个键之前交过不同内容。不要换键硬交：先查明是哪次提交（常浩页面上的待确认列表），再决定 |
| `400` | 参数问题，按原因改 |
| `401` / `403` | 凭据问题，停下来请常浩处理（第 2 节） |
| **结果不明**：超时、断线、`5xx`、`workdesk.mjs` 退出码 3 | 见下一节，**不自动重试** |

### 底稿变了

`inputFingerprint` 和研判时不同（提交前复核发现，或提交返回 `stale: true`）：

1. 用新底稿重组装，并带上研判时的旧底稿：`node scripts/assemble.mjs facts-new.json draft.json --out-dir <目录> --prev-facts facts.json`。研判稿的 `basedOnFingerprint` 和新底稿不同时，不给 `--prev-facts` 脚本直接拦截，不会把旧判断悄悄换成新版本。脚本会拦下引用的 Evidence 版本变了或消失的对象：只重新研判这些对象，其余不动；全部没变的，`basedOnFingerprint` 保持研判时的值，不要改成新指纹。
2. 通过后提交新的那份（指纹变了，键自然变），旧文件改名留档（`-1` 后缀）。
3. **只重做一次**。重交后仍然 `stale: true`，或几分钟内指纹又变，不再循环：把两次的 `inputFingerprint`、变化的内容（用 digest 对比）报告给常浩，由他决定。
4. 之前那条过期的 submission 不用 skill 处理：常浩确认新的那条时，同月其余待确认提交会自动转为过期；他也可以在页面直接拒绝。答复里写明两条的 id 和哪条是新的。

### 结果不明

不知道 submission 有没有建成时，不再调 `strategy_submit`：

1. 手上有 submission `id`（例如提交返回了、但后续步骤出错）：调 `strategy_submission { id }` 查状态，照实告诉常浩。
2. 没有 `id`：告诉常浩「提交结果不明」，给出 `idempotencyKey` 和 `submit-args.json` 的路径，请他看工作台页面的待确认列表里有没有这个月新出现的 submission。
3. 常浩明确说「重提」后，才用**同一份** `submit-args.json`（同一个键、同一份内容）再交一次：之前已建成的会原样返回（`repeated: true`），没建成的会新建。重提时不改内容、不换键。

### 第 8 步 · 答复与预览入口

答复里写清：

- 提交结果：submission `id`、状态、`agent`（服务端从凭据认定的）、提交时间、服务端提示。
- 预览入口：`<工作台地址>/#/user/strategy`（策略 → 用户策略）的待确认区，工作台地址就是 `WORKDESK_URL`（默认 `http://127.0.0.1:5280`）；页面还没有待确认区时，预览接口是 `GET <工作台地址>/api/v3/strategy-v2/submissions/<id>/preview`。**请常浩在页面预览、确认**；skill 不会、也不能替他确认。
- 内容摘要（只写文档里确实有的内容，说法和文档一致）：一句话判断；底稿里看到的时间线疑点（例如同一格两个日期、冲突未决、跨度异常长的日期段），提醒常浩去时间线页核对；六个地区的优先级（与默认不同的附理由）、情境数；空地区及原因；主要的 unknown 与缺口（尤其是缺背景卡导致的降级）；自检里的「待确认」项。
- 工作目录路径（底稿、文档、提交结果都在那里）。

## 4. 不许做

- 编 Evidence ID、学校、日期，或把推测、只有月份、冲突未决的日期当精确日期写。
- 没有行为证据写 `known` 的障碍；从新签复制续费障碍；把覆盖率写成「需求旺盛」「付费意愿强」。
- 写 `origin=manual`，改动或删除常浩手写的 Claim（`assemble.mjs` 会原样带上）。
- 往 `opportunities`、`strategies` 里写东西；写促销、打法、价格、限时类建议。
- 结果不明时自动重提；换 `idempotencyKey` 绕开 409。
- 调确认、拒绝、回退接口，读写数据库或 `data/`，对正式数据目录签发凭据。
- 自行修改 `docs/策略规则/` 或本 skill 的规则摘录来让提交通过。
