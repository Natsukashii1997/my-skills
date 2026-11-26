# three-versions 修订记录

版本号写在 SKILL.md frontmatter 的 `metadata.version`，和这里最上面一条保持一致。升版本的规则见 `templates/CHANGELOG.md`。

## 1.0.0 - 2026-11-27

首次通过准入（闸 2），盲测结果见 evals.md。

- 新增：七步流程（吃透现状 → 定三条思路 → 定风格 → 套外壳画三版 → 自查 → 发布一个链接 → 选定登记）。
- 新增：外壳模板 `assets/shell.html`：三版一键切换（按钮、键盘 1/2/3、`#a` 直达）、1440×900 画板等比缩放和「按 100% 查看」、只看画板模式 `#bare-x`、亮暗两套外壳令牌。
- 新增：自查脚本 `scripts/check.mjs`：查占位和三块画板，借 ui-preflight 在 1280 / 1440 查三版产品界面，借 ui-styles 的 shot.mjs 在 1440 / 390 查外壳。
