"""Relative report paths must work with offline artifacts, as in Actions."""
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("robustness_report_paths", ROOT / "scripts/report_robustness_v2.py")
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


@contextlib.contextmanager
def working_directory(path):
    previous = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


def unit_plan():
    return {"plan_id": "unit-path-regression", "source_sha256": "0" * 64,
            "models": [{"model_id": "unit", "tag": "unit:1", "manifest_digest": "sha256:" + "1" * 64}],
            "methods": ["one-shot"], "conditions": ["clean"],
            "cases": [{"id": "unit-case", "family": "unit-family", "expected": "repair"}],
            "controls": ["noop"], "images": {"base": "python@sha256:" + "2" * 64},
            "cells": [{"model_id": "unit", "method_id": "one-shot", "case_id": "unit-case", "condition": "clean", "repetition": 0}]}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class RelativeArtifactPathsTests(unittest.TestCase):
    def test_build_summary_reads_record_from_relative_shard(self):
        plan = unit_plan()
        with tempfile.TemporaryDirectory() as directory:
            shard = Path(directory) / "shard"
            write_json(shard / "plan.json", plan)
            write_json(shard / "records/unit.json", plan["cells"][0])
            result = {"outcome": "task_failure", "evidence_verified": True,
                      "task_correct": False, "model_origin_verified": False, "metrics": {}, "evidence_error": None}
            with working_directory(directory):
                summary = reporter.build_summary(plan, [Path("shard")], auditor=lambda *_: result)
            self.assertEqual(summary["coverage"]["observed_trials"], 1)
            self.assertEqual(summary["coverage"]["missing_trials"], 0)

    def test_control_audit_uses_relative_artifact_directory(self):
        # Only trusted evaluation boundaries are mocked. Real directory traversal,
        # inventory loading, hashes, registry matching and group aggregation run.
        plan = unit_plan()
        with tempfile.TemporaryDirectory() as directory:
            shard = Path(directory) / "reference"
            write_json(shard / "plan.json", plan)
            write_json(shard / "summary.json", {"stage": "validate", "plan_id": plan["plan_id"], "source_sha256": plan["source_sha256"]})
            write_json(shard / "commands.json", [])
            write_json(shard / "setup-image-verification.json", {"passed": True})
            setup_hash = hashlib.sha256((shard / "setup-image-verification.json").read_bytes()).hexdigest()
            write_json(shard / "image-pins.json", {"base_image": plan["images"]["base"],
                       "fixture_image": "robustness-python:" + "2" * 12, "setup_verification_sha256": setup_hash})
            write_json(shard / "controls/unit-case--noop.json", {"case_id": "unit-case", "control_id": "noop"})
            result = {"outcome": "task_failure", "evidence_verified": True, "runtime_pass": False, "error": None}
            with working_directory(directory), patch("kube_robustness.protocol.validate_plan"), \
                    patch.object(reporter, "verify_image_setup") as setup, \
                    patch.object(reporter, "audit_control_record", return_value=result):
                audit = reporter.audit_controls(plan, Path("reference"))
            self.assertEqual(len(audit["rows"]), 1)
            self.assertEqual(audit["groups"][0]["verified_cases"], 1)
            self.assertEqual(setup.call_args.args[1], shard.resolve())

    def test_actual_cli_relative_paths_reports_invalid_unit_evidence_without_crashing(self):
        # No model/cluster fixture is fabricated. The incomplete unit record must
        # stay invalid evidence while the real CLI completes its path handling.
        plan = unit_plan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "plan.json", plan)
            write_json(root / "shard/plan.json", plan)
            write_json(root / "shard/records/unit.json", {**plan["cells"][0], "status": "completed", "task_correct": True})
            process = subprocess.run([sys.executable, str(ROOT / "scripts/report_robustness_v2.py"),
                                      "--plan", "plan.json", "--shard", "shard", "--output", "report"],
                                     cwd=root, capture_output=True, text=True,
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            summary = json.loads((root / "report/summary.json").read_text())
            self.assertEqual(summary["coverage"]["observed_trials"], 1)
            self.assertEqual(summary["coverage"]["invalid_evidence_trials"], 1)
            self.assertEqual(summary["coverage"]["task_correct_trials"], 0)


if __name__ == "__main__":
    unittest.main()
