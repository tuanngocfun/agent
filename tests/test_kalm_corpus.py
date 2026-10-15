"""Safety, leakage, provenance, and partition checks for the external importer."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import yaml
except ImportError as exc:
    raise unittest.SkipTest("KALM corpus tests require the separately installed PyYAML dependency") from exc

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_kalm_corpus.py"
SPEC = importlib.util.spec_from_file_location("import_kalm_corpus", SCRIPT)
corpus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(corpus)


def manifest(name="root-unsafe", expected="alert", check="POD-033-1"):
    return f"""apiVersion: v1
kind: ServiceAccount
metadata:
  name: {name}-sa
  namespace: external-lab
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {name}
  namespace: external-lab
  labels:
    check: {check}
  annotations:
    expected: {expected}
    description: root filesystem is unsafe
    check_path: .spec.containers[].securityContext
    ccss_score: '8.5'
    standards: benchmark-answer
spec:
  selector:
    matchLabels:
      check: {check}
  template:
    metadata:
      labels:
        check: {check}
      annotations:
        container.apparmor.security.beta.kubernetes.io/app: runtime/default
    spec:
      serviceAccountName: {name}-sa
      containers:
        - name: app
          image: example.invalid/app@sha256:abc
          securityContext:
            readOnlyRootFilesystem: false
""".encode()


class KalmCorpusTests(unittest.TestCase):
    def test_separates_oracles_from_input_and_preserves_exact_references(self):
        record, agent = corpus.make_record("manifests/pod-033-1-root-unsafe.yaml", manifest())
        encoded = json.dumps(agent)
        for answer in ("root-unsafe", "POD-033-1", "benchmark-answer", "ccss_score", "check_path", "description", "expected"):
            self.assertNotIn(answer, encoded)
        self.assertEqual(record["oracle_annotations"][0]["annotations"]["expected"], "alert")
        service_account, deployment = agent["resources"]
        spec = deployment["spec"]
        self.assertEqual(service_account["metadata"]["name"], spec["template"]["spec"]["serviceAccountName"])
        self.assertEqual(spec["selector"]["matchLabels"], spec["template"]["metadata"]["labels"])
        self.assertFalse(spec["template"]["spec"]["containers"][0]["securityContext"]["readOnlyRootFilesystem"])
        self.assertIn("container.apparmor.security.beta.kubernetes.io/app", spec["template"]["metadata"]["annotations"])
        self.assertFalse(record["runtime_validated"])

    def test_structural_duplicates_ignore_descriptive_names_and_answer_annotations(self):
        a, _ = corpus.make_record("manifests/pod-033-1-a.yaml", manifest("root-unsafe", "alert", "POD-033-1"))
        b, _ = corpus.make_record("manifests/pod-033-2-b.yaml", manifest("already-fixed", "pass", "POD-033-2"))
        self.assertNotEqual(a["exact_duplicate_group"], b["exact_duplicate_group"])
        self.assertEqual(a["semantic_duplicate_group"], b["semantic_duplicate_group"])
        changed = manifest().replace(b"readOnlyRootFilesystem: false", b"readOnlyRootFilesystem: true")
        c, _ = corpus.make_record("manifests/pod-033-3-c.yaml", changed)
        self.assertNotEqual(a["semantic_duplicate_group"], c["semantic_duplicate_group"])

    def test_duplicates_and_rule_families_never_cross_partitions(self):
        records = [corpus.make_record("manifests/pod-033-1-a.yaml", manifest())[0],
                   corpus.make_record("manifests/pod-033-2-b.yaml", manifest("other", "pass", "POD-033-2"))[0],
                   corpus.make_record("manifests/pod-017-1-c.yaml", manifest("third", "alert", "POD-017-1"))[0]]
        records[1]["semantic_duplicate_group"] = "distinct-but-same-rule"
        records[2]["semantic_duplicate_group"] = records[1]["semantic_duplicate_group"]
        original = copy.deepcopy(records)
        summary = corpus.assign_partitions(records)
        self.assertEqual(summary["components"], 1)
        self.assertEqual(len({record["partition"] for record in records}), 1)
        self.assertEqual(len({record["split_group"] for record in records}), 1)
        corpus.assign_partitions(original)
        self.assertEqual(records, original)

    def test_rejects_path_escape_and_non_manifest_paths(self):
        for path in ("../escape.yaml", "/manifests/a.yaml", "manifests/../escape.yaml", "manifests/sub/a.yaml",
                     "manifests/evil\\a.yaml", "manifests/%2e%2e.yaml", "LICENSE", "manifests/a.py"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                corpus.safe_manifest_path(path)

    def test_rejects_ambiguous_unsafe_and_non_resource_yaml(self):
        payloads = [b"apiVersion: v1\nkind: Pod\nkind: Deployment\n", b"a: &a [*a]\n",
                    b"!!python/object/apply:os.system ['false']", b"- not-a-resource\n",
                    b"apiVersion: v1\nkind: Pod\nvalue: .nan\n", b"apiVersion: [\n",
                    b"apiVersion: v1\nkind: Pod\nvalue: " + b"[" * 70 + b"0" + b"]" * 70]
        for payload in payloads:
            with self.subTest(payload=payload[:60]), self.assertRaises((ValueError, corpus.yaml.YAMLError)):
                corpus.parse_documents(payload)

    def fake_source(self, raw=None, corrupt_blob=False):
        raw = manifest() if raw is None else raw
        sources = {"manifests/pod-033-1-example.yaml": raw, "LICENSE": b"Apache License, Version 2.0\n"}
        entries = []
        for path, payload in sources.items():
            blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
            entries.append({"path": path, "type": "blob", "size": len(payload), "sha": "0" * 40 if corrupt_blob else blob})
        def fake_fetch(url, *, limit):
            if url.startswith("https://api.github.com/"):
                return json.dumps({"tree": entries, "sha": "f" * 40, "truncated": False}).encode()
            prefix = f"https://raw.githubusercontent.com/{corpus.REPOSITORY}/{corpus.COMMIT}/"
            if not url.startswith(prefix):
                raise AssertionError("Importer requested an unpinned source URL")
            return sources[url[len(prefix):]]
        return sources, fake_fetch

    def fixture_anchor(self, sources):
        return corpus.source_inventory_digest([{"path": path, "git_blob_sha1": hashlib.sha1(
            b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest(), "bytes": len(payload)}
            for path, payload in sources.items()])

    def test_import_preserves_raw_bytes_hashes_and_license(self):
        sources, fake_fetch = self.fake_source()
        with tempfile.TemporaryDirectory() as directory, patch.object(corpus, "EXPECTED_FILES", 1), patch.object(corpus, "fetch", fake_fetch), patch.object(corpus, "SOURCE_INVENTORY_SHA256", self.fixture_anchor(sources)):
            output = Path(directory) / "corpus"
            summary = corpus.import_corpus(output)
            self.assertEqual(summary["manifest_file_count"], 1)
            self.assertEqual(summary["resource_document_count"], 2)
            self.assertEqual(summary["runtime_validated_cases"], 0)
            record = json.loads((output / "records.jsonl").read_text())
            original = sources["manifests/pod-033-1-example.yaml"]
            self.assertEqual((output / "raw/manifests/pod-033-1-example.yaml").read_bytes(), original)
            self.assertEqual((output / "LICENSE").read_bytes(), sources["LICENSE"])
            self.assertEqual(record["source_sha256"], hashlib.sha256(original).hexdigest())
            agent_bytes = (output / "agent-inputs" / (record["candidate_id"] + ".json")).read_bytes()
            self.assertEqual(record["agent_input_sha256"], hashlib.sha256(agent_bytes).hexdigest())
            self.assertFalse((output / "INCOMPLETE").exists())

    def test_existing_or_symlink_output_is_immutable_before_network_access(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(corpus, "fetch", side_effect=AssertionError("network called")):
            output = Path(directory) / "existing"
            output.mkdir()
            marker = output / "keep"
            marker.write_text("original")
            with self.assertRaises(ValueError):
                corpus.import_corpus(output)
            self.assertEqual(marker.read_text(), "original")
            link = Path(directory) / "link"
            link.symlink_to(output, target_is_directory=True)
            with self.assertRaises(ValueError):
                corpus.import_corpus(link)

    def test_corrupt_upstream_or_invalid_yaml_never_creates_output(self):
        for raw, corrupt in ((manifest(), True), (b"apiVersion: v1\nkind: Pod\nkind: Job\n", False)):
            sources, fake_fetch = self.fake_source(raw, corrupt)
            with tempfile.TemporaryDirectory() as directory, patch.object(corpus, "EXPECTED_FILES", 1), patch.object(corpus, "fetch", fake_fetch), patch.object(corpus, "SOURCE_INVENTORY_SHA256", self.fixture_anchor(sources)):
                output = Path(directory) / "corpus"
                with self.assertRaises(ValueError):
                    corpus.import_corpus(output)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
