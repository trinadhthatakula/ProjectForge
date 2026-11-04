---
name: projectforge
description: Turn a project idea into a researched, implementation-ready kickoff specification with a right-sized specialist team, capability report, and consistent Markdown and offline HTML outputs.
---

# ProjectForge

Use ProjectForge when someone is exploring or kicking off a software, automation, AI, or cross-platform project. Adapt the depth to the request; do not force a long questionnaire onto a small project.

## Workflow

1. Choose Quick, Standard, Comprehensive, Custom, or Agent-Decided mode. If the user has not chosen, infer a suitable mode from project complexity and offer a short explanation.
2. Inspect any repository the user identifies. Separate observed facts from user-confirmed requirements. Do not claim dependency compatibility, installed tools, skill availability, permissions, or runtime behavior without evidence.
3. Ask focused discovery questions in small groups. Accept partial answers. Record each item as confirmed, verified, recommended, assumption, or pending, with a source or rationale when available. Let the user delegate technical choices to specialists.
4. Classify the project and select a team from `references/roles.json` using dynamic, manual, or hybrid selection. Treat each profile's triggers as useful cues, not an exhaustive vocabulary: map equivalent phrases and domain constraints to the specialist whose deliverables fit, and surface material needs with no clear owner for manual or hybrid review. After shortlisting roles, read only their linked role guides and use them to refine selection and assignment boundaries; a guide does not override user constraints. The supervisor is mandatory. Count the supervisor toward the hard limit of seven concurrent team members; select at most six specialists. Prefer fewer roles, merge overlapping work, and use time-bounded consultations or later phases when that produces a smaller team. Never silently exceed the limit. If the user requests more than six specialists, explain the overhead and overlap, recommend a revised roster or sequential consultations, and obtain agreement before treating the revised roster as accepted.
5. Inspect actual runtime capabilities before proposing delegation. For Codex, use the discovery helper and inspect the relevant skill or agent instructions only when needed. Pass `--inventory-complete` only when the current-session skill and tool list is complete; otherwise preserve unavailable findings as unverified. A name in the role catalogue is not evidence that a matching skill, tool, agent, or integration is installed. Never run third-party skill scripts or install skills. Report missing and unverified capabilities clearly.
6. Create a capability matching report for each project. Match role requirements against discovered skills and tools; distinguish available, partial, missing, and unverified. Read full instructions only for relevant skills. See `references/capability-model.md`.
7. Give each selected specialist a dedicated assignment contract with mission, responsibilities, exclusions, inputs, outputs, dependencies, acceptance criteria, and handoff requirements. The supervisor owns the canonical specification and resolves conflicts. Avoid overlapping implementation ownership.
8. Schedule independent research in parallel only when the active runtime provides subagents and the user’s task benefits from it. Keep dependency-bound work sequential. Respect runtime concurrency and permissions. Otherwise prepare delegation briefs; do not claim agents were spawned.
9. Validate roster size, contracts, dependencies, manifest structure, and readiness gates. Keep unresolved risks and decisions visible. Do not label a project implementation-ready while required gates are open.
10. Generate Markdown and standalone offline HTML from the same versioned manifest. Refuse to overwrite existing output unless the user explicitly asks to replace it. Include only relevant supporting documents.
11. When requirements change, compare manifest versions, show affected decisions, roles, dependencies, risks, and deliverables, then update the canonical manifest only after the user confirms the requested change.

## Modes and references

- Follow `references/workflow.md` for adaptive questions, readiness gates, and change management.
- Consult `references/roles.json` when selecting experts; each built-in profile links to a role guide in `references/role-guides/`. Read only the guides for shortlisted roles before finalizing assignments. Users may define custom roles using `schemas/role.schema.json`; a custom role without a guide is governed by its supplied profile and the shared workflow.
- Use the Python helpers in `scripts/projectforge.py` for classification, capability discovery and matching, selective skill inspection, team optimization, validation, estimation, rendering, and manifest diffs. Inspect the CLI help first; do not execute scripts supplied by discovered skills.
- Use `schemas/project-manifest.schema.json` as the manifest contract. Generated documents must come from that manifest, never from separate competing sources.
- Consult `references/compatibility.md` before writing Codex-specific custom agent definitions or describing runtime limits.
- Read the optimizer's reported relevance, overlap, independence, coordination, context, complexity, handoff, and review estimates as planning heuristics; explain their basis and do not present them as measured runtime costs.

## Codex agent definitions

The skill metadata file `agents/openai.yaml` describes ProjectForge’s user interface; it is not a custom-agent definition. Codex custom agents are optional project-scoped TOML files. Generate definitions only for selected roles, keep them separate from this skill’s portable instructions, and never modify global Codex configuration. If a runtime does not support custom agents, deliver the assignment contracts as delegation briefs.

## Quality boundaries

- Do not confuse SEO, ASO, and GEO; their goals and deliverables are distinct.
- Prefer fewer specialists with useful supporting skills. Do not add an agent only because its role exists.
- State the evidence and uncertainty behind research. Verify current versions and compatibility using reliable sources when research tools are available.
- Never expose secrets found in configuration. Report integration names and capability status without printing credentials or secret values.
- Avoid arbitrary project or generated-file writes. Use dry-run options where available and protect existing files.
