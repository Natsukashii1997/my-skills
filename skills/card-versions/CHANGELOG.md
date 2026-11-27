# card-versions 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。

## 1.0.0 - 2026-11-28

首次送准入（闸 2），盲测结果见 evals.md。立项见 #148：skill-evolution 首次每周复盘（2026-11-16 周）的提案 N2，常浩 2026-11-28 批「做」。形态定为独立 skill，不改 three-versions（three-versions 1.0.0 是 11-27 定稿的，要改得单独确认）。

- 新增：吃透现状 → 定几版（差在信息怎么排、怎么回）→ 用项目卡片零件生成 → 检查 → 发到私聊并回读 → 回复差别表 → 选了之后只改一版 → 定稿登记 DECIDED。
- 新增：`scripts/card_preview.py`：`check` 查标题、正文组件上限（199）、按钮；`send` 加【预览 X】前缀、以机器人身份发出、逐张回读（是卡片、在这个私聊、标题对得上），同一批幂等，记 `card-preview.jsonl`。

准入审计的两条 warning 及处置（2026-11-28）：

- `RISK_SIGNAL_CREDENTIAL_ACCESS`（`card_preview.py` 调 `lark-cli --profile`）：用的是 lark-cli 自己保管的飞书应用凭据，脚本不读、不打印、不存凭据；profile 由调用方给，只用项目正式发这张卡的那个应用。声明已改为 `credentials: required`。确认。
- `RISK_SIGNAL_EXTERNAL_WRITE`（发送记录追加到证据目录，以及经 lark-cli 发消息）：只往调用方给的证据目录追加一行，只发到调用方给的私聊会话；同一批有幂等键，不重复发。确认。

送准入前按盲测第 1 轮打分改过一轮（记录见 evals.md）：第 6 节「选了一版、还要改」写明回复要说清定稿后登记哪几样、按什么流程改正式代码；补「卡片正文的字要和预览对得上」（第 1 轮 E1 有一版卡片写着「点按钮就算定了」，和按钮摆样子矛盾）。
