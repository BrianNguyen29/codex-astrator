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

The checked-in workflow is configured as independent jobs on
`windows-latest`, `ubuntu-latest`, and `macos-latest`, with Python 3.11 only
and `fail-fast: false`. It parses the payload, runs `doctor`, and runs the
focused tests on each matrix entry. The
[observed run for b16999d](https://github.com/BrianNguyen29/codex-astrator/actions/runs/34311240409)
passed on Windows and Ubuntu, but failed the focused tests on macOS. Parsing
and doctor passed on all three hosts. These results apply to that revision,
not to subsequent local fixes. The workflow does not exercise a live Codex
host or a real user project.
Broaden the Python matrix only after the initial three-host run has produced
evidence.

| Surface | Windows + Python 3.11 | Ubuntu + Python 3.11 | macOS + Python 3.11 | Live Codex runtime |
| --- | --- | --- | --- | --- |
| Payload and reference-profile TOML parsing at b16999d | Passed | Passed | Passed | Unverified |
| `doctor` layout check at b16999d | Passed | Passed | Passed | Unverified |
| Focused tests at b16999d | Passed | Passed | Failed | Unverified |
| Live Codex host loading and role execution | Not covered by CI | Not covered by CI | Not covered by CI | Unverified |
| Installer preview/apply filesystem behavior | Covered by focused tests using disposable targets; real-target permissions are not covered | Same | Same | Unverified |

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
6. Run `python scripts/install.py status --scope project --target PATH` and
   `python scripts/install.py verify --scope project --target PATH` to
   distinguish file integrity from runtime compatibility.
7. Start Codex from the target project where project-scoped configuration is
   trusted and loaded by that host.

## Opt-in manual runtime smoke

The [evaluation harness](evaluation.md) supplies disposable cases and records
the latest bounded attempt, including blockers rather than inferred success.

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
