#!/usr/bin/env python3
"""Static payload checker for codex-astrator.

Doctor deliberately checks files and parses TOML only.  It does not inspect a
user's personal configuration and does not claim runtime compatibility.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tomllib


EXPECTED_ROLES = {
    "explorer": ("gpt-5.6-luna", "low", "read-only"),
    "worker": ("gpt-5.6-luna", "xhigh", "workspace-write"),
    "complex_worker": ("gpt-5.6-sol", "medium", "workspace-write"),
    "tester": ("gpt-5.6-luna", "medium", "workspace-write"),
    "researcher": ("gpt-5.6-luna", "medium", "read-only"),
    "reviewer": ("gpt-6-astra", "low", "read-only"),
}

try:
    from install import InstallerError, _assert_not_symlink, _load_profile, _resolve_source, _source_files
except ImportError:  # pragma: no cover - allows direct execution from another cwd
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from install import InstallerError, _assert_not_symlink, _load_profile, _resolve_source, _source_files


def _check(source: Path) -> list[str]:
    problems: list[str] = []
    try:
        profile, agents, skills, instructions = _resolve_source(source)
        _load_profile(profile)
        profile_data = tomllib.loads(profile.read_text(encoding="utf-8"))
        expected_profile = {
            "model": "gpt-6-astra",
            "model_reasoning_effort": "low",
            "model_context_window": 400000,
            "model_auto_compact_token_limit": 250000,
            "model_auto_compact_token_limit_scope": "total",
            "agents": {"enabled": True, "max_concurrent_threads_per_session": 3},
            "features": {"multi_agent": True},
        }
        if profile_data != expected_profile:
            raise InstallerError("reference profile does not match the single supported preset")
        _assert_not_symlink(instructions, allow_missing=False)
        instructions.read_text(encoding="utf-8")
        actual_roles: dict[str, tuple[str, str, str]] = {}
        for file, relative in _source_files(agents):
            if not file.name.lower().endswith(".toml"):
                raise InstallerError(f"agent payload must be TOML: {file}")
            try:
                role = tomllib.loads(file.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                raise InstallerError(f"invalid agent TOML {file}: {exc}") from exc
            name = role.get("name")
            if not isinstance(name, str) or relative != f"{name}.toml":
                raise InstallerError(f"agent filename/name mismatch: {file}")
            actual_roles[name] = (
                role.get("model"), role.get("model_reasoning_effort"), role.get("sandbox_mode")
            )
        if actual_roles != EXPECTED_ROLES:
            raise InstallerError("agent payload does not match the six supported role definitions")
        skill_files = list(_source_files(skills))
        if any(not relative.endswith("/SKILL.md") for _, relative in skill_files):
            raise InstallerError("skill payload must contain only SKILL.md files")
        if not any(relative.endswith("/SKILL.md") for _, relative in skill_files):
            raise InstallerError("payload has no SKILL.md file")
        print(f"OK: payload files parse and pass static safety checks ({source})")
    except (InstallerError, OSError) as exc:
        problems.append(str(exc))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Static payload and TOML checker (not a runtime compatibility test)")
    parser.add_argument("--source", help="payload/repository root (defaults to this repository)")
    args = parser.parse_args(argv)
    source = Path(args.source).expanduser().absolute() if args.source else Path(__file__).resolve().parents[1]
    problems = _check(source)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print("NOTE: doctor performs parse/file checks only; runtime compatibility is not evaluated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
