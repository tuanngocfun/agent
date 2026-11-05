# Completed Tier 1–2 worked examples

`Tier1_Student.ipynb`, `Tier2_Student.ipynb` and `student_impl.py` now contain **complete worked/reference solutions**. Their historical filenames are retained so existing links open complete examples. They contain no executable blank exercises and do not rely on expected errors. Run them from top to bottom with the project kernel.

For presentation, use the dedicated [Tier 1 instructor notebook](../Tier1_Instructor.ipynb) and [Tier 2 instructor notebook](../Tier2_Instructor.ipynb). They cover the same tasks with explanations, complete code and checks. The implementation is loaded from this folder explicitly; the setup cell prints a package-relative location.

The four implemented functions are `attention`, `causal_mask`, `next_token_pairs` and `masked_cross_entropy`. From this directory, run the nine behavior checks with:

```bash
python -m pytest -q tests
```

Attention uses additive 0/−∞ masks before softmax. Valid attention rows sum to one; fully blocked rows have zero weights/output under this API's declared policy. Loss requires an explicit ignore index; an all-ignored batch has differentiable zero loss. Masking padded labels does not mask padding keys in attention.

Independent learner tasks are **Markdown prompts only** in [STUDENT_PRACTICE.md](../../teaching/STUDENT_PRACTICE.md). Use a separate scratch file for that practice. Keep these worked examples intact. Passing their supplied reference tests checks the included implementation; it does not establish independent student completion or understanding.
