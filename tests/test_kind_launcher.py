import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "kind_demo.py"
spec = importlib.util.spec_from_file_location("kind_demo_for_tests", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
BASE = "python@sha256:" + "b" * 64


class Worker:
    def __init__(self, break_control=False, break_create=False):
        self.calls = []
        self.break_control = break_control
        self.break_create = break_create

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        stdout, code = b"", 0
        if "create" in argv and "cluster" in argv:
            config = Path(argv[argv.index("--kubeconfig") + 1])
            config.write_text("mock private credentials")
            if self.break_create:
                code = 1
        elif "get" in argv and "pods" in argv:
            stdout = json.dumps({"items": [{"metadata": {"uid": "setup-pod-uid"}, "status": {
                "containerStatuses": [{"name": "app", "ready": True,
                                        "imageID": "containerd://sha256:" + "c" * 64}]}}]}).encode()
        elif len(argv) > 3 and argv[1:3] == ["-m", "kube_repair"]:
            agent = argv[3] == "run"
            strategy = "agent" if agent else argv[argv.index("--strategy") + 1]
            output = Path(argv[argv.index("--output") + 1])
            output.mkdir(parents=True)
            accepted = strategy in ("known-good", "agent")
            report = {"accepted": accepted and not (self.break_control and strategy == "known-good"),
                      "runtime_verified": accepted, "status": "repaired" if accepted else "failed",
                      "verification": {"static_pass": strategy != "noop", "behavior_pass": strategy != "naive"}}
            (output / "report.json").write_text(json.dumps(report))
            code = 0 if accepted else 1
        return subprocess.CompletedProcess(argv, code, stdout, b"mock failure" if code else b"")


class KindLauncherTests(unittest.TestCase):
    def invoke(self, output, worker, *extra):
        with patch.object(launcher.shutil, "which", side_effect=lambda name: "/trusted/" + name):
            with patch.object(launcher.subprocess, "run", side_effect=worker):
                with patch("builtins.print"):
                    return launcher.main(["--base-image", BASE, "--output", str(output), *extra])

    def test_ollama_decoding_selection_reaches_worker_cli(self):
        for mode in ("json", "schema", "compact-schema"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                output, worker = Path(temporary) / "run", Worker()
                self.assertEqual(self.invoke(output, worker, "--provider", "ollama", "--model", "lab:fixed",
                                             "--decoding-mode", mode), 0)
                command = next(a for a in worker.calls if len(a) > 3 and a[1:4] == ["-m", "kube_repair", "run"])
                self.assertEqual(command[command.index("--decoding-mode") + 1], mode)
                self.assertEqual(command[command.index("--model") + 1], "lab:fixed")

    def test_scripted_worker_has_no_ollama_decoding_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, worker = Path(temporary) / "run", Worker()
            self.assertEqual(self.invoke(output, worker, "--decoding-mode", "compact-schema"), 0)
            command = next(a for a in worker.calls if len(a) > 3 and a[1:4] == ["-m", "kube_repair", "run"])
            self.assertNotIn("--decoding-mode", command)
            self.assertNotIn("--model", command)

    def test_missing_worker_stops_before_output_or_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "run"
            with patch.object(launcher.shutil, "which", return_value=None):
                with patch.object(launcher.subprocess, "run") as commands:
                    with self.assertRaises(SystemExit) as error:
                        launcher.main(["--base-image", BASE, "--output", str(output)])
            self.assertEqual(error.exception.code, 2)
            self.assertFalse(output.exists())
            commands.assert_not_called()

    def test_success_deletes_only_created_cluster_and_removes_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, worker = Path(temporary) / "run", Worker()
            self.assertEqual(self.invoke(output, worker), 0)
            created = next(a for a in worker.calls if "create" in a and "cluster" in a)
            deleted = next(a for a in worker.calls if "delete" in a and "cluster" in a)
            self.assertEqual(created[created.index("--name") + 1], deleted[deleted.index("--name") + 1])
            self.assertFalse((output / "private-kubeconfig").exists())
            self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "passed")
            for command in worker.calls:
                if command[0].endswith("kubectl"):
                    self.assertIn("--context", command)

    def test_control_failure_invalidates_summary_and_still_cleans_up(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, worker = Path(temporary) / "run", Worker(break_control=True)
            self.assertEqual(self.invoke(output, worker), 1)
            self.assertEqual(json.loads((output / "summary.json").read_text())["status"], "failed")
            self.assertTrue(any("delete" in a and "cluster" in a for a in worker.calls))
            self.assertFalse((output / "private-kubeconfig").exists())

    def test_partial_cluster_creation_still_attempts_own_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, worker = Path(temporary) / "run", Worker(break_create=True)
            self.assertEqual(self.invoke(output, worker), 1)
            self.assertTrue(any("delete" in a and "cluster" in a for a in worker.calls))
            self.assertFalse((output / "private-kubeconfig").exists())


if __name__ == "__main__":
    unittest.main()
