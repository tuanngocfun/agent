# Fixed controls

Repeated fixed controls across model jobs are execution replicates, not independent cases. Known-good is author-provided oracle; template and oracle repairs coincide on supported storage cases.

A case is demonstrated correct only when every registered control execution is present and correct.

| Control | Oracle | Observed cases | Complete cases | All executions task-correct cases |
|---|---|---:|---:|---:|
| noop | False | 8/8 | 8/8 | 2/8 |
| naive | False | 8/8 | 8/8 | 4/8 |
| template | False | 8/8 | 8/8 | 6/8 |
| known-good | True | 8/8 | 8/8 | 8/8 |

Per-case behavior/static/security and failure counts are in `controls-summary.json`; raw bound control paths are in `controls.json`.
