# Dependency and Risk Declarations

Use this reference only after the pre-install auditor reports a dependency or capability-risk diagnostic. These declarations are an admission of intended capability, not an authorization or safety certificate.

## Candidate declaration

Put optional governance metadata in the candidate `SKILL.md` frontmatter:

```yaml
metadata:
  governance:
    network: required
    external-writes: optional
    destructive-actions: none
    credentials: optional
    dependencies:
      - requests
```

Allowed values:

| Key | Values | Meaning |
| --- | --- | --- |
| `network` | `none`, `optional`, `required` | Whether execution is intended to contact a remote system. |
| `external-writes` | `none`, `optional`, `required` | Whether execution may create or change files, messages, deployments, or other objects outside the response. |
| `destructive-actions` | `none`, `guarded` | Whether deletion or another difficult-to-recover action is in scope. `guarded` still requires exact-target checks and user authority. |
| `credentials` | `none`, `optional`, `required` | Whether execution needs a credential source. Never place the credential value in this metadata. |
| `dependencies` | list of strings | Runtime packages or executables the candidate expects. This does not install or verify them. |

Declare MCP tool dependencies in the supported `agents/openai.yaml` shape:

```yaml
dependencies:
  tools:
    - type: "mcp"
      value: "example-server"
      description: "Why the Skill needs this server"
```

Do not add a declaration merely to make a warning disappear. The scanner always retains the underlying signal. If a declared value is `none` while a matching signal remains, the auditor emits the error `RISK_DECLARATION_CONFLICT`. Resolve it by inspecting the exact source context: remove an unnecessary capability, narrow the instruction, or correct the declaration.

## Warning disposition

For each warning, record:

1. the file and matched behavior;
2. why the capability is necessary for the Skill's narrow purpose;
3. the authority boundary and exact target scope;
4. the user confirmation, dry-run, validation, or recovery guard required before mutation;
5. how credentials are obtained without embedding, logging, exporting, or returning them.

A warning can be a false positive, especially when a Skill explains a forbidden operation or contains illustrative code. Explain that context; do not silently suppress the diagnostic.

After that disposition is recorded, acknowledge each accepted warning by its exact, case-sensitive code:

```bash
python3 scripts/audit_skills.py pre-install <candidate-directory> \
  --ack-warning RISK_SIGNAL_NETWORK \
  --ack-warning RISK_SIGNAL_EXTERNAL_WRITE
```

The flag is repeatable and code-scoped: it acknowledges every warning carrying that exact code in the current result. A typo or stale code acknowledges nothing. The report still contains every signal, declaration, and conflict; acknowledgement changes only whether a warning remains fail-closed. Errors—including candidate destructive-action signals, declaration conflicts, and oversized supported source—remain failures regardless of acknowledgement.

## Static scan boundary

The pre-install scan is read-only. It reads the candidate `SKILL.md`, supported source files anywhere under the Skill directory, root dependency manifests, and structured `agents/openai.yaml` tool dependencies. Its destructive-action catalog includes selected Python and shell operations plus Node `fs.rm*`/`fs.unlink*`/`fs.rmdir*`, Deno removal, and PowerShell `Remove-Item`. It does not run candidate code, install packages, contact servers, or mutate the candidate.

The scanner intentionally skips test/fixture, vendored/cache directories, unreferenced test-named source, symlinks, and unsupported file types. A test-named source directly referenced by `SKILL.md` remains in scope. A supported source file larger than the fixed limit is not scanned and causes a fail-closed error. The scanner can miss dynamic imports, generated or obfuscated code, aliasing and destructuring that evade its patterns, indirect shell execution, tool-side effects, transitive dependency behavior, runtime permission escalation, and behavior described in unscanned assets or references. Pattern matches can also be non-executable prose or examples.

Post-install uses the same structural and explicit-policy checks, plus a narrower executable-source check for the Node, Deno, and PowerShell deletion signals above. It does not repeat the candidate's full dependency, network, external-write, credential, secret, Python, or shell inventory. Its simple same-source create-then-delete exception reduces noise for locally generated temporary files/directories, but does not validate path flow or establish safety.

Therefore:

- a signal means “inspect this capability and its safeguards,” not “malicious”;
- no signal means “nothing matched this bounded scanner,” not “safe”;
- a declaration means “the author claims this is intended,” not “verified”;
- dependency discovery does not establish provenance, integrity, availability, license compatibility, or vulnerability status.
