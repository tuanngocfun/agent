# Tasks: VGU rehearsal alignment

**Input**: spec.md,plan.md,research.md,data-model.md,quickstart.md.
**Tests**: Explicitly required by the user-facing verification specification.
**Organization**: User stories with independent acceptance checks. Boxes reflect implementation evidence, not personal readiness.

## Phase 1: Setup
- [x] T001 Use the Spec Kit specification/plan/task structure; detailed authoring logs remain local (FR-009).
- [x] T002 Complete constitution, spec.md and checklists/requirements.md with source authority and human boundaries (FR-003,FR-009,FR-010).
- [x] T003 Install canonical .venv, pin requirements.lock.txt and document the interpreter in START_HERE.md (FR-015).

## Phase 2: Foundations
- [x] T004 Preserve prechange authoring material locally; include only package-relative hashes and checks in the repository edition (FR-011).
- [x] T005 Establish corrected canonical src/vgu_transformers.py and behavior checks in tests/ (FR-007).

## Phase 3: User Story 1 - Visible results
- [x] T006 [US1] Complete the original visible-output repair locally; the repository edition distributes the selected worked notebooks with accurate status labels (FR-001,FR-011).
- [x] T007 [US1] Deliver strict-executed core notebooks notebooks/01_Core_Attention_Worked.ipynb and notebooks/02_Training_and_Generation_Worked.ipynb (FR-002,FR-003).
- [x] T008 [US1] Deliver strict-executed optional notebooks notebooks/03_Optional_Systems_Worked.ipynb and notebooks/04_Optional_Image_to_Sequence_Worked.ipynb with measured controls and scope (FR-002,FR-007).
- [x] T009 [US1] Separate notebooks/student_exercises/ from private references and verify blank student tests fail for TODOs (FR-006).

## Phase 4: User Story 2 - Coherent lecture
- [x] T010 [P] [US2] Finalize content/trial_lecture.json and teaching/LECTURE_SCRIPT.md with aligned30-minute schedule and numerics (FR-003,FR-004).
- [x] T011 [US2] Render slides/Trial_Lecture_30min.pptx and slides/Trial_Lecture_30min.pdf with matching embedded notes (FR-004,FR-008).
- [x] T012 [P] [US2] Deliver teaching/STUDENT_PATHWAY.md and teaching/ASSESSMENT_AND_HANDOUT.md matching notebooks and four-function learner API (FR-003,FR-006).

## Phase 5: User Story 3 - Evidence-grounded research
- [x] T013 [P] [US3] Finalize content/research_orientation.json and research/RESEARCH_SCRIPT.md with20-minute schedule and verified historical claims (FR-004,FR-005).
- [x] T014 [US3] Render slides/Research_Orientation_20min.pptx and slides/Research_Orientation_20min.pdf with matching notes (FR-004,FR-008).
- [x] T015 [P] [US3] Deliver research/CLAIM_LEDGER.md and interview/INTERVIEW_QA.md with claim evidence and independent explanation prompts (FR-005,FR-010).

## Phase 6: User Story 4 - Practical entrypoint and fulfillment
- [x] T016 [US4] Write START_HERE.md and scripts/open_jupyter.sh with current links and rehearsal sequence (FR-012,FR-015).
- [x] T017 [P] [US4] Write a generic preparation checklist with human actions left unchecked; administrative details remain outside this edition (FR-010).
- [x] T018 [US4] Provide packaged checks in scripts/check_portable.py and aggregate export evidence in verification/EXPORT_CHECKS.md (FR-001 through FR-017).
- [x] T019 [US4] Render and inspect delivered notebooks/slides locally, resolve clipping/content omissions, and distribute an aggregate summary without preview images (FR-013).

## Phase 7: Final integration and convergence
- [x] T020 Run authoring prerequisite/convergence checks locally and preserve the repository scope and human-pending limits in the aggregate export summary (FR-009,FR-010).

## Dependencies and parallel work
T001–T005 establish project contracts. T006 is the independent original-output repair. Core/optional notebooks (T007–T009),lecture content (T010/T012),and research content/ledger (T013/T015/T017) can proceed in parallel after foundations. Deck rendering requires its respective JSON. Entry links and final verification depend on finished artifacts. T020 follows completed implementation and tests. No candidate-only action is a build task.

## Implementation strategy
Complete the original visible-output interaction as local authoring work. Deliver four complete worked notebooks while leaving student exercises honest. Build aligned static decks and full scripts from the same structured content. Verify content, saved outputs, source claims, links, rendering and local launch;only then assess material convergence. Human timed rehearsal and application submission remain separate.

## Phase 8: User-requested browser rendering and repository delivery
- [x] T021 [US4] Render this edition’s linked guides and Markdown in site/ using scripts/render_docs.py; earlier export repairs remain local authoring history (FR-016).
- [x] T022 [US4] Verify HTTP links, local math assets and actual browser rendering in verification/document_browser_checks.json (FR-016,FR-013).
- [x] T023 [US4] Deliver the initial reviewed package to the user-selected repository branch and verify its remote contents; the reference snapshot is recorded in verification/github_upload.json (FR-017). Later reader changes require their own readback.
- [x] T024 Update the aggregate export check summary for the verified initial browser/repository snapshot and preserve the separate pending status of later reader changes (FR-009,FR-016,FR-017).
