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

Do not target a full context window or encode a hard 260K-token stop; effective
limits and behavior depend on the model, endpoint, and release. A preset does
not configure internal Codex API caching, Batch, or Flex controls. Those are
API/request-environment concerns when supported.

API cost calculators must include cache writes when they are billable. For any
long-context surcharge, calculate the difference using the same usage in both
cases: `long-context total - baseline total`. Do not apply a surcharge to a
partial token category or compare unrelated runs.
