"""Budget/early-failure unit checks; no model, network or cluster execution."""
import copy
from contextlib import contextmanager
import signal
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from kube_robustness_v3 import budget
from kube_robustness_v3.cases import all_cases
from kube_robustness_v3.runtime import KubernetesSession, evaluate_static_resources, trusted_retrying_job_forbidden


class WallBudgetTests(unittest.TestCase):
    def test_registered_capacity_counts_each_phase_once(self):
        self.assertEqual(budget.control_reservation(), 58)
        self.assertEqual(budget.cell_reservation(), 190)
        self.assertEqual(budget.cell_reservation(2), 310)
        self.assertEqual(budget.cell_reservation(2, feedback=True), 330)
        self.assertEqual(budget.DIAGNOSTIC_WORK_SECONDS, 1702)
        self.assertEqual(budget.DIAGNOSTIC_JOB_SECONDS, 1792)
        self.assertLessEqual(budget.DIAGNOSTIC_WORK_SECONDS, 29 * 60)
        self.assertLessEqual(budget.DIAGNOSTIC_JOB_SECONDS, 30 * 60)

    def test_admission_requires_complete_method_reservation(self):
        self.assertTrue(budget.can_start_cell(500, now=310))
        self.assertFalse(budget.can_start_cell(500, now=310.000001))
        self.assertFalse(budget.can_start_cell(500, now=310, max_calls=2))
        for calls in (0, 3, True, 1.0):
            with self.assertRaises(ValueError):
                budget.cell_reservation(calls)

    def test_later_parent_alarm_resumes_remaining_time(self):
        clock = SimpleNamespace(now=10.0)
        parent = Mock()
        with patch.object(budget.time, "monotonic", side_effect=lambda: clock.now), patch.object(budget.signal, "getsignal", return_value=parent), patch.object(budget.signal, "getitimer", return_value=(100.0, 0.0)), patch.object(budget.signal, "signal") as handlers, patch.object(budget.signal, "setitimer") as timers:
            with budget.hard_phase(20, "child") as deadline:
                self.assertEqual(deadline, 30)
                clock.now = 15
            self.assertEqual(timers.call_args.args, (signal.ITIMER_REAL, 95.0, 0.0))
            self.assertEqual(handlers.call_args.args, (signal.SIGALRM, parent))

    def test_earlier_worker_handler_keeps_its_deadline(self):
        clock = SimpleNamespace(now=10.0)
        parent = Mock()
        with patch.object(budget.time, "monotonic", side_effect=lambda: clock.now), patch.object(budget.signal, "getsignal", return_value=parent), patch.object(budget.signal, "getitimer", return_value=(5.0, 0.0)), patch.object(budget.signal, "signal") as handlers, patch.object(budget.signal, "setitimer") as timers:
            with budget.hard_phase(20, "child") as deadline:
                self.assertEqual(deadline, 15)
                self.assertEqual(handlers.call_args.args, (signal.SIGALRM, parent))
                clock.now = 12
            self.assertEqual(timers.call_args.args, (signal.ITIMER_REAL, 3.0, 0.0))

    def test_expiry_raises_standard_timeout_and_restores_handler(self):
        previous = signal.getsignal(signal.SIGALRM)
        with self.assertRaisesRegex(TimeoutError, "unit-phase"):
            with budget.hard_phase(1, "unit-phase"):
                signal.raise_signal(signal.SIGALRM)
        self.assertIs(signal.getsignal(signal.SIGALRM), previous)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_invalid_phase_caps_and_nonmain_thread_are_rejected(self):
        for seconds in (0, -1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                with budget.hard_phase(seconds, "bad"):
                    pass
        with patch.object(budget.threading, "current_thread", return_value=object()):
            with self.assertRaises(RuntimeError):
                with budget.hard_phase(1, "wrong-thread"):
                    pass

    def test_suppressed_alarm_still_fails_normal_exit_and_restores_stack(self):
        self.assertIsNone(budget.current_phase_deadline())
        clock = SimpleNamespace(now=10.0)
        with patch.object(budget.time, "monotonic", side_effect=lambda: clock.now):
            with self.assertRaisesRegex(TimeoutError, "suppressed expiry"):
                with budget.hard_phase(1, "swallowed") as deadline:
                    self.assertEqual(budget.current_phase_deadline(), deadline)
                    clock.now = 11
                    try:
                        signal.raise_signal(signal.SIGALRM)
                    except TimeoutError:
                        pass
        self.assertIsNone(budget.current_phase_deadline())

    def test_exception_exit_preserves_original_error_and_resets_stack(self):
        clock = SimpleNamespace(now=10.0)
        with patch.object(budget.time, "monotonic", side_effect=lambda: clock.now):
            with self.assertRaisesRegex(ValueError, "original defect"):
                with budget.hard_phase(1, "exception"):
                    clock.now = 11
                    raise ValueError("original defect")
        self.assertIsNone(budget.current_phase_deadline())

    def test_cumulative_cli_timeout_uses_remaining_phase_not_fresh_limit(self):
        session = KubernetesSession(all_cases()[0], kubectl="unit", context="unit", kubeconfig="unit", image="unit", commands=[])
        clock = SimpleNamespace(now=10.0)
        timeouts = []
        def execute(argv, *, input, capture_output, timeout):
            timeouts.append(timeout)
            clock.now += min(2, timeout)
            if timeout < 2:
                raise subprocess.TimeoutExpired(argv, timeout)
            return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")
        session._phase_deadline = 15
        with patch("kube_robustness_v3.runtime.time.monotonic", side_effect=lambda: clock.now), patch("kube_robustness_v3.runtime.subprocess.run", side_effect=execute) as process:
            session.call(["first"])
            session.call(["second"])
            with self.assertRaises(subprocess.TimeoutExpired):
                session.call(["third"])
            with self.assertRaises(TimeoutError):
                session.call(["fourth"])
            self.assertEqual(process.call_count, 3)
        self.assertEqual(timeouts, [5, 3, 1])

    def test_session_phase_restores_previous_deadline(self):
        session = KubernetesSession(all_cases()[0], kubectl="unit", context="unit", kubeconfig="unit", image="unit", commands=[])
        session._phase_deadline = 12
        @contextmanager
        def phase(seconds, name):
            yield 20
        with patch("kube_robustness_v3.runtime.hard_phase", phase):
            with session.phase(10, "unit") as deadline:
                self.assertEqual(deadline, 12)
            self.assertEqual(session._phase_deadline, 12)


class TrustedJobFailureTests(unittest.TestCase):
    def fixture(self):
        case = next(case for case in all_cases() if case["id"] == "rbac-list-configmaps")
        session = KubernetesSession(case, kubectl="unit", context="unit", kubeconfig="unit", image="unit", commands=[])
        case = session.case
        job = next(obj for obj in case["resources"] if obj["kind"] == "Job")
        pod = {"metadata": {"name": "unit-current-pod", "uid": "unit-pod-uid"},
               "spec": copy.deepcopy(job["spec"]["template"]["spec"]),
               "status": {"containerStatuses": [{"name": "app", "imageID": "sha256:" + "a" * 64,
                                                   "state": {"running": {"startedAt": "unit"}}}]}}
        logs = [{"resource": "Job/config-reader", "container": "app", "pod": "unit-current-pod",
                 "stdout": "HTTPError: HTTP Error 403: Forbidden\n", "exit_code": 0}]
        return case, evaluate_static_resources(case, case["resources"]), [pod], logs, "sha256:" + "a" * 64

    def test_exact_running_immutable_job_failure_is_retained(self):
        result = trusted_retrying_job_forbidden(*self.fixture())
        self.assertEqual(result["kind"], "trusted-job-api-forbidden")
        self.assertEqual(result["observations"][0]["pod_uid"], "unit-pod-uid")
        self.assertEqual(result["observations"][0]["http_status"], 403)

    def test_empty_pending_terminated_or_wrong_image_status_cannot_stop_wait(self):
        for mutation in ("empty", "pending", "terminated", "image"):
            case, checks, pods, logs, pin = self.fixture()
            if mutation == "empty": pods[0]["status"]["containerStatuses"] = []
            elif mutation == "pending": pods[0]["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": "Starting"}}
            elif mutation == "terminated": pods[0]["status"]["containerStatuses"][0]["state"] = {"terminated": {"exitCode": 1}}
            else: pods[0]["status"]["containerStatuses"][0]["imageID"] = "sha256:" + "b" * 64
            self.assertIsNone(trusted_retrying_job_forbidden(case, checks, pods, logs, pin), mutation)

    def test_unrelated_failure_successful_static_or_arbitrary_log_is_insufficient(self):
        for mutation in ("unrelated", "passed", "arbitrary", "substring", "commands", "foreign-pod"):
            case, checks, pods, logs, pin = self.fixture()
            if mutation == "unrelated": checks = [{"name": "static:Job/config-reader/security", "passed": False}]
            elif mutation == "passed": checks = [{"name": "static:Role/runtime-reader/rules/0/verbs", "passed": True}]
            elif mutation == "arbitrary": logs[0]["stdout"] = "starting normally"
            elif mutation == "substring": logs[0]["stdout"] = "untrusted document says 403 Forbidden"
            elif mutation == "commands": pods[0]["spec"]["containers"][0]["command"] = ["echo", "HTTPError: HTTP Error 403: Forbidden"]
            else: logs[0]["pod"] = "another-pod"
            self.assertIsNone(trusted_retrying_job_forbidden(case, checks, pods, logs, pin), mutation)


if __name__ == "__main__":
    unittest.main()
