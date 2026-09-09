# Permissions and safety

The installer is designed for explicit, local, preview-first changes.

## Write boundary

Without `--apply`, `install` and `uninstall` only inspect the source and print a
plan. With `--apply`, the selected scope may write or remove only its mapped
payload paths below the explicit `--target`:

- global: `.codex/config.toml`, `.codex/AGENTS.md`, `.codex/agents/`, and
  `.agents/skills/`;
- project: `.codex/config.toml`, `.codex/agents/`, `.agents/skills/`, and the
  target-root `AGENTS.md`.

The installer does not read authentication stores or use credentials. It does
not install packages, contact a model API, publish, deploy, commit, or push. It
may read explicit target configuration/instruction files to merge them and copy
their prior bytes into local recovery backups; those bytes may contain
sensitive values.

Apply may also create and maintain installer state below the target-local
`.codex/.astrator-backups/`, including `.codex/.astrator-backups/.gitignore`
with a protective `*` rule before any backup bytes are written. This is not a
project-root `.gitignore`. Unsafe rules, symlinks, and Git-tracked backup
content fail closed. If Git is unavailable, tracked-content detection is
unavailable and is not evidence that the backup is untracked. A newly created
protective `.gitignore` is intentionally retained if an apply rolls back.

The recovery mutation guard allows only that protective `.gitignore` and backup
files referenced by the loaded manifest. Retained transaction or orphan
artifacts block install/update and uninstall, including read-only previews. A
blocked preview exits `2` with a content-free `recovery-required` result and
does not mutate the target. Apply repeats the guard after acquiring the
per-target cooperative lock and before any managed, backup, or manifest
write/delete; `--replace-existing` cannot bypass it. Reconcile the current
files and recovery bytes manually before retrying.

## Approval boundaries

Review the dry-run before `--apply`. Existing files require the explicit
`--replace-existing` option; do not use it casually on a global config or an
existing instruction file. `uninstall --apply` is destructive within the
payload-owned paths, so verify scope and target first.

`--replace-existing` resolves only a first-install collision. It never bypasses
drift protection for paths already tracked by a current installer manifest.
Install/update validates all tracked regular files against their installed
hashes before planning, snapshots the manifest and relevant destinations, and
rechecks the snapshot immediately before writing. Legacy safety-version
manifests block automatic install/update and uninstall; their current files and
backups are left for explicit manual reconciliation.

A current v2 manifest that lacks `expected_role_sha256` is an explicit,
recoverable metadata migration case, not permission to infer or change
ownership. Its install/update preview counts one manifest metadata change and
states that role-integrity metadata will be added with ownership and backup
entries unchanged. Only an explicitly approved `--apply` writes the role
hashes; `status` and `verify` remain read-only and never migrate manifests.

The installer cannot decide which local policy should win. It preserves
settings outside the mapped paths; review managed-value conflicts and resolve
them in the target project. Project trust and any host-specific permission
prompts remain the user's responsibility.

Mutating `install --apply` and `uninstall --apply` acquire a per-target,
cooperative OS lock at `.codex/.astrator.lock` before manifest/source/destination
validation and hold it through commit or rollback. Preview, `status`, and
`verify` never create or acquire the lock. The lock contains no configuration or
user content and may remain as a harmless marker. It serializes only
cooperating installer processes; it is not a security boundary and cannot stop
an external editor or process. Existing snapshots still detect many
non-cooperating edits, but cannot eliminate the residual race after the final
check. This applies equally to global targets, where drift in managed files
must still be reconciled explicitly.

`status` is read-only and exits successfully for healthy or absent state;
`verify` is read-only and succeeds only for a current healthy installation.
Both reject mutating flags and validate manifest structure, path allowlists,
installed/original-backup hashes, backup privacy, and role/profile consistency;
neither proves runtime model availability or source freshness. Recovery-required
state is reported when retained unreferenced artifacts are present; status and
verify preserve those bytes. See
[Installation](installation.md) for the exact output and exit-status contract.

## Agent permissions

The named roles express intended access: explorers, researchers, and reviewers
are read-only; workers, complex workers, and testers are workspace-write. A generic spawn API may
not enforce a TOML sandbox solely from the role name, so callers must pass and
verify model, effort, and access controls supported by their host. Do not claim
that a sandbox or model override was enforced when the execution trace cannot
show it.
