import unittest

from kube_repair.engine import _task
from kube_repair.policy import harden, repair_storage, validate_candidate
from kube_repair.providers import ScriptedProvider
from kube_repair.scenarios import get_scenario


class LinuxIdentityIntegrationTests(unittest.TestCase):
    def test_allowed_linux_identity_is_preserved_in_hardening(self):
        scenario = get_scenario("cache-path", host_identity=(1014, 1015))
        candidate = repair_storage(harden(scenario.base, 1014, 1015), scenario.contract)
        self.assertEqual(validate_candidate(scenario.base, candidate, scenario.contract), [])
        task = _task(scenario)
        self.assertEqual(task["allowed_uid"], 1014)
        self.assertEqual(task["allowed_primary_gid"], 1015)

    def test_linux_does_not_claim_unsupported_volume_or_root_cases(self):
        for name in ("volume-permissions", "authority-limit"):
            with self.assertRaisesRegex(ValueError, "supports"):
                get_scenario(name, host_identity=(1014, 1015))
        with self.assertRaisesRegex(ValueError, "non-root"):
            get_scenario("cache-path", host_identity=(0, 0))

    def test_already_secure_uses_actual_authorized_identity(self):
        scenario = get_scenario("already-secure", host_identity=(1014, 1015))
        self.assertEqual(scenario.base["spec"]["template"]["spec"]["containers"][0]["securityContext"]["runAsUser"], 1014)
        self.assertEqual(scenario.base["spec"]["template"]["spec"]["securityContext"]["fsGroup"], 1015)

    def test_other_identity_proposal_is_rejected(self):
        scenario = get_scenario("cache-path", host_identity=(1014, 1015))
        unauthorized = harden(scenario.base)
        self.assertTrue(validate_candidate(scenario.base, unauthorized, scenario.contract))


if __name__ == "__main__":
    unittest.main()
