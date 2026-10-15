#!/usr/bin/env python3
"""Import a pinned, static ITBench CISO corpus; never execute upstream code.

These are policy-assessment candidates, not measured Kubernetes repairs. The
separate agent-input views exclude reference policies and compliant targets.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import urllib.parse
import urllib.request

import yaml

REPOSITORY = "ibm-research/ITBench-Lite"
REVISION = "d0916b08ba421ce5e672e9ad68aa947d938dfef0"
PREFIX = "snapshots/ciso/v0.1/"
SCENARIOS = tuple("k8s-opa-static-cis-" + x for x in (
    "5.1.1", "5.1.3", "5.1.5", "5.1.6", "5.1.7",
    "5.2.2", "5.2.3", "5.2.4", "5.2.5", "5.2.6"))
MISSING_ADVERTISED = ["5.2.7", "5.2.8", "5.2.9", "5.7.3", "5.7.4"]
MAX_FILE_BYTES = 2_000_000
EXPECTED_YAML_FILES = 301
TREE_SHA256 = "2e868f4e16ee76368dc2c4ed5cbe6a17aa5fd882b119a3379fde92da32181bf1"
README_SHA256 = "55fe4b3019e173948e079676e1228d0e45e4c4119b3ee21664158da834778b40"
LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0.txt"
LICENSE_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
ORACLE_KEY = re.compile(r"(?:oracle|evaluation|expected|ground.?truth|compliance|violation|(?:^|[./_-])cis(?:$|[./_-]))", re.I)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def dumps(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def read_url(url: str, limit: int = MAX_FILE_BYTES):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "huggingface.co") and url != LICENSE_URL:
        raise ValueError("Only official HTTPS Hugging Face endpoints are allowed")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kube-repair-corpus-import/1"}), timeout=45) as response:
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError("Upstream response exceeds byte limit")
        return data, response.headers.get("Link", "")


def pinned_tree():
    """Follow all Hub tree pages; reject duplicates or a changed scenario set."""
    url = f"https://huggingface.co/api/datasets/{REPOSITORY}/tree/{REVISION}/{PREFIX.rstrip('/')}?recursive=true&limit=1000"
    entries, seen_pages = [], set()
    while url:
        if url in seen_pages or len(seen_pages) >= 20:
            raise ValueError("Repeated or excessive Hub tree pagination")
        seen_pages.add(url)
        raw, link = read_url(url, 5_000_000)
        page = json.loads(raw)
        if not isinstance(page, list):
            raise ValueError("Hub tree returned an incomplete/error response")
        entries.extend(page)
        links = re.findall(r'<([^>]+)>;\s*rel="?([^",;]+)"?', link)
        next_links = [value for value, rel in links if rel == "next"]
        if len(next_links) > 1:
            raise ValueError("Ambiguous Hub pagination")
        url = next_links[0] if next_links else ""
        if link and not links:
            raise ValueError("Cannot parse Hub pagination")
    validate_tree(entries)
    entries = sorted(entries, key=lambda item: item["path"])
    if sha256(dumps(entries)) != TREE_SHA256:
        raise ValueError("Pinned Hub inventory hash changed")
    return entries


def safe_path(path: str) -> bool:
    p = PurePosixPath(path)
    return bool(path and not p.is_absolute() and ".." not in p.parts and "\\" not in path and str(p) == path)


def validate_tree(entries):
    paths = [entry["path"] for entry in entries]
    if len(paths) != len(set(paths)) or any(not safe_path(p) or not p.startswith(PREFIX) for p in paths):
        raise ValueError("Duplicate or unsafe upstream inventory paths")
    scenarios = {p[len(PREFIX):].split("/")[0] for p in paths if p[len(PREFIX):].startswith("k8s-")}
    if scenarios != set(SCENARIOS):
        raise ValueError("Pinned upstream scenario inventory changed")
    files = {entry["path"] for entry in entries if entry["type"] == "file"}
    yaml_files = {p for p in files if p.endswith(".yaml")}
    if len(yaml_files) != EXPECTED_YAML_FILES:
        raise ValueError("Pinned upstream YAML file count changed")
    for scenario in SCENARIOS:
        for suffix in ("problem.md", "ground-truth/policy.rego"):
            if PREFIX + scenario + "/" + suffix not in files:
                raise ValueError("Missing task or reference policy")
        for variant in ("static-resources/", "static-resources-compliant/"):
            if not any(p.startswith(PREFIX + scenario + "/" + variant) and p.endswith(".yaml") for p in files):
                raise ValueError("Missing resource variant")


def selected_entries(entries):
    selected = []
    for entry in entries:
        path = entry["path"]
        if entry["type"] != "file":
            continue
        relative = path[len(PREFIX):]
        parts = PurePosixPath(relative).parts
        if len(parts) >= 2 and parts[0] in SCENARIOS and (
            relative.endswith("/problem.md") or relative.endswith("/ground-truth/policy.rego")
            or (path.endswith(".yaml") and parts[1] in ("static-resources", "static-resources-compliant"))):
            selected.append(entry)
    return sorted(selected, key=lambda x: x["path"])


def scrub_metadata(value, removed=None, trail=""):
    """Remove explicit oracle keys while preserving workload selectors/names.

    Public resource names may still hint at violations. No held-out/leakage-free
    claim is made. This transformation is for static input only, never deployment.
    """
    removed = [] if removed is None else removed
    if isinstance(value, dict):
        for kind in ("annotations", "labels"):
            mapping = value.get("metadata", {}).get(kind, {}) if isinstance(value.get("metadata"), dict) else {}
            if isinstance(mapping, dict):
                for key in list(mapping):
                    if ORACLE_KEY.search(str(key)):
                        removed.append(trail + "/metadata/" + kind + "/" + str(key))
                        del mapping[key]
        for key, item in value.items():
            scrub_metadata(item, removed, trail + "/" + str(key))
    elif isinstance(value, list):
        for i, item in enumerate(value):
            scrub_metadata(item, removed, trail + "/" + str(i))
    return removed


def derive_views(files):
    """Return derived bytes and metadata using only non-reference task inputs."""
    derived, tasks, parsing = {}, [], []
    for index, scenario in enumerate(SCENARIOS, 1):
        task_id = f"itbench-ciso-{index:03d}"
        agent_base = f"agent-input/{task_id}/"
        base = PREFIX + scenario + "/"
        source_paths = sorted(p for p in files if p.startswith(base + "static-resources/") and p.endswith(".yaml"))
        target_paths = sorted(p for p in files if p.startswith(base + "static-resources-compliant/") and p.endswith(".yaml"))
        resources, removed = [], []
        for path in source_paths:
            documents = list(yaml.safe_load_all(files[path]))
            removed_keys = scrub_metadata(documents)
            removed.extend({"source_path": path, "metadata_path": key} for key in removed_keys)
            filename = path[len(base + "static-resources/"):]
            resources.append({"filename": filename, "documents": documents})
            derived[agent_base + "static-resources/" + filename] = yaml.safe_dump_all(documents, sort_keys=False).encode()
            parsing.append({"source_path": path, "documents": len(documents), "variant": "insecure"})
        for path in target_paths:
            parsing.append({"source_path": path, "documents": len(list(yaml.safe_load_all(files[path]))), "variant": "compliant"})
        derived[agent_base + "problem.md"] = files[base + "problem.md"]
        derived[agent_base + "resources.json"] = dumps(resources)
        tasks.append({
            "task_id": task_id, "source_scenario": scenario, "group_id": scenario,
            "split": "candidate-unassigned", "task_type": "static-policy-assessment-candidate",
            "runtime_validated": False, "model_evaluated": False,
            "agent_input_paths": [agent_base + "problem.md", agent_base + "resources.json"] + [agent_base + "static-resources/" + resource["filename"] for resource in resources],
            "protected_reference_paths": ["source/" + base + "ground-truth/policy.rego"] + ["source/" + p for p in target_paths],
            "insecure_source_paths": ["source/" + p for p in source_paths],
            "removed_metadata": removed,
            "limitations": ["Public authored resources may expose hints in names or selectors", "No application behavior oracle or repair runtime has been validated", "Aggregate and per-object YAML files may describe duplicate resources"],
        })
    derived["tasks.json"] = dumps(tasks)
    derived["yaml-parsing.json"] = dumps(parsing)
    return derived, tasks


def build_corpus(output: Path):
    if output.exists():
        raise ValueError("Output must not exist; use --verify for existing corpus")
    entries = pinned_tree()
    selected = selected_entries(entries)
    def fetch(entry):
        path = entry["path"]
        data, _ = read_url(f"https://huggingface.co/datasets/{REPOSITORY}/raw/{REVISION}/{urllib.parse.quote(path, safe='/')}")
        if len(data) != entry["size"] or git_blob_sha(data) != entry["oid"]:
            raise ValueError("Upstream Git blob size/hash mismatch: " + path)
        return path, data
    with ThreadPoolExecutor(max_workers=8) as pool:
        files = dict(pool.map(fetch, selected))
    readme, _ = read_url(f"https://huggingface.co/datasets/{REPOSITORY}/raw/{REVISION}/README.md")
    # Only a declared upstream license is copied; this importer grants no new license.
    if sha256(readme) != README_SHA256 or "license: apache-2.0" not in readme.decode():
        raise ValueError("Upstream dataset license declaration changed")
    license_text, _ = read_url(LICENSE_URL)
    if sha256(license_text) != LICENSE_SHA256:
        raise ValueError("Official Apache license text checksum changed")
    derived, tasks = derive_views(files)
    payload = {"source/" + p: data for p, data in files.items()}
    payload.update({"provenance/upstream-README.md": readme, "provenance/hub-tree.json": dumps(entries),
                    "provenance/LICENSE-Apache-2.0.txt": license_text})
    payload.update(derived)
    manifest = {
        "format_version": 1, "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": REPOSITORY, "revision": REVISION, "declared_license": "apache-2.0",
        "license_text_source": LICENSE_URL, "license_text_sha256": LICENSE_SHA256,
        "source_url": f"https://huggingface.co/datasets/{REPOSITORY}/tree/{REVISION}/{PREFIX.rstrip('/')}",
        "case_count": len(tasks), "source_yaml_files": len([p for p in files if p.endswith('.yaml')]),
        "source_policy_files": len([p for p in files if p.endswith('/policy.rego')]),
        "upstream_card_claimed_ciso_cases": 15, "available_ciso_cases": len(SCENARIOS),
        "advertised_but_absent_cis_scenarios": MISSING_ADVERTISED,
        "status": "imported-static-candidates-not-runtime-validated",
        "case_unit": "One upstream CISO policy scenario; files and repeated objects are not independent cases",
        "split_policy": "No held-out split claimed; future splits must keep every variant of a scenario together",
        "files": [{"path": path, "bytes": len(data), "sha256": sha256(data)} for path, data in sorted(payload.items())],
    }
    # Do all network and parse validation before creating the destination.
    output.mkdir(parents=True)
    for path, data in sorted(payload.items()):
        destination = output / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    (output / "manifest.json").write_bytes(dumps(manifest))
    verify_corpus(output)
    return manifest


def verify_corpus(root: Path):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("repository") != REPOSITORY or manifest.get("revision") != REVISION:
        raise ValueError("Corpus pin missing or changed")
    inventory = manifest["files"]
    paths = [row["path"] for row in inventory]
    if len(paths) != len(set(paths)) or any(not safe_path(p) for p in paths):
        raise ValueError("Duplicate or unsafe corpus inventory paths")
    actual = set()
    for p in root.rglob("*"):
        if p.is_symlink():
            raise ValueError("Corpus symlinks are forbidden")
        if p.is_file():
            actual.add(p.relative_to(root).as_posix())
    if actual != set(paths) | {"manifest.json"}:
        raise ValueError("Unregistered or missing corpus files")
    for row in inventory:
        data = (root / row["path"]).read_bytes()
        if len(data) != row["bytes"] or sha256(data) != row["sha256"]:
            raise ValueError("Corpus content hash mismatch: " + row["path"])
    for path, expected in (("provenance/hub-tree.json", TREE_SHA256),
                           ("provenance/upstream-README.md", README_SHA256),
                           ("provenance/LICENSE-Apache-2.0.txt", LICENSE_SHA256)):
        if sha256((root / path).read_bytes()) != expected:
            raise ValueError("Pinned provenance content hash mismatch: " + path)
    if manifest.get("status") != "imported-static-candidates-not-runtime-validated":
        raise ValueError("Corpus status must not imply measured runtime results")
    entries = json.loads((root / "provenance/hub-tree.json").read_text())
    validate_tree(entries)
    files = {}
    for entry in selected_entries(entries):
        path = entry["path"]
        data = (root / "source" / path).read_bytes()
        if len(data) != entry["size"] or git_blob_sha(data) != entry["oid"]:
            raise ValueError("Source differs from pinned Git blob: " + path)
        files[path] = data
    derived, tasks = derive_views(files)
    for path, data in derived.items():
        if (root / path).read_bytes() != data:
            raise ValueError("Derived agent view does not match pinned sources: " + path)
    if (manifest["case_count"], manifest["source_yaml_files"], manifest["source_policy_files"]) != (10, 301, 10):
        raise ValueError("Corpus task/file totals changed")
    return {"status": "verified-static-candidates", "cases": len(tasks), "source_yaml_files": 301,
            "source_policy_files": 10, "runtime_validated": False, "model_evaluated": False,
            "revision": REVISION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("benchmark/corpus-v2/itbench"))
    parser.add_argument("--verify", action="store_true", help="Verify offline; no network or runtime execution")
    args = parser.parse_args()
    result = verify_corpus(args.output) if args.verify else build_corpus(args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "files"}, indent=2))


if __name__ == "__main__":
    main()
