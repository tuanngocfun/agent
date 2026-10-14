"""Create a fresh pre-evaluation plan, or verify an existing frozen plan."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kube_repair.artifacts import canonical
from kube_repair.benchmark_protocol import make_plan, validate_locked_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "benchmark/models.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if bool(args.output) == bool(args.check):
        parser.error("Select exactly one of --output or --check")
    if args.check:
        plan = validate_locked_plan(json.loads(args.check.read_text()))
    else:
        plan = make_plan(json.loads(args.registry.read_text()))
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(canonical(plan))
    print(json.dumps({"status": "validated", "plan_id": plan["plan_id"],
                      "expected_model_tasks": plan["primary_expected_model_tasks"]}))


if __name__ == "__main__":
    main()
