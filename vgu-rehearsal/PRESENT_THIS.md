# Present this lecture

Use this page as the presentation entrypoint. Keep the [30-minute lecture PDF](slides/Trial_Lecture_30min.pdf) and [timed script](teaching/LECTURE_SCRIPT.md) open together. The [PowerPoint](slides/Trial_Lecture_30min.pptx) contains the same presenter notes. Allow a separate 15 minutes for questions.

## Before the audience arrives

- Open the PDF and the two core demonstrations below. Check that their saved outputs are visible; reopen an old IDE tab to load the saved version.
- If you plan to execute code, choose **VGU rehearsal (CPU)** from this package. Run the demonstrations before the session.
- Keep the script's static attention calculation, mask and shifted-target table ready. If a live window fails, continue with the PDF and those calculations.
- Start a timer. The 30-minute schedule is a plan; record an actual timed rehearsal and teach-back in the [rehearsal log](teaching/REHEARSAL_LOG.md).

## Demonstrations for the 30-minute lecture

| Open | Explain and ask |
|---|---|
| [01 — Core attention worked](notebooks/01_Core_Attention_Worked.ipynb) | Connect tokens, IDs and embeddings; calculate attention; check dimensions, the causal mask and shifted targets. Ask what information one prediction can use. |
| [02 — Training and generation worked](notebooks/02_Training_and_Generation_Worked.ipynb) | Compare training prefixes with generated prefixes. Show future-invariance, padding and decoding checks. Ask why a locally best next token can lose over a complete sequence. |

Show selected saved outputs inside the script's example time. The lesson does not need a new training run, a download or a benchmark during delivery.

## Completed instructor references for questions and follow-up

These are completed examples. They supplement the two core demonstrations; they do not add time to the 30-minute lecture.

- [Tier 1 — Instructor](notebooks/Tier1_Instructor.ipynb): the introductory implementation and its worked checks.
- [Tier 2 — Instructor](notebooks/Tier2_Instructor.ipynb): the extended implementation and its worked checks.
- [03 — Optional systems worked](notebooks/03_Optional_Systems_Worked.ipynb): position methods, grouped queries, cache offsets and measured CPU behavior.
- [04 — Optional image-to-sequence worked](notebooks/04_Optional_Image_to_Sequence_Worked.ipynb): a small trained model, a template baseline, matched evaluations and observed failure cases. Toy results do not establish real document OCR performance.

Independent tasks are written in [Student practice](teaching/STUDENT_PRACTICE.md). The two historical `Student` notebook filenames now hold completed reference examples; they contain no deliberate unimplemented exercise cells. Use the Markdown questions when asking learners to write or explain their own solution.

## Finish and rehearse the research talk separately

Use the final exit ticket to check the mechanism and information available to a prediction. Finish the lecture at 30 minutes, then take its separate Q&A. Complete the [rehearsal log](teaching/REHEARSAL_LOG.md) after you actually deliver and explain the examples.

The [20-minute research PDF](slides/Research_Orientation_20min.pdf) and [research script](research/RESEARCH_SCRIPT.md) form a separate presentation with an additional 10-minute Q&A. Use [Start here](START_HERE.md) for setup and verification records and [the browser guide](BROWSER_README.md) for formatted reading.
