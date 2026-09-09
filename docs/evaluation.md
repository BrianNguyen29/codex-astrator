# Bounded local evaluation

The implementation plan is: installed-state checks and cooperative locking;
seeded parser tests; three-OS CI configuration; a four-task harness and local
reports; then independent review and release evidence. The single preset,
experimental context-management setting, and delegation-first policy stay
unchanged. Model-routing experiments follow an observed bottleneck, not a new
public preset.

## Harness

Run from the repository root, replacing placeholders with explicit local paths.
Output parents must already exist. Outputs must be new; nothing is overwritten.

```text
python scripts/evaluate.py prepare --output NEW_DIRECTORY --repeats 2
python scripts/evaluate.py check --workspace TASK_DIRECTORY --output NEW_CHECK_JSON
python scripts/evaluate.py check --workspace TASK_DIRECTORY --execute --output NEW_BEHAVIOR_JSON
python scripts/evaluate.py report --input NEW_BEHAVIOR_JSON --output NEW_REPORT_JSON
```

`prepare` creates four synthetic tasks twice by default. `--task onefilebug`
selects a single task. `check` accepts either the prepared batch directory or
one task/repeat directory. Default checks only inspect text; they are not
functional evidence. With `--execute`, the three code tasks use fixed behavior
tests rather than implementation-specific text matches. The supplied-facts
review task remains structural-only and requires human judgment for accuracy.
These small examples are a pilot, not a representative performance benchmark.

**Execution safety:** `--execute` runs workspace Python code with current
process permissions in a child interpreter, with a five-second timeout per
task. It is NOT a security sandbox and cannot contain malicious code or its
descendants. Review the code first; use only disposable, trusted synthetic
workspaces. It does not launch a model, install dependencies, or offer an
arbitrary shell-command runner. Live model invocation is a separate opt-in
step using the [runtime protocol](compatibility.md#opt-in-manual-runtime-smoke).

Exit codes: `check` returns 0 when its selected checks pass, 1 for failed
checks, and 2 for invalid input or file-operation errors. A structural pass is
not a behavioral pass. `report` validates complete check sets and recomputes
outcomes; it does not authenticate manually supplied measurements.

Reports use controlled task/role/model/effort/access values and optional numeric
duration/token fields. Unknown execution fields remain `unavailable`, numeric
fields remain null. They contain no source paths, prompts, config, or raw logs.
Reasoning tokens are an annotation, not added to output tokens. Keep reports
local; inspect before sharing. Use `report --help` for optional measured fields.

## Pilot budget and current evidence

Local acceptance on Windows/Python 3.12.8: 54 unittest tests passed, static
doctor passed, and local Markdown file targets and `git diff --check` passed.
Independent review covered installer safety and the harness; its three
harness findings were fixed with regression tests. This describes the working
tree, not a clean release revision or hosted CI run.

Initial comparison plan: four tasks, two repeats per condition (preset and
root-only experimental baseline). Before model execution, set a total time
and token/quota budget using the [comparison protocol](token-usage.md).
Do not infer cost or savings from harness tests. Routing comparisons remain
deferred until this first comparison identifies a bottleneck.

On 2026-09-09, a bounded smoke attempt used Windows, Python 3.12.8, and Codex
CLI 0.153.4 with a two-minute wall-time budget. The disposable project install
verified healthy (9/9 managed files, 6/6 role profiles). The runtime invocation
requested workspace-write and disabled hooks/apps/plugins/memories for this
attempt without editing global configuration. Host execution policy rejected
even scoped file reads. No synthetic source file changed; functional runtime
verification was blocked. CLI exit 0 did not mean task success. Actual role,
model, effort, and effective access remain unavailable. Do not treat this as
validation of the unmodified end-user runtime environment.

The CLI exposed aggregate usage: input 86,596, cached input 68,096, cache-write
input 0, output 525, reasoning-output annotation 21. Aggregation across children
was not independently verified. No quota-to-dollar conversion is claimed.
The full workflow benchmark was not run after the policy blocker. Hosted
Windows/Linux/macOS CI, exact release-revision archive checks, and release
publication remain pending; no global install, commit, push, or tag was made.
