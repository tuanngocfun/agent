"""Independent behavior/control checks, plus Docker protocol tests without a daemon."""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from kube_repair.policy import harden, repair_storage
from kube_repair.scenarios import get_scenario
from kube_repair import verification as verifier


IMAGE = "sha256:" + "a" * 64


class VerificationTests(unittest.TestCase):
    def test_root_baseline_behaves_but_is_not_secure(self):
        scenario = get_scenario("cache-path")
        result = verifier.verify(scenario.base, scenario.contract)
        self.assertTrue(result["behavior_pass"])
        self.assertFalse(result["static_pass"])
        self.assertFalse(result["negative_pass"])
        self.assertFalse(result["passed"])
        self.assertFalse(result["runtime_verified"])

    def test_hardening_breaks_required_cache_then_mount_restores_it(self):
        scenario = get_scenario("cache-path")
        hardened = harden(scenario.base)
        before = copy.deepcopy(hardened)
        failed = verifier.verify(hardened, scenario.contract)
        self.assertTrue(failed["static_pass"])
        self.assertFalse(failed["behavior_pass"])
        self.assertTrue(any("Read-only" in line for line in failed["feedback"]))
        repaired = verifier.verify(repair_storage(hardened, scenario.contract), scenario.contract)
        self.assertTrue(repaired["passed"])
        self.assertEqual(hardened, before)
        self.assertFalse(repaired["runtime_verified"])

    def test_volume_requires_matching_supplementary_or_primary_group(self):
        scenario = get_scenario("volume-permissions")
        hardened = harden(scenario.base)
        failed = verifier.verify(hardened, scenario.contract)
        self.assertTrue(any("Permission denied" in line for line in failed["feedback"]))
        self.assertFalse(failed["behavior_pass"])
        fs_group_fix = repair_storage(hardened, scenario.contract)
        self.assertTrue(verifier.verify(fs_group_fix, scenario.contract)["passed"])
        primary_group_fix = copy.deepcopy(hardened)
        primary_group_fix["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsGroup"] = 2000
        self.assertTrue(verifier.verify(primary_group_fix, scenario.contract)["passed"])

    def test_authority_limit_cannot_be_fixed_by_storage(self):
        scenario = get_scenario("authority-limit")
        candidate = repair_storage(harden(scenario.base), scenario.contract)
        result = verifier.verify(candidate, scenario.contract)
        self.assertFalse(result["passed"])
        self.assertTrue(any("requires root" in detail for detail in result["feedback"]))

    def test_malformed_manifest_fails_with_serializable_result(self):
        result = verifier.verify({"spec": None}, {})
        self.assertFalse(result["passed"])
        self.assertIsInstance(result["infrastructure_error"], str)
        json.dumps(result)

    def test_unknown_backend_does_not_default_to_simulation(self):
        scenario = get_scenario("already-secure")
        result = verifier.verify(scenario.base, scenario.contract, "other")
        self.assertFalse(result["passed"])
        self.assertFalse(result["runtime_verified"])


class DockerProtocolTests(unittest.TestCase):
    """Mocks verify fixed argv/failure handling; these are not Docker runtime results."""

    def setUp(self):
        self.scenario = get_scenario("already-secure", image=IMAGE)

    def _evidence(self):
        return json.dumps({name: [True, "Mocked trusted probe evidence"] for name in verifier._RUNTIME_CHECKS})

    def _run(self, argv, timeout=8):
        if argv[1] == "run":
            return 0, "mock-container-id"
        if argv[1] == "inspect":
            return 0, "true\n"
        if argv[1] == "exec":
            return 0, self._evidence()
        if argv[1] == "rm":
            return 0, "removed"
        raise AssertionError(f"Unexpected mocked argv: {argv!r}")

    def test_fixed_runner_uses_local_image_no_network_or_host_mounts(self):
        pod, container = verifier._container(self.scenario.base)
        argv = verifier._docker_args("/mock/docker", "test-container", pod, container, self.scenario.contract)
        self.assertIn("--pull=never", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertNotIn("--volume", argv)
        self.assertNotIn("--mount", argv)
        self.assertNotIn("--publish", argv)
        self.assertNotIn("--privileged", argv)
        self.assertIn("--read-only", argv)
        self.assertEqual(argv[-2:], [IMAGE, "/app/app.py"])

    def test_group_mapping_preserves_fixture_gid_and_adds_supplementary_group(self):
        scenario = get_scenario("volume-permissions", image=IMAGE)
        manifest = repair_storage(harden(scenario.base), scenario.contract)
        pod, container = verifier._container(manifest)
        argv = verifier._docker_args("/mock/docker", "test-container", pod, container, scenario.contract)
        self.assertEqual(argv[argv.index("--group-add") + 1], "2000")
        tmpfs = argv[argv.index("--tmpfs") + 1]
        self.assertIn("mode=0770", tmpfs)
        self.assertIn("gid=2000", tmpfs)

    def test_manifest_tag_rejected_without_implicit_resolution(self):
        scenario = get_scenario("already-secure")
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run") as runner:
            result = verifier.verify(scenario.base, scenario.contract, "docker")
        runner.assert_not_called()
        self.assertFalse(result["passed"])
        self.assertIn("pinned local sha256", result["infrastructure_error"])

    def test_missing_docker_never_passes_simulated_checks(self):
        with patch.object(verifier.shutil, "which", return_value=None):
            result = verifier.verify(self.scenario.base, self.scenario.contract, "docker")
        self.assertFalse(result["passed"])
        self.assertFalse(result["runtime_verified"])
        self.assertIn("Docker CLI is unavailable", result["infrastructure_error"])
        self.assertNotIn("application-cache", {check["name"] for check in result["checks"]})

    def test_successful_mock_protocol_cleans_up_and_labels_approximation(self):
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", side_effect=self._run) as runner:
            result = verifier.verify(self.scenario.base, self.scenario.contract, "docker")
        self.assertTrue(result["passed"])
        self.assertTrue(result["runtime_verified"])
        self.assertIsNone(result["infrastructure_error"])
        self.assertEqual(runner.call_args_list[-1].args[0][1:3], ["rm", "--force"])
        self.assertTrue(any("Kubernetes fsGroup behavior is not verified" in check["detail"] for check in result["checks"]))

    def test_cleanup_failure_invalidates_successful_mock_probes(self):
        def cleanup_failure(argv, timeout=8):
            if argv[1] == "rm":
                return 1, "daemon unavailable"
            return self._run(argv, timeout)
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", side_effect=cleanup_failure):
            result = verifier.verify(self.scenario.base, self.scenario.contract, "docker")
        self.assertFalse(result["passed"])
        self.assertIn("cleanup failed", result["infrastructure_error"])

    def test_start_exception_still_attempts_cleanup_and_never_falls_back(self):
        def failed_start(argv, timeout=8):
            if argv[1] == "run":
                raise verifier.VerificationInfrastructureError("timeout")
            if argv[1] == "rm":
                return 0, "removed"
            raise AssertionError("No probes should be attempted")
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", side_effect=failed_start) as runner:
            result = verifier.verify(self.scenario.base, self.scenario.contract, "docker")
        self.assertFalse(result["passed"])
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(runner.call_args_list[-1].args[0][1:3], ["rm", "--force"])

    def test_local_image_resolution_rejects_absent_or_bad_identity(self):
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", return_value=(0, IMAGE + "\n")):
            self.assertEqual(verifier.resolve_local_image("repair-cache-app:lab"), IMAGE)
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", return_value=(1, "not found")):
            with self.assertRaises(verifier.VerificationInfrastructureError):
                verifier.resolve_local_image("repair-cache-app:lab")
        with self.assertRaises(verifier.VerificationInfrastructureError):
            verifier.resolve_local_image("--privileged")

    def test_command_output_is_bounded_and_slow_command_is_terminated(self):
        with self.assertRaisesRegex(verifier.VerificationInfrastructureError, "output limit"):
            verifier._run([sys.executable, "-c", "print('x' * 70000)"], timeout=2)
        with self.assertRaisesRegex(verifier.VerificationInfrastructureError, "time limit"):
            verifier._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)

    def test_malformed_probe_evidence_fails_and_container_is_removed(self):
        def invalid_evidence(argv, timeout=8):
            if argv[1] == "exec":
                return 0, "not valid JSON"
            return self._run(argv, timeout)
        with patch.object(verifier, "_docker_path", return_value="/mock/docker"), patch.object(verifier, "_run", side_effect=invalid_evidence) as runner:
            result = verifier.verify(self.scenario.base, self.scenario.contract, "docker")
        self.assertFalse(result["passed"])
        self.assertIn("invalid JSON", result["infrastructure_error"])
        self.assertEqual(runner.call_args_list[-1].args[0][1:3], ["rm", "--force"])


class FixtureBehaviorTests(unittest.TestCase):
    """The handler's actual cache contract, exercised without opening a server port."""

    def test_compute_caches_correct_result_and_readiness_reports_ready(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "cache_app" / "app.py"
        spec = importlib.util.spec_from_file_location("trusted_cache_fixture", fixture)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = object.__new__(module.CacheHandler)
        responses = []
        handler._respond = lambda status, payload: responses.append((status, payload))
        with tempfile.TemporaryDirectory() as cache:
            handler.cache_dir = cache
            handler.path = "/health"
            handler.do_GET()
            self.assertEqual(responses[-1], (200, {"ready": True}))
            handler.path = "/compute?value=independent-probe-v1"
            handler.do_GET()
            self.assertEqual(responses[-1][0], 200)
            self.assertFalse(responses[-1][1]["cached"])
            import hashlib
            expected = hashlib.sha256(b"independent-probe-v1").hexdigest()
            self.assertEqual(responses[-1][1]["result"], expected)
            self.assertEqual((Path(cache) / (expected + ".txt")).read_text(), expected)
            handler.do_GET()
            self.assertTrue(responses[-1][1]["cached"])
            self.assertEqual(responses[-1][1]["result"], expected)


if __name__ == "__main__":
    unittest.main()
