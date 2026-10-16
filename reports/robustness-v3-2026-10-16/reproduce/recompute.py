#!/usr/bin/env python3
"""Recompute the published report offline, without models or Kubernetes.

Run from a checkout containing the frozen execution source from d4bf2d5.
Uses the separately versioned offline auditor correcting the original reporter's
namespace-prefix mismatch; it does not rerun or replace the original failed step.
Later report/documentation commits are fine when the frozen source still
matches. Hashes establish reproducibility of trusted execution records, not
hardware attestation. The archive and metadata must already be downloaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

REPORT = Path(__file__).resolve().parents[1]
ROOT = REPORT.parents[1]
LIMIT = 250 * 1024 * 1024
TOP_LEVEL = {"robustness-v3-diagnostic", "robustness-v3-report"}


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key: " + key)
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON: " + value)))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspected_entries(archive):
    entries = archive.infolist()
    if not entries or len(entries) > 20000:
        raise ValueError("Archive is empty or exceeds 20,000 entries")
    seen, files, directories, total = set(), set(), set(), 0
    for info in entries:
        name = info.orig_filename
        parts = name.rstrip("/").split("/")
        if ("\\" in name or "\x00" in name or any(part in ("", ".", "..") or ":" in part for part in parts)
                or parts[0] not in TOP_LEVEL):
            raise ValueError("Unsafe or unexpected archive path: " + repr(name))
        normalized = "/".join(parts)
        if normalized in seen:
            raise ValueError("Duplicate archive path: " + normalized)
        seen.add(normalized)
        mode = stat.S_IFMT(info.external_attr >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.flag_bits & 1:
            raise ValueError("Symlinks, special files and encrypted entries are forbidden")
        if mode == stat.S_IFDIR and not info.is_dir():
            raise ValueError("Inconsistent archive directory entry")
        parents = {"/".join(parts[:index]) for index in range(1, len(parts))}
        if parents & files:
            raise ValueError("Archive path crosses a file")
        if not info.is_dir():
            if normalized in directories:
                raise ValueError("Archive file replaces a directory")
            files.add(normalized)
        else:
            directories.add(normalized)
        directories.update(parents)
        total += info.file_size
        if info.file_size < 0 or total > LIMIT:
            raise ValueError("Archive exceeds the 250 MiB expanded-data limit")
    return entries


def extract(archive, entries, destination):
    total = 0
    for info in entries:
        target = destination.joinpath(*info.filename.rstrip("/").split("/"))
        if info.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with archive.open(info) as source, target.open("xb") as output:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                written += len(block)
                total += len(block)
                if total > LIMIT or written > info.file_size:
                    raise ValueError("Expanded archive exceeded its declared bound")
                output.write(block)
        if written != info.file_size:
            raise ValueError("Archive entry length differs from its declaration")


def normalized_summary(value):
    value = json.loads(json.dumps(value, allow_nan=False))
    for shard in value.get("shards", []):
        shard.pop("path", None)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Fresh directory for restored evidence and recomputed report")
    arguments = parser.parse_args()
    output = arguments.output.absolute()
    if output.exists() or output.is_symlink() or any(parent.is_symlink() for parent in output.parents):
        raise ValueError("Output must be fresh and have no symlink ancestors")
    metadata = read_json(REPORT / "evidence-artifact.json")
    expected = metadata["archive_sha256"]
    archive_path = REPORT / "evidence.zip"
    if not isinstance(expected, str) or not re.fullmatch("[0-9a-f]{64}", expected):
        raise ValueError("Metadata requires an explicit archive SHA256")
    if archive_path.stat().st_size > LIMIT or file_sha256(archive_path) != expected:
        raise ValueError("Evidence archive exceeds size limit or fails its SHA256 check")
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(ROOT / "scripts/freeze_robustness_v3_plan.py"), "--check",
                    str(ROOT / "benchmark/robustness-v3/diagnostic-plan.json")], cwd=ROOT, env=environment, check=True)
    plan = read_json(REPORT / "plan.json")
    if plan != read_json(ROOT / "benchmark/robustness-v3/diagnostic-plan.json"):
        raise ValueError("Published plan differs from the frozen execution plan")
    restored = output / "restored"
    with zipfile.ZipFile(archive_path) as archive:
        entries = inspected_entries(archive)
        output.mkdir(parents=True)
        extract(archive, entries, restored)
    recomputed = output / "recomputed"
    command = [sys.executable, str(ROOT / "scripts/audit_robustness_v3_evidence.py"), "--plan", str(REPORT / "plan.json")]
    command += ["--shard", str(restored / "robustness-v3-diagnostic"),
                "--validation", str(restored / "robustness-v3-diagnostic"), "--output", str(recomputed)]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    if normalized_summary(read_json(recomputed / "summary.json")) != normalized_summary(read_json(REPORT / "summary.json")):
        raise ValueError("Recomputed measured summary differs from the published report")
    csvs = sorted(REPORT.glob("*.csv"))
    for published in csvs:
        if (recomputed / published.name).read_bytes() != published.read_bytes():
            raise ValueError("Recomputed CSV differs: " + published.name)
    print(json.dumps({"offline_reproduction_verified": True, "plan_id": plan["plan_id"],
                      "archive_sha256": expected, "csv_files_compared": len(csvs),
                      "run_id": metadata.get("run_id"), "artifact_id": metadata.get("artifact_id")}))


if __name__ == "__main__":
    main()
