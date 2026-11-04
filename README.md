# ProjectForge

ProjectForge turns an early software, automation, AI, or cross-platform idea into a researched kickoff specification. It guides adaptive discovery, recommends a right-sized specialist team, reports runtime capability gaps, validates a versioned manifest, and generates Markdown plus standalone offline HTML.

## Install with `npx`

Use the [Vercel Skills CLI](https://github.com/vercel-labs/skills/blob/main/docs/commands.md) from the project where you want to use ProjectForge. Its current release requires Node.js 22.20 or newer.

```sh
npx skills add trinadhthatakula/ProjectForge --skill projectforge --agent codex
```

This installs ProjectForge for Codex in the current project. Add `--global` (or `-g`) to install it for your user account instead:

```sh
npx skills add trinadhthatakula/ProjectForge --skill projectforge --agent codex --global
```

The CLI also supports other agents; replace `codex` with a supported agent name. See its [supported agents](https://github.com/vercel-labs/skills/blob/main/docs/agents.md).

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

Validate and render both deliverables. Existing output files are protected unless `--force` is supplied. Use `--dry-run` to preview writes.

```sh
python3 scripts/projectforge.py validate /path/to/projectforge.json
python3 scripts/projectforge.py render /path/to/projectforge.json \
  --output-dir /path/to/kickoff --format both --dry-run
```

See `examples/` for Android, web SaaS, Python automation, and cross-platform manifests. Run the automated suite with:

```sh
python3 -m unittest discover -s tests -v
```

Generate selected specialist agent files only when a target project explicitly wants Codex project-scoped agents:

```sh
python3 scripts/projectforge.py codex-agents /path/to/projectforge.json \
  --target-dir /path/to/target-project --dry-run
```

## Package layout

- `SKILL.md` contains the shared workflow and key constraints.
- `references/roles.json` contains the specialist catalogue; other references explain discovery, architecture, and runtime limits.
- `schemas/` defines the canonical project manifest, role profile, and assignment contract.
- `scripts/` implements deterministic operations. It reads skill metadata and agent configuration but never executes discovered scripts.
- `templates/` holds document framing; renderers fill both formats from the same manifest.
- `examples/` are complete manifests. `tests/` exercise CLI behavior and safety invariants.

## Safety and limitations

Capability discovery is local and best-effort. Installed CLI binaries or skill files do not prove that an agent session exposes those tools. The report preserves unknowns rather than claiming they are usable. Pricing, token counts, and team cost scores are planning estimates. Dependency compatibility must be researched and recorded with evidence. Codex custom-agent generation is optional and project scoped; generated definitions do not change global configuration or spawn agents.
