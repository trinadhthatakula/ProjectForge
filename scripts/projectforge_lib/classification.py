from __future__ import annotations

import re
from typing import Any


SIGNALS = {
    "mobile_app": ["mobile app", "android app", "ios app", "iphone app", "phone app"],
    "web_app": ["web app", "website", "browser app", "web application", "frontend"],
    "saas": ["saas", "subscription product", "multi tenant", "team workspace", "billing plans"],
    "backend_service": ["backend service", "api server", "http api", "webhook", "service endpoint"],
    "automation": ["automation", "command line", "cli", "batch job", "scheduled job", "script that"],
    "ai_product": ["artificial intelligence", "machine learning", "llm", "generative ai", "ai assistant", "chatbot"],
    "library": ["software library", "sdk", "package for developers", "framework", "reusable package"],
    "cross_platform": ["cross platform", "cross-platform", "multiple platforms", "share across devices"],
}


def classify_project(manifest: dict[str, Any]) -> dict[str, Any]:
    project = manifest["project"]
    current = project["classification"]
    if current != "pending":
        return {"classification": current, "status": "already_classified", "scores": {}, "evidence": ["Existing classification was preserved."], "alternatives": []}
    text = " ".join([project.get("name", ""), project.get("summary", ""), project.get("problem_statement", ""), *project.get("platforms", []), *project.get("goals", []), *manifest["technology"].get("preferences", []), *manifest["technology"].get("selected", [])]).casefold()
    scores = {key: 0 for key in SIGNALS}
    evidence: dict[str, list[str]] = {key: [] for key in SIGNALS}
    for classification, phrases in SIGNALS.items():
        for phrase in phrases:
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                scores[classification] += 3 if len(phrase.split()) > 1 else 2
                evidence[classification].append(f"matched {phrase!r}")
    platforms = [value.casefold() for value in project.get("platforms", [])]
    mobile_platforms = [value for value in platforms if any(name in value for name in ("android", "ios", "iphone"))]
    web_platforms = [value for value in platforms if any(name in value for name in ("web", "browser"))]
    if mobile_platforms:
        scores["mobile_app"] += 4
        evidence["mobile_app"].append("selected mobile platform: " + ", ".join(mobile_platforms))
    if web_platforms:
        scores["web_app"] += 4
        evidence["web_app"].append("selected browser platform: " + ", ".join(web_platforms))
    if len(mobile_platforms) + len(web_platforms) > 1:
        scores["cross_platform"] += 5
        evidence["cross_platform"].append("multiple mobile/browser platforms selected")
    if any("server" in value or "backend" in value or "cloud function" in value for value in platforms):
        scores["backend_service"] += 4
        evidence["backend_service"].append("selected server platform")
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, score = ranked[0]
    second_score = ranked[1][1]
    if score < 2:
        return {"classification": "pending", "status": "insufficient_evidence", "scores": scores, "evidence": [], "alternatives": []}
    if second_score and score - second_score < 2:
        alternatives = [name for name, value in ranked if value >= score - 1]
        return {"classification": "pending", "status": "ambiguous", "scores": scores, "evidence": [*evidence[best]], "alternatives": alternatives}
    return {"classification": best, "status": "recommended", "scores": scores, "evidence": evidence[best], "alternatives": [name for name, value in ranked[1:] if value and score - value < 4]}
