#!/usr/bin/env python3
"""生成 Excel-Aura 配色测试表：总览 1 页 + 10 套各 1 页（内容相同，只换配色）。

  demo.py OUT_DIR        写出 layout.json（给 aura.py）和 values.json（给 +cells-set --writes）

每套页面的结构：明细表（主色 + 斑马纹 + 合计）、分组汇总（分组表头取 ②–⑤、业务线按色序着色）、
测算卡（输入 / 计算 / 重点 / 目标）、本套色卡。
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import aura  # noqa: E402

LINES = ["留学申请", "语言培训", "背景提升", "游学营地", "职业规划"]
DETAIL = [
    ("2026-10-03", 0, "英美硕士申请季启动", "林夏", "完成", 286000, 1.00, "首批 12 位学生已递交"),
    ("2026-10-05", 1, "雅思冲刺班第 3 期", "周屿", "进行中", 98000, 0.62, ""),
    ("2026-10-08", 2, "科研项目暑期回访", "许诺", "完成", 54000, 1.00, ""),
    ("2026-10-10", 3, "冬令营英国线报名", "陈默", "风险", 132000, 0.35, "报名进度落后两周"),
    ("2026-10-12", 4, "求职辅导 1v1 试点", "沈星", "计划中", 26000, 0.10, ""),
    ("2026-10-15", 0, "港新硕士申请", "林夏", "进行中", 174000, 0.58, ""),
    ("2026-10-17", 1, "托福基础班", "周屿", "完成", 76000, 1.00, ""),
    ("2026-10-19", 2, "竞赛辅导秋季班", "许诺", "进行中", 63000, 0.71, ""),
    ("2026-10-21", 3, "新加坡研学营", "陈默", "暂停", 0, 0.00, "合作方档期调整"),
    ("2026-10-23", 4, "简历工作坊", "沈星", "完成", 18000, 1.00, ""),
    ("2026-10-25", 0, "澳洲本科直申", "顾言", "进行中", 92000, 0.44, ""),
    ("2026-10-27", 1, "学术写作小班", "周屿", "风险", 41000, 0.28, "师资未到位"),
]
TONE = {"完成": "good", "进行中": "warn", "风险": "bad", "计划中": "info", "暂停": "neutral"}
PLAN = [(500000, 4, "申请季主力"), (260000, 4, ""), (140000, 3, ""), (180000, 2, "英国线待追"), (60000, 2, "试点阶段")]
CALC = [  # (行, 指标, 值或公式, 角色, 格式)
    (7, "投放预算", 120000, "input", "¥#,##0"),
    (8, "获客成本", 600, "input", "¥#,##0"),
    (9, "获客人数", "=M7/M8", "calc", "#,##0"),
    (10, "转化率", 0.18, "input", "0.0%"),
    (11, "成交单数", "=M9*M10", "calc", "#,##0.0"),
    (12, "客单价", 26000, "input", "¥#,##0"),
    (13, "预计营收", "=M11*M12", "calc", "¥#,##0"),
    (14, "目标营收", 1000000, "target", "¥#,##0"),
    (15, "ROI", "=M13/M7", "key", "0.00"),
]
CIRCLED = "①②③④⑤"


def v(x):
    if isinstance(x, str) and x.startswith("="):
        return {"formula": x}
    return {"value": x}


def text(x):
    return {"value": x, "cell_styles": {"number_format": "@"}}


def suite_sheet(sid):
    s = aura.PAL["suites"][sid]
    tok = aura.suite_tokens(sid, 5)
    name = f"{sid} {s['name']}"
    order = " ".join(f"{CIRCLED[i]} {h}" for i, h in enumerate(s["hues"]))
    grid = {}  # (row, col) -> cell

    def put(row, col, cell):
        grid[(row, aura.col2n(col))] = cell

    put(2, "B", v(f"{sid} · {s['name']}"))
    put(3, "B", v(f"{s['mood']}｜适用：{s['fit']}｜色序 {order}｜用 N 色就取前 N 个"))
    put(5, "B", v("一、明细表 · 主色"))
    put(5, "L", v("三、测算卡 · 输入 / 计算 / 重点"))
    for c, h in zip("BCDEFGHIJ", ["序号", "日期", "业务线", "项目名称", "负责人", "状态", "金额", "完成率", "备注"]):
        put(6, c, v(h))
    put(6, "L", v("指标"))
    put(6, "M", v("数值"))
    tags, roles, paint = [], [], []
    for i, (d, li, proj, who, st, amt, rate, note) in enumerate(DETAIL):
        r = 7 + i
        for c, cell in zip("BCDEFGHIJ", [v(i + 1), text(d), v(LINES[li]), v(proj), v(who), v(st), v(amt), v(rate), v(note)]):
            put(r, c, cell)
        tags.append({"range": f"G{r}", "tone": TONE[st]})
    put(19, "B", v("合计"))
    put(19, "H", v("=SUM(H7:H18)"))
    put(19, "I", v("=AVERAGE(I7:I18)"))
    put(20, "B", v("注：状态只用文字色，只有风险带浅红底；正文不按类别铺色；合计、完成率均值、汇总区实际值都是公式。"))

    for r, label, val, role, fmt in CALC:
        put(r, "L", v(label))
        put(r, "M", v(val))
        roles.append({"range": f"M{r}", "role": role})
        paint.append({"range": f"M{r}", "fmt": fmt})

    put(22, "B", v("二、分组汇总 · 多色（表头分组依次取 ②③④⑤）"))
    put(22, "L", v("四、本套色卡"))
    for c, h in zip("BCDFHJ", ["序号", "业务线", "计划", "实际", "差异", "说明"]):
        put(23, c, v(h))
    for c, h in zip("DEFGHI", ["营收", "单量", "营收", "单量", "差额", "达成率"]):
        put(24, c, v(h))
    put(23, "L", v("色系"))
    put(23, "M", v("标题带色"))
    for i, ln in enumerate(LINES):
        r = 25 + i
        pv, pn, note = PLAN[i]
        cells = [v(i + 1), v(ln), v(pv), v(pn),
                 v(f'=SUMIF($D$7:$D$18,C{r},$H$7:$H$18)'), v(f'=COUNTIF($D$7:$D$18,C{r})'),
                 v(f"=F{r}-D{r}"), v(f"=IF(D{r}=0,0,F{r}/D{r})"), v(note)]
        for c, cell in zip("BCDEFGHIJ", cells):
            put(r, c, cell)
        H, lr = tok["hues"][i], 24 + i     # 色卡块表头在 23 行，色卡从 24 行起
        put(lr, "L", v(f"{CIRCLED[i]} {H['name']}"))
        put(lr, "M", v(H["band"]))
        paint += [{"range": f"L{lr}", "bg": H["soft"], "color": H["ink"], "bold": True},
                  {"range": f"M{lr}", "bg": H["band"], "color": "#FFFFFF", "align": "center"}]
    put(30, "B", v("合计"))
    for c in "DEFGH":
        put(30, c, v(f"=SUM({c}25:{c}29)"))
    put(30, "I", v("=IF(D30=0,0,F30/D30)"))
    put(31, "B", v("色序：① 主色 ② 辅色（冷暖相对）③ 中性色 ④⑤ 邻近色——用到 5 色看起来仍只有两个色相家族。分组表头依次取 ②③④⑤，色数不够就循环。"))

    num = {"type": "money"}
    layout = {
        "name": name, "suite": sid, "colors": 5,
        "gap_rows": [4, 21],
        "gap_cols": ["K"],
        "columns": {"B": {"type": "index"}, "C": {"type": "date"}, "D": {"type": "category", "width": 112},
                    "E": {"type": "name", "width": 168}, "F": {"type": "name", "width": 112},
                    "G": {"type": "tag", "width": 96}, "H": dict(num, width=120),
                    "I": {"type": "percent", "width": 96}, "J": {"type": "text", "width": 180},
                    "L": {"type": "label", "width": 160}, "M": {"type": "kpi", "width": 128}},
        "title": {"range": "B2:M2", "subtitle": "B3:M3"},
        "blocks": [
            {"hue": 1, "section": "B5:J5", "header": "B6:J6", "body": "B7:J18", "total": "B19:J19"},
            {"hue": 1, "section": "L5:M5", "header": "L6:M6", "body": "L7:M15",
             "columns": {"L": {"type": "label"}, "M": {"type": "kpi"}}},
            {"hue": 1, "section": "B22:J22", "header": "B23:J24", "body": "B25:J29", "total": "B30:J30",
             "header_groups": [{"range": "D23:E24", "hue": 2}, {"range": "F23:G24", "hue": 3},
                               {"range": "H23:I24", "hue": 4}, {"range": "J23:J24", "hue": 5}],
             "columns": {"B": {"type": "index"}, "C": {"type": "category"}, "D": num, "E": {"type": "number"},
                         "F": num, "G": {"type": "number"}, "H": num, "I": {"type": "percent"},
                         "J": {"type": "text"}}},
            {"hue": 1, "section": "L22:M22", "header": "L23:M23", "body": "L24:M28"},
        ],
        "merges": ["B23:B24", "C23:C24", "D23:E23", "F23:G23", "H23:I23", "J23:J24"],
        "roles": roles, "tags": tags, "paint": paint,
        "notes": ["B20:J20", "B31:J31"],
    }
    return name, layout, grid


def overview_sheet():
    name = "色卡总览"
    grid, paint, merges = {}, [], []

    def put(row, col, cell):
        grid[(row, aura.col2n(col))] = cell

    put(2, "B", v("Excel-Aura · 标准配色总览"))
    put(3, "B", v("10 套标准配色，每套按色序 ①→⑤ 排好；要几个主色就取前几个。下方是 19 条源色阶与参考表的 3 条，L1 最浅 → L5 最深。"))
    put(5, "B", v("一、10 套标准配色"))
    for c, h in zip("BCDEFGHIJ", ["编号", "套组", "气质", "①", "②", "③", "④", "⑤", "适用"]):
        put(6, c, v(h))
    r = 7
    for sid, s in aura.PAL["suites"].items():
        tok = aura.suite_tokens(sid, 5)
        put(r, "B", v(sid)); put(r, "C", v(s["name"])); put(r, "D", v(s["mood"])); put(r, "J", v(s["fit"]))
        merges += [f"{c}{r}:{c}{r + 1}" for c in "BCDJ"]
        for i, H in enumerate(tok["hues"]):
            c = "EFGHI"[i]
            put(r, c, v(H["name"]))
            put(r + 1, c, v(H["band"]))
            paint += [{"range": f"{c}{r}", "bg": H["soft"], "color": H["ink"], "bold": True, "align": "center"},
                      {"range": f"{c}{r + 1}", "bg": H["band"], "color": "#FFFFFF", "align": "center"}]
        r += 2
    end1 = r - 1
    sec2 = r + 1
    put(sec2, "B", v("二、源色阶（L1 → L5）"))
    for c, h in zip("BCDEFGHIJ", ["来源", "色阶", "出现在", "L1", "L2", "L3", "L4", "L5", "派生：标题带 / 浅底文字"]):
        put(sec2 + 1, c, v(h))
    used = {}
    for sid, s in aura.PAL["suites"].items():
        for i, h in enumerate(s["hues"]):
            used.setdefault(h, []).append(f"{sid}{CIRCLED[i]}")
    r = sec2 + 2
    for rn, ramp in aura.PAL["ramps"].items():
        H = aura.hue_tokens(rn)
        put(r, "B", v(ramp["src"])); put(r, "C", v(rn)); put(r, "D", v(" ".join(used.get(rn, []))))
        for i, hx in enumerate(ramp["steps"]):
            c = "EFGHI"[i]
            put(r, c, v(hx))
            fg = "#FFFFFF" if aura.contrast(hx, "#FFFFFF") >= 3.0 else H["ink"]
            paint.append({"range": f"{c}{r}", "bg": hx, "color": fg, "align": "center"})
        put(r, "J", v(f"{H['band']} / {H['ink']}"))
        r += 1
    end2 = r - 1
    layout = {
        "name": name, "suite": "S01", "colors": 1, "align": "center",
        "gap_rows": [4, sec2 - 1],
        "columns": {"B": {"type": "code", "width": 72}, "C": {"type": "category", "width": 104},
                    "D": {"type": "text", "width": 200}, **{c: {"type": "kpi", "width": 116} for c in "EFGHI"},
                    "J": {"type": "text", "width": 220}},
        "title": {"range": "B2:J2", "subtitle": "B3:J3"},
        "blocks": [
            {"hue": 1, "section": "B5:J5", "header": "B6:J6", "body": f"B7:J{end1}", "zebra": False,
             "columns": {"B": {"type": "code"}, "C": {"type": "category"}, "D": {"type": "text"}, "J": {"type": "text"}}},
            {"hue": 1, "section": f"B{sec2}:J{sec2}", "header": f"B{sec2 + 1}:J{sec2 + 1}",
             "body": f"B{sec2 + 2}:J{end2}", "zebra": False, "compact": True,
             "columns": {"B": {"type": "category"}, "C": {"type": "category"}, "D": {"type": "text"},
                         "J": {"type": "text"}}},
        ],
        "merges": merges, "paint": paint, "freeze": {"rows": 3},
    }
    return name, layout, grid


def writes(name, grid):
    """每段连续的非空格一项；空格不写，免得撞上已合并区域（飞书不许往合并区非左上角写值）。"""
    items = []
    for r in sorted({r for r, _ in grid}):
        cs = sorted(c for rr, c in grid if rr == r and grid[(rr, c)].get("value", 0) != "")
        while cs:
            n = 1
            while n < len(cs) and cs[n] == cs[0] + n:
                n += 1
            seg, cs = cs[:n], cs[n:]
            items.append({"sheet_name": name, "range": f"{aura.n2col(seg[0])}{r}:{aura.n2col(seg[-1])}{r}",
                          "cells": [[grid[(r, c)] for c in seg]]})
    return items


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    sheets, vals = [], {}
    for name, lay, grid in [overview_sheet()] + [suite_sheet(sid) for sid in aura.PAL["suites"]]:
        sheets.append(lay)
        vals[name] = writes(name, grid)
    (out / "layout.json").write_text(json.dumps({"font": "Arial", "sheets": sheets}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "values.json").write_text(json.dumps(vals, ensure_ascii=False), encoding="utf-8")
    print(out / "layout.json", out / "values.json", [s["name"] for s in sheets])


if __name__ == "__main__":
    main()
