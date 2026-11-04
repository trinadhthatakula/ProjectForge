from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from .changes import compare_manifests, diff_markdown
from .classification import classify_project
from .common import catalog, new_manifest, now_utc, read_json, read_json_with_sha256, skill_root, write_text, write_text_if_unchanged
from .discovery import discover_environment, inspect_skill, match_capabilities
from .handoffs import result_sha256, validate_agent_result, validate_result_location
from .migrations import CURRENT_MANIFEST_VERSION, migrate_manifest
from .optimization import _estimate, optimize_team
from .rendering import render_html, render_markdown
from .security import redact_sensitive
from .validation import readiness_blockers, validate_manifest, validate_role_catalog
from .verification import derive_verification_status, verification_errors


_CAPABILITY_VERIFICATION_BLOCKERS = {
    "Capability discovery was refreshed; required capabilities need verification again.",
    "A required capability needs new verification.",
    "Required capabilities must be verified against the active runtime.",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="projectforge", description="Discover and verify capabilities, plan a small specialist team, validate a project manifest, and generate kickoff documents.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create a protected starter manifest")
    init.add_argument("--name", required=True)
    init.add_argument("--mode", choices=["quick", "standard", "comprehensive", "custom", "agent_decided"], default="agent_decided")
    init.add_argument("--output", required=True, type=Path)
    init.add_argument("--force", action="store_true")
    init.add_argument("--dry-run", action="store_true")

    roles = sub.add_parser("roles", help="list catalogue roles")
    roles.add_argument("--category")
    roles.add_argument("--format", choices=["text", "json"], default="text")

    classify = sub.add_parser("classify", help="recommend a project classification from stated signals")
    classify.add_argument("manifest", type=Path)
    classify.add_argument("--apply", action="store_true", help="apply an unambiguous recommendation to a pending classification")
    classify.add_argument("--dry-run", action="store_true")

    inspect = sub.add_parser("inspect-skill", help="read one locally discovered skill instruction file without executing it")
    inspect.add_argument("name")
    inspect.add_argument("--cwd", type=Path, default=Path.cwd())
    inspect.add_argument("--skills-dir", type=Path, action="append", default=[])
    inspect.add_argument("--max-chars", type=int, default=40000)
    inspect.add_argument("--format", choices=["text", "json"], default="text")

    discover = sub.add_parser("discover", help="inspect local skills, agents, and runtime metadata")
    discover.add_argument("--cwd", type=Path, default=Path.cwd())
    discover.add_argument("--skills-dir", type=Path, action="append", default=[])
    discover.add_argument("--active-tool", action="append", default=[], help="tool confirmed in the current session; repeat as needed")
    discover.add_argument("--active-skill", action="append", default=[], help="skill confirmed in the current session; repeat as needed")
    discover.add_argument("--inventory-complete", action="store_true", help="confirm that supplied active tool/skill lists are complete for this session")
    discover.add_argument("--format", choices=["text", "json"], default="text")
    discover.add_argument("--output", type=Path)
    discover.add_argument("--force", action="store_true")
    discover.add_argument("--dry-run", action="store_true")

    for name, help_text in (("match", "match selected roles to discovered capabilities"), ("optimize", "recommend or apply a team within the seven-person limit")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("manifest", type=Path)
        command.add_argument("--role", action="append", default=[], help="requested specialist role ID; repeat to select more than one")
        command.add_argument("--role-file", type=Path, action="append", default=[], help="custom role profile JSON; repeat as needed")
        command.add_argument("--cwd", type=Path, default=Path.cwd())
        command.add_argument("--skills-dir", type=Path, action="append", default=[])
        command.add_argument("--active-tool", action="append", default=[])
        command.add_argument("--active-skill", action="append", default=[])
        if name == "match":
            command.add_argument("--inventory-complete", action="store_true", help="confirm that supplied active tool/skill lists are complete for this session")
        if name == "optimize":
            command.add_argument("--mode", choices=["quick", "standard", "comprehensive", "custom", "agent_decided"], help="discovery depth; it sets how many automatic roles hybrid selection may add")
            command.add_argument("--selection-mode", choices=["dynamic", "manual", "hybrid"], help="choose an automatic team, a fully user-selected team, or a mix")
        command.add_argument("--apply", action="store_true", help="write the result into the input manifest")
        command.add_argument("--dry-run", action="store_true")
        command.add_argument("--format", choices=["text", "json"], default="text")

    validate = sub.add_parser("validate", help="validate a manifest, role catalogue, or both")
    validate.add_argument("manifest", nargs="?", type=Path)
    validate.add_argument("--catalog-only", action="store_true")
    validate.add_argument("--format", choices=["text", "json"], default="text")

    migrate = sub.add_parser("migrate", help="migrate a supported manifest to the current schema version")
    migrate.add_argument("manifest", type=Path)
    migrate.add_argument("--output", required=True, type=Path, help="new manifest path; the source file is never rewritten")
    migrate.add_argument("--force", action="store_true")
    migrate.add_argument("--dry-run", action="store_true")

    resolve = sub.add_parser("resolve-dependencies", help="apply supervisor-confirmed role prerequisite resolutions")
    resolve.add_argument("manifest", type=Path)
    resolve.add_argument("resolutions", type=Path, help="JSON array of assignment_id, prerequisite, provider_assignment_id, and kind")
    resolve.add_argument("--apply", action="store_true")
    resolve.add_argument("--dry-run", action="store_true")
    resolve.add_argument("--format", choices=["text", "json"], default="json")

    record_verification = sub.add_parser("record-verification", help="record evidence-based verification for discovered capabilities")
    record_verification.add_argument("manifest", type=Path)
    record_verification.add_argument("verifications", type=Path, help="JSON file validated by schemas/capability-verification.schema.json")
    record_verification.add_argument("--apply", action="store_true", help="record the verification results in the manifest")
    record_verification.add_argument("--dry-run", action="store_true")
    record_verification.add_argument("--format", choices=["text", "json"], default="json")

    validate_result = sub.add_parser("validate-result", help="validate an agent result against its assignment and manifest version")
    validate_result.add_argument("manifest", type=Path)
    validate_result.add_argument("result", type=Path)
    validate_result.add_argument("--format", choices=["text", "json"], default="text")

    record_result = sub.add_parser("record-result", help="record a validated result and supervisor review in the manifest")
    record_result.add_argument("manifest", type=Path)
    record_result.add_argument("result", type=Path)
    record_result.add_argument("--review", choices=["pending", "accepted", "rejected", "rework_required"], default="pending")
    record_result.add_argument("--reviewer")
    record_result.add_argument("--review-notes", default="")
    record_result.add_argument("--apply", action="store_true", help="append the result to the manifest execution ledger")
    record_result.add_argument("--dry-run", action="store_true")

    render = sub.add_parser("render", help="generate Markdown and/or offline HTML from a validated manifest")
    render.add_argument("manifest", type=Path)
    render.add_argument("--output-dir", required=True, type=Path)
    render.add_argument("--format", choices=["manifest", "markdown", "html", "both"], default="manifest")
    render.add_argument("--force", action="store_true")
    render.add_argument("--dry-run", action="store_true")

    diff = sub.add_parser("diff", help="compare two manifest versions")
    diff.add_argument("old_manifest", type=Path)
    diff.add_argument("new_manifest", type=Path)
    diff.add_argument("--format", choices=["markdown", "json"], default="markdown")
    diff.add_argument("--output", type=Path)
    diff.add_argument("--force", action="store_true")
    diff.add_argument("--dry-run", action="store_true")

    estimate = sub.add_parser("estimate", help="estimate coordination token usage and optional model cost")
    estimate.add_argument("manifest", type=Path)
    estimate.add_argument("--input-rate-per-million", type=float)
    estimate.add_argument("--output-rate-per-million", type=float)
    estimate.add_argument("--currency")
    estimate.add_argument("--apply", action="store_true")
    estimate.add_argument("--dry-run", action="store_true")

    agents = sub.add_parser("codex-agents", help="generate optional project-scoped Codex agent TOML files")
    agents.add_argument("manifest", type=Path)
    agents.add_argument("--target-dir", required=True, type=Path, help="root of the target project")
    agents.add_argument("--force", action="store_true")
    agents.add_argument("--dry-run", action="store_true")

    return parser


def _json_text(value: Any) -> str:
    return json.dumps(redact_sensitive(value), ensure_ascii=False, indent=2) + "\n"


def _text_report(value: Any) -> str:
    if isinstance(value, dict) and "role_matches" in value:
        lines = [f"Runtime: {value['runtime']['name']} ({value['runtime']['session_availability']} session availability; inventory complete: {str(value['runtime'].get('session_inventory_complete', False)).lower()})", f"Discovered skills: {len(value.get('skills', []))}; agents: {len(value.get('agents', []))}; tools: {len(value.get('tools', []))}"]
        for match in value["role_matches"]:
            verification = match.get("verification", {}).get("status", "unverified")
            lines.append(f"- {match['role_id']}: {match['requirement']} [discovery: {match['status']}; verification: {verification}]")
            lines.extend(f"    {source}" for source in match["evidence"])
        lines.extend(["Gaps:", *(f"- {gap}" for gap in value["gaps"] or ["None reported."])])
        return "\n".join(lines) + "\n"
    if isinstance(value, dict) and "selected_role_ids" in value:
        lines = [f"Mode: {value['mode']}; selection: {value['selection_mode']}", f"Approval required: {str(value['approval_required']).lower()}", "Team: supervisor + " + (", ".join(value["selected_role_ids"]) or "no specialists")]
        lines.extend(f"- {line}" for line in value["rationale"])
        for item in value.get("unresolved_prerequisites", []):
            lines.append(f"- Unresolved prerequisite for {item['assignment_id']}: {item['prerequisite']}")
            if item.get("candidate_providers"):
                candidates = ", ".join(f"{candidate['assignment_id']} ({', '.join(candidate['matched_terms'])})" for candidate in item["candidate_providers"])
                lines.append(f"    Provider hints requiring supervisor confirmation: {candidates}")
        lines.append(f"Estimated orchestration tokens: {value['estimates']['estimated_input_tokens']} input / {value['estimates']['estimated_output_tokens']} output")
        metrics = value["metrics"]
        lines.append(f"Team metrics: independence {metrics['workstream_independence']['score']:.2f}; overlap pairs {metrics['role_overlap']['pair_count']}; research complexity {metrics['research_complexity']['score']:.2f}; integration complexity {metrics['integration_complexity']['score']:.2f}; handoffs {metrics['handoffs']}; review effort {metrics['expected_review_effort_points']:.2f} points")
        if value["approval_required"]:
            lines.append("The requested roster has not been accepted or silently reduced.")
        return "\n".join(lines) + "\n"
    return _json_text(value)


def _emit(value: Any, format_name: str = "json") -> None:
    print(_json_text(value) if format_name == "json" else _text_report(value), end="")


def _load_profiles(role_files: list[Path] | None = None) -> list[dict[str, Any]]:
    source = catalog()
    profiles = list(source["roles"])
    for role_file in role_files or []:
        content = read_json(role_file)
        if isinstance(content, dict) and "role" in content:
            custom = content["role"]
        elif isinstance(content, dict):
            custom = content
        else:
            raise ValueError(f"Custom role file {role_file} must contain a role object")
        catalog_errors = validate_role_catalog({"catalog_version": "custom", "roles": [custom]})
        if catalog_errors:
            raise ValueError(f"Invalid custom role {role_file}: " + "; ".join(catalog_errors))
        if any(existing["id"] == custom["id"] for existing in profiles):
            raise ValueError(f"Custom role ID {custom['id']!r} duplicates a catalogue role")
        profiles.append(custom)
    return profiles


def _load_manifest(path: Path) -> dict[str, Any]:
    manifest = read_json(path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest root must be an object: {path}")
    return manifest


def _load_manifest_snapshot(path: Path) -> tuple[dict[str, Any], str]:
    manifest, manifest_sha256 = read_json_with_sha256(path)
    if not isinstance(manifest, dict):
        raise ValueError(f"Manifest root must be an object: {path}")
    return manifest, manifest_sha256


def _save_manifest(path: Path, manifest: dict[str, Any], *, expected_sha256: str, dry_run: bool = False) -> str:
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        return f"Dry run: would update {path}"
    write_text_if_unchanged(path, content, expected_sha256=expected_sha256)
    return f"Updated {path}"


def _discover_args(args: argparse.Namespace) -> dict[str, Any]:
    return discover_environment(cwd=args.cwd, extra_skill_dirs=args.skills_dir, active_tools=args.active_tool, active_skills=args.active_skill, inventory_complete=getattr(args, "inventory_complete", False))


def _cmd_init(args: argparse.Namespace) -> int:
    manifest = new_manifest(args.name, args.mode)
    errors = validate_manifest(manifest)
    if errors:
        raise RuntimeError("Internal starter manifest is invalid: " + "; ".join(errors))
    write_text(args.output, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", force=args.force, dry_run=args.dry_run)
    print(("Dry run: would create " if args.dry_run else "Created ") + str(args.output))
    return 0


def _cmd_roles(args: argparse.Namespace) -> int:
    profiles = catalog()["roles"]
    if args.category:
        profiles = [role for role in profiles if role["category"] == args.category]
    report = [{"id": role["id"], "category": role["category"], "identity": role["identity"], "mission": role["mission"]} for role in profiles]
    if args.format == "json":
        _emit(report, "json")
    else:
        for role in report:
            print(f"{role['id']} [{role['category']}] — {role['identity']}: {role['mission']}")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    result = classify_project(manifest)
    if args.apply and result["status"] == "recommended":
        manifest["project"]["classification"] = result["classification"]
        manifest["facts"].append({"id": "project-classification", "topic": "Project classification", "value": result["classification"], "status": "recommended", "source": "ProjectForge signal heuristic", "rationale": "; ".join(result["evidence"])})
        manifest["discovery"]["updated_at"] = now_utc()
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Classified manifest is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    elif args.apply and result["status"] in {"ambiguous", "insufficient_evidence"}:
        print("Classification remains pending; review the alternatives and decide with the user.")
    _emit(result, "json")
    return 0


def _cmd_inspect_skill(args: argparse.Namespace) -> int:
    report = inspect_skill(args.name, cwd=args.cwd, extra_skill_dirs=args.skills_dir, max_chars=args.max_chars)
    if args.format == "json":
        _emit(report, "json")
    else:
        print(f"Skill: {report['name']}\nSource: {report['source']}\nTruncated: {str(report['truncated']).lower()}\n\n{report['content']}", end="" if report["content"].endswith("\n") else "\n")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    report = _discover_args(args)
    output = _json_text(report) if args.format == "json" else _text_report({**report, "role_matches": [], "gaps": []})
    if args.output:
        write_text(args.output, output, force=args.force, dry_run=args.dry_run)
        print(("Dry run: would write " if args.dry_run else "Wrote ") + str(args.output))
    else:
        print(output, end="")
    return 0


def _cmd_match(args: argparse.Namespace) -> int:
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    if args.apply and manifest.get("schema_version") != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Applying a capability report requires manifest {CURRENT_MANIFEST_VERSION}; run 'migrate' first")
    profiles = _load_profiles(args.role_file)
    inventory = _discover_args(args)
    report = match_capabilities(manifest, inventory, profiles)
    if args.apply:
        selected_role_ids = {item["role_id"] for item in [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]}
        if manifest["readiness"]["status"] == "ready" and any(
            item["role_id"] in selected_role_ids and item["kind"] == "required" for item in report["role_matches"]
        ):
            manifest["readiness"]["status"] = "needs_input"
            manifest["readiness"]["checked_at"] = now_utc()
            blocker = "Capability discovery was refreshed; required capabilities need verification again."
            if blocker not in manifest["readiness"]["blockers"]:
                manifest["readiness"]["blockers"].append(blocker)
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Capability report update is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    _emit(report, args.format)
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    if args.apply and manifest.get("schema_version") != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Applying team changes requires manifest {CURRENT_MANIFEST_VERSION}; run 'migrate' first")
    profiles = _load_profiles(args.role_file)
    mode = args.mode or manifest["discovery"]["mode"]
    selection_mode = args.selection_mode or ("manual" if args.role else manifest["team"].get("selection_mode", "dynamic"))
    requested_roles = args.role or ([item["role_id"] for item in manifest["team"]["specialists"]] if selection_mode in {"manual", "hybrid"} else None)
    plan = optimize_team(manifest, roles=profiles, mode=mode, requested_roles=requested_roles or None, selection_mode=selection_mode)
    if args.apply and not plan["approval_required"]:
        manifest["discovery"]["mode"] = mode
        manifest["discovery"]["updated_at"] = now_utc()
        team = manifest["team"]
        team["specialists"] = plan["assignments"]
        team["approval_status"] = "proposed"
        team["selection_mode"] = selection_mode
        team["rationale"] = plan["rationale"]
        estimate = plan["estimates"]
        team["optimization"] = {"mode": mode, "coordination_score": estimate["coordination_score"], "estimated_input_tokens": estimate["estimated_input_tokens"], "estimated_output_tokens": estimate["estimated_output_tokens"], "handoffs": estimate["handoffs"], "metrics": plan["metrics"]}
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Optimized manifest is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    _emit(plan, args.format)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    all_errors: list[str] = []
    catalog_errors = validate_role_catalog()
    all_errors.extend(f"role catalogue: {error}" for error in catalog_errors)
    manifest_result = None
    if args.manifest and not args.catalog_only:
        manifest = _load_manifest(args.manifest)
        errors = validate_manifest(manifest)
        all_errors.extend(f"manifest: {error}" for error in errors)
        readiness = manifest.get("readiness", {}) if isinstance(manifest, dict) else {}
        readiness_status = readiness.get("status", "unknown") if isinstance(readiness, dict) else "unknown"
        readiness_items = readiness.get("blockers", []) if isinstance(readiness, dict) else []
        if not isinstance(readiness_items, list):
            readiness_items = []
        if not errors and isinstance(manifest, dict):
            readiness_items = readiness_blockers(manifest)
        elif readiness_status == "ready":
            gate_prefix = "readiness.status cannot be 'ready'"
            readiness_items = list(dict.fromkeys([*readiness_items, *[error for error in errors if error.startswith(gate_prefix)]]))
        manifest_result = {
            "path": str(args.manifest), "valid": not errors, "errors": errors,
            "readiness": {"status": readiness_status, "blockers": readiness_items},
        }
    result = {"valid": not all_errors, "catalog": {"role_count": len(catalog()["roles"]), "valid": not catalog_errors, "errors": catalog_errors}, "manifest": manifest_result, "errors": all_errors}
    if args.format == "json":
        _emit(result, "json")
    elif all_errors:
        print("Validation failed:")
        for error in all_errors:
            print(f"- {error}")
    else:
        print(f"Validation passed. Role profiles: {len(catalog()['roles'])}" + (f"; manifest: {args.manifest}" if args.manifest and not args.catalog_only else ""))
        if manifest_result and manifest_result["readiness"]["blockers"]:
            print(f"Readiness remains {manifest_result['readiness']['status']}; open gates:")
            for blocker in manifest_result["readiness"]["blockers"]:
                print(f"- {blocker}")
    return 0 if not all_errors else 1


def _cmd_migrate(args: argparse.Namespace) -> int:
    source = _load_manifest(args.manifest)
    source_errors = validate_manifest(source)
    if source_errors:
        raise ValueError("Refusing to migrate an invalid source manifest: " + "; ".join(source_errors))
    if args.manifest.expanduser().resolve() == args.output.expanduser().resolve():
        raise ValueError("Migration output must be a different path; the source manifest is preserved")
    migrated = migrate_manifest(source, CURRENT_MANIFEST_VERSION)
    errors = validate_manifest(migrated)
    if errors:
        raise ValueError("Migrated manifest is invalid: " + "; ".join(errors))
    write_text(args.output, json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", force=args.force, dry_run=args.dry_run)
    print(("Dry run: would write " if args.dry_run else "Migrated to ") + str(args.output))
    return 0


def _cmd_resolve_dependencies(args: argparse.Namespace) -> int:
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    if manifest.get("schema_version") != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Dependency resolution requires manifest {CURRENT_MANIFEST_VERSION}; run 'migrate' first")
    resolutions = read_json(args.resolutions)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Dependency resolution requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    resolution_schema = read_json(skill_root() / "schemas" / "dependency-resolution.schema.json")
    Draft202012Validator.check_schema(resolution_schema)
    resolution_errors = list(Draft202012Validator(resolution_schema).iter_errors(resolutions))
    if resolution_errors:
        raise ValueError("Invalid dependency resolutions: " + "; ".join(error.message for error in resolution_errors))
    assignments = [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]
    assignment_map = {item["id"]: item for item in assignments}
    added: list[dict[str, str]] = []
    for index, item in enumerate(resolutions):
        if not isinstance(item, dict):
            raise ValueError(f"Resolution {index} must be an object")
        required = {"assignment_id", "prerequisite", "provider_assignment_id", "kind"}
        if set(item) != required:
            raise ValueError(f"Resolution {index} must contain exactly: {', '.join(sorted(required))}")
        source_id, prerequisite = item["assignment_id"], item["prerequisite"]
        provider_id, kind = item["provider_assignment_id"], item["kind"]
        if source_id not in assignment_map:
            raise ValueError(f"Resolution {index} refers to unknown assignment_id {source_id!r}")
        if provider_id not in assignment_map:
            raise ValueError(f"Resolution {index} refers to unknown provider_assignment_id {provider_id!r}")
        if source_id == provider_id:
            raise ValueError(f"Resolution {index} cannot assign a prerequisite to the same assignment")
        if not isinstance(prerequisite, str) or prerequisite not in assignment_map[source_id].get("prerequisites", []):
            raise ValueError(f"Resolution {index} prerequisite must exactly match one declared by {source_id!r}")
        if kind not in {"blocks", "informs", "reviews"}:
            raise ValueError(f"Resolution {index} kind must be blocks, informs, or reviews")
        prior_mapping = next((current for current in manifest["dependencies"] if current.get("resolution_source") == "role_prerequisite" and current["from"] == source_id and current.get("prerequisite") == prerequisite), None)
        if prior_mapping:
            raise ValueError(f"Prerequisite {prerequisite!r} for {source_id!r} is already mapped to {prior_mapping['to']!r} ({prior_mapping['kind']})")
        edge = {"from": source_id, "to": provider_id, "kind": kind, "prerequisite": prerequisite, "resolution_source": "role_prerequisite"}
        existing = next((current for current in manifest["dependencies"] if (current["from"], current["to"], current["kind"]) == (source_id, provider_id, kind)), None)
        if existing:
            if existing.get("prerequisite"):
                raise ValueError(f"Prerequisite resolution already exists for {source_id!r}: {prerequisite!r}")
            existing.update({"prerequisite": prerequisite, "resolution_source": "role_prerequisite"})
        else:
            manifest["dependencies"].append(edge)
        added.append(edge)
    resolved = {(edge["from"], edge.get("prerequisite")) for edge in manifest["dependencies"] if edge.get("resolution_source") == "role_prerequisite"}
    unresolved = [
        {"assignment_id": assignment["id"], "prerequisite": prerequisite}
        for assignment in assignments
        for prerequisite in assignment.get("prerequisites", [])
        if (assignment["id"], prerequisite) not in resolved
    ]
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Dependency graph is invalid: " + "; ".join(errors))
    if args.apply:
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    report = {"applied": bool(args.apply and not args.dry_run), "added": added, "unresolved": unresolved, "schedule_note": "blocks and reviews edges order assignments; informs edges preserve parallel scheduling"}
    _emit(report, args.format)
    return 0


def _cmd_record_verification(args: argparse.Namespace) -> int:
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ValueError("Manifest is invalid: " + "; ".join(manifest_errors))
    if manifest.get("schema_version") != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Capability verification requires manifest {CURRENT_MANIFEST_VERSION}; run 'migrate' first")

    entries = read_json(args.verifications)
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Capability verification requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    verification_schema = read_json(skill_root() / "schemas" / "capability-verification.schema.json")
    Draft202012Validator.check_schema(verification_schema)
    schema_errors = sorted(Draft202012Validator(verification_schema).iter_errors(entries), key=lambda error: tuple(str(part) for part in error.absolute_path))
    if schema_errors:
        messages = [f"{'.'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}" for error in schema_errors]
        raise ValueError("Invalid capability verification input: " + "; ".join(messages))

    requirement_map = {
        (role["role_id"], requirement["capability"].casefold(), requirement["kind"], requirement.get("requirement_type", "capability"), requirement.get("source", "role_profile")): requirement
        for role in manifest["capability_report"]["role_matches"]
        for requirement in role["requirements"]
    }
    selected_role_ids = {item["role_id"] for item in [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]}
    updated = []
    seen = set()
    for index, entry in enumerate(entries["verifications"]):
        record_errors = verification_errors(entry)
        if record_errors:
            raise ValueError(f"Verification {index} is invalid: " + "; ".join(record_errors))
        key = (entry["role_id"], entry["capability"].casefold(), entry["kind"], entry["requirement_type"], entry["source"])
        if key in seen:
            raise ValueError(f"Verification {index} duplicates an earlier role/capability entry")
        seen.add(key)
        if entry["role_id"] not in selected_role_ids:
            raise ValueError(f"Verification {index} names role {entry['role_id']!r}, which is not assigned in the manifest")
        requirement = requirement_map.get(key)
        if requirement is None:
            raise ValueError(f"Verification {index} does not match a capability requirement in the manifest: {entry['role_id']} / {entry['capability']}")
        status = derive_verification_status(entry["checks"])
        verification = {
            "status": status,
            "discovery_generated_at": manifest["capability_report"]["generated_at"],
            "recorded_at": now_utc(),
            "recorded_by": redact_sensitive(entry["recorded_by"]),
            "checks": redact_sensitive(entry["checks"]),
        }
        requirement["verification"] = verification
        updated.append({"role_id": entry["role_id"], "capability": entry["capability"], "status": status})

    manifest["capability_report"]["gaps"] = [
        f"{role['role_id']}: {'assignment-specific ' if requirement.get('source') == 'assignment' else ''}{requirement['capability']} is discovered as {requirement['status']} and remains {requirement['verification']['status']}"
        for role in manifest["capability_report"]["role_matches"]
        for requirement in role["requirements"]
        if role["role_id"] in selected_role_ids and requirement["kind"] == "required" and requirement["verification"]["status"] != "verified"
    ]
    has_unverified_required = any(
        role["role_id"] in selected_role_ids and requirement["kind"] == "required" and requirement["verification"]["status"] != "verified"
        for role in manifest["capability_report"]["role_matches"]
        for requirement in role["requirements"]
    )
    if manifest["readiness"]["status"] == "ready" and has_unverified_required:
        manifest["readiness"]["status"] = "needs_input"
        manifest["readiness"]["checked_at"] = now_utc()
        blocker = "A required capability needs new verification."
        if blocker not in manifest["readiness"]["blockers"]:
            manifest["readiness"]["blockers"].append(blocker)
    if not has_unverified_required:
        manifest["readiness"]["blockers"] = [
            blocker for blocker in manifest["readiness"]["blockers"]
            if blocker not in _CAPABILITY_VERIFICATION_BLOCKERS
        ]

    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Capability verification update is invalid: " + "; ".join(errors))
    if args.apply:
        message = _save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run)
    else:
        message = "Preview only; pass --apply to record these verification results."
    _emit({"updated": updated, "manifest_write": message}, args.format)
    return 0


def _load_agent_result(manifest_path: Path, result_path: Path) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    manifest, manifest_sha256 = _load_manifest_snapshot(manifest_path)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors:
        raise ValueError("Manifest is invalid: " + "; ".join(manifest_errors))
    if manifest.get("schema_version") != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Agent result protocol requires manifest {CURRENT_MANIFEST_VERSION}; run 'migrate' first")
    result = read_json(result_path)
    if not isinstance(result, dict):
        raise ValueError("Agent result root must be an object")
    relative_result = validate_result_location(result_path, manifest_path)
    recorded = next((item for item in manifest.get("execution", {}).get("results", []) if item["result_file"] == relative_result), None)
    if recorded and recorded["result_sha256"] != result_sha256(result_path):
        raise ValueError(f"Recorded result file {relative_result!r} has changed since it was added to the execution ledger")
    return manifest, result, relative_result, manifest_sha256


def _cmd_validate_result(args: argparse.Namespace) -> int:
    manifest, result, relative_result, _ = _load_agent_result(args.manifest, args.result)
    errors = validate_agent_result(result, manifest)
    ledger = manifest["execution"]["results"]
    if any(item["result_id"] == result.get("result_id") for item in ledger):
        errors.append(f"result_id {result.get('result_id')!r} is already recorded")
    if any(item["result_file"] == relative_result for item in ledger):
        errors.append(f"result file {relative_result!r} is already recorded")
    if any(item["assignment_id"] == result.get("assignment_id") and item["attempt"] == result.get("attempt") for item in ledger):
        errors.append(f"attempt {result.get('attempt')!r} is already recorded for assignment {result.get('assignment_id')!r}")
    report = {"valid": not errors, "result_id": result.get("result_id"), "assignment_id": result.get("assignment_id"), "errors": errors}
    if args.format == "json":
        _emit(report, "json")
    else:
        print("Agent result is valid." if not errors else "Agent result validation failed:")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


def _cmd_record_result(args: argparse.Namespace) -> int:
    manifest, result, relative_result, manifest_sha256 = _load_agent_result(args.manifest, args.result)
    if args.review != "pending" and not args.reviewer:
        raise ValueError("Provide --reviewer for accepted, rejected, or rework_required decisions")
    errors = validate_agent_result(result, manifest, args.review)
    ledger = manifest["execution"]["results"]
    by_id = next((item for item in ledger if item["result_id"] == result.get("result_id")), None)
    by_path = next((item for item in ledger if item["result_file"] == relative_result), None)
    if by_id is not by_path and (by_id is not None or by_path is not None):
        errors.append("result ID or result file is already associated with a different ledger entry")
    existing = by_id or by_path
    if existing:
        if existing["review_status"] != "pending":
            errors.append("a recorded supervisor decision is final; submit a new result attempt for rework")
        elif args.review == "pending":
            errors.append("this result is already pending review; provide a supervisor decision to update it")
    assignment_id = result.get("assignment_id")
    if not existing and any(item["assignment_id"] == assignment_id and item["attempt"] == result.get("attempt") for item in ledger):
        errors.append("an assignment may have only one immutable result file per attempt")
    if args.review == "accepted" and not errors:
        root = args.manifest.resolve().parent
        for output in result["outputs"]:
            candidate = (root / output["path"]).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                errors.append(f"output {output['path']!r} resolves outside the manifest directory")
                continue
            if not candidate.exists():
                errors.append(f"accepted output {output['path']!r} does not exist")
    if errors:
        raise ValueError("Agent result cannot be recorded: " + "; ".join(errors))
    if existing:
        existing.update({"review_status": args.review, "reviewed_at": now_utc(), "reviewer": args.reviewer})
        if args.review_notes:
            existing["review_notes"] = args.review_notes
        action = "review"
    else:
        manifest["execution"]["results"].append({
            "result_id": result["result_id"], "assignment_id": assignment_id,
            "manifest_version": result["manifest_version"], "status": result["status"],
            "attempt": result["attempt"], "prior_result_id": result["prior_result_id"],
            "result_file": relative_result, "result_sha256": result_sha256(args.result),
            "review_status": args.review, "created_at": result["created_at"],
            **({"reviewed_at": now_utc()} if args.review != "pending" else {}),
            **({"reviewer": args.reviewer} if args.reviewer else {}),
            **({"review_notes": args.review_notes} if args.review_notes else {}),
        })
        action = "append"
    manifest["discovery"]["updated_at"] = now_utc()
    validation_errors = validate_manifest(manifest)
    if validation_errors:
        raise ValueError("Updated manifest is invalid: " + "; ".join(validation_errors))
    if args.apply:
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    else:
        print(f"Dry run: result is valid and would {action} the execution ledger; pass --apply to record it.")
    _emit({"result_id": result["result_id"], "assignment_id": assignment_id, "status": result["status"], "review_status": args.review, "action": action, "recorded": bool(args.apply and not args.dry_run)}, "json")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Refusing to render invalid manifest: " + "; ".join(errors))
    selected = manifest["output_preferences"]["formats"] if args.format == "manifest" else (["markdown", "html"] if args.format == "both" else [args.format])
    outputs = {}
    if "markdown" in selected:
        outputs[args.output_dir / f"{manifest['project']['id']}-kickoff.md"] = render_markdown(manifest)
    if "html" in selected:
        outputs[args.output_dir / f"{manifest['project']['id']}-kickoff.html"] = render_html(manifest)
    existing = [str(path) for path in outputs if path.exists() and not args.force]
    if existing:
        raise FileExistsError("Refusing to overwrite existing output(s): " + ", ".join(existing) + " (pass --force to replace)")
    for path, content in outputs.items():
        write_text(path, content, force=args.force, dry_run=args.dry_run)
    verb = "Would generate" if args.dry_run else "Generated"
    print(verb + ": " + ", ".join(str(path) for path in outputs))
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    report = compare_manifests(_load_manifest(args.old_manifest), _load_manifest(args.new_manifest))
    output = _json_text(report) if args.format == "json" else diff_markdown(report)
    if args.output:
        write_text(args.output, output, force=args.force, dry_run=args.dry_run)
        print(("Dry run: would write " if args.dry_run else "Wrote ") + str(args.output))
    else:
        print(output, end="")
    return 0


def _cmd_estimate(args: argparse.Namespace) -> int:
    if (args.input_rate_per_million is None) != (args.output_rate_per_million is None):
        raise ValueError("Provide both --input-rate-per-million and --output-rate-per-million, or neither")
    if args.input_rate_per_million is not None and (args.input_rate_per_million < 0 or args.output_rate_per_million < 0):
        raise ValueError("Token rates must be zero or greater")
    if args.input_rate_per_million is not None and not args.currency:
        raise ValueError("Provide --currency when supplying token rates")
    currency = args.currency or "UNSPECIFIED"
    manifest, manifest_sha256 = _load_manifest_snapshot(args.manifest)
    specialists = len(manifest["team"]["specialists"])
    handoffs = manifest["team"]["optimization"]["handoffs"]
    complexity = len(manifest["features"]) + len(manifest["architecture"]["components"])
    estimate = _estimate(specialists, handoffs, complexity)
    amount = None
    if args.input_rate_per_million is not None:
        amount = estimate["estimated_input_tokens"] * args.input_rate_per_million / 1_000_000 + estimate["estimated_output_tokens"] * args.output_rate_per_million / 1_000_000
    result = {"project_id": manifest["project"]["id"], **estimate, "currency": currency, "estimated_model_cost": round(amount, 6) if amount is not None else None, "cost_basis": "Uses caller-supplied per-million token rates." if amount is not None else "No current provider rate supplied; cost amount is unknown."}
    if args.apply:
        manifest["cost_estimate"]["token_estimate"] = {"input": estimate["estimated_input_tokens"], "output": estimate["estimated_output_tokens"], "method": estimate["method"]}
        manifest["cost_estimate"]["currency"] = currency
        manifest["cost_estimate"]["confidence"] = "low" if amount is None else "medium"
        other_items = [item for item in manifest["cost_estimate"]["items"] if item["label"] != "Estimated model usage"]
        if amount is not None:
            other_items.append({"label": "Estimated model usage", "amount": result["estimated_model_cost"], "basis": result["cost_basis"]})
        manifest["cost_estimate"]["items"] = other_items
        manifest["cost_estimate"]["total_amount"] = sum(item["amount"] for item in other_items) if other_items and all(item["amount"] is not None for item in other_items) else None
        manifest["cost_estimate"]["assumptions"] = list(dict.fromkeys([*manifest["cost_estimate"]["assumptions"], estimate["method"], result["cost_basis"]]))
        manifest["discovery"]["updated_at"] = now_utc()
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Updated manifest is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, expected_sha256=manifest_sha256, dry_run=args.dry_run))
    _emit(result, "json")
    return 0


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _cmd_codex_agents(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Refusing to generate agents from invalid manifest: " + "; ".join(errors))
    if not manifest["team"]["specialists"]:
        raise ValueError("No specialist assignments are selected in the manifest")
    output_dir = args.target_dir / ".codex" / "agents"
    template = (skill_root() / "templates" / "codex-agent.toml.tpl").read_text(encoding="utf-8")
    outputs: dict[Path, str] = {}
    for assignment in manifest["team"]["specialists"]:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", assignment["role_id"]):
            raise ValueError(f"Unsafe Codex agent filename derived from role ID {assignment['role_id']!r}")
        result_contract = assignment.get("result_contract", {})
        instructions = [assignment["mission"], "", "Responsibilities:", *[f"- {item}" for item in assignment["responsibilities"]], "", "Exclusions:", *[f"- {item}" for item in assignment["exclusions"]], "", "Inputs:", *[f"- {item}" for item in assignment["inputs"]], "", "Outputs:", *[f"- {item}" for item in assignment["outputs"]], "", "Dependencies:", *[f"- {item}" for item in assignment["dependencies"]], "", "Acceptance criteria:", *[f"- {item}" for item in assignment["acceptance_criteria"]], "", "Handoff requirements:", *[f"- {item}" for item in assignment["handoff_requirements"]], "", "Provider-neutral result contract (schemas/agent-result.schema.json):", f"- Protocol version: {result_contract.get('protocol_version', '1.0.0')}", f"- Expected output: {result_contract.get('expected_output_format', 'JSON result')}", f"- Allowed paths: {', '.join(result_contract.get('allowed_paths', [])) or 'none; return findings without writing files'}", f"- Protected paths: {', '.join(result_contract.get('protected_paths', [])) or 'none listed'}", f"- Required checks: {', '.join(result_contract.get('required_checks', [])) or 'none specified'}", "- Return a distinct result_id and attempt number. Preserve failures and link retries to the preceding rejected or rework-required result.", "- Report evidence and actual check outcomes. Do not claim validation that was not performed, or supervisor acceptance.", "", "Required capabilities:", *[f"- {item}" for item in assignment["required_capabilities"]], "", "Supporting skill categories:", *[f"- {item}" for item in assignment["supporting_skills"]], "", "Use only capabilities verified in the active session. Do not claim a capability or research result without evidence. These instructions do not change the parent session permissions or authorization."]
        mapping = {"name": _toml_string(assignment["role_id"]), "description": _toml_string(assignment["mission"]), "developer_instructions": _toml_string("\n".join(instructions))}
        content = re.sub(r"\{\{(\w+)\}\}", lambda match: mapping.get(match.group(1), ""), template)
        outputs[output_dir / f"{assignment['role_id']}.toml"] = content
    existing = [str(path) for path in outputs if path.exists() and not args.force]
    if existing:
        raise FileExistsError("Refusing to overwrite existing agent file(s): " + ", ".join(existing) + " (pass --force to replace)")
    for path, content in outputs.items():
        write_text(path, content, force=args.force, dry_run=args.dry_run)
    print(("Dry run: would create" if args.dry_run else "Created") + " project-scoped Codex agent definitions:")
    for path in outputs:
        print("- " + str(path))
    print("These files do not spawn agents, grant tools, or change parent permissions.")
    return 0


COMMANDS = {"init": _cmd_init, "roles": _cmd_roles, "classify": _cmd_classify, "inspect-skill": _cmd_inspect_skill, "discover": _cmd_discover, "match": _cmd_match, "optimize": _cmd_optimize, "validate": _cmd_validate, "migrate": _cmd_migrate, "resolve-dependencies": _cmd_resolve_dependencies, "record-verification": _cmd_record_verification, "validate-result": _cmd_validate_result, "record-result": _cmd_record_result, "render": _cmd_render, "diff": _cmd_diff, "estimate": _cmd_estimate, "codex-agents": _cmd_codex_agents}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (ValueError, FileExistsError, RuntimeError, OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"projectforge: error: {exc}", file=sys.stderr)
        return 2
