# KALM static candidate corpus

Imported **241 upstream YAML files / 445 resource documents** from [dynatrace-oss/Kalm-Benchmark](https://github.com/dynatrace-oss/Kalm-Benchmark/tree/6da1b2d75e7fb05a69adc632e89ad0dc84e5f115), revision `6da1b2d75e7fb05a69adc632e89ad0dc84e5f115`, Apache-2.0.

These are scanner test examples. **Zero cases in this corpus have been validated as executable repair tasks, and zero model results are claimed.** Intentionally vulnerable raw manifests are retained for provenance; do not deploy them indiscriminately.

`agent-inputs/` contains answer-sanitized static JSON. `raw/` and `records.jsonl` contain oracle labels and descriptive filenames and must remain outside an evaluated model's accessible workspace. Runtime-relevant legacy seccomp/AppArmor annotations and PSA labels remain; other annotations are removed. Declared names and benchmark check labels are anonymized with exact references consistently rewritten. This is not a proven behavior-preserving conversion.

`provenance.json` binds every original file by pinned Git blob SHA-1 plus SHA-256; original bytes and license text are unmodified. `records.jsonl` separates source scanner expectations from model input and records exact and identifier-normalized structural duplicate groups. Source rule families and duplicates are assigned together to a deterministic development/evaluation partition. This public split does not claim hidden tests or model-training decontamination.

Regenerate into a fresh directory with `python3 scripts/import_kalm_corpus.py --output NEW_DIRECTORY`. Dependency: `PyYAML>=6.0.1,<7`. Nothing from upstream is executed. See `summary.json` for precise counts and limitations.
