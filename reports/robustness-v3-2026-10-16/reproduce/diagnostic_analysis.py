#!/usr/bin/env python3
"""Offline, post hoc decoder diagnostics from actual worker artifacts.

This portable standard-library script reads an independently recomputed report
and its integrated raw artifact. It runs no model, container, cluster or network
operation. Primary outcomes are copied unchanged; raw outputs are descriptive
diagnostics, including when their primary evidence is invalid or incomplete.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import sys


COORDINATES = ("model_id", "method_id", "case_id", "condition", "repetition")
DECODERS = {
    "decoder-legacy": "original bounds and empty value schema",
    "decoder-unbounded": "bounds removed; empty value schema retained",
    "decoder-any-json": "bounds removed; explicit JSON type union",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(value):
    result = json.loads(value, object_pairs_hook=unique_object,
                        parse_constant=lambda value: (_ for _ in ()).throw(
                            ValueError("Nonfinite JSON constant: " + value)))
    canonical(result)
    return result


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 80_000_000:
        raise ValueError("Expected a bounded regular JSON file: " + str(path))
    return parse(path.read_text())


def coordinate(row):
    return tuple(row.get(name) for name in COORDINATES)


def nonnegative_integer(value):
    return type(value) is int and value >= 0


def finite_seconds(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def nanoseconds(value):
    return value / 1_000_000_000 if nonnegative_integer(value) else None


def value_type(value):
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise ValueError("Value is outside the JSON domain")


def compact_error(error):
    return type(error).__name__ + ": " + str(error)


def call_rows(primary, record, model, disagreements):
    rows, edits = [], []
    for index, call in enumerate((record.get("method_result") or {}).get("calls", [])):
        raw = call.get("raw_server_response")
        raw_present = isinstance(raw, str)
        raw_hash_matches = (hashlib.sha256(raw.encode()).hexdigest() == call.get("response_sha256")) if raw_present else call.get("response_sha256") is None
        server, envelope_error, decision, decision_error = {}, None, None, None
        if raw_present:
            try:
                server = parse(raw)
                if not isinstance(server, dict):
                    raise ValueError("Server response is not an object")
            except (TypeError, ValueError) as error:
                envelope_error = compact_error(error)
                server = {}
        if server:
            try:
                content = (server.get("message") or {}).get("content")
                if not isinstance(content, str):
                    raise ValueError("Server message.content is not text")
                decision = parse(content)
                if not isinstance(decision, dict):
                    raise ValueError("Generated decision is not an object")
            except (TypeError, ValueError, AttributeError) as error:
                decision_error = compact_error(error)
                decision = None
        identity_matches = server.get("model") == model.get("tag") if server else None
        if call.get("call_index") != index or not raw_hash_matches or identity_matches is False:
            disagreements.append({"cell": record.get("cell_id"), "call_index": index,
                                  "error": "Raw call index, hash or model identity mismatch"})
        identity = {name: primary[name] for name in COORDINATES}
        types = Counter()
        raw_edits = decision.get("edits") if decision else None
        if isinstance(raw_edits, list):
            for edit_index, edit in enumerate(raw_edits):
                if isinstance(edit, dict) and "value" in edit:
                    kind = value_type(edit["value"])
                    types[kind] += 1
                    edits.append({**identity, "call_index": index, "edit_index": edit_index,
                                  "primary_outcome": primary["outcome"],
                                  "primary_evidence_verified": primary["evidence_verified"],
                                  "call_status": call.get("status"), "resource": edit.get("resource"),
                                  "path": edit.get("path"), "value_type": kind,
                                  "value": canonical(edit["value"])})
        row = {**identity, "call_index": index,
               "primary_outcome": primary["outcome"],
               "primary_evidence_verified": primary["evidence_verified"],
               "call_status": call.get("status"), "call_error": call.get("error"),
               "raw_response_present": raw_present, "raw_hash_matches": raw_hash_matches,
               "model_identity_matches": identity_matches,
               "recorded_call_elapsed_seconds": nanoseconds(call.get("elapsed_ns")),
               "done": server.get("done"), "done_reason": server.get("done_reason"),
               "envelope_parse_error": envelope_error,
               "generated_decision_parse_error": decision_error,
               "generated_action": decision.get("action") if decision else None,
               "parsed_edit_count": sum(types.values()), "edit_value_types": dict(sorted(types.items()))}
        for raw_key, output_key in (("prompt_eval_count", "prompt_tokens"), ("eval_count", "completion_tokens")):
            value = server.get(raw_key)
            row[output_key] = value if nonnegative_integer(value) else None
        for raw_key, output_key in (("prompt_eval_duration", "prompt_seconds"),
                                    ("eval_duration", "generation_seconds"),
                                    ("load_duration", "load_seconds"),
                                    ("total_duration", "raw_total_seconds")):
            row[output_key] = nanoseconds(server.get(raw_key))
            row[raw_key + "_ns"] = server.get(raw_key) if nonnegative_integer(server.get(raw_key)) else None
        rows.append(row)
    return rows, edits


def write_csv(path, rows, required_fields):
    fields = list(required_fields) + sorted({key for row in rows for key in row} - set(required_fields))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: canonical(value) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})


def analyze(summary_path, artifact):
    summary = load(summary_path)
    plan = summary["plan"]
    if plan.get("campaign_kind") != "diagnostic":
        raise ValueError("This script accepts the registered decoder diagnostic only")
    if load(artifact / "plan.json") != plan:
        raise ValueError("Raw artifact plan differs from the independently recomputed summary")
    worker = load(artifact / "summary.json")
    for name in ("plan_id", "source_sha256"):
        if summary.get(name) != plan[name] or worker.get(name) != plan[name]:
            raise ValueError("Plan/source identity mismatch: " + name)
    if worker.get("stage") != "diagnostic":
        raise ValueError("Raw worker stage is not diagnostic")
    primary = {coordinate(row): row for row in summary["trials"]}
    registered = {coordinate(row): row for row in plan["cells"]}
    if len(primary) != len(summary["trials"]) or set(primary) != set(registered):
        raise ValueError("Audited trial rows do not exactly cover registered cells")
    observed = {}
    for path in sorted((artifact / "records").glob("*.json")):
        record = load(path)
        key = coordinate(record)
        if key not in registered or key in observed:
            raise ValueError("Duplicate or unregistered raw trial: " + str(key))
        if record.get("plan_id") != plan["plan_id"] or record.get("source_sha256") != plan["source_sha256"]:
            raise ValueError("Raw record is not bound to the registered plan/source")
        observed[key] = record
    models = {model["model_id"]: model for model in plan["models"]}
    cells, calls, edits, disagreements = [], [], [], []
    for key, cell in registered.items():
        audited, record = primary[key], observed.get(key)
        if type(audited.get("task_correct")) is not bool or type(audited.get("evidence_verified")) is not bool:
            raise ValueError("Audited score and evidence fields must be Boolean")
        if (record is None) != (audited.get("outcome") == "missing"):
            disagreements.append({"cell": cell.get("cell_id"), "error": "Raw presence disagrees with audited missing status"})
        row = {**{name: cell[name] for name in COORDINATES},
               "cell_id": cell.get("cell_id"), "decoder_treatment": DECODERS.get(cell["method_id"]),
               "expected": audited.get("expected"), "raw_record_present": record is not None,
               "outcome": audited["outcome"], "evidence_verified": audited["evidence_verified"],
               "model_origin_verified": audited.get("model_origin_verified"),
               "task_correct": audited["task_correct"], "evidence_error": audited.get("evidence_error"),
               "cell_wall_seconds": None, "observed_model_calls": None, "edit_value_types": {}}
        if record is not None:
            row.update(worker_status=record.get("status"),
                       method_status=(record.get("method_result") or {}).get("status"),
                       cell_wall_seconds=finite_seconds((record.get("metrics") or {}).get("wall_seconds")),
                       initial_runtime_pass=(record.get("initial_verification") or {}).get("passed"),
                       final_runtime_pass=(record.get("final_verification") or {}).get("passed"))
            current_calls, current_edits = call_rows(audited, record, models[cell["model_id"]], disagreements)
            calls.extend(current_calls); edits.extend(current_edits)
            row["observed_model_calls"] = len(current_calls)
            row["edit_value_types"] = dict(sorted(Counter(edit["value_type"] for edit in current_edits).items()))
        cells.append(row)
    controls, raw_controls = [], {}
    for path in sorted((artifact / "controls").glob("*.json")):
        raw = load(path)
        key = (raw.get("case_id"), raw.get("control_id"))
        if key in raw_controls:
            raise ValueError("Duplicate raw deterministic control")
        raw_controls[key] = raw
    expected_controls = {(case["id"], mode) for case in plan["cases"] for mode in plan["controls"]}
    audited_controls = {(row["case_id"], row["control_id"]): row for row in summary["controls"]["rows"]}
    if set(audited_controls) != expected_controls or not set(raw_controls).issubset(expected_controls):
        raise ValueError("Control inventory differs from the frozen diagnostic")
    for key in sorted(expected_controls):
        audited, raw = audited_controls[key], raw_controls.get(key)
        controls.append({**audited, "raw_record_present": raw is not None,
                         "worker_runtime_pass": (raw.get("verification") or {}).get("passed") if raw else None,
                         "namespace_deleted": (raw.get("cleanup") or {}).get("namespace_deleted") if raw else None})
    if summary["coverage"]["observed_trials"] != len(observed):
        disagreements.append({"error": "Raw record count differs from primary observed coverage"})
    source_hashes = {"analysis_script": file_hash(Path(__file__).resolve()),
                     "independently_recomputed_summary": file_hash(summary_path)}
    for path in sorted(artifact.rglob("*.json")):
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != artifact.parent):
            raise ValueError("Symlink in artifact input: " + str(path))
        source_hashes["artifact/" + path.relative_to(artifact).as_posix()] = file_hash(path)
    raw_types = Counter(edit["value_type"] for edit in edits)
    observed_usage = {}
    for key in ("prompt_tokens", "completion_tokens", "prompt_eval_duration_ns", "eval_duration_ns", "load_duration_ns", "total_duration_ns"):
        available = [row[key] for row in calls if row.get(key) is not None]
        observed_usage[key] = {"available_calls": len(available), "total_observed_calls": len(calls),
                               "observed_sum": sum(available) if available else None}
    return {"schema_version": "decoder-diagnostic-supplement-v1", "post_hoc": True,
            "plan_id": plan["plan_id"], "source_sha256": plan["source_sha256"],
            "primary_coverage_unchanged": summary["coverage"],
            "primary_groups_unchanged": summary["groups"],
            "worker": {"status": worker.get("status"), "elapsed_seconds": finite_seconds(worker.get("seconds")),
                       "record_count": worker.get("record_count"), "control_count": worker.get("control_count"),
                       "cleanup": worker.get("cleanup"), "errors": worker.get("errors")},
            "cells": cells, "calls": calls, "edits": edits, "controls": controls,
            "observed_edit_value_types": dict(sorted(raw_types.items())),
            "observed_done_reasons": dict(sorted(Counter(str(row["done_reason"]) for row in calls if row["raw_response_present"]).items())),
            "returned_raw_calls": sum(row["raw_response_present"] for row in calls),
            "observed_usage": observed_usage, "input_consistency_disagreements": disagreements,
            "source_files_sha256": source_hashes,
            "limitations": [
                "This is a post hoc engineering diagnostic on two selected cases, not a broader robustness or model ranking study.",
                "Task outcomes are copied from the independently recomputed summary and are never rescored by these supplemental counts.",
                "Raw parsed edit types include rejected, truncated or otherwise invalid decisions; consult primary evidence/outcome columns before interpreting them.",
                "Call elapsed, prompt, generation, load and raw total times have different scopes; none is substituted for another.",
                "Observed token/timing sums cover returned counters only. No response, unavailable counters and not-started cells are never imputed as zero.",
                "Fresh namespaces, different observations, hardware variation and prefix caching are not isolated by two reversed execution orders.",
                "Worker elapsed excludes Actions checkout, tool installation, reporting, upload, queue time and other job overhead.",
                "No v2 scores, denominators or method rankings are replaced, pooled or altered.",
            ]}


def markdown(result):
    lines = ["# Post hoc decoder diagnostic", "", "Primary audited scores are unchanged. This is a two-case engineering diagnostic.", "",
             "| Case | Decoder | Primary outcome | Verified | Correct | Cell wall seconds | Parsed edit types |",
             "|---|---|---|---|---|---:|---|"]
    for row in result["cells"]:
        values = (row["case_id"], row["method_id"], row["outcome"], row["evidence_verified"],
                  row["task_correct"], row["cell_wall_seconds"], canonical(row["edit_value_types"]))
        lines.append("| " + " | ".join(str(value).replace("|", "&#124;") for value in values) + " |")
    lines += ["", "Worker elapsed seconds: " + str(result["worker"]["elapsed_seconds"]) + ".",
              "Input consistency disagreements: " + str(len(result["input_consistency_disagreements"])) + ".", "",
              "The CSVs contain every observed call's recorded wall, prompt, generation, load and raw total durations, token counts, done reason and errors. `controls.csv` preserves all registered control outcomes. `diagnostic.json` contains source SHA256 hashes and full provenance.", "",
              *["- " + value for value in result["limitations"]]]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True, help="Independently recomputed summary.json")
    parser.add_argument("--artifact", type=Path, required=True, help="Integrated raw diagnostic worker directory")
    parser.add_argument("--output", type=Path, required=True, help="Fresh supplemental output directory")
    args = parser.parse_args(argv)
    if args.artifact.is_symlink() or not args.artifact.is_dir():
        parser.error("Artifact must be a regular directory")
    if args.output.exists() or any(path.is_symlink() for path in args.output.parents):
        parser.error("Output must be fresh and have no symlink ancestors")
    try:
        result = analyze(args.summary.resolve(), args.artifact.resolve())
        args.output.mkdir(parents=True)
        (args.output / "diagnostic.json").write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
        (args.output / "README.md").write_text(markdown(result))
        for name in ("cells", "calls", "edits", "controls"):
            required = ("case_id", "control_id") if name == "controls" else COORDINATES
            write_csv(args.output / (name + ".csv"), result[name], required)
        files = sorted(path for path in args.output.iterdir() if path.is_file())
        (args.output / "SHA256SUMS").write_text("".join(file_hash(path) + "  " + path.name + "\n" for path in files))
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        parser.exit(2, "Diagnostic supplement refused: " + compact_error(error) + "\n")
    print(json.dumps({"output": str(args.output), "registered_cells": len(result["cells"]),
                      "actual_calls": len(result["calls"]), "controls": len(result["controls"]),
                      "consistency_disagreements": len(result["input_consistency_disagreements"]),
                      "primary_scores_changed": False}, sort_keys=True))
    return 0 if not result["input_consistency_disagreements"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
