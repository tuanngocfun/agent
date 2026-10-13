"""Trusted Linux fixture worker; configuration never contains executable code.

This worker is a local process, not a container. Landlock implements a write
allowlist; libseccomp applies a small local profile, not OCI RuntimeDefault.
"""

from __future__ import annotations

import ctypes
import errno
import importlib.util
import json
import os
from pathlib import Path
import resource
import socket
import sys
from http.server import HTTPServer


_WRITE_ACCESS = sum(1 << bit for bit in (1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14))


def _require(value: int, operation: str) -> int:
    if value < 0:
        error = ctypes.get_errno()
        raise OSError(error, operation + ": " + os.strerror(error))
    return value


def _landlock(cache: str | None) -> int:
    if os.uname().machine != "x86_64":
        raise RuntimeError("This local Landlock worker currently supports x86_64 only")
    libc = ctypes.CDLL(None, use_errno=True)
    abi = _require(libc.syscall(444, 0, 0, 1), "Landlock ABI query")
    if abi < 3:
        raise RuntimeError("Landlock ABI >= 3 is required for truncate enforcement")

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int)]

    ruleset = Ruleset(_WRITE_ACCESS)
    fd = _require(libc.syscall(444, ctypes.byref(ruleset), ctypes.sizeof(ruleset), 0), "Landlock create ruleset")
    try:
        if cache is not None:
            cache_fd = os.open(cache, os.O_PATH | os.O_CLOEXEC)
            try:
                rule = PathBeneath(_WRITE_ACCESS, cache_fd)
                _require(libc.syscall(445, fd, 1, ctypes.byref(rule), 0), "Landlock cache rule")
            finally:
                os.close(cache_fd)
        _require(libc.prctl(38, 1, 0, 0, 0), "PR_SET_NO_NEW_PRIVS")
        _require(libc.syscall(446, fd, 0), "Landlock restrict self")
    finally:
        os.close(fd)
    return abi


def _seccomp() -> None:
    library = ctypes.CDLL("libseccomp.so.2", use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError("libseccomp could not allocate a filter")
    try:
        denied = ("socket", "connect", "execve", "execveat", "ptrace", "capset",
                  "mount", "umount2", "pivot_root", "chroot", "clone", "clone3",
                  "fork", "vfork", "unshare", "setns", "bpf", "keyctl",
                  "userfaultfd", "io_uring_setup", "open_by_handle_at", "process_vm_writev")
        for name in denied:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number >= 0:
                value = library.seccomp_rule_add(context, 0x00050000 | errno.EACCES, number, 0)
                if value < 0:
                    raise OSError(-value, "libseccomp rule: " + name)
        value = library.seccomp_load(context)
        if value < 0:
            raise OSError(-value, "libseccomp load")
    finally:
        library.seccomp_release(context)


def _fixture_handler():
    path = Path(__file__).resolve().parents[2] / "fixtures" / "cache_app" / "app.py"
    spec = importlib.util.spec_from_file_location("trusted_linux_cache_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Trusted fixture is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CacheHandler


def main() -> int:
    config = json.loads(sys.argv[1])
    control_fd = int(sys.argv[2])
    control = os.fdopen(control_fd, "w", encoding="utf-8", buffering=1)
    server = None
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        base_handler = _fixture_handler()

        class Handler(base_handler):
            cache_dir = config["cache"]
            ready = False

            def do_GET(self):
                if self.path == "/health":
                    return self._respond(200 if self.ready else 503, {"ready": self.ready})
                return super().do_GET()

            def log_message(self, *args):
                pass

        # Construct the only listener before forbidding new sockets/connects.
        server = HTTPServer(("127.0.0.1", 0), Handler)
        outside = config["outside_probe"]
        with open(outside, "a", encoding="utf-8") as handle:
            handle.write("pre-sandbox-write\n")
        evidence = {"port": server.server_port, "pre_write_succeeded": True,
                    "landlock_abi": None, "outside_write_errno": None,
                    "socket_errno": None, "cache_error": None}
        if config["no_new_privileges"]:
            libc = ctypes.CDLL(None, use_errno=True)
            _require(libc.prctl(38, 1, 0, 0, 0), "PR_SET_NO_NEW_PRIVS")
        if config["read_only"]:
            evidence["landlock_abi"] = _landlock(config["cache"] if config["writable_cache"] else None)
        if config["seccomp"]:
            _seccomp()
        try:
            with open(outside, "a", encoding="utf-8") as handle:
                handle.write("post-sandbox-write\n")
        except OSError as exc:
            evidence["outside_write_errno"] = exc.errno
        try:
            probe = socket.socket()
            probe.close()
        except OSError as exc:
            evidence["socket_errno"] = exc.errno
        try:
            marker = os.path.join(config["cache"], "cache-contract.txt")
            with open(marker, "w", encoding="utf-8") as handle:
                handle.write("kube-repair-cache-contract-v1")
            with open(marker, encoding="utf-8") as handle:
                Handler.ready = handle.read() == "kube-repair-cache-contract-v1"
        except OSError as exc:
            evidence["cache_error"] = "Cache initialization failed: " + str(exc)
        control.write(json.dumps(evidence, sort_keys=True) + "\n")
        control.close()
        server.serve_forever(poll_interval=0.1)
        return 0
    except Exception as exc:
        if not control.closed:
            control.write(json.dumps({"infrastructure_error": type(exc).__name__ + ": " + str(exc)}) + "\n")
            control.close()
        return 1
    finally:
        if server is not None:
            server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
