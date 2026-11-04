from __future__ import annotations

import re
from typing import Any

from .common import new_assignment


MODE_LIMITS = {"quick": 1, "standard": 4, "comprehensive": 6, "custom": 6, "agent_decided": 6}


def _selection_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        ignored = {"id", "status", "owner", "source", "likelihood", "impact", "evidence_status", "confidence"}
        return [text for key, item in value.items() if key not in ignored for text in _selection_text(item)]
    if isinstance(value, list):
        return [text for item in value for text in _selection_text(item)]
    return []


def _project_text(manifest: dict[str, Any]) -> tuple[str, str]:
    project = manifest["project"]
    confirmed_fields: list[Any] = [
        project.get("name", ""), project.get("summary", ""), project.get("problem_statement", ""),
        project.get("classification", ""), project.get("target_audience", []), project.get("goals", []),
        project.get("platforms", []), project.get("scope", {}), project.get("existing_repository", {}).get("observations", []),
        {key: manifest.get("technology", {}).get(key, []) for key in ("preferences", "selected", "alternatives")},
        manifest.get("architecture", {}), manifest.get("constraints", {}),
        {key: value for key, value in manifest.get("data_api", {}).items() if key != "decisions"},
    ]
    open_fields: list[Any] = [manifest.get("risks", [])]
    for evidence in manifest.get("technology", {}).get("compatibility_evidence", []):
        target = confirmed_fields if evidence.get("status") in {"confirmed", "verified"} else open_fields
        target.append({key: value for key, value in evidence.items() if key != "status"})
    for feature in manifest.get("features", []):
        target = confirmed_fields if feature.get("status") in {"confirmed", "verified"} else open_fields
        target.append({key: value for key, value in feature.items() if key != "status"})
    for fact in manifest.get("facts", []):
        target = confirmed_fields if fact.get("status") in {"confirmed", "verified"} else open_fields
        target.append({key: value for key, value in fact.items() if key not in {"status", "source"}})
    decisions = [*manifest.get("decisions", []), *manifest.get("data_api", {}).get("decisions", [])]
    for decision in decisions:
        target = confirmed_fields if decision.get("status") in {"confirmed", "verified"} else open_fields
        fields = {key: value for key, value in decision.items() if key not in {"status", "owner", "id", "evidence"}}
        target.append(fields)
    for assumption in manifest.get("assumptions", []):
        target = confirmed_fields if assumption.get("status") == "validated" else open_fields
        target.append({key: value for key, value in assumption.items() if key not in {"status", "owner", "id"}})
    confirmed_text = " ".join(text for value in confirmed_fields for text in _selection_text(value)).casefold()
    open_text = " ".join(text for value in open_fields for text in _selection_text(value)).casefold()
    return confirmed_text, open_text


def _token_match(phrase: str, text: str) -> bool:
    words = [word for word in re.findall(r"[a-z0-9+#.-]+", phrase.casefold()) if len(word) > 1]
    if not words or phrase.casefold() in {"all projects", "project kickoff", "coordination"}:
        return False
    normalized = " ".join(re.findall(r"[a-z0-9+#.-]+", text.casefold()))
    if len(words) > 1:
        phrase_pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(word) for word in words) + r"(?![a-z0-9])"
        return re.search(phrase_pattern, normalized) is not None
    word = words[0]
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", normalized) is not None


def _prerequisite_candidates(prerequisite: str, assignment: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stop_words = {"the", "and", "for", "from", "with", "that", "this", "contract", "needs", "choices", "requirements"}
    terms = {word for word in re.findall(r"[a-z0-9+#.-]+", prerequisite.casefold()) if len(word) > 2 and word not in stop_words}
    ranked = []
    for candidate in candidates:
        if candidate["id"] == assignment["id"]:
            continue
        text = " ".join([
            candidate.get("name", ""), candidate.get("mission", ""),
            *candidate.get("responsibilities", []), *candidate.get("outputs", []),
        ]).casefold()
        matches = sorted(term for term in terms if _token_match(term, text))
        if matches:
            ranked.append({"assignment_id": candidate["id"], "matched_terms": matches})
    return sorted(ranked, key=lambda item: (-len(item["matched_terms"]), item["assignment_id"]))[:3]


def _score_role(role: dict[str, Any], text: str, platforms: list[str], open_text: str = "") -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    for trigger in role["triggers"]:
        if role["id"] == "cost-financial-analyst" and trigger in {"budget", "finance"}:
            continue
        if _token_match(trigger, text):
            score += 2.5 if " " not in trigger else 3.0
            reasons.append(f"project signal matches {trigger!r}")
        elif _token_match(trigger, open_text):
            score += 1.5 if " " not in trigger else 2.0
            reasons.append(f"open question or assumption matches {trigger!r}")
    identity = role["identity"].casefold()
    for platform in platforms:
        if platform and _token_match(platform, identity + " " + role["mission"].casefold()):
            score += 4.0
            reasons.append(f"selected platform is {platform}")
    return score, reasons


def _overlap_pairs(role_ids: list[str], role_map: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for role_id in role_ids:
        role = role_map[role_id]
        for other in role["overlap_with"]:
            if other in role_ids and other != role_id:
                pairs.add(tuple(sorted((role_id, other))))
    return sorted(pairs)


def _schedule(role_ids: list[str], manifest: dict[str, Any]) -> list[list[str]]:
    dependencies: dict[str, set[str]] = {role_id: set() for role_id in role_ids}
    for assignment in [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]:
        if assignment["id"] in dependencies:
            dependencies[assignment["id"]].update(dep for dep in assignment.get("dependencies", []) if dep in dependencies)
    for edge in manifest["dependencies"]:
        if edge["kind"] in {"blocks", "reviews"} and edge["from"] in dependencies and edge["to"] in dependencies:
            dependencies[edge["from"]].add(edge["to"])
    remaining = set(role_ids)
    layers: list[list[str]] = []
    while remaining:
        ready = sorted(node for node in remaining if not (dependencies[node] & remaining))
        if not ready:
            break
        layers.append(ready)
        remaining.difference_update(ready)
    return layers


def _team_metrics(
    selected: list[str], profiles: dict[str, dict[str, Any]], scores: dict[str, tuple[float, list[str]]],
    manifest: dict[str, Any], estimates: dict[str, Any],
) -> dict[str, Any]:
    overlap_details = _overlap_pairs(selected, profiles)
    possible_pairs = len(selected) * (len(selected) - 1) / 2
    independence = 1.0 if possible_pairs == 0 else 1.0 - len(overlap_details) / possible_pairs
    relevance = []
    for role_id in selected:
        score, signals = scores.get(role_id, (0.0, []))
        relevance.append({"role_id": role_id, "score": round(min(score, 10.0), 2), "signals": signals})

    per_role_context = []
    for role_id in selected:
        profile = profiles[role_id]
        per_role_context.append({
            "role_id": role_id,
            "required_capability_count": len(profile["required_capabilities"]) + len(profile["tool_requirements"]),
            "deliverable_count": len(profile["deliverables"]),
            "research_method_count": len(profile["research_methodology"]),
            "estimated_input_tokens": 1500,
        })
    complexity_units = len(manifest.get("features", [])) + len(manifest["architecture"].get("components", []))
    context_tokens = estimates["estimated_input_tokens"]
    research_count = sum(len(profiles[role_id]["research_methodology"]) for role_id in selected)
    research_score = min(10.0, round(research_count / max(1, len(selected)) * 1.5, 2))
    integration_score = min(10.0, round(
        1 + len(selected) * 0.75 + len(overlap_details) * 0.8
        + len(manifest.get("dependencies", [])) * 0.6
        + len(manifest["architecture"].get("components", [])) * 0.25, 2
    ))
    review_points = round(2 + sum(
        1 + len(profiles[role_id]["deliverables"]) * 0.5
        + len(profiles[role_id]["acceptance_criteria"]) * 0.25
        for role_id in selected
    ), 2)
    return {
        "role_relevance": relevance,
        "role_overlap": {"pair_count": len(overlap_details), "pairs": [list(pair) for pair in overlap_details]},
        "workstream_independence": {
            "score": round(independence, 2),
            "basis": "1 minus overlapping role pairs divided by all possible specialist pairs; a one-role team scores 1.0.",
        },
        "coordination_overhead": {
            "score": estimates["coordination_score"],
            "handoffs": estimates["handoffs"],
            "basis": "Team-size, handoff, and project-complexity planning heuristic; lower is simpler.",
        },
        "context_requirements": {
            "estimated_input_tokens": context_tokens,
            "project_complexity_units": complexity_units,
            "per_role": per_role_context,
            "basis": "Planning estimate uses 2,500 supervisor input tokens, 1,500 per specialist, and 120 per feature or architecture component.",
        },
        "research_complexity": {
            "score": research_score,
            "research_method_count": research_count,
            "basis": "Average number of catalogue research methods per selected role, multiplied by 1.5 and capped at 10.",
        },
        "integration_complexity": {
            "score": integration_score,
            "basis": "Heuristic: 1 + 0.75 per specialist + 0.8 per overlap pair + 0.6 per manifest dependency + 0.25 per architecture component, capped at 10.",
        },
        "handoffs": estimates["handoffs"],
        "expected_review_effort_points": review_points,
        "review_effort_basis": "Uncalibrated points: 2 supervisor points, 1 per specialist, 0.5 per catalogue deliverable, and 0.25 per acceptance criterion.",
    }


def _handoff_count(selected: list[str], profiles: dict[str, dict[str, Any]], manifest: dict[str, Any], overlap_count: int) -> int:
    selected_ids = set(selected)
    dependency_pairs = {
        (edge["from"], edge["to"]) for edge in manifest["dependencies"]
        if edge["from"] in selected_ids and edge["to"] in selected_ids
    }
    for role_id in selected:
        dependency_pairs.update((role_id, dependency) for dependency in profiles[role_id].get("dependencies", []) if dependency in selected_ids)
    return overlap_count + len(dependency_pairs)


def optimize_team(
    manifest: dict[str, Any], *, roles: list[dict[str, Any]], mode: str | None = None,
    requested_roles: list[str] | None = None, selection_mode: str | None = None,
) -> dict[str, Any]:
    mode = mode or manifest["discovery"].get("mode", "agent_decided")
    if mode not in MODE_LIMITS:
        raise ValueError(f"Unknown team mode {mode!r}; choose one of {', '.join(MODE_LIMITS)}")
    profiles = {role["id"]: role for role in roles}
    if "supervisor" not in profiles:
        raise ValueError("Role catalogue does not include the required supervisor profile")
    selection_mode = selection_mode or ("manual" if requested_roles else manifest["team"].get("selection_mode", "dynamic"))
    if selection_mode not in {"dynamic", "manual", "hybrid"}:
        raise ValueError("Unknown selection mode; choose dynamic, manual, or hybrid")
    if selection_mode == "manual" and not requested_roles:
        raise ValueError("Manual selection requires one or more role IDs via --role")
    if selection_mode == "hybrid" and not requested_roles:
        raise ValueError("Hybrid selection requires at least one user-selected role via --role")
    if selection_mode == "dynamic" and requested_roles:
        raise ValueError("Dynamic selection cannot be combined with --role; choose manual or hybrid")
    specialist_profiles = [role for role in roles if role["id"] != "supervisor"]
    project_text, open_text = _project_text(manifest)
    platforms = manifest["project"].get("platforms", [])
    scores = {role["id"]: _score_role(role, project_text, platforms, open_text) for role in specialist_profiles}
    database_terms = (
        "database architecture", "database design", "database schema", "data model", "schema migration",
        "query optimization", "data warehouse", "database architect", "multi-tenant data", "tenant isolation",
        "postgresql", "backup and restore", "data retention", "audit log", "transactions",
    )
    local_stores = manifest["data_api"].get("datastores", [])
    project_signals = project_text + " " + open_text
    local_storage_terms = ("local database", "local storage", "offline-first", "offline first", "room database", "sqlite", "file system", "filesystem")
    local_context = any(term in project_signals for term in local_storage_terms)
    local_store_declarations = not local_stores or all(
        any(token in store.casefold() for token in ("local", "room", "sqlite", "filesystem", "file system"))
        for store in local_stores
    )
    local_only = local_context and local_store_declarations and not manifest["data_api"].get("apis")
    if local_only and not any(term in project_text + " " + open_text for term in database_terms):
        prior_score, prior_reasons = scores.get("database-architect", (0.0, []))
        if prior_score:
            scores["database-architect"] = (0.0, [reason for reason in prior_reasons if "datastore" not in reason])
    suggestions: list[str] = []
    approval_required = False

    if selection_mode in {"manual", "hybrid"}:
        selected = list(dict.fromkeys(requested_roles or []))
        unknown = [role_id for role_id in selected if role_id not in profiles or role_id == "supervisor"]
        if unknown:
            raise ValueError("Unknown specialist role ID(s): " + ", ".join(unknown))
        if selection_mode == "hybrid":
            complexity = len(manifest.get("features", [])) + len(manifest["data_api"].get("apis", [])) + len(manifest["data_api"].get("datastores", [])) + len(manifest["data_api"].get("authentication", [])) + max(0, len(platforms) - 1) * 2 + len(manifest.get("risks", []))
            limit = 1 if mode == "quick" else 2 if mode == "standard" and complexity <= 2 else 3 if mode == "standard" and complexity <= 6 else 4 if mode == "standard" else 6
            target_size = max(limit, len(selected))
            ranked = sorted(specialist_profiles, key=lambda role: (-scores[role["id"]][0], role["id"]))
            for role in ranked:
                role_id = role["id"]
                if len(selected) >= target_size:
                    break
                if scores[role_id][0] > 0 and role_id not in selected:
                    selected.append(role_id)
    else:
        complexity = len(manifest.get("features", [])) + len(manifest["data_api"].get("apis", [])) + len(manifest["data_api"].get("datastores", [])) + len(manifest["data_api"].get("authentication", [])) + max(0, len(platforms) - 1) * 2 + len(manifest.get("risks", []))
        if mode == "quick":
            limit = 1
        elif mode == "standard":
            limit = 2 if complexity <= 2 else 3 if complexity <= 6 else 4
        elif mode == "comprehensive":
            limit = 6
        else:
            limit = 2 if complexity <= 2 else 4 if complexity <= 7 else 6
        limit = min(limit, MODE_LIMITS[mode])
        ranked = sorted(specialist_profiles, key=lambda role: (-scores[role["id"]][0], role["id"]))
        selected = [role["id"] for role in ranked if scores[role["id"]][0] > 0][:limit]
        if not selected and (manifest["project"].get("problem_statement") or manifest["project"].get("summary")):
            selected = ["product-manager"] if "product-manager" in profiles else []
            if selected:
                scores[selected[0]] = (0.5, ["project has a goal but no domain signals; use one product discovery specialist"])

    overlaps = _overlap_pairs(selected, profiles)
    handoffs = _handoff_count(selected, profiles, manifest, len(overlaps))
    if len(selected) > 6:
        approval_required = True
        estimates = _estimate(len(selected), handoffs, len(manifest.get("features", [])) + len(manifest["architecture"].get("components", [])))
        metrics = _team_metrics(selected, profiles, scores, manifest, estimates)
        suggestions = [
            f"The requested team has {1 + len(selected)} people including the supervisor; the limit is seven.",
            ("Potentially overlapping pairs: " + "; ".join(f"{profiles[left]['identity']} / {profiles[right]['identity']}" for left, right in overlaps)) if overlaps else "Review roles with adjacent responsibilities for a possible merge.",
            "Keep only the highest-value six specialists for this phase and consult other experts sequentially.",
            "Split work into project phases when all requested expertise is necessary.",
        ]
        return {"mode": mode, "selection_mode": selection_mode, "approval_required": True, "approval_status": "needs_user_approval", "selected_role_ids": selected, "assignments": [], "rationale": suggestions, "overlap_pairs": len(overlaps), "overlap_details": overlaps, "schedule": [], "estimates": estimates, "metrics": metrics}

    role_ids = ["supervisor", *selected]
    overlap_details = overlaps
    selected_overlap = len(overlap_details)
    assignments = [new_assignment(profiles[role_id]) for role_id in selected]
    planned_assignments = [manifest["team"]["supervisor"], *assignments]
    rationale = []
    for role_id in selected:
        score, reasons = scores.get(role_id, (0.0, []))
        rationale.append(f"{profiles[role_id]['identity']}: " + ("; ".join(reasons) if reasons else "explicitly requested"))
    if selected_overlap:
        rationale.append(f"Review {selected_overlap} overlapping role pair(s); keep separate only if their deliverables have distinct owners.")
    if len(assignments) < 3:
        rationale.append("Kept the team small because the current project signals do not establish independent work for more specialists.")
    estimates = _estimate(len(selected), handoffs, len(manifest.get("features", [])) + len(manifest["architecture"].get("components", [])))
    metrics = _team_metrics(selected, profiles, scores, manifest, estimates)
    resolved_prerequisites = {
        (edge["from"], edge["prerequisite"])
        for edge in manifest.get("dependencies", [])
        if edge.get("prerequisite") and edge.get("resolution_source") == "role_prerequisite"
    }
    unresolved_prerequisites = [
        {
            "assignment_id": assignment["id"], "role_id": assignment["role_id"], "prerequisite": prerequisite,
            "candidate_providers": _prerequisite_candidates(prerequisite, assignment, planned_assignments),
        }
        for assignment in planned_assignments
        for prerequisite in assignment.get("prerequisites", [])
        if (assignment["id"], prerequisite) not in resolved_prerequisites
    ]
    if unresolved_prerequisites:
        rationale.append(f"Resolve {len(unresolved_prerequisites)} role prerequisite(s) before finalizing the execution schedule; no provider or relationship was guessed.")
    return {
        "mode": mode,
        "selection_mode": selection_mode,
        "approval_required": approval_required,
        "approval_status": "proposed",
        "selected_role_ids": selected,
        "assignments": assignments,
        "rationale": rationale,
        "overlap_pairs": selected_overlap,
        "overlap_details": overlap_details,
        "schedule": _schedule(role_ids, manifest),
        "unresolved_prerequisites": unresolved_prerequisites,
        "estimates": estimates,
        "metrics": metrics,
    }


def _estimate(specialists: int, handoffs: int, complexity_units: int) -> dict[str, Any]:
    # Transparent planning heuristic, not measured model usage.
    input_tokens = 2500 + specialists * 1500 + max(0, complexity_units) * 120
    output_tokens = 1800 + specialists * 1150 + handoffs * 250
    score = round((specialists + 1) ** 1.4 + handoffs * 0.8 + complexity_units * 0.15, 2)
    return {"estimated_input_tokens": input_tokens, "estimated_output_tokens": output_tokens, "handoffs": handoffs, "coordination_score": score, "method": "Planning heuristic: supervisor 2500 input/1800 output tokens; each specialist 1500/1150; complexity 120 input per feature or component; 250 output per handoff."}
