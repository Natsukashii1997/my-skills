# 第 1 轮 · 完整研究（SCOUT 阶段 01–05 与组装预检）

从 1.2.0 SKILL.md 第 3 节第 1–6 步原样移来（2.0.0 起是五轮里的第 1 轮）。产出研究层的结构化资产：`facts.json`、`digest.md`、`draft.json`、组装预检通过的 `document.json`（要提交时另加 `--submit-args` 写出 `submit-args.json`）。这些是报告的研究底座，**不是报告本身**；第 1 轮只负责研究，不做洞察综合、商业设计和写作。

本文的「第 N 步」指第 1 轮内部的步骤；「第 8 步」「第 7 步」等提交相关的内容见 `submit.md`。

### 第 1 步 · 事实取证（阶段 01）

1. `strategy_facts { month }` → 存为 `facts.json`。
   - `409 TIMELINE_RESYNC`：**停止生成**，请常浩先到工作台「策略 → 用户时间」同步一次时间线。
   - 其他错误：照实报告，不编底稿。
2. `node scripts/digest.mjs facts.json --out digest.md`，读 `digest.md`（不要整份读 `facts.json`，太大）。
3. 记下 `inputFingerprint`、`baseRevision`、各地区覆盖率与默认优先级、背景卡哪些字段有内容、正式版本里有没有常浩手写的 Claim。
4. 列出不确定性：推测、冲突未决、只有月份、锚点不明、`ambiguous`。这些不能当精确日期用。摘要最后一列是原格原文：同一格写了几个日期、跨年日期段被解析成「仅月份」、列名和内容对不上的，记为时间线疑点。
   - `verification=verified` / `ruled` 而原格原文（`source.raw`）写着「推测」「AI推测」、日期还差一两天，是**正常的**：官网核实、人工裁定本来就是来纠正原表推测的，生效日期以核实结果为准，强度照常 strong，不降级、不当疑点。
   - 核实日期与原表**差三天及以上，或跨了旬、跨了月**：强度照常（以核实结果为准），但记为时间线疑点（本 skill 的报告口径，不是规则原文）：原表可能填错，也可能核实的是另一场考试。附录和交付答复里列出，请常浩到时间线页核对；正文按核实日期写，标「待核对」。

阶段要求见 `references/scout-generate.md`，窗口与覆盖率怎么读见 `references/lifecycle-bizcard.md`。

### 第 2 步 · 情境定位（阶段 02）

- 每个地区 0–4 个情境（通常 1–3 个），按「地区与学校 + 学业阶段 + 关键任务 + 目标人群」分，任务、困难、时间窗相同的合并。研究生节点明显不同时单列。
- `evidenceRefs` 只从摘要里抄 Evidence ID，至少一个。`schools` 照抄底稿的校名。
- `academicStage`：底稿事件的 `scope` 写了「仅研究生」等限定，或常浩、背景卡给了研究生的不同节点，才单列 `postgraduate` 情境；没有这类信息时按 `undergraduate` 写，并在 `research.assumptions` 记一句「时间线未标学业阶段，按本科处理」。
- `observedRelation`：只有引用 business 类 Evidence、且它的适用范围和本情境对得上（第 4 步）时才能写新签 / 续费，否则 `unknown`。
- 证据不够形成独立情境的地区：`scenarios` 留空，`emptyReason` 写原因和覆盖情况（学校数、可计算数、活跃数、数据不足数），不编学生群体。
- 字段见 `references/schema.md` 第 2 节。

### 第 3 步 · 需求解码（阶段 03）

每个情境至少写 `task`、`academic_need`、`pain`、`need_strength` 各一条：

- `task`：引用的事件是官网核实或人工裁定的（强度上限 strong）才能 `known + strong`；原表日期最高 `inferred + partial`；推测最高 `inferred + weak`。
- `academic_need`：只有时间线证据时一律 `inferred + weak`（潜在需求，考试存在不等于有辅导需求），用克制写法；有业务观察、事实记录或 Voice 支撑时才到 partial 以上。不能写成已验证需求。
- `pain`：`painKind=observed` 必须引用对应的「用户观察」条目（适用范围对得上本情境，第 4 步）或 Voice，否则只能 `typical`，且最高 `inferred + weak`。不把「有考试」写成「学生缺乏复习能力」。
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
- **业务证据只用在背景卡条目填了的适用范围里**（bizcard-v1.1）：只看 Evidence 上的 `countries`（适用国家）和 `relation`（适用人群），**不从原文推**，原文写了「英国」「新签」也不算。判法和服务端一致：国家与本处情境的 `countries` 至少一个相同；人群「通用」的条目对任何人群都算，「新签」「续费」只撑同一人群，本处是「通用」时只接受「通用」条目。本处人群：障碍、购买准备度看 Claim 的 `targetRelation`，实际商业关系看它自己的 `value`；学业需求、痛点（含 observed）看情境的 `targetRelation`，但只拦人群相反的：「通用」情境包含新签和续费两类学生，新签、续费条目都能用，新签情境不能用续费条目，反之亦然。没填（任一字段为空）按「范围不明」处理，和对不上一样：可以作为 `inferred + weak` 的线索引用，但不能把购买判断、学业需求、痛点提到 weak 以上，也不能撑 observed 痛点和实际商业关系。英国新签的台账不能拿来证明美国新签准备度。`assemble.mjs` 按这条拦截，并把引用了却没填范围的事实记录、业务观察列为「背景卡待补范围」。
- **行为证据只有三种**：背景卡的事实记录（可到 known）、业务观察（最高 inferred + partial）、Voice。学校日历再强（官网核实）也只证明节点存在，不证明购买行为；管理判断是待检验的假设，单独或和校历一起引用都最高 `inferred + weak`。`assemble.mjs` 会按这条拦截。
- **证据要对得上判定要点**：引用的业务证据必须直接说到这个障碍的判定要点（例如「觉得还来得及」要有推迟、观望、问「晚点再报行不行」这类时间判断的行为），只是间接相关的不能把障碍往上提，照「没有行为证据」处理；`evidenceRefs` 只放真正支撑这条判断的证据，不为凑强度多挂。
- 学业需求（第 3 步）和购买需求（本步）不混写。

### 第 5 步 · 地区优先级与一句话判断（阶段 05，研究层字段）

研判稿要求的 `priority`、一句话判断、`brief` 是研究层字段（组装脚本和服务端要它们）。报告第一、二、四章另外在第 2–4 轮重写，不照抄这里；但两边的事实与地区结论要一致。


- 六个地区都给 `priority`：默认矩阵（摘要里已算好）只是参考；与默认不同写 `reason`。覆盖率高不等于付费需求大，样本很小、日期质量差时可以调档。这是研究阶段的判断，不是本月的经营结论：报告第四章的主攻 / 培育 / 观察在第 3 轮按洞察另定，可以和这里不同（对应关系与写法见 `design.md` 第 1 节）。
- 一句话月度判断：不超过 100 字，引用至少一条本稿 Claim。
- **地区概括要核对例外**，范围是所有写地区结论的地方：一句话判断、`brief.diff`、`brief.external`、情境的 `phase` / `keyTask`、Claim 正文，以及给常浩的答复。做法：先按地区写 `brief.diff`，每个地区回到摘要事件表逐校看一遍，把例外写进去；**一句话判断从 `diff` 压缩出来，压缩时保留「多数 / 部分」这类限定词，或带上例外**，不能在压缩时把例外丢掉（例：diff 写了「UNSW 期末至 12 月 10 日」，判断就不能写「澳洲已转入出分与补考」）。用了「均、都、全部、已结束、基本、普遍」这类说法，要么确实没有例外，要么写出例外学校（例：「多数已进入出分与补考阶段，UNSW 期末持续到 12 月 10 日」），要么改成限定说法（「多所学校…，部分持续至下旬」）。引用了真实 Evidence 不等于归纳出的文字就对。
- **「上旬 / 中旬 / 下旬」按日期算**：1–10 日上旬、11–20 日中旬、21 日到月底下旬。写「某组学校上旬考完」前，对照摘要每个地区的「结束日分旬」，逐校看结束日；跨两个旬的写日期段（例：UC 四校 12 月 11–12 日结束，写「中旬初」或「12 月 11–12 日」，不写「上旬」）。
- `brief.common` / `diff` / `external`：共性、地区差异、外部变量。背景卡整张没填时，`common` 第一条写「本月未提供业务背景，用户需求与购买判断均基于学校时间线推断」。`external` 只写节假日、出行、学校放假对学生**可用学习时间、注意力和排课**的影响，以及考试与出分节点怎样交错；不写等优惠、家长参与决策这类消费心理推断（那属于购买研判，要有行为证据或写成明确的待验证假设）。
- 想到的机会方向记进 `research.notes`，交给第 2 轮的机会主题；研究层的 `opportunities`、`strategies` 仍必须为空（当前 Schema 的约束），机会、产品、促销写在 `design.md` 和报告里。

### 第 6 步 · 组装与自检（阶段 08 前半）

1. 按 `references/schema.md` 第 5 节写 `draft.json`：`basedOnFingerprint` 写研判时底稿的 `inputFingerprint`（digest.md 顶部），`declared.executor` 写当前执行方（Claude 或 Codex），`model` 写当前模型。
2. 按 `references/quality.md` 第 1 节逐项自检，结论写进 `research.selfCheck`；逐条对照第 3 节的四个反例。「事实与来源核验」带上 `regionCheck`：每个有情境的地区一句，写核过哪些学校、例外是哪几所、落到了哪句话里（没有例外就写「逐校核过 N 所，无例外」），脚本缺了会拦截。
3. `node scripts/assemble.mjs facts.json draft.json --out-dir <工作目录>`。
   - 脚本每次先删掉目录里旧的 `document.json`、`submit-args.json`；全部通过才写新的 `document.json`，失败只写 `assemble-errors.txt`。**默认不写 `submit-args.json`**（试写期默认不提交，目录里不留能直接提交的参数）；要提交时按 `submit.md` 加 `--submit-args` 重跑，目录里有 `submit-args.json` 就一定是最近一次通过的那份。
   - 退出码 2：按「拦截」逐条改研判稿，重跑，直到通过。「提示」逐条看，能改就改。拦截项包括：每个情境缺四类需求 Claim 之一、缺该人群的 readiness（判断不了写 unknown）、购买判断没有行为证据却超过 inferred + weak、observed 痛点没引用用户观察、业务证据的适用范围（`countries`、`relation`）没填或对不上本处、弱证据主障碍没标「暂定研究重点」、自检缺某个有情境地区的 `regionCheck`。
   - 提示「背景卡待补范围」：研判稿引用了没填范围的事实记录、业务观察。脚本已把它们写进 `research.notes`；相关判断照「范围不明」写（最高 `inferred + weak`），自检「购买障碍论证」判「待确认」，`fix` 写「待常浩在背景卡补适用范围」。
   - 退出码 1：输入读不了或不是合法 JSON（原因写在 `assemble-errors.txt`），修好文件后重跑；旧的 document.json、submit-args.json 同样已删除。
   - 通过后得到 `document.json` 和 `idempotencyKey`（由月份、输入指纹和内容哈希决定：内容不变，键就不变）；带 `--submit-args` 时另有 `submit-args.json`。
4. 组装通过即完成第 1 轮。要提交结构化版本时（默认不提交），按 `submit.md`：提交前重取底稿比 `inputFingerprint`，变了按其中「底稿变了」处理。

