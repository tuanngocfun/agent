import copy
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from kube_repair.artifacts import digest
from kube_repair.benchmark_cases import BENCHMARK_VERSION, benchmark_case, benchmark_cases_manifest, list_benchmark_cases
from kube_repair.kubernetes_backend import verify_kubernetes
from kube_repair.policy import app_container, harden, pod_spec, repair_storage, validate_candidate
from kube_repair.verification import _PROBE, _SQLITE_PROBE, _probe_for_contract, _static


ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("benchmark_sqlite_fixture", ROOT / "fixtures/sqlite_cache/app.py")
sqlite_fixture = importlib.util.module_from_spec(specification)
specification.loader.exec_module(sqlite_fixture)


class BenchmarkDefinitionTests(unittest.TestCase):
    def test_primary_split_is_explicit_and_excludes_development_demo(self):
        evaluation = list_benchmark_cases()
        self.assertEqual(evaluation, ("file-new-path", "sqlite-new-path", "sqlite-already-secure", "file-root-required",
                                     "file-mounted-hardening", "file-already-secure", "sqlite-mounted-hardening", "sqlite-root-required"))
        development = list_benchmark_cases("development")
        self.assertEqual(len(development), 1)
        self.assertIn("dev-original-cache", development)
        self.assertFalse(set(evaluation) & set(development))
        self.assertEqual(set(list_benchmark_cases("all")), set(evaluation) | set(development))
        with self.assertRaises(ValueError):
            list_benchmark_cases("held-out")

    def test_locked_manifest_hashes_sources_probes_and_copies(self):
        manifest = benchmark_cases_manifest()
        self.assertEqual(manifest["version"], BENCHMARK_VERSION)
        payload = copy.deepcopy(manifest)
        self.assertEqual(payload.pop("suite_sha256"), digest(payload))
        for definition in manifest["definitions"]:
            payload = copy.deepcopy(definition)
            self.assertEqual(payload.pop("definition_sha256"), digest(payload))
        for relative, expected in manifest["fixture_sources"].items():
            self.assertEqual(expected, hashlib.sha256((ROOT / relative).read_bytes()).hexdigest())
        for kind, expected in manifest["probe_sha256"].items():
            self.assertEqual(expected, hashlib.sha256(_probe_for_contract({"fixture_kind": kind}).encode()).hexdigest())
        manifest["definitions"][0]["allowed_groups"].append(999)
        self.assertNotIn(999, benchmark_cases_manifest()["definitions"][0]["allowed_groups"])

    def test_case_authority_and_targets_are_varied_and_protected(self):
        identities, paths, kinds = set(), set(), set()
        for case_id in list_benchmark_cases("all"):
            scenario = benchmark_case(case_id, "fixture:explicit-tag")
            self.assertEqual(scenario.id, case_id)
            self.assertIsNone(scenario.contract["volume_gid"])
            self.assertEqual(app_container(scenario.base)["image"], "fixture:explicit-tag")
            contract = scenario.contract
            identities.add((contract["allowed_uid"], contract["allowed_primary_gid"]))
            paths.add(contract["cache_path"])
            kinds.add(contract["fixture_kind"])
            candidate = repair_storage(harden(scenario.base, contract["allowed_uid"], contract["allowed_primary_gid"]), contract)
            self.assertEqual(validate_candidate(scenario.base, candidate, contract), [])
            app_container(candidate)["image"] = "attacker:replacement"
            self.assertTrue(validate_candidate(scenario.base, candidate, contract))
            candidate = copy.deepcopy(scenario.base)
            app_container(candidate)["env"][0]["value"] = "/tmp/different"
            self.assertTrue(validate_candidate(scenario.base, candidate, contract))
        self.assertGreaterEqual(len(identities), 8)
        self.assertGreaterEqual(len(paths), 8)
        self.assertEqual(kinds, {"file-cache", "sqlite-cache"})

    def test_initial_states_and_fixed_expected_outcomes(self):
        for case_id in list_benchmark_cases("all"):
            with self.subTest(case=case_id):
                scenario = benchmark_case(case_id, "fixture:explicit-tag")
                checks = []
                _static(scenario.base, checks)
                controls_pass = all(check["passed"] for check in checks)
                if scenario.expected == "unchanged":
                    self.assertTrue(controls_pass)
                    self.assertEqual(pod_spec(scenario.base)["volumes"][0]["name"], "cache-data")
                else:
                    self.assertFalse(controls_pass)
                self.assertEqual(scenario.contract["requires_root"], scenario.expected == "abstain")
                if scenario.expected == "abstain":
                    self.assertEqual(app_container(scenario.base)["env"][1]["value"], "1")
        fresh = benchmark_case("file-new-path", "fixture:tag")
        changed = benchmark_case("file-new-path", "fixture:tag")
        changed.contract["allowed_groups"].append(999)
        app_container(changed.base)["image"] = "changed:tag"
        self.assertEqual(benchmark_case("file-new-path", "fixture:tag"), fresh)
        with self.assertRaises(ValueError):
            benchmark_case("missing", "fixture:tag")
        with self.assertRaises(ValueError):
            benchmark_case("file-new-path", "")

    def test_legacy_probe_unchanged_and_unknown_fixture_fails_before_cli(self):
        self.assertEqual(_probe_for_contract({}), _PROBE)
        self.assertEqual(_probe_for_contract({"fixture_kind": "file-cache"}), _PROBE)
        self.assertIn("sqlite3.connect", _probe_for_contract({"fixture_kind": "sqlite-cache"}))
        scenario = benchmark_case("sqlite-new-path", "fixture:tag")
        scenario.contract["fixture_kind"] = "model-supplied-script"
        with patch("kube_repair.kubernetes_backend.command") as cli:
            result = verify_kubernetes(scenario.base, scenario.contract)
        self.assertFalse(result["passed"])
        self.assertIn("Unsupported trusted fixture kind", result["infrastructure_error"])
        cli.assert_not_called()

    def test_kubernetes_chooses_sqlite_probe_without_changing_security_inventory(self):
        # Reuse the existing protocol mock: it asserts commands/ownership, not
        # real Kubernetes execution. Real SQLite behavior is checked below.
        from test_kubernetes_backend import FakeKubectl, IMAGE_ID
        scenario = benchmark_case("sqlite-new-path", "fixture:tag")
        contract = copy.deepcopy(scenario.contract)
        contract["kubernetes"] = {"context": "kind-test-lab", "kubectl": "/trusted/kubectl", "expected_image_id": IMAGE_ID}
        candidate = repair_storage(harden(scenario.base, contract["allowed_uid"], contract["allowed_primary_gid"]), contract)
        fake = FakeKubectl()
        with patch("kube_repair.kubernetes_backend.command", side_effect=fake):
            result = verify_kubernetes(candidate, contract)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["checks"]), 14)
        invocation = next(argv for argv, _ in fake.calls if "exec" in argv)
        self.assertEqual(invocation[invocation.index("-c", invocation.index("--") + 1) + 1], _SQLITE_PROBE)
        self.assertEqual(invocation[-1], contract["cache_path"])
        self.assertEqual(result["runtime"]["fixture_kind"], "sqlite-cache")
        self.assertEqual(result["runtime"]["probe_sha256"], hashlib.sha256(_SQLITE_PROBE.encode()).hexdigest())


class SQLiteBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = sqlite_fixture.initialize_database(self.directory.name)
        sqlite_fixture.CacheHandler.database_path = self.database
        self.server = HTTPServer(("127.0.0.1", 0), sqlite_fixture.CacheHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = "http://127.0.0.1:" + str(self.server.server_address[1])
        self.urlopen = urllib.request.urlopen

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.directory.cleanup()

    def probe(self, tamper_counter=False):
        calls = 0

        def local_open(url, timeout):
            nonlocal calls
            result = self.urlopen(url.replace("http://127.0.0.1:8080", self.endpoint, 1), timeout=timeout)
            if "/compute?" in url:
                calls += 1
                if tamper_counter and calls == 2:
                    # HTTP can still claim cached=True; the independent DB
                    # read must detect that the actual reuse counter regressed.
                    result.read()
                    result.close()
                    with sqlite3.connect(self.database) as database:
                        database.execute("UPDATE results SET hits = 0")
                    # A fresh response object with the same valid JSON claim.
                    import io
                    response = io.BytesIO(json.dumps({"result": hashlib.sha256(b"sqlite-independent-probe-v1").hexdigest(), "cached": True}).encode())
                    response.status = 200
                    return response
            return result

        namespace = {}
        application_probe = _SQLITE_PROBE.split("status = {}\n", 1)[0]
        with patch("sys.argv", ["trusted-probe", self.directory.name]), patch("urllib.request.urlopen", side_effect=local_open):
            exec(compile(application_probe, "trusted-sqlite-application-probe", "exec"), namespace)
        return namespace["results"]["application-cache"]

    def test_real_sqlite_persistence_and_reuse_satisfy_independent_probe(self):
        passed, detail = self.probe()
        self.assertTrue(passed, detail)
        with sqlite3.connect(self.database) as database:
            rows = database.execute("SELECT input, result, hits FROM results").fetchall()
        self.assertEqual(rows, [("sqlite-independent-probe-v1", hashlib.sha256(b"sqlite-independent-probe-v1").hexdigest(), 1)])
        # Re-running the trusted probe must work on the already persisted cache.
        self.assertTrue(self.probe()[0])

    def test_http_cached_claim_cannot_hide_wrong_committed_database_counter(self):
        passed, detail = self.probe(tamper_counter=True)
        self.assertFalse(passed, detail)

    def test_database_corruption_fails_application_probe(self):
        Path(self.database).write_bytes(b"a JSON HTTP claim is not a SQLite database")
        passed, detail = self.probe()
        self.assertFalse(passed)
        self.assertIn("SQLite service or persisted cache behavior failed", detail)


if __name__ == "__main__":
    unittest.main()
