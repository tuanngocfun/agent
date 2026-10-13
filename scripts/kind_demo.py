"""Build a trusted fixture and run a real Kubernetes demo on a Docker worker.

No sudo, global kubeconfig change, cloud deployment or model download. The only
cluster removed is the uniquely named cluster created by this invocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kube_repair.artifacts import source_fingerprint
from kube_repair.scenarios import get_scenario

NODE_IMAGE = "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a"
PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}$")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True, help="Trusted local Python base image, repository@sha256:digest")
    parser.add_argument("--node-image", default=NODE_IMAGE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("scripted", "ollama", "session"), default="scripted")
    parser.add_argument("--model")
    parser.add_argument("--endpoint", default="http://localhost:11434")
    parser.add_argument("--exchange-dir", type=Path)
    args = parser.parse_args(argv)
    if not PIN.fullmatch(args.base_image) or not PIN.fullmatch(args.node_image):
        parser.error("Base and node images must include exact sha256 digests")
    if args.provider == "ollama" and not args.model:
        parser.error("Ollama requires --model and an existing server")
    if args.provider == "session" and not args.exchange_dir:
        parser.error("Session requires --exchange-dir for live assistant responses")
    binaries = {name: shutil.which(name) for name in ("docker", "kind", "kubectl")}
    absent = [name for name, binary in binaries.items() if not binary]
    if absent:
        parser.error("Worker is missing: " + ", ".join(absent) + ". No cluster was created.")
    output = args.output.resolve()
    if output.exists():
        parser.error("Use a new output directory")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), KIND_EXPERIMENTAL_PROVIDER="docker")
    logs = []
    created = False
    success = False
    failure = None
    cluster = "repair-demo-" + uuid.uuid4().hex[:12]
    kubeconfig = output / "private-kubeconfig"
    context = "kind-" + cluster

    def run(command, *, input_value=None, expected=0, timeout=90, live=False):
        payload = json.dumps(input_value).encode() if input_value is not None else None
        try:
            result = subprocess.run([str(a) for a in command], cwd=ROOT, env=env, input=payload,
                                    capture_output=not live, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            logs.append({"argv": [str(a) for a in command], "expected_exit": expected,
                         "actual_exit": None, "timed_out": True, "timeout_seconds": timeout,
                         "live_output": live,
                         "stdout": (exc.stdout or b"").decode("utf-8", "replace")[-6000:],
                         "stderr": (exc.stderr or b"").decode("utf-8", "replace")[-6000:]})
            raise
        record = {"argv": [str(a) for a in command], "expected_exit": expected,
                  "actual_exit": result.returncode, "live_output": live,
                  "stdout": (result.stdout or b"").decode("utf-8", "replace")[-6000:],
                  "stderr": (result.stderr or b"").decode("utf-8", "replace")[-6000:]}
        logs.append(record)
        if result.returncode != expected:
            raise RuntimeError("Command failed: " + str(command[0]) + ": " + record["stderr"])
        return (result.stdout or b"").decode("utf-8", "replace")

    # Read-only worker checks before creating artifacts or resources.
    try:
        run([binaries["docker"], "info", "--format", "{{.ServerVersion}}"], timeout=10)
        run([binaries["docker"], "image", "inspect", args.base_image, "--format", "{{.Id}}"], timeout=10)
        run([binaries["docker"], "image", "inspect", args.node_image, "--format", "{{.Id}}"], timeout=10)
    except Exception as exc:
        print(f"Worker preflight failed: {exc}. No cluster was created.", file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=False)
    fingerprint = source_fingerprint()
    fixture_tag = "repair-cache-app:demo-" + fingerprint[:16] + "-" + uuid.uuid4().hex[:8]
    fixture_snapshot = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (ROOT / "fixtures" / "cache_app").glob("*") if p.is_file()}
    config = output / "kind-config.json"
    config.write_text(json.dumps({"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "nodes": [
        {"role": "control-plane"}], "networking": {"apiServerAddress": "127.0.0.1"}}, indent=2) + "\n")
    k = [binaries["kubectl"], "--context", context, "--kubeconfig", str(kubeconfig), "--request-timeout=10s"]
    expected_image = None
    try:
        run([binaries["docker"], "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE=" + args.base_image,
             "-t", fixture_tag, str(ROOT / "fixtures" / "cache_app")], timeout=120)
        created = True  # even a timed-out create may leave this uniquely named cluster
        run([binaries["kind"], "create", "cluster", "--name", cluster, "--image", args.node_image,
             "--config", config, "--kubeconfig", kubeconfig, "--wait", "120s"], timeout=180)
        kubeconfig.chmod(0o600)
        run([binaries["kind"], "load", "docker-image", fixture_tag, "--name", cluster], timeout=90)
        # Establish the CRI image identity inside this private cluster. A Docker
        # config digest must not be guessed equivalent to a Kubernetes imageID.
        pin_namespace = "repair-pin-" + uuid.uuid4().hex[:12]
        run(k + ["create", "namespace", pin_namespace])
        pin_fixture = get_scenario("already-secure", image=fixture_tag).base
        pin_fixture["metadata"]["namespace"] = pin_namespace
        run(k + ["-n", pin_namespace, "apply", "-f", "-"], input_value=pin_fixture)
        run(k + ["-n", pin_namespace, "rollout", "status", "deployment/repair-cache-app", "--timeout=60s"], timeout=70)
        pods = json.loads(run(k + ["-n", pin_namespace, "get", "pods", "-l", "app=repair-cache-app", "-o", "json"]))["items"]
        if len(pods) != 1:
            raise RuntimeError("Image-pin setup did not produce exactly one pod")
        status = next(s for s in pods[0]["status"]["containerStatuses"] if s["name"] == "app")
        if not status.get("ready") or not re.search(r"sha256:[0-9a-f]{64}$", status.get("imageID", "")):
            raise RuntimeError("No trustworthy runtime image identity from setup")
        expected_image = status["imageID"]
        (output / "image-pin.json").write_text(json.dumps({"source_fingerprint": fingerprint,
            "fixture_files": fixture_snapshot, "fixture_tag": fixture_tag, "runtime_image_id": expected_image,
            "pod_uid": pods[0]["metadata"]["uid"], "base_image": args.base_image, "node_image": args.node_image}, indent=2) + "\n")
        run(k + ["delete", "namespace", pin_namespace, "--wait=true", "--timeout=30s"], timeout=40)
        common = ["--scenario", "cache-path", "--backend", "kubernetes", "--kube-context", context,
                  "--kubeconfig", kubeconfig, "--kubectl", binaries["kubectl"], "--image", fixture_tag,
                  "--expected-image-id", expected_image]
        for strategy, expected_exit in (("noop", 1), ("naive", 1), ("known-good", 0)):
            run([sys.executable, "-m", "kube_repair", "baseline", *common, "--strategy", strategy,
                 "--output", output / "results" / strategy], expected=expected_exit, timeout=90)
        agent_args = [sys.executable, "-m", "kube_repair", "run", *common, "--provider", args.provider,
                      "--output", output / "results" / "agent",
                      "--progress-output", output / "results" / "agent-progress.json"]
        if args.provider == "ollama":
            agent_args += ["--model", args.model, "--endpoint", args.endpoint]
        elif args.provider == "session":
            agent_args += ["--exchange-dir", args.exchange_dir, "--decision-source", "current_assistant_session"]
        run(agent_args, timeout=1800 if args.provider in ("session", "ollama") else 360, live=True)
        reports = {name: json.loads((output / "results" / name / "report.json").read_text())
                   for name in ("noop", "naive", "known-good", "agent")}
        if not (reports["noop"]["verification"]["behavior_pass"] and not reports["noop"]["accepted"]
                and reports["naive"]["verification"]["static_pass"] and not reports["naive"]["verification"]["behavior_pass"]
                and reports["naive"]["status"] == "failed" and reports["known-good"]["accepted"]
                and reports["agent"]["accepted"] and reports["agent"]["runtime_verified"]):
            raise RuntimeError("Demo controls did not distinguish a safe repair from a behavior regression")
        success = True
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        if created:
            try:
                run([binaries["kind"], "export", "logs", "--name", cluster, output / "cluster-logs"], timeout=30)
            except Exception:
                pass  # evidence collection failure does not prevent cleanup
            try:
                run([binaries["kind"], "delete", "cluster", "--name", cluster], timeout=60)
            except Exception as exc:
                success = False
                failure = (failure + "; " if failure else "") + f"Cluster cleanup failed: {exc}"
        # Never retain usable credentials in shareable run artifacts.
        kubeconfig.unlink(missing_ok=True)
        (output / "commands.json").write_text(json.dumps(logs, indent=2) + "\n")
        summary = {"status": "passed" if success else "failed", "backend": "kubernetes",
                   "provider": args.provider, "runtime_image_id": expected_image,
                   "source_fingerprint": fingerprint, "node_image": args.node_image,
                   "base_image": args.base_image, "error": failure, "cluster_cleanup_requested": created,
                   "claim": "One trusted synthetic fixture on real Kubernetes; no generalization or benchmark claim."}
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
