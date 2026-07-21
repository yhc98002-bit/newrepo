# Benchmark v2 freeze, build, and launch report

- Report date: 2026-07-21 (Asia/Shanghai)
- Scope: preregistration freeze, terminal Phase-B build receipts, and the
  first ledgered ordinary-core batch for each launched backbone
- Benchmark result status: **no endpoint has been scored**
- Human-audit packet: **not assembled**; timing-pilot ingestion is still
  required

## Executive status

| Phase | Terminal status | Evidence |
| --- | --- | --- |
| A — preregistration v2 | `FROZEN_PROSPECTIVE_DESIGN` | D-0021; `BENCHMARK_PREREG_v2.md` SHA-256 `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| B1 — instruments | `PASS` | `provenance/b1/B1_VALIDATION_REPORT.json` SHA-256 `656c8f960538ac0e35ea85786d1025d2350b581a0adb510a9879b2917506d448` |
| B2 — adapters | `TERMINAL` | amended receipt `provenance/b2/build_status_terminal_v2_ace_amendment.json` SHA-256 `619eb06b21012624b446dfa0d41dc6602c060889406ec431ff52d5a9cb879a34` |
| B3 — prompts and raters | `PASS; TIMING_PILOT_OFFERED_AWAITING_PI_RESPONSE` | prompt manifest SHA-256 `171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089`; offer record SHA-256 `645cca46a001b42aace2f20a95d35921c6e26d7c56665cb7c457b30cf57227cb` |
| C — ordinary core | `ACE_INCREMENTAL_LAUNCHED_FIRST_LEDGERED_BATCH` | SA3 run complete; active ACE run `benchmark-core-v2-ace-20260721t091500z`; immutable ACE shard-0 heartbeat SHA-256 `b76fb604e0151bb88ccda1bc7badfc566db71bd21638143c5606fda8efc93a6f` |

The completed SA3 worker is bound by a 1,536-call completion receipt. The
active ACE worker continues after its milestone, as required by
`BENCHMARK_CORE_PROTOCOL_v2.md`. Stable Audio Open 1.0 remains
`BLOCKED_ON_LICENSE`. The initial and supplemental state queues are
materialized but closed. No evaluator, best-of-N selector, or human-audit
packet builder is running.

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

All three rows in the additive amended receipt
`provenance/b2/build_status_terminal_v2_ace_amendment.json` are terminal:

| Backbone | Build / queue status | Measured or blocking evidence |
| --- | --- | --- |
| Stable Audio 3 Medium Base | `MEASURED_READY` / `READY` | D-0020 measured `c_m = 116.34399104863405 s`, `u_m = 25.023961771279573 s`, state capability `PASS` |
| Stable Audio Open 1.0 | `BLOCKED_ON_LICENSE` / `BLOCKED_ON_LICENSE` | No credential, access acceptance, download, or generation was attempted; cost is not measured and is not treated as zero |
| ACE-Step v1 | `MEASURED_READY` / `READY` | D-0026 re-adjudicates S-0008 under the 0.25-second rule; the sole S-0009 confirmation independently passed at the same native `29.9073125 s` decoder duration |

The user ceiling was ten B2 calls. D-0021 and D-0026 jointly consumed exactly
two ACE engineering calls and two outputs, with zero retries. Both requested
30 seconds and decoded to 1,435,551 stereo frames at 48 kHz, exactly
`29.9073125 s`, an exact `0.0926875 s` error within the amended inclusive
`0.25 s` rule. S-0009 passed every other frozen sanity check. Its retained
WAV/provenance SHA-256s are
`5070dc1b8916cc0cdc7d8fdf533968e72b5fe4198829546bd01fed4525b3a052` /
`b1c141a59d3eebded4f7cf587d9325c46328bf4fc9d4d459af10321cec08fe67`;
the terminal result SHA-256 is
`213ab5fa2937ae263a1c2fbee1276774755a69d60a0e0032f388ed7677720f75`.

S-0009 measured actual NFE 45, synchronized wall
`30.9385858848691 s`, load wall `241.99800701066852 s`, one-GPU residency
`281.0608921535313 s`, and peak allocated/reserved VRAM
`8,371,731,968 / 10,085,203,968 B`. Conservatively combining it with S-0008
freezes `u_m = 30.9385858848691 s`, `c_m = 272.93659289553762 s`, and a
1,536-call cap of `95,254.39525944367462 GPU-s`
(`26.459554238734354 GPU-h`). These are engineering-cost observations, not
benchmark scores.

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

The recovery SA3 run subsequently completed all 1,536 rows with zero failures.
`provenance/core/sa3_core_completion_v2.json`, SHA-256
`4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6`,
binds its terminal heartbeat, ledger, generation queue, and retained counts.
D-0027 therefore excludes SA3 from regeneration and authorizes exactly the
ACE-only incremental run described below.

### SA3 immutable launch bundle (complete)

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

### SA3 first ledgered batch

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

### ACE-Step v1 incremental launch

- Run: `benchmark-core-v2-ace-20260721t091500z`
- Launch Git: `79d9193b7e67944242395600576d0a3762503ea6`, clean and
  equal to `origin/main` at launch
- Incremental config SHA-256:
  `6e4886b235474ea08083b9a01d24d6cddaad8443ce3e0ab3fef49dedfe5ef23f`
- Launch claim / run manifest SHA-256s:
  `9ae7640d42198cd0a985f092d40a06afb63affbdb9963a7ead6c70249ce8a990` /
  `776cf4ed9bd14a6bc1712d3edc85cf21c27694861810fd8353d3895882aab64d`
- Generation queue: 1,536 rows, all and only
  `ACE-Step/ACE-Step-v1-3.5B`, SHA-256
  `db4ce65dabee9219e30a5c22c0eb56ed7b0a6f9e3ebaf98302f725cb8e8fd37f`
- Initial state queue: 432 prior-SA3 rows, SHA-256
  `bc03a333e9cb096747ca7d9392a1a33a1c781315b1c1c698b20c888f74ca00c8`,
  closed
- Supplemental state queue: 432 prior-SA3 rows, SHA-256
  `e7eb055e53183f2f6f85bd6ede586e9ed22a390a07cc149bdb121261961da8c1`,
  locked
- Placement: `an12`, physical GPU 4 exposed as logical GPU 0, TP1, one
  replica; worker PID at launch `3426125`
- Placement rationale: ACE-Step v1 fits one A800. Immediately before launch,
  GPU 4 had 81,226 MiB free, no compute PID, and 0% utilization; TP1/R1 leaves
  ample headroom and does not alter neighboring processes

Preparation made zero model calls and created no claims or WAVs. The detached
worker then loaded once in `123.0669956356287 s` and continued beyond the
first shard under the no-retry and `95,254.39525944367462 GPU-s` cap.

The immutable first-shard heartbeat
`workers/ace-step-v1/heartbeat-snapshots/
shard-000000-b76fb604e0151bb88ccda1bc7badfc566db71bd21638143c5606fda8efc93a6f.json`
has SHA-256
`b76fb604e0151bb88ccda1bc7badfc566db71bd21638143c5606fda8efc93a6f`.
Its immutable shard record has SHA-256
`1466cec9a528e157a7ead46fcfde879eba357ef10f3149c2af4858e1d41d5ac2`.
The boundary records four completed, zero failed, `RUNNING`, cumulative
synchronized call wall `11.75711365789175 s`, peak allocated/reserved VRAM
`8,544,569,856 / 10,085,203,968 B`, and ledger tail SHA-256
`4d0a91627c3b4175ee5891ded72ea52f30f4447f5fbb23a9a3d77acb60631fab`.

| Root | Actual NFE | Synchronized wall (s) | WAV SHA-256 | Commit SHA-256 |
| --- | ---: | ---: | --- | --- |
| 0 | 45 | 3.715504363179207 | `563473b06c7d84a9e550e8ff6ba761d7aa3e82a9945cef12caf33cfd9bd0a5ec` | `c67d9932ecae50834b1c1d41f47afa0c41bc07ab96a1470b701eb12082a8be3f` |
| 1 | 45 | 2.7087645642459393 | `f2cf0ef8142404b83e3f74d3411a44fbbff4987718d3b4cc63b817fa33ac1f9b` | `180b424c34d2a7db55a0d06e4009ee390a8542def5a5f4138bfba43d4730affc` |
| 2 | 45 | 2.6346603482961655 | `080659bc3e5ae984604132f0227dd1d475e6b2c47d1ef6cfdce8f3386df7f7ca` | `cf3015dd64fe2306f38b0aac94176df65dfd7eb0ec4505b197edebad95123f3f` |
| 3 | 45 | 2.6981843821704388 | `746610fd7d90029ca45954cbd8378e6db17503bac3a1faa95ba9a04936d32831` | `c10404c0e9a7d6ba085fab97c170112e7a8e0a86b2301363c80a43e105088a1c` |

All four are retained 48-kHz stereo WAVs at the native
`29.9073125 s` decoder duration. Each passes the frozen inclusive
`0.25 s` duration rule and has adjacent hash-bound provenance, sanity, and
commit records. They are BASE roots 0–3 for `voice-frame-01-vocal`.
No automatic instrument has scored them and no human label has been obtained.

## Execution-cost appendix

### Frozen launch accounting

| Item | Status | Value and use |
| --- | --- | --- |
| SA3 foundation calibration | `MEASURED_SINGLETON` | `c_m = 116.34399104863405 s`; `u_m = 25.023961771279573 s` |
| SA3 ordinary-core cap | frozen formula output | `76,939.90662887692 GPU-s = 21.372196285799145 GPU-h` for 1,536 calls; this is a conservative cap, not an observed final cost |
| ACE-Step v1 calibration | `MEASURED_TWO_OBSERVATIONS_READY` | conservative `c_m = 272.93659289553762 s`; `u_m = 30.9385858848691 s` |
| ACE-Step v1 ordinary-core cap | frozen formula output | `95,254.39525944367462 GPU-s = 26.459554238734354 GPU-h` for 1,536 calls; conservative cap, not observed final cost |
| Stable Audio Open 1.0 | `NOT_MEASURED_BLOCKED_ON_LICENSE` | no cost imputation and no core queue |

### SA3 obtained launch measurements at first-batch boundary

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

### ACE-Step v1 obtained launch measurements at first-batch boundary

| Measurement | Obtained value |
| --- | ---: |
| Model-load wall | `123.0669956356287 s` |
| Four synchronized call walls | `11.75711365789175 s` |
| Total NFE | `180` |
| Peak allocated VRAM | `8,544,569,856 B` |
| Peak reserved VRAM | `10,085,203,968 B` |
| Completed / failed at immutable boundary | `4 / 0` |
| GPUs / TP / replicas | `1 / 1 / 1` |

These are measured launch facts through ACE shard 0 only. The resident run
continues under the frozen cap; this boundary does not support a final-cost or
p95 claim.

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

Before the D-0027 ACE launch commit:

```text
/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m pytest -q
278 passed, 111 subtests passed

/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m ruff check .
All checks passed
```

The incremental launch gate additionally verifies the ACE-only allowlist,
the SA3 completion receipt and prior queue, both explicit 0.25-second
tolerances, exact measured budget arithmetic, closed state queues, and
fail-closed drift behavior. The same full suite is run again after this
report and its append-only governance entries are added.

## Remaining gates

- The ordinary SA3 run is complete and must not be regenerated.
- The ACE-Step v1 worker is active and should be monitored through its
  mutable heartbeat; it must not be preempted merely to close this report.
- Stable Audio Open 1.0 remains `BLOCKED_ON_LICENSE`.
- Both state-capture queues remain unauthorized.
- Timing-pilot ingestion is required before human-audit packet assembly.
- Automatic evaluators, human labels, fixed-intervention comparisons,
  best-of-N baselines, and the eligibility gate remain unrun; this report
  makes no benchmark-performance claim.
