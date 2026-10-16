"""Mocked startup-log observations; these are not Kubernetes benchmark results."""
import copy
import json
import unittest
from unittest.mock import patch

from kube_robustness_v3.cases import all_cases
from kube_robustness_v3.runtime import KubernetesSession, OWNER, PROBE


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class LogReadinessTests(unittest.TestCase):
    def session(self, *, outputs, fatal=False):
        case = next(case for case in all_cases() if case["id"] == "already-secure-cache")
        session = KubernetesSession(case, kubectl="unit-kubectl", context="unit-context", kubeconfig="unit-config",
                                    image="unit-image", commands=[], expected_image_id="sha256:" + "a" * 64)
        session.uid = "unit-namespace-uid"
        session.current = copy.deepcopy(session.case["resources"])
        session.resource_uids = {"Deployment/filesystem-app": "unit-deployment-uid"}
        resource = copy.deepcopy(session.current[0])
        resource["metadata"].update(uid="unit-deployment-uid", generation=1)
        resource["status"] = {"observedGeneration": 1, "replicas": 1, "updatedReplicas": 1,
                              "readyReplicas": 0 if fatal else 1, "availableReplicas": 0 if fatal else 1}
        owner = {"kind": "ReplicaSet", "name": "unit-current-rs", "uid": "unit-rs-uid", "controller": True}
        pod = {"metadata": {"name": "unit-current-pod", "uid": "unit-pod-uid", "ownerReferences": [owner]},
               "spec": copy.deepcopy(resource["spec"]["template"]["spec"]),
               "status": {"containerStatuses": [{"name": "app", "imageID": "sha256:" + "a" * 64, "ready": not fatal,
                            "state": {"terminated": {"exitCode": 1}} if fatal else {"running": {"startedAt": "unit-start"}}}]}}
        replica = {"metadata": {"name": "unit-current-rs", "uid": "unit-rs-uid", "ownerReferences": [
                   {"kind": "Deployment", "name": "filesystem-app", "uid": "unit-deployment-uid", "controller": True}]},
                   "spec": {"template": {"spec": copy.deepcopy(pod["spec"])}}}
        observed = {"log_calls": [], "exec_calls": [], "apply_calls": []}

        def read(args):
            if args == ["version"]:
                return {"serverVersion": {"gitVersion": "v1.34.0"}}
            if args == ["get", "namespace", session.namespace]:
                return {"metadata": {"uid": session.uid, "labels": {OWNER: session.owner,
                         "pod-security.kubernetes.io/enforce": "restricted", "pod-security.kubernetes.io/enforce-version": "v1.34"}}}
            if args[-1] == "pods":
                return {"items": [copy.deepcopy(pod)]}
            if "replicaset" in args:
                return copy.deepcopy(replica)
            if "deployment" in args or "Deployment/filesystem-app" in args:
                return copy.deepcopy(resource)
            raise AssertionError("Unexpected read: " + repr(args))

        def call(args, value=None, **kwargs):
            if "logs" in args:
                observed["log_calls"].append(list(args))
                index = min(len(observed["log_calls"]) - 1, len(outputs) - 1)
                row = {"exit_code": 0, "stdout": outputs[index], "stderr": ""}
            elif "exec" in args:
                observed["exec_calls"].append(list(args))
                self.assertEqual(args[-1], PROBE)
                row = {"exit_code": 0, "stdout": json.dumps({"uid": 10001, "gid": 10001, "no_new_privileges": 1,
                       "capabilities": 0, "seccomp": 2, "root_readonly": True}), "stderr": ""}
            elif "apply" in args:
                observed["apply_calls"].append(list(args))
                raise AssertionError("Polling must never reapply a repair")
            else:
                raise AssertionError("Unexpected call: " + repr(args))
            session.commands.append({"argv": list(args), **row})
            return row

        session.read, session.call = read, call
        return session, observed

    def verify_with_clock(self, session, wait):
        clock = Clock()
        with patch("kube_robustness_v3.runtime.time.monotonic", clock.monotonic), patch("kube_robustness_v3.runtime.time.sleep", clock.sleep):
            result = session.verify(session.case["resources"], max_wait=wait)
        return result, clock

    def test_ready_workload_first_empty_log_then_marker_is_observed(self):
        session, observed = self.session(outputs=["", "cache write and read succeeded\n"])
        result, clock = self.verify_with_clock(session, 2)
        self.assertTrue(result["passed"], [row for row in result["checks"] if not row["passed"]])
        self.assertEqual(len(observed["log_calls"]), 2)
        self.assertEqual(len(observed["exec_calls"]), 1)
        self.assertEqual(observed["apply_calls"], [])
        self.assertLess(clock.now, 2)
        self.assertEqual(result["runtime"]["behavior_logs"][0]["pod"], "unit-current-pod")
        for argv in observed["log_calls"]:
            self.assertEqual(argv[argv.index("logs") + 1], "unit-current-pod")

    def test_persistent_empty_log_stops_at_existing_deadline_without_probe(self):
        session, observed = self.session(outputs=[""])
        result, clock = self.verify_with_clock(session, 1)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["infrastructure_error"])
        self.assertEqual(clock.now, 1)
        self.assertEqual(len(observed["log_calls"]), 3)
        self.assertEqual(observed["exec_calls"], [])
        self.assertEqual(observed["apply_calls"], [])
        self.assertTrue(any(row["name"].startswith("behavior:log:") and not row["passed"] for row in result["checks"]))

    def test_fatal_workload_gets_one_diagnostic_read_without_log_polling(self):
        session, observed = self.session(outputs=["application failed"], fatal=True)
        result, clock = self.verify_with_clock(session, 2)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["infrastructure_error"])
        self.assertEqual(len(observed["log_calls"]), 1)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(observed["exec_calls"], [])
        self.assertEqual(observed["apply_calls"], [])


if __name__ == "__main__":
    unittest.main()
