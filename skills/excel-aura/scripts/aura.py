#!/usr/bin/env python3
"""Excel-Aura：按标准配色套组 + 版式规则，给表格稳定上样式。

用法：
  aura.py list                                  列出 10 套配色
  aura.py tokens S02 [--colors 3]               打印某套的派生色（标题带 / 文字色 / 边框 / 斑马纹…）
  aura.py feishu layout.json [--out-dir DIR] [--skip-merges]
                                                生成飞书 +styles-put 规格（按 70 项自动分片；重刷时跳过合并）
  aura.py xlsx layout.json in.xlsx out.xlsx     给本地 xlsx 上同一套样式
  aura.py preview layout.json [--sheet 名] [--cells cells.json] [--info info.json] [--out x.html] [--png x.png]
                                                写入前预览：原表样式叠上新样式渲染成 HTML（可选 PNG），并列出风险
  aura.py audit cells.json [--info info.json] [--before 原表cells.json]
                                                检查一张表（含别人美化过的）的残留与不合规之处；给 --before 时核对值和公式

cells.json 是 `+cells-get --include value,formula,style --output-path` 的产物，info.json 是 `+sheet-info` 的输出。
layout.json 的写法见 references/layout.md。
"""
import argparse
import colorsys
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAL = json.loads((ROOT / "palettes.json").read_text(encoding="utf-8"))
WHITE = "#FFFFFF"

# ---------- 颜色 ----------

def _rgb(h):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _hex(c):
    return "#" + "".join(f"{max(0, min(255, round(v))):02X}" for v in c)


def _lum(h):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = map(ch, _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted([_lum(a), _lum(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a, b, t):
    A, B = _rgb(a), _rgb(b)
    return _hex([A[i] * (1 - t) + B[i] * t for i in range(3)])


def darken_to(color, bg, target):
    """保持色相与饱和度，只降明度，直到与 bg 的对比度达到 target。"""
    r, g, b = [v / 255 for v in _rgb(color)]
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    while contrast(_hex([v * 255 for v in colorsys.hls_to_rgb(h, l, s)]), bg) < target and l > 0.04:
        l -= 0.01
    return _hex([v * 255 for v in colorsys.hls_to_rgb(h, l, s)])


def _sat(h):
    r, g, b = [v / 255 for v in _rgb(h)]
    return colorsys.rgb_to_hsv(r, g, b)[1]


def ink_on(L, bg, target):
    """浅底上的文字色：先试第 4 级，不够再用第 5 级，还不够就把第 5 级压深。"""
    for c in (L[3], L[4]):
        if contrast(c, bg) >= target:
            return c
    return darken_to(L[4], bg, target)


def hue_tokens(name):
    L = PAL["ramps"][name]["steps"]
    return {
        "name": name,
        "steps": L,
        "tint": L[0],                         # 强调行、合计行底
        "soft": L[1],                         # 表头 / 区块头底
        "mid": L[2],                          # 点缀、数据条
        "accent": L[3],
        "deep": L[4],
        "band": L[4] if contrast(L[4], WHITE) >= 4.8 else darken_to(L[4], WHITE, 4.8),  # 深色带，配白字
        "ink": ink_on(L, L[1], 5.0),          # 浅底上的文字色
        "line": mix(L[1], WHITE, 0.45),       # 边框
        "zebra": mix(L[0], WHITE, 0.35),      # 斑马纹
        "chip": mix(L[0], L[1], 0.5),         # 分类标记底（比斑马纹深、比表头浅）
        "vivid": _sat(L[1]) > 0.3,            # 第 2 级就很艳的色系，大块填充改用 chip
    }


def tone_tokens(key):
    t = PAL["tones"][key]
    if t["ramp"] is None:
        return {"bg": "#F2F3F5", "ink": PAL["neutral"]["text_2"], "fill": t["fill"]}
    L = PAL["ramps"][t["ramp"]]["steps"]
    return {"bg": L[0], "ink": ink_on(L, L[0], 5.5), "fill": t["fill"]}


def suite_tokens(sid, n=5):
    s = PAL["suites"][sid]
    n = max(1, min(5, n))
    return {"id": sid, "name": s["name"], "colors": n,
            "hues": [hue_tokens(h) for h in s["hues"][:n]],
            "neutral": PAL["neutral"],
            "tones": {k: tone_tokens(k) for k in PAL["tones"]}}

# ---------- 版式常量（单位 px） ----------

ROW = {"top": 12, "title": 52, "subtitle": 24, "gap": 12, "section": 32,
       "header": 40, "body": 34, "compact": 30, "total": 36, "note": 24}
# 页级疏密：长清单用 compact，卡片 / 少行测算用 airy；layout 里 "rows" 还能逐项覆盖
DENSITY = {"compact": {"header": 34, "body": 28, "compact": 26, "total": 32},
           "normal": {},
           "airy": {"header": 44, "body": 38, "compact": 34, "total": 40}}
FONT = {"title": 15, "section": 11, "header": 10, "body": 10, "note": 9}
SIDES = ("top", "bottom", "left", "right")
# 清旧样式：已有表先把整片区域洗成白底常规字，免得空格子里留着旧底色、斜体、旧边框（数字格式不动）
RESET = dict(background_color="#FFFFFF", font_weight="normal", font_style="normal", font_line="none",
             horizontal_alignment="left", word_wrap="overflow")

# 列类型 → 对齐、宽度上下限、数字格式
TYPES = {
    "index":    {"align": "center", "w": (48, 64)},
    "code":     {"align": "center", "w": (80, 140)},
    "date":     {"align": "center", "w": (100, 120)},
    "tag":      {"align": "center", "w": (80, 110)},
    "category": {"align": "center", "w": (88, 140)},
    "name":     {"align": "left",   "w": (96, 180)},
    "label":    {"align": "left",   "w": (140, 300)},
    "text":     {"align": "left",   "w": (120, 320), "wrap": True},
    "longtext": {"align": "left",   "w": (240, 360), "wrap": True},
    "amount":   {"align": "right",  "w": (104, 160), "fmt": "#,##0"},
    "money":    {"align": "right",  "w": (110, 160), "fmt": "¥#,##0"},
    "number":   {"align": "right",  "w": (80, 130),  "fmt": "#,##0"},
    "decimal":  {"align": "right",  "w": (88, 130),  "fmt": "#,##0.00"},
    "percent":  {"align": "right",  "w": (80, 110),  "fmt": "0.0%"},
    "kpi":      {"align": "center", "w": (110, 180)},
}
GUTTER_W, GAP_W = 20, 24


def text_px(s):
    return sum(15 if ord(c) > 0x2E80 else 8 for c in str(s)) + 28


def col_width(spec):
    if "width" in spec:
        return spec["width"]
    lo, hi = TYPES[spec["type"]]["w"]
    if "max" in spec:
        return max(lo, min(hi, text_px(spec["max"])))
    return lo

# ---------- A1 ----------

def col2n(c):
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def n2col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def parse(rng):
    m = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", rng)
    c1, r1 = col2n(m[1]), int(m[2])
    c2, r2 = (col2n(m[3]), int(m[4])) if m[3] else (c1, r1)
    return c1, r1, c2, r2


def cells(rng):
    c1, r1, c2, r2 = parse(rng)
    for r in range(r1, r2 + 1):
        for c in range(c1, c2 + 1):
            yield r, c

# ---------- 构建：每格最终样式 ----------

class Sheet:
    def __init__(self, tok, font):
        self.tok, self.font = tok, font
        self.style = {}      # (r,c) -> dict
        self.merges, self.unmerges, self.rows, self.cols = [], [], {}, {}

    def put(self, rng, *bases, _border=None, **st):
        """给区域盖样式：bases（如基础字体）先铺，关键字参数覆盖其上。"""
        for rc in cells(rng):
            d = self.style.setdefault(rc, {})
            for b in bases:
                d.update(b)
            d.update(st)
            if _border:
                d.setdefault("border", {}).update(_border)

    def box(self, rng, color):
        side = {"style": "solid", "weight": "thin", "color": color}
        self.put(rng, _border={k: dict(side) for k in SIDES})

    def row(self, r, size, force=False):
        # 同一物理行有并排区块时取最大值，row_sizes 显式值用 force 覆盖
        self.rows[r] = size if force else max(size, self.rows.get(r, 0))

    def merge(self, rng):
        if ":" in rng:
            self.merges.append(rng)


def build_sheet(spec, tok, font):
    P = tok["hues"][0]
    N = tok["neutral"]
    sh = Sheet(tok, font)
    hue = lambda i: tok["hues"][(max(i, 1) - 1) % len(tok["hues"])]  # 超过色数循环取色
    # 本页的行高、字号：默认值 ← 疏密档 ← layout 里逐项覆盖
    ROW = {**globals()["ROW"], **DENSITY[spec.get("density", "normal")], **spec.get("rows", {})}
    FONT = {**globals()["FONT"], **spec.get("fonts", {})}
    base = dict(font_family=font, font_size=FONT["body"], font_color=N["text"], vertical_alignment="middle")

    if spec.get("reset"):                     # 必须最先铺，后面的样式逐项盖在上面
        sh.put(spec["reset"], base, **RESET, _border={k: {"style": "none"} for k in SIDES})
    sh.unmerges = list(spec.get("unmerge", []))

    if spec.get("gutter", True):
        sh.cols[1] = GUTTER_W
        sh.row(1, ROW["top"])
    for c in spec.get("gap_cols", []):
        sh.cols[col2n(c)] = GAP_W
    for r in spec.get("gap_rows", []):
        sh.row(int(r), ROW["gap"])
    for c, cs in spec.get("columns", {}).items():
        sh.cols[col2n(c)] = col_width(cs)

    align = spec.get("align", "center")
    if "title" in spec:
        t = spec["title"]
        sh.merge(t["range"])
        sh.put(t["range"], base, background_color=P["band"], font_color=WHITE,
               font_size=FONT["title"], font_weight="bold", horizontal_alignment=t.get("align", align))
        sh.row(parse(t["range"])[1], ROW["title"])
        if "subtitle" in t:
            sh.merge(t["subtitle"])
            sh.put(t["subtitle"], base, font_color=N["text_2"], font_size=FONT["note"],
                   horizontal_alignment=t.get("align", align))
            sh.row(parse(t["subtitle"])[1], ROW["subtitle"])

    for b in spec.get("blocks", []):
        H = hue(b.get("hue", 1))
        if "section" in b:
            sh.merge(b["section"])
            sh.put(b["section"], base, background_color=P["band"], font_color=WHITE,
                   font_size=FONT["section"], font_weight="bold",
                   horizontal_alignment=b.get("section_align", align))
            sh.row(parse(b["section"])[1], ROW["section"])
        if "header" in b:
            sh.put(b["header"], base, background_color=H["soft"], font_color=H["ink"],
                   font_size=FONT["header"], font_weight="bold", horizontal_alignment="center",
                   word_wrap="auto-wrap")
            sh.box(b["header"], P["line"])
            hc1, hr1, hc2, hr2 = parse(b["header"])
            for r in range(hr1, hr2 + 1):
                sh.row(r, ROW["header"])
            if hr2 > hr1:                           # 多行表头：下层比上层浅一档
                sh.put(f"{n2col(hc1)}{hr1 + 1}:{n2col(hc2)}{hr2}", background_color=H["chip"])
            for g in b.get("header_groups", []):   # 分组表头：依次取 ②③④⑤
                G = hue(g["hue"])
                gc1, gr1, gc2, gr2 = parse(g["range"])
                sh.put(g["range"], background_color=G["chip"], font_color=G["ink"])
                sh.put(f"{n2col(gc1)}{gr1}:{n2col(gc2)}{gr1}", background_color=G["soft"])
        body_rows = []
        if "body" in b:
            c1, r1, c2, r2 = parse(b["body"])
            sh.put(b["body"], base, background_color=WHITE)
            sh.box(b["body"], P["line"])
            zebra = b.get("zebra", r2 - r1 + 1 > 10)
            for i, r in enumerate(range(r1, r2 + 1)):
                sh.row(r, ROW["compact"] if b.get("compact") else ROW["body"])
                if zebra and i % 2 == 1:
                    sh.put(f"{n2col(c1)}{r}:{n2col(c2)}{r}", background_color=H["zebra"])
            body_rows = [r1, r2]
        if "total" in b:
            tc1, tr1, tc2, tr2 = parse(b["total"])
            sh.put(b["total"], base, background_color=H["tint"], font_color=H["ink"], font_weight="bold")
            sh.box(b["total"], P["line"])
            sh.put(f"{n2col(tc1)}{tr1}:{n2col(tc2)}{tr1}",
                   _border={"top": {"style": "solid", "weight": "medium", "color": H["band"]}})
            for r in range(tr1, tr2 + 1):
                sh.row(r, ROW["total"])
            body_rows = [body_rows[0] if body_rows else tr1, tr2]
        # 按列类型定对齐、数字格式、换行（表头恒居中）
        if body_rows:
            bc1, _, bc2, _ = parse(b.get("body") or b["total"])
            for c in range(bc1, bc2 + 1):
                cs = b.get("columns", {}).get(n2col(c)) or spec.get("columns", {}).get(n2col(c))
                if not cs:
                    continue
                ty = TYPES[cs["type"]]
                st = {"horizontal_alignment": cs.get("align", ty["align"])}
                if cs.get("fmt", ty.get("fmt")):
                    st["number_format"] = cs.get("fmt", ty.get("fmt"))
                if ty.get("wrap"):
                    st["word_wrap"] = "auto-wrap"
                sh.put(f"{n2col(c)}{body_rows[0]}:{n2col(c)}{body_rows[1]}", **st)

    # 角色：输入 / 计算 / 重点 / 目标 / 弱化
    for item in spec.get("roles", []):
        role = item["role"]
        fill = lambda H: H["chip"] if H["vivid"] else H["soft"]
        if role == "input":                   # 输入 / 假设：第 2 色，加粗
            H = hue(2) if tok["colors"] >= 2 else P
            st = dict(background_color=fill(H) if tok["colors"] >= 2 else P["tint"], font_color=H["ink"], font_weight="bold")
        elif role == "calc":                  # 公式结果：第 3 色
            H = hue(3) if tok["colors"] >= 3 else P
            st = dict(background_color=fill(H) if tok["colors"] >= 3 else P["zebra"], font_color=H["ink"])
        elif role == "key":
            st = dict(background_color=P["band"], font_color=WHITE, font_weight="bold")
        elif role == "target":
            st = dict(font_color=tok["tones"]["bad"]["ink"], font_weight="bold")
        elif role == "muted":
            st = dict(font_color=N["text_3"])
        elif role.startswith("hue"):          # hue2 … hue5：用第 N 色的浅底标出一块
            H = hue(int(role[3:]))
            st = dict(background_color=H["chip"], font_color=H["ink"])
        else:
            raise SystemExit(f"未知角色：{role}")
        sh.put(item["range"], **st)

    for rng in spec.get("merges", []):
        sh.merge(rng)

    for item in spec.get("paint", []):        # 逃生口：个别格子指定颜色 / 格式
        st = {k2: item[k1] for k1, k2 in (("bg", "background_color"), ("color", "font_color"),
              ("fmt", "number_format"), ("align", "horizontal_alignment")) if k1 in item}
        if item.get("bold"):
            st["font_weight"] = "bold"
        sh.put(item["range"], **st)

    for item in spec.get("tags", []):         # 状态只上文字色，只有「风险」类带浅底，免得一列彩块
        t = tok["tones"][item["tone"]]
        st = dict(font_color=t["ink"], horizontal_alignment="center")
        if t["fill"]:
            st["background_color"] = t["bg"]
        sh.put(item["range"], **st)

    for rng in spec.get("notes", []):
        sh.merge(rng)
        sh.put(rng, base, font_color=N["text_3"], font_size=FONT["note"], horizontal_alignment="left",
               word_wrap="auto-wrap")
        sh.row(parse(rng)[1], ROW["note"])

    for r, size in spec.get("row_sizes", {}).items():
        sh.row(int(r), size, force=True)
    sh.freeze = spec.get("freeze")
    return sh

# ---------- 输出：飞书 ----------

def _rects(style):
    """把每格样式合成尽量大的矩形：先按行合并相同样式，再把列跨度相同的相邻行并起来。"""
    key = lambda d: json.dumps(d, sort_keys=True, ensure_ascii=False)
    segs = {}
    for r in sorted({r for r, _ in style}):
        cs = sorted(c for rr, c in style if rr == r)
        i = 0
        while i < len(cs):
            j = i
            k = key(style[(r, cs[i])])
            while j + 1 < len(cs) and cs[j + 1] == cs[j] + 1 and key(style[(r, cs[j + 1])]) == k:
                j += 1
            segs.setdefault((cs[i], cs[j], k), []).append(r)
            i = j + 1
    out = []
    for (c1, c2, k), rows in segs.items():
        start = prev = rows[0]
        for r in rows[1:]:
            if r != prev + 1:
                out.append((start, c1, prev, c2, json.loads(k)))
                start = r
            prev = r
        out.append((start, c1, prev, c2, json.loads(k)))
    return sorted(out, key=lambda x: x[:4])


def _runs(sizes):
    """{序号: 尺寸} → [(起, 止, 尺寸)]：连续且尺寸相同的行 / 列并成一项，省 +styles-put 的操作额度。"""
    out = []
    for i, s in sorted(sizes.items()):
        if out and out[-1][1] == i - 1 and out[-1][2] == s:
            out[-1][1] = i
        else:
            out.append([i, i, s])
    return [tuple(x) for x in out]


def to_feishu(name, sh, chunk=70, merges=True):
    items = []
    for r1, c1, r2, c2, st in _rects(sh.style):
        rng = f"{n2col(c1)}{r1}" + (f":{n2col(c2)}{r2}" if (r1, c1) != (r2, c2) else "")
        d = {"range": rng, **{k: v for k, v in st.items() if k != "border"}}
        if "border" in st:
            d["border_styles"] = st["border"]
        items.append(d)
    rows = [{"range": f"{a}:{b}", "size": s} for a, b, s in _runs(sh.rows)]
    cols = [{"range": f"{n2col(a)}:{n2col(b)}", "size": s} for a, b, s in _runs(sh.cols)]
    specs = []
    first = {"name": name}
    if not merges:                             # 重刷样式时跳过：飞书的合并不能重复执行
        sh.merges = []
    if sh.merges:
        first["cell_merges"] = [{"range": m} for m in sh.merges]
    head = max(0, chunk - len(sh.merges))      # 合并也占单次 100 项的子操作额度
    groups = [items[:head]] + [items[i:i + chunk] for i in range(head, len(items), chunk)]
    for i, g in enumerate(groups):
        part = dict(first) if i == 0 else {"name": name}
        if g:
            part["cell_styles"] = g
        specs.append(part)
    last = specs[-1]
    last["row_sizes"], last["col_sizes"] = rows, cols
    if sh.freeze:
        last["freeze"] = sh.freeze
    return specs

# ---------- 输出：xlsx ----------

def to_xlsx(ws, sh):
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    for m in sh.unmerges:
        if m in {str(x) for x in ws.merged_cells.ranges}:
            ws.unmerge_cells(m)
    for m in sh.merges:
        ws.merge_cells(m)
    for (r, c), st in sh.style.items():
        cell = ws.cell(row=r, column=c)
        cell.font = Font(name=st.get("font_family"), size=st.get("font_size"),
                         bold=st.get("font_weight") == "bold",
                         color=(st.get("font_color") or "#000000").lstrip("#"))
        if st.get("background_color"):
            cell.fill = PatternFill("solid", fgColor=st["background_color"].lstrip("#"))
        cell.alignment = Alignment(horizontal=st.get("horizontal_alignment"),
                                   vertical={"middle": "center"}.get(st.get("vertical_alignment"), st.get("vertical_alignment")),
                                   wrap_text=st.get("word_wrap") == "auto-wrap")
        if st.get("number_format"):
            cell.number_format = st["number_format"]
        if st.get("border"):
            sd = lambda k: (Side(style=st["border"][k]["weight"], color=st["border"][k]["color"].lstrip("#"))
                            if st["border"].get(k, {}).get("style", "none") != "none" else Side())
            cell.border = Border(top=sd("top"), bottom=sd("bottom"), left=sd("left"), right=sd("right"))
    for r, px in sh.rows.items():
        ws.row_dimensions[r].height = round(px * 0.75, 1)       # px → 磅
    for c, px in sh.cols.items():
        ws.column_dimensions[get_column_letter(c)].width = round(px / 7.0, 1)  # px → 字符宽
    if sh.freeze:
        fr, fc = sh.freeze.get("rows", 0), sh.freeze.get("cols", 0)
        ws.freeze_panes = ws.cell(row=fr + 1, column=fc + 1)
    ws.sheet_view.showGridLines = False

# ---------- 读回读结果：+cells-get / +sheet-info ----------

def _hex6(c):
    """飞书回读的颜色有 #abc、#aabbcc、rgb(r, g, b) 几种写法，统一成 #RRGGBB。"""
    if not c:
        return None
    m = re.fullmatch(r"rgba?\((\d+),\s*(\d+),\s*(\d+).*\)", c.strip())
    if m:
        return _hex([int(v) for v in m.groups()])
    c = c.strip().upper()
    return "#" + "".join(ch * 2 for ch in c[1:]) if re.fullmatch(r"#[0-9A-F]{3}", c) else c


def load_cells(path, sheet=None):
    """{(行, 列): {value, formula, style}}。认 +cells-get 的输出（可带外层 data），也认 demo.py 的 values.json。"""
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    d = d.get("data", d)
    grid = {}
    if "ranges" in d:
        if d.get("has_more"):
            print(f"注意：{path} 没读全（has_more），请用 --output-path 重新读", file=sys.stderr)
        for rg in d["ranges"]:
            for i, row in enumerate(rg["cells"]):       # 行列号以 row_indices / col_indices 为准，不按下标数
                for j, cell in enumerate(row):
                    grid[(int(rg["row_indices"][i]), col2n(rg["col_indices"][j]))] = {
                        "value": cell.get("value"), "formula": cell.get("formula"),
                        "style": cell.get("cell_styles") or {}}
        return grid
    for item in d.get(sheet) or next(iter(d.values())):
        c1, r1, _, _ = parse(item["range"])
        for i, row in enumerate(item["cells"]):
            for j, cell in enumerate(row):
                grid[(r1 + i, c1 + j)] = {"value": cell.get("value"), "formula": cell.get("formula"), "style": {}}
    return grid


def load_info(path):
    if not path:
        return {}
    d = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    d = d.get("data", d)
    span = lambda s: range(int(str(s).split(":")[0]), int(str(s).split(":")[-1]) + 1)
    info = {"hidden_cols": {col2n(c) for c in d.get("hidden_columns", [])},
            "hidden_rows": {r for s in d.get("hidden_rows", []) for r in span(s)},
            "merges": [m["range"] for m in d.get("merged_cells", [])],
            "rows": {}, "cols": {}, "auto_rows": set()}
    for x in d.get("row_heights", []):
        for r in span(x["rows"]):
            info["rows"][r] = x["height"]
            if x.get("type") == "auto":
                info["auto_rows"].add(r)
    for x in d.get("column_widths", []):
        a, b = x["cols"].split(":")
        for c in range(col2n(a), col2n(b) + 1):
            info["cols"][c] = x["width"]
    return info


def _empty(cell):
    return not cell or (cell.get("value") in (None, "") and not cell.get("formula"))


def _overlap(a, b):
    a1, ar1, a2, ar2 = parse(a)
    b1, br1, b2, br2 = parse(b)
    return not (a2 < b1 or b2 < a1 or ar2 < br1 or br2 < ar1)


def _spans(keys, limit=8):
    """一堆格子 → 「A2:C2、J29:K29 等 n 处」：同一行连续的并成一段。"""
    segs = []
    for r, c in sorted(keys):
        if segs and segs[-1][0] == r and segs[-1][2] == c - 1:
            segs[-1][2] = c
        else:
            segs.append([r, c, c])
    txt = [f"{n2col(a)}{r}" + (f":{n2col(b)}{r}" if b > a else "") for r, a, b in segs]
    return "、".join(txt[:limit]) + (f" 等 {len(txt)} 处" if len(txt) > limit else "")

# ---------- 写入前检查与预览 ----------

def lint(spec, sh, info, grid):
    """写入前查会出事的地方：隐藏列被设宽、新旧合并撞车、合并吞内容、已有表开着页边距或没洗旧样式。"""
    warn = []
    for c in sorted(set(sh.cols) & info.get("hidden_cols", set())):
        warn.append(f"{n2col(c)} 列是隐藏列，设列宽会让它显示出来：从页级 columns 里拿掉（类型可以写在区块的 columns 里）")
    old = [m for m in info.get("merges", []) if m not in sh.unmerges]
    for m in sh.merges:
        for o in old:
            if m == o:
                warn.append(f"{m} 已经合并过：重刷时加 --skip-merges")
            elif _overlap(m, o):
                warn.append(f"新合并 {m} 和已有合并 {o} 重叠：把 {o} 写进 unmerge")
    for m in sh.unmerges:
        if info and m not in info.get("merges", []):
            warn.append(f"unmerge 里的 {m} 在表里并没有合并")
    for m in sh.merges:
        c1, r1, _, _ = parse(m)
        lost = [(r, c) for r, c in cells(m) if (r, c) != (r1, c1) and not _empty(grid.get((r, c)))]
        if lost:
            warn.append(f"合并 {m} 会吞掉 {_spans(lost)} 的内容")
    if spec.get("gutter", True) and any(c == 1 and not _empty(v) for (_, c), v in grid.items()):
        warn.append("A 列有内容却开着 gutter（会把 A 列压成 20px 页边距）：已有表写 \"gutter\": false")
    if any(v["style"] for v in grid.values()) and not spec.get("reset"):
        warn.append("这是已有表但没写 reset：旧底色、斜体、旧边框会留在区块没盖到的格子里")
    return warn


def _fmt(v, f):
    """按数字格式粗略显示，够预览用：千分位、小数位、百分比、¥。"""
    if v in (None, ""):
        return ""
    x = v
    if isinstance(v, str):
        try:
            x = float(v.replace(",", "").replace("¥", ""))     # cells-get 把数字按原格式写成了字符串
        except ValueError:
            return v
    if not f or f in ("@", "General"):
        return v if isinstance(v, str) else f"{x:g}"
    m = re.search(r"0(?:\.(0+))?", f)
    pct = "%" in f
    s = format(x * 100 if pct else x, ("," if "," in f else "") + f".{len(m[1] or '') if m else 0}f")
    return ("¥" if "¥" in f else "") + s + ("%" if pct else "")


def preview_html(name, sh, grid, info, warns):
    """原表样式逐项叠上新样式（和飞书 +styles-put 的效果一致），渲染成一张网页。"""
    hc, hr = info.get("hidden_cols", set()), info.get("hidden_rows", set())
    used = [k for k, v in grid.items() if not _empty(v)] + list(sh.style)
    maxr, maxc = max(r for r, _ in used), max(c for _, c in used)
    rows = {**info.get("rows", {}), **sh.rows}
    cols = {**info.get("cols", {}), **sh.cols}
    merges = [m for m in info.get("merges", []) if m not in sh.unmerges] + sh.merges
    vis_r = [r for r in range(1, maxr + 1) if r not in hr]
    vis_c = [c for c in range(1, maxc + 1) if c not in hc]
    span, covered = {}, set()
    for m in merges:
        c1, r1, c2, r2 = parse(m)
        span[(r1, c1)] = (len([r for r in range(r1, r2 + 1) if r not in hr]),
                          len([c for c in range(c1, c2 + 1) if c not in hc]))
        covered |= set(cells(m)) - {(r1, c1)}
    out = []
    for r in vis_r:
        tds = []
        for c in vis_c:
            if (r, c) in covered:
                continue
            g = grid.get((r, c), {})
            st = {**g.get("style", {}), **sh.style.get((r, c), {})}
            css = [f"background:{_hex6(st.get('background_color')) or '#FFFFFF'}",
                   f"color:{_hex6(st.get('font_color')) or '#1F2329'}",
                   f"font-size:{st.get('font_size', 10) * 4 / 3:.1f}px",
                   f"font-weight:{700 if st.get('font_weight') == 'bold' else 400}",
                   f"font-style:{st.get('font_style') or 'normal'}",
                   f"text-align:{st.get('horizontal_alignment') or 'left'}",
                   "white-space:" + ("normal" if st.get("word_wrap") == "auto-wrap" else "nowrap")]
            for k, sd in (st.get("border") or st.get("border_styles") or {}).items():
                if sd.get("style", "none") != "none":
                    css.append(f"border-{k}:{2 if sd.get('weight') in ('medium', 'thick') else 1}px solid {_hex6(sd.get('color')) or '#000'}")
            txt = html.escape(_fmt(g.get("value"), st.get("number_format"))).replace("\n", "<br>")
            if not txt and g.get("formula"):
                txt = f'<i style="color:#8F959E">{html.escape(g["formula"])}</i>'
            rs, cs = span.get((r, c), (1, 1))
            tds.append(f'<td rowspan="{rs}" colspan="{cs}" style="{";".join(css)}">{txt}</td>')
        out.append(f'<tr style="height:{rows.get(r, 27)}px"><th>{r}</th>{"".join(tds)}</tr>')
    width = sum(cols.get(c, 100) for c in vis_c) + 32
    head = "".join(f"<th>{n2col(c)}</th>" for c in vis_c)
    notes = (f'<ul class="warn">{"".join(f"<li>{html.escape(w)}</li>" for w in warns)}</ul>' if warns
             else '<p class="ok">写入前检查：没发现风险</p>')
    hid = f"（隐藏列 {'、'.join(n2col(c) for c in sorted(hc))} 未显示）" if hc else ""
    page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:16px;background:#fff;font-family:Arial,"PingFang SC","Microsoft YaHei",sans-serif}}
h1{{font-size:15px;color:#1F2329;margin:0 0 6px}} .warn{{color:#B42318;font-size:13px;margin:0 0 10px;padding-left:18px}}
.ok{{color:#2E7D32;font-size:13px;margin:0 0 10px}}
table{{border-collapse:collapse;table-layout:fixed;width:{width}px}}
td{{border:1px solid #EEF0F2;padding:0 6px;overflow:hidden;box-sizing:border-box;vertical-align:middle}}
th{{background:#F5F6F7;color:#8F959E;font:400 11px Arial;border:1px solid #E4E5E7}}
</style></head><body><h1>预览 · {html.escape(name)}{hid}</h1>{notes}<table>
<colgroup><col style="width:32px">{"".join(f'<col style="width:{cols.get(c, 100)}px">' for c in vis_c)}</colgroup>
<tr style="height:22px"><th></th>{head}</tr>{"".join(out)}</table></body></html>"""
    height = sum(rows.get(r, 27) for r in vis_r) + 140 + 20 * len(warns)
    return page, width + 40, height


CHROME = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium", "chromium-browser"]


def screenshot(page, png, w, h):
    exe = next((p for p in CHROME if shutil.which(p) or pathlib.Path(p).exists()), None)
    if not exe:
        print("没找到 Chrome，只生成了 HTML", file=sys.stderr)
        return
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                    "--force-device-scale-factor=1", f"--screenshot={pathlib.Path(png).resolve()}",
                    pathlib.Path(page).resolve().as_uri()], capture_output=True, timeout=90)
    print(png)

# ---------- 审查：一张表（谁美化的都行）还剩哪些问题 ----------

NUMERIC = re.compile(r"^[-¥]?[\d,]+(\.\d+)?%?$")


def audit(grid, info, before=None):
    """只看看得见的格子（隐藏行列、被合并盖住的格子不算）。返回 (问题, 提示)。"""
    hc, hr = info.get("hidden_cols", set()), info.get("hidden_rows", set())
    covered = set()
    for m in info.get("merges", []):
        c1, r1, _, _ = parse(m)
        covered |= set(cells(m)) - {(r1, c1)}
    vis = {k: v for k, v in grid.items() if k[1] not in hc and k[0] not in hr and k not in covered}
    full = {k: v for k, v in vis.items() if not _empty(v)}
    if not full:
        return ["没读到内容"], []
    maxr, maxc = max(r for r, _ in full), max(c for _, c in full)
    area = {k: v for k, v in vis.items() if k[0] <= maxr and k[1] <= maxc}
    S = lambda v: v["style"]
    bg = lambda v: _hex6(S(v).get("background_color")) or WHITE
    probs, tips = [], []

    if before is not None:
        diff = [k for k in set(grid) | set(before)
                if (grid.get(k, {}).get("value"), grid.get(k, {}).get("formula")) !=
                   (before.get(k, {}).get("value"), before.get(k, {}).get("formula"))]
        (probs if diff else tips).append(f"值和公式与原表相比改了 {len(diff)} 格：{_spans(diff)}" if diff
                                         else "值和公式与原表一致")

    ital = [k for k, v in area.items() if S(v).get("font_style") == "italic"]
    if ital:
        probs.append(f"斜体 {len(ital)} 格：{_spans(ital)}")

    by_bg = {}
    for k, v in area.items():
        by_bg.setdefault(bg(v), [[], []])[_empty(v)].append(k)
    for color, (filled, empty) in sorted(by_bg.items()):
        if color != WHITE and not filled:
            probs.append(f"底色 {color} 只出现在空格子里（多半是旧样式残留）：{_spans(empty)}")

    bands = {bg(v) for v in full.values() if contrast(bg(v), WHITE) >= 3 and
             contrast(_hex6(S(v).get("font_color")) or "#000000", WHITE) < 1.5}
    if len(bands) > 1:
        probs.append(f"用了 {len(bands)} 种深色带（{'、'.join(sorted(bands))}），一页只该有一个深色")

    low = [k for k, v in full.items() if v.get("value") not in (None, "") and
           contrast(_hex6(S(v).get("font_color")) or "#1F2329", bg(v)) < 2.9]
    if low:
        probs.append(f"文字和底色对比度不足 3：{_spans(low)}")

    sizes = {}
    for k, v in full.items():
        sizes.setdefault(S(v).get("font_size"), []).append(k)
    dist = "、".join(f"{s} 号 {len(ks)} 格" for s, ks in sorted(sizes.items(), key=lambda x: -len(x[1])))
    if len(sizes) > 4 or max(s or 0 for s in sizes) >= 18:
        probs.append(f"字号层级太多或有 18 号以上的大字：{dist}")
    else:
        tips.append(f"字号分布：{dist}")
    fams = {S(v).get("font_family") or "默认" for v in full.values()}
    if len(fams) > 1:
        tips.append(f"字体混用：{'、'.join(sorted(fams))}")
    black = [k for k, v in full.items() if _hex6(S(v).get("font_color")) == "#000000"]
    if black:
        tips.append(f"纯黑字 {len(black)} 格（标准用 #1F2329）：{_spans(black, 4)}")

    for c in range(1, maxc + 1):                # 同一列连续的一段数字，格式应当一致
        run = []
        for r in range(1, maxr + 2):
            v = full.get((r, c))
            num = v and (isinstance(v["value"], (int, float)) or NUMERIC.match(str(v["value"] or "")))
            if num:
                run.append(S(v).get("number_format"))
                continue
            if len(set(run)) > 1:
                probs.append(f"{n2col(c)} 列第 {r - len(run)}–{r - 1} 行数字格式不一：{'、'.join(sorted(map(str, set(run))))}")
            run = []

    if not any(any(sd.get("style", "none") != "none" for sd in (S(v).get("border") or S(v).get("border_styles") or {}).values())
               for v in full.values()):
        tips.append("整页没有边框，只靠网格线对齐")
    anchors = {(parse(m)[1], parse(m)[0]) for m in info.get("merges", [])}
    wide, tight = [], []
    for c in range(1, maxc + 1):                # 列宽对照内容估算：中文 15px、其他 8px、加 28px 内边距；多行按最长一行
        w = info.get("cols", {}).get(c)
        need = [max(map(text_px, _fmt(v["value"], S(v).get("number_format")).split("\n")))
                for (r, cc), v in full.items() if cc == c and (r, c) not in anchors
                and S(v).get("word_wrap") != "auto-wrap"]
        if not w or not need:
            continue
        if w > max(need) * 1.5 and w - max(need) > 40:
            wide.append(f"{n2col(c)}（{w}px，内容约 {max(need)}px）")
        elif w < max(need) - 8:
            tight.append(f"{n2col(c)}（{w}px，内容约 {max(need)}px）")
    if tight:
        probs.append(f"这些列放不下内容，会被截断或显示 ####：{'、'.join(tight)}")
    if wide:
        tips.append(f"这些列比内容宽很多，表会显得散：{'、'.join(wide)}")
    for m in info.get("merges", []):
        if parse(m)[2] > maxc:
            probs.append(f"合并 {m} 超出表格右边界（内容只到 {n2col(maxc)} 列）")
    auto = sorted(r for r in info.get("auto_rows", set()) if r <= maxr and r not in hr)
    if auto:
        tips.append(f"这些行没设行高（自动）：{'、'.join(map(str, auto))}")
    return probs, tips

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    t = sub.add_parser("tokens"); t.add_argument("suite"); t.add_argument("--colors", type=int, default=5)
    f = sub.add_parser("feishu"); f.add_argument("layout"); f.add_argument("--out-dir", default=".")
    f.add_argument("--skip-merges", action="store_true", help="表里已合并过（重刷样式）时加上")
    x = sub.add_parser("xlsx"); x.add_argument("layout"); x.add_argument("src"); x.add_argument("dst")
    pv = sub.add_parser("preview"); pv.add_argument("layout"); pv.add_argument("--sheet", help="默认 layout 里第一页")
    pv.add_argument("--cells", help="原表回读（+cells-get）或 demo 的 values.json")
    pv.add_argument("--info", help="原表 +sheet-info（合并、隐藏、行高列宽）")
    pv.add_argument("--out", default="preview.html"); pv.add_argument("--png")
    u = sub.add_parser("audit"); u.add_argument("cells"); u.add_argument("--info")
    u.add_argument("--before", help="改之前回读的 cells.json，用来核对值和公式")
    a = ap.parse_args()

    if a.cmd == "list":
        for sid, s in PAL["suites"].items():
            print(f"{sid} {s['name']}｜{s['mood']}｜{s['fit']}｜{' · '.join(s['hues'])}")
        return
    if a.cmd == "tokens":
        json.dump(suite_tokens(a.suite, a.colors), sys.stdout, ensure_ascii=False, indent=1)
        print()
        return
    if a.cmd == "audit":
        probs, tips = audit(load_cells(a.cells), load_info(a.info), load_cells(a.before) if a.before else None)
        print(f"问题（{len(probs)}）")
        print("\n".join(f"  ✗ {x}" for x in probs) or "  无")
        print("提示")
        print("\n".join(f"  · {x}" for x in tips) or "  无")
        return

    lay = json.loads(pathlib.Path(a.layout).read_text(encoding="utf-8"))
    font = lay.get("font", "Arial")
    built = [(s["name"], build_sheet(s, suite_tokens(s.get("suite", lay.get("suite", "S02")),
                                                      s.get("colors", lay.get("colors", 3))), font))
             for s in lay["sheets"]]

    if a.cmd == "preview":
        i = next((k for k, s in enumerate(lay["sheets"]) if s["name"] == a.sheet), 0) if a.sheet else 0
        (name, sh), spec = built[i], lay["sheets"][i]
        grid = load_cells(a.cells, name) if a.cells else {}
        info = load_info(a.info)
        warns = lint(spec, sh, info, grid)
        page, w, h = preview_html(name, sh, grid, info, warns)
        pathlib.Path(a.out).write_text(page, encoding="utf-8")
        print(a.out)
        print("\n".join(f"  ! {x}" for x in warns) or "  写入前检查：没发现风险")
        if a.png:
            screenshot(a.out, a.png, w, h)
    elif a.cmd == "feishu":
        out = pathlib.Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for name, sh in built:
            if sh.unmerges:                    # +styles-put 不能取消合并，要先单独跑
                print(f"先取消「{name}」的这些合并，再跑下面的 styles 文件：")
                for m in sh.unmerges:
                    print(f"  lark-cli sheets +cells-unmerge --url <表> --sheet-name '{name}' --range {m}")
            for spec in to_feishu(name, sh, merges=not a.skip_merges):
                n += 1
                p = out / f"styles-{n:02d}.json"
                p.write_text(json.dumps({"styles": [spec]}, ensure_ascii=False), encoding="utf-8")
                print(p)
    else:
        from openpyxl import load_workbook
        wb = load_workbook(a.src)
        for name, sh in built:
            to_xlsx(wb[name], sh)
        wb.save(a.dst)
        print(a.dst)


if __name__ == "__main__":
    main()
