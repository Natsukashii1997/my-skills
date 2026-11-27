#!/usr/bin/env python3
"""card_preview 测试：用一个假的 lark-cli，不连飞书。

运行：python3 -m unittest discover -s skills/card-versions/tests -v
"""

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import card_preview as cp  # noqa: E402

sys.path.insert(0, str(HERE))
import make_fixture  # noqa: E402

FAKE_LARK = make_fixture.FAKE_LARK


def card(title="日报", n=3, button=False):
    elements = [{"tag": "markdown", "content": "第 %d 段" % i} for i in range(n)]
    if button:
        elements.append({"tag": "button", "text": {"tag": "plain_text", "content": "按推荐"}, "value": {"x": 1}})
    return {"schema": "2.0", "header": {"title": {"tag": "plain_text", "content": title}}, "body": {"elements": elements}}


def run(argv, env=None):
    out, err = io.StringIO(), io.StringIO()
    old = dict(os.environ)
    os.environ.update(env or {})
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cp.main(argv)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, out.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="card-preview-"))
        self.lark = self.tmp / "lark-cli"
        self.lark.write_text(FAKE_LARK.replace("#!/usr/bin/env python3", "#!" + sys.executable), encoding="utf-8")
        self.lark.chmod(self.lark.stat().st_mode | stat.S_IEXEC)
        self.log = self.tmp / "calls.jsonl"
        self.out = self.tmp / "evidence"

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def write(self, name, data):
        path = self.tmp / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text(encoding="utf-8").splitlines()]

    def send(self, cards, mode="ok", extra=()):
        argv = ["send", "--profile", "app_x", "--chat-id", "oc_me", "--out", str(self.out), "--lark-cli", str(self.lark)]
        for c in cards:
            argv += ["--card", c]
        return run(argv + list(extra), {"FAKE_LARK_LOG": str(self.log), "FAKE_LARK_MODE": mode, "HERMES_HOME": "/should/not/pass"})


class FixtureCase(Base):
    def test_fixture_project_sends_through_fake_lark(self):
        project = make_fixture.build(self.tmp / "fx", chosen=True)
        conf = json.loads((project / "send_config.json").read_text(encoding="utf-8"))
        self.assertEqual(run(["check", str(project / "cards" / "daily.card.json")] + [str(p) for p in sorted((project / "evidence" / "preview").glob("*.json"))])[0], 0)
        code, out, err = run(["send", "--card", str(project / "cards" / "daily.card.json"), "--profile", conf["lark_profile"],
                              "--chat-id", conf["owner_chat_id"], "--out", str(project / "evidence"), "--lark-cli", str(project / "bin" / "lark-cli")],
                             {"FAKE_LARK_LOG": str(self.log)})
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["cards"][0]["read_back"])
        self.assertEqual(len((project / "evidence" / "card-preview.jsonl").read_text(encoding="utf-8").splitlines()), 2)


class InspectCase(Base):
    def test_counts_nested_components(self):
        nested = card(n=1)
        nested["body"]["elements"].append({"tag": "collapsible_panel", "elements": [{"tag": "markdown", "content": "x"}] * 3})
        self.assertEqual(len(list(cp.walk(cp.body_elements(nested)))), 5)

    def test_limits(self):
        self.assertEqual(cp.inspect(card(n=10))[0], [])
        problems, notes = cp.inspect(card(n=185))
        self.assertEqual(problems, [])
        self.assertTrue(any("接近上限" in n for n in notes))
        self.assertTrue(any("超过飞书上限 199" in p for p in cp.inspect(card(n=200))[0]))

    def test_missing_title_and_button_note(self):
        no_title = card()
        del no_title["header"]
        self.assertTrue(any("没有标题" in p for p in cp.inspect(no_title)[0]))
        self.assertTrue(any("按钮点了不会有真实效果" in n for n in cp.inspect(card(button=True))[1]))

    def test_check_cli(self):
        good, bad = self.write("a.json", card()), self.write("b.json", card(n=200))
        self.assertEqual(run(["check", good])[0], 0)
        code, out, _ = run(["check", good, bad])
        self.assertEqual(code, 1)
        self.assertIn("不能发", out)


class SendCase(Base):
    def test_sends_labels_and_reads_back(self):
        code, out, err = self.send([self.write("a.json", card("日报")), self.write("b.json", card("日报"))])
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual([c["title"] for c in result["cards"]], ["【预览 甲】日报", "【预览 乙】日报"])
        self.assertTrue(all(c["read_back"] for c in result["cards"]))
        calls = self.calls()
        self.assertEqual(len(calls), 4)
        first = calls[0]["args"]
        self.assertEqual(first[:4], ["--profile", "app_x", "im", "+messages-send"])
        self.assertIn("--as", first)
        self.assertEqual(first[first.index("--as") + 1], "bot")
        self.assertIsNone(calls[0]["hermes"])  # HERMES_* 不传给 lark-cli
        lines = (self.out / "card-preview.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["chat_id"], "oc_me")

    def test_same_batch_rerun_is_idempotent(self):
        a = self.write("a.json", card("日报"))
        first = json.loads(self.send([a])[1])["cards"][0]["message_id"]
        second = json.loads(self.send([a])[1])["cards"][0]["message_id"]
        self.assertEqual(first, second)

    def test_label_not_doubled(self):
        code, out, _ = self.send([self.write("a.json", card("【预览 甲】日报"))])
        self.assertEqual(json.loads(out)["cards"][0]["title"], "【预览 甲】日报")

    def test_custom_labels(self):
        code, out, _ = self.send([self.write("a.json", card()), self.write("b.json", card())], extra=["--label", "乙一", "--label", "乙二"])
        self.assertEqual([c["label"] for c in json.loads(out)["cards"]], ["乙一", "乙二"])
        self.assertEqual(self.send([self.write("c.json", card())], extra=["--label", "甲", "--label", "乙"])[0], 2)

    def test_readback_mismatch_fails(self):
        code, out, _ = self.send([self.write("a.json", card())], mode="readback_text")
        self.assertEqual(code, 1)
        self.assertIn("是卡片", json.loads(out)["cards"][0]["error"])

    def test_send_error_reported(self):
        code, out, _ = self.send([self.write("a.json", card())], mode="send_fail")
        self.assertEqual(code, 1)
        self.assertIn("no permission", json.loads(out)["cards"][0]["error"])

    def test_refuses_bad_card_before_sending(self):
        code, _, err = self.send([self.write("a.json", card(n=200))])
        self.assertEqual(code, 2)
        self.assertIn("不能发", err)
        self.assertFalse(self.log.exists())

    def test_dry_run_sends_nothing(self):
        code, out, _ = self.send([self.write("a.json", card())], extra=["--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("会发：", out)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
