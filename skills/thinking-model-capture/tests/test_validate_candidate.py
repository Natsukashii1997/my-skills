from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import stat
from unittest import mock


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from validate_candidate import validate_candidate_file  # noqa: E402
import safe_create_candidate as capture_module  # noqa: E402
from safe_create_candidate import (  # noqa: E402
    LOCK_DIRNAME,
    ReservationError,
    abort_reservation,
    reserve_candidate,
    validate_and_release,
)


def candidate_text(
    *,
    candidate_id: str = "TM-CAND-20260825-163000-a1b2c3d4",
    captured_at: str = "2026-08-25T16:30:00+08:00",
    thread_id: str = "thread-123",
    turn_id: str = "turn-456",
    candidate_type: str = "决策原则",
) -> str:
    return f"""---
candidate_schema_version: 3
candidate_id: {candidate_id}
captured_at: {captured_at}
source_thread_id: {thread_id}
source_turn_id: {turn_id}
source_project: /tmp/example-project
candidate_type: {candidate_type}
authorship: 常浩原创
sensitivity: 已抽象脱敏
redaction_status: abstracted_and_reviewed
redaction_categories: business
confidence: A
dedupe_fingerprint: 项目入口选择|先梳理再按需路由|项目级新想法
status: pending
---

# 项目入口选择

## 来源原话

> 新项目先询问是否进入深度梳理。

## 一句话抽象

项目级想法先由用户决定梳理深度，再进入按需执行。

## 作用机制

先锁定问题树可减少未经确认的实现假设，后续只调用命中当前任务的能力。

## 适用边界

适用于新应用、网站和项目级改造；小修复无需重开完整梳理。

## 与现有模型的关系

这是项目入口与能力路由之间的衔接规则，不替代具体开发方法。

## 待核验点

观察是否减少需求返工以及无关能力误调用。
"""


class CandidateValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def write_candidate(self, filename: str, text: str) -> Path:
        path = self.inbox / filename
        path.write_text(text, encoding="utf-8")
        return path

    def test_accepts_a_complete_v3_candidate(self) -> None:
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            candidate_text(),
        )
        self.assertEqual(validate_candidate_file(path, self.inbox), [])

    def test_rejects_a_second_candidate_for_the_same_known_turn(self) -> None:
        self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            candidate_text(),
        )
        second = self.write_candidate(
            "2026-08-25-163001-b2c3d4e5-另一候选.md",
            candidate_text(
                candidate_id="TM-CAND-20260825-163001-b2c3d4e5",
                captured_at="2026-08-25T16:30:01+08:00",
            ),
        )
        errors = validate_candidate_file(second, self.inbox)
        self.assertTrue(any("source turn already has a candidate" in error for error in errors))

    def test_unique_ids_do_not_bypass_unknown_source_fingerprint_dedupe(self) -> None:
        first = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            candidate_text(thread_id="unknown", turn_id="unknown"),
        )
        second = self.write_candidate(
            "2026-08-25-163001-b2c3d4e5-另一候选.md",
            candidate_text(
                candidate_id="TM-CAND-20260825-163001-b2c3d4e5",
                captured_at="2026-08-25T16:30:01+08:00",
                thread_id="unknown",
                turn_id="unknown",
            ),
        )
        first_errors = validate_candidate_file(first, self.inbox)
        second_errors = validate_candidate_file(second, self.inbox)
        self.assertTrue(any("dedupe_fingerprint exactly duplicates" in error for error in first_errors))
        self.assertTrue(any("dedupe_fingerprint exactly duplicates" in error for error in second_errors))

    def test_rejects_normalized_duplicate_fingerprint_even_when_sources_are_unknown(self) -> None:
        self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            candidate_text(thread_id="unknown", turn_id="unknown"),
        )
        second_text = candidate_text(
            candidate_id="TM-CAND-20260825-163001-b2c3d4e5",
            captured_at="2026-08-25T16:30:01+08:00",
            thread_id="unknown",
            turn_id="unknown",
        ).replace(
            "dedupe_fingerprint: 项目入口选择|先梳理再按需路由|项目级新想法",
            "dedupe_fingerprint:  项目入口选择 ｜ 先梳理再按需路由 | 项目级新想法 ",
        )
        second = self.write_candidate(
            "2026-08-25-163001-b2c3d4e5-另一候选.md",
            second_text,
        )
        errors = validate_candidate_file(second, self.inbox)
        self.assertTrue(any("dedupe_fingerprint exactly duplicates" in error for error in errors))

    def test_rejects_filename_identity_drift_and_invalid_enum(self) -> None:
        path = self.write_candidate(
            "2026-08-25-163005-deadbeef-错误候选.md",
            candidate_text(candidate_type="随手想法"),
        )
        errors = validate_candidate_file(path, self.inbox)
        joined = "\n".join(errors)
        self.assertIn("candidate_type must be one of", joined)
        self.assertIn("filename date/time must match candidate_id", joined)
        self.assertIn("filename suffix must match candidate_id", joined)

    def test_rejects_oversized_quotes_and_candidates(self) -> None:
        text = candidate_text().replace(
            "> 新项目先询问是否进入深度梳理。",
            "> 第一行\n> 第二行\n> 第三行",
        )
        text += "\n" + "\n".join(f"补充行 {index}" for index in range(30))
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            text,
        )
        errors = validate_candidate_file(path, self.inbox)
        joined = "\n".join(errors)
        self.assertIn("candidate must be at most 60 lines", joined)
        self.assertIn("source quotes may use at most 2", joined)

    def test_rejects_credentials_and_private_contact_details(self) -> None:
        text = candidate_text().replace(
            "观察是否减少需求返工以及无关能力误调用。",
            "测试凭据 sk-1234567890abcdefghijkl 与 test.person@example.com 不应进入候选箱。",
        )
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            text,
        )
        errors = validate_candidate_file(path, self.inbox)
        joined = "\n".join(errors)
        self.assertIn("possible OpenAI-style API key", joined)
        self.assertIn("possible email address", joined)

    def test_rejects_expanded_secret_link_and_international_phone_patterns(self) -> None:
        malicious_values = {
            "assigned credential": "api_key: abcdefghijklmnop12345678",
            "generic secret": "secret: abcdefghijklmnop12345678",
            "assigned private key": "private_key: abcdefghijklmnop12345678",
            "private key block": "-----BEGIN PRIVATE KEY-----",
            "Chinese key": "密钥：abcdefghijklmnop12345678",
            "Lark link": "https://private.larksuite.com/docx/doxcnSensitiveResource",
            "international phone": "+44 20 7946 0958",
        }
        for label, malicious_value in malicious_values.items():
            with self.subTest(label=label):
                text = candidate_text().replace(
                    "观察是否减少需求返工以及无关能力误调用。",
                    f"观察项：{malicious_value}",
                )
                path = self.write_candidate(
                    "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
                    text,
                )
                errors = validate_candidate_file(path, self.inbox)
                self.assertTrue(
                    any("candidate contains a possible" in error for error in errors),
                    errors,
                )
                path.unlink()

    def test_rejects_non_shanghai_timestamp_even_when_wall_clock_matches(self) -> None:
        for timestamp in ("2026-08-25T16:30:00+09:00", "2026-08-25T16:30:00Z"):
            with self.subTest(timestamp=timestamp):
                path = self.write_candidate(
                    "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
                    candidate_text(captured_at=timestamp),
                )
                errors = validate_candidate_file(path, self.inbox)
                self.assertTrue(any("actual Asia/Shanghai local time" in error for error in errors))
                path.unlink()

    def test_counts_blockquotes_indented_by_up_to_three_spaces(self) -> None:
        text = candidate_text().replace(
            "> 新项目先询问是否进入深度梳理。",
            "   > 第一行\n  > 第二行\n > 第三行",
        )
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            text,
        )
        errors = validate_candidate_file(path, self.inbox)
        self.assertTrue(any("source quotes may use at most 2" in error for error in errors))

    def test_requires_consistent_structured_redaction_declaration(self) -> None:
        text = candidate_text().replace(
            "redaction_status: abstracted_and_reviewed",
            "redaction_status: not_needed",
        )
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            text,
        )
        errors = validate_candidate_file(path, self.inbox)
        self.assertTrue(any("sensitivity 已抽象脱敏 requires" in error for error in errors))

    def test_historical_v2_candidate_is_read_only_but_still_participates_in_dedupe(self) -> None:
        historical = candidate_text().replace(
            "candidate_schema_version: 3",
            "candidate_schema_version: 2",
        ).replace(
            "redaction_status: abstracted_and_reviewed\nredaction_categories: business\n",
            "",
        )
        historical_path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-历史候选.md",
            historical,
        )
        historical_errors = validate_candidate_file(historical_path, self.inbox)
        self.assertTrue(any("historical v2 candidates are read-only" in error for error in historical_errors))

        new_path = self.write_candidate(
            "2026-08-25-163001-b2c3d4e5-新候选.md",
            candidate_text(
                candidate_id="TM-CAND-20260825-163001-b2c3d4e5",
                captured_at="2026-08-25T16:30:01+08:00",
                thread_id="unknown",
                turn_id="unknown",
            ),
        )
        new_errors = validate_candidate_file(new_path, self.inbox)
        self.assertTrue(any("dedupe_fingerprint exactly duplicates" in error for error in new_errors))

    def test_rejects_hard_link_candidate_and_does_not_follow_inbox_symlink(self) -> None:
        original = self.inbox / "original.txt"
        original.write_text(candidate_text(), encoding="utf-8")
        hard_link = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        os.link(original, hard_link)
        errors = validate_candidate_file(hard_link, self.inbox)
        self.assertTrue(any("may not be a hard link" in error for error in errors))

        hard_link.unlink()
        outside = self.inbox / "outside.md"
        outside.write_text(candidate_text(), encoding="utf-8")
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        candidate.write_text(candidate_text(), encoding="utf-8")
        unsafe = self.inbox / "unsafe.md"
        unsafe.symlink_to(outside)
        errors = validate_candidate_file(candidate, self.inbox)
        self.assertTrue(any("unsafe Markdown symlink" in error for error in errors))

    def test_rejects_ambiguous_dedupe_fingerprint(self) -> None:
        text = candidate_text().replace(
            "dedupe_fingerprint: 项目入口选择|先梳理再按需路由|项目级新想法",
            "dedupe_fingerprint: 只有一个模糊短语",
        )
        path = self.write_candidate(
            "2026-08-25-163000-a1b2c3d4-项目入口选择.md",
            text,
        )
        errors = validate_candidate_file(path, self.inbox)
        self.assertTrue(any("exactly 核心概念|作用机制|适用边界" in error for error in errors))


class CandidateReservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tempdir.name)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def archive_dirs(self, state: str) -> list[Path]:
        return sorted(self.inbox.glob(f"{LOCK_DIRNAME}.{state}-*"))

    def assert_auditable_archive(self, state: str) -> Path:
        archives = self.archive_dirs(state)
        self.assertEqual(len(archives), 1)
        archive = archives[0]
        self.assertRegex(archive.name, rf"^{re.escape(LOCK_DIRNAME)}\.{state}-[0-9a-f]{{32}}$")
        self.assertTrue(stat.S_ISDIR(archive.lstat().st_mode))
        payload = archive / "lock"
        self.assertTrue(stat.S_ISDIR(payload.lstat().st_mode))
        self.assertFalse(payload.is_symlink())
        return payload

    def test_reserve_then_validate_release_is_apply_patch_compatible(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        self.assertFalse(candidate.exists())
        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())

        # Unit-test setup stands in for the apply_patch step required by SKILL.md.
        candidate.write_text(candidate_text(), encoding="utf-8")
        self.assertEqual(validate_and_release(candidate, token, self.inbox), [])
        self.assertTrue(candidate.exists())
        self.assertFalse((self.inbox / LOCK_DIRNAME).exists())
        archived_lock = self.assert_auditable_archive("released")
        self.assertTrue((archived_lock / "reservation.json").is_file())

        next_candidate = self.inbox / "2026-08-25-163001-b2c3d4e5-下一候选.md"
        next_token = reserve_candidate(next_candidate, self.inbox)
        self.assertEqual(len(next_token), 64)
        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())
        abort_reservation(next_candidate, next_token, self.inbox)
        self.assertFalse((self.inbox / LOCK_DIRNAME).exists())

    def test_wrong_token_and_wrong_target_fail_closed(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        candidate.write_text(candidate_text(), encoding="utf-8")

        with self.assertRaisesRegex(ReservationError, "token is invalid"):
            validate_and_release(candidate, "0" * 64, self.inbox)
        other = self.inbox / "2026-08-25-163001-b2c3d4e5-另一候选.md"
        with self.assertRaisesRegex(ReservationError, "target does not match"):
            validate_and_release(other, token, self.inbox)
        self.assertTrue((self.inbox / LOCK_DIRNAME).exists())

    def test_validation_failure_keeps_lock_and_abort_requires_patch_cleanup(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        candidate.write_text(candidate_text().replace("candidate_schema_version: 3", "candidate_schema_version: 2"), encoding="utf-8")

        errors = validate_and_release(candidate, token, self.inbox)
        self.assertTrue(any("historical v2 candidates are read-only" in error for error in errors))
        self.assertTrue((self.inbox / LOCK_DIRNAME).exists())
        with self.assertRaisesRegex(ReservationError, "delete it with apply_patch"):
            abort_reservation(candidate, token, self.inbox)

        # Unit-test setup stands in for the required apply_patch deletion.
        candidate.unlink()
        abort_reservation(candidate, token, self.inbox)
        self.assertFalse((self.inbox / LOCK_DIRNAME).exists())

    def test_active_lock_blocks_and_expired_lock_is_recovered(self) -> None:
        first = self.inbox / "2026-08-25-163000-a1b2c3d4-第一候选.md"
        second = self.inbox / "2026-08-25-163001-b2c3d4e5-第二候选.md"
        base_time = datetime(2026, 8, 25, tzinfo=timezone.utc)
        reserve_candidate(first, self.inbox, ttl_seconds=30, now=base_time)

        with self.assertRaisesRegex(ReservationError, "active reservation"):
            reserve_candidate(second, self.inbox, ttl_seconds=30, now=base_time + timedelta(seconds=29))

        new_token = reserve_candidate(
            second,
            self.inbox,
            ttl_seconds=30,
            now=base_time + timedelta(seconds=31),
        )
        self.assertEqual(len(new_token), 64)
        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())
        self.assert_auditable_archive("stale")

    def test_expired_lock_is_not_recovered_while_its_candidate_remains(self) -> None:
        first = self.inbox / "2026-08-25-163000-a1b2c3d4-第一候选.md"
        second = self.inbox / "2026-08-25-163001-b2c3d4e5-第二候选.md"
        base_time = datetime(2026, 8, 25, tzinfo=timezone.utc)
        reserve_candidate(first, self.inbox, ttl_seconds=30, now=base_time)
        # Unit-test setup stands in for the apply_patch step required by SKILL.md.
        first.write_text(candidate_text(), encoding="utf-8")

        with self.assertRaisesRegex(ReservationError, "delete it with apply_patch"):
            reserve_candidate(
                second,
                self.inbox,
                ttl_seconds=30,
                now=base_time + timedelta(seconds=31),
            )
        self.assertTrue((self.inbox / LOCK_DIRNAME).exists())

        # Unit-test setup stands in for the required apply_patch deletion.
        first.unlink()
        token = reserve_candidate(
            second,
            self.inbox,
            ttl_seconds=30,
            now=base_time + timedelta(seconds=31),
        )
        self.assertEqual(len(token), 64)

    def test_symlink_lock_is_never_recovered_or_followed(self) -> None:
        outside = self.inbox / "outside"
        outside.mkdir()
        (self.inbox / LOCK_DIRNAME).symlink_to(outside, target_is_directory=True)
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        with self.assertRaisesRegex(ReservationError, "not a real directory"):
            reserve_candidate(candidate, self.inbox)

    def test_malformed_stale_lock_is_quarantined_without_recursive_deletion(self) -> None:
        lock_dir = self.inbox / LOCK_DIRNAME
        lock_dir.mkdir()
        (lock_dir / "reservation.json").write_text("not-json", encoding="utf-8")
        stale_epoch = datetime.now(timezone.utc).timestamp() - 700
        os.utime(lock_dir, (stale_epoch, stale_epoch))

        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        self.assertEqual(len(token), 64)
        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())
        archived_lock = self.assert_auditable_archive("stale")
        self.assertEqual((archived_lock / "reservation.json").read_text(encoding="utf-8"), "not-json")

    def test_metadata_write_failure_archives_only_the_exclusively_created_lock(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        with mock.patch(
            "safe_create_candidate._write_metadata_exclusive",
            side_effect=OSError("simulated metadata failure"),
        ):
            with self.assertRaisesRegex(ReservationError, "could not persist"):
                reserve_candidate(candidate, self.inbox)

        self.assertFalse((self.inbox / LOCK_DIRNAME).exists())
        self.assert_auditable_archive("failed")

    def test_archive_destination_is_exclusive_and_never_overwritten(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        candidate.write_text(candidate_text(), encoding="utf-8")
        collision = self.inbox / f"{LOCK_DIRNAME}.released-{'a' * 32}"
        collision.mkdir()
        sentinel = collision / "do-not-overwrite.txt"
        sentinel.write_text("preserve", encoding="utf-8")

        with mock.patch("safe_create_candidate.secrets.token_hex", return_value="a" * 32):
            with self.assertRaisesRegex(ReservationError, "archive destination"):
                validate_and_release(candidate, token, self.inbox)

        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())

    def test_archive_payload_race_uses_kernel_no_replace(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        candidate.write_text(candidate_text(), encoding="utf-8")
        real_archive_rename = capture_module._rename_noreplace

        def claim_payload_then_rename(
            source_dir_fd: int,
            source: str,
            destination_dir_fd: int,
            destination: str,
        ) -> None:
            os.mkdir(destination, dir_fd=destination_dir_fd)
            real_archive_rename(
                source_dir_fd,
                source,
                destination_dir_fd,
                destination,
            )

        with mock.patch(
            "safe_create_candidate._rename_noreplace",
            side_effect=claim_payload_then_rename,
        ):
            with self.assertRaisesRegex(ReservationError, "claimed concurrently"):
                validate_and_release(candidate, token, self.inbox)

        self.assertTrue((self.inbox / LOCK_DIRNAME / "reservation.json").is_file())
        archives = self.archive_dirs("released")
        self.assertEqual(len(archives), 1)
        self.assertTrue((archives[0] / "lock").is_dir())
        self.assertFalse((archives[0] / "lock" / "reservation.json").exists())

    def test_release_rechecks_the_exact_metadata_snapshot_after_validation(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        token = reserve_candidate(candidate, self.inbox)
        candidate.write_text(candidate_text(), encoding="utf-8")
        metadata_path = self.inbox / LOCK_DIRNAME / "reservation.json"

        def mutate_metadata_after_validation(*_args: object, **_kwargs: object) -> list[str]:
            metadata_path.write_text(
                metadata_path.read_text(encoding="utf-8") + " ",
                encoding="utf-8",
            )
            return []

        with mock.patch(
            "safe_create_candidate.validate_candidate_file",
            side_effect=mutate_metadata_after_validation,
        ):
            with self.assertRaisesRegex(ReservationError, "changed after ownership verification"):
                validate_and_release(candidate, token, self.inbox)

        self.assertTrue((self.inbox / LOCK_DIRNAME).is_dir())
        self.assertEqual(self.archive_dirs("released"), [])

    def test_failed_creation_never_archives_a_replacement_lock(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        detached_owned_lock = self.inbox / ".owned-lock-detached-by-test"
        replacement_lock = self.inbox / LOCK_DIRNAME

        def replace_lock_then_fail(*_args: object, **_kwargs: object) -> None:
            os.rename(replacement_lock, detached_owned_lock)
            replacement_lock.mkdir()
            (replacement_lock / "foreign.txt").write_text("preserve", encoding="utf-8")
            raise OSError("simulated metadata failure after source replacement")

        with mock.patch(
            "safe_create_candidate._write_metadata_exclusive",
            side_effect=replace_lock_then_fail,
        ):
            with self.assertRaisesRegex(ReservationError, "could not be archived safely"):
                reserve_candidate(candidate, self.inbox)

        self.assertTrue(detached_owned_lock.is_dir())
        self.assertEqual(
            (replacement_lock / "foreign.txt").read_text(encoding="utf-8"),
            "preserve",
        )
        self.assertEqual(self.archive_dirs("failed"), [])

    def test_stale_archive_post_rename_rejects_a_symlink_source_swap(self) -> None:
        stale_lock = self.inbox / LOCK_DIRNAME
        stale_lock.mkdir()
        (stale_lock / "reservation.json").write_text("not-json", encoding="utf-8")
        stale_epoch = datetime.now(timezone.utc).timestamp() - 700
        os.utime(stale_lock, (stale_epoch, stale_epoch))
        detached_stale_lock = self.inbox / ".stale-lock-detached-by-test"
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"

        with tempfile.TemporaryDirectory() as outside_tempdir:
            outside = Path(outside_tempdir)
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("untouched", encoding="utf-8")
            real_archive_rename = capture_module._rename_noreplace

            def swap_source_then_rename(
                source_dir_fd: int,
                source: str,
                destination_dir_fd: int,
                destination: str,
            ) -> None:
                os.rename(
                    source,
                    detached_stale_lock.name,
                    src_dir_fd=source_dir_fd,
                    dst_dir_fd=source_dir_fd,
                )
                os.symlink(
                    str(outside),
                    LOCK_DIRNAME,
                    target_is_directory=True,
                    dir_fd=source_dir_fd,
                )
                real_archive_rename(
                    source_dir_fd,
                    source,
                    destination_dir_fd,
                    destination,
                )

            with mock.patch(
                "safe_create_candidate._rename_noreplace",
                side_effect=swap_source_then_rename,
            ):
                with self.assertRaisesRegex(ReservationError, "post-rename identity proof"):
                    reserve_candidate(candidate, self.inbox)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")

        self.assertTrue(detached_stale_lock.is_dir())
        archives = self.archive_dirs("stale")
        self.assertEqual(len(archives), 1)
        self.assertTrue((archives[0] / "lock").is_symlink())

    def test_non_hex_token_is_rejected_without_touching_lock(self) -> None:
        candidate = self.inbox / "2026-08-25-163000-a1b2c3d4-项目入口选择.md"
        reserve_candidate(candidate, self.inbox)
        with self.assertRaisesRegex(ReservationError, "64 lowercase hexadecimal"):
            abort_reservation(candidate, "🔐" * 32, self.inbox)
        self.assertTrue((self.inbox / LOCK_DIRNAME).exists())


if __name__ == "__main__":
    unittest.main()
