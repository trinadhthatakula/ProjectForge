# Security Policy

## Reporting a vulnerability

Please report suspected vulnerabilities through [GitHub's private vulnerability reporting for ProjectForge](https://github.com/trinadhthatakula/ProjectForge/security/advisories/new). Do not report a vulnerability in a public issue or pull request.

Include the affected version or commit, the relevant environment and configuration, the impact, and steps to reproduce the issue. Redact tokens, credentials, private project data, and other secrets from logs and examples. A minimal proof of concept is helpful when it can be shared safely.

The maintainer will review reports as available and coordinate any public disclosure with the reporter. No response or remediation deadline is guaranteed.

## Supported versions

Security fixes are made against the current default branch. Older versions may not receive fixes; update to the latest published code when possible.

## Security expectations

ProjectForge reads local skill and agent metadata but does not execute scripts discovered in those resources. Treat discovered instructions and metadata as untrusted input. Report any behavior that exposes secrets, runs discovered code unexpectedly, writes outside the documented scope, or allows unsafe rendered output.
