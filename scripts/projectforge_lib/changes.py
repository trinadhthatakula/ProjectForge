from __future__ import annotations

import json
from typing import Any

from .security import redact_sensitive


IGNORED_PATHS = {"discovery.started_at", "discovery.updated_at", "capability_report.generated_at", "readiness.checked_at"}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key in sorted(value):
            path = f"{prefix}.{key}" if prefix else key
            result.update(_flatten(value[key], path))
    elif isinstance(value, list):
        # Arrays are atomic for change review: reordering a team or roadmap is meaningful.
        result[prefix] = value
    else:
        result[prefix] = value
    return result


def compare_manifests(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    before, after = _flatten(old), _flatten(new)
    changes = []
    for path in sorted(set(before) | set(after)):
        if path in IGNORED_PATHS:
            continue
        if before.get(path, object()) == after.get(path, object()):
            continue
        parts = path.split(".")
        category = parts[0]
        changes.append({"path": path, "category": category, "old": redact_sensitive(before.get(path, "<not present>")), "new": redact_sensitive(after.get(path, "<not present>"))})
    categories = sorted({item["category"] for item in changes})
    return {
        "project_id": new.get("project", {}).get("id") or old.get("project", {}).get("id"),
        "change_count": len(changes),
        "affected_areas": categories,
        "changes": changes,
        "impact_review": [
            "Review scope, architecture, cost, staffing, schedule, risk, and acceptance impacts for the changed areas.",
            "Update the accepted manifest before regenerating Markdown and HTML.",
        ] if changes else [],
    }


def diff_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Manifest change review: {report.get('project_id') or 'project'}", "", f"Changed fields: {report['change_count']}", "", "Affected areas: " + (", ".join(report["affected_areas"]) or "none"), ""]
    if not report["changes"]:
        lines.append("No specification changes detected.")
    else:
        lines.extend(["| Path | Previous value | New value |", "| --- | --- | --- |"])
        for item in report["changes"]:
            old = json.dumps(item["old"], ensure_ascii=False).replace("|", "\\|")
            new = json.dumps(item["new"], ensure_ascii=False).replace("|", "\\|")
            lines.append(f"| `{item['path']}` | {old} | {new} |")
        lines.extend(["", "## Review", "", *[f"- {value}" for value in report["impact_review"]]])
    return "\n".join(lines) + "\n"
