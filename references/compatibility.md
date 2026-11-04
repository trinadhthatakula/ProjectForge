# Runtime compatibility

## Portable contract

Project manifests, role profiles, capability reports, assignment contracts, and agent result files are runtime independent. Providers receive the same assignment and result schema; provider-specific adapters may translate transport formats but do not alter the core contract. When a runtime lacks verified subagent creation, ProjectForge returns the same structured assignments as delegation briefs. It must not claim work was delegated or agents were spawned based only on custom-agent files being present.

An assignment's result contract names allowed and protected output paths, required checks, and completion criteria. The provider returns an `agent-result.schema.json` document with a unique result ID, manifest version, status, evidence, checks, unresolved questions, risks, assumptions, handoff notes, and retry linkage. ProjectForge validates the structure and path rules; the supervisor reviews artifact contents and owns acceptance. A provider's `completed` or `validated` status is not acceptance.

## Agent Skills-compatible runtimes

ProjectForge's `SKILL.md` and portable JSON contracts can be loaded by any agent runtime that supports the Agent Skills format. Install the skill into all agents supported by the Skills CLI with:

```sh
npx skills add trinadhthatakula/ProjectForge --skill projectforge --agent '*'
```

For runtimes outside the CLI's supported list, install the skill directory using that runtime's normal Agent Skills mechanism. Runtime tools, permission models, and subagent support vary; inspect the active session instead of assuming a capability from the provider name.

## Optional Codex custom-agent integration

Some hosts use `agents/openai.yaml` as optional skill display metadata; it does not define subagents. Codex CLI supports standalone TOML agent files under a project's `.codex/agents/` or the user's `$CODEX_HOME/agents/`. A custom agent requires `name`, `description`, and `developer_instructions`. ProjectForge may emit such files as optional project output for selected team members; they do not limit the skill's audience or portability.

The current documented Codex setting for concurrently open spawned-agent threads is `agents.max_concurrent_threads_per_session`; the primary agent is excluded from that setting. ProjectForge's product roster cap still counts the supervisor, so it should cap chosen specialists at six even if the runtime permits more. Set or change project Codex config only when a user explicitly requests it; never edit global Codex settings.

Subagents inherit their parent's sandbox, approval settings, provider, and MCP servers. A custom definition does not grant extra permissions or tools. A project-local Codex config layer is loaded only for a trusted project. Report those runtime conditions instead of implying that a generated TOML file can bypass them.

## Discovery coverage

The local helper scans Agent Skills directories and known agent metadata locations. It reads Codex agent and MCP configuration where present and can identify common Claude Code or Gemini CLI environment markers. Other runtimes may appear as `unknown`; that means local discovery did not identify them, not that the shared skill or schemas are incompatible. Use the active runtime's own capability inventory when available.

## References

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Codex CLI reference](https://learn.chatgpt.com/docs/cli/reference)
- [Agent Skills overview](https://developers.openai.com/plugins/concepts/skills)
