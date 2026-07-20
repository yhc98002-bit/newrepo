# Benchmark preregistration v2 — frozen prospective design

- Draft date: 2026-07-20
- Supersedes: `BENCHMARK_PREREG_v1.md`; v1 remains immutable historical context
- Status: `FROZEN_PROSPECTIVE_DESIGN`
- `BENCHMARK_PREREG_V2_FROZEN = YES`
- Generation authorization at this draft cutoff: `CLOSED`
- Benchmark endpoints scored at this draft cutoff: zero
- Benchmark audio generated under v2 at this draft cutoff: zero
- Intended scientific unit: one backbone × one confirmatory axis

This document incorporates the PI-adjudicated v2 amendments prospectively. It
is a design, not a result report. A planned sample size, threshold, selector,
cost bound, or engineering measurement is not a benchmark result. The file is
not frozen until an append-only `DECISIONS.md` entry records this file's exact
SHA-256, every required companion identity in Section 3, the adjudication, and
`BENCHMARK_PREREG_V2_FROZEN = YES`. That freeze does not itself authorize a
model call: benchmark generation opens only through a later explicit launch
entry after the Phase-B gates in Section 13 have reached terminal states.

The separate D-0019 Smoke-E session is terminal and is not part of v2
generation. D-0020 records its PASS: three distinct processes resumed genuine
FP32 SA3 runtime states at 30/60/80% and produced waveforms exactly equal to
the uninterrupted reference. This gives `SA3_STATE_CAPABILITY = PASS` as
technical foundation evidence. It does not score a benchmark endpoint, supply
the formal per-axis state rows in Section 11, or reopen any Smoke-E authority.

## 1. Questions, claims, and fixed scope

The benchmark asks how text-to-music backbones fail under three constraints
with deliberately different failure structures, whether a fixed prompt
intervention or best-of-N selection reduces those automatic failures, and
whether a root's true intermediate state adds action information beyond the
prompt plus elapsed time and remaining budget.

The confirmatory axes are:

1. vocal versus instrumental satisfaction as measured by the frozen automatic
   instrument;
2. explicit tempo satisfaction; and
3. acoustic integrity.

Structure and repetition are exploratory only. They cannot support a
confirmatory rank, multiplicity-adjusted claim, eligibility decision, or claim
that state-adaptive control works.

The former vocal packet is relabeled **TARGETED_HUMAN_STRESS_AUDIT**, a
targeted human stress audit of the automatic instrument rather than a
model-performance endpoint. All model-level vocal and
instrumental results are called **automatic-instrument outcomes**. Human labels
audit transport and known failure slices; they never silently replace the
automatic endpoint or become model-level voice success rates.

This benchmark does not test training, fine-tuning, preference optimization,
causal mechanisms, general musical quality, commercial suitability, or
population preference. Solo-PI labels are adjudicated audit references, not a
population estimate or inter-rater reliability evidence.

## 2. Backbone registry and tiering

There are exactly three primary human-audited backbones in v2:

| Backbone | Canonical artifact | v2 tier and entry state |
| --- | --- | --- |
| `stable-audio-3-medium-base` | `stabilityai/stable-audio-3-medium-base` | Primary human-audited. D-0020 gives technical `SA3_STATE_CAPABILITY = PASS`; Section 11's formal axis rows remain unrun. |
| `stable-audio-open-1.0` | `stabilityai/stable-audio-open-1.0` | Primary human-audited, license-gated. A terminal `BLOCKED_ON_LICENSE` adapter status is honest and valid but does not permit generation for this backbone. |
| `ACE-Step v1` | `ACE-Step/ACE-Step-v1-3.5B` | Primary human-audited, subject to exact frozen config, adapter, license, and measured mini-smoke gates. |

Exact revisions, weight hashes, native configs, dependency locks, applicable
license records, and measured build-smoke rows are launch companions. Model
aliases and post-trained variants are not substitutes.

No fourth backbone enters the primary human-audited tier under this
preregistration. A fourth backbone requires either:

- a prospective, versioned amendment with a new human-time calculation and
  the same primary audit obligations; or
- a prospectively declared **automatic-only tier**, reported separately with
  no human-audit transport claim and no pooled primary ranking.

ACE-Step v1.5 is deferred for scope and solo-PI budget, not because v2 requires
it to expose resumable state. Its permitted future path is a generation-only
amendment (normally the automatic-only tier) with identity, license, adapter,
cost, and ordinary generation checks. It does **not** require a Gate-0
state-resume retry. Historical v1.5 engineering attempts neither admit nor
permanently exclude it.

If a primary backbone is `BLOCKED_ON_LICENSE`, ready backbones may enter their
own preregistered generation queues, but the blocked backbone is not silently
dropped, replaced by a fourth model, or represented in pooled three-backbone
claims. Its rows remain explicitly unavailable until the human license steps
are completed and a launch amendment records the exact artifact.

## 3. Freeze package and immutable identities

Every value below is a verified 64-character lowercase SHA-256 that must be
named in the freeze decision. The adapter rows bind the pre-generation B2
state; later measured mini-smoke/run records are append-only execution
companions and do not mutate this design.

| Frozen companion | Required path | Freeze-candidate identity |
| --- | --- | --- |
| Vocal/instrumental prompts | `prompts/v2/vocal_instrumental.json` | `602c4e0fb419d7a300116eb5fb76c30a8e19364aaef566aec05425caffed9f90` |
| Tempo prompts | `prompts/v2/tempo.json` | `16e31c155e1d535f2211fcd85c8d666c9ba7a6636e4487fd43ea2fd5fa0e36ab` |
| Integrity prompts | `prompts/v2/integrity.json` | `be0e7c65fa8dfad8c7fdbf4456b2c1ad7e6f4fe0bbeb67eba2fcbf96b5f16d03` |
| Exploratory structure prompts | `prompts/v2/structure_exploratory.json` | `6e9ca89c20ebb43313d9b492140970d876a5cfc657cf123cfe44b7d89e974af8` |
| Prompt/cluster master manifest | `prompts/v2/manifest.json` | `171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089` |
| Seed and eligibility-pool manifest | `prompts/v2/seed_registry.json` | `2115d7e70a6c3f4dd19f38503861b8aeb3595a8f64dd1fc839d7a209e80724eb` |
| Append-only engineering seed registry | `SEED_REGISTRY.md` | `d9b175296a97e8acca72d124a950c4e2fcd08c2d4287587c5e70c149f24deb97` |
| Canonical promoted-OR artifact | `provenance/b1/T6_PROMOTION_RESULT.json` | `2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2` |
| Promoted-OR source manifest | `provenance/b1/voice_source_manifest.json` | `422f5509b12ae101c4bfa96db96254717c3a454f350e1907d05fc6e72eab8df0` |
| Tempo evaluator pins | `provenance/b1/tempo_evaluator_pins.json` | `375df3abe0daf13cc50741db16db8d0347ba3074b874c3434402d54593476447` |
| Synthetic integrity fixture manifest | `provenance/b1/integrity_synthetic_fixture.json` | `ec1fe4292dea823a4cfca29b83302b04c8a31151c9e5218157982c1fc342aaad` |
| Synthetic integrity terminal validation | `provenance/b1/integrity_synthetic_validation.json` | `4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab` |
| B1 validation report | `provenance/b1/B1_VALIDATION_REPORT.json` | `656c8f960538ac0e35ea85786d1025d2350b581a0adb510a9879b2917506d448` |
| SA3 adapter/native config | `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| SAO license-gated adapter config | `configs/backbones/stable_audio_open_1_0.json` | `fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b` |
| ACE-Step v1 adapter/native config | `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| B2 pre-generation status | `provenance/b2/build_status_pre_generation.json` | `16a13a6275be01b6ba45544b58e37798b93b30ac03ebfe5b99def07f87a0718e` |
| SA3 adapter provenance | `provenance/b2/stable_audio_3_adapter.json` | `b6add6d47b608930b02de340db52bb3eaf5a36ca10aa19805ae99ba6562b677c` |
| SAO terminal license blocker | `provenance/b2/stable_audio_open_license_block.json` | `1f5d314c2b01622bdaeb9575404753ea4b4b295ea364765942bde3f2812474ef` |
| ACE-Step v1 port provenance | `provenance/b2/ace_step_v1_port.json` | `e57705caedab66d8c4b5ac138ed24fcff79527016e71e3a964f1321080d4d923` |
| ACE-Step v1 bounded mini-smoke config | `configs/b2_mini_smoke_v2.json` | `01a1bd650dbe3f23eeb60c07c46c4a9d66750f4d8070f5e872604c7c4142f632` |
| ACE-Step v1 bounded mini-smoke protocol | `B2_MINI_SMOKE_PROTOCOL_v2.md` | `2338cc92b1be99ce011902f9f7429976657ccb8ce2a791634d965096ce9c6118` |
| ACE-Step v1 bounded mini-smoke inner runner | `scripts/run_b2_mini_smoke_v2.py` | `040d0f75280c7adfbe614f74dab4a236b70068325ea4f85fe20b4b98ad56baff` |
| ACE-Step v1 GNU-timeout production wrapper | `scripts/run_b2_mini_smoke_v2_with_timeout.py` | `1ba0dcd7f35e4f56a0f836da10491f440eed12689ca83cca47fbd56aeb47400f` |
| ACE-Step v1 external-authorization template | `provenance/b2/b2_mini_smoke_authorization.template.json` | `3d0aaa08408ba394d827a578a8a231a39d3a965af325a4afbb019c2c34506ff1` |
| B2 lazy backbone package boundary | `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| B2 ACE-Step adapter | `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| B2 common adapter contracts | `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| B2 common adapter factory | `src/backbones/factory.py` | `7774236d732d0262cbc412b4c516c0484ce20867ec48bc370821d037f09f60e3` |
| B2 common no-clobber I/O | `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| B2 common mini-smoke executor | `src/backbones/mini_smoke.py` | `d7b810a1f1e35a7193ea2bf3ac34a5071c017c415407b90cf203737f9fed20e5` |
| B2 common source/runtime verifier | `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| B2 retained-audio artifact writer | `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| B2 retained-audio sanity | `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| Statistics and eligibility config | `configs/statistics_v2.json` | `d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d` |
| Rater schema and human-packet gate | `rater/schema_v2.json` | `0edb492fbf00355aec3e9f059d3b17557814f58b203c963f1c420f0c92ccde76` |
| Rater freeze manifest | `rater/freeze_manifest_v2.json` | `3fc506db647b4b1690866abe39f23f786c256376de3f304845a3fae294edc232` |
| Blinded timing-pilot source | `rater/timing_pilot_v2.source.json` | `1328c48f8a10b524cf5fc78e04e415e4c4a86713a9b74a3a9742570981be3d70` |
| Blinded timing-pilot UI | `rater/timing_pilot.html` | `78bba8a189b7f281888a7607bb8197ac457196501134e9dec8a3996e724e2708` |
| Blinded timing-pilot offer record | `rater/timing_pilot_offer_v2.json` | `645cca46a001b42aace2f20a95d35921c6e26d7c56665cb7c457b30cf57227cb` |
| Immutable timing-pilot bundle JSON | external immutable bundle named by `rater/timing_pilot_offer_v2.json` | `a25454b31672a435ffeb5cdb10593f0ae99dfbe4426e2ae409f71f2dcd2da537` |
| Immutable timing-pilot bundle manifest | external immutable bundle named by `rater/timing_pilot_offer_v2.json` | `715a2ac5024965a57525f836b690fe21fb0fd5bb1aac25ba35e94fed44ad3a80` |
| Verified-citation audit | `provenance/citation_audit_v2.json` | `f6fadd8b36dfc05b55ba48211c1440de26af10da93f5b8306e4d5d44a5d43311` |
| Benchmark core protocol | `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |

The freeze decision also records this file, seed construction code, evaluator
weight identities, statistics config, run/ledger schemas, license snapshot,
and environment lock. Exact prompt IDs/text, intervention strings, prompt
clusters, root/pool roles, and hidden-repeat mappings are immutable after
freeze. Files, checkpoints, audio, ledgers, packets, and evaluations are never
overwritten. Any post-freeze change is a versioned amendment labeled
administrative, measurement-affecting, or claim-affecting.

## 4. Common generation contract

### 4.1 Standardized prompt sets and seeds

Each axis uses one English prompt set unchanged across eligible backbones.
Prompts are authored and frozen before any benchmark endpoint is generated or
scored.

| Axis | Rows and clusters | Frozen construction | Role |
| --- | ---: | --- | --- |
| Vocal/instrumental | 24 rows in 12 paired content-frame clusters | Each frame has paired vocal and instrumental requests. Every instrumental row names its intended leading instruments. Genre, instrumentation, tempo, and structure language stay paired. | Confirmatory automatic-instrument endpoint. |
| Explicit tempo | 30 prompt clusters | Targets `{60,72,84,96,108,120,132,144,156,168}` BPM × percussive/regular, syncopated, and legato/light-percussion salience. | Confirmatory. |
| Acoustic integrity | 18 prompt clusters | Six style families × three dynamic/attack profiles; no requested silence, glitch, clipping, dropout, or crackle. | Confirmatory. |
| Structure/repetition | 18 prompt clusters | Six requested forms × three genre families. | Exploratory only. |

There are exactly eight core seed indices, `0..7`, for every prompt,
condition, and backbone, satisfying the at-least-eight-seed requirement. Seeds
use namespace `benchmark-v2-root-seed-20260720` and derivation
`1 + uint64_be(sha256(namespace|model_id|prompt_id|root_index)[0:8]) mod
2147483646`. The same integer is matched between `BASE` and `FIXED` within a
backbone but is not described as common random noise across architectures.
Failures receive no outcome-aware replacement; an infrastructure retry, if
separately authorized, must repeat identical inputs and remains a separately
ledgered call.

All requested core outputs are 30.0 seconds. Record decoded duration, sample
rate, channels, native amplitude transformations, prompt/token truncation,
sampler, actual transformer calls/NFE, synchronized wall, peak VRAM, Git/config
hashes, node/GPU placement, seed, and every artifact hash. Each backbone uses
one pre-frozen native sampler/budget in all conditions.

### 4.2 Primary fixed interventions and negation diagnostic

`BASE` is the standardized prompt verbatim. `FIXED` appends one ASCII space
and the registered suffix. The instrumental primary intervention is
positive-only:

| Request/axis | Exact primary `FIXED` suffix |
| --- | --- |
| Vocal | `Clearly audible lead human singing is central throughout.` |
| Instrumental | Per-row exact expansion of `A purely instrumental arrangement led throughout by {named_instruments}.` in the frozen prompt file. |
| Tempo | `Maintain a steady quarter-note pulse at exactly {target_bpm} BPM.` |
| Integrity | `Clean intact audio: no clipping, dropouts, unintended silence, or digital crackle.` |
| Structure | `Follow the requested section order and make recurring sections recognizably recurrent.` |

`{named_instruments}` is expanded before freeze to the instrument names already
present in that row; it is not sent literally to a model. The 12 exact expanded
suffixes are the values hashed in `prompts/v2/vocal_instrumental.json`, and no
post hoc substitution is allowed. Instrumental prompts that omit named
instruments fail the pre-generation schema gate.

The old negation suffix is retained only as a preregistered, estimate-only
`NEGATION_DIAGNOSTIC` on the 12 instrumental rows:

```text
Instrumental only; no singing, speech, rap, choir, or other functioning human voice.
```

It is excluded from the primary `FIXED − BASE` hypothesis, multiplicity
family, model ranking, and state-eligibility endpoint. Its 12 × 8 outputs per
backbone are generated and ledgered like other rows and reported beside, never
in place of, the positive-only intervention. A truncated or undelivered suffix
is an intervention-delivery failure, not permission to rewrite it.

### 4.3 Fixed-intervention and best-of-N baselines

For every confirmatory axis × backbone, report the eight-seed `BASE`
distribution, matched-seed primary `FIXED − BASE`, and `BoN-N` for
`N ∈ {1,2,4,8}`. BoN uses prefixes of the already generated `BASE` pool and
adds no generation. Human labels never select candidates.

Frozen lexicographic selectors, highest tuple first, are:

- vocal request: `(voice_present, voice_margin, integrity_pass, -seed)`;
- instrumental request: `(not voice_present, -voice_margin, integrity_pass,
  -seed)`;
- tempo: `(resolved, -e_oct, -raw_APE, integrity_pass, -seed)`;
- integrity: `(integrity_pass, -defect_count, -clipped_fraction, -dropout_ms,
  -silent_frame_fraction, -crackle_count, -seed)`; and
- exploratory structure: `(recurrence_score, -short_loop_fraction,
  integrity_pass, -seed)`.

Invalid tempo receives `resolved=0`, `e_oct=+infinity`, and
`raw_APE=+infinity`. Every BoN table states N-fold candidate compute.

## 5. Axis A — vocal/instrumental automatic-instrument outcomes

### 5.1 Promoted-OR instrument and canonical parsing

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
`Vocal music`, and `A capella`. Comparisons are inclusive. Near-silence is a
separate integrity failure.

The selector margin is gate-aware and finite. With `f=1e-12`, mixture RMS
`r`, Demucs ratio `d`, PANNs maximum `p`, and the two artifact-derived
thresholds `t_d,t_p`, define:

```text
m_D_rms   = log2(max(r,f) / 1e-3)
m_D_ratio = log2(max(d,f) / t_d)
m_D       = min(m_D_rms, m_D_ratio)
m_P       = log2(max(p,f) / t_p)
voice_margin = max(m_D, m_P)
```

Thus the Demucs AND gate includes the RMS floor, the final maximum implements
the promoted OR, and `voice_present` is exactly `voice_margin >= 0`. BoN and
human boundary/far selectors use this `voice_margin`. Candidate transport
includes `r,d,p`; the rater validator reloads the hash-bound canonical
promotion artifact, recomputes all three Boolean decisions and the margin, and
rejects any mismatch. It never trusts a supplied scalar margin or embeds the
learned thresholds as independent literals.

The authorized predecessor source is `yhc98002-bit/Audio` main commit
`062d75f4c235ebf306d42e215a74cfbf8c5afe87`. The promotion-result artifact
SHA-256 is
`2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2`;
the recorded predecessor implementation SHA-256 is
`3aa68674b9ce919d407f25070a93ca73f14ed39af36f41090a4db000b5df1524`.
These identify a port, not a result of this benchmark.

The v2 implementation must parse both thresholds and the promoted Boolean
rule from the canonical copied artifact
`provenance/b1/T6_PROMOTION_RESULT.json`, whose SHA-256 is the promotion-result
identity above. Threshold literals may appear in this preregistration and
frozen data, but not as an independent source of truth in evaluator code. A
mutation test substitutes a canonical fixture with different valid thresholds
and must change behavior; this forbids a hard-coded port.

A vocal request's automatic-instrument success is `voice_present=1`; an
instrumental request's is `voice_present=0`. The terms “model vocal success”
and “model instrumental success” must be qualified as automatic-instrument
outcomes in tables and prose.

### 5.2 Targeted human stress audit

For each primary backbone, select 12 unique clips before labels: six requested
vocal and six requested instrumental. Within direction, deterministic priority
is two closest to the promoted-OR boundary, two Demucs/PANNs disagreements,
one far predicted present, and one far predicted absent. Empty strata use the
next closest unused row after distinct content clusters are exhausted.

The six vocal slots are balanced three `BASE`/three `FIXED`; the six
instrumental slots are balanced two `BASE`/two positive `FIXED`/two
`NEGATION_DIAGNOSTIC`. A frozen prompt-hash rotation assigns condition quotas
to the six priority slots before detector values are observed. Empty-cell
fallback stays inside the assigned condition until it is exhausted, then uses
the next condition in frozen rotation and records the deviation.

The PI is blind to backbone, condition, seed, detector values, and stratum and
hears the full clip. Labels are `present`, `absent`, or `unsure`; “present”
means functioning singing, speech, rap, or choir. `Unsure` is retained. Report
confusion counts and targeted stress-slice metrics by backbone and direction.
Do not retune thresholds. Fewer than eight decided labels or three per
direction is `MEASUREMENT_LIMITED`. These labels audit the instrument only and
do not create human model-performance outcomes.

## 6. Axis B — explicit tempo

### 6.1 Pinned pair, validity, and octave-invariant error

The two operationalizations are the frozen official Beat This! event tracker
and `librosa==0.11.0`. Their exact code, weight, dependency, and evaluator
configuration hashes are Section-3 freeze companions. Beat This! is pinned to
v1.1.0 commit `ad7974846029835307ba19a3d5cefbf40b243041` and official `final0`
checkpoint SHA-256
`8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`;
librosa is pinned to 0.11.0 commit
`af8c839fb15317fa2712ea66e7a22da6a9267b32`. Beat This! BPM is
`60/median(diff(finite beat-event seconds))`; librosa retains both its tempo
and beat frames.

An estimate is valid with at least eight finite events, BPM in `[30,300]`, and
inter-beat-interval IQR no greater than 25% of its median. Stereo is averaged
to float32 mono; native sample rate is retained unless the frozen config
requires resampling. For estimate `b` and target `t`:

```text
e_oct(b,t) = min over k in {-2,-1,0,1,2} abs(log2(b/t) - k)
```

The **primary** target tolerance is 5%:
`e_oct <= log2(1.05)`. The preregistered sensitivity is 10%:
`e_oct <= log2(1.10)`. Both denominators include abstentions as failures in
strict rates; neither tolerance is chosen after results. Raw absolute
percentage error is secondary.

### 6.2 Frozen estimator disagreement

For each estimator, choose `k*` by minimizing
`(abs(log2(b/t)-k), abs(k), k)` over `k in {-2,-1,0,1,2}` and set
`b_aligned=b/2^k*`. With two valid estimates:

```text
d_oct = min over k in {-2,-1,0,1,2} abs(log2(b_bt/b_librosa) - k)
```

- `d_oct <= log2(1.08)`: consensus is exactly
  `sqrt(b_bt_aligned*b_librosa_aligned)`;
- larger disagreement: `ESTIMATOR_DISAGREEMENT` and abstain;
- either invalid: `ESTIMATOR_INVALID` and abstain.

Report strict, resolved-only, all-abstain-fail, and all-abstain-pass rows. No
estimator is selected clip-by-clip for target proximity.

### 6.3 First/second-window drift and PI tap audit

In addition to the full-clip primary result, run each estimator independently
on seconds `2–14` (`FIRST_WINDOW`) and `16–28` (`SECOND_WINDOW`) with the same
validity and disagreement rules. Report, as separate columns and distributions:

- first-window 5% success and 10% sensitivity;
- second-window 5% success and 10% sensitivity;
- signed drift `log2(b_second/b_first)`; and
- octave-invariant absolute drift
  `min_k abs(log2(b_second/b_first)-k)`.

The two `b` values are independently resolved dual-estimator consensuses. If
either window abstains, drift is `WINDOW_DRIFT_UNRESOLVED` (missing, not zero),
while each window's own validity and target result remain reported.

Do not average the two windows into a drift-free score, and do not substitute
one window for a failed full-clip estimate.

Exactly 30 unique tempo clips per primary backbone are selected before labels:
ten full-clip agreements nearest the 5% boundary, ten disagreements/invalids,
five far passes, and five far failures, with deterministic target/salience/
prompt/seed spread and exactly 15 `BASE`/15 `FIXED` slots assigned by frozen
hash before evaluator values. The PI is blind to backbone, target, condition,
seed, and estimates. One playback has two premarked tap windows at seconds
`2–14` and `16–28`, each requiring at least eight taps.

Human first- and second-window BPMs, their separate 5%/10% target labels, and
their signed and octave-invariant drift are always retained separately. If
octave-aligned window BPMs differ by more than 8%, one fixed-order 12-second
replay is allowed. The closest two of three yield a geometric mean; otherwise
the clip is `unsure`. Target adherence is revealed only after tap values lock.

## 7. Axis C — acoustic integrity

### 7.1 Frozen DSP flags

All DSP uses decoded float audio before benchmark normalization, limiting,
dither, or integer conversion and computes in float64. A primary integrity
failure is the OR of separately retained flags:

Frames are left-aligned. A partial final frame is zero-padded for scalar frame
calculations and excluded from run-length decisions. Define
`dBFS = 20*log10(max(RMS,1e-12))`. Multi-channel clipping, dropout, and crackle
trigger if any channel triggers; silence uses RMS across all channel samples.

| Defect | Frozen objective rule |
| --- | --- |
| Clipping | Per channel, `abs(sample) >= 1-2^-15` for more than 0.1% of samples or a run of at least 3 samples; or 4× true peak at least 1.0 after `scipy.signal.resample_poly(x,4,1,window=('kaiser',8.6),padtype='constant')`, trimming symmetric filter padding. |
| Dropout | Per channel, an interior run of at least 50 ms in nonoverlapping 10-ms frames below `-80 dBFS`, at least 250 ms from boundaries, flanked within 100 ms by frames above `-40 dBFS`, with at least 30 dB fall and recovery. |
| Silence | All-sample RMS at most `1e-5`, or at least 90% of nonoverlapping 50-ms all-channel frames below `-60 dBFS`. |
| Crackle | Per channel, at least 3 isolated 1–3-sample excursions separated by at least 10 ms; onset and offset differences are at least 0.20 full scale and have robust z at least 12 against the centered 20-ms derivative neighborhood excluding candidate ±3 samples, with scale `max(1.4826*MAD,1e-6)`. |

Defect sampling uses exact dimensionless scorer margins. OR gates take the
maximum of component margins and AND gates take the minimum. Let
`next(x)=nextafter(x,+infinity)`. The frozen formulas are:

```text
m_clip = max(hard_clipped_fraction/next(0.001)-1,
             longest_hard_clip_run_samples/3-1,
             true_peak/1.0-1)

m_dropout(candidate) = min(duration_ms/50-1,
  left_boundary_ms/250-1, right_boundary_ms/250-1,
  (left_level_dbfs-next(-40))/40,
  (right_level_dbfs-next(-40))/40,
  (left_level_dbfs-low_level_dbfs)/30-1,
  (right_level_dbfs-low_level_dbfs)/30-1)
m_dropout = max over every below--80-dBFS frame run; empty maximum = -1

m_silence = max(1-all_sample_rms/1e-5,
                silent_frame_fraction/0.90-1)
m_crackle = maximum_channel_crackle_count/3-1
```

For each defect, `flag` is exactly `margin >= 0`; `next` preserves the
clipped-fraction and flank-level rules' strict comparisons. Candidate
transport contains the raw clipping/silence/crackle scalars and every finite
dropout constraint vector. The hash-bound DSP implementation recomputes flags
and margins and rejects inconsistent rows. Within an integrity stratum the
registered margin is ranked first; prompt-cluster diversity is only a tie
breaker and never outranks highest severity, closest clean side, or highest
subthreshold crackle.

NaN/Inf, decode failure, unexpected channels, and sample-count mismatch are
file-validity failures above the defect flags. Defect-specific prevalence and
failure rates for clipping, dropout, silence, and crackle are **always
reported**, even when the four-way OR is also shown. No “integrity failure”
aggregate may replace the four rows.

### 7.2 Mandatory synthetic-injection validation before generation

Before the first benchmark model call, the frozen synthetic suite must PASS:

- clean finite controls trigger none of the four flags;
- clear positive injections separately trigger clipping, dropout, silence,
  and crackle at their registered locations;
- below-threshold/clean-side fixtures remain negative for their target defect;
- sharp transient and percussive controls do not trigger crackle; and
- stereo-any-channel, boundary exclusion, padding, duration, and NaN/Inf
  cases match the frozen expected vectors.

Fixture waveforms are deterministic code-generated test data, not model
outputs. The expected-vector manifest is
`provenance/b1/integrity_synthetic_fixture.json`, SHA-256
`ec1fe4292dea823a4cfca29b83302b04c8a31151c9e5218157982c1fc342aaad`;
the terminal PASS vector SHA-256 is
`4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab`.
Its generator and source hashes are bound by the B1 report. Any failed
assertion sets
`INTEGRITY_SYNTHETIC_VALIDATION = FAIL` and blocks all benchmark generation;
thresholds are not tuned on the fixtures or later audio.

### 7.3 Defect-separated human stress audit

The human integrity audit is selected only from that backbone's
**integrity-axis outputs**, never opportunistically from vocal or tempo rows.
Before labels, select ten unique clips per backbone:

- one highest-severity flagged row for each of the four defects;
- one closest clean-side row below each defect's decision boundary; and
- two additional sharp/percussive controls, chosen by the highest subthreshold
  crackle score from prompt rows registered as sharp/percussive.

For each defect, a frozen hash assigns its flagged slot to `BASE` or `FIXED`
and assigns its clean-side slot to the other condition. The two controls use
one condition each, giving five `BASE` and five `FIXED` slots per backbone
before scores are observed.

Selections are defect-separated strata. Empty strata are reported
`STRATUM_EMPTY`; they are not filled from another defect. The PI hears the full
clip blind to backbone, condition, seed, flags, scores, and stratum, then marks
each defect `audible`, `not_audible`, or `unsure` and may mark intentional
musical content. The transported integrity response is
`{defect_labels, intentional_musical_content}`. The intentional-content
Boolean is nonexclusive and may accompany defect labels, `clean`, or `unsure`;
`clean` and `unsure` are each otherwise exclusive of all defect labels and of
one another. Report defect-specific confusion counts and audit rates plus
clean-side and sharp/percussive-control false-positive slices. Human labels do
not replace the objective primary.

## 8. Structure and repetition — exploratory only

The frozen exploratory instrument records recurrence, novelty, section
balance, repeated-window coverage, and short-loop fraction. For BoN only,
`recurrence_score = 0.5*recurring_window_cosine +
0.5*repeated_window_coverage`, with inputs clipped to `[0,1]`.
`short_loop_fraction` is coverage by lags under four seconds. No threshold
creates success, and no human-gold or eligibility claim uses this axis.

## 9. Evaluator audit against pooled solo-PI gold

Human labels pool across primary backbones only to audit fixed instruments;
model outcomes remain model-specific automatic results. Deterministic targeted
sampling means these are unweighted stress-set metrics, not prevalence or
transport estimates. Hidden repeats have zero audit weight. Report decided N,
unsure rate, exact confusion counts, sensitivity, specificity, balanced
accuracy, MCC, and Wilson 95% intervals overall and by registered slice. A
one-class slice receives class accuracy, not MCC.

An operationalization is `FAILED_IN_SLICE` only with at least eight decided
labels and at least 25% unweighted error; otherwise report
`NO_FAILURE_CALLED` or `INSUFFICIENT_N`.

| Axis | Common operationalization | Prospectively audited failure slice |
| --- | --- | --- |
| Voice | Demucs threshold alone | Quiet/embedded voice, leakage, near-silence. |
| Voice | PANNs threshold alone | Speech/noise false positives and missed singing. |
| Voice | Demucs AND PANNs | Sensitivity loss when one family alone detects voice. |
| Voice | Promoted Demucs OR PANNs | Specificity loss and backbone transport shift. |
| Tempo | Beat This! alone | Sparse/nonstationary beats and continuity error. |
| Tempo | Librosa alone | Percussive ambiguity, half/double pulse, weak salience. |
| Tempo | Raw exact-BPM error | Octave-equivalent pulse counted as large error. |
| Tempo | Frozen octave consensus | Joint metrical error or model/style abstention. |
| Integrity | Clipping rule | Soft/intersample clipping and intentional limiting. |
| Integrity | Dropout rule | Legitimate rests/fades and transient low-energy spans. |
| Integrity | Silence rule | Quiet-but-intentional material. |
| Integrity | Crackle rule | Sharp/percussive attacks. |
| Integrity | Four-defect OR | Error accumulation and preprocessing artifacts. |

No pooled-gold tuning, winner selection, model-specific threshold, or hidden
failure is allowed.

## 10. Prompt-cluster inference and reporting

The independent resampling unit is the paired content frame for vocal and the
prompt row for other axes. Seeds, conditions, roots, checkpoints, and restart
pool reuses stay inside their prompt group. Headline rates first average seeds
within row, then vocal directions within frame, then clusters within frozen
strata.

For each confirmatory axis × backbone, report base failure with a 95% cluster
interval, matched primary fixed-minus-base risk difference, BoN-1/2/4/8,
every prompt/seed outcome, missingness, abstention, file validity, and the
evaluator-audit row. The negation diagnostic is estimate-only.

Uncertainty uses 10,000 deterministic, stratified two-stage bootstrap
replicates: whole prompt clusters first, then matched seed indices within
cluster. Vocal pairs and `BASE`/`FIXED` matches stay intact. The bootstrap seed
and code hash freeze before generation.

The only confirmatory null per axis/backbone is
`H0: mean_cluster(success_FIXED - success_BASE) <= 0`, against improvement,
using the same studentized cluster bootstrap and one-sided 95% lower bound.
Let `D_hat` be the cluster-mean contrast and `SE_hat` its stratified
between-cluster standard error. In bootstrap replicate `b`, recompute both and
set:

```text
SE_b_plus = max(SE_b, 1e-12)
Z_b = (D_b - D_hat) / SE_b_plus
lower_95 = D_hat - quantile_0.95(Z_b) * SE_hat
p_unadjusted = (1 + count(Z_b >= D_hat/SE_hat)) / (10000 + 1)
```

If `D_hat <= 0`, `SE_hat = 0`, or a required estimate/SE is nonfinite, set
`p_unadjusted=1` and `lower_95=-infinity`; report the number of bootstrap SEs
that used the floor. The registered Holm family is all three primary backbones
within an axis. If one is unavailable, its scientific row remains missing and
receives no effect claim; for conservative three-slot Holm arithmetic only,
its unavailable p-value is treated as 1. BoN, negation, structure, window
drift, 10% tempo sensitivity, and human stress-audit slices are estimate-only.

No result uses a pooled clip-level test, favorable seed, best prompt, post hoc
threshold, unreported excluded row, or a human-selected candidate.

## 11. Embedded state-information eligibility screen

This screen is a prospective replicated-action adaptation of the frozen
Gate-1.5A-style workflow. It uses true checkpoint state, prompt-grouped
cross-fitting, measured action costs, and no single-draw outcome-aware oracle.
Passing only permits a separately preregistered state-adaptive study.

### 11.1 Capability is nonblocking for ordinary output generation

For each confirmatory axis/backbone, true state is tested at 25%, 50%, and 75%
of that backbone's frozen transformer budget. State, conditioning, schedule,
RNG, serialization, preview decode, resume, and terminal hashes follow the
frozen contract. An independent low-step generation is not state. Failure is
`NOT_IDENTIFIABLE` for this screen but does not disqualify Sections 4–10.

D-0020 establishes only the technical foundation row
`SA3_STATE_CAPABILITY = PASS`: a fresh official 50-step reference exported
FP32 runtime state at 30/60/80%, and separate processes resumed all three with
zero decoded error. The formal per-axis 25/50/75 captures remain unexecuted at
this cutoff. The original five-smoke run remains historically
`FAIL_ESCALATED`; the terminal E-only retry is PASS and consumed.

### 11.2 Unit, root-local features, and replicated actions

The eligibility unit is exactly `(prompt, root, checkpoint)`. Twelve prompts
per confirmatory axis are selected by frozen hash strata. Vocal uses all 12
content frames and assigns one direction per frame by hash, balanced six/six.
The exact selection namespace is
`benchmark-v2-eligibility-prompt-selection-20260720`. Sort ascending by
`sha256(namespace + "|" + identity)`: for vocal, rank the 12 `cluster_id`
values and assign vocal to the first six and instrumental to the last six; for
tempo, take the first four prompt IDs within each of the three salience strata;
for integrity, take the first four prompt IDs within each of the three profile
strata. The resulting 36 exact IDs are frozen in
`configs/statistics_v2.json`; no observed output can change them.

Initial roots are core seeds `0..3`; the only permitted doubling adds roots
`4..7`. At a unit `(p,r,q)`, state features are computed from **only root r's
decoded preview at checkpoint q**. No preview, score, dispersion, or latent
summary from another root enters that row.

The true state is captured from the selected prompt's `BASE` condition only.
Thus `KEEP` continues that exact BASE-root prefix; `RESTART_BASE` and
`RESTART_FIXED` draw from their separately frozen replicated prompt-level
terminal pools. No `FIXED` or diagnostic prefix is silently treated as the
observed KEEP state. This one-condition rule yields exactly 36 prompts × four
initial roots × three checkpoints = 432 initial capture units per capable
backbone.

Actions are `KEEP`, `RESTART_BASE`, and `RESTART_FIXED`. At each
prompt/checkpoint, every action has four registered root outcomes initially:

- `KEEP` resumes each root's true state and is evaluated on that root's frozen
  terminal outcome;
- initial restart outcomes come from the frozen prompt-level core pool at
  seeds `4..7`; and
- if doubled, new roots `4..7` are added and the complementary frozen
  prompt-level restart pool at seeds `0..3` is added.

A frozen hash rotation maps restart-pool rows to root units so every action
uses every pool member exactly once per prompt/checkpoint. Restart rows are
always labeled `RESTART_POOL_SHARED_AT_PROMPT_LEVEL`, never “root-specific”.
The mapping is for balanced policy evaluation only; no outcome chooses it.
Whole-prompt folds and whole-prompt bootstrap clusters retain the dependence
created by restart reuse and repeated terminal outcomes across checkpoints.

Initial action evidence is therefore replicated across four roots, and the
doubled evidence across eight. No maximum over one observed draw, favorable
root, hand-picked continuation, or human choice is an oracle. A replicated
outcome-aware ceiling may be shown only as an unavailable diagnostic excluded
from every gate.

`KEEP` costs measured remaining NFE; restart costs one full native generation.
The action cap is one full generation beyond sunk prefix cost. Rank predicted
success, lower incremental cost, then `KEEP`, `RESTART_FIXED`,
`RESTART_BASE`. Invalid files are failures, not dropped rows. A failed true
resume makes the axis/backbone screen `NOT_IDENTIFIABLE`.

### 11.3 Prompt-plus-time/budget baseline and root-local state tier

Six deterministic prompt-grouped folds keep every root, checkpoint, action,
and pool reuse for a prompt in one fold. With 12 prompts, each fold holds out
two. Standardization and fitting use training folds only; no hyperparameter
search occurs.

The baseline is named `PROMPT_PLUS_TIME_BUDGET`. Its frozen features are
action × request/target factors, prompt-matrix metadata, checkpoint fraction,
elapsed NFE/time, remaining NFE/time budget, and measured action cost. The
state tier is named `PROMPT_PLUS_TIME_BUDGET_PLUS_STATE` and adds only the
current unit's root-local pre-action preview features: axis evaluator values,
integrity values, within-preview summaries, and frozen decoder metadata. It
excludes other roots, action outcomes, terminal features, human gold, and
held-out fitted values.

Both tiers use the same frozen Bernoulli-logit hierarchical MAP model:
intercept `Normal(0,2.5)`, coefficients `Normal(0,1)`, prompt intercept
`Normal(0,sigma_prompt)`, and `sigma_prompt ~ HalfNormal(1)`. The optimizer is
L-BFGS-B with at most 2,000 iterations and gradient tolerance `1e-8`; an unseen
prompt intercept is zero. There is no hyperparameter search. The target is
primary-axis success. Policy value is the equal-weight held-out mean across
prompts, roots, and checkpoints under the frozen mapped outcomes. Exact fold,
mapping, tie, bootstrap, and model settings are bound by
`configs/statistics_v2.json`.

### 11.4 Information, commitment, deviation, and four-way gate

At checkpoint `q`, report:

```text
LEGIBILITY(q) =
  [OOF_logloss(PROMPT_PLUS_TIME_BUDGET)
   - OOF_logloss(PROMPT_PLUS_TIME_BUDGET_PLUS_STATE)] / ln(2)

OUTCOME_COMMITMENT(q) =
  mean abs(2*p_hat_KEEP_root_state(prompt,root,q) - 1)

STATE_INCREMENTAL_VALUE =
  VALUE(PROMPT_PLUS_TIME_BUDGET_PLUS_STATE)
  - VALUE(PROMPT_PLUS_TIME_BUDGET)

CROSS_FITTED_DEVIATION_SHARE =
  mean I(action_state_OOF(prompt,root,q) != action_baseline_OOF(prompt,root,q))
```

Report calibration, Brier score, prompt-cluster intervals, and all three
curves at every checkpoint. The one-sided 95% lower bound is the fifth
percentile of 10,000 paired, stratified whole-prompt bootstraps.

The four-way gate is verbatim **ELIGIBLE / REPLICATION_ONLY /
INCONCLUSIVE_UNDERPOWERED / STOP_AXIS**. The four terminal labels are:

```text
ELIGIBLE
REPLICATION_ONLY
INCONCLUSIVE_UNDERPOWERED
STOP_AXIS
```

Apply this order at the initial four-root analysis:

1. `ELIGIBLE` iff the one-sided 95% lower bound on
   `STATE_INCREMENTAL_VALUE` is greater than zero **and**
   `CROSS_FITTED_DEVIATION_SHARE >= 0.10`.
2. `REPLICATION_ONLY` iff that lower bound is greater than zero but deviation
   share is below `0.10`; state predicts value but changes too few held-out
   actions for an eligibility headline.
3. `INCONCLUSIVE_UNDERPOWERED` iff the lower bound is not greater than zero,
   the point estimate is at least `0.05`, and the two-sided 95% interval still
   includes a positive value.
4. `STOP_AXIS` otherwise.

Thus `ELIGIBLE` always requires cross-fitted deviation share ≥0.10; statistical
value evidence alone cannot waive the policy-deviation floor.

Only `INCONCLUSIVE_UNDERPOWERED` triggers one preregistered doubling: add roots
`4..7`, add their root-local states and complementary prompt-level restart
pool, then refit once on combined roots `0..7` with unchanged folds, features,
priors, thresholds, seeds, and bootstrap. Apply the same four rules once to
that combined dataset. There is no second doubling. If the single re-gate is
again `INCONCLUSIVE_UNDERPOWERED`, that label is final. Neither
`REPLICATION_ONLY` nor `STOP_AXIS` permits more eligibility generation.

## 12. Solo-PI packet, timing pilot, blinding, and budget

The solo-PI target is at most three hours **including** the timing pilot. There
is no population or inter-rater reliability claim. Per primary backbone the
planned packet has 52 unique clips/presentations: 30 tempo, 12 targeted voice
stress-audit, and 10 integrity-axis stress-audit clips. Five hidden repeats per
backbone—two tempo, two voice, and one integrity selected by frozen hash—are
interleaved across at least two blocks and have zero evaluator weight.

| Component/backbone | Presentations | Frozen allowance | PI minutes |
| --- | ---: | --- | ---: |
| Tempo unique | 30 | 30-s playback/taps + 5-s response | 17.5 |
| Voice stress audit | 12 | 30-s playback + 5-s response | 7.0 |
| Integrity stress audit | 10 | 30-s playback + 5-s defect response | 5.8 |
| Hidden repeats | 5 | 35-s average | 2.9 |
| **Timed subtotal/backbone** | **57** | — | **33.2** |

Three backbones require 99.8 timed minutes. Fixed allowances are 10 minutes
instructions/calibration, 10 minutes breaks, 20 minutes replay/adjudication,
and 15 minutes for the single blinded timing pilot. Applying 15% contingency
to the resulting 154.8 minutes yields **178.0 minutes**, below the absolute
180-minute stop.

Phase B3 builds exactly one 8–10-item blinded timing-pilot bundle (target about
15 minutes) from retained foundation audio only; this makes zero new model
calls, contains no benchmark endpoint, and is not benchmark evidence. It
exercises both tap windows, defect checkboxes, voice labels, hidden repeats,
timing logging, and the stop control. The obtained bundle has nine
presentations and is `TIMING_PILOT_OFFERED_AWAITING_PI_RESPONSE`. Core
generation does **not** wait for pilot ingestion, but
`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION` until a
signed pilot receipt with actual minutes and usability/deviation fields is
ingested. If actual pilot time or the updated conservative projection would
exceed 180 minutes, packet assembly stops for amendment; sample rows are not
silently trimmed.

The receipt requires a separate strict PI attestation bound to the exact
bundle ID, build identity, and response SHA-256. It records required PI
identity `pxy1289`, matching typed signature, UTC signing time, measured
minutes equal to the UI session timer, `usability_status = PASS`, an empty
deviation list, and the exact affirmation
`I_ATTEST_THIS_TIMING_PILOT_RESPONSE_IS_COMPLETE_ACCURATE_AND_USABLE`.
Missing attestation, identity/signature mismatch, non-PASS usability, any
deviation, response-hash mismatch, or time mismatch fails closed before a
receipt is written; the immutable receipt binds the attestation SHA-256.

The UI hides backbone, condition, seed, automatic values, selection stratum,
and repeat identity. The administrative map is hashed before ratings. Before
each item/replay, the UI checks its entire allowance against remaining time;
it never starts an item that would cross 180 minutes. Missing labels remain
missing without result-guided substitution.

## 13. Build gates, launch queue, hard caps, and heartbeat

### 13.1 Terminal Phase-B gates

No benchmark endpoint is scored during Phase B.

- **B1 instruments:** terminal `PASS`; canonical promoted-OR port and mutation
  test PASS, pinned Beat This!/librosa pair and both tempo tolerances PASS, and
  integrity synthetic-injection suite PASS. The immutable B1 report records
  48 passing tests, zero model calls, and zero endpoint scores.
- **B2 adapters:** SA3 exact adapter identified; ACE-Step v1 exact frozen
  config port terminal; Stable Audio Open terminal `READY` or
  `BLOCKED_ON_LICENSE` with exact human acceptance/download/cache-verification
  steps. Across SAO and ACE-Step v1, the larger of model-call count and
  generated-output-slot count may not exceed 10; all mini-smoke outputs are
  retained and ledgered. Successful cost rows append actual duration,
  NFE/calls, synchronized wall, peak VRAM, placement, hashes,
  `MEASUREMENT_STATUS = MEASURED`, and `MEASUREMENT_SCOPE = MINI_SMOKE`;
  missing license access is not a zero-cost row.
- **B3 prompts/raters:** all Section-3 prompt and seed hashes resolved, rater
  builders PASS, one timing-pilot bundle built and offered. Pilot ingestion is
  not a generation gate.

At the design-freeze cutoff, B2's pre-generation build is terminal
`BUILD_COMPLETE_EXECUTION_PENDING_PHASE_A_FREEZE`: SA3 is
`READY_FOR_AUTHORIZED_BENCHMARK_CALL`, ACE-Step v1 is
`READY_FOR_AUTHORIZED_MINI_SMOKE`, SAO is `BLOCKED_ON_LICENSE`, and B2 has
made zero model calls, outputs, or measured cost rows. Its frozen pre-generation
record reports 37 passing CPU tests and Ruff PASS. Those are engineering gate
facts, not benchmark results. After the Phase-A freeze decision, the bounded
mini-smoke authority in this section may be exercised and its immutable
measured rows cited by the later launch decision.

The exact ACE-Step v1 mini-smoke plan is two non-benchmark 30-second calls,
zero retries, one A800, TP1, one replica, and at most 1,800 GPU-seconds. It
uses append-only `SEED_REGISTRY.md` rows `S-0008 = 73193008` and
`S-0009 = 73193009`; neither prompt belongs to a benchmark prompt set and no
instrument may score the outputs. The committed config, protocol, runner, and
external-authorization template in Section 3 fail closed until a post-freeze
decision and a clean-`origin/main` external claim bind the exact execution.
The live ACE environment is independently identified from
`/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm` by its conda metadata/history
and sorted `pip freeze --all`; the SA3 foundation package freeze is not used as
ACE environment evidence.

`BLOCKED_ON_LICENSE` is a valid terminal B2 status, but only `READY` backbones
receive queue rows. A blocked primary backbone remains registered and absent.

### 13.2 Core launch and absolute corpus cap

After v2 freeze and a launch decision, each `READY` backbone has exactly 1,536
registered core calls/outputs:

| Axis/condition | Outputs/backbone |
| --- | ---: |
| Vocal/instrumental `BASE` + positive `FIXED` | 384 |
| Instrumental `NEGATION_DIAGNOSTIC` | 96 |
| Tempo `BASE` + `FIXED` | 480 |
| Integrity `BASE` + `FIXED` | 288 |
| Exploratory structure `BASE` + `FIXED` | 288 |
| **Total** | **1,536** |

The absolute three-backbone core ceiling is 4,608 model calls and 4,608
retained outputs, each at most 30 seconds. No automatic retry, favorable
replacement, or extra prompt is inside that ceiling. State-screen resume calls
are separately ledgered and capped at 432 per capable backbone initially
(`36 prompts × 4 roots × 3 checkpoints`) plus at most one additional 432 only
after `INCONCLUSIVE_UNDERPOWERED`. Ordinary core launch materializes two
separate state-queue manifests but authorizes neither: the initial queue is
closed pending its own budget and decision, and the supplemental roots queue
is locked unless the initial gate is `INCONCLUSIVE_UNDERPOWERED` and a second
decision opens the sole doubling. Ordinary core workers cannot claim or
consume either state queue.

### 13.3 Measured conservative cap

Mini-smoke measurements are engineering bounds, not p95 estimates. For each
ready backbone, record:

- `c_m`: observed cold model-load plus first valid 30-second output seconds;
- `u_m`: maximum duration-normalized synchronized seconds among valid resident
  calls, normalized conservatively as `wall_seconds * 30/duration_seconds`;
- `R_m`: launched TP1 replica count; and
- `n_m`: scheduled core outputs, at most 1,536.

The frozen hard generation budget is:

```text
CORE_GPU_HOUR_CAP_m =
  [R_m*c_m + max(n_m-R_m,0)*(2*u_m)] / 3600
```

The factor two is a preregistered safety bound for sparse mini-smoke evidence,
not an uncertainty or expected-cost claim. Reaching the cap stops before the
next call and leaves rows missing; it never permits shorter clips or fewer
registered seeds. GPU evaluator and state-screen caps are recorded separately
before their queues open.

For SA3, obtained D-0020 values give `c_SA3 = 116.34399104863405 s`
(91.32002927735448-s load plus 25.023961771279573-s reference call) and
`u_SA3 = 25.023961771279573 s`. With one replica and all 1,536 core rows, the
formula gives a conservative
`CORE_GPU_HOUR_CAP_SA3 = 21.372196285799145 GPU-h`.
This does not claim p95 calibration. The earlier D-0013 singleton remains
`SA3_COST_OBSERVATION_STATUS = MEASURED_SINGLETON` and
`SA3_BENCHMARK_COST_CALIBRATION_STATUS = INSUFFICIENT_REPETITIONS` for any
p95 claim.

### 13.4 Queue-do-not-preempt and heartbeat

Each shard is single-node, one visible GPU, TP1, one replica. Parallel shards
may use disjoint idle GPUs on `an12` and/or `an29`; one model call never spans
nodes. Immediately before load, the launcher must hold a device lock and
verify no compute process, expected A800 identity, sufficient free VRAM above
the adapter's measured peak plus frozen safety margin, and no conflict with an
existing lock. If no safe device exists, the row stays queued.

Existing processes are never terminated, evicted, migrated, reconfigured, or
put at OOM risk. The queue waits rather than preempts. A post-load memory probe
must still leave the frozen safety reserve; otherwise unload cleanly before a
generation call and mark `PLACEMENT_HEADROOM_BLOCKED`.

Every active run writes an atomic heartbeat at least every 60 seconds with run
ID, node, physical/logical GPU, PID, Git/config/prompt hashes, current shard
and row, completed/failed counts, cumulative synchronized GPU seconds, peak
VRAM, last ledger hash, and timestamp. A stale heartbeat makes the supervisor
stop assigning new rows; it does not kill an active model call. Before every
adapter call, an `O_EXCL` request claim is durably fsynced; the ledger then
records hash-chained `CLAIMED`, `CALL_STARTED`, and exactly one terminal
`SUCCEEDED` or `FAILED` transition. A crash between claim and ledger remains
non-retryable and auditable from the claim. Every call, failure, and retained
audio artifact has an immutable ledger record; every retained
audio/provenance/sanity/commit artifact is bound by the terminal row.
Checkpoints and outputs are never overwritten.

## 14. Deliverables and licensing

| Deliverable | Contents | License/restriction |
| --- | --- | --- |
| Instruments | Wrappers, canonical configs, thresholds, synthetic fixtures, tests, audit cards. | Project-authored code MIT; third-party code/weights retain upstream terms. |
| Gold labels | De-identified PI labels, `unsure`, timing, repeats, strata, dictionary. | Project-authored tables CC BY 4.0; blind map released after analysis. |
| Atlas | Row outcomes, prompt-cluster summaries, defect-specific rates, audits, state curves, missingness. | Project-authored tables/figures CC BY 4.0; audio only where model terms permit. |
| Harness | Adapters, manifests, queues, ledgers, scorers, statistics, rater builders, tests. | Project-authored code MIT; dependencies separately identified. |

Model weights are not MIT. No license gate is bypassed, scripted around, or
misrepresented as technical failure. Exact applicable upstream terms and
redistribution limits are frozen per artifact.

## 15. Verified-citation policy

Only verified primary papers, official model cards, and official repositories
are cited; citations establish identity or method, not benchmark results.

1. Zach Evans et al., [Stable Audio 3](https://arxiv.org/abs/2605.17991), 2026;
   official [Medium Base card](https://huggingface.co/stabilityai/stable-audio-3-medium-base).
2. Zach Evans et al., [Stable Audio Open](https://arxiv.org/abs/2407.14358),
   2024; official [1.0 card](https://huggingface.co/stabilityai/stable-audio-open-1.0).
3. Junmin Gong et al.,
   [ACE-Step](https://arxiv.org/abs/2506.00045), 2025; official
   [repository](https://github.com/ace-step/ACE-Step).
4. Junmin Gong et al.,
   [ACE-Step 1.5](https://arxiv.org/abs/2602.00744), 2026; official
   [repository](https://github.com/ace-step/ACE-Step-1.5).
5. Francesco Foscarin, Jan Schlüter, and Gerhard Widmer,
   [Beat this!](https://arxiv.org/abs/2407.21658), ISMIR 2024; official
   [implementation](https://github.com/CPJKU/beat_this).
6. Brian McFee et al.,
   [librosa](https://doi.org/10.25080/Majora-7b98e3ed-003), SciPy 2015;
   [0.11.0 archive](https://doi.org/10.5281/zenodo.15006942).

`MTRF` is excluded as unverified. It has no citation, borrowed result,
operationalization, or benchmark role.

# Appendix A — execution cost, capability, and human effort

## A.1 Frozen workload

The v2 core has 1,536 outputs/backbone and at most 4,608 outputs/38.4 audio
hours across the three primary backbones. The 96-output increase over v1 is the
instrumental negation diagnostic; it has no confirmatory endpoint. A
license-blocked backbone contributes zero obtained rows, explicitly missing
rather than imputed.

The initial state screen has 36 prompts × 4 roots × 3 checkpoints = 432 true
state captures/resumes per state-capable backbone and reuses the frozen
terminal pool. Only an initial `INCONCLUSIVE_UNDERPOWERED` result permits the
same count once more for roots `4..7`. `NOT_IDENTIFIABLE` contributes zero
formal state calls and stays reason-coded.

## A.2 Obtained SA3 engineering evidence

The original bounded run
`sa3-foundation-20260719T134821.040493Z-9ea9d06209d6` remains terminal
`FAIL_ESCALATED`: A–D passed and its three E resumes failed before a resumed
DiT transition. It measured 46.013084 synchronized call seconds for 11
reserved calls, maximum allocated/reserved VRAM
5,890,185,728/10,464,788,480 bytes, and one warmed batch-one/batch-four pair.
Those singleton observations are retained, not promoted to p95 estimates.

D-0020's one consumed E-only retry run is
`sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24`, result SHA-256
`10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117`.
Four calls succeeded at actual NFE `50/35/20/10`, synchronized call wall
`25.023961771279573/3.7141848169267178/2.7067666836082935/
1.8672252222895622 s`, 115 total NFE, and
5,438,810,112/9,839,837,184-byte peak allocated/reserved VRAM. All three
resume waveforms exactly equaled the reference. Therefore:

| Scope | Terminal state | Interpretation |
| --- | --- | --- |
| SA3 Smoke-E technical capability | `SA3_SMOKE_E_RETRY_STATUS = PASS`; `SA3_STATE_CAPABILITY = PASS` | True-state export/resume works at foundation 30/60/80%; the claim is consumed. |
| SA3 formal v2 per-axis capability | `NOT_YET_EXECUTED` | v2 25/50/75 root-local captures are separate work after launch authority. |
| SA3 raw cost evidence | `SA3_COST_OBSERVATION_STATUS = MEASURED_SINGLETON` | Supports the conservative max-times-two launch cap, not p95 precision. |
| SA3 p95 calibration | `SA3_BENCHMARK_COST_CALIBRATION_STATUS = INSUFFICIENT_REPETITIONS` | No p95 claim is made or needed by the v2 max-times-two cap. |
| SAO adapter/cost | `BLOCKED_ON_LICENSE`; `NOT_MEASURED_BLOCKED_ON_LICENSE` | Exact human steps are frozen in the adapter config. Missing access is not a zero-cost measurement and creates no queue row. |
| ACE-Step v1 adapter/cost | `READY_FOR_AUTHORIZED_MINI_SMOKE`; `NOT_MEASURED_NO_GENERATION_AUTHORIZED_DURING_BUILD` | Offline source/weight preflight passed. A later measured mini-smoke row is required before its core queue opens. |
| ACE-Step v1.5 | `DEFERRED_SCOPE_BUDGET` | No v2 core or human row; future generation-only amendment needs no state-resume Gate-0. |

No other project's runtime measurement is imported.

## A.3 PI-minute accounting

`PI_LABELING_MINUTES_OBTAINED = 0.0` at this freeze-candidate cutoff. Planned
maximum is 178.0 minutes for the timing pilot, all three primary-backbone
packets, five hidden repeats/backbone, overhead, replay reserve, and 15%
contingency. The absolute stop is 180 minutes. Actual pilot, playback, pause,
tap, replay, and adjudication time is logged and reported.

## A.4 Gate state at this draft cutoff

`BENCHMARK_PREREG_V2_FROZEN = YES`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_CORE_GENERATION_STATUS = NOT_LAUNCHED`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

These cutoff facts do not predetermine the later freeze and launch decisions.
No benchmark generation is authorized by this draft.
