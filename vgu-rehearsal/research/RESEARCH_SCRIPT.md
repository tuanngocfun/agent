# Research orientation: rehearsal script

Repository edition. This script and `content/research_orientation.json` contain the same speaker notes. The planned presentation is **20 minutes**, followed by **10 minutes of Q&A**. Times include pauses and transitions; actual spoken delivery must be rehearsed and measured.

Public scholarly claims cite public sources. Personal records and administrative history are withheld from this repository. Individual contributions and future commitments require the candidate’s own factual confirmation. Proposed studies are not reported as completed results.

| Slide | Time | Topic |
|---|---|---|
| R01 | 00:00–01:00 | Reliable learning from limited document labels |
| R02 | 01:00–02:30 | Preparation through collaborative document research |
| R03 | 02:30–04:00 | Prior collaboration: recognizing mathematical structure |
| R04 | 04:00–06:00 | Three results, three meanings |
| R05 | 06:00–07:30 | Prior collaboration: expanding Nôm annotations |
| R06 | 07:30–09:00 | Research question: does structural agreement add evidence? |
| R07 | 09:00–11:00 | One controlled four-arm experiment |
| R08 | 11:00–13:00 | Build an evaluation set that can challenge the model |
| R09 | 13:00–15:00 | Success means quality, useful gain and feasible review |
| R10 | 15:00–17:00 | Annual research plan to agree with the supervisor |
| R11 | 17:00–18:30 | Research should strengthen teaching and service |
| R12 | 18:30–20:00 | First steps and decisions for discussion |

If short of time, shorten R02/R03 background; preserve R04 metric definitions, R07 primary comparison and R10 role expectations.

## R01 · Reliable learning from limited document labels

Planned duration: 1 minutes.

Good morning. I am Nguyen Tuan Ngoc. My proposed research direction is reliable learning for historical document recognition when detailed labels and expert time are limited. A page image is not yet searchable text. The system must locate characters, identify them and preserve meaningful structure. A recognition error can then become a training label for the next model, so we need evidence about label quality as well as model accuracy.

I will distinguish published collaborative results from the experiments I propose to conduct. I will first describe two research collaborations, then explain a controlled study of confidence and structural agreement. Finally, I will connect that study to teaching, service and the annual research expectations of this position. The practical question throughout is: what evidence would justify trusting the next step of the pipeline?

**Takeaway:** A useful research direction needs a measurable reliability question.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R02 · Preparation through collaborative document research

Planned duration: 1.5 minutes.

My research preparation includes collaborative work on document recognition. Public publisher records list me as a coauthor of the two papers shown here. I will describe their methods and group results, while keeping individual implementation ownership separate. A coauthor list supports participation in the publication record; it does not establish which person implemented each module.

The two projects raise related questions. Mathematical-expression recognition asks whether local symbol and relationship decisions form a correct complete structure. Historical-document annotation asks whether automatically assigned labels can support subsequent learning. In both cases an intermediate score can look strong while the complete task remains difficult. That is why I want to make the evaluation unit and the evidence boundary explicit.

For new work, I would begin by reproducing a baseline, checking the data split and examining actual errors before claiming an improvement. The common habit is asking what data a system saw, what its metric counts, which comparison is fair and what remains uncertain. These questions also matter in teaching. A student should learn how to question an impressive number and design a useful check, rather than treating the number as its own explanation.

**Takeaway:** Use the public research record accurately and keep individual ownership explicit.

Evidence: [ICDAR 2025 Workshops publisher record](https://link.springer.com/chapter/10.1007/978-3-032-09368-4_17); [ICDAR 2026 publisher abstract](https://link.springer.com/chapter/10.1007/978-3-032-36039-7_28).

## R03 · Prior collaboration: recognizing mathematical structure

Planned duration: 1.5 minutes.

The first collaboration concerns online handwritten mathematical expressions. Online input contains pen strokes; it is different from a photograph of a finished page. The task is more than identifying isolated symbols. A symbol can sit above, below or inside another structure, and those relationships change the meaning of the expression.

The reported pipeline uses BLSTM-based recognition, a two-dimensional CYK parser and line-of-sight filtering to form a candidate graph. Nodes represent symbols and edges represent possible relationships. An edge-feature graph attention model then predicts which links should be retained. The structural candidates restrict the problem, but an early symbol or segmentation error can still limit the final answer.

This is an important conceptual link to the trial lecture. Sequence models and graph models use different representations, but both must combine local evidence into a coherent structured output. The practical lesson is to evaluate that complete output, rather than stopping at a successful intermediate classifier. On the next slide I will show why two numbers from the same system can tell very different stories.

**Takeaway:** Correct local components do not automatically make a correct structured output.

Evidence: [ICDAR 2025 Workshops publisher record](https://link.springer.com/chapter/10.1007/978-3-032-09368-4_17); [Public author manuscript: Tables 2–3](https://arxiv.org/html/2511.02288v1).

## R04 · Three results, three meanings

Planned duration: 2 minutes.

These are the reported CROHME 2019 results for the BLSTM–CYK and line-of-sight configuration with EGAT. Table 2 reports 92.78 percent link accuracy. Table 3 reports 51.42 percent structure rate and 38.86 percent exact expression rate.

These metrics answer different questions. Link accuracy evaluates link predictions. Structure rate asks whether all the spatial relationships in an expression are correct. Exact expression rate asks whether the entire expression is recognized correctly. The unit of evaluation changes, and the complete-output requirement is stricter. Therefore, I should not say that the system recognizes almost 93 percent of whole expressions correctly.

Imagine a long expression with several related decisions. Many decisions can be right while a single wrong symbol or relationship makes the complete expression wrong. The reported numbers motivate looking at failure propagation and task-level quality; they do not by themselves identify a single causal explanation for every error.

The manuscript also compares stronger overall recognition systems, so I do not describe these results as state of the art. The supported contribution is the reported graph-based approach and its evaluated behavior. My research question moves from this lesson toward another intermediate object that can look convincing: an automatically assigned training label.

Pause here and ask yourself: if I quote a percentage, can the listener identify exactly what was counted?

**Takeaway:** Always identify the evaluation unit, configuration and test set.

Evidence: [Public author manuscript: Tables 2–3](https://arxiv.org/html/2511.02288v1); [ICDAR 2025 Workshops publisher record](https://link.springer.com/chapter/10.1007/978-3-032-09368-4_17).

## R05 · Prior collaboration: expanding Nôm annotations

Planned duration: 1.5 minutes.

The second collaboration concerns automatic character-level annotation of historical Nôm documents. The published abstract describes a detector, a radical-based recognizer using Ideographic Description Sequences, and an iterative update loop. It reports annotation coverage of 83.95 percent of character instances.

I keep the interpretation narrow: coverage describes the extent of the resulting annotation set. It is not the same as an independent human audit of label precision, and it is not end-to-end OCR accuracy. A pipeline can expand its label set while preserving systematic errors. If the next model learns from those errors, quantity alone is not enough.

That distinction motivates my proposed study. I want to test whether structural agreement supplies useful reliability information beyond recognition confidence. The next slides describe a proposed evaluation, rather than additional results already achieved.

**Takeaway:** More automatic labels require separate evidence about their correctness.

Evidence: [ICDAR 2026 publisher abstract](https://link.springer.com/chapter/10.1007/978-3-032-36039-7_28); Local candidate confirmation; evidence withheld from repository.

## R06 · Research question: does structural agreement add evidence?

Planned duration: 1.5 minutes.

The proposed question is whether structural agreement provides useful information beyond recognition confidence. Recognition confidence should score the assigned target label on the stored crop. It should not silently score a different top prediction and then attach that confidence to the assigned label.

The second signal is agreement between the predicted Ideographic Description Sequence and the sequence associated with the transcription character. Alignment and edit distance can make this agreement explicit. For nonempty sequences, a simple starting similarity is one minus edit distance divided by the longer sequence length. If both sequences are empty, the score is defined as zero and the case is flagged, because no usable identity evidence has been supplied.

Agreement is not independent verification: it is partly derived from the recognizer itself. Reviewed development labels are needed to learn and assess a mapping from these signals to pair correctness. The primary hypothesis is about a held-out learning improvement over recognizer-only weighting. A well-controlled finding of little added benefit would also be useful, especially if it identifies repeated characters, bad segmentation or shared model errors as the limiting cases.

**Takeaway:** A confidence score is a hypothesis about correctness until tested against independent labels.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R07 · One controlled four-arm experiment

Planned duration: 2 minutes.

The four arms make the question testable. U gives every selected instance equal weight. R uses the assigned-target recognition signal. A uses structural agreement. C combines both signals. For R, A and C, probability mappings are learned using the same reviewed development labels and the same book-grouped validation procedure. The mappings are locked before test evaluation.

Every arm uses one frozen candidate-label set. Initializations, random seeds, sampling, augmentation, update counts, invalid-target rules and stopping rules are matched. Only the weights change. The weighted loss is the sum of each instance loss multiplied by its weight, divided by the sum of weights. If the total weight is zero, the optimizer update is skipped. Otherwise, a division by zero would make a supposed learning improvement meaningless.

The primary comparison is C against R: does adding agreement help beyond recognition evidence? U and A explain the result but cannot replace an unfavorable primary finding. If agreement becomes constant after selection and A collapses to uniform weighting, that is a finding to report. We should not quietly change A's selected training examples to manufacture a difference.

At the initial scope, four arms with three matched seeds require twelve training runs, plus scoring, calibration and evaluation. The pilot must establish whether that resource request is feasible.

**Takeaway:** Change the proposed information source while holding the rest of the comparison fixed.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R08 · Build an evaluation set that can challenge the model

Planned duration: 2 minutes.

The data plan starts with a twenty-page development pilot. Its purpose is to test annotation instructions, identify ambiguity and measure time. It cannot establish that the full scientific comparison will have enough power. A subsequent reviewed study sample of approximately two hundred to three hundred pages is a proposed starting scope; final source diversity and sample size must follow the pilot and resource discussion.

Pages from the same book or edition can share layout, print style and near-duplicate content. I would therefore split by source and group related pages, rather than randomly mixing adjacent pages across training and test. There is another leakage risk: a previously trained checkpoint may already have seen the chosen pages. Renaming a split cannot erase that exposure. The protocol must audit it, obtain eligible new material or explicitly narrow its claim.

Human review must examine whole pages. Reviewing only high-confidence crops would miss detection failures and bias the quality estimate. The record should include page identity, boxes, transcription and normalization versions, model checkpoint, review status and provenance. Machine-assigned and reviewed labels must remain distinguishable.

Finally, web access does not establish redistribution rights. Image, transcription and annotation permissions need separate records. If images cannot be released, the project should document which code, metadata or labels can be shared under the actual terms.

**Takeaway:** A frozen test set is credible only when its source, exposure and gold labels are understood.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R09 · Success means quality, useful gain and feasible review

Planned duration: 2 minutes.

There are three distinct outcomes. First, does the combined policy improve recognition? I would report character error rate and the paired difference between C and R, with uncertainty that preserves book or page clustering. Three seeds describe some training variability, but are not three independent populations of historical documents. Before testing, the supervisor and team should agree what improvement is practically useful. An interval spanning that threshold is inconclusive; failure to show superiority is not proof of equivalence.

Second, do the scores actually identify correct character pairs? Pair quality must include localization and identity, with duplicates and missed characters counted. Coverage, precision and recall remain separate. Normalization rules and any modified character error metric must be versioned.

Third, can experts work faster while maintaining acceptable quality? Compare the same initial labels with and without confidence guidance, balance page difficulty and reviewer assignment, and measure inspection, correction, re-review and adjudication time. Independent quality assessment should be blinded where feasible.

The five-thousand-page ambition is conditional. At an assumed half hour of primary review per page, plus fifteen percent re-review and twenty percent coordination overhead, the proposal estimates three thousand four hundred and fifty team-hours. That is a planning calculation, not measured throughput. The pilot must replace it before a staffing or release commitment is made.

**Takeaway:** An improvement claim needs a defined benefit, uncertainty and a quality-constrained cost.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R10 · Annual research plan to agree with the supervisor

Planned duration: 2 minutes.

The job description sets substantial annual expectations: at least one journal article published as assigned by the supervisor, at least two articles in Scopus-indexed international conference proceedings each year, and research performance of 0.6 EIA under VGU's rules. I recognize these as employment expectations. A plan to write two PhD manuscripts over three years does not by itself meet them.

I would therefore agree an annual portfolio with the supervisor, combining contributions to assigned group projects with the longer-term methodological study. In the first quarter, the discussion should identify which existing projects are mature enough for near-term manuscripts, what contribution I can take responsibility for, and what data, review and compute resources are available. Quarterly reviews would track experiment completion, drafts, submissions, reviews and published outputs separately.

Submission is under our influence; acceptance and publication timing also depend on editors and reviewers. I should not promise guaranteed acceptance. The detailed EIA calculation and current venue indexing need confirmation under the university's applicable rules, rather than inference from a venue name.

The same plan should reserve time for teaching and administration, include an internal research seminar at least annually, and account for national and international conference presentations from the second year. The PhD development direction is three to five years, subject to supervision, admission, resources and a feasible scope.

**Takeaway:** A realistic annual portfolio acknowledges the JD and distinguishes plans from accepted outputs.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R11 · Research should strengthen teaching and service

Planned duration: 1.5 minutes.

The RTA role includes one hundred and twenty academic hours of teaching assistance each academic year, alongside research and service. My proposed approach is to make tutorials explain why the concept matters, show one complete example and then require students to test an idea themselves. For the Transformer topic, that means connecting the equation to a small attention calculation, connecting the calculation to code and connecting the code to a controlled student project.

A successful notebook run is evidence about execution, not proof that the student understands. I would ask the student to explain the mask, predict a changed output and debug a minimal error. I would also preserve a usable boundary between student exercises and instructor reference solutions, and keep examination material secure.

The service duties are concrete: check equipment and environments, maintain teaching materials, help screen and mark assessments, support visiting faculty and events, and co-supervise Bachelor work with an appropriate faculty member. Research practice can support those duties through reproducible environments, clear documentation and careful feedback. The plan must fit the advising lecturer's course and the programme's needs rather than assuming I independently set institutional policy.

**Takeaway:** Research habits become useful teaching when students can explain, test and repair their own reasoning.

Evidence: Local candidate confirmation; evidence withheld from repository.

## R12 · First steps and decisions for discussion

Planned duration: 1.5 minutes.

My first priority would be an agreed scope. In the first month I would clarify teaching and service responsibilities, assigned research projects, individual contributions and the data or compute resources that can actually be used.

During the first three months, the research milestones would be a reproduced baseline, a small reviewed pilot and a protocol with explicit success criteria. The pilot should resolve whether the review workload, source diversity and score variation justify the planned comparison. If the evidence supports a smaller study, I would narrow the claim and document the decision rather than substituting automatically generated pages for reviewed data.

The practical contribution I propose is a reliable cycle: understand the problem, build a baseline, make one controlled change, inspect failures and explain the evidence clearly. That cycle connects my research direction to the teaching demonstration and to students' later projects. I welcome questions about the study design, the interpretation of the published results and how to align the work with the group's annual priorities.

**Takeaway:** Agree ownership and resources, then make a small study produce inspectable evidence.

Evidence: Local candidate confirmation; evidence withheld from repository.

## Ten-minute research Q&A rehearsal

Practice the following explanations and allow the panel to ask follow-ups.

1. Why might agreement add information beyond model confidence? State the C–R comparison and accept a null result.
2. What exactly do 92.78% and 83.95% mean? State the evaluation unit and what each does not establish.
3. How will you control leakage and uncertainty? Explain source splits, checkpoint exposure and paired clustered comparisons.
4. How will the plan fit the role? Describe an agreed annual portfolio, realistic review capacity and the difference between submissions and published outputs.

Candidate rehearsal, individual contribution statements and professional eligibility are separate confirmations. No file-generation or notebook check certifies those actions.
