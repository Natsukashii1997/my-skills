"""excel-aura 脚本测试：python3 -m unittest discover -s skills/excel-aura/tests

用 evals/make_fixture.py 生成的原表（斜体正文、隐藏 C 列、空格子 E9 黄底、第 10 行 SUM 合计）。
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
sys.path.insert(0, str(SKILL / "scripts"))
import aura  # noqa: E402

LAYOUT = {"suite": "S02", "colors": 2, "sheets": [{
    "name": "10月周报", "gutter": False, "reset": "A1:G10",
    "columns": {"A": {"type": "category"}, "D": {"type": "number"}, "G": {"type": "money", "max": "¥223,500"}},
    "blocks": [{"header": "A2:G2", "body": "A3:G8", "total": "A10:G10"}]}]}


class AuraTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = pathlib.Path(cls.tmp.name)
        subprocess.run([sys.executable, str(SKILL / "evals" / "make_fixture.py"), str(cls.dir)],
                       check=True, capture_output=True)
        cls.src = cls.dir / "10月周报-原表.xlsx"

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_aura(self, *args):
        return subprocess.run([sys.executable, str(SKILL / "scripts" / "aura.py"), *map(str, args)],
                              check=True, capture_output=True, text=True).stdout

    def build(self, sheet):
        return aura.build_sheet(sheet, aura.suite_tokens("S02", 2), "Arial")

    def test_load_xlsx_reads_values_formulas_styles_and_sheet_info(self):
        grid, info = aura.load_xlsx(self.src)
        self.assertEqual(grid[(10, 7)]["formula"], "=SUM(G3:G8)")
        self.assertEqual(grid[(3, 4)]["value"], 120)
        self.assertEqual(grid[(3, 3)]["style"].get("font_style"), "italic")
        self.assertEqual(grid[(9, 5)]["style"].get("background_color"), "#FFFF00")
        self.assertEqual(grid[(1, 1)]["style"].get("font_color"), "#FF0000")
        self.assertEqual(grid[(2, 1)]["style"], {})          # 没设过样式的格子
        self.assertEqual(info["hidden_cols"], {3})
        self.assertEqual(info["cols"][7], 42)                 # 6 个字符宽 → 42px

    def test_reset_accepts_a_list_and_a_string_alike(self):
        one = self.build({"gutter": False, "reset": "A1:B2"})
        many = self.build({"gutter": False, "reset": ["A1:A2", "B1:B2"]})
        self.assertEqual(one.style, many.style)

    def test_audit_reports_residue_in_hidden_cells(self):
        grid, info = aura.load_xlsx(self.src)
        probs, _ = aura.audit(grid, info)
        self.assertTrue(any("隐藏格子" in p and "C3:C8" in p for p in probs), probs)

    def test_lint_warns_when_reset_skips_hidden_column_with_old_style(self):
        grid, info = aura.load_xlsx(self.src)
        spec = {"gutter": False, "reset": ["A1:B10", "D1:G10"]}
        warns = aura.lint(spec, self.build(spec), info, grid)
        self.assertTrue(any("隐藏格子" in w for w in warns), warns)
        spec = {"gutter": False, "reset": "A1:G10"}
        sh = self.build(spec)
        self.assertFalse(any("隐藏格子" in w for w in aura.lint(spec, sh, info, grid)))
        self.assertTrue(aura.lint_notes(sh, info))          # 改了隐藏格子要写进说明

    def test_xlsx_roundtrip_washes_hidden_italic_and_keeps_values(self):
        lay, out = self.dir / "layout.json", self.dir / "out.xlsx"
        lay.write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
        self.run_aura("xlsx", lay, self.src, out)
        report = self.run_aura("audit", out, "--before", self.src)
        self.assertIn("值和公式与原表一致", report)
        self.assertNotIn("斜体", report)
        grid, info = aura.load_xlsx(out)
        self.assertEqual(info["hidden_cols"], {3})
        self.assertEqual(info["cols"].get(3), aura.load_xlsx(self.src)[1]["cols"].get(3))  # 隐藏列宽没被改
        self.assertNotIn("background_color", {k: v for k, v in grid[(9, 5)]["style"].items()
                                              if v != "#FFFFFF"})

    def test_preview_lets_unmerged_title_overflow_but_not_numbers(self):
        out = self.dir / "p.html"
        lay = self.dir / "layout.json"
        lay.write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
        self.run_aura("preview", lay, "--cells", self.src, "--out", out)
        page = out.read_text(encoding="utf-8")
        title = next(td for td in page.split("<td") if "10 月各业务线线索周报" in td)
        self.assertIn("overflow:visible", title)
        grid, info = aura.load_xlsx(self.src)
        self.assertFalse(aura._spills(grid, 3, 7, {}, info["hidden_cols"], set()))   # 数字不溢出

    def test_audit_ignores_spilling_title_when_checking_widths(self):
        grid, info = aura.load_xlsx(self.src)
        probs, _ = aura.audit(grid, info)
        tight = next((p for p in probs if "放不下" in p), "")
        self.assertNotIn("A（", tight)
        self.assertIn("G（", tight)


if __name__ == "__main__":
    unittest.main()
