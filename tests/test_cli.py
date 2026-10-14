import unittest
from unittest.mock import patch

from kube_repair import cli
from kube_repair.providers import ScriptedProvider


class ProviderArgumentTests(unittest.TestCase):
    def test_ollama_decoding_selection_reaches_provider(self):
        for requested in (None, "json", "schema", "compact-schema"):
            with self.subTest(requested=requested):
                argv = ["run", "--provider", "ollama", "--model", "lab:fixed", "--endpoint", "http://127.0.0.1:12345"]
                if requested is not None:
                    argv += ["--decoding-mode", requested]
                args = cli.parser().parse_args(argv)
                with patch.object(cli, "OllamaProvider") as provider:
                    self.assertIs(cli._provider(args), provider.return_value)
                    provider.assert_called_once_with(model="lab:fixed", endpoint="http://127.0.0.1:12345",
                                                     decoding_mode=requested or "json")

    def test_scripted_provider_keeps_its_existing_behavior(self):
        args = cli.parser().parse_args(["run", "--decoding-mode", "compact-schema"])
        with patch.object(cli, "OllamaProvider") as provider:
            self.assertIsInstance(cli._provider(args), ScriptedProvider)
            provider.assert_not_called()

    def test_unknown_decoding_mode_is_rejected_before_provider_creation(self):
        with patch.object(cli, "OllamaProvider") as provider, patch("sys.stderr"):
            with self.assertRaises(SystemExit) as error:
                cli.parser().parse_args(["run", "--provider", "ollama", "--model", "lab:fixed", "--decoding-mode", "guess"])
        self.assertEqual(error.exception.code, 2)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
