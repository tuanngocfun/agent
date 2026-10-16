"""Namespace-only audit amendment checks; synthetic fixtures are not experiments."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from kube_robustness_v3.cases import all_cases
from kube_robustness_v3.runtime import KubernetesSession


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


original = load("frozen_v3_prefix_regression", "report_robustness_v3.py")
amended = load("amended_v3_prefix_regression", "audit_robustness_v3_evidence.py")


class NamespaceAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.case = next(row for row in all_cases() if row["id"] == "already-secure-cache")
        self.frozen = {"plan_id": "synthetic-unit-plan", "source_sha256": "0" * 64,
                       "images": {"base": "python@sha256:" + "2" * 64},
                       "controls": ["noop", "oracle"], "cases": [copy.deepcopy(self.case)]}
        self.frozen["cases"][0]["definition_sha256"] = amended.digest(self.case)
        self.image = "robustness-python:" + "2" * 12
        # Constructing a session selects the actual runtime prefix but executes
        # no commands. Every network/subprocess operation would be unexpected.
        session = KubernetesSession(self.case, kubectl="unused", context="unit",
                                    kubeconfig="unused", image=self.image, commands=[])
        self.namespace = session.namespace
        self.assertTrue(self.namespace.startswith("robust-v3-"))
        self.assertFalse(session.created)
        self.assertEqual(session.commands, [])

    def test_amendment_changes_exactly_three_prefix_guards_plus_marked_metadata(self):
        frozen = (ROOT / "scripts/report_robustness_v3.py").read_text()
        current = (ROOT / "scripts/audit_robustness_v3_evidence.py").read_text()
        begin = "\n\n# BEGIN EXPLICIT POSTHOC AUDITOR AMENDMENT V3.1\n"
        end = "# END EXPLICIT POSTHOC AUDITOR AMENDMENT V3.1\n"
        before, block = current.split(begin)
        _, after = block.split(end)
        self.assertEqual(frozen.count('"robust-v2-"'), 3)
        self.assertEqual(before + after, frozen.replace('"robust-v2-"', '"robust-v3-"'))

    def test_actual_runtime_setup_prefix_passes_guard_but_cannot_skip_image_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "setup-image-verification.json"
            for namespace in (self.namespace, "robust-v2-unit", "arbitrary-unit"):
                with self.subTest(namespace=namespace):
                    path.write_text(json.dumps({"runtime": {"namespace": namespace}, "passed": True}))
                    documents = {"commands": [], "image_pins": {
                        "setup_case_id": self.case["id"],
                        "setup_verification_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
                    with self.assertRaisesRegex(ValueError, "owned namespace"):
                        if namespace == self.namespace:
                            original.verify_image_setup(self.frozen, Path(directory), documents)
                        else:
                            amended.verify_image_setup(self.frozen, Path(directory), documents)
                    if namespace == self.namespace:
                        with self.assertRaisesRegex(ValueError, "frozen base image"):
                            amended.verify_image_setup(self.frozen, Path(directory), documents)

    def test_actual_runtime_control_prefix_cannot_skip_cleanup_proof(self):
        resources = amended.instantiate(self.case, self.namespace, self.image)["resources"]
        record = {"case_id": self.case["id"], "control_id": "noop", "expected": "unchanged",
                  "reference_only": False, "model_inference_observed": False,
                  "resources": resources, "verification": {"passed": True, "runtime": {"namespace": self.namespace}}}
        old = original.audit_control_record(self.frozen, record, Path("unused"), {})
        new = amended.audit_control_record(self.frozen, record, Path("unused"), {})
        self.assertIn("owned trial namespace", old["error"])
        self.assertIn("namespace cleanup", new["error"])
        self.assertFalse(new["evidence_verified"])
        self.assertFalse(new["runtime_pass"])
        record["verification"]["runtime"]["namespace"] = "robust-v2-unit"
        self.assertIn("owned trial namespace", amended.audit_control_record(self.frozen, record, Path("unused"), {})["error"])

    def test_actual_runtime_model_prefix_cannot_skip_initial_candidate_hash(self):
        record = {"schema_version": "robustness-v3-record-v1", "plan_id": self.frozen["plan_id"],
                  "source_sha256": self.frozen["source_sha256"], "status": "completed", "expected": "unchanged",
                  "case_id": self.case["id"], "case_definition_sha256": amended.digest(self.case),
                  "namespace": self.namespace, "fixture_image": self.image, "task_correct": True}
        with patch("kube_robustness_v3.protocol.validate_plan", return_value=None):
            old = original.audit_record(self.frozen, record, Path("unused"))
            new = amended.audit_record(self.frozen, record, Path("unused"))
            self.assertIn("Namespace or pinned fixture", old["evidence_error"])
            self.assertIn("Initial manifest hash", new["evidence_error"])
            self.assertFalse(new["task_correct"])
            self.assertFalse(new["evidence_verified"])
            record["namespace"] = "robust-v2-unit"
            self.assertIn("Namespace or pinned fixture", amended.audit_record(self.frozen, record, Path("unused"))["evidence_error"])

    def test_amendment_metadata_binds_both_scripts_and_declares_posthoc_scope(self):
        metadata = amended.audit_amendment_metadata()
        self.assertEqual(metadata["phase"], "posthoc_offline_audit")
        self.assertEqual(metadata["correction"]["guard_count"], 3)
        self.assertEqual(metadata["frozen_reporter_sha256"], amended.FROZEN_REPORTER_SHA256)
        self.assertEqual(metadata["amended_auditor_sha256"], hashlib.sha256((ROOT / "scripts/audit_robustness_v3_evidence.py").read_bytes()).hexdigest())
        for key in ("execution_plan_modified", "frozen_execution_source_modified", "raw_execution_artifacts_modified", "models_or_kubernetes_executed_by_auditor"):
            self.assertIs(metadata[key], False)
        with patch.object(amended, "FROZEN_REPORTER_SHA256", "0" * 64):
            with self.assertRaisesRegex(ValueError, "Frozen original reporter differs"):
                amended.audit_amendment_metadata()


if __name__ == "__main__":
    unittest.main()
