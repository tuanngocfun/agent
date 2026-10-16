# Post hoc decoder diagnostic

Primary audited scores are unchanged. This is a two-case engineering diagnostic.

| Case | Decoder | Primary outcome | Verified | Correct | Cell wall seconds | Parsed edit types |
|---|---|---|---|---|---:|---|
| restricted-init-sidecar | decoder-legacy | provider_failure | True | False | 125.943344938 | {} |
| restricted-init-sidecar | decoder-unbounded | provider_failure | True | False | 125.74813690800005 | {} |
| restricted-init-sidecar | decoder-any-json | task_failure | True | False | 118.23800127200002 | {"boolean":2} |
| rbac-list-configmaps | decoder-any-json | provider_failure | True | False | 124.83642195799996 | {} |
| rbac-list-configmaps | decoder-unbounded | task_failure | True | False | 107.2949984810001 | {"object":5} |
| rbac-list-configmaps | decoder-legacy | task_failure | True | False | 87.01498780400004 | {} |

Worker elapsed seconds: 971.261402043.
Input consistency disagreements: 0.

The CSVs contain every observed call's recorded wall, prompt, generation, load and raw total durations, token counts, done reason and errors. `controls.csv` preserves all registered control outcomes. `diagnostic.json` contains source SHA256 hashes and full provenance.

- This is a post hoc engineering diagnostic on two selected cases, not a broader robustness or model ranking study.
- Task outcomes are copied from the independently recomputed summary and are never rescored by these supplemental counts.
- Raw parsed edit types include rejected, truncated or otherwise invalid decisions; consult primary evidence/outcome columns before interpreting them.
- Call elapsed, prompt, generation, load and raw total times have different scopes; none is substituted for another.
- Observed token/timing sums cover returned counters only. No response, unavailable counters and not-started cells are never imputed as zero.
- Fresh namespaces, different observations, hardware variation and prefix caching are not isolated by two reversed execution orders.
- Worker elapsed excludes Actions checkout, tool installation, reporting, upload, queue time and other job overhead.
- No v2 scores, denominators or method rankings are replaced, pooled or altered.
