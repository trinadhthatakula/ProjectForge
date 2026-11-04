# Capability discovery and matching

## Sources and evidence

The discovery helper checks explicit directories, standard user skill locations, and the selected project. It records the file path and source for each skill or agent. For Codex it also records the CLI version, agent definitions, configured agent limit when readable, and MCP server names. Credentials, tokens, environment-variable values, and full tool configuration are never emitted.

The running model must add any tools it can see in the current session. Local discovery cannot prove the session has a tool, an account connection, network permission, or authorization to use it. Keep these as separate facts.

Use `--inventory-complete` only when the caller has supplied the complete active-session capability inventory. Without it, an unmatched capability remains `unverified` when session availability is unknown; with it, unmatched items can be reported as `missing`.

Each required capability has a status:

- `available`: current-session evidence shows the capability can be used, or the user confirms it.
- `partial`: a related capability exists but does not meet the whole requirement.
- `missing`: searched locations or active tool inventory show no matching capability.
- `unverified`: the source could not be inspected or session availability is unknown.

The report includes role requirements, discovered matches, source path or tool name, reason for the match, missing items, and recommendations. Skill names are clues, not proof. Read full instructions only for candidates relevant to selected roles and current work.

## Skill locations

Discovery can inspect `$CODEX_HOME/skills`, `~/.codex/skills`, `~/.agents/skills`, and project-local `.codex/skills` or `.agents/skills`, plus paths supplied with `--skills-dir`. It reads the `name` and `description` frontmatter fields. It does not execute helper scripts from these directories.

## Matching

Match role capability tags against skill name and description terms, then against the active tool inventory and known custom agent metadata. Report the signals that matched. Do not claim semantic equivalence from one overlapping word. A related skill can satisfy an optional capability, but a required capability remains partial or missing until its instructions or behavior are checked.

## Recommendations

Recommend additional skills only when the gap materially affects the project. Include the capability gap, suggested category, and rationale. Do not auto-install, download, or run them. Report “not available in this runtime” when no suitable option was found.
