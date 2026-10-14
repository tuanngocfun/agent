"""Local, content-bound review and export. No cluster or remote side effects."""

import difflib
import hashlib
import json
import os
import shutil
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_fingerprint():
    root = Path(__file__).resolve().parents[2]
    files = sorted((root / "src" / "kube_repair").glob("*.py"))
    files += sorted(p for p in (root / "fixtures").rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts
                    and p.suffix not in (".pyc", ".pyo"))
    return digest({str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in files if p.is_file()})


def write_bundle(output, base, candidate, report, trace, contract):
    path = Path(output).resolve()
    path.mkdir(parents=True, exist_ok=False)
    payloads = {
        "base.json": canonical(base), "candidate.json": canonical(candidate),
        "report.json": canonical(report), "trace.json": canonical(trace),
        "contract.json": canonical(contract),
    }
    payloads["patch.diff"] = "".join(difflib.unified_diff(
        payloads["base.json"].splitlines(keepends=True),
        payloads["candidate.json"].splitlines(keepends=True),
        fromfile="base/deployment.json", tofile="candidate/deployment.json",
    ))
    payloads["REVIEW.md"] = (
        f"# Review: {report['scenario']}\n\n"
        f"Outcome: **{report['status']}**. Provider: `{report['provider']['name']}`. "
        f"Backend: `{report['backend']}`. Runtime verified: **{report['runtime_verified']}**.\n\n"
        "Simulation checks model fixture semantics; they do not execute a workload. "
        "Docker checks this fixture in a container; Linux checks a process with Landlock. "
        "The Kubernetes backend executes the selected fixture on an explicitly named lab cluster. "
        "Verification scope and infrastructure errors are recorded in report.json.\n\n"
        "Inspect `patch.diff`, `report.json` and `trace.json`. Run `review --bundle <this-directory>` "
        "to validate contents and obtain the hash for an explicit local export. "
        "No deployment or PR is performed. A failed/abstained run cannot be exported as a repair.\n"
    )
    for name, content in payloads.items():
        (path / name).write_text(content, encoding="utf-8")
    binding = {
        "schema_version": 1,
        "base_hash": digest(base), "candidate_hash": digest(candidate),
        "contract_hash": digest(contract), "source_fingerprint": source_fingerprint(),
        "files": {name: hashlib.sha256(content.encode()).hexdigest() for name, content in payloads.items()},
    }
    binding["review_hash"] = digest(binding)
    (path / "binding.json").write_text(canonical(binding), encoding="utf-8")
    return binding


def load_bundle(bundle):
    root = Path(bundle).resolve()
    binding_path = root / "binding.json"
    if binding_path.is_symlink():
        raise ValueError("Review binding must be a regular file")
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    unhashed = dict(binding)
    review_hash = unhashed.pop("review_hash")
    if digest(unhashed) != review_hash:
        raise ValueError("Review binding has changed")
    required = {"base.json", "candidate.json", "report.json", "trace.json", "contract.json", "patch.diff", "REVIEW.md"}
    if set(binding["files"]) != required:
        raise ValueError("Unexpected review inventory")
    contents = {}
    for name, expected in binding["files"].items():
        file = root / name
        if file.is_symlink() or not file.is_file():
            raise ValueError(f"Invalid artifact file: {name}")
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Review artifact changed: {name}")
        contents[name] = content
    if binding["source_fingerprint"] != source_fingerprint():
        raise ValueError("Policy/runner/source changed; create and review a fresh run")
    for name, field in (("base.json", "base_hash"), ("candidate.json", "candidate_hash"), ("contract.json", "contract_hash")):
        if digest(json.loads(contents[name])) != binding[field]:
            raise ValueError(f"Version binding mismatch: {name}")
    return binding, contents


def export_bundle(bundle, output, expected_hash, base_file=None):
    root = Path(bundle).resolve()
    binding, contents = load_bundle(root)
    if expected_hash != binding["review_hash"]:
        raise ValueError("Reviewed hash no longer matches the current bundle")
    if base_file and digest(json.loads(Path(base_file).read_text())) != binding["base_hash"]:
        raise ValueError("Base manifest changed since review")
    report = json.loads(contents["report.json"])
    if report["status"] not in ("repaired", "unchanged") or not report["accepted"]:
        raise ValueError("Only accepted local candidates can be exported")
    target = Path(output).resolve()
    if target.exists():
        raise ValueError("Export output must be a new directory")
    if (root / "exported.json").exists():
        raise ValueError("This review was already exported; replay refused")
    lock = root / ".export.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    created = False
    try:
        if (root / "exported.json").exists():
            raise ValueError("This review was already exported; replay refused")
        # Recheck after acquiring the lock; use the validated bytes for export.
        new_binding, contents = load_bundle(root)
        if new_binding["review_hash"] != expected_hash:
            raise ValueError("Review changed during export")
        target.mkdir(parents=True, exist_ok=False)
        created = True
        (target / "deployment.json").write_bytes(contents["candidate.json"])
        for name in ("patch.diff", "report.json", "REVIEW.md", "contract.json"):
            (target / name).write_bytes(contents[name])
        receipt = {"review_hash": expected_hash, "output": str(target), "effect": "local_export_only"}
        (target / "receipt.json").write_text(canonical(receipt))
        (root / "exported.json").write_text(canonical(receipt))
        return receipt
    except Exception:
        if created:
            shutil.rmtree(target)
        raise
    finally:
        lock.unlink(missing_ok=True)
