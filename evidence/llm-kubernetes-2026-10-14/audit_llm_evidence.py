#!/usr/bin/env python3
"""Fail-closed consistency audit of this trusted worker's LLM/Kubernetes artifacts.

This is not remote attestation or independent execution of the workload. It
trusts the checked-out runner, verifier and recorded command results. Canonical
bundles sort dictionary keys; request replay therefore restores source-defined
ordering and Kubernetes v1.34 version.Info's Go field ordering. Exact request
hash replay is a separate diagnostic: lost insertion ordering may make it
unavailable. Raw-response hashes, model origin, artifact bindings, protected
candidate policy and runtime checks remain mandatory. No network, runtime or
model is started.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from kube_repair.artifacts import digest, load_bundle, source_fingerprint
from kube_repair.engine import _task
from kube_repair.kubernetes_backend import _root_policy_rejection
from kube_repair.policy import apply_changes, validate_candidate
from kube_repair.providers import (ACTION_SCHEMA, COMPACT_ACTION_SCHEMA, COMPACT_SYSTEM_PROMPT,
                                  JSON_SYSTEM_PROMPT, SYSTEM_PROMPT, OllamaProvider,
                                  _compact_generation_schema, _generation_schema,
                                  _strict_json_loads, _validate_action)
from kube_repair.scenarios import get_scenario

MODEL = "qwen2.5:3b-instruct-q4_K_M"
MODEL_DIGEST = "357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b"
WEIGHT_DIGEST = "5ee4f07cdb9beadbbb293e85803c569b01bd37ed059d2715faa7bb405f31caa6"
LICENSE_URL = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE"
OLLAMA_IMAGE = "ollama/ollama:0.6.8@sha256:50ab2378567a62b811a2967759dd91f254864c3495cbe50576bd8a85bc6edd56"
CHECKS = {
    "static-non-root", "static-read-only", "static-no-escalation", "static-capabilities",
    "static-seccomp", "static-unprivileged", "runtime-image-identity", "application-cache",
    "runtime-non-root", "runtime-read-only", "runtime-no-new-privileges",
    "runtime-capabilities", "runtime-seccomp", "namespace-cleanup",
}
VERSION_ORDER = ["major", "minor", "emulationMajor", "emulationMinor", "minCompatibilityMajor",
                 "minCompatibilityMinor", "gitVersion", "gitCommit", "gitTreeState", "buildDate",
                 "goVersion", "compiler", "platform"]
RUNTIME_ORDER = ["context", "namespace", "server_version", "deployment_uid", "generation",
                 "container_waiting", "pod_uid", "pod_name", "image_id", "startup_error", "startup_logs"]
RESULT_ORDER = ["backend", "runtime_verified", "static_pass", "behavior_pass", "negative_pass",
                "passed", "checks", "feedback", "infrastructure_error", "runtime",
                "kubernetes_execution_observed"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    require(path.is_file() and not path.is_symlink(), "Missing/nonregular evidence: " + str(path))
    return _strict_json_loads(path.read_text(encoding="utf-8"))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalize_digest(value):
    require(isinstance(value, str), "Digest must be a string")
    result = value.removeprefix("sha256:")
    require(len(result) == 64 and all(c in "0123456789abcdef" for c in result), "Invalid digest")
    return result


def ordered(value, keys, label):
    require(isinstance(value, dict) and set(value) <= set(keys), "Unknown " + label + " fields")
    return {key: copy.deepcopy(value[key]) for key in keys if key in value}


def restore_result(value):
    result = ordered(value, RESULT_ORDER, "verifier result")
    require(set(result) == set(RESULT_ORDER), "Incomplete Kubernetes verifier result")
    result["checks"] = [ordered(item, ["name", "passed", "detail"], "check") for item in value["checks"]]
    result["runtime"] = ordered(value["runtime"], RUNTIME_ORDER, "Kubernetes runtime")
    if "server_version" in result["runtime"]:
        result["runtime"]["server_version"] = ordered(value["runtime"]["server_version"], VERSION_ORDER, "version.Info")
    if "container_waiting" in result["runtime"]:
        result["runtime"]["container_waiting"] = ordered(value["runtime"]["container_waiting"], ["reason", "message"], "container waiting")
    return result


def model_entry(payload, label, cpu=False):
    require(isinstance(payload, dict) and isinstance(payload.get("models"), list), label + " has no model list")
    require(len(payload["models"]) == 1, label + " must contain only the selected model")
    model = payload["models"][0]
    require(model.get("name") == MODEL and model.get("model") == MODEL, label + " model mismatch")
    require(normalize_digest(model.get("digest")) == MODEL_DIGEST, label + " digest mismatch")
    details = model.get("details", {})
    require(details.get("parameter_size") == "3.1B" and details.get("quantization_level") == "Q4_K_M", label + " model format mismatch")
    if cpu:
        require(type(model.get("size_vram")) is int and model["size_vram"] == 0, label + " does not establish CPU-only execution")
    return model


def successful_verifier(result, label):
    require(result.get("backend") == "kubernetes" and result.get("runtime_verified") is True,
            label + " is not verified Kubernetes execution")
    require(all(result.get(key) is True for key in ("passed", "static_pass", "behavior_pass", "negative_pass")), label + " did not pass")
    require(result.get("infrastructure_error") is None, label + " has infrastructure errors")
    checks = result.get("checks", [])
    require(len(checks) == 14 and {item.get("name") for item in checks} == CHECKS
            and all(item.get("passed") is True for item in checks), label + " must pass precisely all 14 protected checks")


def replay(base, contract, trace, provider, candidate, report, image_id):
    image = base["spec"]["template"]["spec"]["containers"][0]["image"]
    scenario = get_scenario(report["scenario"], image=image)
    require(scenario.base == base, "Base differs from the current trusted scenario")
    require(scenario.contract == {key: value for key, value in contract.items() if key != "kubernetes"}, "Contract differs from current fixture")
    current = copy.deepcopy(scenario.base)  # Preserve source insertion order.
    history, observations, evidence = [], [], {}
    calls = provider.get("inference_calls", [])
    require(isinstance(trace, list) and trace and trace[0].get("event") == "initial_verification", "No initial verification")
    require(trace[0].get("manifest_hash") == digest(current), "Initial manifest hash mismatch")
    result = restore_result(trace[0]["result"])
    history.append({"event": "initial_verification", "manifest_hash": digest(current), "result": result})
    observations.append(dict(result, trust="trusted_verifier"))
    repairs, tests, rejected, decisions, prompt_total, completion_total, reservation = 0, 1, 0, 0, 0, 0, 0
    valid_decisions, provider_errors = 0, []
    budget = report["budget"]
    completion_policy = report.get("completion_policy", "model-finish")
    require(completion_policy in {"model-finish", "verified-repair"}, "Unknown experiment completion policy")
    trusted_completed = False
    mode = provider["decoding_mode"]
    system_content = {
        "json": JSON_SYSTEM_PROMPT,
        "schema": SYSTEM_PROMPT + "\nAction JSON schema:\n" + json.dumps(ACTION_SCHEMA, separators=(",", ":")),
        "compact-schema": COMPACT_SYSTEM_PROMPT,
    }[mode]
    generation_format = "json" if mode == "json" else (_compact_generation_schema() if mode == "compact-schema" else _generation_schema())
    compact_security = COMPACT_ACTION_SCHEMA["oneOf"][1]["properties"]["changes"]["properties"]["securityContext"]
    index, call_results = 1, []
    while index < len(trace):
        event = trace[index]
        if event.get("event") == "trusted_completion":
            require(completion_policy == "verified-repair" and report.get("completion_actor") == "trusted_engine",
                    "Trusted completion was not explicitly selected/attributed")
            require(index == len(trace) - 1 and history[-1].get("event") in {"candidate_verification", "requested_verification"},
                    "Trusted completion does not immediately follow the final independent verification")
            require(repairs > 0 and current != base and validate_candidate(base, current, contract) == [],
                    "Trusted completion has no changed validated model proposal")
            successful_verifier(result, "Trusted completion")
            require(history[-1].get("manifest_hash") == digest(current)
                    and event == {"event": "trusted_completion", "actor": "trusted_engine", "manifest_hash": digest(current)},
                    "Trusted completion is not bound to the verified candidate")
            require(any(item.get("event") == "decision" and item.get("action", {}).get("action") == "propose" for item in history),
                    "Trusted completion lacks a raw model-origin proposal")
            history.append({"event": "trusted_completion", "actor": "trusted_engine", "manifest_hash": digest(current)})
            trusted_completed = True
            index += 1
            break
        require(event.get("event") in {"decision", "rejected_provider_output"}, "Unexpected event outside an action")
        decisions += 1
        require(decisions <= len(calls) and event.get("step") == decisions, "Decision/call sequence mismatch")
        call = calls[decisions - 1]
        require(call.get("call") == decisions, "Model call sequence mismatch")
        require(call.get("response_truncated") is False and isinstance(call.get("raw_server_response"), str), "Missing complete raw inference response")
        raw = call["raw_server_response"]
        require(call.get("response_sha256") == sha(raw.encode()), "Raw response hash mismatch")
        require(call.get("response_bytes_received") == len(raw.encode()), "Raw response byte count mismatch")
        response = _strict_json_loads(raw)
        require(response.get("model") == MODEL and response.get("done") is True and not response.get("error"), "Incomplete/wrong-model response")
        require(response.get("message", {}).get("role") == "assistant", "Response has no assistant role")
        action, invalid_error = None, None
        try:
            action = _validate_action(_strict_json_loads(response["message"]["content"]))
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            invalid_error = str(exc)[:1000]
        if event["event"] == "decision":
            require(invalid_error is None and call.get("status") == "action_returned"
                    and response.get("done_reason") == "stop", "Valid action did not complete normally")
            require(action == call.get("action") == event.get("action"), "Model response/action/engine decision mismatch")
            if mode == "compact-schema" and action["action"] == "propose":
                require("changes" in action and "manifest" not in action, "Compact decoder emitted a full-manifest proposal")
                if "securityContext" in action["changes"]:
                    require(set(action["changes"]["securityContext"]) == set(compact_security["required"]), "Compact decoder omitted required security fields")
            valid_decisions += 1
        else:
            require(invalid_error is not None and call.get("status") == "error"
                    and call.get("error_code") == "invalid_action" and call.get("action") is None,
                    "Rejected provider output was corrected or was not independently invalid")
            provider_errors.append({"code": "invalid_action", "message": invalid_error})
        for key in ("prompt_eval_count", "eval_count"):
            require(type(response.get(key)) is int and response[key] > 0, "Missing positive actual token usage")
        usage = {"prompt_tokens": response["prompt_eval_count"], "completion_tokens": response["eval_count"],
                 "total_tokens": response["prompt_eval_count"] + response["eval_count"]}
        require(call.get("reported_usage") == usage, "Per-call token usage mismatch")
        prompt_total += usage["prompt_tokens"]
        completion_total += usage["completion_tokens"]
        context = {"task": _task(SimpleNamespace(contract=contract), stop_on_verified_repair=completion_policy == "verified-repair"), "manifest": copy.deepcopy(current),
                   "observations": copy.deepcopy(observations), "evidence": copy.deepcopy(evidence),
                   "remaining": {"actions": budget["max_actions"] - decisions + 1,
                                 "repairs": budget["max_repairs"] - repairs},
                   "history": copy.deepcopy(history)}
        content, compaction = OllamaProvider._compact_context(None, context)
        require(call.get("context_compaction") == compaction, "Compaction metadata mismatch at call " + str(decisions))
        payload = {"model": MODEL, "stream": False, "format": generation_format,
                   "messages": [{"role": "system", "content": system_content}, {"role": "user", "content": content}],
                   "options": {"temperature": 0, "num_predict": 512, "num_ctx": 8192, "num_thread": 2}}
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
        require(call.get("request_bytes") == len(data), "Reconstructed request byte count mismatch")
        exact_request = call.get("request_sha256") == sha(data)
        system_bytes, context_bytes = len(system_content.encode()), len(content.encode())
        require(call.get("system_prompt_bytes") == system_bytes and call.get("prompt_text_bytes") == system_bytes + context_bytes, "Prompt byte audit mismatch")
        reservation += context_bytes + system_bytes + 512 + 1024
        call_results.append({"call": decisions, "action": action["action"] if invalid_error is None else None,
                             "protocol_rejected_before_execution": invalid_error is not None,
                             "request_hash_reconstructed": exact_request,
                             "request_hash_diagnostic": "exact" if exact_request else "unavailable: original insertion ordering was not preserved by canonical bundle serialization; observed mismatch is not treated as proof of equality",
                             "response_hash_verified": True, **usage})
        if invalid_error is not None:
            detail = "".join(character if character.isprintable() else " "
                             for character in "ProviderError: invalid_action: " + invalid_error)[:1200]
            expected = {"event": "rejected_provider_output", "step": decisions,
                        "provider_call": decisions, "detail": detail}
            require(event == expected, "Provider rejection event differs from strict validation")
            history.append(expected)
            observations.append({"trust": "trusted_protocol", "passed": False,
                                 "protocol_errors": [detail], "feedback": [detail]})
            rejected += 1
            index += 1
            continue
        history.append({"event": "decision", "step": decisions, "action": copy.deepcopy(action)})
        index += 1
        kind = action["action"]
        if kind == "inspect":
            require(index < len(trace), "Inspection has no evidence")
            item = trace[index]
            source = action["source"]
            record = {"trust": "untrusted_repository" if source == "repository" else "approved_metadata",
                      "content": scenario.evidence[source]}
            expected = {"event": "evidence", "source": source, "record": record}
            require(item == expected, "Inspected evidence differs from the current trusted fixture")
            evidence[source] = record
            history.append(expected)
            index += 1
        elif kind in ("propose", "test"):
            errors = []
            if kind == "propose":
                require(repairs < budget["max_repairs"], "Repair budget exceeded")
                repairs += 1
                try:
                    proposed = apply_changes(current, action["changes"]) if "changes" in action else action["manifest"]
                except (ValueError, TypeError, KeyError) as exc:
                    errors = [f"Invalid change proposal: {exc}"]
                else:
                    errors = validate_candidate(base, proposed, contract)
                if errors:
                    require(index < len(trace) and trace[index] == {"event": "rejected_proposal", "errors": errors}, "Policy rejection replay mismatch")
                    history.append({"event": "rejected_proposal", "errors": errors})
                    observations.append({"trust": "trusted_policy", "passed": False, "policy_errors": errors, "feedback": errors})
                    rejected += 1
                    index += 1
                    continue
                current = copy.deepcopy(proposed)
            require(index < len(trace), "Action has no protected verification event")
            item = trace[index]
            expected_event = "candidate_verification" if kind == "propose" else "requested_verification"
            require(item.get("event") == expected_event and item.get("manifest_hash") == digest(current), "Verification manifest identity mismatch")
            if kind == "propose":
                require(item.get("candidate") == repairs, "Candidate sequence mismatch")
            result = restore_result(item["result"])
            require(result.get("infrastructure_error") is None and result.get("backend") == "kubernetes", "Verification infrastructure failure")
            if result["runtime"].get("image_id") != image_id:
                waiting = result["runtime"].get("container_waiting", {})
                require(result["runtime"].get("image_id") == "" and _root_policy_rejection(current, waiting)
                        and result["runtime"].get("startup_error") == waiting.get("message")
                        and result.get("runtime_verified") is False and result.get("passed") is False
                        and result.get("behavior_pass") is False and result.get("negative_pass") is False
                        and result.get("kubernetes_execution_observed") is False,
                        "Verification runtime image changed or missing without the specifically confirmed UID policy startup rejection")
            rebuilt = {"event": expected_event}
            if kind == "propose":
                rebuilt["candidate"] = repairs
            rebuilt.update({"manifest_hash": digest(current), "result": result})
            require(rebuilt == item, "Unexpected verification event fields")
            history.append(rebuilt)
            observations.append(dict(result, trust="trusted_verifier"))
            tests += 1
            index += 1
        elif kind == "finish":
            require(index == len(trace) and result.get("passed") is True, "Finish occurred without latest passing verification")
            require(report.get("reason") == action["reason"], "Finish reason differs from the model")
        else:
            raise ValueError("Accepted demo cannot end with abstention")
    require(decisions == len(calls) == provider.get("calls") and valid_decisions > 0, "Unmatched model calls or engine decisions")
    require(1 <= decisions <= budget["max_actions"], "Action budget exceeded")
    require(provider.get("errors") == provider_errors, "Provider errors differ from strictly rejected raw responses")
    require(history == trace and current == candidate and validate_candidate(base, candidate, contract) == [], "Candidate/trace/policy replay mismatch")
    if trusted_completed:
        require(report.get("completion_actor") == "trusted_engine" and report.get("status") == "repaired", "Trusted completion attribution mismatch")
    else:
        require(history[-1].get("action", {}).get("action") == "finish", "No model-origin finish or selected trusted completion")
        require(report.get("completion_actor", "decision_provider") == "decision_provider", "Model finish attribution mismatch")
    require(report["verification"] == result, "Final verifier result differs from last trusted test")
    require(budget["actions"] == decisions and budget["candidate_repairs"] == repairs and budget["test_runs"] == tests, "Engine budget totals differ from replay")
    require(report.get("rejected_actions") == rejected, "Policy rejection totals mismatch")
    total = provider["token_usage"]
    require(total.get("reported_prompt_tokens") == prompt_total and total.get("reported_completion_tokens") == completion_total
            and total.get("reported_total_tokens") == prompt_total + completion_total, "Aggregate token usage mismatch")
    require(total.get("counts_available_calls") == decisions and total.get("counts_complete") is True, "Incomplete token accounting")
    require(total.get("reserved_token_upper_bound") == reservation and reservation <= total["max_total_tokens"]
            and prompt_total + completion_total <= total["max_total_tokens"], "Token budget mismatch")
    return {"calls": call_results, "actual_prompt_tokens": prompt_total, "actual_completion_tokens": completion_total,
            "actual_total_tokens": prompt_total + completion_total, "candidate_repairs": repairs, "test_runs": tests,
            "actions_replayed": decisions, "model_actions_returned": valid_decisions,
            "rejected_actions": rejected,
            "completion_policy": completion_policy,
            "completion_actor": "trusted_engine" if trusted_completed else "decision_provider",
            "model_origin_finish": not trusted_completed,
            "model_origin_changed_proposal_independently_verified": repairs > 0 and current != base,
            "exact_request_hashes_reconstructed": sum(item["request_hash_reconstructed"] for item in call_results),
            "all_requests_exactly_reconstructed": all(item["request_hash_reconstructed"] for item in call_results),
            "model_response_and_engine_effects_consistent": True}


def audit(reports, result):
    fingerprint = source_fingerprint()
    result["source_fingerprint"] = fingerprint
    summary = read(reports / "summary.json")
    kube_summary = read(reports / "kubernetes/summary.json")
    require(summary.get("status") == kube_summary.get("status") == "passed", "Worker/demo did not pass")
    require(summary.get("backend") == kube_summary.get("backend") == "kubernetes" and summary.get("provider") == kube_summary.get("provider") == "ollama", "Wrong execution backend/provider")
    require(summary.get("uses_llm") is True and summary.get("error") is None and kube_summary.get("error") is None, "Worker failure or wrong model-origin claim")
    require(summary.get("model") == MODEL and normalize_digest(summary.get("model_digest")) == MODEL_DIGEST
            and summary.get("cpu_only") is True, "Worker model/CPU summary mismatch")
    require(kube_summary.get("source_fingerprint") == fingerprint, "Kubernetes summary source mismatch")
    pin = read(reports / "model-pin.json")
    require(pin.get("model") == MODEL and normalize_digest(pin.get("model_digest")) == MODEL_DIGEST
            and normalize_digest(pin.get("weight_blob_digest")) == WEIGHT_DIGEST, "Model pins differ from selected public model")
    require(pin.get("ollama_image") == OLLAMA_IMAGE and pin.get("ollama_version") == {"version": "0.6.8"}, "Ollama version/image mismatch")
    require(pin.get("downloaded_weight_sha256_verified") is True and pin.get("model_digest_unchanged") is True and pin.get("cpu_only") is True, "Missing checksum/identity/CPU flags")
    for key in ("tags_before", "tags_after"):
        model_entry(pin[key], key)
    for key in ("ps_before", "ps_after"):
        model_entry(pin[key], key, cpu=True)
    require(model_entry(pin["tags_before"], "selected model") == pin.get("selected_model"), "Selected model snapshot mismatch")
    show, info = pin.get("show", {}), pin.get("show", {}).get("model_info", {})
    parameter_count = info.get("general.parameter_count")
    parameter_count_source = "actual server-reported GGUF general.parameter_count"
    if parameter_count is None:
        # This older pinned GGUF may omit modern general.* metadata. Count only
        # actual recorded tensor dimensions rather than inventing that field.
        tensors = show.get("tensors", [])
        if tensors:
            require(isinstance(tensors, list), "Invalid tensor metadata")
            require(len({item.get("name") for item in tensors}) == len(tensors), "Duplicate GGUF tensor names")
            for item in tensors:
                require(isinstance(item.get("shape"), list) and item["shape"]
                        and all(type(size) is int and size > 0 for size in item["shape"]), "Invalid recorded GGUF tensor shape")
            parameter_count = sum(math.prod(item["shape"]) for item in tensors)
            parameter_count_source = "sum of actual server-reported GGUF tensor shapes; no embedded count field"
        else:
            parameter_count_source = "unavailable: actual show response has neither embedded count nor tensor shapes; model identity instead uses mandatory manifest/weight digests"
    if parameter_count is not None:
        require(type(parameter_count) is int and parameter_count == 3085938688, "Actual model parameter count mismatch")
    if "general.license" in info:
        require(info["general.license"] in {"other", "qwen-research"}, "Embedded license metadata mismatch")
    if "general.license.link" in info:
        require(info["general.license.link"] == LICENSE_URL, "Embedded license link mismatch")
    require(show.get("license", "").startswith("Qwen RESEARCH LICENSE AGREEMENT")
            and pin.get("weight_license") == "Qwen Research License; weights are not published in this repository", "Actual model license text mismatch")
    result["model_parameters_and_license"] = {
        "parameter_count": parameter_count, "parameter_count_available": parameter_count is not None,
        "parameter_count_source": parameter_count_source,
        "license_text_verified": True, "author_license_reference": LICENSE_URL,
        "embedded_license_link_available": "general.license.link" in info,
        "limitation": "The author license URL was verified from primary documentation during audit preparation; absent GGUF metadata is not fabricated.",
    }
    smoke = read(reports / "inference-smoke.json")
    require(smoke == pin.get("inference_smoke") and smoke.get("model") == MODEL and smoke.get("done") is True
            and smoke.get("done_reason") == "stop" and _strict_json_loads(smoke["message"]["content"]) == {"ready": True}, "Smoke response mismatch")
    require(type(smoke.get("prompt_eval_count")) is int and smoke["prompt_eval_count"] > 0
            and type(smoke.get("eval_count")) is int and smoke["eval_count"] > 0, "Smoke has no actual token evidence")
    result["model_identity_and_cpu_verified"] = True
    result["smoke_tokens"] = {"prompt": smoke["prompt_eval_count"], "completion": smoke["eval_count"]}
    bundles, bindings = {}, {}
    for name in ("noop", "naive", "known-good", "agent"):
        binding, contents = load_bundle(reports / "kubernetes/results" / name)
        bindings[name] = binding
        bundles[name] = {key: _strict_json_loads(contents[key]) for key in ("base.json", "candidate.json", "report.json", "trace.json", "contract.json")}
        require(binding["source_fingerprint"] == fingerprint, "Bundle source fingerprint mismatch")
    result["review_hashes"] = {name: binding["review_hash"] for name, binding in bindings.items()}
    agent = bundles["agent"]
    base, candidate, contract, report, trace = (agent[key] for key in ("base.json", "candidate.json", "contract.json", "report.json", "trace.json"))
    for name, bundle in bundles.items():
        require(bundle["base.json"] == base and bundle["contract.json"] == contract, "Baseline task/base differs from the agent")
    require(bundles["noop"]["report.json"].get("accepted") is False and bundles["noop"]["report.json"]["verification"].get("behavior_pass") is True, "Noop control failed to preserve behavior")
    naive = bundles["naive"]["report.json"]
    require(naive.get("accepted") is False and naive["verification"].get("static_pass") is True
            and naive["verification"].get("behavior_pass") is False, "Naive control did not show behavior regression")
    known = bundles["known-good"]["report.json"]
    require(known.get("accepted") is True, "Known-good control failed")
    successful_verifier(known["verification"], "Known-good")
    require(report.get("accepted") is True and report.get("status") == "repaired"
            and report.get("runtime_verified") is True and report.get("backend") == "kubernetes"
            and report.get("executed_unauthorized_effects") == 0, "Agent report is not an accepted runtime repair")
    required_controls = _task(SimpleNamespace(contract=contract))["required_security_controls"]
    candidate_security = candidate["spec"]["template"]["spec"]["containers"][0].get("securityContext", {})
    missing_controls = [key for key in required_controls if key not in candidate_security]
    wrong_controls = [key for key, expected in required_controls.items() if key in candidate_security
                      and (type(candidate_security[key]) is not type(expected) or candidate_security[key] != expected)]
    result["explicit_task_security_targets"] = {
        "required": required_controls, "missing_fields": missing_controls,
        "incorrect_fields": wrong_controls, "all_targets_met": not missing_controls and not wrong_controls,
    }
    require(not missing_controls and not wrong_controls,
            "Accepted candidate misses explicit task security targets: missing=" + repr(missing_controls)
            + "; incorrect=" + repr(wrong_controls))
    successful_verifier(report["verification"], "Agent")
    provider = report["provider"]
    require(provider.get("name") == "ollama" and provider.get("uses_llm") is True and provider.get("is_language_model") is True
            and provider.get("model") == MODEL and provider.get("model_reported") == MODEL
            and normalize_digest(provider.get("model_revision")) == MODEL_DIGEST
            and provider.get("model_revision_available") is True
            and normalize_digest(provider.get("model_identity", {}).get("digest")) == MODEL_DIGEST, "Missing real model provenance")
    mode = provider.get("decoding_mode")
    require(mode in {"json", "schema", "compact-schema"} and pin.get("settings", {}).get("decoding_mode") == mode
            and provider["limits"]["max_output_tokens"] == 512
            and provider["limits"]["num_ctx"] == 8192 and provider["limits"]["num_thread"] == 2, "Unexpected inference settings")
    result["actual_decoding_mode"] = mode
    if mode == "compact-schema":
        security_schema = COMPACT_ACTION_SCHEMA["oneOf"][1]["properties"]["changes"]["properties"]["securityContext"]
        required_fields = ["runAsNonRoot", "runAsUser", "runAsGroup", "readOnlyRootFilesystem",
                           "allowPrivilegeEscalation", "capabilities", "seccompProfile"]
        require(security_schema.get("required") == required_fields, "Compact schema security fields differ from its declared protocol")
        for key in ("runAsUser", "runAsGroup"):
            field = security_schema["properties"][key]
            require(field.get("type") == "integer" and field.get("minimum") == 1
                    and not {"const", "default", "enum"}.intersection(field), "Compact schema inserted/chose task identity values")
        require(provider.get("decoding_constraints", {}).get("proposal_shape") == "changes only"
                and provider["decoding_constraints"].get("security_context_required_fields") == required_fields
                and provider["decoding_constraints"].get("repair_values") == "raw model output; no inferred or inserted identity values",
                "Compact schema provenance metadata differs from the reviewed protocol")
        result["compact_decoder_scope"] = {
            "required_security_fields": required_fields,
            "identity_values_injected_by_schema": False,
            "limitation": "Schema-constrained generation requires the envelope and security field names; correctness is not attributed solely to unconstrained model instruction following.",
        }
    require(pin.get("agent_provider") == provider, "Model pin/provider snapshot differs from accepted bundle")
    image_pin = read(reports / "kubernetes/image-pin.json")
    require(image_pin.get("source_fingerprint") == fingerprint and image_pin.get("runtime_image_id") == contract["kubernetes"]["expected_image_id"], "Trusted runtime image pin mismatch")
    fixture_files = {path.name: sha(path.read_bytes()) for path in (ROOT / "fixtures/cache_app").glob("*") if path.is_file()}
    require(image_pin.get("fixture_files") == fixture_files and image_pin.get("fixture_tag") == base["spec"]["template"]["spec"]["containers"][0]["image"], "Fixture source/tag differs from image setup")
    result["replay"] = replay(base, contract, trace, provider, candidate, report, image_pin["runtime_image_id"])
    result["all_14_protected_checks_passed"] = True
    progress = read(reports / "kubernetes/results/agent-progress.json")
    unhashed = dict(progress)
    snapshot_hash = unhashed.pop("snapshot_hash")
    require(digest(unhashed) == snapshot_hash and progress.get("source_fingerprint") == fingerprint, "Progress snapshot hash/source mismatch")
    require(progress.get("artifact_kind") == "partial_agent_progress" and progress.get("status") == "in_progress"
            and progress.get("accepted") is False and progress.get("exportable") is False, "Progress was mislabeled as accepted/exportable")
    require(progress.get("stage") == "final_bundle_written" and progress.get("execution_state") == "completed"
            and progress.get("final_bundle_review_hash") == bindings["agent"]["review_hash"], "Progress does not reference the final accepted bundle")
    require(progress.get("trace") == trace and progress.get("manifest") == candidate and progress.get("manifest_hash") == digest(candidate)
            and progress.get("verification_manifest_hash") == digest(candidate) and progress.get("verification") == report["verification"]
            and progress.get("provider") == provider and progress.get("budget") == report["budget"]
            and progress.get("base_hash") == digest(base) and progress.get("contract_hash") == digest(contract), "Progress/final evidence mismatch")
    if "completion_policy" in report:
        require(progress.get("completion_policy") == report["completion_policy"]
                and progress.get("completion_actor") == report.get("completion_actor"), "Progress completion policy/actor differs from final bundle")
    result["progress_snapshot_hash"] = snapshot_hash
    commands = read(reports / "model-commands.json")
    cleanup = [item for item in commands if len(item.get("argv", [])) > 2 and item["argv"][1:3] == ["rm", "--force"]]
    require(len(cleanup) == 1 and cleanup[0].get("actual_exit") == 0, "Model cleanup did not succeed")
    model_created = [item for item in commands if len(item.get("argv", [])) > 2 and item["argv"][1:3] == ["run", "--detach"]]
    require(len(model_created) == 1 and model_created[0].get("actual_exit") == 0, "Model container was not created successfully")
    require(cleanup[0]["argv"][-1] == model_created[0]["argv"][model_created[0]["argv"].index("--name") + 1], "Different model container removed")
    kube_commands = read(reports / "kubernetes/commands.json")
    removed = [item for item in kube_commands if item.get("argv", [])[1:3] == ["delete", "cluster"]]
    created = [item for item in kube_commands if item.get("argv", [])[1:3] == ["create", "cluster"]]
    require(len(removed) == len(created) == 1 and removed[0].get("actual_exit") == created[0].get("actual_exit") == 0,
            "Cluster create/cleanup was not successful")
    require(removed[0]["argv"][removed[0]["argv"].index("--name") + 1] == created[0]["argv"][created[0]["argv"].index("--name") + 1], "Different cluster removed")
    require(summary.get("model_cleanup_requested") is True and kube_summary.get("cluster_cleanup_requested") is True, "Cleanup summary missing")
    result["recorded_model_and_cluster_cleanup_succeeded"] = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, help="Extracted reports directory")
    parser.add_argument("--output", type=Path, required=True, help="Standalone JSON audit result")
    args = parser.parse_args()
    result = {"status": "failed", "reports_directory": str(args.reports.resolve()),
              "assumptions": ["Checked-out source, runner and verifier are trusted.",
                              "Recorded API responses and command results are trusted worker evidence, not cryptographic remote attestation.",
                              "One synthetic fixture establishes execution and internal consistency, not generalization or benchmark performance."],
              "request_replay_order_source": "Current Python source plus Kubernetes v1.34 version.Info Go field order. Raw response and engine-effect checks are mandatory; exact request-hash reproduction is reported separately when canonical serialization lost ordering.",
              "error": None}
    try:
        audit(args.reports.resolve(), result)
        result["status"] = "passed"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()), "error": result["error"]}))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
