"""Tier 1–2 exercises. Implement these functions, then run your tests.

Interface contract:
- Attention uses floating additive masks: 0 permits a key; -inf blocks it.
- All-masked query rows have zero output AND zero weights.
- Valid attention rows sum to 1.
- Loss requires an explicit ignore_index. An all-ignored batch returns a
  differentiable zero, so backward() produces zero gradients.
- Padding in the loss and padding in attention are different operations.
"""
from __future__ import annotations
import torch


def attention(q, k, v, mask=None):
    """q [...,Tq,d], k [...,Tk,d], v [...,Tk,dv]; return (output, weights)."""
    raise NotImplementedError("Implement scaled dot-product attention (Tier 2A).")


def causal_mask(t_query, t_key=None, past=0, device=None):
    """Return [Tq,Tk], with key j visible iff j <= past + query_index."""
    raise NotImplementedError("Implement an additive causal mask (Tier 2B).")


def next_token_pairs(ids):
    """For [B,T] including BOS/EOS, return ids[:,:-1], ids[:,1:]."""
    raise NotImplementedError("Implement teacher-forcing shift (Tier 2C).")


def masked_cross_entropy(logits, labels, *, ignore_index):
    """Mean [B,T,V] CE over valid labels; all ignored -> differentiable zero."""
    raise NotImplementedError("Implement padding-aware target loss (Tier 2C).")
