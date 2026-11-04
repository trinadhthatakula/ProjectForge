# Contributing to ProjectForge

Contributions are welcome through focused pull requests. For security vulnerabilities, follow [SECURITY.md](SECURITY.md) and use private reporting instead of opening a public issue.

## Development setup

ProjectForge supports Python 3.11 and newer. Install its runtime dependency with:

```sh
python3 -m pip install -r requirements.txt
```

Run the unit suite before submitting a change:

```sh
python3 -m unittest discover -s tests -v
```

The GitHub Actions workflow also validates all JSON schemas and example manifests and runs a CLI initialization, validation, and rendering smoke workflow on Python 3.11, 3.12, and 3.13.

## Change guidelines

- Keep changes focused and explain the user-visible behavior or bug being addressed.
- Include or update regression coverage for behavior changes when practical, and update relevant examples and documentation.
- For a breaking manifest change, preserve the old versioned schema, add an explicit migration, and describe the compatibility change. Do not silently rewrite existing manifests.
- Keep provider-specific behavior in adapters; preserve the provider-neutral assignment and result contracts.
- Do not add secrets, credentials, private customer data, or generated local configuration to commits.
- Run the relevant checks locally and include the commands and outcomes in the pull request description. Be clear about checks that could not be run.

## Pull requests

Describe the problem, the change, and any compatibility or security impact. Link related issues when applicable. Keep each pull request reviewable and respond to requested changes in follow-up commits.

By submitting a contribution, you agree that it may be distributed under the project's [GNU GPL version 3 or any later version](LICENSE). You retain copyright in your contribution.

## Changelog and releases

Add user-visible changes to [CHANGELOG.md](CHANGELOG.md) under `Unreleased`. Before a release, move those entries under the release version and date, check that the supported Python versions and manifest migration notes are accurate, and run the CI workflow.

Before changing the current manifest schema, copy it to `schemas/project-manifest-VERSION.schema.json` and keep an explicit migration path from that version. For a release, create an annotated tag named `vMAJOR.MINOR.PATCH` on the reviewed commit, then publish GitHub release notes from the matching changelog section. Do not retarget or reuse a published version tag.
