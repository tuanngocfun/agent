"""Replay verifier claims against their retained raw observations.

This verifies evidence consistency, not a cryptographic attestation that a
cluster existed.  GitHub job logs and the immutable execution bundle supply
the separate execution provenance.  Unit fixtures never constitute runtime
benchmark results.
"""
from __future__ import annotations

import json
import re

from .methods import sha256
from .runtime import OWNER, PROBE, evaluate_static_resources, identity, runtime_probe_checks

_DIGEST = re.compile(r"(?:^|@|://)(sha256:[0-9a-f]{64})$")
_RAW_PROBE_KEYS = {"uid", "gid", "no_new_privileges", "capabilities", "seccomp", "root_readonly"}


def _strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate raw JSON key")
            result[key] = item
        return result
    return json.loads(value, object_pairs_hook=pairs,
                      parse_constant=lambda item: (_ for _ in ()).throw(ValueError("Non-finite raw JSON value")))


def _image_digest(value):
    match = _DIGEST.search(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _workload(runtime, key):
    value = runtime.get("workloads", {}).get(key, {})
    return value if isinstance(value, dict) else {}


def audit_verification(case, resources, result):
    """Return defects; an empty list means the retained evidence is consistent.

    Failed tasks can have valid evidence.  Missing observations or a fabricated
    passed flag are audit defects rather than ordinary application failures.
    """
    errors = []
    try:
        _audit(case, resources, result, errors)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        errors.append("Malformed verification evidence: " + type(exc).__name__ + ": " + str(exc)[:250])
    return errors


def _audit(case, resources, result, errors):
    if not isinstance(result, dict):
        raise ValueError("Result must be an object")
    if result.get("resources_sha256") != sha256(resources):
        errors.append("Candidate resources hash mismatch")
    if type(result.get("elapsed_ns")) is not int or result["elapsed_ns"] < 0:
        errors.append("Invalid monotonic verification duration")
    for key in ("passed", "security_pass", "behavior_pass"):
        if type(result.get(key)) is not bool:
            errors.append("Non-boolean result flag: " + key)
    checks = result.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("A nonempty check inventory is required")
    observed = {}
    for item in checks:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or type(item.get("passed")) is not bool:
            raise ValueError("Malformed check entry")
        if item["name"] in observed:
            errors.append("Duplicate check: " + item["name"])
        observed[item["name"]] = item
    expected_names = set()

    def replay(name, passed, *, detail=None, compare_detail=False):
        expected_names.add(name)
        row = observed.get(name)
        if row is None:
            errors.append("Missing check: " + name)
            return
        if row["passed"] is not bool(passed):
            errors.append("Passed flag differs from raw evidence: " + name)
        if compare_detail and row.get("detail") != detail:
            errors.append("Check detail differs from raw evidence: " + name)

    for check in evaluate_static_resources(case, resources):
        replay(check["name"], check["passed"], detail=check.get("detail"), compare_detail=True)
    runtime = result.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError("Runtime observations are required")
    rejection = runtime.get("apply_rejection")
    if result.get("infrastructure_error") or rejection:
        # A rejected apply is an observed task failure, not successful runtime
        # evidence.  It may exit before logs/pods exist.  The command-range audit
        # in the execution bundle must separately bind the actual rejection.
        if result.get("infrastructure_error") and not isinstance(result["infrastructure_error"], str):
            errors.append("Infrastructure/rejection detail must be text")
        if rejection:
            admission = observed.get("candidate-admitted")
            if admission is None or admission["passed"] is not False:
                errors.append("Rejected candidate has no failed admission check")
            interval = result.get("command_range", {})
            if (type(interval.get("start")) is not int or type(interval.get("end")) is not int
                    or interval.get("start", -1) < 0 or interval.get("end", 0) <= interval.get("start", 0)):
                errors.append("Rejected candidate has no retained command interval")
        behavior = [item for item in checks if item["name"].startswith("behavior:")]
        security = [item for item in checks if not item["name"].startswith("behavior:")]
        if result.get("passed") is not False:
            errors.append("A partial infrastructure result cannot pass")
        if result.get("behavior_pass") is not (bool(behavior) and all(item["passed"] for item in behavior)):
            errors.append("Partial behavior aggregate differs from observed checks")
        if result.get("security_pass") is not (bool(security) and all(item["passed"] for item in security)):
            errors.append("Partial security aggregate differs from observed checks")
        return
    namespace = runtime.get("namespace")
    namespace_uid = runtime.get("namespace_uid")
    if not isinstance(namespace, str) or not namespace or "__NAMESPACE__" in namespace:
        errors.append("Missing instantiated namespace identity")
    if not isinstance(namespace_uid, str) or not namespace_uid:
        errors.append("Missing namespace UID")
    labels = runtime.get("namespace_labels")
    if labels is None:
        labels = observed.get("security:namespace-policy", {}).get("detail")
    if not isinstance(labels, dict):
        errors.append("Missing raw namespace labels")
        labels = {}
    owner = runtime.get("namespace_owner")
    owned = isinstance(owner, str) and bool(owner) and labels.get(OWNER) == owner
    replay("identity:namespace", bool(namespace_uid) and owned, detail=namespace_uid, compare_detail=True)
    policy = case["contract"]["namespace_security"]
    policy_ok = (labels.get("pod-security.kubernetes.io/enforce") == policy
                 and labels.get("pod-security.kubernetes.io/enforce-version") == "v1.34")
    replay("security:namespace-policy", policy_ok, detail=labels, compare_detail=True)

    inventory = {identity(resource): resource for resource in resources}
    if len(inventory) != len(resources):
        errors.append("Duplicate candidate resource identity")
    if any(resource.get("metadata", {}).get("namespace") != namespace for resource in resources):
        errors.append("Candidate resource is outside the owned namespace")
    if "__NAMESPACE__" in json.dumps(resources, allow_nan=False) or "__IMAGE__" in json.dumps(resources, allow_nan=False):
        errors.append("Candidate retains an uninstantiated source placeholder")
    uids = runtime.get("resource_uids", {})
    if not isinstance(uids, dict) or set(uids) != set(inventory):
        errors.append("Resource UID inventory differs from the candidate inventory")
        uids = uids if isinstance(uids, dict) else {}
    nonempty_uids = [value for value in uids.values() if isinstance(value, str) and value]
    if len(nonempty_uids) != len(uids) or len(set(nonempty_uids)) != len(nonempty_uids):
        errors.append("Missing or duplicate observed resource UID")
    for key in inventory:
        replay("identity:" + key, isinstance(uids.get(key), str) and bool(uids[key]), detail=uids.get(key), compare_detail=True)

    contract = case["contract"]
    for name in contract["ready_deployments"]:
        key = "Deployment/" + name
        workload = _workload(runtime, key)
        status = workload.get("status", {})
        generation = workload.get("generation")
        if type(generation) is not int or generation <= 0:
            errors.append("Missing raw workload generation: " + key)
        ready = (type(generation) is int and type(status.get("observedGeneration")) is int
                 and status["observedGeneration"] >= generation
                 and type(status.get("updatedReplicas")) is int and status["updatedReplicas"] == 1
                 and type(status.get("availableReplicas")) is int and status["availableReplicas"] == 1
                 and type(status.get("readyReplicas")) is int and status["readyReplicas"] == 1
                 and type(status.get("replicas")) is int and status["replicas"] == 1)
        replay("behavior:ready:" + key, ready, detail=status, compare_detail=True)
        if workload.get("uid") != uids.get(key):
            errors.append("Workload UID differs from resource binding: " + key)
    for name in contract["completed_jobs"]:
        key = "Job/" + name
        workload = _workload(runtime, key)
        status = workload.get("status", {})
        replay("behavior:complete:" + key, type(status.get("succeeded")) is int and status["succeeded"] == 1, detail=status, compare_detail=True)
        if workload.get("uid") != uids.get(key):
            errors.append("Workload UID differs from resource binding: " + key)

    log_rows = runtime.get("behavior_logs", [])
    log_map = {}
    for row in log_rows:
        key = (row.get("resource"), row.get("container"))
        if key in log_map:
            errors.append("Duplicate behavior log: " + str(key))
        log_map[key] = row
    expected_logs = {(item["resource"], item["container"]) for item in contract["behavior_checks"]}
    if set(log_map) != expected_logs:
        errors.append("Behavior log inventory differs from the protected contract")
    for protected in contract["behavior_checks"]:
        key = (protected["resource"], protected["container"])
        row = log_map.get(key, {})
        stdout = row.get("stdout", "")
        if not isinstance(stdout, str) or not isinstance(row.get("stderr", ""), str):
            raise ValueError("Behavior log text must be strings")
        if row.get("contains") != protected["contains"]:
            errors.append("Behavior expectation differs from protected contract: " + str(key))
        good = type(row.get("exit_code")) is int and row["exit_code"] == 0 and protected["contains"] in stdout
        replay("behavior:log:" + key[0] + "/" + key[1], good, detail=stdout[-2000:], compare_detail=True)

    auth_rows = runtime.get("authorizations", [])
    auth_map = {}
    def auth_key(item):
        return (item.get("service_account"), item.get("verb"), item.get("resource"), item.get("resource_name"))
    for row in auth_rows:
        key = auth_key(row)
        if key in auth_map:
            errors.append("Duplicate authorization observation: " + str(key))
        auth_map[key] = row
    expected_auth = {auth_key(item) for item in contract["rbac_checks"]}
    if set(auth_map) != expected_auth:
        errors.append("Authorization inventory differs from protected contract")
    for protected in contract["rbac_checks"]:
        row = auth_map.get(auth_key(protected), {})
        raw = row.get("observed")
        wanted = "yes" if protected["allowed"] else "no"
        if row.get("allowed") is not protected["allowed"]:
            errors.append("Authorization expectation differs from protected contract")
        good = (raw == wanted and type(row.get("exit_code")) is int and row["exit_code"] in {0, 1})
        suffix = protected["resource"] + ("/" + protected["resource_name"] if protected.get("resource_name") else "")
        replay("security:rbac:" + protected["verb"] + ":" + suffix, good, detail=raw, compare_detail=True)

    pod_rows = runtime.get("pods", [])
    running = set()
    workloads_with_pods = set()
    pod_names, pod_uids = set(), set()
    expected_digest = _image_digest(runtime.get("expected_image_id"))
    if expected_digest is None:
        errors.append("Missing pinned runtime image digest")
    version = runtime.get("server_version", {})
    if result.get("passed") and (not isinstance(version, dict)
                                 or not str(version.get("gitVersion", "")).startswith("v1.34.")):
        errors.append("Missing pinned Kubernetes server version")
    for pod in pod_rows:
        pod_name, pod_uid, resource_key = pod.get("name"), pod.get("uid"), pod.get("resource")
        if not pod_name or not pod_uid or pod_name in pod_names or pod_uid in pod_uids:
            errors.append("Missing or duplicate pod identity")
        pod_names.add(pod_name); pod_uids.add(pod_uid)
        if resource_key not in inventory or inventory.get(resource_key, {}).get("kind") not in {"Deployment", "Job"}:
            errors.append("Pod has no protected workload binding")
            continue
        workloads_with_pods.add(resource_key)
        owners = [item for item in pod.get("owner_references", []) if item.get("controller") is True]
        owner_ref = owners[0] if len(owners) == 1 else {}
        good_owner = bool(owner_ref.get("uid"))
        if resource_key.startswith("Job/"):
            good_owner &= owner_ref.get("kind") == "Job" and owner_ref.get("uid") == uids.get(resource_key)
        else:
            good_owner &= (owner_ref.get("kind") == "ReplicaSet"
                           and pod.get("controller_uid") == uids.get(resource_key))
        replay("identity:pod-owner:" + str(pod_name), good_owner, detail=owner_ref, compare_detail=True)
        pod_spec = inventory[resource_key]["spec"]["template"]["spec"]
        init_names = {item["name"] for item in pod_spec.get("initContainers", [])}
        container_names = {item["name"] for item in pod_spec["containers"]} | init_names
        statuses = pod.get("container_statuses", [])
        if len({item.get("name") for item in statuses}) != len(statuses):
            errors.append("Duplicate container status observation")
        if result.get("passed") and {item.get("name") for item in statuses} != container_names:
            errors.append("Successful pod has incomplete container/image status inventory")
        for status in statuses:
            name = status.get("name")
            if name not in container_names:
                errors.append("Container status has no protected container binding")
            state = status.get("state", {})
            actual_image = status.get("image_id")
            if actual_image and runtime.get("expected_image_id"):
                replay("security:image:" + str(pod_name) + "/" + str(name),
                       expected_digest is not None and _image_digest(actual_image) == expected_digest,
                       detail=actual_image, compare_detail=True)
            if state.get("running") is not None and name not in init_names:
                running.add((resource_key, name))
            if name in init_names and result.get("passed"):
                if state.get("terminated", {}).get("exitCode") != 0:
                    errors.append("Successful workload has an uncompleted or failed init container")
            if state.get("running") is not None or state.get("terminated") is not None:
                if expected_digest is None or _image_digest(status.get("image_id")) != expected_digest:
                    errors.append("Observed pod image differs from the runtime pin")

    probes = runtime.get("probes", [])
    probe_keys = set()
    for row in probes:
        key = (row.get("resource"), row.get("container"))
        if key in probe_keys:
            errors.append("Duplicate process probe: " + str(key))
        probe_keys.add(key)
        if key not in running:
            errors.append("Process probe is not bound to a running protected container")
        if row.get("probe_sha256") != sha256(PROBE):
            errors.append("Trusted process probe hash mismatch")
        raw = row.get("raw")
        if not isinstance(raw, str):
            raise ValueError("Raw process probe must be retained as JSON text")
        values = _strict_json(raw)
        if not isinstance(values, dict) or set(values) != _RAW_PROBE_KEYS:
            raise ValueError("Malformed raw process probe key inventory")
        recomputed = runtime_probe_checks(key[0], key[1], raw)
        for check in recomputed:
            replay(check["name"], check["passed"], detail=check.get("detail"), compare_detail=True)
        if key[0] in inventory:
            pod_spec = inventory[key[0]]["spec"]["template"]["spec"]
            container = next((item for item in pod_spec["containers"] if item["name"] == key[1]), None)
            if container is None:
                errors.append("Process probe container is absent from the candidate")
            else:
                sc = container["securityContext"]
                if values.get("uid") != sc.get("runAsUser") or values.get("gid") != sc.get("runAsGroup"):
                    errors.append("Observed process identity differs from candidate UID/GID")
    if probe_keys != running:
        if result.get("passed") or result.get("behavior_pass"):
            errors.append("Every running application container must have exactly one process probe")
        elif runtime.get("probe_scope") != "only_behavior_passing_workloads":
            errors.append("Missing process probes have no declared failed-behavior scope")
    expected_probe_keys = set()
    for name in contract["ready_deployments"]:
        key = "Deployment/" + name
        expected_probe_keys.update((key, container["name"])
                                   for container in inventory[key]["spec"]["template"]["spec"]["containers"])
    coverage = probe_keys == expected_probe_keys and len(probes) == len(expected_probe_keys)
    replay("runtime:process-probe-coverage", coverage)
    if result.get("passed") and not pod_rows:
        errors.append("Successful runtime evidence has no observed pod")
    expected_workloads = {"Deployment/" + name for name in contract["ready_deployments"]} | {"Job/" + name for name in contract["completed_jobs"]}
    if result.get("passed") and workloads_with_pods != expected_workloads:
        errors.append("Successful runtime evidence lacks a pod for each protected workload")

    extra = set(observed) - expected_names
    if extra:
        errors.append("Unexpected check inventory: " + ", ".join(sorted(extra)))
    behavior_checks = [item for item in checks if item["name"].startswith("behavior:")]
    security_checks = [item for item in checks if not item["name"].startswith("behavior:")]
    behavior_pass = bool(behavior_checks) and all(item["passed"] for item in behavior_checks)
    security_pass = bool(security_checks) and all(item["passed"] for item in security_checks)
    if result.get("behavior_pass") is not behavior_pass:
        errors.append("Behavior aggregate differs from check results")
    if result.get("security_pass") is not security_pass:
        errors.append("Security aggregate differs from check results")
    combined = behavior_pass and security_pass and not result.get("infrastructure_error")
    if result.get("passed") is not combined:
        errors.append("Overall aggregate differs from check results")
