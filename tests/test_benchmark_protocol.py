"""Freeze integrity and collection tests; these do not claim runtime results."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from kube_repair.benchmark_protocol import make_plan, validate_locked_plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("benchmark_collector_tests", ROOT / "scripts/collect_benchmark.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class FrozenProtocolTests(unittest.TestCase):
    def plan(self):
        return make_plan(json.loads((ROOT / "benchmark/models.json").read_text()))

    def test_frozen_campaign_is_96_tasks_within_authorized_budget(self):
        plan = self.plan()
        self.assertEqual(validate_locked_plan(plan), plan)
        self.assertEqual(plan["primary_expected_model_tasks"], 96)
        self.assertEqual(len(plan["cases"]), 8)
        self.assertEqual(plan["development_cases_excluded"], ["dev-original-cache"])
        self.assertLessEqual(plan["runner_budget"]["campaign_timeout_upper_bound_minutes"], 1000)

    def test_changed_model_case_method_settings_and_source_are_refused(self):
        for change in (lambda p: p["models"][0].update(manifest_digest="sha256:" + "f" * 64),
                       lambda p: p["cases"].pop(),
                       lambda p: p["methods"][0].update(max_actions=2),
                       lambda p: p["settings"].update(temperature=1),
                       lambda p: p.update(source_fingerprint="f" * 64),
                       lambda p: p.update(plan_id="pretend-plan")):
            with self.subTest(change=change):
                plan = self.plan()
                change(plan)
                with self.assertRaises(ValueError):
                    validate_locked_plan(plan)

    def test_empty_or_missing_shards_report_all_missing_instead_of_zero_success_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = self.plan()
            path = root / "plan.json"
            path.write_text(json.dumps(plan))
            summary = collector.collect(path, root / "missing-input", root / "reports")
            self.assertEqual(summary["coverage"]["expected_trials"], 96)
            self.assertEqual(summary["coverage"]["observed_trials"], 0)
            collection = json.loads((root / "reports/collection.json").read_text())
            self.assertEqual(len(collection["missing_shards"]), 48)
            self.assertTrue((root / "reports/index.html").is_file())

    def test_collector_rejects_unregistered_shards_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "plan.json"
            path.write_text(json.dumps(self.plan()))
            shards = root / "shards"
            (shards / "unregistered-model").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "Unregistered shard"):
                collector.collect(path, shards, root / "output")
            source = root / "source"
            source.mkdir()
            (source / "commands.json").symlink_to(path)
            with self.assertRaisesRegex(ValueError, "symlink"):
                collector.copy_shard(source, root / "copy")

    def test_fixed_control_case_requires_all_registered_executions(self):
        plan = self.plan()
        row = {"case_id": plan["cases"][0]["case_id"], "control_id": "template",
               "task_correct": True, "static_pass": True, "behavior_pass": True,
               "security_pass": True, "infrastructure_error": None}
        partial = collector.fixed_control_report(plan, [row])
        group = next(group for group in partial["groups"] if group["control_id"] == "template")
        self.assertEqual(group["observed_cases"], 1)
        self.assertEqual(group["complete_cases"], 0)
        self.assertEqual(group["all_registered_executions_correct_cases"], 0)
        # These are synthetic unit inputs, never exported as benchmark evidence.
        complete = collector.fixed_control_report(plan, [copy.deepcopy(row) for _ in range(12)])
        group = next(group for group in complete["groups"] if group["control_id"] == "template")
        self.assertEqual(group["complete_cases"], 1)
        self.assertEqual(group["all_registered_executions_correct_cases"], 1)
        self.assertEqual(group["expected_cases"], 8)
