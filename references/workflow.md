# Discovery, readiness, and change workflow

## Modes

- **Quick:** identify outcome, audience, platform, major constraints, and next decision; keep the team small.
- **Standard:** cover scope, architecture, technology, data/API, security, quality, deployment, and material risks.
- **Comprehensive:** explore all relevant product, technical, operational, cost, accessibility, localization, and release questions.
- **Custom:** let the user choose topics, depth, specialists, and output sections.
- **Agent-Decided:** choose the lightest mode that can establish a responsible plan, explain the choice, and let the user redirect.

Ask only questions that can change a decision, team assignment, risk, estimate, or acceptance criterion. Group a few related questions, accept partial answers, and continue with explicit assumptions. Tailor platform-specific details instead of presenting every question to every project.

## Discovery topics

Consider project identity, problem, audience, goals, platforms, identifiers/namespaces, technology preferences, features and exclusions, architecture, databases and APIs, authentication, storage, security/privacy, offline behavior, monetization, performance, accessibility, localization, deployment/hosting, budget, existing repository, and integration constraints. Record evidence from repository inspection separately from user statements.

Use the manifest's `evidence_status` values consistently:

| Status | Meaning |
| --- | --- |
| `confirmed` | Explicitly stated or approved by the user. |
| `verified` | Checked against a repository, reliable source, or runtime evidence. |
| `recommended` | Specialist recommendation awaiting a decision. |
| `assumption` | Working value used to make progress; state why it is plausible. |
| `pending` | Unanswered decision or required evidence. |

## Team selection and contracts

Support three selection modes: **dynamic** ranks relevant roles from project signals, **manual** keeps the user's selected roles, and **hybrid** keeps the user's selections then adds relevant roles within the mode limit. Treat catalogue trigger phrases as routing cues rather than a closed vocabulary; map equivalent terms and constraints to the role whose deliverables fit. Compare material project needs against shortlisted roles and surface important work without a clear owner for manual or hybrid review. Read only the linked guides for shortlisted roles to refine role-specific boundaries and assignment criteria. Manual selections are never silently trimmed. Select the mandatory supervisor and only specialists who materially improve an independent workstream. Consider relevance, overlap, independence, context needs, research and integration complexity, handoffs, token cost, and review effort. Combine compatible responsibilities when practical. Prefer a temporary consultation for a narrow question. Keep implementation ownership unambiguous.

Report the optimizer's role relevance, overlap, independence, coordination overhead, context needs, research complexity, integration complexity, handoffs, and review effort. Treat scores and token counts as transparent planning heuristics, and include their basis; do not imply empirical calibration.

Every assignment contract states mission, responsibilities, exclusions, inputs, outputs, dependencies, acceptance criteria, and handoff requirements. Preserve catalogue prerequisites as input notes. When a prerequisite is owned by another selected assignment, represent that relationship in the manifest dependency graph using stable assignment IDs and the appropriate `blocks`, `informs`, or `reviews` relationship. The supervisor maintains the canonical manifest, reviews specialist claims, resolves conflicts, and records accepted decisions. Specialists should identify evidence and uncertainty, not silently decide user-owned product questions.

## Dependency-aware work

Represent dependencies by stable assignment IDs. Validate that every referenced dependency exists and that the graph is acyclic. Run independent research concurrently only when supported by the active runtime and useful for the task. Start blocked work after its inputs are accepted. If no subagents are available, retain the same contracts as sequential delegation briefs.

## Readiness gates

Before marking a kickoff ready, check:

1. Goals, audience, and in/out scope are explicit enough to guide implementation.
2. Platform and core architecture choices are verified or visibly pending.
3. Data, API, authentication, and security/privacy decisions have owners and evidence status.
4. Must-have features have acceptance criteria and dependencies.
5. The team fits the hard limit, has minimal overlap, and has valid contracts and handoffs.
6. Required capabilities are available or have an owner and concrete next action in `readiness.capability_plans`; tool requirements have direct tool evidence, and skill metadata alone is not proof of a usable executable or integration.
7. Required decisions are confirmed or verified. Optional open decisions remain visible with an owner and are marked `required: false`.
8. Risks, assumptions, budget, monetization disposition, and milestones are visible; high-impact risks and open assumptions have owners and next actions. State explicitly when a budget limit or monetization plan does not apply.
9. Manifest validation passes and generated documents match the manifest.

The validator reports derived open gates in addition to recorded blockers and rejects `ready` whenever a required gate remains open. Keep `readiness.blockers` aligned with those findings. An open required gate means the readiness state is `needs_input` or `blocked`; do not call it implementation-ready. A missing specialist capability can be planned work rather than a blocker only when its role, capability, owner, and concrete next action are recorded in `readiness.capability_plans`. Unresolved optional decisions remain visible and owned without blocking readiness.

## Change management

Keep accepted changes in the next manifest version and retain a short change record with date, request, affected areas, and decision status. Use `projectforge diff OLD NEW` to surface changed project fields, roster, capability needs, dependencies, milestones, risks, and decisions. Before applying a consequential change, explain effects on scope, architecture, cost, staffing, schedule, and prior acceptance criteria. Regenerate both documents from the accepted manifest.
