# 飞书执行参考

进入文档读写阶段时读取。表达、模式和交付范围以主 `SKILL.md` 为准；本文件只规定原生操作路径。先读取已安装的 `lark-doc`、`lark-drive`；画板分支再读取 `lark-whiteboard`。本机这些技能位于 `/Users/nat/.agents/skills/`，路径变化时重新发现。

## 1. 身份与副本基线

所有命令固定 `--profile codex --as user`，即机械邪龙兽应用 `cli_aacf58ab61b85beb` 下的个人授权。CLI 管理凭据；检查身份时仅提取 profile、App ID、identity、available、tokenStatus 等必要字段，日志不保留凭据。权限失败按该应用处理。

为本次操作准备独立本地工作目录。下面命令中的大写占位值替换为真实值；文件参数用该目录下的 `@./...` 或 stdin。

```bash
# 保存完整响应，包括 content、reference_map、document ID 与 revision。
lark-cli --profile codex docs +fetch --as user \
  --doc 'SOURCE_URL' --detail full > ./source.full.json

# 服务端复制到“我的空间”；Wiki URL 会解析到底层资源。
lark-cli --profile codex drive +copy --as user \
  --url 'SOURCE_URL' --name '原题｜优化版' \
  --folder-token my_space > ./copy.result.json

# 检查复制成功，记录响应 data.file_token / data.url，再回读副本。
lark-cli --profile codex docs +fetch --as user \
  --doc 'COPY_URL' --detail full > ./copy.before.full.json
```

完成条件：源文全文覆盖可核实，副本 URL/ID 已确认，副本完整快照已保存。`full` 仍需检查截断或 excerpt；长文继续按目录/章节补齐。资源与引用的核验使用完整 JSON，不能只保存正文。

- `my_space` 解析需对应 Drive 元数据权限；实际 scope 缺口以错误为准。原生复制失败时先解决复制条件。
- 旧版 `/doc/` 可用 copy 的 `--extra target_type=docx`，检查返回类型后再按 Docx 操作。
- 复制后的块 ID 以副本回读为准。媒体 token 可能变化；按资源类型、内容、位置、链接目标和可读性核验保留情况。评论、历史及分享关系以实际结果为准。
- 下文所有写命令的 `COPY_URL` 必须与已记录的副本 ID 对上；执行前核对一次。源文快照是语义依据，副本修改前快照是写入基线。

## 2. 最小操作与回读

```bash
# 改写文本块或一个可安全重建的容器；片段须符合其父容器语法。
lark-cli --profile codex docs +update --as user \
  --doc 'COPY_URL' --command block_replace \
  --block-id 'CURRENT_BLOCK_ID' --content @./fragment.xml

# 移动已有完整块序列，保留资源块本体。
lark-cli --profile codex docs +update --as user \
  --doc 'COPY_URL' --command block_move_after \
  --block-id 'DESTINATION_ANCHOR' --src-block-ids 'SOURCE_A,SOURCE_B'

# 插入新增组件。
lark-cli --profile codex docs +update --as user \
  --doc 'COPY_URL' --command block_insert_after \
  --block-id 'CURRENT_ANCHOR' --content @./fragment.xml
```

- 整节移动取标题与所属正文的完整序列，目标锚点在源序列之外。`block_move_after` 的底层参考声明支持所有块类型；实际容器约束以响应和回读为准。
- 多块替换用 `--start-block-id FIRST --end-block-id LAST`，仅限同一个直接父节点下、连续且正向的闭区间。列表项替换用 `<li>`；不能跨容器拼一个替换范围。简单行内改字才用 `str_replace`。
- 先局部验证，再串行执行。结构写入后重新 fetch，刷新块 ID、顺序、章节范围和版本。可通过 `--revision-id` 传入已观察版本；版本变化先重新对齐，不能将默认的最新版本当作并发保护。
- 同一块的多处修改合并为一次 patch。资源或未知/只读块优先保留并移动外围内容；避免重建其容器。单独复制块的支持面有限，bitable、同步块、OKR 等不支持 `block_copy_insert_after`。
- 必须回放已有引用时，从当前副本响应提取完整 `reference_map` 对象到文件，给 update 加 `--reference-map @./reference-map.json`。保留资源的原有 token、src、data-ref 等字段。

每次写入检查退出码、信封 `ok`、`data.result`、warnings、tips 和实际更新数。`partial_success` 或响应未知时先回读定位实际结果，再只修复受影响部分；重试上限沿用主文件。完成条件是回读中的真实结构与预期一致，不能仅据 API 成功继续。

## 3. 原生组件语法

具体属性查 `lark-doc/references/lark-doc-xml.md`。以下是可调整的组件片段，不是每篇必用的模板：

```xml
<blockquote><p><em><span text-color="gray">来源或背景引用</span></em></p></blockquote>
<h1><span text-color="orange">章节标题</span></h1>
<p><b>关键结论</b>及对应说明。</p>
<grid>
  <column width-ratio="0.5">
    <callout emoji="💡" background-color="light-blue" border-color="blue">
      <p><b>主题 A</b></p><ul><li>并列信息</li></ul>
    </callout>
  </column>
  <column width-ratio="0.5">
    <callout emoji="✅" background-color="light-green" border-color="green">
      <p><b>主题 B</b></p><p>对应说明</p>
    </callout>
  </column>
</grid>
<table>
  <colgroup><col width="240"/><col width="580"/></colgroup>
  <thead><tr>
    <th background-color="light-gray"><p>事项</p></th>
    <th background-color="light-gray"><p>说明</p></th>
  </tr></thead>
  <tbody><tr>
    <td vertical-align="top"><p>某事项</p></td>
    <td vertical-align="top"><p>对应说明</p></td>
  </tr></tbody>
</table>
```

- 合法嵌套为 `grid → column → callout`，列宽比例总和为 1。callout 子块仅支持 p、ol、ul、checkbox 与行内标签；图、表、画板、代码块和分栏放在 callout 外。
- 原生文档表格用 `<table>`，已有 Sheet 用 `<sheet>`，两者保持业务用途。table 支持列宽、背景、垂直对齐及 rowspan/colspan；合并覆盖的单元格不重复写。
- 新写颜色采用底层 XML 参考允许的语义值；既有样式先保留。片段不另加文档 `<title>`。文本 `& < >` 转义为实体，换行用 `<br/>`。
- 本地 `lark-cli --profile codex docs +script --command parse --content @./fragment.xml --as user` 可辅助解析；它不是服务端 schema validator，不能替代实际写入与页面验收。

## 4. 画板分支

读取 `lark-doc/references/lark-doc-whiteboard.md` 及 `lark-whiteboard` 中与所选格式对应的 route、update、export 和 workflow 参考。复杂新图按底层 workflow 交给独立子代理；已有非空画板只保留内容或移动文档块。本版不执行既有画板重绘，补充图示使用独立新板。

简单新图先完成 Mermaid/SVG 文件，只表达原文已有节点与关系，再通过 docs 的 `block_insert_after` 插入以下片段之一：

```xml
<whiteboard type="mermaid" path="@./diagram.mmd"></whiteboard>
<whiteboard type="svg" path="@./diagram.svg"></whiteboard>
```

SVG 自包含，有根 `<svg>` 和 viewBox。需复杂布局时先运行本地预览与几何检查，并查看 PNG：

```bash
npx -y '@larksuite/whiteboard-cli@^0.2.13' \
  -i ./diagram.svg -o ./diagram.png -f svg
npx -y '@larksuite/whiteboard-cli@^0.2.13' \
  -i ./diagram.svg -f svg --check
```

如果选择先插入 `<whiteboard type="blank"></whiteboard>`，立即定位该新板 token，确认其不在源文画板 token 清单中再填充；不得交付空白占位板：

```bash
lark-cli --profile codex whiteboard +update --as user \
  --whiteboard-token 'BOARD_TOKEN' --input_format svg \
  --source @./diagram.svg --idempotent-token 'STABLE_KEY_AT_LEAST_10_CHARS'

lark-cli --profile codex whiteboard +export --as user \
  --whiteboard-token 'BOARD_TOKEN' --output-type preview --output ./board-preview
```

- update 默认追加；仅向本次新建且独立的画板写入，不使用整板清空参数，不修改源文或复制得到的既有非空板。同次逻辑写入的重试复用 idempotent-token，未知结果先回读，避免重复追加。
- 新增块返回字段在底层参考中有 `data.document.new_blocks` / `data.new_blocks` 两种示例。检查真实响应，并以副本 full fetch 定位新增 whiteboard 的真实 token。
- SVG 部分特性会退化为图片。可编辑节点用基础形状、连线和 `<text>`；避免 mask、clipPath、pattern 及非阴影 filter。SVG 导出是视觉快照，不保留全部连接或层级语义。
- 源码导出仅在板内有且仅有一个 Mermaid/PlantUML 图时适用。要回写 raw，导出时用 `--output ./nodes.json`；终端响应信封不能直接作为 raw 输入。

完成条件：真实画板有内容，导出预览可读，关系与原文一致，文档内对应块加载正常。底层 SVG 指南关于扩充稀疏内容的建议不适用于保真精修。

## 5. 最终回读与验证边界

保存副本修改后的完整快照供主文件保真检查使用。原生表格局部响应若为切片，用 fetch 的 `--scope range --start-block-id TABLE_ID --end-block-id TABLE_ID` 读取全表。核对资源内容、引用目标与实际位置；必要时再用 `drive +list-comments` 检查评论，comments sidecar 本身不证明锚点保留。

最后回读原稿核验未变，并打开副本检查真实页面。结构回读、本地解析或本地 PNG 都不能替代文档的真实视觉验收；页面不可访问时标记“视觉待验”。

本参考在 2026-09-07 使用 CLI 1.0.89 跑通合成文档的读取、服务端复制、局部替换、原生块移动与 SVG 画板插入，回读了结果并查看副本关键区域；新增画板已导出预览检查。显式版本的 whiteboard-cli 0.2.13 版本/help 可运行，未证明其全局安装。这些证据覆盖本次测试路径，不能代替每次执行的权限、保真和真实页面验收。
