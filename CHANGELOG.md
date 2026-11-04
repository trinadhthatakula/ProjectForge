# Changelog

User-visible changes are recorded here. Dates use ISO 8601.

## Unreleased

- Add manifest schema 1.3.0 with metadata-only execution event history and a migration from 1.2.0.
- Record applied CLI mutations and agent result review transitions, and display the event history in generated Markdown and HTML.
- Persist refreshed capability reports when applying `match` and record that update in the event history.
- Reject secret-like values in event metadata.
- Add offline conformance fixtures that exercise the shared provider-neutral result validation and review path. These do not invoke live model providers or provider adapters.
- Preserve the 1.2.0 manifest schema for validation and migration of existing projects.
