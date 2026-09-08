# Installation

Install/update and uninstall precheck file hashes before changing files and
attempt rollback after a publication failure. An I/O or rollback failure can
still require manual recovery from retained backups. Do not run concurrent
installers or edit destination files while an apply operation is running.

The installer is a local Python command-line tool. It does not download
dependencies, install Codex, select a model, modify authentication, or publish
anything.

## Commands

Python 3.11 or newer is required:

```text
python scripts/install.py install --scope global|project --target PATH
```

The command previews its plan by default. Add `--apply` to write files:

```text
python scripts/install.py install --scope project --target PATH --apply
```

If the payload root cannot be inferred from the script location/current
checkout, pass the repository root explicitly:

```text
python scripts/install.py install --source PATH --scope project --target TARGET --apply
```

`--source` identifies this repository, not the target project. `--target` is
the home directory for a global install and the project root for a project
install.

To remove the files owned by the payload, preview first and then add `--apply`:

```text
python scripts/install.py uninstall --scope project --target PATH
python scripts/install.py uninstall --scope project --target PATH --apply
```

`--uninstall` is an alias for the uninstall operation:

```text
python scripts/install.py --uninstall --scope project --target PATH
```

The `doctor` command performs file-existence and TOML parsing checks only:

```text
python scripts/doctor.py --source .
```

Use `python scripts/install.py --help` for the installed CLI's complete option
set. The command names above are the stable contract documented by this
repository.

## Destination mapping

| Scope | Files written below target |
| --- | --- |
| Global | `.codex/config.toml`, `.codex/AGENTS.md`, `.codex/agents/`, `.agents/skills/` |
| Project | `.codex/config.toml`, `.codex/agents/`, `.agents/skills/`, root `AGENTS.md` |

The global instructions file is placed under `.codex/AGENTS.md`; project
instructions are placed at the target root so they are project-scoped. The
optional artifact clarifications file can accompany the orchestration
instructions when the installer exposes that payload component.

## Collision and recovery behavior

An existing destination is reported by dry-run and is not replaced implicitly.
Use `--replace-existing` explicitly with `--apply` only after reviewing the
exact paths. Keep a backup or rely on version control for target files that
contain local policy. The installer preserves unrelated Codex settings while
applying its managed values; inspect the plan and preserve settings outside the
payload's owned paths.

An existing current-version installer manifest records the complete source role set separately
from the files it owns. This lets an identical pre-existing role file remain
unmanaged and survive uninstall. If a later source contains a different role
set, installation refuses before planning writes,
including when `--replace-existing` is supplied. This prevents renamed roles
from leaving stale managed files behind. Preview and apply uninstall of the
previous version first, inspect the restored target, then install the new
version.

Before an install/update plan is built, every file tracked by the current
manifest must exist as a regular file and match its recorded installed hash.
Drift is refused even with `--replace-existing`; that option does not transfer
ownership of user edits to the installer. The plan snapshots the manifest and
all relevant destinations, including identical pre-existing files that remain
unmanaged, and checks those snapshots again immediately before its first
write. A stale plan fails without applying or rolling back over the intervening
content.

Manifest safety version 2 provides these update checks. Version 1 manifests
are not automatically promoted: install/update and uninstall, including their
previews, report a blocked legacy state and preserve current files and backups.
Manually compare each installed file with its referenced backup, decide which
content to retain, and remove the legacy manifest only after that reconciliation.
The installer deliberately performs no automatic restore, export, or migration
from a legacy manifest.

Uninstall is also preview-first. With `--apply`, it removes only paths that the
payload identifies as owned for the selected scope. Verify the target and plan
before approving a destructive operation.

These checks narrow the time-of-check/time-of-use window but do not lock the
target. An external editor or process can still race after the final check, so
keep the target quiescent during `--apply`.
