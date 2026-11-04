# ProjectForge

ProjectForge is a provider-neutral Agent Skill for turning an early software, automation, AI, or cross-platform idea into a researched kickoff specification. It works in any agent runtime that can load Agent Skills instructions; its shared workflow and assignment/result schemas do not depend on a model provider. It guides adaptive discovery, recommends a right-sized specialist team, verifies capability fit with evidence, reports gaps, validates a versioned manifest, and generates Markdown plus standalone offline HTML.

## Install with `npx`

Use the [Vercel Skills CLI](https://github.com/vercel-labs/skills/blob/main/docs/commands.md) from the project where you want to use ProjectForge. Its current release requires [Node.js 22.20 or newer](https://github.com/vercel-labs/skills/blob/main/package.json). Select every compatible target agent with `--agent '*'`:

```sh
npx skills add trinadhthatakula/ProjectForge --skill projectforge --agent '*'
```

This installs the same ProjectForge skill for all agents supported by the CLI in the current project. Add `--global` (or `-g`) to install it for your user account instead:

```sh
npx skills add trinadhthatakula/ProjectForge --skill projectforge --agent '*' --global
```

To target a subset, replace `'*'` with the supported agent name or names. See the CLI's [supported agents](https://github.com/vercel-labs/skills/blob/main/docs/agents.md). Other Agent Skills-compatible runtimes can load `SKILL.md` through their own skill installer.

## Run the helper CLI

Python 3.11 or newer is required. `jsonschema` is the only runtime dependency; it validates the shipped Draft 2020-12 schemas.

```sh
python3 -m pip install -r requirements.txt
python3 scripts/projectforge.py --help
```

Create a starter manifest without replacing an existing file:

```sh
python3 scripts/projectforge.py init \
  --name "Sample project" \
  --output /path/to/projectforge.json
```

Inspect runtime skills and agents, then match them to a project:

```sh
python3 scripts/projectforge.py discover --cwd /path/to/repo
python3 scripts/projectforge.py inspect-skill android-cli
python3 scripts/projectforge.py classify /path/to/projectforge.json
python3 scripts/projectforge.py match /path/to/projectforge.json
python3 scripts/projectforge.py optimize /path/to/projectforge.json
```

Team selection defaults to dynamic. Use `optimize --selection-mode manual --role ROLE_ID` to select roles directly, or `--selection-mode hybrid --role ROLE_ID` to seed a team that ProjectForge can extend with relevant roles. Pass `--inventory-complete` to `discover` or `match` only when the active-session capability inventory is complete. Otherwise, unknown capabilities remain unverified where appropriate. Optimization scores and token counts are planning heuristics, not measured usage.

Capability matching is discovery only. Verify each selected requirement's runtime access, instructions, operation fit, permissions, and expected output using evidence. Create a verification file that follows [`schemas/capability-verification.schema.json`](schemas/capability-verification.schema.json), then record it in the manifest:

```sh
python3 scripts/projectforge.py optimize /path/to/projectforge.json --apply
python3 scripts/projectforge.py match /path/to/projectforge.json --apply
python3 scripts/projectforge.py record-verification \
  /path/to/projectforge.json /path/to/capability-verifications.json --apply
```

Without `--apply`, the command previews the derived status. Verification outcomes are `verified`, `partially_verified`, `unverified`, or `unavailable`; ProjectForge derives them from the recorded checks. Required capabilities must be verified for a manifest to pass the `ready` gate. Running `match` again refreshes discovery and clears old verification, so verify against the refreshed inventory.

Validate and render both deliverables. Existing output files are protected unless `--force` is supplied. Use `--dry-run` to preview writes.

```sh
python3 scripts/projectforge.py validate /path/to/projectforge.json
python3 scripts/projectforge.py render /path/to/projectforge.json \
  --output-dir /path/to/kickoff --format both --dry-run
```

New manifests use schema version `1.2.0`. Versions `1.0.0` and `1.1.0` remain supported. Migrate an older manifest to a new file; ProjectForge validates both the source and migrated result and does not rewrite the source. Migration marks earlier capability matches unverified and downgrades a previously ready manifest until required capabilities are checked:

```sh
python3 scripts/projectforge.py migrate /path/to/projectforge.json \
  --output /path/to/projectforge-1.2.json
```

Resolve selected-role prerequisites only after the supervisor confirms the provider assignment and relationship. The JSON input is an array following `schemas/dependency-resolution.schema.json`; `blocks` and `reviews` edges sequence work, while `informs` edges preserve parallel scheduling.

```sh
python3 scripts/projectforge.py resolve-dependencies \
  /path/to/projectforge-1.2.json /path/to/resolutions.json --apply
```

Provider results use `schemas/agent-result.schema.json`, independent of model provider. Before dispatch, set each assignment's allowed paths, protected paths, and required checks. A path ending in `/` covers that directory and its descendants; other paths match exactly. Validate results before review; accepted results must pass the required checks and point to existing project-local outputs. Keep every retry in a separate result file and link it to the previous rejected or rework-required attempt.

```sh
python3 scripts/projectforge.py validate-result \
  /path/to/projectforge-1.2.json /path/to/.projectforge/results/result-001.json
python3 scripts/projectforge.py record-result \
  /path/to/projectforge-1.2.json /path/to/.projectforge/results/result-001.json \
  --review accepted --reviewer supervisor --apply
```

See `examples/` for Android, web SaaS, Python automation, and cross-platform manifests. GitHub Actions validates schemas and examples, runs the CLI smoke workflow, and runs the automated suite on Python 3.11–3.13. To run the suite locally:

```sh
python3 -m unittest discover -s tests -v
```

ProjectForge's shared instructions and contracts are provider-neutral. As an optional runtime-specific output, generate selected Codex project-scoped agent files only when the target project wants them:

```sh
python3 scripts/projectforge.py codex-agents /path/to/projectforge.json \
  --target-dir /path/to/target-project --dry-run
```

## Package layout

- `SKILL.md` contains the provider-neutral shared workflow and key constraints. `agents/openai.yaml` is optional display metadata for hosts that use it; it does not change the skill's supported runtimes.
- `references/roles.json` contains the specialist catalogue and links each built-in role to its focused guide under `references/role-guides/`; other references explain discovery, architecture, and runtime limits.
- `schemas/` defines versioned project manifests, capability verification, role profiles, assignment contracts, dependency resolutions, and provider-neutral agent results.
- `scripts/` implements deterministic operations. It reads skill metadata and agent configuration but never executes discovered scripts.
- `templates/` holds document framing; renderers fill both formats from the same manifest.
- `examples/` are complete manifests. `tests/` exercise CLI behavior and safety invariants.

## Safety and limitations

Capability discovery is local and best-effort. Installed CLI binaries or skill files do not prove that an agent session exposes those tools. The report preserves unknowns rather than claiming they are usable. Pricing, token counts, and team cost scores are planning estimates. Dependency compatibility must be researched and recorded with evidence. Runtime-specific custom-agent generation is optional; generated definitions do not change global configuration or spawn agents.

## License, security, and contributions

ProjectForge is licensed under [GPL-3.0-or-later](LICENSE). See [CONTRIBUTING.md](CONTRIBUTING.md) for development and pull request guidance. Report vulnerabilities privately using the process in [SECURITY.md](SECURITY.md); do not post them in public issues.
