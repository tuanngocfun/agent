"""Importer safety tests use synthetic fixtures, never benchmark observations."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import sys
from unittest.mock import patch

if sys.version_info < (3, 11):
    raise unittest.SkipTest('Runtime corpus tooling requires Python 3.11+ for tomllib')

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_corpus_import", ROOT / "scripts/import_runtime_corpus.py")
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


class RuntimeCorpusImportTests(unittest.TestCase):
    def fixture(self):
        contents = {name: b"Synthetic unit fixture\n" for name in IMPORTER.SHARED}
        contents["LICENSE"] = b"Apache License\nVersion 2.0\nSynthetic unit fixture\n"
        root = IMPORTER.DATASET + "/example-rbac-case"
        contents[root + "/task.toml"] = b'[task]\nname="unit/example"\ncategory="access-and-isolation"\ndescription="A unit fixture"\nkeywords=["rbac"]\n'
        contents[root + "/instruction.md"] = b"Repair this synthetic unit fixture\n"
        contents[root + "/solution/solve.sh"] = b"exit 77 # forbidden answer for agent\n"
        contents[root + "/tests/test.sh"] = b"exit 78 # forbidden verifier for agent\n"
        contents[root + "/environment/scripts/bootstrap-cluster"] = b"exit 79 # setup must not execute\n"
        tree = {"truncated": False, "sha": "0" * 40,
                "tree": [{"path": name, "type": "blob", "mode": "100755" if name.endswith(".sh") else "100644",
                          "size": len(data), "sha": IMPORTER.git_blob_sha(data)} for name, data in contents.items()]}
        return contents, tree

    def archive(self, contents, extra=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, data in contents.items():
                member = tarfile.TarInfo("infra-bench-" + IMPORTER.COMMIT + "/" + name)
                member.size = len(data)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(data))
            if extra:
                archive.addfile(extra)
        return stream.getvalue()

    def import_fixture(self, output, contents=None, tree=None, archive=None):
        baseline_contents, baseline_tree = self.fixture()
        contents = baseline_contents if contents is None else contents
        tree = baseline_tree if tree is None else tree
        # Synthetic fixtures have their own explicit trusted inventory anchor;
        # production always uses the reviewed upstream anchor in the importer.
        with patch.object(IMPORTER, "SOURCE_TREE_INVENTORY_SHA256", IMPORTER.source_inventory_digest(tree)):
            return IMPORTER.create_import(json.dumps(tree).encode(), self.archive(contents) if archive is None else archive,
                                          output, expected_cases=1)

    def test_original_bytes_and_upstream_hashes_are_preserved_without_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "corpus"
            contents, tree = self.fixture()
            manifest = self.import_fixture(output)
            self.assertEqual(manifest["case_count"], 1)
            self.assertFalse(manifest["locally_runtime_validated"])
            self.assertFalse(manifest["ready_for_our_agent"])
            for row in manifest["files"]:
                data = (output / row["path"]).read_bytes()
                self.assertEqual(data, contents[row["source_path"]])
                self.assertEqual(IMPORTER.sha256(data), row["sha256"])
                self.assertEqual(IMPORTER.git_blob_sha(data), row["upstream_git_blob_sha1"])
                self.assertEqual((output / row["path"]).stat().st_mode & 0o777, 0o644)

    def test_answers_setup_and_verifiers_never_enter_agent_input_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "corpus"
            manifest = self.import_fixture(output)
            case = manifest["cases"][0]
            self.assertEqual(case["agent_input_files"], ["cases/example-rbac-case/agent-inputs/instruction.md"])
            self.assertTrue(case["discovery_only_security_terms"])
            for row in manifest["files"]:
                if any(term in row["source_path"] for term in ("/solution/", "/tests/", "/environment/")):
                    self.assertEqual(row["role"], "protected_evaluation_asset")
                    self.assertNotIn(row["path"], case["agent_input_files"])
                    self.assertIn(row["path"], case["protected_files"])

    def test_changed_blob_is_rejected_before_creating_output(self):
        contents, tree = self.fixture()
        contents[next(name for name in contents if name.endswith("instruction.md"))] = b"changed bytes\n"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "corpus"
            with self.assertRaisesRegex(ValueError, "differs|differ"):
                self.import_fixture(output, contents=contents, tree=tree)
            self.assertFalse(output.exists())

    def test_fresh_output_required_without_overwriting_existing_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "corpus"
            output.mkdir()
            marker = output / "keep"
            marker.write_text("preserve")
            with self.assertRaisesRegex(ValueError, "fresh"):
                self.import_fixture(output)
            self.assertEqual(marker.read_text(), "preserve")

    def test_output_cannot_follow_a_symlink_ancestor(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "actual").mkdir()
            (directory / "link").symlink_to(directory / "actual", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlinks"):
                self.import_fixture(directory / "link" / "corpus")
            self.assertFalse((directory / "actual" / "corpus").exists())

    def test_path_traversal_absolute_path_and_archive_symlink_are_rejected(self):
        contents, _ = self.fixture()
        extras = [tarfile.TarInfo("../escape"), tarfile.TarInfo("/absolute")]
        link = tarfile.TarInfo("infra-bench-" + IMPORTER.COMMIT + "/unselected-link")
        link.type, link.linkname = tarfile.SYMTYPE, "/outside"
        extras.append(link)
        for extra in extras:
            with self.subTest(path=extra.name), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "corpus"
                with self.assertRaises(ValueError):
                    self.import_fixture(output, archive=self.archive(contents, extra=extra))
                self.assertFalse(output.exists())

    def test_duplicate_member_is_rejected(self):
        contents, _ = self.fixture()
        duplicate = tarfile.TarInfo("infra-bench-" + IMPORTER.COMMIT + "/LICENSE")
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                self.import_fixture(Path(temporary) / "corpus", archive=self.archive(contents, extra=duplicate))

    def test_incomplete_tree_wrong_task_count_and_symlink_tree_are_rejected(self):
        _, tree = self.fixture()
        for mutate in (lambda value: value.update(truncated=True),
                       lambda value: value.update(tree=[row for row in value["tree"] if row["path"] != "LICENSE"]),
                       lambda value: value["tree"][0].update(mode="120000")):
            altered = copy.deepcopy(tree)
            mutate(altered)
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(ValueError):
                    self.import_fixture(Path(temporary) / "corpus", tree=altered)
        with self.assertRaisesRegex(ValueError, "count"):
            IMPORTER.select_files(tree, expected_cases=2)

    def test_unexpected_asset_requires_explicit_review(self):
        contents, tree = self.fixture()
        name = IMPORTER.DATASET + "/example-rbac-case/exfiltrate.env"
        contents[name] = b"do not import\n"
        tree["tree"].append({"path": name, "type": "blob", "mode": "100644", "size": len(contents[name]),
                             "sha": IMPORTER.git_blob_sha(contents[name])})
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "explicit review"):
                self.import_fixture(Path(temporary) / "corpus", contents=contents, tree=tree)

    def test_expanded_file_limit_is_enforced(self):
        contents, tree = self.fixture()
        selected = IMPORTER.select_files(tree, expected_cases=1)[1]
        oversized = tarfile.TarInfo("infra-bench-" + IMPORTER.COMMIT + "/oversized")
        oversized.size = IMPORTER.MAX_FILE_BYTES + 1
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            archive.addfile(oversized, io.BytesIO(b"x" * oversized.size))
        with self.assertRaisesRegex(ValueError, "size limit"):
            IMPORTER.read_verified_archive(stream.getvalue(), selected)


if __name__ == "__main__":
    unittest.main()
