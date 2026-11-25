# Kaggle draft fields

| Field | Value |
| --- | --- |
| Title | Pi on Physical Engineering |
| Subtitle | An audit of the official Pi and Claude Opus 5.5 baseline across 29 engineering development tasks. |
| Track | Main Track |
| Project description | [project-description.md](project-description.md) |
| Card and thumbnail | [thumbnail.png](thumbnail.png), 560 × 280 |
| Media gallery | [Architecture](architecture.png), [score versus cost](dev-score-vs-cost.png), [zero-score breakdown](dev-zero-score-breakdown.png) |
| Project link | [tuanngocfun/agent](https://github.com/tuanngocfun/agent) |
| Entry commit | [`9125501f508151917f308f1b9d64ac7177cb8edd`](https://github.com/tuanngocfun/agent/tree/9125501f508151917f308f1b9d64ac7177cb8edd) |

Add the repository link above in Project Links and keep the entry’s 40-character SHA at the top of the description. The pinned entry has the same Git tree as the organizer template. The later commit on main adds the writeup files for readers. Put the architecture, score-versus-cost, and failure figures in the writeup. [Competition requirements](https://www.kaggle.com/competitions/physical-engineerings-last-exam/overview/submission-requirements)

## Validation record

- Template revision `22c26a93a9e4974b16e4351faab0e860ff9fb24f` and kit revision `5cf736f8b6e6f28eea71cae52de0c3bedaa88fa2`.
- `kit validate` passed. `kit artifacts` exited successfully with 28 usable tasks, one empty task, and a dev-set-version warning.
- `kit check` stopped before the smoke run because `MODEL_PROXY_URL` and `MODEL_PROXY_KEY` were unset. This host also lacks the Docker runtime required by the kit.
- The 0.4912 archived mean summarizes the organizer’s 29 manifest entries. The leaderboard’s 0.474 and $13.29/task describe a separate cohort.
- The provided [Avik Das notebook](https://www.kaggle.com/code/avikdas567/code-gated-agent-harness-for-physical-engineering/notebook) uses seeded random draws for its 87.66% Claude figure. The published notebook and its generated placeholder files serve as a design reference for the audit.

The organizer template permits an unchanged submission with its bundled artifacts. The current kit’s version warning and the rubric’s controlled comparison requirements still apply to the entry. The draft describes the evidence presently available and records which runs are pending. [Organizer template](https://github.com/physical-engineerings-last-exam/submission-template) · [Evaluation rubric](https://www.kaggle.com/competitions/physical-engineerings-last-exam/overview/evaluation)

## Inputs for a fresh official run

The organizers publish the [evaluation kit](https://github.com/google-research/ple/tree/5cf736f8b6e6f28eea71cae52de0c3bedaa88fa2) and gate the [public dev task materials](https://huggingface.co/datasets/google/physical-engineerings-last-exam) behind dataset access. The source Kaggle notebook's attached competition link does not supply a runnable dev evaluation. Use a Docker-capable machine with the official dev download and model proxy in place.

From the kit checkout, run the smoke check first, then generate fresh artifacts and validate them.

```bash
uv run python -m kit check ../your-entry
uv run python eval/run.py ../your-entry --tasks wind-diaphragm-shear --trials 1
uv run python eval/run.py ../your-entry
uv run python -m kit artifacts ../your-entry
```

Work in an entrant repository for a new run so the archived organizer checkout remains available for comparison. The named pilot checks the evaluation pipeline. Submit artifacts and code from the same commit after the full run. [Evaluator instructions](https://github.com/google-research/ple/blob/5cf736f8b6e6f28eea71cae52de0c3bedaa88fa2/eval/README.md)
