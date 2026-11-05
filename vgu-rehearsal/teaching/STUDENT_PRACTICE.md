# Independent practice — prompts without executable blanks

All delivered notebooks now contain completed worked/reference examples. This page holds the unanswered tasks for independent practice. Use paper and a new scratch file of your own; keep the supplied demonstrations intact. No incomplete executable notebook is needed.

The four implementation targets are `attention(q,k,v,mask=None)`, `causal_mask(t_query,t_key=None,past=0,device=None)`, `next_token_pairs(ids)` and `masked_cross_entropy(logits,labels,*,ignore_index)`. Explain each contract before coding. Do not treat passing the package's reference tests as evidence that you independently implemented them.

## Tier 1 — reason before running code

1. **A changed attention query.** Use `q=[0,1]`, keys `[[1,0],[0,1]]` and values `[[3,1],[-1,5]]`. Predict the more relevant key, calculate scaled scores, softmax weights and the weighted output. Explain which quantities change if only the second value vector changes.
2. **Distinct dimensions.** Let `B=3,H=2,T=4,S=7,d_k=5,d_v=6`. Write Q/K/V, score, weight and output shapes. Identify the softmax axis and the axis summed away when mixing V. Draw one query's seven comparisons.
3. **Visibility and next-target alignment.** For `[BOS,x,y,EOS]`, write decoder inputs and supervised labels. Draw the additive causal mask. Identify exactly which future input would leak the first target if masking were omitted. Explain why a correct shift alone cannot stop that leak.
4. **Loss and perplexity.** For vocabulary logits `[0,ln(3),0]` and target class 0, calculate probabilities, negative log-likelihood and one-token perplexity. State the logarithm base. Explain why this distribution is different from attention weights over keys.
5. **Local versus sequence decisions.** The first choice has `P(A)=0.7,P(B)=0.3`. After A, the next-symbol probabilities for X/Y/Z are `[0.4,0.35,0.25]`; after B they are `[0.95,0.03,0.02]`. Compare greedy with the highest-probability complete two-symbol sequence. State tie, length and EOS conventions rather than silently changing them.

Submit your intermediate calculations and explanations, not only final numbers.

## Tier 2 — build and challenge your own component

1. Implement the four named API functions in a separate file. Use floating additive masks: zero permits, negative infinity blocks. Compare rectangular attention with an independent reference API and explain any numerical tolerance.
2. Create a future-perturbation check: change only future keys/values and show which earlier outputs must stay the same. Show a normal unmasked contrast to explain what the causal rule prevents. Do not hide a failed assertion or declare an exception a pass.
3. Test a padding-key mask and an offset causal mask with nonzero `past`. Explain why the local and absolute query indices differ when cached history is present.
4. Define and implement the reference edge policy: all-masked attention rows produce zero weights/output; all-ignored targets produce differentiable zero loss. Check finite gradients. Explain why valid row sums of one have an explicit empty-row exception.
5. Build a batch containing BOS, EOS and PAD. Inspect shifted labels, count supervised targets and confirm ignored positions contribute zero loss gradient. Explain why target-loss masking does not hide padding keys from attention.
6. Ask a peer to change a dimension, mask or value without warning. Predict the result before running it. Record a mismatch, its cause and the correction in your own words.

## Transfer to an application or research question

Choose translation, code generation, speech transcription or document recognition. Name the input, token unit, output sequence, BOS/EOS behavior, training objective, simple baseline and held-out metric. Identify one plausible leakage path and one behavioral check that would expose it.

If extending the synthetic glyph demonstration, compare greedy and beam width 3 on the same cases. Report actual errors or none observed, with the sample count. Known-template success does not establish real-document recognition or a need for useful target-history dependence.

A completed independent submission should include your code, actual outputs, explanations, a controlled comparison and a limitation. Learner understanding and unscripted teaching remain human observations; they are not certified by the supplied worked solutions.
