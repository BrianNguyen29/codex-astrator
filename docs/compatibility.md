# Compatibility

## Supported input

- Python 3.11 or newer. The installer uses the standard-library TOML parser
  available in Python 3.11+.
- A Codex environment that recognizes project/global instructions, TOML
  configuration, named agent files, and the installed skill path.

The exact feature set is controlled by the target Codex release and host. This
repository does not claim that every host supports every payload feature or
model.

## Validation status

The checked-in workflow currently runs on `windows-latest` with Python 3.11.
macOS and Linux execution has not been validated by this repository yet. Run
the focused tests and `doctor` check in your own target environment before
relying on an installation there.

Named model IDs are configuration values, not availability guarantees. Confirm
that the target account and host expose `gpt-6-astra`, `gpt-5.6-luna`, and
`gpt-5.6-sol` with the
requested efforts. If a model, effort, role, or delegation mechanism is
unavailable, report that limitation and use only an authorized fallback.

## Compatibility checklist

1. Confirm `python --version` is 3.11 or newer.
2. Run `python scripts/doctor.py --source .`.
3. Run a dry-run with the intended scope and target.
4. Inspect collisions and preserve unrelated target configuration.
5. Apply only after the plan is acceptable.
6. Start Codex from the target project where project-scoped configuration is
   trusted and loaded by that host.
