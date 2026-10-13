import copy
import json
import unittest
from unittest.mock import patch

from kube_repair.kubernetes_backend import OWNER_LABEL, image_digest, verify_kubernetes
from kube_repair.policy import harden, repair_storage
from kube_repair.scenarios import get_scenario
from kube_repair.verification import _RUNTIME_CHECKS

IMAGE_ID = "containerd://sha256:" + "a" * 64


class FakeKubectl:
    def __init__(self, startup_failure=False, wrong_image=False, changed_owner=False, cleanup_failure=False, malformed=False):
        self.calls = []
        self.ns = None
        self.deployment = None
        self.startup_failure = startup_failure
        self.wrong_image = wrong_image
        self.changed_owner = changed_owner
        self.cleanup_failure = cleanup_failure
        self.malformed = malformed

    def __call__(self, argv, *, input_value=None, timeout=8):
        self.calls.append((argv, input_value))
        if "version" in argv:
            data = {"serverVersion": {"gitVersion": "v1.34.0"}}
        elif "create" in argv:
            self.ns = copy.deepcopy(input_value)
            self.ns["metadata"]["uid"] = "namespace-uid"
            data = self.ns
        elif "apply" in argv:
            self.deployment = copy.deepcopy(input_value)
            self.deployment["metadata"].update(uid="deployment-uid", generation=1)
            data = self.deployment
        elif "delete" in argv:
            if self.cleanup_failure:
                return 1, "", "cleanup unavailable"
            return 0, "deleted", ""
        elif "logs" in argv:
            return 0, "Cache initialization failed: Read-only file system", ""
        elif "exec" in argv:
            if self.malformed:
                data = {"application-cache": [True, "forged partial inventory"]}
            else:
                data = {name: [True, "mocked protocol evidence"] for name in _RUNTIME_CHECKS}
        elif "get" in argv:
            kind = argv[argv.index("get") + 1]
            if kind == "namespace":
                data = copy.deepcopy(self.ns)
                if self.changed_owner:
                    data["metadata"]["uid"] = "foreign-namespace-uid"
            elif kind == "deployment":
                data = self.deployment
            elif kind == "replicaset":
                data = {"metadata": {"uid": "replica-uid", "ownerReferences": [
                    {"kind": "Deployment", "uid": "deployment-uid", "controller": True}]}}
            elif kind in ("pods", "pod"):
                app = {"name": "app", "ready": not self.startup_failure,
                       "imageID": "containerd://sha256:" + ("b" if self.wrong_image else "a") * 64,
                       "state": {"terminated": {"exitCode": 1}} if self.startup_failure else {"running": {}}}
                pod = {"metadata": {"name": "fixture-pod", "uid": "pod-uid", "ownerReferences": [
                    {"kind": "ReplicaSet", "name": "fixture-replica", "uid": "replica-uid", "controller": True}]},
                    "status": {"containerStatuses": [app]}}
                data = {"items": [pod]} if kind == "pods" else pod
            else:
                raise AssertionError(argv)
        else:
            raise AssertionError(argv)
        return 0, json.dumps(data), ""


class KubernetesProtocolTests(unittest.TestCase):
    def setUp(self):
        scenario = get_scenario("cache-path", image="repair-cache-app:unique-source-tag")
        self.manifest = repair_storage(harden(scenario.base), scenario.contract)
        self.contract = copy.deepcopy(scenario.contract)
        self.contract["kubernetes"] = {"context": "kind-private-lab", "kubeconfig": "/private/lab-config",
                                       "kubectl": "/trusted/kubectl", "expected_image_id": IMAGE_ID}

    def evaluate(self, fake):
        with patch("kube_repair.kubernetes_backend.command", side_effect=fake):
            return verify_kubernetes(self.manifest, self.contract)

    def test_protocol_pins_context_image_and_owns_namespace(self):
        fake = FakeKubectl()
        result = self.evaluate(fake)
        self.assertTrue(result["passed"])
        self.assertTrue(result["runtime_verified"])
        self.assertEqual(result["runtime"]["image_id"], IMAGE_ID)
        self.assertEqual(result["runtime"]["pod_uid"], "pod-uid")
        self.assertEqual(result["runtime"]["generation"], 1)
        for argv, _ in fake.calls:
            self.assertEqual(argv[1:3], ["--context", "kind-private-lab"])
            self.assertIn("/private/lab-config", argv)
            self.assertNotIn("use-context", argv)
        deletion = [argv for argv, _ in fake.calls if "delete" in argv]
        self.assertEqual(len(deletion), 1)
        self.assertTrue(deletion[0][deletion[0].index("namespace") + 1].startswith("kube-repair-"))

    def test_real_startup_failure_is_behavior_failure(self):
        result = self.evaluate(FakeKubectl(startup_failure=True))
        self.assertFalse(result["passed"])
        self.assertTrue(result["static_pass"])
        self.assertFalse(result["behavior_pass"])
        self.assertIsNone(result["infrastructure_error"])
        self.assertIn("Read-only", " ".join(result["feedback"]))

    def test_wrong_image_fails_before_probe_and_cleans_up(self):
        fake = FakeKubectl(wrong_image=True)
        result = self.evaluate(fake)
        self.assertFalse(result["passed"])
        self.assertIn("image identity", result["infrastructure_error"])
        self.assertFalse(any("exec" in argv for argv, _ in fake.calls))
        self.assertTrue(any("delete" in argv for argv, _ in fake.calls))

    def test_foreign_namespace_is_never_deleted(self):
        fake = FakeKubectl(changed_owner=True)
        result = self.evaluate(fake)
        self.assertFalse(result["passed"])
        self.assertIn("deletion refused", result["infrastructure_error"])
        self.assertFalse(any("delete" in argv for argv, _ in fake.calls))

    def test_cleanup_failure_and_partial_probe_cannot_pass(self):
        for fake in (FakeKubectl(cleanup_failure=True), FakeKubectl(malformed=True)):
            with self.subTest(fake=fake):
                result = self.evaluate(fake)
                self.assertFalse(result["passed"])
                self.assertIsNotNone(result["infrastructure_error"])

    def test_context_and_image_pin_required_before_any_command(self):
        for field in ("context", "expected_image_id"):
            contract = copy.deepcopy(self.contract)
            contract["kubernetes"].pop(field)
            with patch("kube_repair.kubernetes_backend.command") as cli:
                result = verify_kubernetes(self.manifest, contract)
            self.assertFalse(result["passed"])
            cli.assert_not_called()

    def test_unsupported_group_and_credential_mount_rejected(self):
        for key in ("volume_gid", "credential_mount"):
            candidate, contract = copy.deepcopy(self.manifest), copy.deepcopy(self.contract)
            if key == "volume_gid":
                contract[key] = 2000
            else:
                candidate["spec"]["template"]["spec"]["automountServiceAccountToken"] = True
            with patch("kube_repair.kubernetes_backend.command") as cli:
                result = verify_kubernetes(candidate, contract)
            self.assertFalse(result["passed"])
            cli.assert_not_called()

    def test_digest_normalization_does_not_guess_config_manifest_equivalence(self):
        expected = "sha256:" + "a" * 64
        for value in (expected, IMAGE_ID, "docker-pullable://repo@" + expected):
            self.assertEqual(image_digest(value), expected)
        with self.assertRaises(ValueError):
            image_digest("repair-cache-app:latest")


if __name__ == "__main__":
    unittest.main()
