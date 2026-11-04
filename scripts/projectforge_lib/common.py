from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "project")[:63].rstrip("-")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc
    except OSError as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def write_text(path: Path, content: str, *, force: bool = False, dry_run: bool = False) -> bool:
    path = path.expanduser()
    if path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing file: {path} (pass --force to replace it)")
    if dry_run:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as temp:
            temp.write(content)
            temp.flush()
            os.fsync(temp.fileno())
            temp_name = temp.name
        if path.exists() and not force:
            raise FileExistsError(f"Refusing to overwrite existing file: {path} (pass --force to replace it)")
        os.replace(temp_name, path)
        return True
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def catalog() -> dict[str, Any]:
    return read_json(skill_root() / "references" / "roles.json")


def role_map() -> dict[str, dict[str, Any]]:
    return {role["id"]: role for role in catalog()["roles"]}


def new_assignment(role: dict[str, Any], assignment_id: str | None = None) -> dict[str, Any]:
    return {
        "id": assignment_id or role["id"],
        "role_id": role["id"],
        "name": role["identity"],
        "mission": role["mission"],
        "responsibilities": list(role["responsibilities"]),
        "exclusions": list(role["exclusions"]),
        "inputs": [
            "Accepted project manifest and relevant repository evidence",
            *[f"Prerequisite: {item}" for item in role["dependencies"]],
        ],
        "outputs": list(role["deliverables"]),
        "dependencies": [],
        "acceptance_criteria": list(role["acceptance_criteria"]),
        "handoff_requirements": list(role["collaboration_requirements"]),
        "required_capabilities": list(role["required_capabilities"]),
        "supporting_skills": list(role["supporting_skill_categories"]),
    }


def new_manifest(name: str, mode: str = "agent_decided") -> dict[str, Any]:
    stamp = now_utc()
    project_id = slugify(name)
    supervisor = role_map()["supervisor"]
    return {
        "schema_version": "1.0.0",
        "project": {
            "id": project_id,
            "name": name,
            "summary": "",
            "problem_statement": "",
            "target_audience": [],
            "goals": [],
            "classification": "pending",
            "platforms": [],
            "identifiers": [],
            "scope": {"included": [], "excluded": []},
            "existing_repository": {"path": None, "inspected": False, "observations": []},
        },
        "discovery": {"mode": mode, "started_at": stamp, "updated_at": stamp, "notes": []},
        "facts": [],
        "technology": {"preferences": [], "selected": [], "alternatives": [], "compatibility_evidence": []},
        "features": [],
        "architecture": {"summary": "", "components": [], "flows": []},
        "data_api": {"datastores": [], "apis": [], "authentication": [], "decisions": []},
        "constraints": {"security_privacy": [], "offline": "", "monetization": "", "performance": [], "accessibility": [], "localization": [], "deployment": [], "budget": ""},
        "capability_report": {"generated_at": stamp, "runtime": {"name": "unknown", "detected": False, "version": None, "session_availability": "unverified", "session_inventory_complete": False, "evidence": []}, "skills": [], "agents": [], "tools": [], "role_matches": [], "gaps": []},
        "team": {
            "approval_status": "proposed", "selection_mode": "dynamic", "supervisor": new_assignment(supervisor),
            "specialists": [], "rationale": [], "optimization": {
                "mode": mode, "coordination_score": 0.0, "estimated_input_tokens": 0,
                "estimated_output_tokens": 0, "handoffs": 0,
                "metrics": {
                    "role_relevance": [], "role_overlap": {"pair_count": 0, "pairs": []},
                    "workstream_independence": {"score": 1.0, "basis": "No specialist pairs exist to overlap."},
                    "coordination_overhead": {"score": 0.0, "handoffs": 0, "basis": "No team plan has been estimated."},
                    "context_requirements": {"estimated_input_tokens": 0, "project_complexity_units": 0, "per_role": [], "basis": "No team plan has been estimated."},
                    "research_complexity": {"score": 0.0, "research_method_count": 0, "basis": "No team plan has been estimated."},
                    "integration_complexity": {"score": 0.0, "basis": "No team plan has been estimated."},
                    "handoffs": 0, "expected_review_effort_points": 0.0,
                    "review_effort_basis": "No team plan has been estimated.",
                },
            },
        },
        "dependencies": [],
        "deliverables": [],
        "milestones": [],
        "risks": [],
        "assumptions": [],
        "decisions": [],
        "cost_estimate": {"currency": "UNSPECIFIED", "total_amount": None, "confidence": "unknown", "items": [], "token_estimate": {"input": 0, "output": 0, "method": "Not estimated."}, "assumptions": []},
        "output_preferences": {"formats": ["markdown", "html"], "include_architecture_diagram": True, "include_team_contracts": True},
        "readiness": {"status": "draft", "blockers": ["Project discovery has not been completed."], "checked_at": stamp},
        "change_log": [],
        "extensions": {},
    }
