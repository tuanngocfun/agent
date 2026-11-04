"""Inspectable synthetic controls for the worked teaching notebooks.

These controls demonstrate algorithms, not claims about a learned language model.
"""
from __future__ import annotations
import torch
import torch.nn.functional as F
from vgu_transformers import BOS, EOS, PAD


class FixedHorizonTree:
    """Exactly two generated tokens: A/B then X/Y; deliberately no EOS.

    A=.6, B=.4; X|A=.5, Y|A=.5; X|B=1. Hence AX=.3, AY=.3, BX=.4.
    Tokens: A=0, B=1, X=2, Y=3, BOS=4, EOS=5, PAD=6.
    """
    def eval(self):
        return self
    def encode(self, images):
        return images
    def decode(self, memory, prefix):
        logits = torch.full((prefix.shape[0], prefix.shape[1], 7), -torch.inf,
                            device=prefix.device)
        for row in range(prefix.shape[0]):
            if prefix.shape[1] == 1:
                logits[row, -1, 0] = torch.log(torch.tensor(.6, device=prefix.device))
                logits[row, -1, 1] = torch.log(torch.tensor(.4, device=prefix.device))
            elif int(prefix[row, 1]) == 0:
                logits[row, -1, 2:4] = torch.log(torch.tensor(.5, device=prefix.device))
            else:
                logits[row, -1, 2] = 0.
        return logits


def sequence_log_probability(model, image, sequence):
    """Recompute the actual raw model log probability of generated tokens."""
    memory = model.encode(image)
    total = 0.
    for stop in range(1, len(sequence)):
        prefix = torch.tensor([sequence[:stop]], dtype=torch.long, device=image.device)
        logp = F.log_softmax(model.decode(memory, prefix)[0, -1], dim=-1)
        total += float(logp[sequence[stop]])
    return total


class EOSControl:
    """Deterministic rows: sample 0 ends immediately; sample 1 emits 1,1,EOS."""
    def eval(self):
        return self
    def encode(self, images):
        return images
    def decode(self, memory, prefix):
        assert len(memory) == 2, 'EOS control demonstrates two rows.'
        logits = torch.full((2, prefix.shape[1], 7), -torch.inf, device=prefix.device)
        logits[0, -1, EOS if prefix.shape[1] == 1 else 3] = 0.
        logits[1, -1, EOS if prefix.shape[1] == 3 else 1] = 0.
        return logits


def nearest_template_predict(images):
    """No-training baseline; access to the same four known glyph templates.

    Fresh noisy examples and a decoder are unnecessary for this simple baseline.
    Argmin over mean squared pixel distance per glyph is independent per position.
    """
    from vgu_transformers import _GLYPHS
    templates = _GLYPHS.to(device=images.device, dtype=images.dtype)
    distance = (images.squeeze(2).unsqueeze(2) - templates[None, None]).square().mean((-1, -2))
    return distance.argmin(-1)
