from __future__ import annotations

from copy import deepcopy
from typing import Any


CURRENT_MANIFEST_VERSION = "1.3.0"


def _migrate_1_0_0_to_1_1_0(manifest: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(manifest)
    for assignment in [migrated["team"]["supervisor"], *migrated["team"]["specialists"]]:
        assignment["prerequisites"] = [
            item.removeprefix("Prerequisite: ")
            for item in assignment.get("inputs", [])
            if item.startswith("Prerequisite: ")
        ]
        assignment["result_contract"] = {
            "protocol_version": "1.0.0",
            "expected_output_format": "provider-neutral JSON result with explicitly authorized artifacts",
            "allowed_paths": [],
            "protected_paths": [],
            "required_checks": [],
            "completion_criteria": list(assignment.get("acceptance_criteria", [])) or ["Supervisor confirms the stated deliverables."],
        }
    migrated["execution"] = {"protocol_version": "1.0.0", "results": []}
    migrated["schema_version"] = "1.1.0"
    return migrated


def _migrate_1_1_0_to_1_2_0(manifest: dict[str, Any]) -> dict[str, Any]:
    from .verification import empty_verification

    migrated = deepcopy(manifest)
    discovery_generated_at = migrated["capability_report"].get("generated_at")
    for role in migrated["capability_report"].get("role_matches", []):
        for requirement in role.get("requirements", []):
            requirement["verification"] = empty_verification(discovery_generated_at)
    selected_role_ids = {
        assignment["role_id"]
        for assignment in [migrated["team"]["supervisor"], *migrated["team"]["specialists"]]
    }
    migrated["capability_report"]["gaps"] = [
        f"{role['role_id']}: {'assignment-specific ' if requirement.get('source') == 'assignment' else ''}{requirement['capability']} is discovered as {requirement['status']} and remains unverified"
        for role in migrated["capability_report"].get("role_matches", [])
        for requirement in role.get("requirements", [])
        if role["role_id"] in selected_role_ids and requirement["kind"] == "required"
    ]
    has_required_capabilities = any(
        requirement.get("kind") == "required"
        for role in migrated["capability_report"].get("role_matches", [])
        if role["role_id"] in selected_role_ids
        for requirement in role.get("requirements", [])
    )
    if migrated.get("readiness", {}).get("status") == "ready" and has_required_capabilities:
        migrated["readiness"]["status"] = "needs_input"
        blockers = migrated["readiness"].setdefault("blockers", [])
        blockers.append("Required capabilities must be verified against the active runtime.")
    migrated["schema_version"] = "1.2.0"
    return migrated


def _migrate_1_2_0_to_1_3_0(manifest: dict[str, Any]) -> dict[str, Any]:
    migrated = deepcopy(manifest)
    migrated["execution"].setdefault("events", [])
    migrated["schema_version"] = "1.3.0"
    return migrated


MIGRATIONS = {
    "1.0.0": _migrate_1_0_0_to_1_1_0,
    "1.1.0": _migrate_1_1_0_to_1_2_0,
    "1.2.0": _migrate_1_2_0_to_1_3_0,
}
SUPPORTED_MANIFEST_VERSIONS = {"1.0.0", "1.1.0", "1.2.0", CURRENT_MANIFEST_VERSION}


def migrate_manifest(manifest: dict[str, Any], target_version: str = CURRENT_MANIFEST_VERSION) -> dict[str, Any]:
    source_version = manifest.get("schema_version")
    if source_version not in SUPPORTED_MANIFEST_VERSIONS:
        raise ValueError(f"Unsupported manifest schema_version {source_version!r}; supported versions: {', '.join(sorted(SUPPORTED_MANIFEST_VERSIONS))}")
    if target_version != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Unsupported migration target {target_version!r}; current target is {CURRENT_MANIFEST_VERSION}")
    if source_version == target_version:
        return deepcopy(manifest)
    migrated = deepcopy(manifest)
    while migrated.get("schema_version") != target_version:
        source = migrated.get("schema_version")
        migration = MIGRATIONS.get(source)
        if migration is None:
            raise ValueError(f"No migration path from manifest schema_version {source!r} to {target_version!r}")
        migrated = migration(migrated)
    return migrated
