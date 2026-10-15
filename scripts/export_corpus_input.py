#!/usr/bin/env python3
"""Export one audited static candidate's intended model inputs, without answers.

Mount only OUTPUT/agent into an agent environment. OUTPUT/receipt.json is an
operator-only provenance record. Exporting does not deploy or evaluate a case.
Requires Python 3.11+ and the separate corpus dependency PyYAML.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_external_corpus as audit

MAX_INPUT_BYTES = 8_000_000
MAX_TOTAL_BYTES = 20_000_000
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,120}\Z")
SOURCES = ("kalm", "itbench", "infra-bench")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def check_ancestors(path):
    if any(candidate.is_symlink() for candidate in (path.absolute(), *path.absolute().parents)):
        raise ValueError("Symlink in source or output path")


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Unsafe input path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("Unsafe input path")
    return path


def read_file(root, value):
    relative_path(value)
    path = root / value
    check_ancestors(path)
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Expected bounded regular corpus file: " + value)
    data = path.read_bytes()
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("Input file exceeds its size limit")
    data.decode("utf-8")
    return data


def read_json(root, value):
    return json.loads(read_file(root, value))


def verify_source(source, root):
    """Rebuild the chosen corpus's views and validate its pinned original bytes."""
    if source == "kalm":
        return audit.verify_kalm(root)
    if source == "itbench":
        return audit.itbench.verify_corpus(root)
    if source == "infra-bench":
        return audit.verify_infra(root)
    raise ValueError("Unknown corpus source")


def only_candidate(rows, field, candidate_id):
    matches = [row for row in rows if row[field] == candidate_id]
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous candidate id")
    return matches[0]


def selection(source, root, candidate_id):
    """Return an explicit allowlist, never a directory copy or metadata export."""
    if source == "kalm":
        pin = read_json(root, "provenance.json")
        if (pin["repository"], pin["commit"]) != (audit.kalm.REPOSITORY, audit.kalm.COMMIT):
            raise ValueError("Source pin changed")
        rows = [json.loads(line) for line in read_file(root, "records.jsonl").decode().splitlines()]
        row = only_candidate(rows, "candidate_id", candidate_id)
        files = [{"corpus_path": "agent-inputs/" + candidate_id + ".json", "agent_path": "resources.json",
                  "sha256": row["agent_input_sha256"]}]
        metadata = ["provenance.json", "records.jsonl"]
        revision = pin["commit"]
        repository = pin["repository"]
    elif source == "itbench":
        pin = read_json(root, "manifest.json")
        if (pin["repository"], pin["revision"]) != (audit.itbench.REPOSITORY, audit.itbench.REVISION):
            raise ValueError("Source pin changed")
        row = only_candidate(read_json(root, "tasks.json"), "task_id", candidate_id)
        prefix = "agent-input/" + candidate_id + "/"
        inventory = {entry["path"]: entry for entry in pin["files"]}
        if len(inventory) != len(pin["files"]):
            raise ValueError("Duplicate corpus inventory path")
        files = []
        for path in row["agent_input_paths"]:
            relative_path(path)
            if not path.startswith(prefix):
                raise ValueError("Input is outside its source-specific candidate prefix")
            target = path[len(prefix):]
            relative_path(target)
            if target not in {"problem.md", "resources.json"} and not (
                    target.startswith("static-resources/") and target.endswith((".yaml", ".yml"))):
                raise ValueError("Protected or unexpected file cannot be promoted into agent input")
            if path in row["protected_reference_paths"]:
                raise ValueError("Protected reference cannot be an agent input")
            if path not in inventory:
                raise ValueError("Agent input is not registered in the audited corpus")
            files.append({"corpus_path": path, "agent_path": target, "sha256": inventory[path]["sha256"],
                          "bytes": inventory[path]["bytes"]})
        if not {"problem.md", "resources.json"}.issubset(entry["agent_path"] for entry in files):
            raise ValueError("Missing required ITBench input files")
        metadata = ["manifest.json", "tasks.json"]
        revision, repository = pin["revision"], pin["repository"]
    else:
        pin = read_json(root, "manifest.json")
        if (pin["repository"], pin["commit"]) != (audit.infra.REPOSITORY, audit.infra.COMMIT):
            raise ValueError("Source pin changed")
        row = only_candidate(pin["cases"], "case_id", candidate_id)
        path = f"cases/{candidate_id}/agent-inputs/instruction.md"
        if row["agent_input_files"] != [path] or path in row["protected_files"]:
            raise ValueError("Protected asset promoted into agent input")
        entries = [entry for entry in pin["files"] if entry["path"] == path]
        if len(entries) != 1 or entries[0]["role"] != "untrusted_agent_instruction":
            raise ValueError("Instruction is not bound to its permitted source role")
        files = [{"corpus_path": path, "agent_path": "instruction.md", "sha256": entries[0]["sha256"],
                  "bytes": entries[0]["bytes"]}]
        metadata = ["manifest.json", "source-tree.json"]
        revision, repository = pin["commit"], pin["repository"]
    if not files or len(files) > 200 or len({entry["corpus_path"] for entry in files}) != len(files):
        raise ValueError("Empty, duplicate or excessive model input inventory")
    if len({entry["agent_path"] for entry in files}) != len(files):
        raise ValueError("Duplicate exported agent path")
    return files, metadata, repository, revision, digest(canonical(row))


def export_candidate(corpus_root, source, candidate_id, output):
    if source not in SOURCES:
        raise ValueError("Unknown corpus source")
    if not isinstance(candidate_id, str) or not SAFE_ID.fullmatch(candidate_id):
        raise ValueError("Unsafe candidate id")
    corpus_root, output = Path(corpus_root), Path(output)
    check_ancestors(corpus_root)
    check_ancestors(output)
    if output.exists():
        raise ValueError("Output must be a fresh path")
    if output.resolve().is_relative_to(corpus_root.resolve()):
        raise ValueError("Output must be outside the audited corpus")
    root = corpus_root / source
    check_ancestors(root)
    if not root.is_dir():
        raise ValueError("Missing corpus source directory")
    # Verification completes before any generated output is written.
    verification = verify_source(source, root)
    files, metadata, repository, revision, record_hash = selection(source, root, candidate_id)
    payloads, inventory, total = [], [], 0
    for entry in files:
        relative_path(entry["agent_path"])
        data = read_file(root, entry["corpus_path"])
        actual_hash = digest(data)
        if actual_hash != entry["sha256"] or "bytes" in entry and len(data) != entry["bytes"]:
            raise ValueError("Agent input bytes differ from the audited source hash")
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Export exceeds total byte limit")
        payloads.append((entry["agent_path"], data))
        inventory.append({"corpus_path": entry["corpus_path"], "agent_path": entry["agent_path"],
                          "bytes": len(data), "sha256": actual_hash})
    receipt = {"schema_version": "corpus-static-input-export-v1", "status": "static_input_export_only",
               "source": source, "repository": repository, "revision": revision, "candidate_id": candidate_id,
               "candidate_record_sha256": record_hash, "files": inventory, "total_input_bytes": total,
               "source_metadata": [{"path": path, "sha256": digest(read_file(root, path))} for path in metadata],
               "source_integrity_verification": verification, "runtime_validated": False, "model_evaluated": False,
               "new_runtime_results": 0, "intended_model_mount": "agent/",
               "operator_only_files": ["receipt.json"],
               "limitations": ["Imported static input only; not a runnable remediation case or measured model result.",
                   "Mount only agent/; keep this receipt, the corpus root, reference policies, tests and solutions outside the agent.",
                   "Public authored inputs may retain semantic hints. Export is packaging, not a runtime sandbox."]}
    output.mkdir(parents=True)
    (output / "agent").mkdir()
    for relative, data in payloads:
        path = output / "agent" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o644)
    (output / "receipt.json").write_bytes(canonical(receipt))
    (output / "receipt.json").chmod(0o644)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, default=Path("benchmark/corpus-v2"))
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--output", type=Path, required=True, help="Fresh directory outside the source corpus")
    args = parser.parse_args()
    try:
        result = export_candidate(args.corpus_root, args.source, args.candidate_id, args.output)
    except (ValueError, KeyError) as exc:
        parser.exit(2, str(exc) + "\n")
    print(json.dumps({key: result[key] for key in ("status", "source", "candidate_id", "total_input_bytes",
                                                  "runtime_validated", "model_evaluated")}))


if __name__ == "__main__":
    main()
