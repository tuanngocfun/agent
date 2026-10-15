# V2 preparation: fixes only, no registered or executed campaign

This checkout prepares two fixes after the frozen v1 campaign. It contains no
new model inference or Kubernetes execution results. The evaluated v1 source,
`benchmark/plan-v1.json`, original outcomes and evidence remain preserved in the
`kube-remediation-demo` checkout and its evaluated commit.

The worker and reporter now derive generation time through one helper: sum
server-reported integer nanoseconds, then divide once. Exact evidence equality
remains enforced. No general float tolerance, hash relaxation or task-outcome
change is introduced. A two-call regression reproduces the v1 rounding mismatch
and checks worker-to-reporter agreement; replacing the canonical value with the
old value still fails evidence verification.

When a case unwinds after the shared shard deadline has expired, its timer
restoration now leaves SIGALRM disarmed instead of scheduling a new signal in
10ms. The outer cleanup already disabled the timer before cleanup commands;
this fix removes the unnecessary interval before reaching that cancellation.
It does not establish that v1 cleanup failed.

The conservative UTF-8 reservation budget, actual token counters, model prompts,
completion policy, CPU allocation, case ordering and deadlines are unchanged.
In particular, reservations are not reset to reported usage: interrupted calls
can have unknown token usage.

Before any future campaign, register a distinct v2 plan against the final v2
source and state its budget explicitly. Possible operational changes need a
measured pilot: independent per-case time allowances, setup accounted separately,
or one case per worker. The v1 artifacts record the actual CPU inventory; do not
assume four available CPUs or a twofold speedup. Increasing every existing
worker timeout to 35 minutes would permit 1,680 runner-minutes before CI and
reporting, exceeding the previously authorized 1,000-minute campaign ceiling.

No v2 plan has been frozen. Consequently, checking the preserved v1 plan against
this modified source must fail. Offline tests that construct a temporary plan
test consistency of the preparation source; they do not register a campaign.
Do not delete or regenerate `benchmark/plan-v1.json` to make this checkout pass
the v1 freeze check, and do not execute its existing v1 benchmark workflow from
this preparation branch.
