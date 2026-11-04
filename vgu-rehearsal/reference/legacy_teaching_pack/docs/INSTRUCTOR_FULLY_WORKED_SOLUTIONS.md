# VGU Transformer Teaching Pack
## Fully Worked Instructor Solutions, Mathematical Notes, Examples and Code Commentary

**Status:** Original, independently prepared VGU-oriented *proposed* teaching resource. **Not** an official VGU, Stanford, MIT, CMU or NUS answer key. **Date:** 04 November 2026. Instructor-only; do not distribute the answers together with student assignments during assessment.

**Scope:** four teaching tiers, 100 marks; 30-minute interview lecture maps to Levels 1 and 2, while Levels 3 and 4 are proposed follow-up labs and a mini-project. Source/lecture links are in [LECTURE_AND_SOURCE_LINKS.md](LECTURE_AND_SOURCE_LINKS.md) and repeated where most relevant.

# A. Audit of the previous package and what this fixes

The previous `Teaching_4_Tier_Assignments_and_Rubrics.docx` gave about 39 paragraphs and **no worked solutions**: it specified four progressively harder assignments, rubrics and course links. The previous 13-cell instructor notebook supplied executable answers to only a **short attention/mask/teacher-forcing/decoding mini-lab**. It did **not** implement RoPE, RMSNorm, GQA or KV-cache equivalence, nor a trainable visual-to-sequence mini-project. Thus, it was an outline, *not* a complete instructor pack. This revision provides: original detailed questions; formula index; complete mathematical derivations; trainable reference implementation; code tests; student/instructor notebooks for all four levels; limitations and lecturer links. Validation is specific to the delivered code and examples, **not** a claim of external validation by universities.

# B. Dictionary of notation (read before the solutions)

| Notation | Formal definition and meaning | Shape or worked value |
|---|---|---|
| $B$ | batch size: number of independently encoded sequences in parallel | $2$ |
| $S$ | source length: encoder input positions | $5$ |
| $T$ | target sequence length | $4$ |
| $d_{model}$ | number of channels in hidden token representation | $16$ |
| $H_q$ | query attention heads | $4$ |
| $H_{kv}$ | key/value attention heads; GQA allows $H_{kv}<H_q$ | $2$ |
| $d_h$ or $d_k$ | dimension of queries and keys **per head** | $d_{model}/H_q=4$ |
| $d_v$ | value feature dimension per head, may differ from $d_h$ | $6$ in rectangular example |
| $X$ | token embeddings or hidden states | $[B,T,d_{model}]$ |
| $W_Q,W_K,W_V$ | **learned** linear maps producing queries, keys and values | typically $[d_{model},H_qd_h]$, etc. |
| $Q$ | queries; each asks what to retrieve | $[B,H_q,T,d_h]$ |
| $K$ | keys; each represents how to be matched | $[B,H_{kv},S,d_h]$ for cross-attn |
| $V$ | values to be weighted and aggregated | $[B,H_{kv},S,d_v]$ |
| $s_{ij}$ | attention logit for query $i$ and key $j$ before softmax | $q_i^\top k_j/\sqrt{d_h}$ |
| $M_{ij}$ | additive attention mask: $0$ allowed; $-\infty$ forbidden | $[T,T]$, broadcast to batch/heads |
| $A$ | softmax-normalized attention weights (each valid row sums to 1) | $[B,H_q,T,S]$ |
| $Z$ | weighted sum of value vectors; context representation | $[B,H_q,T,d_v]$ |
| $\mathcal V$ | vocabulary (discrete symbols), $|\mathcal V|$ its size | $7$ in toy glyph project |
| $z_{t,c}$ | vocabulary logit of class $c$ at position $t$ | raw real number |
| $p_{t,c}$ | softmax probability for token $c$ at output position $t$ | $\sum_c p_{t,c}=1$ |
| $y_t$ | token at position $t$ in reference output | one integer index |
| $\theta$ | all trainable parameters | encoder/decoder weights |
| $\mathcal L$ | optimization objective (loss), e.g. negative log-likelihood | scalar |
| $\mathrm{PPL}$ | perplexity: exponential of average NLL per token | $4$ in the toy example |
| $R(\phi)$ | $2\times2$ rotation matrix by angle $\phi$ | RoPE |
| $\epsilon$ | small numerical stability constant in normalization | $10^{-6}$ |
| $\alpha$ | exponent for **one chosen** beam length-normalization score | $0.7$ in code |
| $\mathrm{ED}(r,h)$ | Levenshtein edit distance of reference and hypothesis | integer |
| $\mathrm{CER}$ | character error rate $\mathrm{ED}(r,h)/|r|$ | can be $>1$ |
| $\mathrm{EM}$ | exact-match rate, all token IDs must match per sample | fraction in $[0,1]$ |
| BOS, EOS, PAD | begin, end and padding tokens | IDs 4, 5, 6 in glyph project |

**Conventions.** Tensor shapes are written in batch-first notation throughout. $i$ denotes query/output position, $j$ denotes key/input position. Attention softmax is over **keys** ($j$), never over queries. In formulas without batch/head indices, $Q\in\mathbb R^{T\times d_h}$, $K\in\mathbb R^{S\times d_h}$, $V\in\mathbb R^{S\times d_v}$.

---

# C. Tier 1 — Full hand-worked solutions (25 marks)

**Related VGU slides:** refined trial lecture 3, 5, 6, 7, 8, 10. **Primary readings:** [MIT transformer notes](https://introml.mit.edu/notes/transformers.html); [Stanford CS224N 2026 Lecture 5 slides](https://web.stanford.edu/class/cs224n/slides_w26/cs224n-2026-lecture05-transformers.pdf); [NUS lecture 7 PDF](https://storage.googleapis.com/xavierbresson/lectures/CS5242/lecture07_attention_neural_networks.pdf).

## T1.A: Derive and compute scaled dot-product attention (6/6)

### Step 1 — Recreate the matrices

The query $q=(1,0)$ has **two features**. There is one query and two candidate keys. Thus:

$$Q=\begin{bmatrix}1&0\end{bmatrix}\in\mathbb R^{1\times2},\quad K=\begin{bmatrix}1&0\\0&1\end{bmatrix}\in\mathbb R^{2\times2},\quad V=\begin{bmatrix}2&0\\0&4\end{bmatrix}\in\mathbb R^{2\times2}.$$

$QK^\top:[1,2]\,[2,2]^\top\mapsto [1,2]$, and $AV:[1,2]\,[2,2]\mapsto[1,2]$.

### Step 2 — Raw logits and scaling

$$QK^\top=\begin{bmatrix}(1,0)\cdot(1,0)&(1,0)\cdot(0,1)\end{bmatrix}=\begin{bmatrix}1&0\end{bmatrix}.$$

With $d_h=2$, the scaled scores are $s=(1/\sqrt2,0)=(0.7071068,0)$. The purpose of the scale is statistical: if independent $q_r$ and $k_r$ have mean 0 and variance 1, $\mathrm{Var}(\sum_{r=1}^{d_h}q_rk_r)=d_h$ under the independence assumptions, hence division by $\sqrt{d_h}$ produces variance near 1. This is a heuristic variance argument, **not** a theorem that every model without scaling must fail.

### Step 3 — Row-wise softmax

$$a_1=\frac{e^{1/\sqrt2}}{e^{1/\sqrt2}+e^0}=0.66976155,\qquad a_2=1-a_1=0.33023845.$$

Both values are non-negative, and $a_1+a_2=1$. A common error is to perform softmax across the query dimension; there is only one query here and doing so would give incorrect weights.

### Step 4 — Weighted value sum

$$z=a_1v_1+a_2v_2=(2a_1,4a_2)=(1.3395231,1.3209538).$$

**Final:** $z\approx(1.340,1.321)$, shape $[1,2]$. The larger attention weight belongs to key 1, yet the second output component is still large because $v_2$ has magnitude 4. Attention weights describe *routing*, not a statement that the first output feature must be larger than the second.

### Without the scale

$\mathrm{softmax}(1,0)=(e/(e+1),1/(e+1))\approx(0.7311,0.2689)$; the output changes to $(1.4621,1.0758)$. For larger $d_h$, more extreme logits may drive softmax close to one-hot, possibly affecting gradient conditioning. Whether this happens requires measurement of activations and optimization behavior.

**Marking:** correct matrices/shapes 2; scores 1; softmax 1; output 1; correct scaling discussion 1.

## T1.B: Full tensor-shape proof and cross-attention (4/4)

Set $B=2,T=4,d_{model}=16,H=4$, so $d_h=16/4=4$. First $X:[2,4,16]$.

For one standard multi-head attention layer, learn $W_Q,W_K,W_V\in\mathbb R^{16\times16}$, then $XW_Q,XW_K,XW_V:[2,4,16]$. Reshape the last dimension into $[H,d_h]=[4,4]$: $[2,4,4,4]$ for $[B,T,H,d_h]$. Transpose positions 2 and 3 to get $Q,K,V:[2,4,4,4]$ for $[B,H,T,d_h]$.

1. $K^\top:[2,4,4,4]$ where the **last two axes** are interchanged.
2. $QK^\top:[B,H,T,T]=[2,4,4,4]$.
3. Apply mask $M:[4,4]$ and row-wise softmax, so $A:[2,4,4,4]$.
4. Multiply $AV:[2,4,4,4]$.
5. Transpose to $[2,4,4,4]$ in $[B,T,H,d_h]$ convention and flatten $H\times d_h=16$, yielding $[2,4,16]$.
6. Multiply by final learned projection $W_O:[16,16]$, output $[2,4,16]$.

**Cross-attention** differs because queries are generated from target decoder states, length $T=4$, while keys/values come from source encoder memory, length $S=5$. Thus:

$$Q:[2,4,4,4],\quad K,V:[2,4,5,4],\quad QK^\top:[2,4,4,5],\quad AV:[2,4,4,4].$$

The rectangular $[4,5]$ score matrix is crucial. Target *causal self-attention* is square $[4,4]$, but encoder–decoder cross-attention normally permits each target query to see **all non-padding source positions**. Applying a $4\times4$ target causal mask to a $4\times5$ cross-attention score matrix is both shape-incorrect and conceptually wrong.

**Marking:** head dim 1; projected/head shapes 1; score/output/concatenation 1; cross-attention rectangle 1.

## T1.C: Masking is not target shifting (5/5)

### Step 1 — Make the additive mask

For $T=4$:

$$M_{ij}=\begin{cases}0&j\le i\\-\infty&j>i\end{cases},\qquad M=\begin{bmatrix}0&-\infty&-\infty&-\infty\\0&0&-\infty&-\infty\\0&0&0&-\infty\\0&0&0&0\end{bmatrix}.$$

The convention is zero-based or one-based as long as query $i$ cannot see key $j>i$. Add $M$ **before softmax**, never after. If the unmasked logits happen to all be zero, each allowed key receives equal probability, giving the concrete matrix

$$A=\begin{bmatrix}1&0&0&0\\1/2&1/2&0&0\\1/3&1/3&1/3&0\\1/4&1/4&1/4&1/4\end{bmatrix}.$$

Each row sums to exactly 1 in real arithmetic. $\exp(-\infty)=0$, so forbidden entries become zero after softmax. This example is for zero logits; **other logits produce different nonzero weights**.

### Step 2 — Shift target labels by one position

Full reference tokens: `[BOS, I, love, AI, EOS]`. Decoder input: `[BOS, I, love, AI]`. Targets: `[I, love, AI, EOS]`.

At input position 0 the model predicts `I`; at position 1 it predicts `love`; at position 2 it predicts `AI`; at position 3 it predicts `EOS`. Shifted labels establish **the learning objective**; the causal mask establishes **which input positions may influence a prediction**. They are complementary, not interchangeable.

### Step 3 — Why neither alone is enough

- Without shift (labels equal inputs), a sufficiently expressive decoder can learn an easy identity-copy objective instead of forecasting the next token. Even correct masking cannot correct a misdefined target.
- Without causal mask, the position predicting `love` may access the future decoder-input position where the token `love` itself already appears. This leaks ground truth. Such a model *may* exploit the leak; zero training loss is **not guaranteed**.
- At inference, the model must use its own generated prefix. There is no ground-truth future target in the prefix.

**Padding caveat.** If a query has all keys masked, softmax over $[-\infty,-\infty,\dots]$ is undefined in the elementary implementation. Common solutions ensure a valid key per query, suppress padded *query losses*, or use a numerically stable attention kernel that handles the mask case explicitly. Do not set all forbidden logits to zero: $\exp(0)=1$ would **not** mask them.

**Marking:** mask correct 2; example weights 1; shifted inputs/targets 1; distinction 1.

## T1.D: Exact loss and perplexity (5/5)

Let logits be $z=(\ln2,0,0)$ and target zero-based token index $c^*=2$ (the **third** token). Softmax denominator:

$$Z=e^{\ln2}+e^0+e^0=2+1+1=4.$$

Hence $p=(2/4,1/4,1/4)=(0.5,0.25,0.25)$. Target probability $p_{c^*}=0.25$ and one-example cross entropy

$$\mathcal L_{CE}=-\ln p_{c^*}=-\ln(0.25)=\ln4\approx1.38629436\quad \text{nats/token}.$$

For a one-token evaluation, $\mathrm{PPL}=\exp(\mathcal L)=4$. For a sequence of $N$ evaluated tokens:

$$\mathrm{PPL}=\exp\left(-\frac1N\sum_{n=1}^N\ln p_{\theta}(y_n\mid y_{<n},x)\right).$$

A perplexity of 4 can be viewed as a geometric-mean inverse token probability of 4, **not** as 25% sequence accuracy. Different tokenization schemes change the number and meaning of target tokens, so raw per-token PPL scores are not directly comparable across tokenizers or vocabularies. For a tokenization-independent byte-level measure, separately define bits per byte and its denominator clearly.

Gradient of single softmax CE with target one-hot vector $e_{c^*}$ is $\partial\mathcal L/\partial z_c=p_c-e_{c^*,c}$, i.e. $(0.5,0.25,-0.75)$; these derivatives sum to zero. This is an instructive optional check.

**Marking:** correct normalization 1; target identification 1; CE 1; PPL 1; interpretation 1.

## T1.E: Construct a real greedy counterexample (5/5)

At step one, greedy selects $A$ because $0.6>0.4$. After $A$, the two possible second tokens are $a_1$ and $a_2$ with probability $0.5$ each. Thus the best two-token sequence starting with $A$ has probability

$$p(A,a_1)=p(A)p(a_1\mid A)=0.6\times0.5=0.30.$$

After $B$, there is only one valid next token $b$ with conditional probability $1$:

$$p(B,b)=0.4\times1=0.40.$$

Although greedy's first token has greater **local** probability, the best sequence beginning with $B$ is more probable globally: $0.4>0.3$. A beam retaining both prefixes $A$ and $B$ after the first step can discover the better final path in this particular two-step example. For longer sequences, limited-width beam search is a heuristic and may still prune the globally best prefix. Length normalization changes ranking and must be declared. **Beam search does not maximize task accuracy**, and sequence probability need not correlate perfectly with correctness.

**Marking:** selection 1; products 2; conclusion 1; beam caveat 1.

---

# D. Tier 2 — Full implementation and diagnostics (25 marks)

**Related VGU slides:** 5–9, 12–13. **Primary readings:** [Stanford CS224N A3 prompt (2026)](https://web.stanford.edu/class/cs224n/assignments_w26/a3.pdf) and [Harvard Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/). Those are **inspiration/reference**, not a source of the code printed here.

## T2.A: Correct attention implementation (6/6)

The formula

$$\mathrm{Attention}(Q,K,V;M)=\underbrace{\mathrm{softmax}_{j}\!\left(\frac{QK^\top}{\sqrt{d_h}}+M\right)}_{A\,\mathrm{with}\,\sum_jA_{ij}=1}V$$

contains a precise operation sequence. `Q @ K.transpose(-2,-1)` computes the last two matrix axes while keeping the earlier dimensions for batch/head broadcasting. Divide by $\sqrt{d_h}$ **before** normalization. Add an additive mask with $0$ for allowed and $-\infty$ for forbidden positions. Softmax on `dim=-1` since the last dimension indexes keys. Finally take `weights @ V`.

```python
import math
import torch

def attention(q, k, v, mask=None):
    # q [B,H,Tq,d], k [B,H,Tk,d], v [B,H,Tk,dv]
    logits = (q @ k.transpose(-2,-1)) / math.sqrt(q.shape[-1])
    if mask is not None:
        logits = logits + mask    # broadcast on B,H
    weights = torch.softmax(logits, dim=-1)  # across keys
    return weights @ v, weights
```

**Shape example.** If `q,k,v=[2,4,4,4]`, `logits=[2,4,4,4]`, weights same, output `[2,4,4,4]`. If `k` source length is 5 and `v` feature depth is 6, score `[2,4,3,5]`, output `[2,4,3,6]`.

**Test invariant:** `weights.sum(dim=-1)==1` within numerical tolerance on rows with at least one valid key. Use `torch.allclose` with tolerance (floating-point error).

## T2.B: Causal and padding mask correctness (6/6)

For query $i$ at absolute position $p+i$ with cached prefix of length $p$, the allowed key positions are $j\le p+i$. Hence the general mask is

$$M_{ij}=\begin{cases}0,&j\le p+i,\\-\infty,&j>p+i.\end{cases}$$

Create mask in PyTorch by comparing ranges, avoiding a shape bug when $T_q\ne T_k$:

```python
def causal_mask(Tq, Tk, past, device):
    qpos = torch.arange(past, past + Tq, device=device)[:,None]
    kpos = torch.arange(Tk, device=device)[None,:]
    return torch.where(kpos <= qpos, 0.0, float('-inf'))
```

For training without caching, $T_q=T_k=T$ and $p=0$. To mask **padded keys**, combine the causal mask with key-padding information: if `valid_key[j]` is false, set score at every query $i$ for key $j$ to $-\infty$. For `B` batches, expand padding mask to `[B,1,1,Tk]` before broadcasting against `[B,H,Tq,Tk]`. Query-padding positions should be excluded from the loss using `ignore_index`, not merely prevented from attending to keys.

**Counterexample to flawed masking.** If future logits are set to `0` rather than `-inf` before softmax, their exponentials become 1, giving positive probability to forbidden future keys. If a row has no valid keys at all, naive softmax produces undefined values; the loss must ignore these query positions or construct a safe non-empty allowed set.

**Test** for regular causal rows:

```python
mask = torch.triu(torch.full((4,4),float('-inf')),diagonal=1)
a = torch.softmax(torch.zeros(4,4)+mask,dim=-1)
assert torch.allclose(a.sum(-1),torch.ones(4))
assert a[0,1:].abs().sum()==0
assert a[1,2:].abs().sum()==0
```

**Marking:** mask values/direction 2; padding semantics 2; invariant tests 1; fully masked caveat 1.

## T2.C: Why teacher forcing and CE must agree exactly (5/5)

Define full token array of length $T+1$: $[\mathrm{BOS},y_1,\dots,y_T]$. During supervised next-token training:

$$x_{decoder}= [\mathrm{BOS},y_1,\ldots,y_{T-1}],\qquad \mathrm{labels}=[y_1,y_2,\ldots,y_T].$$

The resulting logits $Z:[B,T,|\mathcal V|]$ are compared against label IDs $Y:[B,T]$. Loss is

$$\mathcal L=-\frac1{N_{valid}}\sum_{b,t:\,Y_{bt}\ne\mathrm{PAD}}\log\frac{\exp(Z_{bt,Y_{bt}})}{\sum_{c\in\mathcal V}\exp(Z_{bt,c})}.$$

The code uses flattening only to match the shape expected by `torch.nn.functional.cross_entropy`:

```python
import torch.nn.functional as F
x = ids[:, :-1]        # B,T
labels = ids[:, 1:]    # B,T
loss = F.cross_entropy(logits.reshape(-1, logits.shape[-1]),
                       labels.reshape(-1), ignore_index=PAD_ID)
```

Ignore the PAD *label*, not the BOS token in the input. If padding is ID 6, set `ignore_index=6`. In the packaged library, generic `masked_lm_loss` uses `ignore_index=-100` by default; call it with the correct actual padding value when present.

**Marking:** correct shift 2; shapes 1; formula 1; padding 1.

## T2.D: An intellectually honest future-leakage demonstration (4/4)

A model trained without a target causal mask can use decoder input position $t+1$ when producing logits at position $t$. With teacher forcing, that input position **contains the reference target $y_{t+1}$**, so the input supplies an answer that will not be available during left-to-right inference.

Concrete illustration: let decoder input token IDs be $x=(\mathrm{BOS},a,b)$ and targets $y=(a,b,\mathrm{EOS})$. Suppose an artificial attention circuit at output position 0 puts weight 1 on input position 1, whose embedding identifies $a$. A classifier can then predict target $a$ almost trivially. Under a causal mask, output position 0 must attend only to BOS; the future $a$ is not accessible from the attention mechanism. This is a **constructed causal demonstration**, not evidence that training *always* collapses to zero loss without a mask. Empirical results depend on model, optimization and data.

Demonstration with one-hot logic (no training needed):

```python
import torch
x = torch.tensor([4, 0, 1])   # BOS, a, b
# Artificial unmasked head: output at position 0 copies x[1].
leaked_prediction_at_0 = x[1]
assert int(leaked_prediction_at_0) == 0  # equals the first next-token label
# A causal head cannot select x[1] when predicting at position 0.
```

To study the effect empirically, train a toy model with/without mask under identical random seeds and compare **held-out autoregressive generation**, not only training loss. Never promise a particular training-loss curve as a guaranteed outcome.

**Marking:** explicit target alignment 1; leak mechanism 2; no universal claim 1.

## T2.E: Cross-attention rectangularity and masks (4/4)

$Q:[B,H,T,d_k]=[2,4,3,8]$, $K:[B,H,S,d_k]=[2,4,5,8]$, and $V:[B,H,S,d_v]=[2,4,5,6]$. Matrix multiplication yields

$$QK^\top:[2,4,3,5],\qquad \mathrm{softmax}(\cdot)V:[2,4,3,6].$$

The target causal mask is $[3,3]$ because only **target** self-attention obeys autoregressive order. Cross-attention uses a $[3,5]$ score matrix and source-padding mask (if required). A rectangular mask could be constructed for application-specific restrictions, but the ordinary encoder–decoder setting allows queries to see every non-padding source feature.

**Marking:** score shape 2; output shape 1; distinction 1.

---

# E. Tier 3 — Advanced architecture, resource accounting and cached inference (25 marks)

**Reference links:** [Stanford CS336 Spring 2025 lecture portal](https://cs336.stanford.edu/spring2025/), [CMU 11-785](https://deeplearning.cs.cmu.edu/S26/), [Princeton COS484](https://princeton-nlp.github.io/cos484/), [ETH Zürich LLM 2026 catalogue](https://www.vorlesungen.ethz.ch/Vorlesungsverzeichnis/lerneinheit.view?ansicht=KATALOGDATEN&lang=en&lerneinheitId=198774&semkez=2026S). **Not** essential for 30-minute Bachelor trial lecture; use for Q&A or later laboratories.

## T3.A: RoPE from first principles (5/5)

Define a planar rotation:

$$R(\phi)=\begin{bmatrix}\cos\phi&-\sin\phi\\\sin\phi&\cos\phi\end{bmatrix}.$$

Its transpose is $R(-\phi)$ and direct multiplication gives $R(\phi)^\top R(\phi)=I$ because $\sin^2\phi+\cos^2\phi=1$. Thus for any $u\in\mathbb R^2$,

$$\|R(\phi)u\|_2^2=u^\top R(\phi)^\top R(\phi)u=u^\top u=\|u\|_2^2.$$

Rotations preserve Euclidean lengths. Now consider a query $q$ at position $i$ and key $k$ at position $j$ transformed with the **same** angular-frequency schedule $\theta$:

$$\begin{aligned}
(R(i\theta)q)^\top(R(j\theta)k)&=q^\top R(i\theta)^\top R(j\theta)k\\
&=q^\top R(-i\theta)R(j\theta)k\\
&=q^\top R((j-i)\theta)k.
\end{aligned}$$

The transformed dot product therefore has an explicit dependence on relative position difference $j-i$. In higher even dimension $d_h$, apply a separate rotation to each coordinate pair $(x_{2r},x_{2r+1})$ with frequency $\theta_r=10000^{-2r/d_h}$.

**Careful qualification:** RoPE does **not**, by itself, guarantee monotonically decreasing attention with increasing distance. Its trigonometric dependence oscillates; the learned queries and keys determine actual attention scores. The real advantages are position-dependent phase relationships and relative-position structure.

**Code** `rope(x, start_pos)` rotates `x[...,::2]` and `x[...,1::2]` pairwise. When using KV cache, fresh queries/keys at time $t$ must rotate by **absolute time $t$**, not restart their positions at zero each step. Otherwise full and cached predictions differ.

**Marking:** rotation 1; norm proof 1; relative-product proof 2; offset implementation 1.

## T3.B: RMSNorm and SwiGLU detailed examples (5/5)

RMSNorm with learned coordinate scale $\gamma\in\mathbb R^d$ is

$$\mathrm{RMSNorm}(x)=\gamma\odot\frac{x}{\sqrt{\frac1d\sum_{k=1}^{d}x_k^2+\epsilon}}.$$

For $x=(3,4)$, $\epsilon=0$ and $\gamma=(1,1)$:

$$\mathrm{RMS}(x)=\sqrt{\frac{3^2+4^2}{2}}=\sqrt{12.5}=3.5355339,$$

$$\mathrm{RMSNorm}(x)=\left(\frac3{\sqrt{12.5}},\frac4{\sqrt{12.5}}\right)\approx(0.848528,1.131371).$$

By contrast, LayerNorm computes a **mean-centered** variance ($x-\bar x$) first. RMSNorm does **not** subtract the mean; its invariance properties are therefore different. It uses fewer reduction statistics, although actual speed depends on kernel fusion and hardware.

The SwiGLU gated feed-forward block takes the general form

$$\mathrm{SwiGLU}(x)=W_{down}\left[\mathrm{SiLU}(W_{gate}x)\odot (W_{up}x)\right],\qquad \mathrm{SiLU}(u)=u\sigma(u),$$

where $\sigma(u)=1/(1+e^{-u})$, $\odot$ is elementwise multiplication, and all $W$ are learned matrices. The order of the $W$ terms depends on row-/column-vector convention. For a **single scalar** with $W_{gate}=1,W_{up}=2,W_{down}=1,x=1$, we get $\mathrm{SiLU}(1)=1/(1+e^{-1})\approx0.731059$, so the output is $2\times0.731059=1.462118$. Real blocks operate on vectors with intermediate width $d_{ff}$.

**Testable invariants:** RMSNorm preserves input shape, weights $\gamma$ are trainable; SwiGLU maps $[...,d_{model}]$ back to $[...,d_{model}]$ and both receive gradients through autograd.

**Marking:** RMSNorm calculation 2; LayerNorm contrast 1; SwiGLU equation/scalar example 2.

## T3.C: KV-cache and GQA resource accounting (7/7)

A decoder layer processes queries $Q\in\mathbb R^{B\times H_q\times T\times d_h}$, while keys and values in GQA have shape $[B,H_{kv},T,d_h]$. With full attention, the layer recomputes $K,V$ for all tokens if a naive implementation runs the entire prefix again at every new step. **KV caching stores previously computed** $K,V$ so a new token only requires new projections for that step.

### Exact cache size formula

Suppose we have $L$ decoder layers, $B$ sequences, $T$ cached positions, $H_{kv}$ KV heads per layer, $d_h$ channels/head and $b$ bytes/element. There are two cached tensors **K and V**. Therefore

$$\boxed{\mathrm{KVBytes}=2\,B\,L\,T\,H_{kv}\,d_h\,b}.$$

For $B=2$, $L=6$, $T=128$, $H_{kv}=2$, $d_h=4$, bf16 $b=2$ bytes:

$$2\cdot2\cdot6\cdot128\cdot2\cdot4\cdot2=49,152\text{ bytes}=48\text{ KiB}.$$

**Why GQA saves memory.** Standard MHA with $H_{kv}=H_q=4$ stores twice as many key/value heads as GQA with $H_{kv}=2$, holding all else fixed. MQA with $H_{kv}=1$ stores one quarter as many as full MHA in this configuration. It can alter model behavior; this comparison is only a memory-accounting fact.

### Derive the shapes of cached decoding

At current time $t$, for one new token $Q_{new}:[B,H_q,1,d_h]$. Cached keys $K_{cache}:[B,H_{kv},t-1,d_h]$ and newly computed $K_{new}:[B,H_{kv},1,d_h]$ concatenate to $[B,H_{kv},t,d_h]$. The corresponding values do likewise. Each KV head is reused for a group of $H_q/H_{kv}$ query heads. After expansion, score shape becomes $[B,H_q,1,t]$, and the output $[B,H_q,1,d_h]$.

### Full-prefix vs cache equivalence

For deterministic model in eval mode, with exactly the same weights, causal mask, position offsets and normalizations, the final hidden output for time $t$ computed with a cache must match the final position of a full-prefix calculation **within floating-point tolerance**. The shipped test `test_cached_matches_full` does this for $H_{kv}=1,2,4$ using RoPE; run `pytest -q`.

**Complexity qualification.** At each new step, the attention score for **one query** against $t$ cached keys costs $O(t d_h)$ per head, compared with recalculating the entire prefix's $t\times t$ attention, $O(t^2 d_h)$ for the attention-score part. This is **not** a claim that the entire model step is $O(t)$—linear projections and MLPs also cost computation, and total latency depends on hardware/memory bandwidth/batching. Storing KV cache increases memory consumption linearly with $T$.

**Marking:** formula 2; arithmetic 1; GQA compare 1; shape proof 1; equivalence test 2.

## T3.D: How to report an ablation correctly (8/8)

**Aim:** Isolate architectural changes, not to claim a universal speedup.

A reproducible ablation report requires a table like the following **template**. The rows below are examples of configurations, **not measured experimental results**:

| Run | Query heads | KV heads | RoPE | Sequence length | Expected KV bytes/layer/seq at bf16 |
|---|---:|---:|---|---:|---:|
| A | 4 | 4 | yes | 128 | $2\cdot1\cdot1\cdot128\cdot4\cdot4\cdot2=8192$ |
| B | 4 | 2 | yes | 128 | $4096$ |
| C | 4 | 1 | yes | 128 | $2048$ |
| D | 4 | 2 | no | 128 | $4096$ |

Record model seed, batch size, whether `.eval()` and `torch.no_grad()` were used, CPU/GPU model, PyTorch version, number of warm-up iterations and repeated measurements (e.g., median of 30). Use synchronized timing for CUDA (`torch.cuda.synchronize()`), but plain `time.perf_counter()` is enough for a CPU reference. Comparing entire cached and non-cached generation loops requires identical output length and careful separation of prefill from decode.

**Interpretation:** Lower KV memory in GQA is analytically predicted; faster runtime is **not guaranteed** for a small CPU toy example. Cached inference introduces overhead and tensor allocations, so tiny sequences can run equally fast or slower. RoPE can preserve norm exactly up to numerical rounding yet still affect learned model quality; our tests cover operator correctness, not generalization. The four-tier code provides the reference kernels and a small benchmark entry point, not a universal GPU performance claim.

**Marking:** controlled variable 2; reproducibility 2; tested outputs 2; interpretation and limits 2.

---

# F. Tier 4 — Synthetic image-to-sequence research mini-project (25 marks)

**Primary context:** [Harvard's Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/), [Stanford CS224N decoding lecture](https://web.stanford.edu/class/cs224n/slides_w26/cs224n-2026-lecture12-reasoning-part1.pdf), [Oxford conditional LM lectures](https://github.com/oxford-cs-deepnlp-2017/lectures). This exercise is *not* a benchmark of historical Hán–Nôm OCR.

## T4.A: Exact dataset construction, information flow and leakage control (5/5)

We define four **synthetic** glyph classes indexed 0–3 as binary $5\times5$ patterns. A sequence contains three glyphs, e.g. $[0,0,1]$. `make_glyph_batch(n=32,length=3,seed=0,noise=0.06)` samples labels uniformly, copies the corresponding patterns and flips each binary pixel independently with probability $\eta=0.06$. Shapes:

- images $I\in\mathbb R^{B\times S\times 1\times5\times5}$;
- target symbol sequence $Y\in\{0,1,2,3\}^{B\times S}$;
- synthetic class dictionary shared across splits.

The actual task is a **sequence of cropped glyph-image patches to a sequence of token IDs**; it is not full-page OCR or unsupervised line segmentation. This clarity prevents overclaiming the research relevance.

**Split:** training seed $11\cdot 1000 + s$ at step $s$, validation seed 777, test seed 999. Different noise seeds ensure independent random corruptions; however, all splits share the four underlying glyph templates. Therefore test results demonstrate robustness to new random corruptions of known glyphs—not generalization to new scripts, new characters, historical print styles or other domains. This limitation is important.

## T4.B: Visual encoder, decoder and full loss (6/6)

Each crop $I_{b,s}\in\mathbb R^{1\times5\times5}$ passes through a small CNN: `Conv2d(1,12,3,padding=1)` gives `[12,5,5]`, then ReLU and Flatten produce length $12\cdot5\cdot5=300$. A linear projection maps it to $d_{model}=32$. With source position embeddings added, the encoder memory is

$$E\in\mathbb R^{B\times S\times32}.$$

For each label row $(y_1,y_2,y_3)$, define complete sequence `[BOS,y1,y2,y3,EOS]`. Shift to obtain decoder inputs `[BOS,y1,y2,y3]` and labels `[y1,y2,y3,EOS]`, each shape $[B,4]$. Input embeddings + learned target positions produce `[B,4,32]`. The Transformer decoder uses target self-attention causal mask `[4,4]` and **cross-attention over all source glyph patches** `[B,S,32]`. The vocabulary projection yields

$$Z\in\mathbb R^{B\times4\times7}$$

because target symbols are 0–3 plus BOS=4, EOS=5 and PAD=6. BOS is never a valid output label in the training examples; padding is unused in the fixed-length demo.

The teacher-forced negative log-likelihood is

$$\mathcal L=-\frac1{4B}\sum_{b=1}^{B}\sum_{t=1}^{4}\log\frac{\exp(z_{b,t,y_{b,t}})}{\sum_{c=0}^6\exp(z_{b,t,c})}.$$

Training loop:

```python
model = GlyphSeq2Seq()
optimizer = torch.optim.AdamW(model.parameters(),lr=0.003)
for step in range(60):
    images, labels = make_glyph_batch(24,seed=11000+step)
    decoder_input, target = make_decoder_labels(labels)
    logits = model(images, decoder_input)
    loss = masked_lm_loss(logits, target)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
```

This matches the implementation in `src/vgu_transformers.py`. With seed 11, the reference validation run decreased its training loss from roughly 2.02 to 0.006 over 60 steps on one CPU in the development environment; it is **not a guaranteed reproducible exact curve on every hardware/software version**, and that low training loss is not evidence of general OCR performance. Test with a new seed.

## T4.C: Autoregressive inference and beam search (5/5)

At test time there is **no ground-truth prefix**. Begin with BOS and iterate

$$\hat y_t=\arg\max_{c\in\mathcal V}p_\theta(c\mid \hat y_{<t},E),$$

appending the predicted token until EOS or maximum length. This is greedy decoding. The implementation calls the decoder once per step and recomputes short prefixes; this is intentional for clarity, not an optimized inference system.

Beam search stores hypotheses $(h,\ell)$, where $h$ is generated token sequence and $\ell=\sum_{t}\log p_\theta(y_t\mid y_{<t},E)$ its accumulated log-probability. With beam width $K=3$, expand each unfinished hypothesis with up to $K$ tokens, then keep $K$ candidates under the declared score

$$\mathrm{score}_\alpha(h)=\frac{\ell(h)}{\max(1,|h|-1)^\alpha},\qquad \alpha=0.7.$$

$|h|-1$ excludes the BOS token but includes EOS when generated. This is **one** heuristic length normalization and is not universally the best scoring convention; different libraries implement length penalties differently. Completed hypotheses are retained. Both methods stop on EOS; a maximum length prevents nontermination.

**Important:** Beam maximizes neither test CER nor semantic correctness. A high-scoring sequence under a miscalibrated model may still be wrong. The small synthetic task can yield equal performance for greedy and beam (and often does), which is a valid observed finding rather than a failed experiment.

## T4.D: Edit distance, CER and exact match, line by line (5/5)

Define Levenshtein dynamic programming with reference $r$ of length $n$ and hypothesis $h$ of length $m$:

$$D_{i,0}=i,\quad D_{0,j}=j,\quad D_{i,j}=\min\begin{cases}D_{i-1,j}+1 &\text{deletion}\\D_{i,j-1}+1 &\text{insertion}\\D_{i-1,j-1}+\mathbb 1[r_i\ne h_j] &\text{substitution / match}\end{cases}.$$

Thus $\mathrm{ED}(r,h)=D_{n,m}$ and

$$\boxed{\mathrm{CER}(r,h)=\frac{\mathrm{ED}(r,h)}{\max(1,n)}}.$$

Example 1: $r=[0,1,2]$, $h=[0,2,2]$. The second character is substituted; ED $=1$, $n=3$, so CER $=1/3\approx0.3333$.

Example 2: $r=[0]$, $h=[0,1,2]$. Two tokens inserted; ED $=2$, $n=1$, CER $=2$. **CER may exceed 1**, so do not clamp it to $[0,1]$.

For dataset of $N$ sequences, we use mean per-sequence CER $N^{-1}\sum_n\mathrm{CER}(r_n,h_n)$. This differs from corpus-weighted CER $\sum_n ED_n /\sum_n |r_n|$ when sequence lengths differ. State your metric convention. Exact-sequence accuracy is

$$\mathrm{EM}=\frac1N\sum_{n=1}^{N}\mathbb 1[h_n=r_n].$$

In code, EOS and BOS are removed appropriately from decoded hypotheses before comparison. A prediction missing EOS is truncated by maximum length and still compared; it may include invalid special tokens, correctly penalized by edit distance.

## T4.E: Reporting and interpretation (4/4)

Use a table of **actual** numbers only after running the experiment. For example, the packaged source was exercised in one local development run using $60$ AdamW steps, batch size $24$, seed 11, noise rate $0.06$, test seed 999, $16$ test sequences: first training loss $\approx2.0232$, last $\approx0.0065$, greedy CER 0 and EM 1.00 for this *small, easy synthetic test*. Beam-width-3 on four of the same test examples also returned CER 0 and EM 1.00. Those numbers describe one implementation smoke test, **not** statistically reliable performance estimates, real-world accuracy or proof of improvement. The test is intentionally easy; report larger test sets, multiple seeds, uncertainty and harder train/test shifts for research claims.

Minimum scientific report must include: dataset generation seeds; $B,S,d_{model}$; implementation dependencies; optimizer/lr/number of updates; held-out sample count; mean CER and its convention; exact match; representative errors; greedy-vs-beam outcomes; failure modes; limitations. Use a no-training/untrained baseline or template matching as a meaningful control and never extrapolate synthetic results to historical documents.

**Marking:** setup 1; reproducibility 1; metrics 1; limitations 1.

---

# G. Consolidated formula sheet (student explanation + instructor checks)

| Equation | Mathematical meaning | Correctness check or common error |
|---|---|---|
| $p(y_{1:T}|x)=\prod_{t=1}^Tp(y_t|y_{<t},x)$ | chain-rule factorization, autoregressive conditional generation | EOS included if modeling termination |
| $Q=XW_Q,K=XW_K,V=XW_V$ | learned projections from hidden vectors | projection widths must match heads |
| $S=QK^\top/\sqrt{d_h}$ | similarity scores with scale | divide by **per-head** key dimension |
| $A=\mathrm{softmax}_{keys}(S+M)$ | normalized attention routing | softmax dimension = last key dimension |
| $Z=AV$ | weighted sum of value vectors | value depth may differ from $d_h$ |
| $M_{ij}=0$ if $j\le i$, else $-\infty$ | future masking for causal self-attention | add before softmax |
| $\mathcal L=-\sum\ln p(y_t|y_{<t},x)$ | negative log-likelihood; use mean for per-token loss | align shifted reference with correct logits |
| $p_c=\exp(z_c)/\sum_r\exp(z_r)$ | convert logits to categorical distribution | stable implementation subtracts max |
| $\mathrm{PPL}=\exp(\mathrm{mean\ NLL})$ | geometric-mean reciprocal token probability | tokenizer-dependent |
| $p_T(c)\propto\exp(z_c/\tau)$ | temperature-scaled probabilities | $\tau>0$; not itself a complete search policy |
| $R(i\theta)^\top R(j\theta)=R((j-i)\theta)$ | relative phase relation in RoPE | not monotonic distance decay |
| $\mathrm{RMSNorm}(x)=\gamma\odot x/\sqrt{\mathrm{mean}(x^2)+\epsilon}$ | rescale feature RMS without centering | differs from LayerNorm |
| $\mathrm{SwiGLU}(x)=W_d[\mathrm{SiLU}(W_gx)\odot W_ux]$ | gated feed-forward | check input/output dimensions |
| $2BLTH_{kv}d_hb$ | bytes occupied by cache K and V | multiply by 2 for K and V |
| $\mathrm{CER}=\mathrm{ED}/|r|$ | normalized edit distance | can exceed 1 |
| $\mathrm{EM}=N^{-1}\sum\mathbb1[h=r]$ | exact sequence correctness | strict entire-sequence comparison |

# H. Common mistakes, diagnostics and actionable feedback

**Mistake 1: Transpose wrong axes.** If `K.transpose(1,2)` rather than `K.transpose(-2,-1)`, matrix multiplication can silently mix heads/time dimensions when some sizes match by coincidence. Assert shape after each operation and test with distinct $B,H,T,d_h$.

**Mistake 2: Softmax on the wrong dimension.** Each query must distribute weights over **keys**. Test `weights.sum(-1)`; if it doesn't equal ones, softmax or masking is suspect.

**Mistake 3: A boolean mask with inverted convention.** PyTorch APIs differ: in some attention APIs `True` denotes **blocked** keys, elsewhere it denotes **allowed** keys. Document the convention explicitly and inspect a tiny $3\times3$ example.

**Mistake 4: No shifted targets.** A decoder training to predict its own input can learn copy identity rather than next-token generation. Compare `ids[:,:-1]` vs `ids[:,1:]` and inspect pairs.

**Mistake 5: Missing RoPE absolute offsets with cache.** Cached incremental and full-prefix outputs diverge, even with identical weights. Use `start_pos=cache_len` for queries and fresh keys and assert parity.

**Mistake 6: Comparing speed without synchronized timing.** CUDA kernels run asynchronously. Synchronize for measurement and report hardware. CPU warm-ups and tiny models make speed claims especially noisy.

**Mistake 7: Claiming historical OCR generalization from synthetic glyphs.** Real Hán–Nôm requires diverse scripts, segmentation, page-layout modeling, annotation provenance, book-level splits, domain shift and human-reviewed metrics. This mini-project teaches mechanics only.

**Mistake 8: Presenting unverified coursework as official VGU.** All material in this archive is *proposed*, and references are public external course sources.

# I. Automated verification and exact reproducibility

From project root:

```bash
python -m pip install -r requirements.txt
OMP_NUM_THREADS=1 python -m pytest -q tests
python -m jupyter notebook notebooks/
```

The tests cover: numeric attention; causal-matrix structure; rectangular cross-attention; shifted labels; greedy counterexample; RMSNorm/SwiGLU/RoPE shapes and norms; cached vs non-cached exactness for $H_{kv}=1,2,4$; analytical cache bytes; differentiable glyph model; CER examples; decoder smoke test. `tests/test_vgu.py` is the authoritative executable specification. A successful unit test means these cases work, **not** a proof all model behavior is correct.

For the mini-project:

```python
from vgu_transformers import *
model, train_losses = train_glyph_demo(steps=60, batch=24, seed=11)
images, targets = make_glyph_batch(16, seed=999)
print(evaluate_glyphs(model, images, targets))
```

**No GPU required.** The supplied code is intentionally small and pedagogical. Use different seeds and multiple runs for scientific conclusions.

# J. Suggested lecturer schedule and references by tier

| VGU lecture slide numbers | Topic | Tier and item | University slide/reference |
|---|---|---|---|
| 3 | autoregressive modeling | 1D, 1E | Stanford CS224N lecture 5 + lecture 12 |
| 5–6 | QKV and dimension trace | 1A–B, 2A | MIT 6.390 Ch.9; NUS Lecture 7 |
| 7–8 | causal masking, shifted labels, NLL | 1C–D, 2B–D | Stanford CS224N A3; Harvard Annotated Transformer |
| 9 | position and cross-attention | 2E, 3A | Stanford CS224N lecture 5; Stanford CS336 |
| 10 | greedy/beam/sampling | 1E, 4C | Stanford CS224N Lecture 12 |
| 11–13 | image-to-sequence and labs | 4A–E | Harvard Annotated Transformer; Oxford Deep NLP (context) |

**Public resources with embedded links:**

1. [Stanford CS224N Winter 2026 Lecture 5: Attention and Transformers (slide PDF)](https://web.stanford.edu/class/cs224n/slides_w26/cs224n-2026-lecture05-transformers.pdf).
2. [Stanford CS224N Winter 2026 Assignment 3 (assignment PDF)](https://web.stanford.edu/class/cs224n/assignments_w26/a3.pdf).
3. [Stanford CS224N Winter 2026 Lecture 12: Decoding and Reasoning (slide PDF)](https://web.stanford.edu/class/cs224n/slides_w26/cs224n-2026-lecture12-reasoning-part1.pdf).
4. [Stanford CS336 Spring 2025 course and lecture material](https://cs336.stanford.edu/spring2025/).
5. [MIT 6.390 Transformer notes](https://introml.mit.edu/notes/transformers.html).
6. [Harvard NLP Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/).
7. [Carnegie Mellon 11-785 Spring 2026 course page](https://deeplearning.cs.cmu.edu/S26/).
8. [Princeton COS484 Spring 2026 course and reading links](https://princeton-nlp.github.io/cos484/).
9. [NUS CS5242 2024/25 Lecture 7 (slide PDF)](https://storage.googleapis.com/xavierbresson/lectures/CS5242/lecture07_attention_neural_networks.pdf).
10. [NUS CS5242 2025 lab repository](https://github.com/xbresson/CS5242_2025).
11. [Oxford Deep NLP Lecture 7/8 (2017 archival slides, not an up-to-date Transformer lecture)](https://github.com/oxford-cs-deepnlp-2017/lectures).
12. [ETH Zurich Spring 2026 LLM course catalogue, not a slide file](https://www.vorlesungen.ethz.ch/Vorlesungsverzeichnis/lerneinheit.view?ansicht=KATALOGDATEN&lang=en&lerneinheitId=198774&semkez=2026S).

---

*Prepared for interview teaching demonstration and potential later Bachelor tutorials. Not submitted or endorsed by the universities listed. Original content, generated to map foundational math to tested PyTorch code.*
