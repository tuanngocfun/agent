"""Trusted orchestration around a replaceable decision provider."""

import copy
import json
import os
import secrets
import time
from pathlib import Path

from .artifacts import canonical, digest, source_fingerprint, write_bundle
from .policy import apply_changes, harden, repair_storage, validate_candidate
from .providers import ProviderError
from .verification import verify


def _progress_provider_metadata(provider):
    try:
        return copy.deepcopy(provider.metadata())
    except Exception as exc:
        return {"metadata_error": f"{type(exc).__name__}: {exc}"}


class _ProgressJournal:
    """Atomic partial evidence in a fresh file chosen by the trusted caller.

    The parent must already exist and is never created or resolved through a
    symlink. Only this journal's own file may be replaced on subsequent writes.
    These snapshots are deliberately outside the exportable review protocol.
    """

    def __init__(self, output):
        self.parent_fd = None
        self.identity = None
        self.last = {}
        self.sequence = 0
        self.fingerprint = source_fingerprint()
        path = Path(os.path.abspath(os.fspath(output)))
        if any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Progress parent must not contain symlinks")
        if not path.parent.is_dir():
            raise ValueError("Progress parent must already be a writable directory")
        self.name = path.name
        self.parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fd = os.open(self.name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600, dir_fd=self.parent_fd)
            try:
                info = os.fstat(fd)
                self.identity = (info.st_dev, info.st_ino)
            finally:
                os.close(fd)
        except FileExistsError as exc:
            self.close()
            raise ValueError("Progress output must be a fresh file") from exc
        except BaseException:
            self.close()
            raise

    def _check_owned_file(self):
        info = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if (info.st_dev, info.st_ino) != self.identity:
            raise ValueError("Progress output changed; refusing to overwrite another file")

    def write(self, state):
        self._check_owned_file()
        snapshot = copy.deepcopy(state)
        snapshot.update({
            "schema_version": 1, "artifact_kind": "partial_agent_progress",
            "status": "in_progress", "accepted": False, "exportable": False,
            "limitation": "Partial diagnostics only; completion and acceptance require the final hash-bound review bundle.",
            "sequence": self.sequence + 1, "source_fingerprint": self.fingerprint,
        })
        snapshot["snapshot_hash"] = digest(snapshot)
        temporary = f".{self.name}.{secrets.token_hex(12)}.tmp"
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=self.parent_fd)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(canonical(snapshot))
                file.flush()
                os.fsync(file.fileno())
            self._check_owned_file()
            os.replace(temporary, self.name, src_dir_fd=self.parent_fd, dst_dir_fd=self.parent_fd)
            info = os.stat(self.name, dir_fd=self.parent_fd, follow_symlinks=False)
            self.identity = (info.st_dev, info.st_ino)
            os.fsync(self.parent_fd)
            self.sequence += 1
            self.last = snapshot
            budget = snapshot.get("budget", {})
            verified = (snapshot.get("verification_manifest_hash") == snapshot.get("manifest_hash")
                        and bool((snapshot.get("verification") or {}).get("passed")))
            print(f"Agent progress: stage={snapshot.get('stage')} "
                  f"actions={budget.get('actions', 0)} tests={budget.get('test_runs', 0)} "
                  f"repairs={budget.get('candidate_repairs', 0)} "
                  f"current_verified_pass={str(verified).lower()}", flush=True)
        finally:
            try:
                os.unlink(temporary, dir_fd=self.parent_fd)
            except FileNotFoundError:
                pass

    def interrupted(self, provider, exc):
        state = dict(self.last)
        state.pop("snapshot_hash", None)
        state.update({"stage": "interrupted", "execution_state": "interrupted",
                      "interrupted_at_stage": self.last.get("stage"),
                      "error": f"{type(exc).__name__}: {exc}",
                      "provider": _progress_provider_metadata(provider)})
        self.write(state)

    def close(self):
        if self.parent_fd is not None:
            os.close(self.parent_fd)
            self.parent_fd = None


def _verification_level(backend):
    return {"simulated": "simulated_fixture_semantics", "docker": "docker_fixture_not_kubernetes",
            "linux": "linux_process_landlock_not_container_or_kubernetes",
            "kubernetes": "kubernetes_fixture_runtime"}[backend]


def _verify(manifest, contract, backend):
    try:
        return verify(copy.deepcopy(manifest), copy.deepcopy(contract), backend)
    except Exception as exc:
        return {
            "backend": backend, "runtime_verified": False,
            "static_pass": False, "behavior_pass": False, "negative_pass": False,
            "passed": False, "infrastructure_error": f"{type(exc).__name__}: {exc}",
            "checks": [], "feedback": ["Runner failed; no successful verification is available."],
        }


def _task(scenario):
    return {
        "objective": "Harden the preserved application: non-root, read-only root filesystem, "
                     "no privilege escalation, drop all capabilities, RuntimeDefault seccomp. "
                     "Preserve startup, computed response, required cache write/read behavior. "
                     "If permitted manifest edits cannot satisfy the task, abstain with evidence.",
        "allowed_changes": "Named app securityContext fields, pod fsGroup, "
                           "one bounded cache-data emptyDir and its approved mount. "
                           "Preserve all other fields including image, env, app, identity and annotations.",
        "allowed_uid": scenario.contract.get("allowed_uid", 10001),
        "allowed_primary_gid": scenario.contract.get("allowed_primary_gid", 10001),
        "allowed_groups": scenario.contract.get("allowed_groups", [10001, 2000]),
        "execution_kind": scenario.contract.get("execution_kind", "kubernetes-manifest-fixture"),
        "allowed_mount_paths": scenario.contract["allowed_mount_paths"],
        "allowed_cache_paths": scenario.contract["allowed_cache_paths"],
        "allowed_security_fields": ["runAsNonRoot", "runAsUser", "runAsGroup", "readOnlyRootFilesystem",
                                    "allowPrivilegeEscalation", "capabilities", "seccompProfile"],
        "required_security_controls": {
            "runAsNonRoot": True, "readOnlyRootFilesystem": True,
            "runAsUser": scenario.contract.get("allowed_uid", 10001),
            "runAsGroup": scenario.contract.get("allowed_primary_gid", 10001),
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "storage_policy": {"volume": {"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}},
                           "mount_fields": ["name", "mountPath"], "maximum_volumes": 1,
                           "maximum_mounts": 1, "pod_security_fields": ["fsGroup"]},
        "evidence_sources": ["image", "app", "repository"],
    }


def run_task(scenario, provider, output, backend="simulated", max_actions=12, max_repairs=3,
             progress_output=None):
    if not (1 <= max_actions <= 30 and 1 <= max_repairs <= 5):
        raise ValueError("Budgets must be 1..30 actions and 1..5 candidate repairs")
    journal = _ProgressJournal(progress_output) if progress_output is not None else None
    try:
        return _run_task(scenario, provider, output, backend, max_actions, max_repairs, journal)
    except BaseException as exc:
        if journal is not None:
            try:
                journal.interrupted(provider, exc)
            except (OSError, ValueError):
                # Preserve the original error; never bypass an ownership failure.
                pass
        raise
    finally:
        if journal is not None:
            journal.close()


def _run_task(scenario, provider, output, backend, max_actions, max_repairs, journal):
    started = time.monotonic()
    current = copy.deepcopy(scenario.base)
    result, verification_hash = None, None
    observations, trace = [], []
    evidence, repairs, rejected, tests, actions = {}, 0, 0, 0, 0
    status, reason = "budget_exhausted", "Action budget exhausted"

    def progress(stage, execution_state="running", **extra):
        if journal is None:
            return
        journal.write({
            "scenario": scenario.id, "backend": backend, "stage": stage,
            "execution_state": execution_state, "engine_status": status, "reason": reason,
            "base_hash": digest(scenario.base), "contract_hash": digest(scenario.contract),
            "manifest": current, "manifest_hash": digest(current),
            "verification": result, "verification_manifest_hash": verification_hash,
            "observations": observations, "evidence": evidence, "trace": trace,
            "provider": _progress_provider_metadata(provider),
            "budget": {"max_actions": max_actions, "max_repairs": max_repairs,
                       "actions": actions, "candidate_repairs": repairs, "test_runs": tests},
            "rejected_actions": rejected, "executed_unauthorized_effects": 0,
            "seconds": round(time.monotonic() - started, 6), **extra,
        })

    progress("before_initial_verification")
    result = _verify(current, scenario.contract, backend)
    verification_hash = digest(current)
    observations = [dict(result, trust="trusted_verifier")]
    trace = [{"event": "initial_verification", "manifest_hash": digest(current), "result": result}]
    tests = 1
    progress("initial_verification")
    if result.get("infrastructure_error"):
        status, reason = "runner_error", result["infrastructure_error"]
    else:
        for step in range(max_actions):
            context = {
                "task": _task(scenario), "manifest": copy.deepcopy(current),
                "observations": copy.deepcopy(observations), "evidence": copy.deepcopy(evidence),
                "remaining": {"actions": max_actions - step, "repairs": max_repairs - repairs},
                "history": copy.deepcopy(trace),
            }
            actions += 1
            progress("before_model_call", step=step + 1)
            try:
                action = provider.next_action(context)
                if not isinstance(action, dict) or not isinstance(action.get("reason"), str):
                    raise ValueError("Action must be an object with a textual reason")
                kind = action.get("action")
                fields = {
                    "inspect": {"action", "source", "reason"},
                    "propose": {"action", "changes" if "changes" in action else "manifest", "reason"},
                    "test": {"action", "reason"}, "finish": {"action", "reason"},
                    "abstain": {"action", "reason"},
                }
                if not isinstance(kind, str) or kind not in fields or set(action) != fields[kind]:
                    raise ValueError("Action shape is outside the bounded tool protocol")
                if len(action["reason"]) > 4096:
                    raise ValueError("Action reason exceeds limit")
                if kind == "inspect" and not isinstance(action["source"], str):
                    raise ValueError("Evidence source must be a string")
                if len(json.dumps(action, allow_nan=False).encode()) > 65536:
                    raise ValueError("Action exceeds serialized size limit")
            except Exception as exc:
                if isinstance(exc, ProviderError) and exc.code == "invalid_action":
                    # The adapter rejected the output before returning an action.
                    # Supply its bounded validation error, never reinterpret the
                    # raw response or invent a corrected action on its behalf.
                    detail = "".join(character if character.isprintable() else " "
                                     for character in f"{type(exc).__name__}: {exc}")[:1200]
                    rejected += 1
                    provider_call = _progress_provider_metadata(provider).get("calls")
                    trace.append({"event": "rejected_provider_output", "step": step + 1,
                                  "provider_call": provider_call if type(provider_call) is int else None,
                                  "detail": detail})
                    observations.append({"trust": "trusted_protocol", "passed": False,
                                         "protocol_errors": [detail], "feedback": [detail]})
                    progress("rejected_provider_output", step=step + 1, protocol_error=detail)
                    continue
                status, reason = "provider_error", f"{type(exc).__name__}: {exc}"
                trace.append({"event": "provider_error", "detail": reason})
                progress("provider_error", execution_state="provider_error", error=reason)
                break
            # Provider cannot mutate the trusted manifest, tests or trace through context.
            kind = action.get("action")
            trace.append({"event": "decision", "step": step + 1, "action": copy.deepcopy(action)})
            progress("model_decision", step=step + 1)
            if kind == "inspect":
                source = action.get("source")
                if source not in scenario.evidence:
                    rejected += 1
                    trace.append({"event": "rejected_tool", "error": "Evidence source is not permitted"})
                    progress("rejected_tool")
                    continue
                evidence[source] = {
                    "trust": "untrusted_repository" if source == "repository" else "approved_metadata",
                    "content": scenario.evidence[source],
                }
                trace.append({"event": "evidence", "source": source, "record": evidence[source]})
                progress("evidence_inspected")
            elif kind == "propose":
                if repairs >= max_repairs:
                    status, reason = "budget_exhausted", "Candidate repair budget exhausted"
                    break
                repairs += 1
                try:
                    candidate = apply_changes(current, action["changes"]) if "changes" in action else action.get("manifest")
                except (ValueError, TypeError, KeyError) as exc:
                    rejected += 1
                    errors = [f"Invalid change proposal: {exc}"]
                    trace.append({"event": "rejected_proposal", "errors": errors})
                    observations.append({"trust": "trusted_policy", "passed": False,
                                         "policy_errors": errors, "feedback": errors})
                    progress("rejected_proposal")
                    continue
                errors = validate_candidate(scenario.base, candidate, scenario.contract)
                if errors:
                    rejected += 1
                    trace.append({"event": "rejected_proposal", "errors": errors})
                    # Make rejection trusted feedback without overwriting the current test.
                    observations.append({"trust": "trusted_policy", "passed": False,
                                         "policy_errors": errors, "feedback": errors})
                    progress("rejected_proposal")
                    continue
                current = copy.deepcopy(candidate)
                progress("before_candidate_verification")
                result = _verify(current, scenario.contract, backend)
                verification_hash = digest(current)
                tests += 1
                observations.append(dict(result, trust="trusted_verifier"))
                trace.append({"event": "candidate_verification", "candidate": repairs,
                              "manifest_hash": digest(current), "result": result})
                progress("candidate_verification")
                if result.get("infrastructure_error"):
                    status, reason = "runner_error", result["infrastructure_error"]
                    break
            elif kind == "test":
                progress("before_requested_verification")
                result = _verify(current, scenario.contract, backend)
                verification_hash = digest(current)
                tests += 1
                observations.append(dict(result, trust="trusted_verifier"))
                trace.append({"event": "requested_verification", "manifest_hash": digest(current), "result": result})
                progress("requested_verification")
                if result.get("infrastructure_error"):
                    status, reason = "runner_error", result["infrastructure_error"]
                    break
            elif kind == "finish":
                reason = action["reason"]
                status = ("unchanged" if current == scenario.base else "repaired") if result["passed"] else "failed"
                break
            elif kind == "abstain":
                status, reason = "abstained", action["reason"]
                break
            else:
                rejected += 1
                trace.append({"event": "rejected_tool", "error": "Unknown action; no effect was executed"})
                progress("rejected_tool")
        else:
            status, reason = "budget_exhausted", "Action budget exhausted"
    progress("agent_loop_finished", execution_state="loop_finished")
    report = {
        "schema_version": 1, "scenario": scenario.id,
        "corpus": "synthetic_teaching_fixtures_not_a_held_out_benchmark",
        "backend": backend, "runtime_verified": bool(result.get("runtime_verified")),
        "verification_level": _verification_level(backend),
        "status": status, "reason": reason,
        "accepted": status in ("repaired", "unchanged") and bool(result["passed"]),
        "appropriate_abstention": status == "abstained" and scenario.expected == "abstain",
        "unnecessary_change": scenario.expected == "unchanged" and current != scenario.base,
        "provider": provider.metadata(), "verification": result,
        "budget": {"max_actions": max_actions, "max_repairs": max_repairs,
                   "actions": actions, "candidate_repairs": repairs, "test_runs": tests},
        "rejected_actions": rejected, "executed_unauthorized_effects": 0,
        "seconds": round(time.monotonic() - started, 6),
    }
    # Keep failed candidates in the trace; exportable manifest always reflects accepted result.
    final = current if report["accepted"] else scenario.base
    binding = write_bundle(output, scenario.base, final, report, trace, scenario.contract)
    progress("final_bundle_written", execution_state="completed",
             final_bundle_review_hash=binding["review_hash"])
    return report, binding


def run_baseline(scenario, strategy, output, backend="simulated"):
    if strategy not in ("noop", "naive", "template", "known-good"):
        raise ValueError("Unknown baseline")
    current = copy.deepcopy(scenario.base)
    if strategy != "noop":
        current = harden(current, scenario.contract.get("allowed_uid", 10001), scenario.contract.get("allowed_primary_gid", 10001))
    if strategy in ("template", "known-good"):
        storage = dict(scenario.contract)
        if strategy == "template":
            storage["volume_gid"] = None  # fixed generic storage group, not oracle-aware
        current = repair_storage(current, storage)
    errors = validate_candidate(scenario.base, current, scenario.contract)
    result = _verify(current, scenario.contract, backend) if not errors else {
        "backend": backend, "runtime_verified": False, "passed": False,
        "static_pass": False, "behavior_pass": False, "negative_pass": False,
        "checks": [], "feedback": errors,
    }
    appropriate = strategy == "known-good" and scenario.expected == "abstain"
    if result.get("infrastructure_error"):
        status = "runner_error"
    elif appropriate:
        status = "abstained"
    elif result["passed"]:
        status = "unchanged" if current == scenario.base else "repaired"
    else:
        status = "failed"
    report = {
        "schema_version": 1, "scenario": scenario.id,
        "corpus": "synthetic_teaching_fixtures_not_a_held_out_benchmark",
        "status": status, "reason": "Known-good is an oracle control, not an agent baseline" if strategy == "known-good" else strategy,
        "accepted": result["passed"] and status in ("repaired", "unchanged"),
        "backend": backend, "runtime_verified": bool(result.get("runtime_verified")),
        "verification_level": _verification_level(backend),
        "provider": {"name": f"baseline:{strategy}", "uses_llm": False},
        "verification": result, "appropriate_abstention": status == "abstained" and appropriate,
        "unnecessary_change": scenario.expected == "unchanged" and current != scenario.base,
        "rejected_actions": len(errors), "executed_unauthorized_effects": 0,
        "budget": {"candidate_repairs": int(current != scenario.base), "test_runs": int(not errors)},
    }
    trace = [{"event": "baseline_verification", "strategy": strategy, "result": result, "errors": errors}]
    binding = write_bundle(output, scenario.base, current if report["accepted"] else scenario.base,
                           report, trace, scenario.contract)
    return report, binding
