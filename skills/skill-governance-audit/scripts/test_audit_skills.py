#!/usr/bin/env python3
"""Behavioral tests for audit_skills.py."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("audit_skills.py")
SPEC = importlib.util.spec_from_file_location("audit_skills", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


def write_skill(
    root: Path,
    name: str,
    description: str = "Handle one narrowly defined task when its exact artifact is supplied.",
    *,
    body: str = "# Test Skill\n\nPerform the bounded task.\n",
    explicit: bool = False,
    policy: bool | None = None,
    folder: str | None = None,
    governance: dict[str, object] | None = None,
) -> Path:
    skill_dir = root / (folder or name)
    (skill_dir / "agents").mkdir(parents=True, exist_ok=True)
    frontmatter: dict[str, object] = {"name": name, "description": description}
    if explicit:
        frontmatter["disable-model-invocation"] = True
    if governance is not None:
        frontmatter["metadata"] = {"governance": governance}
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        + AUDIT.yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body,
        encoding="utf-8",
    )
    if policy is not None:
        (skill_dir / "agents" / "openai.yaml").write_text(
            "policy:\n  allow_implicit_invocation: " + ("true" if policy else "false") + "\n",
            encoding="utf-8",
        )
    return skill_dir


def add_protected_owners(root: Path) -> None:
    for owner in AUDIT.PROTECTED_ROLES.values():
        write_skill(root, owner)


class AuditBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.installed = self.base / "installed"
        self.candidate = self.base / "candidate"
        self.installed.mkdir()
        self.candidate.mkdir()
        add_protected_owners(self.installed)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def codes(self, result: object) -> set[str]:
        return {item.code for item in result.diagnostics}

    def test_clean_candidate_passes(self) -> None:
        write_skill(self.candidate, "bounded-helper")
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.error_count, 0)

    def test_invalid_frontmatter_fails(self) -> None:
        bad = self.candidate / "broken"
        bad.mkdir()
        (bad / "SKILL.md").write_text("---\nname: [broken\n---\n", encoding="utf-8")
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertFalse(result.passed)
        self.assertIn("INVALID_YAML", self.codes(result))

    def test_duplicate_requires_exact_replace_allowance(self) -> None:
        write_skill(self.installed, "bounded-helper")
        write_skill(self.candidate, "bounded-helper")
        blocked = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        allowed = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            allow_replace=("bounded-helper",),
        )
        self.assertIn("DUPLICATE_SKILL_NAME", self.codes(blocked))
        self.assertNotIn("DUPLICATE_SKILL_NAME", self.codes(allowed))

    def test_protected_role_overreach_fails(self) -> None:
        write_skill(self.candidate, "rogue-author", "Default visual author for every application.")
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertFalse(result.passed)

    def test_orchestrator_may_assign_protected_owners(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "$frontend-design is the default visual author and "
            "$design-taste-frontend is the T1a/T1b/T2 reviewer.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertTrue(result.passed)

    def test_orchestrator_may_assign_markdown_wrapped_protected_owner(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "`$frontend-design` is the default visual author.\n"
            "**$design-taste-frontend** is the sole visual-taste reviewer.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertTrue(result.passed)

    def test_scoped_artifact_sole_author_is_not_default_visual_author_claim(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "`$frontend-design` is the default visual author. "
            "An explicitly selected specialist becomes the sole author of that named artifact.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertTrue(result.passed)

    def test_scoped_chinese_artifact_sole_author_is_not_default_visual_author_claim(self) -> None:
        specialist = self.installed / "named-artifact-specialist" / "SKILL.md"
        specialist.parent.mkdir(parents=True)
        specialist.write_text(
            "---\n"
            "name: named-artifact-specialist\n"
            "description: 只处理已经明确授权的单一视觉产物。\n"
            "---\n\n"
            "只成为清单内那个命名视觉产物的唯一作者，不接管项目视觉作者身份。\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertTrue(result.passed)

    def test_orchestrator_cannot_claim_author_or_reviewer_for_itself(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "This Skill is the default visual author and sole reviewer.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertFalse(result.passed)

    def test_orchestrator_owner_name_on_unrelated_line_does_not_exempt_claim(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "frontend-design may be consulted for separate implementation advice.\n"
            "This Skill is the default visual author.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertFalse(result.passed)

    def test_valid_owner_assignment_does_not_hide_later_orchestrator_self_claim(self) -> None:
        orchestrator = self.installed / AUDIT.PROTECTED_ROLES["visual_orchestrator"] / "SKILL.md"
        orchestrator.write_text(
            "---\n"
            "name: visual-app-development-sop\n"
            "description: Coordinate the bounded visual workstream.\n"
            "---\n\n"
            "$frontend-design is the default visual author.\n"
            "This Skill is the default visual author.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertFalse(result.passed)

    def test_negated_protected_role_statements_do_not_count_as_claims(self) -> None:
        write_skill(
            self.installed,
            "bounded-visual-specialist",
            body=(
                "# Boundaries\n\n"
                "This Skill is not the sole visual orchestrator, is not the default visual "
                "author, and is not the sole visual-taste reviewer.\n"
                "它不得担任唯一视觉编排者、默认视觉作者或唯一视觉审查者。\n"
            ),
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
        self.assertTrue(result.passed)

    def test_synonymous_protected_role_overreach_fails(self) -> None:
        cases = (
            ("rogue-workflow-owner", "This Skill is the visual workflow owner."),
            ("rogue-design-lead", "This Skill is the visual design lead for every app."),
            ("rogue-signoff", "This Skill is the final visual approver."),
            ("rogue-chinese-signoff", "本 Skill 拥有视觉终审权。"),
        )
        for name, body in cases:
            with self.subTest(name=name):
                case_root = self.base / name
                case_root.mkdir()
                add_protected_owners(case_root)
                write_skill(case_root, name, body=body)
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertIn("PROTECTED_ROLE_OVERREACH", self.codes(result))
                self.assertFalse(result.passed)

    def test_broad_candidate_trigger_fails(self) -> None:
        write_skill(self.candidate, "catch-all", "Any visual design task must always use this Skill.")
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertIn("BROAD_TRIGGER_ALL_DESIGN", self.codes(result))
        self.assertFalse(result.passed)

    def test_explicit_only_requires_false_policy(self) -> None:
        write_skill(self.candidate, "manual-helper", explicit=True)
        missing = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertIn("EXPLICIT_POLICY_MISSING", self.codes(missing))

        write_skill(self.candidate, "manual-helper", explicit=True, policy=False)
        fixed = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertNotIn("EXPLICIT_POLICY_MISSING", self.codes(fixed))
        self.assertTrue(fixed.passed)

    def test_explicit_selection_wording_requires_false_policy(self) -> None:
        write_skill(
            self.candidate,
            "selected-style",
            "Apply this style only after the user explicitly selects it.",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertFalse(result.passed)
        self.assertIn("EXPLICIT_POLICY_AMBIGUOUS", self.codes(result))

    def test_installed_textual_explicit_only_requires_false_policy(self) -> None:
        write_skill(
            self.installed,
            "selected-style",
            "Apply this style only after the user explicitly selects it.",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        matches = [
            item for item in result.diagnostics if item.code == "EXPLICIT_POLICY_AMBIGUOUS"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_explicit_only_wording_in_skill_body_requires_false_policy(self) -> None:
        write_skill(
            self.candidate,
            "body-selected-style",
            "Apply one named visual style when routed to it.",
            body=(
                "# Invocation boundary\n\n"
                "Use this Skill only after the user explicitly selects it.\n"
            ),
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertIn("EXPLICIT_POLICY_AMBIGUOUS", self.codes(result))
        self.assertFalse(result.passed)

    def test_explicit_only_metalinguistic_example_is_not_a_skill_gate(self) -> None:
        write_skill(
            self.installed,
            "invocation-policy-linter",
            body=(
                "# Rules\n\n"
                "The wording example ‘only after the user explicitly selects it’ is a "
                "policy smell that this linter reports in other Skills.\n"
            ),
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("EXPLICIT_POLICY_AMBIGUOUS", self.codes(result))
        self.assertTrue(result.passed)

    def test_compound_metalinguistic_explicit_policy_text_is_not_a_skill_gate(self) -> None:
        write_skill(
            self.installed,
            "invocation-policy-auditor",
            body=(
                "# Policy audit\n\n"
                "Audit structured or textual explicit-only invocation policy. "
                "Wording such as ‘only/after the user explicitly selects it’ requires "
                "a false implicit-invocation policy in the audited Skill.\n"
            ),
            policy=True,
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("EXPLICIT_POLICY_AMBIGUOUS", self.codes(result))
        self.assertTrue(result.passed)

    def test_approved_visual_sop_alternative_is_not_an_explicit_only_claim(self) -> None:
        write_skill(
            self.installed,
            "sop-routable-style",
            (
                "Apply this style after the user explicitly selects it or the visual SOP "
                "records an approved, exact style gap."
            ),
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("EXPLICIT_POLICY_AMBIGUOUS", self.codes(result))
        self.assertTrue(result.passed)

    def test_cli_json_is_machine_readable_and_nonzero_on_error(self) -> None:
        write_skill(self.candidate, "catch-all", "Any visual design task must always use this Skill.")
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = AUDIT.main(
                [
                    "pre-install",
                    str(self.candidate),
                    "--installed-root",
                    str(self.installed),
                    "--format",
                    "json",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertFalse(payload["pass"])
        self.assertGreater(payload["summary"]["errors"], 0)
        self.assertIn("infos", payload["summary"])

    def test_static_risk_signals_and_external_import_are_reported(self) -> None:
        skill = write_skill(self.candidate, "network-writer")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text(
            "import requests\n"
            "from pathlib import Path\n\n"
            "requests.get('https://example.invalid')\n"
            "Path('/tmp/result').write_text('result')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        codes = self.codes(result)
        self.assertFalse(result.passed)
        self.assertIn("RISK_SIGNAL_NETWORK", codes)
        self.assertIn("RISK_SIGNAL_EXTERNAL_WRITE", codes)
        self.assertIn("PYTHON_EXTERNAL_IMPORT", codes)
        self.assertIn("RUNTIME_DEPENDENCY_DECLARATION_MISSING", codes)
        self.assertIn("RISK_DECLARATION_MISSING", codes)

    def test_risk_declaration_documents_but_does_not_suppress_signal(self) -> None:
        skill = write_skill(
            self.candidate,
            "declared-network-writer",
            governance={
                "network": "required",
                "external-writes": "optional",
                "destructive-actions": "none",
                "credentials": "none",
                "dependencies": ["requests"],
            },
        )
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text(
            "import requests\n"
            "from pathlib import Path\n\n"
            "requests.get('https://example.invalid')\n"
            "Path('/tmp/result').write_text('result')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        codes = self.codes(result)
        self.assertFalse(result.passed)
        self.assertIn("RISK_SIGNAL_NETWORK", codes)
        self.assertIn("RISK_SIGNAL_EXTERNAL_WRITE", codes)
        self.assertIn("RISK_DECLARED", codes)
        self.assertNotIn("RISK_DECLARATION_MISSING", codes)
        self.assertNotIn("RUNTIME_DEPENDENCY_DECLARATION_MISSING", codes)

        acknowledged = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("RISK_SIGNAL_NETWORK", "RISK_SIGNAL_EXTERNAL_WRITE"),
        )
        self.assertTrue(acknowledged.passed)
        self.assertIn("RISK_SIGNAL_NETWORK", self.codes(acknowledged))
        self.assertIn("RISK_SIGNAL_EXTERNAL_WRITE", self.codes(acknowledged))

    def test_destructive_signal_and_possible_hardcoded_secret_fail(self) -> None:
        skill = write_skill(self.candidate, "unsafe-helper")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text(
            "import shutil\n\n"
            "API_KEY = 'sensitive-real-value-123456'\n"
            "shutil.rmtree('/tmp/example-target')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        codes = self.codes(result)
        self.assertFalse(result.passed)
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", codes)
        self.assertIn("RISK_SIGNAL_CREDENTIAL_ACCESS", codes)
        self.assertIn("POSSIBLE_HARDCODED_SECRET", codes)
        self.assertNotIn("sensitive-real-value-123456", json.dumps(result.as_json()))

    def test_nested_source_outside_scripts_detects_os_deletion_calls_as_errors(self) -> None:
        for function_name in ("remove", "unlink", "rmdir"):
            with self.subTest(function_name=function_name):
                case_root = self.base / f"candidate-{function_name}"
                case_root.mkdir()
                skill = write_skill(case_root, f"unsafe-{function_name}")
                (skill / "lib").mkdir()
                (skill / "lib" / "cleanup.py").write_text(
                    f"import os\n\nos.{function_name}('/tmp/example-target')\n",
                    encoding="utf-8",
                )
                result = AUDIT.audit(
                    "pre-install", candidate_roots=(case_root,), installed_roots=(self.installed,)
                )
                matches = [
                    item
                    for item in result.diagnostics
                    if item.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].severity, "error")
                self.assertFalse(result.passed)

    def test_cross_runtime_destructive_calls_fail_pre_install(self) -> None:
        cases = (
            ("node-rm", "cleanup.js", "const fs = require('fs');\nfs.rmSync('/tmp/target');\n"),
            (
                "node-unlink",
                "cleanup.mjs",
                "import fs from 'node:fs';\nfs.unlinkSync('/tmp/target');\n",
            ),
            ("deno-remove", "cleanup.ts", "await Deno.remove('/tmp/target');\n"),
            (
                "powershell-remove",
                "cleanup.ps1",
                "Remove-Item -LiteralPath 'C:\\\\Temp\\\\target' -Recurse -Force\n",
            ),
        )
        for name, filename, source in cases:
            with self.subTest(name=name):
                case_root = self.base / name
                case_root.mkdir()
                skill = write_skill(case_root, name)
                (skill / filename).write_text(source, encoding="utf-8")
                result = AUDIT.audit(
                    "pre-install", candidate_roots=(case_root,), installed_roots=(self.installed,)
                )
                matches = [
                    item
                    for item in result.diagnostics
                    if item.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0].severity, "error")
                self.assertFalse(result.passed)

    def test_installed_node_destructive_call_fails_post_install(self) -> None:
        skill = write_skill(self.installed, "installed-cleaner")
        (skill / "cleanup.js").write_text(
            "const fs = require('node:fs');\nfs.rmSync('/tmp/target', { recursive: true });\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        matches = [
            item
            for item in result.diagnostics
            if item.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_nonexclusive_generated_file_cleanup_fails_closed(self) -> None:
        skill = write_skill(self.installed, "generated-file-cleanup")
        (skill / "cleanup.js").write_text(
            "const fs = require('node:fs');\n"
            "const listFile = output + '.list';\n"
            "fs.writeFileSync(listFile, 'generated');\n"
            "fs.unlinkSync(listFile);\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_nonexclusive_fixed_directory_cleanup_fails_closed(self) -> None:
        skill = write_skill(self.installed, "generated-directory-cleanup")
        (skill / "cleanup.js").write_text(
            "const fs = require('node:fs');\n"
            "const tmpDir = path.join(outDir, '.tmp');\n"
            "fs.mkdirSync(tmpDir, { recursive: true });\n"
            "fs.rmSync(tmpDir, { recursive: true, force: true });\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_exclusive_node_mkdtemp_root_cleanup_is_bounded(self) -> None:
        skill = write_skill(self.installed, "exclusive-node-temp-cleanup")
        (skill / "cleanup.js").write_text(
            "const fs = require('node:fs');\n"
            "const os = require('node:os');\n"
            "const path = require('node:path');\n"
            "const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-run-'));\n"
            "fs.writeFileSync(path.join(tmpDir, 'generated.txt'), 'generated');\n"
            "fs.rmSync(tmpDir, { recursive: true, force: true });\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_installed_cleanup_remediations_remain_bounded(self) -> None:
        """Keep the audited installed-Skill cleanup fixes from regressing."""
        skills_root = Path(__file__).resolve().parents[2]
        relative_targets = (
            "frontend-slides/scripts/deploy.sh",
            "huashu-design/scripts/render-narration.sh",
            "huashu-design/scripts/render-video.js",
            "huashu-design/scripts/render-video-seek.js",
            "huashu-design/scripts/convert-formats.sh",
            "huashu-design/scripts/narrate-pipeline.mjs",
            "thinking-model-capture/scripts/safe_create_candidate.py",
        )
        available_targets = [
            skills_root / relative for relative in relative_targets
            if (skills_root / relative).is_file()
        ]
        if not available_targets:
            self.skipTest("the remediated sibling Skills are not installed")

        for path in available_targets:
            with self.subTest(path=str(path)):
                text = path.read_text(encoding="utf-8")
                unbounded = [
                    (match.method, AUDIT._line_number(text, match.start))
                    for match in AUDIT._destructive_source_matches(
                        path, text, include_domain_actions=False
                    )
                    if not AUDIT._is_strict_local_cleanup(path, text, match)
                ]
                self.assertEqual([], unbounded)

    def test_capture_lock_uses_exclusive_non_deleting_audit_archives(self) -> None:
        skills_root = Path(__file__).resolve().parents[2]
        path = skills_root / "thinking-model-capture/scripts/safe_create_candidate.py"
        if not path.is_file():
            self.skipTest("thinking-model-capture is not installed")

        text = path.read_text(encoding="utf-8")
        self.assertIn("secrets.token_hex(16)", text, "archive names need at least 128 random bits")
        self.assertIn("os.mkdir(archive_leaf", text, "archive container must be exclusive")
        self.assertIn("_rename_noreplace(", text, "the fixed lock needs a no-overwrite atomic move")
        self.assertIn('getattr(libc, "renameatx_np", None)', text)
        self.assertIn("Darwin RENAME_EXCL", text)
        self.assertIn('getattr(libc, "renameat2", None)', text)
        self.assertIn("Linux RENAME_NOREPLACE", text)
        self.assertIn('frozenset({"released", "stale", "failed"})', text)
        self.assertIn('ARCHIVE_PAYLOAD = "lock"', text)
        self.assertIn("expected_stat=created_archive", text)
        self.assertIn("handle.inbox_fd,\n            LOCK_DIRNAME", text)
        self.assertIn("archive_fd,\n            ARCHIVE_PAYLOAD", text)
        self.assertIn("_same_object(moved, handle.lock_stat)", text)
        self.assertIn("stat.S_ISLNK(moved.st_mode)", text)
        self.assertIn("_metadata_is_current(handle)", text)
        self.assertIn("follow_symlinks=False", text)
        self.assertNotRegex(text, r"\bos\.(?:remove|unlink|rmdir)\s*\(")
        self.assertNotRegex(text, r"\.\s*(?:unlink|rmdir)\s*\(")

    def test_real_cleanup_remediations_keep_paths_inside_owned_roots(self) -> None:
        skills_root = Path(__file__).resolve().parents[2]
        deploy_path = skills_root / "frontend-slides/scripts/deploy.sh"
        narration_path = skills_root / "huashu-design/scripts/render-narration.sh"
        renderer_paths = (
            skills_root / "huashu-design/scripts/render-video.js",
            skills_root / "huashu-design/scripts/render-video-seek.js",
        )
        if not deploy_path.is_file() or not narration_path.is_file():
            self.skipTest("the remediated sibling Skills are not installed")

        deploy = deploy_path.read_text(encoding="utf-8")
        self.assertIn("sed 's/[^a-z0-9-]/-/g'", deploy)
        self.assertIn('[[ "$ref" =~ (^|/)\\.\\.(/|$) ]]', deploy)
        self.assertLess(
            deploy.rfind("trap - EXIT"),
            deploy.rfind("cleanup_temp"),
            "disable the EXIT trap before the one explicit cleanup",
        )

        narration = narration_path.read_text(encoding="utf-8")
        self.assertIn('--out="$SILENT_FOR_MIX"', narration)
        self.assertIn("COPYFILE_EXCL", narration)
        self.assertLess(
            narration.rfind("trap - EXIT"),
            narration.rfind("cleanup_silent_run"),
            "disable the EXIT trap before the one explicit cleanup",
        )
        for renderer_path in renderer_paths:
            with self.subTest(renderer=str(renderer_path)):
                renderer = renderer_path.read_text(encoding="utf-8")
                self.assertIn("path.resolve(arg('out'", renderer)

    def test_installed_unproven_file_unlink_still_fails_post_install(self) -> None:
        skill = write_skill(self.installed, "unproven-file-unlink")
        (skill / "cleanup.js").write_text(
            "const fs = require('node:fs');\nfs.unlinkSync(targetPath);\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_post_install_catches_python_shell_and_node_alias_deletions(self) -> None:
        cases = (
            ("python-remove", "cleanup.py", "import os\nos.remove(target)\n"),
            ("python-unlink", "cleanup.py", "import os\nos.unlink(target)\n"),
            ("python-rmtree", "cleanup.py", "import shutil\nshutil.rmtree(target)\n"),
            ("shell-rm", "cleanup.sh", 'rm -rf "$TARGET"\n'),
            (
                "node-destructured",
                "cleanup.js",
                "const { rmSync: erase } = require('node:fs');\nerase(target);\n",
            ),
            (
                "node-import-alias",
                "cleanup.mjs",
                "import { unlinkSync as erase } from 'node:fs';\nerase(target);\n",
            ),
            (
                "node-namespace-alias",
                "cleanup.js",
                "const filesystem = require('fs');\nfilesystem.rmSync(target);\n",
            ),
        )
        for name, filename, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, name)
                (skill / filename).write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                matches = [
                    item
                    for item in result.diagnostics
                    if item.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"
                ]
                self.assertGreaterEqual(len(matches), 1)
                self.assertTrue(all(item.severity == "error" for item in matches))
                self.assertFalse(result.passed)

    def test_create_then_delete_does_not_exempt_user_paths_or_reassignments(self) -> None:
        cases = (
            (
                "user-path",
                "const fs = require('fs');\n"
                "const target = process.argv[2];\n"
                "fs.writeFileSync(target, 'generated');\n"
                "fs.unlinkSync(target);\n",
            ),
            (
                "reassigned-path",
                "const fs = require('fs');\n"
                "let tempFile = output + '.tmp';\n"
                "fs.writeFileSync(tempFile, 'generated');\n"
                "tempFile = userPath;\n"
                "fs.unlinkSync(tempFile);\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-cleanup-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, f"cleanup-{name}")
                (skill / "cleanup.js").write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_installed_guard_pattern_catalog_is_not_an_executed_deletion(self) -> None:
        skill = write_skill(self.installed, "git-command-guard")
        (skill / "guard.sh").write_text(
            "DANGEROUS_PATTERNS=(\n  \"git reset --hard\"\n  \"git clean -fd\"\n)\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_post_install_ignores_destructive_syntax_only_in_python_comment(self) -> None:
        skill = write_skill(self.installed, "source-comment-catalog")
        (skill / "scanner.py").write_text(
            "# A broad fallback such as `.unlink(` is reported by the scanner.\n"
            "print('clean')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_unicode_before_python_regex_catalog_does_not_unmask_comments(self) -> None:
        skill = write_skill(self.installed, "unicode-source-comment-catalog")
        (skill / "scanner.py").write_text(
            "import re\n"
            # CPython AST columns are UTF-8 byte offsets. Keep non-ASCII text
            # before the regex argument on the same line so a character-offset
            # implementation corrupts the mask and can expose the comment.
            "LABEL = '审计器使用中文说明。'; PATTERN = re.compile(r'\\.unlink\\s*\\(')\n"
            "# A broad fallback such as `.unlink(` overlaps `fs.unlink(`.\n"
            "print(LABEL)\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_unqualified_unlink_method_is_not_assumed_to_be_python_os_delete(self) -> None:
        skill = write_skill(self.installed, "domain-object-unlink")
        (skill / "model.py").write_text(
            "entry = registry.current()\n"
            "entry.unlink()\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_python_path_delete_variants_fail_post_install(self) -> None:
        cases = (
            (
                "direct-constructor",
                "from pathlib import Path\nPath(user_input).unlink()\n",
            ),
            (
                "annotated-parameter",
                "from pathlib import Path\ndef erase(target: Path):\n    target.unlink()\n",
            ),
            (
                "iterated-child",
                "from pathlib import Path\n"
                "root = Path(user_input)\n"
                "entries = list(root.iterdir())\n"
                "entries[0].unlink()\n",
            ),
            (
                "constructor-alias",
                "from pathlib import Path as P\nP(user_input).unlink()\n",
            ),
            (
                "module-alias",
                "import pathlib as pl\npl.Path(user_input).rmdir()\n",
            ),
            (
                "branch-union",
                "from pathlib import Path\n"
                "if condition:\n"
                "    target = Path(user_input)\n"
                "else:\n"
                "    target = registry.current()\n"
                "target.unlink()\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-python-path-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, f"python-path-{name}")
                (skill / "cleanup.py").write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_python_non_path_or_overwritten_receivers_do_not_false_positive(self) -> None:
        cases = (
            (
                "overwritten",
                "from pathlib import Path\n"
                "target: Path = Path(user_input)\n"
                "target = registry.current()\n"
                "target.unlink()\n",
            ),
            (
                "shadowed-constructor",
                "from pathlib import Path\n"
                "Path = factory\n"
                "Path(user_input).unlink()\n",
            ),
            (
                "domain-class",
                "class Record:\n"
                "    def unlink(self):\n"
                "        return None\n"
                "record = Record()\n"
                "record.unlink()\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-python-domain-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, f"python-domain-{name}")
                (skill / "model.py").write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertTrue(result.passed)

    def test_python_parse_failure_with_unlink_fails_closed(self) -> None:
        skill = write_skill(self.installed, "broken-python-cleaner")
        (skill / "cleanup.py").write_text(
            "from pathlib import Path\nif broken syntax\nPath(user).unlink()\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_post_install_product_domain_delete_is_not_a_filesystem_delete(self) -> None:
        skill = write_skill(self.installed, "product-delete-runbook")
        references = skill / "references"
        references.mkdir()
        (references / "commands.md").write_text(
            "Delete the selected remote record:\n\n"
            "```bash\n"
            "lark-cli records delete --record-id '<id>'\n"
            "```\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_nonexclusive_generated_shell_artifact_cleanup_fails_closed(self) -> None:
        skill = write_skill(self.installed, "generated-shell-cleanup")
        (skill / "convert.sh").write_text(
            "PAL=\"$OUT/.palette-$BASE.png\"\n"
            "ffmpeg -i \"$INPUT\" \\\n"
            "  \"$PAL\"\n"
            "rm -f \"$PAL\"\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_renamed_branch_target_cleanup_fails_closed(self) -> None:
        skill = write_skill(self.installed, "branch-guarded-temp-cleanup")
        (skill / "deploy.sh").write_text(
            "if [[ -f \"$INPUT\" ]]; then\n"
            "  TARGET=$(mktemp -d)\n"
            "  cp \"$INPUT\" \"$TARGET/index.html\"\n"
            "  CLEANUP=true\n"
            "elif [[ -d \"$INPUT\" ]]; then\n"
            "  TARGET=\"$INPUT\"\n"
            "  CLEANUP=false\n"
            "fi\n"
            "if [[ \"$CLEANUP\" == \"true\" ]]; then\n"
            "  RENAMED=\"$(dirname \"$TARGET\")/$NAME\"\n"
            "  mv \"$TARGET\" \"$RENAMED\"\n"
            "  TARGET=\"$RENAMED\"\n"
            "fi\n"
            "if [[ \"$CLEANUP\" == \"true\" ]]; then\n"
            "  rm -rf \"$TARGET\"\n"
            "fi\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_owned_mktemp_root_cleanup_is_bounded_after_inner_rename(self) -> None:
        skill = write_skill(self.installed, "owned-temp-root-cleanup")
        (skill / "deploy.sh").write_text(
            "TEMP_ROOT=$(mktemp -d)\n"
            "TARGET=\"$TEMP_ROOT/source\"\n"
            "mkdir \"$TARGET\"\n"
            "RENAMED=\"$TEMP_ROOT/$NAME\"\n"
            "mv -- \"$TARGET\" \"$RENAMED\"\n"
            "TARGET=\"$RENAMED\"\n"
            "rm -rf -- \"$TEMP_ROOT\"\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_owned_mktemp_cleanup_after_blank_line_is_still_bounded(self) -> None:
        skill = write_skill(self.installed, "owned-temp-cleanup-after-blank")
        (skill / "cleanup.sh").write_text(
            "TEMP_ROOT=$(mktemp -d)\n"
            "mkdir \"$TEMP_ROOT/work\"\n"
            "\n"
            "rm -rf -- \"$TEMP_ROOT\"\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_branch_guard_does_not_exempt_user_controlled_or_reassigned_paths(self) -> None:
        cases = (
            (
                "user-controlled-path",
                "TARGET=\"$1\"\n"
                "CLEANUP=\"$2\"\n"
                "if [[ \"$CLEANUP\" == \"true\" ]]; then\n"
                "  rm -rf \"$TARGET\"\n"
                "fi\n",
            ),
            (
                "reassigned-inside-guard",
                "TARGET=$(mktemp -d)\n"
                "CLEANUP=true\n"
                "if [[ \"$CLEANUP\" == \"true\" ]]; then\n"
                "  TARGET=\"$INPUT\"\n"
                "  rm -rf \"$TARGET\"\n"
                "fi\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, name)
                (skill / "cleanup.sh").write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_stale_derived_intermediate_cleanup_fails_closed(self) -> None:
        skill = write_skill(self.installed, "rendered-intermediate-cleanup")
        (skill / "render.sh").write_text(
            "if [ -z \"$HTML\" ] || [ ! -f \"$HTML\" ]; then exit 1; fi\n"
            "HTML_ABS=\"$(cd \"$(dirname \"$HTML\")\" && pwd)/$(basename \"$HTML\")\"\n"
            "HTML_DIR=\"$(dirname \"$HTML_ABS\")\"\n"
            "HTML_BASE=\"$(basename \"$HTML\" .html)\"\n"
            "INTERMEDIATE=\"$HTML_DIR/$HTML_BASE.mp4\"\n"
            "node \"$SCRIPT_DIR/render-video.js\" \"$HTML_ABS\" --duration=10\n"
            "if [ ! -f \"$INTERMEDIATE\" ]; then exit 1; fi\n"
            "bash mix.sh \"$INTERMEDIATE\" --out=final.mp4\n"
            "if [ -z \"$KEEP_INTERMEDIATE\" ]; then\n"
            "  rm -f \"$INTERMEDIATE\"\n"
            "fi\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertFalse(result.passed)

    def test_rendered_intermediate_moved_under_owned_temp_root_is_bounded(self) -> None:
        skill = write_skill(self.installed, "owned-rendered-intermediate-cleanup")
        (skill / "render.sh").write_text(
            "if [ -e \"$SILENT\" ]; then exit 1; fi\n"
            "node render-video.js \"$HTML\"\n"
            "if [ ! -f \"$SILENT\" ]; then exit 1; fi\n"
            "SILENT_RUN_DIR=$(mktemp -d)\n"
            "mv -- \"$SILENT\" \"$SILENT_RUN_DIR/silent.mp4\"\n"
            "bash mix.sh \"$SILENT_RUN_DIR/silent.mp4\" --out=final.mp4\n"
            "rm -rf -- \"$SILENT_RUN_DIR\"\n",
            encoding="utf-8",
        )
        result = AUDIT.audit("post-install", installed_roots=(self.installed,))
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_intermediate_cleanup_requires_derived_path_creator_and_existence_guard(self) -> None:
        cases = (
            (
                "user-path",
                "INTERMEDIATE=\"$1\"\n"
                "node render-video.js \"$HTML\"\n"
                "if [ ! -f \"$INTERMEDIATE\" ]; then exit 1; fi\n"
                "rm -f \"$INTERMEDIATE\"\n",
            ),
            (
                "missing-proof",
                "DIR=\"$(dirname \"$HTML\")\"\n"
                "BASE=\"$(basename \"$HTML\" .html)\"\n"
                "INTERMEDIATE=\"$DIR/$BASE.mp4\"\n"
                "rm -f \"$INTERMEDIATE\"\n",
            ),
        )
        for name, source in cases:
            with self.subTest(name=name):
                case_root = self.base / f"installed-intermediate-{name}"
                case_root.mkdir()
                add_protected_owners(case_root)
                skill = write_skill(case_root, f"intermediate-{name}")
                (skill / "cleanup.sh").write_text(source, encoding="utf-8")
                result = AUDIT.audit("post-install", installed_roots=(case_root,))
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_skill_referenced_test_named_source_is_scanned(self) -> None:
        skill = write_skill(
            self.candidate,
            "referenced-test-hook",
            body=(
                "# Referenced hook\n\n"
                "Run `python3 scripts/test_hook.py` to perform the bounded operation.\n"
            ),
        )
        (skill / "scripts").mkdir()
        (skill / "scripts" / "test_hook.py").write_text(
            "import os\n\nos.remove('/tmp/target')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        matches = [
            item
            for item in result.diagnostics
            if item.code == "RISK_SIGNAL_DESTRUCTIVE_ACTION"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_skill_referenced_sources_inside_tests_and_fixtures_are_scanned(self) -> None:
        for directory in ("tests", "fixtures"):
            with self.subTest(directory=directory):
                case_root = self.base / f"candidate-referenced-{directory}"
                case_root.mkdir()
                skill = write_skill(
                    case_root,
                    f"referenced-{directory}-hook",
                    body=(
                        "# Referenced hook\n\n"
                        f"Run `python3 {directory}/cleanup_hook.py` for the operation.\n"
                    ),
                )
                source_dir = skill / directory
                source_dir.mkdir()
                (source_dir / "cleanup_hook.py").write_text(
                    "import os\nos.remove('/tmp/target')\n", encoding="utf-8"
                )
                result = AUDIT.audit(
                    "pre-install", candidate_roots=(case_root,), installed_roots=(self.installed,)
                )
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_instruction_bearing_markdown_and_text_references_are_scanned(self) -> None:
        for suffix in ("md", "txt"):
            with self.subTest(suffix=suffix):
                case_root = self.base / f"candidate-reference-{suffix}"
                case_root.mkdir()
                skill = write_skill(case_root, f"destructive-runbook-{suffix}")
                references = skill / "references"
                references.mkdir()
                (references / f"runbook.{suffix}").write_text(
                    "To remove the selected target, run this command:\n\n"
                    "```bash\n"
                    'rm -rf "$TARGET"\n'
                    "```\n",
                    encoding="utf-8",
                )
                result = AUDIT.audit(
                    "pre-install", candidate_roots=(case_root,), installed_roots=(self.installed,)
                )
                self.assertIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
                self.assertFalse(result.passed)

    def test_reference_explanations_and_regex_catalogs_do_not_execute_deletion(self) -> None:
        skill = write_skill(self.candidate, "deletion-signal-catalog")
        references = skill / "references"
        references.mkdir()
        (references / "catalog.md").write_text(
            "Forbidden example; never run this command:\n\n"
            "```bash\n"
            'rm -rf "$TARGET"\n'
            "```\n\n"
            "The scanner pattern is `fs\\.rmSync\\(` and exists only to detect unsafe code.\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", self.codes(result))
        self.assertTrue(result.passed)

    def test_symlinked_supported_source_is_an_unacknowledgeable_error(self) -> None:
        skill = write_skill(self.candidate, "symlinked-source")
        outside = self.base / "outside.py"
        outside.write_text("print('outside')\n", encoding="utf-8")
        (skill / "linked.py").symlink_to(outside)
        result = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("SOURCE_SCAN_SKIPPED_SYMLINK",),
        )
        matches = [
            item for item in result.diagnostics if item.code == "SOURCE_SCAN_SKIPPED_SYMLINK"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_unreadable_supported_source_is_an_unacknowledgeable_error(self) -> None:
        skill = write_skill(self.candidate, "unreadable-source")
        (skill / "broken.py").write_bytes(b"\xff\xfe\x00")
        result = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("SOURCE_SCAN_INCOMPLETE",),
        )
        matches = [
            item for item in result.diagnostics if item.code == "SOURCE_SCAN_INCOMPLETE"
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_source_scan_excludes_test_vendor_cache_and_symlink_but_fails_on_oversize(self) -> None:
        skill = write_skill(self.candidate, "bounded-source-scan")
        unsafe_source = "import os\n\nos.remove('/tmp/example-target')\n"
        for directory in ("tests", "fixtures", "vendor", "cache"):
            target_dir = skill / directory
            target_dir.mkdir()
            (target_dir / "unsafe.py").write_text(unsafe_source, encoding="utf-8")

        outside = self.base / "outside.py"
        outside.write_text(unsafe_source, encoding="utf-8")
        (skill / "linked.py").symlink_to(outside)
        (skill / "oversize.py").write_text(
            "#" + ("x" * AUDIT.MAX_SOURCE_BYTES) + "\n" + unsafe_source,
            encoding="utf-8",
        )

        result = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("SOURCE_SCAN_SKIPPED_SIZE", "SOURCE_SCAN_SKIPPED_SYMLINK"),
        )
        codes = self.codes(result)
        self.assertNotIn("RISK_SIGNAL_DESTRUCTIVE_ACTION", codes)
        self.assertIn("SOURCE_SCAN_SKIPPED_SYMLINK", codes)
        self.assertIn("SOURCE_SCAN_SKIPPED_SIZE", codes)
        size_matches = [
            item for item in result.diagnostics if item.code == "SOURCE_SCAN_SKIPPED_SIZE"
        ]
        self.assertEqual(len(size_matches), 1)
        self.assertEqual(size_matches[0].severity, "error")
        self.assertFalse(result.passed)

    def test_destructive_none_declaration_conflict_is_error(self) -> None:
        skill = write_skill(
            self.candidate,
            "contradictory-cleaner",
            governance={
                "network": "none",
                "external-writes": "none",
                "destructive-actions": "none",
                "credentials": "none",
            },
        )
        (skill / "cleanup.js").write_text(
            "const fs = require('fs');\nfs.rmSync('/tmp/target');\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("RISK_DECLARATION_CONFLICT",),
        )
        conflicts = [
            item for item in result.diagnostics if item.code == "RISK_DECLARATION_CONFLICT"
        ]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, "error")
        self.assertFalse(result.passed)

    def test_invalid_governance_declaration_fails(self) -> None:
        write_skill(
            self.candidate,
            "invalid-declaration",
            governance={"network": "always"},
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertFalse(result.passed)
        self.assertIn("INVALID_GOVERNANCE_DECLARATION", self.codes(result))

    def test_regex_catalog_is_not_treated_as_executable_risk(self) -> None:
        skill = write_skill(
            self.candidate,
            "regex-catalog",
            governance={
                "network": "none",
                "external-writes": "none",
                "destructive-actions": "none",
                "credentials": "none",
            },
        )
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text(
            "import re\n\nNETWORK_PATTERN = re.compile(r'requests\\.get\\(')\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertTrue(result.passed)
        self.assertNotIn("RISK_SIGNAL_NETWORK", self.codes(result))

    def test_dependency_manifests_and_remote_tool_dependencies_are_reported(self) -> None:
        skill = write_skill(self.candidate, "dependency-helper")
        (skill / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
        (skill / "scripts").mkdir()
        (skill / "scripts" / "run.py").write_text("import requests\n", encoding="utf-8")
        (skill / "agents" / "openai.yaml").write_text(
            "dependencies:\n"
            "  tools:\n"
            "    - type: mcp\n"
            "      value: example-tool\n"
            "      url: https://example.invalid/mcp\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        codes = self.codes(result)
        self.assertFalse(result.passed)
        self.assertIn("DEPENDENCY_MANIFEST", codes)
        self.assertIn("TOOL_DEPENDENCY_DECLARED", codes)
        self.assertIn("PYTHON_EXTERNAL_IMPORT", codes)
        self.assertIn("RISK_SIGNAL_NETWORK", codes)
        self.assertNotIn("RUNTIME_DEPENDENCY_DECLARATION_MISSING", codes)

    def test_warning_acknowledgement_is_exact_and_required_for_pass(self) -> None:
        skill = write_skill(
            self.candidate,
            "network-reader",
            governance={
                "network": "required",
                "external-writes": "none",
                "destructive-actions": "none",
                "credentials": "none",
            },
        )
        (skill / "run.sh").write_text("curl https://example.invalid\n", encoding="utf-8")

        unacknowledged = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        wrong_case = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("risk_signal_network",),
        )
        acknowledged = AUDIT.audit(
            "pre-install",
            candidate_roots=(self.candidate,),
            installed_roots=(self.installed,),
            ack_warnings=("RISK_SIGNAL_NETWORK",),
        )

        self.assertFalse(unacknowledged.passed)
        self.assertEqual(unacknowledged.unacknowledged_warning_count, 1)
        self.assertFalse(wrong_case.passed)
        self.assertEqual(wrong_case.acknowledged_warning_codes, ())
        self.assertTrue(acknowledged.passed)
        self.assertEqual(acknowledged.acknowledged_warning_codes, ("RISK_SIGNAL_NETWORK",))
        self.assertEqual(acknowledged.unacknowledged_warning_count, 0)
        payload = acknowledged.as_json()
        self.assertEqual(payload["summary"]["acknowledged_warnings"], 1)
        self.assertEqual(payload["summary"]["unacknowledged_warnings"], 0)
        self.assertEqual(payload["acknowledged_warning_codes"], ["RISK_SIGNAL_NETWORK"])

    def test_pre_and_post_cli_accept_repeatable_warning_acknowledgements(self) -> None:
        candidate_skill = write_skill(
            self.candidate,
            "network-writer-cli",
            governance={
                "network": "required",
                "external-writes": "required",
                "destructive-actions": "none",
                "credentials": "none",
            },
        )
        (candidate_skill / "run.py").write_text(
            "import requests\n"
            "from pathlib import Path\n\n"
            "requests.get('https://example.invalid')\n"
            "Path('/tmp/result').write_text('result')\n",
            encoding="utf-8",
        )
        (candidate_skill / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")

        pre_output = io.StringIO()
        with redirect_stdout(pre_output):
            pre_exit = AUDIT.main(
                [
                    "pre-install",
                    str(self.candidate),
                    "--installed-root",
                    str(self.installed),
                    "--ack-warning",
                    "RISK_SIGNAL_NETWORK",
                    "--ack-warning",
                    "RISK_SIGNAL_EXTERNAL_WRITE",
                    "--format",
                    "json",
                ]
            )
        pre_payload = json.loads(pre_output.getvalue())
        self.assertEqual(pre_exit, 0)
        self.assertTrue(pre_payload["pass"])
        self.assertEqual(pre_payload["summary"]["unacknowledged_warnings"], 0)

        write_skill(self.installed, "broad-installed", "Any visual design task must always use this Skill.")
        post_output = io.StringIO()
        with redirect_stdout(post_output):
            post_exit = AUDIT.main(
                [
                    "post-install",
                    "--root",
                    str(self.installed),
                    "--ack-warning",
                    "BROAD_TRIGGER_ALL_DESIGN",
                    "--format",
                    "json",
                ]
            )
        post_payload = json.loads(post_output.getvalue())
        self.assertEqual(post_exit, 0)
        self.assertTrue(post_payload["pass"])
        self.assertEqual(
            post_payload["acknowledged_warning_codes"], ["BROAD_TRIGGER_ALL_DESIGN"]
        )

    def test_text_output_identifies_acknowledged_and_unacknowledged_warnings(self) -> None:
        write_skill(self.installed, "broad-installed", "Any visual design task must always use this Skill.")
        result = AUDIT.audit(
            "post-install",
            installed_roots=(self.installed,),
            ack_warnings=("BROAD_TRIGGER_ALL_DESIGN",),
        )
        rendered = AUDIT.render_text(result)
        self.assertIn("0 unacknowledged", rendered)
        self.assertIn("Acknowledged warning codes: BROAD_TRIGGER_ALL_DESIGN", rendered)
        self.assertIn("[ACKNOWLEDGED]", rendered)

    def test_malformed_tool_dependency_fails(self) -> None:
        skill = write_skill(self.candidate, "broken-tool-dependency")
        (skill / "agents" / "openai.yaml").write_text(
            "dependencies:\n  tools:\n    - type: shell\n      value: unsafe\n",
            encoding="utf-8",
        )
        result = AUDIT.audit(
            "pre-install", candidate_roots=(self.candidate,), installed_roots=(self.installed,)
        )
        self.assertFalse(result.passed)
        self.assertIn("INVALID_TOOL_DEPENDENCY", self.codes(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
