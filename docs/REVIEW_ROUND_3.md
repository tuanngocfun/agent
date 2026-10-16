# Round-three review: preserve the failed run and separate decoder repair from method evaluation

The supplied Sonnet and Gemini reviews were checked against the official artifact from [run 38781747009](https://github.com/tuanngocfun/agent/actions/runs/38781747009), its registered source and the pinned Ollama implementation. The measured campaign is preserved under [reports/robustness-v2-2026-10-15](../reports/robustness-v2-2026-10-15/README.md). No proposed patch was applied to the historical v2 execution source.

The reproduced result is **47/54 observed, zero task-correct, 44 task failures, three provider failures, seven missing and zero invalid evidence**. All 47 supplied records have internally consistent evidence; that is different from a successful repair. The official ZIP's SHA256 matches GitHub's artifact digest. An independent reconstruction reproduced the summary except machine-local shard paths, and reproduced all three CSVs and the generated report byte-for-byte. [Audit proof](../reports/robustness-v2-2026-10-15/independent-reproduction-audit.json).

## Confirmed findings

| Finding | Observed evidence | Implication |
|---|---|---|
| Four workers stopped before completing their cells | Shards 0/1/2/4 recorded the 180-second start-reserve error and incomplete coverage; counts were 10/11, 9/11, 8/11 and 9/10. Shard 3 completed 11/11. | Seven registered cells remain missing. Changing a duration limit is an amendment, not grounds to fill or remove old cells. |
| The edit-value schema was incompatible with the pinned grammar converter | Our historical schema used `value: {}`. The pinned converter selects an object for an empty schema; all 128 edits in 63 parseable decisions had dictionary values. | This is a major harness defect. The run cannot fairly rank the underlying agent methods. |
| Provider timeouts occurred, but returned-response truncation was rare | 84 calls: 64 raw replies, of which 63 ended `stop` and one ended `length`; 20 calls returned no raw response and recorded timeout errors. | Three whole-trial provider failures must not be confused with 20 individual request timeouts. Widespread output truncation is not supported. |
| Some feedback check names lost their leaf field | A 107-character init-container check was projected into a name ending `securityConte`; another projected name ended `securityContext/a`. | Preserve useful check identity in an amended projection. Other admission text still named the required field, so the causal effect on correctness is not isolated. |
| Job edits were not all equivalent | Of 57 emitted Job edits, 12 exactly repeated the cumulative candidate value; 45 changed booleans, integers, lists or strings into dictionaries. | Avoid saying all 57 necessarily triggered immutable-Job updates. The changed values were already invalid for their intended fields. |
| The cumulative allowance was almost consumed | As of the saved 2026-10-16 02:32:25 UTC ledger: 957 per-job rounded minutes, zero unfinished jobs, 43 minutes remaining under the authorized 1,000. | The earlier 233-minute balance is stale. A 230-minute rerun does not fit. |

The source finding uses directly verified tagged contents rather than cached line numbers. Ollama `v0.6.8` resolves to commit `6a74bba7e7e19bf5f5aeacb039a1537afa3522a5`; the server calls `SchemaToGrammar` at [server.go:742](https://github.com/ollama/ollama/blob/6a74bba7e7e19bf5f5aeacb039a1537afa3522a5/llm/server.go#L741-L746), and the converter's empty-schema branch is at [json-schema-to-grammar.cpp:966–967](https://github.com/ollama/ollama/blob/6a74bba7e7e19bf5f5aeacb039a1537afa3522a5/llama/llama.cpp/common/json-schema-to-grammar.cpp#L966-L967). The review's cached line anchors 913/690 did not match the directly fetched files. Commit, blob and SHA256 identities are saved in [decoder-source-evidence.json](../reports/robustness-v2-2026-10-15/decoder-source-evidence.json).

The independent [raw decoder audit](../reports/robustness-v2-2026-10-15/raw-decoder-audit.json) records request identities and response hashes. Parseable decisions comprise 49 patch, 11 finish and three abstain actions. Of the 45 changed Job values, prior types were 22 booleans, 14 integers, four lists and five strings. No frozen task score changed during this inspection.

## Hypotheses that require a separate diagnostic

**Grammar bounds caused severe slowdown.** The supplied reviews attribute latency to `maxLength: 2000` and `maxItems: 64`. Their presence is visible, but the historical run does not isolate their timing effect. It is appropriate to compare decoder-only variants under fixed prompts, model, output limit and hardware. It is not appropriate to claim a measured speedup or a specific number of grammar states without that evidence.

**A 256-token output ceiling was the dominant failure.** One returned response was truncated. That one failure is real, but it cannot explain the other 63 raw replies or the universal dictionary-valued edits. A larger ceiling might help particular responses; it is not a demonstrated general remedy and would also change the call budget.

**Second-round wording caused incorrect `finish` decisions.** Clear acknowledgement that no edits were applied after a rejected proposal is a reasonable improvement. The existing sequence alone does not prove that wording caused a later action. The decoder defect and request failures are competing explanations; preserve identical task information across comparison arms.

**Early RBAC stopping would improve the experiment.** A protected Job can log authorization failures while retrying. Earlier feedback might reduce waiting, but its stopping rule changes which runtime observations the model receives. It needs an explicit, tested rule that preserves successful API behavior, deny checks and final independent verification; static failure alone is not a substitute for application evidence.

**Longer workers would complete the matrix.** More time would likely improve coverage, but the reviews' estimates are not a guarantee. The saved worker durations are 1,658.780, 1,644.841, 1,594.233, 1,544.953 and 1,609.442 seconds for shards 0–4. Exact job and trial measurements are in the report. Increasing only the deadline would leave the edit-value defect intact.

## Proposals rejected for this historical run

| Proposal | Reason |
|---|---|
| Apply the 230-minute full-rerun patch against the old 233-minute balance | Only 43 conservative minutes remained at the recorded cutoff. A static test accepting a 230-minute plan does not restore spent authorization. |
| Treat unchanged case-to-shard assignment as an unchanged experiment | Source, timeouts, prompts, decoding or feedback changes alter the registered protocol. A new source/plan and fresh validation are required; old and new records cannot be silently pooled. |
| Cap every repair at one or two edits | This can exclude legitimate multi-container or multi-resource repairs and turns a prompt convenience into an artificial method limit. Keep a general bounded surface and measure actual edits. |
| Add a task-specific `os.geteuid()==0` → abstain answer hint | That risks teaching the expected result for the benchmark's known infeasible case. Uniform security requirements and inspectable application evidence support a more informative comparison. |
| Reduce the start reserve to 75 seconds while allowing two long model calls | The longest observed trial was 243.191 seconds, and two 120-second provider calls can consume 240 seconds before runtime work and cleanup. A 75-second reserve cannot promise a complete cell. |
| Relax final security/application checks or remove failed/missing cells to improve figures | That would change the success definition or introduce selection bias. Every registered cell and the original zero-success result remain visible. |

The 180-second historical reserve also failed to guarantee a complete cell; replacing it with another unproved constant is insufficient. A future bounded scheduler should derive admission and cleanup reserves from the actual operation limits and remaining authorization. The review's 270-second suggestion is not a worst-case proof either.

## What a limited amendment should establish

A separate decoder diagnostic should first establish that boolean, integer, string, list, object and null edit values can be generated and parsed as intended, with Python-side size/type validation still enforced. It should then demonstrate an independently verified runtime repair before another broad method comparison. Type-union decoding, prompt clarity, feedback projection, request limits and worker scheduling should be recorded as explicit changes rather than silently folded into v2.

The historical report does not claim that this amendment succeeded. Its [supplement](../reports/robustness-v2-2026-10-15/supplement/README.md) found zero raw re-audit disagreements and zero verified failed-runtime-feedback → changed-candidate → successful-primary-outcome sequences. It copies the frozen scores without alteration and retains all 54 registered rows.

No method winner follows from this run. The fixed template repaired 4/10 feasible cases, naive hardening repaired 2/10, and the protected oracle repaired 10/10. Those measured controls are useful; the faulty LLM decoder prevents attributing the gap to the merits of feedback, filtering, self-review or Qwen itself.

## Separately executed v3 diagnostic

[Run 38868589212](https://github.com/tuanngocfun/agent/actions/runs/38868589212) attempted all six registered calls on two reused cases. The [report](../reports/robustness-v3-2026-10-16/README.md) records **0/6 correct**, three task failures and three request timeouts. Both oracle controls passed and both no-op states failed. The corrected decoder emitted two Boolean values, but both edits were redundant and left the failing security fields unresolved. Returned calls spent most of their server time evaluating prompts; no stable bound-removal speedup or agent-method winner was demonstrated.

A new integration defect was also found: the frozen reporter retained three `robust-v2-` namespace guards while the v3 runtime used `robust-v3-`. The original reporting refusal is retained. A separate [v3.1 offline auditor](../scripts/audit_robustness_v3_evidence.py) corrects those three prefix guards and records both script hashes; it leaves the frozen execution source, raw artifacts and security/application checks unchanged. Its actual replay verified all six records and all four controls. Five new regressions cover runtime/reporter namespace alignment and unchanged audit scope. This is an explicit post-hoc audit correction, not a successful original report step.
