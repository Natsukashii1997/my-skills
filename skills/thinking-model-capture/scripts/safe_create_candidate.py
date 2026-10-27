#!/usr/bin/env python3
"""Reserve, validate, and release an apply_patch-compatible candidate transaction.

This script never writes, replaces, or deletes the final Markdown candidate. The
caller must create/fix/delete that file with apply_patch while holding the token.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from typing import Any

from validate_candidate import DEFAULT_INBOX, validate_candidate_file


LOCK_DIRNAME = ".thinking-model-capture.lock"
LOCK_METADATA = "reservation.json"
ARCHIVE_PAYLOAD = "lock"
ARCHIVE_STATES = frozenset({"released", "stale", "failed"})
MAX_METADATA_BYTES = 4096
DEFAULT_TTL_SECONDS = 600
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 1800
INVALID_LOCK_GRACE_SECONDS = 600


class ReservationError(RuntimeError):
    """A fail-closed reservation error suitable for user-visible JSON output."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def re_full_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _ensure_real_inbox(inbox: Path) -> Path:
    if inbox.is_symlink() or not inbox.is_dir():
        raise ReservationError("candidate inbox must be an existing real directory")
    return inbox.resolve()


def _directory_open_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise ReservationError("this platform cannot safely open reservation directories")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _same_object(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _same_stable_file(first: os.stat_result, second: os.stat_result) -> bool:
    """Compare identity plus the fields that change when metadata is rewritten."""
    return (
        _same_object(first, second)
        and first.st_mode == second.st_mode
        and first.st_nlink == second.st_nlink
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and first.st_ctime_ns == second.st_ctime_ns
    )


def _stat_at(directory_fd: int, leaf: str) -> os.stat_result | None:
    try:
        return os.stat(leaf, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _rename_noreplace(
    source_dir_fd: int,
    source_leaf: str,
    destination_dir_fd: int,
    destination_leaf: str,
) -> None:
    """Atomically rename while asking the kernel to reject any destination."""
    libc = ctypes.CDLL(None, use_errno=True)
    source = os.fsencode(source_leaf)
    destination = os.fsencode(destination_leaf)
    ctypes.set_errno(0)
    if sys.platform == "darwin":
        rename_exclusive = getattr(libc, "renameatx_np", None)
        if rename_exclusive is None:
            raise ReservationError("this platform lacks exclusive atomic rename support")
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            source_dir_fd,
            source,
            destination_dir_fd,
            destination,
            0x00000004,  # Darwin RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        rename_exclusive = getattr(libc, "renameat2", None)
        if rename_exclusive is None:
            raise ReservationError("this platform lacks exclusive atomic rename support")
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(
            source_dir_fd,
            source,
            destination_dir_fd,
            destination,
            0x00000001,  # Linux RENAME_NOREPLACE
        )
    else:
        raise ReservationError("this platform lacks exclusive atomic rename support")

    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise ReservationError("candidate lock archive payload was claimed concurrently")
        raise OSError(error_number, os.strerror(error_number))


def _assert_visible_directory(
    parent_fd: int,
    leaf: str,
    descriptor: int,
    expected_stat: os.stat_result,
    *,
    error_label: str,
) -> None:
    opened = os.fstat(descriptor)
    visible = _stat_at(parent_fd, leaf)
    if (
        visible is None
        or not stat.S_ISDIR(opened.st_mode)
        or not stat.S_ISDIR(visible.st_mode)
        or not _same_object(opened, expected_stat)
        or not _same_object(visible, expected_stat)
    ):
        raise ReservationError(f"{error_label} changed after it was pinned")


def _open_real_inbox(inbox: Path) -> tuple[Path, int]:
    resolved = _ensure_real_inbox(inbox)
    try:
        descriptor = os.open(resolved, _directory_open_flags())
    except OSError as exc:
        raise ReservationError(f"candidate inbox could not be opened safely: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        visible = os.stat(resolved, follow_symlinks=False)
        if not stat.S_ISDIR(opened.st_mode) or not _same_object(opened, visible):
            raise ReservationError("candidate inbox changed while it was being opened")
    except (OSError, ReservationError):
        os.close(descriptor)
        raise
    return resolved, descriptor


def _open_real_directory_at(
    parent_fd: int,
    leaf: str,
    *,
    error_label: str,
    expected_stat: os.stat_result | None = None,
) -> tuple[int, os.stat_result]:
    before = _stat_at(parent_fd, leaf)
    if before is None or not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise ReservationError(f"{error_label} is not a real directory")
    if expected_stat is not None and not _same_object(before, expected_stat):
        raise ReservationError(f"{error_label} changed after exclusive creation")
    try:
        descriptor = os.open(leaf, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as exc:
        raise ReservationError(f"{error_label} could not be opened safely: {exc}") from exc
    try:
        opened = os.fstat(descriptor)
        after = _stat_at(parent_fd, leaf)
        if (
            after is None
            or not stat.S_ISDIR(opened.st_mode)
            or not _same_object(before, opened)
            or not _same_object(opened, after)
            or (expected_stat is not None and not _same_object(opened, expected_stat))
        ):
            raise ReservationError(f"{error_label} changed while it was being opened")
    except (OSError, ReservationError):
        os.close(descriptor)
        raise
    return descriptor, opened


def _ensure_target(candidate_path: Path, inbox: Path) -> None:
    resolved_inbox = inbox.resolve()
    if (
        not candidate_path.is_absolute()
        or candidate_path.parent.is_symlink()
        or candidate_path.parent.resolve() != resolved_inbox
    ):
        raise ReservationError(f"candidate must be directly inside {inbox}")
    if candidate_path.name.startswith(".") or candidate_path.suffix != ".md":
        raise ReservationError("candidate target must be a non-hidden Markdown file")


def _validate_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise ReservationError("reservation metadata does not match the fixed schema")
    required = {"version", "token_hash", "target_name", "created_at", "expires_at", "pid"}
    if set(metadata) != required or metadata.get("version") != 1:
        raise ReservationError("reservation metadata does not match the fixed schema")
    if not re_full_hex(metadata.get("token_hash"), 64):
        raise ReservationError("reservation token hash is invalid")
    target_name = metadata.get("target_name")
    if (
        not isinstance(target_name, str)
        or not target_name
        or Path(target_name).name != target_name
        or target_name.startswith(".")
        or Path(target_name).suffix != ".md"
    ):
        raise ReservationError("reservation target is invalid")
    if not isinstance(metadata.get("pid"), int) or metadata["pid"] <= 0:
        raise ReservationError("reservation pid is invalid")
    for key in ("created_at", "expires_at"):
        try:
            parsed = datetime.fromisoformat(str(metadata[key]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReservationError(f"reservation {key} is invalid") from exc
        if parsed.tzinfo is None:
            raise ReservationError(f"reservation {key} must carry a timezone")
    return metadata


def _read_metadata(lock_fd: int) -> tuple[dict[str, Any], os.stat_result, str]:
    before = _stat_at(lock_fd, LOCK_METADATA)
    if (
        before is None
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise ReservationError("reservation metadata is missing or unsafe")
    try:
        descriptor = os.open(
            LOCK_METADATA,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=lock_fd,
        )
        try:
            opened = os.fstat(descriptor)
            after = _stat_at(lock_fd, LOCK_METADATA)
            if (
                after is None
                or not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or not _same_stable_file(before, opened)
                or not _same_stable_file(opened, after)
            ):
                raise ReservationError("reservation metadata changed while it was being opened")
            payload = bytearray()
            while len(payload) <= MAX_METADATA_BYTES:
                chunk = os.read(descriptor, MAX_METADATA_BYTES + 1 - len(payload))
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) > MAX_METADATA_BYTES:
                raise ReservationError("reservation metadata exceeds the size limit")
            final_opened = os.fstat(descriptor)
            final_visible = _stat_at(lock_fd, LOCK_METADATA)
            if (
                final_visible is None
                or not _same_stable_file(opened, final_opened)
                or not _same_stable_file(final_opened, final_visible)
            ):
                raise ReservationError("reservation metadata changed while it was being read")
        finally:
            os.close(descriptor)
        metadata = json.loads(bytes(payload).decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReservationError(f"reservation metadata is unreadable: {exc}") from exc
    return _validate_metadata(metadata), final_opened, hashlib.sha256(payload).hexdigest()


def _is_expired(metadata: dict[str, Any], now: datetime) -> bool:
    if now.tzinfo is None:
        raise ReservationError("reservation clock must carry a timezone")
    expires_at = datetime.fromisoformat(str(metadata["expires_at"]).replace("Z", "+00:00"))
    return expires_at <= now


@dataclass
class _LockHandle:
    inbox_fd: int
    lock_fd: int
    lock_stat: os.stat_result
    metadata: dict[str, Any] | None = None
    metadata_stat: os.stat_result | None = None
    metadata_digest: str | None = None
    exclusively_created: bool = False

    def close(self) -> None:
        os.close(self.lock_fd)
        os.close(self.inbox_fd)


def _open_lock(inbox_fd: int) -> _LockHandle:
    lock_fd, lock_stat = _open_real_directory_at(
        inbox_fd,
        LOCK_DIRNAME,
        error_label="candidate lock path",
    )
    return _LockHandle(inbox_fd=inbox_fd, lock_fd=lock_fd, lock_stat=lock_stat)


def _metadata_is_current(handle: _LockHandle) -> bool:
    if handle.metadata_stat is None:
        return True
    try:
        metadata, visible, digest = _read_metadata(handle.lock_fd)
    except ReservationError:
        return False
    return (
        handle.metadata is not None
        and handle.metadata_digest is not None
        and metadata == handle.metadata
        and digest == handle.metadata_digest
        and _same_stable_file(visible, handle.metadata_stat)
    )


def _assert_lock_identity(handle: _LockHandle) -> None:
    opened = os.fstat(handle.lock_fd)
    visible = _stat_at(handle.inbox_fd, LOCK_DIRNAME)
    if (
        visible is None
        or not stat.S_ISDIR(visible.st_mode)
        or not _same_object(opened, handle.lock_stat)
        or not _same_object(visible, handle.lock_stat)
        or not _metadata_is_current(handle)
    ):
        raise ReservationError("candidate lock changed after ownership verification")


def _archive_lock(handle: _LockHandle, state: str) -> str:
    """Move the verified lock into an exclusive audit container; never delete it."""
    if state not in ARCHIVE_STATES:
        raise ReservationError("candidate lock archive state is invalid")
    if state == "failed" and not handle.exclusively_created:
        raise ReservationError("only this reservation's exclusively created lock may be archived as failed")
    _assert_lock_identity(handle)

    archive_leaf = f"{LOCK_DIRNAME}.{state}-{secrets.token_hex(16)}"
    if _stat_at(handle.inbox_fd, archive_leaf) is not None:
        raise ReservationError("candidate lock archive destination already exists")
    try:
        os.mkdir(archive_leaf, mode=0o700, dir_fd=handle.inbox_fd)
    except FileExistsError as exc:
        raise ReservationError("candidate lock archive destination was claimed concurrently") from exc
    except OSError as exc:
        raise ReservationError(f"candidate lock archive destination could not be created: {exc}") from exc

    created_archive = _stat_at(handle.inbox_fd, archive_leaf)
    if created_archive is None or not stat.S_ISDIR(created_archive.st_mode):
        raise ReservationError("candidate lock archive destination changed after exclusive creation")

    archive_fd, _ = _open_real_directory_at(
        handle.inbox_fd,
        archive_leaf,
        error_label="candidate lock archive destination",
        expected_stat=created_archive,
    )
    try:
        if _stat_at(archive_fd, ARCHIVE_PAYLOAD) is not None:
            raise ReservationError("candidate lock archive payload already exists")
        _assert_lock_identity(handle)
        _assert_visible_directory(
            handle.inbox_fd,
            archive_leaf,
            archive_fd,
            created_archive,
            error_label="candidate lock archive destination",
        )
        _rename_noreplace(
            handle.inbox_fd,
            LOCK_DIRNAME,
            archive_fd,
            ARCHIVE_PAYLOAD,
        )
        _assert_visible_directory(
            handle.inbox_fd,
            archive_leaf,
            archive_fd,
            created_archive,
            error_label="candidate lock archive destination",
        )
        moved = _stat_at(archive_fd, ARCHIVE_PAYLOAD)
        if (
            moved is None
            or not stat.S_ISDIR(moved.st_mode)
            or stat.S_ISLNK(moved.st_mode)
            or not _same_object(moved, handle.lock_stat)
            or not _metadata_is_current(handle)
        ):
            raise ReservationError("archived candidate lock failed its post-rename identity proof")
    except OSError as exc:
        raise ReservationError(f"candidate lock could not be atomically archived: {exc}") from exc
    finally:
        os.close(archive_fd)
    return archive_leaf


def _recover_if_stale(inbox_fd: int, now: datetime) -> bool:
    """Return True after recovering a stale lock, False when an active lock remains."""
    if _stat_at(inbox_fd, LOCK_DIRNAME) is None:
        return True
    handle = _open_lock(inbox_fd)
    try:
        try:
            metadata, metadata_stat, metadata_digest = _read_metadata(handle.lock_fd)
            handle.metadata = metadata
            handle.metadata_stat = metadata_stat
            handle.metadata_digest = metadata_digest
        except ReservationError:
            age_seconds = max(0.0, now.timestamp() - handle.lock_stat.st_mtime)
            if age_seconds < INVALID_LOCK_GRACE_SECONDS:
                raise ReservationError(
                    "candidate lock metadata is invalid but still within the recovery grace period"
                )
            _archive_lock(handle, "stale")
            return True

        if not _is_expired(metadata, now):
            return False
        if _stat_at(inbox_fd, metadata["target_name"]) is not None:
            raise ReservationError(
                "expired reservation target still exists; delete it with apply_patch "
                "before recovering the stale lock"
            )
        _archive_lock(handle, "stale")
        return True
    finally:
        os.close(handle.lock_fd)


def reserve_candidate(
    candidate_path: Path,
    inbox: Path = DEFAULT_INBOX,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> str:
    """Atomically reserve the whole inbox and return the one-time release token."""
    inbox = Path(inbox)
    candidate_path = Path(candidate_path)
    resolved_inbox, inbox_fd = _open_real_inbox(inbox)
    try:
        _ensure_target(candidate_path, resolved_inbox)
        if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
            raise ReservationError(
                f"reservation TTL must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS} seconds"
            )
        if _stat_at(inbox_fd, candidate_path.name) is not None:
            raise ReservationError("candidate destination already exists; refusing to overwrite it")

        current_time = now or _utc_now()
        if current_time.tzinfo is None:
            raise ReservationError("reservation clock must carry a timezone")
        for _ in range(3):
            if _stat_at(inbox_fd, LOCK_DIRNAME) is not None:
                if not _recover_if_stale(inbox_fd, current_time):
                    raise ReservationError("candidate inbox already has an active reservation")
            try:
                os.mkdir(LOCK_DIRNAME, mode=0o700, dir_fd=inbox_fd)
                created_lock = _stat_at(inbox_fd, LOCK_DIRNAME)
                if created_lock is None or not stat.S_ISDIR(created_lock.st_mode):
                    raise ReservationError("newly created candidate lock changed before it could be pinned")
                break
            except FileExistsError:
                continue
        else:
            raise ReservationError("could not reserve the candidate inbox after concurrent retries")

        lock_fd, lock_stat = _open_real_directory_at(
            inbox_fd,
            LOCK_DIRNAME,
            error_label="newly created candidate lock",
            expected_stat=created_lock,
        )
        handle = _LockHandle(
            inbox_fd=inbox_fd,
            lock_fd=lock_fd,
            lock_stat=lock_stat,
            exclusively_created=True,
        )
        token = secrets.token_hex(32)
        metadata = {
            "version": 1,
            "token_hash": _token_hash(token),
            "target_name": candidate_path.name,
            "created_at": current_time.isoformat(),
            "expires_at": (current_time + timedelta(seconds=ttl_seconds)).isoformat(),
            "pid": os.getpid(),
        }
        try:
            _write_metadata_exclusive(handle.lock_fd, metadata)
            verified_metadata, metadata_stat, metadata_digest = _read_metadata(handle.lock_fd)
            handle.metadata = verified_metadata
            handle.metadata_stat = metadata_stat
            handle.metadata_digest = metadata_digest
            _assert_lock_identity(handle)
        except (OSError, ReservationError) as exc:
            try:
                _archive_lock(handle, "failed")
            except ReservationError as archive_exc:
                raise ReservationError(
                    "could not persist the candidate reservation and its owned lock "
                    f"could not be archived safely: {archive_exc}"
                ) from exc
            raise ReservationError(f"could not persist the candidate reservation: {exc}") from exc
        finally:
            os.close(handle.lock_fd)
        return token
    finally:
        os.close(inbox_fd)


def _write_metadata_exclusive(lock_fd: int, metadata: dict[str, Any]) -> None:
    descriptor = os.open(
        LOCK_METADATA,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0),
        0o600,
        dir_fd=lock_fd,
    )
    try:
        payload = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("reservation metadata write made no progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_reservation(
    candidate_path: Path,
    token: str,
    inbox: Path,
    *,
    now: datetime | None = None,
) -> _LockHandle:
    resolved_inbox, inbox_fd = _open_real_inbox(inbox)
    handle: _LockHandle | None = None
    try:
        _ensure_target(candidate_path, resolved_inbox)
        handle = _open_lock(inbox_fd)
        metadata, metadata_stat, metadata_digest = _read_metadata(handle.lock_fd)
        handle.metadata = metadata
        handle.metadata_stat = metadata_stat
        handle.metadata_digest = metadata_digest
        if metadata["target_name"] != candidate_path.name:
            raise ReservationError("reservation target does not match this candidate")
        if not re_full_hex(token, 64):
            raise ReservationError(
                "reservation token must be exactly 64 lowercase hexadecimal characters"
            )
        if not hmac.compare_digest(metadata["token_hash"], _token_hash(token)):
            raise ReservationError("reservation token is invalid")
        if _is_expired(metadata, now or _utc_now()):
            raise ReservationError("candidate reservation has expired; recover it before retrying")
        _assert_lock_identity(handle)
        return handle
    except Exception:
        if handle is not None:
            os.close(handle.lock_fd)
        os.close(inbox_fd)
        raise


def _release_verified_lock(handle: _LockHandle) -> None:
    _archive_lock(handle, "released")


def validate_and_release(
    candidate_path: Path,
    token: str,
    inbox: Path = DEFAULT_INBOX,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Validate the reserved candidate and release only when every check passes."""
    handle = _verify_reservation(candidate_path, token, inbox, now=now)
    try:
        errors = validate_candidate_file(candidate_path, inbox)
        if errors:
            return errors
        _release_verified_lock(handle)
        return []
    finally:
        handle.close()


def abort_reservation(
    candidate_path: Path,
    token: str,
    inbox: Path = DEFAULT_INBOX,
    *,
    now: datetime | None = None,
) -> None:
    """Release after failure only when apply_patch has removed the final candidate."""
    handle = _verify_reservation(candidate_path, token, inbox, now=now)
    try:
        if _stat_at(handle.inbox_fd, candidate_path.name) is not None:
            raise ReservationError(
                "candidate still exists; delete it with apply_patch before aborting the reservation"
            )
        _release_verified_lock(handle)
    finally:
        handle.close()


def _emit(pass_: bool, action: str, **details: Any) -> int:
    print(json.dumps({"pass": pass_, "action": action, **details}, ensure_ascii=False, indent=2))
    return 0 if pass_ else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    subparsers = parser.add_subparsers(dest="action", required=True)

    reserve_parser = subparsers.add_parser("reserve")
    reserve_parser.add_argument("candidate", type=Path)
    reserve_parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS)

    validate_parser = subparsers.add_parser("validate-release")
    validate_parser.add_argument("candidate", type=Path)
    validate_parser.add_argument("--token", required=True)

    abort_parser = subparsers.add_parser("abort")
    abort_parser.add_argument("candidate", type=Path)
    abort_parser.add_argument("--token", required=True)

    args = parser.parse_args()
    try:
        if args.action == "reserve":
            token = reserve_candidate(args.candidate, args.inbox, ttl_seconds=args.ttl)
            return _emit(True, args.action, token=token, expires_in_seconds=args.ttl)
        if args.action == "validate-release":
            errors = validate_and_release(args.candidate, args.token, args.inbox)
            return _emit(not errors, args.action, released=not errors, errors=errors)
        abort_reservation(args.candidate, args.token, args.inbox)
        return _emit(True, args.action, released=True)
    except ReservationError as exc:
        return _emit(False, args.action, errors=[str(exc)])


if __name__ == "__main__":
    sys.exit(main())
