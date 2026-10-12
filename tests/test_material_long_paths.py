from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "paperspine5/core/03_联合开发/src"))
from paperspine_figure_integration.filesystem_paths import native_path
from paperspine_figure_integration.product_kernel import ContractError, _build_material_grant
from paperspine_figure_integration.product_runner import ProductRunner


class MaterialLongPathTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="paperspine-paths-")).resolve()
        self.addCleanup(self.cleanup)
        self.runner = ProductRunner.__new__(ProductRunner)
        self.runner.max_files, self.runner.max_total_bytes = 100, 1024 * 1024
        self.runner.expected_build_id = "test-build"

    def cleanup(self):
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        shutil.rmtree(native_path(self.base))

    def task(self, long):
        run_root = self.base / "run"
        if long:
            run_root /= "r" * 80
            run_root /= "s" * 80
        return {"task_id": "test", "run_root": str(run_root), "created_at": "2026-01-01T00:00:00Z",
                "state": {}, "material_grants": []}

    def test_long_source_and_destination_scan_and_deduplicate(self):
        root = self.base / ("a" * 80) / ("b" * 80) / ("c" * 80)
        native_path(root).mkdir(parents=True)
        source = root / "data.csv"
        native_path(source).write_bytes(b"x,y\n1,2\n")
        task = self.task(True)
        task["material_grants"] = [_build_material_grant(root, 1, task["created_at"])]
        inventory = self.runner._scan_materials(task, revision=1, command_id="first")
        self.assertEqual(inventory["scan_issues"], [])
        self.assertEqual(inventory["source_count"], 1)
        item = inventory["entries"][0]
        destination = Path(task["run_root"]) / item["object_path"]
        self.assertGreater(len(str(source)), 260)
        self.assertGreater(len(str(destination)), 260)
        self.assertEqual(native_path(destination).read_bytes(), b"x,y\n1,2\n")
        self.assertFalse(item["object_path"].startswith("\\\\?"))
        repeated = self.runner._scan_materials(task, revision=2, command_id="second")
        self.assertEqual(repeated["snapshot_sha256"], inventory["snapshot_sha256"])
        self.assertEqual(repeated["entries"], inventory["entries"])
        self.assertEqual(list(native_path(Path(task["run_root"]) / "runner/.staging").rglob("*.pending")), [])

    def test_failed_replace_cleans_pending_file(self):
        source = self.base / "input.txt"
        source.write_bytes(b"source")
        task = self.task(True)
        with patch("paperspine_figure_integration.product_runner.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaisesRegex(OSError, "replace failed"):
                self.runner._ingest_object(task, source, command_id="failure", source_key="input")
        self.assertEqual(list(native_path(Path(task["run_root"]) / "runner/.staging").rglob("*.pending")), [])
        self.assertEqual(source.read_bytes(), b"source")

    def test_short_paths_and_conflicting_existing_object(self):
        source = self.base / "input.txt"
        source.write_bytes(b"source")
        task = self.task(False)
        digest, size, relative = self.runner._ingest_object(task, source, command_id="short", source_key="input")
        self.assertEqual(digest, hashlib.sha256(b"source").hexdigest())
        self.assertEqual(size, 6)
        destination = Path(task["run_root"]) / relative
        destination.write_bytes(b"broken")
        with self.assertRaises(ContractError):
            self.runner._ingest_object(task, source, command_id="conflict", source_key="input")
        self.assertEqual(list((Path(task["run_root"]) / "runner/.staging").rglob("*.pending")), [])

    def test_reconcile_long_objects_keeps_committed_bytes(self):
        source = self.base / "input.txt"
        source.write_bytes(b"committed")
        task = self.task(True)
        _, _, committed = self.runner._ingest_object(task, source, command_id="kept", source_key="input")
        source.write_bytes(b"orphan")
        _, _, orphan = self.runner._ingest_object(task, source, command_id="orphan", source_key="input")
        self.runner.kernel = SimpleNamespace(
            get_task=lambda task_id: task,
            list_artifacts=lambda task_id: [{"receipt": {"path": "runner/artifacts/ledger.json",
                                                       "artifact_type": "materials.source-ledger"},
                                            "payload": {"entries": [{"object_path": committed}]}}])
        report = self.runner.reconcile_orphans("test")
        self.assertEqual(report["orphan_objects"], [str(Path(task["run_root"]) / orphan)])
        applied = self.runner.reconcile_orphans("test", apply=True)
        self.assertEqual(applied["deleted_count"], 1)
        self.assertEqual(native_path(Path(task["run_root"]) / committed).read_bytes(), b"committed")
        self.assertFalse(native_path(Path(task["run_root"]) / orphan).exists())


if __name__ == "__main__":
    unittest.main()
