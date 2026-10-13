import copy
import unittest

from kube_repair.policy import harden, repair_storage, validate_candidate
from kube_repair.scenarios import get_scenario


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.scenario = get_scenario("cache-path")
        self.good = repair_storage(harden(self.scenario.base), self.scenario.contract)

    def check_rejected(self, candidate):
        self.assertTrue(validate_candidate(self.scenario.base, candidate, self.scenario.contract))

    def test_authorized_repair_and_original_unchanged(self):
        self.assertEqual(validate_candidate(self.scenario.base, self.good, self.scenario.contract), [])
        self.assertEqual(self.scenario.base["spec"]["template"]["spec"]["containers"][0]["securityContext"], {"runAsUser": 0})

    def test_image_identity_and_scanner_suppression_protected(self):
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["containers"][0]["image"] = "attacker/health-only:latest"
        self.check_rejected(changed)
        changed = copy.deepcopy(self.good)
        changed["metadata"]["annotations"] = {"checkov.io/skip1": "CKV_K8S_22"}
        self.check_rejected(changed)

    def test_hostpath_and_unapproved_mount_rejected(self):
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["volumes"] = [{"name": "cache-data", "hostPath": {"path": "/"}}]
        self.check_rejected(changed)
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]["mountPath"] = "/"
        self.check_rejected(changed)

    def test_deleted_workload_and_added_sidecar_rejected(self):
        self.check_rejected({})
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["containers"].append({"name": "extra", "image": "x"})
        self.check_rejected(changed)

    def test_same_value_different_protected_json_type_rejected(self):
        changed = copy.deepcopy(self.good)
        changed["spec"]["replicas"] = True
        self.check_rejected(changed)

    def test_privilege_addition_or_widened_volume_rejected(self):
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["containers"][0]["securityContext"]["capabilities"] = {"drop": ["ALL"], "add": ["SYS_ADMIN"]}
        self.check_rejected(changed)
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["volumes"][0]["emptyDir"]["sizeLimit"] = "1Gi"
        self.check_rejected(changed)

    def test_malformed_security_and_nan_rejected(self):
        changed = copy.deepcopy(self.good)
        changed["spec"]["template"]["spec"]["securityContext"] = []
        self.check_rejected(changed)
        changed = copy.deepcopy(self.good)
        changed["spec"]["replicas"] = float("nan")
        self.check_rejected(changed)


if __name__ == "__main__":
    unittest.main()
