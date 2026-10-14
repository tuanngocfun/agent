"""Freeze and verify a public synthetic benchmark before any evaluation call."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .artifacts import digest, source_fingerprint
from .benchmark_cases import benchmark_cases_manifest
from .providers import COMPACT_SYSTEM_PROMPT, _compact_generation_schema

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = {
    "temperature": 0, "num_ctx": 8192, "num_thread": 2,
    "max_output_tokens": 512, "provider_timeout_seconds": 420,
    "max_total_tokens": 32768, "completion_policy": "verified-repair",
    "decoding_mode": "compact-schema",
    "initial_evidence_policy": "all approved metadata and untrusted repository supplied to both methods",
    "repetition_policy": "two repeated executions at identical settings; no independent stochastic-sample claim",
    "case_deadline_seconds": 900, "shard_deadline_seconds": 960,
    "cpu_threads": 2, "cpu_memory_limit": "4g",
}
IMAGES = {
    "ollama": "ollama/ollama:0.6.8@sha256:50ab2378567a62b811a2967759dd91f254864c3495cbe50576bd8a85bc6edd56",
    "base": "python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1",
    "node": "kindest/node:v1.34.0@sha256:7416a61b42b1662ca6ca89f02028ac133a309a2a30ba309614e8ec94d976dc5a",
}


def evaluator_fingerprint():
    files = ["src/kube_repair/engine.py", "src/kube_repair/policy.py",
             "src/kube_repair/verification.py", "src/kube_repair/kubernetes_backend.py",
             "src/kube_repair/providers.py", "src/kube_repair/benchmark_cases.py",
             "src/kube_repair/benchmark_protocol.py", "src/kube_repair/benchmark_reporting.py",
             "scripts/benchmark_worker.py", "scripts/benchmark_report.py",
             "scripts/collect_benchmark.py", "scripts/freeze_benchmark_plan.py",
             ".github/workflows/benchmark.yml", ".github/workflows/ci.yml",
             ".github/workflows/kubernetes-demo.yml"]
    return digest({name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files})


def make_plan(registry):
    suite = benchmark_cases_manifest()
    schema_hash = digest(_compact_generation_schema())
    methods = [{"method_id": name, "token_ceiling": 32768, "max_actions": actions,
                "max_repairs": repairs, "guided_schema_fingerprint": schema_hash}
               for name, actions, repairs in (("one-shot", 1, 1), ("feedback", 6, 3))]
    definitions = suite["definitions"]
    cases = [{"case_id": row["id"], "expected_outcome": row["expected"], **row}
             for row in definitions if row["split"] == "evaluation"]
    plan = {
        "schema_version": 1, "benchmark_version": suite["version"],
        "suite_fingerprint": suite["suite_sha256"],
        "evaluator_fingerprint": evaluator_fingerprint(),
        "source_fingerprint": source_fingerprint(),
        "settings_fingerprint": digest(SETTINGS), "settings": copy.deepcopy(SETTINGS),
        "system_prompt_sha256": hashlib.sha256(COMPACT_SYSTEM_PROMPT.encode()).hexdigest(),
        "images": copy.deepcopy(IMAGES), "models": copy.deepcopy(registry["models"]),
        "model_registry_fingerprint": digest(registry), "methods": methods,
        "cases": cases, "repetitions": 2, "case_shards": 4,
        "development_cases_excluded": [row["id"] for row in definitions if row["split"] == "development"],
        "primary_expected_model_tasks": len(cases) * len(methods) * len(registry["models"]) * 2,
        "runner_budget": {"matrix_jobs": 48, "timeout_minutes_per_job": 20,
                          "matrix_timeout_upper_bound_minutes": 960,
                          "ci_and_reporting_timeout_upper_bound_minutes": 20,
                          "campaign_timeout_upper_bound_minutes": 980},
        "controls": ["noop", "naive", "template", "known-good"],
        "primary_score": "task-correct outcome on each case, with repeated stability and repair-only rates reported separately",
        "comparison_scope": "same source, suite, guided schema, initial evidence and token ceiling; action budgets differ and observed compute is reported",
        "limitations": ["Eight public synthetic evaluation cases across two authored fixture families.",
                        "No production-workload or hidden-held-out generalization claim.",
                        "All models are from the Qwen2.5 family; this is not a cross-family frontier-model study.",
                        "Two repetitions measure execution stability at fixed temperature, not independent cases.",
                        "No post-evaluation tuning, replacing failures or skipping missing cells within this plan."],
    }
    plan["plan_id"] = "kube-benchmark-v1-" + digest(plan)
    return plan


def validate_locked_plan(plan):
    registry = json.loads((ROOT / "benchmark/models.json").read_text())
    expected = make_plan(registry)
    if plan != expected:
        different = sorted(key for key in set(plan) | set(expected) if plan.get(key) != expected.get(key))
        raise ValueError("Frozen benchmark differs from current source/protocol: " + ", ".join(different))
    return plan
