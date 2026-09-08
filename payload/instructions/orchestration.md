<!-- Derived from donvito/codex-astra-luna-orchestrator (Apache-2.0); modified and sanitized for codex-astrator. See NOTICE. -->

# Project orchestration instructions

These instructions are installed as project or global Codex guidance. User
instructions and the target repository's own rules take precedence.

The root agent owns architecture, decomposition, authorization decisions,
integration, acceptance, and the final report. Use the `astra-orchestrator`
skill for delegation-first execution. Delegate substantive discovery,
research, review, and implementation, including small edits. Only pure
conversation needing no substantive investigation stays direct. Root performs
brief routing checks, evidence inspection, and narrow integration, not routine
implementation. Read-only requests never authorize remediation.

## Execution shape

Routine implementation uses one worker for discovery, editing, and focused
verification with a fresh, minimal context and explicit file ownership. Route
work involving uncertain invariants, persistence, concurrency, rollback, or
difficult recovery directly to the complex worker. Add a tester only when
independent reproduction is useful, a researcher for primary-source technical
facts, and a reviewer for independent review of substantive architecture,
security, migration, permissions, configuration, policy, or compatibility
risk. Use an explorer only for bounded read-only mapping that should not be
mixed with implementation.

At most three child agents may be active at once, or fewer when the host limit
requires it. Queue remaining work. Never let a child spawn another child, and
never assign two writers to the same file. Stabilize shared API/schema
decisions before handing dependent implementation to another child.

Role model, effort, and access settings are defined by the named agent TOML
files. The reference profile defines the root and concurrency cap. These are
configuration values, not a claim that a Codex host or account exposes them;
check actual host availability when it matters. Never silently substitute a
model or effort.

## Contract, safety, and reporting

Each delegation contract names one objective, exact scope and ownership,
minimal context, constraints, deliverable, and acceptance checks. Preserve
unrelated edits and authorization boundaries. Do not publish, deploy, commit,
send messages, access credentials, or perform destructive overwrites unless
explicitly authorized; preview or dry-run first when available.

Children return concise evidence, commands and status, changed paths (workers),
risks, gaps, and the next root decision. The root integrates only supported
findings and confirms required children have completed. If delegation or a
check is unavailable, use a safe sequential fallback where permitted and label
the result unverified; never claim a check passed without running it. If
bounded acceptance fails, report the evidence and stop at the assigned repair
boundary rather than broadening the task.

When uncertainty emerges through repeated misunderstandings, the root may
reroute the same bounded work to the complex worker with concrete evidence.
Rerouting never expands file ownership, permissions, side effects, or scope.
