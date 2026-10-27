#!/usr/bin/env python3
"""Regression boundaries for the four confirmed admission false positives."""

from pathlib import Path
import tempfile
import unittest

from test_audit_skills import AUDIT, add_protected_owners, write_skill


class GateBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.installed = self.base / "installed"
        self.installed.mkdir()
        add_protected_owners(self.installed)
        self.candidate = self.base / "candidate"
        self.candidate.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_audit(self, **kwargs):
        return AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,),
            installed_roots=(self.installed,), **kwargs,
        )

    def destructive_findings(self, result):
        return [d for d in result.diagnostics if d.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"]

    def test_existing_same_folder_mismatch_stays_visible_and_requires_ack(self):
        for root in (self.installed, self.candidate):
            write_skill(root, "named-helper", folder="legacy-folder")
        result = self.run_audit(allow_replace=("named-helper",))
        findings = [d for d in result.diagnostics if d.code == "FOLDER_NAME_MISMATCH"]
        self.assertEqual(2, len(findings))
        self.assertTrue(all(d.severity == "warning" for d in findings))
        self.assertEqual(0, result.error_count)
        self.assertFalse(result.passed)
        accepted = self.run_audit(
            allow_replace=("named-helper",), ack_warnings=("FOLDER_NAME_MISMATCH",),
        )
        self.assertTrue(accepted.passed)
        self.assertEqual(2, len([d for d in accepted.diagnostics if d.code == "FOLDER_NAME_MISMATCH"]))

    def test_new_mismatch_and_unauthorized_or_duplicate_replacements_fail(self):
        cases = (
            ("new-mismatch", "named-helper", "new-folder", True, 0, 0),
            ("changed-mismatch", "old-folder", "new-folder", True, 0, 0),
            ("unauthorized", "old-folder", "old-folder", False, 0, 0),
            ("installed-duplicate", "old-folder", "old-folder", True, 1, 0),
            ("candidate-duplicate", "old-folder", "old-folder", True, 0, 1),
        )
        for label, installed_folder, candidate_folder, allowed, extra_i, extra_c in cases:
            with self.subTest(case=label):
                installed = self.base / label / "installed"
                candidate = self.base / label / "candidate"
                add_protected_owners(installed)
                write_skill(installed, "named-helper", folder=installed_folder)
                write_skill(candidate, "named-helper", folder=candidate_folder)
                if extra_i:
                    write_skill(installed, "named-helper", folder="duplicate-installed")
                if extra_c:
                    write_skill(candidate, "named-helper", folder="duplicate-candidate")
                result = AUDIT.audit(
                    "pre-install", candidate_roots=(candidate,), installed_roots=(installed,),
                    allow_replace=("named-helper",) if allowed else (),
                    ack_warnings=("FOLDER_NAME_MISMATCH", "DUPLICATE_SKILL_NAME"),
                )
                self.assertFalse(result.passed)
                self.assertTrue(any(d.code == "FOLDER_NAME_MISMATCH" and d.severity == "error" for d in result.diagnostics))
                if extra_i or extra_c or not allowed:
                    self.assertTrue(any(d.code == "DUPLICATE_SKILL_NAME" for d in result.diagnostics))

    def test_sql_prohibition_mentions_do_not_imply_execution(self):
        skill = write_skill(self.candidate, "sql-manual")
        reference = skill / "references" / "sql.md"
        reference.parent.mkdir()
        cases = (
            "`CREATE/DROP DATABASE·SCHEMA·USER·ROLE`、非白名单 `CREATE EXTENSION`、平台保留表 `auth`/`users` 会被硬拒，`online` 环境禁 DDL。\n",
            "Do not execute `DROP TABLE users`.\n",
            "`TRUNCATE TABLE users` is prohibited.\n",
            "禁止执行 `DROP DATABASE example`。\n",
        )
        for source in cases:
            with self.subTest(source=source):
                reference.write_text(source)
                result = self.run_audit()
                self.assertEqual([], self.destructive_findings(result))
                self.assertTrue(result.passed)

    def test_sql_prohibition_does_not_mask_other_commands_or_code(self):
        skill = write_skill(self.candidate, "sql-manual")
        reference = skill / "references" / "sql.md"
        reference.parent.mkdir()
        cases = (
            "`DROP DATABASE example` is prohibited. Run `DROP TABLE users`.\n",
            "禁止执行 `DROP DATABASE example`；现在执行 `DROP TABLE users`。\n",
            "`DROP DATABASE example` 会被硬拒，执行 `DROP TABLE users`。\n",
            "Do not execute `DROP DATABASE example`.\n```sql\nDROP TABLE users;\n```\n",
            "```sql\n-- `DROP TABLE users` is prohibited\nDROP TABLE users;\n```\n",
            "`DROP DATABASE example` 会被硬拒。\nrm -rf /tmp/user-artifact\n",
            "Run `lark-cli apps +db-execute --sql 'DROP TABLE users'` even though it is prohibited.\n",
            "`DROP DATABASE example` is prohibited.\n\nDROP TABLE users;\n",
        )
        for source in cases:
            with self.subTest(source=source):
                reference.write_text(source)
                result = self.run_audit(ack_warnings=("RISK_SIGNAL_DESTRUCTIVE_ACTION",))
                self.assertTrue(self.destructive_findings(result))
                self.assertFalse(result.passed)
        reference.write_text("`DROP DATABASE example` 会被硬拒。\nDROP TABLE users;\n")
        self.assertEqual(2, self.destructive_findings(self.run_audit())[0].line)

    def test_sql_source_files_do_not_gain_prose_exemption(self):
        skill = write_skill(self.candidate, "sql-source")
        (skill / "execute.sh").write_text("echo '`DROP DATABASE example` is prohibited'\n")
        self.assertTrue(self.destructive_findings(self.run_audit()))

    def test_owned_mktemp_file_cleanup_is_bounded_in_candidate_and_installed(self):
        skill = write_skill(self.candidate, "owned-file")
        (skill / "convert.sh").write_text(
            'PAL=$(mktemp)\ncleanup_palette() {\n  rm -f -- "$PAL"\n}\ntrap cleanup_palette EXIT\n'
        )
        self.assertEqual([], self.destructive_findings(self.run_audit()))
        self.assertTrue(self.run_audit().passed)
        post = AUDIT.audit("post-install", installed_roots=(self.candidate, self.installed))
        self.assertTrue(post.passed)

    def test_candidate_cleanup_rejects_unproven_or_recursive_deletion(self):
        skill = write_skill(self.candidate, "cleanup-candidate")
        script = skill / "convert.sh"
        cases = (
            'PAL="$INPUT"\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\nPAL="$INPUT"\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\ncleanup() {\nrm -f -- "$PAL"\n}\nPAL="$INPUT"\ntrap cleanup EXIT\n',
            'PAL=$(mktemp)\nrm -rf -- "$PAL"\n',
            'PAL=$(mktemp -d)\nrm -rf -- "$PAL"\n',
            'PAL=$(mktemp -u)\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\nrm -f $PAL\n',
            'PAL=$(mktemp)\nrm -f -- "$PAL" "$INPUT"\n',
            'PAL=$(mktemp)\nread PAL\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\nsource config.sh\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\nOTHER="$PAL"\nrm -f -- "$OTHER"\n',
            'mktemp() {\nprintf /tmp/user-owned\n}\nPAL=$(mktemp)\nrm -f -- "$PAL"\n',
            'alias mktemp="printf /tmp/user-owned"\nPAL=$(mktemp)\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\nfor PAL in "$INPUT"; do\nrm -f -- "$PAL"\ndone\n',
            'PAL=$(mktemp)\nselect PAL in "$INPUT"; do\nrm -f -- "$PAL"\ndone\n',
            'PAL=$(mktemp)\ntrue; read PAL\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\ntrue; source config.sh\nrm -f -- "$PAL"\n',
            'PAL=$(mktemp)\ntrue; eval "$INPUT"\nrm -f -- "$PAL"\n',
        )
        for source in cases:
            with self.subTest(source=source):
                script.write_text(source)
                result = self.run_audit(ack_warnings=("RISK_SIGNAL_DESTRUCTIVE_ACTION",))
                self.assertTrue(self.destructive_findings(result))
                self.assertFalse(result.passed)

    def test_runtime_setting_override_is_not_a_skill_invocation_gate(self):
        sources = (
            "- Inherit the current model, reasoning effort, and service settings for discovery, generation, and QA workers. Change them only when the user explicitly requests it.\n",
            "Change the model only when the user explicitly requests it.\n",
        )
        for source in sources:
            with self.subTest(source=source):
                write_skill(self.candidate, "automatic-helper", body=source, policy=True)
                self.assertTrue(self.run_audit().passed)

    def test_model_setting_context_does_not_hide_actual_explicit_invocation_gate(self):
        prefix = "Inherit the current model, reasoning effort, and service settings. Change them only when the user explicitly requests it.\n"
        gates = (
            "Use this Skill only when the user explicitly requests it.\n",
            "Apply this style only after the user explicitly selects it.\n",
            "仅当用户明确点名时调用本 Skill。\n",
        )
        for gate in gates:
            with self.subTest(gate=gate):
                write_skill(self.candidate, "gated-helper", body=prefix + gate, policy=True)
                result = self.run_audit(ack_warnings=("EXPLICIT_POLICY_AMBIGUOUS",))
                self.assertFalse(result.passed)
                self.assertTrue(any(d.code == "EXPLICIT_POLICY_AMBIGUOUS" for d in result.diagnostics))


if __name__ == "__main__":
    unittest.main()
