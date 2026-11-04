from __future__ import annotations

import json
import contextlib
import io
import sys
import tempfile
import tomllib
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from projectforge_lib.changes import compare_manifests
from projectforge_lib.common import catalog, new_assignment, new_manifest, write_text
from projectforge_lib.discovery import discover_environment, inspect_skill, match_capabilities
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
