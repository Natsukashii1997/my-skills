#!/usr/bin/env python3
"""Read-only GET笔记 OpenAPI client for the 路觅带教 bot."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


BASE_URL = "https://openapi.biji.com/open/api/v1"
KEYCHAIN_SERVICE = os.environ.get("GET_NOTES_KEYCHAIN_SERVICE", "lumiedu-get-notes")
API_KEY_ACCOUNT = "api-key"
CLIENT_ID_ACCOUNT = "client-id"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 4
MAX_OUTPUT_CHARS = 50_000


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SSL_CONTEXT = _ssl_context()


class GetNotesError(RuntimeError):
    pass


def _redact(value: str) -> str:
    value = re.sub(r"gk_live_[A-Za-z0-9._-]+", "[REDACTED_API_KEY]", value)
    value = re.sub(r"cli_[A-Za-z0-9_-]{12,}", "[REDACTED_CLIENT_ID]", value)
    return value


def _sanitize_text(value: Any) -> str:
    """Remove credentials and URL query strings that may contain signed access."""
    text = _redact(str(value))

    def strip_url_query(match: re.Match[str]) -> str:
        url = match.group(0)
        base = url.split("?", 1)[0].split("#", 1)[0]
        return f"{base}?[REDACTED_QUERY]" if "?" in url else base

    return re.sub(r"https?://[^\s<>\"']+", strip_url_query, text)


def _sanitize_output(value: Any) -> Any:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, list):
        return [_sanitize_output(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_output(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_output(item) for key, item in value.items()}
    return value


def _max_chars_arg(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--max-chars 必须是整数") from exc
    if parsed < 0 or parsed > MAX_OUTPUT_CHARS:
        raise argparse.ArgumentTypeError(
            f"--max-chars 必须在 0 到 {MAX_OUTPUT_CHARS} 之间"
        )
    return parsed


def _credential(account: str, env_name: str) -> str:
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        return env_value
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                account,
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise GetNotesError(
            f"未找到 GET 凭据：请在 macOS Keychain 服务 {KEYCHAIN_SERVICE!r} 中配置账户 {account!r}"
        ) from exc
    value = result.stdout.strip()
    if not value:
        raise GetNotesError(f"GET 凭据为空：{account}")
    return value


class Client:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.api_key = _credential(API_KEY_ACCOUNT, "GET_NOTES_API_KEY")
        self.client_id = _credential(CLIENT_ID_ACCOUNT, "GET_NOTES_CLIENT_ID")
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{BASE_URL}{path}"
        if query:
            clean_query = {k: str(v) for k, v in query.items() if v is not None}
            url = f"{url}?{urllib.parse.urlencode(clean_query)}"
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": self.api_key,
            "X-Client-ID": self.client_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "lumiedu-get-notes-retrieval/1.0",
        }

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            req = urllib.request.Request(url, data=body, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=SSL_CONTEXT) as response:
                    raw = response.read().decode("utf-8")
                envelope = json.loads(raw)
                if not envelope.get("success") or "data" not in envelope:
                    err = envelope.get("error") or {}
                    message = str(err.get("message") or err.get("reason") or "GET API 请求失败")
                    raise GetNotesError(_sanitize_text(message))
                return envelope["data"]
            except urllib.error.HTTPError as exc:
                last_error = exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == MAX_RETRIES - 1:
                    raise GetNotesError(f"GET API HTTP {exc.code}") from exc
                retry_after = exc.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(wait, 30))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, GetNotesError) as exc:
                last_error = exc
                if isinstance(exc, GetNotesError) or attempt == MAX_RETRIES - 1:
                    raise GetNotesError(_sanitize_text(str(exc))) from exc
                time.sleep(min(2**attempt, 30))
        raise GetNotesError(_sanitize_text(str(last_error or "GET API 请求失败")))

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        data = self.request("POST", "/resource/recall", payload={"query": query, "top_k": top_k})
        return list(data.get("results") or [])

    def detail(self, note_id: str) -> dict[str, Any]:
        data = self.request(
            "GET",
            "/resource/note/detail",
            query={"id": note_id, "image_quality": "original"},
        )
        return dict(data.get("note") or data)

    def list_all(self, max_pages: int = 100) -> list[dict[str, Any]]:
        cursor = "0"
        seen: set[str] = set()
        notes: list[dict[str, Any]] = []
        for _ in range(max_pages):
            data = self.request("GET", "/resource/note/list", query={"since_id": cursor})
            batch = list(data.get("notes") or [])
            for item in batch:
                note_id = _note_id(item)
                if note_id and note_id in seen:
                    continue
                if note_id:
                    seen.add(note_id)
                notes.append(item)
            if not data.get("has_more"):
                return notes
            next_cursor = str(data.get("next_cursor") or "").strip()
            if not next_cursor or next_cursor == cursor:
                ids = [int(nid) for nid in (_note_id(item) for item in batch) if nid and nid.isdigit()]
                if not ids:
                    raise GetNotesError("GET 笔记列表游标无法推进")
                next_cursor = str(max(ids) + 1)
            cursor = next_cursor
        raise GetNotesError(f"GET 笔记列表超过安全分页上限 {max_pages}")

    def quota(self) -> dict[str, Any]:
        data = self.request("GET", "/resource/rate-limit/quota")
        return dict(data)


def _note_id(note: dict[str, Any]) -> str:
    raw = note.get("id") or note.get("note_id") or note.get("uid") or ""
    return str(raw).strip()


def _dedupe_search_results(
    items: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """Keep search rank while preventing one note from occupying several slots."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in items:
        note_id = _note_id(item)
        if note_id and note_id in seen:
            continue
        if note_id:
            seen.add(note_id)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _parse_time(value: Any) -> dt.datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return parsed.astimezone(dt.timezone.utc)


def _query_terms(query: str) -> list[str]:
    terms: set[str] = set()
    for latin in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]{1,}", query.lower()):
        terms.add(latin)
    for chunk in re.findall(r"[\u3400-\u9fff]+", query):
        if len(chunk) <= 8:
            terms.add(chunk)
        for width in (2, 3, 4):
            if len(chunk) >= width:
                for i in range(len(chunk) - width + 1):
                    terms.add(chunk[i : i + width])
    stop = {
        "什么",
        "怎么",
        "如何",
        "这个",
        "那个",
        "我们",
        "他们",
        "问题",
        "是否",
        "可以",
        "需要",
        "进行",
    }
    return sorted((term for term in terms if term not in stop), key=len, reverse=True)[:80]


def _bounded_excerpt(text: str, query: str, max_chars: int) -> str:
    clean = text.strip()
    if not clean or max_chars <= 0:
        return ""
    if len(clean) <= max_chars:
        return clean
    terms = _query_terms(query)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", clean) if p.strip()]
    scored: list[tuple[int, int, str]] = []
    for index, paragraph in enumerate(paragraphs):
        lower = paragraph.lower()
        score = sum((len(term) ** 2) * lower.count(term.lower()) for term in terms)
        scored.append((score, index, paragraph))
    positive = [item for item in scored if item[0] > 0]
    if not positive:
        return clean[:max_chars] + "\n\n[后文省略]"
    positive.sort(key=lambda item: (-item[0], item[1]))
    chosen: list[tuple[int, str]] = []
    used = 0
    for _, index, paragraph in positive:
        remaining = max_chars - used
        if remaining <= 0:
            break
        piece = paragraph[:remaining]
        chosen.append((index, piece))
        used += len(piece) + 2
    chosen.sort(key=lambda item: item[0])
    return "\n\n[中间省略]\n\n".join(piece for _, piece in chosen)


def _safe_detail(detail: dict[str, Any], query: str, max_chars: int) -> dict[str, Any]:
    note_id = _note_id(detail)
    content = str(detail.get("content") or "").strip()
    ref_content = str(detail.get("ref_content") or "").strip()
    audio = detail.get("audio") if isinstance(detail.get("audio"), dict) else {}
    transcript = str(audio.get("original") or "").strip()
    combined_parts = []
    if content:
        combined_parts.append(f"[笔记正文]\n{content}")
    if ref_content and ref_content != content:
        combined_parts.append(f"[引用内容]\n{ref_content}")
    if transcript:
        combined_parts.append(f"[录音转写]\n{transcript}")
    combined = "\n\n".join(combined_parts)
    tags = []
    for item in detail.get("tags") or []:
        if isinstance(item, dict) and item.get("name"):
            tags.append(str(item["name"]))
        elif isinstance(item, str):
            tags.append(item)
    return {
        "source_id": f"get:{note_id}" if note_id else "get:unknown",
        "note_id": note_id,
        "title": str(detail.get("title") or "未命名"),
        "note_type": str(detail.get("note_type") or ""),
        "created_at": detail.get("created_at"),
        "updated_at": detail.get("updated_at"),
        "tags": tags,
        "has_full_transcript": bool(transcript),
        "transcript_chars": len(transcript),
        "content_chars": len(content),
        "context_excerpt": _bounded_excerpt(combined, query, max_chars),
    }


def _safe_search_result(item: dict[str, Any]) -> dict[str, Any]:
    note_id = _note_id(item)
    snippet = str(item.get("content") or "")
    return {
        "source_id": f"get:{note_id}" if note_id else "get:unknown",
        "note_id": note_id,
        "note_type": item.get("note_type"),
        "title": item.get("title"),
        "created_at": item.get("created_at"),
        "snippet": snippet[:1600],
    }


def _safe_quota(quota: dict[str, Any]) -> dict[str, Any]:
    allowed = {}
    for name in ("read", "write", "write_note"):
        value = quota.get(name)
        if isinstance(value, dict):
            allowed[name] = value
    return allowed


def command_doctor(args: argparse.Namespace) -> dict[str, Any]:
    client = Client(timeout=args.timeout)
    notes = client.request("GET", "/resource/note/list", query={"since_id": "0"})
    output: dict[str, Any] = {
        "status": "ok",
        "credential_store": f"macOS Keychain:{KEYCHAIN_SERVICE}",
        "first_page_count": len(notes.get("notes") or []),
        "has_more": bool(notes.get("has_more")),
    }
    try:
        output["quota"] = _safe_quota(client.quota())
    except GetNotesError as exc:
        output["quota_status"] = f"unavailable: {_redact(str(exc))}"
    if args.probe_query:
        results = client.search(args.probe_query, 1)
        probe: dict[str, Any] = {"search_results": len(results)}
        if results:
            note_id = _note_id(results[0])
            if note_id:
                detail = client.detail(note_id)
                audio = detail.get("audio") if isinstance(detail.get("audio"), dict) else {}
                transcript = str(audio.get("original") or "")
                probe.update(
                    {
                        "detail_readable": True,
                        "has_full_transcript": bool(transcript.strip()),
                        "transcript_chars": len(transcript),
                    }
                )
        output["probe"] = probe
    return output


def command_search(args: argparse.Namespace) -> dict[str, Any]:
    client = Client(timeout=args.timeout)
    fetch_k = min(10, max(args.top_k, args.detail_top, args.top_k * 2))
    raw_results = client.search(args.query, fetch_k)
    results = _dedupe_search_results(raw_results, args.top_k)
    output: dict[str, Any] = {
        "query": args.query,
        "result_count": len(results),
        "raw_result_count": len(raw_results),
        "duplicate_result_count": len(raw_results) - len(_dedupe_search_results(raw_results, len(raw_results))),
        "results": [_safe_search_result(item) for item in results],
        "details": [],
    }
    for item in results[: args.detail_top]:
        note_id = _note_id(item)
        if not note_id:
            continue
        detail = client.detail(note_id)
        output["details"].append(_safe_detail(detail, args.query, args.max_chars))
    return output


def command_detail(args: argparse.Namespace) -> dict[str, Any]:
    client = Client(timeout=args.timeout)
    detail = client.detail(args.id)
    return _safe_detail(detail, args.query or "", args.max_chars)


def command_changes(args: argparse.Namespace) -> dict[str, Any]:
    after = _parse_time(args.after)
    if after is None:
        raise GetNotesError("--after 必须是 ISO 时间或 YYYY-MM-DD HH:MM:SS")
    client = Client(timeout=args.timeout)
    all_notes = client.list_all(max_pages=args.max_pages)
    changed = []
    for note in all_notes:
        remote = _parse_time(note.get("updated_at") or note.get("created_at"))
        if remote is not None and remote > after:
            changed.append(note)
    changed.sort(
        key=lambda item: _parse_time(item.get("updated_at") or item.get("created_at"))
        or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    )
    truncated = len(changed) > args.max_notes
    selected = changed[: args.max_notes]
    items = []
    for note in selected:
        items.append(
            {
                "source_id": f"get:{_note_id(note)}",
                "note_id": _note_id(note),
                "title": note.get("title"),
                "note_type": note.get("note_type"),
                "created_at": note.get("created_at"),
                "updated_at": note.get("updated_at"),
                "tags": [
                    tag.get("name") if isinstance(tag, dict) else str(tag)
                    for tag in (note.get("tags") or [])
                ],
            }
        )
    return {
        "status": "partial" if truncated else "ok",
        "after": args.after,
        "scanned_count": len(all_notes),
        "changed_count": len(changed),
        "returned_count": len(items),
        "truncated": truncated,
        "cursor_advance_allowed": not truncated,
        "items": items,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only GET笔记 retrieval client")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Verify credentials and read access")
    doctor.add_argument("--probe-query", default="")
    doctor.set_defaults(handler=command_doctor)

    search = subparsers.add_parser("search", help="Semantic search across all GET notes")
    search.add_argument("--query", required=True)
    search.add_argument("--top-k", type=int, choices=range(1, 11), default=5)
    search.add_argument("--detail-top", type=int, choices=range(0, 11), default=3)
    search.add_argument("--max-chars", type=_max_chars_arg, default=8000)
    search.set_defaults(handler=command_search)

    detail = subparsers.add_parser("detail", help="Read one note and its full transcript")
    detail.add_argument("--id", required=True)
    detail.add_argument("--query", default="")
    detail.add_argument("--max-chars", type=_max_chars_arg, default=20000)
    detail.set_defaults(handler=command_detail)

    changes = subparsers.add_parser("changes", help="List notes changed after a timestamp")
    changes.add_argument("--after", required=True)
    changes.add_argument("--max-pages", type=int, default=100)
    changes.add_argument("--max-notes", type=int, default=500)
    changes.set_defaults(handler=command_changes)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
        print(json.dumps(_sanitize_output(result), ensure_ascii=False, indent=2))
        return 0
    except GetNotesError as exc:
        print(
            json.dumps(
                {"status": "error", "error": _sanitize_text(str(exc))},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:  # defensive boundary: never print credentials or headers
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": _sanitize_text(f"{type(exc).__name__}: {exc}"),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
