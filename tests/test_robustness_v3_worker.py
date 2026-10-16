"""Worker protocol regressions; mocked commands are not runtime evidence."""
import copy
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import signal
import time
import unittest
from unittest.mock import patch

from kube_robustness_v3.cases import all_cases
from kube_robustness_v3.methods import apply_edits
from kube_robustness_v3.runtime import KubernetesSession, contains_desired, deployment_ready, evaluate_static_resources

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("robustness_worker_test", ROOT / "scripts/robustness_v3_worker.py")
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class RobustnessWorkerTests(unittest.TestCase):
    def test_execution_deadline_uses_unrounded_worker_capacity(self):
        plan = {"budget": {"capacity": [{"worker_seconds": 1702, "worker_timeout_seconds": 1740}],
                           "validation_job_timeout_minutes": 30}}
        self.assertEqual(WORKER.execution_seconds(plan, "diagnostic"), 1632)
        self.assertEqual(WORKER.execution_seconds(plan, "models"), 1632)
        self.assertEqual(WORKER.execution_seconds(plan, "diagnostic")
                         + WORKER.limits.GLOBAL_CLEANUP_SECONDS + WORKER.FINALIZATION_SECONDS, 1702)
        self.assertLessEqual(1702 + WORKER.limits.CHECKOUT_TOOL_SECONDS + WORKER.limits.ARTIFACT_SECONDS, 30 * 60)

    def test_validation_deadline_derives_unrounded_reference_work(self):
        plan = {"cases": [{}, {}], "controls": ["noop", "oracle"],
                "budget": {"validation_job_timeout_minutes": 999}}
        # Rounded job metadata must not grant the worker extra execution time.
        expected = WORKER.limits.SETUP_SECONDS + 4 * WORKER.limits.CONTROL_SECONDS + WORKER.PROCESSING_SECONDS
        self.assertEqual(WORKER.execution_seconds(plan, "validate"), expected)

    def test_processing_exhaustion_cannot_consume_finalization_reserve(self):
        self.assertEqual(WORKER.PROCESSING_SECONDS, 20)
        self.assertEqual(WORKER.FINALIZATION_SECONDS, 10)
        self.assertEqual(WORKER.PROCESSING_SECONDS + WORKER.FINALIZATION_SECONDS,
                         WORKER.limits.BOOKKEEPING_SECONDS)
        processing = WORKER.allowance(WORKER.PROCESSING_SECONDS, "unit-processing")
        with patch.object(WORKER.time, "monotonic", side_effect=[0, 20, 20]), \
                patch.object(WORKER, "hard_phase", side_effect=lambda *args: nullcontext()) as phases:
            with processing():
                pass
            with self.assertRaisesRegex(TimeoutError, "Cumulative phase exhausted"):
                with processing():
                    self.fail("Exhausted processing must not execute another segment")
            with WORKER.hard_phase(WORKER.FINALIZATION_SECONDS, "finalization"):
                finalization_entered = True
        self.assertTrue(finalization_entered)
        self.assertEqual(phases.call_args_list[0].args, (20, "unit-processing"))
        self.assertEqual(phases.call_args_list[-1].args, (10, "finalization"))

    def test_finalization_expiry_always_restores_process_signal_handlers(self):
        old_alarm = signal.getsignal(signal.SIGALRM)
        old_term = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(TimeoutError):
            with WORKER.restoring_signal_handlers(old_alarm, old_term):
                signal.signal(signal.SIGALRM, lambda signum, frame: None)
                signal.signal(signal.SIGTERM, lambda signum, frame: None)
                with WORKER.hard_phase(0.02, "unit-finalization"):
                    time.sleep(0.2)
        self.assertEqual(signal.getsignal(signal.SIGALRM), old_alarm)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old_term)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_an_old_healthy_pod_cannot_hide_an_unready_replacement(self):
        resource = {"metadata": {"generation": 2}, "status": {"observedGeneration": 2, "replicas": 2, "readyReplicas": 1, "updatedReplicas": 1, "availableReplicas": 1}}
        self.assertFalse(deployment_ready(resource))
        resource["status"]["replicas"] = 1
        self.assertTrue(deployment_ready(resource))
        resource["status"]["observedGeneration"] = 1
        self.assertFalse(deployment_ready(resource))

    def test_malformed_model_list_values_fail_static_checks_without_crashing(self):
        case = all_cases()[0]
        path = "/spec/template/spec/containers/0/securityContext/capabilities/drop"
        candidate = apply_edits(case["resources"], [{"resource": "Deployment/reporting", "path": path, "value": [{}]}], case["allowed_paths"])
        checks = evaluate_static_resources(case, candidate)
        self.assertTrue(any(not row["passed"] and row["name"].endswith("capabilities/drop") for row in checks))

    def test_kubernetes_omitted_false_mount_matches_but_omitted_true_does_not(self):
        observed = {"volumeMounts": [{"name": "runtime", "mountPath": "/cache"}]}
        expected = copy.deepcopy(observed)
        expected["volumeMounts"][0]["readOnly"] = False
        self.assertTrue(contains_desired(expected, observed))
        expected["volumeMounts"][0]["readOnly"] = True
        self.assertFalse(contains_desired(expected, observed))

    def test_old_replicaset_security_and_mount_state_cannot_match_current_candidate(self):
        case = all_cases()[0]
        initial = case["resources"][0]["spec"]["template"]["spec"]
        repaired = apply_edits(case["resources"], case["oracle_edits"], case["allowed_paths"])[0]["spec"]["template"]["spec"]
        self.assertFalse(contains_desired(repaired, initial))
        defaulted = copy.deepcopy(repaired)
        defaulted["dnsPolicy"] = "ClusterFirst"
        defaulted["containers"][0]["terminationMessagePath"] = "/dev/termination-log"
        self.assertTrue(contains_desired(repaired, defaulted))

    def test_all_raw_generations_contribute_even_when_decision_parsing_failed(self):
        result = {"calls": [{"status": "error", "raw_server_response": json.dumps({"prompt_eval_count": 10, "eval_count": 3, "eval_duration": 1})},
                            {"status": "decision-returned", "raw_server_response": json.dumps({"prompt_eval_count": 12, "eval_count": 7, "eval_duration": 2})}]}
        actual = WORKER.raw_metrics(result, 1.5)
        self.assertEqual(actual["generation_ns"], 3)
        self.assertEqual(actual["prompt_tokens"], 22)
        self.assertEqual(actual["completion_tokens"], 10)
        self.assertTrue(actual["usage_complete"])

    def test_missing_or_boolean_usage_is_unknown_rather_than_zero(self):
        for raw in (None, json.dumps({"prompt_eval_count": True, "eval_count": 7, "eval_duration": 4})):
            actual = WORKER.raw_metrics({"calls": [{"raw_server_response": raw}]}, 2)
            self.assertFalse(actual["usage_complete"])
            self.assertIsNone(actual["generation_ns"])
            self.assertIsNone(actual["completion_tokens"])

    def test_fixed_baselines_stay_inside_case_authority_and_oracle_is_separate(self):
        for case in all_cases():
            for mode in ("noop", "naive", "template", "oracle"):
                edits = WORKER.baseline_edits(case, mode)
                apply_edits(case["resources"], edits, case["allowed_paths"])
                if mode == "noop":
                    self.assertEqual(edits, [])
            self.assertEqual(WORKER.baseline_edits(case, "oracle"), case["oracle_edits"])

    def test_partial_multi_object_apply_preserves_successful_prefix_for_later_rollback(self):
        case = next(c for c in all_cases() if c["id"] == "rbac-tenant-subject")
        session = KubernetesSession(case, kubectl="kubectl", context="lab", kubeconfig="owned-config", image="trusted-image", commands=[])
        session.uid = "namespace-uid"
        session.current = copy.deepcopy(session.case["resources"])
        session.resource_uids = {r["kind"] + "/" + r["metadata"]["name"]: "uid-" + str(i) for i, r in enumerate(session.current)}
        candidate = apply_edits(session.current, case["oracle_edits"], case["allowed_paths"])
        role = next(r for r in candidate if r["kind"] == "Role")
        observed_role = copy.deepcopy(role)
        observed_role["metadata"]["uid"] = session.resource_uids["Role/runtime-reader"]
        responses = [{"exit_code": 0, "stdout": json.dumps(observed_role), "stderr": "", "stdin_sha256": "test"},
                     {"exit_code": 1, "stdout": "", "stderr": "role binding rejected", "stdin_sha256": "test"}]
        with patch.object(session, "read", return_value={"serverVersion": {"gitVersion": "v1.34.0"}}), patch.object(session, "call", side_effect=responses):
            result = session.verify(candidate)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["infrastructure_error"])
        self.assertEqual(next(r for r in session.current if r["kind"] == "Role"), role)
        original_binding = next(r for r in session.case["resources"] if r["kind"] == "RoleBinding")
        self.assertEqual(next(r for r in session.current if r["kind"] == "RoleBinding"), original_binding)


if __name__ == "__main__":
    unittest.main()
