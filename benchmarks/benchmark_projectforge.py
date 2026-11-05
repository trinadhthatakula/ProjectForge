#!/usr/bin/env python3
"""Repeatable, offline microbenchmarks for ProjectForge's local planning helpers."""

from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from projectforge_lib import __version__ as PROJECTFORGE_VERSION  # noqa: E402
from projectforge_lib.common import catalog, new_manifest  # noqa: E402
from projectforge_lib.discovery import match_capabilities  # noqa: E402
from projectforge_lib.optimization import optimize_team  # noqa: E402
from projectforge_lib.rendering import render_html, render_markdown  # noqa: E402
from projectforge_lib.validation import validate_manifest  # noqa: E402


def _sizes(value: str) -> list[int]:
    try:
        sizes = [int(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated positive integers") from exc
    if not sizes or any(size < 1 for size in sizes) or len(set(sizes)) != len(sizes):
        raise argparse.ArgumentTypeError("sizes must be unique positive integers")
    return sizes


def _manifest(feature_count: int) -> dict:
    manifest = new_manifest("Synthetic ProjectForge benchmark workspace", mode="standard")
    manifest["project"].update({
        "summary": "A multi-tenant SaaS workspace with web and mobile clients, team access, subscription billing, and audit history.",
        "problem_statement": "Teams need a secure workspace to manage projects, collaborate, and review account activity.",
        "classification": "saas",
        "platforms": ["Web", "Android"],
        "goals": ["Manage shared work", "Protect tenant data", "Track important activity"],
    })
    manifest["features"] = [
        {
            "id": f"feature-{index:06d}",
            "name": f"Workspace feature {index:06d}",
            "description": "Tenant-aware collaboration, authorization, activity history, and billing behavior.",
            "priority": "should",
            "status": "confirmed",
            "acceptance_criteria": [
                "Authorized workspace members can complete the action.",
                "Cross-tenant access is rejected and recorded.",
            ],
            "depends_on": [],
        }
        for index in range(feature_count)
    ]
    return manifest


def _inventory(skill_count: int) -> dict:
    return {
        "generated_at": "2026-11-05T00:00:00Z",
        "runtime": {
            "name": "synthetic-benchmark",
            "detected": False,
            "version": None,
            "session_availability": "unverified",
            "session_inventory_complete": False,
            "evidence": [],
        },
        "skills": [
            {
                "name": f"Synthetic capability {index:06d}",
                "description": "Software development, SaaS security, APIs, testing, and documentation.",
                "source": "benchmark fixture",
                "status": "unverified",
            }
            for index in range(skill_count)
        ],
        "agents": [],
        "tools": [],
        "searched_skill_directories": [],
        "notes": [],
    }


def _measure(operation: Callable[[], object], warmups: int, iterations: int) -> dict[str, float | int]:
    for _ in range(warmups):
        operation()
    samples_ms = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        operation()
        samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples_ms)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "iterations": iterations,
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[p95_index], 3),
    }


def _revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def run_benchmarks(sizes: list[int], iterations: int, warmups: int) -> dict:
    roles = catalog()["roles"]
    results = []
    for size in sizes:
        manifest = _manifest(size)
        validation_errors = validate_manifest(manifest)
        if validation_errors:
            raise RuntimeError("Synthetic benchmark manifest is invalid: " + "; ".join(validation_errors))
        inventory = _inventory(size)

        def validate() -> None:
            errors = validate_manifest(manifest)
            if errors:
                raise RuntimeError("Manifest validation failed during benchmark: " + "; ".join(errors))

        def optimize() -> None:
            optimize_team(manifest, roles=roles, mode="standard")

        def match() -> None:
            match_capabilities(manifest, inventory, roles)

        operations = {
            "manifest_validation": validate,
            "markdown_render": lambda: render_markdown(manifest),
            "offline_html_render": lambda: render_html(manifest),
            "team_optimization": optimize,
            "capability_matching": match,
        }
        results.append({
            "feature_count": size,
            "synthetic_skill_count": size,
            "operations": {
                name: _measure(operation, warmups, iterations)
                for name, operation in operations.items()
            },
        })

    return {
        "benchmark": "ProjectForge local manifest operations",
        "projectforge_version": PROJECTFORGE_VERSION,
        "git_revision": _revision(),
        "measured_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "system_release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or "not reported",
        },
        "method": {
            "timer": "time.perf_counter_ns",
            "warmups_per_operation": warmups,
            "iterations_per_operation": iterations,
            "reported_units": "milliseconds",
            "reported_statistics": ["median", "nearest-rank p95"],
            "network_access": "none",
            "fixture": "synthetic manifest and capability inventory; feature and skill counts scale together",
            "thresholds": "informational only; rerun on the same environment for comparisons",
        },
        "measurements": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=_sizes, default=_sizes("10,100,1000"), help="synthetic feature and skill counts (default: 10,100,1000)")
    parser.add_argument("--iterations", type=int, default=9, help="timed samples per operation and size (default: 9)")
    parser.add_argument("--warmups", type=int, default=1, help="warmup calls per operation and size (default: 1)")
    args = parser.parse_args()
    if args.iterations < 1 or args.warmups < 0:
        parser.error("iterations must be positive and warmups cannot be negative")
    print(json.dumps(run_benchmarks(args.sizes, args.iterations, args.warmups), indent=2) + "\n", end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
