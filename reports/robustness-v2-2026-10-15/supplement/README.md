# Supplemental campaign diagnostics

Post hoc analysis of real audited artifacts. **Frozen primary scores are unchanged.** Missing and invalid cells remain in every registered trial table.

Primary coverage: `{"base_cases": 12, "conditions": 2, "families": 11, "infrastructure_or_provider_trials": 3, "invalid_evidence_trials": 0, "missing_trials": 7, "observed_trials": 47, "outcomes": {"missing": 7, "provider_failure": 3, "task_failure": 44}, "registered_trials": 54, "task_correct_trials": 0, "verified_trials": 47}`.

Primary summary SHA256: `6a622fa78fd65baf0a8e556775bc129095d58fdc12291d4534666adddfdd67b5`.

## Verified feedback sequences

| Sequence category | Registered trial rows |
|---|---:|
| no_verified_failed_feedback_to_success_sequence | 26 |
| registered_raw_record_missing | 4 |

The changed-candidate category requires independently bound raw evidence, an actual failed Kubernetes intermediate test, a later patch that changes the candidate, and a successful frozen primary outcome. Protocol/policy feedback and success without a candidate change are separate.

## Time and request failures

| Method | Condition | Registered trials | Raw-bound trials | Wall seconds sum / measured trials | Trusted requests | Transport timeouts | Truncations |
|---|---|---:|---:|---|---:|---:|---:|
| feedback | clean | 12 | 8 | 1126.473 / 8 | 16 | 3 | 0 |
| feedback | injection | 6 | 6 | 1076.528 / 6 | 12 | 4 | 0 |
| feedback-filtered | clean | 6 | 6 | 1021.475 / 6 | 12 | 4 | 0 |
| feedback-filtered | injection | 6 | 6 | 961.031 / 6 | 12 | 3 | 1 |
| one-shot | clean | 12 | 10 | 1109.906 / 10 | 10 | 3 | 0 |
| self-review | clean | 12 | 11 | 1594.739 / 11 | 22 | 3 | 0 |

Per-trial measured durations and actual request failures are in `trial-durations.csv` and `model-requests.csv`. Missing values are blank, not zero. Generation totals sum integer raw nanoseconds before division.

## Paired wins and regressions

`paired-outcomes.csv` records every matched base-case pair, including incomplete pairs. A right win and a right regression are both visible; only pairs explicitly marked complete support a fully observed contrast. These descriptive comparisons do not establish population generalization.

## Current consumer controls

`consumer-mount-review.csv` reviews readonly consumer fields already enforced by this exact frozen contract. It does not reuse an older pilot's contract gap or change primary outcomes.

Raw re-audit disagreements with the primary report: **0**. Any disagreement is retained for investigation; the primary result is not overwritten.

## Limits

- This analysis was prepared after preregistration and is supplemental. Frozen primary task-correct scores and missing/invalid rows are copied without alteration.
- A failed feedback test followed by a successful changed candidate is temporal trace evidence, not causal proof of feedback superiority. The matched two-call self-review comparison is the relevant control.
- Success without a candidate change after failed feedback can reflect settling or repeated verification and is reported separately.
- Method-generated protocol/policy error feedback is not an actual Kubernetes test failure; those correction sequences are separate.
- Pairs retain incomplete and invalid cases. Injection conditions are variants of the same case, not additional independent problems.
- Raw request diagnostics lacking a matching independent binding are labelled untrusted and excluded from trusted request-cost aggregates; their primary trial rows remain.
- Consumer readonly checks are already present in this campaign's frozen contract. This review confirms candidate fields and does not add a new primary scoring rule.
