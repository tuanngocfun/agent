"""Exercise CLI behavior without a model server or container runtime.

Pass a new validation output directory. This intentionally tampers with a
separate control bundle and checks that its old review becomes invalid.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONPATH=str(root / "src"))
    records = []

    def run(name, arguments, expected):
        cmd = [sys.executable, "-m", "kube_repair"] + [str(a) for a in arguments]
        result = subprocess.run(cmd, cwd=root, env=env, text=True, capture_output=True, timeout=30)
        record = {"check": name, "argv": cmd, "expected_exit": expected,
                  "actual_exit": result.returncode, "passed": result.returncode == expected,
                  "stdout": result.stdout, "stderr": result.stderr}
        records.append(record)
        if not record["passed"]:
            raise RuntimeError(f"CLI check failed: {name}: {result.stdout} {result.stderr}")
        return result

    try:
        run("scenario-list", ["list"], 0)
        run("twenty-simulated-controls", ["demo", "--output", output / "demo"], 0)
        run("no-output-overwrite", ["demo", "--output", output / "demo"], 2)
        bundle = output / "single-repair"
        run("bounded-repair", ["run", "--scenario", "cache-path", "--output", bundle], 0)
        review = run("review-integrity", ["review", "--bundle", bundle], 0)
        reviewed_hash = json.loads(review.stdout)["review_hash"]
        run("local-export", ["export", "--bundle", bundle, "--output", output / "export",
                             "--expected-hash", reviewed_hash], 0)
        run("replay-refused", ["export", "--bundle", bundle, "--output", output / "replayed-export",
                               "--expected-hash", reviewed_hash], 2)
        tamper = output / "tamper-control"
        run("tamper-control-setup", ["run", "--output", tamper], 0)
        candidate = tamper / "candidate.json"
        candidate.write_bytes(candidate.read_bytes() + b"\n")
        run("changed-artifact-refused", ["review", "--bundle", tamper], 2)
        run("naive-behavior-regression", ["baseline", "--scenario", "cache-path", "--strategy", "naive",
                                          "--output", output / "naive-control"], 1)
        run("appropriate-authority-abstention", ["baseline", "--scenario", "authority-limit",
                                                 "--strategy", "known-good", "--output", output / "authority-control"], 0)
        run("model-selection-required", ["run", "--provider", "ollama", "--output", output / "no-model"], 2)
    finally:
        (output / "cli-checks.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"{len(records)} CLI checks passed: {output / 'cli-checks.json'}")


if __name__ == "__main__":
    main()
