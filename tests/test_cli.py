import unittest
from unittest.mock import patch

from kube_repair import cli
from kube_repair.providers import ScriptedProvider


class ProviderArgumentTests(unittest.TestCase):
    def test_verified_repair_completion_is_opt_in_and_reaches_engine(self):
        scenario, provider, output = object(), object(), object()
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                argv = ["run"] + (["--stop-on-verified-repair"] if enabled else [])
                with patch.object(cli, "_scenario", return_value=scenario), \
                        patch.object(cli, "_provider", return_value=provider), \
                        patch.object(cli, "_output", return_value=output), \
                        patch.object(cli, "_print_run"), \
                        patch.object(cli, "run_task", return_value=({"accepted": True}, {})) as run_task:
                    self.assertEqual(cli.main(argv), 0)
                    run_task.assert_called_once_with(scenario, provider, output, "simulated", 12, 3,
                                                     progress_output=None, stop_on_verified_repair=enabled)

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
