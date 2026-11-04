import math
import torch
from teaching_demos import FixedHorizonTree, EOSControl, nearest_template_predict, sequence_log_probability
from vgu_transformers import BOS, EOS, PAD, greedy_generate, beam_generate_one, make_glyph_batch


def test_actual_decoder_tree_disproves_greedy_sequence_optimality():
    model=FixedHorizonTree(); images=torch.zeros(1,1,1,5,5)
    greedy=greedy_generate(model,images,max_len=2)[0].tolist()
    beam,score=beam_generate_one(model,images,beam_width=3,alpha=0.,max_len=2)
    assert greedy==[BOS,0,2] and beam==[BOS,1,2]
    assert math.isclose(math.exp(sequence_log_probability(model,images,greedy)),.3,abs_tol=1e-6)
    assert math.isclose(math.exp(score),.4,abs_tol=1e-6)
    assert math.isclose(score,sequence_log_probability(model,images,beam),abs_tol=1e-6)


def test_eos_stops_individual_rows_and_preserves_padding():
    rows=greedy_generate(EOSControl(),torch.zeros(2,3,1,5,5)).tolist()
    assert rows==[[BOS,EOS,PAD,PAD],[BOS,1,1,EOS]]


def test_template_baseline_recovers_all_clean_known_templates():
    images,labels=make_glyph_batch(20,length=3,seed=22,noise=0.)
    assert torch.equal(nearest_template_predict(images),labels)
