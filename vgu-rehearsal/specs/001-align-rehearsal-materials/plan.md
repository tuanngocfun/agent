# Implementation Plan: VGU rehearsal alignment

**Branch**: `codex/vgu-rehearsal-2026-11-04` | **Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)
**Input**: specs/001-align-rehearsal-materials/spec.md

## Summary
Publish fresh results into the 14 original notebooks and build a single rehearsal package with four strict worked notebooks, aligned 30/20-minute decks, matching notes, evidence-grounded research claims, clear student exercises and requirement-level verification.

## Technical Context
**Language/Version**: Python 3.12.3, Bash; editable JSON/Markdown content.
**Primary Dependencies**: PyTorch 2.10.0+cpu, nbformat/nbclient, Matplotlib, python-pptx, ReportLab, PyMuPDF, Playwright. Local Specify CLI 1.3.1.dev0 from revision a227e38315cd38172b04f2fb8f06ce8b69b38331.
**Storage**: package-relative teaching artifacts and generated browser pages. Original authoring inputs and backups remain local and are excluded from this repository edition.
**Testing**: strict fresh-kernel execution; behavior tests against canonical src; saved-output readback; rendered PDF/HTML inspections; slide/notes timing and claim ledger checks.
**Target Platform**: Linux host and IDE; static PDF/PPTX for rehearsal.
**Project Type**: local educational/rehearsal artifact package and verification scripts.
**Performance Goals**: runnable self-contained CPU demos; no model-speed or student-learning guarantee.
**Constraints**: 30-minute Bachelor English trial;20-minute research;Q&A separate. No real data or online model download during labs. Human confirmations remain unverified.
**Scale/Scope**: 14 original notebooks;4 canonical worked notebooks;separate student stubs;14 trial slides;12 research slides;rehearsal scripts and candidate action checklist.

## Constitution Check
All five principles are covered: outputs at linked paths; invitation-driven content; behavioral and delivery checks; primary-evidence claims; one offline rehearsal route. No violations or unresolved technical clarifications. Recheck after implementation. No extension hooks configured.

## Project Structure
### Documentation (this feature)
specs/001-align-rehearsal-materials/{spec,plan,research,data-model,quickstart,tasks}.md and verification traceability.
### Source Code (repository root)
START_HERE.md;content/{trial_lecture,research_orientation}.json;slides/*.pptx and *.pdf;teaching/*.md;research/*.md;interview/*.md;notebooks/01..04_Worked.ipynb;notebooks/student_exercises/;src/vgu_transformers.py;tests/;scripts/;verification/;.venv/.
**Structure Decision**: one canonical entrypoint with static artifacts and executed notebooks beside their scripts. Content JSON drives both slide formats and embedded notes; Markdown scripts are checked against the same timings. The original authoring history remains a local-only provenance record. This repository edition contains the selected teaching artifacts and aggregate checks; it does not reproduce that wider history.

## Phases
0. Confirm original symptom and controlling invitation/evidence;pin local Spec Kit source.
1. Define the specification, artifact contracts and task coverage.
2. Publish original outputs and build core/optional worked notebooks with behavioral checks.
3. Build corrected lecture and research content;render PDF/PPTX with the same typed layout and notes.
4. Run output/timing/claims/link/render verification;assess convergence and complete remaining gaps.

## Complexity Tracking
No constitution violations need exceptions. No new web service, public hosting, external account or large pretrained model is required.
