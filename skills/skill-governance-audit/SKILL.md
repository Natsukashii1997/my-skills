---
name: skill-governance-audit
description: Audit a local Codex Skill package before activation or scan installed custom Skill roots for deterministic naming, trigger, invocation-policy, protected-role, dependency, and static capability-risk signals. Use when installing, updating, enabling, or reviewing Skills; it reports findings but does not install, rewrite, disable, or delete them.
metadata:
  governance:
    network: none
    external-writes: none
    destructive-actions: none
    credentials: none
    dependencies:
      - PyYAML
---

# Skill Governance Audit

Use the static auditor as a gate, not as a Skill workbench or package registry. It reads local Skill files and returns reproducible diagnostics; the primary workflow owns any installation or repair.

Resolve every `scripts/...` path below from this Skill directory, independent of the current project working directory.

## Before activation

Stage the candidate outside the active Skill roots, then run:

```bash
python3 scripts/audit_skills.py pre-install <candidate-directory> --format text
```

The command also compares the candidate with the current custom roots (`~/.codex/skills` and `~/.agents/skills`). For an intentional replacement, add `--allow-replace <exact-skill-name>`. This accepts one candidate replacing exactly one installed same-name package. If their folder names also match, an identical existing folder/name mismatch remains a visible warning requiring disposition; new mismatches, extra duplicates, and other package errors still fail.

Do not activate a candidate while the result is `FAIL`. Treat warnings as review items: explain their concrete scope, then decide whether the candidate description or policy needs a bounded correction. If a pre-install artifact cannot be inspected, return `BLOCKED: PREINSTALL_ARTIFACT_UNAVAILABLE` instead of treating an install command or repository name as evidence.

Warnings are fail-closed until explicitly acknowledged by exact code. After inspecting and recording the disposition, rerun with one repeatable argument per accepted code:

```bash
python3 scripts/audit_skills.py pre-install <candidate-directory> \
  --ack-warning RISK_SIGNAL_NETWORK \
  --format text
```

An acknowledgement does not remove the diagnostic. JSON and text output retain the warning and distinguish acknowledged from unacknowledged findings. Error diagnostics cannot be acknowledged into a pass. Candidate destructive-action signals, declarations that contradict a matching signal, and supported source files above the scan-size limit are errors.

The scanner distinguishes inline SQL capabilities explicitly prohibited in reference prose from executable SQL. Pre-install recognizes quoted `rm -f` of the sole file created by argument-free `mktemp`, with no detected variable mutation or command rebinding. A recursive shell cleanup requires `ROOT=$(mktemp -d)` immediately followed by `readonly ROOT`, then exact `rm -rf -- "$ROOT"`; reassignment, dynamic setters, fake or out-of-scope creation, extra targets and unknown root uses remain errors. It also recognizes one Node ESM form: canonical `fs`/`os`/`path` builtin imports, a `const` directory from `fs.mkdtempSync(path.join(os.tmpdir(), 'literal-prefix-'))`, and `fs.rmSync` of that exact directory with literal recursive/force options. The creator must remain in lexical scope and protected bindings must have only recognized uses. Dynamic or unknown module loading, namespace aliases, shadowing, mutation, extra expressions or targets, and unproven ownership remain errors. These bounded static heuristics do not replace reading the source or testing its behavior.

Pre-install also inventories dependency manifests, external Python/Node imports, declared MCP tools, and high-signal source patterns for network access, external writes, destructive actions, credential access, and possible hardcoded secrets. Destructive patterns cover selected Python, shell, Node `fs`, Deno, and PowerShell calls. The scanner considers supported source types throughout the Skill directory; test/fixture/vendor/cache paths remain excluded, except that a test-named source directly referenced by `SKILL.md` stays in scope. When any dependency or risk diagnostic appears, read [references/risk-declarations.md](references/risk-declarations.md) before proposing a declaration or disposition. A declaration documents intended capability; it never suppresses a source signal, grants permission, or proves safety.

## After installation or policy edits

Run:

```bash
python3 scripts/audit_skills.py post-install --format text
```

Use `--format json` when another validator will consume the result. Use repeatable `--root <directory>` or `--installed-root <directory>` arguments only when the active roots differ from the defaults. If reviewed warnings remain, rerun with repeatable `--ack-warning <exact-code>`; an unacknowledged warning keeps the result and exit status at `FAIL` / `1`.

Post-install repeats the structural checks and scans supported executable source for high-signal Node `fs`, Deno, and PowerShell deletion calls. It treats a simple same-source create-then-delete sequence for one file or directory as bounded cleanup; this is only a narrow noise-reduction heuristic, not proof that the path or surrounding behavior is safe. The fuller dependency, network, external-write, credential, secret, Python, and shell inventory remains a pre-install gate.

The auditor checks basic frontmatter/OpenAI policy validity, duplicate names, protected visual-role ownership, catch-all trigger language, unscoped global visual mandates, and structured or textual explicit-only invocation policy. Wording such as “only/after the user explicitly selects it” requires `policy.allow_implicit_invocation: false` in both candidate and installed Skills; a same-sentence approved visual-SOP route is not treated as an exclusive user-only gate. `visual-app-development-sop` may assign `frontend-design` and `design-taste-frontend` their real protected roles only in the same local statement; the SOP cannot claim those roles for itself. Static scanning does not execute code and cannot prove that instructions are correct, safe, useful, source-authentic, or harmless; those remain human/agent review questions.

A user-approval condition specifically on changing model, reasoning, or service settings does not require disabling automatic Skill discovery. An actual Skill invocation gate elsewhere still applies.

## Completion criterion

Finish only when the exact candidate or installed files were scanned, every error is resolved, every warning is explicitly dispositioned, and the command plus exit status are recorded. Never mutate a Skill merely to make the report green without preserving its intended capability.
