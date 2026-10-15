# Review round 2: confirmed issues and corrections

Reviewed the supplied Sonnet and Gemini discussions against evaluated source `b5fc820` and the actual 96-record artifact. The [complete result](../reports/benchmark-v1-2026-10-14/README.md) preserves failed, interrupted and invalid executions.

| Review item | Assessment and action |
|---|---|
| Float summation mismatch | Confirmed. Four invalid records are caused solely by the generation-duration formula. Exact errata is published; frozen outcomes are unchanged. Prepare integer-nanosecond aggregation and a multi-call regression for a future version. The claimed universal 27.2% probability is unsupported. |
| Feedback token ceiling | Confirmed as restrictive admission control. Actual tokens and conservative UTF-8 reservations are distinct. Six actions is an upper limit. Retain unresolved reservations when usage is unavailable; do not blindly reset all reservations to reported usage. |
| Shared worker deadline | Confirmed. Five second-case executions in 3B feedback were interrupted. They remain infrastructure failures, not model decisions. Future independent per-case budgets require a new plan and bounded compute allocation. |
| Timer rearmed for 10 ms | There is an unnecessary signal-reentry interval after expiry. The outer cleanup block cancels the timer before cleanup commands; all worker summaries report cleanup. This is not evidence of interrupted cleanup. A separate future fix can disarm expired timers. |
| Four vCPUs / twice as fast | Unsupported here. All 48 actual hardware documents report two host logical CPUs and two inference threads. Container quotas cannot create additional CPUs. |
| Teach finish/abstain mappings | This changes the prompt experiment. Do not retrofit it into evaluated v1. Automatically accepting unchanged proposals also changes the primary completion policy. |
| Delete and regenerate `plan-v1.json` | Rejected. It would erase the code/settings binding for an executed campaign. Use a separately registered v2 and retain the v1 source. |
| Re-run failed jobs | Not performed. Retried artifact names can conflict, and successful-only replacement would bias the comparison. Preserve the failed workflow and original artifacts. |
| Raise 48 jobs to 35 minutes | A 1,680-minute matrix ceiling exceeds the existing 1,000-minute campaign authorization. Similarly, 96 jobs at 20 minutes imply 1,920 minutes. A smaller future pilot or a new allocation is needed. |

The first campaign used 557.517 summed GitHub job minutes plus its separate source CI. No v2 Kubernetes/model evaluation has been claimed. Fix preparation and analysis are separate from experimental results.
