"""Protected Kubernetes execution for the public, adapted robustness cases.

The model receives JSON and returns bounded edits. It never receives credentials,
a shell, reference repairs, or this verifier. Each trial owns a fresh namespace;
candidate updates preserve the resources created at the start of that trial.
"""
from __future__ import annotations

import copy
import json
import subprocess
import time
import uuid

from .methods import canonical, sha256

OWNER = "robustness.kube-repair/run"
PROBE = """import json,os
s={}
for line in open('/proc/1/status'):
 if ':' in line:
  k,v=line.split(':',1); s[k]=v.strip()
print(json.dumps({'uid':int(s['Uid'].split()[1]),'gid':int(s['Gid'].split()[1]),
 'no_new_privileges':int(s.get('NoNewPrivs','0')),
 'capabilities':int(s.get('CapEff','0'),16),'seccomp':int(s.get('Seccomp','0')),
 'root_readonly':bool(os.statvfs('/').f_flag & os.ST_RDONLY)}))
"""


def instantiate(case, namespace, image):
    def replace(value):
        if isinstance(value, str):
            return value.replace("__NAMESPACE__", namespace).replace("__IMAGE__", image)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value
    return replace(copy.deepcopy(case))


def identity(resource):
    return resource["kind"] + "/" + resource["metadata"]["name"]


def pointer(value, path):
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def contains_desired(expected, observed):
    """Compare authored fields while allowing Kubernetes API defaults."""
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(
            (key == "readOnly" and value is False and key not in observed)
            or key in observed and contains_desired(value, observed[key])
            for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(observed, list) and len(expected) == len(observed) and all(contains_desired(a, b) for a, b in zip(expected, observed))
    return type(expected) is type(observed) and expected == observed


def deployment_ready(resource):
    status = resource.get("status", {})
    return (status.get("observedGeneration", 0) >= resource["metadata"]["generation"]
            and all(status.get(key, 0) == 1 for key in ("replicas", "readyReplicas", "updatedReplicas", "availableReplicas")))


def pod_spec(resource):
    if resource["kind"] in {"Deployment", "Job"}:
        return resource["spec"]["template"]["spec"]
    return None


def evaluate_static_resources(case, resources):
    checks = []
    objects = {identity(item): item for item in resources}
    for item in case["contract"]["security_checks"]:
        try:
            observed = pointer(objects[item["resource"]], item["path"])
        except (KeyError, IndexError, TypeError, ValueError):
            observed = None
        expected = item["value"]
        if isinstance(expected, list) and all(isinstance(x, str) for x in expected):
            passed = (isinstance(observed, list) and all(isinstance(item, str) for item in observed)
                      and len(observed) == len(expected) and set(observed) == set(expected))
        else:
            passed = observed == expected and type(observed) is type(expected)
        checks.append(check("static:" + item["resource"] + item["path"], passed,
                            {"expected": expected, "observed": observed}))
    for resource in resources:
        pod = pod_spec(resource)
        if pod is None:
            continue
        for container in pod.get("containers", []) + pod.get("initContainers", []):
            context = dict(pod.get("securityContext", {}))
            context.update(container.get("securityContext", {}))
            prefix = "static:" + identity(resource) + "/" + container["name"] + ":"
            uid = context.get("runAsUser")
            goals = {"non-root": context.get("runAsNonRoot") is True and type(uid) is int and uid > 0,
                     "no-escalation": context.get("allowPrivilegeEscalation") is False,
                     "unprivileged": context.get("privileged") is not True,
                     "drop-capabilities": context.get("capabilities", {}).get("drop") == ["ALL"] and not context.get("capabilities", {}).get("add"),
                     "seccomp": context.get("seccompProfile", {}).get("type") == "RuntimeDefault",
                     "read-only-root": context.get("readOnlyRootFilesystem") is True}
            checks.extend(check(prefix + key, passed, "Protected container security requirement") for key, passed in goals.items())
    return checks


def runtime_probe_checks(resource_key, container, raw):
    values = json.loads(raw)
    required = {"uid", "gid", "no_new_privileges", "capabilities", "seccomp", "root_readonly"}
    if set(values) != required or any(type(values[k]) is not int for k in required - {"root_readonly"}) or type(values["root_readonly"]) is not bool:
        raise ValueError("Malformed protected runtime probe")
    prefix = "runtime:" + resource_key + "/" + container + ":"
    goals = {"non-root": values["uid"] > 0, "no-escalation": values["no_new_privileges"] == 1,
             "capabilities": values["capabilities"] == 0, "seccomp": values["seccomp"] == 2,
             "read-only-root": values["root_readonly"]}
    return [check(prefix + key, passed, values) for key, passed in goals.items()]


class KubernetesSession:
    def __init__(self, case, *, kubectl, context, kubeconfig, image, commands, expected_image_id=None):
        self.namespace = "robust-v2-" + uuid.uuid4().hex[:16]
        self.owner = uuid.uuid4().hex
        self.case = instantiate(case, self.namespace, image)
        self.commands = commands
        self.argv = [str(kubectl), "--context", context, "--kubeconfig", str(kubeconfig), "--request-timeout=8s"]
        self.context = context
        self.expected_image_id = expected_image_id
        self.uid = None
        self.resource_uids = {}
        self.current = []
        self.created = False
        self.cleanup = {"namespace_deleted": False}

    def call(self, args, value=None, timeout=12, allow_failure=False):
        started = time.monotonic_ns()
        payload = canonical(value).encode() if value is not None else None
        row = {"argv": self.argv + args, "stdin_sha256": sha256(value) if value is not None else None}
        self.commands.append(row)
        try:
            result = subprocess.run(row["argv"], input=payload, capture_output=True, timeout=timeout)
            if len(result.stdout) + len(result.stderr) > 1_000_000:
                raise RuntimeError("Kubernetes response exceeds evidence limit")
            row.update(exit_code=result.returncode, stdout=result.stdout.decode("utf-8", "replace"),
                       stderr=result.stderr.decode("utf-8", "replace"))
            if result.returncode and not allow_failure:
                raise RuntimeError("kubectl failed: " + row["stderr"][-2500:])
            return row
        finally:
            row["elapsed_ns"] = time.monotonic_ns() - started

    def read(self, args):
        return json.loads(self.call(args + ["-o", "json"])["stdout"])

    def start(self):
        namespace = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": self.namespace,
                     "labels": {OWNER: self.owner, "pod-security.kubernetes.io/enforce": self.case["contract"]["namespace_security"],
                                "pod-security.kubernetes.io/enforce-version": "v1.34"}}}
        self.created = True
        observed = json.loads(self.call(["create", "-f", "-", "-o", "json"], namespace)["stdout"])
        self.uid = observed["metadata"]["uid"]
        for resource in self.case["resources"]:
            observed = json.loads(self.call(["-n", self.namespace, "apply", "-f", "-", "-o", "json"], resource)["stdout"])
            self.resource_uids[identity(resource)] = observed["metadata"]["uid"]
        self.current = copy.deepcopy(self.case["resources"])
        return self

    def verify(self, resources, *, max_wait=None):
        started = time.monotonic_ns()
        self._verify_command_start = len(self.commands)
        checks = []
        runtime = {"namespace": self.namespace, "namespace_uid": self.uid, "context": self.context,
                   "resource_uids": dict(self.resource_uids), "pods": [], "probes": [], "behavior_logs": [], "authorizations": [],
                   "expected_image_id": self.expected_image_id, "namespace_owner": self.owner, "workloads": {}}
        infrastructure = None
        objects = {identity(value): value for value in resources}
        target_keys = set(self.case["allowed_paths"])
        try:
            checks = evaluate_static_resources(self.case, resources)
            runtime["server_version"] = self.read(["version"]).get("serverVersion")
            if set(objects) != set(self.resource_uids):
                raise ValueError("Candidate changed resource inventory")
            for current_index, old in enumerate(self.current):
                key = identity(old)
                candidate = objects[key]
                if key not in target_keys and candidate != old:
                    raise ValueError("Immutable support resource changed")
                if candidate != old:
                    row = self.call(["-n", self.namespace, "apply", "-f", "-", "-o", "json"], candidate, allow_failure=True)
                    if row["exit_code"]:
                        runtime["apply_rejection"] = {key_name: row.get(key_name) for key_name in ("stdin_sha256", "stdout", "stderr", "exit_code")}
                        runtime["apply_rejection"]["resource"] = key
                        checks.append(check("candidate-admitted", False, row["stderr"][-2500:]))
                        return self._result(checks, runtime, resources, started, None)
                    observed = json.loads(row["stdout"])
                    if observed["metadata"]["uid"] != self.resource_uids[key]:
                        raise RuntimeError("Candidate update replaced an existing resource")
                    # Preserve successfully applied prefixes even if a later object
                    # is rejected, so subsequent proposals can correctly roll back.
                    self.current[current_index] = copy.deepcopy(candidate)
            self.current = copy.deepcopy(resources)
            deadline = time.monotonic() + (max_wait if max_wait is not None else self.case["contract"]["timeout_seconds"])
            last_pods = []
            replicas = {}
            def current_replica(name):
                if name not in replicas:
                    replicas[name] = self.read(["-n", self.namespace, "get", "replicaset", name])
                replica = replicas[name]
                owners = replica["metadata"].get("ownerReferences", [])
                owner = next((o for o in owners if o.get("kind") == "Deployment" and o.get("controller")), {})
                desired = objects.get("Deployment/" + owner.get("name", ""))
                return bool(desired and owner.get("uid") == self.resource_uids.get(identity(desired))
                            and contains_desired(desired["spec"]["template"]["spec"], replica["spec"]["template"]["spec"]))

            def current_pod(pod):
                if pod["metadata"].get("deletionTimestamp"):
                    return False
                owner = next((o for o in pod["metadata"].get("ownerReferences", []) if o.get("controller")), {})
                if owner.get("kind") == "ReplicaSet":
                    return current_replica(owner["name"])
                return owner.get("kind") == "Job" and owner.get("uid") == self.resource_uids.get("Job/" + owner.get("name", ""))

            while True:
                workload_ready = True
                fatal_workload = False
                for name in self.case["contract"]["ready_deployments"]:
                    observed = self.read(["-n", self.namespace, "get", "deployment", name])
                    status = observed.get("status", {})
                    good = deployment_ready(observed)
                    workload_ready &= good
                for name in self.case["contract"]["completed_jobs"]:
                    observed = self.read(["-n", self.namespace, "get", "job", name])
                    workload_ready &= observed.get("status", {}).get("succeeded", 0) == 1
                    fatal_workload |= bool(observed.get("status", {}).get("failed", 0))
                last_pods = [pod for pod in self.read(["-n", self.namespace, "get", "pods"])["items"] if current_pod(pod)]
                for pod in last_pods:
                    for status in pod.get("status", {}).get("containerStatuses", []) + pod.get("status", {}).get("initContainerStatuses", []):
                        waiting = status.get("state", {}).get("waiting", {})
                        if waiting.get("reason") in {"ErrImageNeverPull", "ImagePullBackOff", "ErrImagePull"}:
                            raise RuntimeError("Pinned fixture image could not start: " + str(waiting))
                        terminated = status.get("state", {}).get("terminated", {})
                        fatal_workload |= bool(terminated and terminated.get("exitCode") != 0)
                        fatal_workload |= waiting.get("reason") in {"CrashLoopBackOff", "CreateContainerConfigError"}
                if workload_ready or fatal_workload or time.monotonic() >= deadline:
                    break
                # Explicit admission denials are task feedback rather than an infrastructure outage.
                if not last_pods:
                    events = self.read(["-n", self.namespace, "get", "events"])["items"]
                    denied = [event.get("message", "") for event in events if event.get("reason") == "FailedCreate"
                              and event.get("involvedObject", {}).get("kind") == "ReplicaSet"
                              and current_replica(event["involvedObject"]["name"])]
                    if denied:
                        runtime["admission_errors"] = denied
                        break
                time.sleep(0.35)
            for name in self.case["contract"]["ready_deployments"]:
                observed = self.read(["-n", self.namespace, "get", "deployment", name])
                status = observed.get("status", {})
                runtime["workloads"]["Deployment/" + name] = {"uid": observed["metadata"]["uid"], "generation": observed["metadata"]["generation"], "status": status}
                good = deployment_ready(observed)
                checks.append(check("behavior:ready:Deployment/" + name, good, status))
            for name in self.case["contract"]["completed_jobs"]:
                observed = self.read(["-n", self.namespace, "get", "job", name])
                runtime["workloads"]["Job/" + name] = {"uid": observed["metadata"]["uid"], "generation": observed["metadata"].get("generation", 1), "status": observed.get("status", {})}
                checks.append(check("behavior:complete:Job/" + name, observed.get("status", {}).get("succeeded", 0) == 1, observed.get("status", {})))
            # Read actual workload logs through its controller, not a caller-supplied pod name.
            for assertion in self.case["contract"]["behavior_checks"]:
                selected_name = None
                for pod in last_pods:
                    owner = next((o for o in pod["metadata"].get("ownerReferences", []) if o.get("controller")), {})
                    key = "Job/" + owner.get("name", "")
                    if owner.get("kind") == "ReplicaSet":
                        replica = replicas[owner["name"]]
                        deployment_owner = next((o for o in replica["metadata"].get("ownerReferences", []) if o.get("controller")), {})
                        key = "Deployment/" + deployment_owner.get("name", "")
                    if key == assertion["resource"]:
                        selected_name = pod["metadata"]["name"]
                        break
                log_target = selected_name or assertion["resource"]
                row = self.call(["-n", self.namespace, "logs", log_target, "-c", assertion["container"], "--tail=40", "--pod-running-timeout=1s"], timeout=5, allow_failure=True)
                runtime["behavior_logs"].append({**assertion, "pod": selected_name, "stdout": row.get("stdout", ""), "stderr": row.get("stderr", ""), "exit_code": row["exit_code"]})
                checks.append(check("behavior:log:" + assertion["resource"] + "/" + assertion["container"], row["exit_code"] == 0 and assertion["contains"] in row["stdout"], row.get("stdout", "")[-2000:]))
            for assertion in self.case["contract"]["rbac_checks"]:
                target = assertion["resource"] + ("/" + assertion["resource_name"] if assertion.get("resource_name") else "")
                row = self.call(["-n", self.namespace, "auth", "can-i", assertion["verb"], target,
                                 "--as=system:serviceaccount:" + self.namespace + ":" + assertion["service_account"]], allow_failure=True)
                actual = row["stdout"].strip()
                runtime["authorizations"].append({**assertion, "observed": actual, "exit_code": row["exit_code"]})
                checks.append(check("security:rbac:" + assertion["verb"] + ":" + target, actual == ("yes" if assertion["allowed"] else "no") and row["exit_code"] in {0, 1}, actual))
            # Preserve all original object identities and the namespace policy.
            for key, expected_uid in self.resource_uids.items():
                observed = self.read(["-n", self.namespace, "get", key])
                checks.append(check("identity:" + key, observed["metadata"]["uid"] == expected_uid, observed["metadata"]["uid"]))
            namespace = self.read(["get", "namespace", self.namespace])
            runtime["namespace_labels"] = namespace["metadata"]["labels"]
            checks.append(check("identity:namespace", namespace["metadata"]["uid"] == self.uid and namespace["metadata"]["labels"].get(OWNER) == self.owner,
                                namespace["metadata"]["uid"]))
            checks.append(check("security:namespace-policy", namespace["metadata"]["labels"].get("pod-security.kubernetes.io/enforce") == self.case["contract"]["namespace_security"], namespace["metadata"]["labels"]))
            behavior_ready = all(item["passed"] for item in checks if item["name"].startswith("behavior:"))
            runtime["probe_scope"] = "only_behavior_passing_workloads"
            for pod in last_pods:
                statuses = pod.get("status", {}).get("containerStatuses", []) + pod.get("status", {}).get("initContainerStatuses", [])
                pod_record = {"name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
                    "init_container_names": [c["name"] for c in pod["spec"].get("initContainers", [])],
                    "owner_references": pod["metadata"].get("ownerReferences", []), "container_statuses": [
                        {"name": s["name"], "image_id": s.get("imageID"), "ready": s.get("ready"), "state": s.get("state")} for s in statuses]}
                runtime["pods"].append(pod_record)
                owner = pod["metadata"].get("ownerReferences", [{}])[0]
                resource_key = "Job/" + owner.get("name", "") if owner.get("kind") == "Job" else None
                if owner.get("kind") == "ReplicaSet":
                    replica = self.read(["-n", self.namespace, "get", "replicaset", owner["name"]])
                    deployment_owner = replica["metadata"].get("ownerReferences", [{}])[0]
                    resource_key = "Deployment/" + deployment_owner.get("name", "")
                    checks.append(check("identity:pod-owner:" + pod["metadata"]["name"],
                        replica["metadata"]["uid"] == owner["uid"] and deployment_owner.get("uid") == self.resource_uids.get(resource_key), owner))
                elif resource_key:
                    checks.append(check("identity:pod-owner:" + pod["metadata"]["name"], owner.get("uid") == self.resource_uids.get(resource_key), owner))
                pod_record["resource"] = resource_key
                pod_record["controller_uid"] = self.resource_uids.get(resource_key)
                for status in statuses:
                    if status.get("imageID") and self.expected_image_id:
                        observed = status["imageID"].rsplit("sha256:", 1)[-1]
                        expected = self.expected_image_id.rsplit("sha256:", 1)[-1]
                        checks.append(check("security:image:" + pod["metadata"]["name"] + "/" + status["name"], observed == expected, status["imageID"]))
                for status in pod.get("status", {}).get("containerStatuses", []):
                    if not behavior_ready or not status.get("state", {}).get("running"):
                        continue
                    row = self.call(["-n", self.namespace, "exec", pod["metadata"]["name"], "-c", status["name"], "--", "python", "-c", PROBE], timeout=10)
                    runtime["probes"].append({"resource": resource_key, "container": status["name"], "raw": row["stdout"], "probe_sha256": sha256(PROBE)})
                    checks.extend(runtime_probe_checks(resource_key or "unknown", status["name"], row["stdout"]))
            expected_probe_keys = {(key, c["name"]) for key, resource in objects.items()
                                   if key in {"Deployment/" + name for name in self.case["contract"]["ready_deployments"]}
                                   for c in resource["spec"]["template"]["spec"]["containers"]}
            actual_probe_keys = {(p["resource"], p["container"]) for p in runtime["probes"]}
            checks.append(check("runtime:process-probe-coverage", actual_probe_keys == expected_probe_keys and len(runtime["probes"]) == len(expected_probe_keys),
                                {"expected": len(expected_probe_keys), "observed": len(runtime["probes"])}))
        except Exception as error:
            infrastructure = type(error).__name__ + ": " + str(error)
            checks.append(check("infrastructure", False, infrastructure))
        return self._result(checks, runtime, resources, started, infrastructure)

    def _result(self, checks, runtime, resources, started, infrastructure):
        behavior = [item for item in checks if item["name"].startswith("behavior:")]
        security = [item for item in checks if not item["name"].startswith("behavior:")]
        return {"passed": bool(checks) and all(item["passed"] for item in checks) and infrastructure is None,
                "security_pass": bool(security) and all(item["passed"] for item in security),
                "behavior_pass": bool(behavior) and all(item["passed"] for item in behavior),
                "infrastructure_error": infrastructure, "checks": checks, "runtime": runtime,
                "resources_sha256": sha256(resources), "elapsed_ns": time.monotonic_ns() - started,
                "command_range": {"start": self._verify_command_start, "end": len(self.commands)}}

    def close(self):
        if self.created:
            observed = self.read(["get", "namespace", self.namespace])
            metadata = observed["metadata"]
            if metadata.get("labels", {}).get(OWNER) != self.owner or self.uid and metadata["uid"] != self.uid:
                raise RuntimeError("Namespace ownership changed; cleanup refused")
            self.call(["delete", "namespace", self.namespace, "--wait=true", "--timeout=35s"], timeout=40)
            self.cleanup["namespace_deleted"] = True
        return self.cleanup
