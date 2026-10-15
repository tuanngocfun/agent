"""Regressions using historical API evidence, never new benchmark results."""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from kube_robustness.runtime import contains_desired, deployment_ready


FIXTURE = Path(__file__).parent / "fixtures/robustness-v2/api-default-omission.json"


class HistoricalApiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text())
        cls.observed = {name: json.loads(row["stdout"]) for name, row in cls.fixture["responses"].items()}
        cls.desired = next(row for row in cls.fixture["desired_resources"] if row["kind"] == "Deployment")
        cls.desired_spec = cls.desired["spec"]["template"]["spec"]

    def test_fixture_retains_exact_historical_response_hashes_and_failed_status(self):
        self.assertFalse(self.fixture["eligible_benchmark_result"])
        self.assertEqual(self.fixture["provenance"]["workflow_run_id"], 38738048984)
        self.assertEqual(self.fixture["provenance"]["historical_pilot_status"], "failed")
        self.assertEqual(self.fixture["provenance"]["original_control_outcome"], "failed")
        for row in self.fixture["responses"].values():
            self.assertEqual(hashlib.sha256(row["stdout"].encode()).hexdigest(), row["stdout_sha256"])
            self.assertEqual(row["exit_code"], 0)

    def test_real_pod_and_replicaset_match_when_api_omits_false_mount_flag(self):
        self.assertIs(self.desired_spec["containers"][0]["volumeMounts"][0]["readOnly"], False)
        pod = self.observed["ready_pod_list"]["items"][0]
        replica = self.observed["current_replica_set"]
        deployment = self.observed["ready_deployment"]
        for observed_spec in (pod["spec"], replica["spec"]["template"]["spec"], deployment["spec"]["template"]["spec"]):
            self.assertNotIn("readOnly", observed_spec["containers"][0]["volumeMounts"][0])
            self.assertTrue(contains_desired(self.desired_spec, observed_spec))

    def test_real_pod_owner_chain_binds_to_the_expected_deployment(self):
        pod = self.observed["ready_pod_list"]["items"][0]
        replica = self.observed["current_replica_set"]
        deployment = self.observed["ready_deployment"]
        pod_owner = next(row for row in pod["metadata"]["ownerReferences"] if row.get("controller"))
        replica_owner = next(row for row in replica["metadata"]["ownerReferences"] if row.get("controller"))
        self.assertEqual(pod_owner["uid"], replica["metadata"]["uid"])
        self.assertEqual(replica_owner["uid"], deployment["metadata"]["uid"])
        self.assertEqual(pod["status"]["containerStatuses"][0]["state"].keys(), {"running"})

    def test_server_default_tolerance_does_not_accept_a_readonly_mount(self):
        observed = copy.deepcopy(self.observed["ready_pod_list"]["items"][0]["spec"])
        observed["containers"][0]["volumeMounts"][0]["readOnly"] = True
        self.assertFalse(contains_desired(self.desired_spec, observed))

    def test_false_default_tolerance_does_not_hide_other_security_or_type_changes(self):
        observed = copy.deepcopy(self.observed["ready_pod_list"]["items"][0]["spec"])
        del observed["containers"][0]["securityContext"]["allowPrivilegeEscalation"]
        self.assertFalse(contains_desired(self.desired_spec, observed))
        observed = copy.deepcopy(self.observed["ready_pod_list"]["items"][0]["spec"])
        observed["containers"][0]["volumeMounts"][0]["readOnly"] = 0
        self.assertFalse(contains_desired(self.desired_spec, observed))

    def test_actual_single_replica_is_ready_but_old_rollout_snapshot_is_not(self):
        ready = self.observed["ready_deployment"]
        transitioning = self.observed["transitioning_deployment"]
        self.assertTrue(deployment_ready(ready))
        self.assertEqual(transitioning["status"]["availableReplicas"], 1)
        self.assertEqual(transitioning["status"]["updatedReplicas"], 1)
        self.assertEqual(transitioning["status"]["replicas"], 2)
        self.assertFalse(deployment_ready(transitioning))


if __name__ == "__main__":
    unittest.main()
