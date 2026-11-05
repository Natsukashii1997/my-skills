# skills 体检报告（2026-11-05）

只读体检，没有改任何现有文件。检查对象是 `main` 分支 `370089e` 时的 `skills/` 下 12 个 skill，加上 `links.tsv`、`README.md`、`scripts/link.sh`。

> 注意：`excel-aura` 和 `ai-landing-method` 另有两个云端会话在改。下面涉及这两个 skill 的条目以 `370089e` 为准，合并前请对照它们的最新版本再看一遍。

## 结论先行

- **结构层面基本健康**：12 个 skill 的 frontmatter 都齐全、`name` 都和目录名一致；`links.tsv`、`skills/` 目录、README 表格三方都是 12 个，一一对得上；所有相对链接都能找到文件；所有脚本都过了语法检查，自带的 125 个单元测试全部通过。
- **真正的问题在「谁来接活」**：有两处触发冲突值得优先处理。一是 `business-project-router` 和 `ai-landing-method` 在 Codex 里都能自动触发，而且都声称要管「从头到尾」，提问流程还互相矛盾；二是 `lumiedu-ai-collaboration` 和 `lumiedu-automation-advisor` 是同一个 skill 的两份拷贝，description 一字不差，正文已经开始各改各的。
- **第二类风险是仓库外依赖**：`business-project-router` 要靠 7 个仓库外的 skill 才能完整工作，`get-notes-retrieval` 和 `thinking-model-capture` 也依赖仓库外的文件，都写成了 `/Users/nat/...` 绝对路径。这些在云端没法核实。换电脑或者外部 skill 改名后，它们会**悄悄失效**，不会报错。

严重程度怎么分：**高**＝会让 agent 选错 skill 或流程打架；**中**＝不影响当前使用，但迟早出错或很难维护；**低**＝规范或一致性问题，顺手改就行。

---

## 高

### H1. `business-project-router` 和 `ai-landing-method` 抢「AI 落地」类项目

- **问题**：
  - 在 Codex 里，两个 skill 都可以自动触发：router 在 `agents/openai.yaml` 里写了 `allow_implicit_invocation: true`；ai-landing-method 没有 `openai.yaml`，按默认也能自动触发。router 链接在 `~/.codex/skills`，ai-landing-method 链接在 `~/.agents/skills`，这两个目录 Codex 都会读。
  - 两边都想把这类请求接下来，并且管到底：
    - router 的 description：「业务项目级思考与推进的**默认总入口**。**主动识别**业务观察、反复困惑、初步判断和高影响决策」；正文：「项目一旦进入本路由，直到用户最终审核结束……**都由本路由承接**」。
    - ai-landing-method 的 description：「用户说……「**想给某个团队做 AI 落地，不知道从哪开始**」……或正在从访谈走到方案、再落到一线执行时使用」。
  - 用户说「想给销售团队做 AI 落地，不知道从哪开始」，两边都会命中。
  - 两边的流程还直接矛盾：router 要求「用户确认前不进入第二环」（必须先确认《问题共识基线》）；ai-landing-method 要求「写完直接开始做，**不再等用户确认**」。
  - router 的分工表 `references/skill-routing.md` 里没有提到 ai-landing-method，所以 router 也不会把活交给它。
- **位置**：
  - `skills/business-project-router/SKILL.md:3`、`:22`、`:87`
  - `skills/business-project-router/agents/openai.yaml:6`
  - `skills/business-project-router/references/skill-routing.md`（没有 ai-landing-method 这一行）
  - `skills/ai-landing-method/SKILL.md:3`、`:52`
- **建议**：先由常浩定两者的关系，再改文字。推荐做法：**ai-landing-method 作为 router 的阶段能力**，也就是 router 进入第二环（方案论证）时，如果判断是「一线业务 AI 落地」，就交给三步法执行，执行完把控制权交还 router。具体要改三处：
  1. 在 `skill-routing.md` 加一行，写明什么时候交给 ai-landing-method。
  2. 在 ai-landing-method 的 description 末尾加一句「已在项目总路由中推进的项目，由总路由调用本 skill，不另起入口」。
  3. 在第 2 节「先问清楚」里注明：由 router 调用时，跳过本 skill 自己的提问，直接沿用 router 已经确认的基线。

  如果常浩更希望三步法单独使用，就反过来：在 router 的 description 里把「一线业务 AI 落地（三步法）」列为排除项。

### H2. `lumiedu-ai-collaboration` 和 `lumiedu-automation-advisor` 是两份分叉的拷贝

- **问题**：
  - 两份的 description 一字不差，都是 109 字，开头是「路觅部门或跨部门业务的飞书 AI 自动化诊断与方案设计。明确调用时……」。
  - 用 `diff -r` 对比：正文只在「选择题题头必须标单选 / 多选」这一条规则上不同，涉及 4 个文件，`automation-advisor` 多了这条，`ai-collaboration` 没有。
  - 版本号是倒挂的：较新的 `automation-advisor` 是 `v1.0.1`，较旧的 `ai-collaboration` 反而是 `v3.0.1`。`automation-advisor/README.md` 写的是「从路觅 AI 自动化诊断 v3.0.1 独立命名而来」，但之后它又单独加了规则，所以 `ai-collaboration` 已经落后了。
  - 两者都设成了只能点名调用（`allow_implicit_invocation: false`），所以**不会自动抢活**。风险在后面：一是以后的修复只改到其中一份；二是用户或 agent 点名时不知道哪个才是当前版本。
- **位置**：
  - 两个 skill 各自的 `SKILL.md:3`、`:5`、`:79`
  - `references/interview.md:15-22`
  - `references/grilling-origin.md:11`
  - `README.md:1-23`
  - 仓库根目录 `README.md` 的表格，写的是「同上的另一版」
- **建议**：由常浩定保留哪一份。
  - 如果只是改名：保留 `automation-advisor`（规则更新），在单独的 PR 里删掉 `ai-collaboration`，同时删掉 `links.tsv` 里对应的行，跑完 `link.sh` 后再手动清理断链。
  - 如果两份要并存（比如一份给公司分发、一份自用）：把 description 改出区别，在 README 里写清楚两者分别给谁用、以哪一份为准同步。

---

## 中

### M1. `hairline-page` 的触发词里直接包含 `ai-landing-method` 的触发词

- **问题**：
  - hairline-page 的 description 写的是：「用户说「用 Hairline / 细线风格」「**按 AI 落地三步法那个风格**」」。
  - ai-landing-method 的 description 写的是：「用户说「用三步法」「**AI 落地三步法**」」。
  - 用户只想要这种页面风格、说了「按 AI 落地三步法那个风格做个页面」时，可能会把三步法的整套提问流程也触发起来。
  - 另外，ai-landing-method 的第 ④ 步本来就要产出「单页 HTML 报告，视觉风格不限定」，两者确实会一起出现，但双方的文字里都没有说明怎么配合。
- **位置**：`skills/hairline-page/SKILL.md:3`、`skills/ai-landing-method/SKILL.md:3`、`:85`
- **建议**：
  - 把 hairline-page 的触发词改成不含「AI 落地三步法」字样的说法，比如「按细线 / Hairline 风格」「做成上次三步法讲解页那种网页质感」，并在末尾补一句「只管样式，不触发三步法流程」。
  - 在 ai-landing-method 第 ④ 步补一句「用户要网站质感时，样式按 hairline-page」。

### M2. `business-project-router` 硬依赖 7 个仓库外的 skill，而且路径前缀不统一

- **问题**：
  - router 的五环要靠下面这些 skill 才能完整工作：`grilling`、`interview-me`、`strategy-red-team`、`roadmap-update`、`diagram-design`、`advanced-evaluation`、`data-analytics:validate-data`。
  - 它们都不在本仓库，也没有登记在 `links.tsv`，引用时写成了 `/Users/nat/...` 绝对路径，而且前缀不一样：`grilling` 写的是 `~/.agents/skills/`，其余写的是 `~/.codex/skills/`。
  - 云端核实不了这些文件是否还在。如果某个被改名或者没装，router 的规则是「读取并使用」，不会报错，会降级成凭印象执行。
- **位置**：
  - `skills/business-project-router/SKILL.md:83`、`:180`
  - `references/skill-routing.md:7-12`
  - `references/problem-alignment.md:3`
- **建议**：
  - 在 router 的 `SKILL.md` 末尾加一节「依赖清单」，列出上面 7 个 skill 的名字、期望路径，以及缺了某个时该怎么做（明确告诉用户缺了什么、哪一环会降级）。
  - 路径改用「按 skill 名在当前 skill 目录里查找」的写法，不写死 `/Users/nat`。
  - 常浩在本机跑一次 `ls ~/.codex/skills ~/.agents/skills`，确认这 7 个都在。

### M3. `project-starter`：骨架有两份，而且给 Claude 用的那个链接没有登记

- **问题**：
  1. 骨架有两份：本仓库的 `skills/project-starter/skeleton/`，和 `agent-kit` 里的 `skeleton/`。SKILL.md 规定「先出提案、用户批准，再改 agent-kit 里的 `skeleton/`」，但没有说明本仓库这份什么时候同步，两份迟早会不一致。
  2. 根目录 README 说 project-starter 链接到「`~/.agents/skills`（`~/.claude/skills` 再链到它）」，但 `links.tsv:3` 只登记了 `~/.agents/skills`。也就是说，给 Claude 用的那个链接是手动建的。README「换电脑」一节说「跑 `link.sh` 就能恢复」，可换电脑后跑 `link.sh`，Claude 那边并不会恢复这个链接，而这个 skill 的用途本来就是「Claude 与 Codex 接力」。
- **位置**：`skills/project-starter/SKILL.md:16`、`:51`；`README.md` 表格第 1 行；`links.tsv:3`
- **建议**：
  1. 定一份为准。推荐以本仓库为准（`skills/` 是正在用的版本），把 SKILL.md 里的「改 agent-kit 里的 `skeleton/`」改成「改本仓库 `skills/project-starter/skeleton/`」，agent-kit 那边只保留指针。
  2. 在 `links.tsv` 补一行 `project-starter	~/.claude/skills`，再把 README 括号里的说明删掉。
  3. 如果「`~/.claude/skills` 再链到它」指的是整个 `~/.claude/skills` 目录都链到 `~/.agents/skills`，那么 `links.tsv` 里所有 `~/.claude/skills` 的行都是重复的，`links.tsv` 开头的注释也要跟着改。**这一点需要常浩在本机用 `ls -la ~/.claude/skills` 确认。**

### M4. `thinking-model-capture` 留着已经不用的旧脚本和测试

- **问题**：
  - SKILL.md 自己写着：「`scripts/` 中的旧事务与校验脚本依赖旧思维模型库目录及旧字段协议……**本入口不执行这些脚本**」。
  - 脚本里写死的目录还是旧库：`DEFAULT_INBOX = Path("/Users/nat/Documents/思维模型库/maintenance/inbox")`。
  - 这些脚本和 `tests/` 仍然留在 skill 包里：2 个脚本、1 个测试文件，28 个测试都能通过。这会让后来读包的 agent 以为它们还在用。
- **位置**：`skills/thinking-model-capture/SKILL.md:31`、`scripts/validate_candidate.py:21`、`scripts/safe_create_candidate.py`、`tests/test_validate_candidate.py`
- **建议**：SKILL.md 说保留是为了「兼容既有历史调用」。先在本机查一下还有没有定时任务或其他 skill 在调用它们（`grep -r validate_candidate ~/.codex ~/.agents`）。
  - 没有：在单独的 PR 里删掉 `scripts/` 和 `tests/`，SKILL.md 那一段缩成一句「旧脚本已于某日移除」。
  - 有：先迁移调用方。

### M5. `get-notes-retrieval` 每次调用前要读一份仓库外的权限合同

- **问题**：SKILL.md 规定「任何 GET 命令执行前，先读取并执行权限唯一真源：[路觅 Skills 权限合同](/Users/nat/.agents/lumiedu-permission-contract.md)」，「身份未通过合同校验时，在调用脚本前停止」。这份合同不在仓库里，也不在 `links.tsv` 里。换电脑或文件挪动后，这个 skill 会直接停止工作，这是 fail-closed 的设计，本身没错，但没有地方记录这份文件要怎么恢复。
- **位置**：`skills/get-notes-retrieval/SKILL.md:21`
- **建议**：在根目录 README「换电脑」一节补一句：「以下仓库外文件也要带过去」，列出这份合同。M2 的 7 个 skill、`thinking-model-capture` 用到的 Obsidian Vault `AGENTS.md`、AGENTS.md 里的「工程流程.md」也一起列上。

### M6. `lark-doc-refine` 写死了飞书应用的 App ID 和机器人名

- **问题**：SKILL.md 写着「所有飞书调用固定 `--profile codex`，使用机械邪龙兽应用（App ID `cli_aacf58ab61b85beb`）」。App ID 不是密钥，但它是账号标识。仓库的 AGENTS.md 规定「不写入账号、token 或凭据」，这条处在边界上。
- **位置**：`skills/lark-doc-refine/SKILL.md:35`
- **建议**：需要常浩定。如果认为 App ID 不算敏感信息，就保持原样，在 AGENTS.md 里注明「应用 ID / profile 名可以写」。如果认为算，就改成「使用 `--profile codex` 绑定的应用，不得切换」，App ID 只留在本机的 lark-cli 配置里。

---

## 低

### L1. 有 3 个链接给 Codex 用的 skill 没有 `agents/openai.yaml`

- **问题**：`ai-landing-method`、`excel-aura`、`hairline-page` 都链接到了 `~/.agents/skills`（Codex 用），但没有 `agents/openai.yaml`，所以在 Codex 里没有显示名，也没有写明调用策略，默认可以自动触发。其余 9 个都有。
- **位置**：上述 3 个 skill 的目录
- **建议**：照其他 skill 补上。其中 ai-landing-method 的 `allow_implicit_invocation` 要等 H1 的结论再定。另外两个改的时候要和那两个在改的云端会话错开。

### L2. 现有 `openai.yaml` 有字段缺失

- **问题**：`get-notes-retrieval/agents/openai.yaml` 没有 `policy` 段，调用策略取决于默认值；`thinking-model-capture/agents/openai.yaml` 没有 `default_prompt`。
- **位置**：上面两个文件
- **建议**：get-notes 显式写上 `allow_implicit_invocation`。它的 description 写的是「只在缺会议史时才用」，推荐写 `true`，靠 description 来限定。thinking-model-capture 补一句 default_prompt。

### L3. 有 2 个 skill 不是用中文写的

- **问题**：AGENTS.md 规定「所有面向用户的文字用简体中文」。`get-notes-retrieval` 的 description 是英文（正文是中文）；`skill-governance-audit` 的 description、正文和 openai.yaml 全是英文。
- **位置**：`skills/get-notes-retrieval/SKILL.md:3`、`skills/skill-governance-audit/SKILL.md`、`skills/skill-governance-audit/agents/openai.yaml`
- **建议**：至少把 description 和 display_name 改成中文。英文触发词（比如「GET笔记」「Skill」）在中文句子里保留。

### L4. `get-notes-retrieval` 前后矛盾：`certifi` 到底是不是必需的

- **问题**：frontmatter 的 `metadata.governance.dependencies` 把 `certifi` 列成依赖；正文第 19 行却说「`certifi` 可选，未安装时脚本使用系统 TLS 信任库」。
- **位置**：`skills/get-notes-retrieval/SKILL.md:12`、`:19`
- **建议**：在 metadata 里把它标成可选，比如 `certifi (可选)`，写法和 lark-doc-refine 的 `lark-whiteboard (画板分支)` 一致。

### L5. `codex-usage-retrospective` 里混进了一个繁体字

- **问题**：写成了「确**認**可读范围」，其中「認」是繁体（U+8A8D），应该是「认」。
- **位置**：`skills/codex-usage-retrospective/SKILL.md:22`
- **建议**：改成「确认」。

### L6. `excel-aura` 和 `lark-doc-refine` 在「美化表格」上轻微重叠

- **问题**：excel-aura 的 description 会被「把表格做好看 / 美化表格」触发，范围是「本地 Excel / xlsx，或飞书电子表格」；lark-doc-refine 的「只美化」模式也会处理飞书文档**里面的原生表格**。用户说「把这篇飞书文档里的表格美化一下」时，可能误触发 excel-aura。
- **位置**：`skills/excel-aura/SKILL.md:3`、`skills/lark-doc-refine/SKILL.md:3`、`:67`
- **建议**：在 excel-aura 的 description 末尾补一句「飞书文档（Docx）里的原生表格不适用，按 lark-doc-refine」。这次改 excel-aura 的云端会话可以顺手带上。

### L7. `link.sh` 核对 `name` 时不只看 frontmatter

- **问题**：`sed -n 's/^name:[[:space:]]*//p' | head -1` 取的是整个 SKILL.md 里第一个以 `name:` 开头的行，不限于 frontmatter。现在 12 个 skill 都没受影响；但如果以后某个 SKILL.md 的 frontmatter 里 `name` 写在 `description` 之后，而 description 是多行块、里面又有一行以 `name:` 开头，就会核对错。
- **位置**：`scripts/link.sh:26`
- **建议**：改成只在第一对 `---` 之间找，比如 `awk '/^---/{n++;next} n==1 && /^name:/{sub(/^name:[ \t]*/,"");print;exit}'`。改动不大，不急。

---

## 已通过的检查（没有发现问题）

| 检查项 | 结果 |
|---|---|
| frontmatter 是否有 `name`、`description`（用 PyYAML 解析） | 12/12 齐全；description 最长 456 字，都没超过 1024 |
| `name` 和目录名是否一致 | 12/12 一致 |
| `links.tsv` 和 `skills/` 目录是否对得上 | 12 个名字一一对应：没有登记了却没目录的，也没有有目录却没登记的；README 表格同样是 12 行 |
| Markdown 相对链接是否存在（含 `#锚点`） | 全部存在。project-starter `skeleton/AGENTS.md` 里的 `{{需求文件}}` 是模板占位，属于预期 |
| 正文里用反引号写的路径（`references/…`、`scripts/…`） | 疑似缺失的路径逐条看过上下文，都是指外部 skill（如 `lark-doc/references/…`）、旧包里的历史文件名，或骨架复制到项目后的相对路径，不算断链 |
| 文档里写的命令和参数是否真实存在 | `aura.py` 的 6 个子命令和文档里的参数都在；`get_notes.py` 的 doctor / search / detail / changes 都在；`audit_skills.py` 的 `pre-install --installed-root`、`post-install --root` 都在 |
| 版本号是否前后一致 | ai-landing-method 主文件和 3 份 reference 都是 v8.1；lumiedu 两份各自的 README 和 frontmatter 一致（两者之间倒挂见 H2）；codex-usage-retrospective v1.0.0 |
| Python 语法（`python3 -m py_compile`，pyc 写到临时目录，没有写进仓库） | 13/13 通过 |
| Node 语法（`node --check`，v22） | 3/3 通过 |
| Shell 语法（`sh -n` / `bash -n scripts/link.sh`） | 通过；skills 里没有 `.sh` 文件 |
| 自带单元测试（`python3 -m unittest`） | skill-governance-audit 89 个（1 个跳过）、get-notes-retrieval 8 个、thinking-model-capture 28 个，全部通过 |
| project-starter 骨架测试（在临时副本里跑 `node --test`） | 4 个测试 3 个通过、1 个失败。失败原因是 `CURRENT.md` 里的 `{{日期}}` 等占位还没填；SKILL.md 第 7 步是填完占位后才跑测试，所以属于预期。`check-rules.mjs` 通过 |
| 用自带的 `skill-governance-audit post-install --root skills` 扫本仓库 | 0 个错误、3 个警告。3 个都是 `PROTECTED_OWNER_MISSING`，原因是第三方 skill（`frontend-design` 等）不在本仓库的扫描范围里，不是本仓库的问题。没有报重名，也没有报「什么都接」式的触发语 |

## 云端核实不了的（需要常浩在本机确认）

- M2 里的 7 个外部 skill 是否都在 `~/.codex/skills`、`~/.agents/skills` 下。
- `~/.claude/skills` 到底是一个整体链接到 `~/.agents/skills` 的目录，还是一个普通目录（影响 M3 的第 3 点）。
- `/Users/nat/.agents/lumiedu-permission-contract.md`、`/Users/nat/Documents/Obsidian Vault/AGENTS.md`、`agent-kit/工程流程.md` 是否存在、是否是最新的。
- thinking-model-capture 的旧脚本还有没有被调用（M4）。

## 汇总表

| 编号 | 严重度 | 涉及 skill | 问题一句话 | 建议动作 | 要常浩定？ |
|---|---|---|---|---|---|
| H1 | 高 | business-project-router、ai-landing-method | Codex 里都会自动触发，都想管到底，确认流程互相矛盾 | 定主从关系，在 skill-routing.md 登记交接 | 是 |
| H2 | 高 | lumiedu-ai-collaboration、lumiedu-automation-advisor | 两份分叉拷贝，description 一样、版本号倒挂 | 保留一份，另一份删除或改出区别 | 是 |
| M1 | 中 | hairline-page、ai-landing-method | 风格 skill 的触发词里包含「AI 落地三步法」 | 改触发词，补上两者怎么配合 | 否 |
| M2 | 中 | business-project-router | 依赖 7 个仓库外 skill，绝对路径写法不统一，缺了不会报错 | 加依赖清单和缺失时的处理 | 否（需本机核实） |
| M3 | 中 | project-starter | 骨架有两份；给 Claude 的链接没进 `links.tsv` | 定一份为准，补登记 | 是（需本机核实） |
| M4 | 中 | thinking-model-capture | 已停用的旧脚本和测试还留在包里 | 确认没人调用后移除 | 否（需本机核实） |
| M5 | 中 | get-notes-retrieval（及其他） | 仓库外必需文件没有清单，换电脑容易丢 | README 补一份「仓库外文件」清单 | 否 |
| M6 | 中 | lark-doc-refine | 写死了 App ID 和机器人名，处在「不写账号」规则的边界 | 定规则：保留或移出 | 是 |
| L1 | 低 | ai-landing-method、excel-aura、hairline-page | 链接给 Codex，却没有 `openai.yaml` | 补上 | 否 |
| L2 | 低 | get-notes-retrieval、thinking-model-capture | `openai.yaml` 缺 `policy` 或 `default_prompt` | 补字段 | 否 |
| L3 | 低 | get-notes-retrieval、skill-governance-audit | description 或正文是英文 | 改成中文 | 否 |
| L4 | 低 | get-notes-retrieval | `certifi` 一处写必需、一处写可选 | metadata 标成可选 | 否 |
| L5 | 低 | codex-usage-retrospective | 「確認」里混了繁体字 | 改成「确认」 | 否 |
| L6 | 低 | excel-aura、lark-doc-refine | 「美化表格」对飞书文档内表格有轻微重叠 | excel-aura 写明排除范围 | 否 |
| L7 | 低 | （仓库脚本）link.sh | 核对 `name` 时不限于 frontmatter | 改成只在 frontmatter 里找 | 否 |

合计：高 2、中 6、低 7。frontmatter、链接登记、相对路径、脚本语法四类检查全部通过。
