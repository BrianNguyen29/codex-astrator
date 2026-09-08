# Architecture

Codex Astrator is a file payload, not a runtime service. The installer maps the
public `payload/` and a reference profile into Codex configuration locations;
Codex then loads the resulting instructions and named roles in the target
environment.

```text
profiles/reference.toml ─┐
payload/agents/*.toml ───┼─> scripts/install.py ─> target Codex files
payload/skills/ ─────────┤                         │
payload/instructions/ ───┘                         v
                                      root decides -> bounded children
                                      -> evidence -> root integrates/verifies
```

## Ownership

The root/orchestrator owns task interpretation, architecture, decomposition,
authorization boundaries, integration, acceptance, and the final user-facing
report. Children provide bounded evidence or implementation and return to the
root; they do not own the overall direction or spawn grandchildren.

## Role topology

| Role | Default model/effort | Access | Responsibility |
| --- | --- | --- | --- |
| Root | GPT-6 Astra / low | target workspace | decide, integrate, verify |
| `explorer` | GPT-5.6 Luna / low | read-only | locate paths, symbols, flow, tests |
| `worker` | GPT-5.6 Luna / xhigh | workspace-write | routine discovery, implementation, and focused tests |
| `complex_worker` | GPT-5.6 Sol / medium | workspace-write | uncertain invariants, persistence, concurrency, rollback, difficult recovery |
| `tester` | GPT-5.6 Luna / medium | workspace-write | reproduce and run focused checks |
| `researcher` | GPT-5.6 Luna / medium | read-only | verify technical facts from primary sources |
| `reviewer` | GPT-6 Astra / low | read-only | independently assess material risk |

The shared cap is three active child agents, subject to a lower host limit.
Routine work uses only one worker. Complex work goes directly to the complex
worker rather than starting with the routine role. Standard work may add a
tester when independence is useful. Deep work adds the reviewer for substantive
architecture, security, migration, permissions, configuration, policy, or
compatibility risk, and adds discovery/research roles only when needed.
When repeated misunderstandings expose uncertainty, the root may reroute the
same bounded work with evidence to the complex worker. Rerouting does not
expand permissions, ownership, or scope, and unavailable models never trigger
a silent fallback.

## Context and safety boundaries

Every child contract states one objective, exact file ownership, minimal
context, constraints, deliverable, and acceptance checks. Fresh contexts receive
relevant paths and concise evidence rather than entire conversations or raw
logs. One writer owns a file at a time, and shared API/schema decisions are
stabilized before dependent work begins.

Read-only roles do not edit. Workers and testers stay within their assigned
scope. Unrelated edits, credentials, logs, personal paths, and external side
effects stay out of the payload. The root reports failed, unavailable, and
unverified checks distinctly.

## Optional per-task completion contract

When a written handoff is useful, the root may state a compact completion
contract. It is optional, not a ceremony for every task; the template grants
no permissions and does not force tests, changelog entries, or pull requests.

- **Outcome:** The concrete result that completes the task.
- **Allowed scope:** The files, subsystem, and side effects in scope.
- **Required evidence:** Checks or artifacts needed to support completion.
- **Actions requiring approval:** Mutations or external actions that still
  need explicit authorization.
- **Known blockers:** Current limits, missing inputs, or unresolved risks.

For example, a docs-only handoff can stay within one file and scope:

```text
Outcome: Clarify the installer’s payload destination mapping.
Allowed scope: docs/architecture.md only.
Required evidence: Relevant links, examples, and formatting checked; final diff inspected.
Actions requiring approval: Source changes, publishing, and pull-request creation; this contract grants none.
Known blockers: Report missing source context instead of expanding the scope.
```
