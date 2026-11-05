# Independent practice and assessment guide

**Topic:** Introduction to Sequence Generation with Transformers  
**Audience:** Bachelor students with vectors, matrix multiplication, probability and basic Python indexing  
**Core practice:** Tier 1, 60–90 minutes / 25 points; Tier 2, 2–3 hours / 25 points

The lecture is 30 minutes; practice time is additional. Every delivered notebook now contains completed worked examples. The historical `Tier1_Student.ipynb`, `Tier2_Student.ipynb` and `student_impl.py` filenames are retained, but their contents are **reference solutions**, not unfinished student submissions. Their passing tests do not establish independent learner implementation.

## Presentation and independent-work routes

For teaching, use [Tier1_Instructor.ipynb](../notebooks/Tier1_Instructor.ipynb) and [Tier2_Instructor.ipynb](../notebooks/Tier2_Instructor.ipynb). They connect motivation, mathematics, complete code, expected behavior and checks. The historical [exercise folder](../notebooks/student_exercises/README.md) also contains completed examples. Keep those demonstrations intact and runnable.

For independent work, use [STUDENT_PRACTICE.md](STUDENT_PRACTICE.md). Its unanswered Markdown prompts use changed inputs. Learners create their **own separate module and folder**, rather than delete code from a supplied notebook. No executable blank notebook ships in this package.

The target functions are `attention`, `causal_mask`, `next_token_pairs` and `masked_cross_entropy`. A learner may copy the supplied behavioral tests into their own practice folder and change the copied import to their own implementation. For example, for their own `my_attention.py`, use `import my_attention as s`. Run from that separate folder and check the imported module's location so the tests cannot accidentally exercise the completed package reference.

The supplied tests are public correctness checks, not a hidden examination. Include a fresh changed-input question and an unscripted explanation when assessing independent understanding.

## What to learn and why

A generator needs inputs, ordered targets, a learning objective and a stopping rule. Attention combines available information; masking prevents future-answer leakage; target shifting defines what each position predicts; generation uses predicted prefixes. These ideas transfer to translation, code, speech transcription and document recognition.

Before practice, check a short dot product, the shape of `[T,d] @ [d,S]` and the meaning of `p(next | earlier)`. Explain that a token may be a word part or symbol, an ID is a lookup address, and an embedding is a learned vector. Use the prerequisite section in [STUDENT_PATHWAY.md](STUDENT_PATHWAY.md) for a short diagnostic.

## Tier 1 — Explain before coding: 25 points

These are the independent variants in STUDENT_PRACTICE.md, deliberately different from the worked demonstrations.

| Task | Required independent evidence | Points |
|---|---|---:|
| 1A Attention | For the changed query/values, predict relevance, calculate raw/scaled scores, weights and output; explain what changes when only V changes. | 8 |
| 1B Shapes | For `B=3,H=2,T=4,S=7,d_k=5,d_v=6`, trace all shapes and name the normalized and summed axes. | 4 |
| 1C Visibility/shift | For `[BOS,x,y,EOS]`, construct inputs, targets and the mask; identify exactly which future input would leak an answer. | 5 |
| 1D Learning signal | For `[0,ln(3),0]`, target 0, derive probabilities, NLL and perplexity; distinguish vocabulary probabilities from attention weights. | 5 |
| 1E Sequence score | Compare greedy and complete-sequence decisions using the practice tree; declare length and EOS conventions. | 3 |

Credit correct intermediate reasoning even when one arithmetic slip changes the result. Ask a fresh value, dimension or visibility question before concluding the method transfers.

## Tier 2 — Implement and challenge your own component: 25 points

| Task | Required independent evidence | Points |
|---|---|---:|
| 2A Attention | Own scaled-score/mask/softmax/value implementation; rectangular reference agreement with a declared tolerance. | 8 |
| 2B Causality/padding | Own offset causal mask; future-perturbation, padding-key and empty-row checks; explain an unmasked contrast. | 7 |
| 2C Shift/loss | Own target alignment and explicit padding-aware CE; retain EOS supervision and check ignored-target gradients. | 7 |
| 2D Explain/transfer | Explain mask, shift, source attention and loss padding; diagnose a mismatch and name an application/baseline. | 3 |

The reference contract uses floating additive masks: zero permits, negative infinity blocks **before** softmax. Valid rows sum to one; fully blocked rows return zero weights/output, with finite gradients. Loss requires an explicit ignore index, averages valid targets only and returns differentiable zero for all-ignored supervision. Ignoring padded targets does not hide padding keys in attention.

Other APIs can choose explicit rejection for empty rows/batches; the supplied reference checks assess its stated zero policy. Do not catch or remove a failed assertion to claim completion. All delivered demonstrations use valid inputs and normal successful execution.

## Feedback and submission

For shapes, draw two queries with three key comparisons each. For mask/weight confusion, write separate before/after-softmax rows. For alignment, state one input → next-target pair. For a causality issue, perturb only future data and compare earlier outputs before inspecting the mask picture.

An independent submission contains the learner's calculations, their own module, actual run/test output and an explanation of a mismatch, correction and limitation. Running the supplied completed notebooks checks reference examples; it does not establish that independent submission. The advising lecturer agrees the final grading policy.

## Optional next work

Systems work checks cached/full agreement before measured timings; no speedup is guaranteed. The glyph example compares greedy and beam width 3 on the same cases and a nearest-template baseline. Report actual errors or none observed, with sample count and CER convention. Four known synthetic templates do not establish real OCR generalization or a need for useful target-history dependence.

Position-method ablations, pretrained models and real-document datasets are later projects with their own controls, not prerequisites for running the completed core demonstrations.
