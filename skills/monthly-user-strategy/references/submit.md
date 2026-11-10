# 结构化版本的提交（可选）

从 1.2.0 SKILL.md 第 3 节第 7、8 步与「底稿变了」「结果不明」原样移来。2.0.0 起主交付是 `report.md`；**试写期（niuma-home 规格 report-v2.0 冻结后、批 D 前）默认不提交**，只有常浩明确说「提交结构化版本」时才按本文走。提交的是第 1 轮的研究层文档（`submit-args.json`），报告正文进不了当前 Schema。

### 第 7 步 · 提交（阶段 08）

先用 `node scripts/assemble.mjs facts.json draft.json --out-dir <工作目录> --submit-args` 重跑组装，写出 `submit-args.json`（2.1.0 起默认不写）。`strategy_submit`，参数就是 `submit-args.json`（MCP 方式再加 `_caller`）；结果存为 `submit-result.json`。

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
- **背景卡待补范围**（组装有这类提示时必写）：逐条写哪一栏、哪一条（原文前十几个字）、缺国家还是人群、建议填什么（按 `references/lifecycle-bizcard.md` 第 5 节的预填规则给建议值和理由）、补了且对得上后最高能到什么强度（事实记录：购买判断可到 known + strong；业务观察：最高 inferred + partial）。指向策略页的业务背景卡；说明补范围会改条目的 Evidence 版本，补完要重新取底稿、重新生成，这次提交的稿子不会自动升级。
- 工作目录路径（底稿、文档、提交结果都在那里）。

