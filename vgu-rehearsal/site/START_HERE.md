# Start rehearsal here

This repository package contains a 30-minute Bachelor-level introduction to sequence generation
with Transformers, a separate 20-minute research-orientation talk, four worked notebooks and
independent learner exercises. The scripts include explanations, questions, feedback and an
offline fallback. Saved outputs let you inspect computations before installing an environment.

This is a teaching and rehearsal export. Its scope and exclusions are described in
[PUBLICATION_SCOPE.md](PUBLICATION_SCOPE.md). Checks of the bundled files do not certify a timed
human delivery, student comprehension or anyone's personal history.

## Clone and read

```bash
git clone --branch codex/vgu-rehearsal-2026-11-04 --single-branch https://github.com/tuanngocfun/agent.git
cd agent/vgu-rehearsal
```

Open [site/index.html](site/index.html), or follow [BROWSER_README.md](BROWSER_README.md).
The browser pages, saved notebook outputs and PDFs can be read without installing packages.

## Rehearse the 30-minute lecture

Open [the lecture PDF](slides/Trial_Lecture_30min.pdf) beside
[the timed script](teaching/LECTURE_SCRIPT.md). The
[PowerPoint](slides/Trial_Lecture_30min.pptx) contains presenter notes. The 15-minute lecture Q&A
is additional to the prepared 30 minutes.

Follow the sequence: motivation → tokens and embeddings → conditional probability → attention
by hand → shapes and scaling → mask and target shift → generation → a student project. Use the
[student pathway](teaching/STUDENT_PATHWAY.md) and
[assessment handout](teaching/ASSESSMENT_AND_HANDOUT.md) to plan the next tutorial.

## Inspect and run the worked notebooks

1. [01 — Core attention worked](notebooks/01_Core_Attention_Worked.ipynb): tokens, embeddings,
   numerical attention, distinct rectangular shapes, mask versus weights, target shift and loss.
   The worked attention output is approximately `[1.3395, 1.3210]`.
2. [02 — Training and generation worked](notebooks/02_Training_and_Generation_Worked.ipynb):
   causal invariance, padding and empty-row policies, actual greedy `0.30` versus beam-width-3
   `0.40` search, EOS behavior and optional temperature sampling.
3. [03 — Optional systems worked](notebooks/03_Optional_Systems_Worked.ipynb): RoPE, grouped-query
   attention, cache offsets and measured CPU timings. The measurements are not a general speed guarantee.
4. [04 — Optional image-to-sequence worked](notebooks/04_Optional_Image_to_Sequence_Worked.ipynb):
   synthetic training, loss curves, matched greedy/beam/template evaluation and actual error analysis.
   Four known glyph templates illustrate mechanics, not real-document OCR generalization.

For code execution on Linux/WSL, have `uv` or Python 3.12 with `venv` support, then run from this directory:

```bash
bash scripts/setup_environment.sh
.venv/bin/python scripts/check_portable.py
bash scripts/open_jupyter.sh
```

The pinned environment targets Linux x86_64 CPU and Python 3.12. Setup downloads packages;
matching wheels on other platforms are not guaranteed. Setup and launch register
**VGU rehearsal (CPU)** using the current checkout location. The
[IDE workspace](VGU_Rehearsal.code-workspace) resolves `.venv/bin/python` relative to this folder.
[Exact dependencies](requirements.lock.txt) are included; environments and caches are excluded.

`check_portable.py` inspects saved outputs, slide counts/notes and the packaged reference tests.
It does not rerun notebooks or overwrite execution manifests. To recompute an example, open its
notebook with the project kernel and run it explicitly. An unrerun saved output is not a new run.

The separate [student exercises](notebooks/student_exercises/README.md) intentionally retain
blank implementations. Their tests call student code and should fail until the learner finishes
it. Use that folder for independent assessment; the wider package contains worked answers.

## Rehearse the 20-minute research talk

Open [the research PDF](slides/Research_Orientation_20min.pdf) beside
[the research script](research/RESEARCH_SCRIPT.md). The
[PowerPoint](slides/Research_Orientation_20min.pptx) contains presenter notes. The 10-minute research
Q&A is additional to the prepared 20 minutes.

Use the [research claim ledger](research/CLAIM_LEDGER.md) to distinguish public scholarly results
from proposed experiments. Check metric names, populations, comparison controls and limitations.
The [technical interview prompts](interview/INTERVIEW_QA.md) support unscripted explanation and
debugging practice. The [generic preparation checklist](interview/SUBMISSION_CHECKLIST.md) remains
unchecked until the presenter performs each action.

The original private evidence collection, application records and machine-specific provenance
audit are not included. This package makes no claim that a clone reproduces that broader audit.
