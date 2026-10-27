#!/usr/bin/env python3

import datetime as dt
import importlib.util
import pathlib
import unittest


SCRIPT = pathlib.Path(__file__).with_name("get_notes.py")
SPEC = importlib.util.spec_from_file_location("get_notes", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class GetNotesTests(unittest.TestCase):
    def test_redacts_credentials(self):
        raw = "Authorization gk_live_example.secret X-Client-ID cli_1234567890abcdef"
        safe = MODULE._redact(raw)
        self.assertNotIn("gk_live_", safe)
        self.assertNotIn("cli_123", safe)

    def test_success_output_recursively_redacts_secrets_and_url_queries(self):
        raw = {
            "title": "cli_1234567890abcdef",
            "content": [
                "gk_live_example.secret",
                "https://audio.example/file.mp3?token=secret&expires=123",
            ],
        }
        safe = MODULE._sanitize_output(raw)
        rendered = str(safe)
        self.assertNotIn("gk_live_", rendered)
        self.assertNotIn("cli_123", rendered)
        self.assertNotIn("token=secret", rendered)
        self.assertIn("[REDACTED_QUERY]", rendered)

    def test_max_chars_has_hard_upper_bound(self):
        self.assertEqual(MODULE._max_chars_arg("50000"), 50000)
        with self.assertRaises(Exception):
            MODULE._max_chars_arg("50001")

    def test_excerpt_prefers_query_match(self):
        text = "无关开头。" * 300 + "\n\n这是关于用户链路重塑和岗位合并的关键讨论。" + "\n\n无关结尾。" * 300
        excerpt = MODULE._bounded_excerpt(text, "用户链路重塑 岗位合并", 300)
        self.assertIn("用户链路重塑", excerpt)

    def test_parse_time_normalizes_timezone(self):
        parsed = MODULE._parse_time("2026-07-24 10:47:05")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, dt.timezone.utc)

    def test_search_results_are_deduplicated_by_note_id(self):
        items = [
            {"id": "1", "title": "第一条"},
            {"id": "1", "title": "第一条的重复命中"},
            {"id": "2", "title": "第二条"},
            {"id": "3", "title": "第三条"},
        ]
        unique = MODULE._dedupe_search_results(items, 3)
        self.assertEqual([item["id"] for item in unique], ["1", "2", "3"])

    def test_truncated_changes_forbids_cursor_advance(self):
        original_client = MODULE.Client

        class FakeClient:
            def __init__(self, timeout):
                self.timeout = timeout

            def list_all(self, max_pages):
                return [
                    {
                        "id": "1",
                        "title": "第一条",
                        "created_at": "2026-07-24T01:00:00+08:00",
                    },
                    {
                        "id": "2",
                        "title": "第二条",
                        "created_at": "2026-07-24T02:00:00+08:00",
                    },
                ]

        args = type(
            "Args",
            (),
            {
                "after": "2026-07-23T00:00:00+08:00",
                "timeout": 30,
                "max_pages": 10,
                "max_notes": 1,
            },
        )()
        try:
            MODULE.Client = FakeClient
            result = MODULE.command_changes(args)
        finally:
            MODULE.Client = original_client
        self.assertTrue(result["truncated"])
        self.assertFalse(result["cursor_advance_allowed"])
        self.assertEqual(result["status"], "partial")

    def test_safe_detail_omits_audio_url_and_keeps_transcript(self):
        detail = {
            "id": "1912345678901234567",
            "title": "测试会议",
            "content": "会议摘要",
            "audio": {"original": "完整转写内容", "play_url": "https://secret.example/audio"},
        }
        safe = MODULE._safe_detail(detail, "完整转写", 1000)
        rendered = str(safe)
        self.assertIn("完整转写内容", rendered)
        self.assertNotIn("play_url", rendered)
        self.assertNotIn("secret.example", rendered)


if __name__ == "__main__":
    unittest.main()
