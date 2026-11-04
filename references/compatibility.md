# Runtime compatibility and Codex agent format

## Portable contract

Project manifests, role profiles, capability reports, and assignment contracts are runtime independent. When a runtime lacks verified subagent creation, ProjectForge returns the same structured assignments as delegation briefs. It must not claim work was delegated or agents were spawned based only on custom-agent files being present.

## Codex

Codex skill UI metadata lives in `agents/openai.yaml`. That file does not define subagents. Current Codex CLI documentation uses standalone TOML files under a project's `.codex/agents/` or the user's `$CODEX_HOME/agents/`. A custom agent requires `name`, `description`, and `developer_instructions`. ProjectForge should emit such files only as optional project output for selected team members.

The current documented Codex setting for concurrently open spawned-agent threads is `agents.max_concurrent_threads_per_session`; the primary agent is excluded from that setting. ProjectForge's product roster cap still counts the supervisor, so it should cap chosen specialists at six even if the runtime permits more. Set or change project Codex config only when a user explicitly requests it; never edit global Codex settings.

Subagents inherit their parent's sandbox, approval settings, provider, and MCP servers. A custom definition does not grant extra permissions or tools. A project-local Codex config layer is loaded only for a trusted project. Report those runtime conditions instead of implying that a generated TOML file can bypass them.

## Observed during ProjectForge setup

The implementation environment reported Codex CLI `0.166.0`, listed the `multi_agent` feature as stable/enabled, and had no custom agent TOML files in the inspected user/project agent locations. Installed skill files existed in both `~/.codex/skills` and `~/.agents/skills`. These are setup observations, not permanent assumptions; run discovery again for each target project.

## References

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference)
- [Agent Skills overview](https://developers.openai.com/plugins/concepts/skills)
