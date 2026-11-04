from __future__ import annotations

from typing import Any


CHECK_NAMES = ("accessibility", "instructions", "operation", "permissions", "expected_output")
CHECK_STATUSES = {"confirmed", "partial", "unconfirmed", "unavailable", "unsupported", "not_applicable"}


def empty_verification(discovery_generated_at: str | None = None) -> dict[str, Any]:
    return {
        "status": "unverified",
        "discovery_generated_at": discovery_generated_at,
        "recorded_at": None,
        "recorded_by": None,
        "checks": {
            name: {"status": "unconfirmed", "evidence": []}
            for name in CHECK_NAMES
        },
    }


def derive_verification_status(checks: dict[str, Any]) -> str:
    access_status = checks["accessibility"]["status"]
    permission_status = checks["permissions"]["status"]
    if access_status == "unavailable" or permission_status == "unavailable":
        return "unavailable"

    optional_checks = {"instructions", "permissions"}
    if access_status == "confirmed" and all(
        checks[name]["status"] == "confirmed" or (name in optional_checks and checks[name]["status"] == "not_applicable")
        for name in CHECK_NAMES
    ):
        return "verified"

    positive_statuses = {"confirmed", "partial", "unsupported"}
    if any(checks[name]["status"] in positive_statuses for name in CHECK_NAMES):
        return "partially_verified"
    return "unverified"


def verification_errors(record: dict[str, Any], *, require_recorded: bool = True) -> list[str]:
    errors: list[str] = []
    checks = record.get("checks")
    if not isinstance(checks, dict):
        return ["verification checks must be an object"]
    if set(checks) != set(CHECK_NAMES):
        return ["verification checks must include accessibility, instructions, operation, permissions, and expected_output"]

    for name in CHECK_NAMES:
        check = checks[name]
        if not isinstance(check, dict):
            errors.append(f"verification check {name} must be an object")
            continue
        status = check.get("status")
        evidence = check.get("evidence", [])
        if status not in CHECK_STATUSES:
            errors.append(f"verification check {name} has unsupported status {status!r}")
            continue
        if name == "accessibility" and status not in {"confirmed", "unconfirmed", "unavailable"}:
            errors.append("accessibility status must be confirmed, unconfirmed, or unavailable")
        if name == "instructions" and status not in {"confirmed", "partial", "unconfirmed", "not_applicable"}:
            errors.append("instructions status must be confirmed, partial, unconfirmed, or not_applicable")
        if name == "operation" and status not in {"confirmed", "partial", "unconfirmed", "unsupported"}:
            errors.append("operation status must be confirmed, partial, unconfirmed, or unsupported")
        if name == "permissions" and status not in {"confirmed", "partial", "unconfirmed", "unavailable", "not_applicable"}:
            errors.append("permissions status must be confirmed, partial, unconfirmed, unavailable, or not_applicable")
        if name == "expected_output" and status not in {"confirmed", "partial", "unconfirmed"}:
            errors.append("expected_output status must be confirmed, partial, or unconfirmed")
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            errors.append(f"verification check {name} evidence must be a list of strings")
        elif status != "unconfirmed" and not any(item.strip() for item in evidence):
            errors.append(f"verification check {name} status {status!r} requires evidence")

    if require_recorded:
        if not isinstance(record.get("recorded_by"), str) or not record["recorded_by"].strip():
            errors.append("verification must name who recorded the checks")
    return errors
