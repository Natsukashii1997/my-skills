# ui-preflight 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。

## 1.0.1 - 2026-11-20

- 修复：经 `~/.claude/skills`、`~/.agents/skills` 的符号链接调用脚本时，入口判断拿链接路径和真实路径按字符串比，对不上，脚本什么都不做、退出码 0（G-38）。改成两边都解析成真实路径再比；补测试「经符号链接调用也会执行」。合并 1.0.0 后核对链接时发现，盲测用的是仓库里的真实路径，没测出来。

## 1.0.0 - 2026-11-20

首次送准入（闸 2），盲测结果见 evals.md。来由：复盘提案 P8「界面交付前自查做成 Skill」，常浩 2026-11-20 批。

- 新增：`scripts/ui-preflight.mjs`：用项目自己的 Playwright 在 1280、1440 查横向溢出、同列对齐、截断与折行、0 高容器，出 report.md / report.json、整页截图和标注截图；分「不通过」和「⚠️ 提示」两级；默认展开 `<details>`；读 `docs/design/pages.json`（setup、ready、clock、evidence、preflight.ignore），或用 `--url`；项目有 `scripts/ui-baseline.mjs` 时查完调它的 compare，并进同一张表。
- 新增：SKILL.md 自查清单（真实与极端数据、正式运行引擎、同一写法其他出现处、相邻状态）和交付说明要写的内容。
- 验证：niuma-home `72de318` 业务页查出「表头不齐」，`5c2fd44` 培养路径页 1280 宽查出「卡头折行」，当前 main 两处都不再报（证据 `~/Library/Application Support/my-skills/evidence/2026-11-20-ui-preflight/`）。
