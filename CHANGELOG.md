# Changelog

User-visible changes are recorded here. Dates use ISO 8601.

## Unreleased

- Add a repeatable offline benchmark harness and a measured ProjectForge 1.0.0 baseline for validation, rendering, team optimization, and capability matching.

## 1.0.0 — 2026-11-05

- Publish the provider-neutral ProjectForge Agent Skill, specialist role guides, installation instructions, schemas, CLI, examples, and GPL-3.0-or-later license.
- Add manifest schema 1.3.0 with metadata-only execution event history and a migration from 1.2.0; preserve manifest validation and migration support for versions 1.0.0 through 1.2.0.
- Record applied CLI mutations and agent result review transitions, and display the event history in generated Markdown and HTML.
- Persist refreshed capability reports when applying `match` and record that update in the event history.
- Reject secret-like values in event metadata and add offline conformance fixtures for the provider-neutral result validation and review path.
- Add direct assignment adapters for OpenAI, Anthropic, Gemini, OpenAI-compatible endpoints, and the Claude Code CLI. Validate provider results and declared artifact paths before writing; preserve supervisor review as a separate step.
- Bound provider prompts, context, responses, and artifacts; reject redirect forwarding; block symlink context and output paths; keep provider credentials out of command arguments and logs.
