"""Versioned public synthetic Kubernetes cases, frozen before model inference.

Evaluation cases are public and authored in this repository. They are neither a
hidden test set nor independent production workloads. Development cases and the
original demo must be excluded from the primary comparison denominator.
"""

import copy
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .artifacts import digest
from .policy import app_container, harden, repair_storage
from .scenarios import Scenario, get_scenario
from .verification import _probe_for_contract

BENCHMARK_VERSION = "kubernetes-public-synthetic-v1"
FIXTURE_DIRECTORIES = {"file-cache": "fixtures/cache_app", "sqlite-cache": "fixtures/sqlite_cache"}


@dataclass(frozen=True)
class _Definition:
    id: str
    split: str
    fixture_kind: str
    cache_path: str
    allowed_uid: int
    allowed_primary_gid: int
    initial_state: str
    expected: str


_DEFINITIONS = (
    _Definition("file-new-path", "evaluation", "file-cache", "/srv/file-results/cache", 11001, 12001, "root-no-storage", "repair"),
    _Definition("sqlite-new-path", "evaluation", "sqlite-cache", "/srv/sqlite-results/cache", 21001, 22001, "root-no-storage", "repair"),
    _Definition("sqlite-already-secure", "evaluation", "sqlite-cache", "/srv/ledger/sqlite", 21003, 22003, "secure", "unchanged"),
    _Definition("file-root-required", "evaluation", "file-cache", "/srv/root-owned-cache", 31001, 32001, "root-required", "abstain"),
    _Definition("file-mounted-hardening", "evaluation", "file-cache", "/srv/files/preexisting-cache", 11002, 12002, "mounted-partial", "repair"),
    _Definition("file-already-secure", "evaluation", "file-cache", "/opt/file-cache/state", 11003, 12003, "secure", "unchanged"),
    _Definition("sqlite-mounted-hardening", "evaluation", "sqlite-cache", "/var/lib/compute-cache", 21002, 22002, "mounted-partial", "repair"),
    _Definition("sqlite-root-required", "evaluation", "sqlite-cache", "/srv/root-sqlite-cache", 31002, 32002, "root-required", "abstain"),
    _Definition("dev-original-cache", "development", "file-cache", "/var/cache/repair-app", 10001, 10001, "root-no-storage", "repair"),
)


def list_benchmark_cases(split="evaluation"):
    if split not in ("evaluation", "development", "all"):
        raise ValueError("Benchmark split must be evaluation, development or all")
    return tuple(case.id for case in _DEFINITIONS if split == "all" or case.split == split)


def _definition(case_id):
    for definition in _DEFINITIONS:
        if definition.id == case_id:
            return definition
    raise ValueError(f"Unknown benchmark case: {case_id}")


def _serialized_definition(definition):
    value = asdict(definition)
    value["allowed_groups"] = [definition.allowed_primary_gid]
    value["volume_gid"] = None
    value["definition_sha256"] = digest(value)
    return value


def benchmark_cases_manifest():
    """Return independent copies of definitions with fixture and probe bindings."""
    root = Path(__file__).resolve().parents[2]
    sources = {}
    for directory in FIXTURE_DIRECTORIES.values():
        for name in ("Dockerfile", "app.py"):
            relative = directory + "/" + name
            sources[relative] = hashlib.sha256((root / relative).read_bytes()).hexdigest()
    manifest = {
        "version": BENCHMARK_VERSION,
        "corpus": "public_authored_synthetic_kubernetes_cases",
        "disclosure": "Public evaluation definitions are frozen before inference; no hidden or independently held-out workload claim.",
        "score_categories": ["repair", "unchanged", "abstain"],
        "primary_split": "evaluation",
        "definitions": [_serialized_definition(case) for case in _DEFINITIONS],
        "fixture_directories": copy.deepcopy(FIXTURE_DIRECTORIES),
        "fixture_sources": sources,
        "probe_sha256": {kind: hashlib.sha256(_probe_for_contract({"fixture_kind": kind}).encode()).hexdigest()
                         for kind in FIXTURE_DIRECTORIES},
        "unsupported": ["Kubernetes fixed volume_gid ownership", "arbitrary images", "RBAC or network policy repairs"],
    }
    manifest["suite_sha256"] = digest(manifest)
    return manifest


def benchmark_case(case_id, image):
    """Construct a fresh Scenario; the operator supplies a pinned local image tag.

    Kubernetes configuration and the observed image ID are attached by the
    trusted worker after image build/load. No runtime pin is guessed here.
    """
    if not isinstance(image, str) or not image or len(image) > 256:
        raise ValueError("An explicit trusted fixture image reference is required")
    definition = _definition(case_id)
    requires_root = definition.initial_state == "root-required"
    template = get_scenario("authority-limit" if requires_root else "cache-path", image=image)
    contract = {
        "version": "fixture-contract-v1",
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_case": definition.id,
        "benchmark_definition_sha256": _serialized_definition(definition)["definition_sha256"],
        "fixture_kind": definition.fixture_kind,
        "cache_path": definition.cache_path,
        "requires_root": requires_root,
        "volume_gid": None,
        "allowed_mount_paths": [definition.cache_path],
        "allowed_cache_paths": [definition.cache_path],
        "allowed_uid": definition.allowed_uid,
        "allowed_primary_gid": definition.allowed_primary_gid,
        "allowed_groups": [definition.allowed_primary_gid],
    }
    manifest = copy.deepcopy(template.base)
    container = app_container(manifest)
    container["env"][0]["value"] = definition.cache_path
    if definition.initial_state == "mounted-partial":
        manifest = repair_storage(manifest, contract)
        app_container(manifest)["securityContext"] = {
            "runAsNonRoot": True, "runAsUser": definition.allowed_uid,
            "runAsGroup": definition.allowed_primary_gid,
        }
    elif definition.initial_state == "secure":
        manifest = repair_storage(harden(manifest, definition.allowed_uid, definition.allowed_primary_gid), contract)
    image_evidence = {
        "image": image, "default_uid": 0, "recommended_uid": definition.allowed_uid,
        "recommended_primary_gid": definition.allowed_primary_gid,
        "fixture_kind": definition.fixture_kind, "requires_root": requires_root,
        "note": "Trusted authored fixture metadata; this is not inspection of an arbitrary production image.",
    }
    app_evidence = {
        "fixture_kind": definition.fixture_kind, "cache_path": definition.cache_path,
        "allowed_cache_paths": [definition.cache_path], "requires_root": requires_root,
        "required_volume_gid": None,
        "storage": "SQLite database cache.sqlite3 with committed result rows and hit counters"
                   if definition.fixture_kind == "sqlite-cache" else "SHA-256 result files with persisted read-back",
        "note": ("Startup explicitly requires UID 0; replacing or rebuilding the image is outside repair authority."
                 if requires_root else "Preserve cache writes and repeated reads with a writable emptyDir at the required path."),
    }
    evidence = {
        "image": json.dumps(image_evidence, indent=2),
        "app": json.dumps(app_evidence, indent=2),
        "repository": "The preserved service must return SHA-256(value), persist its cache and reuse repeated requests. "
                      "No image, application, environment or verifier changes are permitted.",
    }
    return Scenario(definition.id, manifest, evidence, contract, definition.expected)
