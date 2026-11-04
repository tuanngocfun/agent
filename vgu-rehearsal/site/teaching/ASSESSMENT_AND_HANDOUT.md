# Core learner handout and assessment guide

**Topic:** Introduction to Sequence Generation with Transformers  
**Audience:** Bachelor students with basic vectors, matrix multiplication, probabilities and Python indexing  
**Core:** Tier 1 (60–90 minutes, 25 points) followed by Tier 2 (2–3 hours, 25 points)  
**Optional:** systems and synthetic image-to-sequence extensions after the core

The lecture is 30 minutes; this homework/tutorial time is additional. The worked teacher notebooks contain answers and saved outputs. For an independent learner distribution, provide the `notebooks/student_exercises/` folder and the learner-facing task/rubric text below, rather than the whole private rehearsal master. Keep worked solutions private until feedback or self-study begins.

## What you will learn and why

You will connect an attention calculation to tensor code, prevent a model from seeing future answers, align inputs with next-token labels, and evaluate the distinction between correct training prefixes and generated prefixes. These skills apply to translation, code generation, speech transcripts and document transcription. They also help you identify a result that looks excellent because of a data or implementation error.

Before beginning, check that you can multiply `[1,0] · [0,1]`, predict the shape of `[T,d] @ [d,S]`, and explain that `p(next | earlier)` means probability of the next item given earlier items. Read a token as a vocabulary item, not necessarily a complete word. An embedding is a learned vector selected by a token ID. Use the prerequisite section in STUDENT_PATHWAY.md and ask for a short prerequisite exercise if one of these steps is unfamiliar.

## Your files and workflow

Open `Tier1_Student.ipynb`, then `Tier2_Student.ipynb` in `notebooks/student_exercises/`. Write your own code in `student_impl.py`. Its four functions deliberately raise `NotImplementedError` until you implement them. Blank work is an incomplete exercise, not an environment failure.

1. Predict and write the calculation or shape before reading an output.
2. Complete the written Tier 1 reasoning.
3. Implement the functions while working through Tier 2.
4. Return to the Tier 1 check cells, which call those same functions.
5. Run the supplied behavioral tests against **your** `student_impl.py`.
6. Explain one failed attempt, its cause, the correction and a fresh case you checked.

Use the tested environment and kernel identified in the package's main run guide. From the learner directory, the assessment command is `python -m pytest -q tests` with that interpreter. Keep the test output in your submission. A notebook opening successfully or a green instructor demonstration is not a substitute for your implementation and reasoning.

## Tier 1 — Explain before coding: 25 points

| Task | Required evidence | Points |
|---|---|---:|
| 1A Attention calculation | For `q=[1,0]`, `K=[[1,0],[0,1]]`, `V=[[2,0],[0,4]]`, predict the larger weight; calculate raw/scaled scores, softmax weights and output. Explain Q/K/V and why key width determines the scale. | 8 |
| 1B Shape trace | For `B=2,H=4,Tq=3,Tk=5,d=8,dv=6`, give Q/K/V, score, weight and output shapes. Name the softmax axis and explain why source and target lengths may differ. | 4 |
| 1C Visibility and shift | Draw a 4×4 additive causal mask. Shift `[BOS,a,b,c,EOS]` into decoder input and next-token targets. Explain separately what an incorrect mask and an incorrect shift would permit. | 5 |
| 1D Learning signal | For logits `[ln(2),0,0]` and target index 2, compute probabilities, negative log-likelihood and perplexity. Declare the loss ignore index. Explain why low training loss alone does not establish generalization. | 5 |
| 1E Sequence score | Given `p(A)=.6`, `p(B)=.4`, best continuation after A `.5`, best after B `1`, calculate both complete scores. Explain why a greedy first choice can lose. This written arithmetic alone does not test a search implementation. | 3 |

The shape numbers in this independent workbook intentionally differ from the lecture's example `B=2,H=3,T=5,S=7,d_k=4,d_v=6`. Transfer the axis meanings rather than copy the lecture tensor sizes.

**Transfer prompt:** choose a next-word predictor, character transcriber or structured-output parser. Name its input, token unit, target sequence, BOS/EOS, loss, metric, one possible leak and one simple baseline. Include this explanation with your code submission.

## Tier 2 — Implement and challenge your code: 25 points

| Task | Required evidence | Points |
|---|---|---:|
| 2A Attention | Implement `attention(q,k,v,mask=None)`: scaled scores, floating additive mask, key-axis softmax, value mixture. Support rectangular attention and broadcast masks. Demonstrate the declared all-masked policy. | 8 |
| 2B Causality | Implement `causal_mask(t_query,t_key=None,past=0,device=None)`. A key `j` is visible iff `j <= past + query_index`. Show that changing only future K/V does not alter earlier outputs. Cover padding keys, offsets and all-masked rows. | 7 |
| 2C Shift and loss | Implement `next_token_pairs(ids)` and `masked_cross_entropy(logits,labels,*,ignore_index)`. Preserve EOS as a target, ignore padded labels explicitly and cover the all-ignored loss policy. | 7 |
| 2D Diagnose and explain | Explain how unmasked teacher-forced input can contain an earlier position's correct label. Submit a 250-word explanation distinguishing mask, shift, source attention and loss padding, supported by one behavioral check. | 3 |

Use the following explicit interface policy:

- Masks are floating additive scores: `0` permits a key, `-inf` blocks it **before** softmax.
- Attention weights are the values **after** softmax. Each valid row sums to one.
- A fully blocked query row returns zero weights and zero output in this exercise; its row sum is zero. Implement the policy without NaN gradients. Ordinary all-`-inf` softmax has no valid distribution.
- Loss averages only valid labels and requires an explicit ignore index. If every label is ignored, return differentiable zero with zero gradients.
- Ignoring PAD in loss does not block PAD in attention. They require different operations.

Other edge policies can be reasonable in a different API, including explicit rejection. The supplied tests assess the stated contract. They import the learner implementation, so an unimplemented function must fail. Do not replace the learner module with an instructor import.

## Grading criteria and feedback

Calculations and explanations receive credit for a correct method even when one arithmetic slip affects a final number. Name the axes and intermediate values so the cause is visible. Code receives credit for behavior under fresh inputs, not resemblance to a reference implementation. Tests provide evidence for the implemented cases; they do not prove every possible behavior.

For a missed shape question, reduce to two queries and three keys and count comparisons. For mask/weight confusion, write the values before and after softmax in separate rows. For a missed shift question, write one explicit pair, such as input `a` → target `b`. For a future-invariance failure, perturb only future data and compare earlier outputs before inspecting the mask's appearance. Reattempt a fresh case after feedback.

To check independent understanding, the teacher may change the query to `[0,1]`, alter a value vector, use unequal source/target lengths, or ask about a different masked key. A correct copied output is insufficient evidence for that check. Human observations are recorded during the real tutorial; this guide does not claim they have occurred.

## What to submit

Submit your completed Tier 1 written work, the two notebooks with your actual outputs, your `student_impl.py`, the behavioral test result and the short explanation/transfer prompt. Identify the interpreter/kernel you used. State any incomplete task directly. Do not fabricate a passing result or an error example. Passing tests plus a clear explanation are both required for the core; the lecturer agrees any final course grade.

## Optional follow-up — choose one

**Systems, one to two weeks:** use `03_Optional_Systems_Worked.ipynb` as a worked reference after the core. Verify cached/full output agreement, including offsets, before benchmarking at multiple supported lengths. State the hardware, dimensions, precision and measurement policy. Report observed timings without promising a speedup. RoPE, grouped-query attention and cache storage are optional extension topics.

**Image-to-sequence, one to two weeks:** use `04_Optional_Image_to_Sequence_Worked.ipynb` as a worked reference. Identify the source encoder, cross-attention, shifted training targets and actual generation loop. Compare greedy and **beam width 3** on the **same 16** worked examples, alongside the nearest-template baseline. Declare exact match and CER conventions and report actual errors, including “none observed” when appropriate. The four-template, fixed-length synthetic task is not evidence of real OCR generalization or a need for target-history dependence. A larger frozen noise experiment is a separate extension, not a claim from those 16 cases.

A position-encoding ablation, a pretrained model and a real-document research dataset are possible later projects with their own controls. They are not promised as completed components of the core handout.
