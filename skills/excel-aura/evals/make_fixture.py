"""生成 evals E2、E3 用的「原表」：带旧样式、隐藏列和合计公式的周报。

用法：python3 make_fixture.py OUT_DIR
数据全是虚构的占位，不对应任何真实业务。
"""
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
wb = Workbook()
ws = wb.active
ws.title = "10月周报"
ws["A1"] = "10 月各业务线线索周报"
ws["A1"].font = Font(bold=True, size=18, color="FF0000")
ws.append(["业务线", "周次", "内部备注", "新增线索", "有效线索", "成交", "销售额（元）"])
rows = [
    ("A 线", "第 1 周", "勿外传", 120, 86, 9, 186000),
    ("A 线", "第 2 周", "", 132, 90, 11, 223500),
    ("B 线", "第 1 周", "渠道调整", 78, 51, 4, 92000),
    ("B 线", "第 2 周", "", 85, 60, 6, 131400),
    ("C 线", "第 1 周", "", 40, 33, 5, 75000),
    ("C 线", "第 2 周", "新人接手", 46, 35, 3, 48600),
]
yellow = PatternFill("solid", fgColor="FFFF00")
for r in rows:
    ws.append(r)
for row in ws.iter_rows(min_row=3, max_row=8):
    for c in row:
        c.font = Font(italic=True, color="000000")
ws["G4"].fill = yellow
ws["G6"].fill = yellow
ws["E9"].fill = yellow  # 空格子里的旧底色
ws["A10"] = "合计"
for col in "DEFG":
    ws[f"{col}10"] = f"=SUM({col}3:{col}8)"
ws.column_dimensions["C"].hidden = True
ws.column_dimensions["A"].width = 30
ws.column_dimensions["G"].width = 6
wb.save(out / "10月周报-原表.xlsx")
print(out / "10月周报-原表.xlsx")
