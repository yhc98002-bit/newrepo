# Benchmark v2 freeze, build, and launch report

- Report date: 2026-07-21 (Asia/Shanghai)
- Scope: preregistration freeze, Phase-B build receipts, and the first
  ledgered ordinary-core batch
- Benchmark result status: **no endpoint has been scored**
- Human-audit packet: **not assembled**; timing-pilot ingestion is still
  required

## Executive status

| Phase | Terminal status | Evidence |
| --- | --- | --- |
| A — preregistration v2 | `FROZEN_PROSPECTIVE_DESIGN` | D-0021; `BENCHMARK_PREREG_v2.md` SHA-256 `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| B1 — instruments | `PASS` | `provenance/b1/B1_VALIDATION_REPORT.json` SHA-256 `656c8f960538ac0e35ea85786d1025d2350b581a0adb510a9879b2917506d448` |
| B2 — adapters | `TERMINAL` | `provenance/b2/build_status_terminal_v2.json` SHA-256 `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| B3 — prompts and raters | `PASS; TIMING_PILOT_OFFERED_AWAITING_PI_RESPONSE` | prompt manifest SHA-256 `171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089`; offer record SHA-256 `645cca46a001b42aace2f20a95d35921c6e26d7c56665cb7c457b30cf57227cb` |
| C — ordinary core | `LAUNCHED_FIRST_LEDGERED_BATCH` | active run `benchmark-core-v2-20260720t174500z`; immutable shard-0 heartbeat SHA-256 `e0cbcec63a1c400b6798ec0e14b747c65f1c73f51944315a07dc591deb30bea3` |

The active worker continues after the milestone, as required by
`BENCHMARK_CORE_PROTOCOL_v2.md`. Stable Audio Open 1.0 and ACE-Step v1 have no
core queue rows. The initial and supplemental state queues are materialized
but closed. No evaluator, best-of-N selector, or human-audit packet builder is
running.

## Phase A — frozen preregistration v2

D-0021 freezes v2 without altering v1. Its exact file identity is above, and
its prompt-set identities are committed in `prompts/v2/manifest.json`. The
eight adjudicated changes are present as follows:

1. The primary vocal/instrumental fixed intervention is positive-only — “A
   purely instrumental arrangement led throughout by the named instruments” —
   while negation is diagnostic only.
2. The vocal packet is a targeted human stress audit. Model-level voice
   outcomes are automatic-instrument outcomes, not general human findings.
3. Tempo uses a 5% primary tolerance, a preregistered 10% sensitivity, and
   separate first-window, second-window, and drift reports.
4. Integrity uses defect-specific clipping, dropout, silence, and crackle
   rates. Human strata include each defect, clean-side controls, and
   sharp/percussive controls; synthetic-injection validation is a hard
   pre-generation gate.
5. Exactly three backbones are primary human-audited. A fourth requires an
   amendment or a prospectively declared automatic-only tier.
6. Eligibility units are `(prompt, root, checkpoint)`; state features use only
   that root's preview, folds are prompt-grouped, and restart outcomes are
   labeled as a frozen prompt-level pool.
7. The gate is verbatim `ELIGIBLE / REPLICATION_ONLY /
   INCONCLUSIVE_UNDERPOWERED / STOP_AXIS`. `ELIGIBLE` requires cross-fitted
   deviation share at least 0.10. Only `INCONCLUSIVE_UNDERPOWERED` permits one
   doubling and one re-gate. The comparator is named the prompt-plus-time/
   budget baseline.
8. ACE-Step v1.5 is deferred for scope and solo-PI budget. Its future path is
   a generation-only amendment, without a Gate-0 state-resume condition.

The citation audit uses verified primary papers, official repositories/model
cards, and version archives only. `provenance/citation_audit_v2.json` records
MTRF as unverified and excluded.

## Phase B1 — instruments

`provenance/b1/B1_VALIDATION_REPORT.json` is terminal `PASS` with zero model
calls and zero benchmark endpoints scored.

- The promoted-OR vocal/instrumental instrument is ported through canonical
  threshold parsing. The report binds the promotion artifact SHA-256
  `2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2`
  and old reference implementation SHA-256
  `3aa68674b9ce919d407f25070a93ca73f14ed39af36f41090a4db000b5df1524`;
  tests forbid substituting hard-coded thresholds.
- The tempo pair pins Beat This! and librosa and implements the frozen
  disagreement rule, octave-invariant error, 5% primary band, 10%
  sensitivity band, and window-separated drift outputs.
- The integrity DSP set was exercised against deterministic synthetic
  injections and clean controls before generation. All defect injections,
  clean-side controls, the sharp/percussive control, stereo-any-channel
  behavior, duration validity, and non-finite-input cases passed. The
  validation receipt SHA-256 is
  `4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab`.

Beat This! and librosa were not invoked on benchmark audio in B1; only their
frozen aggregation contract was tested. That diagnostic evidence is not an
obtained benchmark result.

## Phase B2 — adapters and bounded mini-smoke

All three rows in `provenance/b2/build_status_terminal_v2.json` are terminal:

| Backbone | Build / queue status | Measured or blocking evidence |
| --- | --- | --- |
| Stable Audio 3 Medium Base | `MEASURED_READY` / `READY` | D-0020 measured `c_m = 116.34399104863405 s`, `u_m = 25.023961771279573 s`, state capability `PASS` |
| Stable Audio Open 1.0 | `BLOCKED_ON_LICENSE` / `BLOCKED_ON_LICENSE` | No credential, access acceptance, download, or generation was attempted; cost is not measured and is not treated as zero |
| ACE-Step v1 | `FAIL_ESCALATED` / `BLOCKED_ON_ENGINEERING_FAILURE` | One retained 30-second request decoded to `29.9073125 s`; exact-duration sanity failed, so the second authorized call was not made and there was no retry |

The user ceiling was ten B2 calls; D-0021 tightened the executable cap to two,
of which one call and one output were consumed. The ACE failure row remains a
measured engineering-cost row, not a benchmark result: actual NFE 45,
synchronized wall `27.25068249553442 s`, load wall `182.45191994681954 s`, peak
allocated/reserved VRAM
`8,371,735,040 / 10,085,203,968 B`. Its retained WAV SHA-256 is
`1a86fb30dceeb03f5da4e0bcb1cbf488aa2fc7490ac1c8297125e451635bd458`.

The prior an29 submission was `REFUSED_PREFLIGHT` before lock or claim because
node-local `/tmp` was full. It made zero calls and outputs. The unconsumed plan
was safely placed on an12 GPU 4 without changing neighboring processes.

Stable Audio Open can move only through the exact human steps in
`configs/backbones/stable_audio_open_1_0.json`: PI browser review and explicit
acceptance, a PI-controlled least-privilege token kept out of project records,
proxy-wrapped acquisition of the exact revision to a new directory, a
path/size/SHA/license receipt matching
`provenance/b2/sao_access_receipt.schema.json`, offline verification, and a new
decision. No substitute model is permitted.

## Phase B3 — frozen prompts, rater builders, and timing pilot

The prompt set contains 90 standardized prompt rows: 24 vocal/instrumental,
30 tempo, 18 integrity, and 18 exploratory structure. Eight registered roots
are used per benchmark cell. Exact hashes are:

| File | SHA-256 |
| --- | --- |
| `prompts/v2/vocal_instrumental.json` | `602c4e0fb419d7a300116eb5fb76c30a8e19364aaef566aec05425caffed9f90` |
| `prompts/v2/tempo.json` | `16e31c155e1d535f2211fcd85c8d666c9ba7a6636e4487fd43ea2fd5fa0e36ab` |
| `prompts/v2/integrity.json` | `be0e7c65fa8dfad8c7fdbf4456b2c1ad7e6f4fe0bbeb67eba2fcbf96b5f16d03` |
| `prompts/v2/structure_exploratory.json` | `6e9ca89c20ebb43313d9b492140970d876a5cfc657cf123cfe44b7d89e974af8` |
| `prompts/v2/seed_registry.json` | `2115d7e70a6c3f4dd19f38503861b8aeb3595a8f64dd1fc839d7a209e80724eb` |

The blinded rater builders and tap-protocol UI passed their tests. The one
active pilot offer has nine items and a target of about 15 PI minutes:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/
timing-pilot-bundles/
benchmark-v2-blinded-timing-pilot-04-51ebc904242e/index.html
```

Its bundle JSON and manifest SHA-256s are respectively
`a25454b31672a435ffeb5cdb10593f0ae99dfbe4426e2ae409f71f2dcd2da537`
and `715a2ac5024965a57525f836b690fe21fb0fd5bb1aac25ba35e94fed44ad3a80`.
No PI response has been ingested, so obtained PI time is currently zero and
the human-audit packet remains blocked. Core generation is intentionally not
blocked by pilot ingestion.

## Phase C — ordinary-core launch

### Authorization and recovery

D-0023 authorized the exact ordinary SA3 queue. The initial run
`benchmark-core-v2-20260720t173000z` failed closed before adapter load,
request claim, model call, audio, or ledger append because its validator
incorrectly compared the CUDA local build string to public wheel metadata.
Its zero-byte ledger, zero claims, zero WAVs, logs, and terminal heartbeat are
retained and bound by D-0024; the run is not reused.

D-0024 corrects only that identity representation: public distribution
metadata must be exactly `torch = torchaudio = 2.7.1`, imported module builds
must be exactly `2.7.1+cu126`, and the CUDA build must be `12.6`. It also binds
the complete project-local SA3 runtime closure in every new launch claim. The
correction changes no prompt, seed, NFE, duration, queue, budget, placement,
evaluator, or retry rule.

### Active immutable bundle

- Run: `benchmark-core-v2-20260720t174500z`
- Launch Git: `f8a44fedf4a466d8dea43c81f58bc6fdb2f8bae1`, clean and equal to
  `origin/main` at launch
- Config SHA-256:
  `d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61`
- Launch claim SHA-256:
  `b03e25ec7ab098d3c563169626c5b1888c7c0aad619e978575b28090cba096fa`
- Run manifest SHA-256:
  `e3d6e8a11bc4a0dd47cd454823463cb699c76b79671ec4aadc09b4799428f56c`
- Generation queue: 1,536 rows, SHA-256
  `afedee0bb422c27c2cad64e7be9dc960384f706f8f9201bbea95e8f2418c7bf4`
- Initial state queue: 432 rows, SHA-256
  `bc03a333e9cb096747ca7d9392a1a33a1c781315b1c1c698b20c888f74ca00c8`,
  closed
- Supplemental state queue: 432 rows, SHA-256
  `e7eb055e53183f2f6f85bd6ede586e9ed22a390a07cc149bdb121261961da8c1`,
  locked
- Placement: an12, physical GPU 4 exposed as logical GPU 0, TP1, one replica
- Placement rationale: SA3 fits one A800; TP1 avoids unnecessary replication
  and leaves neighboring GPU 0–3 jobs untouched

Before launch, GPU 4 was an idle A800 with 81,226 MiB free, no compute PID,
and 0% utilization. The worker's first-batch peak allocated/reserved VRAM was
`5,437,102,080 / 9,839,837,184 B`; the frozen post-load reserve remained
available.

The initial SSH submission used a node wrapper that stripped shell variables
and was rejected before worker creation. The same unconsumed run was then
started with absolute paths. The rejected submission created no worker,
request claim, model call, ledger row, or audio and is not a generation retry.

### First ledgered batch

Immutable heartbeat snapshot
`workers/sa3-medium-base/heartbeat-snapshots/
shard-000000-e0cbcec63a1c400b6798ec0e14b747c65f1c73f51944315a07dc591deb30bea3.json`
has SHA-256 `e0cbcec63a1c400b6798ec0e14b747c65f1c73f51944315a07dc591deb30bea3`.
It records four completed, zero failed, `RUNNING`, cumulative synchronized
call wall `29.783272966742516 s`, and last ledger-row SHA-256
`6d54f1ce9508b5f89329525a4339d2ae69fb5d2385f686917e040614636be904`.

| Root | Actual NFE | Synchronized wall (s) | WAV SHA-256 | Commit SHA-256 |
| --- | ---: | ---: | --- | --- |
| 0 | 50 | 18.60281352326274 | `7ebab84222e3498d18e194fed6422ac990550a7b05b691c0921b3c38d3617e88` | `49e5f679e057663e648c62388ed78ef33f7effafbe39b78fd46f5f81091da69e` |
| 1 | 50 | 3.7345843501389027 | `d250377495c13ad9bc1b5fdb4399d4cb84b740df9fca93559fbe5f9d7d4ac46e` | `9633fb305e246c67c68198abe709aea3c48222d84be13139f13a48d0226c05d2` |
| 2 | 50 | 3.7451464980840683 | `a9d6a65e96e48416c721b3dce0684e4518e5299f062bd87658f46593d0d8d3a7` | `f3876ec1899ad4729203bd6737dce805cab014f164a9f3e159663fda9febcd4e` |
| 3 | 50 | 3.7007285952568054 | `4334ed0f55a9b78cc87e613206a56cc95a6715991445ec8db91e1127e86fea43` | `9df2d90646f4e2dc96c42f806c19f528ee92c81ff04148eb5f1304fb44d678b3` |

All four are retained 30-second, 44.1-kHz stereo WAVs with adjacent
provenance, sanity, and commit records. They are the first four BASE roots for
`voice-frame-01-vocal`. No automatic instrument has scored them and no human
has heard or labeled them through this workflow.

## Execution-cost appendix

### Frozen launch accounting

| Item | Status | Value and use |
| --- | --- | --- |
| SA3 foundation calibration | `MEASURED_SINGLETON` | `c_m = 116.34399104863405 s`; `u_m = 25.023961771279573 s` |
| SA3 ordinary-core cap | frozen formula output | `76,939.90662887692 GPU-s = 21.372196285799145 GPU-h` for 1,536 calls; this is a conservative cap, not an observed final cost |
| ACE-Step v1 B2 failed row | `MEASURED_FAILURE_ROW_NOT_QUEUE_ELIGIBLE` | load `182.45191994681954 s`; call `27.25068249553442 s`; NFE 45; no core queue |
| Stable Audio Open 1.0 | `NOT_MEASURED_BLOCKED_ON_LICENSE` | no cost imputation and no core queue |

### Obtained launch measurements at first-batch boundary

| Measurement | Obtained value |
| --- | ---: |
| Model-load wall | `72.65626287087798 s` |
| Four synchronized call walls | `29.783272966742516 s` |
| Total NFE | `200` |
| Peak allocated VRAM | `5,437,102,080 B` |
| Peak reserved VRAM | `9,839,837,184 B` |
| Completed / failed at immutable boundary | `4 / 0` |
| GPUs / TP / replicas | `1 / 1 / 1` |

These are measured launch facts through the first completed shard only. They
do not replace the frozen full-run cap and do not support p95 claims.

### PI-minute accounting

The frozen solo-PI target remains at most three hours total. The preregistered
packet design allocates at most 178 minutes including the pilot and hidden
repeat blocks. At this report boundary, obtained PI review time is zero
because no timing-pilot response has been ingested. The offered pilot targets
about 15 minutes; packet assembly remains gated on its strict ingestion
receipt.

## Deliverables and licensing state

The frozen plan remains: instruments and harness under MIT; project-authored
prompt/instrument tables and atlas metadata under the declared project terms;
de-identified gold-label tables under CC BY 4.0 after blinding is safely
released; upstream model/audio terms remain separate. The repository `LICENSE`
is MIT. No gold-label or atlas result is claimed at launch because human
auditing and endpoint scoring have not begun.

## Verification

Before the recovery launch commit:

```text
/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m pytest -q
242 passed, 111 subtests passed

/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m ruff check .
All checks passed
```

The focused relaunch gate additionally verifies every frozen runtime identity
in D-0024 and exercises public metadata drift, imported module-build drift,
and the flash-attention special-case boundary. A final full-suite receipt is
recorded after this report and its append-only governance entries are added.

## Remaining gates

- The ordinary SA3 worker is active and should be monitored through its
  mutable heartbeat; it must not be preempted merely to close this report.
- Stable Audio Open 1.0 remains `BLOCKED_ON_LICENSE`.
- ACE-Step v1 remains `BLOCKED_ON_ENGINEERING_FAILURE`.
- Both state-capture queues remain unauthorized.
- Timing-pilot ingestion is required before human-audit packet assembly.
- Automatic evaluators, human labels, fixed-intervention comparisons,
  best-of-N baselines, and the eligibility gate remain unrun; this report
  makes no benchmark-performance claim.
