"""Completed Tier 1–2 worked implementation, retained at its historical filename.

This module contains reference solutions for every runnable example in this
folder. It is no longer an unfinished learner submission. Independent practice
prompts live in teaching/STUDENT_PRACTICE.md, without executable blank functions.

The four short implementations follow the corrected package reference, with
explicit names and comments so their mathematics can be taught directly.
Inputs are finite floating tensors; masks are floating additive 0/-inf scores.
"""
from __future__ import annotations

import math
import torch
import torch.nn.functional as F


def attention(q, k, v, mask=None):
    """Return (mixed values, weights) for q [...,Tq,d], k [...,Tk,d], v [...,Tk,dv].

    Each valid query distributes weight across keys. Our declared policy for a
    fully blocked query is zero weights/output, with finite zero gradients for
    that query. We construct a safe softmax input before normalization; we do
    not discard exceptions or conceal invalid results after computation.
    """
    scores = (q @ k.transpose(-2, -1)) / math.sqrt(q.shape[-1])
    if mask is not None:
        if mask.dtype == torch.bool:
            raise TypeError("This API uses a floating additive 0/-inf mask.")
        scores = scores + mask
    has_visible_key = ~torch.isneginf(scores).all(dim=-1, keepdim=True)
    safe_scores = torch.where(has_visible_key, scores, torch.zeros_like(scores))
    weights = torch.softmax(safe_scores, dim=-1)
    weights = torch.where(has_visible_key, weights, torch.zeros_like(weights))
    return weights @ v, weights


def causal_mask(t_query, t_key=None, past=0, device=None):
    """Return [Tq,Tk]: key j is visible iff j <= past + query_index.

    Zero permits a score, negative infinity blocks it. With cached history,
    local query zero has absolute position ``past``. By default Tk=Tq+past.
    """
    if t_query < 0 or past < 0 or (t_key is not None and t_key < 0):
        raise ValueError("Sequence lengths and past must be nonnegative.")
    t_key = t_query + past if t_key is None else t_key
    query_positions = torch.arange(past, past + t_query, device=device)[:, None]
    key_positions = torch.arange(t_key, device=device)[None, :]
    return torch.where(key_positions <= query_positions, 0.0, float('-inf'))


def next_token_pairs(ids):
    """For [B,T] containing BOS/EOS, return previous inputs and next labels.

    EOS remains a supervised label. Any padded labels are handled explicitly by
    the loss function; this alignment function does not silently remove tokens.
    """
    if ids.ndim != 2 or ids.shape[1] < 2:
        raise ValueError("Expected a [batch,time] tensor with at least two tokens.")
    return ids[:, :-1], ids[:, 1:]


def masked_cross_entropy(logits, labels, *, ignore_index):
    """Mean [B,T,C] cross-entropy over valid labels; padding choice is explicit.

    If every target is ignored, the declared loss is differentiable zero. Loss
    masking and attention padding masks are separate operations.
    """
    if not labels.ne(ignore_index).any():
        return logits.sum() * 0.0
    return F.cross_entropy(
        logits.reshape(-1, logits.shape[-1]),
        labels.reshape(-1),
        ignore_index=ignore_index,
    )
