"""Trusted checks for the teaching lab and the optional isolated Docker lab.

The simulated backend demonstrates a state machine; it proves no runtime claim.
Docker checks Linux container behavior, not Kubernetes admission or fsGroup.
"""

from __future__ import annotations

import copy
import json
import os
import re
import selectors
import shutil
import subprocess
import time
import uuid
from typing import Any


_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}\Z")
_RUNTIME_CHECKS = ("application-cache", "runtime-non-root", "runtime-read-only",
                   "runtime-no-new-privileges", "runtime-capabilities", "runtime-seccomp")


class VerificationInfrastructureError(RuntimeError):
    """The independent verifier cannot obtain usable evidence."""


def _run(argv: list[str], timeout: float = 8.0) -> tuple[int, str]:
    """Run fixed argv with bounded time and bounded captured output, never a shell."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as exc:
        raise VerificationInfrastructureError(f"Could not start Docker CLI: {exc}") from exc
    assert proc.stdout is not None
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise VerificationInfrastructureError("Docker command exceeded its time limit")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        output.extend(chunk)
                        if len(output) > 65536:
                            raise VerificationInfrastructureError("Docker command exceeded its output limit")
            return proc.wait(timeout=max(0.01, timeout - (time.monotonic() - started))), output.decode("utf-8", "replace")
    except BaseException:
        proc.kill()
        proc.wait(timeout=2)
        raise
    finally:
        proc.stdout.close()


def _docker_path() -> str:
    path = shutil.which("docker")
    if not path:
        raise VerificationInfrastructureError("Docker CLI is unavailable; no simulated fallback was used")
    return path


def resolve_local_image(image: str) -> str:
    """Pin an explicitly requested, already local image without building or pulling."""
    if not isinstance(image, str) or not _IMAGE_REFERENCE.fullmatch(image):
        raise VerificationInfrastructureError("Invalid local image reference")
    code, output = _run([_docker_path(), "image", "inspect", "--format", "{{.Id}}", image])
    image_id = output.strip()
    if code or not _IMAGE_ID.fullmatch(image_id):
        raise VerificationInfrastructureError("The requested image is not available locally as a sha256 image ID")
    return image_id


def _container(manifest: dict) -> tuple[dict, dict]:
    pod = manifest["spec"]["template"]["spec"]
    containers = pod["containers"]
    if len(containers) != 1 or containers[0].get("name") != "app":
        raise ValueError("Verifier accepts one container named app")
    return pod, containers[0]


def _env(container: dict) -> dict[str, str]:
    env = {}
    for item in container.get("env", []):
        if set(item) != {"name", "value"} or item["name"] in env:
            raise ValueError("Verifier accepts unique literal environment values")
        if not isinstance(item["value"], str):
            raise ValueError("Environment values must be strings")
        env[item["name"]] = item["value"]
    return env


def _check(checks: list[dict], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": str(detail)})


def _static(manifest: dict, checks: list[dict]) -> tuple[dict, dict]:
    pod, container = _container(manifest)
    sc = container.get("securityContext", {})
    uid = sc.get("runAsUser")
    drop = sc.get("capabilities", {}).get("drop", [])
    seccomp = sc.get("seccompProfile", pod.get("securityContext", {}).get("seccompProfile", {}))
    items = (
        ("static-non-root", sc.get("runAsNonRoot") is True and type(uid) is int and uid > 0,
         "runAsNonRoot must be true and runAsUser must be a positive integer"),
        ("static-read-only", sc.get("readOnlyRootFilesystem") is True, "readOnlyRootFilesystem must be true"),
        ("static-no-escalation", sc.get("allowPrivilegeEscalation") is False, "allowPrivilegeEscalation must be false"),
        ("static-capabilities", "ALL" in drop and not sc.get("capabilities", {}).get("add"), "Drop ALL capabilities without adding any"),
        ("static-seccomp", seccomp.get("type") == "RuntimeDefault", "Use RuntimeDefault seccomp"),
        ("static-unprivileged", sc.get("privileged", False) is False, "Privileged containers are forbidden"),
    )
    for name, passed, detail in items:
        _check(checks, name, passed, detail)
    return pod, container


def _matching_mount(pod: dict, container: dict, path: str) -> dict | None:
    volume_names = {volume["name"] for volume in pod.get("volumes", []) if "emptyDir" in volume}
    matches = [mount for mount in container.get("volumeMounts", [])
               if mount.get("name") in volume_names
               and (path == mount.get("mountPath") or path.startswith(mount.get("mountPath", "\x00").rstrip("/") + "/"))]
    return max(matches, key=lambda m: len(m["mountPath"])) if matches else None


def _simulated(pod: dict, container: dict, contract: dict, checks: list[dict]) -> None:
    sc = container.get("securityContext", {})
    uid = sc.get("runAsUser", 0)
    env = _env(container)
    cache = env.get("CACHE_DIR", contract["cache_path"])
    mount = _matching_mount(pod, container, cache)
    required_gid = contract.get("volume_gid")
    fs_group = pod.get("securityContext", {}).get("fsGroup")
    if contract.get("requires_root") and uid != 0:
        behavior, detail = False, "Application initialization requires root under the trusted application contract"
    elif mount and mount.get("readOnly", False):
        behavior, detail = False, f"Read-only file system: cache mount at {cache} is read-only"
    elif sc.get("readOnlyRootFilesystem") is True and not mount:
        behavior, detail = False, f"Read-only file system: application cannot write cache at {cache}; no writable emptyDir covers it"
    elif mount and required_gid is not None and uid != 0 and fs_group != required_gid and sc.get("runAsGroup", 0) != required_gid:
        behavior, detail = False, f"Permission denied: cache volume group is {required_gid}; the non-root process lacks fsGroup={required_gid} or runAsGroup={required_gid}"
    elif not mount and uid != 0:
        behavior, detail = False, f"Permission denied: application cache path {cache} is owned by root and lacks a writable emptyDir"
    else:
        behavior, detail = True, f"Simulated cache write/read succeeds at {cache}; this is a model, not runtime evidence"
    _check(checks, "application-cache", behavior, detail)
    _check(checks, "runtime-non-root", type(uid) is int and uid > 0, "Simulated UID constraint only")
    _check(checks, "runtime-read-only", sc.get("readOnlyRootFilesystem") is True, "Simulated root write denial only")
    _check(checks, "runtime-no-new-privileges", sc.get("allowPrivilegeEscalation") is False, "Simulated no-new-privileges setting only")
    _check(checks, "runtime-capabilities", "ALL" in sc.get("capabilities", {}).get("drop", []) and not sc.get("capabilities", {}).get("add"), "Simulated capability constraint only")
    _check(checks, "runtime-seccomp", sc.get("seccompProfile", pod.get("securityContext", {}).get("seccompProfile", {})).get("type") == "RuntimeDefault", "Simulated seccomp setting only")


# The model cannot supply probe code, commands, or process arguments.
_PROBE = r'''
import errno, hashlib, json, os, sys, urllib.error, urllib.request
cache = sys.argv[1]
results = {}
try:
    with open(os.path.join(cache, "cache-contract.txt"), encoding="utf-8") as handle:
        value = handle.read()
    with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1) as response:
        healthy = response.status == 200 and json.loads(response.read(4096)).get("ready") is True
    expected = hashlib.sha256(b"independent-probe-v1").hexdigest()
    with urllib.request.urlopen("http://127.0.0.1:8080/compute?value=independent-probe-v1", timeout=1) as response:
        first = json.loads(response.read(4096))
    with urllib.request.urlopen("http://127.0.0.1:8080/compute?value=independent-probe-v1", timeout=1) as response:
        second = json.loads(response.read(4096))
    with open(os.path.join(cache, expected + ".txt"), encoding="utf-8") as handle:
        stored = handle.read()
    valid = healthy and value == "kube-repair-cache-contract-v1" and first.get("result") == expected and second.get("result") == expected and second.get("cached") is True and stored == expected
    results["application-cache"] = [valid, "HTTP health, independently computed SHA-256 result, cache read-back and repeated cached request checked"]
except (OSError, ValueError, urllib.error.URLError) as exc:
    results["application-cache"] = [False, "Service or cache behavior failed: " + str(exc)]
status = {}
with open("/proc/1/status", encoding="utf-8") as handle:
    for line in handle:
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
uid = int(status["Uid"].split()[1])
results["runtime-non-root"] = [uid > 0, "PID 1 effective UID=" + str(uid)]
results["runtime-no-new-privileges"] = [status.get("NoNewPrivs") == "1", "PID 1 NoNewPrivs=" + status.get("NoNewPrivs", "missing")]
results["runtime-seccomp"] = [status.get("Seccomp") == "2", "PID 1 Seccomp=" + status.get("Seccomp", "missing") + "; expected filter mode 2"]
caps = {key: int(status[key], 16) for key in ("CapEff", "CapPrm", "CapBnd")}
results["runtime-capabilities"] = [all(value == 0 for value in caps.values()), "PID 1 capabilities=" + json.dumps(caps, sort_keys=True)]
try:
    fd = os.open("/rootfs-write-probe", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    os.unlink("/rootfs-write-probe")
    results["runtime-read-only"] = [False, "Writing outside the allowed cache volume succeeded"]
except OSError as exc:
    results["runtime-read-only"] = [exc.errno == errno.EROFS, "Root write denied with errno=" + str(exc.errno) + "; expected EROFS"]
print(json.dumps(results, sort_keys=True))
'''


def _docker_args(docker: str, name: str, pod: dict, container: dict, contract: dict) -> list[str]:
    image = container.get("image", "")
    if not _IMAGE_ID.fullmatch(image):
        raise VerificationInfrastructureError("Docker verification requires a pinned local sha256 image ID")
    sc = container.get("securityContext", {})
    uid, gid = sc.get("runAsUser", 0), sc.get("runAsGroup", 0)
    if type(uid) is not int or uid < 0 or type(gid) is not int or gid < 0:
        raise ValueError("Invalid numeric process identity")
    argv = [docker, "run", "--detach", "--name", name, "--pull=never", "--network", "none",
            "--pids-limit", "32", "--memory", "128m", "--cpus", "0.5", "--restart", "no",
            "--log-opt", "max-size=64k", "--log-opt", "max-file=1", "--user", f"{uid}:{gid}",
            "--entrypoint", "python"]
    if sc.get("readOnlyRootFilesystem") is True:
        argv.append("--read-only")
    if sc.get("allowPrivilegeEscalation") is False:
        argv.extend(["--security-opt", "no-new-privileges=true"])
    if "ALL" in sc.get("capabilities", {}).get("drop", []):
        argv.extend(["--cap-drop", "ALL"])
    fs_group = pod.get("securityContext", {}).get("fsGroup")
    if fs_group is not None:
        if type(fs_group) is not int or fs_group < 0:
            raise ValueError("Invalid fsGroup")
        argv.extend(["--group-add", str(fs_group)])
    env = _env(container)
    if set(env) - {"CACHE_DIR", "FIXTURE_REQUIRES_ROOT"}:
        raise ValueError("Unsupported environment variable for the trusted fixture")
    if env.get("FIXTURE_REQUIRES_ROOT", "0") != ("1" if contract.get("requires_root") else "0"):
        raise ValueError("Fixture root requirement differs from the trusted contract")
    cache = env.get("CACHE_DIR", contract["cache_path"])
    if cache not in contract.get("allowed_cache_paths", [contract["cache_path"]]):
        raise ValueError("Unsupported cache path")
    argv.extend(["--env", f"CACHE_DIR={cache}", "--env", f"FIXTURE_REQUIRES_ROOT={env.get('FIXTURE_REQUIRES_ROOT', '0')}"])
    volumes = {volume["name"]: volume for volume in pod.get("volumes", [])}
    for mount in container.get("volumeMounts", []):
        path = mount.get("mountPath")
        volume = volumes.get(mount.get("name"))
        if path not in contract.get("allowed_mount_paths", []) or not volume or "emptyDir" not in volume or mount.get("subPath") or mount.get("subPathExpr"):
            raise ValueError("Docker verifier accepts only permitted emptyDir mount paths")
        volume_gid = contract.get("volume_gid")
        tmpfs_gid = volume_gid if volume_gid is not None else (fs_group or 0)
        mode = "0770" if volume_gid is not None else "1777"
        access = "ro" if mount.get("readOnly", False) else "rw"
        argv.extend(["--tmpfs", f"{path}:{access},nosuid,nodev,noexec,size=16m,mode={mode},uid=0,gid={tmpfs_gid}"])
    return argv + [image, "/app/app.py"]


def _docker(pod: dict, container: dict, contract: dict, checks: list[dict]) -> bool:
    docker = _docker_path()
    name = "kube-repair-" + uuid.uuid4().hex
    argv = _docker_args(docker, name, pod, container, contract)
    started = False
    probed = False
    deadline = time.monotonic() + 25

    def command(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise VerificationInfrastructureError("Docker verification exceeded its total time limit")
        return _run(args, timeout=min(8.0, remaining))

    try:
        # Set before the call: even a timed-out run may have created a container.
        started = True
        code, output = command(argv)
        if code:
            raise VerificationInfrastructureError("Docker container start failed: " + output.strip()[:1000])
        running = False
        for _ in range(20):
            code, state = command([docker, "inspect", "--format", "{{.State.Running}}", name])
            if code:
                raise VerificationInfrastructureError("Cannot inspect fixture container: " + state[:1000])
            if state.strip() == "true":
                # Probe itself can observe startup/cache-write races and retry.
                running = True
                break
            time.sleep(0.05)
        if not running:
            code, logs = command([docker, "logs", "--tail", "8", name])
            for check in _RUNTIME_CHECKS:
                _check(checks, check, False, "Fixture initialization failed: " + logs.strip()[:1000])
        else:
            cache = _env(container).get("CACHE_DIR", contract["cache_path"])
            evidence = None
            for attempt in range(10):
                code, output = command([docker, "exec", name, "python", "-c", _PROBE, cache])
                if code:
                    log_code, logs = command([docker, "logs", "--tail", "8", name])
                    for check in _RUNTIME_CHECKS:
                        _check(checks, check, False, "Fixture could not run trusted probes: " + logs.strip()[:1000])
                    break
                try:
                    evidence = json.loads(output)
                except (ValueError, TypeError) as exc:
                    raise VerificationInfrastructureError("Trusted probe returned invalid JSON") from exc
                if evidence.get("application-cache", [False])[0] or attempt == 9:
                    for check in _RUNTIME_CHECKS:
                        item = evidence.get(check)
                        if not isinstance(item, list) or len(item) != 2 or type(item[0]) is not bool or not isinstance(item[1], str):
                            raise VerificationInfrastructureError("Trusted probe returned an invalid check")
                        _check(checks, check, item[0], item[1])
                    probed = True
                    break
                time.sleep(0.05)
        _check(checks, "docker-fsGroup-approximation", True,
               "Docker maps initialized tmpfs gid/mode and supplementary groups; Kubernetes fsGroup behavior is not verified")
    finally:
        if started:
            code, output = _run([docker, "rm", "--force", name])
            _check(checks, "container-cleanup", code == 0, "Ephemeral container removed" if code == 0 else "Container cleanup failed: " + output.strip()[:1000])
    return probed


def verify(manifest: dict, contract: dict, backend: str = "simulated") -> dict[str, Any]:
    """Evaluate independent controls and behavior; backend failures always fail closed."""
    if backend == "linux":
        from .linux_backend import verify_linux
        return verify_linux(copy.deepcopy(manifest), copy.deepcopy(contract))
    if backend == "kubernetes":
        from .kubernetes_backend import verify_kubernetes
        return verify_kubernetes(copy.deepcopy(manifest), copy.deepcopy(contract))
    checks: list[dict] = []
    runtime_verified = False
    try:
        pod, container = _static(copy.deepcopy(manifest), checks)
        if backend == "simulated":
            _simulated(pod, container, contract, checks)
        elif backend == "docker":
            runtime_verified = _docker(pod, container, contract, checks)
        else:
            raise ValueError(f"Unsupported verification backend: {backend}")
    except Exception as exc:
        _check(checks, "verifier-infrastructure", False, f"{type(exc).__name__}: {exc}")
    by_name = {check["name"]: check["passed"] for check in checks}
    static_names = [check["name"] for check in checks if check["name"].startswith("static-")]
    static_pass = bool(static_names) and all(by_name[name] for name in static_names)
    behavior_pass = by_name.get("application-cache", False)
    negative_pass = all(by_name.get(name, False) for name in _RUNTIME_CHECKS[1:])
    passed = bool(checks) and static_pass and behavior_pass and negative_pass and all(check["passed"] for check in checks)
    infrastructure = [check["detail"] for check in checks
                      if not check["passed"] and check["name"] in ("verifier-infrastructure", "container-cleanup")]
    return {"backend": backend, "runtime_verified": runtime_verified,
            "static_pass": static_pass, "behavior_pass": behavior_pass,
            "negative_pass": negative_pass, "passed": passed, "checks": checks,
            "infrastructure_error": "; ".join(infrastructure) if infrastructure else None,
            "feedback": [check["detail"] for check in checks if not check["passed"]]}
