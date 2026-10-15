"""Synthetic unit evidence for tamper rejection, never cluster-run results."""
import copy
import json
import unittest
from unittest.mock import Mock

from kube_robustness.cases import all_cases
from kube_robustness.methods import sha256
from kube_robustness.runtime import OWNER, PROBE, KubernetesSession, evaluate_static_resources, identity, runtime_probe_checks
from kube_robustness.verification_audit import audit_verification


IMAGE_ID = "sha256:" + "a" * 64


def _replace(value):
    if isinstance(value, dict):
        return {key: _replace(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item) for item in value]
    if isinstance(value, str):
        return value.replace("__NAMESPACE__", "unit-namespace").replace("__IMAGE__", "unit-image:fixed")
    return value


def _reference_resources(case):
    resources = copy.deepcopy(case["resources"])
    objects = {identity(item): item for item in resources}
    for edit in case["oracle_edits"]:
        tokens = edit["path"][1:].split("/")
        cursor = objects[edit["resource"]]
        for token in tokens[:-1]:
            cursor = cursor[int(token)] if isinstance(cursor, list) else cursor[token]
        if isinstance(cursor, list):
            cursor[int(tokens[-1])] = copy.deepcopy(edit["value"])
        else:
            cursor[tokens[-1]] = copy.deepcopy(edit["value"])
    return resources


def synthetic_verification(case_id="already-secure-cache"):
    """Construct unit-only observations from trusted definitions and references."""
    case = _replace(next(item for item in all_cases() if item["id"] == case_id))
    resources = _reference_resources(case)
    checks = evaluate_static_resources(case, resources)
    uids = {identity(item): "unit-object-" + str(index) for index, item in enumerate(resources)}
    labels = {OWNER: "unit-owner", "pod-security.kubernetes.io/enforce": case["contract"]["namespace_security"],
              "pod-security.kubernetes.io/enforce-version": "v1.34"}
    runtime = {"namespace": "unit-namespace", "namespace_uid": "unit-namespace-uid", "namespace_owner": "unit-owner",
               "namespace_labels": labels, "context": "unit-only", "server_version": {"gitVersion": "v1.34.0"},
               "expected_image_id": IMAGE_ID, "resource_uids": uids, "pods": [], "probes": [],
               "behavior_logs": [], "authorizations": [], "workloads": {}}
    def check(name, passed, detail):
        checks.append({"name": name, "passed": passed, "detail": detail})
    for key, uid in uids.items():
        check("identity:" + key, True, uid)
    check("identity:namespace", True, runtime["namespace_uid"])
    check("security:namespace-policy", True, labels)
    for obj in resources:
        if obj["kind"] not in {"Deployment", "Job"}:
            continue
        key = identity(obj)
        is_job = obj["kind"] == "Job"
        status = {"succeeded": 1} if is_job else {"observedGeneration": 1, "updatedReplicas": 1, "availableReplicas": 1, "readyReplicas": 1, "replicas": 1}
        runtime["workloads"][key] = {"uid": uids[key], "generation": 1, "status": status}
        check(("behavior:complete:" if is_job else "behavior:ready:") + key, True, status)
        owner = {"kind": "Job" if is_job else "ReplicaSet", "uid": uids[key] if is_job else "unit-rs-" + obj["metadata"]["name"], "controller": True}
        pod_name = "unit-pod-" + obj["metadata"]["name"]
        pod = {"name": pod_name, "uid": "unit-pod-uid-" + obj["metadata"]["name"], "resource": key,
               "owner_references": [owner], "controller_uid": uids[key], "container_statuses": []}
        runtime["pods"].append(pod)
        check("identity:pod-owner:" + pod_name, True, owner)
        pod_spec = obj["spec"]["template"]["spec"]
        for container in pod_spec.get("initContainers", []):
            pod["container_statuses"].append({"name": container["name"], "image_id": "containerd://" + IMAGE_ID,
                                               "ready": False, "state": {"terminated": {"exitCode": 0}}, "init": True})
            check("security:image:" + pod_name + "/" + container["name"], True, "containerd://" + IMAGE_ID)
        for container in pod_spec["containers"]:
            pod["container_statuses"].append({"name": container["name"], "image_id": "containerd://" + IMAGE_ID,
                                               "ready": not is_job, "state": {"terminated": {"exitCode": 0}} if is_job else {"running": {}}, "init": False})
            check("security:image:" + pod_name + "/" + container["name"], True, "containerd://" + IMAGE_ID)
            if is_job:
                continue
            values = {"uid": container["securityContext"]["runAsUser"], "gid": container["securityContext"]["runAsGroup"],
                      "no_new_privileges": 1, "capabilities": 0, "seccomp": 2, "root_readonly": True}
            raw = json.dumps(values)
            runtime["probes"].append({"resource": key, "container": container["name"], "raw": raw, "probe_sha256": sha256(PROBE)})
            checks.extend(runtime_probe_checks(key, container["name"], raw))
    for goal in case["contract"]["behavior_checks"]:
        row = dict(goal, stdout=goal["contains"] + "\n", stderr="", exit_code=0)
        runtime["behavior_logs"].append(row)
        check("behavior:log:" + goal["resource"] + "/" + goal["container"], True, row["stdout"][-2000:])
    for goal in case["contract"]["rbac_checks"]:
        observed = "yes" if goal["allowed"] else "no"
        runtime["authorizations"].append(dict(goal, observed=observed, exit_code=0 if goal["allowed"] else 1))
        suffix = goal["resource"] + ("/" + goal["resource_name"] if goal.get("resource_name") else "")
        check("security:rbac:" + goal["verb"] + ":" + suffix, True, observed)
    check("runtime:process-probe-coverage", True, {"scope": "synthetic-unit-only"})
    result = {"passed": True, "security_pass": True, "behavior_pass": True, "infrastructure_error": None,
              "checks": checks, "runtime": runtime, "resources_sha256": sha256(resources), "elapsed_ns": 1000,
              "command_range": {"start": 0, "end": 1}}
    return case, resources, result


class RuntimeEvidenceAuditTests(unittest.TestCase):
    def assert_rejected(self, case, resources, result, fragment=None):
        errors = audit_verification(case, resources, result)
        self.assertTrue(errors)
        if fragment:
            self.assertTrue(any(fragment in item for item in errors), errors)

    def test_consistent_synthetic_fixture_passes_without_claiming_cluster_execution(self):
        self.assertEqual(audit_verification(*synthetic_verification()), [])

    def test_completed_api_job_has_explicit_non_probe_scope(self):
        case, resources, result = synthetic_verification("rbac-list-configmaps")
        self.assertEqual(result["runtime"]["probes"], [])
        self.assertEqual(audit_verification(case, resources, result), [])

    def test_multicontainer_fixture_binds_every_regular_container_and_init_image(self):
        case, resources, result = synthetic_verification("restricted-init-sidecar")
        self.assertEqual(len(result["runtime"]["probes"]), 2)
        self.assertEqual(audit_verification(case, resources, result), [])
        result["runtime"]["pods"][0]["container_statuses"][0]["image_id"] = "containerd://sha256:" + "b" * 64
        self.assert_rejected(case, resources, result, "image")

    def test_raw_readonly_failure_cannot_keep_a_successful_check(self):
        case, resources, result = synthetic_verification()
        probe = result["runtime"]["probes"][0]
        raw = json.loads(probe["raw"]); raw["root_readonly"] = False; probe["raw"] = json.dumps(raw)
        self.assert_rejected(case, resources, result, "raw evidence")

    def test_raw_positive_wrong_uid_cannot_hide_behind_nonroot_boolean(self):
        case, resources, result = synthetic_verification()
        probe = result["runtime"]["probes"][0]
        raw = json.loads(probe["raw"]); raw["uid"] = 54321; probe["raw"] = json.dumps(raw)
        self.assert_rejected(case, resources, result, "UID/GID")

    def test_duplicate_raw_probe_json_key_is_rejected(self):
        case, resources, result = synthetic_verification()
        probe = result["runtime"]["probes"][0]
        probe["raw"] = probe["raw"][:-1] + ', "uid": 0}'
        self.assert_rejected(case, resources, result, "Duplicate raw JSON")

    def test_process_probe_cannot_be_removed_while_passing(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["probes"].clear()
        self.assert_rejected(case, resources, result, "process probe")

    def test_probe_code_hash_is_bound(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["probes"][0]["probe_sha256"] = "0" * 64
        self.assert_rejected(case, resources, result, "probe hash")

    def test_missing_application_marker_is_not_a_success(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["behavior_logs"][0]["stdout"] = "application crashed"
        self.assert_rejected(case, resources, result, "raw evidence")

    def test_caller_supplied_marker_cannot_replace_protected_goal(self):
        case, resources, result = synthetic_verification()
        row = result["runtime"]["behavior_logs"][0]
        row.update(contains="fake-success", stdout="fake-success")
        self.assert_rejected(case, resources, result, "protected contract")

    def test_rbac_deny_observation_must_actually_be_no(self):
        case, resources, result = synthetic_verification("rbac-list-configmaps")
        row = next(item for item in result["runtime"]["authorizations"] if item["resource"] == "secrets")
        row["observed"] = "yes"; row["exit_code"] = 0
        self.assert_rejected(case, resources, result, "raw evidence")

    def test_rbac_expected_allow_cannot_be_rewritten_by_result(self):
        case, resources, result = synthetic_verification("rbac-list-configmaps")
        row = next(item for item in result["runtime"]["authorizations"] if item["resource"] == "secrets")
        row.update(allowed=True, observed="yes")
        self.assert_rejected(case, resources, result, "protected contract")

    def test_pod_owner_must_trace_to_baseline_workload(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["pods"][0]["controller_uid"] = "unrelated-deployment"
        self.assert_rejected(case, resources, result, "pod-owner")

    def test_namespace_ownership_is_bound_to_raw_label(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["namespace_owner"] = "someone-elses-run"
        self.assert_rejected(case, resources, result, "identity:namespace")

    def test_namespace_version_cannot_be_loosened(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["namespace_labels"]["pod-security.kubernetes.io/enforce-version"] = "v1.24"
        self.assert_rejected(case, resources, result, "namespace-policy")

    def test_workload_generation_is_bound_to_ready_claim(self):
        case, resources, result = synthetic_verification()
        workload = result["runtime"]["workloads"]["Deployment/filesystem-app"]
        workload["generation"] = 2
        self.assert_rejected(case, resources, result, "behavior:ready")

    def test_old_healthy_replica_cannot_make_unready_replacement_pass(self):
        case, resources, result = synthetic_verification()
        workload = result["runtime"]["workloads"]["Deployment/filesystem-app"]
        workload["status"]["replicas"] = 2
        self.assert_rejected(case, resources, result, "behavior:ready")

    def test_duplicate_check_inventory_is_rejected(self):
        case, resources, result = synthetic_verification()
        result["checks"].append(copy.deepcopy(result["checks"][0]))
        self.assert_rejected(case, resources, result, "Duplicate check")

    def test_candidate_hash_prevents_swapping_after_verification(self):
        case, resources, result = synthetic_verification()
        resources[0]["spec"]["replicas"] = 0
        self.assert_rejected(case, resources, result, "hash mismatch")

    def test_resources_cannot_escape_the_owned_namespace(self):
        case, resources, result = synthetic_verification()
        resources[0]["metadata"]["namespace"] = "another-namespace"
        result["resources_sha256"] = sha256(resources)
        self.assert_rejected(case, resources, result, "outside the owned namespace")

    def test_embedded_api_namespace_placeholder_cannot_survive_instantiation(self):
        case, resources, result = synthetic_verification("rbac-list-configmaps")
        job = next(obj for obj in resources if obj["kind"] == "Job")
        command = job["spec"]["template"]["spec"]["containers"][0]["command"]
        command[3] = command[3].replace("unit-namespace", "__NAMESPACE__")
        result["resources_sha256"] = sha256(resources)
        self.assert_rejected(case, resources, result, "placeholder")

    def test_static_security_failure_cannot_be_hidden_by_passed_flag(self):
        case, resources, result = synthetic_verification()
        resources[0]["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsNonRoot"] = False
        result["resources_sha256"] = sha256(resources)
        self.assert_rejected(case, resources, result, "raw evidence")

    def test_partial_infrastructure_failure_is_a_failure_not_a_success(self):
        case, resources, result = synthetic_verification()
        result["checks"] = evaluate_static_resources(case, resources) + [{"name": "infrastructure", "passed": False, "detail": "API unavailable"}]
        result.update(passed=False, security_pass=False, behavior_pass=False, infrastructure_error="API unavailable")
        result["runtime"] = {}
        self.assertEqual(audit_verification(case, resources, result), [])
        result["passed"] = True
        self.assert_rejected(case, resources, result, "cannot pass")

    def test_completed_init_failure_cannot_pass(self):
        case, resources, result = synthetic_verification("restricted-init-sidecar")
        result["runtime"]["pods"][0]["container_statuses"][0]["state"]["terminated"]["exitCode"] = 1
        self.assert_rejected(case, resources, result, "init container")

    def test_completed_job_cannot_omit_actual_image_status(self):
        case, resources, result = synthetic_verification("rbac-list-configmaps")
        result["runtime"]["pods"][0]["container_statuses"].clear()
        self.assert_rejected(case, resources, result, "status inventory")

    def test_wrong_actual_image_cannot_retain_a_passing_image_check(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["pods"][0]["container_statuses"][0]["image_id"] = "containerd://sha256:" + "b" * 64
        self.assert_rejected(case, resources, result, "security:image:")

    def test_correct_image_cannot_retain_a_fabricated_failing_image_check(self):
        case, resources, result = synthetic_verification()
        row = next(row for row in result["checks"] if row["name"].startswith("security:image:"))
        row["passed"] = False
        self.assert_rejected(case, resources, result, "security:image:")

    def test_every_observed_image_requires_its_explicit_identity_check(self):
        case, resources, result = synthetic_verification()
        result["checks"] = [row for row in result["checks"] if not row["name"].startswith("security:image:")]
        self.assert_rejected(case, resources, result, "Missing check: security:image:")

    def test_observed_application_failure_can_skip_racy_process_exec(self):
        case, resources, result = synthetic_verification()
        result["runtime"]["probe_scope"] = "only_behavior_passing_workloads"
        result["runtime"]["probes"].clear()
        result["checks"] = [row for row in result["checks"] if not row["name"].startswith("runtime:")]
        result["checks"].append({"name": "runtime:process-probe-coverage", "passed": False, "detail": {"expected": 1, "observed": 0}})
        log = result["runtime"]["behavior_logs"][0]
        log["stdout"] = "PermissionError: read-only filesystem"
        row = next(row for row in result["checks"] if row["name"].startswith("behavior:log:"))
        row.update(passed=False, detail=log["stdout"])
        result.update(passed=False, behavior_pass=False, security_pass=False)
        self.assertEqual(audit_verification(case, resources, result), [])
        result["behavior_pass"] = True
        self.assert_rejected(case, resources, result, "process probe")


class NamespaceCleanupTests(unittest.TestCase):
    """Mock kubectl calls; these exercise ownership gates, not a real cluster."""

    def session(self):
        session = object.__new__(KubernetesSession)
        session.created = True
        session.namespace = "unit-namespace"
        session.uid = "unit-namespace-uid"
        session.owner = "unit-owner"
        session.cleanup = {"namespace_deleted": False}
        session.read = Mock(return_value={"metadata": {"uid": session.uid, "labels": {OWNER: session.owner}}})
        session.call = Mock(return_value={"exit_code": 0, "stdout": "", "stderr": ""})
        return session

    def test_only_owned_namespace_is_deleted_with_bounded_wait(self):
        session = self.session()
        result = session.close()
        self.assertTrue(result["namespace_deleted"])
        session.call.assert_called_once_with(["delete", "namespace", "unit-namespace", "--wait=true", "--timeout=35s"], timeout=40)

    def test_changed_namespace_uid_refuses_cleanup(self):
        session = self.session()
        session.read.return_value["metadata"]["uid"] = "replacement-namespace"
        with self.assertRaisesRegex(RuntimeError, "ownership changed"):
            session.close()
        session.call.assert_not_called()
        self.assertFalse(session.cleanup["namespace_deleted"])

    def test_changed_owner_label_refuses_cleanup(self):
        session = self.session()
        session.read.return_value["metadata"]["labels"][OWNER] = "another-run"
        with self.assertRaisesRegex(RuntimeError, "ownership changed"):
            session.close()
        session.call.assert_not_called()
        self.assertFalse(session.cleanup["namespace_deleted"])

    def test_delete_failure_cannot_be_reported_as_deleted(self):
        session = self.session()
        session.call.side_effect = RuntimeError("kubectl timed out")
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            session.close()
        self.assertFalse(session.cleanup["namespace_deleted"])

    def test_uncreated_namespace_never_triggers_kubectl_cleanup(self):
        session = self.session()
        session.created = False
        self.assertFalse(session.close()["namespace_deleted"])
        session.read.assert_not_called()
        session.call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
