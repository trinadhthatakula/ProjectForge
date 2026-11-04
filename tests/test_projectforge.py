from __future__ import annotations

import json
import contextlib
import io
import sys
import tempfile
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from projectforge_lib.changes import compare_manifests
from projectforge_lib.common import catalog, new_assignment, new_manifest, read_json_with_sha256, write_text, write_text_if_unchanged
from projectforge_lib.discovery import discover_environment, inspect_skill, match_capabilities
from projectforge_lib.handoffs import validate_agent_result
from projectforge_lib.optimization import optimize_team
from projectforge_lib.rendering import render_html, render_markdown
from projectforge_lib.validation import validate_manifest, validate_role_catalog


class DocumentParser(HTMLParser):
    pass


class ProjectForgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.roles = catalog()["roles"]
        cls.role_map = {role["id"]: role for role in cls.roles}

    def make_android_manifest(self) -> dict:
        manifest = new_manifest("Pocket Garden", "standard")
        manifest["project"].update({"summary": "Offline care reminders for plants", "problem_statement": "Apartment gardeners need reliable plant care reminders.", "target_audience": ["Apartment gardeners"], "goals": ["Reduce missed care tasks"], "platforms": ["Android"], "classification": "mobile_app"})
        manifest["features"] = [{"id": "reminders", "name": "Care reminders", "description": "Schedule watering reminders", "priority": "must", "status": "confirmed", "acceptance_criteria": ["A reminder can be scheduled and rescheduled"], "depends_on": []}]
        manifest["technology"]["selected"] = ["Kotlin", "Jetpack Compose"]
        manifest["architecture"].update({"summary": "Compose UI with a local database and scheduler.", "components": [{"id": "ui", "name": "Android UI", "description": "Plant list and care actions"}, {"id": "store", "name": "Local store", "description": "Plant profiles"}], "flows": [{"from": "ui", "to": "store", "label": "read plant profiles"}]})
        return manifest

    def make_legacy_manifest(self) -> dict:
        manifest = self.make_android_manifest()
        manifest["schema_version"] = "1.0.0"
        manifest.pop("execution")
        manifest["team"]["specialists"] = [new_assignment(self.role_map["android-engineer"])]
        manifest["team"]["specialists"][0]["inputs"].append("Prerequisite: reviewed API contract")
        for assignment in [manifest["team"]["supervisor"], *manifest["team"]["specialists"]]:
            assignment.pop("prerequisites")
            assignment.pop("result_contract")
        return manifest

    def make_handoff_manifest(self) -> dict:
        manifest = self.make_android_manifest()
        assignment = new_assignment(self.role_map["android-engineer"])
        assignment["result_contract"].update({
            "allowed_paths": ["src/"],
            "protected_paths": ["src/secrets/"],
            "required_checks": ["Unit tests"],
        })
        manifest["team"]["specialists"] = [assignment]
        return manifest

    def make_agent_result(self, manifest: dict, **overrides) -> dict:
        return {
            "protocol_version": "1.0.0",
            "result_id": "android-result-1",
            "assignment_id": manifest["team"]["specialists"][0]["id"],
            "manifest_version": manifest["schema_version"],
            "status": "validated",
            "summary": "Implemented the authentication repository.",
            "outputs": [{"path": "src/auth.py", "description": "Authentication repository"}],
            "evidence": ["Unit tests completed."],
            "validation": {"passed": True, "checks": [{"name": "Unit tests", "status": "passed", "evidence": ["3 tests passed"]}]},
            "unresolved_questions": [],
            "risks": [],
            "assumptions": [],
            "handoff_notes": "Ready for integration review.",
            "attempt": 1,
            "prior_result_id": None,
            "created_at": "2026-11-05T00:00:00Z",
            **overrides,
        }

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        from projectforge_lib.cli import main
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_catalog_profiles_match_schema_and_include_all_specialists(self) -> None:
        self.assertEqual(validate_role_catalog(), [])
        self.assertEqual(len(self.roles), 24)
        required = {"seo-specialist", "aso-specialist", "geo-specialist", "supervisor"}
        self.assertTrue(required.issubset(self.role_map))
        self.assertIn("seo", self.role_map["seo-specialist"]["triggers"])
        self.assertIn("app store listing", self.role_map["aso-specialist"]["triggers"])
        self.assertIn("generative search", self.role_map["geo-specialist"]["triggers"])
        self.assertTrue(any("app-store ranking" in item for item in self.role_map["seo-specialist"]["exclusions"]))
        self.assertTrue(any("website SEO" in item for item in self.role_map["aso-specialist"]["exclusions"]))
        self.assertTrue(any("technical SEO" in item for item in self.role_map["geo-specialist"]["exclusions"]))
        assignment = new_assignment(self.role_map["android-engineer"])
        self.assertTrue(any("Prerequisite: backend API contract" in item for item in assignment["inputs"]))

    def test_starter_manifest_passes_json_schema(self) -> None:
        self.assertEqual(validate_manifest(new_manifest("Sample project")), [])

    def test_simple_android_project_gets_one_domain_specialist(self) -> None:
        plan = optimize_team(self.make_android_manifest(), roles=self.roles, mode="standard")
        self.assertEqual(plan["selected_role_ids"], ["android-engineer"])
        self.assertEqual(1 + len(plan["assignments"]), 2)
        self.assertEqual(plan["selection_mode"], "dynamic")
        self.assertEqual(plan["metrics"]["role_relevance"][0]["role_id"], "android-engineer")
        self.assertEqual(plan["metrics"]["workstream_independence"]["score"], 1.0)
        self.assertIn("expected_review_effort_points", plan["metrics"])

    def test_hybrid_selection_keeps_user_role_then_adds_relevant_roles(self) -> None:
        plan = optimize_team(
            self.make_android_manifest(), roles=self.roles, mode="standard",
            requested_roles=["product-manager"], selection_mode="hybrid",
        )
        self.assertEqual(plan["selected_role_ids"], ["product-manager", "android-engineer"])
        self.assertEqual(plan["selection_mode"], "hybrid")
        self.assertFalse(plan["approval_required"])
        self.assertIn("role_overlap", plan["metrics"])
        self.assertIn("context_requirements", plan["metrics"])
        self.assertIn("research_complexity", plan["metrics"])
        self.assertIn("integration_complexity", plan["metrics"])

    def test_cli_applies_hybrid_selection_and_persists_metrics(self) -> None:
        from projectforge_lib.cli import main
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(self.make_android_manifest()), encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["optimize", str(path), "--selection-mode", "hybrid", "--role", "product-manager", "--apply"]), 0)
            updated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(updated["team"]["selection_mode"], "hybrid")
            self.assertEqual([item["role_id"] for item in updated["team"]["specialists"]], ["product-manager", "android-engineer"])
            self.assertIn("role_relevance", updated["team"]["optimization"]["metrics"])
            self.assertEqual(validate_manifest(updated), [])

    def test_manifest_updates_reject_stale_snapshots_without_losing_newer_edits(self) -> None:
        import projectforge_lib.cli as cli

        manifest = self.make_android_manifest()
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            original_save = cli._save_manifest

            def simulate_concurrent_edit(path, updated_manifest, *, expected_sha256, dry_run=False):
                concurrent = json.loads(path.read_text(encoding="utf-8"))
                concurrent["project"]["summary"] = "Changed by a concurrent writer"
                path.write_text(json.dumps(concurrent), encoding="utf-8")
                return original_save(path, updated_manifest, expected_sha256=expected_sha256, dry_run=dry_run)

            with patch("projectforge_lib.cli._save_manifest", side_effect=simulate_concurrent_edit):
                code, _, error = self.run_cli([
                    "optimize", str(manifest_path), "--selection-mode", "manual",
                    "--role", "android-engineer", "--apply",
                ])

            self.assertEqual(code, 2)
            self.assertIn("Manifest changed since it was read", error)
            latest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(latest["project"]["summary"], "Changed by a concurrent writer")
            self.assertEqual(latest["team"]["specialists"], [])

    def test_concurrent_manifest_writes_serialize_and_only_one_stale_snapshot_wins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text('{"generation": 0}\n', encoding="utf-8")
            _, original_hash = read_json_with_sha256(manifest_path)
            start = Barrier(2)

            def write_generation(generation: int) -> str:
                start.wait(timeout=5)
                try:
                    write_text_if_unchanged(
                        manifest_path,
                        json.dumps({"generation": generation}) + "\n",
                        expected_sha256=original_hash,
                    )
                    return "written"
                except ValueError as error:
                    self.assertIn("Manifest changed since it was read", str(error))
                    return "conflict"

            with ThreadPoolExecutor(max_workers=2) as workers:
                outcomes = list(workers.map(write_generation, [1, 2]))

            self.assertEqual(sorted(outcomes), ["conflict", "written"])
            self.assertIn(json.loads(manifest_path.read_text(encoding="utf-8"))["generation"], {1, 2})

    def test_manual_and_hybrid_require_user_seed_roles_and_never_trim(self) -> None:
        manifest = self.make_android_manifest()
        with self.assertRaisesRegex(ValueError, "Manual selection requires"):
            optimize_team(manifest, roles=self.roles, selection_mode="manual")
        with self.assertRaisesRegex(ValueError, "Hybrid selection requires"):
            optimize_team(manifest, roles=self.roles, selection_mode="hybrid")
        requested = ["android-engineer", "ios-engineer", "web-engineer", "backend-engineer", "python-engineer", "security-engineer", "devops-engineer"]
        plan = optimize_team(manifest, roles=self.roles, requested_roles=requested, selection_mode="hybrid")
        self.assertEqual(plan["selected_role_ids"], requested)
        self.assertTrue(plan["approval_required"])

    def test_complex_web_service_gets_relevant_roles_but_respects_cap(self) -> None:
        manifest = self.make_android_manifest()
        manifest["project"].update({"name": "Fieldnote SaaS", "summary": "Web SaaS teams need subscriptions and organization workspaces.", "problem_statement": "A SaaS workspace stores customer records behind API authorization.", "classification": "saas", "platforms": ["Web"]})
        manifest["data_api"].update({"apis": ["REST API"], "datastores": ["PostgreSQL database"], "authentication": ["OAuth authentication"]})
        manifest["technology"]["selected"] = ["web deployment", "cloud"]
        manifest["features"].extend([{**manifest["features"][0], "id": "billing", "name": "Subscription billing"}, {**manifest["features"][0], "id": "workspace", "name": "Organization workspace"}])
        plan = optimize_team(manifest, roles=self.roles, mode="comprehensive")
        self.assertIn("web-engineer", plan["selected_role_ids"])
        self.assertIn("backend-engineer", plan["selected_role_ids"])
        self.assertGreaterEqual(len(plan["assignments"]), 3)
        self.assertLessEqual(1 + len(plan["assignments"]), 7)

    def test_explicit_seven_specialists_are_not_silently_trimmed(self) -> None:
        requested = ["android-engineer", "ios-engineer", "web-engineer", "backend-engineer", "python-engineer", "security-engineer", "devops-engineer"]
        plan = optimize_team(self.make_android_manifest(), roles=self.roles, mode="custom", requested_roles=requested)
        self.assertTrue(plan["approval_required"])
        self.assertEqual(plan["selected_role_ids"], requested)
        self.assertEqual(plan["assignments"], [])
        self.assertIn("consult other experts sequentially", " ".join(plan["rationale"]))

    def test_search_specialist_roles_are_distinct_and_explicit_selection_is_kept(self) -> None:
        ids = ["aso-specialist", "seo-specialist", "geo-specialist"]
        plan = optimize_team(self.make_android_manifest(), roles=self.roles, mode="custom", requested_roles=ids)
        self.assertEqual(plan["selected_role_ids"], ids)
        self.assertEqual(len(plan["assignments"]), 3)
        self.assertGreater(plan["overlap_pairs"], 0)

    def test_classification_uses_platform_and_leaves_ambiguous_signal_visible(self) -> None:
        from projectforge_lib.classification import classify_project
        manifest = self.make_android_manifest()
        self.assertEqual(classify_project(manifest)["status"], "already_classified")
        manifest["project"]["classification"] = "pending"
        report = classify_project(manifest)
        self.assertEqual(report["classification"], "mobile_app")
        self.assertEqual(report["status"], "recommended")

    def test_capability_report_distinguishes_active_tools_from_local_skills(self) -> None:
        manifest = self.make_android_manifest()
        inventory = discover_environment(cwd=Path(tempfile.gettempdir()), active_tools=["Android platform knowledge"])
        report = match_capabilities(manifest, inventory, self.roles)
        android = [item for item in report["role_matches"] if item["role_id"] == "android-engineer"]
        self.assertTrue(android)
        platform_match = next(item for item in android if item["requirement"] == "Android platform knowledge")
        self.assertEqual(platform_match["status"], "available")
        self.assertEqual(report["runtime"]["session_availability"], "unverified")

    def test_local_skill_metadata_does_not_verify_tool_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "skills" / "android-sdk-tools-guide"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: Android SDK Tools Guide\ndescription: Android SDK tools, Gradle, and official Android documentation.\n---\n",
                encoding="utf-8",
            )
            inventory = discover_environment(cwd=root, extra_skill_dirs=[root / "skills"])
            inventory["skills"] = [item for item in inventory["skills"] if item["name"] == "Android SDK Tools Guide"]
            inventory["agents"] = []
            inventory["tools"] = []

            report = match_capabilities(self.make_android_manifest(), inventory, self.roles)
            android = [item for item in report["role_matches"] if item["role_id"] == "android-engineer"]
            sdk_requirement = next(item for item in android if item["requirement"] == "Android SDK tools")
            self.assertEqual(sdk_requirement["requirement_type"], "tool")
            self.assertEqual(sdk_requirement["status"], "unverified")
            self.assertFalse(any("Android SDK Tools Guide" in evidence for evidence in sdk_requirement["evidence"]))

    def test_complete_inventory_marks_unmatched_capability_missing(self) -> None:
        manifest = self.make_android_manifest()
        inventory = discover_environment(cwd=Path(tempfile.gettempdir()), inventory_complete=True)
        report = match_capabilities(manifest, inventory, self.roles)
        self.assertTrue(report["runtime"]["session_inventory_complete"])
        android = [item for item in report["role_matches"] if item["role_id"] == "android-engineer"]
        self.assertTrue(any(item["status"] == "missing" for item in android))

    def test_discover_and_match_cli_accept_inventory_complete(self) -> None:
        from projectforge_lib.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["discover", "--cwd", str(root), "--inventory-complete", "--format", "json"]), 0)
            self.assertTrue(json.loads(out.getvalue())["runtime"]["session_inventory_complete"])
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(self.make_android_manifest()), encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["match", str(manifest_path), "--cwd", str(root), "--inventory-complete", "--format", "json"]), 0)
            self.assertTrue(json.loads(out.getvalue())["runtime"]["session_inventory_complete"])

    def test_examples_validate_against_current_manifest_schema(self) -> None:
        for path in sorted((ROOT / "examples").glob("*.json")):
            with self.subTest(example=path.name):
                manifest = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(validate_manifest(manifest), [])
                if path.name in {"cross-platform-application.json", "web-saas.json"}:
                    self.assertTrue(manifest["dependencies"], path.name)

    def test_discovery_and_inspection_read_metadata_without_running_skill_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill_dir = root / "skills" / "pf-isolated-test-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("---\nname: pf-isolated-test-skill\ndescription: Isolated discovery fixture.\n---\napi_key: should-not-leak\n", encoding="utf-8")
            marker = root / "script-ran"
            (skill_dir / "scripts").mkdir()
            (skill_dir / "scripts" / "setup.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n", encoding="utf-8")
            (root / ".codex" / "agents").mkdir(parents=True)
            (root / ".codex" / "agents" / "reader.toml").write_text('name="reader"\ndescription="Read only investigator"\ndeveloper_instructions="do not edit"\n', encoding="utf-8")
            (root / ".codex").mkdir(exist_ok=True)
            (root / ".codex" / "config.toml").write_text('[mcp_servers.docs]\napi_key="local-secret-do-not-print"\n', encoding="utf-8")
            inventory = discover_environment(cwd=root, extra_skill_dirs=[root / "skills"])
            rendered = json.dumps(inventory)
            self.assertIn("pf-isolated-test-skill", rendered)
            self.assertIn("reader", rendered)
            self.assertIn("docs", rendered)
            self.assertNotIn("local-secret-do-not-print", rendered)
            inspected = inspect_skill("pf-isolated-test-skill", cwd=root, extra_skill_dirs=[root / "skills"])
            self.assertIn("[REDACTED]", inspected["content"])
            self.assertFalse(marker.exists())

    def test_dependency_validator_rejects_unknown_reference_and_cycle(self) -> None:
        manifest = self.make_android_manifest()
        manifest["team"]["specialists"] = [new_assignment(self.role_map["android-engineer"]), new_assignment(self.role_map["backend-engineer"])]
        manifest["dependencies"] = [{"from": "android-engineer", "to": "backend-engineer", "kind": "blocks"}, {"from": "backend-engineer", "to": "android-engineer", "kind": "blocks"}]
        errors = validate_manifest(manifest)
        self.assertTrue(any("team dependency cycle" in error for error in errors), errors)
        manifest["dependencies"] = [{"from": "android-engineer", "to": "missing", "kind": "blocks"}]
        errors = validate_manifest(manifest)
        self.assertTrue(any("unknown" in error or "missing" in error for error in errors), errors)

    def test_dependency_resolver_orders_blocking_edges_and_keeps_informs_parallel(self) -> None:
        manifest = self.make_android_manifest()
        role_ids = ["android-engineer", "backend-engineer", "qa-test-engineer"]
        manifest["team"]["specialists"] = [new_assignment(self.role_map[role_id]) for role_id in role_ids]
        assignments = {item["id"]: item for item in manifest["team"]["specialists"]}
        assignments["android-engineer"]["prerequisites"] = ["Backend API contract"]
        assignments["qa-test-engineer"]["prerequisites"] = ["API context"]

        resolutions = [
            {"assignment_id": "android-engineer", "prerequisite": "Backend API contract", "provider_assignment_id": "backend-engineer", "kind": "blocks"},
            {"assignment_id": "qa-test-engineer", "prerequisite": "API context", "provider_assignment_id": "backend-engineer", "kind": "informs"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            resolutions_path = root / "resolutions.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            resolutions_path.write_text(json.dumps(resolutions), encoding="utf-8")

            code, output, error = self.run_cli(["resolve-dependencies", str(manifest_path), str(resolutions_path), "--apply", "--format", "json"])

            self.assertEqual(code, 0, error)
            report_start = output.index("{")
            report, _ = json.JSONDecoder().raw_decode(output[report_start:])
            self.assertTrue(report["applied"])
            unresolved = {(item["assignment_id"], item["prerequisite"]) for item in report["unresolved"]}
            self.assertNotIn(("android-engineer", "Backend API contract"), unresolved)
            self.assertNotIn(("qa-test-engineer", "API context"), unresolved)
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest(updated), [])
            self.assertEqual({edge["kind"] for edge in updated["dependencies"]}, {"blocks", "informs"})

            plan = optimize_team(updated, roles=self.roles, requested_roles=role_ids, selection_mode="manual")
            self.assertEqual(plan["schedule"], [["backend-engineer", "qa-test-engineer", "supervisor"], ["android-engineer"]])

    def test_dependency_resolver_rejects_unknown_providers_and_cycles_without_writing(self) -> None:
        manifest = self.make_android_manifest()
        role_ids = ["android-engineer", "backend-engineer"]
        manifest["team"]["specialists"] = [new_assignment(self.role_map[role_id]) for role_id in role_ids]
        assignments = {item["id"]: item for item in manifest["team"]["specialists"]}
        assignments["android-engineer"]["prerequisites"] = ["Backend API contract"]
        assignments["backend-engineer"]["prerequisites"] = ["Android implementation"]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            resolutions_path = root / "resolutions.json"
            original = json.dumps(manifest)
            manifest_path.write_text(original, encoding="utf-8")

            resolutions_path.write_text(json.dumps([{
                "assignment_id": "android-engineer", "prerequisite": "Backend API contract",
                "provider_assignment_id": "missing-provider", "kind": "blocks",
            }]), encoding="utf-8")
            code, _, error = self.run_cli(["resolve-dependencies", str(manifest_path), str(resolutions_path), "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("unknown provider_assignment_id", error)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), original)

            cycle = [
                {"assignment_id": "android-engineer", "prerequisite": "Backend API contract", "provider_assignment_id": "backend-engineer", "kind": "blocks"},
                {"assignment_id": "backend-engineer", "prerequisite": "Android implementation", "provider_assignment_id": "android-engineer", "kind": "blocks"},
            ]
            resolutions_path.write_text(json.dumps(cycle), encoding="utf-8")
            code, _, error = self.run_cli(["resolve-dependencies", str(manifest_path), str(resolutions_path), "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("team dependency cycle", error)
            self.assertEqual(manifest_path.read_text(encoding="utf-8"), original)

    def test_manifest_migration_preserves_source_and_maps_legacy_prerequisites(self) -> None:
        manifest = self.make_legacy_manifest()
        self.assertEqual(validate_manifest(manifest), [])
        source_content = json.dumps(manifest, indent=2) + "\n"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "legacy.json"
            output_path = root / "migrated.json"
            source_path.write_text(source_content, encoding="utf-8")

            code, _, error = self.run_cli(["migrate", str(source_path), "--output", str(output_path), "--dry-run"])
            self.assertEqual(code, 0, error)
            self.assertFalse(output_path.exists())

            code, _, error = self.run_cli(["migrate", str(source_path), "--output", str(output_path)])
            self.assertEqual(code, 0, error)
            migrated = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest(migrated), [])
            self.assertEqual(migrated["schema_version"], "1.2.0")
            self.assertEqual(migrated["execution"], {"protocol_version": "1.0.0", "results": []})
            assignment = migrated["team"]["specialists"][0]
            self.assertIn("reviewed API contract", assignment["prerequisites"])
            self.assertEqual(assignment["result_contract"]["completion_criteria"], assignment["acceptance_criteria"])
            self.assertEqual(source_path.read_text(encoding="utf-8"), source_content)

    def test_manifest_migration_rejects_unsupported_versions_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.json"
            output_path = root / "existing.json"
            legacy = self.make_legacy_manifest()
            source_path.write_text(json.dumps(legacy), encoding="utf-8")
            output_path.write_text("preserve", encoding="utf-8")

            code, _, error = self.run_cli(["migrate", str(source_path), "--output", str(output_path)])
            self.assertEqual(code, 2)
            self.assertIn("Refusing to overwrite", error)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "preserve")

            legacy["schema_version"] = "9.9.9"
            source_path.write_text(json.dumps(legacy), encoding="utf-8")
            code, _, error = self.run_cli(["migrate", str(source_path), "--output", str(root / "unsupported.json")])
            self.assertEqual(code, 2)
            self.assertIn("Unsupported manifest schema_version", error)

    def test_agent_result_validation_enforces_version_paths_checks_and_unique_errors(self) -> None:
        manifest = self.make_handoff_manifest()
        result = self.make_agent_result(manifest)
        self.assertEqual(validate_agent_result(result, manifest), [])

        mismatched_version = deepcopy(result)
        mismatched_version["manifest_version"] = "1.0.0"
        self.assertTrue(any("does not match manifest schema_version" in error for error in validate_agent_result(mismatched_version, manifest)))

        protected_output = deepcopy(result)
        protected_output["outputs"][0]["path"] = "src/secrets/token.txt"
        self.assertTrue(any("overlaps a protected path" in error for error in validate_agent_result(protected_output, manifest)))

        escaping_output = deepcopy(result)
        escaping_output["outputs"][0]["path"] = "../outside.txt"
        self.assertTrue(any("normalized relative POSIX path" in error for error in validate_agent_result(escaping_output, manifest)))

        missing_check = deepcopy(result)
        missing_check["validation"]["checks"] = [{"name": "Lint", "status": "passed", "evidence": ["clean"]}]
        self.assertTrue(any("required validation check 'Unit tests'" in error for error in validate_agent_result(missing_check, manifest)))

        unlinked_retry = deepcopy(result)
        unlinked_retry["attempt"] = 2
        unlinked_retry["prior_result_id"] = "unknown-result"
        self.assertTrue(any("immediately preceding recorded attempt" in error for error in validate_agent_result(unlinked_retry, manifest)))

        duplicate_check = deepcopy(result)
        duplicate_check["validation"]["checks"].append(deepcopy(duplicate_check["validation"]["checks"][0]))
        errors = validate_agent_result(duplicate_check, manifest)
        duplicate_errors = [error for error in errors if error == "validation.checks contains duplicate check names"]
        self.assertEqual(len(duplicate_errors), 1, errors)

    def test_agent_result_review_rework_retry_and_immutable_evidence_lifecycle(self) -> None:
        manifest = self.make_handoff_manifest()
        first_result = self.make_agent_result(manifest, status="completed", validation={
            "passed": False,
            "checks": [{"name": "Unit tests", "status": "failed", "evidence": ["One test failed"]}],
        })
        retry_result = self.make_agent_result(manifest, result_id="android-result-2", status="validated", attempt=2, prior_result_id="android-result-1")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            result_dir = root / "results"
            result_dir.mkdir()
            first_path = result_dir / "attempt-1.json"
            retry_path = result_dir / "attempt-2.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            first_path.write_text(json.dumps(first_result), encoding="utf-8")

            code, _, error = self.run_cli(["record-result", str(manifest_path), str(first_path), "--review", "accepted", "--reviewer", "supervisor", "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("required validation check 'Unit tests'", error)
            self.assertEqual(json.loads(manifest_path.read_text(encoding="utf-8"))["execution"]["results"], [])

            code, _, error = self.run_cli(["record-result", str(manifest_path), str(first_path), "--review", "rework_required", "--reviewer", "supervisor", "--review-notes", "Fix failing test", "--apply"])
            self.assertEqual(code, 0, error)

            retry_path.write_text(json.dumps(retry_result), encoding="utf-8")
            output = root / "src" / "auth.py"
            code, _, error = self.run_cli(["validate-result", str(manifest_path), str(retry_path)])
            self.assertEqual(code, 0, error)
            code, _, error = self.run_cli(["record-result", str(manifest_path), str(retry_path), "--review", "accepted", "--reviewer", "supervisor", "--apply"])
            self.assertEqual(code, 2)
            self.assertIn("does not exist", error)

            output.parent.mkdir()
            output.write_text("class AuthRepository: pass\n", encoding="utf-8")
            code, _, error = self.run_cli(["record-result", str(manifest_path), str(retry_path), "--review", "accepted", "--reviewer", "supervisor", "--apply"])
            self.assertEqual(code, 0, error)

            recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(validate_manifest(recorded), [])
            self.assertEqual([item["review_status"] for item in recorded["execution"]["results"]], ["rework_required", "accepted"])
            self.assertEqual(recorded["execution"]["results"][1]["prior_result_id"], "android-result-1")

            first_result["summary"] = "Tampered after recording"
            first_path.write_text(json.dumps(first_result), encoding="utf-8")
            code, _, error = self.run_cli(["validate-result", str(manifest_path), str(first_path)])
            self.assertEqual(code, 2)
            self.assertIn("has changed since it was added to the execution ledger", error)

    def test_manifest_validation_rejects_duplicate_and_missing_assignment_fields(self) -> None:
        manifest = self.make_android_manifest()
        manifest["team"]["specialists"] = [new_assignment(self.role_map["android-engineer"])]
        manifest["team"]["specialists"][0]["handoff_requirements"] = []
        manifest["team"]["specialists"][0]["responsibilities"] = []
        errors = validate_manifest(manifest)
        self.assertTrue(any("responsibilities" in error for error in errors), errors)

    def test_markdown_and_html_share_manifest_and_escape_untrusted_values(self) -> None:
        manifest = self.make_android_manifest()
        manifest["project"]["summary"] = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
        manifest["facts"] = [{"id": "note", "topic": "User note", "value": 'api_key: "highly-secret-value"', "status": "confirmed", "source": "user", "rationale": "checked"}]
        markdown = render_markdown(manifest)
        page = render_html(manifest)
        parser = DocumentParser()
        parser.feed(page)
        parser.close()
        self.assertIn("Pocket Garden", markdown)
        self.assertIn("Architecture", markdown)
        self.assertIn("data-checklist", page)
        self.assertIn("localStorage", page)
        self.assertIn("&lt;img", page)
        self.assertIn("&lt;script&gt;alert(2)", page)
        self.assertNotIn('<img src=x', page)
        self.assertNotIn("onerror=\"alert(1)", page)
        self.assertNotIn("highly-secret-value", markdown)
        self.assertNotIn("highly-secret-value", page)
        self.assertIn("Content-Security-Policy", page)

    def test_static_html_has_no_network_asset_dependencies(self) -> None:
        page = render_html(self.make_android_manifest())
        self.assertNotIn("<script src=", page)
        self.assertNotIn("<link rel=\"stylesheet\" href=", page)
        self.assertIn("@media print", page)
        self.assertIn("<details", page)

    def test_render_cli_generates_both_formats_and_dry_run_creates_nothing(self) -> None:
        from projectforge_lib.cli import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(self.make_android_manifest()), encoding="utf-8")
            output_dir = root / "generated"
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["render", str(manifest_path), "--output-dir", str(output_dir), "--format", "both"]), 0)
            markdown = output_dir / "pocket-garden-kickoff.md"
            html = output_dir / "pocket-garden-kickoff.html"
            self.assertTrue(markdown.is_file())
            self.assertTrue(html.is_file())
            self.assertIn("Team optimization estimates", markdown.read_text(encoding="utf-8"))
            page = html.read_text(encoding="utf-8")
            self.assertIn("Team optimization estimates", page)
            parser = DocumentParser()
            parser.feed(page)
            parser.close()
            preview_dir = root / "preview"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["render", str(manifest_path), "--output-dir", str(preview_dir), "--format", "both", "--dry-run"]), 0)
            self.assertFalse(preview_dir.exists())

    def test_existing_output_is_protected_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "existing.txt"
            target.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_text(target, "replace")
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            write_text(target, "replace", force=True)
            self.assertEqual(target.read_text(encoding="utf-8"), "replace")

    def test_manifest_diff_reports_areas_and_ignores_generated_timestamps(self) -> None:
        old = self.make_android_manifest()
        new = self.make_android_manifest()
        new["discovery"]["updated_at"] = "later"
        new["readiness"]["checked_at"] = "later"
        new["project"]["goals"].append("Share plant care with family")
        report = compare_manifests(old, new)
        self.assertEqual(report["change_count"], 1)
        self.assertEqual(report["affected_areas"], ["project"])

    def test_codex_agent_output_is_optional_project_scoped_and_valid_toml(self) -> None:
        from projectforge_lib.cli import main
        manifest = self.make_android_manifest()
        manifest["team"]["specialists"] = [new_assignment(self.role_map["android-engineer"])]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            target = root / "target-project"
            self.assertEqual(main(["codex-agents", str(manifest_path), "--target-dir", str(target)]), 0)
            agent_path = target / ".codex" / "agents" / "android-engineer.toml"
            parsed = tomllib.loads(agent_path.read_text(encoding="utf-8"))
            self.assertEqual(parsed["name"], "android-engineer")
            self.assertIn("Acceptance criteria", parsed["developer_instructions"])
            before = agent_path.read_text(encoding="utf-8")
            self.assertEqual(main(["codex-agents", str(manifest_path), "--target-dir", str(target)]), 2)
            self.assertEqual(agent_path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
