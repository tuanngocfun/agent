#!/usr/bin/env python3
"""Post hoc diagnostics from an audited real campaign; never change primary scores.

Usage: python supplemental_analysis.py --summary REPORT/summary.json
       --shard SHARD0 [--shard SHARD1 ...] --output FRESH_DIRECTORY

This script starts no models, containers, clusters or network operations. It reads
the frozen report and raw shard artifacts, rechecks their bindings using the same
frozen auditor, and writes separately labelled supplemental diagnostics. It has
no built-in results and must not be run on synthetic fixtures as a model study.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import sys


def find_repository(script):
    """Check at most six known ancestors; never scan unrelated directories."""
    for candidate in tuple(script.resolve().parents)[:6]:
        if ((candidate / "pyproject.toml").is_file()
                and (candidate / "src/kube_robustness").is_dir()
                and (candidate / "scripts/report_robustness_v2.py").is_file()):
            return candidate
    raise RuntimeError("Cannot locate the associated Kubernetes benchmark repository")


REPO = find_repository(Path(__file__))
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
EXPECTED_PLAN = "robustness-v2-0b2666e6ec62a843d35dcabe14599e9f55340e92404749322dff95b46f8d8333"
EXPECTED_SOURCE = "f49a4550e31d63dcd4fd949a52aaeef617c63c08e0196747ebca62b1c931ca0b"
KEYS = ("model_id", "method_id", "case_id", "condition", "repetition")


def key(row):
    return tuple(row.get(name) for name in KEYS)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 80_000_000:
        raise ValueError("Expected bounded regular artifact file: " + str(path))
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("Duplicate JSON key: " + name)
            result[name] = value
        return result
    return json.loads(path.read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON " + value)))


def integer(value):
    return type(value) is int and value >= 0


def metric_summary(values):
    present = [value for value in values if value is not None]
    ordered = sorted(present)
    return {"available": len(present), "unavailable": len(values) - len(present),
            "sum": sum(present) if present else None,
            "mean": statistics.mean(present) if present else None,
            "median": statistics.median(present) if present else None,
            "p95_nearest_rank": ordered[math.ceil(.95 * len(ordered)) - 1] if ordered else None,
            "minimum": ordered[0] if ordered else None,
            "maximum": ordered[-1] if ordered else None}


def pointer(resource, path):
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        resource = resource[int(token)] if isinstance(resource, list) else resource[token]
    return resource


def raw_call_rows(primary, record, binding_verified):
    result = []
    for call in (record.get("method_result") or {}).get("calls", []):
        server, raw_error = None, None
        raw = call.get("raw_server_response")
        if isinstance(raw, str):
            try:
                server = json.loads(raw)
            except (ValueError, TypeError) as error:
                raw_error = type(error).__name__ + ": " + str(error)
        server = server if isinstance(server, dict) else {}
        error = call.get("error")
        complete = server.get("done") is True and server.get("done_reason") != "length" and integer(server.get("eval_count")) and server["eval_count"] > 0
        transport_timeout = raw is None and isinstance(error, str) and any(word in error.lower() for word in ("timeout", "timed out"))
        result.append({**{name: primary[name] for name in KEYS},
                       "call_index": call.get("call_index"), "call_status": call.get("status"),
                       "primary_outcome": primary["outcome"],
                       "primary_evidence_verified": primary["evidence_verified"],
                       "raw_binding_verified": binding_verified,
                       "raw_response_present": raw is not None,
                       "complete_generation_observed": complete,
                       "transport_timeout": transport_timeout,
                       "truncated_generation": server.get("done_reason") == "length",
                       "error": error, "raw_parse_error": raw_error,
                       "request_sha256": call.get("request_sha256"),
                       "response_sha256": call.get("response_sha256"),
                       "reported_model": server.get("model"),
                       "elapsed_ns": call.get("elapsed_ns"),
                       "raw_prompt_tokens": server.get("prompt_eval_count"),
                       "raw_completion_tokens": server.get("eval_count"),
                       "raw_generation_ns": server.get("eval_duration"),
                       "measurement_caveat": None if binding_verified else "Diagnostic only: not independently bound to the primary audited row"})
    return result


def revision_row(primary, record, binding_verified):
    if primary["method_id"] not in ("feedback", "feedback-filtered"):
        return None
    method = record.get("method_result") or {}
    feedback = method.get("intermediate_verifications") or []
    trace = method.get("trace") or []
    if not feedback or not trace:
        return {**{name: primary[name] for name in KEYS}, "category": "intermediate_feedback_unavailable",
                "primary_outcome": primary["outcome"], "primary_task_correct": primary["task_correct"],
                "raw_binding_verified": binding_verified}
    first = feedback[0]
    first_hash = trace[0].get("resources_sha256")
    final_hash = record.get("candidate_sha256")
    changed = bool(first_hash and final_hash and first_hash != final_hash)
    final = record.get("final_verification") or {}
    final_decision = method.get("decision") or {}
    structured_runtime = isinstance(first.get("runtime"), dict) and bool(first["runtime"]) and bool(first.get("resources_sha256")) and not first.get("failure_type")
    eligible = (binding_verified and primary["evidence_verified"] is True
                and primary["task_correct"] is True and final.get("passed") is True)
    failed_then_success = eligible and first.get("passed") is False
    category = "no_verified_failed_feedback_to_success_sequence"
    if not binding_verified:
        category = "raw_evidence_unavailable_or_mismatched"
    elif failed_then_success:
        if structured_runtime and not first.get("infrastructure_error") and changed and final_decision.get("action") == "patch":
            category = "runtime_failure_then_changed_candidate_then_primary_success"
        elif structured_runtime and not changed:
            category = "runtime_failure_then_success_without_candidate_change"
        elif first.get("failure_type") in ("model-error", "policy-error"):
            category = "method_validation_failure_then_primary_success"
        else:
            category = "other_failure_then_primary_success"
    return {**{name: primary[name] for name in KEYS}, "category": category,
            "primary_outcome": primary["outcome"], "primary_task_correct": primary["task_correct"],
            "primary_evidence_verified": primary["evidence_verified"], "raw_binding_verified": binding_verified,
            "first_feedback_type": "runtime" if structured_runtime else first.get("failure_type", "unavailable"),
            "first_feedback_passed": first.get("passed"),
            "first_feedback_infrastructure_error": first.get("infrastructure_error"),
            "first_failed_checks": [row.get("name") for row in first.get("checks", []) if row.get("passed") is False],
            "first_candidate_sha256": first_hash, "final_candidate_sha256": final_hash,
            "candidate_changed_after_feedback": changed, "final_runtime_passed": final.get("passed"),
            "final_decision_action": final_decision.get("action"),
            "first_model_response_sha256": (method.get("calls") or [{}])[0].get("response_sha256"),
            "final_model_response_sha256": (method.get("calls") or [{}])[-1].get("response_sha256"),
            "interpretation": "Temporal trace evidence; causal advantage requires the matched self-review comparison."}


def paired_rows(primary):
    cases = primary.get("cases") or []
    index = {(row["model_id"], row["method_id"], row["condition"], row["case_id"]): row for row in cases}
    methods = [row if isinstance(row, str) else row["method_id"] for row in primary["plan"]["methods"]]
    conditions = [row if isinstance(row, str) else row["condition_id"] for row in primary["plan"]["conditions"]]
    result = []
    def add(left, right, identity):
        left_correct, right_correct = left["all_repetitions_correct"], right["all_repetitions_correct"]
        outcome = "both_correct" if left_correct and right_correct else "right_win" if right_correct else "right_regression" if left_correct else "both_not_demonstrated_correct"
        result.append({**identity, "case_id": left["case_id"], "family": left["family"],
                       "left_correct": left_correct, "right_correct": right_correct,
                       "pair_complete_verified": left["complete_verified"] and right["complete_verified"],
                       "paired_outcome": outcome,
                       "incomplete_pairs_retained": True})
    for model in (row["model_id"] for row in primary["plan"]["models"]):
        for condition in conditions:
            for left, right in itertools.combinations(methods, 2):
                for case in primary["plan"]["cases"]:
                    a, b = (model, left, condition, case["id"]), (model, right, condition, case["id"])
                    if a in index and b in index:
                        add(index[a], index[b], {"comparison": "method", "model_id": model,
                            "condition": condition, "left": left, "right": right})
        for method in methods:
            for case in primary["plan"]["cases"]:
                a, b = (model, method, "clean", case["id"]), (model, method, "injection", case["id"])
                if a in index and b in index:
                    add(index[a], index[b], {"comparison": "evidence_condition", "model_id": model,
                        "method_id": method, "left": "clean", "right": "injection"})
    return result


def analyze(primary_path, shard_dirs):
    from report_robustness_v2 import audit_record
    primary = load(primary_path)
    if primary.get("schema_version") != "robustness-v2-report-v1" or primary.get("plan_id") != EXPECTED_PLAN or primary.get("source_sha256") != EXPECTED_SOURCE:
        raise ValueError("Expected the exact frozen campaign's audited summary")
    plan = primary["plan"]
    allowed = {key(row) for row in plan["cells"]}
    trials = primary.get("trials")
    if not isinstance(trials, list) or len(trials) != len(allowed) or {key(row) for row in trials} != allowed:
        raise ValueError("Primary report does not retain every registered cell exactly once")
    by_key, inventory = {}, []
    for supplied in shard_dirs:
        if supplied.is_symlink() or not supplied.is_dir():
            raise ValueError("Expected a real shard directory")
        shard = supplied.resolve()
        if load(shard / "plan.json") != plan:
            raise ValueError("Raw shard plan differs from primary frozen plan")
        for path in sorted((shard / "records").glob("*.json")):
            record = load(path)
            identity = key(record)
            if identity not in allowed or identity in by_key:
                raise ValueError("Duplicate or unregistered raw cell")
            by_key[identity] = (record, shard, path)
            inventory.append({"path": str(path), "sha256": file_hash(path), **{name: record.get(name) for name in KEYS}})
    durations, calls, revisions, mount_review, recheck_issues = [], [], [], [], []
    case_index = {row["id"]: row for row in plan["cases"]}
    for row in trials:
        identity = key(row)
        original = by_key.get(identity)
        binding_verified, binding_error = False, None
        record = None
        if original is not None:
            record, shard, _ = original
            audit = audit_record(plan, record, shard)
            agrees = all(audit.get(field) == row.get(field) for field in ("outcome", "evidence_verified", "model_origin_verified", "task_correct"))
            binding_verified = agrees and audit.get("evidence_verified") is True
            if not agrees:
                binding_error = "Raw re-audit differs from primary flags; primary flags were preserved"
                recheck_issues.append({**{name: row[name] for name in KEYS}, "error": binding_error,
                                       "primary_outcome": row["outcome"], "rechecked_outcome": audit.get("outcome"),
                                       "recheck_error": audit.get("evidence_error")})
            elif not audit.get("evidence_verified"):
                binding_error = audit.get("evidence_error")
        else:
            binding_error = "Raw record unavailable; registered primary row retained"
        metrics = row.get("metrics") or {}
        trusted = row["evidence_verified"] is True
        measure = lambda name: metrics.get(name) if trusted else None
        duration = {**{name: row[name] for name in KEYS}, "family": row.get("family"),
                    "primary_outcome": row["outcome"], "primary_task_correct": row["task_correct"],
                    "primary_evidence_verified": trusted, "raw_available": original is not None,
                    "raw_binding_verified": binding_verified, "raw_binding_error": binding_error,
                    "wall_seconds": measure("wall_seconds"), "inference_ns": measure("inference_ns"),
                    "generation_ns": measure("generation_ns"), "prompt_tokens": measure("prompt_tokens"),
                    "completion_tokens": measure("completion_tokens"), "model_calls": measure("model_calls")}
        duration["generation_seconds"] = duration["generation_ns"] / 1_000_000_000 if integer(duration["generation_ns"]) else None
        durations.append(duration)
        if record is None:
            if row["method_id"].startswith("feedback"):
                revisions.append({**{name: row[name] for name in KEYS}, "category": "registered_raw_record_missing",
                                  "primary_outcome": row["outcome"], "primary_task_correct": row["task_correct"], "raw_binding_verified": False})
            continue
        calls.extend(raw_call_rows(row, record, binding_verified))
        revision = revision_row(row, record, binding_verified)
        if revision is not None:
            revisions.append(revision)
        objects = {item["kind"] + "/" + item["metadata"]["name"]: item for item in record.get("candidate_resources", [])}
        for assertion in case_index[row["case_id"]]["contract"]["security_checks"]:
            path = assertion["path"]
            if "/volumeMounts/" not in path or not path.endswith("/readOnly") or assertion["value"] is not True:
                continue
            try:
                observed = pointer(objects[assertion["resource"]], path)
                maintained = observed is True
            except (KeyError, TypeError, IndexError, ValueError):
                observed, maintained = None, False
            mount_review.append({**{name: row[name] for name in KEYS}, "resource": assertion["resource"],
                                 "path": path, "frozen_required_value": True, "candidate_observed_value": observed,
                                 "required_readonly_preserved": maintained, "primary_task_correct": row["task_correct"],
                                 "primary_outcome": row["outcome"], "raw_binding_verified": binding_verified,
                                 "posthoc_diagnostic": True,
                                 "note": "This property is already protected in the current frozen primary contract; no historical pilot gap is carried forward."})
    groups = []
    group_rows = defaultdict(list)
    for row in durations:
        group_rows[(row["model_id"], row["method_id"], row["condition"])].append(row)
    for identity, rows in sorted(group_rows.items()):
        request_rows = [call for call in calls if (call["model_id"], call["method_id"], call["condition"]) == identity and call["raw_binding_verified"]]
        ns = [row["generation_ns"] for row in rows if integer(row["generation_ns"])]
        groups.append({"model_id": identity[0], "method_id": identity[1], "condition": identity[2],
                       "registered_trials": len(rows), "primary_outcomes": dict(Counter(row["primary_outcome"] for row in rows)),
                       "primary_task_correct": sum(row["primary_task_correct"] for row in rows),
                       "raw_binding_verified_trials": sum(row["raw_binding_verified"] for row in rows),
                       "wall_seconds": metric_summary([row["wall_seconds"] for row in rows]),
                       "generation_ns": metric_summary([row["generation_ns"] for row in rows]),
                       "generation_seconds_sum_from_integer_ns": sum(ns) / 1_000_000_000 if ns else None,
                       "trusted_recorded_requests": len(request_rows),
                       "transport_timeouts": sum(call["transport_timeout"] for call in request_rows),
                       "truncated_generations": sum(call["truncated_generation"] for call in request_rows),
                       "request_errors": sum(call["call_status"] == "error" for call in request_rows),
                       "usage_caveat": "Request counts cover revalidated raw records only; absent records remain in registered_trials, not zero-valued observations."})
    return {"analysis_kind": "post-hoc-supplemental-diagnostics-v1", "primary_scores_changed": False,
            "plan_id": primary["plan_id"], "source_sha256": primary["source_sha256"],
            "primary_summary_path": str(primary_path.resolve()), "primary_summary_sha256": file_hash(primary_path),
            "analysis_script_sha256": file_hash(Path(__file__)), "raw_record_inventory": inventory,
            "primary_coverage_unchanged": primary["coverage"], "primary_groups_unchanged": primary["groups"],
            "trial_durations": durations, "raw_model_requests": calls, "feedback_revisions": revisions,
            "feedback_revision_categories": dict(Counter(row["category"] for row in revisions)),
            "paired_case_outcomes": paired_rows(primary), "current_frozen_consumer_mount_review": mount_review,
            "raw_recheck_issues": recheck_issues, "execution_cost_groups": groups,
            "limitations": [
                "This analysis was prepared after preregistration and is supplemental. Frozen primary task-correct scores and missing/invalid rows are copied without alteration.",
                "A failed feedback test followed by a successful changed candidate is temporal trace evidence, not causal proof of feedback superiority. The matched two-call self-review comparison is the relevant control.",
                "Success without a candidate change after failed feedback can reflect settling or repeated verification and is reported separately.",
                "Method-generated protocol/policy error feedback is not an actual Kubernetes test failure; those correction sequences are separate.",
                "Pairs retain incomplete and invalid cases. Injection conditions are variants of the same case, not additional independent problems.",
                "Raw request diagnostics lacking a matching independent binding are labelled untrusted and excluded from trusted request-cost aggregates; their primary trial rows remain.",
                "Consumer readonly checks are already present in this campaign's frozen contract. This review confirms candidate fields and does not add a new primary scoring rule.",
            ]}


def csv_write(path, rows):
    fields = list(dict.fromkeys(name for row in rows for name in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({name: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for name, value in row.items()} for row in rows)


def write(result, output):
    if output.exists() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Expected a fresh output directory without symlink parents")
    output.mkdir(parents=True)
    (output / "supplemental.json").write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    for name, field in (("trial-durations.csv", "trial_durations"), ("model-requests.csv", "raw_model_requests"),
                        ("feedback-revisions.csv", "feedback_revisions"), ("paired-outcomes.csv", "paired_case_outcomes"),
                        ("consumer-mount-review.csv", "current_frozen_consumer_mount_review")):
        csv_write(output / name, result[field])
    coverage = result["primary_coverage_unchanged"]
    lines = ["# Supplemental campaign diagnostics", "",
             "Post hoc analysis of real audited artifacts. **Frozen primary scores are unchanged.** Missing and invalid cells remain in every registered trial table.", "",
             "Primary coverage: `" + json.dumps(coverage, sort_keys=True) + "`.", "",
             "Primary summary SHA256: `" + result["primary_summary_sha256"] + "`.", "",
             "## Verified feedback sequences", "",
             "| Sequence category | Registered trial rows |", "|---|---:|"]
    for name, count in sorted(result["feedback_revision_categories"].items()):
        lines.append(f"| {name} | {count} |")
    lines += ["", "The changed-candidate category requires independently bound raw evidence, an actual failed Kubernetes intermediate test, a later patch that changes the candidate, and a successful frozen primary outcome. Protocol/policy feedback and success without a candidate change are separate.", "",
              "## Time and request failures", "",
              "| Method | Condition | Registered trials | Raw-bound trials | Wall seconds sum / measured trials | Trusted requests | Transport timeouts | Truncations |", "|---|---|---:|---:|---|---:|---:|---:|"]
    for row in result["execution_cost_groups"]:
        wall = row["wall_seconds"]
        wall_value = "unavailable" if wall["sum"] is None else f"{wall['sum']:.3f} / {wall['available']}"
        lines.append(f"| {row['method_id']} | {row['condition']} | {row['registered_trials']} | {row['raw_binding_verified_trials']} | {wall_value} | {row['trusted_recorded_requests']} | {row['transport_timeouts']} | {row['truncated_generations']} |")
    lines += ["", "Per-trial measured durations and actual request failures are in `trial-durations.csv` and `model-requests.csv`. Missing values are blank, not zero. Generation totals sum integer raw nanoseconds before division.", "",
              "## Paired wins and regressions", "",
              "`paired-outcomes.csv` records every matched base-case pair, including incomplete pairs. A right win and a right regression are both visible; only pairs explicitly marked complete support a fully observed contrast. These descriptive comparisons do not establish population generalization.", "",
              "## Current consumer controls", "",
              "`consumer-mount-review.csv` reviews readonly consumer fields already enforced by this exact frozen contract. It does not reuse an older pilot's contract gap or change primary outcomes.", "",
              f"Raw re-audit disagreements with the primary report: **{len(result['raw_recheck_issues'])}**. Any disagreement is retained for investigation; the primary result is not overwritten.", "",
              "## Limits", ""] + ["- " + text for text in result["limitations"]]
    (output / "README.md").write_text("\n".join(lines) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--shard", required=True, action="append", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze(args.summary, args.shard)
        write(result, args.output)
    except (OSError, ValueError, TypeError, KeyError, ImportError) as error:
        parser.exit(2, f"Supplemental analysis refused: {type(error).__name__}: {error}\n")
    print(json.dumps({"output": str(args.output), "primary_scores_changed": False,
                      "registered_trial_rows": len(result["trial_durations"]),
                      "raw_recheck_issues": len(result["raw_recheck_issues"]),
                      "feedback_revision_categories": result["feedback_revision_categories"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
