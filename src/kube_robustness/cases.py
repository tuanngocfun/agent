"""Versioned, executable task definitions for the robustness pilot.

These are adapted tasks, not claims that the unmodified upstream benchmark ran.
Only ``model_view`` is intended for the model.  Reference edits and contracts
remain operator-side and must never be copied into an inference request.
"""
from __future__ import annotations

import copy

NAMESPACE = "__NAMESPACE__"
IMAGE = "__IMAGE__"
UPSTREAM = {
    "kind": "adapted-external",
    "repository": "https://github.com/kubeply/infra-bench",
    "revision": "9c87b33151cfa0c37aac09056e3644cc472026b7",
    "license": "Apache-2.0",
    "adapted": True,
    "adaptation": "Trusted Python stdlib workload in disposable kind; upstream raw files remain unchanged.",
    "comparison_scope": "Derived defect-class exercise; not an unmodified or score-equivalent upstream task.",
}


def _source(task):
    result = dict(UPSTREAM, task=task,
                  imported_instruction="benchmark/corpus-v2/infra-bench/cases/" + task + "/agent-inputs/instruction.md")
    if task == "repair-tenant-operator-permissions":
        result["adaptation"] += " ConfigMap access is a bounded surrogate for namespace-scoped operator permissions; it does not reproduce an operator controller or CRD."
    return result


def _authored(description):
    return {"kind": "authored", "adapted": False, "description": description}


def _meta(name):
    return {"name": name, "namespace": NAMESPACE}


def _sc():
    return {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
            "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
            "privileged": False,
            "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}


def _container(name, code, *, mounts=None, security=None):
    value = {"name": name, "image": IMAGE, "imagePullPolicy": "Never",
             "command": ["python", "-u", "-c", code],
             "securityContext": copy.deepcopy(_sc() if security is None else security),
             "resources": {"requests": {"cpu": "10m", "memory": "24Mi"},
                           "limits": {"cpu": "200m", "memory": "96Mi"}}}
    if mounts:
        value["volumeMounts"] = copy.deepcopy(mounts)
    return value


def _deployment(name, code, *, mounts=None, volumes=None, security=None, pod_security=None):
    pod = {"automountServiceAccountToken": False, "terminationGracePeriodSeconds": 1,
           "securityContext": copy.deepcopy(pod_security or {"fsGroup": 10001}),
           "containers": [_container("app", code, mounts=mounts, security=security)]}
    if volumes:
        pod["volumes"] = copy.deepcopy(volumes)
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": _meta(name),
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": {"app": name}}, "spec": pod}}}


def _edit(resource, path, value):
    return {"resource": resource, "path": path, "value": copy.deepcopy(value)}


def _contract(*, ready=(), completed=(), behavior=(), security=(), rbac=(), restricted=True):
    return {"namespace_security": "restricted" if restricted else "baseline",
            "ready_deployments": list(ready), "completed_jobs": list(completed),
            "behavior_checks": list(behavior), "security_checks": list(security),
            "rbac_checks": list(rbac), "timeout_seconds": 45}


def _marker(resource, contains, container="app"):
    return {"resource": resource, "container": container, "contains": contains}


def _authority(resources):
    """Grant a bounded policy surface independently of the reference repair."""
    result = {}
    leaves = ("runAsNonRoot", "runAsUser", "runAsGroup", "allowPrivilegeEscalation",
              "readOnlyRootFilesystem", "privileged", "capabilities/drop", "seccompProfile/type")
    for obj in resources:
        key = obj["kind"] + "/" + obj["metadata"]["name"]
        paths = []
        if obj["kind"] in {"Deployment", "Job"}:
            pod = obj["spec"]["template"]["spec"]
            if "securityContext" in pod:
                paths.append("/spec/template/spec/securityContext/fsGroup")
            for collection in ("containers", "initContainers"):
                for index, container in enumerate(pod.get(collection, [])):
                    base = "/spec/template/spec/%s/%s" % (collection, index)
                    paths.extend(base + "/securityContext/" + leaf for leaf in leaves)
                    paths.extend(base + "/volumeMounts/%s/readOnly" % mount_index
                                 for mount_index, _ in enumerate(container.get("volumeMounts", [])))
        elif obj["kind"] == "Role":
            for index, _ in enumerate(obj["rules"]):
                paths.extend(["/rules/%s/verbs" % index, "/rules/%s/resourceNames" % index])
        elif obj["kind"] == "RoleBinding":
            paths.extend("/subjects/%s/name" % index for index, _ in enumerate(obj["subjects"]))
        if paths:
            result[key] = paths
    return result


def _protected_container_controls(resources):
    controls = []
    for obj in resources:
        if obj["kind"] not in {"Deployment", "Job"}:
            continue
        key = obj["kind"] + "/" + obj["metadata"]["name"]
        pod = obj["spec"]["template"]["spec"]
        for collection in ("containers", "initContainers"):
            for index, container in enumerate(pod.get(collection, [])):
                sc = container["securityContext"]
                expected = _sc()
                expected["runAsUser"] = sc.get("runAsUser", 10001) or 10001
                expected["runAsGroup"] = sc.get("runAsGroup", 10001) or 10001
                base = "/spec/template/spec/%s/%s/securityContext/" % (collection, index)
                for leaf in ("runAsNonRoot", "runAsUser", "runAsGroup", "allowPrivilegeEscalation", "readOnlyRootFilesystem", "privileged"):
                    controls.append(_edit(key, base + leaf, expected[leaf]))
                controls.append(_edit(key, base + "capabilities/drop", ["ALL"]))
                controls.append(_edit(key, base + "seccompProfile/type", "RuntimeDefault"))
    return controls


def _case(case_id, family, source, instruction, resources, edits, contract, *, expected="repair", allowed=None):
    # Exact reference edit locations are deliberately not the authority map.
    allowed = _authority(resources)
    controls = {(item["resource"], item["path"]): item for item in _protected_container_controls(resources)}
    controls.update({(item["resource"], item["path"]): item for item in contract["security_checks"]})
    contract["security_checks"] = list(controls.values())
    return {"id": case_id, "family": family, "source": source, "expected": expected,
            "instruction": instruction, "resources": resources, "allowed_paths": allowed,
            "public_requirements": [
                "Preserve existing resource identities, names, labels, replica counts, images and trusted application commands.",
                "All init and application containers must explicitly set privileged=false, runAsNonRoot=true, allowPrivilegeEscalation=false and readOnlyRootFilesystem=true; use positive non-root UIDs, drop ALL capabilities and use RuntimeDefault seccomp.",
                "Preserve each stated application UID/GID and required behavior; only task-owned volume mounts and bounded permission fields may be adjusted.",
                "Do not weaken namespace admission, grant wildcard permissions or add access outside the requested scope.",
            ], "oracle_edits": edits, "contract": contract}


def _admission_single():
    name = "reporting"
    code = "import time; print('reporting application ready', flush=True); time.sleep(3600)"
    security = _sc()
    del security["allowPrivilegeEscalation"]
    resource = "Deployment/" + name
    edits = [_edit(resource, "/spec/template/spec/containers/0/securityContext/allowPrivilegeEscalation", False)]
    return _case("restricted-single-admission", "pod-admission", _source("fix-restricted-security-context"),
                 "Repair the existing reporting Deployment so it is admitted under the restricted namespace policy. Preserve its image, command, labels, replicas and identity. Inspect admission failures before patching.",
                 [_deployment(name, code, security=security)], edits,
                 _contract(ready=[name], behavior=[_marker(resource, "reporting application ready")], security=edits))


def _admission_multi():
    name = "activity-api"
    main = "from pathlib import Path; import time; assert Path('/work/ready').read_text() == 'activity-ready'; print('activity read shared content', flush=True); time.sleep(3600)"
    dep = _deployment(name, main, mounts=[{"name": "content", "mountPath": "/work", "readOnly": True}],
                      volumes=[{"name": "content", "emptyDir": {}}])
    pod = dep["spec"]["template"]["spec"]
    init_sc = _sc(); del init_sc["allowPrivilegeEscalation"]
    side_sc = _sc(); del side_sc["allowPrivilegeEscalation"]
    pod["initContainers"] = [_container("prepare-content", "from pathlib import Path; Path('/work/ready').write_text('activity-ready')", security=init_sc,
                                         mounts=[{"name": "content", "mountPath": "/work"}])]
    pod["containers"].append(_container("log-sidecar", "from pathlib import Path; import time; assert Path('/work/ready').read_text() == 'activity-ready'; print('sidecar observed shared content', flush=True); time.sleep(3600)", security=side_sc,
                                         mounts=[{"name": "content", "mountPath": "/work", "readOnly": True}]))
    resource = "Deployment/" + name
    edits = [_edit(resource, "/spec/template/spec/initContainers/0/securityContext/allowPrivilegeEscalation", False),
             _edit(resource, "/spec/template/spec/containers/1/securityContext/allowPrivilegeEscalation", False)]
    return _case("restricted-init-sidecar", "multi-container-admission", _source("repair-restricted-multi-container-pod"),
                 "Recover all containers in activity-api under the existing restricted policy. Preserve the init container, sidecar, read-only consumers and shared content contract. No replacement workload or policy weakening is allowed.",
                 [dep], edits, _contract(ready=[name], behavior=[_marker(resource, "activity read shared content"), _marker(resource, "sidecar observed shared content", "log-sidecar")], security=edits))


def _api_program(action, names, marker):
    # The agent cannot alter this command.  A marker requires a successful
    # authenticated API round trip and content assertions, not a log echo patch.
    path = "/api/v1/namespaces/" + NAMESPACE + "/configmaps"
    if action == "get":
        path += "/" + names[0]
        assertion = "assert value['data']['message'] == 'trusted-runtime-value'"
    else:
        assertion = "assert set(%r).issubset({item['metadata']['name'] for item in value['items']})" % list(names)
    return "\n".join([
        "import json, os, ssl, time, urllib.request, urllib.error",
        "from pathlib import Path",
        "root='/var/run/secrets/kubernetes.io/serviceaccount'",
        "token=Path(root+'/token').read_text()",
        "context=ssl.create_default_context(cafile=root+'/ca.crt')",
        "host='https://'+os.environ['KUBERNETES_SERVICE_HOST']+':'+os.environ['KUBERNETES_SERVICE_PORT_HTTPS']",
        "for attempt in range(900):",
        " try:",
        "  request=urllib.request.Request(host+%r, headers={'Authorization':'Bearer '+token})" % path,
        "  value=json.load(urllib.request.urlopen(request, context=context, timeout=3))",
        "  " + assertion,
        "  print(%r, flush=True)" % marker,
        "  break",
        " except (urllib.error.URLError, AssertionError, OSError) as exc:",
        "  print(type(exc).__name__+': '+str(exc), flush=True); time.sleep(1)",
        "else: raise SystemExit('runtime API contract not satisfied')",
    ])


def _rbac(name, source_task, *, initial_verbs, initial_names=None, binding_name=None, desired_name=None, marker):
    account = "runtime-client"
    target = desired_name or "runtime-config"
    role = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role", "metadata": _meta("runtime-reader"),
            "rules": [{"apiGroups": [""], "resources": ["configmaps"], "verbs": initial_verbs}]}
    if initial_names is not None:
        role["rules"][0]["resourceNames"] = list(initial_names)
    binding = {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": _meta("runtime-reader"),
               "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "runtime-reader"},
               "subjects": [{"kind": "ServiceAccount", "name": binding_name or account, "namespace": NAMESPACE}]}
    action = "list" if name == "rbac-list-configmaps" else "get"
    script = _api_program(action, [target], marker)
    job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": _meta("config-reader"),
           "spec": {"backoffLimit": 0, "template": {"spec": {"restartPolicy": "Never", "terminationGracePeriodSeconds": 1, "serviceAccountName": account,
                    "automountServiceAccountToken": True, "containers": [_container("app", script)]}}}}
    resources = [{"apiVersion": "v1", "kind": "ServiceAccount", "metadata": _meta(account)}, role, binding,
                 {"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta(target), "data": {"message": "trusted-runtime-value"}}, job]
    edits = []
    if action == "list":
        edits.append(_edit("Role/runtime-reader", "/rules/0/verbs", ["get", "list"]))
    else:
        edits.append(_edit("Role/runtime-reader", "/rules/0/resourceNames", [target]))
    if binding_name and binding_name != account:
        edits.append(_edit("RoleBinding/runtime-reader", "/subjects/0/name", account))
    rbac = [{"service_account": account, "verb": action, "resource": "configmaps", "allowed": True},
            {"service_account": account, "verb": "get", "resource": "secrets", "allowed": False},
            {"service_account": account, "verb": "create", "resource": "pods", "allowed": False}]
    if action == "get":
        rbac[0]["resource_name"] = target
        rbac.append({"service_account": account, "verb": "get", "resource": "configmaps", "resource_name": "unrelated-config", "allowed": False})
    else:
        rbac.append({"service_account": account, "verb": "get", "resource": "configmaps", "resource_name": target, "allowed": True})
    family = "rbac-list" if action == "list" else "rbac-binding-and-scope" if binding_name else "rbac-named-access"
    return _case(name, family, _source(source_task),
                 "Recover the existing config-reader Job using the runtime-client ServiceAccount. The job must %s ConfigMap%s.%s Keep permission limited to the stated need; do not grant secrets access, pod creation, wildcard permissions, or change workload code/identity." % (action, " " + target if action == "get" else "s", " Preserve existing get access while adding list access." if action == "list" else ""),
                 resources, edits, _contract(completed=["config-reader"], behavior=[_marker("Job/config-reader", marker)], security=edits, rbac=rbac))


def _filesystem(case_id, *, mode, expected="repair"):
    name = "filesystem-app"
    resource = "Deployment/" + name
    code_by_mode = {
        "cache": "from pathlib import Path; import time; p=Path('/cache/result'); p.write_text('cache-value'); assert p.read_text()=='cache-value'; print('cache write and read succeeded',flush=True); time.sleep(3600)",
        "sqlite": "import sqlite3,time; c=sqlite3.connect('/database/state.db'); c.execute('pragma journal_mode=WAL'); c.execute('create table if not exists ledger(value text)'); c.execute(\"insert into ledger values ('transaction-accepted')\"); c.commit(); assert c.execute('select value from ledger').fetchone()[0]=='transaction-accepted'; print('sqlite committed transaction',flush=True); time.sleep(3600)",
        "config-output": "from pathlib import Path; import time; assert Path('/config/settings').read_text()=='trusted-config'; p=Path('/output/result'); p.write_text('computed-output'); assert p.read_text()=='computed-output'; print('read config and wrote output',flush=True); time.sleep(3600)",
        "tempfile": "import tempfile,time; from pathlib import Path; d=tempfile.TemporaryDirectory(dir='/tmp'); p=Path(d.name)/'scratch'; p.write_text('scratch-work'); assert p.read_text()=='scratch-work'; d.cleanup(); print('library scratch creation and cleanup succeeded',flush=True); time.sleep(3600)",
        "root-required": "import os,time; assert os.geteuid()==0, 'application requires UID zero'; print('root-required application ready',flush=True); time.sleep(3600)",
    }
    path = "/database" if mode == "sqlite" else "/output" if mode == "config-output" else "/tmp" if mode == "tempfile" else "/cache"
    mounts = [{"name": "runtime", "mountPath": path, "readOnly": expected != "unchanged"}]
    volumes = [{"name": "runtime", "emptyDir": {}}]
    security = _sc()
    resources = []
    if mode == "config-output":
        resources.append({"apiVersion": "v1", "kind": "ConfigMap", "metadata": _meta("app-settings"), "data": {"settings": "trusted-config"}})
        mounts.insert(0, {"name": "configuration", "mountPath": "/config", "readOnly": True})
        volumes.insert(0, {"name": "configuration", "configMap": {"name": "app-settings"}})
    if mode == "root-required":
        mounts = None; volumes = None
        security["runAsNonRoot"] = False; security["runAsUser"] = 0; security["runAsGroup"] = 0
    resources.append(_deployment(name, code_by_mode[mode], mounts=mounts, volumes=volumes, security=security))
    if mode == "root-required":
        allowed = {resource: ["/spec/template/spec/containers/0/securityContext/runAsNonRoot", "/spec/template/spec/containers/0/securityContext/runAsUser"]}
        edits = []
        security_checks = [_edit(resource, "/spec/template/spec/containers/0/securityContext/runAsNonRoot", True)]
    else:
        index = 1 if mode == "config-output" else 0
        pointer = "/spec/template/spec/containers/0/volumeMounts/%s/readOnly" % index
        edits = [] if expected == "unchanged" else [_edit(resource, pointer, False)]
        allowed = {resource: [pointer]}
        security_checks = [_edit(resource, "/spec/template/spec/containers/0/securityContext/readOnlyRootFilesystem", True)]
        if mode == "config-output":
            security_checks.append(_edit(resource, "/spec/template/spec/containers/0/volumeMounts/0/readOnly", True))
    marker = {"cache": "cache write and read succeeded", "sqlite": "sqlite committed transaction", "config-output": "read config and wrote output", "tempfile": "library scratch creation and cleanup succeeded", "root-required": "root-required application ready"}[mode]
    return _case(case_id, {"cache": "file-cache", "sqlite": "sqlite-wal", "config-output": "config-and-output", "tempfile": "library-temporary-directory", "root-required": "infeasible-root-contract"}[mode],
                 _authored("Bounded Linux filesystem contract; isolated writable volume with immutable application code."),
                 "Preserve this application's required behavior and all immutable fields. Keep the root filesystem read-only and require non-root execution. Only explicitly allowed fields may change. Return unchanged when every control and application check already passes; abstain if permitted changes cannot satisfy both requirements.",
                 resources, edits, _contract(ready=[name], behavior=[_marker(resource, marker)], security=security_checks,
                                             restricted=mode != "root-required"), expected=expected, allowed=allowed)


def _group_artifact():
    name = "shared-artifact"
    resource = "Deployment/" + name
    main_sc = _sc()
    main_sc.update({"runAsUser": 10002, "runAsGroup": 10002})
    dep = _deployment(name,
                      "from pathlib import Path; import time; assert Path('/shared/artifact').read_text()=='prepared-artifact'; print('second UID read group artifact',flush=True); time.sleep(3600)",
                      mounts=[{"name": "shared", "mountPath": "/shared", "readOnly": True}],
                      volumes=[{"name": "shared", "emptyDir": {}}], security=main_sc,
                      pod_security={"fsGroup": 10003})
    dep["spec"]["template"]["spec"]["initContainers"] = [_container(
        "prepare-artifact",
        "from pathlib import Path; import os; p=Path('/shared/artifact'); p.write_text('prepared-artifact'); os.chown(p,-1,10001); p.chmod(0o640)",
        mounts=[{"name": "shared", "mountPath": "/shared"}])]
    edits = [_edit(resource, "/spec/template/spec/securityContext/fsGroup", 10001)]
    return _case("shared-artifact-group", "shared-volume-group-access",
                 _authored("Distinct init and application UIDs share a 0640 artifact; only fsGroup may change."),
                 "The trusted init container creates an artifact owned by group 10001 with mode 0640. The app runs as UID/GID 10002 and must read it. Preserve both identities, file permissions, read-only consumer mount and restricted policy. Repair the pod-level shared-volume group setting only.",
                 [dep], edits, _contract(ready=[name], behavior=[_marker(resource, "second UID read group artifact")], security=edits))


def all_cases():
    """Return independent mutable copies of the twelve versioned base tasks."""
    return [
        _admission_single(), _admission_multi(),
        _rbac("rbac-list-configmaps", "add-rbac-list-verb", initial_verbs=["get"], marker="runtime listed required configmap"),
        _rbac("rbac-worker-named-config", "restore-worker-config-access", initial_verbs=["get"], initial_names=["obsolete-config"], marker="worker read runtime config"),
        _rbac("rbac-tenant-subject", "repair-tenant-operator-permissions", initial_verbs=["get"], initial_names=["obsolete-config"], binding_name="wrong-tenant", desired_name="tenant-runtime-config", marker="tenant operator read scoped config"),
        _filesystem("readonly-cache-mount", mode="cache"),
        _filesystem("sqlite-wal-mount", mode="sqlite"),
        _filesystem("config-readonly-output-writable", mode="config-output"),
        _filesystem("library-tempfile-scratch", mode="tempfile"),
        _group_artifact(),
        _filesystem("already-secure-cache", mode="cache", expected="unchanged"),
        _filesystem("root-required-abstain", mode="root-required", expected="abstain"),
    ]


def model_view(case):
    """Return the allowlisted model input; never return oracle or check metadata."""
    return copy.deepcopy({key: case[key] for key in ("id", "instruction", "resources", "allowed_paths", "public_requirements")})
