"""Create a fresh robustness plan or validate an existing frozen plan offline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kube_robustness_v3.methods import strict_json
from kube_robustness_v3.protocol import build_plan, validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--output", type=Path, help="Write a new plan; refuse an existing target")
    target.add_argument("--check", type=Path, help="Validate a plan without changing files")
    parser.add_argument("--campaign", choices=("diagnostic", "full"), default="full")
    arguments = parser.parse_args()
    if arguments.check:
        plan = strict_json(arguments.check.read_bytes())
        validate_plan(plan)
        print(json.dumps({"validated": True, "plan_id": plan["plan_id"], "source_sha256": plan["source_sha256"]}))
        return
    plan = build_plan(arguments.campaign)
    output = arguments.output
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("The plan output parent must be an existing real directory")
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(plan, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(json.dumps({"frozen": True, "plan_id": plan["plan_id"], "case_count": plan["case_count"],
                      "cell_count": plan["cell_count"], "max_model_calls": plan["budget"]["max_model_calls"]}))


if __name__ == "__main__":
    main()
