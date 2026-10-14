"""Run the trusted fixture in fresh namespaces on an explicitly selected lab.

Only fixed kubectl commands and the versioned probe are available. Cluster
credentials and image setup are supplied by the operator, never by the model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid

from .verification import _RUNTIME_CHECKS, _check, _container, _env, _probe_for_contract, _static

OWNER_LABEL = "kube-repair.lab/run"
_DIGEST = re.compile(r"(?:^|@|://)(sha256:[0-9a-f]{64})$")
_ROOT_POLICY_REJECTION = re.compile(
    r"container's runAsUser breaks non-root policy \(pod: \"[^\"\r\n]+\", container: app\)"
)


def image_digest(value):
    match = _DIGEST.search(value or "")
    if not match:
        raise ValueError("A trusted sha256 runtime image ID is required")
    return match.group(1)


def command(argv, *, input_value=None, timeout=8):
    """Fixed trusted CLI, bounded deadline; output is rejected beyond 64 KiB."""
    payload = json.dumps(input_value, allow_nan=False).encode() if input_value is not None else None
    if payload is not None and len(payload) > 65536:
        raise RuntimeError("Manifest exceeds the runner input limit")
    result = subprocess.run(argv, input=payload, capture_output=True, timeout=timeout)
    if len(result.stdout) + len(result.stderr) > 65536:
        raise RuntimeError("kubectl output exceeds the runner limit")
    return result.returncode, result.stdout.decode("utf-8", "replace"), result.stderr.decode("utf-8", "replace")


def prefix(configuration):
    context = configuration.get("context")
    if not isinstance(context, str) or not context or context.startswith("-") or len(context) > 200:
        raise ValueError("Explicit lab Kubernetes context is required")
    binary = configuration.get("kubectl") or shutil.which("kubectl")
    if not binary:
        raise RuntimeError("kubectl is unavailable; no simulation fallback is used")
    argv = [binary, "--context", context, "--request-timeout=8s"]
    kubeconfig = configuration.get("kubeconfig")
    if kubeconfig:
        argv += ["--kubeconfig", kubeconfig]
    return argv


def _guard(manifest, contract):
    _probe_for_contract(contract)
    pod, app = _container(manifest)
    if manifest.get("apiVersion") != "apps/v1" or manifest.get("kind") != "Deployment":
        raise ValueError("Only the fixture Deployment can be evaluated")
    if manifest.get("metadata", {}).get("name") != "repair-cache-app" or manifest["spec"].get("replicas") != 1:
        raise ValueError("Fixture identity and one replica must be preserved")
    if contract.get("volume_gid") is not None:
        raise ValueError("Kubernetes volume-permissions fixture is not implemented yet")
    if pod.get("automountServiceAccountToken") is not False:
        raise ValueError("The fixture must not mount API credentials")
    if any(pod.get(key) for key in ("hostNetwork", "hostPID", "hostIPC", "initContainers", "ephemeralContainers")):
        raise ValueError("Host namespaces and extra containers are outside the lab")
    if app.get("command") or app.get("args") or app.get("lifecycle") or app.get("securityContext", {}).get("privileged"):
        raise ValueError("Only the trusted unprivileged fixture entrypoint can run")
    if app.get("imagePullPolicy") != "Never" or not isinstance(app.get("image"), str):
        raise ValueError("A preloaded trusted fixture image with imagePullPolicy Never is required")
    if any("emptyDir" not in volume for volume in pod.get("volumes", [])):
        raise ValueError("Only task-owned emptyDir storage is allowed")
    environment = _env(app)
    if set(environment) != {"CACHE_DIR", "FIXTURE_REQUIRES_ROOT"} or environment["CACHE_DIR"] != contract["cache_path"]:
        raise ValueError("The trusted fixture environment must be preserved")
    if environment["FIXTURE_REQUIRES_ROOT"] != ("1" if contract.get("requires_root") else "0"):
        raise ValueError("Fixture root requirement differs from the protected contract")


def _root_policy_rejection(manifest, waiting):
    """Recognize kubelet's explicit UID-zero rejection, never generic config errors."""
    _, app = _container(manifest)
    security = app.get("securityContext", {})
    uid = security.get("runAsUser")
    message = waiting.get("message", "")
    return (waiting.get("reason") == "CreateContainerConfigError"
            and security.get("runAsNonRoot") is True and type(uid) is int and uid == 0
            and isinstance(message, str) and _ROOT_POLICY_REJECTION.fullmatch(message) is not None)


def verify_kubernetes(manifest, contract):
    checks, runtime = [], {}
    infrastructure = None
    observed_uid = None
    created = False
    probed = False
    run_id = uuid.uuid4().hex
    namespace = "kube-repair-" + run_id[:16]
    started = time.monotonic()
    argv = None

    def call(arguments, input_value=None, cleanup=False):
        remaining = 50 if cleanup else min(8, 35 - (time.monotonic() - started))
        if remaining <= 0:
            raise RuntimeError("Kubernetes verification exceeded its deadline")
        code, stdout, stderr = command(argv + arguments, input_value=input_value, timeout=remaining)
        if code:
            raise RuntimeError(f"kubectl {arguments[0]} failed: {(stderr or stdout).strip()[:1200]}")
        return stdout

    def read(arguments):
        return json.loads(call(arguments + ["-o", "json"]))

    try:
        _static(copy.deepcopy(manifest), checks)
        _guard(manifest, contract)
        configuration = contract.get("kubernetes", {})
        expected_digest = image_digest(configuration.get("expected_image_id"))
        argv = prefix(configuration)
        runtime["context"] = configuration["context"]
        runtime["fixture_kind"] = contract.get("fixture_kind", "file-cache")
        runtime["probe_sha256"] = hashlib.sha256(_probe_for_contract(contract).encode()).hexdigest()
        runtime["namespace"] = namespace
        runtime["server_version"] = json.loads(call(["version", "-o", "json"])).get("serverVersion")
        ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": namespace, "labels": {
            OWNER_LABEL: run_id, "pod-security.kubernetes.io/enforce": "baseline",
        }}}
        # Record before create: timeout can still leave the uniquely named namespace behind.
        created = True
        created_ns = json.loads(call(["create", "-f", "-", "-o", "json"], ns))
        observed_uid = created_ns["metadata"]["uid"]
        if created_ns["metadata"].get("labels", {}).get(OWNER_LABEL) != run_id:
            raise RuntimeError("Created namespace does not match this run")
        deployed = copy.deepcopy(manifest)
        deployed["metadata"]["namespace"] = namespace
        deployment = json.loads(call(["-n", namespace, "apply", "-f", "-", "-o", "json"], deployed))
        deployment_uid = deployment["metadata"]["uid"]
        generation = deployment["metadata"]["generation"]
        runtime.update({"deployment_uid": deployment_uid, "generation": generation})
        selected = None
        logs = ""
        startup_rejection = None
        while time.monotonic() - started < 25:
            pods = read(["-n", namespace, "get", "pods", "-l", "app=repair-cache-app"])["items"]
            if len(pods) > 1:
                raise RuntimeError("Unexpected extra fixture pods")
            if not pods:
                time.sleep(0.1)
                continue
            selected = pods[0]
            pod_name = selected["metadata"]["name"]
            status = next((s for s in selected.get("status", {}).get("containerStatuses", []) if s.get("name") == "app"), {})
            state = status.get("state", {})
            waiting = state.get("waiting", {})
            if waiting:
                runtime["container_waiting"] = {
                    "reason": waiting.get("reason", "")[:128],
                    "message": waiting.get("message", "")[:2000],
                }
            if waiting.get("reason") in ("ErrImageNeverPull", "ImagePullBackOff", "ErrImagePull", "CreateContainerConfigError"):
                if status.get("ready") is not True and _root_policy_rejection(manifest, waiting):
                    startup_rejection = runtime["container_waiting"]["message"]
                    break
                detail = runtime["container_waiting"]
                raise RuntimeError("Fixture image/configuration is unavailable: " + detail["reason"]
                                   + (": " + detail["message"] if detail["message"] else ""))
            if any(c.get("type") == "PodScheduled" and c.get("status") == "False" for c in selected.get("status", {}).get("conditions", [])):
                raise RuntimeError("Fixture pod could not be scheduled")
            if status.get("ready") is True:
                break
            if state.get("terminated") or status.get("lastState", {}).get("terminated") or waiting.get("reason") == "CrashLoopBackOff":
                logs = call(["-n", namespace, "logs", pod_name, "-c", "app", "--tail=10"]).strip()
                break
            time.sleep(0.1)
        if selected is None:
            raise RuntimeError("No fixture pod was created before the deadline")
        owners = selected["metadata"].get("ownerReferences", [])
        owner = next((o for o in owners if o.get("kind") == "ReplicaSet" and o.get("controller") is True), None)
        if not owner:
            raise RuntimeError("Fixture pod has no expected ReplicaSet owner")
        replica = read(["-n", namespace, "get", "replicaset", owner["name"]])
        if replica["metadata"]["uid"] != owner["uid"] or not any(
            o.get("kind") == "Deployment" and o.get("uid") == deployment_uid and o.get("controller") is True
            for o in replica["metadata"].get("ownerReferences", [])
        ):
            raise RuntimeError("Fixture resource ownership changed")
        runtime["pod_uid"] = selected["metadata"]["uid"]
        runtime["pod_name"] = selected["metadata"]["name"]
        actual_id = status.get("imageID", "")
        runtime["image_id"] = actual_id
        if startup_rejection and not actual_id:
            # Kubelet rejects the contradictory UID policy before creating a
            # container, so there is no runtime image identity or execution claim.
            _check(checks, "runtime-image-identity", False,
                   "No container image ID: kubelet rejected startup before creating the container")
        else:
            _check(checks, "runtime-image-identity", image_digest(actual_id) == expected_digest,
                   f"Expected {expected_digest}; observed {actual_id}")
            if not checks[-1]["passed"]:
                raise RuntimeError("Fixture image identity differs from the setup pin")
        if status.get("ready") is not True:
            if startup_rejection:
                runtime["startup_error"] = startup_rejection
                _check(checks, "application-cache", False, "Fixture startup rejected: " + startup_rejection[:1500])
            else:
                if not logs:
                    logs = call(["-n", namespace, "logs", runtime["pod_name"], "-c", "app", "--tail=10"]).strip()
                runtime["startup_logs"] = logs[:2000]
                _check(checks, "application-cache", False, "Fixture startup/cache failed: " + logs[:1500])
            for check in _RUNTIME_CHECKS[1:]:
                _check(checks, check, False, "No successful runtime probe: application was not ready")
        else:
            result = json.loads(call(["-n", namespace, "exec", runtime["pod_name"], "-c", "app", "--",
                                      "python", "-c", _probe_for_contract(contract), contract["cache_path"]]))
            if set(result) != set(_RUNTIME_CHECKS):
                raise RuntimeError("Trusted probe returned an unexpected check inventory")
            for name in _RUNTIME_CHECKS:
                item = result[name]
                if not isinstance(item, list) or len(item) != 2 or type(item[0]) is not bool or not isinstance(item[1], str):
                    raise RuntimeError("Trusted probe returned malformed evidence")
                _check(checks, name, item[0], item[1])
            probed = True
        current_deployment = read(["-n", namespace, "get", "deployment", "repair-cache-app"])
        current_pod = read(["-n", namespace, "get", "pod", runtime["pod_name"]])
        if (current_deployment["metadata"]["uid"] != deployment_uid or current_deployment["metadata"]["generation"] != generation
                or current_pod["metadata"]["uid"] != runtime["pod_uid"]):
            raise RuntimeError("Workload identity/version changed during verification")
    except Exception as exc:
        infrastructure = f"{type(exc).__name__}: {exc}"
        _check(checks, "verifier-infrastructure", False, infrastructure)
    finally:
        if created and argv:
            try:
                current = json.loads(call(["get", "namespace", namespace, "-o", "json"], cleanup=True))
                metadata = current["metadata"]
                if metadata.get("labels", {}).get(OWNER_LABEL) != run_id or (observed_uid and metadata.get("uid") != observed_uid):
                    raise RuntimeError("Namespace UID/ownership differs; deletion refused")
                call(["delete", "namespace", namespace, "--wait=true", "--timeout=45s"], cleanup=True)
                _check(checks, "namespace-cleanup", True, "Only this run's namespace was deleted")
            except Exception as exc:
                error = f"Namespace cleanup failed: {type(exc).__name__}: {exc}"
                infrastructure = (infrastructure + "; " if infrastructure else "") + error
                _check(checks, "namespace-cleanup", False, error)
    by_name = {c["name"]: c["passed"] for c in checks}
    static = [c for c in checks if c["name"].startswith("static-")]
    static_pass = bool(static) and all(c["passed"] for c in static)
    behavior_pass = by_name.get("application-cache", False)
    negative_pass = all(by_name.get(name, False) for name in _RUNTIME_CHECKS[1:])
    passed = static_pass and behavior_pass and negative_pass and all(c["passed"] for c in checks)
    return {"backend": "kubernetes", "runtime_verified": probed, "static_pass": static_pass,
            "behavior_pass": behavior_pass, "negative_pass": negative_pass, "passed": passed,
            "checks": checks, "feedback": [c["detail"] for c in checks if not c["passed"]],
            "infrastructure_error": infrastructure, "runtime": runtime,
            "kubernetes_execution_observed": bool(runtime.get("image_id"))}
