from __future__ import annotations

from copy import deepcopy
from typing import Any


CURRENT_MANIFEST_VERSION = "1.1.0"


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


MIGRATIONS = {"1.0.0": _migrate_1_0_0_to_1_1_0}
SUPPORTED_MANIFEST_VERSIONS = {"1.0.0", CURRENT_MANIFEST_VERSION}


def migrate_manifest(manifest: dict[str, Any], target_version: str = CURRENT_MANIFEST_VERSION) -> dict[str, Any]:
    source_version = manifest.get("schema_version")
    if source_version not in SUPPORTED_MANIFEST_VERSIONS:
        raise ValueError(f"Unsupported manifest schema_version {source_version!r}; supported versions: {', '.join(sorted(SUPPORTED_MANIFEST_VERSIONS))}")
    if target_version != CURRENT_MANIFEST_VERSION:
        raise ValueError(f"Unsupported migration target {target_version!r}; current target is {CURRENT_MANIFEST_VERSION}")
    if source_version == target_version:
        return deepcopy(manifest)
    migration = MIGRATIONS.get(source_version)
    if migration is None:
        raise ValueError(f"No migration path from manifest schema_version {source_version!r} to {target_version!r}")
    return migration(manifest)
