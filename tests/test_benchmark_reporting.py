"""Synthetic unit records test reporting guards; they are never benchmark data."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from kube_repair.artifacts import canonical, digest, source_fingerprint, write_bundle
from kube_repair.benchmark_reporting import (
    build_summary, expected_cells, generate_reports, render_html, verify_record_evidence,
    wilson_interval, write_reports,
)
from kube_repair.policy import apply_changes
from kube_repair.scenarios import get_scenario


class BenchmarkReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = {"model_id": "model-a", "tag": "test-model:1b", "manifest_digest": "sha256:" + "a" * 64,
                      "pin": {"tag": "test-model:1b", "manifest_digest": "sha256:" + "a" * 64}}
        self.plan = {"schema_version": 1, "plan_id": "synthetic-unit-fixture", "suite_fingerprint": "suite-unit",
                     "evaluator_fingerprint": "verifier-unit", "source_fingerprint": source_fingerprint(),
                     "settings_fingerprint": "settings-unit", "models": [self.model],
                     "methods": [{"method_id": "one-shot", "token_ceiling": 32768, "max_actions": 1, "guided_schema_fingerprint": "schema-unit"},
                                 {"method_id": "feedback", "token_ceiling": 32768, "max_actions": 6, "guided_schema_fingerprint": "schema-unit"}],
                     "cases": [{"case_id": "repair-a", "split": "evaluation", "expected_outcome": "repair"},
                               {"case_id": "secure-a", "split": "evaluation", "expected_outcome": "unchanged"},
                               {"case_id": "infeasible-a", "split": "evaluation", "expected_outcome": "abstain"}], "repetitions": 2}

    def record(self, case="repair-a", method="one-shot", repetition=0, outcome=None):
        expected = next(c["expected_outcome"] for c in self.plan["cases"] if c["case_id"] == case)
        outcome = outcome or {"repair": "repaired", "unchanged": "unchanged", "abstain": "abstained"}[expected]
        scenario = get_scenario("cache-path")
        base, contract = scenario.base, scenario.contract
        action = {"action": "propose", "changes": {"securityContext": {"runAsUser": 10001}}, "reason": "Unit fixture"} if outcome == "repaired" else {"action": "abstain" if outcome == "abstained" else "finish", "reason": "Unit fixture"}
        candidate = apply_changes(base, action["changes"]) if outcome == "repaired" else copy.deepcopy(base)
        accepted = outcome in ("repaired", "unchanged")
        verification = {"backend": "kubernetes", "behavior_pass": accepted, "static_pass": accepted, "negative_pass": accepted,
                        "passed": accepted, "runtime_verified": True, "kubernetes_execution_observed": True,
                        "checks": [{"name": "namespace-cleanup", "passed": True}], "infrastructure_error": None}
        server = {"model": "test-model:1b", "done": True, "message": {"content": json.dumps(action)},
                  "prompt_eval_count": 13, "eval_count": 7, "eval_duration": 2_000_000_000}
        raw = json.dumps(server)
        provider = {"name": "ollama", "uses_llm": True, "is_language_model": True, "model": "test-model:1b", "model_revision": "a" * 64,
                    "decoding_mode": "compact-schema", "calls": 1, "elapsed_seconds": 2.5,
                    "token_usage": {"counts_complete": True, "counts_available_calls": 1, "reported_prompt_tokens": 13,
                                    "reported_completion_tokens": 7, "reported_total_tokens": 20,
                                    "reserved_token_upper_bound": 500, "max_total_tokens": 32768},
                    "inference_calls": [{"raw_server_response": raw, "response_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                                         "response_truncated": False, "reported_usage": {"prompt_tokens": 13, "completion_tokens": 7, "total_tokens": 20},
                                         "status": "action_returned", "action": action}]}
        budget = {"candidate_repairs": int(outcome == "repaired"), "test_runs": 1, "max_actions": 1 if method == "one-shot" else 6}
        report = {"schema_version": 1, "scenario": "cache-path", "backend": "kubernetes", "provider": provider,
                  "status": outcome, "runtime_verified": True, "accepted": accepted, "verification": verification,
                  "budget": budget, "appropriate_abstention": outcome == "abstained", "unnecessary_change": False,
                  "rejected_actions": 0, "executed_unauthorized_effects": 0, "seconds": 3.5}
        trace = [{"event": "initial_verification", "manifest_hash": digest(base), "result": verification},
                 {"event": "decision", "action": action}]
        bundle = self.root / f"{case}-{method}-{repetition}" / "bundle"
        binding = write_bundle(bundle, base, candidate, report, trace, contract)
        cleanup = {"model_container_removed": True, "cluster_removed": True, "kubeconfig_removed": True, "model_cache_removed": True}
        audit = {"status": "passed", "bundle_review_hash": binding["review_hash"], "model_origin_verified": True,
                 "namespace_cleanup_verified": True, "worker_cleanup_verified": True, "worker_cleanup": cleanup}
        audit_path = bundle.parent / "audit.json"
        audit_path.write_text(canonical(audit))
        return {"schema_version": 1, **{key: self.plan[key] for key in ("plan_id", "suite_fingerprint", "evaluator_fingerprint", "source_fingerprint", "settings_fingerprint")},
                "model_id": "model-a", "method_id": method, "case_id": case, "repetition": repetition, "expected_outcome": expected,
                "outcome": outcome, "accepted": accepted, "appropriate_abstention": outcome == "abstained", "unnecessary_change": False,
                "rejected_actions": 0, "unauthorized_effects": 0, "failure_reason": None,
                "metrics": {"inspections": 0, "repairs": budget["candidate_repairs"], "tests": 1, "model_calls": 1,
                            "prompt_tokens": 13, "output_tokens": 7, "total_tokens": 20, "reserved_tokens": 500,
                            "wall_seconds": 3.5, "inference_seconds": 2.5, "protocol_rejections": 0, "policy_rejections": 0},
                "checks": {"behavior": accepted, "static": accepted, "security": accepted, "cleanup": True},
                "evidence": {"validated": True, "model_origin_verified": True,
                             "bundle_path": str(bundle.relative_to(self.root)), "bundle_sha256": hashlib.sha256((bundle / "binding.json").read_bytes()).hexdigest(),
                             "audit_path": str(audit_path.relative_to(self.root)), "audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest()},
                "provenance": {"model_pin": self.model, "worker_cleanup": cleanup}}

    def test_full_cartesian_coverage_and_missing_not_dropped(self):
        self.assertEqual(len(expected_cells(self.plan)), 12)
        summary = build_summary(self.plan, [], self.root)
        self.assertEqual(summary["coverage"]["missing_trials"], 12)
        self.assertEqual(summary["groups"][0]["case_task_correct"]["cases"], 3)
        self.assertIsNone(summary["groups"][0]["metrics"]["total_tokens"]["sum"])

    def test_real_bundle_inventory_and_raw_response_guard(self):
        record = self.record()
        self.assertTrue(verify_record_evidence(record, self.root)["verified"])
        bundle = self.root / record["evidence"]["bundle_path"]
        (bundle / "candidate.json").write_text("{}")
        result = verify_record_evidence(record, self.root)
        self.assertFalse(result["verified"])
        self.assertIn("changed", result["error"])

    def test_worker_flag_and_audit_hash_not_sufficient_without_artifacts(self):
        record = self.record()
        (self.root / record["evidence"]["audit_path"]).write_text("{}")
        result = build_summary(self.plan, [record], self.root)
        self.assertEqual(result["trials"][0]["outcome"], "invalid_evidence")
        self.assertFalse(result["trials"][0]["task_correct"])

    def test_metric_tamper_cannot_change_trusted_costs(self):
        record = self.record()
        record["metrics"]["total_tokens"] = 200
        record["metrics"]["output_tokens"] = 187
        summary = build_summary(self.plan, [record], self.root)
        self.assertEqual(summary["trials"][0]["outcome"], "invalid_evidence")
        self.assertIsNone(summary["groups"][0]["metrics"]["total_tokens"]["sum"])

    def test_every_repeat_required_without_pseudoreplication(self):
        records = [self.record(repetition=i) for i in range(2)]
        summary = build_summary(self.plan, records, self.root)
        group = summary["groups"][0]
        self.assertEqual(group["task_correct_trials"], 2)
        self.assertEqual(group["case_repair_success"]["successes"], 1)
        self.assertEqual(group["case_repair_success"]["cases"], 1)
        self.assertEqual(group["case_task_correct"]["cases"], 3)
        partial = build_summary(self.plan, records[:1], self.root)
        self.assertEqual(partial["groups"][0]["case_repair_success"]["successes"], 0)

    def test_unchanged_and_appropriate_abstention_separate_denominators(self):
        records = [self.record(case=case, repetition=i) for case in ("secure-a", "infeasible-a") for i in range(2)]
        group = build_summary(self.plan, records, self.root)["groups"][0]
        self.assertEqual(group["case_unchanged_success"]["successes"], 1)
        self.assertEqual(group["case_abstention_success"]["successes"], 1)
        self.assertEqual(group["case_repair_success"]["successes"], 0)

    def test_mismatched_fingerprint_hard_gate(self):
        record = self.record()
        for key in ("plan_id", "suite_fingerprint", "evaluator_fingerprint", "source_fingerprint", "settings_fingerprint"):
            changed = copy.deepcopy(record)
            changed[key] = "other"
            with self.assertRaisesRegex(ValueError, "Incompatible comparison"):
                build_summary(self.plan, [changed], self.root)

    def test_duplicate_unregistered_and_wrong_model_pin_refused(self):
        record = self.record()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build_summary(self.plan, [record, record], self.root)
        other = copy.deepcopy(record)
        other["case_id"] = "outside"
        with self.assertRaisesRegex(ValueError, "Unregistered"):
            build_summary(self.plan, [other], self.root)
        other = copy.deepcopy(record)
        other["provenance"]["model_pin"]["tag"] = "different"
        with self.assertRaisesRegex(ValueError, "model pin"):
            build_summary(self.plan, [other], self.root)

    def test_provider_and_infrastructure_failure_kept_as_distinct_unverified_attempts(self):
        records = []
        for repetition, outcome in enumerate(("provider_failure", "infrastructure_failure")):
            record = self.record(repetition=repetition)
            record["outcome"] = outcome
            record["evidence"] = {"validated": False}
            record["metrics"] = {}
            records.append(record)
        group = build_summary(self.plan, records, self.root)["groups"][0]
        self.assertEqual(group["outcomes"]["provider_failure"], 1)
        self.assertEqual(group["outcomes"]["infrastructure_failure"], 1)
        self.assertEqual(group["task_correct_trials"], 0)
        self.assertIsNone(group["metrics"]["total_tokens"]["sum"])

    def test_cleanup_failure_cannot_be_accepted(self):
        record = self.record()
        record["checks"]["cleanup"] = False
        result = verify_record_evidence(record, self.root)
        self.assertFalse(result["verified"])
        self.assertIn("cleanup", result["error"])

    def test_generation_speed_uses_raw_duration_and_refuses_tamper(self):
        record = self.record()
        record["metrics"]["generation_seconds"] = 2.0
        summary = build_summary(self.plan, [record], self.root)
        self.assertEqual(summary["groups"][0]["metrics"]["generation_tokens_per_second"]["mean"], 3.5)
        record["metrics"]["generation_seconds"] = 0.01
        self.assertFalse(verify_record_evidence(record, self.root)["verified"])

    def test_optional_model_pin_file_hash_is_rechecked(self):
        record = self.record()
        pin_path = self.root / "model-pin.json"
        pin_path.write_text(canonical({"unit_fixture": True}))
        record["evidence"]["model_pin_path"] = pin_path.name
        record["evidence"]["model_pin_sha256"] = hashlib.sha256(pin_path.read_bytes()).hexdigest()
        self.assertTrue(verify_record_evidence(record, self.root)["verified"])
        pin_path.write_text(canonical({"unit_fixture": "changed"}))
        self.assertFalse(verify_record_evidence(record, self.root)["verified"])

    def test_paired_complete_case_exclusions_and_action_budgets(self):
        records = [self.record(method=method, repetition=i) for method in ("one-shot", "feedback") for i in range(2)]
        summary = build_summary(self.plan, records, self.root)
        pair = summary["pairs"][0]
        self.assertEqual(pair["matched_complete_cases"], 1)
        self.assertEqual(pair["excluded_incomplete_cases"], 2)
        self.assertEqual(pair["both_correct"], 1)
        self.assertEqual(pair["right_minus_left_percentage_points"], 0)
        self.assertEqual((pair["left_action_budget"], pair["right_action_budget"]), (1, 6))

    def test_wilson_reference_and_zero_cases(self):
        result = wilson_interval(5, 10)
        self.assertAlmostEqual(result["low"], 0.2365930905)
        self.assertAlmostEqual(result["high"], 0.7634069095)
        self.assertIsNone(wilson_interval(0, 0)["rate"])
        with self.assertRaises(ValueError):
            wilson_interval(11, 10)

    def test_nonfinite_negative_and_nonreconciling_usage_refused(self):
        record = self.record()
        for field, value in (("wall_seconds", float("inf")), ("model_calls", -1), ("tests", True), ("total_tokens", 19)):
            changed = copy.deepcopy(record)
            changed["metrics"][field] = value
            with self.assertRaises(ValueError):
                build_summary(self.plan, [changed], self.root)

    def test_evidence_paths_cannot_escape_or_follow_symlinks(self):
        record = self.record()
        changed = copy.deepcopy(record)
        changed["evidence"]["audit_path"] = "../secret.json"
        self.assertFalse(verify_record_evidence(changed, self.root)["verified"])
        audit = self.root / record["evidence"]["audit_path"]
        linked = audit.parent / "linked.json"
        linked.write_bytes(audit.read_bytes())
        audit.unlink()
        audit.symlink_to(linked)
        self.assertFalse(verify_record_evidence(record, self.root)["verified"])

    def test_portable_exports_keep_missing_cells_and_refuse_overwrite(self):
        records_dir = self.root / "records"
        records_dir.mkdir()
        (records_dir / "trial.json").write_text(canonical(self.record()))
        plan_path = self.root / "plan.json"
        plan_path.write_text(canonical(self.plan))
        output = self.root / "report"
        summary = generate_reports(plan_path, records_dir, self.root, output)
        self.assertEqual(set(p.name for p in output.iterdir()), {"summary.json", "trials.csv", "report.md", "index.html"})
        self.assertEqual(len((output / "trials.csv").read_text().splitlines()), 13)
        self.assertIn("unavailable", (output / "report.md").read_text())
        self.assertNotIn("<script", (output / "index.html").read_text())
        with self.assertRaises(FileExistsError):
            write_reports(summary, output)

    def test_html_escapes_untrusted_failure_text(self):
        record = self.record()
        record["failure_reason"] = "<script>alert('x')</script>"
        output = render_html(build_summary(self.plan, [record], self.root))
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)


if __name__ == "__main__":
    unittest.main()
