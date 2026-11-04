"""Original VGU-oriented educational implementations for sequence generation.
Uses PyTorch CPU; no course-specific reference solutions are reproduced.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass
from typing import Optional
import torch
from torch import nn
import torch.nn.functional as F


def causal_additive_mask(t_query: int, t_key: Optional[int] = None, past: int = 0,
                         device=None) -> torch.Tensor:
    """[Tq,Tk] additive mask; query t sees all keys <= past+t."""
    t_key = t_query + past if t_key is None else t_key
    qpos = torch.arange(past, past+t_query, device=device)[:,None]
    kpos = torch.arange(t_key, device=device)[None,:]
    return torch.where(kpos <= qpos, 0.0, float('-inf'))


def scaled_dot_product_manual(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor,
                              mask: Optional[torch.Tensor]=None):
    """q [...,Tq,d], k [...,Tk,d], v [...,Tk,dv]."""
    score = q @ k.transpose(-2, -1) / math.sqrt(q.shape[-1])
    if mask is not None:
        if mask.dtype == torch.bool:
            raise TypeError("Use an additive 0/-inf mask; boolean mask conventions differ across APIs.")
        score = score + mask
    # Chosen policy: an all-masked query has zero weights/output, not NaN.
    # All other rows retain the usual probability normalization.
    has_visible_key = ~torch.isneginf(score).all(dim=-1, keepdim=True)
    safe_score = torch.where(has_visible_key, score, torch.zeros_like(score))
    weights = torch.where(has_visible_key, torch.softmax(safe_score, dim=-1), 0.0)
    return weights @ v, weights


def next_token_pairs(ids: torch.Tensor):
    assert ids.ndim == 2 and ids.shape[1] >= 2
    return ids[:, :-1], ids[:, 1:]


def masked_lm_loss(logits: torch.Tensor, labels: torch.Tensor, *, ignore_index):
    """Mean CE over supervised tokens. Callers must explicitly select padding.

    Chosen empty-batch policy: differentiable zero when all labels are ignored.
    Loss masking alone does not supply decoder/source attention padding masks.
    """
    if not labels.ne(ignore_index).any():
        return logits.sum() * 0.0
    return F.cross_entropy(logits.reshape(-1,logits.shape[-1]),labels.reshape(-1),ignore_index=ignore_index)


def normalized_sequence_score(log_probs, alpha=1.0):
    """One possible length-normalization policy; not universally optimal."""
    return sum(log_probs) / (len(log_probs) ** alpha)


def cer(reference, hypothesis):
    """Levenshtein distance / len(reference); may exceed 1."""
    n,m=len(reference),len(hypothesis)
    prev=list(range(m+1))
    for i in range(1,n+1):
        curr=[i]+[0]*m
        for j in range(1,m+1):
            curr[j]=min(prev[j]+1,curr[j-1]+1,prev[j-1]+(reference[i-1]!=hypothesis[j-1]))
        prev=curr
    return prev[m]/max(1,n)


class RMSNorm(nn.Module):
    def __init__(self, d, eps=1e-6):
        super().__init__()
        self.scale=nn.Parameter(torch.ones(d));self.eps=eps
    def forward(self,x):
        return x*torch.rsqrt(x.square().mean(dim=-1,keepdim=True)+self.eps)*self.scale


class SwiGLU(nn.Module):
    def __init__(self, d, hidden):
        super().__init__()
        self.gate=nn.Linear(d,hidden,bias=False)
        self.up=nn.Linear(d,hidden,bias=False)
        self.down=nn.Linear(hidden,d,bias=False)
    def forward(self,x):
        return self.down(F.silu(self.gate(x))*self.up(x))


def rope(x: torch.Tensor, start_pos=0):
    """Rotary transform, x=[B,H,T,d] and d even, same q/k frequencies."""
    assert x.ndim==4 and x.shape[-1]%2==0
    d=x.shape[-1];t=x.shape[-2]
    i=torch.arange(0,d,2,device=x.device,dtype=torch.float32)
    theta=1.0/(10000.0**(i/d))
    angles=torch.arange(start_pos,start_pos+t,device=x.device,dtype=torch.float32)[:,None]*theta[None,:]
    cosine=torch.cos(angles).to(x.dtype).view(1,1,t,d//2)
    sine=torch.sin(angles).to(x.dtype).view(1,1,t,d//2)
    even,odd=x[...,::2],x[...,1::2]
    return torch.stack((even*cosine-odd*sine,even*sine+odd*cosine),dim=-1).flatten(-2)


class GQACausalAttention(nn.Module):
    """Group-query causal attention with deterministic full/cache equivalence.

    Does not include dropout; GQA repeats KV heads across groups of Q heads.
    """
    def __init__(self, d_model=16, n_heads=4, n_kv_heads=2, use_rope=True):
        super().__init__()
        assert d_model%n_heads==0 and n_heads%n_kv_heads==0
        self.d_model=d_model;self.h=n_heads;self.hk=n_kv_heads
        self.d=d_model//n_heads;self.use_rope=use_rope
        assert self.d%2==0
        self.wq=nn.Linear(d_model,n_heads*self.d,bias=False)
        self.wk=nn.Linear(d_model,n_kv_heads*self.d,bias=False)
        self.wv=nn.Linear(d_model,n_kv_heads*self.d,bias=False)
        self.wo=nn.Linear(d_model,d_model,bias=False)

    def forward(self,x,past_kv=None,use_cache=False):
        b,t,_=x.shape
        start=0 if past_kv is None else past_kv[0].shape[-2]
        q=self.wq(x).reshape(b,t,self.h,self.d).transpose(1,2)
        k=self.wk(x).reshape(b,t,self.hk,self.d).transpose(1,2)
        v=self.wv(x).reshape(b,t,self.hk,self.d).transpose(1,2)
        if self.use_rope:
            q,k=rope(q,start),rope(k,start)
        if past_kv is not None:
            k=torch.cat((past_kv[0],k),dim=-2)
            v=torch.cat((past_kv[1],v),dim=-2)
        kq=k.repeat_interleave(self.h//self.hk,dim=1)
        vq=v.repeat_interleave(self.h//self.hk,dim=1)
        m=causal_additive_mask(t,t_key=k.shape[-2],past=start,device=x.device)
        y,_=scaled_dot_product_manual(q,kq,vq,m)
        y=self.wo(y.transpose(1,2).contiguous().reshape(b,t,self.d_model))
        return (y,(k,v)) if use_cache else y


def kv_bytes(batch: int, layers: int, t: int, kv_heads: int, head_dim: int, bytes_per_element: int=2):
    return 2*batch*layers*t*kv_heads*head_dim*bytes_per_element


# Four synthetic symbol glyphs. All samples derived from these patterns.
_GLYPHS=torch.tensor([
    [[0,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,0,0,0,1],[0,1,1,1,0]],  # 0
    [[0,0,1,0,0],[0,1,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,1,1,1,0]],  # 1
    [[0,1,1,1,0],[1,0,0,0,1],[0,0,0,1,0],[0,0,1,0,0],[1,1,1,1,1]],  # 2
    [[1,1,1,1,0],[0,0,0,0,1],[0,1,1,1,0],[0,0,0,0,1],[1,1,1,1,0]],  # 3
],dtype=torch.float32)
BOS,EOS,PAD=4,5,6


def make_glyph_batch(n=32, length=3, seed=0, noise=0.06):
    """Inputs [B,S,1,5,5], token references [B,S]. Independence by RNG seed."""
    g=torch.Generator().manual_seed(seed)
    labels=torch.randint(0,4,(n,length),generator=g)
    clean=_GLYPHS[labels].unsqueeze(2)
    flip=(torch.rand(clean.shape,generator=g)<noise)
    images=torch.where(flip,1-clean,clean)
    return images.float(),labels


class GlyphSeq2Seq(nn.Module):
    """Small, trainable image-patch encoder + causal Transformer decoder."""
    def __init__(self,d_model=32,nhead=4):
        super().__init__()
        self.visual=nn.Sequential(nn.Conv2d(1,12,3,padding=1),nn.ReLU(),nn.Flatten(),nn.Linear(12*25,d_model))
        self.source_pos=nn.Embedding(16,d_model)
        self.target_embed=nn.Embedding(7,d_model)
        self.target_pos=nn.Embedding(16,d_model)
        decoder_layer=nn.TransformerDecoderLayer(d_model=d_model,nhead=nhead,
                  dim_feedforward=64,dropout=0.0,batch_first=True,norm_first=True)
        self.decoder=nn.TransformerDecoder(decoder_layer,num_layers=1)
        self.lm_head=nn.Linear(d_model,7)
    def encode(self,images):
        b,s,c,h,w=images.shape
        x=self.visual(images.reshape(b*s,c,h,w)).reshape(b,s,-1)
        return x+self.source_pos(torch.arange(s,device=x.device))[None,:,:]
    def decode(self,memory,token_prefix):
        t=token_prefix.shape[1]
        x=self.target_embed(token_prefix)+self.target_pos(torch.arange(t,device=token_prefix.device))[None,:,:]
        mask=torch.triu(torch.ones(t,t,device=token_prefix.device,dtype=torch.bool),1)
        return self.lm_head(self.decoder(tgt=x,memory=memory,tgt_mask=mask))
    def forward(self,images,token_prefix):
        return self.decode(self.encode(images),token_prefix)


def make_decoder_labels(labels):
    b,s=labels.shape
    bos=torch.full((b,1),BOS,device=labels.device,dtype=torch.long)
    eos=torch.full((b,1),EOS,device=labels.device,dtype=torch.long)
    full=torch.cat([bos,labels,eos],dim=1)
    return full[:,:-1],full[:,1:]


@torch.no_grad()
def greedy_generate(model,images,max_len=None):
    model.eval();memory=model.encode(images)
    max_len=max_len or images.shape[1]+2
    prefix=torch.full((images.shape[0],1),BOS,device=images.device,dtype=torch.long)
    finished=torch.zeros(images.shape[0],device=images.device,dtype=torch.bool)
    for _ in range(max_len):
        logits=model.decode(memory,prefix)[:,-1,:]
        nxt=logits.argmax(-1)
        nxt=torch.where(finished,torch.full_like(nxt,PAD),nxt)
        prefix=torch.cat([prefix,nxt[:,None]],dim=1)
        finished=finished | (nxt==EOS)
        if torch.all(finished):
            break
    return prefix


@torch.no_grad()
def beam_generate_one(model,image,beam_width=3,alpha=0.7,max_len=None):
    """Explicit pedagogical beam search; image is [1,S,1,5,5]."""
    assert image.shape[0]==1
    model.eval();memory=model.encode(image)
    max_len=max_len or image.shape[1]+2
    # (sequence, raw_sum_logprob)
    beam=[([BOS],0.0)]
    for _ in range(max_len):
        candidates=[]
        for seq,score in beam:
            if seq[-1]==EOS:
                candidates.append((seq,score));continue
            token_prefix=torch.tensor([seq],device=image.device)
            logp=F.log_softmax(model.decode(memory,token_prefix)[0,-1],dim=-1)
            for value,index in zip(*torch.topk(logp,beam_width)):
                candidates.append((seq+[int(index)],score+float(value)))
        # Ranking with normalized score is one declared search heuristic.
        beam=sorted(candidates,key=lambda item:item[1]/max(1,len(item[0])-1)**alpha,reverse=True)[:beam_width]
        if all(seq[-1]==EOS for seq,_ in beam):break
    return beam[0]


def tokens_before_eos(seq):
    seq=[int(x) for x in seq]
    if seq and seq[0]==BOS:
        seq=seq[1:]
    # Internal BOS and pre-EOS PAD remain visible as prediction errors.
    return seq[:seq.index(EOS)] if EOS in seq else seq


def evaluate_glyphs(model,images,labels,beam_width=None):
    truths=[list(x) for x in labels.tolist()]
    if beam_width is None:
        preds=[tokens_before_eos(row) for row in greedy_generate(model,images).tolist()]
    else:
        preds=[tokens_before_eos(beam_generate_one(model,images[i:i+1],beam_width=beam_width)[0]) for i in range(images.shape[0])]
    return {'cer':sum(cer(t,p) for t,p in zip(truths,preds))/len(truths),
            'exact_match':sum(t==p for t,p in zip(truths,preds))/len(truths),
            'samples':list(zip(truths[:3],preds[:3]))}


def train_glyph_demo(steps=50,batch=24,seed=11,noise=0.06,lr=0.003):
    torch.manual_seed(seed); torch.set_num_threads(1)
    model=GlyphSeq2Seq()
    opt=torch.optim.AdamW(model.parameters(),lr=lr)
    losses=[]
    for step in range(steps):
        model.train()
        images,labels=make_glyph_batch(batch,seed=seed*1000+step,noise=noise)
        xi,yi=make_decoder_labels(labels)
        logits=model(images,xi)
        loss=masked_lm_loss(logits,yi,ignore_index=PAD)
        opt.zero_grad();loss.backward();opt.step()
        losses.append(float(loss.detach()))
    return model,losses
