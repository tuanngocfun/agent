# Feature Specification: Align VGU rehearsal materials and visible notebook results

**Feature Branch**: None; a standalone materials project, no branch changes.
**Created**: 2026-11-04
**Status**: Specified
**Input**: The user cannot see notebook outputs and requests use of the local GitHub Spec Kit to fulfill interview and teaching requirements so rehearsal can begin.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See actual notebook results (Priority: P1)
The candidate opens the original interview notebooks and immediately sees actual saved results, with unfinished student exercises clearly identified. The candidate also has a distinct set of complete worked notebooks for rehearsal.

**Why this priority**: The prior handoff placed results elsewhere, leaving the candidate's files empty.
**Independent Test**: Open the original instructor notebook and a canonical worked notebook without running a kernel; inspect visible numerical outputs and saved execution counts.
**Acceptance Scenarios**:
1. Given the 14 original notebooks, when their saved files are read, all code cells have fresh execution counts and every file has saved output; instructor paths contain no errors, student TODOs remain explicitly incomplete.
2. Given the four canonical worked notebooks, when run from a clean kernel, all code cells execute without allowed errors and results remain saved at the linked paths.
3. Given blank student code, when its own grading checks run, they fail for unfinished work rather than passing through imported answers.

### User Story 2 - Rehearse a coherent Bachelor lecture (Priority: P1)
The candidate follows one 30-minute English lecture and its matching script, using worked numerical and code examples to explain what students learn, why it matters and what they can apply later.

**Why this priority**: Rehearsal requires finished teaching artifacts, not another findings-only report.
**Independent Test**: Compare slide order, notes, time allocations, handout and notebook examples, then open static slides and worked results offline.
**Acceptance Scenarios**:
1. Given the trial lecture, when slide minutes are summed, the schedule is 30 minutes, with the invitation's 15-minute Q&A additional.
2. Given each slide, when the presenter reads embedded notes and the script, examples, labels, timings and promised labs match.
3. Given the worked attention example, the reader can follow dot products, scaling, weights, weighted values, causal masking and target shift into code and inspect corresponding results.
4. Given the student pathway, prerequisites, observable core outcomes, optional extensions, feedback questions, baseline and held-out evaluation are explicit.

### User Story 3 - Rehearse an evidence-grounded research presentation (Priority: P1)
The candidate rehearses a 20-minute research orientation whose historical claims match primary evidence and whose future plan reflects the actual RTA duties without inventing personal facts.

**Why this priority**: Unverified numerical or ownership claims could undermine the interview.
**Independent Test**: Trace every historical number to the claim ledger and compare the roadmap with the supplied JD.
**Acceptance Scenarios**:
1. Given the research deck and script, unsupported project percentages, scholarship labels and personal implementation ownership are omitted from spoken claims.
2. Given published group metrics, metric names, datasets and group attribution match the primary record.
3. Given the research schedule, slide allocations total 20 minutes; the 10-minute Q&A remains separate.
4. Given annual research, teaching and service expectations, the plan acknowledges them and separates intended submissions from accepted publications.

### User Story 4 - Start rehearsal from one place and inspect fulfillment (Priority: P2)
The candidate opens one entrypoint, follows the rehearsal order, selects the installed environment and inspects a requirement-to-evidence record without confusing material checks with personal readiness.

**Why this priority**: Multiple old masters and scattered evidence caused ambiguity.
**Independent Test**: Follow every local entrypoint link and the documented launch command; inspect requirement statuses and the separate personal-action checklist.
**Acceptance Scenarios**:
1. Given START_HERE, every recommended artifact exists and opens directly.
2. Given the local Spec Kit project, its constitution, specification, plan, tasks and convergence assessment are present and trace each obligation to delivered evidence.
3. Given a candidate-only action, it remains unchecked unless an actual user confirmation or observed action exists.

### Edge Cases
- Student TODO failures and comment-only scaffolds must never be treated as completed assignments.
- Fully masked attention rows, padded loss targets and all-ignored targets need declared behavior.
- Internal generated BOS/PAD tokens must not disappear from recognition metrics; finished sequences need a clear EOS convention.
- Cache chunk offsets and future-token changes must preserve the appropriate past outputs.
- Equal-shaped dimensions must not hide transposition mistakes; include rectangular examples.
- A zero toy error rate does not require inventing error examples or imply real OCR generalization.
- Beam search comparisons must use the same cases and an explicit ranking convention.
- No live network or package installation is available during a lecture; static outputs must remain useful.
- The invitation's confirmation deadline says 2025 despite a 2026 interview; preserve the discrepancy as a human clarification.
- Existing files are backed up before in-place output changes; notebook code remains intact.
- Notebook HTML links to Markdown must open a rendered guide with working local assets rather than a missing file or raw source.
- Repository upload must create a new branch and retain the existing main branch and unrelated repository contents.

## Requirements *(mandatory)*

### Functional Requirements
- **FR-001**: All 14 original notebooks MUST retain fresh code-cell execution counts and saved results at their original paths, with accurate instructor/student status.
- **FR-002**: Four clearly named canonical worked notebooks MUST be complete, contain actual results, and execute without allowed errors; core and optional work MUST be distinct.
- **FR-003**: Core teaching MUST connect motivation, prerequisites, theory, a worked numerical example, code, checks and a later application or research question.
- **FR-004**: The trial lecture, embedded notes and script MUST agree in content/order and allocate exactly 30 minutes; research equivalents MUST allocate 20 minutes, excluding their respective Q&A.
- **FR-005**: Historical presentation claims MUST have metric-specific primary evidence and group/personal attribution; unsupported claims MUST be removed from speech and isolated in a confirmation ledger.
- **FR-006**: Promised lab tasks and assessment MUST match delivered notebooks; unfinished student code and private reference solutions MUST be separated and graded through the correct implementation.
- **FR-007**: Behavioral verification MUST cover attention-reference agreement, causal invariance, rectangular shapes, padding/empty rows, shifted labels, cache equivalence and special-token metric behavior.
- **FR-008**: Both presentations MUST have offline-readable slide files, matching rehearsal scripts and directly inspectable notebook results.
- **FR-009**: The local Spec Kit checkout MUST actually initialize and structure this project, with recorded revision/commands and traceable specification, plan, tasks and convergence assessment.
- **FR-010**: Human rehearsal, certificate/current-status confirmation, HR completion, attendance confirmation and submission MUST remain distinct from material verification; no unobserved action may be marked done.
- **FR-011**: Exact original notebook bytes MUST be backed up before updates, and code sources MUST remain unchanged during output publication.
- **FR-012**: One START_HERE entrypoint MUST identify current decks, scripts, worked notebooks, environment and rehearsal sequence; all local links MUST resolve.
- **FR-013**: Delivered slides and notebook previews MUST be rendered and inspected for missing content, unreadable results or clipped text; checks MUST concern the files the candidate opens.
- **FR-014**: No shared dataset writes, outgoing messages or public publication may be performed; computation MUST remain self-contained.
- **FR-015**: An installed, discoverable environment and tested launch procedure MUST run the canonical notebooks; setup and exact dependency versions MUST be recorded.
- **FR-016**: Notebook and rehearsal-browser guide links MUST open properly rendered HTML with readable mathematics, tables and code; local links and required assets MUST resolve through an HTTP server, including the previously broken instructor-guide link.
- **FR-017**: The corresponding rehearsal package MUST be uploaded to a new branch of the user-specified tuanngocfun/agent repository, with remote content readback; existing main and unrelated files MUST be preserved, and installed environments, credentials and private application records MUST be excluded.

### Key Entities
- **Teaching artifact**: title, core/optional scope, audience, outcomes, source references, paths and linked worked examples.
- **Slide**: stable ID, title, minutes, bullets, visual data, embedded notes, takeaway and sources.
- **Notebook result**: actual path, source digest, executed-cell counts, outputs, errors, runtime and status.
- **Research claim**: wording, metric/population, primary evidence, group/personal scope and disposition.
- **Verification record**: requirement, artifact, actual check, observation and passed/failed/human-pending status.

## Success Criteria *(mandatory)*

### Measurable Outcomes
- **SC-001**: Opening any original instructor or canonical worked notebook without rerunning reveals saved outputs; no canonical worked notebook contains an execution error.
- **SC-002**: The candidate can locate the current lecture, research talk and worked notebook from START_HERE in one link each.
- **SC-003**: All scheduled lecture minutes total 30 and research minutes total 20; each slide has matching presenter guidance.
- **SC-004**: Every historical quantitative research claim in the new presentation maps to matching evidence; unsupported claims are absent from spoken content.
- **SC-005**: Every FR has a delivered artifact and recorded verification; candidate-only actions remain separately unverified.
- **SC-006**: The package provides a numeric attention example, causal-mask/shift diagnosis, actual generation comparison and a baseline-based project pathway, with results directly inspectable.
- **SC-007**: The rendered browser entrypoint and instructor guide load through HTTP with no broken local links or math-rendering errors.
- **SC-008**: The new repository branch contains the prepared artifact snapshot, confirmed by remote tree/blob identities, while main remains unchanged.

## Assumptions
- Rehearsal-material preparation is authorized; final personal confirmations and any external submission remain the candidate's responsibility.
- The supplied invitation/JD and verified primary records control requirements. Older AI reviews are evidence to check, not authorities.
- English Bachelor instruction targets an introduction, not mastery of advanced Transformer engineering in 30 minutes.
- Four synthetic known glyphs remain a fixed-length educational demo; no real OCR performance or novel-character generalization is claimed.
- Human timed delivery and student learning cannot be observed by preparing files; the package supplies practical checks for the candidate to perform.
- The user's later request explicitly authorizes uploading corresponding prepared files to a new repository branch. The connected repository was verified as private; no public website deployment is requested.
