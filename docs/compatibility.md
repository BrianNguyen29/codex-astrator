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
It parses the payload, runs `doctor`, and runs the focused tests; it does not
exercise a live Codex host or a real user project. macOS and Linux runtime
behavior has not been validated by this repository.

| Surface | Windows + Python 3.11 CI | macOS/Linux runtime |
| --- | --- | --- |
| Payload and reference-profile TOML parsing | Checked in CI | Unverified |
| `doctor` layout check and focused installer tests | Checked in CI | Unverified |
| Live Codex host loading and role execution | Not covered by CI | Unverified |
| Installer preview/apply filesystem behavior | Covered by focused tests using disposable targets; real-target permissions are not covered | Unverified |

Run the focused tests and `doctor` check in each target environment before
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

## Opt-in manual runtime smoke

This protocol is optional for end users and is not a general compatibility
guarantee. It is required as a release-gate check for `v0.1.0`. Use an empty,
disposable project that contains no real work, credentials, or private
configuration. Verify the target path before applying anything, then:

1. Run the project-scoped install preview, inspect every path, and apply only
   to that disposable target.
2. Start Codex from the disposable project and run a harmless, bounded task
   against a synthetic file such as `SMOKE.md`. Keep the task scoped to that
   file and verify the target's file hashes or `git status` afterward.
3. Exercise only the roles needed for the check. For `explorer`, `researcher`,
   and `reviewer`, use read-only prompts limited to the synthetic file; do not
   test those roles against real project files. A routine worker/tester smoke
   may make one bounded write to that synthetic file as part of this protocol;
   no separate per-role approval is needed for that scoped disposable check.
   Keep every write-capable test confined to disposable files and do not test
   real-target permissions.
4. Record the exact host, role, model, reasoning effort, and access mode from
   the execution trace or host view. If any field is unavailable, record it as
   unavailable rather than inferring it from the preset.
5. Remove the disposable target only through its normal local workflow after
   preserving the sanitized result. Do not upload configuration files, logs,
   prompts, credentials, or personal paths. If Git is unavailable, record
   tracked-backup detection as unavailable rather than treating it as passed.
