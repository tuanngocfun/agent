"""A bounded file bridge for decisions made by the current assistant session.

The bridge is not a model server and does not authenticate who wrote a reply.
It preserves the current-session source declaration, not model provenance.
Only the trusted engine can apply a proposal or execute verification.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time
from typing import Any
import uuid

from .providers import ACTION_SCHEMA, SYSTEM_PROMPT, ProviderError, _strict_json_loads, _validate_action


def _plain_json(value: Any) -> None:
    """Reject non-JSON Python values and nonfinite numbers, including 1e400."""
    if value is None or type(value) in (bool, int, str):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _plain_json(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            _plain_json(item)
        return
    raise ValueError("Only finite plain JSON values with string object keys are permitted")


def _no_symlink_components(path: Path) -> None:
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise ValueError("Session exchange paths must not contain symlinks")


class SessionProvider:
    """Request one bounded action from a caller-declared assistant session.

    ``runs_root`` is a trusted host configuration parameter; candidates cannot
    choose it. The default confines exchange files to this project's runs tree.
    A fresh exchange directory should be used for each run. Existing request or
    response filenames are rejected, so stale decisions cannot be replayed.
    """

    def __init__(
        self,
        exchange_dir: str | Path,
        *,
        decision_source: str,
        runs_root: str | Path | None = None,
        timeout: float = 120.0,
        poll_interval: float = 0.1,
        max_context_bytes: int = 100000,
        max_response_bytes: int = 65536,
    ) -> None:
        if decision_source != "current_assistant_session":
            raise ValueError("Explicit decision_source='current_assistant_session' is required")
        for label, value, maximum in (("timeout", timeout, 300), ("poll_interval", poll_interval, 1)):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
                raise ValueError(f"{label} must be finite, positive and at most {maximum}")
        if poll_interval > timeout:
            raise ValueError("poll_interval must not exceed timeout")
        for label, value, maximum in (("max_context_bytes", max_context_bytes, 100000), ("max_response_bytes", max_response_bytes, 65536)):
            if type(value) is not int or not 0 < value <= maximum:
                raise ValueError(f"{label} must be a positive integer at most {maximum}")
        root = Path(runs_root) if runs_root is not None else Path(__file__).resolve().parents[2] / "runs"
        root = Path(os.path.abspath(root))
        directory = Path(exchange_dir)
        if ".." in directory.parts:
            raise ValueError("Parent traversal is not permitted in exchange_dir")
        directory = directory if directory.is_absolute() else root / directory
        directory = Path(os.path.abspath(directory))
        try:
            relative = directory.relative_to(root)
        except ValueError as exc:
            raise ValueError("Session exchange_dir must be under the trusted runs_root") from exc
        if not relative.parts:
            raise ValueError("Use a dedicated exchange directory below runs_root")
        _no_symlink_components(root)
        _no_symlink_components(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        _no_symlink_components(directory)
        if not directory.is_dir():
            raise ValueError("Session exchange_dir must be a directory")
        identity = directory.stat()
        self.exchange_dir = directory
        self._root = root
        self._identity = (identity.st_dev, identity.st_ino)
        self._decision_source = decision_source
        self._timeout = float(timeout)
        self._poll_interval = float(poll_interval)
        self._max_context_bytes = max_context_bytes
        self._max_response_bytes = max_response_bytes
        self._calls = 0
        self._errors: list[dict[str, str]] = []
        self._elapsed_seconds = 0.0

    def metadata(self) -> dict[str, Any]:
        return {
            "name": "session", "provider": "session",
            "kind": "current assistant session through bounded file transport",
            "decision_source": self._decision_source,
            "uses_llm": True,
            "uses_llm_basis": "explicit caller declaration; file replies are not authenticated model outputs",
            "source_declared_only": True, "provenance_authenticated": False,
            "independent_model_benchmark": False,
            "model": None, "model_revision": None,
            "model_revision_available": False, "token_usage": None,
            "calls": self._calls, "elapsed_seconds": round(self._elapsed_seconds, 6),
            "exchange_dir": str(self.exchange_dir),
            "limits": {"timeout_seconds": self._timeout,
                       "max_context_bytes": self._max_context_bytes,
                       "max_response_bytes": self._max_response_bytes},
            "errors": [dict(error) for error in self._errors],
        }

    def _fail(self, code: str, message: str) -> ProviderError:
        self._errors.append({"code": code, "message": message[:1000]})
        return ProviderError(code, message[:1000])

    def _open_exchange(self) -> int:
        _no_symlink_components(self.exchange_dir)
        descriptor = os.open(self.exchange_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != self._identity:
            os.close(descriptor)
            raise ValueError("Session exchange directory was replaced")
        return descriptor

    @staticmethod
    def _exists(name: str, directory_fd: int) -> bool:
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _publish_request(name: str, data: bytes, directory_fd: int) -> None:
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            # A hard link publishes the complete regular file atomically while
            # refusing to replace any existing request (including a symlink).
            os.link(temporary, name, src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd, follow_symlinks=False)
        finally:
            os.unlink(temporary, dir_fd=directory_fd)

    def _read_response(self, name: str, directory_fd: int) -> bytes | None:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory_fd)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise self._fail("unsafe_response", "Session response must be a regular file, never a symlink or pipe")
            raw = stream.read(self._max_response_bytes + 1)
        if len(raw) > self._max_response_bytes:
            raise self._fail("response_limit", "Session response exceeds the configured byte limit")
        return raw

    def next_action(self, context: dict[str, Any]) -> dict[str, Any]:
        try:
            if type(context) is not dict:
                raise ValueError("Context must be a JSON object")
            _plain_json(context)
            canonical = json.dumps(context, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, RecursionError, UnicodeEncodeError) as exc:
            raise self._fail("invalid_context", str(exc)) from exc
        if len(canonical) > self._max_context_bytes:
            raise self._fail("context_limit", "Context exceeds the byte limit; it was not silently truncated")
        self._calls += 1
        sequence = self._calls
        request_id = f"{sequence:04d}-{uuid.uuid4().hex}"
        context_hash = hashlib.sha256(canonical).hexdigest()
        request_name, response_name = f"request-{sequence:04d}.json", f"response-{sequence:04d}.json"
        request = {
            "schema_version": 1, "sequence": sequence, "request_id": request_id,
            "context_hash": context_hash, "decision_source": self._decision_source,
            "system_prompt": SYSTEM_PROMPT, "action_schema": ACTION_SCHEMA,
            "context": context, "response_filename": response_name,
        }
        request_bytes = (json.dumps(request, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        started = time.monotonic()
        directory_fd = None
        try:
            directory_fd = self._open_exchange()
            if self._exists(request_name, directory_fd) or self._exists(response_name, directory_fd):
                raise self._fail("stale_exchange", "Existing request/response filename; use a fresh exchange directory")
            self._publish_request(request_name, request_bytes, directory_fd)
            while True:
                remaining = self._timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise self._fail("deadline", "No matching session response arrived before the deadline")
                raw = self._read_response(response_name, directory_fd)
                if raw is not None:
                    break
                time.sleep(min(self._poll_interval, remaining))
            if time.monotonic() - started > self._timeout:
                raise self._fail("deadline", "Session response exceeded the wall-clock deadline")
            try:
                response = _strict_json_loads(raw.decode("utf-8"))
                _plain_json(response)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
                raise self._fail("invalid_json", "Session returned invalid or nonfinite JSON") from exc
            if type(response) is not dict or set(response) != {"request_id", "context_hash", "action"}:
                raise self._fail("invalid_response", "Session response must contain only request_id, context_hash and action")
            if response["request_id"] != request_id or response["context_hash"] != context_hash:
                raise self._fail("response_mismatch", "Session response does not match this request and context")
            try:
                return _validate_action(response["action"])
            except (TypeError, ValueError) as exc:
                raise self._fail("invalid_action", str(exc)) from exc
        except ProviderError:
            raise
        except (OSError, ValueError) as exc:
            raise self._fail("transport_error", str(exc)) from exc
        finally:
            if directory_fd is not None:
                os.close(directory_fd)
            self._elapsed_seconds += max(0.0, time.monotonic() - started)
