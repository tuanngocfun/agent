"""Protect case independence, executable contracts and the inference boundary."""
import ast
import copy
import json
import unittest

from kube_robustness.cases import IMAGE, NAMESPACE, all_cases, model_view


def get_pointer(resource, path):
    value = resource
    for token in path[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def set_pointer(resource, path, value):
    tokens = path[1:].split("/")
    cursor = resource
    for token in tokens[:-1]:
        cursor = cursor[int(token)] if isinstance(cursor, list) else cursor[token]
    key = tokens[-1]
    if isinstance(cursor, list):
        cursor[int(key)] = copy.deepcopy(value)
    else:
        cursor[key] = copy.deepcopy(value)


def inventory(case):
    return {resource["kind"] + "/" + resource["metadata"]["name"]: resource for resource in case["resources"]}


class RobustnessCasesTests(unittest.TestCase):
    def test_case_grain_and_outcomes_are_explicit(self):
        cases = all_cases()
        self.assertEqual(len(cases), 12)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual(sum(case["expected"] == "repair" for case in cases), 10)
        self.assertEqual(sum(case["expected"] == "unchanged" for case in cases), 1)
        self.assertEqual(sum(case["expected"] == "abstain" for case in cases), 1)
        self.assertGreaterEqual(len({case["family"] for case in cases}), 10)

    def test_external_tasks_have_pinned_honest_derivation_metadata(self):
        external = [case for case in all_cases() if case["source"]["kind"] == "adapted-external"]
        self.assertEqual(len(external), 5)
        self.assertEqual(len({case["source"]["task"] for case in external}), 5)
        for case in external:
            self.assertTrue(case["source"]["adapted"])
            self.assertEqual(len(case["source"]["revision"]), 40)
            self.assertIn("not an unmodified", case["source"]["comparison_scope"])

    def test_model_view_excludes_reference_answers_and_checks(self):
        forbidden = {"source", "expected", "oracle_edits", "contract", "family"}
        for case in all_cases():
            view = model_view(case)
            self.assertEqual(set(view), {"id", "instruction", "resources", "allowed_paths", "public_requirements"})
            self.assertFalse(forbidden.intersection(view))
            view["resources"][0]["metadata"]["name"] = "changed"
            self.assertNotEqual(case["resources"][0]["metadata"]["name"], "changed")

    def test_calls_return_independent_mutable_values(self):
        first, second = all_cases(), all_cases()
        first[0]["resources"][0]["spec"]["replicas"] = 999
        first[0]["oracle_edits"][0]["value"] = "corrupt"
        self.assertEqual(second[0]["resources"][0]["spec"]["replicas"], 1)
        self.assertIs(second[0]["oracle_edits"][0]["value"], False)

    def test_every_reference_repair_is_authorized_and_satisfies_static_contract(self):
        for case in all_cases():
            resources = inventory(copy.deepcopy(case))
            for edit in case["oracle_edits"]:
                self.assertIn(edit["path"], case["allowed_paths"][edit["resource"]])
                set_pointer(resources[edit["resource"]], edit["path"], edit["value"])
            for check in case["contract"]["security_checks"]:
                if case["expected"] != "abstain":
                    self.assertEqual(get_pointer(resources[check["resource"]], check["path"]), check["value"], case["id"])

    def test_reference_repairs_are_non_noop_changes(self):
        for case in all_cases():
            if case["expected"] != "repair":
                continue
            resources = inventory(case)
            unsatisfied = []
            # This checks definition consistency.  Only the independent runtime
            # pilot can establish that broken states fail and references pass.
            for edit in case["oracle_edits"]:
                try:
                    current = get_pointer(resources[edit["resource"]], edit["path"])
                except KeyError:
                    current = object()
                unsatisfied.append(current != edit["value"])
            self.assertTrue(any(unsatisfied), case["id"])

    def test_no_agent_edit_can_replace_trusted_commands_images_or_identities(self):
        forbidden = ("/command", "/args", "/image", "/metadata", "/replicas", "/selector", "/serviceAccountName")
        for case in all_cases():
            for resource, paths in case["allowed_paths"].items():
                self.assertIn(resource, inventory(case))
                for path in paths:
                    self.assertTrue(path.startswith("/"))
                    self.assertFalse(any(item in path for item in forbidden), (case["id"], path))
                    self.assertNotIn("..", path)
                    self.assertNotIn("*", path)

    def test_all_resources_use_only_operator_namespace_and_image_placeholders(self):
        for case in all_cases():
            for resource in case["resources"]:
                self.assertEqual(resource["metadata"]["namespace"], NAMESPACE)
                self.assertNotIn(resource["kind"], {"ClusterRole", "ClusterRoleBinding", "Namespace"})
                if resource["kind"] not in {"Deployment", "Job"}:
                    continue
                pod = resource["spec"]["template"]["spec"]
                self.assertFalse(any(pod.get(field) for field in ("hostNetwork", "hostPID", "hostIPC")))
                for container in pod.get("containers", []) + pod.get("initContainers", []):
                    self.assertEqual(container["image"], IMAGE)
                    self.assertEqual(container["imagePullPolicy"], "Never")
                    self.assertEqual(container["command"][:3], ["python", "-u", "-c"])
                    ast.parse(container["command"][3])
                    self.assertFalse(container["securityContext"].get("privileged", False))
                for volume in pod.get("volumes", []):
                    self.assertTrue("emptyDir" in volume or "configMap" in volume)

    def test_api_behavior_uses_real_authentication_and_retries_without_oracle(self):
        cases = {case["id"]: case for case in all_cases()}
        for case_id in ("rbac-list-configmaps", "rbac-worker-named-config", "rbac-tenant-subject"):
            case = cases[case_id]
            job = inventory(case)["Job/config-reader"]
            code = job["spec"]["template"]["spec"]["containers"][0]["command"][3]
            self.assertIn("urllib.request.urlopen", code)
            self.assertIn("/var/run/secrets/kubernetes.io/serviceaccount", code)
            self.assertIn("ssl.create_default_context", code)
            self.assertIn("for attempt in range(900)", code)
            self.assertIn(NAMESPACE, code)
            self.assertTrue(any(not check["allowed"] and check["resource"] == "secrets" for check in case["contract"]["rbac_checks"]))
            self.assertTrue(any(not check["allowed"] and check["resource"] == "pods" for check in case["contract"]["rbac_checks"]))

    def test_multicontainer_contract_checks_both_consumers_and_init_policy(self):
        case = next(case for case in all_cases() if case["id"] == "restricted-init-sidecar")
        consumers = {check["container"] for check in case["contract"]["behavior_checks"]}
        self.assertEqual(consumers, {"app", "log-sidecar"})
        self.assertTrue(any("/initContainers/" in edit["path"] for edit in case["oracle_edits"]))
        self.assertTrue(any("/containers/1/" in edit["path"] for edit in case["oracle_edits"]))

    def test_abstention_is_a_real_immutable_application_conflict(self):
        case = next(case for case in all_cases() if case["expected"] == "abstain")
        self.assertEqual(case["oracle_edits"], [])
        self.assertEqual(case["contract"]["namespace_security"], "baseline")
        pod = inventory(case)["Deployment/filesystem-app"]["spec"]["template"]["spec"]
        self.assertIn("assert os.geteuid()==0", pod["containers"][0]["command"][3])
        self.assertEqual(pod["containers"][0]["securityContext"]["runAsUser"], 0)

    def test_shared_group_case_preserves_both_uids_and_readonly_consumer(self):
        case = next(case for case in all_cases() if case["id"] == "shared-artifact-group")
        pod = inventory(case)["Deployment/shared-artifact"]["spec"]["template"]["spec"]
        self.assertEqual(pod["initContainers"][0]["securityContext"]["runAsUser"], 10001)
        self.assertEqual(pod["containers"][0]["securityContext"]["runAsUser"], 10002)
        self.assertTrue(pod["containers"][0]["volumeMounts"][0]["readOnly"])
        self.assertIn("p.chmod(0o640)", pod["initContainers"][0]["command"][3])
        self.assertIn("/spec/template/spec/securityContext/fsGroup", case["allowed_paths"]["Deployment/shared-artifact"])
        self.assertNotIn("/spec/template/spec/containers/0/command", case["allowed_paths"]["Deployment/shared-artifact"])

    def test_authority_is_broader_than_the_reference_answer(self):
        for case in all_cases():
            reference = {(edit["resource"], edit["path"]) for edit in case["oracle_edits"]}
            authority = {(resource, path) for resource, paths in case["allowed_paths"].items() for path in paths}
            self.assertLess(reference, authority, case["id"])
            resources = inventory(case)
            for obj in resources.values():
                if obj["kind"] not in {"Deployment", "Job"}:
                    continue
                key = obj["kind"] + "/" + obj["metadata"]["name"]
                for index, _ in enumerate(obj["spec"]["template"]["spec"]["containers"]):
                    self.assertIn("/spec/template/spec/containers/%s/securityContext/runAsNonRoot" % index, case["allowed_paths"][key])

    def test_definitions_roundtrip_as_plain_json(self):
        cases = all_cases()
        self.assertEqual(json.loads(json.dumps(cases, allow_nan=False)), cases)


if __name__ == "__main__":
    unittest.main()
