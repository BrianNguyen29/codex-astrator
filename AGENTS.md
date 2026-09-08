# Contributor instructions

This repository packages a public, sanitized Codex orchestration payload and a
small Python installer. Keep the repository useful as a reviewable source
distribution: the payload must never contain personal configuration,
credentials, rollout logs, or machine-specific paths.

## Repository map

- `payload/` is the installable content: named agent profiles, the
  `astra-orchestrator` skill, and project/global instructions.
- `profiles/` contains tool-neutral model presets used by the installer.
- `docs/` explains architecture, installation, compatibility, permissions, and
  token measurement limitations.
- `scripts/` contains the installer and related command-line helpers.
- `tests/` contains focused installer and payload checks.

## Autonomy and clarification

If ambiguity in my instructions would materially affect the outcome, scope, or risk, ask me to clarify before taking the affected action. For minor ambiguity, use reasonable defaults, state relevant assumptions, and continue independent work.

## Contribution rules

- Preserve unrelated user changes and keep one clear owner per file.
- Do not add personal `.codex` configuration, authentication material, session
  or rollout logs, cache contents, or absolute home-directory paths.
- Keep model names and concurrency limits in sync across the reference profile,
  payload role files, and documentation.
- Keep the English and Vietnamese README files aligned for user-visible
  behavior and safety notes.
- Derived material must retain the upstream attribution and modification notice
  described in `NOTICE`.
- Do not publish, deploy, commit, or push as part of local validation.

## Focused validation

Use Python 3.11 or newer. Before submitting a change, run the focused tests and
the installer parser/doctor check from the repository root:

```text
python -m unittest discover -s tests -p "test_*.py"
python scripts/doctor.py --source .
```

The CI workflow is intentionally Windows-only until cross-host execution has
been validated. Report checks that could not run instead of treating them as
passing.
