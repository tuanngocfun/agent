#!/usr/bin/env python3
"""Import pinned, unexecuted infra-bench task definitions; never run upstream code.

Only instruction.md is an agent input. Bootstrap scripts, manifests, task
metadata, tests, and reference solutions remain protected evaluation assets.
Importing these files does not establish a working or independent benchmark.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tomllib
import urllib.request

REPOSITORY = "kubeply/infra-bench"
COMMIT = "9c87b33151cfa0c37aac09056e3644cc472026b7"
DATASET = "datasets/kubernetes-core"
EXPECTED_CASES = 71
# Canonical reviewed Git tree inventory, independent of mutable local manifest
# checksums. Keep source identity anchored when source+metadata change together.
SOURCE_TREE_INVENTORY_SHA256 = "cbbb7517703831217c96f035359e56a6a5f2c9b8c50226d6ec7027352cb11328"
MAX_ARCHIVE_BYTES = 10_000_000
MAX_EXPANDED_BYTES = 20_000_000
MAX_FILE_BYTES = 200_000
MAX_MEMBERS = 5000
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,100}\Z")
SHARED = {"LICENSE", "README.md", "CITATION.cff", DATASET + "/dataset.toml", DATASET + "/metric.py"}
DISCOVERY_TERMS = ("security", "rbac", "network-policy", "secret", "tls", "isolation", "permissions", "certificate")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def source_inventory_digest(tree):
    rows = [{key: row[key] for key in ("path", "mode", "type", "sha", "size") if key in row}
            for row in sorted(tree["tree"], key=lambda row: row["path"])]
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return sha256(canonical)


def verify_source_inventory(tree):
    if source_inventory_digest(tree) != SOURCE_TREE_INVENTORY_SHA256:
        raise ValueError("Infra-Bench pinned source inventory anchor mismatch")


def bounded_download(url, limit):
    request = urllib.request.Request(url, headers={"User-Agent": "kube-security-remediation/corpus-import"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.geturl().split("/", 3)[2] not in {"api.github.com", "codeload.github.com"}:
            raise ValueError("Unexpected download host")
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Download exceeds size limit")
    return data


def safe_path(value):
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        raise ValueError("Unsafe source path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("Unsafe source path")
    return path


def select_files(tree, expected_cases=EXPECTED_CASES):
    if tree.get("truncated") is not False:
        raise ValueError("Incomplete upstream tree")
    entries = {}
    for entry in tree["tree"]:
        name = entry["path"]
        safe_path(name)
        if name in entries:
            raise ValueError("Duplicate upstream path")
        entries[name] = entry
    roots = sorted(name.rsplit("/", 1)[0] for name, entry in entries.items()
                   if name.startswith(DATASET + "/") and name.endswith("/task.toml") and entry["type"] == "blob")
    if len(roots) != expected_cases:
        raise ValueError("Unexpected Kubernetes task count")
    for root in roots:
        if not SAFE_ID.fullmatch(root[len(DATASET) + 1:]):
            raise ValueError("Unsafe case id")
    selected = {}
    for name, entry in entries.items():
        if name in SHARED or any(name.startswith(root + "/") for root in roots):
            if entry["type"] == "tree":
                continue
            if entry["type"] != "blob" or entry["mode"] not in {"100644", "100755"}:
                raise ValueError("Symlink or unexpected Git entry")
            if not isinstance(entry.get("size"), int) or not 0 <= entry["size"] <= MAX_FILE_BYTES:
                raise ValueError("Invalid source file size")
            if not re.fullmatch(r"[0-9a-f]{40}", entry.get("sha", "")):
                raise ValueError("Invalid upstream blob hash")
            selected[name] = entry
    if not SHARED.issubset(selected):
        raise ValueError("Missing license or corpus provenance files")
    return roots, selected


def read_verified_archive(archive_bytes, selected):
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("Archive exceeds size limit")
    prefix = "infra-bench-" + COMMIT + "/"
    contents, seen, expanded = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for index, member in enumerate(archive, 1):
            if index > MAX_MEMBERS:
                raise ValueError("Too many archive members")
            name = member.name.rstrip("/") if member.isdir() else member.name
            safe_path(name)
            if name == prefix[:-1] and member.isdir():
                continue
            if not name.startswith(prefix):
                raise ValueError("Unexpected archive root")
            relative = name[len(prefix):]
            safe_path(relative)
            if relative in seen:
                raise ValueError("Duplicate archive member")
            seen.add(relative)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Archive links and special files are forbidden")
            expanded += member.size
            if member.size > MAX_FILE_BYTES or expanded > MAX_EXPANDED_BYTES:
                raise ValueError("Expanded archive exceeds size limit")
            if relative not in selected:
                continue
            if member.size != selected[relative]["size"]:
                raise ValueError("Archive size differs from pinned Git tree")
            stream = archive.extractfile(member)
            data = stream.read(MAX_FILE_BYTES + 1)
            if git_blob_sha(data) != selected[relative]["sha"]:
                raise ValueError("Archive bytes differ from pinned Git blob")
            data.decode("utf-8")
            if "\x00" in data.decode("utf-8"):
                raise ValueError("Non-text file in definition corpus")
            contents[relative] = data
    if set(contents) != set(selected):
        raise ValueError("Archive is missing selected pinned files")
    return contents


def destination_path(source, roots):
    if source in SHARED:
        return "upstream/" + source, "provenance"
    root = next(root for root in roots if source.startswith(root + "/"))
    case_id = root.rsplit("/", 1)[-1]
    relative = source[len(root) + 1:]
    if relative == "instruction.md":
        return f"cases/{case_id}/agent-inputs/instruction.md", "untrusted_agent_instruction"
    if relative == "task.toml":
        return f"cases/{case_id}/metadata/task.toml", "protected_metadata"
    if relative.startswith(("environment/", "tests/", "solution/")):
        return f"cases/{case_id}/evaluation-assets/{relative}", "protected_evaluation_asset"
    raise ValueError("Unexpected case asset; explicit review required: " + source)


def derive_cases(roots, contents, files):
    """Derive every public count/category and input role from pinned task bytes."""
    cases = []
    for root in roots:
        task = tomllib.loads(contents[root + "/task.toml"].decode("utf-8"))
        case_id = root.rsplit("/", 1)[-1]
        if not all(root + "/" + required in contents for required in
                   ("instruction.md", "solution/solve.sh", "tests/test.sh")):
            raise ValueError("Incomplete case evaluation asset set")
        upstream = task["task"]
        # These tags are literal discovery aids, never validated security labels.
        search_text = " ".join([case_id, upstream.get("description", ""),
                                upstream.get("category", ""), *upstream.get("keywords", [])]).lower()
        matches = [term for term in DISCOVERY_TERMS if term in search_text]
        case_files = [row for row in files if row["source_path"].startswith(root + "/")]
        cases.append({"case_id": case_id, "source_path": root, "upstream_task_name": upstream["name"],
                      "description": upstream.get("description"), "upstream_category": upstream.get("category"),
                      "upstream_keywords": upstream.get("keywords", []),
                      "discovery_only_security_terms": matches,
                      "agent_input_files": [row["path"] for row in case_files if row["role"] == "untrusted_agent_instruction"],
                      "protected_files": [row["path"] for row in case_files if row["role"] != "untrusted_agent_instruction"],
                      "locally_runtime_validated": False, "ready_for_our_agent": False,
                      "validation_status": "imported definitions only; no upstream code executed"})
    return cases


def create_import(tree_bytes, archive_bytes, output, expected_cases=EXPECTED_CASES):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a fresh path")
    if any(parent.is_symlink() for parent in output.absolute().parents):
        raise ValueError("Output ancestors must not be symlinks")
    tree = json.loads(tree_bytes)
    roots, selected = select_files(tree, expected_cases)
    verify_source_inventory(tree)
    contents = read_verified_archive(archive_bytes, selected)
    if b"Apache License" not in contents["LICENSE"] or b"Version 2.0" not in contents["LICENSE"]:
        raise ValueError("Unexpected upstream license")
    # Validate and prepare every destination before creating the output directory.
    files = []
    for source in sorted(contents):
        destination, role = destination_path(source, roots)
        files.append({"source_path": source, "path": destination, "role": role,
                      "bytes": len(contents[source]), "sha256": sha256(contents[source]),
                      "upstream_git_blob_sha1": selected[source]["sha"],
                      "upstream_mode": selected[source]["mode"], "local_mode": "0644"})
    cases = derive_cases(roots, contents, files)
    manifest = {"schema_version": "runtime-corpus-import-v1", "repository": REPOSITORY, "commit": COMMIT,
                "source_url": "https://github.com/" + REPOSITORY + "/tree/" + COMMIT,
                "license": "Apache-2.0", "case_count": len(cases), "file_count": len(files),
                "source_archive_sha256": sha256(archive_bytes), "source_tree_sha256": sha256(tree_bytes),
                "locally_runtime_validated": False, "ready_for_our_agent": False,
                "security_discovery_candidate_count": sum(bool(case["discovery_only_security_terms"]) for case in cases),
                "security_label_status": "literal upstream metadata matches; not manually validated security labels",
                "agent_input_policy": "Only instruction.md. Do not mount the corpus root or protected assets into an agent environment.",
                "required_before_evaluation": ["Review bootstrap privileges and network access", "Pin all images and dependencies",
                    "Adapt to isolated disposable Kubernetes", "Validate broken initial state and reference repair",
                    "Protect verifiers and reference solutions", "Freeze workload-family split before model evaluation"],
                "cases": cases, "files": files}
    output.mkdir(parents=True)
    for row in files:
        target = output / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents[row["source_path"]])
        target.chmod(0o644)
    (output / "source-tree.json").write_bytes(tree_bytes)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    (output / "README.md").write_text(
        "# Imported infra-bench definitions\n\n"
        f"Source: [{REPOSITORY}](https://github.com/{REPOSITORY}/tree/{COMMIT}), pinned commit `{COMMIT}`.\n\n"
        f"{len(cases)} external Kubernetes task definitions, licensed Apache-2.0; exact license is in `upstream/LICENSE`. "
        "These are unexecuted imported definitions, **not newly measured benchmark results**. "
        "No case is yet validated for this project's runtime or agent.\n\n"
        "Only each case's `agent-inputs/instruction.md` is an agent input. Task metadata, setup scripts, "
        "manifests, verifiers and reference solutions are separate protected assets. Do not expose this full directory "
        "to an evaluated agent. Import does not sandbox or approve executing any upstream script.\n\n"
        "`manifest.json` records every imported file's original path, SHA-256, Git blob SHA-1, and role. "
        "`source-tree.json` preserves the pinned GitHub tree response. Keyword matches are discovery aids, "
        "not security annotations. The documentation task template is excluded.\n\n"
        "Before evaluation, vet privileges and dependencies, pin images, build isolated adapters, "
        "verify initial failures and oracle repairs, protect tests, and freeze a family-aware split. "
        "See `required_before_evaluation` in the manifest.\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Fresh output directory")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output must be a fresh path")
    tree = bounded_download(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}?recursive=1", 2_000_000)
    archive = bounded_download(f"https://codeload.github.com/{REPOSITORY}/tar.gz/{COMMIT}", MAX_ARCHIVE_BYTES)
    result = create_import(tree, archive, args.output)
    print(json.dumps({key: result[key] for key in ("repository", "commit", "case_count", "file_count",
                      "security_discovery_candidate_count", "locally_runtime_validated", "ready_for_our_agent")}))


if __name__ == "__main__":
    main()
