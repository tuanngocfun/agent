import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kube_repair.artifacts import digest
from kube_repair.engine import run_baseline, run_task
from kube_repair.policy import harden
from kube_repair.providers import ProviderError, ScriptedProvider
from kube_repair.scenarios import get_scenario


class ActionsProvider:
    def __init__(self, actions):
        self.actions = iter(actions)

    def next_action(self, context):
        return next(self.actions)

    def metadata(self):
        return {"name": "test-provider", "uses_llm": False}


class EngineTests(unittest.TestCase):
    def run_one(self, scenario, provider=None, **kwargs):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "bundle"
        return run_task(get_scenario(scenario), provider or ScriptedProvider(), self.output, **kwargs)[0]

    def test_expected_teaching_outcomes_and_no_runtime_claim(self):
        for name, expected in (("cache-path", "repaired"), ("volume-permissions", "repaired"),
                               ("authority-limit", "abstained"), ("already-secure", "unchanged")):
            with self.subTest(name=name):
                report = self.run_one(name)
                self.assertEqual(report["status"], expected)
                self.assertFalse(report["runtime_verified"])
                if expected == "unchanged":
                    self.assertEqual(report["budget"]["candidate_repairs"], 0)
                    self.assertEqual((self.output / "patch.diff").read_text(), "")
                if expected == "abstained":
                    self.assertTrue(report["appropriate_abstention"])

    def test_unsafe_shortcut_never_reaches_runner(self):
        scenario = get_scenario("cache-path")
        unsafe = harden(scenario.base)
        unsafe["spec"]["template"]["spec"]["containers"][0]["image"] = "attacker/health-only:latest"
        actions = [{"action": "propose", "manifest": unsafe, "reason": "Malicious doc requested replacement"},
                   {"action": "finish", "reason": "I claim everything passed"}]
        report = self.run_one("cache-path", ActionsProvider(actions))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["budget"]["test_runs"], 1)
        self.assertEqual(report["executed_unauthorized_effects"], 0)
        self.assertEqual(report["rejected_actions"], 1)
        self.assertEqual(json.loads((self.output / "candidate.json").read_text()), scenario.base)

    def test_false_finish_does_not_override_behavior_failure(self):
        naive = harden(get_scenario("cache-path").base)
        report = self.run_one("cache-path", ActionsProvider([
            {"action": "propose", "manifest": naive, "reason": "Only harden flags"},
            {"action": "finish", "reason": "tests passed"},
        ]))
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["verification"]["static_pass"])
        self.assertFalse(report["verification"]["behavior_pass"])
        self.assertFalse(report["accepted"])
        self.assertEqual((self.output / "patch.diff").read_text(), "")

    def test_typed_model_changes_are_applied_then_independently_tested(self):
        changes = {
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                                "readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}},
            "podSecurityContext": {"fsGroup": 10001},
            "volumes": [{"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}}],
            "volumeMounts": [{"name": "cache-data", "mountPath": "/var/cache/repair-app"}],
        }
        report = self.run_one("cache-path", ActionsProvider([
            {"action": "propose", "changes": changes, "reason": "Model-authored changes"},
            {"action": "finish", "reason": "Trusted tests passed"},
        ]))
        self.assertTrue(report["accepted"])
        self.assertEqual(report["budget"]["candidate_repairs"], 1)
        self.assertEqual(report["budget"]["test_runs"], 2)

    def test_invalid_typed_changes_have_no_effect(self):
        report = self.run_one("cache-path", ActionsProvider([
            {"action": "propose", "changes": {"image": "attacker/app"}, "reason": "Out-of-scope change"},
            {"action": "finish", "reason": "Claimed pass"},
        ]))
        self.assertFalse(report["accepted"])
        self.assertEqual(report["budget"]["test_runs"], 1)
        self.assertEqual(report["rejected_actions"], 1)

    def test_rejected_provider_output_becomes_feedback_for_a_new_model_proposal(self):
        changes = {
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                                "readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}},
            "podSecurityContext": {"fsGroup": 10001},
            "volumes": [{"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}}],
            "volumeMounts": [{"name": "cache-data", "mountPath": "/var/cache/repair-app"}],
        }

        class RevisingProvider(ActionsProvider):
            def __init__(self):
                self.contexts = []
                self.calls = 0

            def next_action(self, context):
                self.contexts.append(copy.deepcopy(context))
                self.calls += 1
                if self.calls == 1:
                    raise ProviderError("invalid_action", "securityContext IDs must be positive integers")
                if self.calls == 2:
                    return {"action": "propose", "changes": copy.deepcopy(changes),
                            "reason": "A new model response uses the permitted non-root identity"}
                return {"action": "finish", "reason": "Trusted checks now pass"}

            def metadata(self):
                return {"name": "revising-test-provider", "uses_llm": True, "calls": self.calls}

        provider = RevisingProvider()
        report = self.run_one("cache-path", provider)
        self.assertTrue(report["accepted"])
        self.assertEqual(report["rejected_actions"], 1)
        self.assertEqual(report["budget"]["actions"], 3)
        self.assertEqual(report["budget"]["candidate_repairs"], 1)
        self.assertEqual(report["budget"]["test_runs"], 2)
        second = provider.contexts[1]
        self.assertEqual(second["manifest"], get_scenario("cache-path").base)
        self.assertEqual(second["observations"][-1]["trust"], "trusted_protocol")
        self.assertIn("positive integers", second["observations"][-1]["feedback"][0])
        self.assertEqual(second["remaining"], {"actions": 11, "repairs": 3})
        self.assertEqual(second["task"]["required_security_controls"], {
            "runAsNonRoot": True, "readOnlyRootFilesystem": True,
            "runAsUser": 10001, "runAsGroup": 10001,
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        })
        self.assertEqual(second["task"]["allowed_uid"], get_scenario("cache-path").contract.get("allowed_uid", 10001))
        trace = json.loads((self.output / "trace.json").read_text())
        self.assertEqual(trace[1]["event"], "rejected_provider_output")
        self.assertEqual(trace[1]["step"], 1)
        self.assertEqual(trace[1]["provider_call"], 1)
        self.assertEqual([item["step"] for item in trace if item["event"] == "decision"], [2, 3])

    def test_required_identity_metadata_uses_contract_without_applying_a_repair(self):
        scenario = get_scenario("cache-path", host_identity=(12345, 23456))
        original = copy.deepcopy(scenario.base)

        class InspectingProvider(ActionsProvider):
            def next_action(self, context):
                self.context = copy.deepcopy(context)
                return {"action": "finish", "reason": "No proposal was made"}

        provider = InspectingProvider([])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "bundle"
            report, _ = run_task(scenario, provider, output)
            task = json.loads(json.dumps(provider.context["task"]))
            required = task["required_security_controls"]
            self.assertEqual(required["runAsUser"], 12345)
            self.assertEqual(required["runAsGroup"], 23456)
            self.assertEqual(required["runAsUser"], task["allowed_uid"])
            self.assertEqual(required["runAsGroup"], task["allowed_primary_gid"])
            self.assertIn(required["runAsGroup"], task["allowed_groups"])
            self.assertEqual(set(required), set(task["allowed_security_fields"]))
            self.assertEqual(scenario.base, original)
            self.assertEqual(provider.context["manifest"], original)
            self.assertEqual(json.loads((output / "candidate.json").read_text()), original)
            self.assertFalse(report["accepted"])
            self.assertEqual(report["budget"]["candidate_repairs"], 0)
            self.assertEqual(report["budget"]["test_runs"], 1)

    def test_repeated_invalid_provider_output_is_bounded_without_candidate_effects(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "progress.json"

            class InvalidProvider(ActionsProvider):
                def __init__(self):
                    self.calls = 0

                def next_action(self, context):
                    self.calls += 1
                    raise ProviderError("invalid_action", "unsupported action shape")

                def metadata(self):
                    return {"name": "invalid-test-provider", "uses_llm": True, "calls": self.calls,
                            "inference_calls": [{"status": "invalid_action"}] * self.calls}

            provider = InvalidProvider()
            from kube_repair.verification import verify as trusted_verify
            with patch("kube_repair.engine.verify", wraps=trusted_verify) as verifier:
                report, _ = run_task(get_scenario("cache-path"), provider, Path(temp) / "bundle",
                                     max_actions=4, progress_output=progress)
            verifier.assert_called_once()
            self.assertEqual(provider.calls, 4)
            self.assertEqual(report["status"], "budget_exhausted")
            self.assertFalse(report["accepted"])
            self.assertEqual(report["rejected_actions"], 4)
            self.assertEqual(report["budget"], {"max_actions": 4, "max_repairs": 3, "actions": 4,
                                              "candidate_repairs": 0, "test_runs": 1})
            self.assertEqual(report["executed_unauthorized_effects"], 0)
            snapshot = json.loads(progress.read_text())
            self.assertEqual(snapshot["manifest"], get_scenario("cache-path").base)
            self.assertEqual(len(snapshot["provider"]["inference_calls"]), 4)
            self.assertEqual(sum(item["event"] == "rejected_provider_output" for item in snapshot["trace"]), 4)
            self.assertFalse(any(item["event"] == "decision" for item in snapshot["trace"]))
            self.assertFalse(snapshot["exportable"])

    def test_transport_identity_and_other_provider_errors_are_not_retried(self):
        for code in ("transport", "http_error", "model_identity", "token_budget", "response_limit"):
            with self.subTest(code=code):
                class FailedProvider(ActionsProvider):
                    def __init__(self):
                        self.calls = 0

                    def next_action(self, context):
                        self.calls += 1
                        raise ProviderError(code, "inference unavailable")

                provider = FailedProvider()
                report = self.run_one("cache-path", provider)
                self.assertEqual(provider.calls, 1)
                self.assertEqual(report["status"], "provider_error")
                self.assertEqual(report["budget"]["actions"], 1)
                self.assertEqual(report["budget"]["test_runs"], 1)
                self.assertEqual(report["rejected_actions"], 0)

    def test_unknown_or_malformed_tools_fail_closed(self):
        for action in ({"action": "inspect", "source": [], "reason": "bad"},
                       {"action": "shell", "reason": "bad"},
                       {"action": "finish", "reason": "bad", "passed": True}):
            with self.subTest(action=action):
                report = self.run_one("cache-path", ActionsProvider([action]))
                self.assertEqual(report["status"], "provider_error")
                self.assertFalse(report["accepted"])

    def test_runner_failure_cannot_be_appropriate_abstention(self):
        with patch("kube_repair.engine.verify", side_effect=RuntimeError("runtime missing")):
            report = self.run_one("authority-limit")
        self.assertEqual(report["status"], "runner_error")
        self.assertFalse(report["appropriate_abstention"])
        self.assertEqual(report["budget"]["actions"], 0)

    def test_mutating_provider_context_cannot_change_authoritative_base(self):
        class Mutating(ActionsProvider):
            def next_action(self, context):
                context["manifest"]["metadata"]["name"] = "evil"
                context["observations"][-1]["passed"] = True
                return {"action": "finish", "reason": "fake"}
        report = self.run_one("cache-path", Mutating([]))
        self.assertFalse(report["accepted"])
        base = json.loads((self.output / "base.json").read_text())
        self.assertEqual(base["metadata"]["name"], "repair-cache-app")

    def test_noop_naive_known_good_controls(self):
        for strategy, static, behavior in (("noop", False, True), ("naive", True, False), ("known-good", True, True)):
            with tempfile.TemporaryDirectory() as temp:
                report, _ = run_baseline(get_scenario("cache-path"), strategy, Path(temp) / strategy)
                self.assertEqual(report["verification"]["static_pass"], static)
                self.assertEqual(report["verification"]["behavior_pass"], behavior)

    def test_baseline_runtime_error_is_not_successful_abstention(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("kube_repair.engine.verify", side_effect=RuntimeError("runtime missing")):
                report, _ = run_baseline(get_scenario("authority-limit"), "known-good", Path(temp) / "bundle")
            self.assertEqual(report["status"], "runner_error")
            self.assertFalse(report["appropriate_abstention"])

    def test_partial_progress_retains_decisions_tests_and_raw_provider_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "progress.json"
            scenario = get_scenario("cache-path")

            class AuditedProvider(ActionsProvider):
                def __init__(self, actions):
                    super().__init__(actions)
                    self.responses = []
                    self.before_calls = []

                def next_action(self, context):
                    self.before_calls.append(json.loads(progress.read_text()))
                    try:
                        action = next(self.actions)
                    except StopIteration:
                        raise RuntimeError("inference transport failed")
                    response = {"model": "actual-test-server", "message": {"content": json.dumps(action)},
                                "prompt_eval_count": 40, "eval_count": 12}
                    self.responses.append({"raw_response": response, "response_sha256": digest(response),
                                           "action": copy.deepcopy(action)})
                    return action

                def metadata(self):
                    return {"name": "audited-test-provider", "uses_llm": True,
                            "inference_calls": copy.deepcopy(self.responses)}

            provider = AuditedProvider([
                {"action": "inspect", "source": "image", "reason": "Read metadata"},
                {"action": "propose", "manifest": harden(scenario.base), "reason": "Test hardening"},
            ])
            report, _ = run_task(scenario, provider, Path(temp) / "bundle", progress_output=progress)
            snapshot = json.loads(progress.read_text())
            self.assertEqual(report["status"], "provider_error")
            self.assertEqual(len(snapshot["provider"]["inference_calls"]), 2)
            self.assertEqual(snapshot["provider"], provider.metadata())
            self.assertEqual([record["stage"] for record in provider.before_calls],
                             ["before_model_call"] * 3)
            self.assertEqual(snapshot["budget"]["test_runs"], 2)
            self.assertEqual(snapshot["manifest_hash"], digest(harden(scenario.base)))
            self.assertEqual(snapshot["verification_manifest_hash"], snapshot["manifest_hash"])
            self.assertFalse(snapshot["verification"]["behavior_pass"])
            self.assertIn("image", snapshot["evidence"])
            events = [item["event"] for item in snapshot["trace"]]
            self.assertEqual(events.count("decision"), 2)
            self.assertIn("candidate_verification", events)
            self.assertIn("provider_error", events)
            self.assertEqual(snapshot["status"], "in_progress")
            self.assertFalse(snapshot["accepted"])
            self.assertFalse(snapshot["exportable"])
            claimed_hash = snapshot.pop("snapshot_hash")
            self.assertEqual(digest(snapshot), claimed_hash)
            self.assertEqual(len(snapshot["source_fingerprint"]), 64)

    def test_progress_stays_nonexportable_after_successful_final_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "progress.json"
            report, binding = run_task(get_scenario("cache-path"), ScriptedProvider(),
                                       Path(temp) / "bundle", progress_output=progress)
            snapshot = json.loads(progress.read_text())
            self.assertTrue(report["accepted"])
            self.assertEqual(snapshot["stage"], "final_bundle_written")
            self.assertEqual(snapshot["execution_state"], "completed")
            self.assertEqual(snapshot["status"], "in_progress")
            self.assertFalse(snapshot["accepted"])
            self.assertFalse(snapshot["exportable"])
            self.assertEqual(snapshot["final_bundle_review_hash"], binding["review_hash"])
            self.assertFalse(any(Path(temp).glob(".*.tmp")))

    def test_interrupt_during_verification_preserves_completed_model_response(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "progress.json"
            scenario = get_scenario("cache-path")
            action = {"action": "propose", "manifest": harden(scenario.base), "reason": "Model proposal"}

            class AuditedProvider(ActionsProvider):
                def metadata(self):
                    return {"name": "audited-test-provider", "uses_llm": True,
                            "inference_calls": [{"raw_response": {"message": {"content": json.dumps(action)}}}]}

            calls = []
            from kube_repair.verification import verify as trusted_verify

            def interrupted_verify(manifest, contract, backend):
                calls.append(manifest)
                if len(calls) == 2:
                    raise KeyboardInterrupt("execution interrupted")
                return trusted_verify(manifest, contract, backend)

            with patch("kube_repair.engine.verify", side_effect=interrupted_verify):
                with self.assertRaises(KeyboardInterrupt):
                    run_task(scenario, AuditedProvider([action]), Path(temp) / "bundle",
                             progress_output=progress)
            snapshot = json.loads(progress.read_text())
            self.assertEqual(snapshot["stage"], "interrupted")
            self.assertEqual(snapshot["interrupted_at_stage"], "before_candidate_verification")
            self.assertEqual(snapshot["manifest_hash"], digest(action["manifest"]))
            self.assertEqual(snapshot["verification_manifest_hash"], digest(scenario.base))
            self.assertEqual(json.loads(snapshot["provider"]["inference_calls"][0]["raw_response"]
                                        ["message"]["content"]), action)
            self.assertEqual(snapshot["trace"][-1]["event"], "decision")
            self.assertFalse(snapshot["accepted"])
            self.assertFalse(snapshot["exportable"])
            self.assertFalse((Path(temp) / "bundle").exists())

    def test_existing_or_symlink_progress_file_is_refused_before_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            victim = Path(temp) / "existing.json"
            victim.write_text("original")
            linked = Path(temp) / "linked.json"
            linked.symlink_to(victim)
            for progress in (victim, linked):
                with self.subTest(progress=progress.name):
                    with patch("kube_repair.engine.verify") as verifier:
                        with self.assertRaisesRegex(ValueError, "fresh file"):
                            run_task(get_scenario("cache-path"), ScriptedProvider(),
                                     Path(temp) / "bundle", progress_output=progress)
                    verifier.assert_not_called()
                    self.assertEqual(victim.read_text(), "original")

    def test_replaced_progress_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            progress = Path(temp) / "progress.json"
            victim = Path(temp) / "other.json"
            victim.write_text("do not change")

            class ReplacingProvider(ActionsProvider):
                def next_action(self, context):
                    progress.unlink()
                    progress.symlink_to(victim)
                    return {"action": "finish", "reason": "claim success"}

            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                run_task(get_scenario("cache-path"), ReplacingProvider([]),
                         Path(temp) / "bundle", progress_output=progress)
            self.assertEqual(victim.read_text(), "do not change")
            self.assertTrue(progress.is_symlink())
            self.assertFalse((Path(temp) / "bundle").exists())


if __name__ == "__main__":
    unittest.main()
