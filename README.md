# Pi on Physical Engineering

This repository holds the Kaggle writeup and the organizers’ Pi harness on Claude Opus 5.5. The archived run averaged **0.4912 across 29 development tasks**. Four tasks scored zero, including two that exported no deliverables. [Archived manifest](https://github.com/physical-engineerings-last-exam/submission-template/blob/22c26a93a9e4974b16e4351faab0e860ff9fb24f/artifacts/manifest.json)

## Kaggle entry

**Pinned entry commit** `9125501f508151917f308f1b9d64ac7177cb8edd`. This commit preserves the exact source and artifacts from the organizers’ Apache-2.0 template. The current kit found 28 usable task artifact directories, flagged one as empty, and warned that the archive came from an earlier dev-set version. The official smoke check for the current environment is pending. [Pinned entry tree](https://github.com/tuanngocfun/agent/tree/9125501f508151917f308f1b9d64ac7177cb8edd) · [Organizer template](https://github.com/physical-engineerings-last-exam/submission-template/tree/22c26a93a9e4974b16e4351faab0e860ff9fb24f)

- [Project Description](writeup/project-description.md)
- [Kaggle fields and figures](writeup/kaggle-fields.md)

## Deliverable-first prototype

A separate local candidate addresses the archived failures. Pi declares the explicitly requested file paths, drafts usable outputs early, and checks constraints before optimizing. The harness audits file structure inside the task container and can start one repair phase capped at four minutes when it finds a file defect or Pi has yet to return a final answer. Tasks that only require application state or a response can complete without a file audit.

The prototype passed ten offline integration scenarios using simulated Pi replies, including missing and malformed files, cancellation, and an app-only task. Its submission configuration passed static kit validation. The next benchmark pairs the baseline and candidate on the same current dev tasks, model, grader, and budget. A third run with repair disabled isolates the value and cost of the repair pass. The official comparison and candidate score are pending. [Official evaluator](https://github.com/google-research/ple/blob/5cf736f8b6e6f28eea71cae52de0c3bedaa88fa2/eval/README.md)

## Baseline files

| Path | Purpose |
| --- | --- |
| `submission.yaml` | Model and install and serve commands |
| `serve.py`, `harness.py` | WebSocket entry point and Pi wrapper |
| `task-tools.ts`, `taskbridge.py` | Relay from Pi to the task container |
| `package.json`, `package-lock.json` | Pinned Pi dependencies |
| `artifacts/` | Archived deliverables, trajectories, and manifest |

The Kubernetes Security Remediation Agent demo is maintained on the [`kube-remediation-demo`](https://github.com/tuanngocfun/agent/tree/kube-remediation-demo) branch.
