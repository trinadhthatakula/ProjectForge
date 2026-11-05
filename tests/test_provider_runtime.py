from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from projectforge_lib.common import new_manifest
from projectforge_lib.provider_runtime import (
    MAX_RESPONSE_BYTES,
    _RejectRedirects,
    _call_claude_cli,
    _call_http_provider,
    _gemini_schema_subset,
    _openai_schema_subset,
    _parse_envelope,
    request_assignment,
    response_schema,
    write_assignment_outputs,
)
from projectforge_lib.validation import validate_manifest


class FakeResponse:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


class ProviderRuntimeTests(unittest.TestCase):
    def make_manifest(self) -> dict:
        manifest = new_manifest("Provider Adapter Test")
        manifest["team"]["supervisor"]["result_contract"]["allowed_paths"] = ["src/"]
        manifest["project"]["summary"] = "Synthetic provider integration test."
        self.assertEqual(validate_manifest(manifest), [])
        return manifest

    def make_result(self, manifest: dict) -> dict:
        return {
            "protocol_version": "1.0.0",
            "result_id": "provider-adapter-test-001",
            "assignment_id": "supervisor",
            "manifest_version": manifest["schema_version"],
            "status": "completed",
            "summary": "Prepared the requested provider-neutral response.",
            "outputs": [{"path": "src/agent-note.md", "description": "Generated agent note"}],
            "evidence": ["No local checks were run."],
            "validation": {"passed": False, "checks": []},
            "unresolved_questions": [],
            "risks": [],
            "assumptions": [],
            "handoff_notes": "Ready for supervisor review.",
            "attempt": 1,
            "prior_result_id": None,
            "created_at": "2026-11-05T00:00:00Z",
        }

    def test_response_schema_wraps_the_shared_result_and_artifact_contract(self) -> None:
        schema = response_schema()
        self.assertEqual(schema["required"], ["result", "artifacts"])
        self.assertEqual(schema["properties"]["result"]["properties"]["protocol_version"]["const"], "1.0.0")
        self.assertFalse(schema["additionalProperties"])

    def test_request_rejects_provider_options_that_would_be_ignored(self) -> None:
        manifest = self.make_manifest()
        common = {
            "manifest": manifest,
            "manifest_path": Path("/tmp/projectforge-manifest.json"),
            "assignment_id": "supervisor",
            "task": "A synthetic request",
            "model": "test-model",
        }
        with self.assertRaisesRegex(ValueError, "only valid for the openai-compatible provider"):
            request_assignment(**common, provider="openai", base_url="https://example.test")
        with self.assertRaisesRegex(ValueError, "authentication is managed by the local CLI"):
            request_assignment(**common, provider="claude-cli", api_key_env="ANTHROPIC_API_KEY")

    def test_provider_schema_adapters_translate_nullable_and_const_keywords(self) -> None:
        schema = response_schema()
        result_schema = schema["properties"]["result"]
        openai_result = _openai_schema_subset(result_schema)
        gemini_result = _gemini_schema_subset(result_schema)
        self.assertEqual(openai_result["properties"]["protocol_version"]["enum"], ["1.0.0"])
        self.assertEqual(
            openai_result["properties"]["prior_result_id"]["anyOf"],
            [{"type": "string"}, {"type": "null"}],
        )
        self.assertEqual(gemini_result["properties"]["protocol_version"]["enum"], ["1.0.0"])
        self.assertEqual(gemini_result["properties"]["prior_result_id"]["type"], "string")
        self.assertTrue(gemini_result["properties"]["prior_result_id"]["nullable"])

    def test_provider_response_text_shapes_and_envelope_parsing(self) -> None:
        manifest = self.make_manifest()
        result = self.make_result(manifest)
        envelope = {"result": result, "artifacts": [{"path": "src/agent-note.md", "content": "Generated note."}]}
        text = json.dumps(envelope)
        self.assertEqual(_parse_envelope(text), envelope)
        self.assertEqual(_parse_envelope("```json\n" + text + "\n```"), envelope)
        with self.assertRaisesRegex(ValueError, "exactly 'result' and 'artifacts'"):
            _parse_envelope(json.dumps({**envelope, "provider": "extra"}))

    def test_http_adapters_use_provider_auth_headers_and_normalize_responses(self) -> None:
        responses = {
            "openai": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]},
            "anthropic": {"content": [{"type": "text", "text": "{}"}]},
            "gemini": {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
            "openai-compatible": {"choices": [{"message": {"content": "{}"}}]},
        }
        credentials = {
            "OPENAI_API_KEY": "openai-test-secret",
            "ANTHROPIC_API_KEY": "anthropic-test-secret",
            "GOOGLE_API_KEY": "google-test-secret",
            "GEMINI_API_KEY": "gemini-test-secret",
            "PROJECTFORGE_OPENAI_COMPATIBLE_API_KEY": "compatible-test-secret",
        }
        for provider, payload in responses.items():
            with self.subTest(provider=provider), patch.dict(os.environ, credentials, clear=False):
                captured = {}

                def fake_urlopen(request, timeout):
                    captured["url"] = request.full_url
                    captured["headers"] = request.headers
                    captured["body"] = json.loads(request.data.decode("utf-8"))
                    return FakeResponse(payload)

                opener = type("FakeOpener", (), {"open": staticmethod(fake_urlopen)})()
                with patch("projectforge_lib.provider_runtime.urllib.request.build_opener", return_value=opener):
                    kwargs = {"base_url": "https://models.example.test/v1"} if provider == "openai-compatible" else {}
                    text = _call_http_provider(provider, "model-test", "prompt", 512, **kwargs)
                self.assertEqual(text, "{}")
                self.assertNotIn("test-secret", captured["url"])
                if provider == "gemini":
                    self.assertEqual(captured["headers"]["X-goog-api-key"], credentials["GEMINI_API_KEY"])
                    self.assertIn(":generateContent", captured["url"])
                elif provider == "anthropic":
                    self.assertEqual(captured["headers"]["X-api-key"], credentials["ANTHROPIC_API_KEY"])
                    self.assertEqual(captured["headers"]["Anthropic-version"], "2023-06-01")
                elif provider == "openai":
                    self.assertEqual(captured["url"], "https://api.openai.com/v1/responses")
                    self.assertEqual(captured["body"]["text"]["format"]["type"], "json_schema")
                else:
                    self.assertEqual(captured["url"], "https://models.example.test/v1/chat/completions")

    def test_request_assignment_validates_artifacts_against_assignment_paths(self) -> None:
        manifest = self.make_manifest()
        envelope = {"result": self.make_result(manifest), "artifacts": [{"path": "src/agent-note.md", "content": "Generated note."}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            context_path = root / "README.md"
            context_path.write_text("api_key: fake-context-secret\nProject notes", encoding="utf-8")
            with patch("projectforge_lib.provider_runtime._call_http_provider", return_value=json.dumps(envelope)) as call:
                result, artifacts = request_assignment(
                    manifest=manifest,
                    manifest_path=manifest_path,
                    assignment_id="supervisor",
                    task="Create a short note.",
                    provider="openai",
                    model="mock-model",
                    context_files=[Path("README.md")],
                )
            self.assertEqual(result["result_id"], envelope["result"]["result_id"])
            self.assertEqual(artifacts, envelope["artifacts"])
            sent_prompt = call.call_args.args[2]
            self.assertIn("[REDACTED]", sent_prompt)
            self.assertNotIn("fake-context-secret", sent_prompt)

    def test_provider_http_adapter_rejects_redirects(self) -> None:
        handler = _RejectRedirects()
        request = __import__("urllib.request").request.Request("https://provider.example.test/endpoint")
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "https://attacker.example.test/"))

    def test_provider_http_adapter_bounds_response_body(self) -> None:
        class OversizedResponse(FakeResponse):
            def read(self, limit: int = -1) -> bytes:
                return b" " * (MAX_RESPONSE_BYTES + 1)

        opener = type("FakeOpener", (), {"open": staticmethod(lambda request, timeout: OversizedResponse({}))})()
        with patch("projectforge_lib.provider_runtime.urllib.request.build_opener", return_value=opener), patch(
            "projectforge_lib.provider_runtime._api_key", return_value="test-only-key"
        ):
            with self.assertRaisesRegex(RuntimeError, "safety limit"):
                _call_http_provider(
                    "openai", "model-test", "prompt", 512,
                    api_key_env="TEST_PROVIDER_API_KEY",
                )

    def test_claude_cli_uses_safe_ephemeral_structured_call(self) -> None:
        envelope_text = '{"result":{},"artifacts":[]}'

        def fake_run(command, **kwargs):
            self.assertIn("--safe-mode", command)
            self.assertIn("--no-session-persistence", command)
            self.assertEqual(command[command.index("--tools") + 1], "")
            schema = json.loads(command[command.index("--json-schema") + 1])
            self.assertEqual(schema["required"], ["result", "artifacts"])
            self.assertEqual(kwargs["input"], "synthetic prompt")
            self.assertNotIn("synthetic prompt", command)
            self.assertTrue(kwargs["cwd"].is_dir())
            return __import__("subprocess").CompletedProcess(command, 0, envelope_text, "")

        with patch("projectforge_lib.provider_runtime.shutil.which", return_value="/usr/bin/claude"), patch(
            "projectforge_lib.provider_runtime.subprocess.run", side_effect=fake_run
        ):
            self.assertEqual(_call_claude_cli("sonnet", "synthetic prompt"), envelope_text)

    def test_claude_cli_reports_safe_model_access_error_without_provider_text(self) -> None:
        failure = __import__("subprocess").CompletedProcess(
            ["claude"], 1,
            "There's an issue with the selected model; secret-like provider details are suppressed.",
            "",
        )
        with patch("projectforge_lib.provider_runtime.shutil.which", return_value="/usr/bin/claude"), patch(
            "projectforge_lib.provider_runtime.subprocess.run", return_value=failure
        ):
            with self.assertRaisesRegex(RuntimeError, "model is unavailable or this account is not authorized") as caught:
                _call_claude_cli("unknown-model", "synthetic prompt")
        self.assertNotIn("secret-like", str(caught.exception))

    def test_context_files_reject_secret_paths_and_parent_escape(self) -> None:
        manifest = self.make_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            (root / ".env.local").write_text("not actually a secret", encoding="utf-8")
            (root / "linked-context.txt").symlink_to(root / ".env.local")
            with patch("projectforge_lib.provider_runtime._call_http_provider"):
                with self.assertRaisesRegex(ValueError, "Sensitive context paths"):
                    request_assignment(
                        manifest=manifest, manifest_path=manifest_path, assignment_id="supervisor",
                        task="Inspect context", provider="openai", model="mock",
                        context_files=[Path(".env.local")],
                    )
                with self.assertRaisesRegex(ValueError, "Unsafe context path"):
                    request_assignment(
                        manifest=manifest, manifest_path=manifest_path, assignment_id="supervisor",
                        task="Inspect context", provider="openai", model="mock",
                        context_files=[Path("../outside.txt")],
                    )
                with self.assertRaisesRegex(ValueError, "symbolic links"):
                    request_assignment(
                        manifest=manifest, manifest_path=manifest_path, assignment_id="supervisor",
                        task="Inspect context", provider="openai", model="mock",
                        context_files=[Path("linked-context.txt")],
                    )

    def test_output_writer_preserves_result_files_and_requires_explicit_artifact_overwrite(self) -> None:
        manifest = self.make_manifest()
        result = self.make_result(manifest)
        artifacts = [{"path": "src/agent-note.md", "content": "first version"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text("{}", encoding="utf-8")
            (root / "src").mkdir()
            existing = root / "src" / "agent-note.md"
            existing.write_text("existing version", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "--force-artifacts"):
                write_assignment_outputs(
                    manifest_path=manifest_path,
                    result_output=Path(".projectforge/results/result.json"),
                    result=result,
                    artifacts=artifacts,
                )
            result_file, written = write_assignment_outputs(
                manifest_path=manifest_path,
                result_output=Path(".projectforge/results/result.json"),
                result=result,
                artifacts=artifacts,
                force_artifacts=True,
            )
            self.assertEqual(result_file, ".projectforge/results/result.json")
            self.assertEqual(written, ["src/agent-note.md"])
            self.assertEqual(existing.read_text(encoding="utf-8"), "first version")
            self.assertEqual(json.loads((root / result_file).read_text(encoding="utf-8"))["result_id"], result["result_id"])
            with self.assertRaisesRegex(FileExistsError, "Refusing to overwrite result file"):
                write_assignment_outputs(
                    manifest_path=manifest_path,
                    result_output=Path(result_file),
                    result=result,
                    artifacts=[],
                )


if __name__ == "__main__":
    unittest.main()
