# Technical explanation and research discussion prompts

Use these prompts to rehearse clear reasoning. They are worked technical explanations and
generic professional questions, not a record of anyone's employment, qualifications or personal
contribution. Give factual personal answers yourself when appropriate.

## Teaching and implementation

### Why should a student learn sequence generation?

Many tasks require an ordered answer of variable length: translation, code generation, speech
transcription and document recognition. The transferable skill is specifying the input, token
unit, target sequence, loss, stopping rule and evaluation metric. A working generator also makes
information leakage and evaluation mistakes easier to understand concretely.

### What prerequisites should you check?

Check a short dot product, matrix multiplication shapes, conditional probability and a two-score
softmax. For code, add basic Python slicing and tensor indexing. English proficiency does not
establish mathematical readiness. Reduce a difficult question to one query and two keys before
adding batch and head axes.

### Explain Q, K and V without assigning fixed meanings to heads.

They are learned projections. Q/K comparisons determine attention weights, and those weights
mix V. In self-attention they can come from the same hidden input; in cross-attention, decoder
queries read encoder keys/values. Heads learn separate transformations rather than receiving
fixed semantic job titles.

### Calculate one attention row.

For `q=[1,0]`, `K=[[1,0],[0,1]]`, `V=[[2,0],[0,4]]`, raw scores are `[1,0]`.
Divide by `sqrt(2)` and apply softmax to get approximately `[0.6698,0.3302]`.
The value mixture is approximately `[1.3395,1.3210]`. These output coordinates are not
vocabulary probabilities. If the second key is blocked, its score becomes negative infinity,
the weights become `[1,0]` and the output becomes `[2,0]`.

For a fresh check, change only a value vector and explain why the weights remain the same.

### Explain the scale and shapes.

Under simple centered, independent-coordinate assumptions, dot-product variance grows with the
key width. Dividing by its square root moderates score scale before softmax; it is not a proof
that every unscaled model fails.

For Q `[B,H,T,d_k]`, K `[B,H,S,d_k]` and V `[B,H,S,d_v]`, scores have shape
`[B,H,T,S]`, and output has shape `[B,H,T,d_v]`. Normalize over the S keys for each query.
Use distinct dimensions to expose an incorrect transpose.

### Why both a causal mask and shifted targets?

For target `a b EOS`, decoder inputs are `BOS a b`, with labels `a b EOS`.
Shifting selects the next-token label. The mask controls which input positions may contribute.
At input `BOS`, a future input already contains label `a`; unmasked training could leak it.
Allowing the diagonal is valid because the current input is already known when predicting its
next token.

### What sums to one, and what happens to padding?

Valid attention-weight rows sum to one over keys. The additive mask does not. Ordinary softmax
of a fully blocked row is undefined; the exercise API explicitly chooses zero weights/output.
Ignoring PAD targets in cross-entropy does not block PAD keys in attention. Define both policies,
including all-ignored loss behavior, and test them.

### Why is teacher-forced training different from generation?

Training supplies correct earlier target tokens and can process positions together while masking
future inputs. Generation must append its own predicted tokens and repeat. Earlier mistakes can
change later predictions. Low teacher-forced loss alone therefore does not establish useful
free-running generation.

### How would you debug tiny loss and poor outputs?

Start with a tiny batch. Inspect inputs versus labels, mask orientation, attention softmax axis,
PAD loss treatment, BOS/EOS handling, evaluation mode and the generated prefix. Change only
future inputs and check that earlier causal outputs remain unchanged. A suspicious loss suggests
hypotheses; it does not identify the cause by itself.

### Does beam search guarantee a better answer?

No. In the fixed two-symbol tree, greedy chooses A with probability `.6`, then X with `.5`,
scoring `.30`; B followed by X scores `.4 × 1 = .40`. Beam width 3 finds BX in that example.
A finite beam remains approximate, and higher model probability need not improve task accuracy.
Compare methods on the same held-out cases with the same stopping and length conventions.

### How should special tokens affect evaluation?

Strip only the initial BOS prefix when that is the declared convention and stop at the first EOS.
An internal generated BOS or inappropriate PAD should not silently disappear. CER divides edit
distance by reference length, so insertions can make it exceed one. Declare empty-reference and
corpus-versus-sequence aggregation policies.

### What does the synthetic glyph lab establish?

It connects an image encoder, cross-attention, shifted training and an actual generation loop.
Four known templates with fixed-length outputs may be solved well by template matching and do
not require useful target-history dependence. Report actual errors or none observed, with the
sample count. Real handwriting or historical-document claims need an appropriate separate dataset.

### How would you help a confused learner?

Ask where the reasoning first became unclear. Reduce the example, ask for a prediction, run or
calculate it, and use the mismatch to choose feedback. Finish with a fresh example the learner
solves independently. Repeating a formula or copying saved output is insufficient evidence.

## Research reasoning

### What makes an experimental comparison credible?

Name a narrow question, a simple baseline, a primary metric and the minimum useful difference.
Hold the candidate data, splits, initialization policy and training budget fixed. Choose methods
on development data, freeze the test, and compare paired cases. Separate exploratory diagnoses
from the prespecified primary result.

### How could a second confidence signal fail to help?

Signals derived from the same model may share errors or supply redundant information. Compare
the combined method against the stronger single-signal baseline rather than only an unweighted
baseline. Report uncertainty; an inconclusive interval is not evidence of equivalence.

### How do you control leakage and label quality?

Group related source documents and duplicates, inspect inherited model exposure, and reserve a
held-out evaluation set. Independently review labels, including missed or rejected cases. Fit
thresholds and calibration on development data. A renamed split cannot undo prior exposure.

### How do you measure review benefit?

Measure inspection, correction, re-review and adjudication effort alongside independently assessed
output quality. Agree the acceptable error margin before testing. Faster work at substantially
worse quality does not meet the same criterion. Estimate staffing from a measured pilot before
promising scale.

### What should you say about published and personal work?

Identify the public source, metric, evaluation unit and whether the result belongs to a group.
Coauthorship does not establish ownership of every component. Describe a personal responsibility
only when it is factual; distinguish implementation, experiment design, data preparation,
evaluation and writing. Keep private evidence and administrative records outside the repository.

### What if the proposed method does not improve the metric?

Verify the data path and implementation, then report the planned comparison with uncertainty.
A precise null result can rule out a useful gain; a wide interval may be inconclusive. Diagnose
actual failures without replacing the primary result with the most favorable later analysis.

## Generic professional discussion

Prepare truthful answers to these questions without filling missing history with invented claims:

- Which concepts can you explain and demonstrate independently today?
- How would you coordinate tutorials, assessment and student projects with the advising lecturer?
- How would you balance preparation, research, student support and service deadlines?
- What real example demonstrates your planning, collaboration or mentoring?
- What resources, project ownership and expected outcomes need agreement before work begins?
- How would you acknowledge and correct a mistake or failed demonstration?

For rehearsal, explain one changed attention example, repair one broken mask/shift case and defend
one research comparison without reading. Record actual timing and listener feedback privately;
these outcomes have not been established by generating this guide.

Public technical references: [Attention Is All You Need](https://arxiv.org/abs/1706.03762) and
[The Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/).
