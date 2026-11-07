# 「Excel-Aura」skill：贴进你的 AI 工具就能自装

适合谁：经常要做给人看的表格（周报、台账、测算、价目表……），希望 AI 做出来的表层次清楚、看着舒服，而不是满屏杂色的人。它带 10 套标准配色和一套版式规则，新建、美化已有表、审查别人的表都能用；本地 Excel 和飞书表格都支持。

## 怎么装

把压缩包 `excel-aura-<版本>.zip` 发给你的 AI 工具，再把下面这段原样贴进去：

```text
请帮我安装附件里的 skill「excel-aura」（表格配色与版式标准）。
1. 先把压缩包解压到一个临时目录，完整读一遍 SKILL.md 和 scripts/aura.py，告诉我它会做什么、会不会联网、会不会改我的文件。
2. 检查本机有没有 python3；做本地 xlsx 还要 openpyxl（没有就 pip install openpyxl），出预览图要有 Google Chrome。
3. 我确认后再安装：
   - 如果你是 Claude Code：放到 ~/.claude/skills/excel-aura/
   - 如果你是 Codex：放到 ~/.agents/skills/excel-aura/
   SKILL.md 里命令写的是 ~/.claude/skills/excel-aura/scripts，装在别处就把路径换成实际位置。
4. 装好后跑一次 python3 <安装位置>/scripts/aura.py list，能列出 10 套配色就算装好了。
```

网页版 AI 跑不了脚本，这个 skill 只能在 Claude Code、Codex 这类能执行命令的工具里用。

## 装好以后怎么用

- 新建表：「把这份数据做成一张给老板看的 xlsx，做得好看一点」，附上数据。
- 美化已有表：「这张表帮我美化一下，配色舒服点」，附上文件。它会先给你看预览，你确认了才写进去，原文件不会被直接覆盖。
- 审查：「看看这张表美化得怎么样」。

## 说明

- 版本见 SKILL.md 开头的 `metadata.version`，改了什么见 CHANGELOG.md。
- 用起来哪里不顺，直接告诉常浩：原话、原表、它做成了什么样。
