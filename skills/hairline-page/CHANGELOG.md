# hairline-page 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条一致。升版本的规则见仓库 `templates/CHANGELOG.md`：改措辞升修订号，加构件或规则升次版本，改令牌、文件格式这类会让旧页面不再符合的改动升主版本。改了 `assets/reference.html` 的，在条目里写明换了哪些构件。改完重跑 [evals.md](evals.md)。

## 0.2.0 - 2026-11-07

补齐资产化材料。首次盲测 2/3 过（E1 按最严读法不过），**还没过闸 2**，所以不定 1.0.0。盲测记录和要补的缺口见 [evals.md](evals.md)。

- 新增：`metadata.version`、本文件和 evals.md（3 条：把流程做成讲解页、审一张不合规的页面、数据仪表盘）。E2 用的页面放在 `evals/flawed.html`。
- skill 正文和参考实现没有改。PR #16（补充第四至第八版沉淀的构件与规则）还没合并，不在这个版本里。

## 0.1.0 - 2026-11-04（bfee678，#14）

把「AI 落地三步法」讲解页定稿时用的风格整理成 skill：设计令牌、三种字体、版式构件、动效规则、Artifact 技术约束和截图自检；参考实现 `assets/reference.html`，截图换成了灰色占位。
