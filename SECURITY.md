# Security

Codex Astrator is a local source distribution and installer. It does not
install packages, read authentication stores, use credentials, contact model
APIs, or publish changes. It may read explicit target configuration and
instruction files to merge them and copy their prior bytes into local recovery
backups; those files and backups can contain sensitive values. The target
project and host still control trust, permissions, authentication, and model
execution.

## Private vulnerability reporting

Do not disclose suspected vulnerabilities in a public issue. Use the
repository's private vulnerability-reporting channel if one is enabled and
visible to you. This document does not assume that such a hosting feature is
enabled and does not publish an email address. If no private channel is
available, contact a maintainer through an existing trusted private channel and
request one before sharing sensitive details.

Include a concise description, affected revision, impact, and a reproduction
using a disposable target when possible. Remove credentials, tokens, private
configuration, session data, personal paths, and raw logs. Do not upload
`config.toml`, installer manifests, backup contents, or execution transcripts
unless a maintainer asks for a sanitized excerpt through a private channel.

## Safe reports

The default installer mode is a read-only preview. Report the exact command
shape, scope, and sanitized output needed to reproduce a problem, and never
include secrets or unredacted project data. For ordinary non-sensitive bugs,
use the repository's bug-report form after removing secrets and personal paths.
