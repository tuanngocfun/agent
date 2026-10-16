"""Run a registered robustness shard on disposable Kubernetes and a real CPU LLM."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_worker import atomic_json, canonical_digest, http as legacy_http, sha256_file
from kube_repair.kubernetes_backend import image_digest
from kube_robustness_v3 import budget as limits
from kube_robustness_v3.budget import hard_phase, current_phase_deadline
from kube_robustness_v3.methods import METHODS, OllamaProvider, apply_edits, canonical, run_method, sha256, strict_json
from kube_robustness_v3.protocol import condition_case, validate_plan
from kube_robustness_v3.runtime import KubernetesSession


class Deadline(BaseException):
    pass


FINALIZATION_SECONDS = 10
PROCESSING_SECONDS = limits.BOOKKEEPING_SECONDS - FINALIZATION_SECONDS


def execution_seconds(plan, stage, shard=0):
    """Reserve cleanup and finalization inside the unrounded worker bound."""
    if stage == "validate":
        worker_seconds = (limits.SETUP_SECONDS
                          + len(plan["cases"]) * len(plan["controls"]) * limits.CONTROL_SECONDS
                          + limits.GLOBAL_CLEANUP_SECONDS + limits.BOOKKEEPING_SECONDS)
    else:
        worker_seconds = plan["budget"]["capacity"][shard]["worker_seconds"]
    seconds = worker_seconds - limits.GLOBAL_CLEANUP_SECONDS - FINALIZATION_SECONDS
    if seconds <= 0 or PROCESSING_SECONDS <= 0:
        raise ValueError("Worker bound cannot reserve cleanup and finalization")
    return seconds


@contextmanager
def restoring_signal_handlers(old_alarm, old_term):
    """Restore process handlers even when cleanup or evidence writing expires."""
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)


def raw_metrics(result, seconds):
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "generation_ns": 0}
    complete = True
    for call in result["calls"]:
        try:
            raw = strict_json(call["raw_server_response"])
            values = {"prompt_tokens": raw["prompt_eval_count"], "completion_tokens": raw["eval_count"], "generation_ns": raw["eval_duration"]}
            if any(type(value) is not int or value < 0 for value in values.values()):
                raise ValueError("Invalid usage")
            for key, value in values.items():
                totals[key] += value
        except (ValueError, TypeError, KeyError):
            complete = False
    return {"wall_seconds": seconds, "model_calls": len(result["calls"]),
            **{key: value if complete else None for key, value in totals.items()}, "usage_complete": complete}


def baseline_edits(case, mode):
    if mode == "oracle":
        return case["oracle_edits"]
    if mode == "noop":
        return []
    fixed = {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
             "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
             "drop": ["ALL"], "type": "RuntimeDefault"}
    edits = []
    for resource, paths in case["allowed_paths"].items():
        for path in paths:
            leaf = path.rsplit("/", 1)[-1]
            if leaf in fixed:
                edits.append({"resource": resource, "path": path, "value": fixed[leaf]})
            elif mode == "template" and leaf == "readOnly":
                edits.append({"resource": resource, "path": path, "value": False})
    return edits



def allowance(seconds, name):
    """One cumulative phase allowance shared across separated work segments."""
    spent = 0.0
    @contextmanager
    def phase():
        nonlocal spent
        began = time.monotonic()
        remaining = seconds - spent
        if remaining <= 0:
            raise TimeoutError("Cumulative phase exhausted: " + name)
        try:
            with hard_phase(remaining, name):
                yield
        finally:
            spent += time.monotonic() - began
    return phase


def http(url, method="GET", data=None, timeout=30):
    phase_deadline = current_phase_deadline()
    remaining = timeout if phase_deadline is None else min(timeout, phase_deadline - time.monotonic())
    if remaining <= 0:
        raise TimeoutError("HTTP phase deadline exhausted")
    return legacy_http(url, method, data, timeout=remaining)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--stage", choices=["validate", "models", "diagnostic"], required=True)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = strict_json(args.plan.read_text())
    validate_plan(plan)
    if args.shard not in range(plan["settings"]["shards"]):
        parser.error("Shard is outside the registered campaign")
    if (args.stage == "diagnostic") != (plan["campaign_kind"] == "diagnostic"):
        parser.error("Diagnostic and full-study stages require their own registered plan")
    binaries = {name: shutil.which(name) for name in ("docker", "kind", "kubectl")}
    if not all(binaries.values()):
        parser.error("Real docker/kind/kubectl required; no simulation fallback")
    output = args.output.resolve()
    if output.exists() or any(path.is_symlink() for path in output.parents):
        parser.error("A fresh output without symlink ancestors is required")
    output.mkdir(parents=True)
    for name in ("records", "controls"):
        (output / name).mkdir()
    atomic_json(output / "plan.json", plan)
    commands, records, controls, errors = [], [], [], []
    cluster = "robustness-" + uuid.uuid4().hex[:12]
    model_container = "robust-model-" + uuid.uuid4().hex[:12]
    context = "kind-" + cluster
    kubeconfig = output / "private-kubeconfig"
    model_cache = ROOT / ".tools" / ("robustness-model-" + uuid.uuid4().hex[:12])
    fixture_image = "robustness-python:" + plan["images"]["base"].split("sha256:")[1][:12]
    model = plan["models"][0]
    image_pins, model_pin = {}, {}
    created_cluster = created_model = False
    active_session = None
    started = time.monotonic()
    limit = execution_seconds(plan, args.stage, args.shard)
    deadline = started + limit
    old_alarm = signal.getsignal(signal.SIGALRM)
    old_term = signal.getsignal(signal.SIGTERM)
    def interrupt(signum, frame):
        raise Deadline("Bounded worker deadline/signal: " + str(signum))
    signal.signal(signal.SIGALRM, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    signal.setitimer(signal.ITIMER_REAL, limit)

    def run(arguments, timeout=120, value=None, cleanup=False):
        phase_deadline = current_phase_deadline()
        operation_deadline = phase_deadline if cleanup else min(deadline, phase_deadline or deadline)
        remaining = min(timeout, operation_deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Command phase deadline exhausted")
        row = {"argv": [str(item) for item in arguments], "stdin_sha256": sha256(value) if value is not None else None}
        commands.append(row)
        began = time.monotonic_ns()
        print("Worker command:", row["argv"][0], row["argv"][1] if len(row["argv"]) > 1 else "", flush=True)
        try:
            result = subprocess.run(row["argv"], cwd=ROOT, input=canonical(value).encode() if value is not None else None,
                                    capture_output=True, timeout=remaining, env=dict(os.environ, KIND_EXPERIMENTAL_PROVIDER="docker"))
            row.update(exit_code=result.returncode, stdout=result.stdout.decode("utf-8", "replace")[-50000:], stderr=result.stderr.decode("utf-8", "replace")[-50000:])
            if result.returncode:
                raise RuntimeError("Setup/cleanup command failed: " + row["stderr"][-2000:])
            return row["stdout"]
        finally:
            row["elapsed_ns"] = time.monotonic_ns() - began
            atomic_json(output / "commands.json", commands)

    def session(case):
        return KubernetesSession(case, kubectl=binaries["kubectl"], context=context, kubeconfig=kubeconfig,
                                 image=fixture_image, commands=commands, expected_image_id=image_pins.get("runtime_image_id"))

    def checkpoint():
        atomic_json(output / "commands.json", commands)
        atomic_json(output / "progress.json", {"stage": args.stage, "shard": args.shard,
                    "completed_cells": [r["cell_id"] for r in records], "validated_controls": len(controls),
                    "seconds": time.monotonic() - started, "errors": errors})
        print("Robustness progress:", args.stage, "controls=", len(controls), "model_cells=", len(records), flush=True)

    setup_phase = allowance(limits.SETUP_SECONDS, "shared-setup")
    processing = allowance(PROCESSING_SECONDS, "cumulative-processing")
    try:
        with setup_phase():
            for key in ("node", "base"):
                run([binaries["docker"], "pull", plan["images"][key]], timeout=180)
            run([binaries["docker"], "tag", plan["images"]["base"], fixture_image])
            docker_image_id = run([binaries["docker"], "image", "inspect", "--format", "{{.Id}}", fixture_image]).strip()
            config = output / "kind-config.json"
            atomic_json(config, {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "nodes": [{"role": "control-plane"}],
                                 "networking": {"apiServerAddress": "127.0.0.1"}})
            created_cluster = True
            run([binaries["kind"], "create", "cluster", "--name", cluster, "--image", plan["images"]["node"],
                 "--config", config, "--kubeconfig", kubeconfig, "--wait", "120s"], timeout=180)
            kubeconfig.chmod(0o600)
            run([binaries["kind"], "load", "docker-image", fixture_image, "--name", cluster], timeout=90)
            # Establish the actual containerd image identity using a protected reference repair.
            active_session = session(plan["cases"][0]).start()
            oracle = apply_edits(active_session.case["resources"], active_session.case["oracle_edits"], active_session.case["allowed_paths"])
            setup = active_session.verify(oracle)
            if not setup["passed"]:
                atomic_json(output / "setup-image-verification.json", setup)
                raise RuntimeError("Protected image-reference smoke failed")
            ids = [s["image_id"] for pod in setup["runtime"]["pods"] for s in pod["container_statuses"] if s["image_id"]]
            if not ids or len({image_digest(value) for value in ids}) != 1:
                raise RuntimeError("Reference image identity is absent or inconsistent")
            active_session.expected_image_id = ids[0]
            setup = active_session.verify(oracle)
            if not setup["passed"]:
                raise RuntimeError("Image identity confirmation failed")
            atomic_json(output / "setup-image-verification.json", setup)
            image_pins = {"base_image": plan["images"]["base"], "fixture_image": fixture_image, "docker_image_id": docker_image_id,
                          "runtime_image_id": ids[0], "image_ids": [ids[0]], "setup_verification_sha256": sha256_file(output / "setup-image-verification.json"),
                          "setup_case_id": plan["cases"][0]["id"], "setup_candidate_sha256": sha256(oracle)}
            atomic_json(output / "image-pins.json", image_pins)
            active_session.close(); active_session = None
        if args.stage in {"validate", "diagnostic"}:
            for case in plan["cases"]:
                for mode in plan["controls"]:
                    print("Reference control started:", case["id"], mode, flush=True)
                    active_session = session(case)
                    with active_session.phase(limits.START_SECONDS, "control-start"):
                        active_session.start()
                    persist = allowance(limits.PERSIST_SECONDS, "control-evidence")
                    resources = apply_edits(active_session.case["resources"], baseline_edits(active_session.case, mode), active_session.case["allowed_paths"])
                    with active_session.phase(limits.FINAL_SECONDS, "control-verification"):
                        verification = active_session.verify(resources, max_wait=limits.FINAL_SECONDS)
                    row = {"case_id": case["id"], "control_id": mode, "expected": case["expected"],
                           "verification": verification, "cleanup": active_session.cleanup, "resources": resources,
                           "reference_only": mode == "oracle", "model_inference_observed": False}
                    controls.append(row)
                    with persist():
                        atomic_json(output / "controls" / (case["id"] + "--" + mode + ".json"), row)
                    with active_session.phase(limits.NAMESPACE_CLEANUP_SECONDS, "control-cleanup"):
                        active_session.close()
                    active_session = None
                    with persist():
                        atomic_json(output / "controls" / (case["id"] + "--" + mode + ".json"), row)
                    if verification["infrastructure_error"]:
                        errors.append(case["id"] + ": control infrastructure failure: " + str(verification["infrastructure_error"]))
                    if mode == "oracle" and case["expected"] != "abstain" and not verification["passed"]:
                        errors.append(case["id"] + ": reference repair failed")
                    if mode == "noop" and (verification["passed"] != (case["expected"] == "unchanged")):
                        errors.append(case["id"] + ": initial state differs from registered expectation")
                    with persist():
                        checkpoint()
        if errors:
            raise RuntimeError("Reference gate failed; no model calls permitted")
        if args.stage in {"models", "diagnostic"}:
            with setup_phase():
                run([binaries["docker"], "pull", plan["images"]["ollama"]], timeout=180)
                model_cache.mkdir(parents=True)
                created_model = True
                run([binaries["docker"], "run", "--detach", "--name", model_container, "--cpus=2", "--memory=4g", "--pids-limit=128",
                     "--user", str(os.getuid()) + ":" + str(os.getgid()), "--env", "HOME=/tmp", "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
                     "--publish", "127.0.0.1::11434", "--volume", str(model_cache) + ":/tmp/.ollama", "--env", "OLLAMA_CONTEXT_LENGTH=4096",
                     "--env", "OLLAMA_NUM_PARALLEL=1", "--env", "OLLAMA_MAX_LOADED_MODELS=1", "--env", "OLLAMA_KEEP_ALIVE=30m",
                     "--env", "OLLAMA_VULKAN=0", "--pull=never", plan["images"]["ollama"]], timeout=30)
                published = run([binaries["docker"], "port", model_container, "11434/tcp"]).strip()
                if not published.startswith("127.0.0.1:"):
                    raise RuntimeError("Model listener is not private loopback")
                endpoint = "http://" + published
                for _ in range(40):
                    try:
                        version = http(endpoint + "/api/version"); break
                    except OSError:
                        if time.monotonic() >= current_phase_deadline():
                            raise TimeoutError("Model-server setup deadline exhausted")
                        time.sleep(0.5)
                else:
                    raise RuntimeError("Model server unavailable")
                run([binaries["docker"], "exec", model_container, "ollama", "pull", model["tag"]], timeout=300)
                tags = http(endpoint + "/api/tags")
                matching = [item for item in tags.get("models", []) if item.get("name") == model["tag"]]
                if len(matching) != 1 or canonical_digest(matching[0]["digest"]) != canonical_digest(model["manifest_digest"]):
                    raise RuntimeError("Actual model manifest differs from frozen pin")
                blob = model_cache / "models/blobs" / canonical_digest(model["weight_blob_digest"]).replace(":", "-")
                if blob.stat().st_size != model["weight_bytes"] or canonical_digest(sha256_file(blob)) != canonical_digest(model["weight_blob_digest"]):
                    raise RuntimeError("Model weight checksum/length differs from pin")
                warmup = http(endpoint + "/api/chat", "POST", {"model": model["tag"], "messages": [], "stream": False,
                              "options": {"num_ctx": 4096, "num_thread": 2}}, timeout=180)
                ps = http(endpoint + "/api/ps")
                if not ps.get("models") or any(item.get("size_vram") != 0 for item in ps["models"]):
                    raise RuntimeError("CPU-only execution could not be established")
                model_pin = {"approved": model, "tags_before": tags, "show": http(endpoint + "/api/show", "POST", {"model": model["tag"]}),
                             "ollama_version": version, "ps_before": ps, "cpu_only": True, "weight_sha256_verified": True,
                             "weight_bytes_verified": True, "warmup": warmup, "settings": plan["settings"]}
                atomic_json(output / "model-pin.json", model_pin)
            cases = {case["id"]: case for case in plan["cases"]}
            cells = [cell for cell in plan["cells"] if cell["shard"] == args.shard]
            for cell in cells:
                reservation = limits.cell_reservation(METHODS[cell["method_id"]], feedback=cell["method_id"].startswith("feedback"))
                if deadline - time.monotonic() < reservation:
                    errors.append("Remaining worker budget insufficient to start another complete cell")
                    break
                began = time.monotonic()
                print("Model cell started:", cell["cell_id"], flush=True)
                case = cases[cell["case_id"]]
                active_session = session(case)
                with active_session.phase(limits.START_SECONDS, "trial-start"):
                    active_session.start()
                persist = allowance(limits.PERSIST_SECONDS, "trial-evidence")
                with active_session.phase(limits.INITIAL_SECONDS, "initial-verification"):
                    initial = active_session.verify(active_session.case["resources"], max_wait=limits.INITIAL_SECONDS)
                supplied = condition_case(copy.deepcopy(active_session.case), cell["condition"])
                supplied["initial_feedback"] = initial
                provider = OllamaProvider(endpoint, model["tag"], timeout=limits.CALL_SECONDS)
                def feedback(resources):
                    with active_session.phase(limits.INTERMEDIATE_SECONDS, "candidate-feedback"):
                        return active_session.verify(resources, max_wait=limits.INTERMEDIATE_SECONDS)
                result = run_method(supplied, cell["method_id"], provider, verify=feedback, processing_phase=processing)
                with active_session.phase(limits.FINAL_SECONDS, "final-verification"):
                    final = active_session.verify(result["resources"], max_wait=limits.FINAL_SECONDS)
                decision = result.get("decision") or {}
                expected = case["expected"]
                correct = (final["passed"] and result["resources"] != active_session.case["resources"] and decision.get("action") in {"patch", "finish"}) if expected == "repair" else (
                    final["passed"] and result["resources"] == active_session.case["resources"] and decision.get("action") == "finish") if expected == "unchanged" else (
                    not final["passed"] and decision.get("action") == "abstain" and bool(decision.get("reason", "").strip()))
                correct = correct and result["status"] not in {"model-error", "policy-error"}
                row = {"schema_version": "robustness-v3-record-v1", **cell, "plan_id": plan["plan_id"], "source_sha256": plan["source_sha256"],
                       "case_definition_sha256": case["definition_sha256"], "namespace": active_session.namespace, "fixture_image": fixture_image,
                       "expected": expected, "status": "infrastructure_failure" if initial["infrastructure_error"] or final["infrastructure_error"] else "provider_failure" if result["status"] == "model-error" and not any(call.get("raw_server_response") for call in result["calls"]) else "completed",
                       "task_correct": bool(correct), "initial_resources_sha256": sha256(active_session.case["resources"]),
                       "candidate_resources": result["resources"], "candidate_sha256": sha256(result["resources"]), "method_result": result,
                       "initial_verification": initial, "final_verification": final,
                       "metrics": raw_metrics(result, time.monotonic() - began), "evidence": {}}
                row["cleanup"] = active_session.cleanup
                records.append(row)
                with persist():
                    atomic_json(output / "records" / (cell["cell_id"] + ".json"), row)
                with active_session.phase(limits.NAMESPACE_CLEANUP_SECONDS, "trial-cleanup"):
                    active_session.close()
                active_session = None
                with persist():
                    atomic_json(output / "records" / (cell["cell_id"] + ".json"), row)
                    checkpoint()
            with processing():
                model_pin["tags_after"] = http(endpoint + "/api/tags")
                model_pin["ps_after"] = http(endpoint + "/api/ps")
                atomic_json(output / "model-pin.json", model_pin)
            if len(records) != len(cells):
                errors.append("Incomplete registered cell coverage")
    except (Exception, Deadline) as error:
        errors.append(type(error).__name__ + ": " + str(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        with restoring_signal_handlers(old_alarm, old_term):
            cleanup = {"cluster_removed": not created_cluster, "model_removed": not created_model,
                       "kubeconfig_removed": False, "model_cache_removed": False}
            try:
                with hard_phase(limits.GLOBAL_CLEANUP_SECONDS, "global-cleanup"):
                    if active_session is not None:
                        try:
                            with active_session.phase(limits.NAMESPACE_CLEANUP_SECONDS, "emergency-namespace-cleanup"):
                                active_session.close()
                        except Exception as error:
                            errors.append("Namespace cleanup: " + str(error))
                    for created, args_cleanup, key in ((created_cluster, [binaries["kind"], "delete", "cluster", "--name", cluster], "cluster_removed"),
                                                        (created_model, [binaries["docker"], "rm", "--force", model_container], "model_removed")):
                        if created:
                            try:
                                run(args_cleanup, timeout=30 if key == "cluster_removed" else 15, cleanup=True); cleanup[key] = True
                            except Exception as error:
                                errors.append("Worker cleanup: " + str(error))
                    kubeconfig.unlink(missing_ok=True)
                    cleanup["kubeconfig_removed"] = not kubeconfig.exists()
                    if model_cache.exists():
                        shutil.rmtree(model_cache)
                    cleanup["model_cache_removed"] = not model_cache.exists()
            except Exception as error:
                errors.append("Global cleanup: " + str(error))
            with hard_phase(FINALIZATION_SECONDS, "finalization"):
                kubeconfig.unlink(missing_ok=True)
                cleanup["kubeconfig_removed"] = not kubeconfig.exists()
                atomic_json(output / "commands.json", commands)
                summary = {"plan_id": plan["plan_id"], "source_sha256": plan["source_sha256"], "stage": args.stage, "shard": args.shard,
                           "status": "passed" if not errors and all(cleanup.values()) else "failed", "cleanup": cleanup,
                           "errors": errors, "record_count": len(records), "control_count": len(controls), "seconds": time.monotonic() - started,
                           "case_ids": sorted({row["case_id"] for row in records})}
                atomic_json(output / "summary.json", summary)
                for row in controls:
                    atomic_json(output / "controls" / (row["case_id"] + "--" + row["control_id"] + ".json"), row)
                for row in records:
                    row["cleanup"].update(cleanup)
                    for name, key in (("summary.json", "summary_sha256"), ("commands.json", "commands_sha256"),
                                      ("model-pin.json", "model_pin_sha256"), ("image-pins.json", "image_pins_sha256")):
                        if (output / name).exists():
                            row["evidence"][key] = sha256_file(output / name)
                    atomic_json(output / "records" / (row["cell_id"] + ".json"), row)
    print(canonical(summary), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
