from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .common import skill_root
from .security import redact_sensitive
from .validation import readiness_blockers


def _value(value: Any) -> str:
    value = redact_sensitive(value)
    if value is None or value == "":
        return "Not specified"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _md(value: Any) -> str:
    text = _value(value).replace("\r", " ").replace("\n", " ")
    for char in ("\\", "`", "*", "_", "[", "]", "<", ">", "|", "#"):
        text = text.replace(char, "\\" + char)
    return text


def _html(value: Any) -> str:
    return html.escape(_value(redact_sensitive(value)), quote=True)


def _md_list(values: list[Any], empty: str = "Not specified") -> str:
    return "\n".join(f"- {_md(value)}" for value in values) if values else f"- {empty}"


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "| " + " | ".join(_md(header) for header in headers) + " |"
    rule = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_md(cell) for cell in row) + " |" for row in rows]
    return "\n".join([head, rule, *body]) if body else "No entries."


def _section(title: str, body: str, anchor: str | None = None) -> str:
    if anchor:
        return f"<section id=\"{anchor}\"><h2>{title}</h2>{body}</section>"
    return f"<section><h2>{title}</h2>{body}</section>"


def _html_list(values: list[Any], empty: str = "Not specified", *, checklist: str | None = None) -> str:
    if not values:
        return f'<p class="empty">{_html(empty)}</p>'
    items = []
    for index, value in enumerate(values):
        if checklist:
            items.append(f'<li><label><input type="checkbox" data-checklist="{checklist}-{index}"><span>{_html(value)}</span></label></li>')
        else:
            items.append(f"<li>{_html(value)}</li>")
    return '<ul class="checklist">' + "".join(items) + "</ul>" if checklist else "<ul>" + "".join(items) + "</ul>"


def _html_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return '<p class="empty">No entries.</p>'
    head = "<thead><tr>" + "".join(f"<th scope=\"col\">{_html(value)}</th>" for value in headers) + "</tr></thead>"
    body = "<tbody>" + "".join("<tr>" + "".join(f"<td>{_html(value)}</td>" for value in row) + "</tr>" for row in rows) + "</tbody>"
    return "<table>" + head + body + "</table>"


def _html_table_with_markup(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="empty">No entries.</p>'
    head = "<thead><tr>" + "".join(f"<th scope=\"col\">{_html(value)}</th>" for value in headers) + "</tr></thead>"
    body = "<tbody>" + "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows) + "</tbody>"
    return "<table>" + head + body + "</table>"


def _mermaid_quote(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").replace('"', "'").replace("[", "(").replace("]", ")")


def _architecture_mermaid(manifest: dict[str, Any]) -> str:
    components = manifest["architecture"]["components"]
    if not components:
        return "```mermaid\nflowchart LR\n  A[Architecture components pending]\n```"
    ids = {item["id"]: f"C{index}" for index, item in enumerate(components)}
    lines = ["```mermaid", "flowchart LR"]
    for component in components:
        lines.append(f'  {ids[component["id"]]}["{_mermaid_quote(component["name"])}"]')
    for flow in manifest["architecture"]["flows"]:
        if flow["from"] in ids and flow["to"] in ids:
            label = _mermaid_quote(flow.get("label", ""))
            lines.append(f'  {ids[flow["from"]]} -->|"{label}"| {ids[flow["to"]]}')
    lines.append("```")
    return "\n".join(lines)


def _dependency_mermaid(manifest: dict[str, Any]) -> str:
    assignments = [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]
    ids = {item["id"]: f"A{index}" for index, item in enumerate(assignments)}
    edges = [(assignment["id"], dependency) for assignment in assignments for dependency in assignment["dependencies"]]
    edges.extend((edge["from"], edge["to"]) for edge in manifest["dependencies"])
    if not edges:
        return "```mermaid\nflowchart LR\n  Supervisor[Supervisor coordinates independent work]\n  Specialists[Selected specialists]\n  Supervisor --> Specialists\n```"
    lines = ["```mermaid", "flowchart LR"]
    for assignment in assignments:
        lines.append(f'  {ids[assignment["id"]]}["{_mermaid_quote(assignment["name"])}"]')
    for item, dependency in edges:
        if item in ids and dependency in ids:
            lines.append(f"  {ids[dependency]} --> {ids[item]}")
    lines.append("```")
    return "\n".join(lines)


def _svg_diagram(items: list[tuple[str, str]], edges: list[tuple[str, str, str]], *, title: str) -> str:
    if not items:
        items = [("pending", "No items recorded yet")]
    width, box_width, box_height, gap = 920, 620, 62, 48
    height = 54 + len(items) * (box_height + gap) + 18
    center = width / 2
    y_for = {key: 40 + index * (box_height + gap) for index, (key, _) in enumerate(items)}
    fragments = [f'<svg class="diagram" role="img" aria-label="{_html(title)}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">', '<defs><marker id="arrow" markerWidth="10" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L10,4 L0,8 z" fill="#54708f"/></marker></defs>']
    for source, target, label in edges:
        if source not in y_for or target not in y_for:
            continue
        if y_for[source] < y_for[target]:
            source_y, target_y = y_for[source] + box_height, y_for[target]
        else:
            source_y, target_y = y_for[source], y_for[target] + box_height
        fragments.append(f'<path d="M {center} {source_y} L {center} {target_y}" stroke="#54708f" stroke-width="2" marker-end="url(#arrow)" fill="none"/>')
        if label:
            fragments.append(f'<text x="{center + 12}" y="{(source_y + target_y) / 2}" font-size="13">{_html(label)}</text>')
    for key, label in items:
        y = y_for[key]
        fragments.append(f'<rect x="{center - box_width / 2}" y="{y}" width="{box_width}" height="{box_height}" rx="12" fill="#f4f7fb" stroke="#aebbd0"/>')
        fragments.append(f'<text x="{center}" y="{y + 38}" text-anchor="middle" font-size="16">{_html(label)}</text>')
    fragments.append("</svg>")
    return "".join(fragments)


def _html_architecture(manifest: dict[str, Any]) -> str:
    components = manifest["architecture"]["components"]
    items = [(item["id"], item["name"] + " — " + item["description"]) for item in components]
    edges = [(flow["from"], flow["to"], flow["label"]) for flow in manifest["architecture"]["flows"]]
    return _svg_diagram(items, edges, title="Architecture components and data flows")


def _html_dependencies(manifest: dict[str, Any]) -> str:
    assignments = [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]
    items = [(item["id"], item["name"]) for item in assignments]
    edges = [(dependency, item["id"], "depends on") for item in assignments for dependency in item["dependencies"]]
    edges.extend((edge["to"], edge["from"], edge["kind"]) for edge in manifest["dependencies"])
    if not edges:
        return '<p class="empty">No blocking dependencies are recorded. The selected specialists can begin independent work under supervisor coordination.</p>'
    return _svg_diagram(items, edges, title="Assignment dependency graph")


def render_markdown(manifest: dict[str, Any]) -> str:
    project = manifest["project"]
    sections: list[str] = []
    sections.append("## Overview\n\n" + _md(manifest["project"].get("summary") or manifest["project"].get("problem_statement")) + "\n\n**Project ID:** " + _md(project["id"]) + "\n\n**Classification:** " + _md(project["classification"]) + "\n\n**Readiness:** " + _md(manifest["readiness"]["status"]) + "\n\n" + _md_list(readiness_blockers(manifest), "No readiness blockers recorded."))
    sections.append("## Goals and scope\n\n### Goals\n" + _md_list(project["goals"]) + "\n\n### Included\n" + _md_list(project["scope"]["included"]) + "\n\n### Excluded\n" + _md_list(project["scope"]["excluded"]))
    fact_rows = [[item["topic"], _value(item["value"]), item["status"], item.get("source", ""), item.get("rationale", "")] for item in manifest["facts"]]
    sections.append("## Discovery record\n\n**Mode:** " + _md(manifest["discovery"]["mode"]) + "\n\n" + _md_table(["Topic", "Value", "Evidence status", "Source", "Rationale"], fact_rows))
    sections.append("## Audience and platforms\n\n### Audience\n" + _md_list(project["target_audience"]) + "\n\n### Platforms\n" + _md_list(project["platforms"]) + "\n\n### Identifiers\n" + _md_list(project["identifiers"]))
    tech = manifest["technology"]
    sections.append("## Technology\n\n### Preferences\n" + _md_list(tech["preferences"]) + "\n\n### Selected\n" + _md_list(tech["selected"]) + "\n\n### Alternatives\n" + _md_list(tech["alternatives"]) + "\n\n### Compatibility evidence\n" + _md_table(["Finding", "Status", "Source"], [[item["statement"], item["status"], item["source"]] for item in tech["compatibility_evidence"]]))
    feature_rows = [[item["name"], item["priority"], item["status"], item.get("description", ""), "; ".join(item["acceptance_criteria"]), "; ".join(item["depends_on"])] for item in manifest["features"]]
    sections.append("## Features\n\n" + _md_table(["Feature", "Priority", "Status", "Description", "Acceptance criteria", "Depends on"], feature_rows))
    architecture = manifest["architecture"]
    sections.append("## Architecture\n\n" + _md(architecture["summary"]) + "\n\n" + _architecture_mermaid(manifest) + "\n\n### Components\n\n" + _md_table(["ID", "Component", "Purpose"], [[item["id"], item["name"], item["description"]] for item in architecture["components"]]))
    data = manifest["data_api"]
    sections.append("## Data, APIs, and identity\n\n### Data stores\n" + _md_list(data["datastores"]) + "\n\n### APIs and integrations\n" + _md_list(data["apis"]) + "\n\n### Authentication\n" + _md_list(data["authentication"]) + "\n\n### Decisions\n\n" + _md_table(["Question", "Status", "Required", "Owner", "Selected option", "Rationale"], [[item["question"], item["status"], item.get("required", True), item["owner"], item.get("selected") or "Pending", item["rationale"]] for item in data["decisions"]]))
    constraints = manifest["constraints"]
    sections.append("## Constraints\n\n### Security and privacy\n" + _md_list(constraints["security_privacy"]) + "\n\n**Offline:** " + _md(constraints["offline"]) + "\n\n**Monetization:** " + _md(constraints["monetization"]) + "\n\n### Performance\n" + _md_list(constraints["performance"]) + "\n\n### Accessibility\n" + _md_list(constraints["accessibility"]) + "\n\n### Localization\n" + _md_list(constraints["localization"]) + "\n\n### Deployment\n" + _md_list(constraints["deployment"]) + "\n\n**Budget:** " + _md(constraints["budget"]))
    caps = manifest["capability_report"]
    cap_plan_rows = [[item["role_id"], item["capability"], item["owner"], item["next_action"]] for item in manifest["readiness"].get("capability_plans", [])]
    sections.append("## Capability matching report\n\n**Runtime:** " + _md(caps["runtime"]["name"]) + "; session availability: " + _md(caps["runtime"]["session_availability"]) + "\n\n### Capability matches\n\n" + _md_table(["Role", "Capability", "Kind", "Type", "Source", "Status", "Evidence"], [[match["role_id"], item["capability"], item["kind"], item.get("requirement_type", "capability"), item.get("source", "role_profile"), item["status"], "; ".join(item["evidence"])] for match in caps["role_matches"] for item in match["requirements"]]) + "\n\n### Gaps\n" + _md_list(caps["gaps"], "No gaps recorded.") + "\n\n### Capability remediation plans\n\n" + _md_table(["Role", "Capability", "Owner", "Next action"], cap_plan_rows))
    team = manifest["team"]
    assignments = [team["supervisor"], *team["specialists"]]
    assignment_rows = [[item["name"], item["role_id"], item["mission"], "; ".join(item["outputs"]), "; ".join(item["dependencies"])] for item in assignments]
    contracts = []
    for item in assignments:
        contracts.append("### " + _md(item["name"]) + "\n\n**Mission:** " + _md(item["mission"]) + "\n\n**Responsibilities**\n" + _md_list(item["responsibilities"]) + "\n\n**Exclusions**\n" + _md_list(item["exclusions"]) + "\n\n**Inputs**\n" + _md_list(item["inputs"]) + "\n\n**Outputs**\n" + _md_list(item["outputs"]) + "\n\n**Dependencies:** " + _md_list(item["dependencies"]) + "\n\n**Acceptance criteria**\n" + _md_list(item["acceptance_criteria"]) + "\n\n**Handoff requirements**\n" + _md_list(item["handoff_requirements"]) + "\n\n**Required capabilities:** " + _md_list(item["required_capabilities"]) + "\n\n**Supporting skill categories:** " + _md_list(item["supporting_skills"]))
    metrics = team["optimization"]["metrics"]
    relevance_text = "; ".join(f"{item['role_id']}: {item['score']}/10 ({', '.join(item['signals']) or 'user-selected'})" for item in metrics["role_relevance"])
    overlap_text = "; ".join(" / ".join(pair) for pair in metrics["role_overlap"]["pairs"]) or "None"
    metric_rows = [
        ["Role relevance", relevance_text or "No specialist selected", "Confirmed project signals and platform matches rank above unresolved facts and decisions; keyword heuristic, capped at 10"],
        ["Role overlap", f"{metrics['role_overlap']['pair_count']} pair(s): {overlap_text}", "Catalogue overlap relationships"],
        ["Workstream independence", metrics["workstream_independence"]["score"], metrics["workstream_independence"]["basis"]],
        ["Coordination overhead", metrics["coordination_overhead"]["score"], metrics["coordination_overhead"]["basis"]],
        ["Context requirements", f"{metrics['context_requirements']['estimated_input_tokens']} estimated input tokens", metrics["context_requirements"]["basis"]],
        ["Research complexity", f"{metrics['research_complexity']['score']} / 10", metrics["research_complexity"]["basis"]],
        ["Integration complexity", f"{metrics['integration_complexity']['score']} / 10", metrics["integration_complexity"]["basis"]],
        ["Handoffs", metrics["handoffs"], "Estimated dependency and overlap handoffs"],
        ["Expected review effort", f"{metrics['expected_review_effort_points']} points", metrics["review_effort_basis"]],
    ]
    sections.append("## Specialist team\n\n**Approval status:** " + _md(team["approval_status"]) + "\n\n**Selection mode:** " + _md(team["selection_mode"]) + "\n\n" + _md_table(["Agent", "Role", "Mission", "Outputs", "Dependencies"], assignment_rows) + "\n\n### Team optimization estimates\n\n" + _md_table(["Measure", "Estimate", "Basis"], metric_rows) + "\n\n### Selection rationale\n" + _md_list(team["rationale"]) + "\n\n### Execution flow\n\n" + _dependency_mermaid(manifest) + "\n\n## Agent assignment contracts\n\n" + "\n\n".join(contracts))
    sections.append("## Dependencies\n\n" + _md_table(["Work item", "Depends on", "Relationship"], [[item["from"], item["to"], item["kind"]] for item in manifest["dependencies"]]))
    sections.append("## Deliverables and milestones\n\n### Deliverables\n\n" + _md_table(["Deliverable", "Owner", "Status", "Acceptance criteria"], [[item["name"], item["owner"], item["status"], "; ".join(item["acceptance_criteria"])] for item in manifest["deliverables"]]) + "\n\n### Milestones\n\n" + _md_table(["Milestone", "Target", "Depends on"], [[item["name"], item["target"], "; ".join(item["depends_on"])] for item in manifest["milestones"]]))
    sections.append("## Risks\n\n" + _md_table(["Risk", "Likelihood", "Impact", "Mitigation", "Owner"], [[item["description"], item["likelihood"], item["impact"], item["mitigation"], item["owner"]] for item in manifest["risks"]]))
    sections.append("## Assumptions\n\n" + _md_table(["Assumption", "Validation action", "Owner", "Status"], [[item["statement"], item["validation_action"], item["owner"], item["status"]] for item in manifest["assumptions"]]))
    sections.append("## Decision register\n\n" + _md_table(["Question", "Status", "Required", "Owner", "Selected", "Options", "Rationale"], [[item["question"], item["status"], item.get("required", True), item["owner"], item.get("selected") or "Pending", "; ".join(item["options"]), item["rationale"]] for item in manifest["decisions"]]))
    cost = manifest["cost_estimate"]
    sections.append("## Cost and token estimate\n\n**Currency:** " + _md(cost["currency"]) + "\n\n**Estimated total:** " + _md(cost["total_amount"]) + "\n\n**Confidence:** " + _md(cost["confidence"]) + "\n\n" + _md_table(["Cost item", "Amount", "Basis"], [[item["label"], item["amount"], item["basis"]] for item in cost["items"]]) + "\n\n**Estimated orchestration tokens:** " + _md(cost["token_estimate"]["input"]) + " input, " + _md(cost["token_estimate"]["output"]) + " output. " + _md(cost["token_estimate"]["method"]) + "\n\n### Estimate assumptions\n" + _md_list(cost["assumptions"]))
    repo = project["existing_repository"]
    sections.append("## Existing repository\n\n**Path:** " + _md(repo["path"]) + "\n\n**Inspected:** " + _md(repo["inspected"]) + "\n\n" + _md_list(repo["observations"]))
    sections.append("## Change log\n\n" + _md_table(["Date", "Request", "Affected areas", "Status"], [[item["date"], item["request"], "; ".join(item["affected_areas"]), item["status"]] for item in manifest["change_log"]]))
    body = "\n\n---\n\n".join(sections)
    template = (skill_root() / "templates" / "kickoff.md.tpl").read_text(encoding="utf-8")
    values = {"project_name": _md(project["name"]), "readiness": _md(manifest["readiness"]["status"]), "sections": body}
    return re.sub(r"\{\{(\w+)\}\}", lambda match: values.get(match.group(1), ""), template)


def render_html(manifest: dict[str, Any]) -> str:
    project = manifest["project"]
    nav_items: list[tuple[str, str]] = []
    content: list[str] = []

    def add(anchor: str, title: str, body: str) -> None:
        nav_items.append((anchor, title))
        content.append(_section(title, body, anchor))

    goals = '<div class="cards"><div class="card"><h3>Goals</h3>' + _html_list(project["goals"]) + '</div><div class="card"><h3>Included</h3>' + _html_list(project["scope"]["included"]) + '</div><div class="card"><h3>Excluded</h3>' + _html_list(project["scope"]["excluded"]) + "</div></div>"
    add("overview", "Overview", '<p class="lead">' + _html(project.get("summary") or project.get("problem_statement")) + "</p>" + _html_table(["Project ID", "Classification", "Readiness"], [[project["id"], project["classification"], manifest["readiness"]["status"]]]) + '<div class="panel"><h3>Readiness blockers and derived open gates</h3>' + _html_list(readiness_blockers(manifest), "No blockers recorded.") + "</div>" + goals)
    add("discovery", "Discovery", '<p>Mode: <strong>' + _html(manifest["discovery"]["mode"]) + "</strong></p>" + _html_table(["Topic", "Value", "Status", "Source", "Rationale"], [[item["topic"], item["value"], item["status"], item.get("source", ""), item.get("rationale", "")] for item in manifest["facts"]]))
    add("audience", "Audience and platforms", '<div class="cards"><div class="card"><h3>Audience</h3>' + _html_list(project["target_audience"]) + '</div><div class="card"><h3>Platforms</h3>' + _html_list(project["platforms"]) + '</div><div class="card"><h3>Identifiers</h3>' + _html_list(project["identifiers"]) + "</div></div>")
    tech = manifest["technology"]
    add("technology", "Technology", '<div class="cards"><div class="card"><h3>Preferences</h3>' + _html_list(tech["preferences"]) + '</div><div class="card"><h3>Selected</h3>' + _html_list(tech["selected"]) + '</div><div class="card"><h3>Alternatives</h3>' + _html_list(tech["alternatives"]) + "</div></div>" + _html_table(["Compatibility finding", "Status", "Source"], [[item["statement"], item["status"], item["source"]] for item in tech["compatibility_evidence"]]))
    features = []
    for index, item in enumerate(manifest["features"]):
        features.append(f'<div class="card"><label><input type="checkbox" data-checklist="feature-{index}"> <strong>{_html(item["name"])}</strong></label><p>{_html(item.get("description", ""))}</p><p><span class="tag">{_html(item["priority"])}</span> <span class="status-chip" data-status="{_html(item["status"])}">{_html(item["status"])}</span></p><h4>Acceptance criteria</h4>{_html_list(item["acceptance_criteria"])}<p class="meta">Dependencies: {_html(", ".join(item["depends_on"]))}</p></div>')
    add("features", "Features", '<div class="cards">' + ("".join(features) if features else '<p class="empty">No features recorded.</p>') + "</div>")
    arch = manifest["architecture"]
    add("architecture", "Architecture", '<p>' + _html(arch["summary"]) + "</p>" + _html_architecture(manifest) + _html_table(["Component", "Purpose"], [[item["name"], item["description"]] for item in arch["components"]]))
    data = manifest["data_api"]
    add("data-api", "Data, APIs, and identity", '<div class="cards"><div class="card"><h3>Data stores</h3>' + _html_list(data["datastores"]) + '</div><div class="card"><h3>APIs and integrations</h3>' + _html_list(data["apis"]) + '</div><div class="card"><h3>Authentication</h3>' + _html_list(data["authentication"]) + "</div></div>" + _html_table(["Decision", "Status", "Required", "Owner", "Selected", "Rationale"], [[item["question"], item["status"], item.get("required", True), item["owner"], item.get("selected") or "Pending", item["rationale"]] for item in data["decisions"]]))
    con = manifest["constraints"]
    add("constraints", "Constraints", '<div class="cards"><div class="card"><h3>Security and privacy</h3>' + _html_list(con["security_privacy"]) + '</div><div class="card"><h3>Performance</h3>' + _html_list(con["performance"]) + '</div><div class="card"><h3>Accessibility</h3>' + _html_list(con["accessibility"]) + '</div><div class="card"><h3>Localization</h3>' + _html_list(con["localization"]) + '</div><div class="card"><h3>Deployment</h3>' + _html_list(con["deployment"]) + '</div><div class="card"><h3>Offline</h3><p>' + _html(con["offline"]) + '</p><h3>Monetization</h3><p>' + _html(con["monetization"]) + '</p><h3>Budget</h3><p>' + _html(con["budget"]) + "</p></div></div>")
    caps = manifest["capability_report"]
    match_rows = [[match["role_id"], item["capability"], item["kind"], item.get("requirement_type", "capability"), item.get("source", "role_profile"), item["status"], "; ".join(item["evidence"])] for match in caps["role_matches"] for item in match["requirements"]]
    cap_plan_rows = [[item["role_id"], item["capability"], item["owner"], item["next_action"]] for item in manifest["readiness"].get("capability_plans", [])]
    add("capabilities", "Capability report", '<p>Runtime: <strong>' + _html(caps["runtime"]["name"]) + "</strong>; session availability: " + _html(caps["runtime"]["session_availability"]) + "</p>" + _html_table(["Role", "Capability", "Kind", "Type", "Source", "Status", "Evidence"], match_rows) + '<h3>Gaps</h3>' + _html_list(caps["gaps"], "No gaps recorded.") + '<h3>Capability remediation plans</h3>' + _html_table(["Role", "Capability", "Owner", "Next action"], cap_plan_rows) + '<details><summary>Discovered skills</summary>' + _html_table(["Skill", "Status", "Source"], [[item["name"], item["status"], item["source"]] for item in caps["skills"]]) + "</details><details><summary>Discovered agents and tools</summary>" + _html_table(["Capability", "Status", "Source"], [[item["name"], item["status"], item["source"]] for item in [*caps["agents"], *caps["tools"]]]) + "</details>")
    team = manifest["team"]
    assignments = [team["supervisor"], *team["specialists"]]
    cards = []
    for item in assignments:
        cards.append('<details class="card" open><summary>' + _html(item["name"]) + "</summary><p>" + _html(item["mission"]) + "</p><h4>Responsibilities</h4>" + _html_list(item["responsibilities"]) + "<h4>Exclusions</h4>" + _html_list(item["exclusions"]) + "<h4>Inputs</h4>" + _html_list(item["inputs"]) + "<h4>Outputs</h4>" + _html_list(item["outputs"]) + "<h4>Dependencies</h4>" + _html_list(item["dependencies"]) + "<h4>Acceptance criteria</h4>" + _html_list(item["acceptance_criteria"]) + "<h4>Handoff requirements</h4>" + _html_list(item["handoff_requirements"]) + "<h4>Required capabilities</h4>" + _html_list(item["required_capabilities"]) + "<h4>Supporting skill categories</h4>" + _html_list(item["supporting_skills"]) + "</details>")
    metrics = team["optimization"]["metrics"]
    relevance_text = "; ".join(f"{item['role_id']}: {item['score']}/10 ({', '.join(item['signals']) or 'user-selected'})" for item in metrics["role_relevance"])
    overlap_text = "; ".join(" / ".join(pair) for pair in metrics["role_overlap"]["pairs"]) or "None"
    metric_rows = [
        ["Role relevance", relevance_text or "No specialist selected", "Confirmed project signals and platform matches rank above unresolved facts and decisions; keyword heuristic, capped at 10"],
        ["Role overlap", f"{metrics['role_overlap']['pair_count']} pair(s): {overlap_text}", "Catalogue overlap relationships"],
        ["Workstream independence", metrics["workstream_independence"]["score"], metrics["workstream_independence"]["basis"]],
        ["Coordination overhead", metrics["coordination_overhead"]["score"], metrics["coordination_overhead"]["basis"]],
        ["Context requirements", f"{metrics['context_requirements']['estimated_input_tokens']} estimated input tokens", metrics["context_requirements"]["basis"]],
        ["Research complexity", f"{metrics['research_complexity']['score']} / 10", metrics["research_complexity"]["basis"]],
        ["Integration complexity", f"{metrics['integration_complexity']['score']} / 10", metrics["integration_complexity"]["basis"]],
        ["Handoffs", metrics["handoffs"], "Estimated dependency and overlap handoffs"],
        ["Expected review effort", f"{metrics['expected_review_effort_points']} points", metrics["review_effort_basis"]],
    ]
    add("team", "Specialist team", '<p>Approval: <strong>' + _html(team["approval_status"]) + "</strong>. Selection mode: <strong>" + _html(team["selection_mode"]) + "</strong>. Supervisor plus " + _html(len(team["specialists"])) + " specialists.</p>" + '<h3>Team optimization estimates</h3>' + _html_table(["Measure", "Estimate", "Basis"], metric_rows) + '<div class="panel"><h3>Selection rationale</h3>' + _html_list(team["rationale"]) + "</div>" + _html_dependencies(manifest) + '<h3>Assignment contracts</h3><div class="cards">' + "".join(cards) + "</div>")
    add("dependencies", "Dependencies", _html_table(["Work item", "Depends on", "Relationship"], [[item["from"], item["to"], item["kind"]] for item in manifest["dependencies"]]))
    deliverables = []
    for index, item in enumerate(manifest["deliverables"]):
        deliverables.append([f'<label><input type="checkbox" data-checklist="deliverable-{index}"> {_html(item["name"])}</label>', _html(item["owner"]), _html(item["status"]), _html("; ".join(item["acceptance_criteria"]))])
    milestones = []
    for index, item in enumerate(manifest["milestones"]):
        milestones.append([f'<label><input type="checkbox" data-checklist="milestone-{index}"> {_html(item["name"])}</label>', _html(item["target"]), _html(", ".join(item["depends_on"]))])
    deliverable_table = _html_table_with_markup(["Deliverable", "Owner", "Status", "Acceptance"], deliverables)
    milestone_table = _html_table_with_markup(["Milestone", "Target", "Depends on"], milestones)
    add("delivery", "Deliverables and milestones", '<h3>Deliverables</h3>' + deliverable_table + "<h3>Milestones</h3>" + milestone_table)
    risk_cards = []
    for risk in manifest["risks"]:
        risk_cards.append(f'<div class="card risk-{_html(risk["impact"])}"><h3>{_html(risk["description"])}</h3><p>Likelihood: {_html(risk["likelihood"])}; impact: {_html(risk["impact"])}</p><p>Mitigation: {_html(risk["mitigation"])}</p><p>Owner: {_html(risk["owner"])}</p></div>')
    add("risks", "Risks", '<div class="cards">' + ("".join(risk_cards) if risk_cards else '<p class="empty">No risks recorded.</p>') + "</div>")
    add("assumptions", "Assumptions", _html_table(["Assumption", "Validation action", "Owner", "Status"], [[item["statement"], item["validation_action"], item["owner"], item["status"]] for item in manifest["assumptions"]]))
    add("decisions", "Decision register", _html_table(["Question", "Status", "Required", "Owner", "Selected", "Options", "Rationale"], [[item["question"], item["status"], item.get("required", True), item["owner"], item.get("selected") or "Pending", "; ".join(item["options"]), item["rationale"]] for item in manifest["decisions"]]))
    cost = manifest["cost_estimate"]
    add("cost", "Cost and token estimate", '<div class="cards"><div class="card"><h3>Estimated total</h3><p>' + _html(cost["total_amount"]) + " " + _html(cost["currency"]) + "</p><p>Confidence: " + _html(cost["confidence"]) + '</p></div><div class="card"><h3>Estimated orchestration tokens</h3><p>' + _html(cost["token_estimate"]["input"]) + " input / " + _html(cost["token_estimate"]["output"]) + " output</p><p>" + _html(cost["token_estimate"]["method"]) + "</p></div></div>" + _html_table(["Cost item", "Amount", "Basis"], [[item["label"], item["amount"], item["basis"]] for item in cost["items"]]) + '<h3>Estimate assumptions</h3>' + _html_list(cost["assumptions"]))
    repo = project["existing_repository"]
    add("repository", "Existing repository", _html_table(["Path", "Inspected"], [[repo["path"], repo["inspected"]]]) + _html_list(repo["observations"]))
    add("changes", "Change log", _html_table(["Date", "Request", "Affected areas", "Status"], [[item["date"], item["request"], "; ".join(item["affected_areas"]), item["status"]] for item in manifest["change_log"]]))

    navigation = "<ul>" + "".join(f'<li><a href="#{anchor}">{_html(title)}</a></li>' for anchor, title in nav_items) + "</ul>"
    status = manifest["readiness"]["status"]
    status_slug = re.sub(r"[^a-z0-9-]", "-", status.casefold())
    template = (skill_root() / "templates" / "kickoff.html.tpl").read_text(encoding="utf-8")
    style = (skill_root() / "templates" / "kickoff.css").read_text(encoding="utf-8")
    script = """(() => { const key = "projectforge:" + """ + json.dumps(project["id"]) + """; try { const saved = JSON.parse(localStorage.getItem(key) || "{}"); document.querySelectorAll("input[data-checklist]").forEach(box => { const id = box.dataset.checklist; box.checked = Boolean(saved[id]); box.addEventListener("change", () => { try { const state = JSON.parse(localStorage.getItem(key) || "{}"); state[id] = box.checked; localStorage.setItem(key, JSON.stringify(state)); } catch (_) {} }); }); } catch (_) {} })();"""
    values = {"title": _html(project["name"]), "summary": _html(project.get("summary") or project.get("problem_statement")), "status": _html(status), "status_slug": status_slug, "version": _html(manifest["schema_version"]), "navigation": navigation, "content": "".join(content), "style": style, "script": script}
    return re.sub(r"\{\{(\w+)\}\}", lambda match: values.get(match.group(1), ""), template)
