"""Protocol integrity tests; no Kubernetes or model service is started."""
import copy
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kube_robustness import protocol
from kube_robustness.methods import METHODS, sha256


def definitions():
    names = list(protocol.INJECTION_CASES) + ["other-case-" + str(index) for index in range(6)]
    return [{"id": name, "family": "family-" + str(index % 3),
             "instruction": "Preserve behavior and enforce the documented security requirement.",
             "resources": [], "allowed_paths": {}, "expected": "repair" if index < 10 else "abstain",
             "source": {"kind": "unit-fixture"}, "oracle_edits": [{"private": name}],
             "contract": {"private_verifier": name}}
            for index, name in enumerate(names)]


APPROVED = {
    "models": [{"model_id": protocol.MAIN_MODEL, "tag": "approved:3b", "manifest_digest": "sha256:" + "d" * 64}],
    "images": {key: "approved-" + key + "@sha256:" + "f" * 64 for key in ("base", "node", "ollama")},
}


@contextmanager
def fixed_inputs(cases=None):
    cases = definitions() if cases is None else cases
    with patch.object(protocol, "_load_approved", return_value=(copy.deepcopy(APPROVED), "a" * 64)), \
         patch.object(protocol, "source_fingerprint", return_value="b" * 64), \
         patch.object(protocol, "legacy_source_fingerprint", return_value="c" * 64), \
         patch.object(protocol, "all_cases", side_effect=lambda: copy.deepcopy(cases)):
        yield


class RobustnessProtocolTests(unittest.TestCase):
    def test_exact_matrix_is_54_cells_96_calls_and_twelve_underlying_cases(self):
        with fixed_inputs():
            plan = protocol.build_plan()
        self.assertEqual(plan["case_count"], 12)
        self.assertEqual(plan["cell_count"], 54)
        self.assertEqual(sum(METHODS[cell["method_id"]] for cell in plan["cells"]), 96)
        self.assertEqual(len({cell["cell_id"] for cell in plan["cells"]}), 54)
        self.assertEqual({cell["repetition"] for cell in plan["cells"]}, {0})
        self.assertEqual({cell["model_id"] for cell in plan["cells"]}, {protocol.MAIN_MODEL})
        by_case = {case["id"]: [] for case in plan["cases"]}
        for cell in plan["cells"]:
            by_case[cell["case_id"]].append((cell["condition"], cell["method_id"]))
        for case_id, variants in by_case.items():
            with self.subTest(case_id=case_id):
                expected = {("clean", method) for method in ("one-shot", "self-review", "feedback")}
                if case_id in protocol.INJECTION_CASES:
                    expected |= {("clean", "feedback-filtered"), ("injection", "feedback"), ("injection", "feedback-filtered")}
                self.assertEqual(set(variants), expected)

    def test_plan_and_each_case_have_content_derived_identities(self):
        with fixed_inputs():
            plan = protocol.build_plan()
        body = copy.deepcopy(plan)
        plan_id = body.pop("plan_id")
        self.assertEqual(plan_id, "robustness-v2-" + sha256(body))
        for case in plan["cases"]:
            body = copy.deepcopy(case)
            fingerprint = body.pop("definition_sha256")
            self.assertEqual(fingerprint, sha256(body))
            self.assertIn("oracle_edits", case)  # Operator plan preserves protected scoring inputs.

    def test_assignment_is_deterministic_and_spreads_each_method_across_shards(self):
        with fixed_inputs():
            first, second = protocol.build_plan(), protocol.build_plan()
        self.assertEqual(first, second)
        self.assertEqual({cell["shard"] for cell in first["cells"]}, set(range(5)))
        for index, cell in enumerate(first["cells"]):
            self.assertEqual(cell["execution_index"], index)
            self.assertEqual(cell["shard"], index % 5)
        for method in METHODS:
            counts = [sum(cell["method_id"] == method and cell["shard"] == shard for cell in first["cells"])
                      for shard in range(5)]
            self.assertLessEqual(max(counts) - min(counts), 1)

    def test_lock_rejects_changed_source_pin_matrix_or_oracle(self):
        with fixed_inputs():
            original = protocol.build_plan()
            protocol.validate_plan(original)
            mutations = [
                lambda plan: plan.update(source_sha256="0" * 64),
                lambda plan: plan["models"][0].update(tag="unapproved:latest"),
                lambda plan: plan["cells"][0].update(method_id="feedback-filtered"),
                lambda plan: plan["cases"][0]["oracle_edits"].append({"private": "changed"}),
                lambda plan: plan["conditions"][1].update(untrusted_note="different attack"),
            ]
            for mutate in mutations:
                candidate = copy.deepcopy(original)
                mutate(candidate)
                with self.subTest(candidate=candidate["plan_id"]), self.assertRaisesRegex(ValueError, "locked"):
                    protocol.validate_plan(candidate)

    def test_changed_case_source_invalidates_previously_frozen_plan(self):
        with fixed_inputs():
            original = protocol.build_plan()
        changed = definitions()
        changed[0]["instruction"] = "Changed task semantics"
        with fixed_inputs(changed), self.assertRaisesRegex(ValueError, "locked"):
            protocol.validate_plan(original)

    def test_missing_priority_case_or_duplicate_case_cannot_silently_reduce_denominator(self):
        malformed = [definitions()[:-1], definitions()[:-1] + [definitions()[0]]]
        unrelated = definitions()
        unrelated[0]["id"] = "replacement-not-preregistered"
        malformed.append(unrelated)
        for cases in malformed:
            with self.subTest(ids=[case["id"] for case in cases]), fixed_inputs(cases), self.assertRaises(ValueError):
                protocol.build_plan()

    def test_conditions_change_only_the_labeled_untrusted_note(self):
        original = definitions()[0]
        original["untrusted_note"] = "Stale operator note must not leak into clean condition"
        clean = protocol.condition_case(original, "clean")
        injected = protocol.condition_case(original, "injection")
        self.assertNotIn("untrusted_note", clean)
        self.assertEqual(injected.pop("untrusted_note"), protocol.INJECTION_NOTE)
        self.assertEqual(injected, clean)
        self.assertIn("untrusted_note", original)
        with self.assertRaises(ValueError):
            protocol.condition_case(original, "unknown")

    def test_job_caps_fit_declared_remaining_budget_without_claiming_measured_time(self):
        with fixed_inputs():
            budget = protocol.build_plan()["budget"]
        calculated = budget["validation_job_timeout_minutes"] + budget["model_shards"] * budget["model_job_timeout_minutes"] + budget["report_job_timeout_minutes"]
        self.assertEqual(calculated, budget["maximum_runner_minutes"])
        self.assertLessEqual(calculated, 233)
        self.assertIn("not measured", budget["budget_kind"])

    def test_new_source_fingerprint_covers_extra_modules_and_legacy_setup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in list(protocol.EXPLICIT_SOURCE_FILES) + ["src/kube_robustness/" + name for name in ("cases.py", "methods.py", "protocol.py", "runtime.py")]:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("unit fixture\n")
            with patch.object(protocol, "ROOT", root), patch.object(protocol, "legacy_source_fingerprint", return_value="c" * 64):
                first = protocol.source_fingerprint()
                (root / "src/kube_robustness/new_verification_audit.py").write_text("new bound source\n")
                second = protocol.source_fingerprint()
                self.assertNotEqual(first, second)
                with patch.object(protocol, "legacy_source_fingerprint", return_value="d" * 64):
                    self.assertNotEqual(second, protocol.source_fingerprint())

    def test_missing_execution_source_fails_before_freezing_plan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(protocol, "ROOT", Path(temporary)):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                protocol.source_fingerprint()

    def test_freezer_refuses_to_overwrite_existing_evidence(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("robustness_freezer_test", root / "scripts/freeze_robustness_plan.py")
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with fixed_inputs():
            plan = protocol.build_plan()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "plan.json"
            with patch.object(script, "build_plan", return_value=plan), \
                 patch("sys.argv", ["freeze", "--output", str(output)]), redirect_stdout(io.StringIO()):
                script.main()
                original = output.read_bytes()
                with self.assertRaises(FileExistsError):
                    script.main()
            self.assertEqual(output.read_bytes(), original)
            self.assertEqual(json.loads(original)["plan_id"], plan["plan_id"])


if __name__ == "__main__":
    unittest.main()
