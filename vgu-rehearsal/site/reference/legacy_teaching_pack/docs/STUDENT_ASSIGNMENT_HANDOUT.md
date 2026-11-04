# VGU — Introduction to Sequence Generation with Transformers
## Student assignment booklet • Four-tier progression

**Independent proposed teaching material (not an official VGU assignment).** English-language handout, designed for Bachelor computer-science students. Mathematically explicit questions, fixed tests, expected shapes and grading criteria; instructor solutions are distributed separately.

**Prerequisites:** vectors, matrix multiplication, elementary conditional probability, `torch.Tensor`. **Setup:** Python 3.10+, PyTorch 2.1+, NumPy, pytest; CPU suffices. Open the linked slides in `LECTURE_AND_SOURCE_LINKS.md` as you progress.

## Notation and definitions

| Symbol | Meaning | Example |
|---|---|---|
| $B$ | batch size / independent samples | $B=2$ |
| $S$ | source/input sequence length | $S=5$ |
| $T$ | target/output sequence length | $T=4$ |
| $d_{model}$ | hidden model dimensionality | $d_{model}=16$ |
| $H_q,H_{kv}$ | query heads / key-value heads | $H_q=4,H_{kv}=2$ |
| $d_h$ | per-head query/key/value dimension | $d_h=d_{model}/H_q=4$ |
| $X$ | input embeddings $\in\mathbb{R}^{B\times T\times d_{model}}$ | $[2,4,16]$ |
| $Q,K,V$ | query, key and value projections | $[B,H,T,d_h]$ |
| $A$ | row-normalized attention matrix | $[B,H,T,T]$ |
| $M$ | additive attention mask, $0$ allowed and $-\infty$ forbidden | $[T,T]$ |
| $z_t$ | unnormalized vocabulary logits | $[|\mathcal V|]$ |
| $\mathcal{V}$ | vocabulary of target symbols | 7 symbols in Tier 4 |
| $\mathcal{L}_{CE}$ | categorical cross-entropy | scalar |
| $\mathrm{CER}$ | edit distance divided by reference length | $0,1/3,2$ possible |
| $\mathrm{EM}$ | fraction of entire sequences exactly correct | $[0,1]$ |

**Core equations:**

$$p_\theta(y_{1:T}\mid x)=\prod_{t=1}^T p_\theta(y_t\mid y_{<t},x).$$

$$\mathrm{Attention}(Q,K,V;M)=\mathrm{softmax}_{\mathrm{keys}}\!\left(\frac{QK^\top}{\sqrt{d_h}}+M\right)V.$$

$$\mathcal{L}_{CE}=-\frac{1}{N}\sum_{n=1}^N\log p_\theta(y_n\mid \mathrm{context}_n).$$

## Tier 1 — Hand calculation and conceptual rigor (60 minutes, 25 points)

### T1.A: Scaled attention by hand (6 points)

Given a **single query** $q=(1,0)$, keys $k_1=(1,0)$, $k_2=(0,1)$ and values $v_1=(2,0)$, $v_2=(0,4)$:

1. Write shapes for $Q,K,V,QK^\top$ and the output.
2. Calculate both scaled scores $s_j=q^\top k_j/\sqrt{2}$.
3. Apply softmax and calculate the full output vector, including numerical values to three decimals.
4. Describe what changes if the scale $1/\sqrt{d_h}$ is removed. Do **not** claim it always leads to gradient collapse.

Read: [MIT Transformer chapter](https://introml.mit.edu/notes/transformers.html) and [NUS CS5242 Lecture 7](https://storage.googleapis.com/xavierbresson/lectures/CS5242/lecture07_attention_neural_networks.pdf).

### T1.B: Tensor dimensions (4 points)

With $B=2$, $T=4$, $d_{model}=16$, $H=4$, compute $d_h$ and the shapes of $Q$, $K$, $V$, $QK^\top$, $A V$, head concatenation, final projection. What changes for cross-attention with $T=4$ target queries and $S=5$ source keys?

### T1.C: Causal masking and shifted labels (5 points)

1. Construct the $4\times 4$ additive causal mask $M_{ij}=0$ when $j\le i$, $-\infty$ otherwise.
2. Show the **zero** entries of the post-softmax attention matrix. Does every row still sum to one?
3. With sequence `[BOS, I, love, AI, EOS]`, list decoder inputs and next-token labels. Clarify whether future-token leakage is prevented by shifting, masking, or both.

### T1.D: Softmax, loss, perplexity (5 points)

Given logits $z=(\ln 2,0,0)$ and target token index $2$ (zero-based), compute $\mathrm{softmax}(z)$, $-\ln p(y=2)$, and perplexity $\exp(\mathcal L)$. Explain why perplexity depends on how tokens are defined.

### T1.E: Greedy-decoding counterexample (5 points)

At the first position, $p(A)=0.6$, $p(B)=0.4$. After $A$, probabilities for two possible second tokens are $(0.5,0.5)$; after $B$, exactly one valid next token has probability $1$. Show that greedy first-step choice does not maximize the joint probability of the final two-token sequence. Would beam width $2$ suffice in this tiny case? State one caveat.

## Tier 2 — Implement and debug causal generation (2 hours, 25 points)

**Files:** `src/vgu_transformers.py`, `tests/test_vgu.py`, Tier2 Student Notebook. Related refined lecture slides **5–9**.

### T2.A: Scaled dot-product attention (6 points)
Implement `scaled_dot_product_manual(q,k,v,mask)` for batched heads. Use shape assertions. For $Q:[2,4,4,4]$ and $K:[2,4,4,4]$, return weights `[2,4,4,4]` and outputs `[2,4,4,4]`.

### T2.B: Causal and padding masks (6 points)
Implement additive triangular mask. In a batch, an optional source padding mask may also mask **key positions**; provide a proof that fully masked query rows would yield undefined softmax and explain an avoidance strategy. Check every valid row sums to 1 and all future positions receive exactly zero weights.

### T2.C: Teacher forcing and cross-entropy (5 points)
Take `[BOS,0,1,2,EOS]`, create input and label arrays by shifting once. For logits `[B,T,V]`, write a function to compute cross-entropy over flattened `B*T` valid prediction locations. Explain ignore-index for padding.

### T2.D: Model leakage demonstration (4 points)
Create a **controlled** future-peeking example where a query may attend to the following *input* position with the target token. Show why this can make training deceptively easy but inference mismatched. Clearly label your experiment as an illustrative construction; do **not** assert every unmasked model necessarily gets zero loss.

### T2.E: Rectangular cross-attention (4 points)
Decoder queries `[2,4,3,8]`, encoder keys `[2,4,5,8]` and values `[2,4,5,6]`: predict score and output shapes. Show why ordinary target causal mask `[3,3]` cannot be reused as an encoder-decoder cross-attention mask `[3,5]`.

## Tier 3 — Modern components and KV cache (1–2 weeks, 25 points)

**Files:** Tier3 notebook, code library. Advanced optional material; keep it **out** of the 30-minute trial lecture unless asked. Reference: [Stanford CS336 lectures](https://cs336.stanford.edu/spring2025/).

### T3.A: Rotary position embeddings (5 points)
1. Define the $2\times 2$ rotation $R(\phi)$ and prove $\|R(\phi)x\|_2=\|x\|_2$.
2. Show $[R(i\theta)q]^\top[R(j\theta)k]=q^\top R((j-i)\theta)k$.
3. Implement pairwise RoPE on `[B,H,T,d_h]` (even $d_h$) using absolute offsets for KV-cache consistency.

### T3.B: RMSNorm and SwiGLU (5 points)
Define both operations and trainable parameters. Calculate RMSNorm of $(3,4)$ when $\epsilon=0$ and scale is $(1,1)$. State why RMSNorm is not identical to LayerNorm.

### T3.C: KV cache and GQA (7 points)
Define the shapes of cached $K,V$ for $B=2$, $L=6$ layers, sequence length $T=128$, $H_{kv}=2$, $d_h=4$, bf16 storage. Compute total bytes. Implement reference GQA and compare cached vs full causal outputs using identical weights, eval mode and correct RoPE offsets. Assert closeness; **runtime is a measured quantity, not a promised speedup**.

### T3.D: Controlled ablation and report (8 points)
Compare two options of `use_rope`, `Hkv` and/or normalization on identical model input; hold seed, architecture, data, hardware constant except the variable being tested. Include theoretical cache size, measured runtime (with warm-up and median of repetitions), and conclusion plus limitations. No minimum speedup is required.

## Tier 4 — Synthetic image-to-sequence mini-project (2–3 weeks, 25 points)

**Files:** Tier4 Student Notebook and Instructor Notebook, `GlyphSeq2Seq` in library. The dataset uses *artificial*, intentionally simple 5×5 symbol patterns, not historical document images.

### T4.A: Dataset and splits (5 points)
Implement 4 synthetic glyph classes with 5×5 patches and independent noise. Each example consists of a length-three sequence of glyph images `[S,1,5,5]`. Targets are symbol IDs. Use disjoint random seeds for train and test; explain what this does and **does not** guarantee about generalization.

### T4.B: Model and training objective (6 points)
Visual encoder: each 5×5 glyph patch becomes a vector. Add source-position embeddings, feed encoded vectors to a Transformer decoder with causal target self-attention and full cross-attention over source patches. Write all intermediate shapes and the shifted target cross-entropy. Train the compact model on CPU.

### T4.C: Autoregressive decoding (5 points)
Implement greedy decode with a BOS prefix and EOS stopping, plus beam width 3 with a declared length-penalty convention. Record generated outputs and **do not** claim beam will necessarily outperform greedy.

### T4.D: Evaluation metrics (5 points)
Implement edit distance with insertion, deletion, substitution costs = 1. For reference `[0,1,2]` and hypothesis `[0,2,2]`, compute CER; for reference `[0]` and hypothesis `[0,1,2]`, compute CER. Compute exact-sequence accuracy on a test set and interpret its units.

### T4.E: Scientific reporting and limitations (4 points)
Report training and test seeds, noise rate, loss trajectory, CER, exact match, three concrete errors, and a case where beam search does not improve. Specify the obvious limitations: synthetic patterns, seen character classes, fixed lengths, small scale, and no claims for Chữ Nôm or real OCR.

## Grading rubric summary

| Tier | Numeric/theory | Correctness/test | Analysis/limits | Reproducibility | Total |
|---|---:|---:|---:|---:|---:|
| 1 | 20 | 0 | 5 | 0 | 25 |
| 2 | 5 | 15 | 3 | 2 | 25 |
| 3 | 5 | 10 | 6 | 4 | 25 |
| 4 | 5 | 10 | 7 | 3 | 25 |
| **Total** | **35** | **35** | **21** | **9** | **100** |

**Academic integrity:** Write your own answers before consulting the instructor key. Cite external material and explain the code you submit. Use AI assistance only according to the policy set by the actual course coordinator.
