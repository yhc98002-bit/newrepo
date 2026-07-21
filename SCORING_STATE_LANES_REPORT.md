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

`NOT_EXECUTED_AT_CODE_FREEZE_BOUNDARY`
