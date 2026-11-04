# Trial lecture rehearsal script

**Introduction to Sequence Generation with Transformers**  

The lecture source is [trial_lecture.json](../content/trial_lecture.json). Each section below contains the exact core presenter notes and its time window. The 30-minute schedule is a rehearsal target; a human timed delivery remains necessary. This document does not claim that delivery or student understanding has been observed.

## Before you rehearse

Use the canonical lecture deck/PDF produced from this source and the worked notebooks under `../notebooks/`. Start with `01_Core_Attention_Worked.ipynb`, then `02_Training_and_Generation_Worked.ipynb`. These are the worked instructor demonstrations with saved outputs. `03_Optional_Systems_Worked.ipynb` and `04_Optional_Image_to_Sequence_Worked.ipynb` are optional follow-up material. Do not add their training or benchmarking to the lecture clock.

Speak at roughly 110–120 words per minute; leave the stated pauses and calculation time. This script has about 3,000 spoken words. Use everyday terms before new terms: earlier answer before prefix; hide future positions before causal mask; correct earlier tokens before teacher forcing. The English level does not imply prior knowledge of matrices, so keep the opening diagnostic.

Open the PDF offline before starting. Keep this script, the two-key numeric calculation, the 4×4 mask and the shifted-target table available in print. The lecture does not require a live internet connection, package installation or model training. Show prepared notebook outputs only if they fit inside the allocated example time. If a demo fails to open, continue with the static numbers below.

## The clock

| Window | Slide | Purpose |
|---|---|---|
| 00:00–02:00 | 1. How can a model generate an ordered answer? | Sequence generation means making ordered choices and learning when to stop. |
| 02:00–04:00 | 2. From text to numbers: token → ID → embedding | Token IDs are lookup addresses; embeddings provide the model's learned input vectors. |
| 04:00–06:00 | 3. A sequence is a chain of next-token decisions | Next-token probabilities combine to score a complete sequence. |
| 06:00–08:00 | 4. Where do the next-token scores come from? | The source, the output prefix and the vocabulary distribution have different jobs. |
| 08:00–11:00 | 5. Attention: compare, normalize, mix | Attention weights select how much of each whole value vector to combine. |
| 11:00–13:00 | 6. Shapes tell us what attention is doing | A score row belongs to one query; its columns are the available keys. |
| 13:00–16:00 | 7. A causal mask blocks future input positions | The causal rule limits available information even when the complete training example is stored. |
| 16:00–19:00 | 8. Training gets correct prefixes; generation gets its own | Target shifting, visibility masking and the generated-prefix loop solve different parts of the problem. |
| 19:00–21:00 | 9. Order needs an explicit explanation | Specify both the position representation and the visibility rule when reasoning about order. |
| 21:00–23:00 | 10. Greedy can miss the best complete sequence | Decoding changes which path is selected; it does not improve the underlying probability model automatically. |
| 23:00–24:00 | 11. Use the same ideas for an image-to-symbol project | A working toy system teaches mechanisms; research claims require an appropriate task and evidence. |
| 24:00–27:00 | 12. Can you diagnose an answer that looks too good? | Test what information the prediction can use and which target it is asked to learn. |
| 27:00–29:00 | 13. From this lesson to your own working project | Progress from explanation, to verified code, to a narrow question with controlled evidence. |
| 29:00–30:00 | 14. Exit ticket: explain the information available | Explain the mechanism, show the computation and check the available information. |

Keep the numerical attention example, mask distinction, shift and exit ticket. If you fall behind, shorten the architecture taxonomy on slide 4, position-method discussion on slide 9 and optional project detail on slide 13. Do not add sampling variants to slide 10. Finish at 30 minutes and begin the separate Q&A afterwards.

## Spoken script

### Slide 1 — How can a model generate an ordered answer?

**00:00–02:00 · A problem worth learning** · 2 minute(s)

Good morning. Imagine that a program receives an image containing x plus one. It must produce a sequence of symbols in the right order. A useful answer must also stop. The same pattern appears in translation, code completion and speech transcription. Today we will study how a Transformer can make the next decision using the input and the answer so far.

By the end, you should be able to do three things: calculate one attention result, explain why a model must hide future answers during training, and describe what changes when the model generates its own answer. These ideas help us write correct code and question a result that looks too good. We will study the mechanism rather than train a large model in class.

You need the idea of a probability, a short vector product and matrix rows and columns. A vector is just an ordered list of numbers here. Quick check: if two queries each compare with three keys, how many comparison scores do we get? [Pause five seconds.] Six: two rows and three columns. If you said five, count three comparisons for the first query and three for the second. Keep that picture; we will use it again. At the end, I will ask what information training has that generation does not.

**Leave visible:** Sequence generation means making ordered choices and learning when to stop.

### Slide 2 — From text to numbers: token → ID → embedding

**02:00–04:00 · Define the vocabulary first** · 2 minute(s)

Before attention, we need to turn a sequence into numbers. A tokenizer divides the input into items called tokens. For this small example, I, love and AI are whole tokens. In real systems, a token may be only part of a word, one character, or a structural symbol. We choose the vocabulary before mapping tokens to IDs.

An ID is an index into a table. ID one for love does not make it more important than ID zero for I. It selects a row containing a vector. That row is called an embedding and its values can be learned during training. These IDs match the core lab: I zero, love one, AI two, BOS four, EOS five and PAD six. The small embedding vectors are hand-chosen examples so that we can follow the mechanism. They are not experimental results.

BOS marks the beginning and EOS tells generation to stop. PAD is used when shorter examples share a batch with longer ones; its visibility and loss treatment need explicit handling. Ask yourself: can we replace an embedding vector with the single integer ID and keep the same meaning? [Pause.] No. The integer is a lookup address; the learned vector is the representation. In a later project, vocabulary choice affects whether the model can express the symbols we care about, including symbols in code or document transcription.

**Leave visible:** Token IDs are lookup addresses; embeddings provide the model's learned input vectors.

### Slide 3 — A sequence is a chain of next-token decisions

**04:00–06:00 · Conditional probability** · 2 minute(s)

Let x mean the source, such as a sentence or an image, and y mean the complete answer. At each step the model estimates a probability distribution for the next token, given x and the earlier output tokens. The vertical bar means given. The prefix is the part of the answer already available.

Follow the table. Starting with BOS, we predict I. Then I is in the prefix and we predict love. We continue until EOS. For these invented probabilities, the probability of this complete output is point eight times point six times point five times point nine, which is point two one six. We multiply conditional probabilities; we do not add them. In software we usually add log probabilities for numerical stability.

A model produces probabilities, not a guarantee of a correct sentence. Ask: if the first token has the largest local probability, must the complete sequence have the largest probability? [Pause.] No. A later continuation can be much less likely. We will calculate a small counterexample later. This factorisation is useful because outputs can have different lengths, but choosing a good complete output still requires a decoding rule. The probability of the whole output and the quality measured by a task are also different things.

**Leave visible:** Next-token probabilities combine to score a complete sequence.

### Slide 4 — Where do the next-token scores come from?

**06:00–08:00 · A conditional encoder–decoder example** · 2 minute(s)

This is an encoder–decoder Transformer used for conditional generation. The encoder reads the source and produces memory vectors. The decoder receives the output prefix. Causal self-attention lets it combine permitted prefix information. Cross-attention lets it use source memory: the decoder supplies queries, while encoder memory supplies keys and values.

Attention is one part of a Transformer block. Feed-forward layers, residual connections and normalization also help transform the representations. We will focus on attention and information visibility today. Several attention heads use separate learned projections; their roles are learned, not assigned labels such as grammar head.

After the decoder, a learned projection gives one real score for each vocabulary token. These scores are called logits. Softmax converts them to a next-token probability distribution. Do not confuse this vocabulary softmax with the attention softmax we will calculate next. One chooses weights over information sources; the other describes possible output tokens.

Some text generators use a causal decoder without a separate encoder. That is a useful variant, but our conditional example makes the source and output paths easy to see. Check: in image transcription, should source information come only from the previously generated words? [Pause.] No; the source encoder provides image features as well. That is why cross-attention is useful in this example.

**Leave visible:** The source, the output prefix and the vocabulary distribution have different jobs.

### Slide 5 — Attention: compare, normalize, mix

**08:00–11:00 · One complete numerical calculation** · 3 minute(s)

We will calculate one query and two information sources. We are not choosing the next word yet. Q is a query, K contains keys to compare against, and V contains values to mix. In self-attention, these can be learned projections of the same input: Q equals X times W-Q, and similarly for K and V. Our small numbers represent outputs of those projections.

The query is one, zero. Its dot product with the first key, one, zero, is one. Its dot product with the second key, zero, one, is zero. Each key has two coordinates, so divide both scores by the square root of two. We obtain about point seven zero seven one and zero.

Softmax takes exponentials and divides by their sum. The first weight is exp of point seven zero seven one divided by exp of point seven zero seven one plus one. It is about point six six nine eight. The second is point three three zero two. Check that they sum to one. [Give students ten seconds to check the sum.]

Now multiply each whole value vector by its weight and add. The first coordinate is twice point six six nine eight. The second is four times point three three zero two. The result is about one point three three nine five, one point three two one zero. These two output coordinates are not probabilities. The attention weights were probabilities over source positions; the output is a mixed information vector.

Question: why keep V separate from K? [Pause.] K helps decide relevance, while V carries what we retrieve. If you treated the output coordinates as next-word probabilities, return to the two value vectors and follow the multiplication. The vocabulary projection still comes later.

**Leave visible:** Attention weights select how much of each whole value vector to combine.

### Slide 6 — Shapes tell us what attention is doing

**11:00–13:00 · Trace the axes before coding** · 2 minute(s)

Return to two queries and three keys. There is one score for every query–key pair. In this larger example, B is batch, H is heads, T is query positions and S is source positions. We deliberately choose different numbers for every axis. Q has shape two, three, five, four; K has two, three, seven, four. Transposing K's last two axes gives a score tensor with five query positions and seven key positions.

For each query, normalize across its seven keys. In code that is softmax with dim minus one. Multiplying those weights by V gives shape two, three, five, six. Ask: why does the seven disappear? [Pause.] We sum over the source positions, keeping one mixture for each query. A square example can hide a wrong transpose, so use rectangular cases when testing.

Why divide by square root of d-k? Under simple assumptions of roughly independent, centered coordinates with similar variance, dot-product variance grows with the number of coordinates. Scaling helps prevent softmax from becoming unnecessarily concentrated. It is an intuition and a practical design choice, not a claim that every unscaled model always fails. In self-attention, T and S often match. In cross-attention, the source and output lengths can differ.

**Leave visible:** A score row belongs to one query; its columns are the available keys.

### Slide 7 — A causal mask blocks future input positions

**13:00–16:00 · Scores before softmax; weights after it** · 3 minute(s)

Imagine that we train the model using a complete known sentence. All its tokens are stored in memory. If an earlier prediction can look at later input positions, the correct answer may already be visible. We need a rule controlling what each query can read.

This triangular table is an additive causal mask. Rows are query positions and columns are key positions. Zero leaves a score unchanged. Negative infinity blocks the score before softmax. A row can read its own input position and earlier ones, because its prediction is for the following token. At position one, containing I, the label will be love. Input position two contains love, so letting position one read position two would leak that answer.

Let us connect this to our two-key calculation. Suppose the second key is future information. The additive mask is zero, negative infinity. After adding it, scores are point seven zero seven one, negative infinity. After softmax, weights are one, zero. The output becomes two, zero. Notice that the mask values and the attention weights are different objects at different stages. Never label one cell as both zero and negative infinity.

Question: may the query at input I inspect the input AI? [Pause five seconds.] No. Both love and AI lie in its future. If someone says yes because all training tokens are known, distinguish storage from permission: the dataset can contain a token that this prediction must not inspect.

A padding mask handles a different problem: unused positions. Also, an entirely blocked row needs a defined policy; ordinary softmax of only negative infinities is undefined. Our valid causal rows always have at least the diagonal available.

**Leave visible:** The causal rule limits available information even when the complete training example is stored.

### Slide 8 — Training gets correct prefixes; generation gets its own

**16:00–19:00 · Shifted targets and teacher forcing** · 3 minute(s)

Put the complete target in a row: I, love, AI, EOS. The decoder input is BOS, I, love, AI. At the input I, what should the model predict? [Pause.] Love. At input AI it should predict EOS. This alignment is called shifting the targets. It is separate from masking: shifting defines what to predict, while masking defines which input information is allowed.

Training with the correct earlier tokens is called teacher forcing. The dataset already has those tokens, so we can compute predictions for the different target positions together in a forward pass, while the mask prevents future access. The model produces logits over the vocabulary at each position. Cross-entropy penalizes low probability for the correct next token. We include the EOS target and explicitly ignore padding labels when padding is used.

During generation, there is no known full answer. Start with BOS and source x, get a next-token distribution, choose a token, append it, and run the next step. Stop when EOS appears or a maximum length is reached. The prefix may now contain a mistake from the model, and that can change later predictions.

Question: can the model use the correct next target during generation to repair a wrong choice? [Pause.] No; that would be using the answer we are trying to predict. This is why an excellent loss on teacher-forced training is insufficient evidence for good generation. We must evaluate actual generated sequences on held-out cases. Parallel training also does not make attention free: it still computes many query–key comparisons. Generation remains sequential across output steps; caching is an optional later optimisation.

**Leave visible:** Target shifting, visibility masking and the generated-prefix loop solve different parts of the problem.

### Slide 9 — Order needs an explicit explanation

**19:00–21:00 · Position information without a misleading slogan** · 2 minute(s)

Attention compares vectors, but a language task also needs order. Dog bites person and person bites dog contain the same kinds of words and have different meanings. A common Transformer design adds a positional vector to each token embedding. Other designs apply position-dependent transformations inside attention. We will leave their formulas for a later lesson.

There is an important qualification. Unmasked attention without position-dependent inputs treats a consistent permutation of the input as a corresponding permutation of its outputs. But a causal decoder also has a triangular visibility pattern: earlier and later positions have different permitted histories. Therefore it is too strong to say that removing positional embeddings makes every causal Transformer completely unable to use order. The mask already introduces a direction and a boundary. Explicit positional methods still provide useful, direct position information.

Ask: if we want to test whether a positional method helps, can we simply compare two unrelated training runs? [Pause.] We need a controlled comparison with the same task and evaluation policy, and we should repeat seeds if practical. That is an optional research extension. It is not a required experiment in today's core lab. For today, explain where position information enters the model and avoid treating a causal mask as a replacement for every positional design choice.

**Leave visible:** Specify both the position representation and the visibility rule when reasoning about order.

### Slide 10 — Greedy can miss the best complete sequence

**21:00–23:00 · A two-symbol probability tree** · 2 minute(s)

We will generate exactly two symbols in this small probability tree. We omit EOS and length penalties only to isolate the search decision. The first choice is A with probability point six or B with point four. Greedy selects A. After A, X and Y each have probability point five; our stated tie rule picks X. The complete AX probability is point three.

After B, X has probability one, so BX has probability point four. Beam search with width three keeps several promising prefixes instead of committing to one. Here it keeps both A and B at the first step and discovers BX. At the next step the three nonzero candidates are BX, AX and AY.

Question: did beam change the model's probabilities? [Pause.] No. It searched differently through the same probabilities. A finite beam can still discard a prefix that would later be useful, so it is approximate search in general. A sequence with a higher model probability may also be wrong for the task. We must compare actual exact match or another stated metric on the same held-out examples.

Our optional glyph lab uses beam width three, matching this lecture. Sampling methods can produce different outputs, but temperature, top-k and top-p are optional follow-up topics; we do not need them to explain this example.

**Leave visible:** Decoding changes which path is selected; it does not improve the underlying probability model automatically.

### Slide 11 — Use the same ideas for an image-to-symbol project

**23:00–24:00 · A small application with clear limits** · 1 minute(s)

Now transfer the mechanism. An image encoder converts a small glyph image into source features. The decoder uses those features and its prefix to generate symbols. We keep the same ideas: embeddings, cross-attention, a causal rule, shifted labels and an actual generation loop.

Our optional lab uses four synthetic known glyph templates. It is a controlled way to connect the components. A simple nearest-template baseline may already solve the task well. That is useful evidence about the toy data, not a failure of the baseline. It also means we cannot claim that the Transformer is necessary, that beam must improve accuracy, or that this establishes real handwritten or historical-document recognition. To study those questions, we need appropriate real data and a carefully held-out evaluation.

**Leave visible:** A working toy system teaches mechanisms; research claims require an appropriate task and evidence.

### Slide 12 — Can you diagnose an answer that looks too good?

**24:00–27:00 · Guided prediction, explanation and feedback** · 3 minute(s)

Let us use the ideas before we finish. Case A: at input I, the model can inspect the future input love. Why can training loss become misleadingly small? [Wait ten seconds.] Love is the target for that position, so the answer has leaked through the input. A small loss alone does not prove a useful generator. If you say the target was shifted, remember that shifting cannot stop the model reading a future input. We need both the correct shift and a causal mask.

Case B: input and target are both BOS, I, love, AI. What task have we accidentally created? [Wait ten seconds.] We may be rewarding the model for copying the current token, rather than predicting the next one. Write a single pair: input I should predict love. That is an easy way to check the alignment.

Case C: we change only future tokens and rerun the same causal decoder. Which outputs should stay the same? [Wait ten seconds.] Earlier-position outputs should remain unchanged, within the numerical tolerance of the chosen implementation. This is a behavioral test, stronger than merely looking at a triangular picture. If outputs change, check the mask orientation and how it is applied.

Now explain one case to a partner in one sentence, or tell me directly if we are a small group. [Allow twenty seconds.] I am checking your explanation, not whether your notebook has a green checkmark. A notebook may run while testing an instructor function rather than your function, or while TODOs contain only comments. The core lab therefore asks for your reasoning as well as executed code and observed outputs.

**Leave visible:** Test what information the prediction can use and which target it is asked to learn.

### Slide 13 — From this lesson to your own working project

**27:00–29:00 · Two core labs; two optional extensions** · 2 minute(s)

After class, begin with the two core labs. In T1, work through the attention numbers, a rectangular shape example, a mask, shifted labels and the greedy counterexample. Write why each step is useful. In T2, implement attention, a mask, target shifting and padding-aware cross-entropy, then inspect visible outputs and test the function you actually wrote. The T1 workbook check cells use the same implementation; return to them after completing those functions. A blank learner file should not be mistaken for a completed solution.

The instructor demonstration notebooks contain worked examples and saved outputs for rehearsal. Use the separate learner tasks when you want to assess yourself. First predict the answer, then run, compare, explain a mismatch and try a changed case. Copying a worked output is not evidence of understanding.

Two extensions are optional. T3 studies caching and systems measurements after correctness checks. T4 connects an image encoder to symbol generation and compares greedy with beam width three on the same cases. A position-encoding ablation is a possible later project, not a promised core task.

For a Bachelor project, choose one narrow question with an advising lecturer, obtain appropriate data, establish a simple baseline and freeze a test set before choosing methods. Your report should include actual errors, limitations and a next hypothesis. A measured absence of improvement can still be a useful result when the comparison is fair.

**Leave visible:** Progress from explanation, to verified code, to a narrow question with controlled evidence.

### Slide 14 — Exit ticket: explain the information available

**29:00–30:00 · Check the three learning goals** · 1 minute(s)

Please answer the first question in one sentence: what does training supply that generation does not? [Pause ten seconds and take one answer.] Training supplies the correct earlier target tokens. During generation, the model must build that prefix from its own choices.

Two quick checks: mask values are added to scores before softmax; attention weights come after softmax. At input I in our shifted example, the next target is love. These are practical checks you can use when writing or reviewing a generator.

You can now connect a sequence probability, one attention calculation and the training–generation distinction. In the core labs, test that explanation with your own code. Thank you. We finish the lecture here at thirty minutes. I am ready for the separate questions.

**Leave visible:** Explain the mechanism, show the computation and check the available information.

## Static calculation card

These values are fully specified teaching examples, not measured model quality:

```text
q = [1, 0]
K = [[1, 0], [0, 1]]
V = [[2, 0], [0, 4]]
raw scores       = [1, 0]
scaled scores    = [0.70710678, 0]
softmax weights  = [0.66976155, 0.33023845]
weighted output  = [1.33952310, 1.32095380]

If key 2 is blocked:
additive mask    = [0, -infinity]       BEFORE softmax
masked scores    = [0.70710678, -infinity]
attention weights= [1, 0]              AFTER softmax
weighted output  = [2, 0]
```

```text
position:          0      1      2      3
decoder input:    BOS     I     love    AI
next-token label:  I     love    AI    EOS

Additive causal mask BEFORE softmax:
[ 0, -inf, -inf, -inf ]
[ 0,    0, -inf, -inf ]
[ 0,    0,    0, -inf ]
[ 0,    0,    0,    0 ]

At input position 1, I predicts love.
Input position 2 already contains love, so it must be hidden from position 1.
```

```text
Distinct dimensions: B=2,H=3,T=5,S=7,d_k=4,d_v=6
Q:       [2,3,5,4]
K:       [2,3,7,4]
V:       [2,3,7,6]
scores:  [2,3,5,7]
output:  [2,3,5,6]
softmax over the last axis: 7 keys for each query.
```

```text
Two-symbol tree; ties choose X before Y; beam width=3; no length penalty:
p(A)=0.6, p(B)=0.4
p(X|A)=0.5, p(Y|A)=0.5  -> AX=.30, AY=.30
p(X|B)=1.0, p(Y|B)=0.0  -> BX=.40, BY=.00
Greedy AX=.30. Beam-3 BX=.40. Equal output length is fixed at two here.
```

## Questions to prepare for the separate 15-minute Q&A

| Likely question | Concise defensible answer |
|---|---|
| Why separate Q, K and V? | Q/K compare relevance in a learned comparison space. V supplies the information to aggregate. Their parameters can learn different transformations. |
| What changes when dimensions grow? | Under simple variance assumptions dot products grow in spread; scaling by √d_k moderates this before softmax. Real activation distributions need not satisfy the assumptions exactly. |
| Is attention the next-token distribution? | No. Attention weights range over key positions. The vocabulary projection and its softmax produce next-token probabilities. |
| Why both mask and shift? | Shift selects the next-token label. Mask limits which input positions may contribute to its prediction. |
| Why allow the diagonal of the causal mask? | Input at position t is the previous token relative to the label at t. The current input is already known and may be used to predict the next token. |
| What if every key in a row is masked? | Ordinary softmax over all −∞ is undefined. Our exercise API chooses zero output/weights and tests gradients; an explicit rejection policy can also be valid. |
| Is ignoring PAD in CE enough? | It removes padded targets from loss. It does not prevent attention to padding keys; those require an attention mask. The optional fixed-length glyph model is not evidence of arbitrary variable-length support. |
| Can a causal model use order without position embeddings? | The fixed causal visibility pattern already provides order-related asymmetry; explicit positional methods add direct information. An unmasked no-position layer has a different symmetry. |
| Why do we call teacher-forced training parallel? | Different output positions can be computed together with the correct prefix tokens and mask. It still performs substantial attention work; generation must select successive output tokens. |
| Does a cache make the model more accurate? | A correct cache should reproduce the uncached computation within tolerance while reusing previous keys/values. It is an implementation optimisation; measure runtime rather than promising a gain. |
| Does a wider beam always help? | No. It can improve the model score found, but finite search and model/task mismatch remain. Compare declared metrics on exactly the same examples. |
| Why a trivial template baseline? | It reveals what the toy task actually requires. If known-template matching solves it, high Transformer accuracy does not establish an autoregressive advantage or real OCR validity. |
| What is the first research step? | Agree a narrow question with the advising lecturer, define legal data and splits, establish a baseline, freeze the test and record errors and limitations. |
| Can this lecture prove you teach effectively? | It provides goals, worked examples, checks and feedback. A timed rehearsal and observed student explanations provide evidence of delivery and comprehension. |

## Rehearsal record — complete after delivery

Record actual start/end times for slides 5, 7, 8, 12 and 14. Ask a listener to explain a fresh rectangular shape and an unseen mask/shift example. Write the listener's answer and the feedback you gave. Record what you shortened and whether the lecture ended at 30 minutes. Leave this record unfilled until a human rehearsal occurs.

Verified primary references: [Attention Is All You Need](https://arxiv.org/html/1706.03762v7) and [The Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/). The presentation's toy numbers and calculation cards are derived examples; they are not publication performance claims.
