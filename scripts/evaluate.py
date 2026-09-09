"""Offline smoke and benchmark harness for the sanitized repository.

Default checks only read files. Explicit --execute runs reviewed synthetic
task code in a subprocess with a timeout; this is NOT a security sandbox.
No model calls or host telemetry are collected. Live Codex runs are separate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import types
import unittest
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
CONFIG_PATH = Path(__file__).resolve().parent.parent / "evals" / "tasks.json"
MANIFEST_NAME = "manifest.json"
METADATA_NAME = ".eval-metadata.json"
CHECK_KIND = "offline-evaluation-check"
REPORT_KIND = "offline-evaluation"
MAX_REPEATS = 10
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

ROLES = {
    "unavailable",
    "root",
    "explorer",
    "worker",
    "complex_worker",
    "tester",
    "researcher",
    "reviewer",
}
MODELS = {"unavailable", "gpt-6-astra", "gpt-5.6-luna", "gpt-5.6-sol"}
EFFORTS = {"unavailable", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
ACCESS_MODES = {"unavailable", "read-only", "workspace-write", "host-defined"}
UNSAFE_KEYS = {"path", "paths", "prompt", "prompts", "source", "workspace", "cwd", "home"}


class EvaluationError(ValueError):
    """A user-facing, safe validation error."""


def _load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError("cannot load the offline task configuration") from exc
    if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
        raise EvaluationError("unsupported offline task configuration")
    tasks = config.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise EvaluationError("offline task configuration has no tasks")
    seen: set[str] = set()
    for task in tasks:
        _validate_task(task, seen)
    return config


def _validate_task(task: Any, seen: set[str] | None = None) -> None:
    if not isinstance(task, dict):
        raise EvaluationError("offline task configuration contains an invalid task")
    task_id = task.get("id")
    if not isinstance(task_id, str) or not SAFE_ID.fullmatch(task_id):
        raise EvaluationError("offline task has an invalid id")
    if seen is not None:
        if task_id in seen:
            raise EvaluationError("offline task ids must be unique")
        seen.add(task_id)
    if not isinstance(task.get("kind"), str) or not isinstance(task.get("prompt"), str):
        raise EvaluationError("offline task is missing its description")
    behavior = task.get("behavior")
    behavior_kind = behavior.get("kind") if isinstance(behavior, dict) else None
    if not isinstance(behavior, dict) or not isinstance(behavior_kind, str) or behavior_kind not in {
        "function", "slug", "state", "structural-only"
    }:
        raise EvaluationError(f"offline task {task_id} has invalid behavior checks")
    files = task.get("files")
    invariants = task.get("invariants")
    if not isinstance(files, list) or not files or not isinstance(invariants, list) or not invariants:
        raise EvaluationError(f"offline task {task_id} is incomplete")
    file_paths: set[str] = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise EvaluationError(f"offline task {task_id} has an invalid file")
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or relative in file_paths:
            raise EvaluationError(f"offline task {task_id} has an invalid file path")
        _validate_relative_path(relative)
        if not isinstance(entry.get("content"), str):
            raise EvaluationError(f"offline task {task_id} has invalid file content")
        file_paths.add(relative)
    invariant_ids: set[str] = set()
    for invariant in invariants:
        if not isinstance(invariant, dict):
            raise EvaluationError(f"offline task {task_id} has an invalid invariant")
        invariant_id = invariant.get("id")
        if not isinstance(invariant_id, str) or not SAFE_ID.fullmatch(invariant_id) or invariant_id in invariant_ids:
            raise EvaluationError(f"offline task {task_id} has an invalid invariant id")
        invariant_ids.add(invariant_id)
        invariant_type = invariant.get("type")
        if not isinstance(invariant_type, str) or invariant_type not in {"contains", "not_contains"}:
            raise EvaluationError(f"offline task {task_id} has an unsupported invariant")
        relative = invariant.get("path")
        if not isinstance(relative, str) or relative not in file_paths:
            raise EvaluationError(f"offline task {task_id} invariant refers to an unknown file")
        if not isinstance(invariant.get("value"), str) or not invariant["value"]:
            raise EvaluationError(f"offline task {task_id} invariant has invalid text")


def _validate_relative_path(value: str) -> None:
    """Accept only slash-separated, workspace-relative paths."""
    if "\\" in value or ":" in value or value.startswith("/") or value.startswith("~"):
        raise EvaluationError("workspace paths must be relative and use forward slashes")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise EvaluationError("workspace paths must not contain traversal components")


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _check_parent(path: Path) -> None:
    """Require an existing, non-symlink parent without following links."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    current = Path(absolute.anchor)
    for component in absolute.relative_to(absolute.anchor).parts[:-1]:
        current /= component
        if current.is_symlink():
            raise EvaluationError("refusing a path with a symlinked parent")
        if not current.is_dir():
            raise EvaluationError("the output parent must be an existing directory")
    parent = absolute.parent
    if parent.is_symlink() or not parent.is_dir():
        raise EvaluationError("the output parent must be an existing, non-symlink directory")


def _require_new_directory(path: Path) -> None:
    _check_parent(path)
    if _lexists(path):
        raise EvaluationError("refusing to overwrite an existing or symlinked output")
    try:
        path.mkdir()
    except FileExistsError as exc:
        raise EvaluationError("refusing to overwrite an existing output") from exc
    if path.is_symlink() or not path.is_dir():
        raise EvaluationError("refusing an unsafe output directory")


def _write_new_text(path: Path, content: str) -> None:
    if _lexists(path):
        raise EvaluationError("refusing to overwrite an existing generated file")
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise EvaluationError("refusing to overwrite an existing generated file") from exc


def _ensure_directory(path: Path) -> None:
    """Create a known generated directory, or validate an existing one."""
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise EvaluationError("refusing an unsafe synthetic workspace directory")
    if not path.exists():
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise EvaluationError("refusing an unsafe synthetic workspace directory") from exc
    if path.is_symlink() or not path.is_dir():
        raise EvaluationError("refusing an unsafe synthetic workspace directory")


def _workspace_file(root: Path, relative: str) -> Path:
    _validate_relative_path(relative)
    candidate = root
    for component in relative.split("/"):
        candidate /= component
        if candidate.is_symlink():
            raise EvaluationError("refusing a symlink in the synthetic workspace")
    return candidate


def _write_json_new(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    _write_new_text(path, text)


def _task_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["id"]: task for task in config["tasks"]}


def _selected_tasks(config: dict[str, Any], task_ids: list[str] | None) -> list[dict[str, Any]]:
    tasks = _task_map(config)
    if not task_ids:
        return list(config["tasks"])
    selected: list[dict[str, Any]] = []
    for task_id in task_ids:
        if task_id not in tasks:
            raise EvaluationError(f"unknown offline task: {task_id}")
        if task_id not in {task["id"] for task in selected}:
            selected.append(tasks[task_id])
    return selected


def prepare(output: Path, task_ids: list[str] | None = None, repeats: int = 2) -> dict[str, Any]:
    """Create fresh synthetic task workspaces under an explicit new directory."""
    config = _load_config()
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= MAX_REPEATS:
        raise EvaluationError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    selected = _selected_tasks(config, task_ids)
    output = Path(output)
    _require_new_directory(output)

    entries: list[dict[str, Any]] = []
    for task in selected:
        task_root = output / task["id"]
        _require_new_directory(task_root)
        for repeat in range(1, repeats + 1):
            relative_workspace = f"{task['id']}/repeat-{repeat:02d}"
            workspace = task_root / f"repeat-{repeat:02d}"
            _require_new_directory(workspace)
            for file_entry in task["files"]:
                destination = _workspace_file(workspace, file_entry["path"])
                _ensure_directory(destination.parent)
                _write_new_text(destination, file_entry["content"])
            task_text = "\n".join(
                [
                    f"# Offline evaluation: {task['id']}",
                    "",
                    task["prompt"],
                    "",
                    "Use only the supplied synthetic files. This task is offline; do not use a shell or network.",
                    "",
                ]
            )
            _write_new_text(workspace / "TASK.md", task_text)
            _write_json_new(
                workspace / METADATA_NAME,
                {"schema_version": SCHEMA_VERSION, "task_id": task["id"], "repeat": repeat},
            )
            entries.append({"task_id": task["id"], "repeat": repeat, "workspace": relative_workspace})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "offline-evaluation-manifest",
        "repeats": repeats,
        "tasks": entries,
    }
    _write_json_new(output / MANIFEST_NAME, manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "offline-evaluation-prepared",
        "task_count": len(entries),
        "tasks": [entry["task_id"] for entry in entries],
        "repeats": repeats,
        "output": str(output),
    }


def _read_json(path: Path) -> dict[str, Any]:
    _check_parent(path)
    if path.is_symlink() or not path.is_file():
        raise EvaluationError("input must be a regular, non-symlink JSON file")
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError("input is not valid JSON") from exc
    if not isinstance(value, dict):
        raise EvaluationError("input JSON must be an object")
    return value


def _metadata_for_workspace(workspace: Path, tasks: dict[str, dict[str, Any]]) -> tuple[str, int]:
    metadata_path = workspace / METADATA_NAME
    metadata = _read_json(metadata_path)
    task_id = metadata.get("task_id")
    repeat = metadata.get("repeat")
    if metadata.get("schema_version") != SCHEMA_VERSION or not isinstance(task_id, str) or task_id not in tasks:
        raise EvaluationError("synthetic workspace metadata is invalid")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
        raise EvaluationError("synthetic workspace repeat is invalid")
    return task_id, repeat


def _manifest_workspaces(root: Path, tasks: dict[str, dict[str, Any]]) -> list[tuple[Path, str, int]]:
    manifest_path = root / MANIFEST_NAME
    if _lexists(manifest_path):
        manifest = _read_json(manifest_path)
        entries = manifest.get("tasks")
        if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("kind") != "offline-evaluation-manifest":
            raise EvaluationError("evaluation manifest is invalid")
        if not isinstance(entries, list) or not entries:
            raise EvaluationError("evaluation manifest has no tasks")
        result: list[tuple[Path, str, int]] = []
        seen: set[tuple[str, int]] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise EvaluationError("evaluation manifest has an invalid task")
            task_id = entry.get("task_id")
            repeat = entry.get("repeat")
            relative = entry.get("workspace")
            if not isinstance(task_id, str) or task_id not in tasks or isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
                raise EvaluationError("evaluation manifest has invalid task metadata")
            if not isinstance(relative, str):
                raise EvaluationError("evaluation manifest has an invalid workspace")
            _validate_relative_path(relative)
            if (task_id, repeat) in seen:
                raise EvaluationError("evaluation manifest contains duplicate tasks")
            seen.add((task_id, repeat))
            workspace = _workspace_file(root, relative)
            if workspace.is_symlink() or not workspace.is_dir():
                raise EvaluationError("evaluation workspace is not a regular directory")
            metadata_task, metadata_repeat = _metadata_for_workspace(workspace, tasks)
            if (metadata_task, metadata_repeat) != (task_id, repeat):
                raise EvaluationError("evaluation workspace metadata does not match its manifest")
            result.append((workspace, task_id, repeat))
        return result

    if _lexists(root / METADATA_NAME):
        if root.is_symlink() or not root.is_dir():
            raise EvaluationError("evaluation workspace is not a regular directory")
        task_id, repeat = _metadata_for_workspace(root, tasks)
        return [(root, task_id, repeat)]
    raise EvaluationError("workspace has no offline evaluation manifest or metadata")


def _run_invariant(workspace: Path, invariant: dict[str, Any]) -> bool:
    try:
        candidate = _workspace_file(workspace, invariant["path"])
        if candidate.is_symlink() or not candidate.is_file():
            return False
        content = candidate.read_text(encoding="utf-8")
    except (EvaluationError, OSError, UnicodeError):
        return False
    found = invariant["value"] in content
    if invariant["type"] == "not_contains":
        return not found
    return found


def _execute_module(workspace: Path, relative: str, module_name: str, package: str, modules: dict[str, Any]) -> types.ModuleType:
    """Execute reviewed synthetic code only in the opted-in child process."""
    source_path = _workspace_file(workspace, relative)
    if source_path.is_symlink() or not source_path.is_file():
        raise EvaluationError("behavior source is not a regular file")
    source = source_path.read_text(encoding="utf-8")

    if package not in sys.modules:
        parent = types.ModuleType(package)
        parent.__path__ = []
        sys.modules[package] = parent
    module = types.ModuleType(module_name)
    module.__package__ = package
    module.__file__ = "<synthetic>"
    modules[module_name] = module
    sys.modules[module_name] = module
    exec(compile(source, "<synthetic-task>", "exec"), module.__dict__, module.__dict__)
    return module


def _call_and_assert(function: Any, args: list[Any], expected: Any) -> bool:
    try:
        actual = function(*args)
        unittest.TestCase().assertEqual(actual, expected)
    except Exception:
        return False
    return True


def _behavioral_checks(task: dict[str, Any], workspace: Path) -> list[dict[str, Any]]:
    """Run only fixed tests for the named synthetic task kind."""
    behavior = task["behavior"]
    kind = behavior["kind"]
    if kind == "structural-only":
        return []
    modules: dict[str, Any] = {}
    if kind == "function":
        module = _execute_module(workspace, behavior["source"], "synthetic.main", "synthetic", modules)
        function = module.__dict__.get(behavior["function"])
        return [
            {"id": f"behavior-case-{index}", "passed": _call_and_assert(function, case["args"], case["expected"])
             if callable(function) else False}
            for index, case in enumerate(behavior["cases"], start=1)
        ]
    if kind == "slug":
        slug_module = _execute_module(workspace, "src/slug.py", "synthetic.slug", "synthetic", modules)
        report_module = _execute_module(workspace, "src/report.py", "synthetic.report", "synthetic", modules)
        slugify = slug_module.__dict__.get("slugify")
        format_label = report_module.__dict__.get("format_label")
        results = [
            {"id": f"behavior-slug-{index}", "passed": _call_and_assert(slugify, [case["input"]], case["expected"])
             if callable(slugify) else False}
            for index, case in enumerate(behavior["slug_cases"], start=1)
        ]
        results.extend(
            {"id": f"behavior-label-{index}", "passed": _call_and_assert(format_label, [case["input"]], case["expected"])
             if callable(format_label) else False}
            for index, case in enumerate(behavior["label_cases"], start=1)
        )
        return results
    if kind == "state":
        state_module = _execute_module(workspace, behavior["source"], "synthetic.state", "synthetic", modules)
        controller_module = _execute_module(workspace, behavior["controller"], "synthetic.controller", "synthetic", modules)
        session_type = state_module.__dict__.get("Session")
        results: list[dict[str, Any]] = []
        for index, case in enumerate(behavior["cases"], start=1):
            if not isinstance(session_type, type):
                passed = False
            else:
                session = session_type()
                if case["operation"] == "stop":
                    session.start()
                if case["operation"] == "run_once":
                    operation = controller_module.__dict__.get("run_once")
                else:
                    operation = getattr(session, case["operation"], None)
                try:
                    actual = operation(session) if case["operation"] == "run_once" else operation()
                except Exception:
                    passed = False
                else:
                    observed = actual if case["operation"] == "run_once" else session.state
                    passed = _call_and_assert(lambda value: value, [observed], case["expected"])
                    if case["operation"] == "run_once":
                        passed = passed and session.state == case["expected"]
            results.append({"id": f"behavior-case-{index}", "passed": passed})
        return results
    raise EvaluationError("unsupported fixed behavior check")


def _behavior_ids(task: dict[str, Any]) -> set[str]:
    behavior = task["behavior"]
    if behavior["kind"] == "function":
        return {f"behavior-case-{index}" for index, _ in enumerate(behavior["cases"], start=1)}
    if behavior["kind"] == "slug":
        slug_ids = {f"behavior-slug-{index}" for index, _ in enumerate(behavior["slug_cases"], start=1)}
        return slug_ids | {f"behavior-label-{index}" for index, _ in enumerate(behavior["label_cases"], start=1)}
    if behavior["kind"] == "state":
        return {f"behavior-case-{index}" for index, _ in enumerate(behavior["cases"], start=1)}
    return set()


def _run_behavior_child(task_id: str, workspace: Path) -> int:
    config = _load_config()
    tasks = _task_map(config)
    if task_id not in tasks or workspace.is_symlink() or not workspace.is_dir():
        return 2
    try:
        metadata_task, _ = _metadata_for_workspace(workspace, tasks)
        if metadata_task != task_id:
            return 2
        checks = _behavioral_checks(tasks[task_id], workspace)
    except (EvaluationError, OSError, UnicodeError, SyntaxError, TypeError, ImportError, AttributeError, NameError):
        checks = [{"id": check_id, "passed": False} for check_id in sorted(_behavior_ids(tasks[task_id]))]
    payload = {"schema_version": SCHEMA_VERSION, "checks": checks}
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


def _execute_behavior(task: dict[str, Any], workspace: Path) -> list[dict[str, Any]]:
    workspace = workspace.absolute()
    ids = _behavior_ids(task)
    if not ids:
        return []
    command = [sys.executable, "-I", os.fspath(Path(__file__).resolve()), "--_run-code", task["id"], os.fspath(workspace)]
    try:
        completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return [{"id": check_id, "passed": False} for check_id in sorted(ids)]
    if completed.returncode != 0:
        return [{"id": check_id, "passed": False} for check_id in sorted(ids)]
    try:
        payload = json.loads(completed.stdout)
        checks = payload["checks"]
        if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(checks, list):
            raise ValueError
        by_id = {item["id"]: item for item in checks if isinstance(item, dict) and isinstance(item.get("passed"), bool)}
        if set(by_id) != ids:
            raise ValueError
        return [{"id": check_id, "passed": by_id[check_id]["passed"]} for check_id in sorted(ids)]
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return [{"id": check_id, "passed": False} for check_id in sorted(ids)]


def check(workspace: Path, *, execute: bool = False) -> dict[str, Any]:
    """Check invariants, with optional fixed behavior tests in a child process."""
    config = _load_config()
    tasks = _task_map(config)
    root = Path(workspace)
    _check_parent(root / METADATA_NAME)
    if root.is_symlink() or not root.is_dir():
        raise EvaluationError("workspace must be a regular, non-symlink directory")
    workspaces = _manifest_workspaces(root, tasks)
    task_results: list[dict[str, Any]] = []
    total = passed = 0
    for task_workspace, task_id, repeat in workspaces:
        invariant_results: list[dict[str, Any]] = []
        behavior_ids = _behavior_ids(tasks[task_id])
        invariants = [] if execute and behavior_ids else tasks[task_id]["invariants"]
        for invariant in invariants:
            invariant_passed = _run_invariant(task_workspace, invariant)
            invariant_results.append({"id": invariant["id"], "passed": invariant_passed})
            total += 1
            passed += int(invariant_passed)
        checks = invariant_results
        behavioral = _execute_behavior(tasks[task_id], task_workspace) if execute and _behavior_ids(tasks[task_id]) else []
        if behavioral:
            # The parent process does not execute task code; it invokes this
            # same fixed checker in an isolated interpreter with a timeout.
            checks = invariant_results + behavioral
            total += len(behavioral)
            passed += sum(int(item["passed"]) for item in behavioral)
        outcome = "passed" if all(item["passed"] for item in checks) else "failed"
        task_results.append(
            {"task_id": task_id, "repeat": repeat, "outcome": outcome, "checks": checks}
        )
    failed = total - passed
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": CHECK_KIND,
        "outcome": "passed" if failed == 0 else "failed",
        "measured_checks": {"total": total, "passed": passed, "failed": failed},
        "tasks": task_results,
        "verification": {
            "mode": "behavioral" if execute else "structural",
            "behavioral_outcome": (
                "unavailable"
                if not execute or not any(_behavior_ids(tasks[task_id]) for _, task_id, _ in workspaces)
                else "passed" if all(item["passed"] for task in task_results for item in task["checks"]
                                     if item["id"] in _behavior_ids(tasks[task["task_id"]]))
                else "failed"
            ),
        },
    }


def _reject_unsafe_keys(value: Any) -> None:
    """Reject unsafe fields rather than accidentally carrying them into reports."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in UNSAFE_KEYS:
                raise EvaluationError("report input contains a path or prompt field")
            _reject_unsafe_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_unsafe_keys(child)


def _validated_check_payload(payload: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    _reject_unsafe_keys(payload)
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != CHECK_KIND:
        raise EvaluationError("report input is not an offline evaluation check")
    raw_tasks = payload.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        raise EvaluationError("report input has no task results")
    verification = payload.get("verification")
    if not isinstance(verification, dict):
        raise EvaluationError("report input has no verification mode")
    mode = verification.get("mode")
    behavioral_outcome = verification.get("behavioral_outcome")
    if (
        not isinstance(mode, str)
        or mode not in {"structural", "behavioral"}
        or not isinstance(behavioral_outcome, str)
        or behavioral_outcome not in {"passed", "failed", "unavailable"}
    ):
        raise EvaluationError("report input has invalid verification metadata")
    validated: list[dict[str, Any]] = []
    seen_tasks: set[tuple[str, int]] = set()
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            raise EvaluationError("report input has an invalid task result")
        task_id = raw_task.get("task_id")
        repeat = raw_task.get("repeat")
        if not isinstance(task_id, str) or task_id not in tasks or isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 1:
            raise EvaluationError("report input has invalid task metadata")
        if (task_id, repeat) in seen_tasks:
            raise EvaluationError("report input contains duplicate tasks")
        seen_tasks.add((task_id, repeat))
        raw_checks = raw_task.get("checks")
        if not isinstance(raw_checks, list) or not raw_checks:
            raise EvaluationError("report input has no measured checks")
        behavior_ids = _behavior_ids(tasks[task_id])
        known = behavior_ids if mode == "behavioral" and behavior_ids else {
            item["id"] for item in tasks[task_id]["invariants"]
        }
        checks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_check in raw_checks:
            if not isinstance(raw_check, dict):
                raise EvaluationError("report input has an invalid measured check")
            check_id = raw_check.get("id")
            passed = raw_check.get("passed")
            if not isinstance(check_id, str) or check_id not in known or check_id in seen or not isinstance(passed, bool):
                raise EvaluationError("report input has an invalid measured check")
            seen.add(check_id)
            checks.append({"id": check_id, "passed": passed})
        if seen != known:
            raise EvaluationError("report input does not contain the complete fixed check set")
        validated.append(
            {
                "task_id": task_id,
                "repeat": repeat,
                "outcome": "passed" if all(item["passed"] for item in checks) else "failed",
                "checks": checks,
            }
        )
    return validated


def _validate_choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EvaluationError(f"{field} must be one of the controlled values")
    return value


def _validate_number(value: Any, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise EvaluationError(f"{field} must be a non-negative number")
    return value


def _behavior_outcome(results: list[dict[str, Any]], tasks: dict[str, Any], mode: str) -> str:
    checks = [item for task in results for item in task["checks"]
              if item["id"] in _behavior_ids(tasks[task["task_id"]])]
    if mode != "behavioral" or not checks:
        return "unavailable"
    return "passed" if all(item["passed"] for item in checks) else "failed"


def build_report(
    check_payload: dict[str, Any],
    *,
    actual_role: str = "unavailable",
    actual_model: str = "unavailable",
    actual_effort: str = "unavailable",
    actual_access: str = "unavailable",
    duration_ms: int | float | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a fixed, local-only report from machine-check output.

    Reasoning tokens are retained as a separate annotation.  They are never
    added to output tokens or to a synthetic total.
    """
    config = _load_config()
    task_specs = _task_map(config)
    validated_tasks = _validated_check_payload(check_payload, task_specs)
    verification = check_payload["verification"]
    execution = {
        "role": _validate_choice(actual_role, ROLES, "actual_role"),
        "model": _validate_choice(actual_model, MODELS, "actual_model"),
        "effort": _validate_choice(actual_effort, EFFORTS, "actual_effort"),
        "access": _validate_choice(actual_access, ACCESS_MODES, "actual_access"),
    }
    duration = _validate_number(duration_ms, "duration_ms")
    usage = {} if usage is None else usage
    if not isinstance(usage, dict):
        raise EvaluationError("usage must be an object of numeric fields")
    usage_fields = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_tokens",
        "output_tokens",
        "reasoning_tokens",
    )
    usage_result: dict[str, int | float | None] = {}
    for field in usage_fields:
        value = usage.get(field)
        usage_result[field] = _validate_number(value, field)
    total = sum(len(task["checks"]) for task in validated_tasks)
    passed = sum(int(item["passed"]) for task in validated_tasks for item in task["checks"])
    failed = total - passed
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": REPORT_KIND,
        "outcome": "passed" if failed == 0 else "failed",
        "measured_checks": {"total": total, "passed": passed, "failed": failed},
        "tasks": validated_tasks,
        "verification": {
            "mode": verification["mode"],
            "behavioral_outcome": _behavior_outcome(validated_tasks, task_specs, verification["mode"]),
        },
        "execution": execution,
        "measurements": {"duration_ms": duration, "usage": usage_result},
    }


def _emit(payload: dict[str, Any], output: Path | None) -> None:
    if output is None:
        print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return
    _check_parent(output)
    if _lexists(output):
        raise EvaluationError("refusing to overwrite an existing or symlinked output")
    _write_json_new(output, payload)
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")))


def _nonnegative_number(value: str) -> int | float:
    try:
        parsed: int | float = int(value)
    except ValueError:
        try:
            parsed = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("must be a non-negative number") from exc
    if isinstance(parsed, bool) or not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative number")
    return parsed


def _positive_repeats(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if not 1 <= parsed <= MAX_REPEATS:
        raise argparse.ArgumentTypeError(f"must be an integer from 1 to {MAX_REPEATS}")
    return parsed


def _parser(config: dict[str, Any]) -> argparse.ArgumentParser:
    task_ids = [task["id"] for task in config["tasks"]]
    parser = argparse.ArgumentParser(description="Prepare and check offline synthetic Codex evaluation tasks.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare_parser = commands.add_parser("prepare", help="create fresh synthetic workspaces")
    prepare_parser.add_argument("--output", type=Path, required=True, help="new directory to create")
    prepare_parser.add_argument("--task", action="append", choices=task_ids, help="task id (default: all)")
    prepare_parser.add_argument("--repeats", "--repeat", dest="repeats", type=_positive_repeats, default=2)

    check_parser = commands.add_parser("check", help="check synthetic task invariants")
    check_parser.add_argument("--workspace", type=Path, required=True)
    check_parser.add_argument("--output", type=Path, help="new JSON file; stdout when omitted")
    check_parser.add_argument(
        "--execute",
        action="store_true",
        help="execute reviewed synthetic code with fixed tests; NOT a sandbox",
    )

    report_parser = commands.add_parser("report", help="write a sanitized local report")
    report_parser.add_argument("--input", type=Path, required=True, help="check JSON file")
    report_parser.add_argument("--output", type=Path, required=True, help="new JSON file")
    report_parser.add_argument("--actual-role", choices=sorted(ROLES), default="unavailable")
    report_parser.add_argument("--actual-model", choices=sorted(MODELS), default="unavailable")
    report_parser.add_argument("--actual-effort", choices=sorted(EFFORTS), default="unavailable")
    report_parser.add_argument("--actual-access", choices=sorted(ACCESS_MODES), default="unavailable")
    report_parser.add_argument("--duration-ms", type=_nonnegative_number)
    for field in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens"):
        report_parser.add_argument(f"--{field.replace('_', '-')}", dest=field, type=_nonnegative_number)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    try:
        arguments = list(argv) if argv is not None else sys.argv[1:]
        if len(arguments) == 3 and arguments[0] == "--_run-code":
            return _run_behavior_child(arguments[1], Path(arguments[2]))
        config = _load_config()
        args = _parser(config).parse_args(arguments)
        if args.command == "prepare":
            result = prepare(args.output, args.task, args.repeats)
            _emit(result, None)
            return 0
        if args.command == "check":
            result = check(args.workspace, execute=args.execute)
            _emit(result, args.output)
            return 0 if result["outcome"] == "passed" else 1
        usage = {
            field: getattr(args, field)
            for field in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")
        }
        result = build_report(
            _read_json(args.input),
            actual_role=args.actual_role,
            actual_model=args.actual_model,
            actual_effort=args.actual_effort,
            actual_access=args.actual_access,
            duration_ms=args.duration_ms,
            usage=usage,
        )
        _emit(result, args.output)
        return 0
    except EvaluationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (OSError, UnicodeError):
        print("error: evaluation file operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
