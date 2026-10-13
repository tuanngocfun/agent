import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kube_repair.artifacts import export_bundle, load_bundle
from kube_repair.engine import run_baseline
from kube_repair.scenarios import get_scenario


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        _, self.binding = run_baseline(get_scenario("cache-path"), "known-good", self.bundle)

    def test_local_export_and_replay_rejected(self):
        target = self.root / "export"
        receipt = export_bundle(self.bundle, target, self.binding["review_hash"])
        self.assertEqual(receipt["effect"], "local_export_only")
        self.assertTrue((target / "deployment.json").is_file())
        with self.assertRaisesRegex(ValueError, "replay"):
            export_bundle(self.bundle, self.root / "second-export", self.binding["review_hash"])

    def test_changed_patch_and_old_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash"):
            export_bundle(self.bundle, self.root / "export", "0" * 64)
        (self.bundle / "patch.diff").write_text("tampered")
        with self.assertRaisesRegex(ValueError, "changed"):
            load_bundle(self.bundle)

    def test_changed_base_and_runner_rejected(self):
        current = get_scenario("cache-path").base
        current["metadata"]["name"] = "new-resource"
        base_file = self.root / "current.json"
        base_file.write_text(json.dumps(current))
        with self.assertRaisesRegex(ValueError, "Base manifest"):
            export_bundle(self.bundle, self.root / "export", self.binding["review_hash"], base_file)
        with patch("kube_repair.artifacts.source_fingerprint", return_value="new-version"):
            with self.assertRaisesRegex(ValueError, "source changed"):
                load_bundle(self.bundle)

    def test_failed_candidate_cannot_be_exported(self):
        failed = self.root / "failed"
        _, binding = run_baseline(get_scenario("cache-path"), "naive", failed)
        with self.assertRaisesRegex(ValueError, "accepted"):
            export_bundle(failed, self.root / "export", binding["review_hash"])

    def test_bundle_path_cannot_swap_artifact_for_symlink(self):
        candidate = self.bundle / "candidate.json"
        target = self.root / "linked.json"
        target.write_bytes(candidate.read_bytes())
        candidate.unlink()
        candidate.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "Invalid artifact"):
            load_bundle(self.bundle)


if __name__ == "__main__":
    unittest.main()
