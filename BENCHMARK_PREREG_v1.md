# Benchmark preregistration v1 — co-PI review draft

- Draft date: 2026-07-19
- Status: `DRAFT_FOR_CO_PI_REVIEW_NOT_FROZEN`
- Generation authorization: `CLOSED`
- Benchmark results in this document: none
- Benchmark audio generated under this preregistration: none
- Foundation engineering evidence: one bounded SA3 Base run, reported only in
  Appendix A; it is not benchmark evidence
- Intended scientific unit: one model × one evaluation axis

This is a design document, not an experiment report. Every number below is a
planned sample size, fixed threshold, budget coefficient, provenance fact, or
explicitly labeled foundation engineering measurement; none is a benchmark
result. No benchmark audio generation may begin until a later append-only entry
in `DECISIONS.md` names this file, its exact SHA-256, all required companion
hashes, and
`BENCHMARK_PREREG_V1_FROZEN = YES`.

One project-local SA3 foundation run exists at this cutoff under the separate,
bounded D-0013/D-0014 authorization. Smokes A–D passed, including Smoke D's
single batch-one and single batch-four cost observations; Smoke E failed before
any resumed DiT transition, so D-0017 records the overall run as terminal
`FAIL_ESCALATED` and consumes the authorization. This does not authorize the
benchmark corpus or a retry. Full benchmark generation still requires a frozen
preregistration, adequate per-model cost calibration, and a later decision
stating `BENCHMARK_EXECUTION_AUTHORIZED = YES`; those gates remain closed.

## 1. Purpose, claims, and non-claims

The benchmark asks how text-to-music backbones fail under constraints with
deliberately different failure structures, whether a fixed prompt intervention
or best-of-N selection reduces those failures, and whether true intermediate
state adds useful action information beyond the prompt.

The three confirmatory axes are:

1. vocal versus instrumental satisfaction;
2. explicit tempo satisfaction; and
3. acoustic integrity.

Structure and repetition are exploratory only. They cannot support a
confirmatory model ranking, a gate decision, multiplicity-adjusted evidence, or
a claim that state-adaptive control works.

This benchmark does not test training, fine-tuning, preference optimization,
causal mechanisms, general musical quality, commercial suitability, or
population-level human preference. An automatic evaluator is an operational
measurement, not ground truth. A solo-PI label is an adjudicated benchmark
reference, not evidence of population consensus.

## 2. Backbone registry and entry gates

Exact repository revisions, weight-file hashes, inference-library revisions,
model-native inference configurations, and license records are required before
the design freeze. Successful measured smoke rows for every eligible model are
required before full benchmark execution authorization. The bounded SA3
foundation record does not waive that requirement: it ended `FAIL_ESCALATED`,
and its cost samples are too few for the registered p95 coefficients. A
similarly named checkpoint is never a substitute.

| Logical backbone | Canonical artifact | Status in this draft | Required evidence before full execution |
| --- | --- | --- | --- |
| `stable-audio-3-medium-base` | `stabilityai/stable-audio-3-medium-base` | Mandatory. This is pre-trained **Base**, not post-trained `stabilityai/stable-audio-3-medium`. D-0017: foundation A–D PASS, E FAIL, overall `FAIL_ESCALATED`. | Exact snapshot; adequate successful generation/NFE/cost calibration; native-config hash; reviewed capability preflight reaching a valid terminal PASS or `NOT_IDENTIFIABLE` classification. |
| `stable-audio-open-1.0` | `stabilityai/stable-audio-open-1.0` | Mandatory. | License/access without bypass; exact snapshot; successful generation/NFE/cost smoke; state capability recorded as PASS or `NOT_IDENTIFIABLE`. |
| `ACE-Step v1` | `ACE-Step/ACE-Step-v1-3.5B` | Mandatory. | Exact snapshot; successful generation/NFE/cost smoke; native-config hash; state capability recorded as PASS or `NOT_IDENTIFIABLE`. |
| `ACE-Step v1.5` | Gate-0 candidate `ACE-Step/acestep-v15-xl-sft@d1ca0bc96e29cd46435219ceb4f8e3a13a8eaf50`, non-Turbo | **Inactive and excluded. Latest merged retry status: `V15_GATE0_STATUS = FAIL_ESCALATED`.** | After design freeze, a specifically authorized continuation fix and fresh bounded Gate-0 must PASS before a prospective amendment may seek inclusion. |

The v1.5 failure is an engineering status, not a scientific model result. The
bounded retry stopped because a continuation timestep suffix was a list where
the native API required a `torch.Tensor`; it stopped before the first
continuation transformer call. No main control, rollover, tempo, constraint,
or policy experiment was launched. V1.5 is excluded from the v1 design freeze.
A later PASS requires a prospectively reviewed, versioned preregistration
amendment before execution authorization; it cannot be inserted post hoc.

State capability is not an entry requirement for the ordinary output
benchmark. A model that cannot expose and resume a true intermediate state is
reported `NOT_IDENTIFIABLE` for Section 11 and remains eligible for Sections
4–10.

## 3. Two-stage freeze package and immutable identities

Before the design-freeze decision, these companion artifacts must exist and
their SHA-256s must be named in `DECISIONS.md`:

- this preregistration, including its exact cost formula, obtained singleton
  evidence, and reason-coded incomplete rows;
- exact prompt IDs/text, intervention strings, and prompt-cluster map;
- the eight-seed manifest and deterministic seed-construction code;
- model IDs/revisions, inference configs, environments, evaluator weights, and
  evaluator configs;
- the bounded per-model smoke protocol, repetition counts, seeds, artifact
  ceilings, and hard smoke GPU-hour caps;
- the PI packet schema, hidden-repeat-map hash procedure, and time budget;
- planned result-table schemas; and
- the run-manifest schema, including node, GPU IDs, TP width, replica count,
  placement justification, command, Git/config hashes, seeds, artifact paths,
  and deviations.

The draft specifies prompt construction below, but the exact prompt-text and
seed companion manifests do not yet exist; it is reviewable, not freeze-ready.
The completed bounded foundation run does not freeze this document or open an
execution gate. Before the later benchmark-execution decision, adequate
immutable smoke rows, measured GPU-hour rows and caps for every eligible model,
state-capability reports, and any v1.5 amendment must be added and hashed.

Frozen prompt rows, seeds, evaluator thresholds, failed outputs, and label
packets are never overwritten or silently replaced. A post-freeze change uses
a versioned amendment and labels itself administrative, measurement-affecting,
or claim-affecting.

## 4. Common generation contract

### 4.1 Standardized prompt matrices

Each axis uses one standardized English prompt set unchanged across eligible
models. Wording is authored without inspecting benchmark outputs, then reviewed
and hashed before design freeze.

| Axis | Prompt rows and registered clusters | Frozen construction | Role |
| --- | --- | --- | --- |
| Vocal/instrumental | 24 rows in 12 paired content-frame clusters | Twelve content frames, each rendered as vocal and instrumental; genre, instrumentation, tempo, and structure language remain paired. | Confirmatory. |
| Explicit tempo | 30 rows/clusters | Ten targets `{60,72,84,96,108,120,132,144,156,168}` BPM × percussive/regular, syncopated, and legato/light-percussion salience. | Confirmatory. |
| Acoustic integrity | 18 rows/clusters | Six style families × three dynamic/attack profiles; prompts prohibit intended silence, glitch, clipping, dropout, and crackle. | Confirmatory. |
| Structure/repetition | 18 rows/clusters | Six requested form templates × three genre families. | Exploratory only. |

There are exactly eight registered seed indices, `0..7`, per prompt row,
condition, and model. The integer is derived from a frozen namespace and is
identical between `BASE` and `FIXED` within a model. The same integer across
architectures is not described as common random noise. A failed row is retried
only with identical inputs and seed; an unrecoverable row remains missing and
receives no outcome-aware replacement.

Every requested output is 30.0 seconds. Record decoded duration, sample rate,
channels, native amplitude path, effective conditioning/token truncation,
actual transformer-call count, wall time, and GPU time. Each model uses its
native recommended sampler family and a pre-frozen budget for both conditions;
no model receives outcome-guided tuning.

### 4.2 Fixed intervention

Each prompt × seed has two conditions:

- `BASE`: standardized prompt verbatim;
- `FIXED`: the same prompt followed by one ASCII space and the exact suffix.

| Axis | Exact suffix |
| --- | --- |
| Vocal | `Clearly audible lead human singing is central throughout.` |
| Instrumental | `Instrumental only; no singing, speech, rap, choir, or other functioning human voice.` |
| Tempo | `Maintain a steady quarter-note pulse at exactly {target_bpm} BPM.` |
| Integrity | `Clean intact audio: no clipping, dropouts, unintended silence, or digital crackle.` |
| Structure | `Follow the requested section order and make recurring sections recognizably recurrent.` |

A truncated suffix is an intervention-delivery failure, not permission to
rewrite after observing outcomes.

### 4.3 Fixed-intervention and best-of-N baselines

For every axis × model, report the `BASE` eight-seed distribution, the
matched-seed `FIXED − BASE` contrast, and `BoN-N` for
`N ∈ {1, 2, 4, 8}`. BoN uses seed prefixes `0..N-1` from the already generated
`BASE` pool and adds no generation. Human labels are forbidden selectors.

The frozen lexicographic selectors, highest tuple first, are:

- vocal request: `(voice_present, voice_margin, integrity_pass, -seed)`;
- instrumental request: `(not voice_present, -voice_margin, integrity_pass,
  -seed)`;
- tempo: `(resolved, -e_oct, -raw_APE, integrity_pass, -seed)`;
- integrity: `(integrity_pass, -defect_count, -clipped_fraction,
  -dropout_ms, -silent_frame_fraction, -crackle_count, -seed)`; and
- exploratory structure: `(recurrence_score, -short_loop_fraction,
  integrity_pass, -seed)`.

Here `voice_margin` is the maximum of
`log2((Demucs_ratio + 1e-12)/0.03161777090281248)` and
`log2((PANNs_max + 1e-12)/0.04403413645923138)`. Invalid tempo has
`resolved=0`, `e_oct=+∞`, and `raw_APE=+∞`. Structure BoN is reported only as a
selector diagnostic with no success or confirmatory claim. All BoN tables
state the N-fold candidate compute.

## 5. Axis A — vocal versus instrumental

### 5.1 Ported promoted-OR instrument

The primary automatic instrument is ported without retuning:

```text
demucs_present =
    (mixture_rms >= 1e-3)
    AND (demucs_vocal_energy_ratio >= 0.03161777090281248)

panns_present =
    max(PANNs vocal-class probabilities) >= 0.04403413645923138

voice_present = demucs_present OR panns_present
```

The PANNs maximum covers `Singing`, `Speech`, `Male singing`,
`Female singing`, `Child singing`, `Choir`, `Rapping`, `Human voice`,
`Vocal music`, and `A capella`. Comparisons are inclusive. A vocal request
succeeds when `voice_present=1`; an instrumental request succeeds when it is
zero. Near-silence is separately an integrity failure.

The ported artifact was calibrated on ACE-Step v1 evidence and is not assumed
to transport. Promotion-result SHA-256:
`2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2`.
Implementation SHA-256:
`3aa68674b9ce919d407f25070a93ca73f14ed39af36f41090a4db000b5df1524`.
These identify the port; they are not results of this benchmark.

### 5.2 Fresh per-model spot-check

For each eligible model, select 12 unique clips before human labels: six vocal
and six instrumental. Within direction, deterministic priority is two closest
to an OR boundary, two Demucs/PANNs disagreements, one far predicted present,
and one far predicted absent. Empty cells take the next closest unused row;
distinct content-frame clusters are exhausted before reusing a cluster.

The PI is blind to model, condition, seed, and detector values and listens to
the full 30-second clip. Labels are `present`, `absent`, or `unsure`.
“Present” requires intentional functioning singing, speech, rap, or choir; an
isolated sub-two-second nonlinguistic one-shot is normally absent unless
prominent. `Unsure` is retained, never mapped to a detector-favored class.

Report per-model confusion rows and a pooled fixed-instrument stress audit. Do
not retune thresholds. Fewer than eight decided labels or fewer than three in
either direction makes that model’s vocal claim `MEASUREMENT_LIMITED`.

## 6. Axis B — explicit tempo

### 6.1 Automatic estimators and octave-invariant error

The two fixed operationalizations are the official Beat This! event tracker
and `librosa==0.11.0`. Beat This! supplies beat-event times; this benchmark
derives BPM from the median interval and does not claim a native scalar output.

An estimator is valid only with at least eight finite events, BPM in `[30,300]`,
and inter-beat-interval IQR no greater than 25% of its median. Beat This! uses
`b_bt = 60/median(diff(beat_times_seconds))`. Librosa uses
`librosa.beat.beat_track`, retaining its tempo and beat frames under the same
checks. Stereo is averaged to float32 mono; native sample rate is retained
unless a hashed evaluator config requires resampling.

For estimate `b` and target `t`:

```text
e_oct(b,t) = min over k in {-2,-1,0,1,2} abs(log2(b/t) - k)
```

The primary target succeeds at `e_oct <= log2(1.05)`. Raw absolute percentage
error is secondary.

### 6.2 Frozen disagreement and alignment rule

For each estimator, choose octave shift `k*` by minimizing the tuple
`(abs(log2(b/t)-k), abs(k), k)` over `k∈{-2,-1,0,1,2}`, then set
`b_aligned=b/2^k*`. This fixes exact ties.

When both estimators are valid, compute:

```text
d_oct = min over k in {-2,-1,0,1,2} abs(log2(b_bt/b_librosa) - k)
```

- If `d_oct <= log2(1.08)`, consensus is exactly
  `sqrt(b_bt_aligned*b_librosa_aligned)`.
- If `d_oct > log2(1.08)`, mark `ESTIMATOR_DISAGREEMENT` and abstain.
- If either estimate is invalid, mark `ESTIMATOR_INVALID` and abstain.
- Abstention is failure in strict primary success; also report resolved-only
  success and all-abstain-fail/all-abstain-pass sensitivity bounds.

No estimator is selected clip-by-clip for proximity to target.

### 6.3 Thirty-clip PI spot-check per model

Exactly 30 unique tempo clips per eligible model are selected before labels:
ten agreement clips nearest the 5% boundary (five passes/five failures where
available), ten disagreements/invalids, five far passes, and five far failures.
Selection deterministically spreads target, salience, condition, prompt, and
seed; closest-score fallbacks fill empty cells.

The PI is blind to model, target, condition, seed, and estimates. One 30-second
playback contains two premarked independent tapping windows, seconds `2–14`
and `16–28`; each must yield at least eight taps. Thus two estimates require no
second playback. If octave-aligned window BPMs differ by more than 8%, one
12-second replay window is scheduled in fixed packet order. The closest two of
three define geometric-mean human BPM; if none agree, label `unsure`. If the
replay reserve is exhausted, unresolved scheduled clips become `unsure`
without outcome-aware substitution. Target adherence is computed only after
human BPM is locked.

## 7. Axis C — acoustic integrity

All DSP uses decoded float audio before benchmark-side normalization, limiting,
dither, or integer conversion. Calculations use float64. Multi-channel clip,
dropout, and crackle flags trigger if any channel triggers; silence uses RMS
over all channel samples. A wrapper that exposes only normalized audio records
that transformation and makes clipping non-comparable.

Frames are left-aligned. A partial final frame is zero-padded and excluded from
run-length decisions. `dBFS=20*log10(max(RMS,1e-12))`. The primary integrity
failure is the OR of these separately retained flags:

| Defect | Frozen objective rule |
| --- | --- |
| Clipping | Per channel, `abs(sample) >= 1-2^-15` for >0.1% of samples or a ≥3-sample run; or 4× true peak ≥1.0 after `scipy.signal.resample_poly(x,4,1,window=('kaiser',8.6),padtype='constant')`, trimming the filter’s symmetric padding. |
| Dropout | Per channel, non-overlapping 10-ms frames; an interior ≥50-ms run below `-80 dBFS`, beginning/ending ≥250 ms from file boundaries, flanked within 100 ms on both sides by frames above `-40 dBFS`, with ≥30 dB fall and recovery. |
| Silence | All-sample RMS `<=1e-5`, or ≥90% of non-overlapping 50-ms all-channel frames below `-60 dBFS`. Prompts prohibit intentional silence. |
| Crackle | Per channel, ≥3 isolated 1–3-sample excursions separated by ≥10 ms. Both onset/offset differences are ≥0.20 full scale and have robust z ≥12 against the centered 20-ms derivative neighborhood excluding the candidate ±3 samples, with scale `max(1.4826*MAD,1e-6)`. |

NaN/Inf, decode failure, channel count differing from the frozen model contract,
and sample count differing from `round(30*sample_rate)` are file-validity
failures above these categories. Continuous values and half/double count or
duration-threshold sensitivities are secondary; no threshold is retuned.

For each model, eight of its already scheduled 42 vocal/tempo clips receive an
acoustic checkbox without another playback: one high-score and one
boundary-score clip per defect. Empty flagged cells use the closest clean-side
row. The PI marks `audible`, `not audible`, or `unsure`, and may flag intentional
musical content. These audit labels never replace the objective primary.

## 8. Structure and repetition — exploratory only

The exploratory instrument records self-similarity recurrence, novelty peaks,
section-duration balance, repeated-window coverage, and short-loop fraction.
For the Section 4 selector only,
`recurrence_score = 0.5*recurring_window_cosine + 0.5*repeated_window_coverage`,
where both inputs are clipped to `[0,1]`; `short_loop_fraction` is coverage by
lags under four seconds. Exact window/hop/config hashes are freeze companions.

No threshold creates a success label. There is no confirmatory test, gate,
winner, or human-gold performance claim. A later confirmatory structure study
requires a separate preregistration.

## 9. Evaluator audit against pooled solo-PI gold

Human labels are pooled across models only to audit fixed instruments;
scientific model outcomes remain model-specific. Sampling is deterministic and
detector-targeted, so all metrics are unweighted stress-set audit metrics, not
prevalence or transport estimates. Hidden repeats have zero weight. Report
decided N, unsure rate, sensitivity, specificity, balanced accuracy, MCC, and
exact confusion counts overall and by model/direction/salience/disagreement.
If a slice contains one gold class, report class accuracy instead of balanced
accuracy or MCC.

A listed operationalization is `FAILED_IN_SLICE` only when the slice has at
least eight decided labels and unweighted error rate is at least 25%; otherwise
report `NO_FAILURE_CALLED` or `INSUFFICIENT_N`. Always show exact counts and a
Wilson 95% interval. This label is descriptive of the targeted audit set.

| Axis | Common fixed operationalization | Prospectively audited failure slice against pooled gold |
| --- | --- | --- |
| Voice | Demucs alone at `0.03161777090281248` | Quiet/embedded voice, separation leakage, near-silence. |
| Voice | PANNs maximum alone at `0.04403413645923138` | Speech/noise false positives, missed singing outside tag calibration. |
| Voice | Demucs AND PANNs | Sensitivity loss when only one family detects voice. |
| Voice | Promoted Demucs OR PANNs | Specificity loss and backbone transport shift. |
| Tempo | Beat This! interval BPM alone | Sparse/nonstationary beats, syncopation, continuity error. |
| Tempo | Librosa beat tracker alone | Percussive ambiguity, half/double tempo, weak salience. |
| Tempo | Raw exact BPM error | Musically equivalent octave pulse counted as large error. |
| Tempo | Frozen octave consensus | Joint wrong metrical level or model/style-specific abstention. |
| Integrity | Peak/clipped-sample test alone | Soft/intersample clipping and intentional limiting. |
| Integrity | Low-RMS run alone | Legitimate rests/fades mistaken for dropout/silence. |
| Integrity | Derivative impulse test alone | Percussive attacks mistaken for crackle. |
| Integrity | Four-flag OR | Error accumulation and preprocessing artifacts. |

No pooled-gold tuning, winner selection, or model-specific repair is allowed.
A failed operationalization stays visible.

## 10. Prompt-cluster statistics and reporting

The registered cluster is independent: a whole paired content frame for vocal,
and a prompt row for other axes. Seeds and conditions are repeated within
cluster. Headline rates first average seeds within prompt row, then directions
within vocal frame, then clusters within frozen strata.

Uncertainty uses 10,000 deterministic two-stage bootstrap replicates: resample
whole clusters within strata, then seed indices within sampled clusters while
preserving vocal direction pairs and BASE/FIXED matches. The bootstrap seed and
implementation hash are frozen before execution.

For each confirmatory axis × model, report base failure with a 95% cluster
interval; matched fixed-minus-base risk difference; BoN-1/2/4/8; every
prompt/seed outcome; missingness, abstention, and file-validity failures; and
the evaluator-audit row. Cross-model contrasts pair registered clusters but do
not call seeds common random noise.

The only confirmatory null per axis/model is
`H0: mean_cluster(success_FIXED-success_BASE) <= 0`, against improvement.
Inference uses the same 10,000 deterministic, stratified two-stage cluster
bootstrap registered above, not a sign-flip test. Let `D_hat` be the observed
cluster-mean contrast and `SE_hat` its stratified between-cluster standard
error. For replicate `b`, recompute both after resampling whole clusters within
frozen strata and seed indices within clusters, then set
`SE_b^+=max(SE_b,1e-12)` and `Z_b=(D_b-D_hat)/SE_b^+`. The
one-sided 95% lower bound is
`D_hat-q_0.95(Z_b)*SE_hat`, and the unadjusted p-value is
`(1 + count(Z_b >= D_hat/SE_hat))/(10000+1)`. If `SE_hat` or a required
effect estimate is nonfinite, or if `SE_hat=0`, the row receives no significance
claim (`p=1`, lower bound `-∞`); `D_hat<=0` also sets `p=1`. Zero bootstrap
standard errors use the stated floor and their count is reported. This
studentized bootstrap is an approximate weak-null procedure
conditional on independent, exchangeable clusters within each frozen stratum
and finite nonzero cluster variance; it does not assume sign symmetry or label
exchangeability. Holm adjustment is applied across eligible models within each
axis. BoN contrasts and all structure results are estimate-only and receive no
significance label.

No conclusion uses a pooled clip-level test, favorable single seed, best
observed prompt, post hoc threshold, or unreported excluded row.

## 11. Embedded state-information eligibility screen

This is a prospective replicated-action adaptation of the frozen Gate-1.5A
workflow. It preserves prompt-grouped cross-fitting, prompt-only versus
prompt+state readouts, measured program cost, completion reserve, and a
prompt-cluster gate. It does not adopt a one-outcome-per-action atlas or a
single-draw outcome-aware oracle.

### 11.1 Nonblocking capability gate

For each confirmatory axis/model, a bounded preflight tests true states at 25%,
50%, and 75% of measured transformer calls. State, conditioning, schedule, RNG,
and final-output hashes follow the frozen state contract; saving/decoding and
resuming must work. An independent low-step generation is not state. Failure
sets the screen to `NOT_IDENTIFIABLE` but does not block the output benchmark.

### 11.2 Equal-draw replicated actions and compute cap

Twelve prompt rows per confirmatory axis are hash-stratified before output. For
vocal, use all 12 content-frame clusters but assign exactly one direction per
frame by frozen hash order, balanced six vocal/six instrumental; the ordinary
benchmark still contains both directions. Thus every axis contributes 12
distinct eligibility clusters and six-fold cross-fitting remains balanced.
Seeds `0..3` are four roots and `4..7` four paired restart replicates. At each
checkpoint, every action produces exactly one registered terminal draw per
replicate:

- `KEEP`: resume root `r` and use BASE seed `r` terminal;
- `RESTART_BASE`: discard state and use BASE seed `4+r`; and
- `RESTART_FIXED`: discard state and use FIXED seed `4+r`.

These rows reuse the ordinary terminal pool. `KEEP` costs measured remaining
NFE; each restart costs one full model-native generation. The decision-time
incremental cap is exactly one full native generation, so all three are
feasible; prefix cost is sunk but total prefix-plus-action cost is reported.
Actions are ranked by predicted primary-axis success, then lower incremental
NFE, then `KEEP`, `RESTART_FIXED`, `RESTART_BASE`. File-invalid action outcomes
count as failure and are never dropped. A failed true-state resume makes the
capability gate fail rather than selectively deleting an action.

Every action value therefore has four registered outcomes at each unit. A
replicated outcome-aware ceiling `max_a mean_r(y_a,r)` may be reported only as
an unavailable diagnostic and is excluded from the gate. No maximum over one
draw, hand-picked continuation, or human-selected candidate is an oracle.

### 11.3 Prompt-only versus prompt+state models

The decision unit is `(prompt cluster, checkpoint)` with four replicated
outcomes/action. Six deterministic prompt-grouped folds keep every row for a
cluster together; with 12 clusters, each holds out two.

Both tiers use the same frozen low-capacity binomial hierarchical MAP model,
fixed priors, deterministic optimizer, training-fold-only standardization, and
no hyperparameter search. The exact formula/prior/config hash is a required
freeze companion. The target for each action is successes out of four under
the same primary endpoint as the axis: voice-direction success, strict tempo
success, or integrity pass.

Prompt-only features are action × request/target factors, prompt-matrix
factors, checkpoint fraction, remaining NFE, and frozen prompt metadata. The
prompt+state tier adds only pre-action summaries over four decoded previews:
axis evaluator values, integrity features, preview dispersion/agreement, and
remaining-budget fractions. It excludes action outcomes, terminal features,
human gold, and held-out fitted features.

Policy value is equal-weight mean observed action success across held-out
prompt clusters and all three checkpoints. Each chosen action is evaluated by
its four registered outcomes. Reused terminal outcomes across checkpoints are
handled by whole-cluster resampling.

### 11.4 Information gain and commitment–legibility curves

These terms are prospective definitions, not claimed predecessor metrics. At
checkpoint fraction `q`:

```text
LEGIBILITY(q) =
  [OOF logloss(prompt-only) - OOF logloss(prompt+state)] / ln(2)

OUTCOME_COMMITMENT(q) =
  mean over held-out clusters of abs(2*p_hat_KEEP_state(cluster,q) - 1)
```

`LEGIBILITY` is incremental predictive information in bits per registered
Bernoulli outcome. `p_hat_KEEP_state` is the out-of-fold prompt+state predicted
probability of KEEP success for a registered replicate in that cluster, from
the binomial decision unit defined in Section 11.3. Commitment can evolve with
the four-preview state summary even though each replicate's exact resumed
terminal is constant across checkpoints. Report calibration, Brier score, and
prompt-cluster intervals at all three fractions; no favorable point is selected
after viewing curves.

The primary gate remains:

```text
STATE_INCREMENTAL_VALUE =
  PROMPT_PLUS_STATE_POLICY_VALUE - PROMPT_ONLY_POLICY_VALUE

if one_sided_95pct_lower_bound > 0:
    ELIGIBILITY = ELIGIBLE_FOR_SEPARATE_STATE_ADAPTIVE_STUDY
elif point_estimate >= 0.05:
    ELIGIBILITY = REPLICATION_ONLY_NO_HEADLINE
else:
    ELIGIBILITY = STOP_STATE_ADAPTIVE_AXIS
```

The lower bound is the fifth percentile of 10,000 paired, stratified
whole-cluster bootstraps. Passing only permits a separately preregistered study.

## 12. Solo-PI budget, hidden repeats, and blinding

The target is at most three hours total for one PI. There is no inter-rater
reliability claim. Per eligible model there are 42 unique playbacks: 30 tempo
and 12 vocal. Eight acoustic checkboxes reuse those playbacks. Five hidden
repeat presentations per model are interleaved across at least two blocks and
excluded from evaluator denominators.

| Component/model | Presentations | Frozen timing | PI minutes |
| --- | ---: | --- | ---: |
| Tempo unique | 30 | one 30-s playback with two tap windows + 5-s response | 17.5 |
| Vocal unique | 12 | full 30-s playback + 5-s response | 7.0 |
| Acoustic checkbox | 8 reused | 5-s incremental response | 0.7 |
| Hidden repeats | 5 | 35-s average | 2.9 |
| **Timed subtotal/model** | **47** | — | **28.1** |

Fixed overhead is 10 minutes instruction/calibration, 10 minutes breaks, and a
20-minute third-tap/replay/adjudication reserve. A further 15% contingency is
applied to timed work plus overhead.

| Eligible models | Unique clips | Repeats | Before contingency | With 15% contingency | Decision |
| ---: | ---: | ---: | ---: | ---: | --- |
| 3 mandatory | 126 | 15 | 124.3 | 142.9 | Within 180 min. |
| 4 including conditional v1.5 | 168 | 20 | 152.4 | 175.3 | Within 180 min; 4.7 min headroom. |

The UI hides model, condition, seed, automatic score, stratum, and repeat
identity. The administrative map is hashed before ratings. Repeat agreement,
direction reversals, tap consistency, unsure counts, actual time, and deviations
are reported. Before each presentation or replay, the UI verifies that its full
registered time allowance fits within the remaining 180-minute budget; if not,
it does not begin that item. The PI never continues merely to finish a block.
Missing scheduled labels stay missing and no result-guided subset is preferred.

## 13. Execution and placement

Every model job is single-node and TP1. These backbones fit one A800, so wider
tensor parallelism is unjustified. Throughput uses at most eight independent
TP1 replicas on one of `an12` or `an29`, sharded deterministically; one job is
never split across nodes. Disjoint jobs may coexist on disjoint GPUs.

Each immutable manifest records node, GPU IDs, TP width, replica count,
placement justification, exact command, Git/config/seed/model/evaluator hashes,
timestamps, transformer calls, artifacts, and deviations. Logs use `logs/` or
immutable run directories. Checkpoints, generated data, and evaluations are
never overwritten.

## 14. Deliverables and licensing plan

| Deliverable | Contents | Planned license/restriction |
| --- | --- | --- |
| Instruments | Evaluator wrappers, thresholds, configs, tests, audit cards, install manifests. | Project-authored code MIT; third-party code/weights keep upstream terms. |
| Gold labels | De-identified PI ratings, unsure labels, timing, repeat reliability, selection strata/priority, data dictionary. | CC BY 4.0 for project-authored tabular labels; blind map released after analysis. |
| Atlas | Per-row outcomes, prompt-cluster summaries, audit slices, commitment–legibility curves, missingness. | CC BY 4.0 for project-authored tables/figures; audio only where every model license permits. |
| Harness | Manifest builders, generation adapters, scorers, statistics, audits, tests. | MIT for project-authored code; dependencies separately identified. |

Model weights are not MIT. Stable Audio 3 Base and Stable Audio Open weights
use the Stability AI Community License; the SA3 text conditioner also has Gemma
terms. ACE-Step v1 official code/checkpoint uses Apache-2.0; the official v1.5
repository/base card uses MIT. Exact applicable files are pinned at freeze.

## 15. Verified-citation policy

Only primary papers, official model cards, and official repositories verified
by the 2026-07-19 cutoff are cited. Citations establish identity or method, not
results of this study.

1. Zach Evans et al., [Stable Audio 3](https://arxiv.org/abs/2605.17991), 2026;
   official [Stable Audio 3 Medium Base card](https://huggingface.co/stabilityai/stable-audio-3-medium-base).
2. Zach Evans et al., [Stable Audio Open](https://arxiv.org/abs/2407.14358),
   2024; official [Stable Audio Open 1.0 card](https://huggingface.co/stabilityai/stable-audio-open-1.0).
3. Junmin Gong et al.,
   [ACE-Step: A Step Towards Music Generation Foundation Model](https://arxiv.org/abs/2506.00045), 2025;
   official [ACE-Step repository](https://github.com/ace-step/ACE-Step).
4. Junmin Gong et al.,
   [ACE-Step 1.5: Pushing the Boundaries of Open-Source Music Generation](https://arxiv.org/abs/2602.00744), 2026;
   official [ACE-Step 1.5 repository](https://github.com/ace-step/ACE-Step-1.5).
5. Francesco Foscarin, Jan Schlüter, and Gerhard Widmer,
   [Beat this! Accurate beat tracking without DBN postprocessing](https://arxiv.org/abs/2407.21658),
   ISMIR 2024; official
   [implementation](https://github.com/CPJKU/beat_this).
6. Brian McFee et al.,
   [librosa: Audio and Music Signal Analysis in Python](https://doi.org/10.25080/Majora-7b98e3ed-003),
   SciPy 2015;
   [librosa 0.11.0 archive](https://doi.org/10.5281/zenodo.15006942).

`MTRF` is excluded because no primary work was verified for this design. It has
no citation, borrowed result, operationalization, or benchmark role.

## 16. Internal protocol provenance

The user-authorized port is limited to the promoted-OR instrument and
Gate-1.5A-style workflow. It does not import predecessor results as results of
this benchmark.

- Source: `yhc98002-bit/Audio` remote main
  `062d75f4c235ebf306d42e215a74cfbf8c5afe87`.
- Promoted-OR result/implementation hashes are in Section 5.
- Gate-1.5A prompt grouping, cross-fitting, cost accounting, and gate structure
  are adapted; its one-draw action atlas is explicitly not adopted.
- The merged v1.5 Gate-0 terminal state is `FAIL_ESCALATED`.

The predecessor’s current preregistration checksum and a historical metrics
input hash do not match, so no cryptographic bind between them is claimed.

# Appendix A — execution cost and human effort

## A.1 Frozen workload

Each model has 90 prompt rows, eight seeds, and two conditions:

| Axis | Base/model | Fixed/model | BoN extra | Total/model |
| --- | ---: | ---: | ---: | ---: |
| Vocal/instrumental | 192 | 192 | 0 | 384 |
| Explicit tempo | 240 | 240 | 0 | 480 |
| Acoustic integrity | 144 | 144 | 0 | 288 |
| Structure/repetition | 144 | 144 | 0 | 288 |
| **Total** | **720** | **720** | **0** | **1,440** |

This is 12 generated audio-hours/model: 4,320 outputs and 36 audio-hours for
the three mandatory models. A later approved v1.5 amendment would make 5,760
outputs and 48 audio-hours.

The state screen reuses terminal rows. For a state-capable model it adds 432
state captures and preview decodes
(`36 eligibility prompt rows × 4 roots × 3 checkpoints`),
not terminal generations. For `NOT_IDENTIFIABLE`, both counts are zero. Let
`C_m=1` for a capable model and `0` otherwise.

## A.2 Measured coefficients and GPU-hour equation

The bounded project-local cost smoke caps terminal outputs at
`R_m + 20 + 5*4 <= 48` per model: one cold first output on each planned
replica, 20 warmed batch-one outputs, and five warmed batch-four invocations.
Distinct registered cost seeds are used and all outputs are retained. State
timing and evaluator timing reuse these rows. The smoke must provide:

- `c_m`: maximum cold load-plus-first-output GPU-seconds across planned TP1
  replicas;
- `g_m`: nearest-rank empirical p95 warmed GPU-seconds from at least 20
  batch-one 30-second terminal outputs;
- `b_m`: nearest-rank p95 from at least five warmed batch-four invocations,
  retained as a throughput cross-check rather than substituted for `g_m`;
- `s_m`, `d_m`: empirical p95 state-capture/serialization and preview-decode
  GPU-seconds from at least 20 operations each when `C_m=1`;
- `v_m`, `t_m`: empirical p95 Demucs+PANNs and Beat This! GPU-seconds from at
  least 20 clips each; and
- actual transformer calls, synchronized wall times, and peak memory.

Nearest-rank p95 is sorted observation `ceil(0.95*n)`. Medians and all raw rows
are also retained. For `R_m<=8` TP1 replicas:

```text
H_m = [R_m*c_m
       + max(1440-R_m,0)*g_m
       + 432*C_m*(s_m+d_m)
       + (384+144*C_m)*v_m
       + (480+144*C_m)*t_m
       + other_frozen_GPU_evaluator_seconds] / 3600
```

The subtraction avoids double-counting first outputs inside `c_m`. CPU-only
librosa, DSP, bootstrap, and packaging are separate. Authorization cap is
`1.25*H_m`; reaching it stops after the current immutable shard and does not
permit fewer seeds or favorable prompts.

The D-0013/D-0014 foundation plan was deliberately smaller than this formal
calibration: it contained one warmed batch-one call and one batch-four call,
not the 20 and five repetitions registered above. Its measurements are raw
engineering observations, not substitutes for `c_m`, `g_m`, `b_m`, `s_m`,
`d_m`, `v_m`, or `t_m`.

## A.3 Terminal foundation-smoke evidence at draft cutoff

The only obtained project-local foundation run is
`sa3-foundation-20260719T134821.040493Z-9ea9d06209d6` on `an12` physical GPU 4,
one NVIDIA A800 80GB PCIe GPU, TP1, replica count one. It used
`stable-audio-3-medium-base`, Git commit
`ae251c62e2ba2bae025ec4413aae875df967b021`, and config SHA-256
`d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`.
The immutable result SHA-256 is
`65adbde1e8abe9e744749a52745243d7c4bb572e778284d76827f98a05b6d912`
and ledger SHA-256 is
`7caafac155c3e04519633749bb89a31d4a86f8d118926aabd0bcdd0130626a2c`.

Smokes A–D passed. Smoke E's uninterrupted reference and 15/30/40-step
checkpoints were retained, but every separate-process resume stopped before
its first resumed DiT transition: the exported checkpoint latent was
`torch.float32`, while the official child created its disposable comparison
latent as `torch.float16`, and the strict boundary check rejected the mismatch.
This was not an OOM. The overall foundation status is terminal
`SA3_FOUNDATION_RUN_STATUS = FAIL_ESCALATED`; its one-shot authorization is
consumed and no retry is authorized.

Raw SA3 observations are:

| Observation (measurement scope) | n / NFE | Synchronized wall | Peak CUDA allocated / reserved | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Model load | 1 / not applicable | 74.005551 s | Not reset around load | Obtained setup wall only. |
| First A batch-one, 30 s (outer official-call wrapper) | 1 / 50 | 15.963724 s | 5,437,102,080 / 9,839,837,184 B | Load plus first call was 89.969274 s; one cold observation only. |
| Warmed D batch-one, 30 s (Smoke D protocol timer) | 1 / 50 | 3.642550 s | 5,439,723,520 / 9,839,837,184 B | Too few rows for `g_m` (requires at least 20). |
| Warmed D batch-four, 4 × 10 s (Smoke D protocol timer) | 1 / 50 | 4.866168 s | 5,890,185,728 / 10,464,788,480 B | 0.822002 items/s and 8.220020 generated-audio-s/s; too few rows for `b_m` (requires at least five). |
| E uninterrupted reference, 30 s (outer official-call wrapper) | 1 / 50 | 3.901632 s | 5,440,120,832 / 10,464,788,480 B | Reference and three checkpoints succeeded. |
| E resume attempts at 15/30/40 steps (outer official-call wrapper) | 3 / 0 each | 0.908469, 0.878612, 0.909384 s | allocated 5,280,795,648; 5,281,319,936; 5,281,319,936 B / reserved 9,837,740,032 B each | Failed pre-transition; inadmissible for resume-equivalence or state-cost coefficients. |
| Entire bounded run (outer budget wrapper) | 11 reserved calls; 8 succeeded; 400 total NFE | 46.013084 s = 0.012781 GPU-h | run maximum 5,890,185,728 / 10,464,788,480 B (5.486 / 9.746 GiB) | Conservative one-GPU residency upper bound: 244.181992 s = 0.067828 GPU-h. |

The Smoke D rows use its nested protocol timer around an already-loaded
`StableAudioModel.generate`; whole-run accounting uses the outer budget
wrapper. They are retained as distinct scopes and are not summed together.
The run reserved 14 generation slots, retained 11 model WAVs, and wrote 14
hash-chained ledger rows: 11 PASS rows plus three `MODEL_CALL_FAILED` rows. The
derived 10-second continuation source was also retained, for 12 retained audio
files total.

Cost evidence is therefore reason-coded as follows:

| Model/scope | Status | Consequence for the registered GPU budget |
| --- | --- | --- |
| SA3 Medium Base raw cost observation | `SA3_COST_OBSERVATION_STATUS = MEASURED_SINGLETON` | Raw singleton values above are obtained engineering evidence despite the terminal Smoke E failure. |
| SA3 Medium Base formal calibration | `SA3_BENCHMARK_COST_CALIBRATION_STATUS = INSUFFICIENT_REPETITIONS` | No registered p95 coefficient, `H_m`, or 25% cap can be calculated; formal state/evaluator timing is absent and state-resume equivalence failed. |
| Stable Audio Open 1.0 | `SAO_COST_STATUS = NOT_MEASURED_BY_THIS_SA3_ONLY_AUTHORIZATION` | No project-local cost coefficient, `H_m`, or cap. |
| ACE-Step v1 | `ACE_STEP_V1_COST_STATUS = NOT_MEASURED_BY_THIS_SA3_ONLY_AUTHORIZATION` | No project-local cost coefficient, `H_m`, or cap. |
| ACE-Step v1.5 | Inactive; `V15_GATE0_STATUS = FAIL_ESCALATED` | Excluded from v1; no cost row is applicable. |
| Mandatory multi-backbone budget | `MULTI_BACKBONE_BENCHMARK_GPU_BUDGET_STATUS = INCOMPLETE` | Full benchmark execution remains closed. |

Absent SAO/ACE and formal p95 rows are missing evidence, not zero-cost results.
Runtime numbers from sibling projects are not imported: their checkpoints,
post-training state, duration, steps, environment, or wrappers differ. A
measurement of post-trained `stable-audio-3-medium` would not be a measurement
of `stable-audio-3-medium-base`.

## A.4 PI-minute budget

`PI_LABELING_MINUTES_OBTAINED = 0.0`: rating has not begun, and automated
foundation execution is not PI labeling. Planned totals from Section 12 remain
142.9 minutes for three mandatory models and 175.3 minutes if a later amendment
admits v1.5, including hidden repeats and contingency. The absolute stop is 180
minutes. Actual playback, pause, third-tap, replay, and adjudication time is
logged; “gold” remains explicitly solo-PI gold.

## A.5 Cost approval rule

This draft retains the obtained raw rows and the reason-coded gaps above. It
does not authorize another foundation call, a repair of Smoke E, or any
benchmark generation. A later explicit decision would have to name a reviewed
fix, new immutable claim/config, and fresh hard caps before any repair run.

Before full benchmark execution, a separately authorized, versioned
measured-cost amendment must contain every eligible model’s smoke hashes,
node/GPU, config hash, duration, actual NFE, cold maximum, warmed median/p95,
batch-four throughput, conditional state cost, evaluator cost, calculated
`H_m`, and 25% cap. Missing, singleton-only, failed, or proxy costs keep
`BENCHMARK_EXECUTION_AUTHORIZED = NO`. This review draft remains
`BENCHMARK_PREREG_V1_FROZEN = NO`.
