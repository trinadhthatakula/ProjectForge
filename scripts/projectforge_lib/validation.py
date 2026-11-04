from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

from .common import read_json, skill_root
from .migrations import SUPPORTED_MANIFEST_VERSIONS


def _schema_errors(manifest: dict[str, Any], schema_path: Path) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Manifest validation requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    schema = read_json(schema_path)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(manifest), key=lambda e: tuple(str(x) for x in e.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{path}: {error.message}")
    return errors


def _check_unique_ids(items: list[dict[str, Any]], label: str, key: str = "id") -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        value = item.get(key)
        if value in seen:
            errors.append(f"{label}[{index}].{key}: duplicate value {value!r}")
        seen.add(value)
    return errors


def _cycle(nodes: set[str], edges: list[tuple[str, str]]) -> list[str] | None:
    graph: dict[str, list[str]] = {node: [] for node in nodes}
    for item, dependency in edges:
        graph[item].append(dependency)
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dependency in graph[node]:
            if state.get(dependency, 0) == 0:
                found = visit(dependency)
                if found:
                    return found
            elif state.get(dependency) == 1:
                start = stack.index(dependency)
                return stack[start:] + [dependency]
        stack.pop()
        state[node] = 2
        return None

    for node in sorted(nodes):
        if state.get(node, 0) == 0:
            found = visit(node)
            if found:
                return found
    return None


def _has_content(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    return value is not None


def _readiness_gate_errors(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    project = manifest["project"]
    required_values = {
        "project.problem_statement": project["problem_statement"],
        "project.target_audience": project["target_audience"],
        "project.goals": project["goals"],
        "project.platforms": project["platforms"],
        "project.scope.included": project["scope"]["included"],
        "project.features": manifest["features"],
        "technology.selected": manifest["technology"]["selected"],
        "constraints.security_privacy": manifest["constraints"]["security_privacy"],
        "constraints.monetization": manifest["constraints"]["monetization"],
        "constraints.budget": manifest["constraints"]["budget"],
        "architecture.summary": manifest["architecture"]["summary"],
        "milestones": manifest["milestones"],
    }
    for path, value in required_values.items():
        if not _has_content(value):
            errors.append(f"readiness.status cannot be 'ready' while {path} is empty")
    if project["classification"] == "pending":
        errors.append("readiness.status cannot be 'ready' while project.classification is pending")

    data_api = manifest["data_api"]
    if not any(_has_content(data_api.get(key)) for key in ("datastores", "apis", "authentication", "decisions")):
        errors.append("readiness.status cannot be 'ready' while data, API, and identity scope is unstated; record the applicable choices or explicitly mark them not applicable")
    for milestone in manifest["milestones"]:
        if not milestone["name"].strip() or not milestone["target"].strip():
            errors.append(f"readiness.status cannot be 'ready' while milestone {milestone['id']!r} lacks a name or target")

    if manifest["team"]["approval_status"] != "accepted":
        errors.append("readiness.status cannot be 'ready' until the proposed team is accepted")
    if len(manifest["team"]["specialists"]) > 6:
        errors.append("readiness.status cannot be 'ready' with more than six specialists plus the supervisor")

    for feature in manifest["features"]:
        if feature["priority"] != "must":
            continue
        criteria = [item for item in feature["acceptance_criteria"] if item.strip()]
        if not criteria:
            errors.append(f"readiness.status cannot be 'ready' while must-have feature {feature['id']!r} has no acceptance criteria")
        if feature["status"] not in {"confirmed", "verified"}:
            errors.append(f"readiness.status cannot be 'ready' while must-have feature {feature['id']!r} is {feature['status']}")

    resolved_statuses = {"confirmed", "verified"}
    decisions = [*manifest["decisions"], *data_api["decisions"]]
    for decision in decisions:
        owner = decision["owner"].strip()
        required = decision.get("required", True)
        if not owner:
            errors.append(f"readiness.status cannot be 'ready' while decision {decision['id']!r} has no owner")
        if required and decision["status"] not in resolved_statuses:
            errors.append(f"readiness.status cannot be 'ready' while required decision {decision['id']!r} is {decision['status']}")
        if required and decision["status"] in resolved_statuses and not (decision.get("selected") or decision["rationale"].strip()):
            errors.append(f"readiness.status cannot be 'ready' while resolved decision {decision['id']!r} has no recorded outcome or rationale")

    for risk in manifest["risks"]:
        if not risk["owner"].strip():
            errors.append(f"readiness.status cannot be 'ready' while risk {risk['id']!r} has no owner")
        if risk["impact"] == "high" and not risk["mitigation"].strip():
            errors.append(f"readiness.status cannot be 'ready' while high-impact risk {risk['id']!r} has no mitigation")
    for assumption in manifest["assumptions"]:
        if assumption["status"] == "open" and (not assumption["owner"].strip() or not assumption["validation_action"].strip()):
            errors.append(f"readiness.status cannot be 'ready' while open assumption {assumption['id']!r} lacks an owner or validation action")

    capability_rows = manifest["capability_report"]["role_matches"]
    team_role_ids = {item["role_id"] for item in [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]}
    reported_role_ids = {item["role_id"] for item in capability_rows}
    if not capability_rows:
        errors.append("readiness.status cannot be 'ready' before required capabilities are matched to the current runtime")
    for role_id in sorted(team_role_ids - reported_role_ids):
        errors.append(f"readiness.status cannot be 'ready' while capability matching has no result for role {role_id!r}")

    plans = manifest["readiness"].get("capability_plans", [])
    for role in capability_rows:
        for requirement in role["requirements"]:
            if requirement["kind"] != "required" or requirement["status"] == "available":
                continue
            planned = any(
                plan["role_id"] == role["role_id"] and plan["capability"].casefold() == requirement["capability"].casefold()
                and plan["owner"].strip() and plan["next_action"].strip()
                for plan in plans
            )
            if not planned:
                errors.append(f"readiness.status cannot be 'ready' while required capability {role['role_id']!r}: {requirement['capability']!r} is {requirement['status']} without an owner and next-action plan")
    return errors


def readiness_blockers(manifest: dict[str, Any]) -> list[str]:
    prefix = "readiness.status cannot be 'ready' while "
    explicit = manifest["readiness"].get("blockers", [])
    derived = [error.removeprefix(prefix) for error in _readiness_gate_errors(manifest)]
    return list(dict.fromkeys([*explicit, *derived]))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    version = manifest.get("schema_version") if isinstance(manifest, dict) else None
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        return [f"Unsupported manifest schema_version {version!r}; supported versions: {', '.join(sorted(SUPPORTED_MANIFEST_VERSIONS))}. Use 'migrate' for a supported older manifest."]
    schema_name = "project-manifest-1.0.0.schema.json" if version == "1.0.0" else "project-manifest.schema.json"
    errors = _schema_errors(manifest, skill_root() / "schemas" / schema_name)
    if errors:
        return errors

    team = manifest["team"]
    if team["supervisor"].get("role_id") != "supervisor":
        errors.append("team.supervisor.role_id must be 'supervisor'")
    if any(item.get("role_id") == "supervisor" for item in team["specialists"]):
        errors.append("team.specialists must not contain a second supervisor")
    assignments = [team["supervisor"], *team["specialists"]]
    errors.extend(_check_unique_ids(assignments, "team.assignments"))
    errors.extend(_check_unique_ids(assignments, "team.assignments", key="role_id"))
    for assignment in assignments:
        contract = assignment.get("result_contract")
        if not contract:
            continue
        for field in ("allowed_paths", "protected_paths"):
            rules = contract.get(field, [])
            if len(rules) != len(set(rules)):
                errors.append(f"assignment {assignment['id']!r} result_contract.{field} contains duplicate paths")
            for rule in rules:
                normalized_rule = rule.rstrip("/")
                path = PurePosixPath(normalized_rule)
                has_windows_drive = len(normalized_rule) > 1 and normalized_rule[0].isalpha() and normalized_rule[1] == ":"
                if "\\" in rule or not normalized_rule or normalized_rule == "." or has_windows_drive or path.is_absolute() or ".." in path.parts or "." in path.parts or normalized_rule != path.as_posix():
                    errors.append(f"assignment {assignment['id']!r} result_contract.{field} contains unsafe relative path {rule!r}")
        check_names = [item.casefold() for item in contract.get("required_checks", [])]
        if len(check_names) != len(set(check_names)):
            errors.append(f"assignment {assignment['id']!r} result_contract.required_checks contains duplicates")
    assignment_ids = {item["id"] for item in assignments}
    execution_results = manifest.get("execution", {}).get("results", [])
    seen_result_ids: dict[str, dict[str, Any]] = {}
    seen_result_files: set[str] = set()
    seen_attempts: set[tuple[str, int]] = set()
    for index, result in enumerate(execution_results):
        result_id = result["result_id"]
        result_file = result["result_file"]
        assignment_id = result["assignment_id"]
        attempt = result["attempt"]
        if result_id in seen_result_ids:
            errors.append(f"execution.results[{index}].result_id duplicates {result_id!r}")
        if result_file in seen_result_files:
            errors.append(f"execution.results[{index}].result_file duplicates {result_file!r}")
        if assignment_id not in assignment_ids:
            errors.append(f"execution result {result_id!r} refers to unknown assignment_id {assignment_id!r}")
        if result["review_status"] in {"accepted", "rejected", "rework_required"} and (not result.get("reviewer", "").strip() or not result.get("reviewed_at", "").strip()):
            errors.append(f"execution result {result_id!r} has a supervisor decision without reviewer and reviewed_at")
        if result["review_status"] == "accepted" and result["status"] not in {"completed", "validated"}:
            errors.append(f"execution result {result_id!r} cannot be accepted from status {result['status']!r}")
        path = PurePosixPath(result_file)
        has_windows_drive = len(result_file) > 1 and result_file[0].isalpha() and result_file[1] == ":"
        if "\\" in result_file or has_windows_drive or path.is_absolute() or ".." in path.parts or "." in path.parts or result_file != path.as_posix() or path.as_posix() in {"", "."}:
            errors.append(f"execution result {result_id!r} has unsafe relative result_file {result_file!r}")
        attempt_key = (assignment_id, attempt)
        if attempt_key in seen_attempts:
            errors.append(f"assignment {assignment_id!r} has more than one result file for attempt {attempt}")
        seen_attempts.add(attempt_key)
        prior_id = result["prior_result_id"]
        if attempt == 1 and prior_id is not None:
            errors.append(f"execution result {result_id!r} attempt 1 must have prior_result_id=null")
        elif attempt > 1:
            prior = seen_result_ids.get(prior_id)
            if prior is None or prior["assignment_id"] != assignment_id or prior["attempt"] + 1 != attempt:
                errors.append(f"execution result {result_id!r} does not follow its immediately preceding attempt")
            elif prior["review_status"] not in {"rejected", "rework_required"}:
                errors.append(f"execution result {result_id!r} retries an attempt without a rejected or rework_required review")
        seen_result_ids[result_id] = result
        seen_result_files.add(result_file)
    dependency_edges: list[tuple[str, str]] = []
    seen_dependency_edges: set[tuple[str, str, str]] = set()
    for assignment in assignments:
        assignment_dependencies = assignment["dependencies"]
        if len(assignment_dependencies) != len(set(assignment_dependencies)):
            errors.append(f"assignment {assignment['id']!r} contains duplicate dependencies")
        for dependency in assignment_dependencies:
            if dependency not in assignment_ids:
                errors.append(f"assignment {assignment['id']!r} refers to unknown dependency {dependency!r}")
            elif dependency == assignment["id"]:
                errors.append(f"assignment {assignment['id']!r} depends on itself")
            else:
                seen_dependency_edges.add((assignment["id"], dependency, "blocks"))
                dependency_edges.append((assignment["id"], dependency))
    for edge in manifest["dependencies"]:
        source, target = edge["from"], edge["to"]
        edge_key = (source, target, edge["kind"])
        if edge_key in seen_dependency_edges:
            errors.append(f"duplicate team dependency edge {source!r} -> {target!r} ({edge['kind']})")
        seen_dependency_edges.add(edge_key)
        if source not in assignment_ids or target not in assignment_ids:
            missing = [value for value in (source, target) if value not in assignment_ids]
            errors.append(f"dependency {source!r} -> {target!r} refers to unknown assignment ID(s): {', '.join(repr(value) for value in missing)}")
        elif source == target:
            errors.append(f"dependency {source!r} cannot refer to itself")
        elif edge["kind"] in {"blocks", "reviews"}:
            dependency_edges.append((source, target))
        if edge.get("prerequisite"):
            source_assignment = next((item for item in assignments if item["id"] == source), None)
            if source_assignment and edge["prerequisite"] not in source_assignment.get("prerequisites", []):
                errors.append(f"dependency {source!r} prerequisite {edge['prerequisite']!r} is not declared by that assignment")
    found_cycle = _cycle(assignment_ids, dependency_edges)
    if found_cycle:
        errors.append("team dependency cycle: " + " -> ".join(found_cycle))

    errors.extend(_check_unique_ids(manifest["features"], "features"))
    feature_ids = {item["id"] for item in manifest["features"]}
    feature_edges: list[tuple[str, str]] = []
    for feature in manifest["features"]:
        for dependency in feature["depends_on"]:
            if dependency not in feature_ids:
                errors.append(f"feature {feature['id']!r} refers to unknown feature {dependency!r}")
            elif dependency == feature["id"]:
                errors.append(f"feature {feature['id']!r} depends on itself")
            else:
                feature_edges.append((feature["id"], dependency))
    feature_cycle = _cycle(feature_ids, feature_edges)
    if feature_cycle:
        errors.append("feature dependency cycle: " + " -> ".join(feature_cycle))
    errors.extend(_check_unique_ids(manifest["architecture"]["components"], "architecture.components"))
    component_ids = {item["id"] for item in manifest["architecture"]["components"]}
    for flow in manifest["architecture"]["flows"]:
        if flow["from"] not in component_ids or flow["to"] not in component_ids:
            errors.append(f"architecture flow {flow['from']!r} -> {flow['to']!r} must refer to component IDs")
    errors.extend(_check_unique_ids(manifest["milestones"], "milestones"))
    milestone_ids = {item["id"] for item in manifest["milestones"]}
    milestone_edges: list[tuple[str, str]] = []
    for milestone in manifest["milestones"]:
        for dependency in milestone["depends_on"]:
            if dependency not in milestone_ids:
                errors.append(f"milestone {milestone['id']!r} refers to unknown milestone {dependency!r}")
            elif dependency == milestone["id"]:
                errors.append(f"milestone {milestone['id']!r} depends on itself")
            else:
                milestone_edges.append((milestone["id"], dependency))
    milestone_cycle = _cycle(milestone_ids, milestone_edges)
    if milestone_cycle:
        errors.append("milestone dependency cycle: " + " -> ".join(milestone_cycle))
    for field in ("deliverables", "risks", "assumptions", "decisions"):
        errors.extend(_check_unique_ids(manifest[field], field))
    # The assignment contract is embedded in the manifest schema; validate it directly as well for a useful independent gate.
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Assignment validation requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    assignment_schema = read_json(skill_root() / "schemas" / "agent-assignment.schema.json")
    Draft202012Validator.check_schema(assignment_schema)
    assignment_validator = Draft202012Validator(assignment_schema)
    for assignment in assignments:
        for error in assignment_validator.iter_errors(assignment):
            errors.append(f"assignment {assignment['id']}.{'.'.join(str(x) for x in error.absolute_path)}: {error.message}")
    if manifest["readiness"]["status"] == "ready" and manifest["readiness"]["blockers"]:
        errors.append("readiness.status cannot be 'ready' while blockers remain")
    if manifest["readiness"]["status"] == "ready":
        errors.extend(_readiness_gate_errors(manifest))
    if not manifest["output_preferences"]["formats"]:
        errors.append("output_preferences.formats must include at least one output format")
    return errors


def validate_role_catalog(catalog: dict[str, Any] | None = None) -> list[str]:
    if catalog is None:
        catalog = read_json(skill_root() / "references" / "roles.json")
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Role validation requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("roles"), list):
        return ["catalogue must be an object containing a roles array"]
    if catalog.get("catalog_version") not in {"1.0.0", "1.1.0", "custom"}:
        return [f"unsupported role catalogue version: {catalog.get('catalog_version')!r}"]
    schema = read_json(skill_root() / "schemas" / "role.schema.json")
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    ids: set[str] = set()
    for index, role in enumerate(catalog.get("roles", [])):
        if role.get("id") in ids:
            errors.append(f"roles[{index}].id: duplicate role ID {role.get('id')!r}")
        ids.add(role.get("id"))
        for error in validator.iter_errors(role):
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            errors.append(f"roles[{index}].{path}: {error.message}")
        guide = role.get("guide")
        if isinstance(guide, str) and guide:
            expected_guide = f"role-guides/{role.get('id')}.md"
            guide_path = skill_root() / "references" / guide
            if guide != expected_guide:
                errors.append(f"roles[{index}].guide: expected {expected_guide!r}")
            elif not guide_path.is_file():
                errors.append(f"roles[{index}].guide: file does not exist: {guide!r}")
    for index, role in enumerate(catalog.get("roles", [])):
        if role.get("id") in role.get("overlap_with", []):
            errors.append(f"roles[{index}] cannot overlap with itself")
    return errors
