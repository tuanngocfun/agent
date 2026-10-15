#!/usr/bin/env python3
"""Import pinned upstream KALM examples as static candidates, never deploy them.

Dependency: PyYAML >= 6.0.1, < 7. Existing outputs are never overwritten.
The raw corpus includes intentionally insecure manifests and answer annotations;
only agent-inputs/ is intended as model input. No runtime readiness is asserted.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import urllib.request

try:
    import yaml
except ImportError as exc:
    raise SystemExit("This importer requires PyYAML >=6.0.1,<7; install it in an isolated environment.") from exc

REPOSITORY = "dynatrace-oss/Kalm-Benchmark"
COMMIT = "6da1b2d75e7fb05a69adc632e89ad0dc84e5f115"
EXPECTED_FILES = 241
# SHA-256 of canonical sorted (path, Git blob SHA-1, byte count) source rows.
# This trusted anchor binds mutable local provenance to the reviewed upstream
# revision; merely retaining the commit string would not establish that link.
SOURCE_INVENTORY_SHA256 = "e7d20c7926e4e13b2f8ba0f5682cff21566eab1f470c9b2e99c31c84f697be25"
MAX_FILE_BYTES = 2_000_000
MAX_API_BYTES = 8_000_000
MAX_TOTAL_BYTES = 50_000_000
BENCHMARK_ANNOTATIONS = {"expected", "check_path", "description", "ccss_score", "ccss_severity", "standards"}
RUNTIME_ANNOTATION_PREFIXES = (
    "container.apparmor.security.beta.kubernetes.io/",
    "container.seccomp.security.alpha.kubernetes.io/",
    "seccomp.security.alpha.kubernetes.io/",
)
BUILTIN_NAMESPACES = {"default", "kube-system", "kube-public", "kube-node-lease"}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_inventory_digest(rows: list[dict]) -> str:
    normalized = [{key: row[key] for key in ("path", "git_blob_sha1", "bytes")}
                  for row in sorted(rows, key=lambda row: row["path"])]
    return digest(canonical(normalized))


def verify_source_inventory(rows: list[dict]) -> None:
    if source_inventory_digest(rows) != SOURCE_INVENTORY_SHA256:
        raise ValueError("KALM pinned source inventory anchor mismatch")


def safe_manifest_path(path: str) -> PurePosixPath:
    parsed = PurePosixPath(path)
    if (not isinstance(path, str) or "\\" in path or parsed.is_absolute()
            or parsed.parts[:1] != ("manifests",) or len(parsed.parts) != 2
            or any(part in ("", ".", "..") for part in path.split("/"))
            or not re.fullmatch(r"[A-Za-z0-9_.-]+\.(yaml|yml)", parsed.name)):
        raise ValueError(f"Unsafe upstream manifest path: {path!r}")
    return parsed


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("YAML mapping keys must be unique strings")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


# Keep timestamps as source strings instead of constructing non-JSON date objects.
StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in values if tag != "tag:yaml.org,2002:timestamp"]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_documents(raw: bytes) -> list[dict]:
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Manifest exceeds the byte limit")
    text = raw.decode("utf-8")
    depth = events = 0
    for event in yaml.parse(text, Loader=StrictLoader):
        events += 1
        if events > 100_000 or isinstance(event, yaml.AliasEvent):
            raise ValueError("YAML aliases or excessive node counts are unsupported")
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > 64:
                raise ValueError("YAML exceeds nesting limit")
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    docs = [doc for doc in yaml.load_all(text, Loader=StrictLoader) if doc is not None]
    if not 1 <= len(docs) <= 64:
        raise ValueError("Expected between one and 64 Kubernetes resource documents")
    for doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("kind"), str) or not isinstance(doc.get("apiVersion"), str):
            raise ValueError("Each YAML document must declare Kubernetes apiVersion and kind")
    canonical(docs)  # Reject non-JSON types, NaN, and infinity.
    return docs


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def sanitize_documents(documents: list[dict], *, structural=False) -> tuple[list[dict], dict]:
    """Remove answers and anonymize descriptive names while preserving exact refs.

    Functional legacy seccomp/AppArmor annotations and PSA labels remain. Other
    annotations are removed and inventoried; this is a static input, not a claim
    of semantic equivalence or an independently healthy runtime workload.
    """
    replacements = {}
    label_values = {}
    removed_annotations = Counter()
    for item in walk(documents):
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            for field in ("name", "namespace"):
                value = metadata.get(field)
                if isinstance(value, str) and value not in BUILTIN_NAMESPACES:
                    if value not in replacements:
                        replacements[value] = (f"identity-{len(replacements)+1}" if structural else "resource-" + digest(value.encode())[:16])
            labels = metadata.get("labels")
            if isinstance(labels, dict) and isinstance(labels.get("check"), str):
                value = labels["check"]
                label_values[value] = "group" if structural else "group-" + digest(value.encode())[:16]
    replacements.update(label_values)
    # Benchmark namespace identity can also occur in label selector values.
    if "kalm-benchmark" not in replacements:
        replacements["kalm-benchmark"] = "corpus"

    def transform(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [transform(child) for child in value]
        if isinstance(value, dict):
            result = {}
            for key, child in value.items():
                if key == "annotations" and isinstance(child, dict):
                    kept = {}
                    for annotation, content in child.items():
                        if annotation.startswith(RUNTIME_ANNOTATION_PREFIXES):
                            kept[annotation] = transform(content)
                        else:
                            removed_annotations[annotation] += 1
                    if kept:
                        result[key] = kept
                elif key == "check":
                    result["corpus.example/group"] = transform(child)
                else:
                    result[key] = transform(child)
            return result
        return value

    return transform(documents), {"removed_annotation_keys": dict(sorted(removed_annotations.items())),
                                  "anonymized_identifier_count": len(replacements)}


def make_record(path: str, raw: bytes) -> tuple[dict, dict]:
    safe_manifest_path(path)
    documents = parse_documents(raw)
    sanitized, transform = sanitize_documents(documents)
    structural, _ = sanitize_documents(documents, structural=True)
    annotations = []
    check_ids = set()
    for index, doc in enumerate(documents):
        metadata = doc.get("metadata", {})
        source_annotations = metadata.get("annotations", {})
        selected = {key: source_annotations[key] for key in sorted(BENCHMARK_ANNOTATIONS) if key in source_annotations}
        if selected:
            annotations.append({"document_index": index, "kind": doc["kind"], "annotations": selected})
        label = metadata.get("labels", {}).get("check")
        if isinstance(label, str):
            check_ids.add(label)
    stem = PurePosixPath(path).stem
    category = "support" if stem.startswith("_") else stem.split("-", 1)[0]
    target = sorted({a["annotations"]["check_path"] for a in annotations if "check_path" in a["annotations"]})
    families = sorted({"-".join(check.split("-")[:2]) for check in check_ids})
    record = {
        "candidate_id": "kalm-" + digest(path.encode())[:20],
        "source_path": path,
        "source_url": f"https://github.com/{REPOSITORY}/blob/{COMMIT}/{path}",
        "source_sha256": digest(raw),
        "source_bytes": len(raw),
        "document_count": len(documents),
        "resource_kinds": dict(sorted(Counter(d["kind"] for d in documents).items())),
        "category": category,
        "source_check_ids": sorted(check_ids),
        "source_rule_families": families,
        "source_check_paths": target,
        "oracle_annotations": annotations,
        "semantic_duplicate_group": digest(canonical(structural)),
        "exact_duplicate_group": digest(raw),
        "status": "static_candidate",
        "runtime_validated": False,
        "runtime_contract": None,
        "sanitization": transform,
    }
    agent_input = {"schema_version": "kalm-static-input-v1", "resources": sanitized}
    record["agent_input_sha256"] = digest(canonical(agent_input) + b"\n")
    return record, agent_input


def assign_partitions(records: list[dict]) -> dict:
    """Keep source rule families AND exact/structural duplicates in one split.

    This is a development/evaluation assignment for future use, not a claim of
    unseen training data or a held-out model experiment already performed.
    """
    parents = list(range(len(records)))
    def find(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    seen = {}
    for i, record in enumerate(records):
        tokens = [(field, record[field]) for field in ("exact_duplicate_group", "semantic_duplicate_group")]
        tokens += [("rule_family", family) for family in record["source_rule_families"]]
        for token in tokens:
            if token in seen:
                parents[find(i)] = find(seen[token])
            else:
                seen[token] = i
    components = defaultdict(list)
    for i in range(len(records)):
        components[find(i)].append(i)
    for indices in components.values():
        group = digest(canonical(sorted(records[i]["candidate_id"] for i in indices)))
        partition = "development" if int(group[:8], 16) % 5 == 0 else "evaluation"
        if all(records[i]["category"] == "support" for i in indices):
            partition = "support"
        for i in indices:
            records[i]["split_group"] = group
            records[i]["partition"] = partition
    return {"method": "sha256 connected components; rule family or exact/structural duplicate links; hash modulo five development",
            "components": len(components), "record_counts": dict(sorted(Counter(r["partition"] for r in records).items())),
            "note": "Public upstream examples; this split does not establish model-training decontamination or unseen-data generalization."}


def fetch(url: str, *, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "kube-remediation-corpus-import/1"})
    with urllib.request.urlopen(request, timeout=45) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected redirect while reading pinned source")
        payload = response.read(limit + 1)
    if len(payload) > limit:
        raise ValueError("Source response exceeds byte limit")
    return payload


def write_exclusive(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)


def import_corpus(output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a fresh directory")
    tree_url = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}?recursive=1"
    tree = json.loads(fetch(tree_url, limit=MAX_API_BYTES))
    if tree.get("truncated"):
        raise ValueError("Truncated upstream tree inventory")
    manifest_entries = sorted((entry for entry in tree["tree"] if entry["type"] == "blob"
        and entry["path"].startswith("manifests/") and entry["path"].endswith((".yaml", ".yml"))), key=lambda entry: entry["path"])
    if len(manifest_entries) != EXPECTED_FILES:
        raise ValueError(f"Pinned source inventory mismatch: expected {EXPECTED_FILES} YAML files")
    for entry in manifest_entries:
        safe_manifest_path(entry["path"])
        if entry.get("size", MAX_FILE_BYTES + 1) > MAX_FILE_BYTES:
            raise ValueError("Manifest tree entry exceeds byte limit")
    notices = [entry for entry in tree["tree"] if entry["type"] == "blob" and entry["path"] in ("LICENSE", "NOTICE")]
    if not any(entry["path"] == "LICENSE" for entry in notices):
        raise ValueError("Pinned source has no LICENSE")
    entries = manifest_entries + notices
    verify_source_inventory([{"path": entry["path"], "git_blob_sha1": entry["sha"], "bytes": entry["size"]}
                             for entry in entries])
    def download(entry):
        url = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}/{entry['path']}"
        raw = fetch(url, limit=MAX_FILE_BYTES)
        git_sha = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if git_sha != entry["sha"] or len(raw) != entry["size"]:
            raise ValueError(f"Pinned Git blob mismatch: {entry['path']}")
        return entry, raw
    with ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = list(pool.map(download, entries))
    if sum(len(raw) for _, raw in downloaded) > MAX_TOTAL_BYTES:
        raise ValueError("Corpus exceeds total byte limit")
    records, agent_inputs = [], {}
    for entry, raw in downloaded:
        if entry["path"].startswith("manifests/"):
            record, agent_input = make_record(entry["path"], raw)
            record["source_git_blob_sha1"] = entry["sha"]
            records.append(record)
            agent_inputs[record["candidate_id"]] = agent_input
    partitions = assign_partitions(records)
    category_counts = Counter(record["category"] for record in records)
    summary = {
        "schema_version": "kalm-static-corpus-v1", "repository": REPOSITORY, "commit": COMMIT,
        "license": "Apache-2.0", "manifest_file_count": len(records),
        "resource_document_count": sum(record["document_count"] for record in records),
        "labeled_candidate_files": sum(bool(record["oracle_annotations"]) for record in records),
        "source_categories": dict(sorted(category_counts.items())),
        "unique_source_rule_families": len({family for record in records for family in record["source_rule_families"]}),
        "exact_unique_files": len({record["exact_duplicate_group"] for record in records}),
        "structural_unique_inputs": len({record["semantic_duplicate_group"] for record in records}),
        "runtime_validated_cases": 0, "model_experiments_run": 0, "partitions": partitions,
        "status": "static_candidates_only",
        "limits": ["YAML files and documents are not independent runtime repair tasks.",
                   "Source labels describe expected scanner findings, not complete security or behavioral ground truth.",
                   "No cluster deployment, model evaluation, or behavioral verification was performed by this importer.",
                   "Public generated scanner fixtures share templates and can be present in model training data.",
                   "Raw YAML and records contain answers; give models only agent-inputs, never raw filenames or oracle records.",
                   "Sanitization removes non-runtime annotations and anonymizes declared identifiers; it is not a proven behavior-preserving transformation.",
                   "Structural grouping normalizes identifiers only; subtler template similarity remains possible."]}
    provenance = {"repository": REPOSITORY, "commit": COMMIT, "tree_api_url": tree_url,
                  "tree_sha": tree["sha"], "license": "Apache-2.0", "yaml_parser_version": yaml.__version__,
                  "source_inventory": [{"path": entry["path"], "git_blob_sha1": entry["sha"], "sha256": digest(raw), "bytes": len(raw)} for entry, raw in downloaded]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Exclusive creation, including protection against symlink reuse.
    write_exclusive(output / "INCOMPLETE", b"Import has not finished.\n")
    for entry, raw in downloaded:
        destination = output / "raw" / entry["path"] if entry["path"].startswith("manifests/") else output / entry["path"]
        write_exclusive(destination, raw)
    for candidate_id, agent_input in agent_inputs.items():
        write_exclusive(output / "agent-inputs" / (candidate_id + ".json"), canonical(agent_input) + b"\n")
    write_exclusive(output / "records.jsonl", b"".join(canonical(record) + b"\n" for record in records))
    write_exclusive(output / "summary.json", json.dumps(summary, sort_keys=True, indent=2).encode() + b"\n")
    write_exclusive(output / "provenance.json", json.dumps(provenance, sort_keys=True, indent=2).encode() + b"\n")
    write_exclusive(output / "README.md", ("# KALM static candidate corpus\n\n"
        f"Imported **{len(records)} upstream YAML files / {summary['resource_document_count']} resource documents** "
        f"from [{REPOSITORY}](https://github.com/{REPOSITORY}/tree/{COMMIT}), revision `{COMMIT}`, Apache-2.0.\n\n"
        "These are scanner test examples. **Zero cases in this corpus have been validated as executable repair tasks, "
        "and zero model results are claimed.** Intentionally vulnerable raw manifests are retained for provenance; do not deploy them indiscriminately.\n\n"
        "`agent-inputs/` contains answer-sanitized static JSON. `raw/` and `records.jsonl` contain oracle labels and "
        "descriptive filenames and must remain outside an evaluated model's accessible workspace. Runtime-relevant "
        "legacy seccomp/AppArmor annotations and PSA labels remain; other annotations are removed. Declared names "
        "and benchmark check labels are anonymized with exact references consistently rewritten. This is not a "
        "proven behavior-preserving conversion.\n\n"
        "`provenance.json` binds every original file by pinned Git blob SHA-1 plus SHA-256; original bytes and "
        "license text are unmodified. `records.jsonl` separates source scanner expectations from model input and "
        "records exact and identifier-normalized structural duplicate groups. Source rule families and duplicates "
        "are assigned together to a deterministic development/evaluation partition. This public split does not "
        "claim hidden tests or model-training decontamination.\n\n"
        "Regenerate into a fresh directory with `python3 scripts/import_kalm_corpus.py --output NEW_DIRECTORY`. "
        "Dependency: `PyYAML>=6.0.1,<7`. Nothing from upstream is executed. See `summary.json` for precise counts and limitations.\n").encode())
    (output / "INCOMPLETE").unlink()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = import_corpus(args.output)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise SystemExit(f"Corpus import failed: {exc}") from exc
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
