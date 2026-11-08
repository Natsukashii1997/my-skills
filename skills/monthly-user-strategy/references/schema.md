# 月度文档与研判稿格式

摘自 niuma-home `docs/策略规则/03-Schema-v2.md` **schema 2.1**（第 2–5 节）与 `01-来源登记表.md` **sources-v1.1**。规则以原文为准。

## 1. status 与证据强度

| status | 含义 | 必须同时满足（不变量） |
|---|---|---|
| `known` | 证据足够，可以判断 | `evidenceStrength=strong`，`evidenceRefs` 非空（I-01）；不能引用 `ambiguous` 的 Evidence（I-18） |
| `inferred` | 有间接依据，有条件推断 | `evidenceStrength` 为 `partial` 或 `weak`，写 `limitations`（I-02） |
| `unknown` | 依据不足，暂不判断（`evidenceStrength` 写 `none`） | 写 `gap`；`route.status` ∈ available / unavailable / research；`route.source` 非空时必须在来源表里；`available` 时 `source` 必填（I-03） |
| `not_applicable` | 对这个情境不适用 | `limitations` 写不适用的原因（I-04） |

**单条证据的强度上限**（01 来源登记表）：

| 证据 | 上限 |
|---|---|
| 时间线 `verification=verified`（官网核实）/ `ruled`（人工裁定） | strong |
| 时间线 `source`（原表日期，未核实） | partial |
| 时间线 `guess`（标推测）/ `conflict`（冲突未决） | weak |
| 背景卡 事实记录 / 业务观察 / 管理判断 | strong / partial / weak |

多条**独立**证据互相印证可以升一级，最高 strong。同一事件的原表日期、官网核验、人工裁定是一条 Evidence，不能叠加；同一张背景卡里同一出处的多条也算一条来源。

**来源登记表 ID**（`route.source` 只能填这些）：`SRC-timeline`、`SRC-official`、`SRC-ruling`、`SRC-bizcard`（可用，可选）、`SRC-playbook`（规则资料）、`SRC-voice`、`SRC-crm`、`SRC-service`（三者不可用）。不可用来源作 route 时 `route.status=unavailable`；确实需要表外的新来源时 `route.status=research`、`source` 留空。

## 2. Scenario

| 字段 | 要求 |
|---|---|
| `id` | `SCN-<月份>-<地区>-<两位序号>`，如 `SCN-2026-12-uk-01` |
| `region` | `uk` / `us` / `hk` / `au` / `ca` / `other` |
| `countries` | 小写具体国家代码，至少一个；`other` 地区写 `sg`、`my`、`nz`、`mo`、`ie` 等，**不能写 `other`**（I-12） |
| `schools` | 代表学校（中文校名含缩写，照抄底稿）；空数组表示该国整体 |
| `academicStage` | `undergraduate` / `postgraduate` |
| `phase`、`keyTask` | 学业阶段；一句话关键任务 |
| `targetRelation` | 研究设定：`新签` / `续费` / `通用` |
| `observedRelation` | `{ value, evidenceRefs }`；`value` 不是 `unknown` 时至少一条 business 类 Evidence（I-05） |
| `evidenceRefs` | 支撑「这个情境存在」的 Evidence，至少一个 |

## 3. Claim

| 字段 | 要求 |
|---|---|
| `id` | `CLM-<月份>-<序号>`，如 `CLM-2026-12-001` |
| `scenario` | 所属 Scenario ID |
| `claimType` | `task` / `academic_need` / `pain` / `need_strength` / `readiness` / `barrier` |
| `text` | 不超过 40 字，结论先行；**不写障碍编码、打法编号**（I-15） |
| `status`、`evidenceStrength`、`evidenceRefs` | 见第 1 节 |
| `rule` | 推导用到的规则，如 `lifecycle-v0.2/Final`；主障碍的选定理由也写这里 |
| `dependsOn` | 依赖的其他 Claim |
| `limitations` / `gap` / `route` | 按 status 必填（第 1 节） |
| `painKind` | 仅 pain：`typical` / `observed`（observed 要有反馈、诊断或记录） |
| `level` | 仅 need_strength、readiness：`高` / `中` / `低`；unknown 时为 `null` |
| `barrierCode` | 仅 barrier：v2 编码（`barriers.md`） |
| `targetRelation` | 仅 barrier、readiness：这条判断针对的人群 |
| `barrierRole` | 仅 barrier：`primary` / `secondary`；同一情境、同一 `targetRelation` 下有障碍时恰好一个 primary（I-11） |

`refVersions`、`origin` 由 `assemble.mjs` 填，研判稿里不写。skill 永远不写 `origin=manual`；正式版本里常浩手写的 Claim，脚本原样带上，研判稿不要改它、也不要占用它的编号。

**页面标签由展示层推导**：`academic_need` + `known` + `strong` 且证据来自 business 或 voice → 已验证需求，其余都是潜在需求。只有时间线证据的需求不可能是已验证需求（09 #21）。

## 4. 月度文档里由 skill 决定的部分

- `brief.judgement`：`{ text, claims }`，一句话月度判断，不超过 100 字，`claims` 至少引用一条本稿的 Claim。
- `brief.common` / `diff` / `external`：每条 `{ text, status, evidenceStrength, evidenceRefs, limitations?, gap?, route? }`，同样受第 1 节约束。`inferred` 的条目没有可引用的 Evidence 时 `evidenceRefs` 写空数组，在 limitations 里说明依据（如「本月没有业务背景卡」）。`external` 写外部变量（当地消费节点、中国节点）；这些多半不在底稿里，写 `inferred + weak`，limitations 说明是公共日历常识、未经来源表核实。
- `regions[]`：六个地区单元都必须有（I-13）。`priority.value` ∈ 主战场 / 次要 / 平稳（或 `null` + reason 含「待研判」）；与默认不同写 `reason`。`activity` 照抄服务端覆盖率（服务端会重算比对，抄错即拦截）。`scenarios` 可以为空，为空时 `emptyReason` 必填（原因 + 覆盖情况）。
- `research`：内部研判记录，不在正式稿展示。`rejected` 放被否掉的判断及原因，`assumptions` 放关键假设，`notes` 放其他（含批 2 才写的机会方向）；自检记录由脚本从 `selfCheck` 转成文字放进 `notes`。

## 5. 研判稿 draft.json（交给 assemble.mjs）

```jsonc
{
  "month": "2026-12",
  "basedOnFingerprint": "<研判时底稿的 inputFingerprint>",   // 必填；与当前底稿不同时须给 --prev-facts
  "declared": { "executor": "Claude", "model": "<当前模型 ID>" },   // Codex 会话写 Codex；skillVersion 由脚本从 SKILL.md 读
  "judgement": { "text": "…", "claims": ["CLM-2026-12-001"] },
  "brief": { "common": [], "diff": [], "external": [] },
  "regions": {                       // 六个 key 都要有
    "uk": { "priority": "主战场", "reason": null, "emptyReason": null },
    "ca": { "priority": "次要", "reason": "仅 2 校有数据，样本太小，降一档", "emptyReason": "…" }
    // priority 省略 = 采用默认矩阵；与默认不同必须写 reason
  },
  "scenarios": [ /* 第 2 节的完整对象 */ ],
  "claims": [ /* 第 3 节的对象，不含 refVersions、origin */ ],
  "research": {
    "rejected": [], "assumptions": [], "notes": [],
    "selfCheck": [ { "item": "事实与来源核验", "result": "通过",
                     "regionCheck": { "uk": "逐校核过 6 所，无例外", "us": "逐校核过 12 所；NYU、UR 考到 12-23，diff 与判断已写「部分持续至下旬」" } },
                   { "item": "购买障碍论证", "result": "待确认", "at": "CLM-2026-12-031", "category": "证据不足", "fix": "已写 unknown + route，待背景卡补充" } ]
  }
}
```

## 6. 批 1 里服务端拦截的其他规则（生成时就要避开）

- I-06：Claim 引用的 Evidence 版本必须是当前版本（脚本按底稿填；研判稿用 `basedOnFingerprint` 绑定研判时的底稿，换了底稿必须带旧底稿比对，见 SKILL.md「底稿变了」）。
- `inputs`（时间线快照、背景卡指纹、引用的 Evidence 版本）在常浩确认时由服务端按当时的事实重写，skill 填的值只是占位；`timelineSnapshot` 写 null 是正常的。
- I-17：引用的每个 ID 都必须存在于本稿或当前快照；**Evidence ID 只能从底稿里抄，不能编**。
- 07 §3：没有「存量用户情况」时，续费的 barrier、readiness 必须 `unknown`，route `{ status: available, source: SRC-bizcard }`；续费情境 `observedRelation=unknown`。没有「用户观察」时，痛点只能 `typical`。
- 02 §2.3：没有 business / voice 证据的障碍，`BR-M2`、`BR-M5` 只能 `unknown`，其他最高 `inferred + weak`。
- `opportunities`、`strategies` 只能是空数组（批 2 实现）。
