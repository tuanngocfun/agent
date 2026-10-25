# Kronos technical report

[Read the compiled PDF](report.pdf) · [LaTeX source](report.tex)

The report documents the implemented forecasting lab, its data and sampling
contract, chronological evaluation and interval expansion, two-stage adaptation,
MCP/HTTP interfaces, recorded results, reproduction commands, and research limits.
It describes implementation commit `693bcc4331a2df80402496492ccfa1a237f90c7a`
on `kronos-evaluation-lab`.

The numerical evidence is the committed
[`evidence/run-summary.json`](../../evidence/run-summary.json), recorded on
24 October 2026 at 17:20 UTC (25 October in Ho Chi Minh City). These are bounded
integration runs: four calibration windows, four test windows, eight sampled
paths, and two optimizer updates per adapted stage. The saved settings are
64 history / 8 future bars / 8 paths; the later dashboard screenshot uses
128 / 12 / 20. The PDF does not claim that the screenshot has been evaluated.

## Build

Python 3.10+ and either [Tectonic](https://tectonic-typesetting.github.io/) or
pdfLaTeX are sufficient. The application environment, model weights, GPU, local
CSV, and full run exports are not needed to rebuild the report.

From the repository root:

```bash
python3 docs/technical-report/generate_tables.py
python3 docs/technical-report/generate_tables.py --check
make -C docs/technical-report
```

For a compiler outside `PATH`:

```bash
make -C docs/technical-report TECTONIC=/absolute/path/to/tectonic
```

Force recompilation with `make -B -C docs/technical-report`. The Makefile runs
pdfLaTeX twice when Tectonic is unavailable. A first Tectonic build may download
its TeX bundle; offline compilation requires its populated cache or a complete
TeX installation. Standard packages used by the source are `fontenc`, `inputenc`,
`lmodern`, `geometry`, `amsmath`, `amssymb`, `booktabs`, `longtable`, `array`,
`xcolor`, `graphicx`, `listings`, and `hyperref`.

The generator uses only Python's standard library. It reads the versioned
aggregate evidence and generates five tables, numerical macros, and
[`evidence-manifest.json`](evidence-manifest.json), which records the source
SHA-256, data hash, model identities, and fixed implementation commit.
`--check` compares those seven files without writing. PDF bytes can differ
across compiler/bundle versions; generated tables and the manifest are
deterministic. `make clean` removes only TeX intermediate files.

## Verification

The publication build uses Tectonic 0.17.0. Table consistency was checked with
`generate_tables.py --check`. Independent recalculation from the local full
evaluation and ablation exports matched their aggregate values to numerical
precision. The project suite was re-run: **159 passed**, with one nonfatal
NumPy timedelta deprecation warning. The four official upstream regressions,
GPU inference, training, MCP, and browser runs are prior recorded checks in
[`VALIDATION.md`](../../VALIDATION.md); they were not all repeated for this
documentation change.

The PDF was opened with PyMuPDF, text was extracted from every page, and rendered
pages were inspected for table legibility, blank pages, unresolved references,
and text outside the page. Optional inspection with PyMuPDF installed:

```bash
python3 - <<'PY'
import pymupdf
doc = pymupdf.open('docs/technical-report/report.pdf')
text = '\n'.join(page.get_text() for page in doc)
assert '??' not in text
assert '185.40' in text and '290.77' in text and '159' in text
for i, page in enumerate(doc):
    assert page.get_text().strip()
    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(f'/tmp/kronos-page-{i+1}.png')
print(f'{len(doc)} pages inspected')
PY
```

The PDF and sources are intentionally versioned here. Raw candles, full trajectory
exports, checkpoints, credentials, and dashboard screenshots remain outside this
report package. The report's source-code links pin the audited implementation;
the report itself is added by a later documentation commit.
