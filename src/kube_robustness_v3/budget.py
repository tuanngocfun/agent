"""Explicit wall reservations for the separately registered v3 diagnostic.

Caps are execution limits, not measured latencies or a promise that a workload
will succeed. Linux/main-thread phase alarms also bound repeated socket reads.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import signal
import threading
import time

SETUP_SECONDS = 240
START_SECONDS = 20
INITIAL_SECONDS = 12
CALL_SECONDS = 120
INTERMEDIATE_SECONDS = 20
FINAL_SECONDS = 20
NAMESPACE_CLEANUP_SECONDS = 15
PERSIST_SECONDS = 3
GLOBAL_CLEANUP_SECONDS = 60
BOOKKEEPING_SECONDS = 30
CHECKOUT_TOOL_SECONDS = 30
ARTIFACT_SECONDS = 60
DIAGNOSTIC_CASES = 2
DIAGNOSTIC_CONTROLS = 4
DIAGNOSTIC_CELLS = 6
CONTROL_SECONDS = START_SECONDS + FINAL_SECONDS + NAMESPACE_CLEANUP_SECONDS + PERSIST_SECONDS
CELL_SECONDS = START_SECONDS + INITIAL_SECONDS + CALL_SECONDS + FINAL_SECONDS + NAMESPACE_CLEANUP_SECONDS + PERSIST_SECONDS
DIAGNOSTIC_WORK_SECONDS = SETUP_SECONDS + DIAGNOSTIC_CONTROLS * CONTROL_SECONDS + DIAGNOSTIC_CELLS * CELL_SECONDS + GLOBAL_CLEANUP_SECONDS + BOOKKEEPING_SECONDS
DIAGNOSTIC_JOB_SECONDS = CHECKOUT_TOOL_SECONDS + DIAGNOSTIC_WORK_SECONDS + ARTIFACT_SECONDS
_PHASE_DEADLINES = ContextVar("robustness_v3_phase_deadlines", default=())


def current_phase_deadline():
    stack = _PHASE_DEADLINES.get()
    return stack[-1] if stack else None


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be finite and positive")
    return value


def control_reservation():
    return CONTROL_SECONDS


def cell_reservation(max_calls=1, *, feedback=False):
    if type(max_calls) is not int or max_calls not in (1, 2) or type(feedback) is not bool:
        raise ValueError("The registered method must allow one or two calls")
    return CELL_SECONDS + (max_calls - 1) * CALL_SECONDS + (INTERMEDIATE_SECONDS if feedback else 0)


def can_start_cell(execution_deadline, *, now=None, max_calls=1, feedback=False):
    if now is None:
        now = time.monotonic()
    return execution_deadline - now >= cell_reservation(max_calls, feedback=feedback)


@contextmanager
def hard_phase(seconds, name):
    """Yield the earliest enclosing/phase deadline and restore elapsed time.

    An earlier worker alarm keeps its original handler. A later worker alarm
    resumes with its remaining duration; it never receives a fresh full period.
    """
    _positive(seconds, "Phase cap")
    if not isinstance(name, str) or not name:
        raise ValueError("A phase name is required")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("Hard wall phases require the Linux worker main thread")
    began = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    previous_deadline = began + previous_delay if previous_delay > 0 else None
    requested_deadline = began + seconds
    parent_deadlines = [value for value in (previous_deadline, current_phase_deadline()) if value is not None]
    parent_deadline = min(parent_deadlines) if parent_deadlines else None
    parent_first = parent_deadline is not None and parent_deadline <= requested_deadline
    deadline = parent_deadline if parent_first else requested_deadline
    if deadline <= began:
        raise TimeoutError("Phase wall limit before entry: " + name)

    def expire(signum, frame):
        raise TimeoutError("Phase wall limit: " + name)

    token = _PHASE_DEADLINES.set(_PHASE_DEADLINES.get() + (deadline,))
    normal_exit = False
    try:
        signal.signal(signal.SIGALRM, previous_handler if parent_first else expire)
        signal.setitimer(signal.ITIMER_REAL, max(1e-6, deadline - time.monotonic()))
        yield deadline
        normal_exit = True
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        _PHASE_DEADLINES.reset(token)
        ended = time.monotonic()
        if previous_deadline is not None:
            signal.setitimer(signal.ITIMER_REAL, max(1e-6, previous_deadline - ended), previous_interval)
        if normal_exit and ended >= deadline:
            raise TimeoutError("Phase wall limit after suppressed expiry: " + name)
