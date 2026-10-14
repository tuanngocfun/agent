# Review: cache-path

Outcome: **repaired**. Provider: `baseline:known-good`. Backend: `kubernetes`. Runtime verified: **True**.

Simulation checks model fixture semantics; they do not execute a workload. Docker checks this fixture in a container; Linux checks a process with Landlock. The Kubernetes backend executes the selected fixture on an explicitly named lab cluster. Verification scope and infrastructure errors are recorded in report.json.

Inspect `patch.diff`, `report.json` and `trace.json`. Run `review --bundle <this-directory>` to validate contents and obtain the hash for an explicit local export. No deployment or PR is performed. A failed/abstained run cannot be exported as a repair.
