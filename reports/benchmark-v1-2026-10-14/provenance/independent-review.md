# Independent final statistics review

Reviewed the downloaded complete report for frozen source `b5fc820e9ef857a82a0861132d5c41faef025002`. This review independently recalculated the primary arithmetic from the 96 raw records and the collected summary. It did not execute models, alter evidence, or rerun Kubernetes workloads.

| Model | Method | Correct trials /16 | Correct cases /8 | Repair cases /4 | Unchanged cases /2 | Abstention cases /2 |
|---|---|---:|---:|---:|---:|---:|
| Qwen2.5-Coder 1.5B | One-shot | 6 | 3 | 3 | 0 | 0 |
| Qwen2.5-Coder 1.5B | Feedback | 4 | 2 | 2 | 0 | 0 |
| Qwen2.5 1.5B | One-shot | 5 | 2 | 0 | 0 | 2 |
| Qwen2.5 1.5B | Feedback | 4 | 2 | 0 | 0 | 2 |
| Qwen2.5 3B | One-shot | 8 | 4 | 4 | 0 | 0 |
| Qwen2.5 3B | Feedback | 7 | 3 | 3 | 0 | 0 |

A correct case requires both registered executions to be correct. All case numerators, category denominators, trial numerators, and overall case Wilson 95% intervals match the independent recalculation. The 96 raw records have unique model/method/case/repetition identities and exactly match the summary trial identities.

There are 34 demonstrated correct trials: 25 repairs, eight appropriate abstentions, and one unchanged completion. Outcomes across all 96 trials are 28 budget exhausted, 25 repaired, 23 security failure, eight abstained, five infrastructure failure, four invalid evidence, two policy failure, and one unchanged. Coverage is 87 verified, four invalid evidence, five infrastructure failure, and zero missing. Collection completeness must not be described as 96 successfully audited trials.

The four invalid evidence trials all failed the generation timing equality check and already had unsuccessful observed outcomes. They are three Coder feedback trials and one 3B feedback trial. Any timing erratum should preserve the original report and state its limited effect; the original registered successful counts do not increase by accepting these failed trials.

The five infrastructure failures are all Qwen2.5 3B feedback non-repair trials interrupted by signal 14. They cannot be presented as ordinary model reasoning failures. The failed 3B feedback repair trial, file-new-path repetition zero, instead proposed disallowed fsGroup 65538, inspected app metadata, then exhausted its conservative token reservation; repetition one proposed the allowed fsGroup and repaired successfully.

The 384 fixed-control records have unique shard/case/control identities. Each control has 12 executions on each of eight cases. All-execution correct case totals are noop 2/8, naive 4/8, template 6/8, and author-provided oracle 8/8. These are repeated execution measurements, not 384 independent cases. Every LLM/controller group has fewer correct cases than the template baseline on this suite.

No group completed an unchanged case in both executions. General Qwen2.5 1.5B one-shot completed file-already-secure only once; the other execution explicitly abstained even while explaining that no changes were necessary. Thus 5/16 correct trials does not imply three correct cases. Preserving an already-correct configuration and issuing a correct completion action are separate observed properties under the registered controller contract.

Raw records report zero unauthorized effects and zero unnecessary changes. Interrupted records have no completed audit; their default flag values must not establish a verified absence of such effects. Cost, checks, and throughput summaries in the primary report include only the 87 evidence-verified trials, with explicit unavailable observations for the other nine. Those aggregate cost sums are not full campaign totals.

An additional repeatability limitation needs disclosure: registered tasks, initial evidence policy, and decoding settings are shared, but literal prompts are not identical between repetitions or methods. Each shard generates a UUID fixture image tag, which appears in the initial image evidence and base manifest; actual initial evidence hashes and first request hashes differ. Runtime verification evidence also varies. Repeated outcomes therefore describe repeated executions of the registered procedure, not a controlled test with byte-identical prompts.

The designed eight-case suite, two fixture families, related Qwen models, unequal action budgets, conservative byte-based token reservation, common shard deadline, CPU variation, and post-start case time remaining limit generalization and causal ranking. The data do not establish that feedback improves remediation or that a larger model is generally superior. They establish actual bounded execution outcomes and several concrete controller, completion, and infrastructure weaknesses.
