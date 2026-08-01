# Security and workflow trust model

## Supported use

The public GitHub Actions workflow is an academic prototype for trusted,
same-repository collaborators. It is not designed to run commands from forked pull
requests or arbitrary outside contributors.

Before checkout or PR-code execution, the preflight job requires both:

- an `OWNER`, `MEMBER` or `COLLABORATOR` author association; and
- a PR head repository equal to the current repository.

Validation checks out the verified PR head SHA with read-only repository permissions
and without persisted checkout credentials. Local-model modes can reach a self-hosted
runner only after that preflight. Reporting and optional writeback run separately on
a GitHub-hosted runner; writeback is attempted only for the selected commit mode and
is refused if the remote PR head no longer equals the SHA that was validated.

These controls reduce credential exposure but do not form a complete sandbox. Target
project dependency installation, project imports, generated tests and test execution
can all run code. Keep self-hosted runners isolated, ephemeral where practical and
free of unrelated credentials or sensitive data.

## Secrets

Cloud API keys are passed only to the generation step for routes that require them.
Do not commit `.env` files, model responses, prompt logs, generated-test corpora or
detailed failure logs. Rotate a key immediately if it is exposed.

## Reporting a vulnerability

Do not include credentials, personal data or exploitable proof-of-concept payloads in
a public issue. Contact the repository owner privately through an appropriate GitHub
channel before public disclosure.
