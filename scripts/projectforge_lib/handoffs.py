from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from .common import read_json, skill_root


def _schema_errors(result: dict[str, Any]) -> list[str]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError("Agent result validation requires jsonschema. Install it with: python3 -m pip install -r projectforge/requirements.txt") from exc
    schema = read_json(skill_root() / "schemas" / "agent-result.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = []
    for error in sorted(Draft202012Validator(schema).iter_errors(result), key=lambda item: tuple(str(part) for part in item.absolute_path)):
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"{path}: {error.message}")
    return errors


def _path_matches(path: str, rule: str) -> bool:
    normalized_rule = rule.rstrip("/")
    return path == normalized_rule or (rule.endswith("/") and path.startswith(normalized_rule + "/"))


def validate_agent_result(result: dict[str, Any], manifest: dict[str, Any], review_status: str = "pending") -> list[str]:
    errors = _schema_errors(result)
    if errors:
        return errors

    if result["manifest_version"] != manifest.get("schema_version"):
        errors.append(f"result manifest_version {result['manifest_version']!r} does not match manifest schema_version {manifest.get('schema_version')!r}")
    assignments = [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]
    assignment = next((item for item in assignments if item["id"] == result["assignment_id"]), None)
    if assignment is None:
        errors.append(f"result refers to unknown assignment_id {result['assignment_id']!r}")
        return errors

    contract = assignment.get("result_contract", {})
    ledger = manifest.get("execution", {}).get("results", [])
    prior_id = result.get("prior_result_id")
    if result["attempt"] == 1 and prior_id is not None:
        errors.append("attempt 1 must have prior_result_id=null")
    if result["attempt"] > 1:
        prior = next((item for item in ledger if item["result_id"] == prior_id), None)
        if prior is None or prior["assignment_id"] != result["assignment_id"] or result["attempt"] != prior["attempt"] + 1:
            errors.append("a retry must reference the immediately preceding recorded attempt for the same assignment")
        elif prior["review_status"] not in {"rejected", "rework_required"}:
            errors.append("retry is allowed only after the previous attempt was rejected or marked rework_required")
    allowed_paths = contract.get("allowed_paths", [])
    protected_paths = contract.get("protected_paths", [])
    output_paths: set[str] = set()
    for output in result["outputs"]:
        raw_path = output["path"]
        path = PurePosixPath(raw_path)
        has_windows_drive = len(raw_path) > 1 and raw_path[0].isalpha() and raw_path[1] == ":"
        if "\\" in raw_path or has_windows_drive or path.is_absolute() or ".." in path.parts or "." in path.parts or raw_path != path.as_posix() or path.as_posix() in {"", "."}:
            errors.append(f"output path {raw_path!r} must be a normalized relative POSIX path")
            continue
        normalized = path.as_posix()
        if normalized in output_paths:
            errors.append(f"duplicate output path {normalized!r}")
        output_paths.add(normalized)
        if not allowed_paths or not any(_path_matches(normalized, rule) for rule in allowed_paths):
            errors.append(f"output path {normalized!r} is not in assignment.result_contract.allowed_paths")
        if any(_path_matches(normalized, rule) for rule in protected_paths):
            errors.append(f"output path {normalized!r} overlaps a protected path")

    check_statuses = {item["name"].casefold(): item["status"] for item in result["validation"]["checks"]}
    if len(check_statuses) != len(result["validation"]["checks"]):
        errors.append("validation.checks contains duplicate check names")
    for check in result["validation"]["checks"]:
        if check["status"] == "passed" and not check["evidence"]:
            errors.append(f"passed validation check {check['name']!r} must include evidence")
    if len(check_statuses) != len(result["validation"]["checks"]):
        errors.append("validation.checks contains duplicate check names")
    for check in result["validation"]["checks"]:
        if check["status"] == "passed" and not check["evidence"]:
            errors.append(f"passed validation check {check['name']!r} must include evidence")
    if result["validation"]["passed"] and (not result["validation"]["checks"] or any(status != "passed" for status in check_statuses.values())):
        errors.append("validation.passed cannot be true unless at least one check is recorded and every recorded check passed")
    if result["status"] == "validated" and not result["validation"]["passed"]:
        errors.append("status 'validated' requires validation.passed=true")
    for required_check in contract.get("required_checks", []):
        if check_statuses.get(required_check.casefold()) != "passed":
            errors.append(f"required validation check {required_check!r} must be reported as passed")
    if review_status == "accepted":
        if result["status"] not in {"completed", "validated"}:
            errors.append("only a completed or validated result can be accepted")
        if not result["validation"]["passed"]:
            errors.append("a result can be accepted only after required validation checks pass")
    return errors


def validate_result_location(result_path: Path, manifest_path: Path) -> str:
    base = manifest_path.resolve().parent
    resolved = result_path.expanduser().resolve(strict=True)
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError("Result files must be stored inside the manifest directory so retries and evidence remain project-scoped") from exc
    if not resolved.is_file():
        raise ValueError(f"Result path is not a file: {result_path}")
    return relative.as_posix()


def result_sha256(result_path: Path) -> str:
    return hashlib.sha256(result_path.expanduser().resolve(strict=True).read_bytes()).hexdigest()
