# Preserved reference-pilot history

These three completed runs executed real Kubernetes reference controls and **zero model evaluations**. Every run failed. Original artifacts and flags remain unchanged. A historical internal-consistency audit is diagnostic evidence, not permission to treat an old run as a successful or current benchmark.

| Pilot | Actual Actions run | Source commit | Worker elapsed | Observed job seconds | Rounded runner-minutes | Recorded controls | Original runtime-pass flags | Worker status | Worker cleanup |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| 1 | [38737214434](https://github.com/tuanngocfun/agent/actions/runs/38737214434) | `a37a3b1de4c8` | 1m 56.376s | 133 | 4 | 0/48 | 0 | failed | All final worker flags true |
| 2 | [38738048984](https://github.com/tuanngocfun/agent/actions/runs/38738048984) | `1e669bac8f75` | 12m 15.775s | 748 | 14 | 48/48 | 9 | failed | All final worker flags true |
| 3 | [38777257458](https://github.com/tuanngocfun/agent/actions/runs/38777257458) | `7ffc6af999bb` | 12m 28.829s | 767 | 14 | 48/48 | 16 | failed | All final worker flags true |

Worker elapsed values come directly from each `summary.json`. Job seconds are the sum of observed protocol/validate job durations, not workflow wall-clock time. Rounded minutes are a conservative per-job budget proxy, not a billing invoice. Source CI is outside the three run totals above.

The 96 control files repeat the same 12 tasks across two verifier revisions. They are not 96 independent dataset cases, and runtime-pass flags are not LLM repair results.

## What failed

### Pilot 1 — 38737214434

Plan: `robustness-v2-efe3425422fa4ba1240415b47757cc5a21c71e336e109569eec9c729f99c460d`. Source fingerprint: `696c6b21c1dba55e52400306c6a387d168b9bd58030869269fa4ad9ab3ea6a7e`.

- Namespace deletion was acknowledged, but waiting for deletion timed out after the configured 35-second limit. No scored control completed. Evidence: commands.json failed kubectl delete namespace row; summary.json errors; original worker elapsed_ns 35056929934 on the delete command.

Original worker errors:

- RuntimeError: kubectl failed: error: timed out waiting for the condition on namespaces/robust-v2-904e2ff067994ade

Namespace deletion was requested and acknowledged, but its confirmation timed out before any scored control completed. Final owned-cluster, model, kubeconfig and model-cache cleanup flags were nevertheless true. There are no completed control namespace-cleanup flags to count.

### Pilot 2 — 38738048984

Plan: `robustness-v2-d92efaff5fb225a1f7dbdc3ad428a38f8f75e97163f8aa2bd29433570341ac31`. Source fingerprint: `859e2c79fb2d81b4679ee03f47cbb093f175c8a3d61a7c07a99cd3dcd71e213b`.

- The Kubernetes API omitted volumeMount.readOnly=false. Current-pod matching treated the omission as a mismatch and retained zero eligible process probes, including for the already-secure workload. Evidence: Historical API fixture tests/fixtures/robustness-v2/api-default-omission.json preserves original ready Pod, ReplicaSet and Deployment response text and hashes.
- Controller-level log fallback selected an older crashing pod during rollouts. Raw log stderr reports Found 2 pods and names the older pod; the updated Deployment already reported an available replica. Evidence: controls/readonly-cache-mount--oracle.json, controls/sqlite-wal-mount--oracle.json, controls/library-tempfile-scratch--oracle.json behavior_logs and workloads.
- Three recorded ready checks were true while raw Deployment status still reported two replicas. Later stricter readiness diagnostics flagged these claims; original overall failures and raw flags remain unchanged. Evidence: controls/library-tempfile-scratch--oracle.json, controls/sqlite-wal-mount--oracle.json, controls/root-required-abstain--naive.json.

Original worker errors:

- readonly-cache-mount: reference repair failed
- sqlite-wal-mount: reference repair failed
- config-readonly-output-writable: reference repair failed
- library-tempfile-scratch: reference repair failed
- already-secure-cache: initial state differs from registered expectation
- already-secure-cache: reference repair failed

All 48 recorded control namespaces have `namespace_deleted=true`; final worker cleanup also passed.

### Pilot 3 — 38777257458

Plan: `robustness-v2-ccd201b7d97aba5975f886b8f99779eb9e6123e0de440e0185115138bdcfca6e`. Source fingerprint: `b2cf59777a5862313ce22e3a7dce09e06ddcd8e33ed9156e6ea501eceac40ff5`.

- Two reference checks captured empty protected application log output with exit_code=0: the sidecar marker in restricted-init-sidecar and the cache marker in already-secure-cache. Their behavior checks failed, so process probes were intentionally skipped and probe coverage also failed. Evidence: controls/restricted-init-sidecar--oracle.json and controls/already-secure-cache--oracle.json behavior_logs and failed checks. These observations motivated bounded marker polling; they do not prove that either application subsequently passed.

Original worker errors:

- restricted-init-sidecar: reference repair failed
- already-secure-cache: reference repair failed

All 48 recorded control namespaces have `namespace_deleted=true`; final worker cleanup also passed.

An independent historical-source audit found **48/48 internally consistent control observations**: 16 original runtime-pass flags and 32 ordinary task failures. This does **not** mean 48 passing references. Oracle passes were 9/12: nine repair cases passed, the already-secure case and one repair case failed unexpectedly, and the infeasible abstention case failed as expected. The failed worker conclusion is preserved.

## Inspectable provenance

[pilot-history.json](pilot-history.json) contains exact original summaries, plan/source identities, job durations, control flags, per-file SHA256 hashes and diagnostic caveats. Raw artifacts remain in the `reference-<run-id>` directories. No original result was rewritten.
