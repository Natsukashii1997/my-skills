#!/usr/bin/env python3
"""Pre-install ESM mkdtemp cleanup: accepted idiom and fail-closed boundaries."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_audit_skills import AUDIT, add_protected_owners, write_skill


IMPORTS = "import fs from 'node:fs';\nimport os from 'node:os';\nimport path from 'node:path';\n"
CREATE = "const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-run-'));\n"
DELETE = "fs.rmSync(tmpDir, { recursive: true, force: true });\n"


class CleanupAuditFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.installed = self.base / 'installed'
        add_protected_owners(self.installed)
        self.candidate = self.base / 'candidate'
        self.skill = write_skill(self.candidate, 'node-cleanup')
        self.script = self.skill / 'cleanup.mjs'

    def tearDown(self):
        self.temp.cleanup()

    def inspect(self, source):
        self.script.write_text(source)
        result = AUDIT.audit('pre-install', candidate_roots=(self.candidate,),
                             installed_roots=(self.installed,),
                             ack_warnings=('RISK_SIGNAL_DESTRUCTIVE_ACTION',))
        return result, [d for d in result.diagnostics if d.code == 'RISK_SIGNAL_DESTRUCTIVE_ACTION']

    def assert_rejected(self, cases):
        for label, source in cases.items():
            with self.subTest(case=label):
                result, findings = self.inspect(source)
                self.assertTrue(findings, label)
                self.assertTrue(all(d.severity == 'error' for d in findings))
                self.assertFalse(result.passed, 'errors must not be acknowledged into pass')

class NodeCleanupBoundaryTests(CleanupAuditFixture):
    def test_exact_esm_owned_cleanup_and_closure_are_accepted(self):
        cases = (
            IMPORTS + CREATE + DELETE,
            IMPORTS.replace('import fs', 'import * as fs') + CREATE + DELETE,
            IMPORTS + 'async function main() {\n' + CREATE
            + 'let cleaned = false;\nconst cleanup = () => {\nif (cleaned) return;\n'
            + DELETE + 'cleaned = true;\n};\nprocess.once("exit", cleanup);\n}\nmain();\n',
            IMPORTS + CREATE + DELETE.replace('recursive: true, force: true', 'force: true, recursive: true,'),
        )
        for source in cases:
            with self.subTest(source=source):
                result, findings = self.inspect(source)
                self.assertEqual([], findings)
                self.assertEqual(0, result.error_count)
                self.assertTrue(result.passed)

    def test_creator_result_must_be_exact_exclusive_expression(self):
        cases = {
            'user-path': "const tmpDir = userInput;\n",
            'fixed-mkdir': "const tmpDir = path.join(os.tmpdir(), 'fixed');\nfs.mkdirSync(tmpDir);\n",
            'fallback': CREATE.replace('));', ')) || userInput;'),
            'comma-operator': "const tmpDir = (fs.mkdtempSync(path.join(os.tmpdir(), 'safe-')), userInput);\n",
            'path-arithmetic': CREATE.replace('));', ')) + "/../user-data";'),
            'property-lookup': CREATE.replace('));', ')).other;'),
            'untrusted-factory': CREATE.replace('fs.mkdtempSync', 'fake.mkdtempSync'),
            'prefix-expression': CREATE.replace("'skill-run-'", 'userInput'),
            'untrusted-creator-argument': CREATE.replace('os.tmpdir()', 'userInput'),
            'extra-creator-argument': CREATE.replace("'skill-run-'))", "'skill-run-')), userInput"),
        }
        self.assert_rejected({k: IMPORTS + v + DELETE for k, v in cases.items()})

    def test_import_provenance_cannot_be_spoofed_or_aliased(self):
        cases = {
            'missing-fs-import': IMPORTS.replace("import fs from 'node:fs';\n", ''),
            'fake-module': IMPORTS.replace("'node:fs'", "'./fake-fs.js'"),
            'comment-import': IMPORTS.replace("import fs from 'node:fs';", "// import fs from 'node:fs';"),
            'string-import': IMPORTS.replace("import fs from 'node:fs';", 'const note = "import fs from \'node:fs\';";'),
            'commonjs-unproven': IMPORTS.replace("import fs from 'node:fs';", "const fs = require('node:fs');"),
            'extra-fs-alias': IMPORTS + "import otherFs from 'node:fs';\notherFs.mkdtempSync = () => userInput;\n",
            'require-alias': IMPORTS + "const otherFs = require('node:fs');\notherFs.mkdtempSync = () => userInput;\n",
            'path-alias': IMPORTS + "import otherPath from 'node:path';\notherPath.join = () => userInput;\n",
            'dynamic-concat-alias': IMPORTS + "const other = await import('node:' + 'fs');\nother.default.mkdtempSync = () => userInput;\n",
            'escaped-module-alias': IMPORTS + "const other = await import('node:\\u0066s');\nother.default.mkdtempSync = () => userInput;\n",
            'builtin-loader-alias': IMPORTS + "const other = process.getBuiltinModule('fs');\nother.mkdtempSync = () => userInput;\n",
            'computed-builtin-loader': IMPORTS + "const other = process['get' + 'BuiltinModule']('fs');\nother.mkdtempSync = () => userInput;\n",
            'process-escape': IMPORTS + "const otherProcess = process;\nconst other = otherProcess.getBuiltinModule('fs');\nother.mkdtempSync = () => userInput;\n",
            'unknown-static-module': IMPORTS + "import './mutate-builtins.mjs';\n",
            'module-create-require': IMPORTS + "import {createRequire} from 'node:module';\nconst loader = createRequire(import.meta.url);\nloader('fs').mkdtempSync = () => userInput;\n",
            'constructor-loader': IMPORTS + "const getGlobal = (() => {}).constructor('return globalThis');\ngetGlobal().process.getBuiltinModule('fs').mkdtempSync = () => userInput;\n",
        }
        self.assert_rejected({k: v + CREATE + DELETE for k, v in cases.items()})

    def test_bindings_reject_assignment_shadowing_and_mutation(self):
        self.assert_rejected({
            'let-reassignment': IMPORTS + CREATE.replace('const tmpDir', 'let tmpDir') + 'tmpDir = userInput;\n' + DELETE,
            'nested-target-parameter': IMPORTS + CREATE + 'function cleanup(tmpDir) {\n' + DELETE + '}\ncleanup(userInput);\n',
            'nested-fs-parameter': IMPORTS + 'function main(fs) {\n' + CREATE + DELETE + '}\n',
            'nested-path-parameter': IMPORTS + 'function main(path) {\n' + CREATE + DELETE + '}\n',
            'destructuring-shadow': IMPORTS + CREATE + 'function cleanup({tmpDir}) {\n' + DELETE + '}\n',
            'loop-shadow': IMPORTS + CREATE + 'for (const tmpDir of userPaths) {\n' + DELETE + '}\n',
            'catch-shadow': IMPORTS + CREATE + 'try {} catch(tmpDir) {\n' + DELETE + '}\n',
            'late-mutation': IMPORTS + CREATE + 'const cleanup = () => {\n' + DELETE + '};\nfs.mkdtempSync = () => userInput;\n',
            'object-assign': IMPORTS + 'Object.assign(fs, replacement);\n' + CREATE + DELETE,
            'define-getter': IMPORTS + "fs.__defineGetter__('mkdtempSync', malicious);\n" + CREATE + DELETE,
            'computed-mutation': IMPORTS + "fs['mkdtempSync'] = malicious;\n" + CREATE + DELETE,
            'method-alias': IMPORTS + 'const remove = fs.rmSync;\n' + CREATE + DELETE,
            'namespace-escape': IMPORTS + 'mutate(fs);\n' + CREATE + DELETE,
            'target-escape': IMPORTS + CREATE + 'rewrite(tmpDir);\n' + DELETE,
        })

    def test_extra_targets_or_option_expressions_still_fail(self):
        cases = {
            'different-target': DELETE.replace('tmpDir,', 'userInput,'),
            'expression-target': DELETE.replace('tmpDir,', '(tmpDir, userInput),'),
            'array-target': DELETE.replace('tmpDir,', '[tmpDir, userInput],'),
            'extra-argument': DELETE.replace(' });', ' }, userInput);'),
            'option-spread': DELETE.replace('recursive: true, force: true', '...options'),
            'option-getter': DELETE.replace('recursive: true', 'get recursive() { mutate(fs); return true; }'),
            'second-delete': DELETE + "fs.rmSync(userInput, { recursive: true, force: true });\n",
            'unlink-not-directory-cleanup': DELETE.replace('rmSync', 'unlinkSync'),
        }
        self.assert_rejected({k: IMPORTS + CREATE + v for k, v in cases.items()})

    def test_creator_must_remain_in_lexical_scope(self):
        self.assert_rejected({
            'unrelated-function': IMPORTS + 'function allocate() {\n' + CREATE + '}\n' + DELETE,
            'sibling-block': IMPORTS + '{\n' + CREATE + '}\n{\n' + DELETE + '}\n',
            'creator-in-child-scope': IMPORTS + 'function main() {\n{\n' + CREATE + '}\n' + DELETE + '}\n',
            'creator-after-delete': IMPORTS + DELETE + CREATE,
        })

    def test_template_and_dynamic_mutation_are_not_hidden(self):
        self.assert_rejected({
            'template-fs': IMPORTS + '`value ${fs.mkdtempSync = () => userInput}`;\n' + CREATE + DELETE,
            'template-path': IMPORTS + '`value ${path.join = () => userInput}`;\n' + CREATE + DELETE,
            'template-target': IMPORTS + CREATE + '`value ${((tmpDir) => { fs.rmSync(tmpDir); })(userInput)}`;\n' + DELETE,
            'eval': IMPORTS + 'eval(userInput);\n' + CREATE + DELETE,
            'function-constructor': IMPORTS + 'new Function(userInput)();\n' + CREATE + DELETE,
        })

    def test_cli_preserves_error_after_acknowledgement(self):
        self.script.write_text(IMPORTS + CREATE + DELETE.replace('tmpDir,', 'userInput,'))
        result = subprocess.run([
            os.sys.executable, str(AUDIT.__file__), 'pre-install', str(self.candidate),
            '--installed-root', str(self.installed), '--format', 'json',
            '--ack-warning', 'RISK_SIGNAL_DESTRUCTIVE_ACTION',
        ], capture_output=True, text=True, check=False)
        report = json.loads(result.stdout)
        self.assertEqual(1, result.returncode)
        self.assertFalse(report['pass'])
        self.assertGreater(report['summary']['errors'], 0)

    def test_real_owned_cleanup_preserves_neighbor_file(self):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the bounded runtime smoke test')
        scratch = self.base / 'runtime'
        scratch.mkdir()
        neighbor = scratch / 'user-sentinel.txt'
        neighbor.write_text('keep-me')
        source = IMPORTS + CREATE + "fs.writeFileSync(path.join(tmpDir, 'generated.txt'), 'generated');\n" + DELETE
        self.script.write_text(source)
        result = subprocess.run([node, str(self.script)], env={**os.environ, 'TMPDIR': str(scratch)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('keep-me', neighbor.read_text())
        self.assertEqual([neighbor], list(scratch.iterdir()))


class ShellDirectoryCleanupBoundaryTests(CleanupAuditFixture):
    def setUp(self):
        super().setUp()
        self.script = self.skill / 'cleanup.sh'

    def test_shell_readonly_owned_root_and_nested_cleanup_are_accepted(self):
        create = 'TEMP_ROOT=$(mktemp -d)\nreadonly TEMP_ROOT\n'
        delete = 'rm -rf -- "$TEMP_ROOT"\n'
        for source in (
            create + delete,
            'if [[ -f "$INPUT" ]]; then\n' + create + 'cleanup() {\n' + delete + '}\ntrap cleanup EXIT\nfi\n',
            create + 'DEST="$TEMP_ROOT/generated"\nmkdir "$DEST"\n' + delete,
        ):
            with self.subTest(source=source):
                result, findings = self.inspect(source)
                self.assertEqual([], findings)
                self.assertEqual(0, result.error_count)

    def test_shell_arbitrary_targets_rebinding_and_fake_ownership_fail(self):
        create = 'TEMP_ROOT=$(mktemp -d)\nreadonly TEMP_ROOT\n'
        delete = 'rm -rf -- "$TEMP_ROOT"\n'
        self.assert_rejected({
            'user-input': create.replace('$(mktemp -d)', '"$INPUT"') + delete,
            'missing-readonly': create.replace('readonly TEMP_ROOT\n', '') + delete,
            'mktemp-file': create.replace('mktemp -d', 'mktemp') + delete,
            'mktemp-unsafe': create.replace('mktemp -d', 'mktemp -u') + delete,
            'late-rebinding': create + 'cleanup() {\n' + delete + '}\nTEMP_ROOT="$INPUT"\ntrap cleanup EXIT\n',
            'extra-target': create + delete.replace('"$TEMP_ROOT"', '"$TEMP_ROOT" "$INPUT"'),
            'unquoted': create + delete.replace('"$TEMP_ROOT"', '$TEMP_ROOT'),
            'missing-option-separator': create + delete.replace(' -- ', ' '),
            'local-shadow': create + 'cleanup() {\nlocal TEMP_ROOT="$INPUT"\n' + delete + '}\n',
            'dynamic-read': create + 'read TEMP_ROOT\n' + delete,
            'dynamic-eval': create + 'eval "$INPUT"\n' + delete,
            'sourced-mutation': create + 'source "$INPUT"\n' + delete,
            'mktemp-rebinding': 'mktemp() { printf /tmp/user-owned; }\n' + create + delete,
            'readonly-rebinding': 'readonly() { :; }\n' + create + delete,
            'path-rebinding': 'PATH="$INPUT"\n' + create + delete,
            'command-hash-rebinding': 'hash -p "$UNTRUSTED_PROGRAM" mktemp\n' + create + delete,
            'builtin-rebinding': 'enable -f "$UNTRUSTED_LIBRARY" mktemp\n' + create + delete,
            'zero-iteration-loop-creator': 'for item in; do\n' + create + 'done\n' + delete,
            'nonmatching-case-creator': 'case "$INPUT" in\nyes)\n' + create + ';;\nesac\n' + delete,
            'subshell-creator': '(\n' + create + ')\n' + delete,
            'function-creator': 'allocate() {\n' + create + '}\n' + delete,
            'conditional-creator-outside-cleanup': 'if false; then\n' + create + 'fi\n' + delete,
            'heredoc-fake-creator': "cat <<'EXAMPLE'\n" + create + 'EXAMPLE\n' + delete,
            'multiline-string-fake-creator': "TEXT='\n" + create + "'\n" + delete,
        })

    def test_real_shell_owned_cleanup_preserves_neighbor_file(self):
        scratch = self.base / 'shell-runtime'
        scratch.mkdir()
        neighbor = scratch / 'user-sentinel.txt'
        neighbor.write_text('keep-me')
        self.script.write_text('set -eu\nTEMP_ROOT=$(mktemp -d)\nreadonly TEMP_ROOT\n'
                               'touch "$TEMP_ROOT/generated"\nrm -rf -- "$TEMP_ROOT"\n')
        result = subprocess.run(['bash', str(self.script)], env={**os.environ, 'TMPDIR': str(scratch)},
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('keep-me', neighbor.read_text())
        self.assertEqual([neighbor], list(scratch.iterdir()))


if __name__ == '__main__':
    unittest.main()
