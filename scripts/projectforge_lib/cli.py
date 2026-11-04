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
from .common import catalog, new_manifest, now_utc, read_json, skill_root, write_text
from .discovery import discover_environment, inspect_skill, match_capabilities
from .optimization import _estimate, optimize_team
from .rendering import render_html, render_markdown
from .security import redact_sensitive
from .validation import validate_manifest, validate_role_catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="projectforge", description="Discover capabilities, plan a small specialist team, validate a project manifest, and generate kickoff documents.")
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
            lines.append(f"- {match['role_id']}: {match['requirement']} [{match['status']}]")
            lines.extend(f"    {source}" for source in match["evidence"])
        lines.extend(["Gaps:", *(f"- {gap}" for gap in value["gaps"] or ["None reported."])])
        return "\n".join(lines) + "\n"
    if isinstance(value, dict) and "selected_role_ids" in value:
        lines = [f"Mode: {value['mode']}; selection: {value['selection_mode']}", f"Approval required: {str(value['approval_required']).lower()}", "Team: supervisor + " + (", ".join(value["selected_role_ids"]) or "no specialists")]
        lines.extend(f"- {line}" for line in value["rationale"])
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


def _save_manifest(path: Path, manifest: dict[str, Any], *, dry_run: bool = False) -> str:
    content = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        return f"Dry run: would update {path}"
    write_text(path, content, force=True)
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
    manifest = _load_manifest(args.manifest)
    result = classify_project(manifest)
    if args.apply and result["status"] == "recommended":
        manifest["project"]["classification"] = result["classification"]
        manifest["facts"].append({"id": "project-classification", "topic": "Project classification", "value": result["classification"], "status": "recommended", "source": "ProjectForge signal heuristic", "rationale": "; ".join(result["evidence"])})
        manifest["discovery"]["updated_at"] = now_utc()
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Classified manifest is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, dry_run=args.dry_run))
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
    manifest = _load_manifest(args.manifest)
    profiles = _load_profiles(args.role_file)
    inventory = _discover_args(args)
    report = match_capabilities(manifest, inventory, profiles)
    if args.apply:
        errors = validate_manifest(manifest)
        if errors:
            raise ValueError("Capability report update is invalid: " + "; ".join(errors))
        print(_save_manifest(args.manifest, manifest, dry_run=args.dry_run))
    _emit(report, args.format)
    return 0


def _cmd_optimize(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.manifest)
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
        print(_save_manifest(args.manifest, manifest, dry_run=args.dry_run))
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
        manifest_result = {"path": str(args.manifest), "valid": not errors, "errors": errors}
    result = {"valid": not all_errors, "catalog": {"role_count": len(catalog()["roles"]), "valid": not catalog_errors, "errors": catalog_errors}, "manifest": manifest_result, "errors": all_errors}
    if args.format == "json":
        _emit(result, "json")
    elif all_errors:
        print("Validation failed:")
        for error in all_errors:
            print(f"- {error}")
    else:
        print(f"Validation passed. Role profiles: {len(catalog()['roles'])}" + (f"; manifest: {args.manifest}" if args.manifest and not args.catalog_only else ""))
    return 0 if not all_errors else 1


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
    manifest = _load_manifest(args.manifest)
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
        print(_save_manifest(args.manifest, manifest, dry_run=args.dry_run))
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
        instructions = [assignment["mission"], "", "Responsibilities:", *[f"- {item}" for item in assignment["responsibilities"]], "", "Exclusions:", *[f"- {item}" for item in assignment["exclusions"]], "", "Inputs:", *[f"- {item}" for item in assignment["inputs"]], "", "Outputs:", *[f"- {item}" for item in assignment["outputs"]], "", "Dependencies:", *[f"- {item}" for item in assignment["dependencies"]], "", "Acceptance criteria:", *[f"- {item}" for item in assignment["acceptance_criteria"]], "", "Handoff requirements:", *[f"- {item}" for item in assignment["handoff_requirements"]], "", "Required capabilities:", *[f"- {item}" for item in assignment["required_capabilities"]], "", "Supporting skill categories:", *[f"- {item}" for item in assignment["supporting_skills"]], "", "Use only capabilities verified in the active session. Do not claim a capability or research result without evidence. These instructions do not change the parent session permissions or authorization."]
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


COMMANDS = {"init": _cmd_init, "roles": _cmd_roles, "classify": _cmd_classify, "inspect-skill": _cmd_inspect_skill, "discover": _cmd_discover, "match": _cmd_match, "optimize": _cmd_optimize, "validate": _cmd_validate, "render": _cmd_render, "diff": _cmd_diff, "estimate": _cmd_estimate, "codex-agents": _cmd_codex_agents}


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (ValueError, FileExistsError, RuntimeError, OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f"projectforge: error: {exc}", file=sys.stderr)
        return 2
