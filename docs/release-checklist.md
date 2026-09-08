# Release checklist — `v0.1.0` planned pre-release

This is a release plan, not a release announcement. `v0.1.0` is not released;
do not create or push its tag until the checks below are complete.

## Source and reproducibility

- [ ] Select one release commit and verify the checkout is clean.
- [ ] Confirm the tree contains no credentials, private configuration, session
      or rollout logs, personal paths, or machine-specific output.
- [ ] From that exact commit, record Python `3.11+` and run:
      `python -m unittest discover -s tests -p "test_*.py"`
      and `python scripts/doctor.py --source .`.
- [ ] Parse every payload/profile TOML file and run `git diff --check`.
- [ ] Build the source archive from the exact release revision, compare its
      file list with the repository tree, and repeat the build from the same
      revision to check reproducibility. Record only sanitized tool versions,
      revision, file-list, and checksum evidence.
- [ ] Validate local Markdown links in both README files and all `docs/` files.

## Behavior and compatibility

- [ ] Review preview output for project and global scopes using disposable
      targets; apply only after reviewing exact paths and collisions.
- [ ] Required release gate: complete the end-user-optional [manual runtime
      smoke protocol](compatibility.md#opt-in-manual-runtime-smoke) in a safe
      disposable project, recording exact host, role, model, effort, and access
      evidence. Read-only roles must be scoped to synthetic files; any routine
      write-capable role test must write only disposable synthetic files. Do
      not test real-target permissions.
- [ ] Validate current hardening for unmanaged orchestration warnings and
      `.codex/.astrator-backups/.gitignore` protection before backup bytes are
      written, including clear preview disclosure. Treat failures as release
      blockers; if Git is unavailable, record tracked-content detection as
      unavailable; verify rollback retains a newly created protective file; do
      not assume undocumented flags.
- [ ] Confirm the compatibility matrix still distinguishes Windows/Python
      3.11 CI coverage from unverified macOS/Linux runtime behavior.
- [ ] Sanitize every report: never upload configs, manifests, backups, logs,
      prompts, credentials, or personal paths.

## Tag gate

- [ ] Confirm `CHANGELOG.md` still says `v0.1.0` is planned and move only the
      validated entries into the release section.
- [ ] Create the annotated `v0.1.0` tag only after all required checks pass.
- [ ] Verify the tag resolves to the selected commit and repeat the archive
      file-list/checksum check from the tag before publishing any artifact.
