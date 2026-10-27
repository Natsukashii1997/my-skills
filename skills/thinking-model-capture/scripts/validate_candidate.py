#!/usr/bin/env python3
"""Deterministically validate one v3 thinking-model candidate.

Historical v2 candidates remain readable while scanning the inbox for identity and
fingerprint conflicts, but they are never accepted as newly created candidates.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import stat
import sys
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo


DEFAULT_INBOX = Path("/Users/nat/Documents/思维模型库/maintenance/inbox")
MAX_LINES = 60
MAX_QUOTE_LINES = 2
MAX_QUOTE_CHARS = 200
MAX_BYTES = 65_536

FRONTMATTER_KEYS = [
    "candidate_schema_version",
    "candidate_id",
    "captured_at",
    "source_thread_id",
    "source_turn_id",
    "source_project",
    "candidate_type",
    "authorship",
    "sensitivity",
    "redaction_status",
    "redaction_categories",
    "confidence",
    "dedupe_fingerprint",
    "status",
]
ENUMS = {
    "candidate_type": {
        "新模型",
        "模型修订",
        "模型组合",
        "因果机制",
        "决策原则",
        "边界条件",
        "诊断框架",
        "重复证据",
    },
    "authorship": {"常浩原创", "人机共创", "助手推断待确认"},
    "sensitivity": {"无", "已抽象脱敏"},
    "redaction_status": {"not_needed", "abstracted_and_reviewed"},
    "confidence": {"A", "B", "C"},
    "status": {"pending"},
}
REQUIRED_SECTIONS = [
    "来源原话",
    "一句话抽象",
    "作用机制",
    "适用边界",
    "与现有模型的关系",
    "待核验点",
]

CANDIDATE_ID_RE = re.compile(r"^TM-CAND-(\d{8})-(\d{6})-([a-f0-9]{8})$")
FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(\d{6})-([a-f0-9]{8})-(.+)\.md$")
TIMESTAMP_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(?:Z|[+-]\d{2}:\d{2})$"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
REDACTION_CATEGORIES = {
    "business",
    "personnel",
    "client",
    "finance",
    "personal",
    "internal_link",
    "other",
}

PRIVACY_PATTERNS = [
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("GitHub token", re.compile(r"\bgh[oprsu]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")),
    ("Bearer credential", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}")),
    (
        "assigned credential",
        re.compile(
            r"(?i)(?:api[ _-]?key|app[ _-]?secret|client[ _-]?secret|private[ _-]?key|secret|access[ _-]?token|refresh[ _-]?token|password|cookie|authorization[ _-]?code|授权码|密码|密钥)\s*[:=：]\s*[\"']?[^\s\"']{8,}"
        ),
    ),
    (
        "private key block",
        re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.I),
    ),
    ("email address", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("mainland China phone number", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    (
        "international phone number",
        re.compile(r"(?<!\d)(?:\+|00)[1-9]\d{0,2}(?:[\s().-]*\d){7,12}(?!\d)"),
    ),
    (
        "private Feishu or Lark resource link",
        re.compile(
            r"https?://[^\s)>\]]*(?:feishu\.cn|doubao\.com|larksuite\.com|larkoffice\.com|lark\.com)/(?:wiki|docx|docs|sheets|base|drive|minutes|file|folder)/[^\s)>\]]+",
            re.I,
        ),
    ),
]


def normalize_fingerprint(value: str) -> str:
    """Return the comparison form used for exact candidate-inbox deduplication."""
    normalized = unicodedata.normalize("NFKC", value)
    parts = normalized.split("|")
    return "|".join(re.sub(r"\s+", " ", part).strip().casefold() for part in parts)


def parse_redaction_categories(value: str) -> set[str] | None:
    """Parse the fixed comma-delimited privacy categories, or return None if invalid."""
    if value == "none":
        return set()
    categories = {part.strip() for part in value.split(",")}
    if not categories or "" in categories or not categories <= REDACTION_CATEGORIES:
        return None
    return categories


def parse_frontmatter(text: str) -> tuple[dict[str, str], list[str], list[str]]:
    """Parse the deliberately small scalar-only YAML subset used by this skill."""
    errors: list[str] = []
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return {}, [], ["file must begin with a YAML frontmatter delimiter"]
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return {}, [], ["frontmatter closing delimiter is missing"]

    data: dict[str, str] = {}
    observed_keys: list[str] = []
    for line_number, line in enumerate(lines[1:closing], start=2):
        match = re.fullmatch(r"([a-z_]+):\s+(.+)", line)
        if not match:
            errors.append(f"frontmatter line {line_number} must be a single key: value scalar")
            continue
        key, value = match.groups()
        if key in data:
            errors.append(f"frontmatter key {key} is duplicated")
            continue
        data[key] = value.strip()
        observed_keys.append(key)

    missing = [key for key in FRONTMATTER_KEYS if key not in data]
    extra = [key for key in observed_keys if key not in FRONTMATTER_KEYS]
    if missing:
        errors.append(f"frontmatter is missing keys: {', '.join(missing)}")
    if extra:
        errors.append(f"frontmatter has unsupported keys: {', '.join(extra)}")
    if observed_keys != FRONTMATTER_KEYS:
        errors.append("frontmatter keys must use the fixed documented order")

    return data, lines[closing + 1 :], errors


def validate_candidate_text(
    text: str,
    candidate_path: Path,
    inbox: Path,
    *,
    check_inbox: bool = True,
) -> list[str]:
    errors: list[str] = []
    lines = text.splitlines()
    if len(lines) > MAX_LINES:
        errors.append(f"candidate must be at most {MAX_LINES} lines; found {len(lines)}")

    frontmatter, body_lines, parse_errors = parse_frontmatter(text)
    errors.extend(parse_errors)
    if parse_errors and not frontmatter:
        return errors

    if frontmatter.get("candidate_schema_version") != "3":
        errors.append(
            "candidate_schema_version must be 3; historical v2 candidates are read-only"
        )

    for field, allowed in ENUMS.items():
        if frontmatter.get(field) not in allowed:
            errors.append(f"{field} must be one of: {', '.join(sorted(allowed))}")

    candidate_match = CANDIDATE_ID_RE.fullmatch(frontmatter.get("candidate_id", ""))
    if not candidate_match:
        errors.append("candidate_id must match TM-CAND-YYYYMMDD-HHMMSS-8hex")

    timestamp_match = TIMESTAMP_RE.fullmatch(frontmatter.get("captured_at", ""))
    captured_at: datetime | None = None
    if not timestamp_match:
        errors.append("captured_at must be an ISO-8601 timestamp with timezone")
    else:
        try:
            captured_at = datetime.fromisoformat(
                frontmatter["captured_at"].replace("Z", "+00:00")
            )
        except ValueError:
            errors.append("captured_at is not a real calendar timestamp")
        else:
            shanghai_time = captured_at.astimezone(SHANGHAI)
            if (
                captured_at.utcoffset() != shanghai_time.utcoffset()
                or captured_at.replace(tzinfo=None) != shanghai_time.replace(tzinfo=None)
            ):
                errors.append(
                    "captured_at must be expressed as the actual Asia/Shanghai local time"
                )

    filename_match = FILENAME_RE.fullmatch(candidate_path.name)
    if not filename_match:
        errors.append("filename must match YYYY-MM-DD-HHMMSS-8hex-简短候选名.md")
    elif candidate_match:
        compact_date, compact_time, suffix = candidate_match.groups()
        filename_date, filename_time, filename_suffix, slug = filename_match.groups()
        if filename_date.replace("-", "") != compact_date or filename_time != compact_time:
            errors.append("filename date/time must match candidate_id")
        if filename_suffix != suffix:
            errors.append("filename suffix must match candidate_id")
        if not slug.strip() or len(slug) > 40:
            errors.append("filename candidate name must contain 1-40 characters")

    if candidate_match and captured_at is not None:
        shanghai_time = captured_at.astimezone(SHANGHAI)
        captured_compact = shanghai_time.strftime("%Y%m%d%H%M%S")
        if captured_compact != "".join(candidate_match.groups()[:2]):
            errors.append("captured_at Asia/Shanghai date/time must match candidate_id")

    fingerprint = frontmatter.get("dedupe_fingerprint", "")
    fingerprint_parts = [part.strip() for part in unicodedata.normalize("NFKC", fingerprint).split("|")]
    if len(fingerprint_parts) != 3 or any(not part for part in fingerprint_parts):
        errors.append("dedupe_fingerprint must contain exactly 核心概念|作用机制|适用边界")

    redaction_status = frontmatter.get("redaction_status")
    redaction_categories = parse_redaction_categories(
        frontmatter.get("redaction_categories", "")
    )
    if redaction_categories is None:
        errors.append(
            "redaction_categories must be none or a comma-delimited subset of: "
            + ", ".join(sorted(REDACTION_CATEGORIES))
        )
    sensitivity = frontmatter.get("sensitivity")
    if sensitivity == "无" and (
        redaction_status != "not_needed" or redaction_categories != set()
    ):
        errors.append(
            "sensitivity 无 requires redaction_status not_needed and redaction_categories none"
        )
    if sensitivity == "已抽象脱敏" and (
        redaction_status != "abstracted_and_reviewed" or not redaction_categories
    ):
        errors.append(
            "sensitivity 已抽象脱敏 requires redaction_status abstracted_and_reviewed "
            "and at least one redaction category"
        )

    h1_lines = [line for line in body_lines if line.startswith("# ")]
    if len(h1_lines) != 1 or not h1_lines[0][2:].strip():
        errors.append("body must contain exactly one non-empty H1 candidate name")

    sections = [line[3:].strip() for line in body_lines if line.startswith("## ")]
    if sections != REQUIRED_SECTIONS:
        errors.append("H2 sections must exactly match the documented names and order")

    section_positions = [index for index, line in enumerate(body_lines) if line.startswith("## ")]
    if len(section_positions) == len(REQUIRED_SECTIONS):
        for index, section_name in enumerate(REQUIRED_SECTIONS):
            start = section_positions[index] + 1
            end = section_positions[index + 1] if index + 1 < len(section_positions) else len(body_lines)
            content = [line for line in body_lines[start:end] if line.strip()]
            if not content:
                errors.append(f"section {section_name} must not be empty")

    quote_lines = [line for line in body_lines if re.match(r"^ {0,3}>", line)]
    if len(quote_lines) > MAX_QUOTE_LINES:
        errors.append(f"source quotes may use at most {MAX_QUOTE_LINES} blockquote lines")
    for index, line in enumerate(quote_lines, start=1):
        quote_content = re.sub(r"^ {0,3}> ?", "", line, count=1)
        if len(quote_content) > MAX_QUOTE_CHARS:
            errors.append(f"source quote line {index} must be at most {MAX_QUOTE_CHARS} characters")

    for label, pattern in PRIVACY_PATTERNS:
        if pattern.search(text):
            errors.append(f"candidate contains a possible {label}; abstract or redact it before capture")

    for field in ("source_thread_id", "source_turn_id", "source_project"):
        if not frontmatter.get(field, "").strip():
            errors.append(f"{field} must be non-empty; use unknown when unavailable")

    if check_inbox and inbox.exists():
        for other_path in inbox.glob("*.md"):
            try:
                if other_path == candidate_path:
                    continue
                other_stat = other_path.lstat()
                if stat.S_ISLNK(other_stat.st_mode):
                    errors.append(
                        f"candidate inbox contains an unsafe Markdown symlink: {other_path.name}"
                    )
                    continue
                if not stat.S_ISREG(other_stat.st_mode) or other_stat.st_size > MAX_BYTES:
                    errors.append(
                        f"candidate inbox contains an unsafe Markdown entry: {other_path.name}"
                    )
                    continue
                other_frontmatter, _, _ = parse_frontmatter(other_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError):
                continue
            if other_frontmatter.get("candidate_id") == frontmatter.get("candidate_id"):
                errors.append(f"candidate_id already exists in {other_path.name}")
            other_fingerprint = other_frontmatter.get("dedupe_fingerprint", "")
            if (
                fingerprint
                and other_fingerprint
                and normalize_fingerprint(other_fingerprint)
                == normalize_fingerprint(fingerprint)
            ):
                errors.append(
                    "dedupe_fingerprint exactly duplicates an existing candidate after "
                    f"normalization: {other_path.name}"
                )
            thread_id = frontmatter.get("source_thread_id")
            turn_id = frontmatter.get("source_turn_id")
            if (
                thread_id not in (None, "unknown")
                and turn_id not in (None, "unknown")
                and other_frontmatter.get("source_thread_id") == thread_id
                and other_frontmatter.get("source_turn_id") == turn_id
            ):
                errors.append(f"this source turn already has a candidate: {other_path.name}")

    return errors


def validate_candidate_file(candidate_path: Path, inbox: Path = DEFAULT_INBOX) -> list[str]:
    errors: list[str] = []
    try:
        candidate_stat = candidate_path.lstat()
    except FileNotFoundError:
        return ["candidate file does not exist"]
    except OSError as exc:
        return [f"candidate file metadata could not be read: {exc}"]
    if stat.S_ISLNK(candidate_stat.st_mode):
        return ["candidate file may not be a symlink"]
    if not stat.S_ISREG(candidate_stat.st_mode):
        return ["candidate file must be a regular file"]
    if candidate_stat.st_nlink != 1:
        return ["candidate file may not be a hard link"]
    if candidate_stat.st_size > MAX_BYTES:
        return errors + [f"candidate must be at most {MAX_BYTES} bytes"]
    try:
        resolved_inbox = inbox.resolve()
        if (
            not candidate_path.is_absolute()
            or candidate_path.parent.is_symlink()
            or candidate_path.parent.resolve() != resolved_inbox
        ):
            errors.append(f"candidate must be directly inside {inbox}")
    except OSError:
        errors.append("candidate or inbox path could not be resolved")
    try:
        text = candidate_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return errors + [f"candidate could not be read as UTF-8: {exc}"]
    return errors + validate_candidate_text(text, candidate_path, inbox)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    args = parser.parse_args()

    errors = validate_candidate_file(args.candidate, args.inbox)
    result = {"pass": not errors, "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
