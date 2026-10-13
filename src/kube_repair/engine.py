"""Trusted orchestration around a replaceable decision provider."""

import copy
import json
import time

from .artifacts import digest, write_bundle
from .policy import apply_changes, harden, repair_storage, validate_candidate
from .verification import verify


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
        "storage_policy": {"volume": {"name": "cache-data", "emptyDir": {"sizeLimit": "16Mi"}},
                           "mount_fields": ["name", "mountPath"], "maximum_volumes": 1,
                           "maximum_mounts": 1, "pod_security_fields": ["fsGroup"]},
        "evidence_sources": ["image", "app", "repository"],
    }


def run_task(scenario, provider, output, backend="simulated", max_actions=12, max_repairs=3):
    if not (1 <= max_actions <= 30 and 1 <= max_repairs <= 5):
        raise ValueError("Budgets must be 1..30 actions and 1..5 candidate repairs")
    started = time.monotonic()
    current = copy.deepcopy(scenario.base)
    result = _verify(current, scenario.contract, backend)
    observations = [dict(result, trust="trusted_verifier")]
    trace = [{"event": "initial_verification", "manifest_hash": digest(current), "result": result}]
    evidence, repairs, rejected, tests, actions = {}, 0, 0, 1, 0
    status, reason = "budget_exhausted", "Action budget exhausted"
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
                status, reason = "provider_error", f"{type(exc).__name__}: {exc}"
                trace.append({"event": "provider_error", "detail": reason})
                break
            # Provider cannot mutate the trusted manifest, tests or trace through context.
            kind = action.get("action")
            trace.append({"event": "decision", "step": step + 1, "action": copy.deepcopy(action)})
            if kind == "inspect":
                source = action.get("source")
                if source not in scenario.evidence:
                    rejected += 1
                    trace.append({"event": "rejected_tool", "error": "Evidence source is not permitted"})
                    continue
                evidence[source] = {
                    "trust": "untrusted_repository" if source == "repository" else "approved_metadata",
                    "content": scenario.evidence[source],
                }
                trace.append({"event": "evidence", "source": source, "record": evidence[source]})
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
                    continue
                errors = validate_candidate(scenario.base, candidate, scenario.contract)
                if errors:
                    rejected += 1
                    trace.append({"event": "rejected_proposal", "errors": errors})
                    # Make rejection trusted feedback without overwriting the current test.
                    observations.append({"trust": "trusted_policy", "passed": False,
                                         "policy_errors": errors, "feedback": errors})
                    continue
                current = copy.deepcopy(candidate)
                result = _verify(current, scenario.contract, backend)
                tests += 1
                observations.append(dict(result, trust="trusted_verifier"))
                trace.append({"event": "candidate_verification", "candidate": repairs,
                              "manifest_hash": digest(current), "result": result})
                if result.get("infrastructure_error"):
                    status, reason = "runner_error", result["infrastructure_error"]
                    break
            elif kind == "test":
                result = _verify(current, scenario.contract, backend)
                tests += 1
                observations.append(dict(result, trust="trusted_verifier"))
                trace.append({"event": "requested_verification", "manifest_hash": digest(current), "result": result})
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
        else:
            status, reason = "budget_exhausted", "Action budget exhausted"
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
