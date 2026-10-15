#!/usr/bin/env python3
"""Diagnose frozen timing-validation errors without changing primary outcomes."""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys

PROJECT_ROOT = next((parent for parent in Path(__file__).resolve().parents
                     if (parent / "src/kube_repair/benchmark_protocol.py").is_file()), None)
if PROJECT_ROOT is None:
    raise RuntimeError("Keep this diagnostic inside its frozen project checkout")
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from kube_repair.artifacts import canonical, load_bundle
from kube_repair.benchmark_protocol import validate_locked_plan
from kube_repair.benchmark_reporting import _evidence_path, build_summary, verify_record_evidence
from kube_repair.providers import _strict_json_loads

TIMING_ERROR = "ValueError: Record generation_seconds differs from bound execution evidence"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise ValueError("Expected a bounded regular JSON file: " + str(path))
    return _strict_json_loads(path.read_bytes())


def cell_key(row):
    return tuple(row[key] for key in ("model_id", "method_id", "case_id", "repetition"))


def diagnose_trial(trial, record, method, root, input_hashes):
    row = {name: trial[name] for name in ("model_id", "method_id", "case_id", "repetition")}
    row.update({"primary_outcome": trial["outcome"], "primary_task_correct": trial["task_correct"],
        "primary_evidence_error": trial["evidence_error"], "raw_worker_outcome": record["outcome"],
        "raw_report_status": None, "raw_accepted": None, "classification": "unsupported_invalid_evidence",
        "rounding_only_established": False, "raw_response_hashes_verified": None,
        "recorded_generation_seconds": record.get("metrics", {}).get("generation_seconds"),
        "worker_formula_seconds": None, "canonical_generation_seconds": None,
        "delta_seconds": None, "delta_nanoseconds": None, "raw_eval_nanoseconds": None,
        "original_worker_formula_exact_match": None, "diagnostic_verification_passed": False,
        "diagnostic_error": None, "bundle_review_hash": None,
        "original_primary_outcome_preserved": True})
    original_check = verify_record_evidence(record, root, method)
    if original_check["verified"] or original_check["error"] != trial["evidence_error"]:
        raise ValueError("Invalid-row evidence changed since the primary summary")
    if trial["evidence_error"] != TIMING_ERROR:
        row["diagnostic_error"] = "Primary invalidity is not the supported generation-time mismatch; no canonicalization attempted."
        return row
    try:
        evidence = record["evidence"]
        bundle = _evidence_path(root, evidence["bundle_path"])
        binding, payloads = load_bundle(bundle)
        report = _strict_json_loads(payloads["report.json"])
        row.update({"raw_report_status": report["status"], "raw_accepted": report["accepted"],
                    "bundle_review_hash": binding["review_hash"]})
        for name in ("binding.json", "report.json", "trace.json", "contract.json", "base.json", "candidate.json"):
            input_hashes[str((bundle / name).relative_to(root))] = sha256(bundle / name)
        provider = report["provider"]
        calls = provider.get("inference_calls", [])
        usage = provider.get("token_usage") or {}
        if not calls or usage.get("counts_complete") is not True or usage.get("counts_available_calls", 0) <= 0:
            raise ValueError("Complete nonempty worker timing evidence is unavailable")
        durations = []
        for call in calls:
            raw = call.get("raw_server_response")
            if not isinstance(raw, str) or call.get("response_truncated"):
                raise ValueError("A raw response is incomplete")
            if hashlib.sha256(raw.encode()).hexdigest() != call.get("response_sha256"):
                raise ValueError("A raw response checksum differs")
            server = _strict_json_loads(raw)
            duration = server.get("eval_duration") if isinstance(server, dict) else None
            if type(duration) is not int or duration < 0:
                raise ValueError("A raw duration is not an integer number of nanoseconds")
            durations.append(duration)
        row["raw_response_hashes_verified"] = True
        worker_seconds = sum(duration / 1e9 for duration in durations)
        canonical_seconds = sum(durations) / 1_000_000_000
        recorded = row["recorded_generation_seconds"]
        if type(recorded) not in (int, float) or not math.isfinite(recorded) or recorded < 0:
            raise ValueError("Recorded generation time is unavailable or malformed")
        row.update({"worker_formula_seconds": worker_seconds,
            "canonical_generation_seconds": canonical_seconds,
            "delta_seconds": recorded - canonical_seconds,
            "delta_nanoseconds": (recorded - canonical_seconds) * 1_000_000_000,
            "raw_eval_nanoseconds": durations,
            "original_worker_formula_exact_match": recorded == worker_seconds})
        if recorded != worker_seconds:
            raise ValueError("Recorded duration does not exactly match the original frozen worker formula")
        if recorded == canonical_seconds:
            raise ValueError("There is no floating-point formula difference to explain this invalidity")
        roundoff_bound = (len(durations) + 1) * max(math.ulp(worker_seconds), math.ulp(canonical_seconds))
        row["floating_point_error_bound_seconds"] = roundoff_bound
        if abs(recorded - canonical_seconds) > roundoff_bound:
            raise ValueError("The timing discrepancy exceeds the diagnostic floating-point bound")
        normalized = copy.deepcopy(record)
        normalized["metrics"]["generation_seconds"] = canonical_seconds
        diagnostic = verify_record_evidence(normalized, root, method)
        row["diagnostic_verification_passed"] = diagnostic["verified"] is True
        row["diagnostic_error"] = diagnostic["error"]
        if diagnostic["verified"] is not True:
            raise ValueError("A separate evidence guard still fails: " + str(diagnostic["error"]))
        row["classification"] = "sole_generation_time_rounding_mismatch"
        row["rounding_only_established"] = True
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        row["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
        row["classification"] = "unsupported_invalid_evidence"
        row["rounding_only_established"] = False
        row["diagnostic_verification_passed"] = False
    return row


def markdown(report):
    coverage = report["primary_coverage"]
    lines = ["# Frozen benchmark timing errata", "",
        f"Primary snapshot: {coverage['observed_trials']}/{coverage['expected_trials']} trials observed; "
        f"{coverage['invalid_evidence_trials']} invalid-evidence rows. "
        f"This diagnostic establishes {report['rounding_only_rows']} timing-only mismatches and leaves "
        f"{report['unsupported_invalid_rows']} invalid rows unsupported.", "",
        "All original files, primary outcomes, task-correctness flags and comparison denominators remain unchanged. "
        "In-memory canonicalization diagnoses the failed guard; it does not accept, promote or rerun a task.", "",
        "The frozen worker sums `duration_ns / 1e9` per call. The frozen reporter divides the integer nanosecond sum by `1e9` "
        "and compares floats with exact equality. Different rounding can therefore reject otherwise intact evidence.", "",
        "| Model | Method | Case | Repeat | Primary / raw worker outcome | Original seconds | Canonical seconds | Difference seconds | Sole rounding guard? |",
        "|---|---|---|---:|---|---:|---:|---:|---|"]
    for row in report["rows"]:
        value = lambda name: "unavailable" if row[name] is None else str(row[name])
        lines.append(f"| {row['model_id']} | {row['method_id']} | {row['case_id']} | {row['repetition']} | "
            f"{row['primary_outcome']} / {row['raw_worker_outcome']} | {value('recorded_generation_seconds')} | "
            f"{value('canonical_generation_seconds')} | {value('delta_seconds')} | {row['rounding_only_established']} |")
    lines += ["", "## Unsupported invalid rows", ""]
    if report["non_rounding_invalids"]:
        for row in report["non_rounding_invalids"]:
            lines.append(f"- `{row['model_id']}/{row['method_id']}/{row['case_id']}/{row['repetition']}`: {row['diagnostic_error']}")
    else:
        lines.append("None in this snapshot.")
    lines += ["", "## Interpretation", "",
        "- Exact raw-response hashes, the worker's original summation and every remaining frozen reporter guard must pass before a row is diagnosed as rounding-only.",
        "- Unsupported discrepancies stay unsupported. Neither their outcome nor their evidence state is waived.",
        "- Original `invalid_evidence` outcomes remain visible even when the underlying worker status is a genuine budget failure or accepted candidate.",
        "- This is descriptive report diagnostics, not a corrected primary analysis or remote attestation.",
        "- A future benchmark version should use a shared integer-nanosecond aggregation rule and a multi-call regression test.", ""]
    return "\n".join(lines)


def analyse(root, output):
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Errata destination must be a fresh directory without symlink parents")
    root = root.resolve(strict=True)
    plan_path, summary_path = root / "plan.json", root / "summary.json"
    plan = validate_locked_plan(read_json(plan_path))
    primary = read_json(summary_path)
    record_paths = sorted((root / "records").glob("*.json"))
    records = [read_json(path) for path in record_paths]
    rebuilt = build_summary(plan, records, root)
    if primary != rebuilt:
        raise ValueError("Primary summary does not exactly reconcile with frozen source and bound evidence")
    input_hashes = {"plan.json": sha256(plan_path), "summary.json": sha256(summary_path),
                    **{str(path.relative_to(root)): sha256(path) for path in record_paths}}
    record_map = {cell_key(record): record for record in records}
    methods = {method["method_id"]: method for method in plan["methods"]}
    invalid = [trial for trial in rebuilt["trials"] if trial["outcome"] == "invalid_evidence"]
    rows = [diagnose_trial(trial, record_map[cell_key(trial)], methods[trial["method_id"]], root, input_hashes) for trial in invalid]
    if len(rows) != primary["coverage"]["invalid_evidence_trials"]:
        raise ValueError("Invalid-row population differs from the primary summary")
    for relative, expected in input_hashes.items():
        if sha256(_evidence_path(root, relative)) != expected:
            raise ValueError("An input file changed during the diagnostic")
    result = {"schema_version": 1, "analysis_role": "descriptive_timing_errata_primary_outcomes_unchanged",
        "plan_id": plan["plan_id"], "source_fingerprint": plan["source_fingerprint"],
        "input_report": os.path.relpath(root, output.resolve()), "script_sha256": sha256(Path(__file__)),
        "input_sha256": input_hashes, "primary_coverage": primary["coverage"],
        "primary_task_correct_trials_unchanged": sum(group["task_correct_trials"] for group in primary["groups"]),
        "primary_summary_exactly_recomputed": True, "original_files_unchanged": True,
        "rounding_only_rows": sum(row["rounding_only_established"] for row in rows),
        "unsupported_invalid_rows": sum(not row["rounding_only_established"] for row in rows),
        "rows": rows, "non_rounding_invalids": [row for row in rows if not row["rounding_only_established"]]}
    output.mkdir(parents=True, exist_ok=False)
    (output / "errata.json").write_text(canonical(result), encoding="utf-8")
    (output / "errata.md").write_text(markdown(result), encoding="utf-8")
    names = list(dict.fromkeys(name for row in rows for name in row)) or ["classification", "primary_outcome"]
    with (output / "errata.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: json.dumps(value) if isinstance(value, list) else value for name, value in row.items()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyse(args.report_root, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Timing errata refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"status": "written", "rounding_only_rows": result["rounding_only_rows"],
                      "unsupported_invalid_rows": result["unsupported_invalid_rows"],
                      "primary_outcomes_unchanged": True, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
