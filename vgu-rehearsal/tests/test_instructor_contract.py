"""These tests grade student_impl, never an instructor answer library.

Run from the student_lab directory: python -m pytest -q tests
"""
import math
import torch
import torch.nn.functional as F
import student_impl as s


def test_two_key_numeric_example():
    q=torch.tensor([[1.,0.]])
    k=torch.eye(2)
    values=torch.tensor([[2.,0.],[0.,4.]])
    actual,w=s.attention(q,k,values)
    p=1/(1+math.exp(-1/math.sqrt(2)))
    torch.testing.assert_close(w,torch.tensor([[p,1-p]]))
    torch.testing.assert_close(actual,torch.tensor([[2*p,4*(1-p)]]))


def test_rectangular_attention_matches_torch():
    generator=torch.Generator().manual_seed(302)
    q=torch.randn(2,3,4,8,generator=generator)
    k=torch.randn(2,3,7,8,generator=generator)
    values=torch.randn(2,3,7,5,generator=generator)
    actual,w=s.attention(q,k,values)
    expected=F.scaled_dot_product_attention(q,k,values,dropout_p=0.)
    torch.testing.assert_close(actual,expected,atol=2e-6,rtol=2e-6)
    assert w.shape==(2,3,4,7)
    torch.testing.assert_close(w.sum(-1),torch.ones(2,3,4))


def test_offset_causal_mask():
    mask=s.causal_mask(2,t_key=5,past=3)
    assert mask.shape==(2,5)
    torch.testing.assert_close(mask[0,:4],torch.zeros(4))
    assert torch.isneginf(mask[0,4])
    torch.testing.assert_close(mask[1],torch.zeros(5))


def test_future_changes_do_not_change_past_outputs():
    generator=torch.Generator().manual_seed(303)
    q=torch.randn(1,2,5,4,generator=generator)
    k=torch.randn(1,2,5,4,generator=generator)
    values=torch.randn(1,2,5,6,generator=generator)
    altered_k=k.clone();altered_k[:,:,3:]=100
    altered_v=values.clone();altered_v[:,:,3:]=-100
    mask=s.causal_mask(5)
    original,_=s.attention(q,k,values,mask)
    changed,w=s.attention(q,altered_k,altered_v,mask)
    torch.testing.assert_close(original[:,:,:3],changed[:,:,:3])
    assert w[...,torch.triu(torch.ones(5,5,dtype=torch.bool),1)].abs().sum()==0


def test_padding_keys_do_not_influence_outputs():
    q=torch.randn(1,2,3,4)
    k=torch.randn(1,2,5,4)
    values=torch.randn(1,2,5,6)
    mask=torch.tensor([0.,0.,0.,-math.inf,-math.inf]).view(1,1,1,5)
    altered_k=k.clone();altered_k[:,:,3:]=100
    altered_v=values.clone();altered_v[:,:,3:]=-100
    original,_=s.attention(q,k,values,mask)
    changed,_=s.attention(q,altered_k,altered_v,mask)
    torch.testing.assert_close(original,changed)


def test_all_masked_rows_have_zero_weights_and_output():
    q=torch.ones(1,1,2,4,requires_grad=True)
    k=torch.ones(1,1,3,4)
    values=torch.ones(1,1,3,5)
    mask=torch.tensor([[0.,0.,0.],[-math.inf,-math.inf,-math.inf]])
    actual,w=s.attention(q,k,values,mask)
    assert torch.isfinite(actual).all() and torch.isfinite(w).all()
    torch.testing.assert_close(w[0,0,0].sum(),torch.tensor(1.))
    assert w[0,0,1].abs().sum()==0 and actual[0,0,1].abs().sum()==0
    actual.sum().backward();assert torch.isfinite(q.grad).all()


def test_shift_includes_EOS_target():
    inputs,labels=s.next_token_pairs(torch.tensor([[4,0,1,2,5]]))
    assert inputs.tolist()==[[4,0,1,2]] and labels.tolist()==[[0,1,2,5]]


def test_padding_loss_and_zero_gradient():
    torch.manual_seed(304)
    logits=torch.randn(1,3,7,requires_grad=True)
    labels=torch.tensor([[0,6,2]])
    actual=s.masked_cross_entropy(logits,labels,ignore_index=6)
    expected=F.cross_entropy(logits[:,[0,2]].reshape(-1,7),torch.tensor([0,2]))
    torch.testing.assert_close(actual,expected)
    actual.backward();assert logits.grad[:,1].abs().sum()==0


def test_all_ignored_loss_is_differentiable_zero():
    logits=torch.randn(1,2,7,requires_grad=True)
    actual=s.masked_cross_entropy(logits,torch.full((1,2),6),ignore_index=6)
    assert actual.item()==0 and actual.requires_grad
    actual.backward();assert logits.grad.abs().sum()==0
