# Changelog

All notable changes are recorded here. The project is preparing a planned
`v0.1.0` pre-release; that version has not been released.

## [Unreleased]

### Fixed

- Profile merging now handles quoted and dotted TOML table headers without
  duplicating or misplacing managed keys, while preserving unrelated comments
  and values.

### Added

- The validation workflow now defines independent Windows, Ubuntu, and macOS
  jobs with Python 3.11 only and `fail-fast: false`; hosted matrix results
  remain pending until that workflow runs after a push.
- Read-only installer `status` and `verify` checks document installation state
  without exposing file contents, hashes, or backup names. Mutating applies use
  a per-target cooperative lock while preserving snapshot checks for external
  processes.
- Added a bounded, local evaluation plan and offline harness notes covering a
  fixed four-task set, initial two-to-three repeats, declared budgets, and
  sanitized optional reports. Routing experiments do not create new presets.

- The reference preset now requests a 400,000-token context window and total-
  usage automatic compaction at 250,000 tokens. These remain client-side
  settings and do not guarantee a server-side input cap or token savings.
- The reference preset now opts into experimental context management with
  `[features.context_management].experimental_mode = true`. OpenAI clients
  keep this opt-in off by default; client/account eligibility must be verified,
  and no performance guarantee is implied.
- Install previews warn when existing orchestration-like `AGENTS.md` content is
  unmanaged and preserve that content; the preview makes clear that the
  combined policy is not claimed to be coherent.
- Before writing recovery bytes, install previews disclose the target-local
  `.codex/.astrator-backups/.gitignore` protection. The installer creates the
  required `*` rule before backup bytes, and fails closed for unsafe rules,
  symlinked backup paths, and backup content tracked by Git when Git can verify
  that state. If Git is unavailable, tracked-content detection is unavailable.
  A newly created protective file is retained after rollback so the backup
  privacy rule is not removed during failure recovery.

These hardening changes are implemented and covered by focused disposable
target tests. Live runtime and release-gate validation are still outstanding;
`v0.1.0` remains unreleased.
