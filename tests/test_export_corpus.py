"""Model-input export boundary tests; these synthetic fixtures are not results."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import tomllib
    import yaml
except ImportError as exc:
    raise unittest.SkipTest("Corpus export tests require Python 3.11+ and the separate PyYAML dependency") from exc

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("corpus_input_exporter", ROOT / "scripts/export_corpus_input.py")
EXPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPORTER)


class CorpusExportTests(unittest.TestCase):
    def write(self, root, path, data):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())

    def make_fixture(self, corpus_root, source):
        root = corpus_root / source
        root.mkdir(parents=True)
        candidate = "unit-candidate"
        if source == "kalm":
            relative = f"agent-inputs/{candidate}.json"
            data = b'{"resources":[{"kind":"Pod","metadata":{"name":"workload"}}]}\n'
            row = {"candidate_id": candidate, "agent_input_sha256": EXPORTER.digest(data), "oracle_annotations": ["ORACLE_SENTINEL"]}
            self.write(root, "records.jsonl", json.dumps(row).encode() + b"\n")
            self.write(root, "provenance.json", {"repository": EXPORTER.audit.kalm.REPOSITORY, "commit": EXPORTER.audit.kalm.COMMIT})
            self.write(root, relative, data)
            self.write(root, "raw/manifests/source.yaml", b"ORACLE_RAW_SENTINEL")
            expected = {"resources.json": data}
        elif source == "itbench":
            base = f"agent-input/{candidate}/"
            expected = {"problem.md": b"Investigate a synthetic unit workload.\n", "resources.json": b"[]\n",
                        "static-resources/pods/input.yaml": b"kind: Pod\napiVersion: v1\n"}
            rows = []
            for relative, data in expected.items():
                path = base + relative
                self.write(root, path, data)
                rows.append({"path": path, "bytes": len(data), "sha256": EXPORTER.digest(data)})
            self.write(root, "manifest.json", {"repository": EXPORTER.audit.itbench.REPOSITORY,
                       "revision": EXPORTER.audit.itbench.REVISION, "files": rows})
            self.write(root, "tasks.json", [{"task_id": candidate, "agent_input_paths": [row["path"] for row in rows],
                       "protected_reference_paths": ["source/ground-truth/policy.rego"]}])
            self.write(root, "source/ground-truth/policy.rego", b"ORACLE_REGO_SENTINEL")
            self.write(root, "source/static-resources-compliant/pod.yaml", b"ORACLE_COMPLIANT_SENTINEL")
        else:
            relative = f"cases/{candidate}/agent-inputs/instruction.md"
            data = b"Investigate a synthetic unit runtime.\n"
            protected = f"cases/{candidate}/evaluation-assets/solution/solve.sh"
            self.write(root, relative, data)
            self.write(root, protected, b"ORACLE_SOLUTION_SENTINEL")
            self.write(root, f"cases/{candidate}/evaluation-assets/tests/test.sh", b"ORACLE_TEST_SENTINEL")
            self.write(root, "manifest.json", {"repository": EXPORTER.audit.infra.REPOSITORY,
                "commit": EXPORTER.audit.infra.COMMIT,
                "cases": [{"case_id": candidate, "agent_input_files": [relative], "protected_files": [protected]}],
                "files": [{"path": relative, "role": "untrusted_agent_instruction", "sha256": EXPORTER.digest(data), "bytes": len(data)}]})
            self.write(root, "source-tree.json", {"unit_fixture": True})
            expected = {"instruction.md": data}
        return candidate, expected

    def call_export(self, root, source, candidate, output):
        # Boundary unit tests stub only the costly whole-source audit. The export
        # allowlist, selection, byte/hash, path, and output checks remain real.
        with patch.object(EXPORTER, "verify_source", return_value={"status": "unit-audit-stub"}) as verifier:
            receipt = EXPORTER.export_candidate(root, source, candidate, output)
        verifier.assert_called_once_with(source, root / source)
        return receipt

    def test_all_sources_export_only_intended_inputs_with_operator_receipt_separate(self):
        for source in EXPORTER.SOURCES:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                candidate, expected = self.make_fixture(base / "corpus", source)
                output = base / "export"
                receipt = self.call_export(base / "corpus", source, candidate, output)
                actual = {path.relative_to(output / "agent").as_posix(): path.read_bytes()
                          for path in (output / "agent").rglob("*") if path.is_file()}
                self.assertEqual(actual, expected)
                self.assertNotIn(b"ORACLE", b"\n".join(actual.values()))
                self.assertFalse((output / "agent/receipt.json").exists())
                self.assertFalse(receipt["runtime_validated"])
                self.assertFalse(receipt["model_evaluated"])
                self.assertEqual(receipt["new_runtime_results"], 0)
                self.assertEqual(receipt["status"], "static_input_export_only")
                self.assertEqual(receipt["intended_model_mount"], "agent/")
                for row in receipt["files"]:
                    self.assertEqual(EXPORTER.digest(actual[row["agent_path"]]), row["sha256"])
                    self.assertEqual((output / "agent" / row["agent_path"]).stat().st_mode & 0o111, 0)

    def test_failed_source_audit_writes_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            candidate, _ = self.make_fixture(base / "corpus", "kalm")
            with patch.object(EXPORTER, "verify_source", side_effect=ValueError("source hash changed")):
                with self.assertRaisesRegex(ValueError, "source hash changed"):
                    EXPORTER.export_candidate(base / "corpus", "kalm", candidate, base / "export")
            self.assertFalse((base / "export").exists())

    def test_changed_source_pin_and_input_hash_are_rejected(self):
        for field in ("commit", "input"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                candidate, _ = self.make_fixture(base / "corpus", "kalm")
                root = base / "corpus/kalm"
                if field == "commit":
                    pin = json.loads((root / "provenance.json").read_text())
                    pin["commit"] = "f" * 40
                    self.write(root, "provenance.json", pin)
                else:
                    self.write(root, f"agent-inputs/{candidate}.json", b"changed source bytes")
                with self.assertRaisesRegex(ValueError, "pin changed|source hash"):
                    self.call_export(base / "corpus", "kalm", candidate, base / "export")
                self.assertFalse((base / "export").exists())

    def test_unknown_ambiguous_and_unsafe_candidate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            candidate, _ = self.make_fixture(base / "corpus", "kalm")
            for value in ("unknown-id", "../escape", "/absolute"):
                with self.subTest(candidate=value), self.assertRaises(ValueError):
                    self.call_export(base / "corpus", "kalm", value, base / "export")
            path = base / "corpus/kalm/records.jsonl"
            path.write_bytes(path.read_bytes() * 2)
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                self.call_export(base / "corpus", "kalm", candidate, base / "export")

    def test_unknown_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Unknown corpus"):
                EXPORTER.export_candidate(Path(temporary), "../oracle", "x", Path(temporary) / "out")

    def test_itbench_cannot_promote_oracle_or_cross_candidate_paths(self):
        for injected in ("source/ground-truth/policy.rego", "agent-input/other/resources.json",
                         "agent-input/unit-candidate/static-resources/../../source.yaml",
                         "agent-input/unit-candidate/solution.sh"):
            with self.subTest(path=injected), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                candidate, _ = self.make_fixture(base / "corpus", "itbench")
                path = base / "corpus/itbench/tasks.json"
                tasks = json.loads(path.read_text())
                tasks[0]["agent_input_paths"].append(injected)
                self.write(path.parent, path.name, tasks)
                with self.assertRaises(ValueError):
                    self.call_export(base / "corpus", "itbench", candidate, base / "export")
                self.assertFalse((base / "export").exists())

    def test_infra_cannot_promote_solutions_or_wrong_file_role(self):
        for change in ("path", "role"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                candidate, _ = self.make_fixture(base / "corpus", "infra-bench")
                root = base / "corpus/infra-bench"
                data = json.loads((root / "manifest.json").read_text())
                if change == "path":
                    data["cases"][0]["agent_input_files"] = data["cases"][0]["protected_files"]
                else:
                    data["files"][0]["role"] = "protected_evaluation_asset"
                self.write(root, "manifest.json", data)
                with self.assertRaises(ValueError):
                    self.call_export(base / "corpus", "infra-bench", candidate, base / "export")

    def test_output_is_fresh_and_outside_corpus_even_with_dot_segments(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            candidate, _ = self.make_fixture(base / "corpus", "kalm")
            (base / "existing").mkdir()
            self.write(base, "existing/keep", b"preserve")
            for output in (base / "existing", base / "corpus/export", base / "other/../corpus/export"):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    self.call_export(base / "corpus", "kalm", candidate, output)
            self.assertEqual((base / "existing/keep").read_bytes(), b"preserve")

    def test_source_file_and_output_ancestor_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            candidate, _ = self.make_fixture(base / "corpus", "kalm")
            path = base / "corpus/kalm/agent-inputs" / (candidate + ".json")
            original = path.read_bytes()
            path.unlink()
            self.write(base, "outside.json", original)
            path.symlink_to(base / "outside.json")
            with self.assertRaisesRegex(ValueError, "Symlink"):
                self.call_export(base / "corpus", "kalm", candidate, base / "export")
            (base / "link").symlink_to(base / "corpus", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "Symlink"):
                self.call_export(base / "corpus", "kalm", candidate, base / "link/export")


if __name__ == "__main__":
    unittest.main()
