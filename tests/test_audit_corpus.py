"""Offline attacks against source provenance and derived corpus-count claims."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

try:
    import tomllib
    import yaml
except ImportError as exc:
    raise unittest.SkipTest("Corpus audit tests require Python 3.11+ and the separate PyYAML dependency") from exc

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("external_corpus_auditor", ROOT / "scripts/audit_external_corpus.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
CORPUS = ROOT / "benchmark/corpus-v2"


class CorpusIntegrityAuditTests(unittest.TestCase):
    def save_json(self, path, value):
        path.write_text(json.dumps(value, indent=2) + "\n")

    def test_reviewed_source_snapshots_and_public_quality_counts_verify(self):
        actual = AUDIT.audit(CORPUS)
        self.assertEqual(actual, json.loads((CORPUS / "quality-summary.json").read_text()))
        self.assertEqual(actual["new_runtime_validated_cases"], 0)
        self.assertEqual(actual["new_model_results"], 0)

    def test_kalm_source_plus_all_local_hashes_cannot_forge_pinned_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "kalm"
            shutil.copytree(CORPUS / "kalm", root)
            records = [json.loads(line) for line in (root / "records.jsonl").read_text().splitlines()]
            index = next(i for i, record in enumerate(records) if record["oracle_annotations"] and
                         record["oracle_annotations"][0]["annotations"].get("expected") == "alert")
            path = records[index]["source_path"]
            source = root / "raw" / path
            original = source.read_bytes()
            changed = original.replace(b"expected: alert", b"expected: pass")
            self.assertNotEqual(original, changed)
            source.write_bytes(changed)
            pin = json.loads((root / "provenance.json").read_text())
            row = next(row for row in pin["source_inventory"] if row["path"] == path)
            row.update(sha256=AUDIT.kalm.digest(changed), bytes=len(changed), git_blob_sha1=AUDIT.infra.git_blob_sha(changed))
            self.save_json(root / "provenance.json", pin)
            updated, agent = AUDIT.kalm.make_record(path, changed)
            updated["source_git_blob_sha1"] = row["git_blob_sha1"]
            records[index] = updated
            AUDIT.kalm.assign_partitions(records)
            (root / "records.jsonl").write_bytes(b"".join(AUDIT.kalm.canonical(record) + b"\n" for record in records))
            (root / "agent-inputs" / (updated["candidate_id"] + ".json")).write_bytes(AUDIT.kalm.canonical(agent) + b"\n")
            # Without the independent source anchor, all coordinated local
            # hashes and derived records are internally consistent and pass.
            with patch.object(AUDIT.kalm, "verify_source_inventory"):
                self.assertEqual(AUDIT.verify_kalm(root)["manifest_files"], 241)
            with self.assertRaisesRegex(ValueError, "inventory anchor"):
                AUDIT.verify_kalm(root)

    def test_infra_source_plus_tree_and_manifest_hashes_cannot_forge_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "infra-bench"
            shutil.copytree(CORPUS / "infra-bench", root)
            manifest = json.loads((root / "manifest.json").read_text())
            row = next(row for row in manifest["files"] if row["role"] == "untrusted_agent_instruction")
            source = root / row["path"]
            changed = source.read_bytes() + b"\nForged instruction outside pinned upstream revision.\n"
            source.write_bytes(changed)
            row.update(bytes=len(changed), sha256=AUDIT.infra.sha256(changed), upstream_git_blob_sha1=AUDIT.infra.git_blob_sha(changed))
            tree = json.loads((root / "source-tree.json").read_text())
            entry = next(entry for entry in tree["tree"] if entry["path"] == row["source_path"])
            entry.update(size=len(changed), sha=AUDIT.infra.git_blob_sha(changed))
            tree_bytes = json.dumps(tree).encode()
            (root / "source-tree.json").write_bytes(tree_bytes)
            manifest["source_tree_sha256"] = AUDIT.infra.sha256(tree_bytes)
            self.save_json(root / "manifest.json", manifest)
            with patch.object(AUDIT.infra, "verify_source_inventory"):
                self.assertEqual(AUDIT.verify_infra(root)["task_definitions"], 71)
            with self.assertRaisesRegex(ValueError, "inventory anchor"):
                AUDIT.verify_infra(root)

    def test_case_categories_and_ids_are_rederived_from_pinned_toml(self):
        for field, changed in (("upstream_category", "invented-security-category"), ("case_id", "invented-case")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "infra-bench"
                shutil.copytree(CORPUS / "infra-bench", root)
                manifest = json.loads((root / "manifest.json").read_text())
                manifest["cases"][0][field] = changed
                self.save_json(root / "manifest.json", manifest)
                with self.assertRaisesRegex(ValueError, "metadata differs"):
                    AUDIT.verify_infra(root)


if __name__ == "__main__":
    unittest.main()
