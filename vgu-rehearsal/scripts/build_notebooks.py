"""Build four instructor notebooks; run_notebooks.py produces fresh saved outputs."""
from pathlib import Path
from textwrap import dedent
import nbformat as nbf

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'notebooks'


def md(text): return nbf.v4.new_markdown_cell(dedent(text).strip())
def code(text): return nbf.v4.new_code_cell(dedent(text).strip())


SETUP=code(r'''
from pathlib import Path
import sys, math, time, statistics, json
ROOT = Path.cwd().parent if Path.cwd().name == 'notebooks' else Path.cwd()
assert (ROOT / 'src/vgu_transformers.py').is_file(), 'Run from REHEARSAL_READY or its notebooks directory.'
sys.path.insert(0, str(ROOT / 'src'))
import torch
from torch import nn
import torch.nn.functional as F
import matplotlib.pyplot as plt
from IPython.display import display
import vgu_transformers as vgu
from vgu_transformers import *
torch.manual_seed(9)
torch.set_num_threads(1)
FIGURES=ROOT/'verification/figures'
FIGURES.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,
                     'axes.spines.top':False,'axes.spines.right':False,
                     'figure.facecolor':'white','axes.facecolor':'white'})
print('PyTorch:',torch.__version__,'| device: CPU | threads:',torch.get_num_threads())
print('Actual imported source:',Path(vgu.__file__).resolve().relative_to(ROOT))
assert Path(vgu.__file__).resolve()==(ROOT/'src/vgu_transformers.py').resolve()
''')


def save(name,cells):
    nb=nbf.v4.new_notebook(cells=cells,metadata={
        'kernelspec':{'display_name':'VGU rehearsal (CPU)','language':'python','name':'vgu-rehearsal'},
        'language_info':{'name':'python'},
        'rehearsal':{'role':'instructor_worked','student_exercises':'student_exercises/'}})
    OUT.mkdir(parents=True,exist_ok=True)
    nbf.write(nb,OUT/name)


def build():
    save('01_Core_Attention_Worked.ipynb',[
    md(r'''
    # 01 · Core attention: from tokens to a next-token objective

    **Instructor worked notebook · 15–20 minute demonstration, with pauses for predictions.**
    Main question: how can a token choose relevant context while training on many positions at once?
    The interview's 30-minute teaching session uses selected cells from notebooks 01–02; it does not require running every optional lab.

    By the end, a learner should trace token IDs and embeddings; calculate a weighted value;
    distinguish a mask from attention probabilities; and explain why shifted labels and causal masking are both needed.
    Numbers below are synthetic teaching inputs. They do not establish what a trained model understands.
    '''),SETUP,
    md(r'''
    ## 1. Text → tokens → integer IDs → vectors

    Our tiny whitespace vocabulary makes the mapping visible. Real tokenizers may split a word into multiple subword tokens.
    An integer ID indexes a learned embedding row; it is not a measure of word meaning or word order.
    IDs are local to this lab: BOS=4, I=0, love=1, AI=2, EOS=5, and PAD=6; another tokenizer may use different IDs.
    **Ask:** if we permute IDs and permute embedding rows consistently, must the model's represented input change?
    '''),
    code(r'''
    vocabulary={'I':0,'love':1,'AI':2,'<unused>':3,'BOS':BOS,'EOS':EOS,'PAD':PAD}
    tokens=['BOS','I','love','AI','EOS']
    ids=torch.tensor([[vocabulary[token] for token in tokens]])
    embedding=nn.Embedding(len(vocabulary),4)
    vectors=embedding(ids)
    print('tokens:',tokens)
    print('IDs:',ids.tolist(),'shape:',tuple(ids.shape))
    print('embedding shape [batch, token position, features]:',tuple(vectors.shape))
    print('first two embedding vectors (random initialization):\n',vectors[0,:2].detach())
    assert ids.tolist()==[[4,0,1,2,5]] and vectors.shape==(1,5,4)
    '''),
    md(r'''
    ## 2. A numerical attention calculation you can teach on paper

    Queries describe what is being sought, keys describe what can match, and values supply the information to combine.
    With $Q=[1,0]$, $K=[[1,0],[0,1]]$, $V=[[2,0],[0,4]]$, and $d_k=2$:

    $$s=QK^T/\sqrt{d_k}=[1/\sqrt2,0],\quad a=\mathrm{softmax}(s),\quad z=aV.$$

    **Predict before running:** the first key gets more weight, but its value does not simply replace the second value.
    Scaling controls score magnitude before softmax; it is not a probability normalization by itself.
    '''),
    code(r'''
    q=torch.tensor([[1.,0.]])
    k=torch.eye(2)
    values=torch.tensor([[2.,0.],[0.,4.]])
    output,weights=scaled_dot_product_manual(q,k,values)
    expected_first=math.exp(1/math.sqrt(2))/(math.exp(1/math.sqrt(2))+1)
    torch.testing.assert_close(weights,torch.tensor([[expected_first,1-expected_first]]))
    torch.testing.assert_close(output,torch.tensor([[1.3395231,1.3209538]]),atol=1e-6,rtol=1e-6)
    print('scaled scores:',(q@k.T/math.sqrt(2)).tolist())
    print('weights:',weights.tolist(),'row sum:',weights.sum(-1).tolist())
    print('weighted value:',output.tolist())
    print('Four-decimal teaching answer:',[round(x,4) for x in output[0].tolist()])
    '''),
    md(r'''
    ## 3. Distinct dimensions expose shape mistakes

    Let $B=2$, $H=3$, target/query length $T=5$, source/key length $S=7$, key dimension $d_k=4$, and value dimension $d_v=6$.
    Self-attention uses the same sequence as context; cross-attention uses a potentially different source sequence.

    | Quantity | Cross-attention shape |
    |---|---|
    | Q | [2,3,5,4] |
    | K | [2,3,7,4] |
    | V | [2,3,7,6] |
    | QKᵀ and weights | [2,3,5,7] |
    | weighted values | [2,3,5,6] |

    The score matrix indexes **query positions × key positions**. Here $d_v$ differs deliberately from $d_k$;
    common implementations often choose them equal. Head outputs concatenate before an output projection.
    '''),
    code(r'''
    B,H,T,S,dk,dv=2,3,5,7,4,6
    q=torch.randn(B,H,T,dk); k=torch.randn(B,H,S,dk); values=torch.randn(B,H,S,dv)
    output,weights=scaled_dot_product_manual(q,k,values)
    reference=F.scaled_dot_product_attention(q,k,values,dropout_p=0.)
    torch.testing.assert_close(output,reference,atol=2e-6,rtol=2e-6)
    assert weights.shape==(B,H,T,S) and output.shape==(B,H,T,dv)
    merged=output.transpose(1,2).contiguous().reshape(B,T,H*dv)
    projected=nn.Linear(H*dv,H*dk)(merged)
    print('Q, K, V:',tuple(q.shape),tuple(k.shape),tuple(values.shape))
    print('weights:',tuple(weights.shape),'output:',tuple(output.shape))
    print('concatenated heads:',tuple(merged.shape),'output projection:',tuple(projected.shape))
    print('Maximum manual-vs-PyTorch difference:',float((output-reference).abs().max()))
    '''),
    md(r'''
    ## 4. A causal mask is not a probability matrix

    An additive mask is $0$ for permitted keys and $-\infty$ for forbidden keys. It is added to **scores**.
    Softmax over keys produces probabilities. Only those weights must sum to one for a row with a visible key.
    Below, all unmasked scores are zero so that the effect of the mask is isolated.
    **Ask:** why can the last position use all earlier input tokens, while the first uses only itself?
    '''),
    code(r'''
    mask=causal_additive_mask(4)
    causal_weights=torch.softmax(torch.zeros(4,4)+mask,dim=-1)
    print('Additive mask (0 allowed; -inf forbidden):\n',mask)
    print('Softmax weights:\n',causal_weights)
    print('Weight row sums:',causal_weights.sum(-1).tolist())
    assert torch.all(causal_weights[torch.triu(torch.ones(4,4,dtype=torch.bool),1)]==0)
    torch.testing.assert_close(causal_weights.sum(-1),torch.ones(4))
    fig,ax=plt.subplots(figsize=(6.8,4.8),layout='constrained')
    im=ax.imshow(causal_weights.numpy(),vmin=0,vmax=1,cmap='Blues')
    for i in range(4):
        for j in range(4):
            ax.text(j,i,f'{causal_weights[i,j]:.2f}',ha='center',va='center',
                    color='white' if causal_weights[i,j]>.65 else '#15263b')
    ax.set(xticks=range(4),yticks=range(4),xlabel='Key / context position',ylabel='Query / prediction position',
           title='Causal attention probabilities · zero unmasked scores')
    fig.colorbar(im,ax=ax,label='Attention probability',shrink=.85)
    fig.savefig(FIGURES/'attention_weights.png',dpi=160)
    display(fig);plt.close(fig)
    '''),
    md(r'''
    ## 5. Shifted supervision and cross-entropy

    For `[BOS, I, love, AI, EOS]`, inputs are `[BOS, I, love, AI]` and labels are `[I, love, AI, EOS]`.
    The shift asks each position to predict its next token. The mask prevents access to future **input** positions.
    These are distinct operations.

    For logits $[\ln2,0,0]$ and target **index 2**, probabilities are $[1/2,1/4,1/4]$.
    Thus loss $-\ln(1/4)=\ln4$ nats per token, and perplexity $e^{\ln4}=4$.
    This is one artificial token, not a language model's reported benchmark perplexity.
    '''),
    code(r'''
    decoder_inputs,labels=next_token_pairs(ids)
    print('decoder inputs:',decoder_inputs.tolist(),'labels:',labels.tolist())
    logits=torch.tensor([[[math.log(2),0.,0.]]])
    target=torch.tensor([[2]])
    loss=masked_lm_loss(logits,target,ignore_index=-100)
    print('probabilities:',torch.softmax(logits,-1).tolist())
    print('cross-entropy (nats/token):',float(loss),'perplexity:',float(loss.exp()))
    assert decoder_inputs.tolist()==[[4,0,1,2]] and labels.tolist()==[[0,1,2,5]]
    assert math.isclose(float(loss),math.log(4),abs_tol=1e-6)
    assert math.isclose(float(loss.exp()),4.,abs_tol=1e-6)
    '''),
    md('''
    ## Exit ticket and why this is worth learning

    Explain which axis is normalized; why values may have a different feature dimension from keys;
    and why shifting labels does not replace the causal mask.
    These skills transfer to debugging decoder training, interpreting tensor traces, and implementing cross-attention in translation or image-to-sequence systems.
    In notebook 02 we test that changing future or padding tokens cannot change a permitted output.
    For a project, implement the separate student exercise API and its invariance tests before replacing toy inputs with real data.

    **Conceptual references:** the linked reading list in the lecture materials provides the Transformer paper and PyTorch documentation.
    The numerical calculations here are completely specified by the cells above; no external download is required.
    ''')])

    save('02_Training_and_Generation_Worked.ipynb',[
    md(r'''
    # 02 · Training safeguards and actual sequence generation

    **Instructor worked notebook · select 8–10 minutes for the interview; use the rest in a follow-up lab.**
    Question: how do we distinguish a useful training objective, correct information flow, and a search decision?
    Predictions, assertions, raw outputs, and interpretation are kept together. All controls are synthetic and completely declared.
    '''),SETUP,
    md(r'''
    ## 1. Test causality by changing the future

    A triangular picture alone cannot prove the implementation uses the mask correctly.
    Change keys and values at positions 3–4 by a large amount and verify that outputs at positions 0–2 do not change.
    The unmasked control should change; otherwise the experiment would not diagnose the mask.
    '''),
    code(r'''
    q=torch.randn(1,2,5,4); k=torch.randn(1,2,5,4); values=torch.randn(1,2,5,6)
    altered_k=k.clone();altered_k[:,:,3:]=100.
    altered_values=values.clone();altered_values[:,:,3:]=-100.
    mask=causal_additive_mask(5)
    original,w=scaled_dot_product_manual(q,k,values,mask)
    changed,_=scaled_dot_product_manual(q,altered_k,altered_values,mask)
    unmasked,_=scaled_dot_product_manual(q,k,values)
    unmasked_changed,_=scaled_dot_product_manual(q,altered_k,altered_values)
    causal_diff=float((original[:,:,:3]-changed[:,:,:3]).abs().max())
    control_diff=float((unmasked[:,:,:3]-unmasked_changed[:,:,:3]).abs().max())
    print('earlier-output max difference with causal mask:',causal_diff)
    print('earlier-output max difference without mask:',control_diff)
    torch.testing.assert_close(original[:,:,:3],changed[:,:,:3])
    assert control_diff>1 and w[...,torch.triu(torch.ones(5,5,dtype=torch.bool),1)].abs().sum()==0
    '''),
    md(r'''
    ## 2. Padding keys, fully blocked queries, and gradients

    A padding **key** mask prevents invalid source positions from contributing to attention.
    Here our explicit all-masked policy is zero weights and zero output; it avoids NaNs but is an implementation choice.
    Valid rows sum to one. Fully blocked rows sum to zero and should not be treated as valid predictions.
    Additive masks are used throughout this teaching API; boolean conventions vary between PyTorch attention APIs.
    '''),
    code(r'''
    q=torch.randn(1,2,3,4,requires_grad=True)
    k=torch.randn(1,2,5,4); values=torch.randn(1,2,5,6)
    padding_mask=torch.tensor([0.,0.,0.,-math.inf,-math.inf]).view(1,1,1,5)
    original,_=scaled_dot_product_manual(q,k,values,padding_mask)
    changed_k=k.clone();changed_k[:,:,3:]=99.
    changed_v=values.clone();changed_v[:,:,3:]=-99.
    changed,_=scaled_dot_product_manual(q,changed_k,changed_v,padding_mask)
    torch.testing.assert_close(original,changed)
    print('padding-key perturbation max difference:',float((original-changed).detach().abs().max()))
    all_blocked=torch.full((3,5),-math.inf)
    zero,zero_weights=scaled_dot_product_manual(q,k,values,all_blocked)
    zero.sum().backward()
    print('all-blocked weights sum:',float(zero_weights.detach().sum()),
          'output sum:',float(zero.detach().sum()),'query gradient norm:',float(q.grad.norm()))
    assert torch.isfinite(zero).all() and torch.isfinite(q.grad).all()
    assert zero.abs().sum()==0 and zero_weights.abs().sum()==0 and q.grad.abs().sum()==0
    '''),
    md(r'''
    ## 3. Loss padding is a separate operation

    `ignore_index=PAD` removes padding labels from the mean cross-entropy and gives those logits zero loss gradient.
    It does not add an attention mask. Our all-ignored-label policy is a differentiable zero loss.
    In a real training loop, report supervised token counts and usually avoid optimizing an empty batch.
    '''),
    code(r'''
    logits=torch.randn(1,3,7,requires_grad=True)
    labels=torch.tensor([[0,PAD,2]])
    loss=masked_lm_loss(logits,labels,ignore_index=PAD)
    independent=F.cross_entropy(logits[:,[0,2]].reshape(-1,7),torch.tensor([0,2]))
    torch.testing.assert_close(loss,independent)
    loss.backward()
    print('supervised tokens:',int(labels.ne(PAD).sum()),'loss:',float(loss.detach()))
    print('ignored-position loss gradient:',logits.grad[:,1].tolist())
    assert logits.grad[:,1].abs().sum()==0
    empty_logits=torch.randn(1,2,7,requires_grad=True)
    empty=masked_lm_loss(empty_logits,torch.full((1,2),PAD),ignore_index=PAD)
    empty.backward()
    print('all-ignored loss:',float(empty.detach()),'total gradient:',float(empty_logits.grad.abs().sum()))
    assert empty.item()==0 and empty.requires_grad and empty_logits.grad.abs().sum()==0
    '''),
    md(r'''
    ## 4. Actually run greedy and beam search on a counterexample

    Fix a **two-token horizon**, with no EOS in this control. The first distribution is $P(A)=0.6$, $P(B)=0.4$.
    After A, $P(X|A)=P(Y|A)=0.5$; after B, $P(X|B)=1$.
    The complete sequence probabilities are AX=0.30, AY=0.30, BX=0.40.

    We feed these distributions through the same generation functions used by the image-to-sequence demo.
    Beam width is **3**, length exponent **alpha=0**, so ranking uses the raw sum of log probabilities.
    Ties under A may choose X or Y; both have probability 0.30. The current PyTorch argmax control selects X.
    **Ask:** why does the locally best first token lose here? Does a higher model score establish real-world correctness?
    '''),
    code(r'''
    from teaching_demos import FixedHorizonTree, EOSControl, sequence_log_probability
    tree=FixedHorizonTree(); dummy=torch.zeros(1,1,1,5,5)
    greedy=greedy_generate(tree,dummy,max_len=2)[0].tolist()
    beam,beam_logscore=beam_generate_one(tree,dummy,beam_width=3,alpha=0.,max_len=2)
    names={0:'A',1:'B',2:'X',3:'Y',BOS:'BOS',EOS:'EOS',PAD:'PAD'}
    greedy_probability=math.exp(sequence_log_probability(tree,dummy,greedy))
    beam_probability=math.exp(beam_logscore)
    print('greedy tokens:',[names[t] for t in greedy],'joint probability:',greedy_probability)
    print('beam width 3, alpha 0:',[names[t] for t in beam],'joint probability:',beam_probability)
    assert greedy==[BOS,0,2] and beam==[BOS,1,2]
    assert math.isclose(greedy_probability,.3,abs_tol=1e-6)
    assert math.isclose(beam_probability,.4,abs_tol=1e-6)
    assert math.isclose(beam_logscore,sequence_log_probability(tree,dummy,beam),abs_tol=1e-6)
    print('The observed result disproves universal greedy sequence optimality; it does not prove beam always finds a global optimum.')
    '''),
    md(r'''
    ## 5. EOS is a separate stopping rule

    The fixed-horizon control above intentionally excludes EOS. Now test two rows that finish at different times.
    Row 0 emits EOS immediately; row 1 emits `1, 1, EOS`. The finished row is padded while the other continues.
    Metrics remove the leading BOS and stop at the first EOS. Internal BOS or pre-EOS PAD remains a prediction error.
    '''),
    code(r'''
    result=greedy_generate(EOSControl(),torch.zeros(2,3,1,5,5))
    print('raw token rows:',result.tolist())
    print('metric token rows:',[tokens_before_eos(row) for row in result.tolist()])
    assert result.tolist()==[[BOS,EOS,PAD,PAD],[BOS,1,1,EOS]]
    assert tokens_before_eos([BOS,0,BOS,PAD,EOS])==[0,BOS,PAD]
    print('Internal special-token errors remain visible:',tokens_before_eos([BOS,0,BOS,PAD,EOS]))
    '''),
    md(r'''
    ## 6. Optional: temperature sampling from the same logits

    For each temperature, use the same base logits $\log[0.55,0.30,0.15]$ and compute softmax(logits/temperature).
    Lower temperature concentrates this distribution; it does not add evidence that the modal token is correct.
    Sample counts vary with the generator. A seed makes this demonstration repeatable in this environment.
    '''),
    code(r'''
    base_logits=torch.log(torch.tensor([.55,.30,.15]))
    for temperature in (.5,1.,2.):
        probabilities=torch.softmax(base_logits/temperature,-1)
        draws=torch.multinomial(probabilities,300,replacement=True,generator=torch.Generator().manual_seed(11))
        counts=torch.bincount(draws,minlength=3)
        print('temperature:',temperature,'probabilities:',[round(x,4) for x in probabilities.tolist()],
              '300 sample counts:',counts.tolist())
        assert counts.sum()==300 and probabilities.argmax()==0
    '''),
    md('''
    ## Exit ticket → a useful next project

    Explain why a padding loss mask does not protect attention, why a causal invariance test is stronger than a mask picture,
    and what objective beam search actually tries to improve.
    Implement the separate student API, make the invariance tests pass, then evaluate greedy/beam on the same held-out examples with an explicit stopping and length-normalization policy.
    Report both model score and task quality; diagnose their disagreements instead of assuming they coincide.
    ''')])

    save('03_Optional_Systems_Worked.ipynb',[
    md(r'''
    # 03 · Optional systems lab: RoPE, grouped keys/values, and caching

    **Optional follow-up, not required background for the 30-minute core lecture.**
    Learn to verify mathematical invariants and compare an optimization against an equivalent baseline.
    CPU timing depends on sequence length, interpreter overhead, hardware, and implementation. No speedup is promised.
    '''),SETUP,
    md(r'''
    ## 1. RoPE rotates paired features without changing their squared norm

    Position changes the rotation angle applied to queries and keys. It does not rotate values here.
    The same frequency convention must be used for Q and K. A cache must start new positions at the correct offset.
    '''),
    code(r'''
    x=torch.randn(2,4,9,8)
    rotated=rope(x,start_pos=0)
    offset=rope(x,start_pos=7)
    norm_error=float((rotated.square().sum(-1)-x.square().sum(-1)).abs().max())
    torch.testing.assert_close(rotated.square().sum(-1),x.square().sum(-1),atol=2e-6,rtol=2e-6)
    print('RoPE max squared-norm difference:',norm_error)
    print('rotation differs at shifted positions:',float((rotated-offset).abs().max()))
    print('2 new queries after 3 cached tokens use mask:\n',causal_additive_mask(2,t_key=5,past=3))
    '''),
    md(r'''
    ## 2. Full, token-cached, and chunk-cached outputs must agree

    With four query heads, compare one, two, and four KV heads. These correspond to shared, grouped, and per-head K/V.
    A cache stores prior K/V; it does not change which past tokens are visible. The full pass is an independent execution path.
    Chunk sizes 2, 3, and 4 exercise causal offsets beyond single-token decoding.
    '''),
    code(r'''
    torch.manual_seed(19)
    for kv_heads in (1,2,4):
        model=GQACausalAttention(d_model=32,n_heads=4,n_kv_heads=kv_heads).eval()
        x=torch.randn(2,9,32)
        with torch.no_grad():
            full=model(x)
            cache=None;token_outputs=[]
            for position in range(9):
                y,cache=model(x[:,position:position+1],past_kv=cache,use_cache=True)
                token_outputs.append(y)
            tokenwise=torch.cat(token_outputs,1)
            chunk_cache=None;chunks=[];start=0
            for length in (2,3,4):
                y,chunk_cache=model(x[:,start:start+length],past_kv=chunk_cache,use_cache=True)
                chunks.append(y);start+=length
            chunkwise=torch.cat(chunks,1)
        torch.testing.assert_close(full,tokenwise,atol=2e-6,rtol=2e-6)
        torch.testing.assert_close(full,chunkwise,atol=2e-6,rtol=2e-6)
        actual_bytes=sum(t.numel()*t.element_size() for t in cache)
        logical_bytes=kv_bytes(2,1,9,kv_heads,8,4)
        assert actual_bytes==logical_bytes
        print('KV heads:',kv_heads,'token error:',float((full-tokenwise).abs().max()),
              'chunk error:',float((full-chunkwise).abs().max()),'KV tensor bytes:',actual_bytes)
    '''),
    md(r'''
    ## 3. A declared CPU benchmark over three lengths

    Compare producing one output per prefix in both paths. The uncached path recomputes the whole growing prefix;
    the cached path only computes the new token and retains earlier K/V. Both use the same model and predetermined inputs.
    Use one warm-up per path and five timed repetitions per length, with one CPU thread and no gradients.
    Report medians in milliseconds. Ratios describe this local toy kernel only and need not exceed one.
    '''),
    code(r'''
    benchmark_model=GQACausalAttention(d_model=32,n_heads=4,n_kv_heads=2).eval()
    @torch.no_grad()
    def cached_decode(x):
        cache=None;parts=[]
        for position in range(x.shape[1]):
            y,cache=benchmark_model(x[:,position:position+1],past_kv=cache,use_cache=True)
            parts.append(y)
        return torch.cat(parts,1)
    @torch.no_grad()
    def uncached_decode(x):
        return torch.cat([benchmark_model(x[:,:position+1])[:,-1:] for position in range(x.shape[1])],1)
    timing_rows=[]
    for length in (8,32,64):
        x=torch.randn(1,length,32)
        torch.testing.assert_close(cached_decode(x),uncached_decode(x),atol=2e-6,rtol=2e-6)
        row={'length':length,'warmup_per_path':1,'repetitions':5}
        for name,method in [('cached_ms',cached_decode),('uncached_ms',uncached_decode)]:
            method(x)
            durations=[]
            for _ in range(5):
                start=time.perf_counter();method(x);durations.append(1000*(time.perf_counter()-start))
            row[name]=statistics.median(durations)
        row['uncached_over_cached']=row['uncached_ms']/row['cached_ms']
        timing_rows.append(row)
        print(json.dumps(row))
    (ROOT/'verification/cache_benchmark.json').write_text(json.dumps(timing_rows,indent=2)+'\n')
    print('Interpret the displayed ratios by length. They are observed local timings, not a universal cache speed claim.')
    '''),
    md('''
    ## Reasoning to take forward

    Explain why a wrong positional offset can invalidate a cache even when its shapes look correct.
    KV tensor bytes here exclude allocator overhead, model weights, activations, and intermediate repeated KV tensors.
    The reference GQA implementation repeats KV heads for clarity; it does not establish the performance of a fused serving kernel.
    A research extension varies sequence length, batch size, dtype, device, and KV-head count, checks output equivalence first,
    then reports timing distributions and total memory with the measurement policy stated.
    ''')])

    save('04_Optional_Image_to_Sequence_Worked.ipynb',[
    md(r'''
    # 04 · Optional image-to-sequence lab: an honest synthetic experiment

    **Optional project bridge · CPU · four known 5×5 glyph templates · fixed three-symbol sequences.**
    This is a controlled demonstration of a visual encoder, causal decoder, teacher forcing, and sequence evaluation.
    It is not evidence of real handwriting recognition, Chữ Nôm OCR, unseen-character generalization, or variable-length robustness.
    Training, test seeds, noise levels, decoding policies, and the baseline are declared before fitting.
    '''),SETUP,
    md(r'''
    ## 1. Declare the question, baseline, and held-out samples first

    Does a tiny encoder–decoder learn this fixed synthetic mapping? Compare it with a no-training nearest-template classifier.
    Both know the same four clean templates; the baseline classifies each position independently.
    Train on fresh noisy batches for **60 optimizer steps**, seed 11, batch 24, bit-flip noise 0.06.
    Test all three methods on the **same 16 cases**, seed 987001, noise 0.06.
    A predeclared stress set uses 16 cases, seed 987002, noise 0.25; it is not used for fitting or selecting checkpoints.
    Disjoint RNG seeds mean independently generated noise/examples, not unseen glyph classes or necessarily unseen label sequences.
    '''),
    code(r'''
    from teaching_demos import nearest_template_predict
    training={'steps':60,'batch':24,'seed':11,'noise':.06,'lr':.003}
    test_images,test_labels=make_glyph_batch(n=16,length=3,seed=987001,noise=.06)
    stress_images,stress_labels=make_glyph_batch(n=16,length=3,seed=987002,noise=.25)
    print('declared training:',training)
    print('test: n=16 sequences, 48 reference symbols, seed=987001, bit-flip noise=0.06')
    print('stress: n=16 sequences, 48 reference symbols, seed=987002, bit-flip noise=0.25')
    xi,yi=make_decoder_labels(test_labels[:2])
    print('two references:',test_labels[:2].tolist())
    print('shifted decoder inputs:',xi.tolist(),'targets (include EOS):',yi.tolist())
    model=GlyphSeq2Seq()
    preview=model(test_images[:2],xi)
    print('images [B,S,C,H,W]:',tuple(test_images[:2].shape),'logits [B,T,V]:',tuple(preview.shape))
    assert preview.shape==(2,4,7)
    '''),
    md(r'''
    ## 2. Fit and show the actual training loss

    The decoder predicts the next symbol while attending to visual source features.
    Training loss includes the EOS target and explicitly ignores PAD. Training loss is not held-out recognition accuracy.
    The curve below includes all 60 recorded values, without smoothing or a selected subsequence.
    '''),
    code(r'''
    start=time.perf_counter()
    model,losses=train_glyph_demo(**training)
    training_seconds=time.perf_counter()-start
    assert len(losses)==60 and all(math.isfinite(v) for v in losses)
    print('CPU training seconds:',round(training_seconds,3))
    print('first loss:',losses[0],'last loss:',losses[-1])
    print('loss values at steps 1, 10, 20, 30, 40, 50, 60:',[losses[i-1] for i in (1,10,20,30,40,50,60)])
    fig,ax=plt.subplots(figsize=(7.2,4.3),layout='constrained')
    ax.plot(range(1,61),losses,color='#2463a6',linewidth=2)
    ax.scatter([1,60],[losses[0],losses[-1]],color='#2463a6',s=28,zorder=3)
    ax.set(xlabel='Optimizer step',ylabel='Mean supervised-token cross-entropy (nats)',
           title='Synthetic glyph training · all 60 CPU steps',xlim=(1,60),ylim=(0,max(losses)*1.08))
    ax.grid(axis='y',color='#dce2e8',linewidth=.7)
    fig.savefig(FIGURES/'glyph_training_loss.png',dpi=160)
    display(fig);plt.close(fig)
    (ROOT/'verification/glyph_training_losses.json').write_text(json.dumps(losses,indent=2)+'\n')
    '''),
    md(r'''
    ## 3. Same examples, declared decoding, inspectable mistakes

    Greedy and beam width **3** use max **5 generated tokens** and stop at EOS.
    Beam length exponent is explicitly **alpha=0** (raw log-probability ranking).
    Normalize output by removing only a leading BOS and stopping at EOS; internal BOS/PAD errors are retained.
    Report character edit distance / **48 reference symbols** (CER) and correct full sequences / **16** (exact match).
    These labels have equal length, so token-weighted CER equals the mean per-sequence CER here.
    CER may exceed one because insertions count. Zero observed errors at n=16 does not establish zero population error.
    '''),
    code(r'''
    def compare_methods(images,labels,split):
        truths=labels.tolist()
        greedy_raw=greedy_generate(model,images,max_len=5).tolist()
        beam_raw=[beam_generate_one(model,images[i:i+1],beam_width=3,alpha=0.,max_len=5)[0]
                  for i in range(len(images))]
        predictions={'nearest_template':nearest_template_predict(images).tolist(),
                     'greedy':[tokens_before_eos(row) for row in greedy_raw],
                     'beam3_alpha0':[tokens_before_eos(row) for row in beam_raw]}
        report={}
        denominator=sum(len(row) for row in truths)
        for method,preds in predictions.items():
            edits=int(round(sum(cer(t,p)*len(t) for t,p in zip(truths,preds))))
            exact=sum(t==p for t,p in zip(truths,preds))
            row={'split':split,'method':method,'n_sequences':len(truths),
                 'reference_symbols':denominator,'edit_count':edits,'cer':edits/denominator,
                 'exact_count':exact,'exact_match':exact/len(truths)}
            report[method]=row
            print(json.dumps(row))
        print('All cases: index | reference | nearest-template | greedy | beam3')
        for i,t in enumerate(truths):
            print(i,t,predictions['nearest_template'][i],predictions['greedy'][i],predictions['beam3_alpha0'][i])
        errors=[{'index':i,'reference':t,'greedy':predictions['greedy'][i],'beam3':predictions['beam3_alpha0'][i]}
                for i,t in enumerate(truths)
                if t!=predictions['greedy'][i] or t!=predictions['beam3_alpha0'][i]]
        print('Neural-decoder error cases:',errors if errors else f'none observed in these {len(truths)} cases')
        print('Rows without EOS: greedy',sum(EOS not in row for row in greedy_raw),
              'beam3',sum(EOS not in row for row in beam_raw))
        return {'metrics':report,'references':truths,'predictions':predictions,'neural_errors':errors}
    test_report=compare_methods(test_images,test_labels,'declared_test_noise_0.06')
    '''),
    md(r'''
    ## 4. The predeclared harder noise check

    Evaluate the fitted model and baseline without additional training. This tests more pixel corruption of the **same four templates**.
    It remains distinct from unseen writers, new alphabets, changed segmentation, or real scan artifacts.
    Read the actual errors below; do not claim a beam improvement unless the same-case comparison shows it.
    '''),
    code(r'''
    stress_report=compare_methods(stress_images,stress_labels,'predeclared_stress_noise_0.25')
    evidence={'training':training,'training_seconds':training_seconds,'losses':losses,
              'decoding':{'beam_width':3,'alpha':0.,'max_generated_tokens':5},
              'declared_test':test_report,'predeclared_stress':stress_report}
    (ROOT/'verification/glyph_experiment.json').write_text(json.dumps(evidence,indent=2)+'\n')
    assert cer([0],[0,1,2])==2.
    assert tokens_before_eos([BOS,0,PAD,EOS])==[0,PAD]
    print('Metric sanity check: reference [0], hypothesis [0,1,2] -> CER',cer([0],[0,1,2]))
    print('Evidence saved with all references and predictions; no task-accuracy claim is inferred from training loss alone.')
    '''),
    md(r'''
    ## How to turn the toy into a research question

    Compare the actual baseline and neural results before deciding a Transformer is necessary.
    This toy has only four templates and 64 possible three-symbol label sequences; a nearest-template system can be strong.
    A useful next experiment declares an unfamiliar-writer or unfamiliar-template split, variable lengths, realistic corruptions,
    multiple training seeds, uncertainty, and a failure taxonomy before collecting results.
    Explain what the visual encoder contributes, what the target causal mask blocks, and why source cross-attention may see all source positions.
    Use real data only with a documented dataset, evaluation protocol, and provenance; this synthetic demo supplies none of that external evidence.
    ''')])
    print('Built four worked instructor notebooks in',OUT)

if __name__=='__main__': build()
