"""Evidence-bound, case-aware reporting for registered Kubernetes experiments.

This module performs no inference, cluster operations or network calls. A report
always retains registered missing cells and authentic failed attempts. Repeated
trials are descriptive; Wilson intervals use distinct cases, never trial rows.
"""
from __future__ import annotations

import csv
import hashlib
import html
import itertools
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .artifacts import canonical, load_bundle
from .providers import _validate_action


FINGERPRINTS = ("plan_id", "suite_fingerprint", "evaluator_fingerprint",
                "source_fingerprint", "settings_fingerprint")
OUTCOMES = {"repaired", "unchanged", "abstained", "behavior_failure",
            "security_failure", "protocol_failure", "policy_failure",
            "provider_failure", "infrastructure_failure", "budget_exhausted",
            "invalid_evidence"}
COUNTS = ("inspections", "repairs", "tests", "model_calls", "prompt_tokens",
          "output_tokens", "total_tokens", "reserved_tokens", "protocol_rejections",
          "policy_rejections")
TIMINGS = ("wall_seconds", "inference_seconds", "generation_seconds")
CHECKS = ("behavior", "static", "security", "cleanup")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")


def _read_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
        raise ValueError(f"Not a bounded regular JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {x}")))


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate a frozen registry. Fingerprints are values, not inferred defaults."""
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("Expected benchmark plan schema_version 1")
    for key in FINGERPRINTS:
        if not isinstance(plan.get(key), str) or not plan[key]:
            raise ValueError(f"Plan requires {key}")
    _integer(plan.get("repetitions"), "repetitions", 1)
    if plan["repetitions"] > 100:
        raise ValueError("Repetitions exceeds bounded reporting limit")
    for collection, identity in (("models", "model_id"), ("methods", "method_id"), ("cases", "case_id")):
        rows = plan.get(collection)
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"Plan requires nonempty {collection}")
        seen = set()
        for row in rows:
            key = row.get(identity) if isinstance(row, dict) else None
            if not isinstance(key, str) or not _ID.fullmatch(key) or key in seen:
                raise ValueError(f"Invalid or duplicate {identity}: {key}")
            seen.add(key)
    for model in plan["models"]:
        if not isinstance(model.get("pin"), dict) or not model["pin"]:
            raise ValueError("Every model requires its frozen pin metadata")
    for method in plan["methods"]:
        _integer(method.get("token_ceiling"), "token_ceiling", 1)
        _integer(method.get("max_actions"), "max_actions", 1)
        if not isinstance(method.get("guided_schema_fingerprint"), str) or not method["guided_schema_fingerprint"]:
            raise ValueError("Every method requires guided_schema_fingerprint")
    for case in plan["cases"]:
        if case.get("expected_outcome") not in ("repair", "unchanged", "abstain"):
            raise ValueError("Case expected_outcome must be repair, unchanged or abstain")
        if not isinstance(case.get("split"), str) or not _ID.fullmatch(case["split"]):
            raise ValueError("Every case requires a split")
    return plan


def expected_cells(plan: dict[str, Any]) -> list[tuple[str, str, str, int]]:
    validate_plan(plan)
    return list(itertools.product(
        [m["model_id"] for m in plan["models"]],
        [m["method_id"] for m in plan["methods"]],
        [c["case_id"] for c in plan["cases"]],
        range(plan["repetitions"])))


def wilson_interval(successes: int, cases: int) -> dict[str, Any]:
    """Wilson 95% interval, with explicit counts and no zero-denominator fiction."""
    _integer(successes, "successes")
    _integer(cases, "cases")
    if successes > cases:
        raise ValueError("Success count exceeds case denominator")
    if not cases:
        return {"successes": 0, "cases": 0, "rate": None, "low": None, "high": None}
    z = 1.959963984540054
    rate = successes / cases
    denominator = 1 + z * z / cases
    center = (rate + z * z / (2 * cases)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / cases + z * z / (4 * cases * cases)) / denominator
    return {"successes": successes, "cases": cases, "rate": rate,
            "low": max(0.0, center - half), "high": min(1.0, center + half)}


def _evidence_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Evidence paths must be relative to the evidence root")
    relative = Path(value)
    if ".." in relative.parts:
        raise ValueError("Evidence path escapes the registered root")
    path = root / relative
    if any(p.is_symlink() for p in [path, *path.parents] if p == root or root in p.parents):
        raise ValueError("Evidence paths must not contain symlinks")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Evidence path escapes the registered root")
    return path


def _same_nullable(given: Any, observed: Any, name: str) -> None:
    if given != observed:
        raise ValueError(f"Record {name} differs from bound execution evidence")


def _verify_raw_responses(provider: dict[str, Any], trace: list[dict[str, Any]]) -> bool:
    """Check exact recorded bytes and raw model actions; audit replays their effects."""
    observed = False
    decisions = [row["action"] for row in trace if row.get("event") == "decision"]
    returned = []
    for call in provider.get("inference_calls", []):
        raw = call.get("raw_server_response")
        if raw is None:
            continue
        if not isinstance(raw, str) or call.get("response_truncated"):
            raise ValueError("Model response is incomplete")
        if hashlib.sha256(raw.encode()).hexdigest() != call.get("response_sha256"):
            raise ValueError("Raw model response hash mismatch")
        try:
            server = json.loads(raw)
        except json.JSONDecodeError:
            if call.get("status") == "action_returned":
                raise ValueError("Returned action has no valid model-server JSON")
            continue
        if not isinstance(server, dict):
            continue
        observed = observed or (type(server.get("eval_count")) is int and server["eval_count"] > 0)
        if server.get("model") and server.get("model") not in (provider.get("model"), provider.get("model_reported")):
            raise ValueError("Raw response model identity mismatch")
        usage = call.get("reported_usage") or {}
        if usage and (usage.get("prompt_tokens") != server.get("prompt_eval_count") or usage.get("completion_tokens") != server.get("eval_count")):
            raise ValueError("Raw response token counts mismatch")
        if call.get("status") == "action_returned":
            action = _validate_action(json.loads(server["message"]["content"]))
            if action != call.get("action"):
                raise ValueError("Stored action differs from raw model output")
            returned.append(action)
    if returned != decisions:
        raise ValueError("Model-origin actions differ from engine decisions")
    return observed


def verify_record_evidence(record: dict[str, Any], root: Path, method: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recheck a worker audit, bundle inventory, exact raw model output and metrics.

    The audit is trusted-worker evidence, not a signature or remote attestation.
    Missing failed-attempt evidence remains distinguishable from task success.
    """
    evidence = record.get("evidence") or {}
    if evidence.get("validated") is not True:
        return {"verified": False, "model_origin_verified": False,
                "error": "Worker supplied no completed evidence audit"}
    try:
        bundle = _evidence_path(root, evidence.get("bundle_path"))
        audit_path = _evidence_path(root, evidence.get("audit_path"))
        binding_bytes = (bundle / "binding.json").read_bytes()
        if hashlib.sha256(binding_bytes).hexdigest() != evidence.get("bundle_sha256"):
            raise ValueError("Bundle binding file hash mismatch")
        if hashlib.sha256(audit_path.read_bytes()).hexdigest() != evidence.get("audit_sha256"):
            raise ValueError("Audit file hash mismatch")
        binding, contents = load_bundle(bundle)
        audit = _read_json(audit_path)
        if audit.get("status") != "passed" or audit.get("bundle_review_hash") != binding["review_hash"]:
            raise ValueError("Audit is not bound to this review bundle")
        pin_documents = {}
        for name in ("model_pin", "image_pins"):
            if evidence.get(name + "_path") is not None:
                pin_path = _evidence_path(root, evidence[name + "_path"])
                if hashlib.sha256(pin_path.read_bytes()).hexdigest() != evidence.get(name + "_sha256"):
                    raise ValueError(f"{name} evidence file hash mismatch")
                pin_documents[name] = _read_json(pin_path)
        if binding["source_fingerprint"] != record["source_fingerprint"]:
            raise ValueError("Bundle source differs from comparison source")
        report = json.loads(contents["report.json"])
        trace = json.loads(contents["trace.json"])
        if report.get("backend") != "kubernetes":
            raise ValueError("Benchmark evidence did not execute Kubernetes")
        provider = report.get("provider") or {}
        if provider.get("uses_llm") is not True or provider.get("is_language_model") is not True:
            raise ValueError("Model comparison row uses a scripted provider")
        model = (record.get("provenance") or {}).get("model_pin") or {}
        model_values = dict(model.get("pin") or {})
        model_values.update(model)
        if model_values.get("tag") is not None and provider.get("model") != model_values["tag"]:
            raise ValueError("Actual provider tag differs from registered model")
        revision = provider.get("model_revision")
        if revision is not None and model_values.get("manifest_digest") is not None:
            if revision.removeprefix("sha256:") != model_values["manifest_digest"].removeprefix("sha256:"):
                raise ValueError("Actual model revision differs from registered pin")
        if model_values.get("weight_blob_digest") is not None:
            pin = pin_documents.get("model_pin")
            if not pin or pin.get("approved") != model or pin.get("weight_sha256_verified") is not True or pin.get("weight_bytes_verified") is not True or pin.get("cpu_only") is not True:
                raise ValueError("Actual downloaded model weight and CPU evidence unavailable")
            if "image_pins" not in pin_documents:
                raise ValueError("Actual fixture image pin evidence unavailable")
        if method is not None:
            if report.get("budget", {}).get("max_actions") != method["max_actions"]:
                raise ValueError("Actual action budget differs from registered method")
            if provider.get("token_usage", {}).get("max_total_tokens") != method["token_ceiling"]:
                raise ValueError("Actual token ceiling differs from registered method")
            if provider.get("decoding_mode") != "compact-schema":
                raise ValueError("Actual decoding method differs from registered guided schema")
        origin = _verify_raw_responses(provider, trace)
        if audit.get("model_origin_verified") is not origin or evidence.get("model_origin_verified") is not origin:
            raise ValueError("Model-origin claim differs from actual recorded inference")
        verification = report.get("verification") or {}
        metrics = record.get("metrics") or {}
        budget = report.get("budget") or {}
        usage = provider.get("token_usage") or {}
        counts_complete = usage.get("counts_complete") is True and usage.get("counts_available_calls", 0) > 0
        observed_metrics = {
            "inspections": sum(row.get("event") == "evidence" for row in trace),
            "repairs": budget.get("candidate_repairs"), "tests": budget.get("test_runs"),
            "model_calls": provider.get("calls"),
            "prompt_tokens": usage.get("reported_prompt_tokens") if counts_complete else None,
            "output_tokens": usage.get("reported_completion_tokens") if counts_complete else None,
            "total_tokens": usage.get("reported_total_tokens") if counts_complete else None,
            "reserved_tokens": usage.get("reserved_token_upper_bound"),
            "wall_seconds": report.get("seconds"),
            "inference_seconds": provider.get("elapsed_seconds"),
            "protocol_rejections": sum(row.get("event") == "rejected_provider_output" for row in trace),
            "policy_rejections": sum(row.get("event") == "rejected_proposal" for row in trace),
        }
        durations = []
        for call in provider.get("inference_calls", []):
            try:
                server = json.loads(call.get("raw_server_response") or "null")
                value = server.get("eval_duration") if isinstance(server, dict) else None
            except json.JSONDecodeError:
                value = None
            durations.append(value)
        generation_available = counts_complete and bool(durations) and all(type(value) is int and value >= 0 for value in durations)
        observed_metrics["generation_seconds"] = sum(durations) / 1_000_000_000 if generation_available else None
        for name, observed_value in observed_metrics.items():
            if name in metrics:
                _same_nullable(metrics[name], observed_value, name)
        checks = record.get("checks") or {}
        for name, report_key in (("behavior", "behavior_pass"), ("static", "static_pass"), ("security", "negative_pass")):
            if name in checks:
                _same_nullable(checks[name], verification.get(report_key), f"checks.{name}")
        verifications = [row["result"] for row in trace if row.get("event") in
                         ("initial_verification", "candidate_verification", "requested_verification")]
        namespace_cleanup = bool(verifications) and all(
            any(check.get("name") == "namespace-cleanup" and check.get("passed") is True
                for check in item.get("checks", [])) for item in verifications)
        if audit.get("namespace_cleanup_verified") is not namespace_cleanup:
            raise ValueError("Namespace cleanup audit differs from execution trace")
        worker_cleanup = (record.get("provenance") or {}).get("worker_cleanup") or {}
        resources_clean = (all(name in worker_cleanup for name in
                               ("model_container_removed", "cluster_removed", "kubeconfig_removed"))
                           and all(value is True for value in worker_cleanup.values()))
        if audit.get("worker_cleanup") is not None and audit["worker_cleanup"] != worker_cleanup:
            raise ValueError("Cleanup provenance differs from bound worker audit")
        if audit.get("worker_cleanup_verified") is not resources_clean:
            raise ValueError("Worker cleanup audit differs from resource evidence")
        if "cleanup" in checks:
            _same_nullable(checks["cleanup"], namespace_cleanup and resources_clean, "checks.cleanup")
        for name, report_key in (("accepted", "accepted"), ("appropriate_abstention", "appropriate_abstention"),
                                 ("unnecessary_change", "unnecessary_change"), ("rejected_actions", "rejected_actions"),
                                 ("unauthorized_effects", "executed_unauthorized_effects")):
            if name in record:
                _same_nullable(record[name], report.get(report_key), name)
        if record["outcome"] in ("repaired", "unchanged", "abstained") and report.get("status") != record["outcome"]:
            raise ValueError("Task outcome differs from bound report")
        if record["outcome"] in ("repaired", "unchanged"):
            if not origin or report.get("accepted") is not True or verification.get("passed") is not True or verification.get("runtime_verified") is not True or verification.get("kubernetes_execution_observed") is not True:
                raise ValueError("Accepted outcome lacks model-origin runtime verification")
            if checks.get("cleanup") is not True:
                raise ValueError("Accepted outcome lacks successful cleanup evidence")
            base = json.loads(contents["base.json"])
            candidate = json.loads(contents["candidate.json"])
            if (record["outcome"] == "repaired") != (base != candidate):
                raise ValueError("Changed/unchanged outcome differs from actual candidate")
        if record["outcome"] == "abstained" and not origin:
            raise ValueError("Abstention has no model-origin decision")
        return {"verified": True, "model_origin_verified": origin, "error": None,
                "review_hash": binding["review_hash"], "audit_sha256": evidence["audit_sha256"]}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return {"verified": False, "model_origin_verified": False,
                "error": f"{type(exc).__name__}: {exc}"}


def _metric_summary(values: list[int | float | None]) -> dict[str, Any]:
    observed = [v for v in values if v is not None]
    return {"available": len(observed), "missing": len(values) - len(observed),
            "sum": sum(observed) if observed else None,
            "mean": statistics.mean(observed) if observed else None,
            "median": statistics.median(observed) if observed else None,
            "minimum": min(observed) if observed else None,
            "maximum": max(observed) if observed else None}


def _validate_record_shape(record: dict[str, Any], plan: dict[str, Any]) -> tuple[str, str, str, int]:
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("Trial record requires schema_version 1")
    for key in FINGERPRINTS:
        if record.get(key) != plan[key]:
            raise ValueError(f"Incompatible comparison: {key} differs from frozen plan")
    key = (record.get("model_id"), record.get("method_id"), record.get("case_id"), record.get("repetition"))
    if record.get("outcome") not in OUTCOMES:
        raise ValueError(f"Unknown outcome: {record.get('outcome')}")
    _integer(record.get("repetition"), "repetition")
    metrics = record.get("metrics") or {}
    for name in COUNTS:
        if metrics.get(name) is not None:
            _integer(metrics[name], name)
    for name in TIMINGS:
        value = metrics.get(name)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
            raise ValueError(f"Invalid finite timing: {name}")
    if all(metrics.get(name) is not None for name in ("prompt_tokens", "output_tokens", "total_tokens")):
        if metrics["prompt_tokens"] + metrics["output_tokens"] != metrics["total_tokens"]:
            raise ValueError("Actual token total does not reconcile")
    for name in CHECKS:
        if (record.get("checks") or {}).get(name) is not None and type(record["checks"][name]) is not bool:
            raise ValueError(f"Check {name} must be true, false or null")
    return key


def build_summary(plan: dict[str, Any], records: list[dict[str, Any]], evidence_root: Path) -> dict[str, Any]:
    """Aggregate only one comparable registered experiment; retain every cell."""
    cells = expected_cells(plan)
    allowed = set(cells)
    cases = {row["case_id"]: row for row in plan["cases"]}
    by_key = {}
    for record in records:
        key = _validate_record_shape(record, plan)
        if key not in allowed:
            raise ValueError(f"Unregistered trial cell: {key}")
        if key in by_key:
            raise ValueError(f"Duplicate trial cell: {key}")
        if record.get("expected_outcome") != cases[key[2]]["expected_outcome"]:
            raise ValueError("Trial expected outcome differs from registered case")
        model = next(row for row in plan["models"] if row["model_id"] == key[0])
        if record.get("provenance", {}).get("model_pin") != model:
            raise ValueError("Trial model pin differs from the registered model")
        by_key[key] = record
    rows = []
    for model, method, case, repetition in cells:
        key = (model, method, case, repetition)
        record = by_key.get(key)
        row = {"model_id": model, "method_id": method, "case_id": case, "repetition": repetition,
               "split": cases[case]["split"], "expected_outcome": cases[case]["expected_outcome"]}
        if record is None:
            row.update({"outcome": "missing", "observed_outcome": None, "evidence_verified": False,
                        "model_origin_verified": False, "evidence_error": "Registered trial record missing",
                        "task_correct": False, "metrics": {}, "checks": {}, "failure_reason": "Not observed",
                        "provenance": {}})
        else:
            method_definition = next(item for item in plan["methods"] if item["method_id"] == method)
            verified = verify_record_evidence(record, evidence_root, method_definition)
            # Infrastructure/provider failures remain visible even if execution
            # stopped before there was a bundle. They never count as success.
            effective = record["outcome"] if verified["verified"] or record["outcome"] in ("infrastructure_failure", "provider_failure") else "invalid_evidence"
            expected_status = {"repair": "repaired", "unchanged": "unchanged", "abstain": "abstained"}[row["expected_outcome"]]
            correct = verified["verified"] and verified["model_origin_verified"] and effective == expected_status
            if effective == "abstained":
                correct = correct and record.get("appropriate_abstention") is True
            if effective in ("repaired", "unchanged"):
                correct = correct and record.get("accepted") is True and record.get("unauthorized_effects", 0) == 0
            if effective == "unchanged":
                correct = correct and record.get("unnecessary_change") is False
            row.update({"outcome": effective, "observed_outcome": record["outcome"],
                        "evidence_verified": verified["verified"], "model_origin_verified": verified["model_origin_verified"],
                        "evidence_error": verified["error"], "task_correct": bool(correct),
                        "metrics": record.get("metrics") or {}, "checks": record.get("checks") or {},
                        "failure_reason": record.get("failure_reason"), "provenance": record.get("provenance") or {},
                        "evidence": record.get("evidence") or {}})
        rows.append(row)
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["model_id"], row["method_id"])].append(row)
    groups = []
    case_rows = []
    for (model, method), trials in grouped.items():
        per_case = defaultdict(list)
        for row in trials:
            per_case[row["case_id"]].append(row)
        case_results = []
        for case, repeats in per_case.items():
            result = {"model_id": model, "method_id": method, "case_id": case,
                      "split": cases[case]["split"], "expected_outcome": cases[case]["expected_outcome"],
                      "registered_repetitions": plan["repetitions"],
                      "observed_repetitions": sum(r["outcome"] != "missing" for r in repeats),
                      "verified_repetitions": sum(r["evidence_verified"] for r in repeats),
                      "correct_repetitions": sum(r["task_correct"] for r in repeats),
                      "all_repetitions_correct": all(r["task_correct"] for r in repeats),
                      "complete_verified_case": all(r["evidence_verified"] for r in repeats)}
            case_results.append(result)
            case_rows.append(result)
        repair_cases = [row for row in case_results if row["expected_outcome"] == "repair"]
        unchanged_cases = [row for row in case_results if row["expected_outcome"] == "unchanged"]
        abstain_cases = [row for row in case_results if row["expected_outcome"] == "abstain"]
        group = {"model_id": model, "method_id": method, "expected_trials": len(trials),
                 "observed_trials": sum(row["outcome"] != "missing" for row in trials),
                 "verified_trials": sum(row["evidence_verified"] for row in trials),
                 "model_origin_trials": sum(row["model_origin_verified"] for row in trials),
                 "task_correct_trials": sum(row["task_correct"] for row in trials),
                 "outcomes": dict(sorted(Counter(row["outcome"] for row in trials).items())),
                 "case_task_correct": wilson_interval(sum(row["all_repetitions_correct"] for row in case_results), len(case_results)),
                 "case_repair_success": wilson_interval(sum(row["all_repetitions_correct"] for row in repair_cases), len(repair_cases)),
                 "case_unchanged_success": wilson_interval(sum(row["all_repetitions_correct"] for row in unchanged_cases), len(unchanged_cases)),
                 "case_abstention_success": wilson_interval(sum(row["all_repetitions_correct"] for row in abstain_cases), len(abstain_cases)),
                 "complete_verified_cases": sum(row["complete_verified_case"] for row in case_results),
                 "metrics": {}, "checks": {}, "failure_reasons": {}}
        for metric in COUNTS + TIMINGS:
            # Rejecting unverifiable success cannot leave its unverified metrics
            # as trusted measurements. Missing cells remain in availability counts.
            group["metrics"][metric] = _metric_summary([row["metrics"].get(metric) if row["evidence_verified"] else None for row in trials])
        for name in CHECKS:
            values = [row["checks"].get(name) if row["evidence_verified"] else None for row in trials]
            group["checks"][name] = {"passed": sum(v is True for v in values), "failed": sum(v is False for v in values), "unavailable": sum(v is None for v in values)}
        speed = []
        for row in trials:
            metrics = row["metrics"]
            seconds, tokens = metrics.get("generation_seconds"), metrics.get("output_tokens")
            speed.append(tokens / seconds if row["evidence_verified"] and seconds and tokens is not None else None)
        group["metrics"]["generation_tokens_per_second"] = _metric_summary(speed)
        group["failure_reasons"] = dict(Counter(row["failure_reason"] or row["evidence_error"] or row["outcome"] for row in trials if not row["task_correct"]))
        groups.append(group)
    pairs = []
    group_cases = defaultdict(dict)
    for case in case_rows:
        group_cases[(case["model_id"], case["method_id"])][case["case_id"]] = case
    methods = {row["method_id"]: row for row in plan["methods"]}
    for left, right in itertools.combinations(group_cases, 2):
        matched = [case for case in cases if group_cases[left][case]["complete_verified_case"] and group_cases[right][case]["complete_verified_case"]]
        left_only = sum(group_cases[left][c]["all_repetitions_correct"] and not group_cases[right][c]["all_repetitions_correct"] for c in matched)
        right_only = sum(group_cases[right][c]["all_repetitions_correct"] and not group_cases[left][c]["all_repetitions_correct"] for c in matched)
        comparable = (methods[left[1]]["token_ceiling"] == methods[right[1]]["token_ceiling"]
                      and methods[left[1]]["guided_schema_fingerprint"] == methods[right[1]]["guided_schema_fingerprint"])
        pairs.append({"left": {"model_id": left[0], "method_id": left[1]}, "right": {"model_id": right[0], "method_id": right[1]},
                      "matched_complete_cases": len(matched), "excluded_incomplete_cases": len(cases) - len(matched),
                      "both_correct": sum(group_cases[left][c]["all_repetitions_correct"] and group_cases[right][c]["all_repetitions_correct"] for c in matched),
                      "left_only_correct": left_only, "right_only_correct": right_only,
                      "both_incorrect": sum(not group_cases[left][c]["all_repetitions_correct"] and not group_cases[right][c]["all_repetitions_correct"] for c in matched),
                      "right_minus_left_percentage_points": (right_only - left_only) * 100 / len(matched) if matched else None,
                      "same_token_ceiling_and_schema": comparable,
                      "left_action_budget": methods[left[1]]["max_actions"], "right_action_budget": methods[right[1]]["max_actions"],
                      "interpretation": "Descriptive paired case outcomes only; no significance or causal model ranking claim."})
    splits = []
    for group in groups:
        for split in sorted({row["split"] for row in plan["cases"]}):
            subset = [row for row in case_rows if row["model_id"] == group["model_id"] and row["method_id"] == group["method_id"] and row["split"] == split]
            splits.append({"model_id": group["model_id"], "method_id": group["method_id"], "split": split,
                           "case_task_correct": wilson_interval(sum(row["all_repetitions_correct"] for row in subset), len(subset)),
                           "complete_verified_cases": sum(row["complete_verified_case"] for row in subset)})
    return {"schema_version": 1, **{key: plan[key] for key in FINGERPRINTS}, "plan": plan,
            "coverage": {"expected_trials": len(rows), "observed_trials": len(records),
                         "missing_trials": len(rows) - len(records), "verified_trials": sum(row["evidence_verified"] for row in rows),
                         "invalid_evidence_trials": sum(row["outcome"] == "invalid_evidence" for row in rows)},
            "groups": groups, "cases": case_rows, "splits": splits, "pairs": pairs, "trials": rows,
            "limitations": [
                "Results describe the registered synthetic Kubernetes case suite, not production incident prevalence.",
                "Case success requires every registered repetition to be task-correct. Missing/invalid trials remain in registered denominators as success not demonstrated.",
                "Wilson 95% intervals are descriptive case-level binomial intervals; this designed suite is not a random population sample.",
                "Repeated runs on a case are not independent cases. No trial-level confidence intervals, significance tests or causal ranking are reported.",
                "Model output uses the same guided action schema; repair correctness is not attributed solely to unconstrained model instruction following.",
                "One-shot and feedback methods may share a token ceiling but have different action budgets. Actual tokens and conservative reservations are separate.",
                "Worker artifacts/audits are assumed trusted execution records, not cryptographic remote attestation.",
            ]}


def _rate(value: dict[str, Any]) -> str:
    if value["rate"] is None:
        return "unavailable (0 cases)"
    return f"{value['successes']}/{value['cases']} ({100 * value['rate']:.1f}%; 95% Wilson {100 * value['low']:.1f}–{100 * value['high']:.1f}%)"


def _display(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(summary: dict[str, Any]) -> str:
    coverage = summary["coverage"]
    lines = ["# Registered Kubernetes remediation benchmark", "",
             f"Observed **{coverage['observed_trials']}/{coverage['expected_trials']}** registered trials; "
             f"**{coverage['verified_trials']}** have revalidated evidence. "
             f"**{coverage['missing_trials']}** are missing and **{coverage['invalid_evidence_trials']}** have invalid evidence.", "",
             "All counts below retain failures and missing cells. Success means the registered expected outcome, including unchanged and abstain cases.", "",
             "## Models and methods", "", "| Model | Frozen pin |", "|---|---|"]
    for model in summary["plan"]["models"]:
        lines.append(f"| {model['model_id']} | `{json.dumps(model['pin'], sort_keys=True).replace('|', '&#124;')}` |")
    lines += ["", "| Method | Conservative token ceiling | Action budget | Guided schema |", "|---|---:|---:|---|"]
    for method in summary["plan"]["methods"]:
        lines.append(f"| {method['method_id']} | {method['token_ceiling']} | {method['max_actions']} | `{method['guided_schema_fingerprint']}` |")
    lines += ["", "## Registered case results", "", "A case is successful only when every registered repetition is correct. Intervals use distinct cases, including missing cases as success not demonstrated.", "",
              "| Model | Method | Observed/registered trials | Verified trials | Correct trials | Repair cases | All task cases |", "|---|---|---:|---:|---:|---|---|"]
    for group in summary["groups"]:
        lines.append(f"| {group['model_id']} | {group['method_id']} | {group['observed_trials']}/{group['expected_trials']} | {group['verified_trials']} | {group['task_correct_trials']} | {_rate(group['case_repair_success'])} | {_rate(group['case_task_correct'])} |")
    lines += ["", "| Model | Method | Correct unchanged cases | Appropriate abstention cases |", "|---|---|---|---|"]
    for group in summary["groups"]:
        lines.append(f"| {group['model_id']} | {group['method_id']} | {_rate(group['case_unchanged_success'])} | {_rate(group['case_abstention_success'])} |")
    lines += ["", "## Outcomes and checks", "", "| Model | Method | Outcomes (trial counts) | Behavior pass/fail/unavailable | Static | Runtime security | Cleanup |", "|---|---|---|---|---|---|---|"]
    for group in summary["groups"]:
        values = [f"{group['checks'][name]['passed']}/{group['checks'][name]['failed']}/{group['checks'][name]['unavailable']}" for name in CHECKS]
        lines.append(f"| {group['model_id']} | {group['method_id']} | {json.dumps(group['outcomes'], sort_keys=True)} | " + " | ".join(values) + " |")
    lines += ["", "## Execution cost", "", "Only measurements bound to revalidated evidence are aggregated. Each value includes availability; missing usage is never zero.", "",
              "| Model | Method | Actual prompt/output/total tokens (sum) | Conservative reserved tokens (sum) | Wall seconds mean | Inference seconds mean | Generation tokens/sec mean |", "|---|---|---|---|---|---|---|"]
    def metric(group, name, stat="sum"):
        item = group["metrics"][name]
        return f"{_display(item[stat])} [{item['available']}/{group['expected_trials']} measured]"
    for group in summary["groups"]:
        token = "/".join(metric(group, name) for name in ("prompt_tokens", "output_tokens", "total_tokens"))
        lines.append(f"| {group['model_id']} | {group['method_id']} | {token} | {metric(group, 'reserved_tokens')} | {metric(group, 'wall_seconds', 'mean')} | {metric(group, 'inference_seconds', 'mean')} | {metric(group, 'generation_tokens_per_second', 'mean')} |")
    lines += ["", "| Model | Method | Inspections | Repairs | Tests | Model calls | Protocol rejects | Policy rejects |", "|---|---|---|---|---|---|---|---|"]
    for group in summary["groups"]:
        lines.append(f"| {group['model_id']} | {group['method_id']} | " + " | ".join(metric(group, name) for name in ("inspections", "repairs", "tests", "model_calls", "protocol_rejections", "policy_rejections")) + " |")
    lines += ["", "## Paired descriptive comparisons", "", "Pairs include only cases with complete revalidated repetitions on both sides. Exclusions and action budgets are explicit; these deltas do not establish significance.", "",
              "| Left | Right | Matched/excluded cases | Left only/both/right only correct | Right − left (percentage points) | Common ceiling/schema | Action budgets |", "|---|---|---|---|---|---|---|"]
    for pair in summary["pairs"]:
        left, right = pair["left"], pair["right"]
        lines.append(f"| {left['model_id']} / {left['method_id']} | {right['model_id']} / {right['method_id']} | {pair['matched_complete_cases']}/{pair['excluded_incomplete_cases']} | {pair['left_only_correct']}/{pair['both_correct']}/{pair['right_only_correct']} | {_display(pair['right_minus_left_percentage_points'])} | {pair['same_token_ceiling_and_schema']} | {pair['left_action_budget']}/{pair['right_action_budget']} |")
    lines += ["", "## Split results", "", "| Model | Method | Split | Correct cases | Complete verified cases |", "|---|---|---|---|---:|"]
    for split in summary["splits"]:
        lines.append(f"| {split['model_id']} | {split['method_id']} | {split['split']} | {_rate(split['case_task_correct'])} | {split['complete_verified_cases']} |")
    lines += ["", "## Per-case repetition results", "", "| Model | Method | Case | Split | Expected | Observed/registered | Verified | Correct repetitions | Every repetition correct |", "|---|---|---|---|---|---|---:|---:|---|"]
    for case in summary["cases"]:
        lines.append(f"| {case['model_id']} | {case['method_id']} | {case['case_id']} | {case['split']} | {case['expected_outcome']} | {case['observed_repetitions']}/{case['registered_repetitions']} | {case['verified_repetitions']} | {case['correct_repetitions']} | {case['all_repetitions_correct']} |")
    lines += ["", "## Failure reasons", ""]
    for group in summary["groups"]:
        lines += [f"### {group['model_id']} / {group['method_id']}", ""]
        if not group["failure_reasons"]:
            lines.append("No observed task failures in this group.")
        for reason, count in sorted(group["failure_reasons"].items()):
            lines.append(f"- {count}: {str(reason).replace(chr(10), ' ')}")
        lines.append("")
    lines += ["## Provenance and limits", "", *[f"- {line}" for line in summary["limitations"]], "",
              "`summary.json` retains the complete plan, trial paths/pins, outcome rows and missingness. `trials.csv` provides one row for every registered cell. `index.html` shows the same source values without external scripts.", "",
              *[f"- `{key}`: `{summary[key]}`" for key in FINGERPRINTS], ""]
    return "\n".join(lines)


def render_html(summary: dict[str, Any]) -> str:
    """A standalone evidence table and zero-based rate bars; no hosted assets."""
    escape = html.escape
    groups = []
    bars = []
    for group in summary["groups"]:
        result = group["case_task_correct"]
        label = f"{group['model_id']} / {group['method_id']}"
        groups.append("<tr>" + "".join(f"<td>{escape(str(value))}</td>" for value in (
            group["model_id"], group["method_id"], f"{group['observed_trials']}/{group['expected_trials']}",
            group["verified_trials"], _rate(result), json.dumps(group["outcomes"], sort_keys=True))) + "</tr>")
        rate = 100 * result["rate"] if result["rate"] is not None else 0
        bars.append(f"<div class='barrow'><span>{escape(label)}</span><div class='track'><div class='bar' style='width:{rate:.6f}%'></div></div><span>{escape(_rate(result))}</span></div>")
    trials = []
    for row in summary["trials"]:
        values = (row["model_id"], row["method_id"], row["case_id"], row["repetition"], row["outcome"],
                  row["task_correct"], row["metrics"].get("total_tokens") if row["evidence_verified"] else None,
                  row["metrics"].get("wall_seconds") if row["evidence_verified"] else None,
                  row["evidence_error"] or row["failure_reason"] or "")
        trials.append("<tr>" + "".join(f"<td>{escape(_display(value))}</td>" for value in values) + "</tr>")
    coverage = summary["coverage"]
    limits = "".join(f"<li>{escape(line)}</li>" for line in summary["limitations"])
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kubernetes remediation benchmark</title>
<style>body{{font:16px system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:1300px;color:#162033;background:#fafcff}}h1,h2{{line-height:1.2}}table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{border:1px solid #cbd4df;padding:.55rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#e8eef5}}.scroll{{overflow:auto}}.barrow{{display:grid;grid-template-columns:15rem 1fr 25rem;gap:1rem;align-items:center;margin:1rem 0}}.track{{height:1.2rem;background:#e4e9ef}}.bar{{height:100%;background:#245ea8}}@media(max-width:850px){{.barrow{{grid-template-columns:1fr}}}}li{{margin:.6rem 0}}</style>
<h1>Registered Kubernetes remediation benchmark</h1><p>{coverage['observed_trials']}/{coverage['expected_trials']} trials observed; {coverage['verified_trials']} evidence-verified; {coverage['missing_trials']} missing; {coverage['invalid_evidence_trials']} invalid evidence.</p>
<p>Each case passes only if every registered repetition is correct. Rate bars start at zero and end at 100%. Wilson 95% intervals describe distinct cases; repeated trials are not independent cases.</p>
<h2>Task-correct cases</h2>{''.join(bars)}<div class="scroll"><table><thead><tr><th>Model</th><th>Method</th><th>Observed/registered</th><th>Verified trials</th><th>Correct cases and interval</th><th>Outcomes</th></tr></thead><tbody>{''.join(groups)}</tbody></table></div>
<h2>All registered trials</h2><div class="scroll"><table><thead><tr><th>Model</th><th>Method</th><th>Case</th><th>Repeat</th><th>Outcome</th><th>Task correct</th><th>Actual total tokens</th><th>Wall seconds</th><th>Failure/evidence issue</th></tr></thead><tbody>{''.join(trials)}</tbody></table></div>
<h2>Interpretation and provenance</h2><ul>{limits}</ul><p>Exact statistics: <a href="summary.json">summary.json</a>; complete methods and costs: <a href="report.md">report.md</a>; registered trial table: <a href="trials.csv">trials.csv</a>.</p></html>"""


def write_reports(summary: dict[str, Any], output: Path) -> None:
    """Require a new directory; preserve earlier reports rather than overwrite."""
    output.mkdir(parents=True, exist_ok=False)
    (output / "summary.json").write_text(canonical(summary), encoding="utf-8")
    (output / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    (output / "index.html").write_text(render_html(summary), encoding="utf-8")
    fields = ["model_id", "method_id", "case_id", "repetition", "split", "expected_outcome", "outcome", "observed_outcome",
              "task_correct", "evidence_verified", "model_origin_verified", *COUNTS, *TIMINGS, *["check_" + name for name in CHECKS],
              "failure_reason", "evidence_error", "bundle_path", "audit_path", "provenance"]
    with (output / "trials.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in summary["trials"]:
            flat = {name: row.get(name) for name in fields}
            flat.update({name: row["metrics"].get(name) if row["evidence_verified"] else None for name in COUNTS + TIMINGS})
            flat.update({"check_" + name: row["checks"].get(name) if row["evidence_verified"] else None for name in CHECKS})
            flat.update({"bundle_path": row.get("evidence", {}).get("bundle_path"), "audit_path": row.get("evidence", {}).get("audit_path"),
                         "provenance": json.dumps(row["provenance"], sort_keys=True)})
            writer.writerow(flat)


def generate_reports(plan_path: Path, records_directory: Path, evidence_root: Path, output: Path) -> dict[str, Any]:
    plan = _read_json(plan_path)
    record_paths = sorted(records_directory.rglob("*.json"))
    records = [_read_json(path) for path in record_paths]
    summary = build_summary(plan, records, evidence_root)
    write_reports(summary, output)
    return summary
