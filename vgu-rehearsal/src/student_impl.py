"""Instructor-only implementation of the student API."""
from vgu_transformers import causal_additive_mask, scaled_dot_product_manual, next_token_pairs, masked_lm_loss

attention = scaled_dot_product_manual
causal_mask = causal_additive_mask
masked_cross_entropy = masked_lm_loss
