import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts" / "llm_kubernetes_demo.py"
spec = importlib.util.spec_from_file_location("llm_launcher_tests", path)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class ModelPinTests(unittest.TestCase):
    def test_digest_normalization_preserves_identity(self):
        digest = launcher.MODEL_DIGEST
        for raw in (digest, digest.removeprefix("sha256:")):
            self.assertEqual(launcher.model_entry({"models": [{"name": launcher.MODEL, "digest": raw}]})["digest"], raw)

    def test_changed_model_identity_is_rejected(self):
        with self.assertRaises(RuntimeError):
            launcher.model_entry({"models": [{"name": launcher.MODEL, "digest": "sha256:" + "0" * 64}]})
        with self.assertRaises(RuntimeError):
            launcher.model_entry({"models": []})

    def test_missing_or_invalid_digest_never_confirms_model(self):
        for value in (None, "latest", "a" * 63, "g" * 64):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    launcher.canonical_digest(value)


if __name__ == "__main__":
    unittest.main()
