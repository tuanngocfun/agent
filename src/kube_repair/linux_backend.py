"""Independent real-service checks in an unprivileged Linux process sandbox.

No container or Kubernetes runtime is involved. Only the trusted cache fixture
is run. Manifest paths map to private task directories; reads are not isolated.
"""

from __future__ import annotations

import copy
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid

from .verification import VerificationInfrastructureError, _RUNTIME_CHECKS, _check, _env, _matching_mount, _static


_PROJECT = Path(__file__).resolve().parents[2]
_WORKLOAD_ROOT = _PROJECT / "runs" / "linux-workloads"
_TIME_LIMIT = 25.0
_OUTPUT_LIMIT = 65536


def _configuration(pod: dict, container: dict, contract: dict, task_root: Path) -> dict:
    if sys.platform != "linux" or os.uname().machine != "x86_64":
        raise VerificationInfrastructureError("Linux x86_64 is required; no simulated fallback was used")
    if contract.get("requires_root") or contract.get("volume_gid") is not None:
        raise ValueError("linux-process supports cache-path/already-secure only; root/group contracts are unsupported")
    sc = container.get("securityContext", {})
    uid, gid = sc.get("runAsUser"), sc.get("runAsGroup")
    if type(uid) is not int or type(gid) is not int or uid != os.geteuid() or gid != os.getegid() or uid <= 0:
        raise ValueError("linux-process requires declared UID/GID to match this non-root host user")
    if sc.get("privileged", False) is not False or sc.get("capabilities", {}).get("add"):
        raise ValueError("linux-process cannot run privileged or added-capability configurations")
    pod_sc = pod.get("securityContext", {})
    if pod_sc.get("fsGroup") not in (None, gid) or pod_sc.get("supplementalGroups"):
        raise ValueError("linux-process cannot emulate fsGroup/supplementary-group changes")
    if container.get("command") or container.get("args") or container.get("lifecycle"):
        raise ValueError("linux-process executes only the trusted fixed fixture")
    env = _env(container)
    if set(env) - {"CACHE_DIR", "FIXTURE_REQUIRES_ROOT"} or env.get("FIXTURE_REQUIRES_ROOT", "0") != "0":
        raise ValueError("Unsupported environment for the trusted Linux fixture")
    cache = env.get("CACHE_DIR", contract["cache_path"])
    if cache != "/var/cache/repair-app" or cache not in contract.get("allowed_cache_paths", [contract["cache_path"]]):
        raise ValueError("linux-process supports the contracted /var/cache/repair-app path only")
    volumes = {}
    for volume in pod.get("volumes", []):
        if set(volume) != {"name", "emptyDir"} or volume["name"] in volumes or not isinstance(volume["emptyDir"], dict):
            raise ValueError("Only unique emptyDir volumes are supported")
        if set(volume["emptyDir"]) - {"sizeLimit", "medium"} or volume["emptyDir"].get("medium", "") not in ("", "Memory"):
            raise ValueError("Unsupported emptyDir configuration")
        volumes[volume["name"]] = volume
    mounts = container.get("volumeMounts", [])
    if len(mounts) > 1:
        raise ValueError("linux-process accepts at most one cache mount")
    for mount in mounts:
        if set(mount) - {"name", "mountPath", "readOnly"} or mount.get("name") not in volumes or mount.get("mountPath") != cache or cache not in contract.get("allowed_mount_paths", []):
            raise ValueError("Only the permitted cache emptyDir mount is supported")
        if type(mount.get("readOnly", False)) is not bool:
            raise ValueError("Cache mount readOnly must be a boolean")
    mount = _matching_mount(pod, container, cache)
    seccomp = sc.get("seccompProfile", pod_sc.get("seccompProfile", {}))
    return {"cache": str(task_root / "fsroot" / "cache"),
            "outside_probe": str(task_root / "fsroot" / "outside-cache-probe"),
            "read_only": sc.get("readOnlyRootFilesystem") is True,
            "writable_cache": bool(mount and not mount.get("readOnly", False)),
            "no_new_privileges": sc.get("allowPrivilegeEscalation") is False,
            "seccomp": seccomp.get("type") == "RuntimeDefault"}


def _startup(proc: subprocess.Popen, control_fd: int, deadline: float) -> dict:
    assert proc.stdout is not None
    buffers = {control_fd: bytearray(), proc.stdout.fileno(): bytearray()}
    with selectors.DefaultSelector() as selector:
        selector.register(control_fd, selectors.EVENT_READ)
        selector.register(proc.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationInfrastructureError("Linux worker exceeded its startup deadline")
            for key, _ in selector.select(min(remaining, 0.1)):
                fd = key.fd
                chunk = os.read(fd, 4096)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[fd].extend(chunk)
                if sum(map(len, buffers.values())) > _OUTPUT_LIMIT:
                    raise VerificationInfrastructureError("Linux worker exceeded its 64 KiB output limit")
                if fd == control_fd and b"\n" in buffers[fd]:
                    try:
                        evidence = json.loads(bytes(buffers[fd]).split(b"\n", 1)[0])
                    except (ValueError, TypeError) as exc:
                        raise VerificationInfrastructureError("Trusted worker returned malformed evidence") from exc
                    if not isinstance(evidence, dict) or evidence.get("infrastructure_error"):
                        raise VerificationInfrastructureError(str(evidence.get("infrastructure_error", "Malformed evidence")))
                    port = evidence.get("port")
                    if type(port) is not int or not 1 <= port <= 65535:
                        raise VerificationInfrastructureError("Trusted worker returned an invalid listener port")
                    return evidence
    output = bytes(buffers[proc.stdout.fileno()]).decode("utf-8", "replace")
    raise VerificationInfrastructureError("Linux worker exited without startup evidence: " + output[:1000])


def _status(pid: int) -> dict[str, str]:
    result = {}
    with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
        for line in handle:
            if ":" in line:
                key, value = line.split(":", 1)
                result[key] = value.strip()
    return result


def _http(port: int, path: str, deadline: float) -> tuple[int, dict]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise VerificationInfrastructureError("Linux application probes exceeded the runtime limit")
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=min(1.5, remaining))
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(4097)
        if len(body) > 4096:
            raise VerificationInfrastructureError("Fixture HTTP response exceeded its output limit")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Fixture HTTP payload must be an object")
        return response.status, payload
    finally:
        connection.close()


def _probes(proc, evidence: dict, config: dict, checks: list[dict], deadline: float) -> None:
    status = _status(proc.pid)
    uid = int(status["Uid"].split()[1])
    gid = int(status["Gid"].split()[1])
    _check(checks, "runtime-non-root", uid == os.geteuid() and gid == os.getegid() and uid > 0,
           f"Parent inspected child effective UID={uid}, GID={gid}; no UID namespace or identity emulation")
    nnp = status.get("NoNewPrivs") == "1"
    _check(checks, "runtime-no-new-privileges", nnp, "Parent inspected child NoNewPrivs=" + status.get("NoNewPrivs", "missing"))
    caps = {key: int(status[key], 16) for key in ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")}
    caps_zero = all(caps[key] == 0 for key in ("CapEff", "CapPrm", "CapInh", "CapAmb"))
    _check(checks, "runtime-capabilities", caps_zero and nnp,
           "Parent inspected capabilities=" + json.dumps(caps, sort_keys=True) + "; effective/permitted/inheritable/ambient zero and no_new_privs prevent acquisition; inherited bounding mask is retained")
    _check(checks, "runtime-seccomp", status.get("Seccomp") == "2" and evidence.get("socket_errno") == errno.EACCES,
           "Parent inspected Seccomp=" + status.get("Seccomp", "missing") + "; trusted post-filter socket creation errno=" + str(evidence.get("socket_errno")) + "; local libseccomp profile, not OCI RuntimeDefault")
    write_denied = evidence.get("pre_write_succeeded") is True and evidence.get("outside_write_errno") == errno.EACCES and type(evidence.get("landlock_abi")) is int
    _check(checks, "runtime-read-only", write_denied,
           "Trusted write to task-owned outside-cache path: writable before restriction; after restriction errno=" + str(evidence.get("outside_write_errno")) + "; Landlock ABI=" + str(evidence.get("landlock_abi")) + "; EACCES write allowlist, not a read-only container mount/EROFS")
    try:
        port = evidence["port"]
        code, healthy = _http(port, "/health", deadline)
        value = "independent-probe-v1-" + uuid.uuid4().hex
        expected = hashlib.sha256(value.encode()).hexdigest()
        first_code, first = _http(port, "/compute?value=" + value, deadline)
        second_code, second = _http(port, "/compute?value=" + value, deadline)
        cache = Path(config["cache"])
        stored = (cache / (expected + ".txt")).read_text(encoding="utf-8")
        marker = (cache / "cache-contract.txt").read_text(encoding="utf-8")
        valid = code == first_code == second_code == 200 and healthy.get("ready") is True and first.get("result") == second.get("result") == stored == expected and first.get("cached") is False and second.get("cached") is True and marker == "kube-repair-cache-contract-v1"
        detail = "Parent checked real HTTP health, independent SHA-256 result, fresh request, repeated cached request, startup marker and cache read-back"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        valid = False
        detail = "Real service/cache behavior failed: " + str(exc)
    if evidence.get("cache_error"):
        valid = False
        detail += "; " + evidence["cache_error"]
    _check(checks, "application-cache", valid, detail)


def _execute(pod: dict, container: dict, contract: dict, checks: list[dict]) -> bool:
    # Validate before creating directories or starting a worker.
    _configuration(pod, container, contract, _WORKLOAD_ROOT / "validation-only")
    _WORKLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    task_root = Path(tempfile.mkdtemp(prefix="workload-", dir=_WORKLOAD_ROOT))
    proc = None
    control_read = control_write = None
    runtime_verified = False
    deadline = time.monotonic() + _TIME_LIMIT
    try:
        (task_root / "fsroot" / "cache").mkdir(parents=True)
        (task_root / "fsroot" / "outside-cache-probe").write_text("", encoding="utf-8")
        config = _configuration(pod, container, contract, task_root)
        control_read, control_write = os.pipe()
        argv = [sys.executable, "-B", str(Path(__file__).with_name("linux_child.py")), json.dumps(config, sort_keys=True), str(control_write)]
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, pass_fds=(control_write,), close_fds=True,
                                cwd=task_root, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"})
        os.close(control_write)
        control_write = None
        evidence = _startup(proc, control_read, deadline)
        _probes(proc, evidence, config, checks, deadline)
        runtime_verified = True
        _check(checks, "linux-process-scope", True,
               "Trusted local HTTP fixture only; manifest cache mapped to a private directory. No containers, Kubernetes admission, fsGroup, read/network namespaces or OCI seccomp equivalence verified. Listener binds ephemeral loopback; new socket/connect syscalls denied after startup when seccomp is requested")
    finally:
        cleanup_errors = []
        if proc is not None:
            try:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=1)
                if proc.stdout is not None:
                    remaining_output = proc.stdout.read(_OUTPUT_LIMIT + 1)
                    if len(remaining_output) > _OUTPUT_LIMIT:
                        cleanup_errors.append("Worker exceeded its 64 KiB output limit")
            except Exception as exc:
                cleanup_errors.append("Worker cleanup failed: " + str(exc))
            finally:
                if proc.stdout is not None:
                    proc.stdout.close()
        for fd in (control_read, control_write):
            if fd is not None:
                os.close(fd)
        try:
            shutil.rmtree(task_root)
            if task_root.exists():
                cleanup_errors.append("Task workload directory remains")
        except Exception as exc:
            cleanup_errors.append("Workload removal failed: " + str(exc))
        _check(checks, "linux-process-cleanup", not cleanup_errors,
               "; ".join(cleanup_errors) if cleanup_errors else "Ephemeral worker stopped and task files removed")
    return runtime_verified


def verify_linux(manifest: dict, contract: dict) -> dict[str, Any]:
    """Run actual process/service checks; unsupported inputs fail closed."""
    checks: list[dict] = []
    runtime_verified = False
    try:
        pod, container = _static(copy.deepcopy(manifest), checks)
        runtime_verified = _execute(pod, container, contract, checks)
    except Exception as exc:
        _check(checks, "verifier-infrastructure", False, f"{type(exc).__name__}: {exc}")
    by_name = {check["name"]: check["passed"] for check in checks}
    static_names = [name for name in by_name if name.startswith("static-")]
    static_pass = bool(static_names) and all(by_name[name] for name in static_names)
    behavior_pass = by_name.get("application-cache", False)
    negative_pass = all(by_name.get(name, False) for name in _RUNTIME_CHECKS[1:])
    infrastructure = [check["detail"] for check in checks if not check["passed"] and check["name"] in ("verifier-infrastructure", "linux-process-cleanup")]
    return {"backend": "linux-process", "runtime_verified": runtime_verified,
            "static_pass": static_pass, "behavior_pass": behavior_pass,
            "negative_pass": negative_pass,
            "passed": bool(checks) and static_pass and behavior_pass and negative_pass and all(item["passed"] for item in checks),
            "checks": checks, "infrastructure_error": "; ".join(infrastructure) if infrastructure else None,
            "feedback": [item["detail"] for item in checks if not item["passed"]]}
