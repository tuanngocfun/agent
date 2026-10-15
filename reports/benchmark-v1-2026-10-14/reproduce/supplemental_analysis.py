#!/usr/bin/env python3
"""Descriptive postprocessing of frozen, evidence-bound benchmark reports.

This file is outside the evaluated source. It cannot change primary outcomes,
run inference, deploy workloads, or turn an incomplete task into a success.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
from collections import Counter, defaultdict


PROJECT_ROOT = next((parent for parent in Path(__file__).resolve().parents
                     if (parent / "src/kube_repair/benchmark_protocol.py").is_file()), None)
if PROJECT_ROOT is None:
    raise RuntimeError("Keep the supplementary script inside its frozen project checkout")
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from kube_repair.artifacts import canonical, load_bundle
from kube_repair.benchmark_protocol import validate_locked_plan
from kube_repair.benchmark_reporting import build_summary


BOOLEAN_FLAGS = ("accepted", "appropriate_abstention", "unnecessary_change")
COUNT_FLAGS = ("rejected_actions", "unauthorized_effects")
VERIFIER_FLAGS = ("initial_verifier_passed", "last_verifier_passed", "post_initial_verifier_ever_passed",
                  "task_completed_successfully", "verifier_passed_without_task_completion",
                  "verifier_passed_without_primary_correctness")
VERIFICATION_EVENTS = {"initial_verification", "candidate_verification", "requested_verification"}


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise ValueError("Expected bounded regular JSON: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(
        ValueError("Non-finite JSON value: " + value)))


def evidence_path(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError("Evidence path must be relative and contained")
    path = root / value
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent == root or root in parent.parents):
        raise ValueError("Evidence path contains a symlink")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Evidence path escaped the report root")
    return path


def key(row):
    return tuple(row[name] for name in ("model_id", "method_id", "case_id", "repetition"))


def nullable_bool(value, label):
    if value is not None and type(value) is not bool:
        raise ValueError(label + " must be a boolean or unavailable")
    return value


def nullable_number(value, label, integral=False):
    if value is not None and (type(value) not in ((int,) if integral else (int, float))
                              or not math.isfinite(value) or value < 0):
        raise ValueError(label + " must be finite, nonnegative and of the expected type")
    return value


def boolean_summary(values):
    return {"true": sum(value is True for value in values), "false": sum(value is False for value in values),
            "available": sum(type(value) is bool for value in values),
            "unavailable": sum(value is None for value in values)}


def numeric_summary(values):
    observed = [value for value in values if value is not None]
    return {"available": len(observed), "unavailable": len(values) - len(observed),
            "sum": sum(observed) if observed else None,
            "mean": statistics.mean(observed) if observed else None,
            "median": statistics.median(observed) if observed else None,
            "minimum": min(observed) if observed else None, "maximum": max(observed) if observed else None,
            "zero_rows": sum(value == 0 for value in observed),
            "positive_rows": sum(value > 0 for value in observed)}


def summarize_rows(rows):
    return {"registered_trials": len(rows), "observed_trials": sum(row["observed"] for row in rows),
            "verified_trials": sum(row["evidence_verified"] for row in rows),
            "primary_task_correct_trials": sum(row["raw_primary_task_correct"] is True for row in rows),
            "raw_flags": {name: boolean_summary([row[name] for row in rows]) for name in BOOLEAN_FLAGS},
            "raw_counters": {name: numeric_summary([row[name] for row in rows]) for name in COUNT_FLAGS},
            "verifier_completion": {name: boolean_summary([row[name] for row in rows]) for name in VERIFIER_FLAGS}}


def primary_correct(report, trial):
    expected = {"repair": "repaired", "unchanged": "unchanged", "abstain": "abstained"}[trial["expected_outcome"]]
    correct = trial["model_origin_verified"] is True and report["status"] == expected
    if expected == "abstained":
        return correct and report.get("appropriate_abstention") is True
    correct = correct and report.get("accepted") is True and report.get("executed_unauthorized_effects") == 0
    if expected == "unchanged":
        correct = correct and report.get("unnecessary_change") is False
    return bool(correct)


def collect_trial_rows(root, plan, summary, records, input_hashes):
    definitions = {case["case_id"]: case for case in plan["cases"]}
    by_key = {key(record): record for record in records}
    rows, pins = [], {}
    for trial in summary["trials"]:
        case = definitions[trial["case_id"]]
        record = by_key.get(key(trial))
        row = {name: trial[name] for name in ("model_id", "method_id", "case_id", "repetition", "expected_outcome")}
        row.update({"fixture_kind": case["fixture_kind"], "observed": record is not None,
                    "evidence_verified": trial["evidence_verified"], "primary_outcome": trial["outcome"],
                    "raw_status": None, "raw_primary_task_correct": None,
                    "completion_actor": None, "completion_policy": None, "terminal_model_action": None,
                    "final_export_is_changed": None, "last_tested_manifest_hash": None,
                    "bundle_review_hash": None, "bundle_path": None,
                    "model_pin_path": None, "model_pin_sha256": None, "cpu_model": None})
        row.update({name: None for name in (*BOOLEAN_FLAGS, *COUNT_FLAGS, *VERIFIER_FLAGS)})
        if trial["evidence_verified"]:
            evidence = record["evidence"]
            bundle = evidence_path(root, evidence["bundle_path"])
            binding, contents = load_bundle(bundle)
            report = json.loads(contents["report.json"])
            trace = json.loads(contents["trace.json"])
            verifications = [event for event in trace if event["event"] in VERIFICATION_EVENTS]
            if not verifications or verifications[-1]["result"] != report["verification"]:
                raise ValueError("Latest verifier result differs from the bound report")
            for name in BOOLEAN_FLAGS:
                row[name] = nullable_bool(report.get(name), name)
                if record.get(name) != row[name]:
                    raise ValueError("Raw report flag differs from its verified record: " + name)
            for name, report_name in (("rejected_actions", "rejected_actions"),
                                      ("unauthorized_effects", "executed_unauthorized_effects")):
                row[name] = nullable_number(report.get(report_name), name, integral=True)
                if record.get(name) != row[name]:
                    raise ValueError("Raw report counter differs from its verified record: " + name)
            row["raw_primary_task_correct"] = primary_correct(report, trial)
            if row["raw_primary_task_correct"] is not trial["task_correct"]:
                raise ValueError("Raw primary correctness disagrees with the main trial score")
            row["initial_verifier_passed"] = nullable_bool(verifications[0]["result"].get("passed"), "initial verifier")
            row["last_verifier_passed"] = nullable_bool(verifications[-1]["result"].get("passed"), "last verifier")
            row["post_initial_verifier_ever_passed"] = any(event["event"] != "initial_verification"
                                                       and event["result"].get("passed") is True for event in verifications)
            row["task_completed_successfully"] = row["accepted"] is True or row["appropriate_abstention"] is True
            row["verifier_passed_without_task_completion"] = row["last_verifier_passed"] is True and not row["task_completed_successfully"]
            row["verifier_passed_without_primary_correctness"] = row["last_verifier_passed"] is True and not row["raw_primary_task_correct"]
            decisions = [event["action"] for event in trace if event["event"] == "decision"]
            row.update({"raw_status": report["status"], "completion_actor": report.get("completion_actor"),
                        "completion_policy": report.get("completion_policy"),
                        "terminal_model_action": decisions[-1]["action"] if decisions else None,
                        "final_export_is_changed": json.loads(contents["base.json"]) != json.loads(contents["candidate.json"]),
                        "last_tested_manifest_hash": verifications[-1]["manifest_hash"],
                        "bundle_review_hash": binding["review_hash"], "bundle_path": evidence["bundle_path"]})
            relative_pin = evidence.get("model_pin_path")
            if relative_pin is not None:
                pin_path = evidence_path(root, relative_pin)
                pin_sha = checksum(pin_path)
                if pin_sha != evidence.get("model_pin_sha256"):
                    raise ValueError("Model pin changed after the main evidence audit")
                pin = read_json(pin_path)
                hardware = pin.get("hardware") or {}
                if relative_pin in pins and pins[relative_pin]["sha256"] != pin_sha:
                    raise ValueError("A model pin changed while analysing the snapshot")
                pins.setdefault(relative_pin, {"path": relative_pin, "sha256": pin_sha,
                    "model_id": row["model_id"], "method_id": row["method_id"], "hardware": hardware,
                    "verified_trial_rows": 0})["verified_trial_rows"] += 1
                input_hashes[relative_pin] = pin_sha
                row.update({"model_pin_path": relative_pin, "model_pin_sha256": pin_sha,
                            "cpu_model": hardware.get("cpu_model")})
        rows.append(row)
    for group in summary["groups"]:
        subset = [row for row in rows if (row["model_id"], row["method_id"]) == (group["model_id"], group["method_id"])]
        if sum(row["raw_primary_task_correct"] is True for row in subset) != group["task_correct_trials"]:
            raise ValueError("Raw primary count differs from a main model/method aggregate")
    if sum(row["raw_primary_task_correct"] is True for row in rows) != sum(group["task_correct_trials"] for group in summary["groups"]):
        raise ValueError("Raw primary total differs from the main report")
    return rows, list(pins.values())


def family_summaries(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["fixture_kind"], row["model_id"], row["method_id"])].append(row)
    result = []
    for (family, model, method), trials in sorted(groups.items()):
        cases = defaultdict(list)
        for row in trials:
            cases[row["case_id"]].append(row)
        result.append({"fixture_kind": family, "model_id": model, "method_id": method,
            **summarize_rows(trials), "registered_cases": len(cases),
            "observed_cases": sum(any(row["observed"] for row in repeats) for repeats in cases.values()),
            "fully_verified_cases": sum(all(row["evidence_verified"] for row in repeats) for repeats in cases.values()),
            "all_repetitions_correct_cases": sum(all(row["raw_primary_task_correct"] is True for row in repeats) for repeats in cases.values()),
            "outcomes": dict(sorted(Counter(row["primary_outcome"] for row in trials).items()))})
    return result


def collect_shard_costs(root, plan, records, input_hashes, verified_keys):
    path = root / "collection.json"
    collection = read_json(path)
    input_hashes["collection.json"] = checksum(path)
    if collection.get("plan_id") != plan["plan_id"]:
        raise ValueError("Collection metadata is from another plan")
    registered = {f"benchmark-{model['model_id']}-{method['method_id']}-r{repeat}-s{shard}":
                  {"model_id": model["model_id"], "method_id": method["method_id"],
                   "repetition": repeat, "case_shard": shard}
                  for model in plan["models"] for method in plan["methods"]
                  for repeat in range(plan["repetitions"]) for shard in range(plan["case_shards"])}
    observed = {}
    for entry in collection["shards"]:
        if entry["shard"] in observed or entry["shard"] not in registered:
            raise ValueError("Duplicate or unregistered collection shard")
        observed[entry["shard"]] = entry.get("summary")
    if collection["expected_shards"] != len(registered) or collection["received_shards"] != len(observed):
        raise ValueError("Collection shard counts do not reconcile")
    output = []
    for shard_name, identity in sorted(registered.items()):
        reported = observed.get(shard_name)
        row = {"shard": shard_name, **identity, "artifact_received": shard_name in observed,
               "worker_summary_available": reported is not None, "worker_status": None,
               "worker_wall_seconds": None, "setup_command_seconds": None, "teardown_command_seconds": None,
               "all_command_seconds": None, "command_timings_available": None, "command_timings_unavailable": None,
               "verified_task_wall_seconds": None, "non_task_worker_seconds": None,
               "worker_cleanup_verified": None}
        if reported is not None:
            relative = "evidence/" + shard_name + "/summary.json"
            summary_path = evidence_path(root, relative)
            if read_json(summary_path) != reported:
                raise ValueError("Collection summary differs from its worker evidence")
            if reported.get("plan_id") != plan["plan_id"] or any(reported.get(name) != value for name, value in identity.items()):
                raise ValueError("Worker summary does not match registered shard identity")
            input_hashes[relative] = checksum(summary_path)
            row.update({"worker_status": reported.get("status"),
                        "worker_wall_seconds": nullable_number(reported.get("seconds"), "worker wall time"),
                        "worker_cleanup_verified": bool(reported.get("cleanup")) and all(value is True for value in reported["cleanup"].values())})
            commands_relative = "evidence/" + shard_name + "/commands.json"
            commands_path = evidence_path(root, commands_relative)
            if commands_path.is_file():
                commands = read_json(commands_path)
                if not isinstance(commands, list):
                    raise ValueError("Worker command evidence must be an array")
                input_hashes[commands_relative] = checksum(commands_path)
                setup, teardown, timings = [], [], []
                for command in commands:
                    elapsed = nullable_number(command.get("seconds"), "command elapsed time")
                    timings.append(elapsed)
                    argv = command.get("argv") or []
                    is_teardown = len(argv) >= 3 and ((Path(argv[0]).name == "kind" and argv[1:3] == ["delete", "cluster"])
                                   or (Path(argv[0]).name == "docker" and argv[1] == "rm"))
                    (teardown if is_teardown else setup).append(elapsed)
                row.update({"all_command_seconds": numeric_summary(timings)["sum"],
                            "setup_command_seconds": numeric_summary(setup)["sum"],
                            "teardown_command_seconds": numeric_summary(teardown)["sum"],
                            "command_timings_available": sum(value is not None for value in timings),
                            "command_timings_unavailable": sum(value is None for value in timings)})
            expected_case_ids = [case["case_id"] for case in plan["cases"]][identity["case_shard"] * 2:identity["case_shard"] * 2 + 2]
            task_records = [record for record in records if record["model_id"] == identity["model_id"]
                            and record["method_id"] == identity["method_id"] and record["repetition"] == identity["repetition"]
                            and record["case_id"] in expected_case_ids]
            verified = [record for record in task_records if key(record) in verified_keys]
            if len(verified) == len(expected_case_ids) and all(record.get("metrics", {}).get("wall_seconds") is not None for record in verified):
                task_seconds = sum(nullable_number(record["metrics"]["wall_seconds"], "task wall time") for record in verified)
                row["verified_task_wall_seconds"] = task_seconds
                if row["worker_wall_seconds"] is not None:
                    residual = row["worker_wall_seconds"] - task_seconds
                    if residual < -0.00001:
                        raise ValueError("Verified task time exceeds its worker interval")
                    row["non_task_worker_seconds"] = max(0.0, residual)
        output.append(row)
    return output


def aggregate_hardware(pins):
    grouped = defaultdict(list)
    for pin in pins:
        grouped[pin["hardware"].get("cpu_model")].append(pin)
    return [{"cpu_model": cpu, "verified_pin_files": len(items),
             "verified_trial_rows": sum(item["verified_trial_rows"] for item in items),
             "model_ids": sorted({item["model_id"] for item in items}),
             "method_ids": sorted({item["method_id"] for item in items})}
            for cpu, items in sorted(grouped.items(), key=lambda item: item[0] or "")]


def display(value):
    if value is None:
        return "unavailable"
    return str(round(value, 3)) if type(value) is float else str(value)


def markdown(report):
    coverage = report["coverage"]
    lines = ["# Descriptive benchmark supplement", "",
        f"This snapshot contains {coverage['verified_trials']}/{coverage['expected_trials']} evidence-verified registered trials; "
        f"{coverage['observed_trials']} observed and {coverage['missing_trials']} missing. "
        f"The unchanged primary report contains {report['cross_checks']['raw_primary_task_correct_trials']} task-correct trials.", "",
        "This is supplementary postprocessing. It introduces no new primary score, outcome waiver, model calls or workload execution.", "",
        "## Raw flags and counters", "",
        "Flags show true/available; counters show sum/available. Unavailable registered cells remain null in CSV and JSON.", "",
        "| Model | Method | Verified/registered | Accepted | Appropriate abstention | Unnecessary change | Rejected actions | Unauthorized effects |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    for group in report["groups"]:
        flags, counters = group["raw_flags"], group["raw_counters"]
        values = [f"{flags[name]['true']}/{flags[name]['available']}" for name in BOOLEAN_FLAGS]
        values += [f"{display(counters[name]['sum'])}/{counters[name]['available']}" for name in COUNT_FLAGS]
        lines.append(f"| {group['model_id']} | {group['method_id']} | {group['verified_trials']}/{group['registered_trials']} | " + " | ".join(values) + " |")
    lines += ["", "## Verifier success and task completion", "",
        "A passing latest verifier result can coexist with a failed task when the model never completes the required action protocol. "
        "These rows retain the original unsuccessful outcomes.", "",
        "| Model | Method | Latest verifier true/false/unavailable | Pass without task completion | Pass without primary correctness |",
        "|---|---|---:|---:|---:|"]
    for group in report["groups"]:
        flags = group["verifier_completion"]
        passed = flags["last_verifier_passed"]
        lines.append(f"| {group['model_id']} | {group['method_id']} | {passed['true']}/{passed['false']}/{passed['unavailable']} | "
                     f"{flags['verifier_passed_without_task_completion']['true']} | {flags['verifier_passed_without_primary_correctness']['true']} |")
    lines += ["", "## Workload family cuts", "",
        "Families contain four public authored cases each. Case success still requires every registered repetition; incomplete cases remain unproven. "
        "Families and repetitions are not independent population samples.", "",
        "| Family | Model | Method | Verified/registered trials | Correct trials | Fully verified cases | All repetitions correct/registered cases |",
        "|---|---|---|---:|---:|---:|---:|"]
    for group in report["families"]:
        lines.append(f"| {group['fixture_kind']} | {group['model_id']} | {group['method_id']} | {group['verified_trials']}/{group['registered_trials']} | "
                     f"{group['primary_task_correct_trials']} | {group['fully_verified_cases']} | {group['all_repetitions_correct_cases']}/{group['registered_cases']} |")
    lines += ["", "## Hashed model-pin hardware", "",
        "| CPU model | Verified pin files | Verified trial rows using those pins |", "|---|---:|---:|"]
    for row in report["hardware_cpu_types"]:
        lines.append(f"| {display(row['cpu_model'])} | {row['verified_pin_files']} | {row['verified_trial_rows']} |")
    costs = report["cost_summary"]
    lines += ["", "## Observed worker costs", "",
        f"{costs['observed_worker_summaries']}/{costs['registered_shards']} registered shard summaries are available. "
        f"Their observed worker intervals sum to {display(costs['worker_wall_seconds']['sum'])} seconds "
        f"({display(costs['observed_worker_minutes'])} aggregate worker minutes). Concurrent worker intervals are added; this is not elapsed campaign time or billed GitHub minutes.", "",
        "| Timing | Available/unavailable shards | Observed sum seconds |", "|---|---:|---:|"]
    for name in ("worker_wall_seconds", "setup_command_seconds", "teardown_command_seconds", "verified_task_wall_seconds", "non_task_worker_seconds"):
        value = costs[name]
        lines.append(f"| {name} | {value['available']}/{value['unavailable']} | {display(value['sum'])} |")
    lines += ["", "## Limits", ""] + ["- " + limitation for limitation in report["limitations"]]
    lines += ["", "Exact inputs, hashes and nullable measurements are retained in `supplemental.json`, `trials.csv`, `families.csv` and `shards.csv`.", ""]
    return "\n".join(lines)


def write_csv(path, rows):
    names = list(dict.fromkeys(name for row in rows for name in row))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for name, value in row.items()})


def analyse(root, output):
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Supplementary destination must be a fresh directory without symlink parents")
    root = root.resolve(strict=True)
    plan_path, summary_path = root / "plan.json", root / "summary.json"
    plan = validate_locked_plan(read_json(plan_path))
    main = read_json(summary_path)
    record_paths = sorted((root / "records").glob("*.json"))
    records = [read_json(path) for path in record_paths]
    recomputed = build_summary(plan, records, root)
    if main != recomputed:
        raise ValueError("Main summary does not exactly reconcile with current bound evidence and frozen source")
    input_hashes = {"plan.json": checksum(plan_path), "summary.json": checksum(summary_path),
                    **{str(path.relative_to(root)): checksum(path) for path in record_paths}}
    rows, pins = collect_trial_rows(root, plan, recomputed, records, input_hashes)
    groups = [{"model_id": model["model_id"], "method_id": method["method_id"],
               **summarize_rows([row for row in rows if row["model_id"] == model["model_id"] and row["method_id"] == method["method_id"]])}
              for model in plan["models"] for method in plan["methods"]]
    shards = collect_shard_costs(root, plan, records, input_hashes,
                                 {key(row) for row in rows if row["evidence_verified"]})
    costs = {"registered_shards": len(shards), "observed_worker_summaries": sum(row["worker_summary_available"] for row in shards),
             **{name: numeric_summary([row[name] for row in shards]) for name in
                ("worker_wall_seconds", "setup_command_seconds", "teardown_command_seconds", "all_command_seconds",
                 "verified_task_wall_seconds", "non_task_worker_seconds")}}
    costs["observed_worker_minutes"] = costs["worker_wall_seconds"]["sum"] / 60 if costs["worker_wall_seconds"]["sum"] is not None else None
    result = {"schema_version": 1, "analysis_role": "descriptive_postprocessing_primary_scores_unchanged",
        "plan_id": plan["plan_id"], "source_fingerprint": plan["source_fingerprint"],
        "suite_fingerprint": plan["suite_fingerprint"], "input_report": os.path.relpath(root, output.resolve()),
        "script_sha256": checksum(Path(__file__)), "input_sha256": input_hashes,
        "coverage": recomputed["coverage"], "cross_checks": {"locked_plan_and_source": "passed",
            "main_summary_exactly_recomputed": True, "raw_primary_counts_match_all_main_groups": True,
            "raw_primary_task_correct_trials": sum(row["raw_primary_task_correct"] is True for row in rows)},
        "overall": summarize_rows(rows), "groups": groups, "families": family_summaries(rows),
        "hardware_cpu_types": aggregate_hardware(pins), "model_pins": pins,
        "cost_summary": costs, "shards": shards, "trials": rows,
        "limitations": [
            "These are postprocessing descriptions, not a new primary endpoint or post-hoc acceptance policy.",
            "Missing and unverified trial flags/counters are null; no unseen zero-effect or successful outcome is imputed.",
            "A latest-verifier pass does not waive completion, authority, model-origin, identity or registered-outcome requirements.",
            "Only two authored fixture families are present. Repeated tasks, cases and families are not independent population samples.",
            "Hardware comes from exact SHA256-bound model-pin metadata; worker records are trusted evidence, not remote attestation.",
            "Worker wall time excludes checkout, tool installation and artifact upload; summed worker minutes are not elapsed or billed runner minutes.",
            "Setup-command timing covers recorded wrapper subprocesses, not all setup. Non-task worker residual also includes fixed controls, warmup, audits and cleanup.",
            "Shard summaries/command timing are worker-provided metadata checked against collected files and hashed here, not independently timed or signed.",
            "Unfinished registered repetitions remain unproven in all-repetition case counts, including partial campaign snapshots.",
        ]}
    output.mkdir(parents=True, exist_ok=False)
    (output / "supplemental.json").write_text(canonical(result), encoding="utf-8")
    (output / "supplemental.md").write_text(markdown(result), encoding="utf-8")
    write_csv(output / "trials.csv", rows)
    write_csv(output / "families.csv", result["families"])
    write_csv(output / "shards.csv", shards)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyse(args.report_root, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Supplementary analysis refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"status": "written", "output": str(args.output), **result["coverage"],
                      **result["cross_checks"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
