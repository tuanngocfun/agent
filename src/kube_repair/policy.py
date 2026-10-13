"""An allowlist over a fixed Deployment; never a model-generated shell command."""

import copy
import json

SECURITY_FIELDS = {
    "runAsNonRoot", "runAsUser", "runAsGroup", "readOnlyRootFilesystem",
    "allowPrivilegeEscalation", "capabilities", "seccompProfile",
}
SECURE_CONTEXT = {
    "runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
    "readOnlyRootFilesystem": True, "allowPrivilegeEscalation": False,
    "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"},
}


def pod_spec(manifest):
    return manifest["spec"]["template"]["spec"]


def app_container(manifest):
    pod = pod_spec(manifest)
    if len(pod["containers"]) != 1 or pod["containers"][0]["name"] != "app":
        raise ValueError("Fixture must preserve exactly one app container")
    return pod["containers"][0]


def harden(manifest, uid=10001, gid=10001):
    result = copy.deepcopy(manifest)
    security = copy.deepcopy(SECURE_CONTEXT)
    security.update({"runAsUser": uid, "runAsGroup": gid})
    app_container(result).setdefault("securityContext", {}).update(security)
    return result


def repair_storage(manifest, contract):
    result = copy.deepcopy(manifest)
    pod = pod_spec(result)
    cache = contract["cache_path"]
    pod["volumes"] = [{"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}}]
    app_container(result)["volumeMounts"] = [{"name": "cache-data", "mountPath": cache}]
    # Kubernetes adjusts supported volume group ownership; Docker runner emulates this.
    pod.setdefault("securityContext", {})["fsGroup"] = contract.get("volume_gid") or contract.get("allowed_primary_gid", 10001)
    return result


def _protected_projection(manifest):
    result = copy.deepcopy(manifest)
    pod = pod_spec(result)
    container = app_container(result)
    security = container.get("securityContext", {})
    for key in SECURITY_FIELDS:
        security.pop(key, None)
    if not security:
        container.pop("securityContext", None)
    psecurity = pod.get("securityContext", {})
    psecurity.pop("fsGroup", None)
    if not psecurity:
        pod.pop("securityContext", None)
    pod.pop("volumes", None)
    container.pop("volumeMounts", None)
    return result


def validate_candidate(base, candidate, contract):
    errors = []
    try:
        if not isinstance(candidate, dict):
            return ["Candidate must be a Deployment object"]
        pod, container = pod_spec(candidate), app_container(candidate)
        if json.dumps(_protected_projection(base), sort_keys=True, allow_nan=False) != json.dumps(
            _protected_projection(candidate), sort_keys=True, allow_nan=False
        ):
            errors.append("Protected fields changed: identity, image, app/env, resources, annotations or evaluator scope")
        security = container.get("securityContext", {})
        if not isinstance(security, dict):
            return errors + ["securityContext must be an object"]
        base_security = app_container(base).get("securityContext", {})
        for key, value in security.items():
            if key not in SECURITY_FIELDS:
                continue  # exact equality of protected projection already required
            if value == base_security.get(key) and type(value) is type(base_security.get(key)):
                continue
            if key in ("runAsUser", "runAsGroup"):
                allowed = (contract.get("allowed_uid", 10001),) if key == "runAsUser" else tuple(contract.get("allowed_groups", (10001, 2000)))
                if type(value) is not int or value not in allowed:
                    errors.append(f"Unapproved {key}: only task-approved non-root identities may be proposed")
            elif value != SECURE_CONTEXT[key] or type(value) is not type(SECURE_CONTEXT[key]):
                errors.append(f"Unapproved security control value for {key}")
        psecurity = pod.get("securityContext", {})
        if not isinstance(psecurity, dict):
            return errors + ["Pod securityContext must be an object"]
        if "fsGroup" in psecurity and (type(psecurity["fsGroup"]) is not int or psecurity["fsGroup"] not in contract.get("allowed_groups", (10001, 2000))):
            errors.append("fsGroup must be an approved non-root group")
        volumes = pod.get("volumes", [])
        mounts = container.get("volumeMounts", [])
        if not isinstance(volumes, list) or not isinstance(mounts, list):
            return errors + ["Volumes and mounts must be lists"]
        permitted_volume = {"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}}
        if volumes not in ([], [permitted_volume]):
            errors.append("Only the bounded task-owned cache-data emptyDir is allowed")
        if len(mounts) > 1:
            errors.append("Only one approved cache mount is allowed")
        for mount in mounts:
            if not isinstance(mount, dict) or set(mount) != {"name", "mountPath"}:
                errors.append("Mount must contain only name and mountPath")
            elif mount["name"] != "cache-data" or mount["mountPath"] not in contract["allowed_mount_paths"]:
                errors.append("Unapproved mount name/path")
        if bool(volumes) != bool(mounts):
            errors.append("Cache volume and mount must be paired")
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        errors.append(f"Malformed fixture manifest: {type(exc).__name__}")
    return errors
