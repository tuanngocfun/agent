#!/usr/bin/env python3
"""Generate portable reports from registered, evidence-bound benchmark cells."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kube_repair.benchmark_reporting import generate_reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path,
                        help="Fresh report directory; existing results are never overwritten")
    args = parser.parse_args(argv)
    try:
        summary = generate_reports(args.plan, args.records, args.evidence_root, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"Benchmark report refused: {type(exc).__name__}: {exc}\n")
    print(json.dumps({"status": "written", "output": str(args.output), **summary["coverage"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
