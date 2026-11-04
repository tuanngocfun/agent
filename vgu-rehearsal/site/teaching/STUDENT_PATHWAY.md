# From the lecture to a defensible student project

The interview asks for a 30-minute introduction to sequence generation with Transformers for Bachelor students, in English at approximately IELTS 6.0. It does not ask students to finish an advanced language-model engineering course in that time. The core outcome is to connect a probability model, an attention calculation, information visibility and the generated-prefix loop. This path makes that outcome inspectable, then offers optional applications and research extensions.

The RTA role includes tutorials and exercises in cooperation with the advising lecturer, checking the rigor and understandability of assessments, maintaining teaching materials, and co-supervising Bachelor work with a faculty member. An independent, proactive assistant can prepare and diagnose a lab while coordinating module scope and assessment decisions with the lecturer.

## Start with the prerequisites

Before the lesson, check that a student can:

- Multiply `[1,0] · [0,1]` and explain why the result is zero.
- Predict that `[T,d] @ [d,S]` has shape `[T,S]`.
- Explain a probability between zero and one and read `p(next | earlier)` as “probability of next, given earlier.”
- Read Python list slicing and tensor indexing before beginning the code lab.

Define a vector as an ordered list of numbers, a token as a vocabulary item and a prefix as the earlier output. Explain that a token can be a word part or a symbol. A vocabulary ID is an embedding-table address, not a meaningful numerical magnitude. The core lecture and core lab use the same local IDs: I=0, love=1, AI=2, BOS=4, EOS=5 and PAD=6. Embedding numbers on the slide are illustrative. The optional synthetic glyph task assigns its content IDs to glyph classes.

For softmax, show the formula `w_i = exp(s_i) / sum_j exp(s_j)` and ask what should sum to one. For cross-entropy, explain that assigning low probability to the correct target is penalized. Students need not derive gradients to start the core lab. English proficiency alone does not establish mathematics or Python readiness; use the diagnostic to choose a small prerequisite exercise.

## Stage 1 — Follow the worked core demonstrations

Open these canonical notebooks in order:

1. [01_Core_Attention_Worked.ipynb](../notebooks/01_Core_Attention_Worked.ipynb): tokens → IDs → embeddings; one numerical attention row; distinct rectangular axes; mask versus weights; shifted targets; loss/perplexity.
2. [02_Training_and_Generation_Worked.ipynb](../notebooks/02_Training_and_Generation_Worked.ipynb): behavioral causality checks; padding and all-masked policies; a real two-symbol greedy/beam-3 counterexample; the generated-prefix distinction. Any sampling section is optional enrichment.

These are worked instructor demonstrations. Saved outputs let a learner inspect actual computed tensors and figures. Predict before reading the next output. Explain a difference between prediction and result. Then change a value or a mask and predict again. Observing an output is useful evidence that code ran; it does not by itself show that the observer understands it.

Check three distinctions aloud: attention weights over keys versus vocabulary probabilities; target shifting versus future-input masking; teacher-forced loss versus actual generated-sequence evaluation. Ask a peer to challenge one explanation with a fresh example.

## Stage 2 — Complete the separate learner exercises

Use [the learner folder](../notebooks/student_exercises/) rather than importing the worked instructor implementation. Start with written work in `Tier1_Student.ipynb` (60–90 minutes, 25 points). Implement the four functions in `student_impl.py` while completing `Tier2_Student.ipynb` (2–3 hours, 25 points). The Tier 1 check cells also call that implementation; return to them after writing the functions. Run the supplied tests against your own file.

The four contracts are:

| Function | What you implement | Why a student needs it |
|---|---|---|
| `attention(q,k,v,mask=None)` | Scaled Q/K scores, additive mask, key-axis softmax, weighted values | Build and inspect the mechanism rather than call an opaque reference |
| `causal_mask(t_query,t_key=None,past=0,device=None)` | Allow key `j` only when `j <= past + query_index` | Prevent future information leakage, including cached offsets |
| `next_token_pairs(ids)` | Inputs `ids[:,:-1]`, labels `ids[:,1:]` | Train next-token prediction with the correct EOS target |
| `masked_cross_entropy(logits,labels,*,ignore_index)` | Mean over valid targets; explicit ignore index | Exclude padded labels while preserving a meaningful learning signal |

The exercise API uses a floating additive mask: zero permits, negative infinity blocks. It chooses zero weights and zero output for an all-masked query row, and differentiable zero loss for an all-ignored batch. Valid attention rows sum to one; all-masked rows sum to zero. Those are explicit exercise policies, not universal behavior guaranteed by every library. Boolean-mask conventions vary between APIs, so do not transfer one convention silently.

Submit numbers, shape annotations, code, output and a short explanation. A blank stub raising `NotImplementedError` is an incomplete exercise. An instructor test pass does not assess a learner's implementation. Keep the distribution limited to the learner folder for independent assessment; the wider rehearsal package is a private teacher master containing worked answers.

## Stage 3 — Optional systems extension

Use [03_Optional_Systems_Worked.ipynb](../notebooks/03_Optional_Systems_Worked.ipynb) only after the core. Suggested project budget: one to two weeks; agree the scope with the lecturer.

Choose one question: does a cached computation reproduce a full pass; how does the declared grouped-query design change cache storage; or what runtime is observed at different supported lengths? Verify outputs first, including multi-token chunks and position offsets. Report batch size, query heads, key/value heads, dimensions, dtype, supported context range, device, warm-up, repetition and measurement method. Report parameter-count changes if the architecture changes. A shorter cache or a correct cache does not establish a runtime speedup; measure it.

A position-encoding ablation is a possible additional project with its own controls. It is not promised by the core lecture or learner tasks. Removing positional embeddings also does not remove the order-related asymmetry supplied by a fixed causal mask. Do not teach RoPE as a guarantee that attention decreases monotonically with distance.

## Stage 4 — Optional image-to-sequence prototype

Use [04_Optional_Image_to_Sequence_Worked.ipynb](../notebooks/04_Optional_Image_to_Sequence_Worked.ipynb). Suggested project budget: one to two weeks to understand, repeat and extend the worked system; not part of the 30-minute lecture.

Explain the whole data flow: known-template glyph images → source encoder memory → decoder cross-attention → vocabulary logits → generated symbols. The current controlled task uses four synthetic glyph classes and fixed-length targets; it demonstrates the mechanics of autoregressive decoding. Its labels do not require useful dependence on previous target symbols. It therefore does not establish an autoregressive advantage, real handwriting generalization or historical OCR performance.

Keep three comparisons honest:

- Compare an untrained or simple baseline with the trained model. A nearest-known-template classifier is a strong and appropriate baseline for this data.
- Compare greedy and beam width **3** on the **same 16 cases** in the worked demonstration. Report both the scores and the sample count. Beam may tie greedy or fail to improve task metrics.
- Define exact match and character/token error rate. For equal-length references, macro and corpus aggregation may coincide; declare the convention rather than assume it. Internal generated BOS or PAD before EOS counts as an error; it must not silently disappear during cleanup.

If the observed predictions contain no errors, report zero observed errors with the sample size. Do not invent examples. An optional extension can predeclare harder conditions: train with independent binary pixel-flip probability 0.06 and evaluate a frozen grid such as 0.06, 0.12 and 0.20, with the same template rules. This is a pixel-flip probability, not Gaussian noise standard deviation. Use a larger frozen set and several training seeds when making a comparison. Keep synthetic-task conclusions separate from claims about real documents.

## Stage 5 — A narrow Bachelor research question

Move to real data only with the supervising lecturer's agreement, appropriate rights and a feasible annotation plan. Choose one question small enough to answer. For example: at a fixed annotation budget, does a chosen confidence filter improve held-out transcription quality over a simple baseline?

A useful proposal names the input, token unit, target, baseline, split unit, metric, independent annotation checks and decision rule. Separate source documents across train/development/test where document identity could leak. Check duplicates and available pretraining exposure. Use the development set to select methods and calibration; freeze the test before choosing the winner. Compare methods on the same cases and inspect actual errors. Quantify uncertainty at the appropriate sample unit. A null improvement is a legitimate result.

The deliverable is a working component plus an understandable report: why the problem matters, what information the model receives, why the method might help, the controlled comparison, observed outputs, limitations and one next hypothesis. A complex architecture is not the goal by itself.

## Teacher maintenance and feedback

Keep the worked teacher version, learner stubs, behavioral tests and assessment rubric versioned together. Verify the machine/kernel and offline fallback before class. During the tutorial, ask for a prediction, run a small case, diagnose the mismatch and retry a changed case. Collect the student's explanation before showing the key. Bring observed student difficulties to the advising lecturer when revising the next tutorial.

No file in this package can certify comprehension. The human evidence is the learner's unscripted explanation, independently completed code and transfer to a fresh example. Record those observations during the actual session.
