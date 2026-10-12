from __future__ import annotations

import contextlib
import copy
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "paperspine5/core"
sys.path.insert(0, str(ROOT / "src/scripts"))
sys.path.insert(0, str(CORE / "03_联合开发/src"))
import paperspine5_web
from paperspine_checkpoint import Checkpoint, CommandFailure, output_directory
from paperspine_figure_integration.filesystem_paths import native_path
from paperspine_figure_integration.p1_application import (
    ApplicationService,
    DomainEventStore,
    LegacyStageAdapter,
    agent_execute,
    agent_open_task,
)
from paperspine_figure_integration.product_kernel import ProductKernel


class HostCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="paperspine-checkpoint-")).resolve()
        self.addCleanup(self.cleanup)
        self.kernel = ProductKernel(self.base / "data", core_root=CORE)
        self.addCleanup(self.kernel.close)
        self.service = ApplicationService(DomainEventStore(self.base / "events.sqlite3"),
            LegacyStageAdapter(self.kernel), contracts_root=CORE / "03_联合开发/contracts")
        agent_open_task(self.service, {"schema_version": "1.1", "task_id": "test-output",
            "command_id": "open-output", "expected_version": 0,
            "payload": {"mode": "open", "requested_task_id": "test-output", "title": "Output test"}},
            principal_id="test-host")
        self.binding = {"project_root": str(CORE), "core_root": str(CORE),
                        "user_data_root": str(self.base / "data"),
                        "domain_database": str(self.base / "events.sqlite3")}
        self.output = self.base / "external-template"
        self.output.mkdir()
        (self.output / "main.tex").write_text("A complete draft.", encoding="utf-8")
        self.calls = []
        self.fail_after_publish = False
        self.syncer = Checkpoint(self.base / "profile", "test-output", self.binding, self.rpc)
        self.syncer.bind(self.output)
        self.manifest = {"stage": "draft", "summary": "Completed the draft.",
                         "files": [{"path": "main.tex", "artifact_type": "manuscript_source"}]}

    def cleanup(self):
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        shutil.rmtree(native_path(self.base))

    def rpc(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        if name == "paperspine_get_task":
            return self.service.get_task(arguments["task_id"])
        operation = {"paperspine_authorize_materials": "AuthorizeMaterials",
                     "paperspine_publish_artifact": "PublishArtifact",
                     "paperspine_commit_milestone": "CommitMilestone"}[name]
        result = agent_execute(self.service, arguments["request"], principal_id="test-host", command_type=operation)
        if self.fail_after_publish and operation == "PublishArtifact":
            self.fail_after_publish = False
            raise TimeoutError("Lost publish acknowledgement")
        return result

    def test_external_outputs_publish_and_repeat_without_mutation(self):
        result = self.syncer.sync(self.manifest)
        self.assertEqual(result["status"], "SYNCED")
        view = self.service.get_task("test-output")
        self.assertEqual(view["stage"], "draft")
        self.assertEqual(view["milestones"][-1]["artifact_ids"], result["artifact_ids"])
        self.assertEqual(len(view["artifacts"]), 1)
        self.assertEqual((self.output / "main.tex").read_text(), "A complete draft.")
        version = view["task_version"]
        self.syncer.sync(self.manifest)
        self.assertEqual(self.service.get_task("test-output")["task_version"], version)
        self.assertEqual(output_directory(self.base / "profile", "test-output", self.binding), str(self.output))

    def test_changed_file_publishes_new_version_without_reauthorizing(self):
        original = self.syncer.sync(self.manifest)
        (self.output / "main.tex").write_text("Revised draft.", encoding="utf-8")
        changed = self.syncer.sync(self.manifest)
        self.assertNotEqual(original["artifact_ids"], changed["artifact_ids"])
        self.assertEqual(sum(name == "paperspine_authorize_materials" for name, _ in self.calls), 1)
        view = self.service.get_task("test-output")
        old = next(item for item in view["artifacts"] if item["artifact_id"] == original["artifact_ids"][0])
        self.assertTrue(old["stale"])

    def test_lost_ack_replays_same_command_and_does_not_duplicate(self):
        self.fail_after_publish = True
        with self.assertRaises(TimeoutError):
            self.syncer.sync(self.manifest)
        pending = self.syncer.load()["pending"]
        resumed = Checkpoint(self.base / "profile", "test-output", self.binding, self.rpc)
        result = resumed.sync(self.manifest)
        publish_calls = [arguments for name, arguments in self.calls if name == "paperspine_publish_artifact"]
        self.assertEqual(len(publish_calls), 2)
        self.assertEqual(publish_calls[0], publish_calls[1])
        self.assertEqual(pending["arguments"], publish_calls[1])
        self.assertEqual(len(self.service.get_task("test-output")["artifacts"]), 1)
        self.assertEqual(result["status"], "SYNCED")

    def test_partial_publish_can_resume(self):
        (self.output / "notes.txt").write_text("Evidence checked.", encoding="utf-8")
        self.manifest["files"].append({"path": "notes.txt", "artifact_type": "research_note"})
        original_rpc = self.syncer.rpc
        def failing_rpc(name, arguments):
            if name == "paperspine_publish_artifact" and arguments["request"]["payload"]["artifact_type"] == "research_note":
                raise TimeoutError("Second file unavailable")
            return original_rpc(name, arguments)
        self.syncer.rpc = failing_rpc
        with self.assertRaises(TimeoutError):
            self.syncer.sync(self.manifest)
        self.assertEqual(len(self.syncer.completed), 1)
        self.assertNotEqual(self.service.get_task("test-output")["stage"], "draft")
        result = Checkpoint(self.base / "profile", "test-output", self.binding, self.rpc).sync(self.manifest)
        self.assertEqual(len(result["artifact_ids"]), 2)
        self.assertEqual(len(self.service.get_task("test-output")["artifacts"]), 2)

    def test_version_conflict_is_reported_and_next_explicit_run_uses_latest_version(self):
        original_rpc = self.syncer.rpc
        def conflicting_rpc(name, arguments):
            if name == "paperspine_authorize_materials":
                raise CommandFailure({"code": "version_conflict", "message": "Task changed"})
            return original_rpc(name, arguments)
        self.syncer.rpc = conflicting_rpc
        with self.assertRaises(CommandFailure):
            self.syncer.sync(self.manifest)
        self.assertNotIn("pending", self.syncer.load())
        self.syncer.rpc = original_rpc
        self.assertEqual(self.syncer.sync(self.manifest)["status"], "SYNCED")

    def test_invalid_files_and_wrong_store_do_not_write_task(self):
        version = self.service.get_task("test-output")["task_version"]
        for relative in ("../outside.tex", "C:/outside.tex", "missing.tex"):
            self.manifest["files"][0]["path"] = relative
            with self.assertRaises((ValueError, OSError)):
                self.syncer.sync(self.manifest)
        self.assertEqual(self.service.get_task("test-output")["task_version"], version)
        other = Checkpoint(self.base / "profile", "test-output",
                           {**self.binding, "domain_database": str(self.base / "other.db")}, self.rpc)
        with self.assertRaisesRegex(ValueError, "different task store"):
            other.load()

    def test_sources_figures_and_render_are_visible_and_reused(self):
        (self.output / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"test-figure")
        (self.output / "main.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        # Deliberately put PDF first; helper must publish render after source/figure.
        self.manifest["files"] = [
            {"path": "main.pdf", "artifact_type": "pdf"},
            {"path": "figure.png", "artifact_type": "figure"},
            {"path": "main.tex", "artifact_type": "manuscript_source"},
        ]
        result = self.syncer.sync(self.manifest)
        self.assertEqual(len(result["artifact_ids"]), 3)
        self.assertFalse(any(a.get("stale") for a in self.service.get_task("test-output")["artifacts"]))
        version = result["task_version"]
        self.assertEqual(self.syncer.sync(self.manifest)["task_version"], version)

    def test_cli_requires_explicit_profile_task_and_manifest(self):
        with patch.object(sys, "argv", ["paperspine5_web.py", "host", "checkpoint",
                                       "--profile-root", str(self.base / "profile"),
                                       "--task-id", "test-output", "--manifest", "-"]):
            args = paperspine5_web.parse_args()
        self.assertEqual(args.host_command, "checkpoint")
        self.assertEqual(args.manifest, "-")
        with patch.object(sys, "argv", ["paperspine5_web.py", "host", "checkpoint",
                                       "--task-id", "test-output", "--manifest", "-"]), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            paperspine5_web.parse_args()


if __name__ == "__main__":
    unittest.main()
