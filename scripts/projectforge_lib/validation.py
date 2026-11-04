from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import read_json, skill_root


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


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    errors = _schema_errors(manifest, skill_root() / "schemas" / "project-manifest.schema.json")
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
    assignment_ids = {item["id"] for item in assignments}
    dependency_edges: list[tuple[str, str]] = []
    for assignment in assignments:
        for dependency in assignment["dependencies"]:
            if dependency not in assignment_ids:
                errors.append(f"assignment {assignment['id']!r} refers to unknown dependency {dependency!r}")
            elif dependency == assignment["id"]:
                errors.append(f"assignment {assignment['id']!r} depends on itself")
            else:
                dependency_edges.append((assignment["id"], dependency))
    for edge in manifest["dependencies"]:
        source, target = edge["from"], edge["to"]
        if source not in assignment_ids or target not in assignment_ids:
            missing = [value for value in (source, target) if value not in assignment_ids]
            errors.append(f"dependency {source!r} -> {target!r} refers to unknown assignment ID(s): {', '.join(repr(value) for value in missing)}")
        elif source == target:
            errors.append(f"dependency {source!r} cannot refer to itself")
        else:
            dependency_edges.append((source, target))
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
        project = manifest["project"]
        required_values = {
            "project.problem_statement": project["problem_statement"],
            "project.target_audience": project["target_audience"],
            "project.goals": project["goals"],
            "project.platforms": project["platforms"],
            "project.features": manifest["features"],
            "architecture.summary": manifest["architecture"]["summary"],
        }
        for path, value in required_values.items():
            if not value:
                errors.append(f"readiness.status cannot be 'ready' while {path} is empty")
        if project["classification"] == "pending":
            errors.append("readiness.status cannot be 'ready' while project.classification is pending")
        if team["approval_status"] != "accepted":
            errors.append("readiness.status cannot be 'ready' until the proposed team is accepted")
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
