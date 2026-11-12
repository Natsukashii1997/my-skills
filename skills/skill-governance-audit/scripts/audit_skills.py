#!/usr/bin/env python3
"""Deterministic, read-only governance checks for local Codex Skills."""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import stat
import sys
import tokenize
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import yaml
except ImportError as exc:  # pragma: no cover - environment failure path
    raise SystemExit(
        "PyYAML is required to validate Skill YAML. Run this command with the Codex "
        "workspace Python runtime or install PyYAML for the selected Python."
    ) from exc


SCHEMA_VERSION = 2
DEFAULT_ROOTS = (Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills")
SKIP_PARTS = {
    ".git",
    ".system",
    "__pycache__",
    "cache",
    "fixtures",
    "node_modules",
    "plugins",
    "test",
    "tests",
    "vendor",
}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SOURCE_SUFFIXES = {
    "",
    ".bash",
    ".cjs",
    ".js",
    ".mjs",
    ".ps1",
    ".py",
    ".rb",
    ".sh",
    ".ts",
    ".tsx",
    ".zsh",
}
REFERENCE_SOURCE_SUFFIXES = {".md", ".txt"}
DEPENDENCY_MANIFESTS = {
    "Pipfile",
    "environment.yml",
    "package-lock.json",
    "package.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}
MAX_SOURCE_BYTES = 2_000_000

RISK_DECLARATION_VALUES = {
    "network": {"none", "optional", "required"},
    "external-writes": {"none", "optional", "required"},
    "destructive-actions": {"none", "guarded"},
    "credentials": {"none", "optional", "required"},
}

CROSS_RUNTIME_DESTRUCTIVE_PATTERNS = (
    re.compile(
        r"\bfs(?:\s*\.\s*promises)?\s*\.\s*"
        r"(?:rm|rmSync|unlink|unlinkSync|rmdir|rmdirSync)\s*\("
    ),
    re.compile(r"\bDeno\s*\.\s*(?:remove|removeSync)\s*\("),
    re.compile(
        r"(?mi)^\s*(?:&\s*)?(?:Microsoft\.PowerShell\.Management\\)?Remove-Item\b"
    ),
)


RISK_SIGNAL_PATTERNS = {
    "network": (
        re.compile(r"(?m)^\s*(?:sudo\s+)?(?:curl|wget)\s+"),
        re.compile(r"\brequests\.(?:get|post|put|patch|delete|request)\s*\("),
        re.compile(r"\bhttpx\.(?:get|post|put|patch|delete|request|Client|AsyncClient)\b"),
        re.compile(r"\burllib\.request\.urlopen\s*\("),
        re.compile(r"\b(?:fetch|WebSocket)\s*\("),
        re.compile(r"\baxios\.(?:get|post|put|patch|delete|request)\s*\("),
        re.compile(
            r"\b(?:use|call|invoke|run)\b.{0,24}\b(?:web\.run|WebSearch)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\btools?\.(?:web__run|web\.run)\s*\("),
    ),
    "external-writes": (
        re.compile(r"\.write_(?:text|bytes)\s*\("),
        re.compile(r"\bopen\s*\([^\n]{0,160},\s*['\"](?:w|a|x|w\+|a\+)['\"]"),
        re.compile(r"\b(?:writeFile|writeFileSync|appendFile|appendFileSync|copyFile|rename)\s*\("),
        re.compile(r"\bshutil\.(?:copy|copy2|copytree|move)\s*\("),
        re.compile(r"(?m)^\s*git\s+push(?:\s|$)"),
        re.compile(
            r"(?m)^\s*(?:[$>]\s*)?(?:npm|pnpm|yarn|npx|vercel|netlify|wrangler|flyctl|gh|docker)\b"
            r"[^\n]*(?:deploy|publish|release)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:deploy|publish|release)\s*\(", re.IGNORECASE),
        re.compile(
            r"\blark-cli\b[^\n]{0,200}\s+(?:create|update|send|reply|upload|move|copy|publish|release)[a-z-]*\b",
            re.IGNORECASE,
        ),
    ),
    "destructive-actions": (
        re.compile(r"(?m)^\s*(?:sudo\s+)?rm\s+(?:-[^\n]*\s+)?[^\n]+$"),
        re.compile(
            r"(?m)^\s*(?:sudo\s+)?git\s+"
            r"(?:reset\s+--hard|clean\s+-[dfx]+|branch\s+-D|push\s+--force(?:-with-lease)?)\b"
        ),
        re.compile(r"\bshutil\.rmtree\s*\("),
        re.compile(r"\bos\.(?:remove|unlink|rmdir)\s*\("),
        re.compile(r"\.unlink\s*\("),
        *CROSS_RUNTIME_DESTRUCTIVE_PATTERNS,
        re.compile(r"\b(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", re.IGNORECASE),
        re.compile(
            r"\blark-cli\b[^\n]{0,200}\s+(?:delete|remove)[a-z-]*\b",
            re.IGNORECASE,
        ),
    ),
    "credentials": (
        re.compile(
            r"\b(?:API_KEY|APP_SECRET|ACCESS_TOKEN|AUTH_TOKEN|COOKIE|PASSWORD|CREDENTIALS?)\b"
        ),
        re.compile(r"\b(?:process\.env|os\.(?:environ|getenv))\b"),
        re.compile(r"(?:^|[\\/])\.env(?:\.|$|[\\/])", re.MULTILINE),
        re.compile(
            r"\b(?:require|provide|read|load|use|export|store)\b.{0,40}"
            r"\b(?:api[- ]?key|app[- ]?secret|access[- ]?token|auth[- ]?token|cookie|password|credentials?)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\baccess(?:es|ed|ing)?\s+(?:an?\s+|the\s+)?"
            r"(?:api[- ]?key|app[- ]?secret|access[- ]?token|auth[- ]?token|cookie|password|credentials?)\b",
            re.IGNORECASE,
        ),
        re.compile(r"\b(?:keychain|credential store|secret manager)\b", re.IGNORECASE),
    ),
}

HARDCODED_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b(?:api[_-]?key|app[_-]?secret|access[_-]?token|auth[_-]?token|password)\s*[:=]\s*"
        r"['\"](?P<assigned_secret>[^'\"\n]{16,})['\"]",
        re.IGNORECASE,
    ),
)

NODE_BUILTINS = {
    "assert",
    "buffer",
    "child_process",
    "crypto",
    "events",
    "fs",
    "http",
    "https",
    "module",
    "os",
    "path",
    "process",
    "querystring",
    "stream",
    "string_decoder",
    "timers",
    "tty",
    "url",
    "util",
    "v8",
    "vm",
    "worker_threads",
    "zlib",
}

PROTECTED_ROLES = {
    "visual_orchestrator": "visual-app-development-sop",
    "default_visual_author": "frontend-design",
    "visual_gate_reviewer": "design-taste-frontend",
}

ROLE_CLAIM_PATTERNS = {
    "visual_orchestrator": (
        re.compile(
            r"\b(?:(?:the|sole|only|default|primary|global|unique)\s+)?"
            r"visual(?:[- ]workflow)?\s+orchestrator\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bvisual\s+(?:workflow\s+owner|program\s+lead)\b", re.IGNORECASE),
        re.compile(r"(?:唯一|默认|全局|总|主要).{0,12}(?:视觉)?(?:编排|总控|工作流负责人)"),
        re.compile(r"(?:视觉流程总负责人|视觉总负责人)"),
    ),
    "default_visual_author": (
        re.compile(
            r"\b(?:(?:default|primary|global)\s+(?:visual\s+)?author"
            r"|(?:sole|only)\s+visual\s+author)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:(?:默认|全局|主要)[^，。；\n]{0,12}(?:视觉)?作者"
            r"|唯一[^，。；\n]{0,6}视觉作者"
            r"|(?:唯一|默认|全局|主要)[^，。；\n]{0,12}(?:设计主笔|主设计师))"
        ),
        re.compile(r"\b(?:visual\s+design\s+lead|lead\s+visual\s+designer)\b", re.IGNORECASE),
        re.compile(r"(?:视觉设计总负责人|首席视觉设计师)"),
    ),
    "visual_gate_reviewer": (
        re.compile(
            r"\b(?:sole|only|default|primary|global)\s+"
            r"(?:visual(?:[- ]taste)?\s+)?reviewer\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bT1a\s*/\s*T1b\s*/\s*T2\b", re.IGNORECASE),
        re.compile(r"(?:唯一|默认|全局|主要).{0,12}(?:视觉)?(?:审查者|评审者)"),
        re.compile(
            r"\b(?:final\s+visual\s+approver|visual\s+sign[- ]off\s+authority)\b",
            re.IGNORECASE,
        ),
        re.compile(r"(?:视觉终审权|视觉终审人|视觉最终拍板人)"),
    ),
}

BROAD_DESCRIPTION_PATTERNS = (
    (
        "BROAD_TRIGGER_ANYTHING",
        re.compile(r"\bmust\s+use\b.{0,100}\banything\b", re.IGNORECASE | re.DOTALL),
        "The description uses a MUST-USE catch-all around ‘anything’.",
    ),
    (
        "BROAD_TRIGGER_ALL_DESIGN",
        re.compile(
            r"\b(?:any|every|all)\s+(?:new\s+)?(?:visual\s+)?design(?:\s+(?:task|request|project|work))?"
            r".{0,60}\b(?:must|required|always|100%)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "The description claims mandatory coverage over all design work.",
    ),
    (
        "BROAD_TRIGGER_ALL_SURFACES",
        re.compile(
            r"\b(?:any|every|all)\s+(?:web|website|mobile|app|ui|ux|frontend)\s+"
            r"(?:task|request|project|work|design)s?\b",
            re.IGNORECASE,
        ),
        "The description claims an unbounded product-surface trigger.",
    ),
    (
        "BROAD_TRIGGER_ALL_DESIGN_ZH",
        re.compile(r"任何(?:新)?(?:视觉|UI|界面)?设计.{0,50}(?:必须|必走|一律|无一例外|100%)"),
        "技能描述把所有设计工作设为强制触发。",
    ),
)

GLOBAL_VISUAL_MANDATE_PATTERNS = (
    (
        "GLOBAL_VISUAL_MANDATE",
        re.compile(
            r"\b(?:any|every|all)\s+(?:new\s+)?(?:visual\s+)?design(?:\s+(?:task|request|project|work))?"
            r".{0,80}\b(?:must|required|always|without exception|100%)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        "The body contains an unscoped mandate over all visual-design work.",
    ),
    (
        "GLOBAL_VISUAL_MANDATE_ZH",
        re.compile(
            r"任何(?:会产出)?(?:新)?(?:视觉|UI|界面)?设计.{0,80}"
            r"(?:必须|必走|一律|无一例外|不豁免|100%)"
        ),
        "正文含有覆盖所有视觉设计工作的无范围强制规则。",
    ),
)

EXPLICIT_TEXT_RE = re.compile(
    r"\b(?:explicit[- ]only"
    r"|only\s+when\s+(?:the\s+user\s+)?explicitly\s+(?:invokes|requests|names|selects|chooses)"
    r"|(?:only\s+)?after\s+(?:the\s+user\s+)?explicitly\s+(?:invokes|requests|names|selects|chooses))\b"
    r"|仅当.{0,40}(?:显式|明确)(?:调用|指定|点名)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    message: str
    path: str
    skill: str | None = None
    line: int | None = None


@dataclass(frozen=True)
class DestructiveSourceMatch:
    """One executable-looking destructive operation found in a source file."""

    start: int
    call_end: int
    method: str
    runtime: str


@dataclass
class SkillRecord:
    skill_file: Path
    skill_dir: Path
    origin: str
    name: str
    description: str
    frontmatter: dict[str, Any]
    body: str
    openai_data: dict[str, Any] | None


@dataclass
class AuditResult:
    mode: str
    scanned_roots: list[str]
    skills_scanned: int
    diagnostics: list[Diagnostic]
    warning_acknowledgements: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(item.severity == "error" for item in self.diagnostics)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.diagnostics)

    @property
    def info_count(self) -> int:
        return sum(item.severity == "info" for item in self.diagnostics)

    @property
    def acknowledged_warning_codes(self) -> tuple[str, ...]:
        warning_codes = {item.code for item in self.diagnostics if item.severity == "warning"}
        return tuple(sorted(warning_codes.intersection(self.warning_acknowledgements)))

    @property
    def unacknowledged_warning_codes(self) -> tuple[str, ...]:
        warning_codes = {item.code for item in self.diagnostics if item.severity == "warning"}
        return tuple(sorted(warning_codes.difference(self.warning_acknowledgements)))

    @property
    def unused_warning_acknowledgements(self) -> tuple[str, ...]:
        warning_codes = {item.code for item in self.diagnostics if item.severity == "warning"}
        return tuple(sorted(set(self.warning_acknowledgements).difference(warning_codes)))

    @property
    def acknowledged_warning_count(self) -> int:
        acknowledged = set(self.acknowledged_warning_codes)
        return sum(
            item.severity == "warning" and item.code in acknowledged for item in self.diagnostics
        )

    @property
    def unacknowledged_warning_count(self) -> int:
        acknowledged = set(self.acknowledged_warning_codes)
        return sum(
            item.severity == "warning" and item.code not in acknowledged
            for item in self.diagnostics
        )

    @property
    def passed(self) -> bool:
        return self.error_count == 0 and self.unacknowledged_warning_count == 0

    def as_json(self) -> dict[str, Any]:
        severity_order = {"error": 0, "warning": 1, "info": 2}
        ordered = sorted(
            self.diagnostics,
            key=lambda item: (
                severity_order.get(item.severity, 3),
                item.code,
                item.path,
                item.line or 0,
            ),
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "pass": self.passed,
            "summary": {
                "skills_scanned": self.skills_scanned,
                "errors": self.error_count,
                "warnings": self.warning_count,
                "acknowledged_warnings": self.acknowledged_warning_count,
                "unacknowledged_warnings": self.unacknowledged_warning_count,
                "infos": self.info_count,
            },
            "scanned_roots": self.scanned_roots,
            "acknowledged_warning_codes": list(self.acknowledged_warning_codes),
            "unacknowledged_warning_codes": list(self.unacknowledged_warning_codes),
            "unused_warning_acknowledgements": list(self.unused_warning_acknowledgements),
            "diagnostics": [asdict(item) for item in ordered],
        }


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _severity(record: SkillRecord, candidate_error: bool = True) -> str:
    if record.origin == "candidate" and candidate_error:
        return "error"
    return "warning"


def _orchestrator_assigns_protected_owner(
    searchable: str, match: re.Match[str], owner: str
) -> bool:
    """Allow only a local, grammatical assignment of a protected role to its real owner."""
    line_start = searchable.rfind("\n", 0, match.start()) + 1
    line_end = searchable.find("\n", match.end())
    if line_end == -1:
        line_end = len(searchable)
    line = searchable[line_start:line_end]
    local_start = match.start() - line_start
    local_end = match.end() - line_start
    before = line[:local_start]
    after = line[local_end:]
    markdown_wrapper = r"(?:`{1,3}|\*{1,2}|_{1,2})?"
    owner_token = (
        rf"{markdown_wrapper}\$?{re.escape(owner)}\b{markdown_wrapper}"
    )
    connector = r"(?:is|serves\s+as|acts\s+as|remains|=|:|是|为|担任)"
    owner_before_role = re.search(
        rf"{owner_token}\s+{connector}\s+(?:the\s+)?[^,;.\n]{{0,64}}$",
        before,
        re.IGNORECASE,
    )
    role_before_owner = re.match(
        rf"[^,;.\n]{{0,64}}?\s*{connector}\s+(?:the\s+)?{owner_token}",
        after,
        re.IGNORECASE,
    )
    return owner_before_role is not None or role_before_owner is not None


def _is_negated_role_claim(searchable: str, match: re.Match[str]) -> bool:
    """Ignore an explicit boundary statement without hiding a later positive claim."""
    clause_start = max(
        searchable.rfind(token, 0, match.start()) for token in ("\n", ".", ";", "；", "。", "，", ",")
    ) + 1
    prefix = searchable[clause_start:match.start()][-96:]
    english_negation = re.search(
        r"\b(?:is|are|be|serve(?:s)?\s+as|act(?:s)?\s+as|claim(?:s)?\s+to\s+be)?\s*"
        r"(?:not(?!\s+only\b)|never|cannot|can't|must\s+not|does\s+not|do\s+not|"
        r"will\s+not|shall\s+not|without\s+claiming\s+to\s+be)\b[^,;.\n]{0,48}$",
        prefix,
        re.IGNORECASE,
    )
    chinese_negation = re.search(
        r"(?:不是|并非|不得|不能|不会|不作为|不担任|无权|禁止担任)[^，。；\n]{0,36}$",
        prefix,
    )
    return english_negation is not None or chinese_negation is not None


def _is_skipped(relative: Path) -> bool:
    return any(part in SKIP_PARTS or part.startswith(".") for part in relative.parts[:-1])


def _entry_identity(path: Path) -> Path:
    path = path.expanduser()
    # 目录别名可以合并；描述文件链接不能把技能的源码根替换为链接目标。
    if path.name == "SKILL.md":
        return path.parent.resolve() / path.name
    return path.resolve()


def discover_skill_files(root: Path, diagnostics: list[Diagnostic] | None = None) -> list[Path]:
    root = _entry_identity(root)
    if root.is_file():
        return [root] if root.name == "SKILL.md" else []
    if not root.is_dir():
        return []

    found: dict[str, Path] = {}
    search_roots = {root}

    def discovery_error(path: Path, exc: Exception) -> None:
        if diagnostics is None:
            raise exc
        diagnostics.append(Diagnostic(
            "error", "SKILL_DISCOVERY_ERROR",
            f"Cannot completely scan Skill entry: {exc.__class__.__name__}.", str(path),
        ))

    # link.sh 安装的是根目录下的技能目录链接。只显式跟随这一层，避免递归追链。
    try:
        for entry in sorted(root.iterdir()):
            if not entry.is_symlink() or _is_skipped(Path(entry.name) / "SKILL.md"):
                continue
            try:
                target = entry.resolve(strict=True)
                if target.is_dir():
                    search_roots.add(target)
            except (OSError, RuntimeError) as exc:
                discovery_error(entry, exc)
    except OSError as exc:
        discovery_error(root, exc)

    def walk_error(exc: OSError) -> None:
        discovery_error(Path(exc.filename or root), exc)

    for search_root in sorted(search_roots):
        for directory, dirs, files in os.walk(search_root, followlinks=False, onerror=walk_error):
            dirs[:] = [name for name in dirs if not _is_skipped(Path(name) / "SKILL.md")]
            if "SKILL.md" in files:
                skill_file = _entry_identity(Path(directory) / "SKILL.md")
                found[str(skill_file)] = skill_file
    return [found[key] for key in sorted(found)]


def _load_yaml_mapping(path: Path, raw: str, label: str) -> tuple[dict[str, Any] | None, Diagnostic | None]:
    try:
        value = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 1) if mark is not None else None
        return None, Diagnostic(
            "error",
            "INVALID_YAML",
            f"{label} is not valid YAML: {exc.__class__.__name__}.",
            str(path),
            line=line,
        )
    if not isinstance(value, dict):
        return None, Diagnostic(
            "error",
            "YAML_NOT_MAPPING",
            f"{label} must be a YAML mapping.",
            str(path),
        )
    return value, None


def parse_skill(skill_file: Path, origin: str) -> tuple[SkillRecord | None, list[Diagnostic]]:
    diagnostics: list[Diagnostic] = []
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return None, [
            Diagnostic("error", "UNREADABLE_SKILL", f"Cannot read SKILL.md: {exc}.", str(skill_file))
        ]

    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, [
            Diagnostic(
                "error",
                "MISSING_FRONTMATTER",
                "SKILL.md must begin with a YAML frontmatter delimiter.",
                str(skill_file),
                line=1,
            )
        ]

    end_index = next((index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end_index is None:
        return None, [
            Diagnostic(
                "error",
                "UNCLOSED_FRONTMATTER",
                "SKILL.md frontmatter has no closing delimiter.",
                str(skill_file),
                line=1,
            )
        ]

    frontmatter_raw = "".join(lines[1:end_index])
    frontmatter, yaml_error = _load_yaml_mapping(skill_file, frontmatter_raw, "SKILL.md frontmatter")
    if yaml_error:
        return None, [yaml_error]
    assert frontmatter is not None

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        diagnostics.append(
            Diagnostic("error", "MISSING_NAME", "Frontmatter needs a non-empty string name.", str(skill_file))
        )
        name = ""
    else:
        name = name.strip()
        if len(name) > 64 or not NAME_RE.fullmatch(name):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "INVALID_NAME",
                    "Skill name must be at most 64 characters of lowercase letters, digits, and hyphens.",
                    str(skill_file),
                    skill=name,
                )
            )

    if not isinstance(description, str) or not description.strip():
        diagnostics.append(
            Diagnostic(
                "error",
                "MISSING_DESCRIPTION",
                "Frontmatter needs a non-empty string description.",
                str(skill_file),
                skill=name or None,
            )
        )
        description = ""
    else:
        description = description.strip()

    if name and skill_file.parent.name != name:
        diagnostics.append(
            Diagnostic(
                "error" if origin == "candidate" else "warning",
                "FOLDER_NAME_MISMATCH",
                f"Folder ‘{skill_file.parent.name}’ does not match frontmatter name ‘{name}’.",
                str(skill_file),
                skill=name,
            )
        )

    openai_path = skill_file.parent / "agents" / "openai.yaml"
    openai_data: dict[str, Any] | None = None
    if openai_path.exists():
        try:
            openai_raw = openai_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "UNREADABLE_OPENAI_YAML",
                    f"Cannot read agents/openai.yaml: {exc}.",
                    str(openai_path),
                    skill=name or None,
                )
            )
        else:
            openai_data, openai_error = _load_yaml_mapping(openai_path, openai_raw, "agents/openai.yaml")
            if openai_error:
                diagnostics.append(
                    Diagnostic(
                        openai_error.severity,
                        openai_error.code,
                        openai_error.message,
                        openai_error.path,
                        skill=name or None,
                        line=openai_error.line,
                    )
                )

    record = SkillRecord(
        skill_file=skill_file,
        skill_dir=skill_file.parent,
        origin=origin,
        name=name,
        description=description,
        frontmatter=frontmatter,
        body="".join(lines[end_index + 1 :]),
        openai_data=openai_data,
    )
    return record, diagnostics


def _declares_explicit_only(record: SkillRecord) -> bool:
    if record.frontmatter.get("disable-model-invocation") is True:
        return True
    metadata = record.frontmatter.get("metadata")
    if isinstance(metadata, dict):
        invocation = metadata.get("invocation")
        if isinstance(invocation, str) and invocation.strip().lower() in {
            "explicit",
            "explicit-only",
            "user-invoked",
        }:
            return True
        if metadata.get("explicit-only") is True:
            return True
    return False


def _text_declares_explicit_only(record: SkillRecord) -> bool:
    """Recognize an exclusive user gate, not a disjunction with an approved SOP route."""
    searchable = f"{record.description}\n{record.body}"
    for match in EXPLICIT_TEXT_RE.finditer(searchable):
        # A gate on changing runtime settings does not gate Skill discovery.
        # Require the action immediately before this occurrence; an unrelated
        # model-setting sentence must not hide a later invocation restriction.
        setting_prefix = searchable[max(0, match.start() - 400):match.start()]
        if re.search(
            r"(?:^|[.\n])\s*(?:[-*]\s*)?(?:change|override|adjust)\s+"
            r"(?:the\s+|current\s+)?(?:model|reasoning\s+effort|service\s+settings)"
            r"(?:\s*,?\s*(?:and\s+)?(?:model|reasoning\s+effort|service\s+settings))*\s*$",
            setting_prefix, re.IGNORECASE,
        ) or re.search(
            r"(?:^|\n)\s*(?:[-*]\s*)?Inherit the current model, reasoning effort, "
            r"and service settings[^.\n]*\.\s*Change them\s*$",
            setting_prefix, re.IGNORECASE,
        ):
            continue
        local_prefix = searchable[max(0, match.start() - 96):match.start()]
        local_suffix = searchable[match.end():match.end() + 48]
        if re.search(
            r"\b(?:wording|phrase|text|regex|pattern)\s+(?:such\s+as\s+)?"
            r"(?:example\s*)?[‘’'\"“”`]*(?:only\s*/\s*)?\s*$",
            local_prefix,
            re.IGNORECASE,
        ) or re.search(
            r"\bexample\s+[‘’'\"“”`]*\s*$", local_prefix, re.IGNORECASE
        ) or (
            re.match(r"\s+invocation\s+policy\b", local_suffix, re.IGNORECASE)
            and re.search(
                r"\b(?:audit|check|detect|inspect|structured|textual)\b",
                local_prefix,
                re.IGNORECASE,
            )
        ):
            continue
        sentence_end_candidates = [
            index
            for token in (".", "!", "?", "\n")
            for index in (searchable.find(token, match.end()),)
            if index != -1
        ]
        sentence_end = min(sentence_end_candidates, default=len(searchable))
        suffix = searchable[match.end():sentence_end]
        if re.search(r"\bor\s+(?:the\s+)?visual\s+SOP\b", suffix, re.IGNORECASE):
            continue
        return True
    return False


def _implicit_policy(record: SkillRecord) -> tuple[bool | None, bool]:
    if record.openai_data is None:
        return None, False
    policy = record.openai_data.get("policy")
    if policy is None:
        return None, False
    if not isinstance(policy, dict):
        return None, True
    value = policy.get("allow_implicit_invocation")
    return value if isinstance(value, bool) else None, value is not None and not isinstance(value, bool)


def _governance_declaration(
    record: SkillRecord,
) -> tuple[dict[str, str], list[str], list[Diagnostic]]:
    """Read candidate-supplied declarations without treating them as evidence of safety."""
    metadata = record.frontmatter.get("metadata")
    if not isinstance(metadata, dict) or "governance" not in metadata:
        return {}, [], []

    governance = metadata.get("governance")
    if not isinstance(governance, dict):
        return {}, [], [
            Diagnostic(
                "error",
                "INVALID_GOVERNANCE_DECLARATION",
                "metadata.governance must be a YAML mapping.",
                str(record.skill_file),
                skill=record.name or None,
            )
        ]

    diagnostics: list[Diagnostic] = []
    declarations: dict[str, str] = {}
    allowed_keys = set(RISK_DECLARATION_VALUES) | {"dependencies"}
    unknown_keys = sorted(str(key) for key in governance if key not in allowed_keys)
    if unknown_keys:
        diagnostics.append(
            Diagnostic(
                "error",
                "INVALID_GOVERNANCE_DECLARATION",
                "Unknown metadata.governance key(s): " + ", ".join(unknown_keys) + ".",
                str(record.skill_file),
                skill=record.name or None,
            )
        )

    for key, allowed_values in RISK_DECLARATION_VALUES.items():
        if key not in governance:
            continue
        value = governance.get(key)
        normalized = value.strip().lower() if isinstance(value, str) else None
        if normalized not in allowed_values:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "INVALID_GOVERNANCE_DECLARATION",
                    f"metadata.governance.{key} must be one of: "
                    + ", ".join(sorted(allowed_values))
                    + ".",
                    str(record.skill_file),
                    skill=record.name or None,
                )
            )
            continue
        declarations[key] = normalized

    dependencies_value = governance.get("dependencies", [])
    declared_dependencies: list[str] = []
    if not isinstance(dependencies_value, list) or any(
        not isinstance(item, str) or not item.strip() for item in dependencies_value
    ):
        diagnostics.append(
            Diagnostic(
                "error",
                "INVALID_GOVERNANCE_DECLARATION",
                "metadata.governance.dependencies must be a list of non-empty strings.",
                str(record.skill_file),
                skill=record.name or None,
            )
        )
    else:
        declared_dependencies = sorted({item.strip() for item in dependencies_value})
        for dependency in declared_dependencies:
            diagnostics.append(
                Diagnostic(
                    "info",
                    "RUNTIME_DEPENDENCY_DECLARED",
                    f"Candidate declares runtime dependency ‘{dependency}’; availability is not verified.",
                    str(record.skill_file),
                    skill=record.name or None,
                )
            )

    return declarations, declared_dependencies, diagnostics


def _tool_dependency_diagnostics(record: SkillRecord) -> tuple[list[Diagnostic], bool]:
    """Validate the supported agents/openai.yaml dependency shape."""
    if record.openai_data is None or "dependencies" not in record.openai_data:
        return [], False

    path = record.skill_dir / "agents" / "openai.yaml"
    dependencies = record.openai_data.get("dependencies")
    if not isinstance(dependencies, dict):
        return [
            Diagnostic(
                "error",
                "INVALID_TOOL_DEPENDENCY",
                "agents/openai.yaml dependencies must be a YAML mapping.",
                str(path),
                skill=record.name or None,
            )
        ], False

    tools = dependencies.get("tools")
    if not isinstance(tools, list):
        return [
            Diagnostic(
                "error",
                "INVALID_TOOL_DEPENDENCY",
                "agents/openai.yaml dependencies.tools must be a list.",
                str(path),
                skill=record.name or None,
            )
        ], False

    diagnostics: list[Diagnostic] = []
    has_remote_url = False
    for index, item in enumerate(tools):
        if not isinstance(item, dict):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "INVALID_TOOL_DEPENDENCY",
                    f"dependencies.tools[{index}] must be a YAML mapping.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        dependency_type = item.get("type")
        value = item.get("value")
        url = item.get("url")
        if dependency_type != "mcp" or not isinstance(value, str) or not value.strip():
            diagnostics.append(
                Diagnostic(
                    "error",
                    "INVALID_TOOL_DEPENDENCY",
                    f"dependencies.tools[{index}] needs type: mcp and a non-empty string value.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        if url is not None and not isinstance(url, str):
            diagnostics.append(
                Diagnostic(
                    "error",
                    "INVALID_TOOL_DEPENDENCY",
                    f"dependencies.tools[{index}].url must be a string when present.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        if isinstance(url, str) and re.match(r"^https?://", url, re.IGNORECASE):
            has_remote_url = True
        diagnostics.append(
            Diagnostic(
                "info",
                "TOOL_DEPENDENCY_DECLARED",
                f"Candidate declares MCP tool dependency ‘{value.strip()}’; reachability and trust are not verified.",
                str(path),
                skill=record.name or None,
            )
        )
    return diagnostics, has_remote_url


def _is_test_named_source(path: Path) -> bool:
    return path.name.startswith("test_") or path.stem.endswith("_test")


def _is_explicitly_referenced_source(record: SkillRecord, relative: Path) -> bool:
    """Keep a test-named runtime hook when SKILL.md directly names that file."""
    searchable = f"{record.description}\n{record.body}"
    relative_token = relative.as_posix()
    if relative_token in searchable or f"./{relative_token}" in searchable:
        return True
    return re.search(
        rf"(?<![A-Za-z0-9_.-]){re.escape(relative.name)}(?![A-Za-z0-9_.-])",
        searchable,
    ) is not None


def _source_files(record: SkillRecord) -> tuple[list[Path], list[Diagnostic]]:
    files = [record.skill_file]
    diagnostics: list[Diagnostic] = []
    for path in sorted(record.skill_dir.rglob("*"), key=lambda item: str(item)):
        try:
            relative = path.relative_to(record.skill_dir)
        except ValueError:
            continue
        suffix = path.suffix.lower()
        reference_document = (
            bool(relative.parts)
            and relative.parts[0] == "references"
            and suffix in REFERENCE_SOURCE_SUFFIXES
        )
        supported_source = suffix in SOURCE_SUFFIXES or reference_document
        if not supported_source or path.name.startswith("."):
            continue
        explicitly_referenced = _is_explicitly_referenced_source(record, relative)
        if _is_skipped(relative) and not explicitly_referenced:
            continue
        if _is_test_named_source(path) and not explicitly_referenced:
            continue
        if path.is_symlink():
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_SKIPPED_SYMLINK",
                    "Symlinked source path was not followed by the static scanner.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        try:
            mode = path.stat().st_mode
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_INCOMPLETE",
                    f"Could not inspect supported Skill source: {exc.__class__.__name__}.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        if stat.S_ISREG(mode):
            files.append(path)
    return sorted(set(files), key=lambda item: str(item)), diagnostics


def _read_sources(
    record: SkillRecord,
) -> tuple[dict[Path, str], list[Diagnostic]]:
    files, diagnostics = _source_files(record)
    sources: dict[Path, str] = {}
    for path in files:
        if path.is_symlink():
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_SKIPPED_SYMLINK",
                    "Symlinked source file was not followed by the static scanner.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_INCOMPLETE",
                    f"Could not stat Skill source: {exc.__class__.__name__}.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        if size > MAX_SOURCE_BYTES:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_SKIPPED_SIZE",
                    f"Source exceeds the {MAX_SOURCE_BYTES}-byte static scan limit.",
                    str(path),
                    skill=record.name or None,
                )
            )
            continue
        try:
            sources[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "SOURCE_SCAN_INCOMPLETE",
                    f"Could not read Skill source as UTF-8: {exc.__class__.__name__}.",
                    str(path),
                    skill=record.name or None,
                )
            )
    return sources, diagnostics


def _python_external_imports(
    record: SkillRecord, sources: dict[Path, str]
) -> tuple[list[tuple[str, Path, int]], list[Diagnostic]]:
    scripts_dir = record.skill_dir / "scripts"
    local_modules = {
        path.stem
        for path in sources
        if path.suffix == ".py" and (path.parent == scripts_dir or path.parent == record.skill_dir)
    }
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}
    imports: dict[str, tuple[Path, int]] = {}
    diagnostics: list[Diagnostic] = []
    for path, text in sorted(sources.items(), key=lambda item: str(item[0])):
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "PYTHON_SOURCE_PARSE_INCOMPLETE",
                    "Python syntax could not be parsed, so import and call detection is incomplete.",
                    str(path),
                    skill=record.name or None,
                    line=exc.lineno,
                )
            )
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if name in stdlib or name in local_modules:
                    continue
                imports.setdefault(name, (path, getattr(node, "lineno", 1)))
    return [(name, *imports[name]) for name in sorted(imports)], diagnostics


NODE_IMPORT_RE = re.compile(
    r"\b(?:import|export)\s+(?:[^'\"\n]*?\s+from\s+)?['\"](?P<static>[^'\"]+)['\"]"
    r"|\b(?:require|import)\s*\(\s*['\"](?P<dynamic>[^'\"]+)['\"]\s*\)"
)


def _node_external_imports(sources: dict[Path, str]) -> list[tuple[str, Path, int]]:
    imports: dict[str, tuple[Path, int]] = {}
    for path, text in sorted(sources.items(), key=lambda item: str(item[0])):
        if path.suffix.lower() not in {".cjs", ".js", ".mjs", ".ts", ".tsx"}:
            continue
        for match in NODE_IMPORT_RE.finditer(text):
            specifier = match.group("static") or match.group("dynamic")
            if specifier.startswith((".", "/", "@/", "~/", "#", "node:")):
                continue
            package = (
                "/".join(specifier.split("/")[:2])
                if specifier.startswith("@")
                else specifier.split("/", 1)[0]
            )
            if package in NODE_BUILTINS:
                continue
            imports.setdefault(package, (path, _line_number(text, match.start())))
    return [(name, *imports[name]) for name in sorted(imports)]


def _looks_like_secret_placeholder(value: str) -> bool:
    normalized = value.lower().replace("_", "-")
    markers = ("changeme", "dummy", "example", "placeholder", "replace-me", "your-")
    return any(marker in normalized for marker in markers) or set(normalized) <= {"x", "-", "_"}


def _mask_python_regex_literals(path: Path, text: str) -> str:
    """Prevent the auditor's own regex catalogs from being treated as executable behavior."""
    if path.suffix != ".py":
        return text
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return text

    line_offsets: list[int] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_offsets.append(offset)
        offset += len(line)
    masked = list(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_re_compile = (
            isinstance(function, ast.Attribute)
            and function.attr == "compile"
            and isinstance(function.value, ast.Name)
            and function.value.id == "re"
        )
        argument = node.args[0]
        if (
            not is_re_compile
            or not isinstance(argument, ast.Constant)
            or not isinstance(argument.value, str)
            or argument.end_lineno is None
            or argument.end_col_offset is None
        ):
            continue
        # CPython AST columns are UTF-8 byte offsets, while Python string
        # indexing uses Unicode code points. Convert explicitly so a non-ASCII
        # token before re.compile(...) cannot corrupt the mask.
        start_line = text.splitlines(keepends=True)[argument.lineno - 1]
        end_line = text.splitlines(keepends=True)[argument.end_lineno - 1]
        start_column = len(
            start_line.encode("utf-8")[: argument.col_offset].decode(
                "utf-8", errors="ignore"
            )
        )
        end_column = len(
            end_line.encode("utf-8")[: argument.end_col_offset].decode(
                "utf-8", errors="ignore"
            )
        )
        start = line_offsets[argument.lineno - 1] + start_column
        end = line_offsets[argument.end_lineno - 1] + end_column
        for index in range(start, min(end, len(masked))):
            if masked[index] not in {"\n", "\r"}:
                masked[index] = " "
    return "".join(masked)


def _mask_explanatory_reference_lines(path: Path, text: str) -> str:
    """Mask clearly non-executable deletion examples while preserving offsets."""
    if path.suffix.lower() not in REFERENCE_SOURCE_SUFFIXES or "references" not in path.parts:
        return text
    lines = text.splitlines(keepends=True)
    masked: list[str] = []
    negative_context = re.compile(
        r"\b(?:do\s+not|don't|never|must\s+not|forbidden|prohibited|unsafe\s+example)\b"
        r"|(?:禁止|不得|不要|切勿|仅作反例|危险示例)",
        re.IGNORECASE,
    )
    catalog_line = re.compile(
        r"\b(?:regex|regular expression|scanner|detection|catalog|pattern)\b",
        re.IGNORECASE,
    )
    deletion_lexeme = re.compile(
        r"(?:^|\s)rm\s+-|\bos\.(?:remove|unlink|rmdir)\s*\(|"
        r"\bshutil\.rmtree\s*\(|\b(?:fs\w*\.)?(?:rmSync|unlinkSync|rmdirSync)\s*\(|"
        r"\bDeno\.remove(?:Sync)?\s*\(|\bRemove-Item\b",
        re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        context = "".join(lines[max(0, index - 4): index + 1])
        explanatory = negative_context.search(context) is not None
        explanatory = explanatory or (
            catalog_line.search(line) is not None
            and re.search(r"\b(?:run|execute|invoke)\b", line, re.IGNORECASE) is None
        )
        if explanatory and deletion_lexeme.search(line):
            masked.append("".join(char if char in "\r\n" else " " for char in line))
        else:
            masked.append(line)
    return "".join(masked)


def _mask_prohibited_sql_reference_mentions(path: Path, text: str) -> str:
    """Mask only an inline SQL capability explicitly prohibited by its prose."""
    if path.suffix.lower() not in REFERENCE_SOURCE_SUFFIXES or "references" not in path.parts:
        return text
    masked = list(text)
    fence: str | None = None
    offset = 0
    sql_mention = re.compile(
        r"`(?P<sql>(?:CREATE/)?(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE\s+TABLE)"
        r"[\w\s·./-]*)`", re.IGNORECASE,
    )
    for line in text.splitlines(keepends=True):
        fence_match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence_match:
            marker = fence_match.group(1)[0]
            fence = None if fence == marker else (marker if fence is None else fence)
        elif fence is None:
            for mention in sql_mention.finditer(line):
                prefix = re.split(r"[。.!?;；\n]", line[:mention.start()])[-1]
                suffix = re.split(r"[。.!?;；\n]", line[mention.end():], maxsplit=1)[0]
                direct_ban = re.search(
                    r"(?:\b(?:do\s+not|don't|never|must\s+not)\s+"
                    r"(?:execute|run|use)\s+|(?:禁止|不得|不要|切勿)(?:执行|运行|使用)?\s*)$",
                    prefix, re.IGNORECASE,
                )
                # A list of inline capabilities may share one rejection verb.
                # No SQL executable string, prose instruction, or newline is
                # consumed as a list item; other matches stay visible.
                rejected = re.match(
                    r"\s*(?:(?:、|,)\s*(?:非白名单|平台保留表)?\s*`[^`\n]+`(?:/`[^`\n]+`)*)*"
                    r"\s*(?:会被硬拒|被禁止|不受支持|(?:is|are)\s+(?:forbidden|prohibited|rejected))",
                    suffix, re.IGNORECASE,
                )
                if direct_ban or rejected:
                    start, end = mention.span("sql")
                    for index in range(offset + start, offset + end):
                        if masked[index] not in "\r\n":
                            masked[index] = " "
        offset += len(line)
    return "".join(masked)


def _risk_scan_sources(sources: dict[Path, str]) -> dict[Path, str]:
    return {
        path: _mask_prohibited_sql_reference_mentions(
            path, _mask_explanatory_reference_lines(
                path, _mask_python_regex_literals(path, text)
            )
        )
        for path, text in sources.items()
    }


def _first_hardcoded_secret(sources: dict[Path, str]) -> tuple[Path, int] | None:
    for path, text in sorted(sources.items(), key=lambda item: str(item[0])):
        for pattern in HARDCODED_SECRET_PATTERNS:
            for match in pattern.finditer(text):
                assigned = match.groupdict().get("assigned_secret")
                if assigned is not None and _looks_like_secret_placeholder(assigned):
                    continue
                return path, _line_number(text, match.start())
    return None


NODE_DESTRUCTIVE_METHODS = (
    "rm",
    "rmSync",
    "unlink",
    "unlinkSync",
    "rmdir",
    "rmdirSync",
)


def _classify_destructive_match(match: re.Match[str]) -> DestructiveSourceMatch:
    token = match.group(0)
    method_match = re.search(
        r"\b(rmSync|unlinkSync|rmdirSync|removeSync|rm|unlink|rmdir|remove|rmtree)\b",
        token,
        re.IGNORECASE,
    )
    method = method_match.group(1) if method_match else "destructive"
    if re.match(r"\s*(?:sudo\s+)?rm\b", token):
        runtime = "shell"
    elif re.search(r"\b(?:fs|Deno)\s*(?:\.|\\)", token):
        runtime = "deno" if "Deno" in token else "node"
    elif re.search(r"\b(?:os\.|shutil\.)", token):
        runtime = "python"
    elif re.search(r"\bRemove-Item\b", token, re.IGNORECASE):
        runtime = "powershell"
    else:
        runtime = "generic"
    # Anchored shell/PowerShell patterns may begin on a preceding blank line
    # because ``\s`` also matches newlines. Anchor diagnostics and cleanup
    # proofs to the actual destructive verb, not that incidental whitespace.
    start = match.start() + (method_match.start() if method_match is not None else 0)
    return DestructiveSourceMatch(start, match.end(), method, runtime)


def _node_delete_bindings(text: str) -> tuple[set[str], dict[str, str]]:
    """Resolve common, high-confidence Node fs namespace and function aliases."""
    namespaces = {"fs"}
    functions: dict[str, str] = {}
    module = r"(?:node:)?fs"
    identifier = r"[A-Za-z_$][A-Za-z0-9_$]*"

    for pattern in (
        re.compile(
            rf"\b(?:const|let|var)\s+({identifier})\s*=\s*"
            rf"require\s*\(\s*['\"]{module}['\"]\s*\)"
        ),
        re.compile(
            rf"\bimport\s+(?:\*\s+as\s+)?({identifier})\s+from\s+['\"]{module}['\"]"
        ),
    ):
        namespaces.update(match.group(1) for match in pattern.finditer(text))

    destructured = re.compile(
        rf"\b(?:const|let|var)\s*\{{(?P<body>[^}}]+)\}}\s*=\s*"
        rf"require\s*\(\s*['\"]{module}['\"]\s*\)"
    )
    named_import = re.compile(
        rf"\bimport\s*\{{(?P<body>[^}}]+)\}}\s*from\s*['\"]{module}['\"]"
    )
    for pattern, separator in ((destructured, ":"), (named_import, "as")):
        for binding in pattern.finditer(text):
            for raw_item in binding.group("body").split(","):
                item = raw_item.strip()
                if not item:
                    continue
                if separator == ":":
                    parts = re.split(r"\s*:\s*", item, maxsplit=1)
                else:
                    parts = re.split(r"\s+as\s+", item, maxsplit=1)
                source = parts[0].strip()
                local = parts[-1].strip()
                if source in NODE_DESTRUCTIVE_METHODS and re.fullmatch(identifier, local):
                    functions[local] = source

    namespace_pattern = "|".join(
        re.escape(name) for name in sorted(namespaces, key=lambda value: (-len(value), value))
    )
    if namespace_pattern:
        property_alias = re.compile(
            rf"\b(?:const|let|var)\s+({identifier})\s*=\s*"
            rf"(?:{namespace_pattern})\s*\.\s*({'|'.join(NODE_DESTRUCTIVE_METHODS)})\b"
        )
        for binding in property_alias.finditer(text):
            functions[binding.group(1)] = binding.group(2)
    return namespaces, functions


def _mask_python_non_code(path: Path, text: str) -> str:
    if path.suffix.lower() != ".py":
        return text
    lines = text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    masked = list(text)
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type not in {tokenize.COMMENT, tokenize.STRING}:
                continue
            start_line, start_column = token.start
            end_line, end_column = token.end
            start = offsets[start_line - 1] + start_column
            end = offsets[end_line - 1] + end_column
            for index in range(start, min(end, len(masked))):
                if masked[index] not in {"\n", "\r"}:
                    masked[index] = " "
    except (IndentationError, tokenize.TokenError):
        return text
    return "".join(masked)


def _mask_javascript_non_code(path: Path, text: str) -> str:
    if path.suffix.lower() not in {".cjs", ".js", ".mjs", ".ts", ".tsx"}:
        return text
    masked = list(text)
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and next_char == "/":
                state = "line-comment"
                masked[index] = masked[index + 1] = " "
                index += 2
                continue
            if char == "/" and next_char == "*":
                state = "block-comment"
                masked[index] = masked[index + 1] = " "
                index += 2
                continue
            if char in {"'", '"', "`"}:
                state = "string"
                quote = char
                masked[index] = " "
                index += 1
                continue
        elif state == "line-comment":
            if char in {"\n", "\r"}:
                state = "code"
            else:
                masked[index] = " "
            index += 1
            continue
        elif state == "block-comment":
            if char == "*" and next_char == "/":
                masked[index] = masked[index + 1] = " "
                state = "code"
                index += 2
                continue
            if char not in {"\n", "\r"}:
                masked[index] = " "
            index += 1
            continue
        elif state == "string":
            if char == "\\":
                masked[index] = " "
                if index + 1 < len(text) and text[index + 1] not in {"\n", "\r"}:
                    masked[index + 1] = " "
                index += 2
                continue
            if char == quote:
                masked[index] = " "
                state = "code"
                index += 1
                continue
            if char not in {"\n", "\r"}:
                masked[index] = " "
            index += 1
            continue
        index += 1
    return "".join(masked)


_PY_PATH = "path"
_PY_PATH_ITER = "path-iter"
_PY_PATH_LIST = "path-list"
_PY_PATH_CTOR = "path-constructor"
_PY_PATHLIB_MODULE = "pathlib-module"


def _python_ast_offset(
    text: str, lines: list[str], line_offsets: list[int], node: ast.AST, *, end: bool = False
) -> int:
    """Convert CPython's UTF-8 byte columns to a character offset."""
    line_number = getattr(node, "end_lineno" if end else "lineno", None)
    byte_column = getattr(node, "end_col_offset" if end else "col_offset", None)
    if line_number is None or byte_column is None or line_number < 1:
        return 0
    line_index = min(line_number - 1, len(lines) - 1)
    character_column = len(
        lines[line_index].encode("utf-8")[:byte_column].decode("utf-8", errors="ignore")
    )
    return min(len(text), line_offsets[line_index] + character_column)


class _PythonPathDeleteAnalyzer:
    """Small flow-sensitive provenance pass for pathlib deletion calls.

    This is deliberately not a general Python type checker. It recognizes only
    explicit pathlib origins and keeps an operation dangerous if any reachable
    branch still carries Path provenance.
    """

    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.splitlines(keepends=True) or [""]
        self.line_offsets: list[int] = []
        offset = 0
        for line in self.lines:
            self.line_offsets.append(offset)
            offset += len(line)
        self.matches: list[DestructiveSourceMatch] = []

    def analyze(self, tree: ast.Module) -> list[DestructiveSourceMatch]:
        self._block(tree.body, {})
        return self.matches

    @staticmethod
    def _merge(*environments: dict[str, frozenset[str]]) -> dict[str, frozenset[str]]:
        merged: dict[str, frozenset[str]] = {}
        for name in set().union(*(environment.keys() for environment in environments)):
            values: set[str] = set()
            for environment in environments:
                values.update(environment.get(name, frozenset()))
            merged[name] = frozenset(values)
        return merged

    @staticmethod
    def _bind_target(
        target: ast.expr, value: frozenset[str], environment: dict[str, frozenset[str]]
    ) -> None:
        if isinstance(target, ast.Name):
            environment[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                _PythonPathDeleteAnalyzer._bind_target(item, frozenset(), environment)

    def _annotation_is_path(
        self, annotation: ast.expr | None, environment: dict[str, frozenset[str]]
    ) -> bool:
        if annotation is None:
            return False
        for node in ast.walk(annotation):
            if isinstance(node, ast.Name) and _PY_PATH_CTOR in environment.get(
                node.id, frozenset()
            ):
                return True
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "Path"
                and _PY_PATHLIB_MODULE in self._expr(node.value, environment)
            ):
                return True
        return False

    def _record_delete(self, function: ast.Attribute) -> None:
        start = _python_ast_offset(
            self.text, self.lines, self.line_offsets, function, end=False
        )
        end = _python_ast_offset(
            self.text, self.lines, self.line_offsets, function, end=True
        )
        open_paren = self.text.find("(", end, min(len(self.text), end + 32))
        call_end = open_paren + 1 if open_paren >= 0 else end
        self.matches.append(
            DestructiveSourceMatch(start, call_end, function.attr, "python")
        )

    def _expr(
        self, node: ast.expr | None, environment: dict[str, frozenset[str]]
    ) -> frozenset[str]:
        if node is None:
            return frozenset()
        if isinstance(node, ast.Name):
            return environment.get(node.id, frozenset())
        if isinstance(node, ast.Attribute):
            base = self._expr(node.value, environment)
            if node.attr == "parent" and _PY_PATH in base:
                return frozenset({_PY_PATH})
            if node.attr == "Path" and _PY_PATHLIB_MODULE in base:
                return frozenset({_PY_PATH_CTOR})
            return frozenset()
        if isinstance(node, ast.BinOp):
            left = self._expr(node.left, environment)
            self._expr(node.right, environment)
            if isinstance(node.op, ast.Div) and _PY_PATH in left:
                return frozenset({_PY_PATH})
            return frozenset()
        if isinstance(node, ast.Subscript):
            value = self._expr(node.value, environment)
            self._expr(node.slice, environment)
            if _PY_PATH_LIST in value:
                return frozenset({_PY_PATH})
            return frozenset()
        if isinstance(node, ast.IfExp):
            self._expr(node.test, environment)
            return self._expr(node.body, environment) | self._expr(node.orelse, environment)
        if isinstance(node, ast.NamedExpr):
            value = self._expr(node.value, environment)
            self._bind_target(node.target, value, environment)
            return value
        if isinstance(node, ast.Await):
            return self._expr(node.value, environment)
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Attribute):
                receiver = self._expr(function.value, environment)
                if function.attr in {"unlink", "rmdir"} and _PY_PATH in receiver:
                    self._record_delete(function)
                if function.attr == "Path" and _PY_PATHLIB_MODULE in receiver:
                    result = frozenset({_PY_PATH})
                elif _PY_PATH in receiver:
                    if function.attr in {
                        "absolute",
                        "expanduser",
                        "joinpath",
                        "resolve",
                        "with_name",
                        "with_suffix",
                    }:
                        result = frozenset({_PY_PATH})
                    elif function.attr in {"glob", "iterdir", "rglob"}:
                        result = frozenset({_PY_PATH_ITER})
                    else:
                        result = frozenset()
                else:
                    result = frozenset()
            else:
                function_kind = self._expr(function, environment)
                if _PY_PATH_CTOR in function_kind:
                    result = frozenset({_PY_PATH})
                elif (
                    isinstance(function, ast.Name)
                    and function.id == "list"
                    and "list" not in environment
                    and node.args
                    and _PY_PATH_ITER in self._expr(node.args[0], environment)
                ):
                    result = frozenset({_PY_PATH_LIST})
                else:
                    result = frozenset()
            for argument in node.args:
                self._expr(argument, environment)
            for keyword in node.keywords:
                self._expr(keyword.value, environment)
            return result
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self._expr(child, environment)
        return frozenset()

    def _block(
        self, statements: list[ast.stmt], environment: dict[str, frozenset[str]]
    ) -> dict[str, frozenset[str]]:
        current = dict(environment)
        for statement in statements:
            current = self._statement(statement, current)
        return current

    def _statement(
        self, statement: ast.stmt, environment: dict[str, frozenset[str]]
    ) -> dict[str, frozenset[str]]:
        current = dict(environment)
        if isinstance(statement, ast.ImportFrom):
            if statement.level == 0 and statement.module == "pathlib":
                for alias in statement.names:
                    current[alias.asname or alias.name] = (
                        frozenset({_PY_PATH_CTOR})
                        if alias.name == "Path"
                        else frozenset()
                    )
            else:
                for alias in statement.names:
                    current[alias.asname or alias.name] = frozenset()
            return current
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                current[local] = (
                    frozenset({_PY_PATHLIB_MODULE})
                    if alias.name == "pathlib"
                    else frozenset()
                )
            return current
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in statement.decorator_list:
                self._expr(decorator, current)
            for default in (*statement.args.defaults, *statement.args.kw_defaults):
                self._expr(default, current)
            child = dict(current)
            arguments = (
                *statement.args.posonlyargs,
                *statement.args.args,
                *statement.args.kwonlyargs,
            )
            if statement.args.vararg is not None:
                arguments += (statement.args.vararg,)
            if statement.args.kwarg is not None:
                arguments += (statement.args.kwarg,)
            for argument in arguments:
                child[argument.arg] = (
                    frozenset({_PY_PATH})
                    if self._annotation_is_path(argument.annotation, current)
                    else frozenset()
                )
            self._block(statement.body, child)
            current[statement.name] = frozenset()
            return current
        if isinstance(statement, ast.ClassDef):
            for decorator in statement.decorator_list:
                self._expr(decorator, current)
            self._block(statement.body, dict(current))
            current[statement.name] = frozenset()
            return current
        if isinstance(statement, ast.Assign):
            value = self._expr(statement.value, current)
            for target in statement.targets:
                self._bind_target(target, value, current)
            return current
        if isinstance(statement, ast.AnnAssign):
            value = (
                self._expr(statement.value, current)
                if statement.value is not None
                else (
                    frozenset({_PY_PATH})
                    if self._annotation_is_path(statement.annotation, current)
                    else frozenset()
                )
            )
            self._bind_target(statement.target, value, current)
            return current
        if isinstance(statement, ast.AugAssign):
            self._expr(statement.value, current)
            self._bind_target(statement.target, frozenset(), current)
            return current
        if isinstance(statement, ast.Expr):
            self._expr(statement.value, current)
            return current
        if isinstance(statement, ast.If):
            self._expr(statement.test, current)
            body = self._block(statement.body, dict(current))
            otherwise = self._block(statement.orelse, dict(current))
            return self._merge(body, otherwise)
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            iterable = self._expr(statement.iter, current)
            body_start = dict(current)
            item = (
                frozenset({_PY_PATH})
                if iterable & {_PY_PATH_ITER, _PY_PATH_LIST}
                else frozenset()
            )
            self._bind_target(statement.target, item, body_start)
            body = self._block(statement.body, body_start)
            otherwise = self._block(statement.orelse, dict(current))
            return self._merge(current, body, otherwise)
        if isinstance(statement, ast.While):
            self._expr(statement.test, current)
            body = self._block(statement.body, dict(current))
            otherwise = self._block(statement.orelse, dict(current))
            return self._merge(current, body, otherwise)
        if isinstance(statement, ast.Try):
            body = self._block(statement.body, dict(current))
            branches = [current, body, self._block(statement.orelse, dict(body))]
            for handler in statement.handlers:
                handler_environment = dict(current)
                if handler.name:
                    handler_environment[handler.name] = frozenset()
                branches.append(self._block(handler.body, handler_environment))
            merged = self._merge(*branches)
            return self._block(statement.finalbody, merged)
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            child = dict(current)
            for item in statement.items:
                value = self._expr(item.context_expr, child)
                if item.optional_vars is not None:
                    self._bind_target(item.optional_vars, value, child)
            return self._block(statement.body, child)
        if isinstance(statement, (ast.Return, ast.Raise, ast.Assert)):
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, ast.expr):
                    self._expr(child, current)
            return current
        return current


def _python_path_destructive_matches(path: Path, text: str) -> list[DestructiveSourceMatch]:
    if path.suffix.lower() != ".py":
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        executable_text = _mask_python_non_code(path, text)
        fallback: list[DestructiveSourceMatch] = []
        for match in re.finditer(r"\.\s*(?P<method>unlink|rmdir)\s*\(", executable_text):
            fallback.append(
                DestructiveSourceMatch(
                    match.start(), match.end(), match.group("method"), "python"
                )
            )
        return fallback
    return _PythonPathDeleteAnalyzer(text).analyze(tree)


def _destructive_source_matches(
    path: Path, text: str, *, include_domain_actions: bool = True
) -> list[DestructiveSourceMatch]:
    """Find supported destructive signals, including common Node fs aliases."""
    executable_text = _mask_javascript_non_code(path, _mask_python_non_code(path, text))
    matches: dict[tuple[int, str], DestructiveSourceMatch] = {}
    for pattern in RISK_SIGNAL_PATTERNS["destructive-actions"]:
        if not include_domain_actions and (
            "lark-cli" in pattern.pattern or "DROP" in pattern.pattern
        ):
            continue
        for match in pattern.finditer(executable_text):
            classified = _classify_destructive_match(match)
            # Post-install recognizes a bare Python .unlink()/.rmdir() only
            # when the AST provenance pass below can tie its receiver to
            # pathlib.Path. Other generic domain methods remain ignored.
            if not include_domain_actions and classified.runtime == "generic":
                continue
            matches[(classified.start, classified.method)] = classified

    if path.suffix.lower() == ".py":
        for item in _python_path_destructive_matches(path, text):
            matches[(item.start, item.method)] = item

    if path.suffix.lower() in {".cjs", ".js", ".mjs", ".ts", ".tsx"}:
        namespaces, functions = _node_delete_bindings(text)
        method_pattern = "|".join(NODE_DESTRUCTIVE_METHODS)
        for namespace in namespaces:
            pattern = re.compile(
                rf"\b{re.escape(namespace)}\s*\.\s*(?P<method>{method_pattern})\s*\("
            )
            for match in pattern.finditer(executable_text):
                item = DestructiveSourceMatch(
                    match.start(), match.end(), match.group("method"), "node"
                )
                matches[(item.start, item.method)] = item
        for function, method in functions.items():
            pattern = re.compile(rf"\b{re.escape(function)}\s*\(")
            for match in pattern.finditer(executable_text):
                item = DestructiveSourceMatch(match.start(), match.end(), method, "node")
                matches[(item.start, item.method)] = item

    # A broad fallback such as `.unlink(` can overlap the more informative
    # `fs.unlink(` match. Keep one operation per call boundary.
    by_call_end: dict[int, DestructiveSourceMatch] = {}
    runtime_priority = {
        "node": 0,
        "deno": 0,
        "python": 0,
        "powershell": 0,
        "shell": 0,
        "generic": 1,
    }
    for item in matches.values():
        previous = by_call_end.get(item.call_end)
        if previous is None or (
            runtime_priority.get(item.runtime, 2), item.start
        ) < (runtime_priority.get(previous.runtime, 2), previous.start):
            by_call_end[item.call_end] = item
    return sorted(
        by_call_end.values(), key=lambda item: (item.start, item.method, item.call_end)
    )


def _first_risk_signals(sources: dict[Path, str]) -> dict[str, tuple[Path, int]]:
    signals: dict[str, tuple[Path, int]] = {}
    for category, patterns in RISK_SIGNAL_PATTERNS.items():
        candidates: list[tuple[str, int, Path, int]] = []
        for path, text in sorted(sources.items(), key=lambda item: str(item[0])):
            if category == "destructive-actions":
                for match in _destructive_source_matches(path, text):
                    if (
                        match.runtime == "shell"
                        and path.suffix.lower() in {"", ".bash", ".sh", ".zsh"}
                        and (
                            _shell_local_cleanup_is_proven(text, match, file_only=True)
                            or _shell_owned_readonly_directory_cleanup_is_proven(text, match)
                        )
                    ):
                        continue
                    if (
                        match.runtime == "node"
                        and _node_owned_mkdtemp_cleanup_is_proven(path, text, match)
                    ):
                        continue
                    candidates.append(
                        (str(path), match.start, path, _line_number(text, match.start))
                    )
                continue
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    candidates.append((str(path), match.start(), path, _line_number(text, match.start())))
        if candidates:
            _, _, path, line = min(candidates)
            signals[category] = (path, line)
    return signals


def check_candidate_risk(record: SkillRecord) -> list[Diagnostic]:
    """Report static capability signals; never infer that absence means safety."""
    diagnostics: list[Diagnostic] = []
    declarations, declared_dependencies, declaration_diagnostics = _governance_declaration(record)
    diagnostics.extend(declaration_diagnostics)

    tool_diagnostics, remote_tool_dependency = _tool_dependency_diagnostics(record)
    diagnostics.extend(tool_diagnostics)

    manifest_names = sorted(
        path.name
        for name in DEPENDENCY_MANIFESTS
        for path in (record.skill_dir / name,)
        if path.is_file() and not path.is_symlink()
    )
    if manifest_names:
        diagnostics.append(
            Diagnostic(
                "info",
                "DEPENDENCY_MANIFEST",
                "Candidate contains dependency manifest(s): " + ", ".join(manifest_names) + ".",
                str(record.skill_dir),
                skill=record.name or None,
            )
        )

    sources, source_diagnostics = _read_sources(record)
    diagnostics.extend(source_diagnostics)

    python_imports, python_diagnostics = _python_external_imports(record, sources)
    diagnostics.extend(python_diagnostics)
    node_imports = _node_external_imports(sources)
    for dependency, path, line in python_imports:
        diagnostics.append(
            Diagnostic(
                "info",
                "PYTHON_EXTERNAL_IMPORT",
                f"Imports non-stdlib Python module ‘{dependency}’; installation and trust are not verified.",
                str(path),
                skill=record.name or None,
                line=line,
            )
        )
    for dependency, path, line in node_imports:
        diagnostics.append(
            Diagnostic(
                "info",
                "NODE_EXTERNAL_IMPORT",
                f"Imports external Node module ‘{dependency}’; installation and trust are not verified.",
                str(path),
                skill=record.name or None,
                line=line,
            )
        )
    if (python_imports or node_imports) and not manifest_names and not declared_dependencies:
        discovered = sorted({item[0] for item in (*python_imports, *node_imports)})
        diagnostics.append(
            Diagnostic(
                "warning",
                "RUNTIME_DEPENDENCY_DECLARATION_MISSING",
                "External imports have no dependency manifest or metadata.governance.dependencies declaration: "
                + ", ".join(discovered)
                + ".",
                str(record.skill_dir),
                skill=record.name or None,
            )
        )

    risk_sources = _risk_scan_sources(sources)
    signals = _first_risk_signals(risk_sources)
    if remote_tool_dependency and "network" not in signals:
        signals["network"] = (record.skill_dir / "agents" / "openai.yaml", 1)

    signal_labels = {
        "network": ("RISK_SIGNAL_NETWORK", "network access"),
        "external-writes": ("RISK_SIGNAL_EXTERNAL_WRITE", "writes outside the response"),
        "destructive-actions": ("RISK_SIGNAL_DESTRUCTIVE_ACTION", "destructive or difficult-to-recover actions"),
        "credentials": ("RISK_SIGNAL_CREDENTIAL_ACCESS", "credential or secret access"),
    }
    for category in RISK_DECLARATION_VALUES:
        declaration = declarations.get(category)
        signal = signals.get(category)
        if signal is None:
            if declaration not in {None, "none"}:
                diagnostics.append(
                    Diagnostic(
                        "info",
                        "RISK_CAPABILITY_DECLARED",
                        f"Candidate declares {category}: {declaration}; no matching static signal was found.",
                        str(record.skill_file),
                        skill=record.name or None,
                    )
                )
            continue

        path, line = signal
        code, label = signal_labels[category]
        diagnostics.append(
            Diagnostic(
                "error" if category == "destructive-actions" else "warning",
                code,
                f"Static source signal suggests {label}; inspect the matched context and safeguards.",
                str(path),
                skill=record.name or None,
                line=line,
            )
        )
        if declaration is None:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "RISK_DECLARATION_MISSING",
                    f"Static signal ‘{category}’ has no metadata.governance declaration.",
                    str(record.skill_file),
                    skill=record.name or None,
                )
            )
        elif declaration == "none":
            diagnostics.append(
                Diagnostic(
                    "error",
                    "RISK_DECLARATION_CONFLICT",
                    f"Candidate declares {category}: none, but a matching static signal remains.",
                    str(record.skill_file),
                    skill=record.name or None,
                )
            )
        else:
            diagnostics.append(
                Diagnostic(
                    "info",
                    "RISK_DECLARED",
                    f"Candidate declares {category}: {declaration}; the declaration does not suppress the signal.",
                    str(record.skill_file),
                    skill=record.name or None,
                )
            )

    secret = _first_hardcoded_secret(risk_sources)
    if secret is not None:
        path, line = secret
        diagnostics.append(
            Diagnostic(
                "error",
                "POSSIBLE_HARDCODED_SECRET",
                "Possible hardcoded credential detected; matched content is intentionally omitted.",
                str(path),
                skill=record.name or None,
                line=line,
            )
        )
    return diagnostics


def check_installed_destructive_risk(record: SkillRecord) -> list[Diagnostic]:
    """Fail closed on destructive source unless a narrow local-cleanup proof succeeds."""
    sources, diagnostics = _read_sources(record)
    scanned_sources = {
        path: text for path, text in sources.items() if path != record.skill_file
    }
    candidates: list[tuple[str, int, Path, int]] = []
    for path, text in sorted(
        _risk_scan_sources(scanned_sources).items(), key=lambda item: str(item[0])
    ):
        for match in _destructive_source_matches(
            path, text, include_domain_actions=False
        ):
            if _is_strict_local_cleanup(path, text, match):
                continue
            candidates.append(
                (str(path), match.start, path, _line_number(text, match.start))
            )
    signal = None
    if candidates:
        _, _, path, line = min(candidates)
        signal = (path, line)
    if signal is not None:
        path, line = signal
        diagnostics.append(
            Diagnostic(
                "error",
                "RISK_SIGNAL_DESTRUCTIVE_ACTION",
                "Installed source suggests a destructive or difficult-to-recover action; inspect the matched context and safeguards.",
                str(path),
                skill=record.name or None,
                line=line,
            )
        )
    return diagnostics


def _simple_call_argument(text: str, call_end: int) -> str | None:
    argument = re.match(
        r"\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:,|\))",
        text[call_end:],
    )
    return argument.group(1) if argument is not None else None


def _is_controlled_temp_expression(expression: str) -> bool:
    """Accept only derived, fixed-name temporary artifacts—not arbitrary user paths."""
    expression = expression.strip()
    if re.search(r"\bmkdtemp(?:Sync)?\s*\(", expression):
        return True
    suffix = re.search(r"\+\s*(['\"])(?P<value>[^'\"]+)\1\s*$", expression)
    if suffix is not None:
        value = suffix.group("value").lower()
        return bool(
            re.search(r"(?:^|[._-])(?:tmp|temp|cache|part|list|palette)(?:[._-]|$)", value)
        )
    if re.search(r"\bpath\s*\.\s*join\s*\(", expression):
        literals = re.findall(r"['\"]([^'\"]+)['\"]", expression)
        if literals:
            leaf = literals[-1].lower()
            return bool(
                re.search(
                    r"(?:^|[._-])(?:tmp|temp|cache|part|list|palette)(?:[._-]|$)",
                    leaf,
                )
            )
    # Shell assignments commonly build an intermediate artifact name inside an
    # already selected output directory (for example `.palette-$BASE.png`).
    if re.search(
        r"""[._-](?:tmp|temp|cache|part|list|palette)(?:[._$\{\}"'/-]|$)""",
        expression,
        re.IGNORECASE,
    ):
        return True
    return False


def _node_callback_cleanup_is_proven(
    text: str, match: DestructiveSourceMatch, argument: str
) -> bool:
    """Recognize deletion of an array containing only files this source just rendered."""
    prefix = text[max(0, match.start - 200):match.start]
    callback = re.search(
        rf"\b(?P<array>[A-Za-z_$][A-Za-z0-9_$]*)\s*\.\s*forEach\s*\(\s*"
        rf"(?:\(\s*)?{re.escape(argument)}\s*(?:\)\s*)?=>\s*$",
        prefix,
    )
    if callback is None:
        return False
    array_name = callback.group("array")
    before = text[:match.start]
    declaration = re.search(
        rf"\bconst\s+{re.escape(array_name)}\s*=\s*\[\s*\]\s*;?",
        before,
    )
    if declaration is None:
        return False
    if re.search(
        rf"\b{re.escape(array_name)}\s*=(?!=)",
        before[declaration.end():],
    ):
        return False
    pushes = list(
        re.finditer(
            rf"\b{re.escape(array_name)}\s*\.\s*push\s*\(\s*"
            rf"([A-Za-z_$][A-Za-z0-9_$]*)\s*\)",
            before[declaration.end():],
        )
    )
    if not pushes:
        return False
    mutation = re.compile(
        rf"\b{re.escape(array_name)}\s*\.\s*(?!push\b|forEach\b)"
        rf"(?:unshift|splice|concat|fill|copyWithin)\s*\("
    )
    if mutation.search(before[declaration.end():]):
        return False
    for push in pushes:
        item = re.escape(push.group(1))
        creator_scope = before[declaration.end(): declaration.end() + push.start()]
        rendered = re.search(
            rf"(?:\b(?:writeFile|writeFileSync|appendFile|appendFileSync)\s*\(\s*{item}\b"
            rf"|\.\s*screenshot\s*\(\s*\{{[^}}]{{0,240}}\bpath\s*:\s*{item}\b)",
            creator_scope,
            re.DOTALL,
        )
        if rendered is None:
            return False
    return True


def _node_owned_mkdtemp_cleanup_is_proven(
    path: Path, text: str, match: DestructiveSourceMatch
) -> bool:
    """Pre-install noise reduction for one deliberately small ESM cleanup idiom.

    This is not the broader post-install heuristic. Require canonical builtin
    imports, an exact exclusive creator expression, unchanged bindings, lexical
    ownership, and an exact single-target cleanup. Unknown forms fail closed.
    """
    if path.suffix.lower() not in {".js", ".mjs"} or match.method != "rmSync":
        return False
    code = _mask_javascript_non_code(path, text)
    call_start = re.search(r"\bfs\s*\.\s*rmSync\s*\($", code[:match.call_end])
    if call_start is None:
        return False
    argument = _simple_call_argument(text, match.call_end)
    if argument is None or argument in {"fs", "os", "path"}:
        return False
    identifier = re.escape(argument)
    options = (
        r"\{\s*(?:recursive\s*:\s*true\s*,\s*force\s*:\s*true"
        r"|force\s*:\s*true\s*,\s*recursive\s*:\s*true)\s*,?\s*\}"
    )
    cleanup = re.compile(
        rf"\bfs\s*\.\s*rmSync\s*\(\s*(?P<target>{identifier})\s*,\s*"
        rf"{options}\s*\)"
    )
    cleanups = list(cleanup.finditer(code))
    if not any(item.start() == call_start.start() for item in cleanups):
        return False

    # Semicolons and a literal basename are intentional boundaries. In
    # particular, do not accept comma operators, fallbacks, or path arithmetic
    # after mkdtempSync, even when the expression contains that method name.
    creator = re.compile(
        rf"\bconst\s+(?P<target>{identifier})\s*=\s*"
        r"fs\s*\.\s*mkdtempSync\s*\(\s*path\s*\.\s*join\s*\(\s*"
        r"os\s*\.\s*tmpdir\s*\(\s*\)\s*,\s*"
        r"(?P<quote>['\"])[A-Za-z0-9_-]+(?P=quote)\s*\)\s*\)\s*;"
    )
    creators = [
        item for item in creator.finditer(text)
        if code[item.start():item.start() + 5] == "const"
    ]
    if len(creators) != 1 or creators[0].end() > call_start.start():
        return False
    creation = creators[0]

    def scopes_at(offset: int) -> tuple[int, ...] | None:
        stack: list[int] = []
        for position, char in enumerate(code[:offset]):
            if char == "{":
                stack.append(position)
            elif char == "}":
                if not stack:
                    return None
                stack.pop()
        return tuple(stack)

    owner_scope = scopes_at(creation.start())
    delete_scope = scopes_at(call_start.start())
    if (
        owner_scope is None or delete_scope is None
        or delete_scope[:len(owner_scope)] != owner_scope
    ):
        return False

    # Only canonical static ESM imports are proven here. Require/Promise/named
    # aliases and additional imports of mutable builtin objects stay unproven.
    import_spans: dict[str, tuple[int, int]] = {}
    accepted_import_starts: set[int] = set()
    for namespace in ("fs", "os", "path"):
        imported = list(re.finditer(
            rf"\bimport\s+(?:\*\s+as\s+)?(?P<name>{namespace})\s+from\s*"
            rf"(?P<quote>['\"])(?:node:)?{namespace}(?P=quote)\s*;",
            text,
        ))
        imported = [
            item for item in imported
            if code[item.start():item.start() + 6] == "import"
        ]
        if (
            len(imported) != 1 or imported[0].end() > creation.start()
            or scopes_at(imported[0].start()) != ()
        ):
            return False
        import_spans[namespace] = imported[0].span("name")
        accepted_import_starts.add(imported[0].start())
    # Unknown loaders can return a second reference to mutable builtin
    # objects. Only these extra statically named helpers are recognized.
    # Dynamic imports, escaped module names, module/createRequire/vm loaders
    # and dependency side effects are unproven.
    for extra in re.finditer(
        r"\bimport\s*\{\s*(?:execFileSync\s*\}\s*from\s*(['\"])(?:node:)?child_process\1"
        r"|fileURLToPath\s*\}\s*from\s*(['\"])(?:node:)?url\2)\s*;", text,
    ):
        if code[extra.start():extra.start() + 6] == "import" and scopes_at(extra.start()) == ():
            accepted_import_starts.add(extra.start())
    if any(
        item.start() not in accepted_import_starts
        and not re.match(r"\s*\.\s*meta\b", code[item.end():])
        for item in re.finditer(r"\bimport\b", code)
    ):
        return False
    if re.search(r"\b(?:require|module|global|globalThis|Reflect)\b|\\u[0-9a-fA-F{]", code):
        return False
    # Reject dynamic access to process (including getBuiltinModule and
    # mainModule) and function constructors that bypass import checks.
    for use in re.finditer(r"\bprocess\b", code):
        if re.match(r"\s*\.\s*(?:argv|env|exit|exitCode|once|removeListener)\b", code[use.end():]) is None:
            return False
    if re.search(r"(?:\.\s*constructor\b|\[\s*['\"]constructor['\"]\s*\])", text):
        return False
    for imported in re.finditer(
        r"\b(?:from\s*|(?:require|import)\s*\(\s*)"
        r"(?P<quote>['\"])(?:node:)?(?P<module>fs|os|path)(?:/promises)?(?P=quote)",
        text,
    ):
        # A builtin module import must belong to the one accepted static
        # statement. Reject alias access that could mutate its shared object.
        statement_start = text.rfind("import", 0, imported.start() + 1)
        if statement_start < 0 or not (
            statement_start < import_spans[imported.group("module")][0] < imported.end()
        ):
            return False

    # Any non-call use of a namespace could pass it to a mutator or shadow it.
    # The call whitelist also rejects __defineGetter__/prototype mutation.
    methods = {
        "fs": {"mkdtempSync", "rmSync", "mkdirSync", "writeFileSync", "readFileSync",
               "appendFileSync", "copyFileSync", "existsSync", "statSync", "lstatSync"},
        "os": {"tmpdir"},
        "path": {"join", "resolve", "dirname", "basename", "relative", "extname"},
    }
    for namespace, permitted in methods.items():
        for use in re.finditer(rf"\b{namespace}\b", code):
            if use.span() == import_spans[namespace]:
                continue
            invocation = re.match(r"\s*\.\s*(\w+)\s*\(", code[use.end():])
            if invocation is None or invocation.group(1) not in permitted:
                return False
    if re.search(r"\b(?:eval|Function|with)\s*\(", code):
        return False

    allowed_targets = {creation.span("target")}
    allowed_targets.update(item.span("target") for item in cleanups)
    derived_paths = re.compile(rf"\bpath\s*\.\s*join\s*\(\s*(?P<target>{identifier})\s*,")
    allowed_targets.update(item.span("target") for item in derived_paths.finditer(code))
    if any(
        use.span() not in allowed_targets
        for use in re.finditer(rf"\b{identifier}\b", code)
    ):
        return False

    # The generic JS masker deliberately hides templates. Do not let a
    # template interpolation hide writes to protected bindings. Pure path
    # formatting calls in log templates are the only accepted namespace use.
    for template in re.finditer(r"`(?:\\.|[^`\\])*`", text, re.DOTALL):
        value = template.group(0)
        if "${" not in value:
            continue
        if re.search(rf"\b(?:fs|os|{identifier})\b|\b(?:eval|Function|with)\s*\(", value):
            return False
        for use in re.finditer(r"\bpath\b", value):
            invocation = re.match(r"\s*\.\s*(\w+)\s*\(", value[use.end():])
            if invocation is None or invocation.group(1) not in methods["path"]:
                return False
    return True


def _node_local_cleanup_is_proven(text: str, match: DestructiveSourceMatch) -> bool:
    argument = _simple_call_argument(text, match.call_end)
    if argument is None:
        return False

    identifier = re.escape(argument)
    before = text[:match.start]
    declarations = list(
        re.finditer(
            rf"\bconst\s+{identifier}\s*=\s*(?P<expr>[^;\n]+)\s*;?",
            before,
        )
    )
    if len(declarations) != 1:
        return False
    declaration = declarations[0]
    if not _is_controlled_temp_expression(declaration.group("expr")):
        return False
    between = before[declaration.end():]
    if re.search(rf"\b{identifier}\s*=(?!=)", between):
        return False

    method = match.method.lower()
    if method in {"unlink", "unlinksync"}:
        return False

    # Only an exclusive mkdtemp result establishes ownership strongly enough
    # for recursive deletion. A fixed-name mkdir/write followed by deletion
    # can clobber and then remove a pre-existing user artifact, even when its
    # name contains "tmp" or "generated".
    expression = declaration.group("expr").strip()
    return re.search(
        r"(?:^|\b)(?:await\s+)?(?:[A-Za-z_$][A-Za-z0-9_$]*\s*\.\s*)?"
        r"mkdtemp(?:Sync)?\s*\(",
        expression,
    ) is not None


def _shell_owned_readonly_directory_cleanup_is_proven(
    text: str, match: DestructiveSourceMatch
) -> bool:
    """Recognize only an immutable exclusive directory root, never a user path."""
    line_end = text.find("\n", match.start)
    if line_end < 0:
        line_end = len(text)
    cleanup = re.fullmatch(
        r'\s*rm\s+-rf\s+--\s+"\$(?P<name>[A-Za-z_][A-Za-z0-9_]*)"\s*',
        text[match.start:line_end],
    )
    if cleanup is None:
        return False
    name = re.escape(cleanup.group("name"))
    code = re.sub(r"(?m)^\s*#[^\n]*", "", text)
    creation = list(re.finditer(
        rf"(?m)^[ \t]*{name}=\$\(mktemp -d\)[ \t]*\n[ \t]*readonly {name}[ \t]*$",
        text,
    ))
    if len(creation) != 1 or creation[0].end() >= match.start:
        return False
    # A creation inside a prior function/subshell does not establish the
    # variable used by a later global cleanup. Balance the code prefix after
    # masking literal strings and comments; unknown syntax stays unproven.
    prefix = re.sub(r"(?m)^\s*#[^\n]*", "", text[:creation[0].start()])
    # Here-documents and a multiline string can contain convincing fake
    # creator statements. Those forms before the creator stay unproven.
    if "<<" in prefix or any(prefix.count(quote) % 2 for quote in ("'", '"')):
        return False
    if_depth = len(re.findall(r"(?m)^\s*if\s+[^\n]*\bthen\b", prefix)) - len(re.findall(r"(?m)^\s*fi\b", prefix))
    if if_depth and re.search(r"(?m)^\s*(?:fi|else|elif)\b", text[creation[0].end():match.start]):
        return False
    loop_depth = len(re.findall(r"(?m)^\s*(?:for|while|until|select)\b", prefix)) - len(re.findall(r"(?m)^\s*done\b", prefix))
    case_depth = len(re.findall(r"(?m)^\s*case\b", prefix)) - len(re.findall(r"(?m)^\s*esac\b", prefix))
    if loop_depth or case_depth:
        return False
    prefix = re.sub(r'''"(?:\\.|[^"\\])*"|'[^']*' ''', "", prefix, flags=re.VERBOSE)
    prefix = re.sub(r"(?m)^[ \t]*[^\s()]+\)[ \t]*$", "", prefix)
    for opening, closing in (("(", ")"), ("{", "}")):
        if prefix.count(opening) != prefix.count(closing):
            return False
    if len(re.findall(rf"\b{name}\s*\+?=", code)) != 1:
        return False
    # Refuse dynamic sourcing, variable indirection, command/path replacement
    # and dynamic setters. readonly also blocks runtime rebinding.
    if re.search(
        rf"\b(?:(?:read|readarray|mapfile|getopts|declare|typeset|local|export)\b[^\n]*\b{name}\b"
        rf"|(?:for|select)\s+{name}\b|printf\s+-v\s+{name}\b|unset\s+{name}\b"
        r"|eval\s|source\s|hash\s|enable\s|function\s+(?:mktemp|rm|readonly)\b"
        r"|(?:mktemp|rm|readonly)\s*\(\s*\)\s*\{|alias\s+(?:mktemp|rm|readonly)=|PATH\s*=)"
        r"|(?:^|[;\n])\s*\.\s+|\$\{!|\b(?:bash|sh|zsh)\s+-c\b", code,
    ):
        return False
    # Only the exact creator, readonly declaration and quoted variable
    # expansions may mention the root. Unknown name-reference uses fail.
    remaining = text[:creation[0].start()] + " " * (creation[0].end() - creation[0].start()) + text[creation[0].end():]
    remaining = re.sub(rf'"\${name}(?:/[^"\n]*)?"', "", remaining)
    return re.search(rf"\b{name}\b", re.sub(r"(?m)^\s*#[^\n]*", "", remaining)) is None


def _shell_local_cleanup_is_proven(
    text: str, match: DestructiveSourceMatch, *, file_only: bool = False
) -> bool:
    line_end = text.find("\n", match.start)
    if line_end == -1:
        line_end = len(text)
    line = text[match.start:line_end]
    if file_only and re.fullmatch(
        r'\s*rm\s+-f\s+(?:--\s+)?"\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"\s*',
        line,
    ) is None:
        return False
    target = re.fullmatch(
        r"\s*(?:sudo\s+)?rm\s+(?:(?:-[A-Za-z]+|--)\s+)*"
        r"['\"]?\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?['\"]?\s*",
        line,
    )
    if target is None:
        return False
    variable = target.group(1)
    before = text[:match.start]
    assignments = list(
        re.finditer(
            rf"(?m)^\s*(?:export\s+)?{re.escape(variable)}\s*=\s*(?P<expr>[^\n]+)$",
            text if file_only else before,
        )
    )
    if len(assignments) != 1:
        return False
    assignment = assignments[0]
    if assignment.start() >= match.start:
        return False
    expression = assignment.group("expr").strip()
    if file_only:
        # Only argument-free mktemp creates one exclusive file here. Reject
        # any other assignment or indirect mutation, including after a trap
        # function definition but before that function can execute.
        mutation_text = re.sub(r"(?m)^\s*#[^\n]*", "", text)
        mutations = re.findall(rf"\b{re.escape(variable)}\s*\+?=", mutation_text)
        if len(mutations) != 1 or re.search(
            rf"\b(?:(?:read|readarray|mapfile|getopts|declare|typeset|local|export|readonly)"
            rf"\b[^\n]*\b{re.escape(variable)}\b|"
            rf"(?:for|select)\s+{re.escape(variable)}\b|"
            rf"printf\s+-v\s+{re.escape(variable)}\b|unset\s+{re.escape(variable)}\b|"
            r"eval\s|source\s|function\s+(?:mktemp|rm)\b|"
            r"(?:mktemp|rm)\s*\(\s*\)\s*\{|alias\s+(?:mktemp|rm)=|PATH\s*=)"
            r"|(?:^|[;\n])\s*\.\s+", mutation_text,
        ):
            return False
        return re.fullmatch(r"\$\(\s*mktemp\s*\)", expression) is not None
    if _shell_local_cleanup_is_proven(text, match, file_only=True):
        return True
    if re.fullmatch(r"\$\(\s*mktemp\s+(?:-[A-Za-z]+\s*)?\)", expression):
        return True
    return False


def _is_strict_local_cleanup(
    path: Path, text: str, match: DestructiveSourceMatch
) -> bool:
    if match.runtime == "node" and path.suffix.lower() in {
        ".cjs",
        ".js",
        ".mjs",
        ".ts",
        ".tsx",
    }:
        return _node_local_cleanup_is_proven(text, match)
    if match.runtime == "shell" and path.suffix.lower() in {"", ".bash", ".sh", ".zsh"}:
        return _shell_local_cleanup_is_proven(text, match)
    return False


def check_record(record: SkillRecord) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    searchable = f"{record.description}\n{record.body}"

    for role, owner in PROTECTED_ROLES.items():
        if record.name == owner:
            continue
        overreach_match: re.Match[str] | None = None
        for pattern in ROLE_CLAIM_PATTERNS[role]:
            for match in pattern.finditer(searchable):
                if _is_negated_role_claim(searchable, match):
                    continue
                if (
                    record.name == PROTECTED_ROLES["visual_orchestrator"]
                    and role != "visual_orchestrator"
                    and _orchestrator_assigns_protected_owner(searchable, match, owner)
                ):
                    continue
                overreach_match = match
                break
            if overreach_match is not None:
                break
        if overreach_match is not None:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "PROTECTED_ROLE_OVERREACH",
                    f"Claims protected role ‘{role}’; its sole owner is ‘{owner}’.",
                    str(record.skill_file),
                    skill=record.name or None,
                    line=_line_number(searchable, overreach_match.start()),
                )
            )

    for code, pattern, message in BROAD_DESCRIPTION_PATTERNS:
        if pattern.search(record.description):
            diagnostics.append(
                Diagnostic(
                    _severity(record),
                    code,
                    message,
                    str(record.skill_file),
                    skill=record.name or None,
                    line=1,
                )
            )

    for code, pattern, message in GLOBAL_VISUAL_MANDATE_PATTERNS:
        match = pattern.search(record.body)
        if match:
            diagnostics.append(
                Diagnostic(
                    _severity(record),
                    code,
                    message,
                    str(record.skill_file),
                    skill=record.name or None,
                    line=_line_number(record.body, match.start()),
                )
            )

    policy_value, malformed_policy = _implicit_policy(record)
    if malformed_policy:
        diagnostics.append(
            Diagnostic(
                "error",
                "INVALID_INVOCATION_POLICY",
                "policy.allow_implicit_invocation must be a YAML boolean.",
                str(record.skill_dir / "agents" / "openai.yaml"),
                skill=record.name or None,
            )
        )

    structured_explicit = _declares_explicit_only(record)
    text_explicit = _text_declares_explicit_only(record)
    if structured_explicit and policy_value is not False:
        diagnostics.append(
            Diagnostic(
                "error",
                "EXPLICIT_POLICY_MISSING",
                "Declared explicit-only Skill must set policy.allow_implicit_invocation: false in agents/openai.yaml.",
                str(record.skill_dir / "agents" / "openai.yaml"),
                skill=record.name or None,
            )
        )
    elif (
        text_explicit
        and policy_value is not False
        and not structured_explicit
    ):
        diagnostics.append(
            Diagnostic(
                "error",
                "EXPLICIT_POLICY_AMBIGUOUS",
                "Skill text implies explicit-only use, but no enforceable false invocation policy is present.",
                str(record.skill_dir / "agents" / "openai.yaml"),
                skill=record.name or None,
            )
        )

    return diagnostics


def audit(
    mode: str,
    candidate_roots: Sequence[Path] = (),
    installed_roots: Sequence[Path] = DEFAULT_ROOTS,
    allow_replace: Iterable[str] = (),
    ack_warnings: Iterable[str] = (),
) -> AuditResult:
    diagnostics: list[Diagnostic] = []
    records: list[SkillRecord] = []
    allowed = set(allow_replace)
    acknowledgements = tuple(
        sorted({code.strip() for code in ack_warnings if isinstance(code, str) and code.strip()})
    )
    scanned_roots = [str(_entry_identity(path)) for path in (*candidate_roots, *installed_roots)]

    seen_files: set[str] = set()
    root_specs = [(path, "candidate") for path in candidate_roots] + [
        (path, "installed") for path in installed_roots
    ]
    for root, origin in root_specs:
        resolved = _entry_identity(root)
        if not resolved.exists():
            diagnostics.append(
                Diagnostic(
                    "error" if origin == "candidate" else "warning",
                    "ROOT_NOT_FOUND",
                    f"{origin.capitalize()} root does not exist.",
                    str(resolved),
                )
            )
            continue
        skill_files = discover_skill_files(resolved, diagnostics)
        if origin == "candidate" and not skill_files:
            diagnostics.append(
                Diagnostic(
                    "error",
                    "NO_CANDIDATE_SKILLS",
                    "Candidate path contains no discoverable SKILL.md.",
                    str(resolved),
                )
            )
        for skill_file in skill_files:
            real = str(_entry_identity(skill_file))
            if real in seen_files:
                continue
            seen_files.add(real)
            record, parse_diagnostics = parse_skill(skill_file, origin)
            diagnostics.extend(parse_diagnostics)
            if record is not None:
                records.append(record)
                diagnostics.extend(check_record(record))
                if record.origin == "candidate":
                    diagnostics.extend(check_candidate_risk(record))
                else:
                    diagnostics.extend(check_installed_destructive_risk(record))

    by_name: dict[str, list[SkillRecord]] = defaultdict(list)
    for record in records:
        if record.name:
            by_name[record.name].append(record)
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        candidate_count = sum(item.origin == "candidate" for item in group)
        installed_count = len(group) - candidate_count
        replacement_only = name in allowed and candidate_count == 1 and installed_count == 1
        if replacement_only:
            candidate = next(item for item in group if item.origin == "candidate")
            installed = next(item for item in group if item.origin == "installed")
            if candidate.skill_dir.name == installed.skill_dir.name != name:
                diagnostics = [
                    Diagnostic(
                        "warning", item.code,
                        item.message + " Preserves the existing folder/name mismatch in this exact replacement.",
                        item.path, item.skill, item.line,
                    )
                    if item.code == "FOLDER_NAME_MISMATCH"
                    and item.path == str(candidate.skill_file)
                    else item
                    for item in diagnostics
                ]
            continue
        locations = ", ".join(sorted(str(item.skill_dir) for item in group))
        diagnostics.append(
            Diagnostic(
                "error",
                "DUPLICATE_SKILL_NAME",
                f"Skill name ‘{name}’ is defined more than once: {locations}.",
                locations,
                skill=name,
            )
        )

    for role, owner in PROTECTED_ROLES.items():
        if owner not in by_name:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "PROTECTED_OWNER_MISSING",
                    f"Protected role ‘{role}’ has no visible owner ‘{owner}’ in the scanned roots.",
                    ", ".join(scanned_roots),
                    skill=owner,
                )
            )

    return AuditResult(
        mode,
        scanned_roots,
        len(records),
        diagnostics,
        warning_acknowledgements=acknowledgements,
    )


def render_text(result: AuditResult) -> str:
    state = "PASS" if result.passed else "FAIL"
    lines = [
        f"{state} skill-governance-audit ({result.mode})",
        f"Scanned {result.skills_scanned} Skills: {result.error_count} error(s), "
        f"{result.warning_count} warning(s) ({result.unacknowledged_warning_count} unacknowledged, "
        f"{result.acknowledged_warning_count} acknowledged), {result.info_count} info item(s).",
        "Acknowledged warning codes: "
        + (", ".join(result.acknowledged_warning_codes) or "(none)"),
        "Unacknowledged warning codes: "
        + (", ".join(result.unacknowledged_warning_codes) or "(none)"),
    ]
    severity_order = {"error": 0, "warning": 1, "info": 2}
    ordered = sorted(
        result.diagnostics,
        key=lambda item: (
            severity_order.get(item.severity, 3),
            item.code,
            item.path,
            item.line or 0,
        ),
    )
    for item in ordered:
        location = item.path + (f":{item.line}" if item.line else "")
        skill = f" [{item.skill}]" if item.skill else ""
        disposition = ""
        if item.severity == "warning":
            disposition = (
                " [ACKNOWLEDGED]"
                if item.code in result.acknowledged_warning_codes
                else " [UNACKNOWLEDGED]"
            )
        lines.append(
            f"- {item.severity.upper()} {item.code}{disposition}{skill}: {item.message} ({location})"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only governance audit for candidate and installed Codex Skills."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    pre = subparsers.add_parser("pre-install", help="Audit staged candidate Skills against installed roots.")
    pre.add_argument("candidate", type=Path, help="Candidate Skill directory, package directory, or SKILL.md.")
    pre.add_argument(
        "--installed-root",
        action="append",
        type=Path,
        dest="installed_roots",
        help="Installed custom Skill root; repeat as needed. Defaults to ~/.codex/skills and ~/.agents/skills.",
    )
    pre.add_argument(
        "--allow-replace",
        action="append",
        default=[],
        metavar="SKILL_NAME",
        help="Allow one candidate to replace one installed Skill with this exact name.",
    )
    pre.add_argument(
        "--ack-warning",
        action="append",
        default=[],
        dest="ack_warnings",
        metavar="CODE",
        help="Acknowledge one exact warning code; repeat until every accepted warning is covered.",
    )
    pre.add_argument("--format", choices=("text", "json"), default="text")

    post = subparsers.add_parser("post-install", help="Audit installed custom Skill roots.")
    post.add_argument(
        "--root",
        action="append",
        type=Path,
        dest="roots",
        help="Installed custom Skill root; repeat as needed. Defaults to ~/.codex/skills and ~/.agents/skills.",
    )
    post.add_argument(
        "--ack-warning",
        action="append",
        default=[],
        dest="ack_warnings",
        metavar="CODE",
        help="Acknowledge one exact warning code; repeat until every accepted warning is covered.",
    )
    post.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "pre-install":
        installed_roots = tuple(args.installed_roots or DEFAULT_ROOTS)
        result = audit(
            "pre-install",
            candidate_roots=(args.candidate,),
            installed_roots=installed_roots,
            allow_replace=args.allow_replace,
            ack_warnings=args.ack_warnings,
        )
    else:
        roots = tuple(args.roots or DEFAULT_ROOTS)
        result = audit("post-install", installed_roots=roots, ack_warnings=args.ack_warnings)

    if args.format == "json":
        print(json.dumps(result.as_json(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
