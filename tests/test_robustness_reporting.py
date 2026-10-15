"""Adversarial checks for report denominators, raw usage and decision provenance."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("report_robustness_v2", ROOT / "scripts/report_robustness_v2.py")
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)
from kube_robustness.methods import run_method


def plan(repetitions=1):
    models = [{"model_id": "test-model", "tag": "unit-test-model:1", "manifest_digest": "sha256:" + "1" * 64}]
    methods = ["one-shot", "feedback"]
    cases = [{"id": "case-a", "family": "family-one", "expected": "repair"},
             {"id": "case-b", "family": "family-two", "expected": "repair"}]
    cells = [{"model_id": model["model_id"], "method_id": method, "case_id": case["id"],
              "condition": condition, "repetition": repetition}
             for model in models for method in methods for case in cases
             for condition in ("clean", "injection") for repetition in range(repetitions)]
    return {"plan_id": "unit-test-plan", "source_sha256": "0" * 64, "models": models,
            "methods": methods, "cases": cases, "conditions": ["clean", "injection"], "cells": cells,
            "images": {"base": "python@sha256:" + "2" * 64}}


def trial(cell, *, correct=True, verified=True, outcome=None):
    return {**cell, "evidence_verified": verified, "model_origin_verified": verified,
            "task_correct": correct and verified, "outcome": outcome or ("correct" if correct else "task_failure"),
            "observed_status": "completed", "metrics": {"wall_seconds": 2.5 if verified else None}, "evidence_error": None}


def raw_response(decision=None, **updates):
    value = {"model": "unit-test-model:1", "done": True, "done_reason": "stop",
             "message": {"content": json.dumps(decision or {"action": "finish", "edits": [], "reason": "unit-test response"})},
             "prompt_eval_count": 11, "eval_count": 7, "eval_duration": 100_000_001,
             "total_duration": 200_000_002}
    value.update(updates)
    return json.dumps(value)


class UnitProvider:
    model = "unit-test-model:1"
    def __init__(self, responses):
        self.responses = iter(responses)
    def __call__(self, messages, schema):
        return next(self.responses)


def method_fixture(method="one-shot", responses=None):
    case = {"instruction": "Keep the unit-test flag false.",
            "resources": [{"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "example"}, "data": {"flag": True}}],
            "allowed_paths": {"ConfigMap/example": ["/data/flag"]}}
    provider = UnitProvider(responses or [raw_response()] * (1 if method == "one-shot" else 2))
    feedback = {"passed": False, "reason": "unit-test failure"}
    return case, run_method(case, method, provider, verify=lambda resources: copy.deepcopy(feedback))


class PlanAndDenominatorTests(unittest.TestCase):
    def test_repeated_and_injected_runs_do_not_increase_case_denominator(self):
        frozen = plan(repetitions=3)
        summary = reporter.aggregate(frozen, [trial(cell) for cell in frozen["cells"]])
        self.assertEqual(len(frozen["cells"]), 24)
        self.assertEqual(len(summary["groups"]), 4)
        for group in summary["groups"]:
            self.assertEqual(group["case_success"]["cases"], 2)
            self.assertEqual(group["case_success"]["successes"], 2)
            self.assertEqual(group["registered_trials"], 6)

    def test_one_missing_repeat_prevents_stable_case_success(self):
        frozen = plan(repetitions=2)
        rows = [trial(cell) for cell in frozen["cells"]]
        selected = next(row for row in rows if row["method_id"] == "one-shot" and row["condition"] == "clean" and row["case_id"] == "case-a")
        selected.update(task_correct=False, evidence_verified=False, outcome="missing", metrics={})
        group = next(row for row in reporter.aggregate(frozen, rows)["groups"] if row["method_id"] == "one-shot" and row["condition"] == "clean")
        self.assertEqual(group["case_success"]["successes"], 1)
        self.assertEqual(group["case_success"]["cases"], 2)

    def test_invalid_metrics_do_not_count_as_trusted_measurements(self):
        frozen = plan()
        rows = [trial(cell) for cell in frozen["cells"]]
        rows[0].update(evidence_verified=False, task_correct=False, outcome="invalid_evidence", metrics={"wall_seconds": 1000000})
        group = next(row for row in reporter.aggregate(frozen, rows)["groups"] if row["method_id"] == rows[0]["method_id"] and row["condition"] == rows[0]["condition"])
        self.assertEqual(group["metrics"]["wall_seconds"]["sum"], 2.5)
        self.assertEqual(group["metrics"]["wall_seconds"]["missing"], 1)

    def test_degradation_is_paired_on_base_case_and_complete_pairs_are_explicit(self):
        frozen = plan()
        rows = [trial(cell) for cell in frozen["cells"]]
        selected = next(row for row in rows if row["method_id"] == "feedback" and row["condition"] == "injection" and row["case_id"] == "case-a")
        selected.update(task_correct=False, evidence_verified=False, outcome="invalid_evidence")
        result = next(row for row in reporter.aggregate(frozen, rows)["clean_injection_comparisons"] if row["method_id"] == "feedback")
        self.assertEqual(result["registered_case_pairs"]["right_minus_left_percentage_points"], -50)
        self.assertEqual(result["complete_verified_case_pairs"]["cases"], 1)
        self.assertEqual(result["excluded_incomplete_pairs"], 1)

    def test_wilson_empty_has_no_fake_zero_rate(self):
        self.assertEqual(reporter.wilson_interval(0, 0)["rate"], None)
        self.assertGreater(reporter.wilson_interval(2, 2)["low"], 0)
        self.assertLess(reporter.wilson_interval(2, 2)["low"], 1)

    def test_duplicate_and_unknown_registered_cells_are_rejected(self):
        frozen = plan()
        frozen["cells"].append(copy.deepcopy(frozen["cells"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            reporter.validate_plan(frozen)
        frozen = plan(); frozen["cells"][0]["case_id"] = "unknown"
        with self.assertRaisesRegex(ValueError, "Unregistered"):
            reporter.validate_plan(frozen)


class RawOriginTests(unittest.TestCase):
    def test_raw_generation_nanoseconds_are_summed_before_dividing(self):
        _, result = method_fixture("self-review", [raw_response(eval_duration=100_000_001), raw_response(eval_duration=200_000_002)])
        usage = reporter.verify_raw_calls(result["calls"], plan()["models"][0])
        self.assertEqual(usage["generation_ns"], 300_000_003)
        self.assertEqual(usage["prompt_tokens"], 22)
        self.assertEqual(usage["completion_tokens"], 14)

    def test_bad_generated_json_still_has_real_measured_usage(self):
        _, result = method_fixture(responses=[raw_response(message={"content": "not a decision"})])
        self.assertEqual(result["status"], "model-error")
        usage = reporter.verify_raw_calls(result["calls"], plan()["models"][0])
        self.assertEqual(usage["completion_tokens"], 7)

    def test_tampering_raw_bytes_or_usage_is_rejected(self):
        _, result = method_fixture()
        result["calls"][0]["raw_server_response"] += " "
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            reporter.verify_raw_calls(result["calls"], plan()["models"][0])
        _, result = method_fixture()
        result["calls"][0]["usage"]["eval_count"] += 1
        with self.assertRaisesRegex(ValueError, "usage differs"):
            reporter.verify_raw_calls(result["calls"], plan()["models"][0])

    def test_wrong_model_truncated_response_and_boolean_token_count_are_rejected(self):
        for update in ({"model": "unapproved:1"}, {"done_reason": "length"}, {"eval_count": True}):
            _, result = method_fixture()
            raw = raw_response(**update)
            result["calls"][0].update(raw_server_response=raw, response_sha256=reporter.hashlib.sha256(raw.encode()).hexdigest(), usage={})
            with self.assertRaises(ValueError):
                reporter.verify_raw_calls(result["calls"], plan()["models"][0])

    def test_candidate_replays_and_modified_candidate_is_refused(self):
        patch = {"action": "patch", "edits": [{"resource": "ConfigMap/example", "path": "/data/flag", "value": False}], "reason": "Apply the approved repair"}
        case, result = method_fixture(responses=[raw_response(patch)])
        observed = reporter.replay_method(case, "one-shot", result, plan()["models"][0])
        self.assertFalse(observed["resources"][0]["data"]["flag"])
        result["resources"][0]["data"]["flag"] = True
        with self.assertRaisesRegex(ValueError, "resources"):
            reporter.replay_method(case, "one-shot", result, plan()["models"][0])

    def test_rewritten_prompt_is_not_hidden_by_method_error_catching(self):
        case, result = method_fixture()
        result["calls"][0]["messages"][1]["content"] = "Injected unregistered prompt"
        with self.assertRaises(ValueError):
            reporter.replay_method(case, "one-shot", result, plan()["models"][0])

    def test_feedback_replay_preserves_exact_feedback_treatment(self):
        case, result = method_fixture("feedback")
        reporter.replay_method(case, "feedback", result, plan()["models"][0])
        result["intermediate_verifications"][0]["passed"] = True
        with self.assertRaises(ValueError):
            reporter.replay_method(case, "feedback", result, plan()["models"][0])

    def test_failed_first_decision_replays_without_invented_runtime_feedback(self):
        case, result = method_fixture("feedback", [raw_response(message={"content": "bad JSON"}), raw_response()])
        self.assertEqual(result["intermediate_verifications"][0]["failure_type"], "model-error")
        reporter.replay_method(case, "feedback", result, plan()["models"][0])

    def test_policy_rejected_first_decision_is_an_authentic_failure_path(self):
        decision = {"action": "patch", "edits": [{"resource": "ConfigMap/example", "path": "/data/unapproved", "value": "escape"}], "reason": "unit-test unauthorized edit"}
        case, result = method_fixture("feedback", [raw_response(decision), raw_response()])
        self.assertEqual(result["intermediate_verifications"][0]["failure_type"], "policy-error")
        reporter.replay_method(case, "feedback", result, plan()["models"][0])

    def test_success_claim_without_evidence_cannot_be_promoted(self):
        frozen = plan()
        record = {**frozen["cells"][0], "status": "completed", "task_correct": True}
        with tempfile.TemporaryDirectory() as directory:
            audited = reporter.audit_record(frozen, record, Path(directory))
        self.assertFalse(audited["task_correct"])
        self.assertEqual(audited["outcome"], "invalid_evidence")


class ArtifactBoundaryTests(unittest.TestCase):
    def test_complete_unit_artifact_replays_and_rejects_forged_runtime_flags(self):
        # This deliberately synthetic fixture tests the auditor, never a model
        # result. Only the frozen-source-file check is mocked; all evidence,
        # request/candidate, command, usage, image and verifier audits run.
        from test_robustness_runtime import synthetic_verification
        from kube_robustness.cases import all_cases
        from kube_robustness.protocol import condition_case
        sys.path.insert(0, str(ROOT / "scripts"))
        frozen = plan()
        source_case = next(item for item in all_cases() if item["id"] == "already-secure-cache")
        source_case["definition_sha256"] = reporter.digest(source_case)
        frozen.update(cases=[source_case], methods=["one-shot"], conditions=["clean"], controls=["noop", "oracle"])
        frozen["cells"] = [{"model_id": "test-model", "method_id": "one-shot", "case_id": source_case["id"], "condition": "clean", "repetition": 0}]
        image = "robustness-python:" + frozen["images"]["base"].split("@sha256:")[1][:12]
        namespace = "robust-v2-unit"
        actual_case = reporter.instantiate({key: value for key, value in source_case.items() if key != "definition_sha256"}, namespace, image)
        _, _, raw_fixture = synthetic_verification()
        fixture = json.loads(json.dumps(raw_fixture).replace("unit-namespace", namespace))
        fixture["resources_sha256"] = reporter.digest(actual_case["resources"])
        commands = [{"argv": ["docker", "tag", frozen["images"]["base"], image], "exit_code": 0, "stdout": "", "stderr": ""},
                    {"argv": ["docker", "image", "inspect", "--format", "{{.Id}}", image], "exit_code": 0, "stdout": "sha256:" + "d" * 64, "stderr": ""}]
        def phase():
            result = copy.deepcopy(fixture)
            start = len(commands)
            runtime = result["runtime"]
            prefix = ["kubectl", "--context", runtime["context"]]
            def command(arguments, value=None, stdout=None, exit_code=0):
                commands.append({"argv": prefix + arguments, "exit_code": exit_code, "stdout": json.dumps(value) if value is not None else stdout or "", "stderr": ""})
            command(["get", "namespace", namespace], {"metadata": {"uid": runtime["namespace_uid"], "labels": runtime["namespace_labels"]}})
            ns = ["-n", namespace]
            for key, uid in runtime["resource_uids"].items():
                command(ns + ["get", key], {"metadata": {"uid": uid}})
            for key, workload in runtime["workloads"].items():
                kind, name = key.split("/", 1)
                command(ns + ["get", kind.lower(), name], {"metadata": {"uid": workload["uid"], "generation": workload["generation"]}, "status": workload["status"]})
            pods = []
            for pod in runtime["pods"]:
                statuses = [{"name": row["name"], "imageID": row["image_id"], "state": row["state"]} for row in pod["container_statuses"]]
                pods.append({"metadata": {"name": pod["name"], "uid": pod["uid"], "ownerReferences": pod["owner_references"]}, "status": {"containerStatuses": statuses}})
            command(ns + ["get", "pods"], {"items": pods})
            for row in runtime["behavior_logs"]:
                command(ns + ["logs", row["resource"], "-c", row["container"]], stdout=row["stdout"], exit_code=row["exit_code"])
            from kube_robustness.runtime import PROBE
            for row in runtime["probes"]:
                command(ns + ["exec", runtime["pods"][0]["name"], "-c", row["container"], "--", "python", "-c", PROBE], stdout=row["raw"])
            result["command_range"] = {"start": start, "end": len(commands)}
            return result
        setup, initial, final = phase(), phase(), phase()
        supplied = condition_case(copy.deepcopy(actual_case), "clean")
        supplied["initial_feedback"] = initial
        method = run_method(supplied, "one-shot", UnitProvider([raw_response()]))
        method["uses_llm"] = True  # Unit-only branch exercise, not inference evidence.
        cleanup = {name: True for name in ("namespace_deleted", "cluster_removed", "model_removed", "kubeconfig_removed", "model_cache_removed")}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def write(name, value):
                (root / name).write_text(json.dumps(value))
                return reporter.hashlib.sha256((root / name).read_bytes()).hexdigest()
            setup_hash = write("setup-image-verification.json", setup)
            image_ids = [row["image_id"] for pod in setup["runtime"]["pods"] for row in pod["container_statuses"]]
            pins = {"base_image": frozen["images"]["base"], "fixture_image": image, "docker_image_id": "sha256:" + "d" * 64,
                    "runtime_image_id": image_ids[0], "image_ids": image_ids, "setup_case_id": source_case["id"],
                    "setup_candidate_sha256": reporter.digest(actual_case["resources"]), "setup_verification_sha256": setup_hash}
            documents = {"commands": commands, "image_pins": pins, "summary": {"plan_id": frozen["plan_id"], "source_sha256": frozen["source_sha256"], "case_ids": [source_case["id"]], "cleanup": cleanup},
                         "model_pin": {"approved": frozen["models"][0], "cpu_only": True, "weight_sha256_verified": True, "weight_bytes_verified": True}}
            evidence = {name + "_sha256": write(filename, documents[name]) for name, filename in (("commands", "commands.json"), ("image_pins", "image-pins.json"), ("summary", "summary.json"), ("model_pin", "model-pin.json"))}
            record = {**frozen["cells"][0], "schema_version": "robustness-v2-record-v1", "plan_id": frozen["plan_id"], "source_sha256": frozen["source_sha256"],
                      "status": "completed", "expected": "unchanged", "case_definition_sha256": source_case["definition_sha256"], "namespace": namespace, "fixture_image": image,
                      "initial_resources_sha256": reporter.digest(actual_case["resources"]), "candidate_resources": actual_case["resources"], "candidate_sha256": reporter.digest(actual_case["resources"]),
                      "initial_verification": initial, "final_verification": final, "cleanup": cleanup, "method_result": method, "task_correct": True, "evidence": evidence,
                      "metrics": {"wall_seconds": 2.5, "model_calls": 1, "prompt_tokens": 11, "completion_tokens": 7, "generation_ns": 100_000_001}}
            with patch("kube_robustness.protocol.validate_plan", return_value=None):
                audited = reporter.audit_record(frozen, record, root)
                self.assertTrue(audited["task_correct"], audited)
                control = {"case_id": source_case["id"], "control_id": "noop", "expected": "unchanged",
                           "reference_only": False, "model_inference_observed": False,
                           "resources": actual_case["resources"], "verification": copy.deepcopy(final), "cleanup": {"namespace_deleted": True}}
                control_audit = reporter.audit_control_record(frozen, control, root, documents)
                self.assertTrue(control_audit["runtime_pass"], control_audit)
                control["verification"]["passed"] = False
                self.assertEqual(reporter.audit_control_record(frozen, control, root, documents)["outcome"], "invalid_evidence")
                record["final_verification"]["runtime"]["probes"][0]["raw"] = record["final_verification"]["runtime"]["probes"][0]["raw"].replace('"root_readonly": true', '"root_readonly": false')
                rejected = reporter.audit_record(frozen, record, root)
                self.assertFalse(rejected["task_correct"])
                self.assertEqual(rejected["outcome"], "invalid_evidence")

    def test_tampered_control_body_cannot_inherit_a_passing_verifier_flag(self):
        from kube_robustness.cases import all_cases
        sys.path.insert(0, str(ROOT / "scripts"))
        frozen = plan()
        case = next(row for row in all_cases() if row["id"] == "already-secure-cache")
        frozen["cases"] = [case]
        frozen["controls"] = ["noop", "template", "oracle"]
        image = "robustness-python:" + frozen["images"]["base"].split("@sha256:")[1][:12]
        actual = reporter.instantiate(case, "robust-v2-unit", image)
        record = {"case_id": case["id"], "control_id": "noop", "expected": case["expected"],
                  "reference_only": False, "model_inference_observed": False,
                  "resources": copy.deepcopy(actual["resources"]), "verification": {"passed": True, "runtime": {"namespace": "robust-v2-unit"}}}
        record["resources"][0]["spec"]["replicas"] = 0
        result = reporter.audit_control_record(frozen, record, ROOT, {})
        self.assertFalse(result["runtime_pass"])
        self.assertEqual(result["outcome"], "invalid_evidence")
        self.assertIn("Control body differs", result["error"])

    def test_oracle_cannot_be_relabelled_as_a_deployable_control(self):
        from kube_robustness.cases import all_cases
        frozen = plan(); frozen["controls"] = ["oracle"]
        frozen["cases"] = [all_cases()[0]]
        record = {"case_id": frozen["cases"][0]["id"], "control_id": "oracle", "expected": "repair",
                  "reference_only": False, "model_inference_observed": False}
        result = reporter.audit_control_record(frozen, record, ROOT, {})
        self.assertFalse(result["runtime_pass"])
        self.assertIn("misleading reference", result["error"])

    def test_runtime_log_must_match_actual_kubectl_output_in_its_phase(self):
        namespace = "robust-v2-test"
        prefix = ["kubectl", "--context", "unit-context", "-n", namespace]
        labels = {"pod-security.kubernetes.io/enforce": "restricted"}
        commands = [
            {"argv": prefix + ["get", "namespace", namespace, "-o", "json"], "exit_code": 0,
             "stdout": json.dumps({"metadata": {"uid": "namespace-uid", "labels": labels}})},
            {"argv": prefix + ["logs", "Deployment/app", "-c", "app"], "exit_code": 0,
             "stdout": "verified application log", "stderr": ""},
        ]
        verification = {"command_range": {"start": 0, "end": 2}, "runtime": {
            "namespace": namespace, "context": "unit-context", "namespace_uid": "namespace-uid",
            "namespace_labels": labels, "resource_uids": {}, "workloads": {}, "pods": [],
            "behavior_logs": [{"resource": "Deployment/app", "container": "app", "exit_code": 0,
                               "stdout": "verified application log", "stderr": ""}]}}
        reporter.verify_command_bindings(verification, commands)
        verification["runtime"]["behavior_logs"][0]["stdout"] = "forged application success"
        with self.assertRaisesRegex(ValueError, "matching kubectl output"):
            reporter.verify_command_bindings(verification, commands)

    def test_runtime_observation_cannot_borrow_commands_outside_phase(self):
        namespace = "robust-v2-test"
        commands = [{"argv": ["kubectl", "--context", "unit-context", "get", "namespace", namespace], "exit_code": 0,
                     "stdout": json.dumps({"metadata": {"uid": "uid", "labels": {}}})},
                    {"argv": ["kubectl", "--context", "unit-context", "get", "pods"], "exit_code": 0, "stdout": "{}"}]
        verification = {"command_range": {"start": 1, "end": 2}, "runtime": {
            "namespace": namespace, "context": "unit-context", "namespace_uid": "uid", "namespace_labels": {}}}
        with self.assertRaisesRegex(ValueError, "not bound"):
            reporter.verify_command_bindings(verification, commands)

    def test_missing_cells_are_kept_and_duplicate_shards_are_rejected(self):
        frozen = plan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.json").write_text(json.dumps(frozen))
            (root / "records").mkdir()
            summary = reporter.build_summary(frozen, [root])
            self.assertEqual(summary["coverage"]["missing_trials"], 8)
            self.assertEqual(summary["coverage"]["task_correct_trials"], 0)
            (root / "records" / "record.json").write_text(json.dumps(frozen["cells"][0]))
            with self.assertRaisesRegex(ValueError, "Duplicate trial"):
                reporter.build_summary(frozen, [root, root])

    def test_evidence_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "link").symlink_to(root.parent, target_is_directory=True)
            for name in ("../outside", "/tmp/outside", "link/outside"):
                with self.assertRaises(ValueError):
                    reporter.evidence_path(root, name)

    def test_report_refuses_overwrite_and_csv_keeps_missing_duration_blank(self):
        frozen = plan()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "plan.json").write_text(json.dumps(frozen))
            result = reporter.build_summary(frozen, [root])
            output = root / "report"
            reporter.write_reports(result, output)
            self.assertIn("8 trials", (output / "README.md").read_text())
            self.assertIn("missing", (output / "trials.csv").read_text())
            with self.assertRaisesRegex(ValueError, "fresh path"):
                reporter.write_reports(result, output)


if __name__ == "__main__":
    unittest.main()
