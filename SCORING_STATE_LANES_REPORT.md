# Benchmark v2 scoring and state lanes report

- Report date: 2026-07-22 (Asia/Shanghai)
- Frozen preregistration: `BENCHMARK_PREREG_v2.md`, SHA-256
  `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa`
- Scope: D-0029 through D-0032 openings and their execution evidence
- Scientific wording: model-level results in these lanes are
  **automatic-instrument outcomes**, not human-gold findings
- `HUMAN_GOLD_STATUS = NOT_HUMAN_GOLD`

## Lane status at the code-freeze boundary

| Lane | Opening | Freeze-boundary status | First required artifact |
| --- | --- | --- | --- |
| Automatic endpoint scoring | D-0029 | `OPEN; IMPLEMENTED_NOT_LAUNCHED` | `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/scoring-v2/automatic-scoring-v2-001/tables/integrity-prevalence-first.json` |
| SA3 formal state capture | D-0030 | `INITIAL_QUEUE_OPEN; IMPLEMENTED_NOT_LAUNCHED` | external run manifest and worker heartbeat under `.../runs/state-capture-v2/` |
| ACE-Step v1 state capability | D-0031 | `SOLE_PREFLIGHT_AUTHORIZED_NOT_CONSUMED` | `.../claims/ace-state-preflight-v2/ace-state-preflight-v2-one-attempt.terminal.json` |
| Human-audit packet | D-0032 | `ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA` | `.../control/human-packet-autoassembly-v2/heartbeat.json` |
| Stable Audio Open 1.0 | existing B2 license gate | `BLOCKED_ON_LICENSE` | verified access receipt after PI action |

These are authorization and implementation states, not obtained experimental
results. Runtime statuses and immutable artifact hashes are appended only after
the clean freeze commit is pushed and the corresponding lane actually runs.

## Completed ordinary-core inputs

The SA3 core source remains complete at 1,536/1,536 rows with zero failures.
The ordinary ACE worker ended naturally without intervention and is now also
complete at 1,536/1,536 rows with zero failures. The new receipt
`provenance/core/ace_core_completion_v2.json`, SHA-256
`813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0`,
binds its terminal heartbeat, generation queue, ledger, retained-artifact
counts, and measured execution. No worker was killed, restarted, or altered.

The scoring snapshot accepts only those terminal hash-bound sources. SAO has
no source rows and remains explicitly missing. No source is regenerated.

## D-0029 — automatic endpoint scoring

The scoring config is `configs/automatic_scoring_v2.json`, SHA-256
`1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd`.
It stages these outputs:

1. Per-axis, per-backbone automatic prevalence with frozen prompt-cluster
   bootstrap intervals, including 5% primary and 10% tempo sensitivity plus
   separate first/second-window outcomes.
2. Defect-specific clipping, dropout, silence, and crackle rows; the four-way
   integrity OR cannot replace them.
3. A fresh-output evaluator table reporting operationalization discordance
   only. Every row says that accuracy/failure claims are unauthorized without
   pooled PI gold.
4. A canonical candidate index for the later human packet. Its header retains
   all three primary backbones, while no SAO row is fabricated.

Integrity extraction is CPU-only and is staged first so the initial automatic
DSP prevalence table does not depend on evaluator GPU availability. Vocal and
tempo workers use at most four independent TP1-equivalent evaluator processes,
one per disjoint live-idle GPU.

## D-0030 — SA3 formal state-capture lane

The config is `configs/sa3_state_capture_v2.json`, SHA-256
`4bb6d6480dd5167da97e4907193204ac319df090668f976734de7d37da87d02e`.
D-0020's technical PASS is the precondition, not a substitute result. The
initial queue contains exactly 144 BASE prefix groups, 432 formal
`(prompt, root, checkpoint)` units, and 1,296 mapped action rows. It enforces:

- roots 0–3 and checkpoints 25/50/75%;
- preview/state features from only the same unit's root;
- six prompt-grouped folds;
- replicated `KEEP`, `RESTART_BASE`, and `RESTART_FIXED` action evidence;
- restart outcomes labeled `RESTART_POOL_SHARED_AT_PROMPT_LEVEL`; and
- no automatic retry, single-draw oracle, outcome-selected mapping, or access
  to the locked supplemental roots 4–7.

The prospectively frozen cap is `71,850.731647392 GPU-s` (19.95853656872
GPU-h), a D-0020-grounded factor-two engineering ceiling rather than a p95 or
expected-cost claim.

## D-0031 — ACE-Step v1 one-attempt preflight

The config is `configs/ace_state_preflight_v2.json`, SHA-256
`7996daa1803a71aeae2f9ac8441b73d8cc487eecd1343eb1ab4075e6cc563ed6`.
It schedules exactly one reference plus three separate-process resumes when
complete, while retaining the user's absolute envelope of at most eight
generations, one GPU, 30 seconds per clip, 600 GPU-seconds, and zero retries.
The nearest attainable 25/50/75% points in the frozen 45-transformer-NFE
schedule are transitions 9/15/20 with cumulative NFE 11/23/33. Equivalence is
exact shape/rate plus maximum absolute error at most `1e-5` and SNR at least
80 dB.

This is a technical capability test only. PASS opens a separately bound ACE
formal initial queue; any new failure makes
`ACE_STATE_CAPABILITY = NOT_IDENTIFIABLE` terminal, with eligibility then
continuing on SA3 alone. It never changes the already-complete ordinary ACE
core evidence.

## D-0032 — human-packet arm and timing pilot

The watcher config is `configs/human_packet_autoassembly_v2.json`, SHA-256
`519f71753ee8340320a9a32e0c8dd72a577e8e48aa57154f20379382520dd4db`.
It is fail-closed on two independent inputs:

1. a valid export from the already-offered nine-item blinded timing pilot;
2. a scorer status and candidate index with every frozen stratum for every
   primary human-audited backbone.

The offered PI bundle remains:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/
timing-pilot-bundles/
benchmark-v2-blinded-timing-pilot-04-51ebc904242e/index.html
```

The receipt path watched by the arm is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/
timing-pilot-receipts/benchmark-v2-blinded-timing-pilot-04/receipt.json
```

No response has been ingested at this boundary. SAO's missing strata also keep
the all-three-backbone packet closed; neither gate can silently downgrade the
packet to two backbones. The assembler accepts both exact 30-second SA3 files
and ACE's native `29.9073125 s` files under D-0026's inclusive ±0.25-second
rule.

## GPU placement and no-preemption rule

The latest read-only probe found an12 physical GPUs 0–3 occupied by existing
Ray workers at roughly 56 GB each and 100% utilization. They are excluded.
GPUs 4–7 were the four idle A800s, each with about 81,226 MiB free, no compute
PID, and 0% utilization. Runtime placement always probes again; this snapshot
does not reserve a card.

Every new GPU worker is single-node, TP1/R1, holds the shared per-device lock,
requires zero compute neighbors and at least 60 GB free before load, then at
least 20 GB free after its actual model/evaluator load. Scoring, state, and
preflight workers receive disjoint cards. If these conditions change, work
queues rather than preempting or risking a neighbor OOM.

## Stable Audio Open 1.0: exact PI steps

SAO remains `BLOCKED_ON_LICENSE`; no workaround or substitute is allowed. The
PI steps remain exactly:

1. Sign in to the PI-controlled Hugging Face account in a browser; do not send
   credentials or tokens to Codex.
2. Open `https://huggingface.co/stabilityai/stable-audio-open-1.0`, read the
   displayed model terms and Stability AI Community License, complete required
   access fields, and accept only if the PI agrees.
3. Wait until that account can access the model's Files and versions page.
4. Create a least-privilege read token and keep it outside Git, logs, shell
   history, chat, and committed configuration.
5. Use the project proxy wrapper to download the exact revision into a new
   no-clobber persistent directory; do not substitute another model or mirror
   identity.
6. Record the resolved 40-hex revision, every file path/size/SHA-256, displayed
   license identifier, and non-secret acceptance metadata in a receipt matching
   `provenance/b2/sao_access_receipt.schema.json`.
7. Unset the token, verify the snapshot and receipt offline, then request a new
   project decision changing only the runtime gate. Do not edit the frozen
   blocker in place.

## Verification at this boundary

Focused verification obtained before any new CUDA call:

- automatic scoring: 7 tests passed; Ruff passed;
- SA3 state capture: 6 tests passed; Ruff passed;
- ACE state preflight: 12 tests passed before the final safety hardening pass;
- human packet arm and duration rule: 28 tests passed; Ruff passed; and
- frozen v2 preregistration acceptance: 12 tests passed.

The repository-wide result and runtime artifacts are recorded in the final
update below; no planned value in this section is presented as obtained.

## Runtime update

### Observed 2026-07-22 after the freeze boundary

This section records obtained runtime evidence after the prospective boundary
above. It does not rewrite the earlier implementation statuses. Unless an
artifact below says otherwise, the observation is through 2026-07-22 01:58
Asia/Shanghai.

| Lane | Obtained status | First or terminal evidence |
| --- | --- | --- |
| ACE ordinary core | `COMPLETE` | `provenance/core/ace_core_completion_v2.json` |
| Automatic endpoint scoring | `SCORING_COMPLETE_MISSING_PRIMARY_BACKBONE` | final prevalence, evaluator-audit, candidate-index, and status artifacts below |
| SA3 formal state capture | `FAILED_STOPPED; NO RETRY` | `.../state-capture-v2/sa3-state-v2-001/workers/replica-00/heartbeat.json` |
| ACE state preflight | `PASS; SOLE ATTEMPT CONSUMED` | fixed terminal claim below |
| ACE formal state capture | `PREPARED_AUTHORIZED_QUEUE_ONLY_NO_MODEL_CALLS` | fresh ACE queue manifest below |
| Human-audit packet | `ARMED_WAITING_ON_TIMING_PILOT_AND_SCORING_STRATA` | watcher heartbeat below |
| Stable Audio Open 1.0 | `BLOCKED_ON_LICENSE` | exact PI steps remain in the preceding section |

### Ordinary ACE core completed naturally

The ordinary ACE worker was not touched by these lanes. It ended naturally at
1,536/1,536 calls and 384/384 shards, with zero failures and 1,536 retained
WAVs. The completion receipt is
`provenance/core/ace_core_completion_v2.json`, SHA-256
`813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0`.
It binds the complete heartbeat SHA-256
`bd6c3a007d32fccf7a274819a56b4c840f6a78ca6aa6c6482308e772bd1aff8d`,
generation queue SHA-256
`db4ce65dabee9219e30a5c22c0eb56ed7b0a6f9e3ebaf98302f725cb8e8fd37f`,
and ledger SHA-256
`7f63aac18b4c503b4f17a6c03d0239715229a9d7751cb6db1531e2bd592b76d9`.
Its measured final synchronized GPU time was `4,063.758026678115 s` on
an12 GPU 4, TP1/R1. This is execution accounting, not an endpoint result.

### ACE state preflight PASS and fresh formal queue

D-0033 records the one permitted ACE preflight as `PASS`. It ran once on an12
physical GPU 4, TP1/R1, from clean Git
`b734a9e1bfdb8db65310f31ed37056636a519db0` and used exactly four model
calls and four retained clips: one reference and three separate-process
resumes. No retry remains. The fixed terminal, result, and ledger SHA-256s are
respectively:

- `69afb2851dbe5b90e6c4c71cc5c4581740bce4b88a4aaab42a410c69c7f8bb7d`;
- `700ec8e32bd200d91f1345fb72d76b69c74678849152367f7f1661e2236398b9`;
- `adbaef777571a2a708f0d2667c332ae58c7a7ade91c771bc7677a88cff957441`.

The terminal path is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
claims/ace-state-preflight-v2/ace-state-preflight-v2-one-attempt.terminal.json
```

All three resumed waveforms matched the reference exactly: maximum absolute
error `0.0`, infinite SNR, identical 48-kHz stereo shape, and native
`29.9073125 s` duration. This passes the frozen `1e-5` maximum-error and
80-dB minimum-SNR tolerances. The reference/resume actual NFEs were
45/34/22/12. Cumulative synchronized GPU time was `309.50720739737153 s`,
exclusive one-GPU occupancy was `364.1350744701922 s`, and peak
allocated/reserved VRAM was `8,371,733,504 / 10,085,203,968 B`. The
measurement stays inside the 600-GPU-second preflight cap and supports only a
technical state-capability claim.

The PASS branch materialized a fresh ACE-derived initial queue at:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
runs/state-capture-v2/ace-state-v2-001/queues/initial/
```

Its manifest SHA-256 is
`62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a`.
The queue has 144 prefix groups, 432 `(prompt, root, checkpoint)` units, 36
prompt-grouped fold rows, and 1,296 replicated-action rows. Their respective
SHA-256s are
`68692ff92fcf7a4e8d4f251306a42a083c1e919fd8554c6ce1c15d8dc4e75f91`,
`9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f`,
`f58c74ac64e1229b5b96528d802d858a96beb52810c87932548b54e25b6a5262`,
and
`82f2362be89d29af1ae942460312043da470532bacd5a76d71f7007180a4d536`.
The manifest explicitly rejects the legacy SA3-derived placeholder, reports
`execution_started = false` and `model_calls = 0`, and keeps supplemental
roots locked. The initial ceiling is `104,870.9014474153536 GPU-s`; no ACE
formal state-capture worker has been launched by this materialization.

### SA3 state lane failed closed on its first resume

The SA3 initial queue was materialized with 144 prefix groups, 432 units, and
1,296 replicated-action rows, then authorized and launched on an12 physical
GPU 4. Its launch claim SHA-256 is
`196fe5b393c2ba4ed1549eda96134ebbf2886a192012ebd926bb067be126c842`.
The retained run is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
runs/state-capture-v2/sa3-state-v2-001/
```

The worker staged the first root reference, previews, and checkpoints, then
failed on the first separate-process resume. Publication had renamed a
checkpoint to its canonical destination without rebinding the adjacent state
metadata's filename. The child therefore stopped on
`checkpoint state metadata names a different file`. The immutable heartbeat
is `FAILED_STOPPED`, with zero formal units completed and one failed; its
SHA-256 is
`50c0a8320e142151b36581debe48330c6b3209764067f84a4c4cd4003239b38e`.
The six-row failure ledger SHA-256 is
`68ddc4f56dbbb9518c5f8ba8a91fa4d757acb8d18c80da31be1f99d60f3011a5`.
No retry was made, the failed run and all staged/published evidence are
retained, and there is no authority to rerun it. A narrowly scoped sidecar
rebind fix and regression test were committed and pushed as
`61ddecf457ad5902fd9bf529a121411dd41ac043`; they are engineering evidence,
not an obtained rerun result.

### Automatic scoring is terminal for the available backbones and automatic-only

The scoring run snapshots only completed ordinary-core shards: all 384 SA3
and all 384 ACE shards. Integrity extraction completed all eight CPU shards,
72 rows each. The first obtained table is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
runs/scoring-v2/automatic-scoring-v2-001/tables/
integrity-prevalence-first.json
```

Its SHA-256 is
`2caa3e375a222fd1c7d4d6e7aab516aa6c18cc7d967a9181d7aafebfa8702018`.
It contains 12 per-backbone rows, including the defect-specific,
integrity-OR, and file-validity outcomes with prompt-cluster intervals. It
explicitly records `human_gold_claims = false` and
`INTEGRITY_FIRST_PREVALENCE_COMPLETE_AUTOMATIC_DSP_ONLY`. These are
**automatic-instrument outcomes**, not human-gold findings.

Tempo feature extraction is complete in four 240-row shards. Part 0 through
part 3 SHA-256s are, in order,
`08550486d4e94957c356a86e3a509762eb9a68e9efbd386ac71d831f02b1babb`,
`1d43f3779f205f1eb2fb4852a4a32fafc5c679b19cfe9700d52823669840dfa3`,
`6952073c59c2669944341231079ecbf661ecea1f83b95be34af42b91322642cc`,
and
`61c9ae22ceb50b4ed3a05bd699f908c612346c81ec320497601935e84f02d06e`.

The first vocal part-0 and part-1 attempts failed before writing a feature
shard because the implementation demanded equality between the PANNs label
table and the frozen vocal source set, while the promoted old instrument uses
their intersection. The failure is an implementation label-check bug, not a
model outcome. The focused correction and its regression test were committed
and pushed as `61ddecf457ad5902fd9bf529a121411dd41ac043`. A clean four-part
relaunch then completed all four 240-row vocal feature shards. Part 0 through
part 3 SHA-256s are, in order,
`40b22bfb961064fb6e02ae3607900c6fa7523c102a455255c526d7d0c545a077`,
`6fd35c794f942e6ff5770f997ffad234ba5987d8c64d96a14682929926bebf25`,
`933beca555410768a044075202321272bd61a206112607864bad88db5aee6af3`,
and
`dc3ef7bfcd9463c6d773ac102c9f40b16c2c80353d4406daa46ae4fc294f79a4`.
The failed logs remain retained; they are not counted as model outcomes.

Final aggregation then completed these immutable outputs:

| Artifact | Status / rows | SHA-256 |
| --- | --- | --- |
| `tables/prevalence.json` | `AUTOMATIC_PREVALENCE_COMPLETE`; 192 rows | `0be7513c018c4e6e088de96960b892e1cd94f2312fa2cca9abd16cdb9a402b9c` |
| `tables/evaluator-audit.json` | `FRESH_OUTPUT_OPERATIONALIZATION_DISCORDANCE_ONLY`; 16 rows | `b7baa6089170ba7b1f7a2785c9fd9a30413e048283bec22f99959c8059eb3094` |
| `tables/human-audit-candidate-index.json` | 2,496 automatic-only candidate rows | `4538d75aea8e245affffbace63ff9f214598cdfa284ed95052827ea1a4978bda` |
| `scoring-status.json` | `SCORING_COMPLETE_MISSING_PRIMARY_BACKBONE` | `9fc9b01e19af41bb588ef4feb3a88da1d3de9540a087e730a17ce3d65b3789b6` |

All four are under:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
runs/scoring-v2/automatic-scoring-v2-001/
```

The prevalence table has 24 vocal/instrumental, 96 tempo, and 72 integrity
rows, all with `human_gold_claims = false`. The evaluator-audit table has 4,
4, and 8 rows for those axes respectively; it explicitly sets
`accuracy_claim_authorized = false`. It reports fresh-output
operationalization discordance only, never evaluator accuracy against human
gold. The normalized automatic-outcome file has 2,496 rows, SHA-256
`e2961646ad811cab4c917ec9056f2127ff1454ddeaf7dd4b668d3617ba368f63`.
Model-level voice entries remain automatic-instrument outcomes under the v2
targeted-stress-audit wording.

The candidate index retains the frozen three-backbone header but contains
1,248 SA3 and 1,248 ACE rows and zero SAO rows. Accordingly,
`scoring-status.json` records both available backbones as
`AUTOMATIC_ENDPOINTS_SCORED`, SAO as `MISSING_BLOCKED_ON_LICENSE`, and the
candidate index as `INCOMPLETE_FROZEN_PRIMARY_BACKBONE_STRATA`. This is a
terminal and honest two-available-backbone scoring result, not permission to
downgrade the three-backbone human packet.

### Human packet remains fail-closed

The CPU watcher is armed at:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/
control/human-packet-autoassembly-v2/heartbeat.json
```

The heartbeat observed at 2026-07-22 01:58:32 Asia/Shanghai has SHA-256
`e1236aa91a391f98285dd66f55cc83a4c6d6896678d776c3ae1888898eecf29c`
and reports `ARMED_WAITING_ON_TIMING_PILOT` plus
`MISSING_SCORING_STRATA`. The PI pilot receipt is absent, and the final scorer
status identifies SAO's frozen primary strata as unavailable. No human-audit
packet was assembled and no human-gold claim is authorized.
This heartbeat is an intentionally mutable operational file: the historical
bytes were not separately snapshotted, so its historical SHA is a timestamped
operator observation rather than an independently reproducible immutable
claim.

### Placement and verification evidence

All new CUDA execution stayed on an12. The jobs used only disjoint physical
GPUs 4–7 under the cooperative locks, TP1/R1, live idle/headroom probes, and
queue-don't-preempt rule; GPUs 0–3 and neighboring processes were not
preempted or modified. The ACE preflight and SA3 state launch were serialized
on GPU 4. Scoring used idle cards independently and never shared the
generation/state allocation.

After both focused fixes were committed and these report edits were applied,
the repository-wide suite completed with `329 passed, 111 subtests passed in
130.81 s`. A focused run covering lane-report governance plus both corrected
modules also passed all 17 collected tests, and repository Ruff passed.
Stable Audio Open 1.0 remains `BLOCKED_ON_LICENSE`; the exact seven human
steps in the preceding section are unchanged.

## 2026-07-22 addendum — Stage-1-first and SAO-live static boundary

This addendum records the repository's static control state after PI
authorizations D-0034 through D-0038. It does not revise the historical
runtime evidence above and does not claim that any newly authorized model
call, state unit, scorer, or packet assembly has run.

### Stage-1 outcome screen is specification-blocked

The CPU gate is `BLOCKED_MISSING_FROZEN_THRESHOLDS`. The frozen v2 record does
not supply numerical minima for either `baseline_failure_rate` or
`mixed_outcome_prompt_share`, so the fail-closed runner has not read the
bound scored rows, computed a confidence interval, assigned a verdict, or
created a cancellation ledger. The six-cell status is therefore:

| Axis | Backbone | BASE failure rate (95% CI) | Mixed-outcome prompt share (95% CI) | Verdict |
| --- | --- | --- | --- | --- |
| Integrity | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Integrity | ACE-Step v1 | Not computed | Not computed | Not computed |
| Tempo, primary 5% band | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Tempo, primary 5% band | ACE-Step v1 | Not computed | Not computed | Not computed |
| Vocal/instrumental automatic instrument | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Vocal/instrumental automatic instrument | ACE-Step v1 | Not computed | Not computed | Not computed |

“Not computed” is a specification status, not an outcome-gate verdict. No
cell is currently labeled `OUTCOME_SCREEN_PASS` or `STOP_AXIS_STAGE1`, and no
state unit is currently labeled `CANCELLED_STAGE1`. The blocked policy and
immutable runtime bindings are in
`configs/stage1_outcome_gates_v2.json`, SHA-256
`bc54978d8257e14dd373c34c2401f99beb20be78fc4a7a97f762dad67a1b82bd`.
The complete blocked-state rationale is in `STAGE1_OUTCOME_GATES.md`.

### State openings are conditional and have executed zero units

D-0035 prospectively opens only the SA3 Stage-1 survivors under
`configs/sa3_state_restricted_rerun_v2.json`, SHA-256
`67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`.
That contract binds the identical materialized queue, the original failed
request, and metadata-filename fix commit
`61ddecf457ad5902fd9bf529a121411dd41ac043`; it requires one-root validation
before continuation and permanently stops on any new failure class. Because
Stage-1 has no survivor set, the restricted rerun has not been launched and
has executed zero units. The failed unit has not yet been replayed.

D-0036 likewise prospectively opens only ACE Stage-1 survivors under
`configs/ace_state_formal_v2.json`, SHA-256
`4cd688c71cff19104d1932386b42c4f1090cce5c5cd20dc61f7881e26a6fba89`.
Its supplemental queue remains locked, and STOP cells would prohibit both
execution and scoring. No ACE formal initial worker has been launched under
this opening, so it too has executed zero units. Both state contracts bind
the future Stage-1 result at
`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/stage1-outcome-gates.json`
and cancellation summary at
`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/cancellations/summary.json`;
neither artifact exists as an obtained gate result at this boundary.

### Decision-grade automatic tables are implemented but not run

The no-clobber builder at `scripts/build_decision_grade_tables.py`, SHA-256
`21f1e01c0a4eb5af7a74bd24e8d0d9ff5f9c151833818a7da2ba5d809a470ffd`,
and implementation at `src/scoring/decision_grade.py`, SHA-256
`cd0a7b3e3cec9ee74c592ff2e6d8438ce1a5a148ac5957d99b90f390aa197428`,
are ready to emit condition-specific per-axis prevalence at both the primary
5% and sensitivity 10% tempo bands, first/second-window drift, and
instrument-disagreement summaries. Every output is watermarked
`AUTOMATIC-INSTRUMENT OUTCOMES`; the builder prohibits accuracy or human-gold
claims. It requires explicit immutable input, scoring-status, scoring-config,
and completed-snapshot bindings. It has not been run in this authorization
round because the PI required Stage-1 outcome gates first. Consequently, no
new decision-grade table path or measured result is claimed here. The current
automatic-scoring configuration is `configs/automatic_scoring_v2.json`,
SHA-256
`1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd`.

### Stable Audio Open is statically opened, with no acquisition or generation yet

D-0037 opens controlled acquisition and the exact three-call engineering
smoke under `configs/sao_live_v2.json`, SHA-256
`850c27343ff06045a6b19e84f93c10ddc7e0afc9d6d0466497ada532d4452aed`.
A read-only Hugging Face credential is available in the local controlled
environment. Its value has not been printed, copied into the repository,
logged, ledgered, or placed in a manifest; the acquisition contract permits
it only in process memory and requires it to be unset after download. At this
static boundary no SAO snapshot has been downloaded, no acquisition receipt
has been obtained, and none of the three smoke generations or 1,536 core rows
has run. The exact core run remains subject to the post-smoke sealed-receipt
opening specified by D-0037.

SAO is generation-and-scoring only for this cycle:
`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`, and eligibility remains restricted to
SA3 plus ACE. No SAO state preflight, state queue, or eligibility-scope
expansion is claimed.

### SAO-aware packet watcher is armed behind both gates

D-0038 arms the fail-closed contract in
`configs/human_packet_autoassembly_v2_sao.json`, SHA-256
`68b74081056136ef2b72d90cdd7466b5ae4aafc3da2f4ffac6942d16526ff144`.
Before assembly, it requires the exact final scoring status
`SCORING_COMPLETE_ALL_PRIMARY_BACKBONES` at
`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/scoring-v2/automatic-scoring-v2-sao-final-001/scoring-status.json`
and its candidate index. Its preassembly validation requires actual
cross-instrument disagreement coverage in both voice directions for every
primary backbone and at least one actual Beat This!/librosa disagreement in
the tempo disagreement-or-invalid stratum. These are evidence checks, not
merely named slots.

Assembly may fire only after both independent conditions are true: the
timing-pilot receipt has status `TIMING_PILOT_INGESTED`, and final SAO scoring
provides every required three-backbone stratum. Neither packet assembly nor a
human-gold claim is made at this static boundary. This addendum records the
armed configuration and authorization only; it does not claim a new watcher
heartbeat or assembled packet.

### Static verification status

Focused and repository-wide verification of this combined change set remain
pending at this reporting boundary. No new test count or suite-wide PASS is
claimed in this addendum.

### Verification update after the static boundary

After the static artifacts above were complete, the repository-wide suite
passed with `409 passed, 111 subtests passed in 397.94 s`; repository-wide
Ruff and `git diff --check` also passed. The final rerun included the
append-only seed-registry governance checks for S-0011/S-0012. No network,
CUDA, state execution, endpoint scoring, or packet assembly occurred during
these tests.

## 2026-07-22 terminal update — Stage-1, D-0040 tables, and SAO live

| Lane | Current status | First or terminal artifact |
| --- | --- | --- |
| Stage-1 outcome screen | `BLOCKED_MISSING_FROZEN_THRESHOLDS` | `STAGE1_OUTCOME_GATES.md`; no result/cancellation artifact |
| SA3 restricted state rerun | `CLOSED_PENDING_STAGE1_RESULT` | Zero units executed |
| ACE formal initial state | `CLOSED_PENDING_STAGE1_RESULT` | Zero units executed; supplemental locked |
| D-0040 decision-grade tables | `PARTIAL_VERIFIED_SOURCES` | `.../decision-grade-v2-001/automatic-instrument-tables.json` |
| SAO acquisition | `COMPLETE_VERIFIED` | `.../sao-acquisition-recovery-v2-002/access-receipt.json` |
| SAO mini-smoke | `FAILED_STOPPED_NO_RETRY` | `.../sao-mini-smoke-v2-002/sao-mini-smoke-terminal.json` |
| SAO ordinary core | `NOT_AUTHORIZED_ENGINEERING_FAILURE` | No run directory, queue, heartbeat, ledger, or shard |
| SAO automatic scoring | `NOT_AUTHORIZED_NO_COMPLETED_SHARDS` | No SAO score table or candidate strata |
| Packet watcher | `ARMED_WAITING_ON_TIMING_PILOT_AND_SCORING_STRATA` | Mutable heartbeat remains active; no packet |

### Stage-1 verdict cells

Both registered numerical minima remain absent. The CPU runner has therefore
read no scored row and produced no CI or formal verdict:

| Axis | Backbone | Failure-rate CI | Mixed-prompt-share CI | Status |
| --- | --- | --- | --- | --- |
| Integrity | stable-audio-3-medium-base | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |
| Integrity | ACE-Step v1 | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |
| Tempo, 5% primary | stable-audio-3-medium-base | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |
| Tempo, 5% primary | ACE-Step v1 | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |
| Vocal/instrumental automatic instrument | stable-audio-3-medium-base | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |
| Vocal/instrumental automatic instrument | ACE-Step v1 | Not computed | Not computed | `NO_VERDICT_SPECIFICATION_BLOCKED` |

No cell is `STOP_AXIS_STAGE1`, so no cancellation was ledgered. No cell is a
survivor either, so both formal state workers remain closed.

### Decision-grade table path and contents

The D-0040 output is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
benchmark_v2_runtime/runs/decision-grade-v2/decision-grade-v2-001/
automatic-instrument-tables.json
```

SHA-256 is
`33b15bf8811d1a2f85575605eef95e58e253f77767e79575dc5a6ec263473d94`.
It includes SA3 and ACE only: 64 primary/diagnostic prevalence rows, eight
window-drift rows, 28 primary disagreement rows, plus separate negation
diagnostics. Tempo has 5% primary and 10% sensitivity metrics; integrity is
defect-separated. Every reported row is watermarked
`AUTOMATIC-INSTRUMENT OUTCOMES`; output-language validation passed and no
human-gold or accuracy claim is authorized. D-0043 makes an SAO extension
unavailable in this cycle.

### SAO failure and queue closure

The sole D-0042 attempt used an12 physical GPU 4, TP1/R1, after observing
85,171,634,176 free VRAM bytes, 0% utilization, and no compute process. Its
claim SHA-256 is
`add88f095bb969c736a28141b0ed89ce6a704e732daeac4b7d2f87536f086184`.
The first `adapter.generate()` attempt stopped before model construction
completed because PyWavelets 1.4.1 is binary-incompatible with NumPy 2.2.6 in
the frozen runtime. The terminal SHA-256 is
`3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097`;
the one-row failed-call ledger SHA-256 is
`bc51c5b926c01eb8afbf774e3763304b6ddb0bbf74890ea8a3eb0dac13bd2813`.
There were one model-call attempt, zero completed model loads, zero WAVs, zero
benchmark endpoint scores, and no measured NFE/cost row. The repository
terminal receipt is `provenance/b2/sao_live_terminal_v2.json`, SHA-256
`c50a9108b910354d7f74d78fdce02587e7d48cd52f16b32e68df6f3b2fb3a153`.

The frozen no-retry rule is now terminal. No environment repair or second
claim is authorized; consequently no SAO 1,536-row core queue, generation
heartbeat, first shard, automatic scorer, or SAO packet stratum exists. SAO
state remains `NOT_ATTEMPTED`, and eligibility remains SA3 plus ACE only.

The watcher process is still alive. At 2026-07-22 11:33:17 UTC its mutable
heartbeat reported `MISSING_SCORING_STRATA` and
`BLOCKED_ON_TIMING_PILOT_INGESTION`, with observed SHA-256
`5a47a54796bc6df49cce24b172c4305d89645df12f33670f1aa068958c41a38e`.
The cross-instrument preassembly test remains enforced; no packet was
assembled.
