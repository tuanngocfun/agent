"""Run a small lab without installing frameworks or starting infrastructure."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import canonical, export_bundle, load_bundle
from .engine import run_baseline, run_task
from .providers import OllamaProvider, ScriptedProvider
from .scenarios import get_scenario, scenario_names
from .verification import resolve_local_image

ROOT = Path(__file__).resolve().parents[2]


def _output(prefix):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return ROOT / "runs" / f"{prefix}-{timestamp}"


def _provider(args):
    if args.provider == "scripted":
        return ScriptedProvider()
    if args.provider == "session":
        from .session_provider import SessionProvider
        if not args.exchange_dir:
            raise ValueError("--exchange-dir is required for the external session decision bridge")
        if not args.decision_source:
            raise ValueError("--decision-source is required to label the external session controller")
        return SessionProvider(args.exchange_dir.resolve(), decision_source=args.decision_source)
    if not args.model:
        raise ValueError("--model is required for --provider ollama; no server is started automatically")
    return OllamaProvider(model=args.model, endpoint=args.endpoint, decoding_mode=args.decoding_mode)


def _print_run(report, binding, output):
    print(canonical({
        "output": str(Path(output).resolve()), "scenario": report["scenario"],
        "status": report["status"], "accepted": report["accepted"],
        "backend": report["backend"], "runtime_verified": report["runtime_verified"],
        "provider": report["provider"]["name"], "review_hash": binding["review_hash"],
    }), end="")


def _scenario(args):
    image = resolve_local_image(args.image) if args.backend == "docker" else None
    identity = (os.geteuid(), os.getegid()) if args.backend == "linux" else None
    if args.backend == "kubernetes":
        if not args.kube_context or not args.expected_image_id:
            raise ValueError("Kubernetes requires --kube-context and --expected-image-id from the trusted fixture setup")
        image = args.image
    scenario = get_scenario(args.scenario, getattr(args, "attacked", False), image=image, host_identity=identity)
    if args.backend == "kubernetes":
        scenario.contract["kubernetes"] = {
            "context": args.kube_context,
            "kubeconfig": str(args.kubeconfig.resolve()) if args.kubeconfig else None,
            "kubectl": args.kubectl,
            "expected_image_id": args.expected_image_id,
        }
    return scenario


def _demo(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for name in scenario_names():
        scenario = get_scenario(name)
        for strategy in ("noop", "naive", "template", "known-good", "scripted"):
            path = output / name / strategy
            if strategy == "scripted":
                report, _ = run_task(scenario, ScriptedProvider(), path)
            else:
                report, _ = run_baseline(scenario, strategy, path)
            rows.append({
                "scenario": name, "strategy": strategy,
                "status": report["status"], "accepted": report["accepted"],
                "static_pass": report["verification"]["static_pass"],
                "behavior_pass": report["verification"]["behavior_pass"],
                "appropriate_abstention": report["appropriate_abstention"],
                "bundle": str(path.relative_to(output)),
            })
    summary = {
        "claim": "Teaching demo: deterministic policies and simulated fixture semantics; "
                 "no LLM, container, Kubernetes, Checkov or held-out study was executed.",
        "runs": rows,
    }
    (output / "summary.json").write_text(canonical(summary))
    lines = ["# Simulated teaching demo", "", summary["claim"], "",
             "| Scenario | Strategy | Outcome | Static | Behavior | Appropriate abstention |",
             "|---|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['scenario']} | [{row['strategy']}]({row['bundle']}/REVIEW.md) | "
                     f"{row['status']} | {row['static_pass']} | {row['behavior_pass']} | "
                     f"{row['appropriate_abstention']} |")
    lines += ["", "`known-good` is an oracle control. `template` uses one fixed storage group. "
              "`scripted` uses feedback and metadata with hand-written rules. "
              "These fixtures share a synthetic application history and provide no evidence of generalization."]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print(f"Demo saved: {output / 'SUMMARY.md'}")
    expected = {"cache-path": "repaired", "volume-permissions": "repaired",
                "authority-limit": "abstained", "already-secure": "unchanged"}
    return 0 if all(row["status"] == expected[row["scenario"]] for row in rows if row["strategy"] == "scripted") else 1


def parser():
    p = argparse.ArgumentParser(description="Bounded Kubernetes-manifest security repair lab")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="List synthetic teaching scenarios")
    demo = sub.add_parser("demo", help="Run teaching comparisons; no LLM or runtime")
    demo.add_argument("--output", type=Path)
    run = sub.add_parser("run", help="Run the bounded investigator")
    baseline = sub.add_parser("baseline", help="Run a fixed control")
    for cmd in (run, baseline):
        cmd.add_argument("--scenario", choices=scenario_names(), default="cache-path")
        cmd.add_argument("--backend", choices=("simulated", "docker", "kubernetes"), default="simulated")
        cmd.add_argument("--image", default="repair-cache-app:lab", help="Trusted fixture image, Docker only; must already exist locally")
        cmd.add_argument("--output", type=Path)
        cmd.add_argument("--kube-context", help="Explicit lab context; global current-context is never changed")
        cmd.add_argument("--kubeconfig", type=Path)
        cmd.add_argument("--kubectl", help="Optional path to kubectl")
        cmd.add_argument("--expected-image-id", help="Trusted fixture image ID observed during setup, sha256 digest")
    run.add_argument("--provider", choices=("scripted", "ollama", "session"), default="scripted")
    run.add_argument("--exchange-dir", type=Path, help="Project runs directory for live external session decisions")
    run.add_argument("--decision-source", help="Explicit declaration of the external controller's origin")
    run.add_argument("--model")
    run.add_argument("--endpoint", default="http://localhost:11434")
    run.add_argument("--decoding-mode", choices=("json", "schema", "compact-schema"), default="json",
                     help="Ollama response decoding; compact-schema constrains the action envelope")
    run.add_argument("--attacked", action="store_true")
    run.add_argument("--max-actions", type=int, default=12)
    run.add_argument("--max-repairs", type=int, default=3)
    run.add_argument("--progress-output", type=Path, help="Fresh file for nonexportable, incremental action evidence")
    baseline.add_argument("--strategy", choices=("noop", "naive", "template", "known-good"), required=True)
    review = sub.add_parser("review", help="Verify review bundle contents and print bound hash")
    review.add_argument("--bundle", type=Path, required=True)
    export = sub.add_parser("export", help="Explicit local export, no deployment or PR")
    export.add_argument("--bundle", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--expected-hash", required=True)
    export.add_argument("--base", type=Path, help="Optional current base Deployment JSON for version revalidation")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "list":
            print("\n".join(scenario_names()))
            return 0
        if args.command == "demo":
            return _demo(args.output or _output("demo"))
        if args.command == "review":
            binding, contents = load_bundle(args.bundle)
            report = json.loads(contents["report.json"])
            print(canonical({"review_hash": binding["review_hash"], "status": report["status"],
                             "backend": report["backend"], "runtime_verified": report["runtime_verified"],
                             "already_exported": (args.bundle / "exported.json").exists(),
                             "base_hash": binding["base_hash"], "candidate_hash": binding["candidate_hash"]}), end="")
            return 0
        if args.command == "export":
            print(canonical(export_bundle(args.bundle, args.output, args.expected_hash, args.base)), end="")
            return 0
        scenario = _scenario(args)
        output = args.output or _output(args.scenario)
        if args.command == "run":
            report, binding = run_task(scenario, _provider(args), output, args.backend,
                                       args.max_actions, args.max_repairs, progress_output=args.progress_output)
        else:
            report, binding = run_baseline(scenario, args.strategy, output, args.backend)
        _print_run(report, binding, output)
        return 0 if report["accepted"] or report["appropriate_abstention"] else 1
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
