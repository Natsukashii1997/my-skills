#!/usr/bin/env python3
"""Excel-Aura：按标准配色套组 + 版式规则，给表格稳定上样式。

用法：
  aura.py list                                  列出 10 套配色
  aura.py tokens S02 [--colors 3]               打印某套的派生色（标题带 / 文字色 / 边框 / 斑马纹…）
  aura.py feishu layout.json [--out-dir DIR] [--skip-merges]
                                                生成飞书 +styles-put 规格（按 70 项自动分片；重刷时跳过合并）
  aura.py xlsx layout.json in.xlsx out.xlsx     给本地 xlsx 上同一套样式

layout.json 的写法见 references/layout-spec.md。
"""
import argparse
import colorsys
import json
import pathlib
import re
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
FONT = {"title": 15, "section": 11, "header": 10, "body": 10, "note": 9}

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
        self.merges, self.rows, self.cols = [], {}, {}

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
        self.put(rng, _border={k: dict(side) for k in ("top", "bottom", "left", "right")})

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
    base = dict(font_family=font, font_size=FONT["body"], font_color=N["text"], vertical_alignment="middle")

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


def to_feishu(name, sh, chunk=70, merges=True):
    items = []
    for r1, c1, r2, c2, st in _rects(sh.style):
        rng = f"{n2col(c1)}{r1}" + (f":{n2col(c2)}{r2}" if (r1, c1) != (r2, c2) else "")
        d = {"range": rng, **{k: v for k, v in st.items() if k != "border"}}
        if "border" in st:
            d["border_styles"] = st["border"]
        items.append(d)
    rows = [{"range": f"{r}:{r}", "size": s} for r, s in sorted(sh.rows.items())]
    cols = [{"range": f"{n2col(c)}:{n2col(c)}", "size": s} for c, s in sorted(sh.cols.items())]
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
                            if k in st["border"] else Side())
            cell.border = Border(top=sd("top"), bottom=sd("bottom"), left=sd("left"), right=sd("right"))
    for r, px in sh.rows.items():
        ws.row_dimensions[r].height = round(px * 0.75, 1)       # px → 磅
    for c, px in sh.cols.items():
        ws.column_dimensions[get_column_letter(c)].width = round(px / 7.0, 1)  # px → 字符宽
    if sh.freeze:
        fr, fc = sh.freeze.get("rows", 0), sh.freeze.get("cols", 0)
        ws.freeze_panes = ws.cell(row=fr + 1, column=fc + 1)
    ws.sheet_view.showGridLines = False

# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    t = sub.add_parser("tokens"); t.add_argument("suite"); t.add_argument("--colors", type=int, default=5)
    f = sub.add_parser("feishu"); f.add_argument("layout"); f.add_argument("--out-dir", default=".")
    f.add_argument("--skip-merges", action="store_true", help="表里已合并过（重刷样式）时加上")
    x = sub.add_parser("xlsx"); x.add_argument("layout"); x.add_argument("src"); x.add_argument("dst")
    a = ap.parse_args()

    if a.cmd == "list":
        for sid, s in PAL["suites"].items():
            print(f"{sid} {s['name']}｜{s['mood']}｜{s['fit']}｜{' · '.join(s['hues'])}")
        return
    if a.cmd == "tokens":
        json.dump(suite_tokens(a.suite, a.colors), sys.stdout, ensure_ascii=False, indent=1)
        print()
        return

    lay = json.loads(pathlib.Path(a.layout).read_text(encoding="utf-8"))
    font = lay.get("font", "Arial")
    built = [(s["name"], build_sheet(s, suite_tokens(s.get("suite", lay.get("suite", "S02")),
                                                      s.get("colors", lay.get("colors", 3))), font))
             for s in lay["sheets"]]

    if a.cmd == "feishu":
        out = pathlib.Path(a.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for name, sh in built:
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
