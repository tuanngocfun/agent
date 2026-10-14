"""Run one bounded, pinned CPU-model shard on disposable real Kubernetes.

Task failures are benchmark observations. Integrity, setup, deadline and cleanup
failures fail the shard. No model action is replaced by a scripted repair.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kube_repair.artifacts import canonical, digest, load_bundle, source_fingerprint
from kube_repair.engine import run_baseline, run_task
from kube_repair.kubernetes_backend import image_digest
from kube_repair.policy import apply_changes, validate_candidate
from kube_repair.providers import OllamaProvider, _NoRedirect, _strict_json_loads, _validate_action
from kube_repair.verification import _probe_for_contract

IMAGE_PIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[a-f0-9]{64}$")
CASE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
METHODS = {"one-shot": (1, 1), "feedback": (6, 3)}
CONTROLS = ("noop", "naive", "template", "known-good")
REQUIRED_CHECKS = {"static-non-root", "static-read-only", "static-no-escalation", "static-capabilities",
    "static-seccomp", "static-unprivileged", "runtime-image-identity", "application-cache", "runtime-non-root",
    "runtime-read-only", "runtime-no-new-privileges", "runtime-capabilities", "runtime-seccomp", "namespace-cleanup"}
SHARD_SECONDS = 960
CASE_SECONDS = 900


class WorkerDeadline(BaseException):
    """Interrupt the engine without disguising a timeout as a model decision."""


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError("Artifact target must not be a symlink")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256_file(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def canonical_digest(value):
    raw = str(value or "").removeprefix("sha256:")
    if not re.fullmatch(r"[a-f0-9]{64}", raw):
        raise ValueError("Identity requires a SHA256 digest")
    return "sha256:" + raw


def http(endpoint, method="GET", payload=None, timeout=15):
    request = urllib.request.Request(endpoint, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise RuntimeError("Model metadata exceeds its byte limit")
    return _strict_json_loads(raw)


def load_plan(path, model_id, method_id, repetition, case_shard):
    plan = _strict_json_loads(Path(path).read_bytes())
    from kube_repair.benchmark_protocol import validate_locked_plan
    validate_locked_plan(plan)
    if plan.get("schema_version") != 1 or not isinstance(plan.get("plan_id"), str):
        raise ValueError("Unsupported benchmark plan")
    model = next((item for item in plan["models"] if item["model_id"] == model_id), None)
    method = next((item for item in plan["methods"] if item["method_id"] == method_id), None)
    if model is None or method is None or method_id not in METHODS:
        raise ValueError("Model/method is absent from the frozen plan")
    if type(repetition) is not int or not 0 <= repetition < plan["repetitions"]:
        raise ValueError("Trial index is outside the frozen plan")
    if type(case_shard) is not int or case_shard not in range(4):
        raise ValueError("Case shard must be zero through three")
    if (method["max_actions"], method["max_repairs"]) != METHODS[method_id] or method["token_ceiling"] != 32768:
        raise ValueError("Method limits differ from the benchmark protocol")
    settings = plan["settings"]
    expected = {"temperature": 0, "num_ctx": 8192, "num_thread": 2, "max_output_tokens": 512,
                "provider_timeout_seconds": 420, "max_total_tokens": 32768,
                "completion_policy": "verified-repair"}
    for key, value in expected.items():
        if settings.get(key) != value:
            raise ValueError("Unapproved benchmark setting: " + key)
    for image in (plan["images"][key] for key in ("ollama", "base", "node")):
        if not IMAGE_PIN.fullmatch(image):
            raise ValueError("Every worker image must be digest pinned")
    for key in ("manifest_digest", "weight_blob_digest"):
        canonical_digest(model[key])
    if not isinstance(model["tag"], str) or model["tag"].startswith("-") or type(model["weight_bytes"]) is not int or model["weight_bytes"] <= 0:
        raise ValueError("Invalid approved model registry entry")
    cases = [item for item in plan["cases"] if item["split"] == "evaluation"]
    if len(cases) != 8 or len({item["case_id"] for item in cases}) != len(cases):
        raise ValueError("Plan must freeze exactly eight distinct primary cases")
    if any(not CASE_ID.fullmatch(item["case_id"]) for item in cases):
        raise ValueError("Case identifiers must be safe directory components")
    selected = cases[case_shard * 2:case_shard * 2 + 2]
    return plan, model, method, selected


class BenchmarkProvider(OllamaProvider):
    """Give both methods the identical, explicitly labeled initial evidence."""
    def __init__(self, *args, initial_evidence, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_evidence = copy.deepcopy(initial_evidence)

    def next_action(self, context):
        supplied = copy.deepcopy(context)
        supplied["evidence"] = copy.deepcopy(self.initial_evidence)
        supplied["evidence"].update(context.get("evidence", {}))
        return super().next_action(supplied)

    def metadata(self):
        result = super().metadata()
        result["benchmark_evidence_policy"] = "all approved metadata and untrusted repository content supplied before the first call"
        result["benchmark_initial_evidence_hash"] = digest(self.initial_evidence)
        return result


def labeled_evidence(scenario):
    return {key: {"trust": "untrusted_repository" if key == "repository" else "approved_metadata", "content": value}
            for key, value in scenario.evidence.items()}


def namespace_cleanup_verified(trace):
    verifications = [event["result"] for event in trace if "result" in event]
    return bool(verifications) and all(any(check.get("name") == "namespace-cleanup" and check.get("passed") is True
        for check in result.get("checks", [])) for result in verifications)


def audit_bundle(bundle, model, scenario, method=None):
    """Replay raw model decisions, authority and verifier bindings for any outcome."""
    binding, payloads = load_bundle(bundle)
    report = json.loads(payloads["report.json"])
    trace = json.loads(payloads["trace.json"])
    base = json.loads(payloads["base.json"])
    candidate = json.loads(payloads["candidate.json"])
    contract = json.loads(payloads["contract.json"])
    if base != scenario.base or contract != scenario.contract:
        raise ValueError("Bundle differs from its locked case inputs")
    provider = report["provider"]
    calls = provider.get("inference_calls", [])
    if method is not None:
        if (report["budget"]["max_actions"], report["budget"]["max_repairs"]) != (method["max_actions"], method["max_repairs"]):
            raise ValueError("Task action or repair budgets differ from the plan")
        if provider.get("decoding_mode") != "compact-schema" or provider.get("token_usage", {}).get("max_total_tokens") != method["token_ceiling"]:
            raise ValueError("Task provider constraints differ from the plan")
        expected_limits = {"timeout_seconds": 420, "max_output_tokens": 512, "num_ctx": 8192, "num_thread": 2}
        if any(provider["limits"].get(key) != value for key, value in expected_limits.items()):
            raise ValueError("Provider inference settings differ from the plan")
        if provider.get("benchmark_initial_evidence_hash") != digest(labeled_evidence(scenario)):
            raise ValueError("Initial evidence differs from the registered identical-evidence policy")
    if provider.get("model_revision") is not None and canonical_digest(provider["model_revision"]) != canonical_digest(model["manifest_digest"]):
        raise ValueError("Task used a different model manifest")
    if provider.get("model") != model["tag"] or provider.get("uses_llm") is not True:
        raise ValueError("Task provider differs from the approved model")
    decisions = [event["action"] for event in trace if event["event"] == "decision"]
    returned = []
    inference_observed = False
    observed_prompt = observed_output = observed_usage_calls = 0
    for call in calls:
        raw = call.get("raw_server_response")
        if raw is None:
            if call.get("status") == "action_returned":
                raise ValueError("A returned decision has no raw response")
            continue
        if not isinstance(raw, str) or call.get("response_truncated"):
            if call.get("status") == "action_returned":
                raise ValueError("A returned decision has incomplete raw evidence")
            continue
        if hashlib.sha256(raw.encode()).hexdigest() != call.get("response_sha256"):
            raise ValueError("Raw server response checksum mismatch")
        try:
            response = _strict_json_loads(raw)
        except (ValueError, UnicodeError):
            if call.get("status") == "action_returned":
                raise ValueError("Returned action has invalid server JSON")
            continue
        if isinstance(response, dict) and response.get("model") and OllamaProvider._normalized_model(response["model"]) != OllamaProvider._normalized_model(model["tag"]):
            raise ValueError("Raw response model identity differs")
        inference_observed |= isinstance(response, dict) and type(response.get("eval_count")) is int and response["eval_count"] > 0
        usage = call.get("reported_usage")
        if usage is not None:
            prompt, output = response.get("prompt_eval_count"), response.get("eval_count")
            if type(prompt) is not int or type(output) is not int or min(prompt, output) < 0:
                raise ValueError("Stored usage lacks raw model token counts")
            if usage != {"prompt_tokens": prompt, "completion_tokens": output, "total_tokens": prompt + output}:
                raise ValueError("Stored token usage differs from raw model response")
            observed_prompt += prompt
            observed_output += output
            observed_usage_calls += 1
        if call.get("status") == "action_returned":
            if response.get("done") is not True or response.get("eval_count", 0) <= 0:
                raise ValueError("Returned action has no completed model inference")
            action = _validate_action(_strict_json_loads(response["message"]["content"]))
            if action != call.get("action"):
                raise ValueError("Stored action does not match raw model content")
            returned.append(action)
    if decisions != returned:
        raise ValueError("Engine decisions do not match actual returned model actions")
    if provider.get("token_usage") is not None:
        usage = provider["token_usage"]
        if (usage.get("reported_prompt_tokens"), usage.get("reported_completion_tokens"), usage.get("reported_total_tokens"), usage.get("counts_available_calls")) != (observed_prompt, observed_output, observed_prompt + observed_output, observed_usage_calls):
            raise ValueError("Aggregate token usage differs from raw inference records")
        if usage.get("counts_complete") is not (observed_usage_calls == len(calls) and len(calls) > 0):
            raise ValueError("Token completeness claim differs from actual calls")
    current, pending = copy.deepcopy(base), None
    applied_changed = False
    for event in trace:
        if event["event"] == "decision" and event["action"]["action"] == "propose":
            action = event["action"]
            try:
                pending = apply_changes(current, action["changes"]) if "changes" in action else action["manifest"]
            except (KeyError, TypeError, ValueError):
                pending = None
        elif event["event"] == "rejected_proposal":
            pending = None
        elif event["event"] == "candidate_verification":
            if pending is None or validate_candidate(base, pending, contract):
                raise ValueError("A candidate was executed without a valid model proposal")
            current = copy.deepcopy(pending)
            applied_changed |= current != base
            pending = None
            if event["manifest_hash"] != digest(current):
                raise ValueError("Verifier tested a different candidate")
        elif event["event"] in {"initial_verification", "requested_verification"}:
            if event["manifest_hash"] != digest(current):
                raise ValueError("Verification manifest binding mismatch")
    if candidate != (current if report["accepted"] else base):
        raise ValueError("Export candidate differs from the engine acceptance policy")
    verifications = [event["result"] for event in trace if event["event"] in {"initial_verification", "candidate_verification", "requested_verification"}]
    if not verifications or report["verification"] != verifications[-1]:
        raise ValueError("Final report verification differs from the latest trusted trace result")
    if report["accepted"]:
        result = report["verification"]
        checks = result.get("checks", [])
        if (result.get("passed") is not True or result.get("infrastructure_error") or not namespace_cleanup_verified(trace)
                or len(checks) != len(REQUIRED_CHECKS) or {check.get("name") for check in checks} != REQUIRED_CHECKS
                or any(check.get("passed") is not True for check in checks) or report.get("runtime_verified") is not True
                or report.get("backend") != "kubernetes" or result.get("backend") != "kubernetes"
                or result.get("runtime_verified") is not True or result.get("kubernetes_execution_observed") is not True):
            raise ValueError("Accepted repair lacks complete independent verification")
        runtime = result.get("runtime", {})
        expected_image = contract.get("kubernetes", {}).get("expected_image_id")
        if (image_digest(runtime.get("image_id")) != image_digest(expected_image)
                or runtime.get("fixture_kind") != contract.get("fixture_kind", "file-cache")
                or runtime.get("probe_sha256") != hashlib.sha256(_probe_for_contract(contract).encode()).hexdigest()):
            raise ValueError("Accepted verification has the wrong fixture, image or protected probe")
        app = current["spec"]["template"]["spec"]["containers"][0]
        uid_check = next(check for check in checks if check["name"] == "runtime-non-root")
        if uid_check.get("detail") != "PID 1 effective UID=" + str(contract.get("allowed_uid", 10001)):
            raise ValueError("Observed runtime UID differs from the task-specific UID")
        expected_controls = {"runAsNonRoot": True, "runAsUser": contract.get("allowed_uid", 10001),
            "runAsGroup": contract.get("allowed_primary_gid", 10001), "readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}, "seccompProfile": {"type": "RuntimeDefault"}}
        if any(app["securityContext"].get(key) != value for key, value in expected_controls.items()):
            raise ValueError("Accepted candidate missed a task-specific security target")
        if report.get("completion_actor") == "trusted_engine":
            if report.get("completion_policy") != "verified-repair" or not applied_changed or trace[-1]["event"] != "trusted_completion" or trace[-1].get("actor") != "trusted_engine":
                raise ValueError("Trusted completion lacks a changed model-origin candidate")
            if trace[-2]["event"] not in {"candidate_verification", "requested_verification"} or trace[-2]["result"].get("passed") is not True:
                raise ValueError("Trusted completion was not preceded by a passing verification")
            if trace[-1]["manifest_hash"] != digest(current):
                raise ValueError("Completion hash differs from the model candidate")
        elif not decisions or decisions[-1]["action"] != "finish":
            raise ValueError("Accepted provider completion has no raw finish decision")
    if report.get("appropriate_abstention") and not (scenario.expected == "abstain" and decisions and decisions[-1]["action"] == "abstain" and decisions[-1]["reason"].strip()):
        raise ValueError("Appropriate abstention has no explicit model-origin reason")
    return {"schema_version": 1, "status": "passed", "bundle_review_hash": binding["review_hash"],
            "model_origin_verified": inference_observed, "inference_observed": inference_observed,
            "raw_model_actions_replayed": len(returned), "namespace_cleanup_verified": namespace_cleanup_verified(trace),
            "worker_cleanup_verified": False, "validators": ["bundle_hashes", "locked_case_inputs", "model_identity",
            "raw_response_hashes", "raw_model_actions", "candidate_policy_replay", "verification_manifest_hashes",
            "task_security_targets", "explicit_completion_provenance"]}


def classify_outcome(report, trace):
    if report.get("status") == "runner_error" or report.get("verification", {}).get("infrastructure_error"):
        return "infrastructure_failure"
    if report.get("accepted"):
        return report["status"]
    if report.get("appropriate_abstention"):
        return "abstained"
    if report.get("status") == "provider_error":
        return "budget_exhausted" if any(error.get("code") == "token_budget" for error in report["provider"].get("errors", [])) else "provider_failure"
    if any(event["event"] == "rejected_proposal" for event in trace):
        return "policy_failure"
    if any(event["event"] == "rejected_provider_output" for event in trace):
        return "protocol_failure"
    if report.get("status") == "budget_exhausted":
        return "budget_exhausted"
    if not report["verification"].get("behavior_pass"):
        return "behavior_failure"
    return "security_failure"


def record_from_bundle(plan, model, method, case, repetition, bundle, audit, root):
    binding, payloads = load_bundle(bundle)
    report, trace = json.loads(payloads["report.json"]), json.loads(payloads["trace.json"])
    provider, verification = report["provider"], report["verification"]
    usage = provider.get("token_usage") or {}
    complete = usage.get("counts_complete") is True and usage.get("counts_available_calls", 0) > 0
    generation_durations = []
    for call in provider.get("inference_calls", []):
        try:
            duration = json.loads(call.get("raw_server_response") or "null").get("eval_duration")
        except (ValueError, AttributeError):
            duration = None
        if type(duration) is not int or duration < 0:
            generation_durations = None
            break
        generation_durations.append(duration / 1e9)
    metrics = {"inspections": sum(event["event"] == "evidence" for event in trace),
        "repairs": report["budget"]["candidate_repairs"], "tests": report["budget"]["test_runs"],
        "model_calls": provider.get("calls"), "prompt_tokens": usage.get("reported_prompt_tokens") if complete else None,
        "output_tokens": usage.get("reported_completion_tokens") if complete else None,
        "total_tokens": usage.get("reported_total_tokens") if complete else None,
        "reserved_tokens": usage.get("reserved_token_upper_bound"), "wall_seconds": report.get("seconds"),
        "inference_seconds": provider.get("elapsed_seconds"),
        "generation_seconds": sum(generation_durations) if generation_durations and complete else None,
        "protocol_rejections": sum(event["event"] == "rejected_provider_output" for event in trace),
        "policy_rejections": sum(event["event"] == "rejected_proposal" for event in trace)}
    audit_path = Path(bundle).parent / "audit.json"
    atomic_json(audit_path, audit)
    return {"schema_version": 1, "plan_id": plan["plan_id"],
        **{key: plan[key] for key in ("suite_fingerprint", "evaluator_fingerprint", "source_fingerprint", "settings_fingerprint")},
        "model_id": model["model_id"], "method_id": method["method_id"], "case_id": case["case_id"],
        "repetition": repetition, "split": case["split"], "expected_outcome": case["expected_outcome"],
        "outcome": classify_outcome(report, trace), "accepted": report["accepted"],
        "appropriate_abstention": report.get("appropriate_abstention", False),
        "unnecessary_change": report.get("unnecessary_change", False), "rejected_actions": report["rejected_actions"],
        "unauthorized_effects": report["executed_unauthorized_effects"], "failure_reason": None if report["accepted"] or report.get("appropriate_abstention") else report["reason"],
        "metrics": metrics, "checks": {"behavior": verification.get("behavior_pass"), "static": verification.get("static_pass"),
            "security": verification.get("negative_pass"), "cleanup": False},
        "evidence": {"validated": True, "model_origin_verified": audit["model_origin_verified"],
            "bundle_path": str(Path(bundle).relative_to(root)), "bundle_sha256": sha256_file(Path(bundle) / "binding.json"),
            "audit_path": str(audit_path.relative_to(root)), "audit_sha256": sha256_file(audit_path)},
        "provenance": {"model_pin": model, "provider": provider, "backend": "kubernetes",
            "bundle_review_hash": binding["review_hash"], "case_definition_sha256": case.get("definition_sha256"),
            "worker_cleanup": None, "repetition_interpretation": "repeat execution at identical temperature-zero settings; not independent stochastic trials"}}


def interrupted_record(plan, model, method, case, repetition, provider, case_root, root, seconds, error):
    """Preserve a timed-out attempt without promoting its partial journal."""
    metadata = provider.metadata()
    progress_path = case_root / "agent-progress.json"
    partial = json.loads(progress_path.read_text()) if progress_path.is_file() else {}
    budget, usage = partial.get("budget", {}), metadata.get("token_usage") or {}
    complete = usage.get("counts_complete") is True and usage.get("counts_available_calls", 0) > 0
    return {"schema_version": 1, "plan_id": plan["plan_id"],
        **{key: plan[key] for key in ("suite_fingerprint", "evaluator_fingerprint", "source_fingerprint", "settings_fingerprint")},
        "model_id": model["model_id"], "method_id": method["method_id"], "case_id": case["case_id"],
        "repetition": repetition, "split": case["split"], "expected_outcome": case["expected_outcome"],
        "outcome": "infrastructure_failure", "accepted": False, "appropriate_abstention": False,
        "unnecessary_change": False, "rejected_actions": partial.get("rejected_actions"), "unauthorized_effects": 0,
        "failure_reason": error, "metrics": {"inspections": sum(event.get("event") == "evidence" for event in partial.get("trace", [])),
            "repairs": budget.get("candidate_repairs"), "tests": budget.get("test_runs"), "model_calls": metadata.get("calls"),
            "prompt_tokens": usage.get("reported_prompt_tokens") if complete else None,
            "output_tokens": usage.get("reported_completion_tokens") if complete else None,
            "total_tokens": usage.get("reported_total_tokens") if complete else None,
            "reserved_tokens": usage.get("reserved_token_upper_bound"), "wall_seconds": seconds,
            "inference_seconds": metadata.get("elapsed_seconds"), "generation_seconds": None,
            "protocol_rejections": None, "policy_rejections": None},
        "checks": {"behavior": None, "static": None, "security": None, "cleanup": None},
        "evidence": {"validated": False, "model_origin_verified": False, "bundle_path": None, "bundle_sha256": None,
            "audit_path": None, "audit_sha256": None,
            "partial_progress_path": str(progress_path.relative_to(root)) if progress_path.is_file() else None,
            "partial_progress_sha256": sha256_file(progress_path) if progress_path.is_file() else None},
        "provenance": {"model_pin": model, "provider": metadata, "backend": "kubernetes", "worker_cleanup": None,
            "partial_only": True, "limitation": "Interrupted diagnostics have no completed hash-bound review audit and cannot establish task success."}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--trial-index", type=int, required=True)
    parser.add_argument("--case-shard", type=int, choices=range(4), default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    plan, model, method, cases = load_plan(args.plan, args.model_id, args.method, args.trial_index, args.case_shard)
    from kube_repair.benchmark_cases import benchmark_case, benchmark_cases_manifest
    suite = benchmark_cases_manifest()
    if suite["suite_sha256"] != plan["suite_fingerprint"] or source_fingerprint() != plan["source_fingerprint"]:
        parser.error("Case suite or engine source differs from the frozen plan")
    binaries = {name: shutil.which(name) for name in ("docker", "kind", "kubectl")}
    if not all(binaries.values()):
        parser.error("Dedicated worker requires docker, kind and kubectl; no simulation fallback")
    output = args.output.resolve()
    if output.exists() or any(parent.is_symlink() for parent in output.parents):
        parser.error("Output must be a fresh directory without symlink parents")
    output.mkdir(parents=True)
    for name in ("records", "controls", "cases"):
        (output / name).mkdir()
    atomic_json(output / "plan.json", plan)
    atomic_json(output / "suite.json", suite)
    commands, records = [], []
    cluster = "repair-bench-" + uuid.uuid4().hex[:12]
    container = "repair-model-" + uuid.uuid4().hex[:12]
    cache = ROOT / ".tools" / ("benchmark-model-cache-" + uuid.uuid4().hex[:12])
    cache.mkdir(parents=True)
    kubeconfig = output / "private-kubeconfig"
    context = "kind-" + cluster
    deadline = time.monotonic() + SHARD_SECONDS
    created_model = created_cluster = False
    fatal_errors = []
    pin = {}
    fixture_pins = {}
    model_inference_observed = False
    started = time.monotonic()
    old_alarm = signal.getsignal(signal.SIGALRM)
    old_term = signal.getsignal(signal.SIGTERM)
    def interrupted(signum, frame):
        raise WorkerDeadline("Worker interrupted by signal " + str(signum))
    signal.signal(signal.SIGALRM, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    signal.setitimer(signal.ITIMER_REAL, SHARD_SECONDS)

    def run(arguments, timeout=120, input_value=None, cleanup=False):
        timeout = min(timeout, max(1, deadline - time.monotonic())) if not cleanup else timeout
        print("Benchmark command:", str(arguments[0]), str(arguments[1]), flush=True)
        record = {"argv": [str(value) for value in arguments], "actual_exit": None, "timeout_seconds": timeout}
        commands.append(record)
        command_started = time.monotonic()
        try:
            result = subprocess.run(record["argv"], cwd=ROOT, capture_output=True, timeout=timeout,
                env=dict(os.environ, KIND_EXPERIMENTAL_PROVIDER="docker"),
                input=json.dumps(input_value).encode() if input_value is not None else None)
            stdout = result.stdout.decode("utf-8", "replace")
            record.update({"actual_exit": result.returncode, "stdout": stdout[-6000:],
                           "stderr": result.stderr.decode("utf-8", "replace")[-6000:]})
            if len(result.stdout) > 1024 * 1024:
                raise RuntimeError("Worker command stdout exceeds its bounded parse limit")
            if result.returncode:
                raise RuntimeError("Worker command failed: " + record["stderr"][-1500:])
            return stdout
        finally:
            record["seconds"] = round(time.monotonic() - command_started, 6)
            atomic_json(output / "commands.json", commands)

    def progress(stage, **extra):
        atomic_json(output / "progress.json", {"schema_version": 1, "status": "in_progress", "exportable": False,
            "stage": stage, "model_id": args.model_id, "method_id": args.method,
            "repetition": args.trial_index, "case_shard": args.case_shard,
            "completed_case_ids": [record["case_id"] for record in records],
            "seconds": round(time.monotonic() - started, 6), **extra})
        print("Benchmark progress:", stage, extra.get("case_id", ""), flush=True)

    try:
        progress("setup")
        for image in (plan["images"][key] for key in ("ollama", "node", "base")):
            run([binaries["docker"], "pull", image], timeout=180)
        created_model = True
        run([binaries["docker"], "run", "--detach", "--name", container, "--cpus=2", "--memory=4g", "--pids-limit=128",
            "--user", f"{os.getuid()}:{os.getgid()}", "--env", "HOME=/tmp", "--cap-drop=ALL",
            "--security-opt=no-new-privileges=true", "--pull=never", "--publish", "127.0.0.1::11434",
            "--volume", str(cache) + ":/tmp/.ollama", "--env", "OLLAMA_NUM_PARALLEL=1",
            "--env", "OLLAMA_MAX_LOADED_MODELS=1", "--env", "OLLAMA_KEEP_ALIVE=30m",
            "--env", "OLLAMA_CONTEXT_LENGTH=8192", "--env", "OLLAMA_VULKAN=0", plan["images"]["ollama"]], timeout=30)
        published = run([binaries["docker"], "port", container, "11434/tcp"], timeout=10).strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", published):
            raise RuntimeError("Model port is not a private loopback listener")
        endpoint = "http://" + published
        for _ in range(60):
            try:
                version = http(endpoint + "/api/version")
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Model server did not become ready")
        run([binaries["docker"], "exec", container, "ollama", "pull", model["tag"]], timeout=300)
        tags = http(endpoint + "/api/tags")
        matching = [entry for entry in tags.get("models", []) if entry.get("name") == model["tag"] or entry.get("model") == model["tag"]]
        if len(matching) != 1 or canonical_digest(matching[0]["digest"]) != canonical_digest(model["manifest_digest"]):
            raise RuntimeError("Actual model manifest differs from frozen model registry")
        blob = cache / "models/blobs" / canonical_digest(model["weight_blob_digest"]).replace(":", "-")
        if blob.stat().st_size != model["weight_bytes"] or canonical_digest(sha256_file(blob)) != canonical_digest(model["weight_blob_digest"]):
            raise RuntimeError("Downloaded model weights differ from the approved blob pin")
        show = http(endpoint + "/api/show", "POST", {"model": model["tag"]})
        warmup = http(endpoint + "/api/chat", "POST", {"model": model["tag"], "messages": [], "stream": False,
            "options": {"num_ctx": 8192, "num_thread": 2}}, timeout=180)
        ps = http(endpoint + "/api/ps")
        if not ps.get("models") or any(entry.get("size_vram") != 0 for entry in ps["models"]):
            raise RuntimeError("CPU-only model execution could not be established")
        pin = {"approved": model, "tags_before": tags, "show": show, "warmup": warmup,
               "ollama_version": version, "ps_before": ps, "cpu_only": True,
               "weight_sha256_verified": True, "weight_bytes_verified": True, "settings": plan["settings"]}
        try:
            cpu_model = next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                             if line.startswith("model name"))
        except (OSError, StopIteration):
            cpu_model = None
        pin["hardware"] = {"platform": platform.platform(), "machine": platform.machine(),
                           "host_logical_cpus": os.cpu_count(), "cpu_model": cpu_model,
                           "model_container_cpus": 2, "model_container_memory": "4g",
                           "inference_threads": 2,
                           "interpretation": "Descriptive shared-runner timing; hardware and contention may vary."}
        atomic_json(output / "model-pin.json", pin)
        config = output / "kind-config.json"
        atomic_json(config, {"kind": "Cluster", "apiVersion": "kind.x-k8s.io/v1alpha4", "nodes": [{"role": "control-plane"}],
                             "networking": {"apiServerAddress": "127.0.0.1"}})
        created_cluster = True
        run([binaries["kind"], "create", "cluster", "--name", cluster, "--image", plan["images"]["node"],
             "--config", config, "--kubeconfig", kubeconfig, "--wait", "120s"], timeout=180)
        kubeconfig.chmod(0o600)
        kubectl = [binaries["kubectl"], "--context", context, "--kubeconfig", str(kubeconfig), "--request-timeout=10s"]
        for fixture_kind in sorted({case["fixture_kind"] for case in cases}):
            directory = ROOT / "fixtures" / ("cache_app" if fixture_kind == "file-cache" else "sqlite_cache")
            tag = "repair-benchmark-" + fixture_kind + ":" + uuid.uuid4().hex[:12]
            run([binaries["docker"], "build", "--pull=false", "--network=none", "--build-arg", "BASE_IMAGE=" + plan["images"]["base"], "-t", tag, directory], timeout=120)
            run([binaries["kind"], "load", "docker-image", tag, "--name", cluster], timeout=90)
            secure_id = "file-already-secure" if fixture_kind == "file-cache" else "sqlite-already-secure"
            setup = benchmark_case(secure_id, image=tag)
            namespace = "repair-image-pin-" + uuid.uuid4().hex[:12]
            run(kubectl + ["create", "namespace", namespace])
            setup.base["metadata"]["namespace"] = namespace
            run(kubectl + ["-n", namespace, "apply", "-f", "-"], input_value=setup.base)
            run(kubectl + ["-n", namespace, "rollout", "status", "deployment/repair-cache-app", "--timeout=60s"], timeout=70)
            pods = json.loads(run(kubectl + ["-n", namespace, "get", "pods", "-l", "app=repair-cache-app", "-o", "json"]))["items"]
            if len(pods) != 1:
                raise RuntimeError("Image pin setup returned an unexpected pod inventory")
            status = next(item for item in pods[0]["status"]["containerStatuses"] if item["name"] == "app")
            if status.get("ready") is not True or not re.search(r"sha256:[a-f0-9]{64}$", status.get("imageID", "")):
                raise RuntimeError("Fixture runtime image identity was not established")
            fixture_pins[fixture_kind] = {"fixture_tag": tag, "runtime_image_id": status["imageID"],
                "pod_uid": pods[0]["metadata"]["uid"], "fixture_files": {path.name: sha256_file(path) for path in directory.glob("*") if path.is_file()}}
            run(kubectl + ["delete", "namespace", namespace, "--wait=true", "--timeout=45s"], timeout=50)
        atomic_json(output / "image-pins.json", fixture_pins)
        for case in cases:
            case_id = case["case_id"]
            case_root = output / "cases" / case_id
            case_root.mkdir()
            image_pin = fixture_pins[case["fixture_kind"]]
            scenario = benchmark_case(case_id, image=image_pin["fixture_tag"])
            scenario.contract["kubernetes"] = {"context": context, "kubeconfig": str(kubeconfig),
                "kubectl": binaries["kubectl"], "expected_image_id": image_pin["runtime_image_id"]}
            if scenario.expected != case["expected_outcome"]:
                raise RuntimeError("Locked case outcome differs from runtime case definition")
            progress("case_started", case_id=case_id)
            for control in CONTROLS:
                control_output = output / "controls" / (case_id + "--" + control)
                report, binding = run_baseline(scenario, control, control_output, backend="kubernetes")
                atomic_json(output / "controls" / (case_id + "--" + control + ".json"), {
                    "control_id": control, "case_id": case_id, "oracle": control == "known-good",
                    "report": report, "bundle_review_hash": binding["review_hash"]})
                if report["status"] == "runner_error":
                    raise RuntimeError("Control infrastructure failed: " + report["reason"])
            provider = BenchmarkProvider(model["tag"], endpoint, initial_evidence=labeled_evidence(scenario),
                timeout=420, max_output_tokens=512, max_total_tokens=32768,
                num_ctx=8192, num_thread=2, decoding_mode="compact-schema")
            signal.setitimer(signal.ITIMER_REAL, min(CASE_SECONDS, max(0.01, deadline - time.monotonic())))
            task_started = time.monotonic()
            try:
                run_task(scenario, provider, case_root / "bundle", backend="kubernetes",
                    max_actions=method["max_actions"], max_repairs=method["max_repairs"],
                    progress_output=case_root / "agent-progress.json", stop_on_verified_repair=True)
                audit = audit_bundle(case_root / "bundle", model, scenario, method)
                record = record_from_bundle(plan, model, method, case, args.trial_index, case_root / "bundle", audit, output)
                model_inference_observed |= audit["inference_observed"]
                records.append(record)
                atomic_json(output / "records" / (case_id + ".json"), record)
                if record["outcome"] == "infrastructure_failure":
                    fatal_errors.append("Task verifier infrastructure failed: " + case_id)
            except WorkerDeadline as exc:
                fatal_errors.append("Case deadline: " + case_id)
                atomic_json(case_root / "interruption.json", {"status": "infrastructure_failure", "error": str(exc),
                    "provider": provider.metadata(), "model_origin_claim": False})
                record = interrupted_record(plan, model, method, case, args.trial_index, provider,
                    case_root, output, round(time.monotonic() - task_started, 6), str(exc))
                records.append(record)
                atomic_json(output / "records" / (case_id + ".json"), record)
                if time.monotonic() >= deadline:
                    raise
            finally:
                signal.setitimer(signal.ITIMER_REAL, max(0.01, deadline - time.monotonic()))
            progress("case_finished", case_id=case_id)
        after_tags, after_ps = http(endpoint + "/api/tags"), http(endpoint + "/api/ps")
        matching = [entry for entry in after_tags.get("models", []) if entry.get("name") == model["tag"] or entry.get("model") == model["tag"]]
        if len(matching) != 1 or canonical_digest(matching[0]["digest"]) != canonical_digest(model["manifest_digest"]) or not after_ps.get("models") or any(entry.get("size_vram") != 0 for entry in after_ps["models"]):
            raise RuntimeError("Model identity or CPU-only execution changed during the shard")
        pin.update({"tags_after": after_tags, "ps_after": after_ps, "model_digest_unchanged": True})
        atomic_json(output / "model-pin.json", pin)
        if len(records) != len(cases):
            fatal_errors.append("Incomplete planned case coverage")
    except (Exception, WorkerDeadline) as exc:
        fatal_errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        cleanup = {"model_container_removed": not created_model, "cluster_removed": not created_cluster,
                   "kubeconfig_removed": False, "model_cache_removed": False}
        for created, arguments, key in ((created_cluster, [binaries["kind"], "delete", "cluster", "--name", cluster], "cluster_removed"),
                                       (created_model, [binaries["docker"], "rm", "--force", container], "model_container_removed")):
            if created:
                try:
                    run(arguments, timeout=60, cleanup=True)
                    cleanup[key] = True
                except Exception as exc:
                    fatal_errors.append("Cleanup failed: " + str(exc))
        kubeconfig.unlink(missing_ok=True)
        cleanup["kubeconfig_removed"] = not kubeconfig.exists()
        try:
            shutil.rmtree(cache)
            cleanup["model_cache_removed"] = True
        except OSError as exc:
            fatal_errors.append("Owned model cache cleanup failed: " + str(exc))
        worker_cleanup_verified = all(cleanup.values())
        for record in records:
            if record["evidence"]["validated"]:
                audit_path = output / record["evidence"]["audit_path"]
                audit = json.loads(audit_path.read_text())
                audit["worker_cleanup_verified"] = worker_cleanup_verified
                audit["worker_cleanup"] = cleanup
                atomic_json(audit_path, audit)
                record["evidence"]["audit_sha256"] = sha256_file(audit_path)
                record["checks"]["cleanup"] = audit["namespace_cleanup_verified"] and worker_cleanup_verified
            record["provenance"]["worker_cleanup"] = cleanup
            if (output / "model-pin.json").is_file():
                record["evidence"]["model_pin_path"] = "model-pin.json"
                record["evidence"]["model_pin_sha256"] = sha256_file(output / "model-pin.json")
            if (output / "image-pins.json").is_file():
                record["evidence"]["image_pins_path"] = "image-pins.json"
                record["evidence"]["image_pins_sha256"] = sha256_file(output / "image-pins.json")
            atomic_json(output / "records" / (record["case_id"] + ".json"), record)
        summary = {"schema_version": 1, "status": "passed" if not fatal_errors and worker_cleanup_verified else "failed",
            "plan_id": plan["plan_id"], "model_id": args.model_id, "method_id": args.method,
            "repetition": args.trial_index, "case_shard": args.case_shard,
            "planned_case_ids": [case["case_id"] for case in cases], "recorded_case_ids": [record["case_id"] for record in records],
            "errors": fatal_errors, "cleanup": cleanup, "seconds": round(time.monotonic() - started, 6),
            "requires_real_llm": True, "requires_real_kubernetes": True,
            "model_inference_observed": model_inference_observed,
            "kubernetes_fixture_execution_observed": bool(fixture_pins), "cpu_only_verified": pin.get("cpu_only") is True,
            "task_success_required_for_shard_pass": False}
        atomic_json(output / "summary.json", summary)
        signal.signal(signal.SIGALRM, old_alarm)
        signal.signal(signal.SIGTERM, old_term)
    print(canonical(summary), flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
