#!/usr/bin/env python3
"""Read-only, local parent-thread index; never exports conversation content."""

import argparse
import json
import math
import os
import re
import sys
import time as clock
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UUID = re.compile(r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
MAX_LINE_BYTES = 16 * 1024 * 1024
KNOWN_RECORDS = {
    "response_item", "event_msg", "turn_context", "compacted",
    "world_state", "token_usage_record",
}
KNOWN_SOURCES = {"vscode", "cli", "exec"}
ORIGINATORS = {
    "Codex Desktop": "codex_desktop",
    "codex_work_desktop": "codex_work_desktop",
    "codex_exec": "codex_exec",
    "claudian": "claudian",
}


class Coverage:
    def __init__(self):
        self.counts = Counter()
        self.samples = []

    def issue(self, code, path, line=None):
        self.counts[code] += 1
        if len(self.samples) < 50:
            entry = {"code": code, "path": str(path)}
            if line is not None:
                entry["line"] = line
            self.samples.append(entry)


class BudgetEnd(Exception):
    pass


class Budget:
    def __init__(self, max_files, max_bytes, max_seconds, max_file_bytes):
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        self.max_file_bytes = max_file_bytes
        self.started = clock.monotonic()
        self.read_bytes = 0
        self.files_attempted = 0
        self.stop_reason = None

    def check(self):
        if self.read_bytes >= self.max_bytes:
            self.stop_reason = "total_byte_budget_reached"
        elif clock.monotonic() - self.started >= self.max_seconds:
            self.stop_reason = "time_budget_reached"
        if self.stop_reason:
            raise BudgetEnd(self.stop_reason)

    def readline(self, stream, size):
        self.check()
        data = stream.readline(min(size, self.max_bytes - self.read_bytes))
        self.read_bytes += len(data)
        return data


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a timezone-aware string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("timestamp requires an explicit timezone")
    return result.astimezone(timezone.utc)


def utc_iso(value):
    return value.isoformat().replace("+00:00", "Z")


def records(stream, byte_limit, path, coverage, budget):
    """Read only the opening file-size snapshot, with bounded per-line memory."""
    remaining = byte_limit
    line_number = 0
    while remaining > 0:
        raw = budget.readline(stream, min(MAX_LINE_BYTES + 1, remaining))
        if not raw:
            coverage.issue("file_truncated_during_scan", path)
            return
        remaining -= len(raw)
        line_number += 1
        if remaining > 0 and not raw.endswith(b"\n") and budget.read_bytes >= budget.max_bytes:
            budget.check()
        if len(raw) > MAX_LINE_BYTES:
            while remaining > 0 and not raw.endswith(b"\n"):
                raw = budget.readline(stream, min(MAX_LINE_BYTES + 1, remaining))
                if not raw:
                    break
                remaining -= len(raw)
            coverage.issue("oversized_record_skipped", path, line_number)
            yield line_number, None
            continue
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError("object required")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            coverage.issue("malformed_record", path, line_number)
            yield line_number, None
            continue
        yield line_number, record


def discover(roots, explicit_files, coverage, budget):
    """Do not follow symlinks or open databases, archives, hidden files or pages."""
    files = set()
    root_rows = []
    for root in roots:
        row = {"path": str(root), "status": "scanned", "jsonl_files": 0}
        root_rows.append(row)
        if budget.stop_reason:
            row["status"] = "not_scanned_budget"
            continue
        if root.is_symlink():
            row["status"] = "unsupported_symlink"
            coverage.issue("root_symlink_not_followed", root)
            continue
        if not root.is_dir():
            row["status"] = "missing_or_not_directory"
            coverage.issue("root_missing_or_not_directory", root)
            continue

        def walk_error(error):
            row["status"] = "incomplete"
            coverage.issue("directory_unreadable", error.filename or root)

        for folder, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
            try:
                budget.check()
            except BudgetEnd:
                row["status"] = "incomplete_budget"
                coverage.issue(budget.stop_reason, root)
                break
            retained = []
            for name in dirs:
                path = Path(folder) / name
                if path.is_symlink():
                    coverage.issue("directory_symlink_not_followed", path)
                elif not name.startswith("."):
                    retained.append(name)
            dirs[:] = sorted(retained)
            for name in sorted(names):
                try:
                    budget.check()
                except BudgetEnd:
                    row["status"] = "incomplete_budget"
                    coverage.issue(budget.stop_reason, root)
                    break
                if name.startswith("."):
                    continue
                path = Path(folder) / name
                if path.is_symlink():
                    coverage.issue("file_symlink_not_followed", path)
                elif path.suffix == ".jsonl" and name.startswith("rollout-"):
                    row["jsonl_files"] += 1
                    files.add(path.absolute())
                else:
                    coverage.issue("unsupported_file_not_opened", path)
            if budget.stop_reason:
                break
    for path in explicit_files:
        if path.is_symlink():
            coverage.issue("file_symlink_not_followed", path)
        elif path.suffix != ".jsonl":
            coverage.issue("unsupported_file_not_opened", path)
        else:
            files.add(path.absolute())
    return sorted(files), root_rows


def scan_file(path, start, end, excluded, coverage, inventory, budget, history_counts):
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            iterator = records(stream, before.st_size, path, coverage, budget)
            first = next(iterator, None)
            if not first or not first[1] or first[1].get("type") != "session_meta":
                coverage.issue("missing_or_invalid_session_header", path)
                return None
            meta = first[1].get("payload")
            if not isinstance(meta, dict):
                coverage.issue("invalid_session_metadata", path)
                return None
            source = meta.get("source")
            agent_path = meta.get("agent_path")
            if agent_path is not None and not isinstance(agent_path, str):
                coverage.issue("unsupported_agent_path", path)
                return None
            if ((isinstance(source, dict) and "subagent" in source)
                    or agent_path not in (None, "/root")):
                inventory["subagent_files_excluded"] += 1
                return None
            thread_id = meta.get("id")
            if not isinstance(thread_id, str) or not UUID.fullmatch(thread_id):
                coverage.issue("missing_or_unsupported_thread_id", path)
                return None
            thread_id = thread_id.lower()
            if thread_id in excluded:
                inventory["specified_thread_files_excluded"] += 1
                return None
            if not isinstance(source, str) or source not in KNOWN_SOURCES:
                coverage.issue("unknown_parent_source", path)
                return None

            inventory["parent_files_scanned"] += 1
            limits = set()
            history_mode = meta.get("history_mode")
            if history_mode == "paginated":
                limits.add("paginated_history_not_reconstructed")
            elif history_mode not in (None, "legacy", "full"):
                limits.add("unknown_history_mode")
                coverage.issue("unknown_history_mode", path)
            if meta.get("history_base") is not None:
                limits.add("referenced_history_not_reconstructed")
            if meta.get("forked_from_id") is not None:
                limits.add("fork_history_not_reconstructed")

            first_event = last_event = None
            header_end = stream.tell()
            remaining_size = before.st_size - header_end
            tail_sampled = remaining_size > budget.max_file_bytes
            if tail_sampled:
                coverage.issue("large_file_tail_sample_only", path)
                inventory["bytes_not_scanned_before_tail"] += remaining_size - budget.max_file_bytes
                stream.seek(before.st_size - budget.max_file_bytes)
                # The first tail fragment can start inside JSON; discard through its newline.
                tail_remaining = budget.max_file_bytes
                while tail_remaining:
                    fragment = budget.readline(stream, min(MAX_LINE_BYTES + 1, tail_remaining))
                    tail_remaining -= len(fragment)
                    if not fragment or fragment.endswith(b"\n"):
                        break
                iterator = records(stream, tail_remaining, path, coverage, budget)
            try:
                for line_number, record in iterator:
                    if record is None:
                        continue
                    kind = record.get("type")
                    if kind == "session_meta":
                        coverage.issue("repeated_session_header", path, line_number)
                        continue
                    if not isinstance(kind, str) or kind not in KNOWN_RECORDS:
                        coverage.issue("unsupported_record_type", path, line_number)
                    try:
                        stamp = parse_timestamp(record.get("timestamp"))
                    except (ValueError, TypeError, OverflowError):
                        coverage.issue("missing_or_invalid_event_timestamp", path, line_number)
                        continue
                    if kind == "compacted":
                        limits.add("compaction_in_window" if start <= stamp < end else "compaction_outside_window")
                    if start <= stamp < end:
                        first_event = min(first_event, stamp) if first_event else stamp
                        last_event = max(last_event, stamp) if last_event else stamp
            except BudgetEnd:
                coverage.issue(budget.stop_reason, path)
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                coverage.issue("file_changed_during_scan", path)
            for limit in sorted(limits):
                history_counts[limit] += 1
            inventory["parent_files_without_observed_window_events"] += first_event is None
            if first_event is None:
                return None
            originator = meta.get("originator")
            originator_kind = ORIGINATORS.get(originator, "other_or_unspecified") if isinstance(originator, str) else "other_or_unspecified"
            return {
                "thread_id": thread_id,
                "source_kinds": {source},
                "originator_kinds": {originator_kind},
                "first_event_at": first_event,
                "last_event_at": last_event,
                "local_files": {str(path)},
                "history_limitations": limits,
            }
    except BudgetEnd:
        coverage.issue(budget.stop_reason, path)
        return None
    except OSError:
        coverage.issue("file_unreadable", path)
        return None


def build_index(roots, explicit_files, start, end, zone_name, excluded,
                max_files=512, max_bytes=128 * 1024 * 1024,
                max_seconds=30, max_file_bytes=8 * 1024 * 1024):
    coverage = Coverage()
    inventory = Counter()
    history_counts = Counter()
    budget = Budget(max_files, max_bytes, max_seconds, max_file_bytes)
    paths, root_rows = discover(roots, explicit_files, coverage, budget)
    inventory["jsonl_files_discovered"] = len(paths)
    parents = {}
    # mtime orders work under a budget; it never filters eligibility or dates.
    def priority(path):
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return 0
    paths.sort(key=lambda path: (-priority(path), str(path)))
    for number, path in enumerate(paths):
        try:
            budget.check()
            if budget.files_attempted >= budget.max_files:
                budget.stop_reason = "file_budget_reached"
                raise BudgetEnd(budget.stop_reason)
        except BudgetEnd:
            coverage.issue(budget.stop_reason, path)
            inventory["files_not_attempted"] = len(paths) - number
            break
        budget.files_attempted += 1
        row = scan_file(path, start, end, excluded, coverage, inventory, budget, history_counts)
        if row is None:
            continue
        target = parents.get(row["thread_id"])
        if target is None:
            parents[row["thread_id"]] = row
        else:
            for field in ("source_kinds", "originator_kinds", "local_files", "history_limitations"):
                target[field].update(row[field])
            target["first_event_at"] = min(target["first_event_at"], row["first_event_at"])
            target["last_event_at"] = max(target["last_event_at"], row["last_event_at"])
    threads = []
    for row in sorted(parents.values(), key=lambda item: item["thread_id"]):
        threads.append({key: sorted(value) if isinstance(value, set)
                        else utc_iso(value) if isinstance(value, datetime) else value
                        for key, value in row.items()})
    partial = bool(coverage.counts)
    return {
        "schema_version": 1,
        "generated_at": utc_iso(datetime.now(timezone.utc)),
        "window": {"timezone": zone_name, "start_inclusive": utc_iso(start), "end_exclusive": utc_iso(end)},
        "inputs": {"roots": root_rows, "explicit_files": [str(path) for path in explicit_files],
                   "excluded_thread_ids": sorted(excluded)},
        "coverage": {
            "status": "partial" if partial else "complete_for_supported_local_files",
            "global_history_completeness": "not_established",
            "activity_assessment": "observed" if threads else "unknown" if partial else "none_observed_in_supported_local_files",
            "inventory": dict(inventory),
            "issue_counts": dict(sorted(coverage.counts.items())),
            "issue_samples": coverage.samples,
            "issue_samples_truncated": sum(coverage.counts.values()) > len(coverage.samples),
            "history_representation_counts": dict(sorted(history_counts.items())),
            "budgets": {"max_files": max_files, "max_read_bytes": max_bytes,
                        "max_seconds": max_seconds, "max_file_body_bytes": max_file_bytes,
                        "files_attempted": budget.files_attempted, "read_bytes": budget.read_bytes,
                        "elapsed_seconds": round(clock.monotonic() - budget.started, 3)},
            "limitations": [
                "This is a local metadata index, not a complete cloud/app history inventory.",
                "Use app read_thread for history content; no text, arguments, outputs, scores or failure rates are exported.",
                "Created time and mtime are not activity filters. Mtime only orders budgeted work; unattempted files remain gaps.",
                "An observed record is not proof of a user task, successful delivery or business acceptance.",
                "Budget gaps, read errors or changing files prevent a no-activity conclusion.",
                "Pagination, forks and compaction describe content limits separately; they do not alone invalidate observed in-window metadata.",
                "Tail samples are incomplete. Their reported line numbers are relative to the sampled segment.",
            ],
        },
        "parent_thread_count": len(threads),
        "threads": threads,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="只读索引本地父聊天元数据，补充 app list_threads 的可见清单；正文优先 app read_thread。",
        epilog="标准输出仅 JSON，不写文件、不联网、不修改会话。退出码：0=支持的本地文件扫描完成；3=有覆盖缺口，JSON仍可用；2=参数错误。0也不代表全平台历史完整。",
    )
    parser.add_argument("--start", required=True, help="包含此日，本地 ISO 日期 YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="不包含此日，本地 ISO 日期 YYYY-MM-DD")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="IANA 时区，默认 Asia/Shanghai")
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--root", action="append", type=Path, help="可重复；默认 ~/.codex/sessions 和 ~/.codex/archived_sessions")
    sources.add_argument("--file", action="append", type=Path, help="仅扫描明确指定的 JSONL 文件，用于小范围核验；可重复")
    parser.add_argument("--exclude-thread", action="append", default=[], help="排除当前复盘或其他指定父聊天 UUID；可重复")
    parser.add_argument("--max-files", type=int, default=512, help="最多尝试文件数，默认512；达到上限返回partial")
    parser.add_argument("--max-bytes", type=int, default=128 * 1024 * 1024, help="总读取字节上限，默认134217728（128MiB）")
    parser.add_argument("--max-seconds", type=float, default=30, help="尽力执行的时间上限，默认30秒（单次文件系统调用可能超时）")
    parser.add_argument("--max-file-bytes", type=int, default=8 * 1024 * 1024, help="单文件正文读取上限，默认8388608（8MiB）；超限读尾部并标记partial")
    args = parser.parse_args(argv)
    try:
        zone = ZoneInfo(args.timezone)
        for value in (args.start, args.end):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("日期格式必须为 YYYY-MM-DD")
        start = datetime.combine(date.fromisoformat(args.start), time.min, zone).astimezone(timezone.utc)
        end = datetime.combine(date.fromisoformat(args.end), time.min, zone).astimezone(timezone.utc)
        if start >= end:
            raise ValueError("end 必须晚于 start")
        if any(not UUID.fullmatch(value) for value in args.exclude_thread):
            raise ValueError("exclude-thread 必须为 UUID")
        if not math.isfinite(args.max_seconds) or min(args.max_files, args.max_bytes, args.max_seconds, args.max_file_bytes) <= 0:
            raise ValueError("所有预算必须大于零")
    except (ValueError, ZoneInfoNotFoundError) as error:
        parser.error(str(error))
    roots = args.root if args.root is not None else ([] if args.file else [
        Path.home() / ".codex" / "sessions", Path.home() / ".codex" / "archived_sessions",
    ])
    result = build_index(roots, args.file or [], start, end, args.timezone,
                         {value.lower() for value in args.exclude_thread}, args.max_files,
                         args.max_bytes, args.max_seconds, args.max_file_bytes)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 3 if result["coverage"]["status"] == "partial" else 0


if __name__ == "__main__":
    sys.exit(main())
