import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kube_repair.engine import run_baseline, run_task
from kube_repair.policy import harden
from kube_repair.providers import ScriptedProvider
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


if __name__ == "__main__":
    unittest.main()
