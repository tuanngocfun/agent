"""Offline protocol tests; no fabricated runtime or benchmark result claims."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kube_repair.artifacts import digest, write_bundle
from kube_repair.benchmark_cases import benchmark_case
from kube_repair.policy import harden, repair_storage

WORKER_PATH = Path(__file__).resolve().parents[1] / "scripts/benchmark_worker.py"
spec = importlib.util.spec_from_file_location("benchmark_worker_tests", WORKER_PATH)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


def plan_fixture():
    return {"schema_version": 1, "plan_id": "offline-test-plan", "repetitions": 2,
        "models": [{"model_id": "test-model", "tag": "test:latest", "manifest_digest": "sha256:" + "a" * 64,
                    "weight_blob_digest": "sha256:" + "b" * 64, "weight_bytes": 100}],
        "methods": [{"method_id": method, "max_actions": limits[0], "max_repairs": limits[1], "token_ceiling": 32768}
                    for method, limits in worker.METHODS.items()],
        "settings": {"temperature": 0, "num_ctx": 8192, "num_thread": 2, "max_output_tokens": 512,
                     "provider_timeout_seconds": 420, "max_total_tokens": 32768, "completion_policy": "verified-repair"},
        "images": {name: "test/image@sha256:" + "c" * 64 for name in ("ollama", "base", "node")},
        "cases": [{"case_id": case, "split": "evaluation", "fixture_kind": "file-cache", "expected_outcome": "repair"}
                  for case in ("case-a", "case-b", "case-c", "case-d", "case-e", "case-f", "case-g", "case-h")],
        **{key: "d" * 64 for key in ("source_fingerprint", "suite_fingerprint", "evaluator_fingerprint", "settings_fingerprint")}}


def raw_call(action=None, error=False, inferred=True):
    response = {"model": "test:latest", "done": True, "eval_count": 20 if inferred else 0,
                "prompt_eval_count": 100, "message": {"content": json.dumps(action or {"bad": "action"})}}
    raw = json.dumps(response)
    return {"call": 1, "raw_server_response": raw, "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "response_truncated": False, "status": "error" if error else "action_returned",
            "action": None if error else action, "reported_usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


class BenchmarkWorkerPlanTests(unittest.TestCase):
    def load(self, value, **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.json"
            path.write_text(json.dumps(value))
            with patch("kube_repair.benchmark_protocol.validate_locked_plan", return_value=True):
                return worker.load_plan(path, "test-model", kwargs.get("method", "feedback"), kwargs.get("repetition", 0), kwargs.get("shard", 0))

    def test_locked_case_shards_cover_exact_primary_cases(self):
        value = plan_fixture()
        selected = [case for shard in range(4) for case in self.load(value, shard=shard)[3]]
        self.assertEqual([case["case_id"] for case in selected], [case["case_id"] for case in value["cases"]])
        self.assertEqual(self.load(value, method="one-shot")[2]["max_actions"], 1)

    def test_unpinned_image_or_changed_budget_or_setting_is_rejected(self):
        for mutation in (lambda value: value["images"].update(base="python:latest"),
                         lambda value: value["settings"].update(temperature=0.5),
                         lambda value: value["methods"][1].update(max_actions=30),
                         lambda value: value["models"][0].update(weight_blob_digest="latest"),
                         lambda value: value["cases"][0].update(case_id="../escaped")):
            with self.subTest(mutation=mutation):
                value = plan_fixture()
                mutation(value)
                with self.assertRaises(ValueError):
                    self.load(value)

    def test_out_of_protocol_repetition_or_duplicate_case_rejected(self):
        for repetition in (-1, 2, True):
            with self.assertRaises(ValueError):
                self.load(plan_fixture(), repetition=repetition)
        value = plan_fixture()
        value["cases"][1] = copy.deepcopy(value["cases"][0])
        with self.assertRaises(ValueError):
            self.load(value)


class BenchmarkWorkerAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model = plan_fixture()["models"][0]
        self.scenario = benchmark_case("file-new-path", image="trusted:fixture")
        self.scenario.contract["kubernetes"] = {"expected_image_id": "containerd://sha256:" + "e" * 64}

    def bundle(self, *, changed=True, accepted=True, raw_tamper=False, candidate_tamper=False, target_tamper=False, observed_uid=11001):
        base = self.scenario.base
        candidate = repair_storage(harden(base, 11001, 12001), self.scenario.contract) if changed else copy.deepcopy(base)
        if target_tamper:
            candidate["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsGroup"] = 10001
        action = {"action": "propose", "manifest": candidate, "reason": "Offline audit test action"}
        # Complete synthetic evidence exists only in the temp directory to test
        # provenance rejection. It is never exported as a real runtime result.
        result = {"backend": "kubernetes", "runtime_verified": True, "kubernetes_execution_observed": True,
                  "passed": True, "infrastructure_error": None, "behavior_pass": True, "negative_pass": True,
                  "static_pass": True, "checks": [{"name": name, "passed": True,
                      "detail": "PID 1 effective UID=" + str(observed_uid) if name == "runtime-non-root" else "Offline synthetic check"}
                      for name in sorted(worker.REQUIRED_CHECKS)],
                  "runtime": {"image_id": self.scenario.contract["kubernetes"]["expected_image_id"], "fixture_kind": "file-cache",
                      "probe_sha256": hashlib.sha256(worker._probe_for_contract(self.scenario.contract).encode()).hexdigest()}}
        call = raw_call(action)
        if raw_tamper:
            call["raw_server_response"] += " "
        trace = [{"event": "initial_verification", "manifest_hash": digest(base), "result": result},
                 {"event": "decision", "action": action},
                 {"event": "candidate_verification", "manifest_hash": digest(candidate), "result": result},
                 {"event": "trusted_completion", "actor": "trusted_engine", "manifest_hash": digest(candidate)}]
        report = {"scenario": self.scenario.id, "status": "repaired", "backend": "kubernetes", "runtime_verified": True,
                  "accepted": accepted, "appropriate_abstention": False, "unnecessary_change": False,
                  "provider": {"name": "ollama", "uses_llm": True, "model": "test:latest", "model_revision": self.model["manifest_digest"],
                               "inference_calls": [call]}, "verification": result, "completion_actor": "trusted_engine",
                  "completion_policy": "verified-repair"}
        output = self.root / ("bundle-" + str(len(list(self.root.iterdir()))))
        exported = copy.deepcopy(base) if candidate_tamper else candidate if accepted else base
        write_bundle(output, base, exported, report, trace, self.scenario.contract)
        return output

    def test_hash_bound_raw_decision_and_changed_candidate_replay(self):
        audit = worker.audit_bundle(self.bundle(), self.model, self.scenario)
        self.assertEqual(audit["status"], "passed")
        self.assertTrue(audit["model_origin_verified"])
        self.assertFalse(audit["worker_cleanup_verified"])

    def test_changed_raw_response_or_export_candidate_cannot_be_promoted(self):
        for kwargs in ({"raw_tamper": True}, {"candidate_tamper": True}, {"changed": False}, {"target_tamper": True}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    worker.audit_bundle(self.bundle(**kwargs), self.model, self.scenario)

    def rewrite(self, bundle, mutate):
        binding, payloads = worker.load_bundle(bundle)
        values = {key: json.loads(payloads[key + ".json"]) for key in ("base", "candidate", "report", "trace", "contract")}
        mutate(values)
        output = self.root / ("rewritten-" + str(len(list(self.root.iterdir()))))
        write_bundle(output, values["base"], values["candidate"], values["report"], values["trace"], values["contract"])
        return output

    def test_missing_check_wrong_probe_or_fabricated_final_verification_rejected(self):
        def missing_check(values):
            values["report"]["verification"]["checks"].pop()
            values["trace"][-2]["result"]["checks"].pop()
        def wrong_probe(values):
            values["report"]["verification"]["runtime"]["probe_sha256"] = "0" * 64
            values["trace"][-2]["result"]["runtime"]["probe_sha256"] = "0" * 64
        def final_mismatch(values):
            values["report"]["verification"]["runtime"]["image_id"] = "containerd://sha256:" + "0" * 64
        for mutation in (missing_check, wrong_probe, final_mismatch):
            with self.subTest(mutation=mutation):
                bundle = self.rewrite(self.bundle(), mutation)
                with self.assertRaises(ValueError):
                    worker.audit_bundle(bundle, self.model, self.scenario)

    def test_positive_but_wrong_runtime_uid_cannot_pass_task_identity(self):
        with self.assertRaisesRegex(ValueError, "Observed runtime UID"):
            worker.audit_bundle(self.bundle(observed_uid=11002), self.model, self.scenario)

    def test_reported_usage_cannot_disagree_with_raw_token_counts(self):
        def changed_count(values):
            values["report"]["provider"]["inference_calls"][0]["reported_usage"]["completion_tokens"] = 19
        bundle = self.rewrite(self.bundle(), changed_count)
        with self.assertRaises(ValueError):
            worker.audit_bundle(bundle, self.model, self.scenario)

    def test_malformed_model_action_is_an_authentic_protocol_failure(self):
        report = {"scenario": self.scenario.id, "status": "budget_exhausted", "backend": "kubernetes", "runtime_verified": False,
            "accepted": False, "appropriate_abstention": False,
            "provider": {"name": "ollama", "uses_llm": True, "model": "test:latest", "model_revision": self.model["manifest_digest"],
                         "inference_calls": [raw_call(error=True)]}, "verification": {"passed": False}}
        trace = [{"event": "initial_verification", "manifest_hash": digest(self.scenario.base), "result": {"passed": False}},
                 {"event": "rejected_provider_output", "provider_call": 1}]
        output = self.root / "protocol-failure"
        write_bundle(output, self.scenario.base, self.scenario.base, report, trace, self.scenario.contract)
        audit = worker.audit_bundle(output, self.model, self.scenario)
        self.assertTrue(audit["model_origin_verified"])
        self.assertEqual(worker.classify_outcome(report, trace), "protocol_failure")

    def test_budget_before_inference_does_not_claim_model_origin(self):
        report = {"scenario": self.scenario.id, "status": "provider_error", "backend": "kubernetes", "runtime_verified": False,
            "accepted": False, "appropriate_abstention": False,
            "provider": {"name": "ollama", "uses_llm": True, "model": "test:latest", "model_revision": None,
                         "inference_calls": [], "errors": [{"code": "token_budget"}]}, "verification": {"passed": False}}
        trace = [{"event": "initial_verification", "manifest_hash": digest(self.scenario.base), "result": {"passed": False}}]
        output = self.root / "budget-failure"
        write_bundle(output, self.scenario.base, self.scenario.base, report, trace, self.scenario.contract)
        audit = worker.audit_bundle(output, self.model, self.scenario)
        self.assertFalse(audit["model_origin_verified"])
        self.assertEqual(worker.classify_outcome(report, trace), "budget_exhausted")


class BenchmarkWorkerEvidenceTests(unittest.TestCase):
    def test_interruption_keeps_null_missing_usage_and_nonexportable_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_root = root / "cases" / "file-new-path"
            case_root.mkdir(parents=True)
            worker.atomic_json(case_root / "agent-progress.json", {
                "accepted": False, "exportable": False, "budget": {"candidate_repairs": 0, "test_runs": 1}, "trace": []})
            plan = plan_fixture()
            provider = worker.BenchmarkProvider("test:latest", initial_evidence={})
            case = {"case_id": "file-new-path", "split": "evaluation", "expected_outcome": "repair"}
            record = worker.interrupted_record(plan, plan["models"][0], plan["methods"][0], case, 0,
                provider, case_root, root, 20, "deadline")
            self.assertEqual(record["outcome"], "infrastructure_failure")
            self.assertFalse(record["evidence"]["validated"])
            self.assertFalse(record["accepted"])
            self.assertIsNone(record["metrics"]["total_tokens"])
            self.assertIsNone(record["checks"]["cleanup"])
            self.assertTrue((root / record["evidence"]["partial_progress_path"]).is_file())

    def test_methods_receive_same_labeled_evidence_and_cannot_mutate_original(self):
        scenario = benchmark_case("file-new-path", image="trusted:fixture")
        evidence = worker.labeled_evidence(scenario)
        contexts = []
        def observe(provider, context):
            contexts.append(copy.deepcopy(context))
            context["evidence"]["app"]["content"] = "mutated"
            return {"action": "abstain", "reason": "test"}
        with patch.object(worker.OllamaProvider, "next_action", observe):
            for method in worker.METHODS:
                provider = worker.BenchmarkProvider("test:latest", initial_evidence=evidence)
                provider.next_action({"evidence": {}, "remaining": {"actions": worker.METHODS[method][0]}})
        self.assertEqual(contexts[0]["evidence"], contexts[1]["evidence"])
        self.assertEqual(evidence["repository"]["trust"], "untrusted_repository")
        self.assertNotEqual(evidence["app"]["content"], "mutated")

    def test_cleanup_requires_every_verification_namespace(self):
        passed = {"result": {"checks": [{"name": "namespace-cleanup", "passed": True}]}}
        failed = {"result": {"checks": [{"name": "namespace-cleanup", "passed": False}]}}
        self.assertTrue(worker.namespace_cleanup_verified([passed, passed]))
        self.assertFalse(worker.namespace_cleanup_verified([passed, failed]))
        self.assertFalse(worker.namespace_cleanup_verified([]))

    def test_atomic_write_preserves_existing_file_after_symlink_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "actual.json"
            worker.atomic_json(target, {"initial": True})
            worker.atomic_json(target, {"updated": True})
            self.assertEqual(json.loads(target.read_text()), {"updated": True})
            symlink = Path(directory) / "link.json"
            symlink.symlink_to(target)
            with self.assertRaises(ValueError):
                worker.atomic_json(symlink, {"overwrite": True})
            self.assertEqual(json.loads(target.read_text()), {"updated": True})


if __name__ == "__main__":
    unittest.main()
