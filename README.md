# Codex Astrator

Codex Astrator is a reviewable, sanitized payload for delegation-first Codex
work. It ships one reference preset with a GPT-6 Astra root and six neutral
roles for routine work, complex implementation, exploration, testing,
research, and independent review.

This repository contains source instructions and a small Python installer. It
does not install Codex, models, credentials, plugins, or third-party packages.
Model availability is host- and account-dependent and is not guaranteed by
this project.

Vietnamese documentation: [README.vi.md](README.vi.md).

## What is included

```text
payload/
  agents/                         six named TOML roles
  skills/astra-orchestrator/      delegation-first skill
  instructions/                   project/global orchestration guidance
profiles/reference.toml           reference model and concurrency preset
docs/                             architecture and operational guidance
scripts/install.py                install and uninstall CLI
scripts/doctor.py                 static payload/file/TOML checker
tests/                            focused installer tests
```

The installable payload is intentionally separate from this repository's
contributor `AGENTS.md`. The latter governs changes to this source tree; the
payload instructions govern a target Codex project after installation.

## Install safely

Requires Python 3.11 or newer. From a checkout of this repository, preview a
project-scoped install first:

```text
python scripts/install.py install --scope project --target PATH
```

The install command is dry-run by default. Add `--apply` only after reviewing
the planned paths:

```text
python scripts/install.py install --scope project --target PATH --apply
```

Use `--scope global` with the target set to the intended home directory. A
global install writes `.codex/config.toml`, `.codex/AGENTS.md`,
`.codex/agents/`, and `.agents/skills/` below that target. A project install
writes `.codex/` and `.agents/` below the target repository and writes the
payload orchestration instructions to its root `AGENTS.md`.

If the source checkout is not discoverable automatically, pass the repository
root explicitly with `--source PATH`:

```text
python scripts/install.py install --source PATH --scope project --target TARGET --apply
```

Existing files are never replaced implicitly. When the dry-run shows intended
collisions, add `--replace-existing` explicitly along with `--apply`; review
the listed paths before proceeding. The installer preserves unrelated Codex
settings while applying its managed values; review the plan and preserve any
local policy you need.

For an existing current-version installation, every tracked file must still
match its recorded installed hash before an update is planned. Drift is refused
even with `--replace-existing`. The installer snapshots the manifest and all
relevant destinations and rechecks them immediately before writing, but it does
not lock the filesystem; avoid concurrent installers or editors during
`--apply`.

Upgrading from an installed version with a different managed role set is
refused even with `--replace-existing`. Uninstall the previous version first,
review the restored files, and then install this version.

Legacy safety-version manifests are not automatically upgraded or uninstalled,
even when their current hashes match. Preview and apply both leave their files
and backups untouched and report manual reconciliation guidance.

To preview removal of files previously installed by this payload, use either
form of the uninstall command. Apply removal only deliberately:

```text
python scripts/install.py uninstall --scope project --target PATH
python scripts/install.py uninstall --scope project --target PATH --apply
python scripts/install.py --uninstall --scope project --target PATH
```

`doctor` performs file and TOML parsing checks without installing anything:

```text
python scripts/doctor.py --source .
```

See [docs/installation.md](docs/installation.md) for path mapping and
collision behavior, and [docs/permissions.md](docs/permissions.md) for the
write boundary.

## Operating model

Delegate execution and substantive investigation by default, including small
edits; only pure conversational answers stay direct. Routine implementation uses one
bounded worker for discovery, editing, and focused tests. Route uncertain
invariants, persistence, concurrency, rollback, and difficult recovery directly
to the complex worker. Add an explorer, tester, or researcher only when
independent evidence materially helps. Use the read-only reviewer for
substantive architecture, security, migration,
permissions, configuration, policy, or compatibility risk. No more than three
child agents are active at once, subject to a lower host limit.

Every child receives one objective, exact scope and ownership, only necessary
context, constraints, deliverable, and acceptance checks. Children do not spawn
children or edit outside their scope. The root preserves unrelated changes,
integrates findings, and reports checks that are unavailable or unverified.

Read [docs/architecture.md](docs/architecture.md) for the topology and
[payload/skills/astra-orchestrator/SKILL.md](payload/skills/astra-orchestrator/SKILL.md)
for the complete routing rules.

## Compatibility and verification

The source and installer target Python 3.11+. The checked-in CI workflow runs
on Windows only until the project has validated other hosts. macOS and Linux
behavior, and availability of each named model on a particular account, remain
unverified. See [docs/compatibility.md](docs/compatibility.md).

Orchestration consumes model context and rate-limit budget. See
[docs/token-usage.md](docs/token-usage.md) for measurement guidance. This
project makes no token- or cost-savings promise; measure your own workloads.

## License and attribution

The repository is distributed under the Apache License 2.0; see
[LICENSE](LICENSE). Portions of the orchestration material are derived from
[donvito/codex-astra-luna-orchestrator](https://github.com/donvito/codex-astra-luna-orchestrator)
under Apache-2.0. See [NOTICE](NOTICE) and the modification notices in derived
payload files.
