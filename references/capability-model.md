# Capability discovery and verification

ProjectForge evaluates capability in two separate stages. Discovery finds candidates from metadata and the active runtime inventory. Verification records evidence that a candidate is accessible and fits a specific project requirement.

## Stage 1: Discovery

The discovery helper checks explicit directories, standard user skill locations, the selected project, and caller-supplied active-session inventory. It records each skill, agent, and tool's source. It never runs discovered scripts. For Codex it also reads agent and MCP metadata where present. Credentials, tokens, environment-variable values, and full tool configuration are never emitted.

Use `--inventory-complete` only when the caller supplied the complete active-session capability inventory. Without it, unmatched requirements remain `unverified` when session availability is unknown; with it, an unmatched requirement can be reported as `missing`.

Discovery status describes inventory and matching evidence only:

- `available`: the active-session inventory lists a matching skill or tool. This does not prove it supports the requested work; local agent definition files remain metadata until checked in the active runtime.
- `partial`: discovered metadata is related but does not fully match the requirement.
- `missing`: a complete searched inventory has no matching candidate.
- `unverified`: the session or inventory could not be confirmed.

Names and descriptions are search hints, not proof of relevant functionality. Local skill or agent files do not prove current-session access, permissions, accounts, or runtime behavior. Match tool requirements only against the active tool inventory.

## Stage 2: Verification

For each selected role requirement, verify these checks against current-session evidence:

1. **Accessibility:** the candidate can be reached from this runtime.
2. **Instructions:** relevant instructions are available and understood, or genuinely not applicable.
3. **Requested operation:** the candidate supports the operation this assignment needs.
4. **Permissions:** required permissions are present, or no additional permission is needed.
5. **Expected output:** it can produce the output the assignment expects.

Do not claim that a tool performed a task unless it was actually used. A trial operation must be within the user's request and permissions. Evidence may come from the active tool inventory, inspected instructions, permission state exposed by the runtime, direct task execution, or explicit user confirmation. Record what was checked and what remains uncertain.

First persist the selected team, then persist the current discovery report so requirement identifiers exist in the manifest. Verification entries are accepted only for roles assigned in the manifest:

```sh
python3 scripts/projectforge.py optimize /path/to/projectforge.json --apply
python3 scripts/projectforge.py match /path/to/projectforge.json --apply
```

Prepare a JSON file following `schemas/capability-verification.schema.json`. Each entry identifies the exact role requirement using `role_id`, `capability`, `kind`, `requirement_type`, and `source`. Every check has a status and evidence. For example:

```json
{
  "verification_version": "1.0.0",
  "verifications": [
    {
      "role_id": "backend-engineer",
      "capability": "API design",
      "kind": "required",
      "requirement_type": "capability",
      "source": "role_profile",
      "recorded_by": "supervisor",
      "checks": {
        "accessibility": {"status": "confirmed", "evidence": ["Relevant tool is exposed in the active session"]},
        "instructions": {"status": "confirmed", "evidence": ["Inspected the relevant skill instructions"]},
        "operation": {"status": "confirmed", "evidence": ["The capability supports the required API design work"]},
        "permissions": {"status": "not_applicable", "evidence": ["No additional permission is required for this planning task"]},
        "expected_output": {"status": "confirmed", "evidence": ["Can produce the API contract and endpoint notes required by the assignment"]}
      }
    }
  ]
}
```

Then record it:

```sh
python3 scripts/projectforge.py record-verification \
  /path/to/projectforge.json /path/to/verifications.json --apply
```

Without `--apply`, the command validates and previews the derived statuses. Evidence is redacted before it is saved.

ProjectForge derives the overall verification status from the checks:

- `verified`: accessibility is confirmed, and every other check is confirmed or justified as not applicable.
- `partially_verified`: some evidence confirms access or fit, but at least one applicable check is partial, unsupported, or unknown.
- `unverified`: there is not enough evidence to assess access and task fit.
- `unavailable`: the candidate cannot be accessed or required permissions are unavailable.

The result is tied to one manifest role requirement. Running `match` again replaces its capability report and clears prior verification; record verification again against the refreshed inventory. Repeated, task-specific permissions or output assumptions should be checked for each project.

In manifest versions `1.2.0` and later, a required capability must be `verified` before readiness can be `ready`. Remediation plans can record an owner and next action, but they do not convert an unverified capability into a verified one. Optional capability gaps remain visible without blocking readiness.

## Reporting and recommendations

The report shows discovery status and verification status separately, with evidence for each. Include role requirements, discovered candidates, source, match reason, gaps, and remediation recommendations. Recommend additional skills only when the gap materially affects the project. Do not auto-install, download, or run third-party capabilities.

## Skill locations

Discovery can inspect `$CODEX_HOME/skills`, `~/.codex/skills`, `~/.agents/skills`, and project-local `.codex/skills` or `.agents/skills`, plus paths supplied with `--skills-dir`. It reads only the `name` and `description` frontmatter fields and does not execute helper scripts.
