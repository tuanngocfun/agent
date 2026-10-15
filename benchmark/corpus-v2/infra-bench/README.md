# Imported infra-bench definitions

Source: [kubeply/infra-bench](https://github.com/kubeply/infra-bench/tree/9c87b33151cfa0c37aac09056e3644cc472026b7), pinned commit `9c87b33151cfa0c37aac09056e3644cc472026b7`.

71 external Kubernetes task definitions, licensed Apache-2.0; exact license is in `upstream/LICENSE`. These are unexecuted imported definitions, **not newly measured benchmark results**. No case is yet validated for this project's runtime or agent.

Only each case's `agent-inputs/instruction.md` is an agent input. Task metadata, setup scripts, manifests, verifiers and reference solutions are separate protected assets. Do not expose this full directory to an evaluated agent. Import does not sandbox or approve executing any upstream script.

`manifest.json` records every imported file's original path, SHA-256, Git blob SHA-1, and role. `source-tree.json` preserves the pinned GitHub tree response. Keyword matches are discovery aids, not security annotations. The documentation task template is excluded.

Before evaluation, vet privileges and dependencies, pin images, build isolated adapters, verify initial failures and oracle repairs, protect tests, and freeze a family-aware split. See `required_before_evaluation` in the manifest.
