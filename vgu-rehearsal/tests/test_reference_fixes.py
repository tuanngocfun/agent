import torch
import pytest
from vgu_transformers import *


def test_internal_BOS_counts_as_insertion():
    prediction=tokens_before_eos([BOS,0,BOS,1,2,EOS])
    assert prediction==[0,BOS,1,2]
    assert cer([0,1,2],prediction)==1/3


def test_internal_PAD_counts_as_error():
    assert tokens_before_eos([BOS,0,PAD,EOS])==[0,PAD]
    assert tokens_before_eos([0,1,EOS])==[0,1]


def test_loss_ignore_index_is_explicit():
    with pytest.raises(TypeError):
        masked_lm_loss(torch.zeros(1,1,7),torch.zeros(1,1,dtype=torch.long))


def test_boolean_attention_mask_rejected():
    x=torch.ones(1,1,2,4)
    with pytest.raises(TypeError):
        scaled_dot_product_manual(x,x,x,torch.ones(2,2,dtype=torch.bool))


def test_greedy_individually_finished_rows_are_padded():
    class Model:
        def eval(self):return self
        def encode(self,images):return images
        def decode(self,memory,prefix):
            logits=torch.full((2,prefix.shape[1],7),-100.)
            logits[0,-1,EOS if prefix.shape[1]==1 else 3]=0
            logits[1,-1,EOS if prefix.shape[1]==3 else 1]=0
            return logits
    result=greedy_generate(Model(),torch.zeros(2,3,1,5,5))
    assert result[0].tolist()==[BOS,EOS,PAD,PAD]
    assert result[1].tolist()==[BOS,1,1,EOS]


def test_existing_fixed_length_demo_still_trains():
    model,losses=train_glyph_demo(steps=5)
    assert all(torch.isfinite(torch.tensor(losses)))
    assert losses[-1]<losses[0]
