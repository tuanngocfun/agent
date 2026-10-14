"""Collect registered shard artifacts without dropping failed or missing cells."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kube_repair.artifacts import canonical, load_bundle
from kube_repair.benchmark_protocol import validate_locked_plan
from kube_repair.benchmark_reporting import generate_reports

SAFE_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,180}$")
PIN_PATH_FIELDS = ("bundle_path", "audit_path", "model_pin_path", "image_pins_path")
ROOT_FILES = {"plan.json", "suite.json", "summary.json", "progress.json", "commands.json",
              "model-pin.json", "image-pins.json"}
FOLDERS = {"cases", "records", "controls"}


def copy_shard(source, destination):
    """Copy only explicit textual evidence; never copy credentials or weights."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Shard must be a regular directory")
    destination.mkdir()
    count, total = 0, 0
    for file in source.rglob("*"):
        if file.is_symlink():
            raise ValueError("Shard contains a symlink")
        if not file.is_file():
            continue
        relative = file.relative_to(source)
        if (len(relative.parts) == 1 and relative.name not in ROOT_FILES
                or len(relative.parts) > 1 and relative.parts[0] not in FOLDERS):
            continue
        if relative.suffix not in (".json", ".md", ".diff"):
            raise ValueError("Unexpected evidence type: " + str(relative))
        data = file.read_bytes()
        data.decode("utf-8")
        total += len(data)
        count += 1
        if total > 50_000_000 or count > 500:
            raise ValueError("Shard evidence exceeds its collection limit")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def task_correct(report, expected):
    if expected == "abstain":
        return report.get("appropriate_abstention") is True
    return (report.get("accepted") is True and report.get("runtime_verified") is True
            and report.get("status") == ("unchanged" if expected == "unchanged" else "repaired")
            and report.get("unnecessary_change") is not True)


def fixed_control_report(plan, controls):
    expected_repeats = len(plan["models"]) * len(plan["methods"]) * plan["repetitions"]
    groups = []
    for strategy in plan["controls"]:
        cases = []
        for case in plan["cases"]:
            rows = [row for row in controls if row["control_id"] == strategy and row["case_id"] == case["case_id"]]
            complete = len(rows) == expected_repeats
            cases.append({"case_id": case["case_id"], "expected_outcome": case["expected_outcome"],
                          "expected_executions": expected_repeats, "observed_executions": len(rows),
                          "complete": complete, "task_correct_executions": sum(row["task_correct"] for row in rows),
                          "all_registered_executions_correct": complete and all(row["task_correct"] for row in rows),
                          "static_pass_executions": sum(row["static_pass"] is True for row in rows),
                          "behavior_pass_executions": sum(row["behavior_pass"] is True for row in rows),
                          "security_pass_executions": sum(row["security_pass"] is True for row in rows),
                          "infrastructure_failures": sum(bool(row["infrastructure_error"]) for row in rows)})
        groups.append({"control_id": strategy, "oracle": strategy == "known-good", "cases": cases,
                       "expected_cases": len(cases), "observed_cases": sum(row["observed_executions"] > 0 for row in cases),
                       "complete_cases": sum(row["complete"] for row in cases),
                       "all_registered_executions_correct_cases": sum(row["all_registered_executions_correct"] for row in cases)})
    return {"plan_id": plan["plan_id"], "groups": groups,
            "interpretation": "Repeated fixed controls across model jobs are execution replicates, not independent cases. Known-good is author-provided oracle; template and oracle repairs coincide on supported storage cases."}


def controls_markdown(summary):
    lines = ["# Fixed controls", "", summary["interpretation"], "",
             "A case is demonstrated correct only when every registered control execution is present and correct.", "",
             "| Control | Oracle | Observed cases | Complete cases | All executions task-correct cases |",
             "|---|---|---:|---:|---:|"]
    for group in summary["groups"]:
        n = group["expected_cases"]
        lines.append(f"| {group['control_id']} | {group['oracle']} | {group['observed_cases']}/{n} | {group['complete_cases']}/{n} | {group['all_registered_executions_correct_cases']}/{n} |")
    lines += ["", "Per-case behavior/static/security and failure counts are in `controls-summary.json`; raw bound control paths are in `controls.json`.", ""]
    return "\n".join(lines)


def collect(plan_path, shards_path, output):
    plan = validate_locked_plan(json.loads(plan_path.read_text()))
    output.mkdir(parents=True, exist_ok=False)
    evidence_root = output / "evidence"
    records_root = output / "records"
    evidence_root.mkdir()
    records_root.mkdir()
    (output / "plan.json").write_text(canonical(plan))
    expected_shards = {f"benchmark-{model['model_id']}-{method['method_id']}-r{repeat}-s{shard}"
                       for model in plan["models"] for method in plan["methods"]
                       for repeat in range(plan["repetitions"]) for shard in range(plan["case_shards"])}
    seen_cells, seen_shards, controls, shard_statuses = set(), set(), [], []
    seen_control_cells = set()
    case_map = {case["case_id"]: case for case in plan["cases"]}
    for shard in sorted(shards_path.iterdir()) if shards_path.exists() else []:
        if not shard.is_dir():
            continue
        if not SAFE_ID.fullmatch(shard.name) or shard.name not in expected_shards:
            raise ValueError("Unregistered shard: " + shard.name)
        if shard.name in seen_shards:
            raise ValueError("Duplicate shard")
        seen_shards.add(shard.name)
        shard_index = int(shard.name.rsplit("-s", 1)[1])
        shard_cases = {case["case_id"] for case in plan["cases"][2 * shard_index:2 * shard_index + 2]}
        target = evidence_root / shard.name
        copy_shard(shard, target)
        if (target / "plan.json").exists() and json.loads((target / "plan.json").read_text()) != plan:
            raise ValueError("Shard has a different frozen plan")
        summary = json.loads((target / "summary.json").read_text()) if (target / "summary.json").exists() else None
        shard_statuses.append({"shard": shard.name, "summary": summary})
        for path in sorted((target / "records").glob("*.json")):
            record = json.loads(path.read_text())
            cell = (record["model_id"], record["method_id"], record["case_id"], record["repetition"])
            if cell in seen_cells:
                raise ValueError("Duplicate registered task cell: " + repr(cell))
            seen_cells.add(cell)
            if f"benchmark-{cell[0]}-{cell[1]}-r{cell[3]}-s" not in shard.name:
                raise ValueError("Task record differs from shard identity")
            if cell[2] not in shard_cases:
                raise ValueError("Task case differs from the registered shard")
            for key in PIN_PATH_FIELDS:
                value = record.get("evidence", {}).get(key)
                if value is None:
                    continue
                relative = Path(value)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Evidence path escapes the shard")
                record["evidence"][key] = str(Path("evidence") / shard.name / relative)
            filename = "--".join(map(str, cell)) + ".json"
            (records_root / filename).write_text(canonical(record))
        for path in sorted((target / "controls").glob("*.json")):
            entry = json.loads(path.read_text())
            case_id, strategy = entry["case_id"], entry["control_id"]
            if case_id not in case_map or strategy not in plan["controls"]:
                raise ValueError("Unregistered fixed control")
            if case_id not in shard_cases or (shard.name, case_id, strategy) in seen_control_cells:
                raise ValueError("Duplicated or misplaced fixed control")
            seen_control_cells.add((shard.name, case_id, strategy))
            bundle = target / "controls" / f"{case_id}--{strategy}"
            binding, payloads = load_bundle(bundle)
            report = json.loads(payloads["report.json"])
            if report != entry["report"] or entry["bundle_review_hash"] != binding["review_hash"]:
                raise ValueError("Control record differs from its bound evidence")
            verification = report["verification"]
            controls.append({"shard": shard.name, "case_id": case_id, "control_id": strategy,
                             "oracle": strategy == "known-good", "expected_outcome": case_map[case_id]["expected_outcome"],
                             "task_correct": task_correct(report, case_map[case_id]["expected_outcome"]),
                             "accepted": report["accepted"], "status": report["status"],
                             "static_pass": verification.get("static_pass"),
                             "behavior_pass": verification.get("behavior_pass"),
                             "security_pass": verification.get("negative_pass"),
                             "infrastructure_error": verification.get("infrastructure_error"),
                             "bundle_path": str(bundle.relative_to(output)),
                             "bundle_review_hash": binding["review_hash"]})
    (output / "collection.json").write_text(canonical({
        "plan_id": plan["plan_id"], "expected_shards": len(expected_shards),
        "received_shards": len(seen_shards), "missing_shards": sorted(expected_shards - seen_shards),
        "task_records": len(seen_cells), "control_records": len(controls), "shards": shard_statuses}))
    (output / "controls.json").write_text(canonical(controls))
    control_summary = fixed_control_report(plan, controls)
    (output / "controls-summary.json").write_text(canonical(control_summary))
    (output / "controls.md").write_text(controls_markdown(control_summary))
    summary = generate_reports(plan_path, records_root, output, output / "statistics")
    for name in ("report.md", "summary.json", "trials.csv", "index.html"):
        shutil.copyfile(output / "statistics" / name, output / name)
    with (output / "report.md").open("a") as stream:
        stream.write("\n[Fixed-control comparison](controls.md) · [Control counts](controls-summary.json) · [Collection coverage](collection.json)\n")
    index = output / "index.html"
    text = index.read_text()
    fixed = "<section><h2>Fixed controls</h2><p>" + html.escape(control_summary["interpretation"]) + "</p><p><a href='controls.md'>Comparison table</a> · <a href='controls-summary.json'>Per-case statistics</a> · <a href='collection.json'>Shard coverage</a></p></section>"
    index.write_text(text.replace("</body>", fixed + "</body>"))
    shutil.rmtree(output / "statistics")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--shards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = collect(args.plan, args.shards, args.output)
    print(json.dumps({"status": "reported", **summary["coverage"]}))


if __name__ == "__main__":
    main()
