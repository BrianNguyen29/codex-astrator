#!/usr/bin/env python3
"""Safe, dependency-free installer for the codex-astrator community bundle.

The command intentionally defaults to a preview.  It only writes after
``--apply`` and never discovers or modifies a real home directory implicitly.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable


MARKER_BEGIN = "# >>> CODEX-ASTRATOR MANAGED BLOCK >>>"
MARKER_END = "# <<< CODEX-ASTRATOR MANAGED BLOCK <<<"
MANIFEST_NAME = "astrator-manifest.json"
BACKUP_DIR_NAME = ".astrator-backups"
BACKUP_IGNORE_CONTENT = b"*\n"
MANIFEST_VERSION = 2
LEGACY_MANIFEST_VERSIONS = {1}
_FAIL_AFTER = None
TablePath = tuple[str, ...]


class InstallerError(Exception):
    """A safe, user-actionable installation error."""


class ConflictError(InstallerError):
    """An existing user file/value differs from the bundle."""


@dataclass(frozen=True)
class ProfileKey:
    table: TablePath | str
    key: str
    value: Any

    @property
    def display(self) -> str:
        table = self.table if isinstance(self.table, str) else ".".join(self.table)
        return f"{table + '.' if table else ''}{self.key}"


@dataclass
class PlannedFile:
    rel: str
    content: bytes
    reason: str


@dataclass(frozen=True)
class PathSnapshot:
    exists: bool
    content: bytes | None


@dataclass(frozen=True)
class PlanSnapshot:
    manifest: PathSnapshot
    destinations: dict[str, PathSnapshot]
    backup_ignore: PathSnapshot
    expected_role_sha256: dict[str, str]


@dataclass(frozen=True)
class InstallationStatus:
    state: str
    manifest: str
    managed_ok: int | None
    managed_total: int | None
    backups_ok: int | None
    backups_total: int | None
    roles_ok: int | None
    roles_total: int | None


class TargetLock:
    """A non-blocking, per-target lock for cooperating mutating installers.

    The harmless lock file is intentionally persistent. Removing it would
    introduce an unlink/open race between cooperating processes.
    """

    def __init__(self, target: Path) -> None:
        self.path = _safe_join(target, ".codex/.astrator.lock")
        self._handle = None

    def __enter__(self) -> "TargetLock":
        _ensure_directory(self.path.parent)
        _assert_not_symlink(self.path)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise InstallerError(f"cannot open installer lock: {exc}") from exc
        try:
            handle = os.fdopen(fd, "r+b", buffering=0)
            fd = -1
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise InstallerError("installer lock is not a regular file")
            if info.st_size == 0:
                handle.write(b"codex-astrator installer lock\n")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._handle = handle
            return self
        except (OSError, InstallerError) as exc:
            if fd >= 0:
                os.close(fd)
            elif 'handle' in locals():
                handle.close()
            if isinstance(exc, InstallerError):
                raise
            raise InstallerError("another codex-astrator apply is active for this target") from exc

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read()
    except OSError as exc:
        raise InstallerError(f"cannot read {path}: {exc}") from exc


def _snapshot_file(path: Path) -> PathSnapshot:
    """Capture exact file state while rejecting links and non-regular files."""
    info = _lstat(path)
    if info is None:
        return PathSnapshot(False, None)
    _assert_not_symlink(path, allow_missing=False)
    if not stat.S_ISREG(info.st_mode):
        raise InstallerError(f"expected regular file, found {path}")
    return PathSnapshot(True, _read_bytes(path))


def _revalidate_snapshot(path: Path, expected: PathSnapshot, *, label: str) -> None:
    current = _snapshot_file(path)
    if current != expected:
        raise InstallerError(f"stale plan: {label} changed after inspection; no changes were applied")


def _lstat(path: Path):
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InstallerError(f"cannot inspect {path}: {exc}") from exc


def _assert_not_symlink(path: Path, *, allow_missing: bool = True) -> None:
    info = _lstat(path)
    if info is None:
        if allow_missing:
            return
        raise InstallerError(f"required path does not exist: {path}")
    if path.is_symlink():
        raise InstallerError(f"refusing symlink path: {path}")


def _relative_parts(relative: str) -> tuple[str, ...]:
    """Validate a manifest-relative path without platform-specific escapes."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise InstallerError("manifest contains an invalid empty/path value")
    if Path(relative).is_absolute() or Path(relative).drive:
        raise InstallerError(f"manifest path must be relative: {relative!r}")
    # Accept only slash-normalized records.  This also prevents a Windows
    # backslash path from being interpreted differently on another host.
    if "\\" in relative:
        raise InstallerError(f"manifest path has unsupported separators: {relative!r}")
    parts = tuple(relative.split("/"))
    if any(part in ("", ".", "..") for part in parts):
        raise InstallerError(f"manifest path traversal: {relative!r}")
    return parts


def _safe_join(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    parts = _relative_parts(relative)
    candidate = root.joinpath(*parts)
    # Resolve is a second defense against unusual path implementations.  The
    # lstat walk below is the important defense against symlink traversal.
    root_resolved = root.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise InstallerError(f"path escapes target: {relative!r}") from exc
    cursor = root
    _assert_not_symlink(cursor)
    for part in parts[:-1]:
        cursor = cursor / part
        info = _lstat(cursor)
        if info is not None and cursor.is_symlink():
            raise InstallerError(f"refusing symlink ancestor: {cursor}")
        if info is not None and not cursor.is_dir():
            raise InstallerError(f"path ancestor is not a directory: {cursor}")
    _assert_not_symlink(candidate, allow_missing=allow_missing)
    return candidate


def _ensure_directory(path: Path) -> None:
    """Create a directory one component at a time, rejecting links."""
    if path.exists() or path.is_symlink():
        _assert_not_symlink(path, allow_missing=False)
        if not path.is_dir():
            raise InstallerError(f"expected directory, found {path}")
        return
    parent = path.parent
    if parent != path:
        _ensure_directory(parent)
    try:
        path.mkdir()
    except FileExistsError:
        _assert_not_symlink(path, allow_missing=False)
    except OSError as exc:
        raise InstallerError(f"cannot create directory {path}: {exc}") from exc


def _write_bytes(path: Path, data: bytes) -> None:
    global _FAIL_AFTER
    if _FAIL_AFTER is not None:
        if _FAIL_AFTER <= 0:
            raise InstallerError("test-injected write failure")
        _FAIL_AFTER -= 1
    _ensure_directory(path.parent)
    _assert_not_symlink(path)
    # A sibling temporary file and replace provide atomic publication.  The
    # temporary file is explicit and cleaned on all error paths.
    tmp = path.with_name(f".{path.name}.astrator-{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise InstallerError(f"cannot write {path}: {exc}") from exc


def _cleanup_empty_dirs(path: Path, stop: Path) -> None:
    """Remove only empty directories created by us; never recurse/delete data."""
    current = path
    stop = stop.resolve(strict=False)
    while current != stop and current != current.parent:
        _assert_not_symlink(current)
        try:
            current.rmdir()
        except FileNotFoundError:
            pass
        except OSError:
            break
        current = current.parent


def _cleanup_explicit_tree(path: Path) -> None:
    """Remove an exact temporary tree without following links or recursing delete APIs."""
    if _lstat(path) is None:
        return
    if path.is_symlink():
        return
    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_symlink():
            continue
        if child.is_file():
            try:
                child.unlink()
            except OSError:
                pass
        elif child.is_dir():
            try:
                child.rmdir()
            except OSError:
                pass
    try:
        path.rmdir()
    except OSError:
        pass


def _toml_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, datetime, date, time)) and not isinstance(value, (list, dict, tuple))


def _format_toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # JSON's double-quoted escapes are valid TOML basic-string escapes for
        # the scalar values accepted by this installer.
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    raise InstallerError(f"profile value is not a supported scalar: {value!r}")


_ASSIGN_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<between>\s*=\s*)(?P<value>.*?)(?P<newline>\r?\n)?$")
_BARE_KEY_RE = re.compile(r"[A-Za-z0-9_-]+")


def _strip_comment(value: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif quote == "'":
            if char == "'":
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "#":
            return value[:index].rstrip(), value[index:]
    return value.rstrip(), ""


def _flatten_profile(data: dict[str, Any], table: TablePath = ()) -> list[ProfileKey]:
    keys: list[ProfileKey] = []
    for key, value in data.items():
        if isinstance(value, dict):
            child = table + (key,)
            keys.extend(_flatten_profile(value, child))
        elif _toml_scalar(value):
            keys.append(ProfileKey(table, key, value))
        else:
            raise InstallerError(
                f"profile key {'.'.join(table) + '.' if table else ''}{key} is not a scalar; refusing ambiguous merge"
            )
    return keys


def _load_profile(path: Path) -> list[ProfileKey]:
    _assert_not_symlink(path, allow_missing=False)
    raw = _read_bytes(path)
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise InstallerError(f"invalid profile TOML {path}: {exc}") from exc
    return _flatten_profile(parsed)


def _table_path(table: TablePath | str) -> TablePath:
    """Normalize the internal table representation while tolerating old callers."""
    if isinstance(table, tuple):
        return table
    return tuple(table.split(".")) if table else ()


def _parse_table_path(content: str) -> TablePath:
    """Parse a single-line TOML dotted table name into decoded key segments."""
    if not content.strip():
        raise InstallerError("empty TOML table name")
    if "'''" in content or '"""' in content:
        raise InstallerError("multiline TOML table names are unsupported for conservative profile merge")
    probe = "__codex_astrator_table_probe__"
    try:
        parsed = tomllib.loads(f"[{content}]\n{probe} = true\n")
    except tomllib.TOMLDecodeError as exc:
        raise InstallerError(f"unsupported TOML table name syntax: [{content}]") from exc
    components: list[str] = []
    value: Any = parsed
    while isinstance(value, dict):
        if value.get(probe) is True:
            return tuple(components)
        if len(value) != 1:
            break
        component, value = next(iter(value.items()))
        components.append(component)
    raise InstallerError(f"unsupported TOML table name syntax: [{content}]")


def _line_table_path(line: str) -> TablePath | None:
    """Return a decoded table path for a single-line table header."""
    text = line.rstrip("\r\n")
    start = len(text) - len(text.lstrip())
    if start >= len(text) or text[start] != "[":
        return None
    if text.startswith("[[", start):
        raise InstallerError("array-of-table syntax is unsupported for conservative profile merge")

    index = start + 1
    quote: str | None = None
    escaped = False
    close = None
    while index < len(text):
        char = text[index]
        if quote is not None:
            if quote == '"' and escaped:
                escaped = False
            elif quote == '"' and char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "]":
            close = index
            break
        index += 1
    if close is None:
        raise InstallerError("unsupported multiline or unterminated TOML table header")
    suffix = text[close + 1:].strip()
    if suffix and not suffix.startswith("#"):
        raise InstallerError(f"unsupported TOML table header syntax: {text}")
    return _parse_table_path(text[start + 1:close])


def _line_table(line: str) -> str | None:
    """Compatibility view of a decoded table path for older internal callers."""
    table = _line_table_path(line)
    return ".".join(table) if table is not None else None


def _format_toml_key(key: str) -> str:
    if _BARE_KEY_RE.fullmatch(key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _format_toml_table(table: TablePath) -> str:
    return ".".join(_format_toml_key(component) for component in table)


def _lookup_table(data: Any, table: TablePath) -> Any:
    value = data
    for component in table:
        if not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    return value


def _multiline_string_lines(lines: list[str]) -> set[int]:
    """Identify multiline string spans so their contents are never lexed as TOML structure."""
    def closes(text: str, marker: str, start: int = 0) -> bool:
        position = text.find(marker, start)
        while position >= 0:
            if marker == "'''":
                return True
            backslashes = 0
            cursor = position - 1
            while cursor >= 0 and text[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                return True
            position = text.find(marker, position + len(marker))
        return False

    ignored: set[int] = set()
    delimiter: str | None = None
    for number, line in enumerate(lines):
        if delimiter is not None:
            ignored.add(number)
            if closes(line, delimiter):
                delimiter = None
            continue
        match = _ASSIGN_RE.match(line)
        if match is None:
            continue
        value = match.group("value").lstrip()
        for candidate in ('"""', "'''"):
            if value.startswith(candidate) and not closes(value, candidate, len(candidate)):
                delimiter = candidate
                ignored.add(number)
                break
    return ignored


def _scan_assignments(raw: str) -> tuple[list[str], dict[tuple[TablePath, str], list[tuple[int, re.Match[str], Any, str]]], dict[str, Any]]:
    try:
        parsed = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise InstallerError(f"existing config is invalid TOML: {exc}") from exc
    lines = raw.splitlines(keepends=True)
    multiline_lines = _multiline_string_lines(lines)
    table: TablePath = ()
    found: dict[tuple[TablePath, str], list[tuple[int, re.Match[str], Any, str]]] = {}
    for number, line in enumerate(lines):
        if number in multiline_lines:
            continue
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[["):
            raise InstallerError("array-of-table syntax is unsupported for conservative config merge")
        parsed_table = _line_table_path(line)
        if parsed_table is not None:
            table = parsed_table
            continue
        match = _ASSIGN_RE.match(line)
        if not match:
            # A valid TOML line which we cannot lexically reason about (for
            # example a quoted key) is safe unless it collides with an owned
            # key.  Keep scanning and let semantic conflict checks catch it.
            continue
        key = match.group("key")
        value_text, _ = _strip_comment(match.group("value"))
        try:
            value = tomllib.loads(f"{key} = {value_text}")[key]
        except tomllib.TOMLDecodeError as exc:
            raise InstallerError(f"cannot parse config assignment on line {number + 1}: {exc}") from exc
        found.setdefault((table, key), []).append((number, match, value, value_text))
    return lines, found, parsed


def _merge_profile(raw: bytes, profile: list[ProfileKey], replace_existing: bool) -> tuple[bytes, list[str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallerError(f"existing config is not UTF-8: {exc}") from exc
    lines, found, parsed = _scan_assignments(text)
    multiline_lines = _multiline_string_lines(lines)
    newline_style = "\r\n" if "\r\n" in text else "\n"
    conflicts: list[str] = []
    replacements: dict[int, str] = {}
    additions: dict[int, list[str]] = {}
    new_table_additions: dict[int, list[str]] = {}
    added_tables: set[TablePath] = set()
    # Locate lexical table ranges for additions.
    table_ranges: dict[TablePath, tuple[int, int]] = {}
    starts: list[tuple[int, TablePath]] = [(0, ())]
    for idx, line in enumerate(lines):
        if idx in multiline_lines:
            continue
        table = _line_table_path(line)
        if table is not None:
            starts.append((idx, table))
    for index, (start, table) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        table_ranges[table] = (start, end)
    for owned in profile:
        owned_table = _table_path(owned.table)
        matches = found.get((owned_table, owned.key), [])
        if len(matches) > 1:
            raise InstallerError(f"owned key {owned.display} occurs more than once; refusing ambiguous merge")
        if matches:
            line_no, match, actual, _ = matches[0]
            if actual == owned.value:
                continue
            conflicts.append(owned.display)
            if replace_existing:
                value_text, comment = _strip_comment(match.group("value"))
                # Preserve inline comments and the original indentation/key
                # spacing.  We replace only the scalar token.
                del value_text
                newline = match.group("newline") or ""
                replacements[line_no] = (
                    f"{match.group('indent')}{match.group('key')}{match.group('between')}"
                    f"{_format_toml_scalar(owned.value)}"
                    f"{(' ' + comment) if comment else ''}{newline}"
                )
            continue
        # A semantically matching quoted/dotted key cannot be edited safely
        # with this lexical writer. Refuse before producing duplicate TOML.
        table_value: Any = _lookup_table(parsed, owned_table)
        if isinstance(table_value, dict) and owned.key in table_value:
            raise InstallerError(f"owned key {owned.display} uses unsupported TOML key syntax")
        if owned_table not in table_ranges:
            # A root key can be inserted into the existing root before the
            # first table; otherwise append a new table and scalar key.
            if owned_table:
                lines_to_add = []
                if owned_table not in added_tables:
                    lines_to_add.append(f"[{_format_toml_table(owned_table)}]{newline_style}")
                    added_tables.add(owned_table)
                lines_to_add.append(
                    f"{_format_toml_key(owned.key)} = {_format_toml_scalar(owned.value)}{newline_style}"
                )
                # Keep newly-created tables after additions to all existing
                # tables, including when both insertion points are EOF.
                new_table_additions.setdefault(len(lines), []).extend(lines_to_add)
            else:
                additions.setdefault(table_ranges.get((), (0, len(lines)))[1], []).append(
                    f"{_format_toml_key(owned.key)} = {_format_toml_scalar(owned.value)}{newline_style}"
                )
        else:
            _, end = table_ranges[owned_table]
            additions.setdefault(end, []).append(
                f"{_format_toml_key(owned.key)} = {_format_toml_scalar(owned.value)}{newline_style}"
            )
    if conflicts and not replace_existing:
        return raw, conflicts
    merged: list[str] = []
    for index in range(len(lines) + 1):
        if index in additions:
            # Ensure inserted assignments are separated from a previous line,
            # while retaining all existing comments/line endings verbatim.
            if merged and merged[-1] and not merged[-1].endswith(("\n", "\r")):
                merged[-1] += newline_style
            merged.extend(additions[index])
        if index in new_table_additions:
            if merged and merged[-1] and not merged[-1].endswith(("\n", "\r")):
                merged[-1] += newline_style
            merged.extend(new_table_additions[index])
        if index < len(lines):
            merged.append(replacements.get(index, lines[index]))
    result = "".join(merged).encode("utf-8")
    try:
        parsed_result = tomllib.loads(result.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise InstallerError(f"merged config is invalid TOML: {exc}") from exc
    # Verify the lexical edit did not accidentally move a key into a different
    # table and that unrelated semantic values survived unchanged.
    for owned in profile:
        owned_table = _table_path(owned.table)
        table_value: Any = _lookup_table(parsed_result, owned_table)
        if table_value is None and owned_table:
            raise InstallerError(f"merged config lost owned table {owned.display}")
        if not isinstance(table_value, dict) or table_value.get(owned.key) != owned.value:
            raise InstallerError(f"merged config did not set owned key {owned.display}")
    baseline = copy.deepcopy(parsed)
    for owned in profile:
        table_value = _lookup_table(baseline, _table_path(owned.table))
        if isinstance(table_value, dict):
            table_value.pop(owned.key, None)
    preserved = copy.deepcopy(parsed_result)
    for owned in profile:
        table_value = _lookup_table(preserved, _table_path(owned.table))
        if isinstance(table_value, dict):
            table_value.pop(owned.key, None)
    # Newly introduced owned tables become empty after removing their keys.
    # Remove only these new containers, preserving pre-existing empty tables.
    for owned in sorted(profile, key=lambda item: len(_table_path(item.table)), reverse=True):
        components = _table_path(owned.table)
        if not components:
            continue
        for depth in range(len(components), 0, -1):
            original = _lookup_table(parsed, components[:depth - 1])
            current = _lookup_table(preserved, components[:depth - 1])
            key = components[depth - 1]
            if isinstance(current, dict) and current.get(key) == {} and (
                not isinstance(original, dict) or key not in original
            ):
                current.pop(key)
    if baseline != preserved:
        raise InstallerError("merged config changed unrelated semantic values")
    return result, conflicts


def _managed_block(instructions: str) -> str:
    if MARKER_BEGIN in instructions or MARKER_END in instructions:
        raise InstallerError("instructions contain reserved managed-block markers")
    body = instructions.rstrip("\r\n")
    return f"{MARKER_BEGIN}\n{body}\n{MARKER_END}\n"


def _merge_agents(raw: bytes, instructions: str) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallerError(f"existing AGENTS.md is not UTF-8: {exc}") from exc
    begins = [m.start() for m in re.finditer(re.escape(MARKER_BEGIN), text)]
    ends = [m.start() for m in re.finditer(re.escape(MARKER_END), text)]
    block = _managed_block(instructions)
    if len(begins) != len(ends) or len(begins) > 1 or (begins and ends and begins[0] > ends[0]):
        raise InstallerError("existing AGENTS.md has an ambiguous managed block")
    if begins:
        start = begins[0]
        end = text.find(MARKER_END, start) + len(MARKER_END)
        if end <= len(MARKER_END):
            raise InstallerError("existing AGENTS.md has an incomplete managed block")
        # Keep one newline after the replacement block. Consume the newline
        # belonging to the old marker so repeated installs are byte-idempotent
        # while preserving all other user content around it.
        suffix_start = end
        if text[suffix_start:].startswith("\r\n"):
            suffix_start += 2
        elif text[suffix_start:].startswith(("\n", "\r")):
            suffix_start += 1
        return (text[:start] + block + text[suffix_start:]).encode("utf-8")
    prefix = "" if not text or text.endswith(("\n", "\r")) else "\n"
    return (text + prefix + block).encode("utf-8")


_ORCHESTRATION_RE = re.compile(
    r"\b(?:delegat(?:e|ion)|sub[- ]?agents?|spawn_agent|multi[- ]agent|orchestrat(?:e|ion|or))\b",
    re.IGNORECASE,
)


def _has_unmanaged_orchestration(raw: bytes) -> bool:
    """Flag likely orchestration policy outside our block without interpreting it."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False  # _merge_agents reports the actionable encoding error.
    start = text.find(MARKER_BEGIN)
    end = text.find(MARKER_END)
    if start != -1 and end > start:
        text = text[:start] + text[end + len(MARKER_END):]
    return _ORCHESTRATION_RE.search(text) is not None


def _resolve_source(source: Path) -> tuple[Path, Path, Path, Path]:
    # The source directory is the trust boundary.  Reject a link at that
    # boundary, then canonicalize it so harmless platform aliases above it
    # (for example macOS /var -> /private/var) are not treated as payload
    # links.  _safe_join still rejects every link inside the boundary.
    if source.is_symlink():
        raise InstallerError(f"payload contains symlink: {source}")
    try:
        boundary = source.resolve(strict=True)
    except OSError as exc:
        raise InstallerError(f"payload source is unavailable: {source}") from exc
    candidates = [
        ("profiles/reference.toml", "payload/agents", "payload/skills", "payload/instructions/orchestration.md"),
        ("payload/profiles/reference.toml", "payload/agents", "payload/skills", "payload/instructions/orchestration.md"),
        ("payload/reference.toml", "payload/agents", "payload/skills", "payload/instructions/orchestration.md"),
    ]
    for relative_paths in candidates:
        profile, agents, skills, instructions = (
            _safe_join(boundary, relative) for relative in relative_paths
        )
        if profile.is_file():
            return profile, agents, skills, instructions
    raise InstallerError(f"payload profile not found below {source}")


def _source_files(root: Path) -> Iterable[tuple[Path, str]]:
    if root.is_symlink():
        raise InstallerError(f"payload contains symlink: {root}")
    if not root.exists():
        return []
    _assert_not_symlink(root, allow_missing=False)
    try:
        root = root.resolve(strict=True)
    except OSError as exc:
        raise InstallerError(f"cannot inspect payload directory: {root}") from exc
    result: list[tuple[Path, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise InstallerError(f"payload contains symlink: {path}")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            _relative_parts(relative)
            result.append((path, relative))
    return result


def _manifest_path(target: Path) -> str:
    return f".codex/{MANIFEST_NAME}"


def _managed_prefixes(scope: str) -> tuple[str, ...]:
    # Kept as a small compatibility helper for callers; _managed_path below
    # applies the stricter file-level allowlist.
    return (".codex/", ".agents/", "AGENTS.md") if scope == "project" else (".codex/", ".agents/")


def _managed_path(scope: str, relative: str) -> bool:
    """Return whether a manifest entry can name a bundle-owned file."""
    if relative in {".codex/config.toml", ".codex/AGENTS.md" if scope == "global" else "AGENTS.md"}:
        return True
    if relative.startswith(".codex/agents/"):
        tail = relative[len(".codex/agents/"):]
        return "/" not in tail and tail.lower().endswith(".toml")
    if relative.startswith(".agents/skills/"):
        tail = relative[len(".agents/skills/"):]
        return tail.endswith("/SKILL.md") and ".." not in tail
    return False


def _load_manifest(target: Path, scope: str) -> tuple[Path, dict[str, Any] | None, PathSnapshot]:
    rel = _manifest_path(target)
    path = _safe_join(target, rel)
    snapshot = _snapshot_file(path)
    if not snapshot.exists:
        return path, None, snapshot
    try:
        value = json.loads((snapshot.content or b"").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerError(f"invalid installer manifest: {exc}") from exc
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value.get("version") not in ({MANIFEST_VERSION} | LEGACY_MANIFEST_VERSIONS)
        or value.get("scope") != scope
    ):
        raise InstallerError("installer manifest version/scope is unsupported")
    entries = value.get("entries")
    if not isinstance(entries, list):
        raise InstallerError("installer manifest entries are invalid")
    managed_agent_paths = value.get("managed_agent_paths")
    if managed_agent_paths is not None:
        if (
            not isinstance(managed_agent_paths, list)
            or any(not isinstance(item, str) for item in managed_agent_paths)
            or managed_agent_paths != sorted(set(managed_agent_paths))
            or any(
                not item.startswith(".codex/agents/")
                or not _managed_path(scope, item)
                for item in managed_agent_paths
            )
        ):
            raise InstallerError("installer manifest has an invalid managed agent role set")
    expected_role_sha256 = value.get("expected_role_sha256")
    if value["version"] == MANIFEST_VERSION and "expected_role_sha256" in value and (
        not isinstance(expected_role_sha256, dict)
        or managed_agent_paths is None
        or set(expected_role_sha256) != set(managed_agent_paths)
        or any(
            not isinstance(role_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", role_hash) is None
            for role_hash in expected_role_sha256.values()
        )
    ):
        raise InstallerError("installer manifest has an invalid expected role hash map")
    seen: set[str] = set()
    seen_backups: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise InstallerError("installer manifest has an invalid entry")
        entry_path = entry["path"]
        _relative_parts(entry_path)
        if not _managed_path(scope, entry_path):
            raise InstallerError(f"installer manifest contains an unmanaged path: {entry_path!r}")
        if entry_path in seen:
            raise InstallerError(f"installer manifest contains a duplicate path: {entry_path!r}")
        seen.add(entry_path)
        if not isinstance(entry.get("installed_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", entry["installed_sha256"]):
            raise InstallerError("installer manifest has an invalid installed hash")
        if not isinstance(entry.get("original_exists"), bool):
            raise InstallerError("installer manifest has an invalid original_exists flag")
        original_hash = entry.get("original_sha256")
        if original_hash is not None and (not isinstance(original_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", original_hash)):
            raise InstallerError("installer manifest has an invalid original hash")
        backup = entry.get("backup")
        if backup is not None:
            _relative_parts(backup)
            expected = f".codex/{BACKUP_DIR_NAME}/"
            if not backup.startswith(expected):
                raise InstallerError("installer manifest backup escapes backup directory")
            if backup in seen_backups:
                raise InstallerError("installer manifest reuses a backup path")
            seen_backups.add(backup)
            backup_path = _safe_join(target, backup, allow_missing=False)
            if not entry["original_exists"] or original_hash is None:
                raise InstallerError("installer manifest backup metadata is inconsistent")
            backup_snapshot = _snapshot_file(backup_path)
            if not backup_snapshot.exists or _sha256(backup_snapshot.content or b"") != original_hash:
                raise InstallerError("installer manifest backup hash does not match metadata")
        elif entry["original_exists"] or original_hash is not None:
            raise InstallerError("installer manifest is missing a required backup")
        _safe_join(target, entry_path)
    if value["version"] == MANIFEST_VERSION:
        role_entries = sorted(
            entry["path"] for entry in entries
            if entry["path"].startswith(".codex/agents/")
        )
        if managed_agent_paths is None or any(path not in managed_agent_paths for path in role_entries):
            raise InstallerError("installer manifest has an undeclared managed role-profile entry")
    return path, value, snapshot


def _require_current_manifest(manifest: dict[str, Any] | None, operation: str) -> None:
    if manifest is not None and manifest.get("version") != MANIFEST_VERSION:
        raise InstallerError(
            f"legacy installer manifest safety version blocks {operation}; current files and backups "
            "were preserved. Manually reconcile the installed files and backup contents, then remove "
            "the legacy manifest only after deciding which copy to keep; automatic upgrade, restore, "
            "or uninstall is intentionally unavailable"
        )


def _validate_installed_files(target: Path, manifest: dict[str, Any]) -> dict[str, PathSnapshot]:
    """Require every tracked destination to remain the exact installed regular file."""
    snapshots: dict[str, PathSnapshot] = {}
    for entry in manifest["entries"]:
        destination = _safe_join(target, entry["path"], allow_missing=False)
        snapshot = _snapshot_file(destination)
        if not snapshot.exists:
            raise InstallerError(f"installed file is missing: {entry['path']}")
        if _sha256(snapshot.content or b"") != entry["installed_sha256"]:
            raise InstallerError(
                f"installed file drift detected: {entry['path']}; preserve and reconcile user edits "
                "before install/update"
            )
        snapshots[entry["path"]] = snapshot
    return snapshots


def _recovery_artifacts_present(target: Path, manifest: dict[str, Any] | None) -> bool:
    """Detect retained backup payloads without reading or revealing their content."""
    try:
        backup_root = _safe_join(target, f".codex/{BACKUP_DIR_NAME}")
        info = _lstat(backup_root)
    except InstallerError:
        return True
    if info is None:
        return False
    if backup_root.is_symlink() or not backup_root.is_dir():
        return True

    prefix = f".codex/{BACKUP_DIR_NAME}/"
    allowed_files = {".gitignore"}
    allowed_directories: set[str] = set()
    for entry in (manifest or {}).get("entries", []):
        backup = entry.get("backup")
        if not isinstance(backup, str) or not backup.startswith(prefix):
            continue
        relative = backup[len(prefix):]
        allowed_files.add(relative)
        parts = relative.split("/")
        allowed_directories.update("/".join(parts[:depth]) for depth in range(1, len(parts)))

    pending = [(backup_root, "")]
    while pending:
        directory, parent_relative = pending.pop()
        try:
            children = list(os.scandir(directory))
        except OSError:
            return True
        for child in children:
            relative = f"{parent_relative}/{child.name}" if parent_relative else child.name
            try:
                if child.is_symlink():
                    return True
                if child.is_dir(follow_symlinks=False):
                    if relative not in allowed_directories:
                        return True
                    pending.append((Path(child.path), relative))
                elif not child.is_file(follow_symlinks=False) or relative not in allowed_files:
                    return True
            except OSError:
                return True
    return False


def _require_recovery_safe(
    target: Path, manifest: dict[str, Any] | None, operation: str
) -> None:
    """Block mutations while unreferenced recovery payloads need reconciliation."""
    if _recovery_artifacts_present(target, manifest):
        raise InstallerError(
            f"recovery-required: retained or unrecognized recovery artifacts block {operation}; "
            "current files, manifest, and backups were preserved. Reconcile the contents below "
            f".codex/{BACKUP_DIR_NAME} before retrying"
        )


def _inspect_installation(target: Path, scope: str) -> InstallationStatus:
    """Return an aggregate, content-free point-in-time integrity report."""
    try:
        _, manifest, _ = _load_manifest(target, scope)
    except InstallerError:
        return InstallationStatus("invalid", "invalid", None, None, None, None, None, None)
    if manifest is None:
        if _recovery_artifacts_present(target, None):
            return InstallationStatus("recovery-required", "missing", 0, 0, None, None, None, None)
        return InstallationStatus("absent", "missing", 0, 0, 0, 0, 0, 0)
    entries = manifest["entries"]
    backup_entries = [entry for entry in entries if entry.get("backup")]
    roles = manifest.get("managed_agent_paths") or []
    if manifest.get("version") != MANIFEST_VERSION:
        return InstallationStatus(
            "legacy", "legacy", None, len(entries), None, len(backup_entries), None, len(roles)
        )

    recovery_required = _recovery_artifacts_present(target, manifest)
    expected_role_sha256 = manifest.get("expected_role_sha256")

    managed_ok = 0
    roles_ok = 0
    for entry in entries:
        try:
            destination = _safe_join(target, entry["path"], allow_missing=False)
            snapshot = _snapshot_file(destination)
        except InstallerError:
            continue
        if snapshot.exists and _sha256(snapshot.content or b"") == entry["installed_sha256"]:
            managed_ok += 1
    if expected_role_sha256 is not None:
        for relative in roles:
            try:
                role_path = _safe_join(target, relative, allow_missing=False)
                role_snapshot = _snapshot_file(role_path)
                roles_ok += int(
                    role_snapshot.exists
                    and _sha256(role_snapshot.content or b"") == expected_role_sha256[relative]
                )
            except InstallerError:
                pass

    backups_ok = len(backup_entries)  # _load_manifest hash-validates every declared backup.
    privacy_ok = True
    try:
        ignore_snapshot = _snapshot_file(_backup_ignore_path(target))
        _validate_backup_ignore(ignore_snapshot)
        if not ignore_snapshot.exists:
            privacy_ok = False
        _reject_tracked_backup_files(target)
    except InstallerError:
        privacy_ok = False
    known_integrity_ok = (
        managed_ok == len(entries)
        and backups_ok == len(backup_entries)
        and privacy_ok
    )
    roles_integrity_ok = expected_role_sha256 is not None and roles_ok == len(roles)
    if not known_integrity_ok or (expected_role_sha256 is not None and not roles_integrity_ok):
        state = "drifted"
    elif expected_role_sha256 is None:
        state = "unverified"
    else:
        state = "healthy"
    if recovery_required:
        state = "recovery-required"
    return InstallationStatus(
        state,
        "current",
        managed_ok,
        len(entries),
        backups_ok if privacy_ok else None,
        len(backup_entries),
        roles_ok if expected_role_sha256 is not None else None,
        len(roles),
    )


def _count_text(ok: int | None, total: int | None) -> str:
    if ok is None or total is None:
        return "unknown"
    return f"{ok}/{total}"


def _print_status(report: InstallationStatus, scope: str) -> None:
    print(
        f"STATUS: state={report.state} scope={scope} manifest={report.manifest} "
        f"managed={_count_text(report.managed_ok, report.managed_total)} "
        f"backups={_count_text(report.backups_ok, report.backups_total)} "
        f"roles={_count_text(report.roles_ok, report.roles_total)}"
    )


def _read_instruction(path: Path) -> str:
    _assert_not_symlink(path, allow_missing=False)
    try:
        return _read_bytes(path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InstallerError(f"instructions are not UTF-8: {exc}") from exc


def _backup_ignore_path(target: Path) -> Path:
    return _safe_join(target, f".codex/{BACKUP_DIR_NAME}/.gitignore")


def _validate_backup_ignore(snapshot: PathSnapshot) -> None:
    if snapshot.exists and snapshot.content not in (b"*\n", b"*\r\n"):
        raise InstallerError(
            f"existing .codex/{BACKUP_DIR_NAME}/.gitignore is not the required protective '*' rule; "
            "refusing to write backups"
        )


def _reject_tracked_backup_files(target: Path) -> None:
    """Refuse known tracked backups; .gitignore cannot make tracked bytes private."""
    git = shutil.which("git")
    if git is None:
        return
    probe = subprocess.run(
        [git, "-C", str(target), "rev-parse", "--is-inside-work-tree"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if probe.returncode != 0:
        return
    tracked = subprocess.run(
        [git, "-C", str(target), "ls-files", "--", f".codex/{BACKUP_DIR_NAME}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if tracked.returncode != 0:
        raise InstallerError("cannot verify whether existing backup files are tracked by Git")
    if tracked.stdout.strip():
        raise InstallerError(
            f"Git already tracks content below .codex/{BACKUP_DIR_NAME}; remove it from the index "
            "without deleting the recovery copy, then retry"
        )


def _build_plan(target: Path, scope: str, source: Path, replace_existing: bool) -> tuple[list[PlannedFile], list[str], dict[str, Any] | None, Path, list[str], PlanSnapshot]:
    profile_path, agents_root, skills_root, instructions_path = _resolve_source(source)
    profile = _load_profile(profile_path)
    instructions = _read_instruction(instructions_path)
    manifest_path, old_manifest, manifest_snapshot = _load_manifest(target, scope)
    backup_ignore_snapshot = _snapshot_file(_backup_ignore_path(target))
    _validate_backup_ignore(backup_ignore_snapshot)
    _reject_tracked_backup_files(target)
    _require_recovery_safe(target, old_manifest, "install/update")
    _require_current_manifest(old_manifest, "install/update")
    installed_snapshots = _validate_installed_files(target, old_manifest) if old_manifest is not None else {}
    agent_files = [(path, relative, _read_bytes(path)) for path, relative in _source_files(agents_root)]
    source_agent_paths = sorted(f".codex/agents/{relative}" for _, relative, _ in agent_files)
    expected_role_sha256 = {
        f".codex/agents/{relative}": _sha256(content)
        for _, relative, content in agent_files
    }
    if old_manifest is not None:
        installed_agent_paths = old_manifest.get("managed_agent_paths")
        if installed_agent_paths is None:
            raise InstallerError(
                "legacy installer manifest has no complete managed role set; uninstall "
                "the previous version first, inspect restored files, then install this version"
            )
        if installed_agent_paths != source_agent_paths:
            raise InstallerError(
                "managed role set changed; uninstall the previous version first, "
                "inspect restored files, then install this version"
            )
    config_rel = ".codex/config.toml"
    agents_rel = ".codex/AGENTS.md" if scope == "global" else "AGENTS.md"
    destination_snapshots: dict[str, PathSnapshot] = dict(installed_snapshots)

    def destination_snapshot(relative: str) -> PathSnapshot:
        if relative not in destination_snapshots:
            destination_snapshots[relative] = _snapshot_file(_safe_join(target, relative))
        return destination_snapshots[relative]

    # Include every previously tracked path, even if it needs no content change.
    for entry in (old_manifest or {}).get("entries", []):
        destination_snapshot(entry["path"])

    # A byte-identical preexisting role is declared but intentionally remains
    # unowned.  Once a hash is available, require explicit replacement consent
    # before adopting any altered bytes as the new expected state.
    old_expected_roles = (old_manifest or {}).get("expected_role_sha256") or {}
    owned_paths = {entry["path"] for entry in (old_manifest or {}).get("entries", [])}
    role_drift_conflicts: list[str] = []
    for relative, expected_hash in old_expected_roles.items():
        if relative in owned_paths:
            continue
        role_snapshot = destination_snapshot(relative)
        if not role_snapshot.exists or _sha256(role_snapshot.content or b"") != expected_hash:
            role_drift_conflicts.append(relative)

    config_path = _safe_join(target, config_rel)
    config_snapshot = destination_snapshot(config_rel)
    existing_config = config_snapshot.content if config_snapshot.exists else b""
    if existing_config:
        config_content, config_conflicts = _merge_profile(existing_config, profile, replace_existing)
    else:
        # A missing config is intentionally generated from profile scalars,
        # with tables inserted only as needed.
        config_content, config_conflicts = _merge_profile(b"", profile, replace_existing)
    plan: list[PlannedFile] = []
    conflicts: list[str] = list(config_conflicts) + role_drift_conflicts
    if config_content != existing_config:
        plan.append(PlannedFile(config_rel, config_content, "merge reference profile"))
    agents_path = _safe_join(target, agents_rel)
    agents_snapshot = destination_snapshot(agents_rel)
    agents_existing = agents_snapshot.content if agents_snapshot.exists else b""
    agents_content = _merge_agents(agents_existing, instructions)
    if agents_content != agents_existing:
        plan.append(PlannedFile(agents_rel, agents_content, "update managed instructions block"))
    for file, relative, new in agent_files:
        if "/" in relative or not relative.lower().endswith(".toml"):
            raise InstallerError(f"agent payload must be TOML: {file}")
        destination = f".codex/agents/{relative}"
        destination_path = _safe_join(target, destination)
        old_snapshot = destination_snapshot(destination)
        old = old_snapshot.content if old_snapshot.exists else b""
        if old != new:
            if old_snapshot.exists:
                conflicts.append(destination)
            plan.append(PlannedFile(destination, new, "install agent profile"))
    for file, relative in _source_files(skills_root):
        if not relative.endswith("/SKILL.md"):
            raise InstallerError(f"skill payload must be a SKILL.md file: {file}")
        destination = f".agents/skills/{relative}"
        destination_path = _safe_join(target, destination)
        old_snapshot = destination_snapshot(destination)
        old = old_snapshot.content if old_snapshot.exists else b""
        new = _read_bytes(file)
        if old != new:
            if old_snapshot.exists:
                conflicts.append(destination)
            plan.append(PlannedFile(destination, new, "install skill file"))
    snapshot = PlanSnapshot(
        manifest_snapshot, destination_snapshots, backup_ignore_snapshot, expected_role_sha256
    )
    return plan, sorted(set(conflicts)), old_manifest, manifest_path, source_agent_paths, snapshot


def _print_plan(
    plan: list[PlannedFile],
    conflicts: list[str],
    *,
    apply: bool,
    replace_existing: bool,
    protect_backups: bool,
    unmanaged_orchestration: bool,
    migrate_manifest_metadata: bool,
) -> None:
    mode = "APPLY" if apply else "PREVIEW"
    change_count = len(plan) + int(protect_backups) + int(migrate_manifest_metadata)
    print(f"{mode}: {change_count} file change(s)")
    for item in plan:
        print(f"  {item.rel}: {item.reason}")
    if protect_backups:
        print(f"  .codex/{BACKUP_DIR_NAME}/.gitignore: protect local recovery backups from normal Git staging")
    if migrate_manifest_metadata:
        print(
            f"  .codex/{MANIFEST_NAME}: add role integrity metadata "
            "(ownership and backups unchanged)"
        )
    if unmanaged_orchestration:
        print("WARNING: existing unmanaged orchestration-like instructions in AGENTS.md were preserved")
        print("  review them with the managed block for conflicts; the installer does not claim the combined policy is coherent")
    if conflicts:
        print("CONFLICTS:")
        for conflict in conflicts:
            print(f"  {conflict}")
        if not replace_existing or not apply:
            print("  rerun apply with --replace-existing to replace conflicting values/files")


def _manifest_entries(target: Path, plan: list[PlannedFile], old_manifest: dict[str, Any] | None, backup_id: str) -> list[dict[str, Any]]:
    previous = {entry["path"]: entry for entry in (old_manifest or {}).get("entries", [])}
    entries: list[dict[str, Any]] = []
    for item in plan:
        destination = _safe_join(target, item.rel)
        old = previous.get(item.rel)
        if old is not None:
            original_exists = bool(old.get("original_exists"))
            original_hash = old.get("original_sha256")
            backup = old.get("backup")
        else:
            old_bytes = _read_bytes(destination) if _lstat(destination) is not None else None
            original_exists = old_bytes is not None
            original_hash = _sha256(old_bytes) if old_bytes is not None else None
            backup = f".codex/{BACKUP_DIR_NAME}/{backup_id}/{hashlib.sha256(item.rel.encode()).hexdigest()}.bak" if old_bytes is not None else None
        entries.append({
            "path": item.rel,
            "installed_sha256": _sha256(item.content),
            "original_exists": original_exists,
            "original_sha256": original_hash,
            "backup": backup,
        })
    # Preserve entries for files that did not need a content change.  This is
    # what makes a repeat install retain its first-install backups.
    if old_manifest:
        planned_paths = {item.rel for item in plan}
        for entry in old_manifest["entries"]:
            if entry["path"] not in planned_paths:
                entries.append(dict(entry))
    return sorted(entries, key=lambda entry: entry["path"])


def _copy_backup(source: Path, destination: Path) -> None:
    _assert_not_symlink(source, allow_missing=False)
    _assert_not_symlink(destination)
    _ensure_directory(destination.parent)
    _write_bytes(destination, _read_bytes(source))


def _remove_file(path: Path) -> None:
    _assert_not_symlink(path)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise InstallerError(f"cannot remove {path}: {exc}") from exc


def _apply_plan(target: Path, scope: str, plan: list[PlannedFile], old_manifest: dict[str, Any] | None, manifest_path: Path, managed_agent_paths: list[str], snapshot: PlanSnapshot) -> None:
    global _FAIL_AFTER
    _require_recovery_safe(target, old_manifest, "install/update")
    _revalidate_snapshot(manifest_path, snapshot.manifest, label="installer manifest")
    for relative, expected in snapshot.destinations.items():
        _revalidate_snapshot(_safe_join(target, relative), expected, label=relative)
    backup_ignore = _backup_ignore_path(target)
    _revalidate_snapshot(backup_ignore, snapshot.backup_ignore, label="backup privacy rule")
    _validate_backup_ignore(snapshot.backup_ignore)
    _reject_tracked_backup_files(target)
    if old_manifest is not None:
        _validate_installed_files(target, old_manifest)
    backup_id = uuid.uuid4().hex
    transaction_dir = target / ".codex" / BACKUP_DIR_NAME / f".txn-{backup_id}"
    persistent_dir = target / ".codex" / BACKUP_DIR_NAME / backup_id
    old_manifest_bytes = _read_bytes(manifest_path) if _lstat(manifest_path) is not None else None
    changed: list[tuple[Path, bytes | None]] = []
    transaction_backups: dict[Path, Path] = {}
    entries: list[dict[str, Any]] = []
    ignore_created = not snapshot.backup_ignore.exists
    try:
        if ignore_created:
            # This must precede creation of any file that can contain user bytes.
            _write_bytes(backup_ignore, BACKUP_IGNORE_CONTENT)
        _ensure_directory(transaction_dir)
        # Back up every destination before the first publication.  Persistent
        # backups are made only for files that have not been installed before.
        previous = {entry["path"]: entry for entry in (old_manifest or {}).get("entries", [])}
        for item in plan:
            destination = _safe_join(target, item.rel)
            if _lstat(destination) is not None:
                transaction_backup = transaction_dir / f"{hashlib.sha256(item.rel.encode()).hexdigest()}.bak"
                _copy_backup(destination, transaction_backup)
                transaction_backups[destination] = transaction_backup
                if item.rel not in previous:
                    persistent_backup = persistent_dir / f"{hashlib.sha256(item.rel.encode()).hexdigest()}.bak"
                    _copy_backup(destination, persistent_backup)
            changed.append((destination, _read_bytes(destination) if _lstat(destination) is not None else None))
        entries = _manifest_entries(target, plan, old_manifest, backup_id)
        manifest = {
            "version": MANIFEST_VERSION,
            "scope": scope,
            "managed_agent_paths": managed_agent_paths,
            "expected_role_sha256": snapshot.expected_role_sha256,
            "entries": entries,
        }
        for item in plan:
            _write_bytes(_safe_join(target, item.rel), item.content)
        _write_bytes(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        _cleanup_explicit_tree(transaction_dir)
    except Exception as exc:
        # A fault-injection hook is used only by tests; rollback must remain
        # available even when the injected failure counter is exhausted.
        saved_fail_after = _FAIL_AFTER
        _FAIL_AFTER = None
        rollback_errors: list[str] = []
        # Restore changed destinations from transaction copies or remove newly
        # created files.  Every path was validated before publication.
        for destination, before in reversed(changed):
            try:
                if before is None:
                    _remove_file(destination)
                else:
                    backup = transaction_backups.get(destination)
                    if backup is not None and _lstat(backup) is not None:
                        _write_bytes(destination, _read_bytes(backup))
                    else:
                        _write_bytes(destination, before)
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        try:
            if old_manifest_bytes is None:
                _remove_file(manifest_path)
            else:
                _write_bytes(manifest_path, old_manifest_bytes)
        except Exception as rollback_exc:
            rollback_errors.append(str(rollback_exc))
        # Explicit cleanup only. No recursive deletion is used. The
        # persistent backup directory is also removed when this transaction
        # never reached manifest publication.
        if not rollback_errors:
            for cleanup_root in (transaction_dir, persistent_dir):
                _cleanup_explicit_tree(cleanup_root)
        _FAIL_AFTER = saved_fail_after
        if rollback_errors:
            raise InstallerError(
                "apply failed and rollback is incomplete; recovery backups were retained: "
                + "; ".join(rollback_errors)
            ) from exc
        raise InstallerError(f"apply failed; changes rolled back: {exc}") from exc
    finally:
        _cleanup_empty_dirs(transaction_dir, target / ".codex" / BACKUP_DIR_NAME)


def _uninstall(target: Path, scope: str, manifest_path: Path, manifest: dict[str, Any], manifest_snapshot: PathSnapshot, *, apply: bool) -> None:
    _require_current_manifest(manifest, "uninstall")
    _require_recovery_safe(target, manifest, "uninstall")
    entries = manifest["entries"]
    # Hash-check everything before any writes/deletes, so one edited file never
    # produces a half-uninstalled installation.
    checked: list[tuple[dict[str, Any], Path, Path | None, bytes, PathSnapshot | None]] = []
    for entry in entries:
        destination = _safe_join(target, entry["path"], allow_missing=True)
        current_info = _lstat(destination)
        if current_info is None:
            raise InstallerError(f"refusing uninstall: installed file is missing or altered: {entry['path']}")
        current = _read_bytes(destination)
        if _sha256(current) != entry["installed_sha256"]:
            raise InstallerError(f"refusing uninstall: installed file was edited: {entry['path']}")
        backup = None
        if entry.get("original_exists"):
            backup_rel = entry.get("backup")
            if not isinstance(backup_rel, str):
                raise InstallerError(f"manifest backup missing for {entry['path']}")
            backup = _safe_join(target, backup_rel, allow_missing=False)
            backup_data = _read_bytes(backup)
            if entry.get("original_sha256") and _sha256(backup_data) != entry["original_sha256"]:
                raise InstallerError(f"refusing uninstall: backup was edited: {entry['path']}")
        checked.append((entry, destination, backup, current, _snapshot_file(backup) if backup else None))
    if not apply:
        print(f"PREVIEW: uninstall {len(checked)} managed file(s)")
        print("  no files changed; rerun with --apply to uninstall")
        return
    _revalidate_snapshot(manifest_path, manifest_snapshot, label="installer manifest")
    for entry, destination, backup, current, backup_snapshot in checked:
        _revalidate_snapshot(destination, PathSnapshot(True, current), label=entry["path"])
        if backup is not None and backup_snapshot is not None:
            _revalidate_snapshot(backup, backup_snapshot, label=f"backup for {entry['path']}")
    try:
        for entry, destination, backup, _, _ in checked:
            if backup is None:
                _remove_file(destination)
                _cleanup_empty_dirs(destination.parent, target)
            else:
                _write_bytes(destination, _read_bytes(backup))
        _remove_file(manifest_path)
    except Exception as exc:
        rollback_errors: list[str] = []
        for _, destination, _, before, _ in reversed(checked):
            try:
                _write_bytes(destination, before)
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        if rollback_errors:
            raise InstallerError(
                "uninstall failed and rollback is incomplete; manifest/backups were retained: "
                + "; ".join(rollback_errors)
            ) from exc
        raise InstallerError(f"uninstall failed; changes rolled back: {exc}") from exc
    # Remove only the exact backup files referenced by this manifest and empty
    # parent directories.  Never recurse through arbitrary user directories.
    referenced = [entry.get("backup") for entry in entries if entry.get("backup")]
    for relative in referenced:
        try:
            backup_path = _safe_join(target, relative)
            _remove_file(backup_path)
            _cleanup_empty_dirs(backup_path.parent, target / ".codex" / BACKUP_DIR_NAME)
        except InstallerError:
            # Cleanup failure is non-destructive; leave the validated backup
            # for a later manual cleanup rather than recreating user files.
            pass
    _cleanup_empty_dirs(manifest_path.parent, target)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or safely install codex-astrator community payload")
    parser.add_argument(
        "command", nargs="?", choices=("install", "uninstall", "status", "verify"), default="install"
    )
    parser.add_argument("--scope", choices=("global", "project"), required=False)
    parser.add_argument("--target", required=True, help="explicit target directory (never inferred)")
    parser.add_argument("--source", help="payload/repository root (defaults to this repository)")
    parser.add_argument("--apply", action="store_true", help="publish changes; default is a read-only preview")
    parser.add_argument("--replace-existing", action="store_true", help="allow replacing conflicts when applying")
    parser.add_argument("--uninstall", action="store_true", help="uninstall the manifest at --target")
    args = parser.parse_args(argv)
    if args.uninstall:
        args.command = "uninstall"
    if not args.scope:
        parser.error("--scope is required")
    if args.command == "uninstall" and args.source:
        parser.error("--source is not used for uninstall")
    if args.command == "uninstall" and args.replace_existing:
        parser.error("--replace-existing is not used for uninstall")
    if args.command in {"status", "verify"}:
        if args.source:
            parser.error(f"--source is not used for {args.command}")
        if args.apply:
            parser.error(f"--apply is not used for {args.command}; it is always read-only")
        if args.replace_existing:
            parser.error(f"--replace-existing is not used for {args.command}")
    return args


def main(argv: list[str] | None = None) -> int:
    global _FAIL_AFTER
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    target = Path(args.target).expanduser().absolute()
    if not target.exists() or not target.is_dir() or target.is_symlink():
        print(f"error: target must be an existing non-symlink directory: {target}", file=sys.stderr)
        return 2
    try:
        if args.command in {"status", "verify"}:
            report = _inspect_installation(target, args.scope)
            _print_status(report, args.scope)
            if report.state == "healthy":
                return 0
            if args.command == "status" and report.state == "absent":
                return 0
            return 2
        if args.command == "uninstall":
            if args.apply:
                with TargetLock(target):
                    manifest_path, manifest, manifest_snapshot = _load_manifest(target, args.scope)
                    if manifest is None:
                        raise InstallerError("no installer manifest found")
                    _uninstall(
                        target, args.scope, manifest_path, manifest, manifest_snapshot,
                        apply=True,
                    )
            else:
                manifest_path, manifest, manifest_snapshot = _load_manifest(target, args.scope)
                if manifest is None:
                    raise InstallerError("no installer manifest found")
                _uninstall(
                    target, args.scope, manifest_path, manifest, manifest_snapshot,
                    apply=False,
                )
            if not args.apply:
                return 0
            print("UNINSTALLED: restored originals and removed managed files")
            return 0
        source = Path(args.source).expanduser().absolute() if args.source else Path(__file__).resolve().parents[1]
        def install_or_preview() -> int:
            global _FAIL_AFTER
            if source.is_symlink():
                raise InstallerError(f"payload source is a symlink: {source}")
            if not source.exists():
                raise InstallerError(f"payload source is unavailable: {source}")
            plan, conflicts, old_manifest, manifest_path, managed_agent_paths, snapshot = _build_plan(
                target, args.scope, source, args.replace_existing
            )
            agents_rel = ".codex/AGENTS.md" if args.scope == "global" else "AGENTS.md"
            agents_snapshot = snapshot.destinations[agents_rel]
            migrate_manifest_metadata = (
                old_manifest is not None
                and "expected_role_sha256" not in old_manifest
            )
            _print_plan(
                plan,
                conflicts,
                apply=args.apply,
                replace_existing=args.replace_existing,
                protect_backups=not snapshot.backup_ignore.exists,
                unmanaged_orchestration=(
                    agents_snapshot.exists
                    and _has_unmanaged_orchestration(agents_snapshot.content or b"")
                ),
                migrate_manifest_metadata=migrate_manifest_metadata,
            )
            if conflicts and (not args.apply or not args.replace_existing):
                return 3
            if not args.apply:
                return 0
            # Test-only fault injection lets rollback be tested without a
            # public failure switch or an actual filesystem fault.
            injected = os.environ.get("CODEX_ASTRATOR_TEST_FAIL_AFTER")
            _FAIL_AFTER = int(injected) if injected is not None else None
            _apply_plan(target, args.scope, plan, old_manifest, manifest_path, managed_agent_paths, snapshot)
            return 0

        if args.apply:
            with TargetLock(target):
                result = install_or_preview()
        else:
            result = install_or_preview()
        if result:
            return result
        if not args.apply:
            return 0
        print("APPLIED: transaction committed")
        return 0
    except (InstallerError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        _FAIL_AFTER = None


if __name__ == "__main__":
    raise SystemExit(main())
