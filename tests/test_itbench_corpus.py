"""Import integrity checks; synthetic unit inputs are not benchmark evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ModuleNotFoundError as exc:
    raise unittest.SkipTest("Dataset corpus checks require PyYAML; dedicated corpus CI installs it") from exc

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("itbench_importer", ROOT / "scripts/import_itbench_corpus.py")
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


class ITBenchCorpusTests(unittest.TestCase):
    def test_hashes_bind_upstream_git_blob_bytes(self):
        self.assertEqual(corpus.git_blob_sha(b"test content\n"), "d670460b4b4aece5915caf5c68d12f560a9fe3e4")
        self.assertNotEqual(corpus.git_blob_sha(b"test content\n"), corpus.git_blob_sha(b"test content"))

    def test_tree_cannot_silently_omit_scenarios_or_yamls(self):
        with self.assertRaisesRegex(ValueError, "scenario inventory"):
            corpus.validate_tree([])
        entries = [{"path": corpus.PREFIX + scenario, "type": "directory"} for scenario in corpus.SCENARIOS]
        with self.assertRaisesRegex(ValueError, "YAML file count"):
            corpus.validate_tree(entries)

    def test_duplicate_and_traversal_source_paths_rejected(self):
        one = {"path": corpus.PREFIX + "x.yaml", "type": "file"}
        for entries in ([one, one], [{"path": corpus.PREFIX + "../escape.yaml", "type": "file"}]):
            with self.subTest(entries=entries), self.assertRaisesRegex(ValueError, "unsafe"):
                corpus.validate_tree(entries)

    def test_explicit_oracle_metadata_removed_without_removing_regular_metadata(self):
        resource = {"metadata": {"name": "workload", "annotations": {"evaluation.example/expected": "fail", "description": "business app"},
                                 "labels": {"compliance-status": "violation", "app": "server"}},
                    "spec": {"template": {"metadata": {"annotations": {"cis-policy": "5.2.6"}}}}}
        removed = corpus.scrub_metadata(resource)
        self.assertEqual(len(removed), 3)
        self.assertEqual(resource["metadata"]["labels"], {"app": "server"})
        self.assertEqual(resource["metadata"]["annotations"], {"description": "business app"})
        self.assertEqual(resource["metadata"]["name"], "workload")

    def test_agent_views_exclude_protected_policy_and_compliant_targets(self):
        scenario = corpus.SCENARIOS[0]
        base = corpus.PREFIX + scenario + "/"
        files = {base + "problem.md": b"Assess privilege escalation restrictions.",
                 base + "static-resources/pod.yaml": b"apiVersion: v1\nkind: Pod\nmetadata: {name: real-app}\n",
                 base + "static-resources-compliant/pod.yaml": b"metadata: {name: ORACLE_COMPLIANT_SENTINEL}\n",
                 base + "ground-truth/policy.rego": b"ORACLE_POLICY_SENTINEL"}
        with patch.object(corpus, "SCENARIOS", (scenario,)):
            derived, tasks = corpus.derive_views(files)
        agent = b"\n".join(value for key, value in derived.items() if key.startswith("agent-input/"))
        self.assertNotIn(b"ORACLE", agent)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["split"], "candidate-unassigned")
        self.assertEqual(tasks[0]["group_id"], scenario)
        self.assertEqual(len(tasks[0]["protected_reference_paths"]), 2)
        self.assertIn("agent-input/itbench-ciso-001/static-resources/pod.yaml", derived)
        self.assertFalse(tasks[0]["runtime_validated"])

    def write_manifest(self, root, **changes):
        manifest = {"repository": corpus.REPOSITORY, "revision": corpus.REVISION, "files": []}
        manifest.update(changes)
        (root / "manifest.json").write_text(json.dumps(manifest))

    def test_verifier_rejects_wrong_or_missing_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for revision in (None, "main", "0" * 40):
                self.write_manifest(root, revision=revision)
                with self.subTest(revision=revision), self.assertRaisesRegex(ValueError, "pin"):
                    corpus.verify_corpus(root)

    def test_verifier_rejects_rehashed_or_unregistered_reference_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source").mkdir()
            path = root / "source/policy.rego"
            path.write_bytes(b"tampered")
            self.write_manifest(root, files=[{"path": "source/policy.rego", "bytes": 8, "sha256": corpus.sha256(b"original")}])
            with self.assertRaisesRegex(ValueError, "content hash"):
                corpus.verify_corpus(root)
            self.write_manifest(root)
            with self.assertRaisesRegex(ValueError, "Unregistered"):
                corpus.verify_corpus(root)

    def test_verifier_rejects_duplicate_inventory_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = {"path": "same", "bytes": 0, "sha256": corpus.sha256(b"")}
            self.write_manifest(root, files=[entry, copy.deepcopy(entry)])
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                corpus.verify_corpus(root)
            self.write_manifest(root)
            (root / "link").symlink_to(root / "manifest.json")
            with self.assertRaisesRegex(ValueError, "symlink"):
                corpus.verify_corpus(root)

    def test_downloads_are_confined_to_official_hub(self):
        for url in ("http://huggingface.co/api", "https://example.com/data", "https://huggingface.co.evil.test/api"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "official HTTPS"):
                corpus.read_url(url)

    def test_imported_actual_corpus_is_reproducible_offline(self):
        root = ROOT / "benchmark/corpus-v2/itbench"
        result = corpus.verify_corpus(root)
        self.assertEqual((result["cases"], result["source_yaml_files"], result["source_policy_files"]), (10, 301, 10))
        self.assertFalse(result["runtime_validated"])


if __name__ == "__main__":
    unittest.main()
