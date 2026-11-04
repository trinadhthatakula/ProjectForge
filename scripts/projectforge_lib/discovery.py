from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from .common import now_utc
from .security import redact_text
from .verification import empty_verification


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)


def _frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}
    match = _FRONTMATTER.search(text)
    if not match:
        return {}
    values: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line or line[:1].isspace():
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _codex_version(binary: str) -> str | None:
    try:
        result = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = (result.stdout or result.stderr).strip()
    return value.splitlines()[0] if result.returncode == 0 and value else None


def _load_toml(path: Path) -> dict[str, Any] | None:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return None


def discover_environment(
    *, cwd: Path | None = None, extra_skill_dirs: list[Path] | None = None,
    active_tools: list[str] | None = None, active_skills: list[str] | None = None, inventory_complete: bool = False,
) -> dict[str, Any]:
    cwd = (cwd or Path.cwd()).expanduser().resolve()
    home = Path.home()
    codex_home = Path(os.environ.get("CODEX_HOME", home / ".codex")).expanduser()
    skill_dirs = [
        codex_home / "skills", home / ".codex" / "skills", home / ".agents" / "skills",
        cwd / ".codex" / "skills", cwd / ".agents" / "skills",
        *(extra_skill_dirs or []),
    ]
    unique_skill_dirs: list[Path] = []
    seen_dirs: set[str] = set()
    for directory in skill_dirs:
        normalized = str(directory.expanduser().resolve())
        if normalized not in seen_dirs:
            seen_dirs.add(normalized)
            unique_skill_dirs.append(Path(normalized))

    skills: list[dict[str, str]] = []
    seen_skills: set[str] = set()
    for directory in unique_skill_dirs:
        try:
            children = sorted(directory.iterdir())
        except OSError:
            continue
        for child in children:
            skill_file = child / "SKILL.md"
            if not child.is_dir() or not skill_file.is_file():
                continue
            metadata = _frontmatter(skill_file)
            name = metadata.get("name", child.name)
            key = name.casefold()
            if key in seen_skills:
                continue
            seen_skills.add(key)
            skills.append({"name": name, "description": metadata.get("description", ""), "source": str(skill_file), "status": "unverified"})

    agent_dirs = [codex_home / "agents", home / ".codex" / "agents", cwd / ".codex" / "agents"]
    agents: list[dict[str, str]] = []
    seen_agents: set[str] = set()
    for directory in agent_dirs:
        try:
            files = sorted(directory.glob("*.toml"))
        except OSError:
            continue
        for file in files:
            content = _load_toml(file)
            if content is None:
                continue
            name = str(content.get("name") or file.stem)
            key = name.casefold()
            if key in seen_agents:
                continue
            seen_agents.add(key)
            agents.append({"name": name, "description": str(content.get("description", "")), "source": str(file), "status": "unverified"})

    configured_tools: list[dict[str, str]] = []
    config_files = [cwd / ".codex" / "config.toml", codex_home / "config.toml"]
    seen_tools: set[str] = set()
    for config_file in config_files:
        content = _load_toml(config_file)
        if content is None:
            continue
        for name in sorted((content.get("mcp_servers") or {}).keys()):
            key = str(name).casefold()
            if key not in seen_tools:
                configured_tools.append({"name": str(name), "source": str(config_file), "status": "unverified"})
                seen_tools.add(key)

    for tool_name in active_tools or []:
        key = tool_name.casefold()
        if key not in seen_tools:
            configured_tools.append({"name": tool_name, "source": "active session inventory supplied by caller", "status": "available"})
            seen_tools.add(key)
        else:
            for item in configured_tools:
                if item["name"].casefold() == key:
                    item["status"] = "available"
                    item["source"] += "; confirmed in active session inventory"

    active_skill_set = {name.casefold() for name in active_skills or []}
    for skill in skills:
        if skill["name"].casefold() in active_skill_set:
            skill["status"] = "available"
            skill["source"] += "; confirmed in active session inventory"
    for name in active_skills or []:
        if name.casefold() not in seen_skills:
            skills.append({"name": name, "description": "", "source": "active session inventory supplied by caller", "status": "available"})
            seen_skills.add(name.casefold())

    codex_binary = shutil.which("codex")
    runtime_name = "unknown"
    version = None
    evidence: list[str] = []
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_CI"):
        runtime_name = "codex"
        evidence.append("Codex session environment marker detected")
    elif os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        runtime_name = "claude-code"
        evidence.append("Claude Code session environment marker detected")
    elif os.environ.get("GEMINI_CLI"):
        runtime_name = "gemini-cli"
        evidence.append("Gemini CLI environment marker detected")
    elif codex_binary:
        runtime_name = "codex-cli-installed"
        version = _codex_version(codex_binary)
        evidence.append(f"Codex CLI executable found at {codex_binary}")
        if version:
            evidence.append(version)
    else:
        for candidate, label in (("claude", "claude-code-installed"), ("gemini", "gemini-cli-installed")):
            executable = shutil.which(candidate)
            if executable:
                runtime_name = label
                evidence.append(f"{candidate} executable found at {executable}")
                break
    evidence.append("Local discovery cannot verify tools exposed by the current conversation session")
    return {
        "generated_at": now_utc(),
        "runtime": {"name": runtime_name, "detected": runtime_name != "unknown", "version": version, "session_availability": "unverified", "session_inventory_complete": inventory_complete, "evidence": evidence},
        "skills": skills,
        "agents": agents,
        "tools": configured_tools,
        "searched_skill_directories": [str(path) for path in unique_skill_dirs],
        "searched_agent_directories": [str(path) for path in agent_dirs],
        "notes": ["Skill and agent files are local evidence only; session availability remains unverified unless the caller supplies an active inventory."],
    }


def _tokens(value: str) -> set[str]:
    ignored = {"and", "or", "for", "with", "from", "the", "tool", "tools", "support", "supporting", "knowledge", "system", "design"}
    return {part for part in re.findall(r"[a-z0-9+#.-]+", value.casefold()) if len(part) > 2 and part not in ignored}


def _match_score(required: str, candidate: str) -> float:
    a, b = _tokens(required), _tokens(candidate)
    if not a or not b:
        return 0.0
    common = a & b
    return len(common) / len(a)


def match_capabilities(
    manifest: dict[str, Any], inventory: dict[str, Any], roles: list[dict[str, Any]], *, threshold: float = 0.34,
) -> dict[str, Any]:
    role_by_id = {role["id"]: role for role in roles}
    assigned = [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]
    selected_role_ids = {assignment["role_id"] for assignment in assigned}
    if len(assigned) == 1:
        # When no team is assigned yet, report likely role capability matches after optimization.
        from .optimization import optimize_team
        plan = optimize_team(manifest, roles=roles, mode=manifest["discovery"]["mode"])
        assigned.extend(plan["assignments"])

    capabilities = []
    for role_assignment in assigned:
        profile = role_by_id.get(role_assignment["role_id"])
        if not profile:
            continue
        assignment_required = role_assignment.get("required_capabilities", [])
        assignment_required_set = {value.casefold() for value in assignment_required}
        reqs: list[tuple[str, str, str, str]] = []
        reqs.extend((value, "required", "capability", "role_profile") for value in profile["required_capabilities"])
        reqs.extend((value, "required", "tool", "role_profile") for value in profile["tool_requirements"])
        reqs.extend((value, "optional", "capability", "role_profile") for value in profile["optional_capabilities"] if value.casefold() not in assignment_required_set)
        reqs.extend((value, "optional", "capability", "role_profile") for value in profile["supporting_skill_categories"] if value.casefold() not in assignment_required_set)
        profile_required = {value.casefold() for value in [*profile["required_capabilities"], *profile["tool_requirements"]]}
        reqs.extend(
            (value, "required", "capability", "assignment")
            for value in assignment_required
            if value.casefold() not in profile_required
        )
        seen_requirements: set[tuple[str, str, str, str]] = set()
        for requirement, kind, requirement_type, source in reqs:
            requirement_key = (requirement.casefold(), kind, requirement_type, source)
            if requirement_key in seen_requirements:
                continue
            seen_requirements.add(requirement_key)
            candidates: list[tuple[float, dict[str, str], str]] = []
            if requirement_type == "capability":
                for skill in inventory.get("skills", []):
                    score = _match_score(requirement, skill["name"] + " " + skill["description"])
                    if score >= threshold:
                        candidates.append((score, skill, "skill"))
                for agent in inventory.get("agents", []):
                    score = _match_score(requirement, agent["name"] + " " + agent["description"])
                    if score >= threshold:
                        candidates.append((score, agent, "agent"))
            for tool in inventory.get("tools", []):
                score = _match_score(requirement, tool["name"])
                if score >= threshold:
                    candidates.append((score, tool, "tool"))
            candidates.sort(key=lambda item: (-item[0], item[1]["name"].casefold()))
            evidence: list[str] = []
            statuses: list[str] = []
            for score, candidate, source_type in candidates[:3]:
                evidence.append(f"{source_type} {candidate['name']} ({candidate['source']}; match {score:.2f})")
                statuses.append(candidate.get("status", "unverified"))
            best_score = candidates[0][0] if candidates else 0.0
            if "available" in statuses and best_score >= 0.66:
                status = "available"
            elif candidates:
                status = "partial" if best_score < 0.66 else "unverified"
            elif inventory["runtime"].get("session_inventory_complete"):
                status = "missing"
            else:
                status = "unverified" if inventory["runtime"]["session_availability"] == "unverified" else "missing"
            if not evidence:
                evidence.append("No matching local metadata; active session capability inventory is not confirmed")
            capabilities.append({"role_id": profile["id"], "requirement": requirement, "kind": kind, "requirement_type": requirement_type, "source": source, "status": status, "evidence": evidence, "verification": empty_verification(inventory["generated_at"])})

    role_groups: dict[str, list[dict[str, Any]]] = {
        assignment["role_id"]: [] for assignment in assigned if assignment["role_id"] in role_by_id
    }
    for item in capabilities:
        role_groups.setdefault(item["role_id"], []).append({"capability": item["requirement"], "kind": item["kind"], "requirement_type": item["requirement_type"], "source": item["source"], "status": item["status"], "evidence": item["evidence"], "verification": item["verification"]})
    gaps = []
    manifest_gaps = []
    for item in capabilities:
        if item["kind"] == "required":
            source = "assignment-specific " if item["source"] == "assignment" else ""
            gap = f"{item['role_id']}: {source}{item['requirement']} is discovered as {item['status']} and remains {item['verification']['status']}"
            gaps.append(gap)
            if item["role_id"] in selected_role_ids:
                manifest_gaps.append(gap)
    manifest["capability_report"] = {
        "generated_at": inventory["generated_at"],
        "runtime": inventory["runtime"],
        "skills": inventory["skills"],
        "agents": inventory["agents"],
        "tools": inventory["tools"],
        "role_matches": [{"role_id": role_id, "requirements": matches} for role_id, matches in sorted(role_groups.items())],
        "gaps": manifest_gaps,
    }
    return {"runtime": inventory["runtime"], "role_matches": capabilities, "gaps": gaps, "skills": inventory["skills"], "agents": inventory["agents"], "tools": inventory["tools"], "searched_skill_directories": inventory["searched_skill_directories"], "notes": inventory["notes"]}


def inspect_skill(name: str, *, cwd: Path | None = None, extra_skill_dirs: list[Path] | None = None, max_chars: int = 40000) -> dict[str, Any]:
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    inventory = discover_environment(cwd=cwd, extra_skill_dirs=extra_skill_dirs)
    matches = [item for item in inventory["skills"] if item["name"].casefold() == name.casefold()]
    if not matches:
        raise ValueError(f"Skill {name!r} was not found in the searched skill directories")
    source = Path(matches[0]["source"])
    if not source.is_file():
        raise ValueError(f"Skill {name!r} was present only as a session inventory entry; no local instruction file is available")
    try:
        content = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Cannot read skill instructions at {source}: {exc}") from exc
    content = redact_text(content)
    truncated = len(content) > max_chars
    return {"name": matches[0]["name"], "description": matches[0]["description"], "source": str(source), "content": content[:max_chars], "truncated": truncated, "max_chars": max_chars, "script_execution": "none; skill content was read as text only"}
