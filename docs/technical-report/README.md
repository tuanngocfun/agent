# Kronos technical report

[Read the compiled PDF](report.pdf) · [LaTeX source](report.tex)

The report documents the implemented forecasting lab, its data and sampling
contract, chronological evaluation and interval expansion, two-stage adaptation,
MCP/HTTP interfaces, recorded results, reproduction commands, and research limits.
It now includes four scientific figures, three actual dashboard screenshots,
visual explanations, a paired Kronos/Chronos-2 benchmark, and cost-aware paper
decisions. The latest saved cost-filtered action is **FLAT**; no stable winning
model or strategy is established.
It describes implementation commit `693bcc4331a2df80402496492ccfa1a237f90c7a`
on `kronos-evaluation-lab`.

The earlier integration evidence is the committed
[`evidence/run-summary.json`](../../evidence/run-summary.json), recorded on
24 October 2026 at 17:20 UTC (25 October in Ho Chi Minh City). These are bounded
integration runs: four calibration windows, four test windows, eight sampled
paths, and two optimizer updates per adapted stage. The saved settings are
64 history / 8 future bars / 8 paths; the later dashboard screenshot uses
128 / 12 / 20. The new experiment uses **128 / 12 / 20**, 999 closed candles,
20 calibration origins and 40 later test origins. Its versioned
[`visual-evaluation-summary.json`](../../evidence/visual-evaluation-summary.json)
records native model metrics, all eight fixed paper rules, an exploratory paired
block bootstrap, exact origins, and source hashes. Screenshots were captured
from the application's saved-result interface using those fresh real exports.

## Build

Python 3.10+ and either [Tectonic](https://tectonic-typesetting.github.io/) or
pdfLaTeX are sufficient. The application environment, model weights, GPU, local
CSV, and full run exports are not needed to rebuild the report.

From the repository root:

```bash
python3 docs/technical-report/generate_tables.py
python3 docs/technical-report/generate_tables.py --check
python3 docs/technical-report/generate_visual_tables.py --check
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
`xcolor`, `graphicx`, `listings`, `placeins`, and `hyperref`.

The generator uses only Python's standard library. It reads the versioned
aggregate evidence and generates five tables, numerical macros, and
[`evidence-manifest.json`](evidence-manifest.json), which records the source
SHA-256, data hash, model identities, and fixed implementation commit.
`--check` compares those seven files without writing. PDF bytes can differ
across compiler/bundle versions; generated tables and the manifest are
deterministic. `make clean` removes only TeX intermediate files.

The additional `generate_visual_tables.py` rebuilds five fresh tables/macros
from the committed visual summary and checks hashes for all published figures,
capture receipts, plotted values and the four reviewed experiment scripts.
The scientific PDFs and PNGs, screenshots, and inspectable
[`figure-data.json`](figures/figure-data.json) are versioned under `figures/`.
Rebuilding the LaTeX PDF requires no model execution or browser.

## Re-run the fresh experiment and capture views

These commands require the prepared application environment, pinned models and
available device. The existing output directory resumes its frozen CSV and
native outputs; use a new directory for a new market snapshot.

```bash
.venv/bin/python scripts/run_visual_evaluation.py \
  --output-dir output/visual-run-20261025 --device cuda:1 --chronos-device cpu
.venv/bin/python scripts/summarize_paired_uncertainty.py \
  --input output/visual-run-20261025/paired-evaluation.json \
  --output output/visual-run-20261025/bootstrap-summary.json
.venv/bin/python scripts/plot_visual_evaluation.py \
  --input-dir output/visual-run-20261025
bash scripts/dashboard.sh start --device cuda:1
.venv/bin/python scripts/capture_report_dashboard.py \
  --results output/visual-run-20261025
python3 docs/technical-report/generate_visual_tables.py \
  --import-run output/visual-run-20261025
```

Capture uses installed Playwright Chromium and the local browser libraries when
present; install Chromium with Playwright on a new machine. It never fills the
API token field or submits an order. The default dashboard URL is
`http://127.0.0.1:8765`; use `--url` to choose another running instance. Only
Plotly label sizes are enlarged for print. Receipt hashes tie captures to native
exports. The longer evaluation is loaded as a saved result because the dashboard
button itself defaults to eight windows.

## Verification

The publication build uses Tectonic 0.17.0. Table consistency was checked with
`generate_tables.py --check`. Independent recalculation from the local full
evaluation and ablation exports matched their aggregate values to numerical
precision. The project suite was re-run: **165 passed in 12.20 s**, with one nonfatal
NumPy timedelta deprecation warning. The four official upstream regressions,
training and MCP integration remain prior checks in
[`VALIDATION.md`](../../VALIDATION.md). Fresh Kronos GPU and Chronos CPU inference,
paired evaluation and the three browser captures were executed for this update.
Six new tests check causal scoring, native median semantics, action/cost gates,
cash/buy-hold accounting, split counts and paired bootstrap validation.

The PDF was opened with PyMuPDF, text was extracted from every page, and rendered
pages were inspected for table legibility, blank pages, unresolved references,
and text outside the page. Optional inspection with PyMuPDF installed:

```bash
python3 - <<'PY'
import pymupdf
doc = pymupdf.open('docs/technical-report/report.pdf')
text = '\n'.join(page.get_text() for page in doc)
assert '??' not in text
assert '467.02' in text and '499.24' in text and '165' in text
for i, page in enumerate(doc):
    assert page.get_text().strip()
    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(f'/tmp/kronos-page-{i+1}.png')
print(f'{len(doc)} pages inspected')
PY
```

The PDF and sources are intentionally versioned here. Raw candles, full trajectory
exports, checkpoints and credentials remain outside this report package.
The three newly requested dashboard screenshots are included. The report's
source-code links pin the audited implementation;
the report itself is added by a later documentation commit.
