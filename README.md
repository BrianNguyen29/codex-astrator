# Codex Astrator

**A reviewable, delegation-first orchestration payload for Codex.**

Codex Astrator gives a Codex project an explicit root/child operating model,
six named roles, and a preview-first Python installer. Delegation boundaries,
model settings, and write scope live in files you can inspect and version. It
is a sanitized source distribution—not a hosted service.

[![Validate](https://github.com/BrianNguyen29/codex-astrator/actions/workflows/validate.yml/badge.svg)](https://github.com/BrianNguyen29/codex-astrator/actions/workflows/validate.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Apache License 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

[English](README.md) · [Tiếng Việt](README.vi.md)

> Status: `v0.1.0` is planned and remains pre-release; it has not been
> released.

## Why Codex Astrator?

- Give the root clear ownership of interpretation, authorization, integration,
  acceptance, and final reporting.
- Route routine implementation, difficult recovery, discovery, research,
  testing, and independent review to named roles with explicit access modes.
- Review an installation plan before it changes a target project, while
  preserving settings outside the payload's managed paths.
- Keep the orchestration layer public, tool-neutral, and free of credentials,
  session data, and machine-specific configuration.

## What is included

```text
payload/
  agents/                         six named TOML roles
  skills/astra-orchestrator/      delegation and routing rules
  instructions/                   project/global orchestration guidance
profiles/reference.toml           one public reference preset
docs/                             architecture, installation, safety, and limits
scripts/install.py                install/update and uninstall CLI
scripts/doctor.py                 static payload and TOML checker
tests/                            focused installer tests
```

The installable payload is separate from this repository's contributor
`AGENTS.md`: that file governs contributions here; the payload instructions
govern a target Codex project after installation.

## Reference preset

The repository ships one reference preset. It enables multi-agent operation
and allows up to three child threads per session. Confirm model availability
and supported features with the target host and account.

The preset opts into the experimental context-management feature with the
`[features.context_management]` table and `experimental_mode = true`. OpenAI
clients keep this opt-in off by default; verify that the target client and
account are eligible before relying on it. Experimental context management
provides no performance or token-savings guarantee.

The root preset requests a 400,000-token context window and automatic
compaction at 250,000 tokens, scoped to total usage. These are client-side
configuration values; they do not guarantee a server-side input cap or token
savings. Confirm that the target host supports them.

| Role | Model | Effort | Access | Responsibility |
| --- | --- | --- | --- | --- |
| Root | `gpt-6-astra` | `low` | host-defined | Decide, integrate, verify |
| `explorer` | `gpt-5.6-luna` | `low` | read-only | Locate paths, flow, and tests |
| `worker` | `gpt-5.6-luna` | `xhigh` | workspace-write | Routine bounded implementation |
| `complex_worker` | `gpt-5.6-sol` | `medium` | workspace-write | Uncertain invariants, persistence, concurrency, rollback, recovery |
| `tester` | `gpt-5.6-luna` | `medium` | workspace-write | Reproduce and verify behavior |
| `researcher` | `gpt-5.6-luna` | `medium` | read-only | Answer bounded technical questions |
| `reviewer` | `gpt-6-astra` | `low` | read-only | Independently assess material risk |

## Quick start

Requires Python 3.11 or newer.

```bash
git clone https://github.com/BrianNguyen29/codex-astrator.git
cd codex-astrator
```

Preview a project-scoped install. The command is read-only by default:

```bash
python scripts/install.py install --scope project --target "PATH/TO/YOUR_PROJECT"
```

Inspect the plan, then apply it deliberately:

```bash
python scripts/install.py install --scope project --target "PATH/TO/YOUR_PROJECT" --apply
```

To preview an optional global install, target the intended home directory.
Add `--apply` only after reviewing its broader scope:

```bash
python scripts/install.py install --scope global --target "PATH/TO/YOUR_HOME"
```

Use `--source PATH` when running the installer from outside the checkout. For
uninstall, preview first and add `--apply` only after reviewing the owned paths;
the complete command contract is in [Installation](docs/installation.md).

The operating loop is:

`root decision → bounded child work → evidence → root integration and verification`

## Safety and boundaries

- Manifest v3 preserves supported POSIX file modes and uses private backup
  modes. Legacy v1/v2 restoration requires manual reconciliation. Windows
  existing-file ACL backup/restore is unsupported and fails closed; see
  [permission limits](docs/permissions.md#filesystem-permission-limits).
- Existing destination files are reported as collisions and are never replaced
  implicitly. Use `--replace-existing` only with an explicit `--apply` after
  reviewing the exact paths.
- Current-version manifests refuse updates when any tracked file has drifted,
  even with `--replace-existing`. Mutating applies coordinate through a
  per-target cooperative lock at `.codex/.astrator.lock`, held through commit
  or rollback; snapshots still matter because external editors do not join the
  lock and can race after the final check.
- Legacy safety-version manifests are not automatically upgraded or removed.
  Files and backups remain untouched until manual reconciliation.
- Changes to the managed role set require uninstalling the previous version,
  inspecting the restored files, and then installing the new version.
- Apply operations attempt rollback. If writing or rollback fails, retained
  transaction backups may require manual recovery.
- The installer does not install Codex, models, plugins, packages, or
  credentials; authentication, API calls, publishing, deployment, commits,
  and pushes are outside its boundary.

See [installation and recovery details](docs/installation.md) and the
[permission boundary](docs/permissions.md).

## Compatibility and verification

The source and installer require Python 3.11+. The checked-in
[GitHub Actions workflow](.github/workflows/validate.yml) validates source
parsing, layout, and focused tests independently on Windows, Ubuntu, and macOS
with Python 3.11, plus one Ubuntu job with Python 3.12
(`fail-fast: false`, four jobs total). An [observed run at the exact hardening
revision `9515d86`](https://github.com/BrianNguyen29/codex-astrator/actions/runs/34341342685)
passed all four jobs. This confirms hosted matrix coverage for that commit;
it does not establish live Codex runtime compatibility or complete the other
release gates.
The workflow does not exercise a live Codex host. Focused
preview/apply tests use disposable targets; real-target permission behavior is
not covered. Named model availability depends on the target host and account.
The optional smoke protocol uses only a disposable project; read-only roles
must not be tested against real project files.

This project makes no token-savings or cost-reduction promise. Measure
representative workloads using the guidance in [Token usage](docs/token-usage.md).

Run the focused checks from the repository root:

```bash
python -m unittest discover -s tests -p "test_*.py"
python scripts/doctor.py --source .
```

## Documentation and contribution

- [Architecture](docs/architecture.md) — topology, ownership, and routing
- [Installation](docs/installation.md) — commands, mapping, recovery, and troubleshooting
- [Permissions](docs/permissions.md) — write and approval boundaries
- [Compatibility](docs/compatibility.md) — matrix and opt-in runtime smoke protocol
- [Token usage](docs/token-usage.md) — measurement protocol and limitations
- [Evaluation](docs/evaluation.md) — local harness, bounded plan, and pilot evidence
- [Release checklist](docs/release-checklist.md) — planned `v0.1.0` pre-release gate
- [Changelog](CHANGELOG.md) — pending and validated changes
- [Security](SECURITY.md) — private vulnerability reporting and safe reports
- [Orchestrator skill](payload/skills/astra-orchestrator/SKILL.md) — complete routing rules

Contributions are welcome. Keep the payload sanitized, preserve unrelated
changes, keep role settings synchronized across source and docs, and keep
project licensing notices accurate.

## License

Distributed under the [Apache License 2.0](LICENSE). See [NOTICE](NOTICE).
