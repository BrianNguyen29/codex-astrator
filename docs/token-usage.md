# Token usage

Orchestration consumes model context and account rate-limit budget. There is no
fixed token number, and this project makes no savings or cost-reduction promise.
Measure representative runs in the target environment instead of inferring
cost from the number of configured roles.

## What to record

For each comparable run, record the Codex version, model and effort for the
root and each child, number of child agents, uncached input, cache-read input,
cache-write input (when exposed), output, reasoning breakdown (when exposed),
wall time, and before/after rate-limit window values if the host exposes them.
Treat the reasoning breakdown as a breakdown or annotation when the host's
output total already includes it; do not add it to output a second time. Keep
records free of source paths, secrets, credentials, and raw private prompts
before sharing them.

The repository ships no bundled token-usage collector and the installer does
not measure or transmit token usage. Use the host's own usage view or an
explicitly selected, sanitized export/rollout record. Inspect exports before
sharing because they may contain prompts, paths, or account data; keep them
outside version control. If a field is not exposed, record it as unavailable,
not zero.

ChatGPT-plan quota and API billing are separate accounting systems. A
ChatGPT/Codex quota or rate-limit percentage is not an API token price and must
never be converted into dollars. For plan details, consult the dated
[ChatGPT pricing documentation](https://learn.chatgpt.com/docs/pricing); for
API runs, use the applicable dated API pricing and model documentation.

## Comparison protocol

Use the same repository, Codex version, task prompts, and account conditions.
Compare this setup with at least one experimental root-only baseline, and
repeat each case because run-to-run variance can be material. The root-only
run is a comparison baseline, not a second preset or default policy. Include a
one-file task, a multi-file feature, a cross-component bug, and a
research-heavy task when the comparison is meant to guide policy. Alongside
token and time measurements, record total root-plus-children outcomes such as
success, rework, and escalations; a faster run with more rework is not an
equivalent result.

## Bounded evaluation plan

See the [local harness and recorded pilot evidence](evaluation.md) for exact
commands, execution safety, and the distinction between structural and
behavioral checks.

Use the original fixed four-task set for the initial comparison, selected
explicitly from the catalog so later extensions do not change the baseline:

1. a one-file task;
2. a multi-file feature;
3. a cross-component bug; and
4. a research-heavy task.

The catalog also includes bounded second-stage cases for failure recovery,
concurrency safety, security boundaries, and reviewer risk assessment. These
cases are useful for targeted follow-up comparisons, not for silently changing
the initial baseline. The concurrency check is a fixed stress schedule whose
thread interleaving can vary; repeat it and report instability rather than
calling one run deterministic. Reviewer and security conclusions still need
the listed human review; structural or behavioral checks do not establish a
complete threat-model or runtime assessment.

Run each condition two or three times initially, with the repetition count and
per-run/total token, time, and quota budget declared before execution. Stop at
the budget and record an incomplete or unavailable measurement; never infer a
successful outcome from a budget stop. Keep prompts, repository revisions,
account conditions, and acceptance checks fixed across the orchestration and
root-only baseline conditions.

After the initial results, use the task bottleneck to guide a second-stage
model-routing experiment (for example, a role or effort that addresses the
observed bottleneck). Keep the existing preset and child cap unchanged; this
is an evaluation of routing, not a reason to add another public preset. Record
the reason for each routing change and compare rework and acceptance outcomes
as well as token usage.

Keep harness output and raw reports local by default. A sanitized report may be
shared optionally after removing source paths, credentials, configuration,
manifests, backups, prompts, and private logs. If the host does not expose a
field, record `unavailable` rather than `0`; do not treat a locally generated
report as evidence of hosted CI or live runtime compatibility.

The repository's offline harness uses a fixed task catalog in
`evals/tasks.json`; it does not provide an arbitrary command runner. Its stable
workflow is:

```text
python scripts/evaluate.py prepare --output BASELINE_DIR --repeats 2 --task onefilebug --task multifilefeature --task statebug --task offline-research-review
python scripts/evaluate.py check --workspace BASELINE_DIR --output CHECK.json
python scripts/evaluate.py report --input CHECK.json --output REPORT.json
```

The default `check` path is structural-only. An optional execution flag, when
exposed by the installed harness, is documented by `python scripts/evaluate.py
check --help`; it is reserved for fixed behavioral checks on the code tasks,
including the failure, concurrency, and security cases. The offline research
review and reviewer-risk tasks remain structural-only and require the explicit
human checks in their task contracts. The harness does not make network calls
or run arbitrary shell commands. A local report is an optional sanitized
artifact, not hosted-CI or live-runtime proof.

Interpret cached and uncached input separately. More parallel children may
reduce elapsed time while increasing context work; the root also remains in the
loop for integration. Lowering the child cap or skipping delegation for a
trivial edit may reduce work, but the effect depends on the task and host.

## Privacy and limits

Usage views and rollout metadata may contain prompts, repository paths, or
account data. Inspect before exporting and keep them outside version control.
Rate-limit percentages are account-wide and can include concurrent sessions;
they are not a universal conversion from tokens to money. Availability of
usage fields varies by host and Codex release, so label missing measurements as
unavailable rather than zero.

## API-only considerations

These notes apply only to direct API usage, not to ChatGPT-plan quota. Consult
dated official pricing, long-context, and service-tier documentation for the
model and endpoint under test. The [prompt caching guide](https://developers.openai.com/api/docs/guides/prompt-caching)
and [GPT-6 Astra model documentation](https://developers.openai.com/api/docs/models/gpt-6-astra)
describe API behavior that may change by model or release.

Do not treat a configured context window or a 250K auto-compaction threshold as
a guaranteed server-side input cap or a universal hard stop; effective limits
and behavior depend on the model, endpoint, and release. Preset token settings
are client configuration requests and do not guarantee token savings. The
preset's experimental context-management opt-in is separate from internal
Codex/API prompt caching: it does not configure prompt-caching, Batch, or Flex
controls. Those remain API/request-environment concerns when supported, and
context-management behavior depends on client and account eligibility.

API cost calculators must include cache writes when they are billable. For any
long-context surcharge, calculate the difference using the same usage in both
cases: `long-context total - baseline total`. Do not apply a surcharge to a
partial token category or compare unrelated runs.
