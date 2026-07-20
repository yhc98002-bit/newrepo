# Decisions (append-only)

This file is append-only. Existing decision text, identifiers, and timestamps
must never be edited or deleted. A later decision may supersede an earlier one
only by naming its identifier; the earlier entry remains authoritative history.

## D-0001 — Governance invariants

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

Before any smoke result, acceptance rules and seeds are committed. Existing
artifacts are immutable; corrections create new artifacts and point back to
what they supersede. Every acquired, generated, transformed, or checkpointed
data artifact has a machine-readable provenance record.

## D-0002 — Foundation scope

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

This project is engineering-only. It may validate installation, official
generation/editing APIs, determinism, execution cost, checkpoint/resume, and
audio-file integrity. It must not add detectors, constraint experiments,
policy work, or facts/results copied from another repository.

## D-0003 — Frozen smoke protocol

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

`SMOKE_PROTOCOL.md` version 1 and `SEED_REGISTRY.md` version 1 are frozen before
results. Any future rule change must be a new, explicitly superseding protocol;
version 1 is never rewritten.

## D-0004 — Network and license boundary

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

ModelScope is checked first and Hugging Face is the fallback. GitHub and Hugging
Face traffic on the login node uses the declared proxy explicitly. If any file
needed from the exact requested base snapshot requires interactive terms
acceptance or an access token, no credential or alternate copy is used. The run
terminates as `BLOCKED_ON_LICENSE` after recording exact human remediation
steps. A similarly named gated post-trained repository is not a substitute for
the requested base snapshot.

## D-0005 — ModelScope mirror and offline path resolution

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

The pinned ModelScope `stable-audio-3-medium-base` snapshot is an explicitly
labelled mirror, not the upstream publisher. It may be used only after its file
sizes and SHA-256s are verified against the public official Hugging Face base
snapshot. The exact base snapshot includes its T5Gemma conditioner and license
files without a technical gate. Loading those already-acquired public files by
an explicit local path is permitted for offline ModelScope-first operation: the
upstream config remains immutable, the local resolved copy and diff are
retained, and the deviation is reported. The gated, differently named
`stable-audio-3-medium` repository must not be accessed or substituted.

## D-0006 — Benchmark design drafting scope

- Date: 2026-07-19
- Status: accepted
- Supersedes: D-0002 only for non-generative benchmark design work

The user authorizes drafting and reviewing `BENCHMARK_PREREG_v1.md`, including
fixed evaluator specifications, prompt/seed plans, state-information screening,
statistics, human-label budgeting, licensing, and cost-accounting design. This
does not authorize model execution, audio generation, labeling, detector runs,
or a claimed benchmark result. D-0002 remains in force for executed work until
a later decision explicitly opens a bounded run.

## D-0007 — Benchmark preregistration and execution gates

- Date: 2026-07-19
- Status: accepted; both gates closed
- Supersedes: none

`BENCHMARK_PREREG_v1.md` is a co-PI review draft, not a frozen protocol. Current
states are `BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO`. No audio generation is authorized. A
future append-only design-freeze entry must name the exact preregistration and
companion hashes; because cost measurement itself requires generation, that
entry may authorize only explicitly bounded entry, cost, true-state, and
conditional Gate-0 smokes. Full benchmark generation requires a later
append-only execution decision naming immutable successful smoke rows, a
measured-cost amendment and caps, capability evidence, and any approved model
amendment. Neither a draft edit nor a smoke PASS opens either gate implicitly.

## D-0006 — Frozen CUDA environment

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

Use CPython 3.10.12, PyTorch and torchaudio 2.7.1+cu126, and Flash Attention
2.6.3 from the recorded wheel digest. These match both pinned upstream package
requirements and the Stable Audio 3 cu126 default. Compatibility with A800
driver 535.104.12 is established by an actual CUDA allocation and Flash
Attention kernel on `an12`, not assumed from a version table.

## D-0007 — Recoverable storage relocation

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

The new `/XYFS02` directory inherited Lustre project ID 2228473301 and rejected
all new data blocks with `EDQUOT` while only 528 KiB was present. Preserve that
checkout under the timestamped sibling backup, place the live clone and runtime
in the declared `/HOME` allocation, and keep the requested repository path as a
symlink to the live clone. This is a storage-only deviation; Git history,
logical paths, remote `main`, and artifact immutability remain unchanged.

## D-0008 — Frozen execution configuration

- Date: 2026-07-19
- Status: accepted
- Supersedes: none

`configs/foundation_v1.json` fixes the prompt strings, negative prompt, sampler,
steps, CFG, durations, masks, checkpoint steps, batch measurement, model
revisions, runtime placement, and seeds before the first model output. Its
SHA-256 is recorded in every run manifest. The file is immutable after the
first result; later changes require a new version and superseding decision.

## D-0009 — Decision-identifier collision resolution and benchmark gate

- Date: 2026-07-19
- Status: accepted; benchmark gates remain closed
- Supersedes: duplicate identifiers D-0006 and D-0007 for naming purposes only

Concurrent append-only work assigned D-0006 and D-0007 twice. No prior text is
rewritten. Future references must use both identifier and title: D-0006
“Benchmark design drafting scope”, D-0006 “Frozen CUDA environment”, D-0007
“Benchmark preregistration and execution gates”, or D-0007 “Recoverable
storage relocation”. Their substantive nonconflicting decisions remain in
force.

For avoidance of doubt, the benchmark state is
`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO`. D-0008 freezes configuration fields but
does not authorize model execution or audio generation. No smoke or benchmark
audio may be generated until a later uniquely identified append-only decision
satisfies the two-stage gate in `BENCHMARK_PREREG_v1.md`.

## D-0010 — SA3 foundation smoke execution authorization

- Date: 2026-07-19
- Status: accepted; SA3 foundation smokes A–E authorized
- Supersedes: D-0009 only for the five SA3 foundation smokes

The user's current instruction explicitly authorizes execution of only the five
engineering smokes A–E in frozen `SMOKE_PROTOCOL.md` version 1 with frozen
`configs/foundation_v1.json` and `SEED_REGISTRY.md` version 1. This bounded
authorization satisfies the later-execution requirement introduced by D-0009
for those foundation smokes only. It does not freeze, execute, amend, or open
any benchmark, detector, constraint, evaluator, labeling, or policy gate.

`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged. Foundation smoke
artifacts and results cannot be claimed as benchmark artifacts or results.

## D-0011 — Revoke foundation-smoke execution under no-generation goal

- Date: 2026-07-19
- Status: accepted; all model execution and audio generation closed
- Supersedes: D-0010 in full

D-0010 incorrectly treated a concurrent foundation workflow as authorization
under the user's active benchmark-preregistration goal. That goal explicitly
requires design work only and no generated audio. At this correction cutoff,
the foundation run directory is empty, no smoke process is active, and the
repository contains no audio file, so the revocation precedes execution.

Current states are `SA3_FOUNDATION_SMOKE_AUTHORIZED = NO`,
`BENCHMARK_PREREG_V1_FROZEN = NO`, and
`BENCHMARK_EXECUTION_AUTHORIZED = NO`. Model loading, forward execution,
decoding, and all audio-generating smokes remain prohibited until a later
user-authorized, uniquely identified decision satisfies the applicable gate.

## D-0012 — Current-prompt SA3 foundation execution authorization

- Date: 2026-07-19
- Status: accepted; frozen foundation smokes A–E authorized
- Supersedes: D-0011 only for the five SA3 foundation smokes

The user's current, explicit SA3 foundation goal requires execution of smokes
A–E and identifies only interactive weight-license acceptance or a required
token as a valid blocking terminal. The exact base snapshot is public and
ungated, all substantive mirror files now match the pinned public upstream
revision, and the rules/config/seeds were frozen before any model output.

`SA3_FOUNDATION_SMOKE_AUTHORIZED = YES` for only the five engineering smokes
in `SMOKE_PROTOCOL.md` version 1 using
`configs/foundation_v1.json`. Execution must use the committed clean
`origin/main` revision, the declared one-A800 TP1 placement, offline local
model paths, and immutable run directories.

D-0011 correctly governed the separate no-generation benchmark drafting goal
at its cutoff; this later decision records the current user's distinct
foundation instruction. It does not authorize benchmark audio, detectors,
constraints, evaluators, labels, policy work, or scientific claims.

`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0013 — PI constraint amendment for bounded foundation cost smokes

- Date: 2026-07-19
- Status: accepted; bounded foundation cost smokes permitted and required
- Authority: Chief Scientist / PI, current prompt
- Supersedes: D-0012 for execution scope and caps; D-0011 only within this exception

The no-generation constraint is amended for one bounded foundation-cost run
against exact `stabilityai/stable-audio-3-medium-base`, using the already-frozen
`SMOKE_PROTOCOL.md`, `configs/foundation_v1.json`, and `SEED_REGISTRY.md`.
`FOUNDATION_COST_SMOKE_AUTHORIZED = YES` only for:

1. two fixed-seed, 30-second text-to-audio outputs with decoded-waveform hash
   comparison;
2. one continuation from a retained 10-second source clip;
3. single- and multi-segment inpainting on one retained generated clip;
4. latent exports after 30%, 60%, and 80% of transitions, each reloaded and
   continued in a separate process under the frozen equivalence tolerance; and
5. one batch-of-four throughput measurement.

Hard guards are `MAX_GENERATIONS = 20`, `MAX_CLIP_SECONDS = 30`,
`MAX_GPUS = 1`, and `MAX_GPU_SECONDS = 1800`. A batch of four counts as four
generations. The runner must fail closed before a call that would exceed a
guard, and must stop after the current atomic write if the measured time cap is
reached. Every output receives the frozen audio sanity checks, is retained in
an immutable run directory, and has adjacent provenance plus a per-generation
ledger row using only registered seeds. No output may be overwritten.

The terminal record is `SA3_FOUNDATION_REPORT.md`, with per-smoke PASS/FAIL,
actual NFE, synchronized wall time, peak VRAM, hashes, placement, commands,
provenance, deviations, and the exact generation/time counters. Its measured
costs must replace estimate/pending/unmeasured rows in the preregistration cost
appendix before the original benchmark goal can complete.

All other model execution and generation remain closed until a later
append-only decision freezes `BENCHMARK_PREREG_v1.md` by exact hash.
`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0014 — Correct bounded foundation call enumeration before execution

- Date: 2026-07-19
- Status: accepted; clarification recorded before any foundation generation
- Authority: Chief Scientist / PI, current foundation prompt
- Supersedes: D-0013 only where its enumerated list omitted the separately
  required batch-one cost call; all D-0013 hard guards remain binding

D-0013 correctly added fail-closed cost caps, but its five-item enumeration
named only the batch-of-four part of smoke D. The current foundation prompt also
explicitly requires the base 50-step batch-one path for measured DiT forward
calls, synchronized wall time, and peak VRAM. That batch-one call is therefore
inside the same bounded foundation authorization; it is not benchmark
execution and does not authorize any additional experiment.

The exact authorized plan is 11 official generation calls producing 14 model
outputs: A has two batch-one outputs; B has one; C has two; D has one 30-second
batch-one cost output and one 10-second batch-of-four call producing four
outputs; E has one uninterrupted reference and three separate-process resumed
outputs. The derived 10-second continuation source is retained and labeled but
is not a model generation. Only registered seeds S-0001 through S-0007 may be
used.

`FOUNDATION_COST_SMOKE_AUTHORIZED = YES` for that exact plan. The unchanged
guards are `MAX_GENERATIONS = 20`, `MAX_CLIP_SECONDS = 30`, `MAX_GPUS = 1`, and
`MAX_GPU_SECONDS = 1800`, with the D-0013 pre-call, post-atomic-write stop,
per-generation ledger, immutable-artifact, sanity, and provenance requirements.

No foundation model call has occurred as of this correction. All benchmark,
detector, constraint, policy, evaluator, and scientific-result work remains
unauthorized. `BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0015 — Placement-only supersession to idle physical GPU 4

- Date: 2026-07-19
- Status: accepted operational supersession before model execution
- Authority: Chief Scientist / PI, current foundation prompt and node-placement rules
- Supersedes: `configs/foundation_v1.json` only for physical GPU ID,
  placement justification, and config version; no sampling or acceptance rule

Immediately before execution, physical GPUs 0-3 on `an12` were occupied by the
researcher's normal neighboring four-GPU RL job. Physical GPU 4 was an idle
A800 with 81,223 MiB free and passed the pinned Torch/Flash Attention kernel
probe. Colocation on a disjoint idle GPU is the declared normal operating mode;
launching into occupied GPU 0 would not be.

`configs/foundation_v2.json` SHA-256
`d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`
supersedes v1 SHA-256
`42e99699e7c3f8fb56d615086684b10afd4fdc1a8b3f162e37818ec462814a14`
only by selecting physical GPU 4, updating its justification, recording the
supersession, and incrementing the config version. The model, snapshot,
protocol hash, audio rules, prompts, sampler, steps, CFG, masks, tolerances,
seeds, run root, one-node TP1 width, and replica count are byte-for-byte
unchanged.

The placement evidence is `environment/gpu-placement-v2.json` SHA-256
`a76eb1fc11eac87238ecd9fcc11e1070968b6a423e9c650698445d45a631229a`.
Execution must set `CUDA_VISIBLE_DEVICES=4`; the single visible device is then
addressed as `cuda:0` inside the process. D-0013/D-0014's exact 11-call,
14-output plan, one-shot claim, registered seeds, and all hard caps remain
binding. `FOUNDATION_COST_SMOKE_AUTHORIZED = YES` only for that plan on this
superseded placement.

No foundation model call had occurred and no one-shot execution claim existed
at this placement cutoff. Benchmark, detector, constraint, policy, evaluator,
and scientific-result execution remains unauthorized.
`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0016 — Compare model snapshot aliases by filesystem identity

- Date: 2026-07-19
- Status: accepted operational correction before model execution
- Authority: Chief Scientist / PI, current foundation prompt and provenance invariant
- Supersedes: the preflight implementation's string-path equality check only

The read-only production preflight at Git commit `8476841` stopped before the
one-shot claim because the frozen config names the snapshot through `/HOME`
while the immutable weights manifest names the same directory through
`/XYFS01/HOME`. On `an12`, those two absolute names have the same device
`3356821666` and inode `162130936496981305`; Python `Path.samefile` returns
true, while lexical resolved-path equality returns false. The failed preflight
log is
`/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/logs/foundation-8476841-production-preflight-20260719T135000Z.log`,
SHA-256 `f1701f460ea93074da77275d42ad960a01d82c7681b35f0c97fc7001148610aa`.

Preflight must therefore bind the configured snapshot and manifest
`artifact_root` by filesystem identity (`samefile`, hence device and inode)
after requiring both paths to exist. Exact manifest file sets, byte sizes, and
SHA-256 verification remain mandatory, so this accepts only two names for the
same stored object and does not relax content provenance.

No model was loaded, no foundation generation occurred, and the one-shot
execution claim remained absent at this correction cutoff. Config v2, the
exact D-0013/D-0014 11-call/14-output plan, registered seeds, and all hard caps
remain unchanged. `FOUNDATION_COST_SMOKE_AUTHORIZED = YES` only for that plan.
Benchmark, detector, constraint, policy, evaluator, and scientific-result
execution remains unauthorized. `BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0017 — Terminal foundation-smoke result and retry gate

- Date: 2026-07-19
- Status: accepted terminal engineering record; one-shot authorization consumed
- Authority: D-0013/D-0014 terminal-report requirement; immutable run evidence
- Supersedes: the prior open foundation execution state only

The one authorized foundation run is terminal
`FOUNDATION_COST_SMOKE_STATUS = FAIL_ESCALATED`. Its immutable run ID is
`sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`, executed from Git commit
`ae251c62e2ba2bae025ec4413aae875df967b021` with config SHA-256
`d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`.
The result SHA-256 is
`65adbde1e8abe9e744749a52745243d7c4bb572e778284d76827f98a05b6d912`,
the one-shot claim SHA-256 is
`ad71f0300d27ca84b2092981ac3283faaef9f24490097c1b7ad23394da09a6ac`,
and the generation-ledger SHA-256 is
`7caafac155c3e04519633749bb89a31d4a86f8d118926aabd0bcdd0130626a2c`.

Smokes A, B, C, and D passed. Smoke E's uninterrupted reference and its
15/30/40-step checkpoints were retained and validated, but all three fresh
separate-process resume calls failed before a resumed DiT transition. The
exported checkpoint latent was `torch.float32`; the official child allocated a
fresh disposable initial latent as `torch.float16`; the resume adapter's
strict pre-transition dtype-equality check rejected that expected boundary.
This was not an OOM and did not corrupt or overwrite an artifact.

The run reserved exactly 11 official calls and 14 generation slots. Eight
calls succeeded, three resume calls failed, 11 model WAVs were retained, and
the 14-row hash-chained ledger contains 11 PASS rows plus three
`MODEL_CALL_FAILED` rows. Actual DiT NFE was 400, synchronized official-call
wall time was 46.013083518 seconds, and the conservative one-GPU residency
upper bound was 244.181992349 seconds. The 20-generation, 30-second, one-GPU,
and 1800-GPU-second caps were all respected.

`FOUNDATION_COST_SMOKE_AUTHORIZATION_STATUS = CONSUMED`,
`FOUNDATION_COST_SMOKE_AUTHORIZED = NO`, and
`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO`. No claim may be removed and no
model call may be retried unless a later explicit PI decision names this
failure, the reviewed fix, a new immutable claim/config, and fresh repair caps.
`BENCHMARK_PREREG_V1_FROZEN = NO` and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0018 — Safe flexible GPU placement pool; no execution expansion

- Date: 2026-07-19
- Status: accepted placement-only authority
- Authority: Chief Scientist / PI, current prompt
- Supersedes: D-0015 only for future node and physical-GPU selection

For a future separately authorized job, physical GPUs on `an12` or `an29` may
be selected operationally. The selected device must be disjoint from existing
GPU processes, rechecked immediately before model load for occupancy and free
memory, and protected by a device-specific lock. Existing jobs are normal
neighbors: they must not be terminated, evicted, migrated, reconfigured, or
placed at OOM risk. If an idle device with adequate safety headroom cannot be
established, execution stops before model load.

For this foundation scope, `MAX_GPUS = 1` remains binding: one node, one visible
GPU, TP1, and one replica. This placement authority does not create a new
claim, authorize a retry, permit another model call, or alter the terminal
D-0017 result. `FOUNDATION_COST_SMOKE_AUTHORIZED = NO`,
`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO`,
`BENCHMARK_PREREG_V1_FROZEN = NO`, and
`BENCHMARK_EXECUTION_AUTHORIZED = NO` remain unchanged.

## D-0019 — One-shot Smoke E dtype-boundary retry

- Date: 2026-07-20
- Status: accepted prospectively; one exact claim open, no result yet
- Authority: PI, current bounded-retry prompt
- Supersedes: D-0017 only for one Smoke E repair attempt and D-0013 only for
  strict active-process termination at this retry's outer deadline

The immutable D-0017 failure remains historical. Its run is
`sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`; result SHA-256 is
`65adbde1e8abe9e744749a52745243d7c4bb572e778284d76827f98a05b6d912`,
Smoke E manifest SHA-256 is
`7d5a25e083e5cdf2385c3505b1896e8e512efc1f78a3082bc76d347a85103495`,
and L-0009 records the failure. The three valid old checkpoint SHA-256s are
`52acec3c52d4f580978222a6f392fe9577cb6e1094719a1505cfd6a62671eee1`,
`95b31c86f4ae909f7009739fe20705cf0cd6c957c857c2cb303583b38b77033d`,
and `acadb11a0d17204370c41d120b09af322bc10388ba7a20600481191a1dc589f5`.

The reviewed mechanism commit is
`59b24ff9597094b1a74b00b4c9447fd23facf7be`. The repair exports the evolved
latent in its actual runtime dtype and resumes from that saved dtype without a
cast. This is selected over a resume-time FP16 cast because the latter would
discard state precision and change the trajectory. Source SHA-256s are:
`src/sa3_smoke/latent.py` =
`9aeb23557be929907548655a9a8deccaec027b6d789132d64f9d729eaa6c43f2`,
`src/sa3_smoke/resume_child.py` =
`5fd11c39aed4e753662a7a7388107a054ed55ec0737b93f0fae58a38f3209a13`,
`src/sa3_smoke/smoke_e.py` =
`1c3f50c7af3534e036794844e190cce7f193515a81d525161b0e996cf9b62fbd`,
and the E-only runner =
`ad9d1b00289386feb83e1cdac4ecc1c06abdafb5ab6d13e75fc749524d8cbda0`.

Rules are frozen before results by
`SMOKE_E_RETRY_PROTOCOL_v1.md` SHA-256
`1a2892b70029bea1e36722145dceea32a814e5a00d917a98c0cb17d4582cd0a0`
and the no-clobber control file below. The original foundation v2 config SHA-256
`d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`
continues to identify the model call and checkpoint state contract.

`RETRY_CONFIG_SHA256 = 39553c595659e29e3c0fa691c0d47f344421548ca3ac12157c01fac32a716c84`

The exact plan is one new uninterrupted official call exporting at 15/30/40
completed steps (30/60/80%), followed by three sequential official resume
calls in distinct processes: four calls and four WAVs total, all Smoke E and
S-0007 = `73193007`. Expected resumed NFE is 35/20/10. The frozen numerical
gate remains maximum absolute decoded-waveform error `<= 1e-5` and SNR
`>= 80 dB`, with full duration/sample-rate/stereo/non-silence/finite checks and
provenance required for every output. A missing condition is failure.

Hard guards are `MAX_GENERATIONS = 8`, `MAX_CLIP_SECONDS = 30`,
`MAX_GPUS = 1`, and `MAX_GPU_SECONDS = 540`. The 540-second claim-bound
residency cap is stricter than the PI's 600-second limit; children are bounded
to 120 seconds or the smaller remaining allowance. The outer command has a
600-second process deadline and may terminate an active subcase, superseding
D-0013's atomic-finish rule only here. The fixed exclusive claim is
`.sa3-smoke-e-d0019-retry-claim.json`; its creation consumes the sole retry.
No claim may be deleted and there is no second retry.

Placement is `an12`, physical GPU 4, TP1, one replica. A read-only selection
probe found it idle with 81,226 MiB free on 2026-07-20. The runner must hold
`/tmp/pxy1289-sa3-smoke-e-gpu-4.lock` and repeat the no-process, A800,
free-memory, utilization, and one-visible-device checks immediately before
claim creation. The exact executable is
`scripts/run_smoke_e_retry_d0019.sh` SHA-256
`87ef45bdf50fe091cb8f7a6ec509c6cfbb7c6904aff07a1bdf3e9ae3e03edbee`.

If every frozen condition and the exact budget pass, terminal values are
`SA3_SMOKE_E_RETRY_STATUS = PASS`, `SMOKE_E = PASS`, and
`SA3_STATE_CAPABILITY = PASS`. Otherwise, after claim consumption, terminal
values are `SA3_SMOKE_E_RETRY_STATUS = FAIL_ESCALATED`, `SMOKE_E = FAIL`, and
`SA3_STATE_CAPABILITY = NOT_IDENTIFIABLE`; eligibility screens then fall back
to ACE-Step v1 only. Either result closes the retry and preserves the original
five-smoke `FAIL_ESCALATED` classification.

`FOUNDATION_COST_SMOKE_AUTHORIZED = NO`

`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = YES`

`BENCHMARK_PREREG_V1_FROZEN = NO`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZED = YES`

## D-0020 — Terminal Smoke E retry PASS and authority closure

- Date: 2026-07-20
- Status: accepted terminal engineering evidence; D-0019 claim consumed
- Authority: D-0019 terminal rule and immutable run evidence
- Supersedes: D-0017 only for latest Smoke E foundation/preflight capability;
  the original five-smoke run remains `FAIL_ESCALATED`

The single D-0019 execution used clean Git
`dd65740782f268e0df21a2a22efe9faa3ab12962`, exact retry config SHA-256
`39553c595659e29e3c0fa691c0d47f344421548ca3ac12157c01fac32a716c84`,
protocol SHA-256
`1a2892b70029bea1e36722145dceea32a814e5a00d917a98c0cb17d4582cd0a0`,
and foundation-call config SHA-256
`d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`.
The immutable run is
`sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24` on `an12`, physical
GPU 4, TP1, one replica. The device lock was held; the immediate pre-claim
probe found one visible A800, no compute process, 81,223 MiB free, and 0%
utilization. No neighboring process was changed.

Claim SHA-256 is
`32bd53e6e6421acede70f2f01e07e50c55abb4a918ee5ef6c2b50b6c3a6fc092`.
Result, Smoke E manifest, generation-ledger, budget-state, and live-placement
SHA-256s are, respectively,
`10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117`,
`27978939dbdef2276f5892f222eeaf9263122c4850cfe21a8f72baffc1da070f`,
`b9c70678a6198530d2c913d873b3033ebc5ca88dbcc79f11b4961c28695a3024`,
`3b80d6e27fa6baed9cc6628c2483a0c7f324a9ad5c1c91d315ac624d128960e7`,
and `a72bf9c0e996a2d8b856d0b3ffb315755732e6bbc163a279db2f5969c849a1b0`.

The reference exported FP32 runtime latents at 15/30/40 steps. Checkpoint
SHA-256s are
`066c6a4673fa0a37751c5de115c31fb43149dcfc2c335c65b33da4fcfda78582`,
`25e11b2770b568f5e1d7187667581eaf96989a7cd28245b5d422ddbbe5b4b011`,
and `64564ee934755a131d33ca56e0725b361167f3d3ec4c90d1cc4a853fdb429ffc`.
Three distinct child PIDs preserved FP32 checkpoint state across fresh FP16
official noise and measured exact remaining NFE 35/20/10. All three decoded
resumes exactly equal the reference: maximum/RMS error zero and infinite SNR,
stricter than the frozen `1e-5`/80 dB gate. Reference and resume WAV SHA-256s
are
`6bda5c51ee57c952badce63827c5c11e2be2edded1ce92c984ba240b9aa3dd0f`,
`60680081e5efda91b12e25505e0ed16c81a5234d28982d523c96d20d4dc7e859`,
`1cff775d63c9d69d4f526ae3d208ce7c17b12c878d64fb35b7b7ecd4fff3c663`,
and `725c9881394a602580d8b53b1a83f8fc08377e79d7b9428c3e1dd73b85a31dc5`.
Every output passed finite, non-silent, 30-second, 44.1-kHz, stereo, and
adjacent-provenance checks.

Exactly four calls and four outputs succeeded with zero failure: actual NFE
50/35/20/10 (115 total), synchronized call wall
`33.31213849410415 s`, model-load wall `91.32002927735448 s`, peak allocated /
reserved VRAM `5,438,810,112 / 9,839,837,184 B`, and conservative one-GPU
residency `249.481707109 s`. The 8-generation, 30-second, one-GPU, and
540-GPU-second caps all passed. The run and claim are read-only; no artifact
was overwritten.

After the Python runner wrote PASS and released the GPU, the outer wrapper
returned 1 while attempting an optional operational-log sidecar with a missing
timestamp and unsupported non-data label. The read-only log SHA-256 is
`0054143ae79877097c890c5e3df11bf001c5bc08e614f3a152cef887152b6579`.
This packaging deviation made no model call and is not a frozen Smoke E PASS
condition; it is retained rather than hidden, and no retry occurred.

The terminal report, factual preregistration amendment, and append-only ledger
SHA-256s before this decision append are
`b7e42c07c3a288df49dc63feafe18b05992fbc835a5ddb5b2aa5d0b164bd2c03`,
`02c141f8e62da5fd37df8767b884a833b52d151b0403cfd9fb1bfe13640fbe20`,
and `c5ff486be3016ebe8d0a98e83ce1ecf16475b2889bd190e8de65cab8120303ed`.
The preregistration's formal per-axis 25/50/75 captures, cost calibration, and
benchmark execution remain unexecuted and closed.

`SA3_SMOKE_E_RETRY_STATUS = PASS`

`SMOKE_E = PASS`

`SA3_STATE_CAPABILITY = PASS`

`SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZATION_STATUS = CONSUMED`

`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO`

`FOUNDATION_COST_SMOKE_AUTHORIZED = NO`

`BENCHMARK_PREREG_V1_FROZEN = NO`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZED = NO`
