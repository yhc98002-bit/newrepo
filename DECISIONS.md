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

## D-0021 — Benchmark preregistration v2 freeze and one-shot ACE-Step v1 B2 engineering authorization

- Date: 2026-07-21
- Status: accepted prospectively; v2 design frozen, one exact non-benchmark
  two-call claim open, benchmark core closed
- Authority: Chief Scientist / PI, consolidated benchmark-v2 task and an12/an29
  placement amendment
- Supersedes: D-0007 “Benchmark preregistration and execution gates” and
  D-0009 “Decision-identifier collision resolution and benchmark gate” only
  for the v2 design freeze and this bounded B2 exception; D-0020 remains
  terminal evidence

`BENCHMARK_PREREG_v2.md`, SHA-256
`77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa`,
is frozen as the prospective v2 design. It supersedes v1 as the active
benchmark design without modifying the historical v1 file.

The freeze adopts the eight adjudicated amendments exactly:

1. The primary instrumental fixed intervention is positive-only — “A purely
   instrumental arrangement led throughout by the named instruments” — while
   negation is an estimate-only diagnostic.
2. The vocal packet is a `TARGETED_HUMAN_STRESS_AUDIT`; model-level voice and
   instrumental results are automatic-instrument outcomes.
3. Tempo uses 5% primary tolerance and a preregistered 10% sensitivity, with
   first- and second-window results and drift reported separately.
4. Integrity human auditing samples only integrity-axis outputs using
   defect-separated clipping, dropout, silence, and crackle strata, clean-side
   rows, and sharp/percussive controls. The synthetic-injection DSP suite
   passed before model generation, and defect-specific rates are mandatory.
5. Exactly three backbones occupy the primary human-audited tier. A fourth
   requires a prospective amendment or a separately reported automatic-only
   tier.
6. The eligibility unit is `(prompt, root, checkpoint)`; state features use
   only that root's preview, folds are prompt-grouped, and restart outcomes
   come from the frozen prompt-level replicated pool rather than a single-draw
   oracle.
7. The gate is verbatim `ELIGIBLE / REPLICATION_ONLY /
   INCONCLUSIVE_UNDERPOWERED / STOP_AXIS`. Only
   `INCONCLUSIVE_UNDERPOWERED` permits one preregistered root doubling followed
   by one re-gate. `ELIGIBLE` requires a positive one-sided 95% lower bound and
   cross-fitted deviation share at least 0.10. The baseline is renamed
   `PROMPT_PLUS_TIME_BUDGET`.
8. ACE-Step v1.5 is deferred for scope and solo-PI budget. Its future path is
   a generation-only amendment and does not require a Gate-0 state-resume
   retry.

Phase B1 is terminal `PASS`. Stable Audio Open 1.0 is terminal
`BLOCKED_ON_LICENSE` with exact human remediation steps. ACE-Step v1 passed
offline identity preflight and only the exact two-call B2 engineering
mini-smoke below is opened. Phase B3 built and offered the single nine-item
blinded timing pilot. Human-audit packet assembly remains closed until its
strict PI receipt is ingested. D-0020 supplies
`SA3_STATE_CAPABILITY = PASS` as technical foundation evidence only.

The complete Section-3 freeze package is bound here:

| Path/artifact | SHA-256 |
| --- | --- |
| `prompts/v2/vocal_instrumental.json` | `602c4e0fb419d7a300116eb5fb76c30a8e19364aaef566aec05425caffed9f90` |
| `prompts/v2/tempo.json` | `16e31c155e1d535f2211fcd85c8d666c9ba7a6636e4487fd43ea2fd5fa0e36ab` |
| `prompts/v2/integrity.json` | `be0e7c65fa8dfad8c7fdbf4456b2c1ad7e6f4fe0bbeb67eba2fcbf96b5f16d03` |
| `prompts/v2/structure_exploratory.json` | `6e9ca89c20ebb43313d9b492140970d876a5cfc657cf123cfe44b7d89e974af8` |
| `prompts/v2/manifest.json` | `171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089` |
| `prompts/v2/seed_registry.json` | `2115d7e70a6c3f4dd19f38503861b8aeb3595a8f64dd1fc839d7a209e80724eb` |
| `SEED_REGISTRY.md` | `d9b175296a97e8acca72d124a950c4e2fcd08c2d4287587c5e70c149f24deb97` |
| `provenance/b1/T6_PROMOTION_RESULT.json` | `2ec9f12fd9008dae0e32675fcdaaf9e7a22fe0ed7006dd310b665b1e82be2ff2` |
| `provenance/b1/voice_source_manifest.json` | `422f5509b12ae101c4bfa96db96254717c3a454f350e1907d05fc6e72eab8df0` |
| `provenance/b1/tempo_evaluator_pins.json` | `375df3abe0daf13cc50741db16db8d0347ba3074b874c3434402d54593476447` |
| `provenance/b1/integrity_synthetic_fixture.json` | `ec1fe4292dea823a4cfca29b83302b04c8a31151c9e5218157982c1fc342aaad` |
| `provenance/b1/integrity_synthetic_validation.json` | `4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab` |
| `provenance/b1/B1_VALIDATION_REPORT.json` | `656c8f960538ac0e35ea85786d1025d2350b581a0adb510a9879b2917506d448` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `configs/backbones/stable_audio_open_1_0.json` | `fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b` |
| `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| `provenance/b2/build_status_pre_generation.json` | `16a13a6275be01b6ba45544b58e37798b93b30ac03ebfe5b99def07f87a0718e` |
| `provenance/b2/stable_audio_3_adapter.json` | `b6add6d47b608930b02de340db52bb3eaf5a36ca10aa19805ae99ba6562b677c` |
| `provenance/b2/stable_audio_open_license_block.json` | `1f5d314c2b01622bdaeb9575404753ea4b4b295ea364765942bde3f2812474ef` |
| `provenance/b2/ace_step_v1_port.json` | `e57705caedab66d8c4b5ac138ed24fcff79527016e71e3a964f1321080d4d923` |
| `configs/b2_mini_smoke_v2.json` | `01a1bd650dbe3f23eeb60c07c46c4a9d66750f4d8070f5e872604c7c4142f632` |
| `B2_MINI_SMOKE_PROTOCOL_v2.md` | `2338cc92b1be99ce011902f9f7429976657ccb8ce2a791634d965096ce9c6118` |
| `scripts/run_b2_mini_smoke_v2.py` | `040d0f75280c7adfbe614f74dab4a236b70068325ea4f85fe20b4b98ad56baff` |
| `scripts/run_b2_mini_smoke_v2_with_timeout.py` | `1ba0dcd7f35e4f56a0f836da10491f440eed12689ca83cca47fbd56aeb47400f` |
| `provenance/b2/b2_mini_smoke_authorization.template.json` | `3d0aaa08408ba394d827a578a8a231a39d3a965af325a4afbb019c2c34506ff1` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/factory.py` | `7774236d732d0262cbc412b4c516c0484ce20867ec48bc370821d037f09f60e3` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/mini_smoke.py` | `d7b810a1f1e35a7193ea2bf3ac34a5071c017c415407b90cf203737f9fed20e5` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `configs/statistics_v2.json` | `d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d` |
| `rater/schema_v2.json` | `0edb492fbf00355aec3e9f059d3b17557814f58b203c963f1c420f0c92ccde76` |
| `rater/freeze_manifest_v2.json` | `3fc506db647b4b1690866abe39f23f786c256376de3f304845a3fae294edc232` |
| `rater/timing_pilot_v2.source.json` | `1328c48f8a10b524cf5fc78e04e415e4c4a86713a9b74a3a9742570981be3d70` |
| `rater/timing_pilot.html` | `78bba8a189b7f281888a7607bb8197ac457196501134e9dec8a3996e724e2708` |
| `rater/timing_pilot_offer_v2.json` | `645cca46a001b42aace2f20a95d35921c6e26d7c56665cb7c457b30cf57227cb` |
| `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/timing-pilot-bundles/benchmark-v2-blinded-timing-pilot-04-51ebc904242e/bundle.json` | `a25454b31672a435ffeb5cdb10593f0ae99dfbe4426e2ae409f71f2dcd2da537` |
| `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/timing-pilot-bundles/benchmark-v2-blinded-timing-pilot-04-51ebc904242e/manifest.json` | `715a2ac5024965a57525f836b690fe21fb0fd5bb1aac25ba35e94fed44ad3a80` |
| `provenance/citation_audit_v2.json` | `f6fadd8b36dfc05b55ba48211c1440de26af10da93f5b8306e4d5d44a5d43311` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |

The additional frozen construction, evaluator, run/ledger, license, and
environment identities are:

| Path | SHA-256 |
| --- | --- |
| `prompts/build_v2_prompts.py` | `5754489fee944a7f03b1f967ca6245f015710af306a47c33576da4d3e24b1ba3` |
| `src/instruments/__init__.py` | `8123ca64673bad026182d590ff35337929dfd5ecc488b01c624daee75c0365a0` |
| `src/instruments/voice.py` | `b952580ec06e8b88cde704a1ad6f8597fd2d15c2f1c4b6e37c90a3a2c2378469` |
| `src/instruments/tempo.py` | `c6cadcb3d65225bccd32ae34c4f5fd9f4881269e738336d3892f0ff7fb614f22` |
| `src/instruments/integrity.py` | `b8d7f22d9b958c5a08a345ccbfba8d7fac09b8b77e51bb762f0f3bedc9a9da5d` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `894e5873c705ee1a8877adc62efffd977a08d6c5c2941175bda89236cbf2d83b` |
| `src/benchmark_core/artifacts.py` | `269845c6a497189cd3eba029007fd22ffb7ffed3027fd5e7ec9f08fd4a8ba83a` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `a48ee85c7c7a2cb2fa9616a5456b4b058e9e8de7d52e6adc27ceecbd91f1f39c` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `8a57fbcb990e7306b3a6389273041519f1f245ed5c5c27f83db25807fb8170f3` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `494333df2429af497a38a62cdd1150403b246f8d2ead7256cdefc08873b1582a` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `d81befde9e813a295bafa1676d8944aa4e1bcad674206ce6cc2eec152fed9284` |
| `scripts/prepare_benchmark_core_run.py` | `b363f44dedf79c839c173c46904ac6f4ea2ed8c3a973ccd9dba502fd6b47e391` |
| `scripts/run_benchmark_core_worker.py` | `40170a3b8be805314164c954923a328debb9783f935647f4b339d41e97f5b12d` |
| `environment/licenses.json` | `10f99624b8438c1dbc385ca2cec9bebac73ecb96cfe1098af32f4b9be8bd3294` |
| `environment/package-freeze.txt` | `da6aae61a6189ee8fc3842fa76652359ff802c6252ce191a199bad5953f98eab` |
| `environment/runtime.json` | `b0e3c4d2dcb9023d862f80518a0bbb1a32f9541ab7c430e0ba7be8fd41fbec70` |
| `LICENSE` | `8bf2f14cad39ed6241ca31c7ee275de9fa3a7695980d52a8fc3cd3812a796987` |

The two B2 calls are non-benchmark engineering measurements. They cannot be
scored by an instrument or human rater, cannot enter a benchmark prompt pool
or human packet, and have zero retries. All other generation, including the
benchmark core and both state-screen queues, remains closed. The exact
authorization assignments are:

`BENCHMARK_PREREG_V2_FROZEN = YES`

`BENCHMARK_PREREG_V2_SHA256 = 77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa`

`B2_MINI_SMOKE_V2_AUTHORIZED = YES`

`B2_MINI_SMOKE_V2_SCOPE = ACE_STEP_V1_ENGINEERING_COST_ONLY_NON_BENCHMARK`

`B2_MINI_SMOKE_V2_CONFIG_SHA256 = 01a1bd650dbe3f23eeb60c07c46c4a9d66750f4d8070f5e872604c7c4142f632`

`B2_MINI_SMOKE_V2_PROTOCOL_SHA256 = 2338cc92b1be99ce011902f9f7429976657ccb8ce2a791634d965096ce9c6118`

`B2_MINI_SMOKE_V2_RUNNER_SHA256 = 040d0f75280c7adfbe614f74dab4a236b70068325ea4f85fe20b4b98ad56baff`

`B2_MINI_SMOKE_V2_WRAPPER_SHA256 = 1ba0dcd7f35e4f56a0f836da10491f440eed12689ca83cca47fbd56aeb47400f`

`B2_MINI_SMOKE_V2_AUTH_TEMPLATE_SHA256 = 3d0aaa08408ba394d827a578a8a231a39d3a965af325a4afbb019c2c34506ff1`

`B2_MINI_SMOKE_V2_SEED_REGISTRY_SHA256 = d9b175296a97e8acca72d124a950c4e2fcd08c2d4287587c5e70c149f24deb97`

`B2_MINI_SMOKE_V2_ACE_CONFIG_SHA256 = b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879`

`B2_MINI_SMOKE_V2_ACE_ADAPTER_SHA256 = a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7`

`B2_MINI_SMOKE_V2_COMMON_FACTORY_SHA256 = 7774236d732d0262cbc412b4c516c0484ce20867ec48bc370821d037f09f60e3`

`B2_MINI_SMOKE_V2_COMMON_RUNNER_SHA256 = d7b810a1f1e35a7193ea2bf3ac34a5071c017c415407b90cf203737f9fed20e5`

`B2_MINI_SMOKE_V2_BACKBONES_INIT_SHA256 = e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0`

`B2_MINI_SMOKE_V2_COMMON_CONTRACTS_SHA256 = 9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2`

`B2_MINI_SMOKE_V2_COMMON_IO_SHA256 = fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a`

`B2_MINI_SMOKE_V2_COMMON_RUNTIME_SHA256 = d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed`

`B2_MINI_SMOKE_V2_SA3_ARTIFACTS_SHA256 = c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3`

`B2_MINI_SMOKE_V2_SA3_AUDIO_SHA256 = c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24`

`B2_MINI_SMOKE_V2_ACE_CHECKPOINT_TREE_SHA256 = 124f8267d6c19f992e8b79880cc59e1ec1104439e6150312ebc94d7563d260fc`

`B2_MINI_SMOKE_V2_ACE_SOURCE_TREE = a526413e5791e8b3bca32c0246701adaf7626f2b`

`B2_MINI_SMOKE_V2_RUNTIME_CONDA_META_SHA256 = d95ae86c3d6c832777b8f571554388fd664044a79e7b8d62138453f58a991845`

`B2_MINI_SMOKE_V2_RUNTIME_PIP_FREEZE_SHA256 = c11b37406749e4ae2abc030bb7ae2c6bb12206a46321af4c45535465086be680`

`B2_MINI_SMOKE_V2_MAX_MODEL_CALLS = 2`

`B2_MINI_SMOKE_V2_MAX_GENERATED_OUTPUTS = 2`

`B2_MINI_SMOKE_V2_MAX_CLIP_SECONDS = 30`

`B2_MINI_SMOKE_V2_MAX_GPUS = 1`

`B2_MINI_SMOKE_V2_MAX_GPU_SECONDS = 1800`

`B2_MINI_SMOKE_V2_RETRIES = 0`

`B2_MINI_SMOKE_V2_PROMPT_IDS = b2-mini-smoke-engineering-ace-01,b2-mini-smoke-engineering-ace-02`

`B2_MINI_SMOKE_V2_RESERVED_NON_BENCHMARK_SEEDS = S-0008:73193008,S-0009:73193009`

`SA3_STATE_CAPABILITY = PASS`

`BENCHMARK_PREREG_V1_FROZEN = NO`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = NO`

`BENCHMARK_CORE_GENERATION_STATUS = NOT_LAUNCHED`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0022 — Terminal B2 adapter receipt and ACE-Step v1 queue closure

- Date: 2026-07-21
- Status: accepted terminal engineering evidence; B2 one-shot consumed
- Authority: D-0021 exact two-call package and its frozen fail-closed rules
- Supersedes: D-0021 only for the now-consumed B2 execution authority

The first placement submission on `an29`, physical GPU 4, was
`REFUSED_PREFLIGHT` before the device lock because that node's local `/tmp`
filesystem was full. It created no global or per-call claim, made zero model
calls, and produced zero outputs. The immutable refusal record SHA-256 is
`2b6315e08152e3f4f414ee854aeebbd6bb2dcf9dd645a2f5156285b5dbf933be`;
its external authorization SHA-256 is
`4fd2016a2ec5342e2cd09dec56e30040b7381755180c220c305846a6a8a7dcec`.
Because the global one-shot claim was still absent, the same unconsumed plan
was submitted on `an12`, physical GPU 4, under authorization SHA-256
`504b91ebdee19a2f3203f45a1d6d3079ad12492bea8131db4edbfa969b9c183d`.
That node had 17 GiB free in `/tmp`, and the selected A800 had 81,226 MiB free,
zero compute processes, and 0% utilization before the runner acquired its
lock. No neighboring process was changed.

The durable global-claim SHA-256 is
`deb9d1c3bff85f96fe162f624a52e54b3b9cc94f84e620efd58d65152a545084`.
Call 0, seed `S-0008 = 73193008`, was claimed once under SHA-256
`93fc96218ef13524237f3a67d2313fed6e18e6dd55c9a919cabcc63198ae0123`
and made one official model call. Its retained WAV SHA-256 is
`1a86fb30dceeb03f5da4e0bcb1cbf488aa2fc7490ac1c8297125e451635bd458`;
adjacent provenance SHA-256 is
`881f09abeb1b4aa103db37125dc3017aa289f6a8b0e6d493b5f15568eaa70f4b`.
The decoded audio was finite, non-silent stereo at 48 kHz, but contained
1,435,551 frames (`29.9073125 s`) rather than the frozen exact 1,440,000-frame
30-second requirement. Sanity therefore failed and call 1 was not made.

The one retained ledger row has `cost_status = MEASURED`: actual NFE 45,
CUDA-synchronized wall `27.25068249553442 s`, load wall
`182.45191994681954 s`, and peak allocated/reserved VRAM
`8,371,735,040 / 10,085,203,968 B`. It remains a factual failed-call cost row,
not a launch calibration. The generation ledger, terminal runner result,
outer terminal result, manifest, and terminal log SHA-256s are respectively
`d6b9aa821f8a4031b370ec267c864a3bbe5d68f8fb8fed26efad4cdc58b9c627`,
`012a6ebb57c2273cf4cea5d4a678bc4285acc92a20d199d481baceb2fd120f36`,
`66c4aafd3dc1d7c8da774d539f003fe03c94ae276e248d85386411461a693df0`,
`466b56249594724e0241cf6fe0f447fa71012bac23bd3a63cde4a38cdd8470e2`,
and `7faccba0587237d653e355cc9555c83c5d9a23f0c0ab559f9e11f4124fb9028d`.
No benchmark instrument or human rater scored this output.

The terminal Phase-B receipt is
`provenance/b2/build_status_terminal_v2.json`, SHA-256
`d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72`.
SA3 is `MEASURED_READY`; Stable Audio Open 1.0 remains
`BLOCKED_ON_LICENSE`; ACE-Step v1 is `FAIL_ESCALATED` and
`BLOCKED_ON_ENGINEERING_FAILURE`. All B2 statuses are terminal. Only SA3 may
enter the ordinary core queue.

`B2_MINI_SMOKE_V2_AUTHORIZATION_STATUS = CONSUMED`

`B2_MINI_SMOKE_V2_AUTHORIZED = NO`

`B2_MINI_SMOKE_V2_STATUS = FAIL_ESCALATED`

`ACE_STEP_V1_QUEUE_STATUS = BLOCKED_ON_ENGINEERING_FAILURE`

`STABLE_AUDIO_OPEN_1_0_QUEUE_STATUS = BLOCKED_ON_LICENSE`

`STABLE_AUDIO_3_MEDIUM_BASE_QUEUE_STATUS = READY`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = NO`

## D-0023 — Benchmark v2 ordinary-core launch authorization

- Date: 2026-07-21
- Status: accepted prospectively; ordinary SA3 core queue open
- Authority: Chief Scientist / PI consolidated benchmark-v2 launch task
- Supersedes: D-0022 only for the ordinary ready-backbone core queue

The frozen v2 design and every Phase-B model row are terminal. The ordinary
core may launch only the `READY` SA3 backbone: 1,536 registered 30-second
requests, shard size four, one `an12` A800, physical GPU 4, TP1, and one
replica. Stable Audio Open 1.0 and ACE-Step v1 receive no queue rows. The SA3
GPU-seconds cap is exactly `76939.90662887692` (`21.372196285799145 GPU-h`),
from `c_m = 116.34399104863405`, `u_m = 25.023961771279573`, and `n_m = 1536`.
No automatic retry, prompt replacement, shorter clip, extra seed, evaluator,
or human-packet assembly is authorized.

The initial 432-row and supplemental 432-row state manifests may be
materialized but both remain closed. Ordinary workers cannot consume them.
The supplemental state queue is locked unless a later initial gate is
`INCONCLUSIVE_UNDERPOWERED` and another decision opens the sole doubling.
Human-audit packet assembly remains blocked on timing-pilot ingestion.

The exact launch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2.json` | `d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `src/benchmark_core/adapter_bridge.py` | `894e5873c705ee1a8877adc62efffd977a08d6c5c2941175bda89236cbf2d83b` |
| `src/benchmark_core/artifacts.py` | `269845c6a497189cd3eba029007fd22ffb7ffed3027fd5e7ec9f08fd4a8ba83a` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `a48ee85c7c7a2cb2fa9616a5456b4b058e9e8de7d52e6adc27ceecbd91f1f39c` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `8a57fbcb990e7306b3a6389273041519f1f245ed5c5c27f83db25807fb8170f3` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `494333df2429af497a38a62cdd1150403b246f8d2ead7256cdefc08873b1582a` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `d81befde9e813a295bafa1676d8944aa4e1bcad674206ce6cc2eec152fed9284` |
| `scripts/prepare_benchmark_core_run.py` | `b363f44dedf79c839c173c46904ac6f4ea2ed8c3a973ccd9dba502fd6b47e391` |
| `scripts/run_benchmark_core_worker.py` | `40170a3b8be805314164c954923a328debb9783f935647f4b339d41e97f5b12d` |
| `prompts/v2/manifest.json` | `171d6c757ff3ecec1918d2f032206c2b570b3302dc5ed0100da0db5d22708089` |
| `prompts/v2/vocal_instrumental.json` | `602c4e0fb419d7a300116eb5fb76c30a8e19364aaef566aec05425caffed9f90` |
| `prompts/v2/tempo.json` | `16e31c155e1d535f2211fcd85c8d666c9ba7a6636e4487fd43ea2fd5fa0e36ab` |
| `prompts/v2/integrity.json` | `be0e7c65fa8dfad8c7fdbf4456b2c1ad7e6f4fe0bbeb67eba2fcbf96b5f16d03` |
| `prompts/v2/structure_exploratory.json` | `6e9ca89c20ebb43313d9b492140970d876a5cfc657cf123cfe44b7d89e974af8` |
| `prompts/v2/seed_registry.json` | `2115d7e70a6c3f4dd19f38503861b8aeb3595a8f64dd1fc839d7a209e80724eb` |
| `configs/statistics_v2.json` | `d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d` |
| `provenance/b1/integrity_synthetic_validation.json` | `4e1b124ad2247eced85d21f049ad5b3849a4e1dd1a395689c235ec3d998a4dab` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |

`BENCHMARK_PREREG_V2_FROZEN = YES`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_GENERATION_STATUS = LAUNCH_AUTHORIZED`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0024 — Ordinary-core pre-call recovery and exact relaunch authorization

- Date: 2026-07-21
- Status: accepted after a fail-closed pre-call stop; one fresh run authorized
- Authority: Chief Scientist / PI consolidated benchmark-v2 launch task
- Supersedes: D-0023 only for the retained failed run and its launch artifact

Run `benchmark-core-v2-20260720t173000z` stopped before adapter load, request
claim, model call, audio creation, or ledger append. Its terminal heartbeat is
`FAILED_STOPPED`; there are zero request claims, zero WAV files, and the
shared ledger is zero bytes. The retained launch claim, run manifest,
heartbeat, worker log, launcher output, and load reservation have SHA-256s
`f10484ff52460ba53e808f97d8cfa3ef67dba09367e2c2e21cea7c083fa18652`,
`d8ca94d445326a87b1bf07813438b8a24ea5088649f242616e6f10e19d2ea0cb`,
`dcd1b7160aa163e7f3ffb57a74770ef17ec33c661cd3d2839f92c784c7185915`,
`2d12fbf3aa01e27edaf1c4c9639dc76a73611ceaa2dd64058987509b242f8404`,
`77271ed10cb60666dc38480a856536aafa32b426263e063e319fd8b19bba9061`,
and `f9b1ee5e39bbd506b03d420dbde57c8e7e0b4b2d324979e5d707c5806fe515b8`.
That run is immutable terminal evidence and cannot be reused.

The stop exposed an identity-representation defect in the benchmark adapter:
the frozen CUDA wheel build was compared directly with the wheel's public
PEP 440 distribution metadata. Live evidence shows distribution metadata
`torch = 2.7.1` and `torchaudio = 2.7.1`, imported-module versions
`torch = 2.7.1+cu126` and `torchaudio = 2.7.1+cu126`, and CUDA build `12.6`.
The reviewed correction now requires both layers exactly. It does not change
the model, prompts, seeds, NFE, duration, queue, budget, placement, evaluator,
or retry policy. Regression tests prove that public metadata passes only with
the exact imported local-build identity, and that module-build, public
metadata, or flash-attention distribution drift each fails closed.

The launch freezer now also binds the production SA3 adapter, its config, and
every project-local runtime dependency used by it. One fresh run with exact ID
`benchmark-core-v2-20260720t174500z` may consume the unchanged ordinary SA3
queue under the D-0023 caps. The earlier run consumed no generation call and
therefore does not reduce the 1,536-call ordinary queue or its GPU-seconds cap.
There is no automatic retry after any request claim. Both state queues and
human-audit packet assembly remain closed.

The exact relaunch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2.json` | `d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/backbones/stable_audio_3.py` | `909f3efceb296caca59667ae4d0a4aa777d74d37a9e86b5170bdaba23ae2aa6b` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `894e5873c705ee1a8877adc62efffd977a08d6c5c2941175bda89236cbf2d83b` |
| `src/benchmark_core/artifacts.py` | `269845c6a497189cd3eba029007fd22ffb7ffed3027fd5e7ec9f08fd4a8ba83a` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `a48ee85c7c7a2cb2fa9616a5456b4b058e9e8de7d52e6adc27ceecbd91f1f39c` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `8a57fbcb990e7306b3a6389273041519f1f245ed5c5c27f83db25807fb8170f3` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `494333df2429af497a38a62cdd1150403b246f8d2ead7256cdefc08873b1582a` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `d81befde9e813a295bafa1676d8944aa4e1bcad674206ce6cc2eec152fed9284` |
| `src/sa3_smoke/__init__.py` | `18704985ac543674c1b8a1ac78764fba1b6f2fa3bf7748efa3fb26f40173af60` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `src/sa3_smoke/budget.py` | `dc1b5ecfdb193e1defd90e48f6fe7a7fb05ce38b9191ea9a1271c0e39a91c332` |
| `src/sa3_smoke/environment_validation.py` | `684e736671055ffc5ad5e14ffe160aef9816ccc3317b080d7beef56dc38cc6fa` |
| `src/sa3_smoke/model_runtime.py` | `614fc7e6d016e1dc07971a028653749318edac2c3c980a40d73aaf8be709fde4` |
| `scripts/prepare_benchmark_core_run.py` | `a5ed0f741e6c4dbae6549f5de07df55997f4956669d9701c1b089133e5420046` |
| `scripts/run_benchmark_core_worker.py` | `40170a3b8be805314164c954923a328debb9783f935647f4b339d41e97f5b12d` |

`BENCHMARK_PREREG_V2_FROZEN = YES`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_GENERATION_STATUS = RELAUNCH_AUTHORIZED`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0025 — Benchmark v2 ordinary core launched and first batch ledgered

- Date: 2026-07-21
- Status: accepted execution milestone; resident worker continues
- Authority: D-0024 exact recovery launch package
- Supersedes: D-0024 only for ordinary-core launch status

Fresh run `benchmark-core-v2-20260720t174500z` was prepared with zero model
calls from clean Git `f8a44fedf4a466d8dea43c81f58bc6fdb2f8bae1`, equal to
`origin/main`. Its config, launch claim, run manifest, and generation queue
SHA-256s are respectively
`d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61`,
`b03e25ec7ab098d3c563169626c5b1888c7c0aad619e978575b28090cba096fa`,
`e3d6e8a11bc4a0dd47cd454823463cb699c76b79671ec4aadc09b4799428f56c`,
and `afedee0bb422c27c2cad64e7be9dc960384f706f8f9201bbea95e8f2418c7bf4`.

The worker runs on `an12`, physical GPU 4 exposed as logical GPU 0, TP1,
one replica. Immediately before launch that A800 had 81,226 MiB free, no
compute PID, and 0% utilization. Neighboring processes on GPUs 0–3 were not
changed. Model-load wall was measured as `72.65626287087798 s`.

Immutable heartbeat snapshot
`shard-000000-e0cbcec63a1c400b6798ec0e14b747c65f1c73f51944315a07dc591deb30bea3.json`
has the same SHA-256 as its embedded suffix. It records the first complete
four-row shard: four completed, zero failed, `RUNNING`, synchronized call wall
`29.783272966742516 s`, peak allocated/reserved VRAM
`5,437,102,080 / 9,839,837,184 B`, and final shard ledger-row SHA-256
`6d54f1ce9508b5f89329525a4339d2ae69fb5d2385f686917e040614636be904`.
The four retained WAV SHA-256s are
`7ebab84222e3498d18e194fed6422ac990550a7b05b691c0921b3c38d3617e88`,
`d250377495c13ad9bc1b5fdb4399d4cb84b740df9fca93559fbe5f9d7d4ac46e`,
`a9d6a65e96e48416c721b3dce0684e4518e5299f062bd87658f46593d0d8d3a7`,
and `4334ed0f55a9b78cc87e613206a56cc95a6715991445ec8db91e1127e86fea43`.
All four passed exact retained-audio sanity and have adjacent provenance and
commit records.

The worker continues after this milestone under the frozen cap and no-retry
rules. No benchmark endpoint has been scored. Both state queues remain closed,
the timing-pilot response has not been ingested, and human-audit packet
assembly remains blocked.

`BENCHMARK_PREREG_V2_FROZEN = YES`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_GENERATION_STATUS = LAUNCHED_FIRST_LEDGERED_BATCH`

`BENCHMARK_CORE_ACTIVE_RUN_ID = benchmark-core-v2-20260720t174500z`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0026 — ACE-Step v1 duration-sanity amendment and sole confirmation authority

- Date: 2026-07-21
- Status: accepted prospectively; exactly one non-benchmark confirmation call authorized
- Authority: Chief Scientist / PI duration-sanity amendment and final B2 ruling
- Supersedes: D-0022 only for interpretation of its sole `sample_count` failure;
  D-0025 only for the now-complete SA3 ordinary-core status

The exact-frame duration invariant was frozen before ACE-Step v1's decoder
frame-rate behavior was known. It is replaced for benchmark-v2 retained-audio
sanity by an explicit per-backbone decoded-duration rule:

`abs(decoded_duration_seconds - requested_duration_seconds) <= 0.25 seconds`

The boundary is inclusive. ACE-Step v1 and Stable Audio 3 both receive exactly
the same `0.25 s` tolerance. This changes only the duration criterion: requested
clips remain capped at `30.0 s`, while sample rate, stereo channels,
decodeability, finite samples, non-silence, provenance, retention, and
no-clobber checks remain strict. SA3's completed 1,536-row core run produced
exact 30-second outputs throughout, so this does not loosen any obtained SA3
acceptance in practice. Its project receipt is
`provenance/core/sa3_core_completion_v2.json`, SHA-256
`4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6`:
1,536 completed, zero failed, terminal heartbeat `COMPLETE`, and no row may be
regenerated.

### Decoder-quantization provenance

The old repository's pre-generation frozen protocol and prompt snapshot are
SHA-256 `e20e0fbeff2cd98acd7df765ad042336a56cbe910547c64e53cf87be65a15176`
and `a616137db58e2e639c2c2665688b72fb0d3c06253cc0266763e52107b79558a6`,
committed at `7f63ab79948736c5bb6bd0d733c3eb570a1a2ac6`. Snapshot row 197 binds
`dev_0196` to a `30.0 s` target. Eight independent ACE-Step v1 outputs at row
99 of ledgers `generation_w0.jsonl` through `generation_w7.jsonl`, committed
at `a2655a19a8f11eb22e5ca9991acf7dd2eeed2f5f`, are each ledgered `PASS`,
48 kHz, and `29.907312 s` after six-decimal serialization. Their ledger
SHA-256s are, in worker order:

1. `ebb9a8fa171efb1f57e4739730dc53c07d239219ab1a2ceb627fe334d762b51c`
2. `b6252f5077cb857a9d74da269317d2888a4f0f839fbdbac9217d271c9a5b59cd`
3. `8aded005153d3d979e41b74e5620cf5cd3c18701713efd1f1e334f20dfc49983`
4. `73626e147e221e4e7e9ef6958dfffd2fdf349086be22f52278b5a6355d711e6b`
5. `57a3c639eb12d8968b703f83776d748f4c9e5f28bcf156e76041eed78db02e2f`
6. `fa1126fe485997c3ab629b49c19f7e6f0bfa7fc889ae2c8c732db7b554c16551`
7. `576fb3aa10be527a505c8c8bcd00b58ba1d99d64260d1bda6c5593a99c8c69a6`
8. `36763f24bc7dd91ee93176312aa4b299b031736dc3560cfe44650b13c3a86f51`

Read-only probes of all eight SHA-bound retained WAVs give 1,435,551 stereo
frames at 48 kHz, exactly `29.9073125 s`, an absolute deviation of
`0.0926875 s`. The full extraction, row identities, seeds, media hashes, Git
ancestry, and the qualification that WAVs are SHA-bound persistent media but
not themselves Git-tracked are recorded in
`provenance/b2/ace_duration_quantization_provenance_v1.json`, SHA-256
`1e7628491badc2d70cfc8357b7502d1facb6b6ed5b8282e73e60302ef5b9f254`.

D-0022's retained call 0 has the same 1,435,551-frame native duration and no
other sanity failure. It therefore passes the amended duration rule. This is
recorded without rewriting its old ledger, result, claim, provenance, or WAV
in `provenance/b2/ace_call0_duration_readjudication_v1.json`, SHA-256
`be4e3a9d705c1e8cb627b08fec3be28fad6ff4623d530283b7f32056a031129e`.
The original row correctly remains `AUDIO_SANITY_FAILED` under the superseded
exact-frame rule.

### Exact one-call package and terminal rule

Exactly one remaining engineering call is authorized in fresh immutable run
`b2-ace-v1-duration-confirmation-v1-001`: original B2 job 1, prompt
`b2-mini-smoke-engineering-ace-02`, seed `S-0009 = 73193009`, requested
duration `30.0 s`, empty lyrics, and output `audio/confirmation-00.wav`.
It is non-benchmark, unscored, excluded from the human packet, and uses one
idle A800, TP1, one replica. Caps are one model call, one output, 1,800
one-GPU seconds, and zero retries. No alternate prompt, seed, run ID, output,
or duration is allowed.

A completed authorization must live outside the repository, bind the
post-append `DECISIONS.md`, clean `main == origin/main`, exact source,
checkpoint, runtime, package hashes, node, and physical GPU, and expire within
24 hours. Once that authorization validates, the runner durable-writes an
exclusive authorized-attempt claim before any prior-evidence, runtime, GPU,
or adapter preflight. Any subsequent new failure is terminal
`BLOCKED_ON_ENGINEERING_FAILURE`; the attempt cannot be submitted again and
no further B2 call is permitted. On PASS only, a later append-only decision
may set ACE-Step v1 to `MEASURED_READY`, freeze its measured cost row, and
open a fresh ACE-only core queue. SA3 is explicitly excluded from that future
generation queue; both state queues remain closed.

The frozen confirmation package is:

| Path | SHA-256 |
| --- | --- |
| `configs/b2_ace_duration_confirmation_v1.json` | `0cb1bb88f98bcc23093713c2edd969908da14f0fa991ed0c54fcc4dea6a88162` |
| `B2_ACE_DURATION_CONFIRMATION_PROTOCOL_v1.md` | `02ea12725dfec085e5375714653f46d81106a0c95a7c412306a4eea0ad324d4b` |
| `scripts/run_b2_ace_duration_confirmation_v1.py` | `656062a15bc00496a56341cdea1b7db93a8c44147d8ee5533a28293e6106ed20` |
| `scripts/run_b2_ace_duration_confirmation_v1_with_timeout.py` | `bdf83f3478f684fd3fed0da0ab2921b010f19a3c2d2c0dcfe7eb36a867db8acf` |
| `provenance/b2/b2_ace_duration_confirmation_authorization.template.json` | `a96e16bff5650a7a2548bb31a31e47a1e9e98052dfd878493120ed81a0901931` |
| `src/audio_duration_policy.py` | `54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e` |
| `src/backbones/duration_sanity.py` | `a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6` |

Stable Audio Open 1.0 remains `BLOCKED_ON_LICENSE`; therefore the PI's
two-backbone continuation on an ACE failure is a scope intent contingent on a
future valid SAO license/access receipt, not a claim that two backbones are
currently executable.

`BENCHMARK_PREREG_V2_FROZEN = YES`

`BENCHMARK_PREREG_V2_SHA256 = 77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa`

`B2_MINI_SMOKE_V2_AUTHORIZED = NO`

`B2_ACE_DURATION_CONFIRMATION_V1_AUTHORIZED = YES`

`B2_ACE_DURATION_CONFIRMATION_V1_SCOPE = ACE_STEP_V1_DURATION_CONFIRMATION_NON_BENCHMARK`

`B2_ACE_DURATION_CONFIRMATION_V1_CONFIG_SHA256 = 0cb1bb88f98bcc23093713c2edd969908da14f0fa991ed0c54fcc4dea6a88162`

`B2_ACE_DURATION_CONFIRMATION_V1_PROTOCOL_SHA256 = 02ea12725dfec085e5375714653f46d81106a0c95a7c412306a4eea0ad324d4b`

`B2_ACE_DURATION_CONFIRMATION_V1_RUNNER_SHA256 = 656062a15bc00496a56341cdea1b7db93a8c44147d8ee5533a28293e6106ed20`

`B2_ACE_DURATION_CONFIRMATION_V1_WRAPPER_SHA256 = bdf83f3478f684fd3fed0da0ab2921b010f19a3c2d2c0dcfe7eb36a867db8acf`

`B2_ACE_DURATION_CONFIRMATION_V1_AUTH_TEMPLATE_SHA256 = a96e16bff5650a7a2548bb31a31e47a1e9e98052dfd878493120ed81a0901931`

`B2_ACE_DURATION_CONFIRMATION_V1_DURATION_POLICY_SHA256 = 54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e`

`B2_ACE_DURATION_CONFIRMATION_V1_DURATION_SANITY_SHA256 = a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6`

`B2_ACE_DURATION_CONFIRMATION_V1_QUANTIZATION_PROVENANCE_SHA256 = 1e7628491badc2d70cfc8357b7502d1facb6b6ed5b8282e73e60302ef5b9f254`

`B2_ACE_DURATION_CONFIRMATION_V1_READJUDICATION_SHA256 = be4e3a9d705c1e8cb627b08fec3be28fad6ff4623d530283b7f32056a031129e`

`B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_GLOBAL_CLAIM_SHA256 = deb9d1c3bff85f96fe162f624a52e54b3b9cc94f84e620efd58d65152a545084`

`B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_CALL_CLAIM_SHA256 = 93fc96218ef13524237f3a67d2313fed6e18e6dd55c9a919cabcc63198ae0123`

`B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_LEDGER_SHA256 = d6b9aa821f8a4031b370ec267c864a3bbe5d68f8fb8fed26efad4cdc58b9c627`

`B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_WAV_SHA256 = 1a86fb30dceeb03f5da4e0bcb1cbf488aa2fc7490ac1c8297125e451635bd458`

`B2_ACE_DURATION_CONFIRMATION_V1_PRIOR_PROVENANCE_SHA256 = 881f09abeb1b4aa103db37125dc3017aa289f6a8b0e6d493b5f15568eaa70f4b`

`B2_ACE_DURATION_CONFIRMATION_V1_MAX_MODEL_CALLS = 1`

`B2_ACE_DURATION_CONFIRMATION_V1_MAX_GENERATED_OUTPUTS = 1`

`B2_ACE_DURATION_CONFIRMATION_V1_MAX_REQUESTED_CLIP_SECONDS = 30`

`B2_ACE_DURATION_CONFIRMATION_V1_DURATION_TOLERANCE_SECONDS = 0.25`

`B2_ACE_DURATION_CONFIRMATION_V1_MAX_GPUS = 1`

`B2_ACE_DURATION_CONFIRMATION_V1_MAX_GPU_SECONDS = 1800`

`B2_ACE_DURATION_CONFIRMATION_V1_RETRIES = 0`

`B2_ACE_DURATION_CONFIRMATION_V1_PROMPT_ID = b2-mini-smoke-engineering-ace-02`

`B2_ACE_DURATION_CONFIRMATION_V1_RESERVED_SEED = S-0009:73193009`

`B2_ACE_DURATION_CONFIRMATION_V1_STATUS = AUTHORIZED_NOT_RUN`

`ACE_STEP_V1_QUEUE_STATUS = PENDING_DURATION_CONFIRMATION`

`STABLE_AUDIO_OPEN_1_0_QUEUE_STATUS = BLOCKED_ON_LICENSE`

`STABLE_AUDIO_3_MEDIUM_BASE_QUEUE_STATUS = COMPLETE`

`PHASE_B_STATUS = AMENDMENT_CONFIRMATION_AUTHORIZED`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = NO`

`BENCHMARK_CORE_GENERATION_STATUS = SA3_COMPLETE_ACE_PENDING_CONFIRMATION`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0027 — ACE-Step v1 confirmation PASS and incremental core launch authority

- Date: 2026-07-21
- Status: accepted terminal B2 adjudication; exact ACE-only ordinary-core run authorized
- Authority: Chief Scientist / PI duration-sanity amendment and final B2 ruling
- Supersedes: D-0026 for ACE-Step v1 terminal build and queue status; D-0025
  only for the now-complete SA3 ordinary-core run

The sole D-0026 confirmation was executed once on `an12`, physical GPU 4,
TP1, one replica, from clean Git
`549f6942599047a579d7561af823adc20154a8d5`, equal to `origin/main`.
S-0009 produced exactly one retained output and no retry. The terminal result
is `PASS`: the 30-second request decoded to 1,435,551 stereo frames at
48 kHz, exactly `29.9073125 s`, so its `0.0926875 s` deviation satisfies
the inclusive per-backbone `0.25 s` rule. Decodeability, finite samples,
non-silence, clipping, channels, sample rate, provenance, retention, and
no-clobber checks all pass.

The authorization, authorized-attempt claim, global claim, per-call claim,
manifest, generation ledger, retained WAV, retained provenance, terminal
result, and hash-chained operational log have SHA-256s:

1. `d0a166c349eb30298d61679f2645b2b5a79b326494363c424fa9facfc3253530`
2. `be7c10cfd2f8240e15b70ccd89957955ee6c18f75a2acf4388004c47fc50e4ef`
3. `bdbde44981fdca3578580dd64256089c6b53b7f7530931ac282940d5e138de25`
4. `2ce0b8c1da213e86fa388ae3e2d64f30c924b5b2d5ce8699dfd26315149e64c5`
5. `a0ecd2229575e2702dc55c9bc1bb4b679300ddb7a9ec8d8ba6933b4a25af1ce1`
6. `714c40d22ee6f8285feb64e0102d03eef5923d4face628b2c0fb957f913d562e`
7. `5070dc1b8916cc0cdc7d8fdf533968e72b5fe4198829546bd01fed4525b3a052`
8. `b1c141a59d3eebded4f7cf587d9325c46328bf4fc9d4d459af10321cec08fe67`
9. `213ab5fa2937ae263a1c2fbee1276774755a69d60a0e0032f388ed7677720f75`
10. `34cfe3ba1cf785eebc52ae57ad3fa29e41fb0cf74ca4f8741ad74e7d08308e72`

Measured confirmation cost is 45 actual NFE, call wall
`30.9385858848691 s`, load wall `241.99800701066852 s`, one-GPU
residency `281.0608921535313 s`, and peak allocated/reserved VRAM
`8,371,731,968 / 10,085,203,968 B`. Combining the two valid ACE
observations conservatively gives
`u_m = max(27.25068249553442, 30.9385858848691) = 30.9385858848691 s`
and
`c_m = max(182.45191994681954 + 27.25068249553442,
241.99800701066852 + 30.9385858848691) = 272.93659289553762 s`.
For 1,536 calls, the exact frozen cap is
`c_m + 1535 * (2 * u_m) = 95254.39525944367462 GPU-s`
(`26.459554238734354 GPU-h`).

ACE-Step v1 is therefore `MEASURED_READY`, with mini-smoke status
`MEASURED_MINI_SMOKE_PASS` and ordinary queue status `READY`. The
D-0026 confirmation authority is consumed and closed; no additional B2 call
is authorized. Stable Audio Open 1.0 remains `BLOCKED_ON_LICENSE`.
The completed 1,536-row SA3 run remains immutable, complete, and excluded
from this queue through its project receipt.

Exactly one fresh ordinary-core run,
`benchmark-core-v2-ace-20260721t091500z`, may be prepared and launched.
Its generation allowlist contains only
`ACE-Step/ACE-Step-v1-3.5B`: 1,536 registered 30-second requests, shard
size four, one `an12` A800 on physical GPU 4, TP1, one replica, and the
exact cap above. There is no automatic retry, row replacement, extra seed,
shorter clip, substitute model, evaluator scoring, or human-packet assembly
authority. SA3 receives no generation row. The initial and supplemental
state manifests may be materialized from the SHA-bound prior SA3 queue but
remain closed and cannot be consumed.

The exact launch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2_ace_incremental.json` | `6e4886b235474ea08083b9a01d24d6cddaad8443ce3e0ab3fef49dedfe5ef23f` |
| `provenance/b2/build_status_terminal_v2_ace_amendment.json` | `619eb06b21012624b446dfa0d41dc6602c060889406ec431ff52d5a9cb879a34` |
| `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| `provenance/core/sa3_core_completion_v2.json` | `4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `src/audio_duration_policy.py` | `54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/duration_sanity.py` | `a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/backbones/stable_audio_3.py` | `909f3efceb296caca59667ae4d0a4aa777d74d37a9e86b5170bdaba23ae2aa6b` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `894e5873c705ee1a8877adc62efffd977a08d6c5c2941175bda89236cbf2d83b` |
| `src/benchmark_core/artifacts.py` | `aec1a672456df5cdae8adf2c2900cd5f4c0fa7904bb3420b16128ac9c4179a8c` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `afd0d962f67e4ac29d2d2e0154b4af6f09653d7e807c54e56d2fb574b5b8b5cf` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `2145c1c7aab9f82addf3f6b70bf7ba81a9f0442f63ff1f1da59b0acaec892ee5` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `df7b37f29ca000ad26a33944ae9f4e9f08677bc7c122b981e8aeb23bacf8f7f7` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `2f23b6172b9d5d012caa15eb4d07a6fc0ee6d20ebe88e4ea2c7bbf6fbafdecea` |
| `src/sa3_smoke/__init__.py` | `18704985ac543674c1b8a1ac78764fba1b6f2fa3bf7748efa3fb26f40173af60` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `src/sa3_smoke/budget.py` | `dc1b5ecfdb193e1defd90e48f6fe7a7fb05ce38b9191ea9a1271c0e39a91c332` |
| `src/sa3_smoke/environment_validation.py` | `684e736671055ffc5ad5e14ffe160aef9816ccc3317b080d7beef56dc38cc6fa` |
| `src/sa3_smoke/model_runtime.py` | `614fc7e6d016e1dc07971a028653749318edac2c3c980a40d73aaf8be709fde4` |
| `scripts/prepare_benchmark_core_run.py` | `5b76ea7ef5001bfaf3d8e8be9e99562849b719de983ce5469e8543fdb801e43f` |
| `scripts/run_benchmark_core_worker.py` | `9961f057d56dd7cad820dc4075362650cc9a20ff9ec36ac3bc5ad39830fc5b25` |

`BENCHMARK_PREREG_V2_FROZEN = YES`

`B2_MINI_SMOKE_V2_AUTHORIZED = NO`

`B2_ACE_DURATION_CONFIRMATION_V1_AUTHORIZED = NO`

`B2_ACE_DURATION_CONFIRMATION_V1_STATUS = PASS_TERMINAL`

`ACE_STEP_V1_BUILD_STATUS = MEASURED_READY`

`ACE_STEP_V1_QUEUE_STATUS = READY`

`STABLE_AUDIO_OPEN_1_0_QUEUE_STATUS = BLOCKED_ON_LICENSE`

`STABLE_AUDIO_3_MEDIUM_BASE_QUEUE_STATUS = COMPLETE`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_GENERATION_STATUS = ACE_INCREMENTAL_LAUNCH_AUTHORIZED`

`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = ACE-Step/ACE-Step-v1-3.5B`

`BENCHMARK_CORE_AUTHORIZED_RUN_ID = benchmark-core-v2-ace-20260721t091500z`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0028 — ACE-Step v1 incremental core launched and first batch ledgered

- Date: 2026-07-21
- Status: accepted execution milestone; resident ACE worker continues
- Authority: D-0027 exact ACE-only launch package
- Supersedes: D-0027 only for ACE ordinary-core launch status

Run `benchmark-core-v2-ace-20260721t091500z` was prepared with zero model
calls from clean Git `79d9193b7e67944242395600576d0a3762503ea6`, equal
to `origin/main`. Its config, launch claim, run manifest, generation queue,
initial state queue, and supplemental state queue SHA-256s are respectively:

1. `6e4886b235474ea08083b9a01d24d6cddaad8443ce3e0ab3fef49dedfe5ef23f`
2. `9ae7640d42198cd0a985f092d40a06afb63affbdb9963a7ead6c70249ce8a990`
3. `776cf4ed9bd14a6bc1712d3edc85cf21c27694861810fd8353d3895882aab64d`
4. `db4ce65dabee9219e30a5c22c0eb56ed7b0a6f9e3ebaf98302f725cb8e8fd37f`
5. `bc03a333e9cb096747ca7d9392a1a33a1c781315b1c1c698b20c888f74ca00c8`
6. `e7eb055e53183f2f6f85bd6ede586e9ed22a390a07cc149bdb121261961da8c1`

The 1,536-row generation queue contains all and only
`ACE-Step/ACE-Step-v1-3.5B`. The two 432-row state queues are reconstructed
from the SHA-bound completed SA3 queue; the initial queue remains closed and
the supplemental queue remains locked. SA3 receives no generation row.

The worker runs on `an12`, physical GPU 4 exposed as logical GPU 0, TP1,
one replica. Immediately before launch the A800 had 81,226 MiB free, no
compute PID, and 0% utilization. The load wall was
`123.0669956356287 s`. The worker is detached as PID `3426125` and
continues under the frozen no-retry and
`95,254.39525944367462 GPU-s` cap.

Immutable heartbeat snapshot
`shard-000000-b76fb604e0151bb88ccda1bc7badfc566db71bd21638143c5606fda8efc93a6f.json`
has the same SHA-256 as its embedded suffix. The immutable shard record
SHA-256 is
`1466cec9a528e157a7ead46fcfde879eba357ef10f3149c2af4858e1d41d5ac2`.
The boundary records four completed, zero failed, `RUNNING`, synchronized
call wall `11.75711365789175 s`, peak allocated/reserved VRAM
`8,544,569,856 / 10,085,203,968 B`, and ledger tail SHA-256
`4d0a91627c3b4175ee5891ded72ea52f30f4447f5fbb23a9a3d77acb60631fab`.

The four rows are BASE roots 0–3 for `voice-frame-01-vocal`, each with
actual NFE 45. Their synchronized walls are
`3.715504363179207`, `2.7087645642459393`,
`2.6346603482961655`, and `2.6981843821704388 s`. Their retained WAV
SHA-256s are:

1. `563473b06c7d84a9e550e8ff6ba761d7aa3e82a9945cef12caf33cfd9bd0a5ec`
2. `f2cf0ef8142404b83e3f74d3411a44fbbff4987718d3b4cc63b817fa33ac1f9b`
3. `080659bc3e5ae984604132f0227dd1d475e6b2c47d1ef6cfdce8f3386df7f7ca`
4. `746610fd7d90029ca45954cbd8378e6db17503bac3a1faa95ba9a04936d32831`

Their adjacent commit-record SHA-256s are:

1. `c67d9932ecae50834b1c1d41f47afa0c41bc07ab96a1470b701eb12082a8be3f`
2. `180b424c34d2a7db55a0d06e4009ee390a8542def5a5f4138bfba43d4730affc`
3. `cf3015dd64fe2306f38b0aac94176df65dfd7eb0ec4505b197edebad95123f3f`
4. `c10404c0e9a7d6ba085fab97c170112e7a8e0a86b2301363c80a43e105088a1c`

Every first-shard output is retained, 48-kHz stereo, finite, non-silent,
provenance-valid, and `29.9073125 s`; every duration deviation is within
the inclusive `0.25 s` ACE rule. No automatic endpoint has scored these
outputs and no human label has been obtained. Both state queues, automatic
evaluation, and human-audit packet assembly remain closed.

`BENCHMARK_PREREG_V2_FROZEN = YES`

`B2_ACE_DURATION_CONFIRMATION_V1_AUTHORIZED = NO`

`ACE_STEP_V1_BUILD_STATUS = MEASURED_READY`

`ACE_STEP_V1_QUEUE_STATUS = READY`

`STABLE_AUDIO_OPEN_1_0_QUEUE_STATUS = BLOCKED_ON_LICENSE`

`STABLE_AUDIO_3_MEDIUM_BASE_QUEUE_STATUS = COMPLETE`

`PHASE_B_STATUS = TERMINAL`

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_GENERATION_STATUS = ACE_INCREMENTAL_LAUNCHED_FIRST_LEDGERED_BATCH`

`BENCHMARK_CORE_ACTIVE_RUN_ID = benchmark-core-v2-ace-20260721t091500z`

`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = ACE-Step/ACE-Step-v1-3.5B`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`HUMAN_AUDIT_PACKET_ASSEMBLY = BLOCKED_ON_TIMING_PILOT_INGESTION`

## D-0029 — Automatic endpoint-scoring lane opened on completed shards

- Date: 2026-07-22
- Status: accepted narrow execution opening
- Authority: PI scoring-and-state-lanes authorization
- Supersedes: D-0028 only for automatic scoring of immutable completed core
  shards; it grants no audio-generation authority

Automatic endpoint scoring may read only terminal, hash-validated completed
shards. The exact sources are the complete 1,536-row SA3 run
`benchmark-core-v2-20260720t174500z` and the now-complete 1,536-row ACE run
`benchmark-core-v2-ace-20260721t091500z`. Active, partial, failed, replaced,
or uncommitted rows are ineligible. The ACE completion receipt is
`provenance/core/ace_core_completion_v2.json`, SHA-256
`813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0`.

The authorized implementation is `configs/automatic_scoring_v2.json`,
SHA-256
`1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd`.
It recomputes only the frozen v2 vocal/instrumental, tempo, and integrity
instruments. Structure/repetition remains exploratory and receives no binary
success endpoint. Tables must report per-axis/per-backbone automatic
prevalence with prompt-cluster intervals. The fresh-output evaluator-audit
table may report operationalization agreement or discordance only; until the
gated PI packet supplies pooled labels, it makes no accuracy, human-gold, or
failed-slice claim. Stable Audio Open 1.0 remains an explicit missing primary
row, not an imputed result.

GPU evaluators run only on live-idle, independently locked an12 physical GPUs
4–7, TP1 and one evaluator replica per card, with at most four replicas. Each
worker requires no compute neighbor, at least 60 GB free before load and 20 GB
free after load. A busy or changed device remains queued. No process is
signaled, killed, moved, reconfigured, or preempted, and a scorer never shares
a live generation or state-worker allocation.

`AUTOMATIC_ENDPOINT_SCORING_AUTHORIZED = YES`

`AUTOMATIC_ENDPOINT_SCORING_RUN_ID = automatic-scoring-v2-001`

`AUTOMATIC_ENDPOINT_SCORING_CONFIG_SHA256 = 1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd`

`AUDIO_GENERATION_AUTHORIZED_BY_SCORING = NO`

`AUTOMATIC_SCORING_COMPLETED_SHARDS_ONLY = YES`

`AUTOMATIC_SCORING_HUMAN_GOLD_CLAIMS = NO`

`QUEUE_DO_NOT_PREEMPT = YES`

## D-0030 — SA3 initial formal state-capture queue opened

- Date: 2026-07-22
- Status: accepted initial-tier state execution opening
- Authority: PI scoring-and-state-lanes authorization and D-0020 technical
  preflight PASS
- Supersedes: D-0028 only for the SA3 initial formal Section-11 queue

D-0020 satisfies the technical precondition, but is not itself a formal
eligibility result. The exact formal lane config is
`configs/sa3_state_capture_v2.json`, SHA-256
`4bb6d6480dd5167da97e4907193204ac319df090668f976734de7d37da87d02e`.
Its immutable source is the completed SA3 core queue. The initial tier has
exactly 36 selected BASE prompts, roots 0–3, and checkpoints 25/50/75%:
144 prefix groups, 432 `(prompt, root, checkpoint)` units, and 1,296 mapped
action rows. Preview features come only from that unit's own root. Folds are
prompt-grouped, and restart outcomes retain the exact
`RESTART_POOL_SHARED_AT_PROMPT_LEVEL` label. No single-draw oracle or
outcome-selected mapping is authorized.

The prospective state cap is grounded only in D-0020's measured
`249.481707109 s` one-group upper-bound residency and a conservative factor
of two. It is exactly `71,850.731647392 GPU-s` (`19.95853656872 GPU-h`) for
144 groups. Reservations are `232.6879820972681 s` per prefix group and
`88.7584773735773 s` per resume unit. This is a hard engineering ceiling, not
a runtime expectation or p95 claim. Calls are durably claimed with no
automatic retry. Only disjoint live-idle an12 GPUs 4–7 may be used, TP1/R1,
up to four concurrent workers; queueing takes precedence over preemption.

The supplemental roots 4–7 tier remains locked. It can open only after the
frozen initial four-way gate returns `INCONCLUSIVE_UNDERPOWERED` and a new
decision authorizes the sole doubling. This decision does not declare any
eligibility outcome.

`SA3_STATE_CAPTURE_INITIAL_AUTHORIZED = YES`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = YES`

`SA3_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`NO_AUTOMATIC_RETRY = YES`

`SA3_STATE_CAPTURE_CONFIG_SHA256 = 4bb6d6480dd5167da97e4907193204ac319df090668f976734de7d37da87d02e`

`SA3_STATE_CAPTURE_INITIAL_GPU_SECONDS_CAP = 71850.731647392`

`SA3_D0020_RESULT_SHA256 = 10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117`

`STATE_CONFIG = configs/sa3_state_capture_v2.json`

`STATE_CONFIG_SHA256 = 4bb6d6480dd5167da97e4907193204ac319df090668f976734de7d37da87d02e`

`INITIAL_STATE_GPU_SECONDS_CAP = 71850.731647392`

`D0020_RESULT_SHA256 = 10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117`

`STATE_PLACEMENT = an12:[4,5,6,7]`

`STATE_MAX_PARALLEL_REPLICAS = 4`

## D-0031 — Sole ACE-Step v1 state-capability preflight opened

- Date: 2026-07-22
- Status: accepted one-attempt technical preflight opening
- Authority: PI scoring-and-state-lanes authorization
- Supersedes: D-0028 only for this non-benchmark ACE technical preflight

The exact one-attempt config is `configs/ace_state_preflight_v2.json`,
SHA-256
`7996daa1803a71aeae2f9ac8441b73d8cc487eecd1343eb1ab4075e6cc563ed6`.
Append-only seed `S-0010 = 73193010` is registered solely for this engineering
reference/export/resume equivalence run. A complete attempt makes exactly
four model calls and retains four clips: one uninterrupted reference exporting
the nearest attainable 25/50/75% states at transitions 9/15/20 (cumulative
transformer NFE 11/23/33), then three reload-and-continue calls in three
separate child processes. The absolute envelope remains no more than eight
generations, one GPU, 30 seconds per clip, 600 GPU-seconds, and zero retries.

The comparison requires identical channels, frames, and sample rate, maximum
absolute decoded error at most `1e-5`, and SNR at least 80 dB. The pinned ACE
upstream exposes no native checkpoint/resume API, so the implementation uses
a source-hash-guarded interposition restricted to the frozen Euler/CFG path;
that limitation is recorded as technical provenance. It authorizes no
benchmark endpoint, human-packet item, or formal Section-11 row.

The attempt prioritizes an12 and selects one live-safe physical GPU from 4–7,
TP1/R1, under the shared no-preempt lock and pre/post-load headroom gates. A
PASS permits a later exact ACE initial-queue opening. Any new failure sets
`ACE_STATE_CAPABILITY = NOT_IDENTIFIABLE` terminally and permits no second
attempt; ordinary ACE core evidence remains valid either way.

`ACE_STATE_PREFLIGHT_V2_AUTHORIZED = YES`

`ACE_STATE_PREFLIGHT_V2_ATTEMPTS = 1`

`ACE_STATE_PREFLIGHT_V2_MAX_GENERATIONS = 8`

`ACE_STATE_PREFLIGHT_V2_MAX_GPU_SECONDS = 600`

`ACE_STATE_PREFLIGHT_V2_RETRIES = 0`

`ACE_STATE_PREFLIGHT_V2_RUN_ID = ace-state-preflight-v2-001`

`ACE_STATE_PREFLIGHT_V2_CONFIG_SHA256 = 7996daa1803a71aeae2f9ac8441b73d8cc487eecd1343eb1ab4075e6cc563ed6`

`ACE_STATE_CAPABILITY = PREFLIGHT_AUTHORIZED_NOT_YET_EXECUTED`

## D-0032 — Human-audit packet autoassembly armed behind both gates

- Date: 2026-07-22
- Status: accepted fail-closed automation arm
- Authority: PI scoring-and-state-lanes authorization
- Supersedes: D-0028 only for the automatic gate watcher; it does not waive
  timing-pilot ingestion or scored-strata completeness

The exact arm config is `configs/human_packet_autoassembly_v2.json`, SHA-256
`519f71753ee8340320a9a32e0c8dd72a577e8e48aa57154f20379382520dd4db`.
It watches only the already-offered blinded timing-pilot receipt and the exact
automatic-scoring candidate/status paths. Assembly occurs once, no-clobber,
only after the pilot receipt validates and scored candidates satisfy every
frozen v2 sampling stratum for all three primary human-audited backbones.
Until then it emits a heartbeat and performs no assembly.

Stable Audio Open 1.0 is still `BLOCKED_ON_LICENSE`; missing SAO strata cannot
be silently filled from SA3 or ACE. Thus a valid timing response alone cannot
produce a two-backbone packet. A future access decision or a prospective
sampling amendment is required before all-three-backbone strata can be
complete. Model-level voice fields retain the targeted-stress-audit wording,
and automatic scoring does not become human gold through transport into the
candidate index.

The packet builder now enforces D-0026's inclusive per-backbone 30-second
duration tolerance (`abs(duration - 30) <= 0.25 s`), so native ACE clips at
`29.9073125 s` remain valid without loosening SA3 in practice.

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED`

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY_CONFIG_SHA256 = 519f71753ee8340320a9a32e0c8dd72a577e8e48aa57154f20379382520dd4db`

`HUMAN_AUDIT_PACKET_ASSEMBLY = ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA`

`HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO`

## D-0033 — ACE-Step v1 state preflight PASS and initial formal queue opened

- Date: 2026-07-22
- Status: accepted terminal capability result and initial-tier execution opening
- Authority: PI scoring-and-state-lanes authorization, conditional PASS branch
- Supersedes: D-0031 for ACE state-capability status and attempt availability;
  D-0028 only for the ACE initial formal Section-11 queue

The sole authorized ACE-Step v1 state preflight ran once on `an12`, physical
GPU 4, TP1/R1, from clean Git
`b734a9e1bfdb8db65310f31ed37056636a519db0`, equal to `origin/main`. It
completed exactly four model calls and retained four clips: one uninterrupted
reference with exports at transitions 9/15/20 and one separately loaded child
process for each 25/50/75% resume. No retry occurred or remains available.

The terminal status is `PASS`. All four outputs are finite, non-silent,
48-kHz stereo and `29.9073125 s`, within the inclusive 0.25-second ACE rule.
Each resumed waveform has the reference's exact shape and sample rate,
maximum absolute error `0.0`, and infinite SNR, satisfying the frozen
`1e-5` / 80-dB equivalence rule. Actual NFE was 45 for the reference and
34/22/12 for the three resumed suffixes. This is a technical state-capability
result, not an automatic endpoint or human-gold claim.

Measured cumulative synchronized GPU time was
`309.50720739737153 s`; exclusive one-GPU occupancy was
`364.1350744701922 s`; peak allocated/reserved VRAM was
`8,371,733,504 / 10,085,203,968 B`. The initial formal ACE ceiling uses the
same prospective conservative rule as the SA3 lane: two times the measured
one-group exclusive occupancy times 144 groups, exactly
`104,870.9014474153536 GPU-s` (`29.130805957615376 GPU-h`). It is a hard
engineering ceiling, not an expected cost or p95 claim.

The exact initial-lane implementation is
`configs/ace_state_capture_v2.json`, SHA-256
`7797efee802aa9380c3953cfd89d05b852692f284d129c07745e46e584dcf8a3`.
It must derive a fresh ACE queue from the complete ACE ordinary-core source,
not reuse the earlier SA3-derived placeholder: 144 prefix groups, 432
`(prompt, root, checkpoint)` units, and 1,296 replicated action mappings with
same-root previews, prompt-grouped folds, and prompt-level restart pools.
Supplemental roots remain locked, and no automatic retry or single-draw
oracle is authorized.

The terminal/result/ledger SHA-256s are respectively
`69afb2851dbe5b90e6c4c71cc5c4581740bce4b88a4aaab42a410c69c7f8bb7d`,
`700ec8e32bd200d91f1345fb72d76b69c74678849152367f7f1661e2236398b9`,
and `adbaef777571a2a708f0d2667c332ae58c7a7ade91c771bc7677a88cff957441`.
The immutable terminal is
`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/ace-state-preflight-v2/ace-state-preflight-v2-one-attempt.terminal.json`.

`ACE_STATE_CAPABILITY = PASS`

`ACE_STATE_CAPTURE_INITIAL_AUTHORIZED = YES`

`ACE_STATE_CAPTURE_SUPPLEMENTAL_AUTHORIZED = NO`

`NO_AUTOMATIC_RETRY = YES`

`ACE_STATE_CAPTURE_CONFIG = configs/ace_state_capture_v2.json`

`ACE_STATE_CAPTURE_CONFIG_SHA256 = 7797efee802aa9380c3953cfd89d05b852692f284d129c07745e46e584dcf8a3`

`ACE_STATE_PREFLIGHT_TERMINAL = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/ace-state-preflight-v2/ace-state-preflight-v2-one-attempt.terminal.json`

`ACE_STATE_PREFLIGHT_TERMINAL_SHA256 = 69afb2851dbe5b90e6c4c71cc5c4581740bce4b88a4aaab42a410c69c7f8bb7d`

`ACE_STATE_PREFLIGHT_RESULT_SHA256 = 700ec8e32bd200d91f1345fb72d76b69c74678849152367f7f1661e2236398b9`

`ACE_STATE_PREFLIGHT_CONFIG_SHA256 = 7996daa1803a71aeae2f9ac8441b73d8cc487eecd1343eb1ab4075e6cc563ed6`

`ACE_STATE_CAPTURE_CORE_QUEUE_SHA256 = db4ce65dabee9219e30a5c22c0eb56ed7b0a6f9e3ebaf98302f725cb8e8fd37f`

`ACE_STATE_CAPTURE_CORE_LEDGER_SHA256 = 7f63aac18b4c503b4f17a6c03d0239715229a9d7751cb6db1531e2bd592b76d9`

`ACE_STATE_CAPTURE_INITIAL_GPU_SECONDS_CAP = 104870.9014474153536`

## D-0034 — Stage-1 outcome-gate CPU lane authorized fail-closed

- Date: 2026-07-22
- Status: authorized but blocked on two absent numerical policy values
- Authority: PI Stage-1-gates-first authorization

The Stage-1 implementation and its exact scored-outcome, statistics, and state
queue bindings are fixed by `configs/stage1_outcome_gates_v2.json`, SHA-256
`bc54978d8257e14dd373c34c2401f99beb20be78fc4a7a97f762dad67a1b82bd`.
The repository's frozen v2 record does not state numerical minima for either
`baseline_failure_rate` or `mixed_outcome_prompt_share`. Neither value may be
inferred from data, examples, the eligibility deviation-share threshold, or a
different project. Therefore no scored row was read, no cell verdict was
computed, and no cancellation event was created. A later append-only PI
decision must state both minima before this CPU lane can run.

`STAGE1_OUTCOME_GATE_CPU_AUTHORIZED = YES`

`STAGE1_OUTCOME_GATE_STATUS = BLOCKED_MISSING_FROZEN_THRESHOLDS`

`STAGE1_BASELINE_FAILURE_RATE_MINIMUM = NOT_SPECIFIED`

`STAGE1_MIXED_OUTCOME_PROMPT_SHARE_MINIMUM = NOT_SPECIFIED`

`STAGE1_VERDICTS_COMPUTED = NO`

`STAGE1_CANCELLATION_LEDGER_CREATED = NO`

`STAGE1_OUTCOME_GATE_CONFIG = configs/stage1_outcome_gates_v2.json`

`STAGE1_OUTCOME_GATE_CONFIG_SHA256 = bc54978d8257e14dd373c34c2401f99beb20be78fc4a7a97f762dad67a1b82bd`

## D-0035 — SA3 survivor-only restricted rerun prospectively opened

- Date: 2026-07-22
- Status: accepted conditional execution opening
- Authority: PI scoped-state authorization

This opening binds the sole repaired SA3 rerun to the identical materialized
queue and the original failed request. Execution is impossible until D-0034
has produced complete immutable Stage-1 result and cancellation artifacts.
At launch their bytes are verified and recorded. Only survivor axes may be
materialized; STOP units prohibit both execution and scoring. The original
failed unit is replayed verbatim because failure occurred before resume. One
root validates first. A new failure class permanently ends the lane, and no
third repair or automatic retry is authorized.

`SA3_STATE_RESTRICTED_RERUN_AUTHORIZED = YES`

`SURVIVORS_ONLY = YES`

`ONE_ROOT_VALIDATION_REQUIRED = YES`

`NO_THIRD_REPAIR = YES`

`RERUN_CONFIG = configs/sa3_state_restricted_rerun_v2.json`

`RERUN_CONFIG_SHA256 = 67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`

`RERUN_RUN_ID = sa3-state-v2-restricted-rerun-001`

`SOURCE_STATE_MANIFEST_SHA256 = 5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3`

`ORIGINAL_FAILED_REQUEST_SHA256 = 8d21cb321f6cc8be963fa8cf387303a508617ba3dec84475ee09d54f540ec27e`

`ORIGINAL_FAILURE_LEDGER_SHA256 = 68ddc4f56dbbb9518c5f8ba8a91fa4d757acb8d18c80da31be1f99d60f3011a5`

`METADATA_FILENAME_FIX_COMMIT = 61ddecf457ad5902fd9bf529a121411dd41ac043`

`STAGE1_RESULT_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/stage1-outcome-gates.json`

`STAGE1_CANCELLATION_SUMMARY_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/cancellations/summary.json`

`STAGE1_RUNTIME_SHA256_BINDING = VERIFIED_AND_RECORDED_AT_LAUNCH`

## D-0036 — ACE formal initial survivor queue prospectively opened

- Date: 2026-07-22
- Status: accepted conditional initial-tier execution opening
- Authority: PI scoped-state authorization

The ACE formal lane is limited to Stage-1 survivor axes from its fresh frozen
queue. Complete Stage-1 result and cancellation artifacts are mandatory at
launch and their live hashes are recorded then. STOP units may be neither
executed nor scored. Supplemental work is locked. Up to four independent TP1
replicas may use live-idle an12 GPUs 4–7 under the shared non-preemption locks;
the prospective hard ceiling is the D-0033 measured-cap calculation. No
automatic retry is authorized.

`ACE_STATE_FORMAL_INITIAL_AUTHORIZED = YES`

`ACE_STATE_FORMAL_SURVIVORS_ONLY = YES`

`ACE_STATE_FORMAL_STOP_UNITS_PROHIBITED = EXECUTE,SCORE`

`ACE_STATE_FORMAL_CONFIG = configs/ace_state_formal_v2.json`

`ACE_STATE_FORMAL_CONFIG_SHA256 = 4cd688c71cff19104d1932386b42c4f1090cce5c5cd20dc61f7881e26a6fba89`

`STAGE1_RESULT_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/stage1-outcome-gates.json`

`STAGE1_CANCELLATION_SUMMARY_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/stage1-outcome-gates-v2/stage1-outcome-gates-v2-001/cancellations/summary.json`

`STAGE1_RUNTIME_SHA256_BINDING = VERIFIED_AND_RECORDED_AT_LAUNCH`

`ACE_STATE_SUPPLEMENTAL_AUTHORIZED = NO`

`NO_AUTOMATIC_RETRY = YES`

`ACE_STATE_FORMAL_PLACEMENT = an12:[4,5,6,7]`

`ACE_STATE_FORMAL_MAX_PARALLEL_REPLICAS = 4`

`ACE_STATE_FORMAL_INITIAL_GPU_SECONDS_CAP = 104870.90144741535`

`ACE_STATE_FORMAL_FRESH_QUEUE_MANIFEST_SHA256 = 62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a`

`ACE_STATE_FORMAL_INITIAL_UNITS_SHA256 = 9218cd0ce81bda171230a4bed40c75c67ade08cd359a4da4b569a8365155923f`

## D-0037 — Stable Audio Open live acquisition and engineering smoke opened

- Date: 2026-07-22
- Status: accepted live acquisition and exact-three-call smoke opening
- Authority: PI SAO-live authorization

The accepted read-only Hugging Face credential may exist only in process
memory during acquisition. It must never enter stdout, stderr, logs, ledgers,
manifests, commits, or retained environment state. Acquisition records the
resolved revision, provider provenance, license identifier, and SHA-256 of
every regular snapshot file. Only after that receipt validates may exactly
three non-benchmark 30-second calls run on one verified-idle an12 GPU from
4–7. The pair is compared by decoded-waveform hash; the third call calibrates
resident cost. Any model-call failure is terminal with no retry.

This decision does not by itself launch the 1,536-row core run: a separate
exact run-ID decision follows only after a PASS smoke and sealed measured
receipt. SAO state capability remains untested and eligibility scope remains
SA3 plus ACE only.

`SAO_ACQUISITION_AUTHORIZED = YES`

`SAO_MINI_SMOKE_EXACT_CALLS = 3`

`SAO_CORE_EXACT_ROWS = 1536`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

`SAO_LIVE_CONFIG_SHA256 = 850c27343ff06045a6b19e84f93c10ddc7e0afc9d6d0466497ada532d4452aed`

## D-0038 — SAO-aware human-packet watcher armed behind both gates

- Date: 2026-07-22
- Status: accepted fail-closed watcher opening
- Authority: PI packet-watcher authorization

The watcher is bound to the exact final three-backbone scoring root. Before
assembly it must prove complete per-backbone packet counts and actual
cross-instrument disagreement coverage: both voice directions contain the
frozen Demucs/PANNs disagreement cells, and the tempo disagreement-or-invalid
stratum includes at least one actual Beat This!/librosa disagreement. It may
assemble once only when the timing-pilot receipt is ingested and SAO scoring
provides every required stratum. Otherwise it emits heartbeat state only.

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED`

`HUMAN_AUDIT_PACKET_ASSEMBLY = ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA`

`HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO`

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY_CONFIG_SHA256 = 68b74081056136ef2b72d90cdd7466b5ae4aafc3da2f4ffac6942d16526ff144`

## D-0039 — Stable Audio Open retained-stage acquisition recovery authorized

- Date: 2026-07-22
- Status: accepted one-time offline artifact-finalization opening
- Authority: PI SAO-live authorization, implemented under D-0037

The exact Hugging Face revision
`f21265c1e2710b3bd2386596943f0007f55f802e` downloaded completely before
the D-0037 acquisition stopped on a local layout assumption: the official
snapshot legitimately contains both root `model.safetensors` and
`model.ckpt`. The immutable source failure records zero model calls and zero
generated audio. This one-time recovery may validate and atomically rename
only that retained stage, hash every regular snapshot file, and seal a new
receipt in a distinct run. It may not contact a provider, inherit a provider
token, redownload or delete files, use a GPU, construct a model, or generate
audio. The original failed run remains intact.

For inference, the receipt-bound root `model.safetensors` is selected
deterministically; `model.ckpt` remains retained and hashed. The bundled
tokenizer and text encoder must likewise be loaded only from receipt-bound
local files with provider networking disabled. This correction changes no
model identity, generation configuration, state scope, or call budget.

`SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES`

`SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID = sao-acquisition-v2-001`

`SAO_ACQUISITION_RECOVERY_RUN_ID = sao-acquisition-recovery-v2-001`

`SAO_ACQUISITION_RECOVERY_REVISION = f21265c1e2710b3bd2386596943f0007f55f802e`

`SAO_ACQUISITION_RECOVERY_FAILURE_TERMINAL_SHA256 = d1b7f3c35ab211372910db3ba9a0a73abcf2b24d49745f3d0717cdb77096db82`

`SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO`

`SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO`

`SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0`

## D-0040 — Decision-grade automatic-instrument tables opened

- Date: 2026-07-22
- Status: accepted CPU execution opening
- Authority: PI decision-grade-table authorization

The automatic-only decision-grade builder may summarize the already complete
SA3 and ACE scored rows now, then emit separate immutable extensions as
completed SAO shards are scored. This CPU lane is not state execution and does
not bypass the blocked Stage-1 outcome gate. Every row remains watermarked
`AUTOMATIC-INSTRUMENT OUTCOMES`; no human-gold or accuracy claim is permitted.
Outputs include per-axis and per-backbone prevalence, tempo results at both the
5% primary and 10% sensitivity bands with separate window drift, defect-
specific integrity rates, and instrument-disagreement summaries.

The initial source rows, scoring status, and completed snapshot SHA-256s are
respectively
`e2961646ad811cab4c917ec9056f2127ff1454ddeaf7dd4b668d3617ba368f63`,
`9fc9b01e19af41bb588ef4feb3a88da1d3de9540a087e730a17ce3d65b3789b6`,
and `150ddcf36b2d6aab1e1e232a4af43c650fdd2a8b137e3b9f236eec20658bfdd5`.
The frozen scoring and statistics config SHA-256s are
`1e03782323d469fe8bcae09aabd9d86aecf740050d54cbe95b26e14d39d1cbdd`
and `d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d`.

`DECISION_GRADE_AUTOMATIC_TABLES_AUTHORIZED = YES`

`DECISION_GRADE_INITIAL_SOURCE_SCOPE = SA3_PLUS_ACE_COMPLETE`

`DECISION_GRADE_SAO_EXTENSION = COMPLETED_SCORED_SHARDS_ONLY`

`DECISION_GRADE_HUMAN_GOLD_CLAIMS = NO`

`DECISION_GRADE_AUDIO_GENERATION_AUTHORIZED = NO`

`DECISION_GRADE_INITIAL_RUN_ID = decision-grade-v2-001`

## D-0041 — SAO filesystem-compatible retained-stage recovery authorized

- Date: 2026-07-22
- Status: accepted single final offline recovery opening
- Authority: PI SAO-live authorization, with D-0039 filesystem-failure evidence

D-0039 stopped with zero model calls and zero generated audio because this
Lustre mount rejects `renameat2(RENAME_NOREPLACE)`. Its exact 944-byte failure
log has SHA-256
`02a9d101c1c20cc9b73fb7e381f1c03cd6929c5eb4105203faf290f211dd1477`.
The failed recovery run is preserved with exactly two regular files: its
access receipt and snapshot manifest have SHA-256s
`1fd37fc4e59ba8439f1dcc6c17b9b04a54f9652474e5fd72e8748bfb71188eb5`
and `e3756f588cf5db90a122e597f3582f2a3c4ee66316b239383c78927402da0b39`;
their canonical two-file tree SHA-256 is
`354b42d6e427a3ab68558a427754dcd949a734d9bddd8cdb293a48d16fab3b8c`.
That receipt is non-operative because its named final snapshot was never
created.

The retained stage independently rehashes to 25 regular files totaling
15,680,736,700 bytes with tree SHA-256
`282bd8c8601e6143939fc54286df40f9208dd38d89c11271089bab04143361a3`.
This final attempt may, under the existing exclusive acquisition lock, create
the exact revision directory and hard-link each already-validated regular file
without overwriting any path. The retained stage and both earlier failed runs
remain present. Hard links are byte-identical aliases, not an independent
archive; publication is therefore explicitly non-atomic and becomes usable
only after complete receipt-wide rehash and a terminal PASS. Any failure is
terminal with all partial evidence retained and no further recovery attempt.
No provider, token, GPU, model construction, audio generation, deletion, or
redownload is authorized.

`SAO_ACQUISITION_RECOVERY_AUTHORIZED = YES`

`SAO_ACQUISITION_RECOVERY_SOURCE_RUN_ID = sao-acquisition-v2-001`

`SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_RUN_ID = sao-acquisition-recovery-v2-001`

`SAO_ACQUISITION_RECOVERY_RUN_ID = sao-acquisition-recovery-v2-002`

`SAO_ACQUISITION_RECOVERY_REVISION = f21265c1e2710b3bd2386596943f0007f55f802e`

`SAO_ACQUISITION_RECOVERY_FAILED_ACCESS_RECEIPT_SHA256 = 1fd37fc4e59ba8439f1dcc6c17b9b04a54f9652474e5fd72e8748bfb71188eb5`

`SAO_ACQUISITION_RECOVERY_FAILED_SNAPSHOT_MANIFEST_SHA256 = e3756f588cf5db90a122e597f3582f2a3c4ee66316b239383c78927402da0b39`

`SAO_ACQUISITION_RECOVERY_FAILED_RECOVERY_TREE_SHA256 = 354b42d6e427a3ab68558a427754dcd949a734d9bddd8cdb293a48d16fab3b8c`

`SAO_ACQUISITION_RECOVERY_FAILURE_LOG_SHA256 = 02a9d101c1c20cc9b73fb7e381f1c03cd6929c5eb4105203faf290f211dd1477`

`SAO_ACQUISITION_RECOVERY_NETWORK_ACCESS = NO`

`SAO_ACQUISITION_RECOVERY_TOKEN_ACCESS = NO`

`SAO_ACQUISITION_RECOVERY_MODEL_CALLS = 0`

`SAO_ACQUISITION_RECOVERY_MATERIALIZATION = HARDLINK_CLONE_RETAINED_STAGE`

`SAO_RECOVERY_ATTEMPT2_GPU_COUNT = 0`

`SAO_RECOVERY_ATTEMPT2_GENERATED_AUDIO = 0`

`SAO_RECOVERY_ATTEMPT2_ATOMIC_PUBLICATION = NO`

`SAO_RECOVERY_ATTEMPT2_RECEIPT_GATED_PUBLICATION = YES`

`SAO_RECOVERY_ATTEMPT2_FURTHER_ATTEMPTS = NO`

## D-0042 — SAO mini-smoke zero-call pre-model replacement authorized

- Date: 2026-07-22
- Status: accepted single pre-model replacement opening
- Authority: PI SAO-live authorization under D-0037, with immutable zero-call failure evidence

The D-0037 one-shot claim was durably consumed, but its runner stopped before
creating a run directory, loading the model, entering a model call, or
generating audio. The exact retained traceback shows that the fixed run
directory's immediate parent did not exist when `Path.mkdir(parents=False)`
ran. The original claim and failure log remain immutable. This is therefore a
single clerical pre-model replacement, not a retry of a model call and not an
increase to the scientific call budget.

The replacement must use the distinct fixed run and O_EXCL claim below, the
identical three prompts, seed schedule, durations, snapshot, receipt, and live
configuration. Its runner creates and fsyncs only the fixed parent before GPU
lease, proves all deterministic inputs and token absence before the lease,
revalidates their exact bytes after the final idle-GPU probe, and atomically
claims immediately before model execution. Any failure after this replacement
claim is terminal. No third claim, retry, or further replacement is
authorized.

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_AUTHORIZED = YES`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUN_ID = sao-mini-smoke-v2-001`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_RUN_ID = sao-mini-smoke-v2-002`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sao-live-v2/sao-mini-smoke-v2-002.pre-model-replacement.claim.json`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIM_SHA256 = e57df24fdec18681764ca11c2585d1727f0fe677494a36e6eb8e4b43f55ad995`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIM_IDENTITY_SHA256 = f9342534decebc58a43e6f70b87d070e73986fbf7820cd7491c3bfb34ea19d6a`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUNTIME_AUTHORIZATION_SHA256 = b6a0be60366701465482c9a0991cd5008c4f9935806466d657885936068fb09e`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_GIT_COMMIT = 17696ed77cb118c01eb51867fc483415788c87a0`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_FAILURE_LOG_SHA256 = 73ecd7e0f5c59b75787d5a55f1016cf85461f862e95ee31c6bc8a87ea77593ba`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_FAILURE_PHASE = PRE_MODEL_RUN_DIRECTORY_CREATION`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_CALLS = 0`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_MODEL_LOADS = 0`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CUMULATIVE_AUDIO_OUTPUTS = 0`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_EXACT_CALLS = 3`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_EXACT_CLAIMS = 1`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_CLIP_SECONDS = 30`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_MAX_GPUS = 1`

`SAO_MINI_SMOKE_FURTHER_REPLACEMENT_AUTHORIZED = NO`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_RUNNER_SHA256 = 91a476fb8f1050c415c147907226c1a99167acb9ba52fa3a3103f404c6603883`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_IMPLEMENTATION_SHA256 = 220d45c4fcd1381946e6f63af9e63abbdefdff3688e7f3e1362b291dcfcc782d`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_CLAIMS_SOURCE_SHA256 = 8e2aa6bd46c3532c09f0045605f98d4a321a5e8c8a0fd953e561521851a7495f`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ORIGINAL_ADAPTER_SHA256 = b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_RUNNER_SHA256 = 116f30e60d8b2878142dbbf887dddccb5c11575470ddc7e35d9e84f50358e44f`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_IMPLEMENTATION_SHA256 = d6d4091a7d14986f8e215c0acdcabfb8df6a9ff064fc6d67146107ccb18e9644`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_CLAIMS_SHA256 = aa3397f702a17a33f0e4bbe8bd5f002f2e90fa7e37528e001bb5b071791495b9`

`SAO_MINI_SMOKE_PRE_MODEL_REPLACEMENT_ADAPTER_SHA256 = b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef`

## D-0043 — SAO live mini-smoke terminal engineering failure

- Date: 2026-07-22
- Status: terminal; no retry, core queue, or scoring queue
- Authority: D-0037 and D-0042 exact failure rules

The sole D-0042 replacement claim was consumed on clean pushed commit
`0a5dac420b8036984973d0f4a596999c37e955ac` after an offline preflight and
an idle-device check on an12 physical GPU 4. Call 0 entered the adapter's
model-call path but failed before a model load completed: importing
PyWavelets 1.4.1 against NumPy 2.2.6 raised a binary-ABI `ValueError` while
the Stable Audio Tools model factory was loading. The retained ledger has one
`MODEL_CALL_FAILED` row. No WAV, adjacent provenance, NFE, or measured cost
row exists; no benchmark endpoint or human label was consulted.

D-0037 makes any model-call failure terminal, and D-0042 expressly authorizes
no further replacement. The environment is therefore not repaired for
another attempt. Stable Audio Open 1.0 receives no 1,536-row core queue and no
automatic-scoring continuation. Its state capability remains `NOT_ATTEMPTED`
and eligibility remains SA3 plus ACE only. The terminal Phase-B receipt is
`provenance/b2/sao_live_terminal_v2.json`, SHA-256
`c50a9108b910354d7f74d78fdce02587e7d48cd52f16b32e68df6f3b2fb3a153`.

`SAO_MINI_SMOKE_STATUS = FAILED_STOPPED_NO_RETRY`

`SAO_MINI_SMOKE_MODEL_CALL_ATTEMPTS = 1`

`SAO_MINI_SMOKE_COMPLETED_MODEL_LOADS = 0`

`SAO_MINI_SMOKE_GENERATED_AUDIO_OUTPUTS = 0`

`SAO_MINI_SMOKE_FAILURE_CLASS = PYWAVELETS_NUMPY_BINARY_ABI_INCOMPATIBILITY`

`SAO_MINI_SMOKE_REPLACEMENT_CLAIM_SHA256 = add88f095bb969c736a28141b0ed89ce6a704e732daeac4b7d2f87536f086184`

`SAO_MINI_SMOKE_MANIFEST_SHA256 = d729c2296d2d123d0eae69387ea9529d2e6b94816cb25f36de7f189f370c8ddf`

`SAO_MINI_SMOKE_LEDGER_SHA256 = bc51c5b926c01eb8afbf774e3763304b6ddb0bbf74890ea8a3eb0dac13bd2813`

`SAO_MINI_SMOKE_TERMINAL_SHA256 = 3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097`

`SAO_MINI_SMOKE_LAUNCH_LOG_SHA256 = eff22da9974237e3fb5fe5f0876f33a41127d97f21e53807dad5e6612075fdbc`

`SAO_LIVE_TERMINAL_RECEIPT = provenance/b2/sao_live_terminal_v2.json`

`SAO_LIVE_TERMINAL_RECEIPT_SHA256 = c50a9108b910354d7f74d78fdce02587e7d48cd52f16b32e68df6f3b2fb3a153`

`SAO_CORE_GENERATION_AUTHORIZED = NO`

`SAO_AUTOMATIC_SCORING_AUTHORIZED = NO`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

`SAO_FURTHER_MINI_SMOKE_ATTEMPTS = 0`

## D-0044 — Initial decision-grade automatic tables sealed

- Date: 2026-07-22
- Status: complete for verified SA3 plus ACE sources; SAO absent
- Authority: D-0040 CPU execution opening

The no-clobber D-0040 builder independently verified the frozen scoring rows,
status, source snapshot, and all complete confirmatory cells for SA3 and ACE.
The immutable legacy schema omitted an empty `incomplete_primary_backbones`
field; commit `0a5dac420b8036984973d0f4a596999c37e955ac` accepts that omission only when
the independently derived incomplete list is empty, at least one registered
primary backbone is genuinely missing, and overall status is exactly
`SCORING_COMPLETE_MISSING_PRIMARY_BACKBONE`. Partial or status-tampered inputs
remain rejected.

The resulting table is watermarked `AUTOMATIC-INSTRUMENT OUTCOMES` and passes
the prohibited-language validator. It contains 64 per-axis/backbone/condition
prevalence rows, including tempo 5% primary and 10% sensitivity metrics and
defect-specific integrity rates; eight first/second-window drift rows; 28
cross-instrument disagreement rows; and separately labeled negation-diagnostic
rows. It contains only SA3 and ACE. SAO is a missing registered backbone, not
a zero-rate observation, and D-0043 prevents an SAO extension this cycle.

`DECISION_GRADE_INITIAL_STATUS = DECISION_GRADE_AUTOMATIC_TABLES_PARTIAL_VERIFIED_SOURCES`

`DECISION_GRADE_INITIAL_OUTPUT = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/decision-grade-v2/decision-grade-v2-001/automatic-instrument-tables.json`

`DECISION_GRADE_INITIAL_OUTPUT_SHA256 = 33b15bf8811d1a2f85575605eef95e58e253f77767e79575dc5a6ec263473d94`

`DECISION_GRADE_INITIAL_PREVALENCE_ROWS = 64`

`DECISION_GRADE_INITIAL_TEMPO_DRIFT_ROWS = 8`

`DECISION_GRADE_INITIAL_DISAGREEMENT_ROWS = 28`

`DECISION_GRADE_INITIAL_INCLUDED_BACKBONES = stable-audio-3-medium-base,ACE-Step_v1`

`DECISION_GRADE_INITIAL_MISSING_BACKBONES = stable-audio-open-1.0`

`DECISION_GRADE_INITIAL_WATERMARK = AUTOMATIC-INSTRUMENT_OUTCOMES`

`DECISION_GRADE_HUMAN_GOLD_CLAIMS = NO`

## D-0045 — Repairable pre-scientific engineering failures

- Date: 2026-07-22
- Status: accepted governance correction; scientific design remains frozen
- Authority: PI consolidated goal `Unblock Stage-1, restore Stable Audio Open, and execute all eligible state lanes`

This decision supersedes every earlier blanket no-retry or permanent-stop rule
only for failures that occur before a valid scientific result and are caused by
dependency/ABI, import/package/path/cache/environment, checkpoint-sidecar,
serialization/manifest/provenance/adapter, launch/publication, or incorrect
engineering-validator bugs. D-0043's PyWavelets/NumPy ABI stop and the
engineering-stop clauses in the formal state lanes are therefore repairable
under new immutable run IDs and claims. Every prior failed attempt, claim,
ledger row, log, and artifact remains immutable and reportable.

This correction does not authorize changing prompts, seeds, weights, inference
budgets, evaluators, endpoints, thresholds, roots, checkpoints, actions,
features, folds, or mappings. It does not permit rerunning a valid experiment
because its result is weak, selecting favorable outputs, or silently replacing
a registered model. Within one claimed attempt, fail-closed execution remains
the rule; an engineering repair is a separately claimed attempt.

`ENGINEERING_FAILURES_REPAIRABLE = YES`

`WITHIN_ATTEMPT_RETRY = NO`

`ENGINEERING_REPAIR_REQUIRES_NEW_RUN_ID = YES`

`ENGINEERING_REPAIR_REQUIRES_NEW_CLAIM = YES`

`SCIENTIFIC_RERUNS_FOR_WEAK_RESULTS = NO`

`FROZEN_SCIENTIFIC_DESIGN_CHANGES_AUTHORIZED = NO`

`FAILED_ATTEMPTS_IMMUTABLE = YES`

`STOP_AXIS_UNITS_EXECUTABLE = NO`

`SAO_D0043_ENGINEERING_STOP_SUPERSEDED = YES`

`SAO_EXACT_MODEL_REVISION_RETAINED = f21265c1e2710b3bd2386596943f0007f55f802e`

`SAO_OFFLINE_TOKEN_ACCESS_AUTHORIZED = NO`

`HUMAN_PACKET_THREE_BACKBONE_REQUIREMENT_CHANGED = NO`

## D-0046 — Stage-1 bounded outcome-screen policy frozen before outcome read

- Date: 2026-07-22
- Status: accepted prospective policy amendment; CPU execution may follow only from this pushed freeze
- Authority: PI-supplied Rescue Experiment recovery values in the consolidated goal

The complete Stage-1 screen is frozen before the Stage-1 runner opens the bound
scored-row JSONL. These values were supplied by the PI as recovery of the prior
Rescue Experiment design and were not selected from current outcomes. A mixed
prompt is defined over the eight registered BASE roots exactly as stated below.
The failure-rate bounds are inclusive. Point estimates use all 12 registered
prompts; confidence intervals retain the frozen 10,000-replicate stratified
prompt-cluster and matched-root bootstrap. A STOP cell cancels every one of its
materialized initial state units and prohibits both execution and scoring.

The schema-v2 loader validates this policy and this append-only decision block,
including the exact config SHA-256, before it validates input bindings or reads
any scored outcome row. The historical blocked readiness record remains
unchanged; `provenance/stage1/stage1_outcome_gate_policy_freeze_v2.json`,
SHA-256 `830ce5b9fc7f4899138a588d2593ce296b477f54a5f8482e859bf4c9407a6301`,
records this superseding freeze.

`STAGE1_POLICY_STATUS = FROZEN_BEFORE_OUTCOME_READ`

`STAGE1_POLICY_CONFIG_PATH = configs/stage1_outcome_gates_v2.json`

`STAGE1_POLICY_CONFIG_SHA256 = 913a87d8286ba91094d2916b3ac9a601afe7e99fa3701803001b13557cca55eb`

`STAGE1_POLICY_SCHEMA_SHA256 = 4c49948dd9d9471f6d66f737ad5858d2662c7c37d16c5a501baf1905d889f0a6`

`STAGE1_BASELINE_FAILURE_RATE_MINIMUM = 0.10`

`STAGE1_BASELINE_FAILURE_RATE_MAXIMUM = 0.60`

`STAGE1_MIXED_OUTCOME_PROMPT_SHARE_MINIMUM = 0.20`

`STAGE1_MIXED_OUTCOME_PROMPT_DEFINITION = registered BASE prompt with at least one success and at least one failure among its eight registered roots`

`STAGE1_GATE_RULE = OUTCOME_SCREEN_PASS iff frozen minimum <= point baseline_failure_rate <= frozen maximum AND point mixed_outcome_prompt_share >= frozen minimum; STOP_AXIS_STAGE1 otherwise`

`STAGE1_OUTCOME_ROWS_READ_AT_FREEZE = NO`

`STAGE1_BOOTSTRAP_REPLICATES = 10000`

`STAGE1_CONFIDENCE_LEVEL = 0.95`

`STAGE1_STOP_UNIT_OPERATIONS = CANCELLED_EXECUTE_AND_SCORE`

## D-0047 — Stage-1 terminal verdicts sealed and survivor-only state lanes opened

- Date: 2026-07-22
- Status: accepted obtained automatic-instrument screen; two initial state cells opened
- Authority: D-0046 prospective policy and PI consolidated state-execution goal

The CPU-only runner executed from clean pushed
`5d686cb50eb310557d153fb14d8916d84a37c5c5` after D-0046 was frozen and
verified. Deep terminal validation independently recomputed all six cells,
their immutable input bindings, and the complete cancellation chain. The
machine result, cancellation summary, and execution receipt SHA-256s are
`5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`,
`7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`,
and `3778acf7f495d6036f7a8dabf075996a4d77f34269e264cf27e01be53a559d7c`.

ACE-Step v1 acoustic integrity and SA3 vocal/instrumental are the only
`OUTCOME_SCREEN_PASS` cells. Each exact survivor manifest contains 144
initial `(prompt, root, checkpoint)` units. The four STOP cells contribute
576 immutable cancellation events; every cancelled unit remains prohibited
from execution and scoring. Supplemental roots remain locked. The repository
terminal receipt is
`provenance/stage1/stage1_outcome_gates_terminal_v2.json`, SHA-256 `3710c09cc494ed1135bab08549fa82987e0cae6fb5299e8f40c71bbcaea78925`.

`STAGE1_OUTCOME_GATE_STATUS = STAGE1_OUTCOME_GATES_COMPLETE`

`STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`STAGE1_CANCELLATION_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`STAGE1_STOP_CELL_COUNT = 4`

`STAGE1_CANCELLED_UNIT_COUNT = 576`

`STAGE1_CANCELLED_UNIT_OPERATIONS = EXECUTE,SCORE`

`ACE_STATE_SURVIVOR_AXES = integrity`

`ACE_STATE_SURVIVOR_UNIT_COUNT = 144`

`ACE_STATE_SURVIVOR_UNITS_SHA256 = 6ae0d8e13f625bd935e9a285b98c79c24f2469b68706ad7e1ae2e576cb637a1f`

`SA3_STATE_SURVIVOR_AXES = vocal_instrumental`

`SA3_STATE_SURVIVOR_UNIT_COUNT = 144`

`SA3_STATE_SURVIVOR_UNITS_SHA256 = f5d31edfc177d013f240d83540b3d0274eea0a799f9b76fe0ff02395cff1c600`

`STATE_INITIAL_SURVIVOR_EXECUTION_AUTHORIZED = YES`

`STATE_SUPPLEMENTAL_ROOTS_AUTHORIZED = NO`

`STATE_ENGINEERING_GOVERNANCE = D-0045`

`STAGE1_HUMAN_GOLD_CLAIMS = NO`

## D-0048 — SA3 survivor-state engineering repair attempt opened

- Date: 2026-07-22
- Status: accepted exact zero-call repair opening
- Authority: D-0045, D-0047, and the PI consolidated execution goal

The prepared `sa3-state-v2-restricted-rerun-001` attempt was stopped by the
pre-call audit because its claim and run manifest omitted exact GPU placement.
Its immutable failure terminal, SHA-256
`edd63740e402f3d91224ffb16872ba62f6482c5bfe5a8220174ae2b0e35689ec`,
proves zero model calls, zero generated outputs, and no worker, heartbeat,
ledger, or audio artifact. This is a publication bug under D-0045, not a
scientific result.

One new sequential attempt is opened on exact an12 GPU 4 as TP1/R1. It must
replay the registered failed validation group `bbbc3309a9a4df4b56822163e6e8308c1d37cab7070c07c583fb4d541f2f7015`
first and may continue only after that validation passes. The Stage-1 result,
cancellation summary, source queue, prompts, roots, checkpoints, actions,
features, outcomes, budgets, and mappings remain byte/hash-bound. Supplemental
roots remain locked.

`SA3_STATE_ENGINEERING_REPAIR_AUTHORIZED = YES`

`SA3_STATE_ENGINEERING_REPAIR_RUN_ID = sa3-state-v2-restricted-rerun-002`

`SA3_STATE_ENGINEERING_REPAIR_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sa3-state-restricted-rerun-v2/sa3-state-v2-restricted-rerun-002.claim.json`

`SA3_STATE_ENGINEERING_REPAIR_PREDECESSOR_SHA256 = edd63740e402f3d91224ffb16872ba62f6482c5bfe5a8220174ae2b0e35689ec`

`SA3_STATE_ENGINEERING_REPAIR_PLACEMENT = an12:[4];TP1;R1`

`SA3_STATE_ENGINEERING_REPAIR_SURVIVOR_AXES = vocal_instrumental`

`SA3_STATE_ENGINEERING_REPAIR_CONFIG_SHA256 = 67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`

`SA3_STATE_ENGINEERING_REPAIR_QUEUE_MANIFEST_SHA256 = 5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3`

`SA3_STATE_ENGINEERING_REPAIR_STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`SA3_STATE_ENGINEERING_REPAIR_STAGE1_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`SA3_STATE_ENGINEERING_REPAIR_VALIDATION_GROUP_SHA256 = bbbc3309a9a4df4b56822163e6e8308c1d37cab7070c07c583fb4d541f2f7015`

`SA3_STATE_ENGINEERING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO`

`SA3_STATE_ENGINEERING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO`

## D-0049 — ACE survivor-state engineering repair attempt opened

- Date: 2026-07-22
- Status: accepted exact zero-call repair opening
- Authority: D-0045, D-0047, and the PI consolidated execution goal

The prepared `ace-state-formal-v2-001` attempt was stopped before assignment
or model loading. Its claim published GPUs 4–7 while the reserved placement
was GPUs 5–6, and its validator rejected the cluster's known `/HOME` versus
`/XYFS01/HOME` mount spelling. The retained failure terminal, SHA-256
`4e647f1c3154ea59ad2e2478ba846f5e0c4b41303e8318d52f01368cf2da34dd`,
proves zero model calls, zero outputs, and no worker, assignment, heartbeat,
ledger, or audio artifact. These are path/publication bugs under D-0045.

One new sequential attempt is opened on exact an12 GPUs 5 and 6 as two
independent TP1 replicas. Its survivor queue remains ACE integrity only. The
Stage-1 result, cancellation summary, source queue, prompts, roots,
checkpoints, actions, features, outcomes, budgets, folds, and mappings remain
byte/hash-bound; every STOP unit and every supplemental root remains locked.

`ACE_STATE_ENGINEERING_REPAIR_AUTHORIZED = YES`

`ACE_STATE_ENGINEERING_REPAIR_RUN_ID = ace-state-formal-v2-002`

`ACE_STATE_ENGINEERING_REPAIR_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/state-capture-v2/ace-state-formal-v2-002/control/formal-launch-claim.json`

`ACE_STATE_ENGINEERING_REPAIR_PREDECESSOR_SHA256 = 4e647f1c3154ea59ad2e2478ba846f5e0c4b41303e8318d52f01368cf2da34dd`

`ACE_STATE_ENGINEERING_REPAIR_PLACEMENT = an12:[5,6];TP1;R2`

`ACE_STATE_ENGINEERING_REPAIR_SURVIVOR_AXES = integrity`

`ACE_STATE_ENGINEERING_REPAIR_CONFIG_SHA256 = 4cd688c71cff19104d1932386b42c4f1090cce5c5cd20dc61f7881e26a6fba89`

`ACE_STATE_ENGINEERING_REPAIR_QUEUE_MANIFEST_SHA256 = 62c215ae38f0753198dcfcad36bebb8afeb669b11d170249c4be974ae7dd6e6a`

`ACE_STATE_ENGINEERING_REPAIR_STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`ACE_STATE_ENGINEERING_REPAIR_STAGE1_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`ACE_STATE_ENGINEERING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO`

`ACE_STATE_ENGINEERING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO`

## D-0050 — Stable Audio Open offline engineering repair smoke opened

- Date: 2026-07-22
- Status: accepted exact three-call engineering repair opening
- Authority: D-0045 and the PI consolidated SAO restoration goal

The official `stabilityai/stable-audio-open-1.0` snapshot remains fixed at
revision `f21265c1e2710b3bd2386596943f0007f55f802e`. A dedicated offline
Python 3.10 environment passed the complete CPU import and model-factory gate
without exposing CUDA, loading the checkpoint, making a generation call,
accessing the network, or reading any Hugging Face token. The environment
manifest is SHA-256
`45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f`;
the repository report and machine receipt are SHA-256
`f2142dc09dd75800684c2273f67301f6cc67dff12545d38ede730ed00a4dc932`
and `85fee0b21917aaad30006e3d71bc1ea29bacc8617e1e6251fb54b49527f6f1e6`.

The exact repair retains PyWavelets 1.4.1 and pins NumPy 1.26.4 for its
matching NumPy 1.x ABI. It also applies the hash-bound inference-only patch
that makes an absent `pytorch_lightning` training callback optional while
re-raising every other import error. Model math, weights, prompts, seeds,
sampler, steps, duration, acceptance rules, and benchmark endpoints are
unchanged.

One new sequential mini-smoke attempt is opened on exact an12 GPU 7. It is the
same registered three-call schedule: the fixed-seed 30-second decoded-waveform
reproducibility pair and one resident-cost call. The prior failed terminal and
the separate CPU factory failure remain immutable. A later pre-scientific
engineering bug remains repairable only through another new sequential run,
claim, and append-only opening; a valid end-to-end capability failure stops
the scientific lane for PI review.

`SAO_ENGINEERING_REPAIR_AUTHORIZED = YES`

`SAO_ENGINEERING_REPAIR_RUN_ID = sao-mini-smoke-v2-003`

`SAO_ENGINEERING_REPAIR_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sao-live-v2/sao-mini-smoke-v2-003.engineering-repair.claim.json`

`SAO_ENGINEERING_REPAIR_EXACT_CALLS = 3`

`SAO_ENGINEERING_REPAIR_MAX_CLIP_SECONDS = 30`

`SAO_ENGINEERING_REPAIR_MAX_GPUS = 1`

`SAO_ENGINEERING_REPAIR_MODEL_ID = stabilityai/stable-audio-open-1.0`

`SAO_ENGINEERING_REPAIR_OFFICIAL_REVISION = f21265c1e2710b3bd2386596943f0007f55f802e`

`SAO_ENGINEERING_REPAIR_ENVIRONMENT_MANIFEST_SHA256 = 45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f`

`SAO_ENGINEERING_REPAIR_PREVIOUS_TERMINAL_SHA256 = 3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097`

`SAO_ENGINEERING_REPAIR_CPU_FAILURE_SHA256 = cb7df87510b2314361b2d5fa177fbc196870d64962d82ce27e994f9781c0a6ac`

`SAO_ENGINEERING_REPAIR_SCIENTIFIC_CONFIGURATION_CHANGED = NO`

`SAO_ENGINEERING_REPAIR_PROMPTS_SEEDS_BUDGETS_CHANGED = NO`

`SAO_ENGINEERING_FAILURES_REPAIRABLE = YES`

`SAO_ENGINEERING_FUTURE_RETRY_REQUIRES_NEW_RUN_AND_CLAIM = YES`

`SAO_ENGINEERING_REPAIR_RUNNER_SHA256 = 53da80ac0d3f7585090fd8f4981391c2ed05b2f3464552c83ca5458731ef3342`

`SAO_ENGINEERING_REPAIR_CLAIMS_SHA256 = f2a8cf2467c4c7198e302472426fc07a76f2bf18033064dbcf6a8603125c3708`

`SAO_ENGINEERING_REPAIR_SMOKE_SHA256 = d6d4091a7d14986f8e215c0acdcabfb8df6a9ff064fc6d67146107ccb18e9644`

`SAO_ENGINEERING_REPAIR_ADAPTER_SHA256 = b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef`

`SAO_ENGINEERING_REPAIR_IMPORT_PATCH_SHA256 = df732865be587fa63fca797cdc19679254b15a86c30b0575b701a0a51c3677c1`

`SAO_ENGINEERING_REPAIR_PLACEMENT = an12:[7];TP1;R1`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

## D-0051 — Stable Audio Open repaired mini-smoke accepted and deep evidence gate repaired

- Date: 2026-07-22
- Status: accepted measured PASS and completed pre-scientific validator repair
- Authority: D-0045 and D-0050

The exact D-0050 offline engineering run `sao-mini-smoke-v2-003` completed
all three authorized calls on an12 physical GPU 7. Each call used 100 actual
NFE and passed the frozen audio sanity and 0.25-second duration rules. The
two fixed-seed calls have identical decoded-waveform SHA-256
`c83f50f1e3ef8abf8c2a5b53f4e271af13b7788b342709490ad64e589c291d30`.
Measured cold-plus-first time is `161.5567436106503 s`, measured resident
unit time is `19.28598228469491 s`, and the frozen 1,536-call cap is
`59369.522357624024 GPU-s` (`16.491533988228895 GPU-h`). Peak allocated and
reserved VRAM were `8,538,524,672 / 10,733,223,936 B`.

The first two core-package preparation attempts stopped before publication,
GPU use, or model calls: the first used an interpreter without `soundfile`;
the second exposed a deep-evidence validator that recognized only the fixed
v2-001 and v2-002 paths. Their combined immutable receipt is
`provenance/b2/sao_core_preparation_engineering_failures_v2.json`, SHA-256
`215df0f7e4deb9e7f806113f611861a333e5fac02ceae8dc5a539644ac37e9b5`.
The targeted repair admits only the exact fixed v2-003 path and consumed
claim, revalidates the D-0050 decision block, environment/package freeze,
runtime authorization, live config, and prior failure lineage, and keeps the
v2-001/v2-002 branches unchanged. The retained v2-003 evidence then passed
the full core admission validator. This is an engineering invariant repair;
no prompt, seed, weight, sampler, inference budget, evaluator, endpoint, or
scientific threshold changed.

`SAO_MINI_SMOKE_STATUS = PASS_MEASURED_READY`

`SAO_MINI_SMOKE_RUN_ID = sao-mini-smoke-v2-003`

`SAO_MINI_SMOKE_MODEL_CALLS = 3`

`SAO_MINI_SMOKE_GENERATED_OUTPUTS = 3`

`SAO_MINI_SMOKE_TERMINAL_SHA256 = 825eac8e43583871fbb2a4b59f73226e68d5577fecb9255fe82b62dd6945a692`

`SAO_MINI_SMOKE_LEDGER_SHA256 = cfb5cb32a015fd174f9f061556db29c9e715e89e3715371a91cbf858aa1317c9`

`SAO_MINI_SMOKE_MANIFEST_SHA256 = 1481056390932b6456743756a56addb1a63aca04b3d7180b491cca12a328f295`

`SAO_MINI_SMOKE_CLAIM_SHA256 = 173c6bd534730e8da01aa5b3c5afef73b709389ed1c39a6d64a328c1c7ce4f7c`

`SAO_MINI_SMOKE_ACTUAL_NFE_PER_CALL = 100`

`SAO_MEASURED_COLD_PLUS_FIRST_SECONDS = 161.5567436106503`

`SAO_MEASURED_RESIDENT_UNIT_SECONDS = 19.28598228469491`

`SAO_CORE_GPU_SECONDS_CAP = 59369.522357624024`

`SAO_CORE_DEEP_EVIDENCE_STATUS = PASS`

`SAO_CORE_PREPARATION_ENGINEERING_FAILURES_RETAINED = YES`

`SAO_SCIENTIFIC_CONFIGURATION_CHANGED = NO`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

## D-0052 — Stable Audio Open exact ordinary-core run opened

- Date: 2026-07-22
- Status: accepted exact SAO-only ordinary-core generation opening
- Authority: PI consolidated SAO-live goal, D-0037, D-0045, and D-0051

The measured PASS terminal and official offline snapshot now satisfy every
SAO generation precondition. Exactly one fresh ordinary-core run,
`benchmark-core-v2-sao-20260722t162200z`, may be prepared and launched. Its
allowlist contains only `stabilityai/stable-audio-open-1.0`: 1,536 registered
30-second requests, shard size four, one an12 A800 on physical GPU 7, TP1,
one replica, and the exact measured cap `59,369.522357624024 GPU-s`. The
official provider revision remains
`f21265c1e2710b3bd2386596943f0007f55f802e`.

The completed SA3 and ACE core runs are immutable prior completions and
receive no generation row. There is no row replacement, extra seed, prompt
change, shorter clip, model substitution, state execution, eligibility-scope
expansion, or human-packet assembly authority. Automatic scoring remains a
separate completed-shard opening. Queue-don't-preempt applies, every output
is retained, and every request crosses the durable claim boundary before its
model call.

The exact launch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2_sao_incremental.json` | `4e96142e35553d391f89ad98b6c8bd055a5583746d15b2461f145713297a7713` |
| `provenance/b2/build_status_terminal_v2_sao_amendment.json` | `e51057d133684b607473629f8791244216b8cbc18939f47558753fd16949e977` |
| `configs/backbones/stable_audio_open_1_0.json` | `fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b` |
| `provenance/core/ace_core_completion_v2.json` | `813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0` |
| `provenance/core/sa3_core_completion_v2.json` | `4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6` |
| `src/backbones/sao_operational_claims.py` | `f89fd13cc50698e4f3bf1d6824c6c459c5eacfd8411892034314dd1c9460a487` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| `src/audio_duration_policy.py` | `54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/duration_sanity.py` | `a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/license_gate.py` | `de94a4c7116a613cfbf80ffe7e810970643122b8534a17613ecdb192740882c3` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/backbones/sao_engineering_retry.py` | `3dd7fbc98cbbb1e3c31294374fa1133893b8317f04485e7cb030392069430420` |
| `src/backbones/sao_environment.py` | `69111c5fb21d42df9bcc7ffd6294f2c3cca67e848515e1e3a0121a2218f1f4fc` |
| `src/backbones/sao_mini_smoke.py` | `daad6dc1c3044d79a0891f2a9a6d4bc3b78f5cef34cecbd441d1ad51e9bf2457` |
| `src/backbones/sao_t5.py` | `b8470ee65b1c466ebb6ff312726672a720178e4d55034d9f467897dc2f584baf` |
| `src/backbones/stable_audio_3.py` | `909f3efceb296caca59667ae4d0a4aa777d74d37a9e86b5170bdaba23ae2aa6b` |
| `src/backbones/stable_audio_open.py` | `b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `d719e9bb24b40dc18ecd5cd30a8c59f8c10a01e88bebb74791e313d2a12e1c6f` |
| `src/benchmark_core/artifacts.py` | `aec1a672456df5cdae8adf2c2900cd5f4c0fa7904bb3420b16128ac9c4179a8c` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `49e840f0bb5850258fe37ebf34e14c185a9df241efe28875c723f8dad89c3edd` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `eb4e8ad60e066dc50b6835a5eefd7b4930ca8276476a15eae2d11299410e9919` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `df7b37f29ca000ad26a33944ae9f4e9f08677bc7c122b981e8aeb23bacf8f7f7` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `2f23b6172b9d5d012caa15eb4d07a6fc0ee6d20ebe88e4ea2c7bbf6fbafdecea` |
| `src/sa3_smoke/__init__.py` | `18704985ac543674c1b8a1ac78764fba1b6f2fa3bf7748efa3fb26f40173af60` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `src/sa3_smoke/budget.py` | `dc1b5ecfdb193e1defd90e48f6fe7a7fb05ce38b9191ea9a1271c0e39a91c332` |
| `src/sa3_smoke/environment_validation.py` | `684e736671055ffc5ad5e14ffe160aef9816ccc3317b080d7beef56dc38cc6fa` |
| `src/sa3_smoke/model_runtime.py` | `614fc7e6d016e1dc07971a028653749318edac2c3c980a40d73aaf8be709fde4` |
| `scripts/prepare_benchmark_core_run.py` | `7722932e2587ae19a489bb526ca23563c4fff1111f2be2ecba89cdeeace09910` |
| `scripts/run_benchmark_core_worker.py` | `9961f057d56dd7cad820dc4075362650cc9a20ff9ec36ac3bc5ad39830fc5b25` |

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = stabilityai/stable-audio-open-1.0`

`BENCHMARK_CORE_AUTHORIZED_RUN_ID = benchmark-core-v2-sao-20260722t162200z`

`SAO_CORE_EXACT_ROWS = 1536`

`SAO_CORE_MAX_CLIP_SECONDS = 30`

`SAO_CORE_GPU_SECONDS_CAP = 59369.522357624024`

`SAO_CORE_PLACEMENT = an12:[7];TP1;R1`

`QUEUE_DO_NOT_PREEMPT = YES`

`SAO_AUTOMATIC_SCORING_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

## D-0053 — Stable Audio Open core preclaim repair and fresh run opened

- Date: 2026-07-22
- Status: accepted exact fresh SAO-only ordinary-core generation opening
- Authority: PI consolidated SAO-live goal, D-0045, D-0051, and the immutable D-0052 zero-claim failure

The measured PASS terminal and official offline snapshot now satisfy every
SAO generation precondition. Exactly one fresh ordinary-core run,
`benchmark-core-v2-sao-20260722t164200z`, may be prepared and launched. Its
allowlist contains only `stabilityai/stable-audio-open-1.0`: 1,536 registered
30-second requests, shard size four, one an12 A800 on physical GPU 7, TP1,
one replica, and the exact measured cap `59,369.522357624024 GPU-s`. The
official provider revision remains
`f21265c1e2710b3bd2386596943f0007f55f802e`.

The D-0052 CPU preparation stopped before the global claim, run directory, GPU use, or model call because the validator rejected the ACE completion receipt's two additional, exact completed-shard counts. The immutable failure receipt is `provenance/core/sao_core_launch_preparation_failure_v2_001.json`, SHA-256 `4b94cd78c6066bc8eec2f82e9bfd242206234c5b81a69501b1840feffc11cea5`. The repair accepts only either the exact legacy three-count receipt or those same counts plus exactly 384 shard records and 384 heartbeat snapshots. It changes no scientific input or threshold. D-0052 is closed without a claim; this decision uses a new run ID and will consume a new one-shot claim.

The completed SA3 and ACE core runs are immutable prior completions and
receive no generation row. There is no row replacement, extra seed, prompt
change, shorter clip, model substitution, state execution, eligibility-scope
expansion, or human-packet assembly authority. Automatic scoring remains a
separate completed-shard opening. Queue-don't-preempt applies, every output
is retained, and every request crosses the durable claim boundary before its
model call.

The exact launch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2_sao_incremental.json` | `4e96142e35553d391f89ad98b6c8bd055a5583746d15b2461f145713297a7713` |
| `provenance/b2/build_status_terminal_v2_sao_amendment.json` | `e51057d133684b607473629f8791244216b8cbc18939f47558753fd16949e977` |
| `configs/backbones/stable_audio_open_1_0.json` | `fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b` |
| `provenance/core/ace_core_completion_v2.json` | `813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0` |
| `provenance/core/sa3_core_completion_v2.json` | `4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6` |
| `src/backbones/sao_operational_claims.py` | `f89fd13cc50698e4f3bf1d6824c6c459c5eacfd8411892034314dd1c9460a487` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| `src/audio_duration_policy.py` | `54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/duration_sanity.py` | `a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/license_gate.py` | `de94a4c7116a613cfbf80ffe7e810970643122b8534a17613ecdb192740882c3` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/backbones/sao_engineering_retry.py` | `3dd7fbc98cbbb1e3c31294374fa1133893b8317f04485e7cb030392069430420` |
| `src/backbones/sao_environment.py` | `69111c5fb21d42df9bcc7ffd6294f2c3cca67e848515e1e3a0121a2218f1f4fc` |
| `src/backbones/sao_mini_smoke.py` | `daad6dc1c3044d79a0891f2a9a6d4bc3b78f5cef34cecbd441d1ad51e9bf2457` |
| `src/backbones/sao_t5.py` | `b8470ee65b1c466ebb6ff312726672a720178e4d55034d9f467897dc2f584baf` |
| `src/backbones/stable_audio_3.py` | `909f3efceb296caca59667ae4d0a4aa777d74d37a9e86b5170bdaba23ae2aa6b` |
| `src/backbones/stable_audio_open.py` | `b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `d719e9bb24b40dc18ecd5cd30a8c59f8c10a01e88bebb74791e313d2a12e1c6f` |
| `src/benchmark_core/artifacts.py` | `aec1a672456df5cdae8adf2c2900cd5f4c0fa7904bb3420b16128ac9c4179a8c` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `66be950ad5f4f37fdfbbb441cfc626365a27454505461085b82a943090141b05` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `eb4e8ad60e066dc50b6835a5eefd7b4930ca8276476a15eae2d11299410e9919` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `df7b37f29ca000ad26a33944ae9f4e9f08677bc7c122b981e8aeb23bacf8f7f7` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `2f23b6172b9d5d012caa15eb4d07a6fc0ee6d20ebe88e4ea2c7bbf6fbafdecea` |
| `src/sa3_smoke/__init__.py` | `18704985ac543674c1b8a1ac78764fba1b6f2fa3bf7748efa3fb26f40173af60` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `src/sa3_smoke/budget.py` | `dc1b5ecfdb193e1defd90e48f6fe7a7fb05ce38b9191ea9a1271c0e39a91c332` |
| `src/sa3_smoke/environment_validation.py` | `684e736671055ffc5ad5e14ffe160aef9816ccc3317b080d7beef56dc38cc6fa` |
| `src/sa3_smoke/model_runtime.py` | `614fc7e6d016e1dc07971a028653749318edac2c3c980a40d73aaf8be709fde4` |
| `scripts/prepare_benchmark_core_run.py` | `7722932e2587ae19a489bb526ca23563c4fff1111f2be2ecba89cdeeace09910` |
| `scripts/run_benchmark_core_worker.py` | `9961f057d56dd7cad820dc4075362650cc9a20ff9ec36ac3bc5ad39830fc5b25` |

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = stabilityai/stable-audio-open-1.0`

`BENCHMARK_CORE_AUTHORIZED_RUN_ID = benchmark-core-v2-sao-20260722t164200z`

`SAO_CORE_EXACT_ROWS = 1536`

`SAO_CORE_MAX_CLIP_SECONDS = 30`

`SAO_CORE_GPU_SECONDS_CAP = 59369.522357624024`

`SAO_CORE_PLACEMENT = an12:[7];TP1;R1`

`QUEUE_DO_NOT_PREEMPT = YES`

`SAO_AUTOMATIC_SCORING_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

`SAO_CORE_PREVIOUS_RUN_ID = benchmark-core-v2-sao-20260722t162200z`

`SAO_CORE_PREVIOUS_PRECLAIM_FAILURE_SHA256 = 4b94cd78c6066bc8eec2f82e9bfd242206234c5b81a69501b1840feffc11cea5`

`SAO_CORE_PREVIOUS_GLOBAL_CLAIM_CREATED = NO`

`SAO_CORE_PREVIOUS_RUN_DIRECTORY_CREATED = NO`

`SAO_CORE_ENGINEERING_REPAIR_SCIENTIFIC_CONFIGURATION_CHANGED = NO`

## D-0054 — Stable Audio Open deferred-state validator repair and fresh core run opened

- Date: 2026-07-22
- Status: accepted exact fresh SAO-only ordinary-core generation opening
- Authority: PI consolidated SAO-live goal, D-0045, D-0051, and the immutable D-0053 zero-claim failure

The measured PASS terminal and official offline snapshot now satisfy every
SAO generation precondition. Exactly one fresh ordinary-core run,
`benchmark-core-v2-sao-20260722t165200z`, may be prepared and launched. Its
allowlist contains only `stabilityai/stable-audio-open-1.0`: 1,536 registered
30-second requests, shard size four, one an12 A800 on physical GPU 7, TP1,
one replica, and the exact measured cap `59,369.522357624024 GPU-s`. The
official provider revision remains
`f21265c1e2710b3bd2386596943f0007f55f802e`.

The D-0053 CPU validation stopped before the global claim, run directory, GPU use, or model call because the ordinary-core loader conflated ACE's immutable launch-time `AUTOMATIC_OUTPUT_ONLY` metadata with its later, separately authorized state eligibility. The immutable failure receipt is `provenance/core/sao_core_launch_preparation_failure_v2_002.json`, SHA-256 `7d9f62a5f29ccfb9fe10c873f0f0c75e66e08e5d0e81642fca60bf3cac6c6b41`. The repair keeps the eligible-model subset check and admits only ACE's deferred state readiness while ordinary-core state launch is exactly `CLOSED_AT_ORDINARY_CORE_LAUNCH`; SAO and every other non-ready-state model remain excluded. It changes no scientific input or threshold. D-0053 is closed without a claim; this decision uses a new run ID and will consume a new one-shot claim.

The completed SA3 and ACE core runs are immutable prior completions and
receive no generation row. There is no row replacement, extra seed, prompt
change, shorter clip, model substitution, state execution, eligibility-scope
expansion, or human-packet assembly authority. Automatic scoring remains a
separate completed-shard opening. Queue-don't-preempt applies, every output
is retained, and every request crosses the durable claim boundary before its
model call.

The exact launch inputs are:

| Path | SHA-256 |
| --- | --- |
| `configs/benchmark_core_v2_sao_incremental.json` | `4e96142e35553d391f89ad98b6c8bd055a5583746d15b2461f145713297a7713` |
| `provenance/b2/build_status_terminal_v2_sao_amendment.json` | `e51057d133684b607473629f8791244216b8cbc18939f47558753fd16949e977` |
| `configs/backbones/stable_audio_open_1_0.json` | `fd3c77b1aa6b07f63d9ca207d795dbfc9c82c103358a2aabff3a6bb48e282e2b` |
| `provenance/core/ace_core_completion_v2.json` | `813c81219c7bcf3035f377248afd6a4996de1a6c2c3cbc1b5c396888149dc2a0` |
| `provenance/core/sa3_core_completion_v2.json` | `4574f439c6f74a7a1b6fac9bf850135f7903f3e49ffd09477e91853826c5bac6` |
| `src/backbones/sao_operational_claims.py` | `f89fd13cc50698e4f3bf1d6824c6c459c5eacfd8411892034314dd1c9460a487` |
| `BENCHMARK_PREREG_v2.md` | `77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa` |
| `BENCHMARK_CORE_PROTOCOL_v2.md` | `869856603666c9d5b8a0ffbcb7e286a20f35bb3ca03955279b2777cc3e0ab685` |
| `provenance/b2/build_status_terminal_v2.json` | `d31c45f80f2397ee7dc9456d543da0bced560de8b299db1b10d495c4162efe72` |
| `configs/backbones/stable_audio_3_medium_base.json` | `e1bcc0d03e6929b8fd2b655f8fc8c182a2be0eb6316549a94f48c4b040a98f75` |
| `configs/backbones/ace_step_v1.json` | `b3cfc59e661a7bb10f16e6c1296fe0de8810945815847ace6f99abbabfe0c879` |
| `src/audio_duration_policy.py` | `54268349d62a35e86b55127c374219749e33c66995aeded6750b26944efb568e` |
| `src/backbones/__init__.py` | `e42845b1df342a56a55aca378f6994a2b56fe50c08cc11cac87296826e7248f0` |
| `src/backbones/ace_step_v1.py` | `a18aeb11d199656b46a18793e1e75bf03a54d0c135894db46738da0f18d8b0d7` |
| `src/backbones/contracts.py` | `9368e2044380000e74bbefcd528d2f09fc22ef2b484b6f3b8bf298617b09f2d2` |
| `src/backbones/duration_sanity.py` | `a06818e4ccb0a0da67a664783bd29181269cc00bfeeb65c4f3d5c5089a283bd6` |
| `src/backbones/io.py` | `fe3e4d101ef34c846b7b86a2cba9e44f36b839364c99487de209406e7254aa3a` |
| `src/backbones/license_gate.py` | `de94a4c7116a613cfbf80ffe7e810970643122b8534a17613ecdb192740882c3` |
| `src/backbones/runtime.py` | `d2e42754a4599e64d43d9ce43db8cfe057034581db2b5099ca6886d1eeedfeed` |
| `src/backbones/sao_engineering_retry.py` | `3dd7fbc98cbbb1e3c31294374fa1133893b8317f04485e7cb030392069430420` |
| `src/backbones/sao_environment.py` | `69111c5fb21d42df9bcc7ffd6294f2c3cca67e848515e1e3a0121a2218f1f4fc` |
| `src/backbones/sao_mini_smoke.py` | `daad6dc1c3044d79a0891f2a9a6d4bc3b78f5cef34cecbd441d1ad51e9bf2457` |
| `src/backbones/sao_t5.py` | `b8470ee65b1c466ebb6ff312726672a720178e4d55034d9f467897dc2f584baf` |
| `src/backbones/stable_audio_3.py` | `909f3efceb296caca59667ae4d0a4aa777d74d37a9e86b5170bdaba23ae2aa6b` |
| `src/backbones/stable_audio_open.py` | `b4d36f87e2e48436498fb5b59e38fbf33882e560a3fd8fa6aeb58259fafd85ef` |
| `src/benchmark_core/__init__.py` | `5fe552169fdb0ed47cb4f92cac51ab982d72ceff67a028c88dd8a461fb9d602c` |
| `src/benchmark_core/adapter_bridge.py` | `d719e9bb24b40dc18ecd5cd30a8c59f8c10a01e88bebb74791e313d2a12e1c6f` |
| `src/benchmark_core/artifacts.py` | `aec1a672456df5cdae8adf2c2900cd5f4c0fa7904bb3420b16128ac9c4179a8c` |
| `src/benchmark_core/claims.py` | `76f3adacaf9ee65884bafa3c53ba11dd3921d5378a79f116107f33c854e92b2c` |
| `src/benchmark_core/config.py` | `5971ba8e9da6ae61074c4bb3bbafd8982be2549a0494a29abaa1c163af3929e3` |
| `src/benchmark_core/heartbeat.py` | `dfd77b90541d0099d6495280d7f7dad4e88c2b9703b91e09617195285bbd8480` |
| `src/benchmark_core/launcher.py` | `eb4e8ad60e066dc50b6835a5eefd7b4930ca8276476a15eae2d11299410e9919` |
| `src/benchmark_core/ledger.py` | `6953bab158fc494b133ddaf8dde76597e1b9515e5c1ae8d3c5fc82a2ec95540f` |
| `src/benchmark_core/placement.py` | `961193d3ab08ded1decc5f7f9086495362948ad296b9dbdba77877881b2b4902` |
| `src/benchmark_core/queue.py` | `df7b37f29ca000ad26a33944ae9f4e9f08677bc7c122b981e8aeb23bacf8f7f7` |
| `src/benchmark_core/state_queue.py` | `fafdbed02820fde1bbf8945d3c2d6679b66bdabbe59ed86200d3f9f08ef619ef` |
| `src/benchmark_core/supervisor.py` | `3e24f8b9d0de58f3b5a204e330e39d6857a4dcaea83e9a7374bbe22dbb032e4c` |
| `src/benchmark_core/worker.py` | `2f23b6172b9d5d012caa15eb4d07a6fc0ee6d20ebe88e4ea2c7bbf6fbafdecea` |
| `src/sa3_smoke/__init__.py` | `18704985ac543674c1b8a1ac78764fba1b6f2fa3bf7748efa3fb26f40173af60` |
| `src/sa3_smoke/artifacts.py` | `c51f2417577927180fa86b4282562a4781446a15d32cd466eda9213c7d679df3` |
| `src/sa3_smoke/audio.py` | `c17634f7e06ff1b2b315f91077a27b0677c34844eb2c916c6f36dcf1186d0a24` |
| `src/sa3_smoke/budget.py` | `dc1b5ecfdb193e1defd90e48f6fe7a7fb05ce38b9191ea9a1271c0e39a91c332` |
| `src/sa3_smoke/environment_validation.py` | `684e736671055ffc5ad5e14ffe160aef9816ccc3317b080d7beef56dc38cc6fa` |
| `src/sa3_smoke/model_runtime.py` | `614fc7e6d016e1dc07971a028653749318edac2c3c980a40d73aaf8be709fde4` |
| `scripts/prepare_benchmark_core_run.py` | `7722932e2587ae19a489bb526ca23563c4fff1111f2be2ecba89cdeeace09910` |
| `scripts/run_benchmark_core_worker.py` | `9961f057d56dd7cad820dc4075362650cc9a20ff9ec36ac3bc5ad39830fc5b25` |

`BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`

`BENCHMARK_CORE_AUTHORIZED_MODEL_IDS = stabilityai/stable-audio-open-1.0`

`BENCHMARK_CORE_AUTHORIZED_RUN_ID = benchmark-core-v2-sao-20260722t165200z`

`SAO_CORE_EXACT_ROWS = 1536`

`SAO_CORE_MAX_CLIP_SECONDS = 30`

`SAO_CORE_GPU_SECONDS_CAP = 59369.522357624024`

`SAO_CORE_PLACEMENT = an12:[7];TP1;R1`

`QUEUE_DO_NOT_PREEMPT = YES`

`SAO_AUTOMATIC_SCORING_AUTHORIZED = NO`

`BENCHMARK_STATE_INITIAL_QUEUE_AUTHORIZED = NO`

`BENCHMARK_STATE_SUPPLEMENTAL_QUEUE_AUTHORIZED = NO`

`SAO_STATE_CAPABILITY = NOT_ATTEMPTED`

`SAO_ELIGIBILITY_SCOPE_EXPANDED = NO`

`SAO_CORE_PREVIOUS_RUN_ID = benchmark-core-v2-sao-20260722t164200z`

`SAO_CORE_PREVIOUS_PRECLAIM_FAILURE_SHA256 = 7d9f62a5f29ccfb9fe10c873f0f0c75e66e08e5d0e81642fca60bf3cac6c6b41`

`SAO_CORE_PREVIOUS_GLOBAL_CLAIM_CREATED = NO`

`SAO_CORE_PREVIOUS_RUN_DIRECTORY_CREATED = NO`

`SAO_CORE_ENGINEERING_REPAIR_SCIENTIFIC_CONFIGURATION_CHANGED = NO`

`SAO_CORE_EARLIER_PRECLAIM_FAILURE_SHA256 = 4b94cd78c6066bc8eec2f82e9bfd242206234c5b81a69501b1840feffc11cea5`

`SAO_CORE_ALL_PRECLAIM_FAILURES_RETAINED = YES`

## D-0055 — SA3 remaining survivor-only state queue opened

- Date: 2026-07-22
- Status: accepted exact remaining-only engineering repair opening
- Authority: PI consolidated repair-governance goal, D-0035, D-0045, and
  the immutable run-002 evidence

The exact failed unit in `sa3-state-v2-restricted-rerun-002` passed the
required one-root validation after the committed checkpoint-sidecar rebind.
That validation completed one group, three state units, and four model calls.
Two later continuation-launch publications failed before a new worker,
claim, model call, or output; both failures remain immutable. The completed
validation is therefore excluded byte-for-byte, and only the original-order
47 groups / 141 units / 423 action rows remaining from the same materialized
Stage-1 survivor queue may execute in the fresh run
`sa3-state-v2-restricted-rerun-003`.

The fresh run uses one an12 A800 on physical GPU 4, TP1, one replica. It may
not repeat the completed validation unit, execute any STOP/cancelled unit,
or unlock supplemental roots. Prompts, roots, checkpoints, actions,
root-local previews, folds, costs, and outcomes remain unchanged. Any later
engineering repair must retain this attempt and use another new run ID and
claim; scientific-design changes still require PI review.

Exact repair evidence and executable sources are:

| Item | SHA-256 |
| --- | --- |
| corrected run-002 terminal | `3279b95bac56f75e074e60e79e4020272e8a60e0506d852410a4348721eadb7c` |
| one-root validation marker | `74870f74b948becc9ca5314279010f40e6220062123b33fb1578f4072324870e` |
| continuation failure 001 | `91f775be763aabdabfa42b5245c0b822a112874a84da60b292cc2805ecc7a253` |
| continuation failure 002 | `7f9796c77cc820fd30ef48749576aa5811c3b81f65684aea936996b4866f7615` |
| completed exclusion | `b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566` |
| remaining manifest | `fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33` |
| `configs/sa3_state_restricted_rerun_v2.json` | `67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2` |
| original state queue manifest | `5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3` |
| `src/state_capture/sa3_restricted_rerun.py` | `dbd5dfe7c3115a6082f7b210e54de6922028a8c5b7deb60993da7532176ef630` |
| `src/state_capture/sa3_remaining_repair.py` | `e073ed74920404c42f79c14cb1b5dc84f2f9acfcaf6de372bdc62390220e7d35` |
| prepare script | `c3b818fba39b92c5cc03471cf15d00b7fbdae64cdd3ec61ea5eb8cbb5d2c7810` |
| worker script | `b8babdf5f6983bc0ad3bc1aec6315b71732bdadb7d0b2010d24b87490c4cc71d` |

`SA3_STATE_REMAINING_REPAIR_AUTHORIZED = YES`

`SA3_STATE_REMAINING_REPAIR_RUN_ID = sa3-state-v2-restricted-rerun-003`

`SA3_STATE_REMAINING_REPAIR_PREDECESSOR_SHA256 = 3279b95bac56f75e074e60e79e4020272e8a60e0506d852410a4348721eadb7c`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_EXCLUSION_SHA256 = b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566`

`SA3_STATE_REMAINING_REPAIR_MANIFEST_SHA256 = fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33`

`SA3_STATE_REMAINING_REPAIR_PLACEMENT = an12:[4];TP1;R1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_GROUP_COUNT = 1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_COUNT = 3`

`SA3_STATE_REMAINING_REPAIR_REMAINING_GROUP_COUNT = 47`

`SA3_STATE_REMAINING_REPAIR_REMAINING_UNIT_COUNT = 141`

`SA3_STATE_REMAINING_REPAIR_REMAINING_ACTION_COUNT = 423`

`SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO`

`SA3_STATE_REMAINING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO`

`SA3_STATE_REMAINING_REPAIR_CONFIG_SHA256 = 67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`

`SA3_STATE_REMAINING_REPAIR_QUEUE_MANIFEST_SHA256 = 5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3`

`SA3_STATE_REMAINING_REPAIR_STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`SA3_STATE_REMAINING_REPAIR_STAGE1_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`SA3_STATE_REMAINING_REPAIR_ATTEMPT_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sa3-state-restricted-rerun-v2/sa3-state-v2-restricted-rerun-003.claim.json`

## D-0056 — SA3 zero-call scheduler repair and run-004 opened

- Date: 2026-07-22
- Status: accepted exact remaining-only pre-model engineering repair
- Authority: PI consolidated repair-governance goal, D-0045, D-0055, and
  immutable run-003 failure evidence

Run-003 prepared and consumed its unique claim, but an independent pre-model
audit found that the worker would still shard by the frozen R4 capacity even
though D-0055 authorized R1. It was stopped before any worker, GPU use, model
call, ledger, staging payload, or output. The immutable failure receipt is
SHA-256 `a58875bf6e5327437be0ce0eb98bf2a6858045c4851b36e0c69aba1db267c2f7`.
Its claim, manifest, plan, D-0055 bytes, and remaining-work package have been
revalidated, including absence of every execution artifact.

The targeted repair passes the exact authorized execution-replica count to
the worker. Fresh run `sa3-state-v2-restricted-rerun-004` uses one an12 A800
on physical GPU 4, TP1, R1 and therefore schedules all 47 remaining groups.
The completed validation stays excluded; the same 141 units and 423 action
rows remain in original order. No STOP/cancelled or supplemental unit may
execute. No prompt, root, checkpoint, action, preview, fold, cost, outcome,
evaluator, or threshold changed.

| Item | SHA-256 |
| --- | --- |
| run-003 failure receipt | `a58875bf6e5327437be0ce0eb98bf2a6858045c4851b36e0c69aba1db267c2f7` |
| run-003 claim | `0b78f71420700a70e0bae28adfd760b3c035df2ac500bc7321bb39aceb93ddfd` |
| run-003 manifest | `5aa66e467fd6bd93ba81fc1242baccba1bbc7a66b710bab50a574c0177717f29` |
| run-003 execution plan | `239e2867e36d3ae8866a003be4355b8edbf49ffbfc1af0da62df09b827f7ff41` |
| completed exclusion | `b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566` |
| remaining manifest | `fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33` |
| `src/state_capture/sa3_restricted_rerun.py` | `758309da8a316c5a7afc49d423236ee030542c4de5b51b81118f2ca5bd0f2769` |
| `src/state_capture/sa3_worker.py` | `425823a15716cb03de8cec7731bef47a95c0b03b83b4335a35c1e72752cb7bd2` |
| worker script | `adf4eb31cc73535d64a7c92ef5aca8a075c0c34ee896f243442819aaac3ed2de` |

`SA3_STATE_REMAINING_REPAIR_AUTHORIZED = YES`

`SA3_STATE_REMAINING_REPAIR_RUN_ID = sa3-state-v2-restricted-rerun-004`

`SA3_STATE_REMAINING_REPAIR_PREDECESSOR_SHA256 = a58875bf6e5327437be0ce0eb98bf2a6858045c4851b36e0c69aba1db267c2f7`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_EXCLUSION_SHA256 = b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566`

`SA3_STATE_REMAINING_REPAIR_MANIFEST_SHA256 = fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33`

`SA3_STATE_REMAINING_REPAIR_PLACEMENT = an12:[4];TP1;R1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_GROUP_COUNT = 1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_COUNT = 3`

`SA3_STATE_REMAINING_REPAIR_REMAINING_GROUP_COUNT = 47`

`SA3_STATE_REMAINING_REPAIR_REMAINING_UNIT_COUNT = 141`

`SA3_STATE_REMAINING_REPAIR_REMAINING_ACTION_COUNT = 423`

`SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO`

`SA3_STATE_REMAINING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO`

`SA3_STATE_REMAINING_REPAIR_CONFIG_SHA256 = 67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`

`SA3_STATE_REMAINING_REPAIR_QUEUE_MANIFEST_SHA256 = 5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3`

`SA3_STATE_REMAINING_REPAIR_STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`SA3_STATE_REMAINING_REPAIR_STAGE1_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`SA3_STATE_REMAINING_REPAIR_ATTEMPT_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sa3-state-restricted-rerun-v2/sa3-state-v2-restricted-rerun-004.claim.json`

## D-0057 — Fresh automatic watermark contract and packet watcher rearmed

- Date: 2026-07-22
- Status: accepted fail-closed watcher replacement behind both existing gates
- Authority: PI packet-watcher authorization, D-0038, and D-0045

Fresh scoring publications must carry the exact watermark
`AUTOMATIC-INSTRUMENT OUTCOMES` and must reject human-gold or evaluator-
accuracy wording before human labels exist. Historical scoring artifacts
remain immutable even where they predate this publication contract; they
will not be silently rewritten or used as the final three-backbone packet
source.

The replacement watcher uses the separately versioned config
`configs/human_packet_autoassembly_v2_sao_watermarked.json`. It may assemble
once only after both the nine-item timing-pilot response/attestation is
ingested and the exact all-three-primary-backbone scoring root provides
tested cross-instrument disagreement strata. Until then it emits heartbeat
state only. It may not downgrade the packet to two backbones and makes no
human-gold claim.

| Item | SHA-256 |
| --- | --- |
| watcher config | `008334d32b4e94f9613bf32e8a9167f6b7183271dd351d08344f8d3c3a171060` |
| watcher source | `5fc8204ec17caf137dd012ab522f8b690a8e7c806ff23c14971df5b5d98e52ab` |
| packet builder | `1e486cc0174833350f75c549a2bbab6a724cdd5977ece287a29f5c457748e805` |
| publication validator | `b0165d5b2b1dade3333e31586d85fb5aadb1fc94aa0118083098734b6b8468b3` |

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY = ARMED`

`HUMAN_AUDIT_PACKET_ASSEMBLY = ARMED_WAITING_FOR_PILOT_AND_SCORING_STRATA`

`HUMAN_AUDIT_PACKET_HUMAN_GOLD_CLAIMS = NO`

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY_CONFIG_PATH = configs/human_packet_autoassembly_v2_sao_watermarked.json`

`HUMAN_AUDIT_PACKET_AUTOASSEMBLY_CONFIG_SHA256 = 008334d32b4e94f9613bf32e8a9167f6b7183271dd351d08344f8d3c3a171060`

`FRESH_AUTOMATIC_TABLE_WATERMARK = AUTOMATIC-INSTRUMENT OUTCOMES`

`HUMAN_PACKET_CROSS_INSTRUMENT_DISAGREEMENT_REQUIRED = YES`

`HUMAN_PACKET_THREE_PRIMARY_BACKBONES_REQUIRED = YES`

## D-0058 — SA3 append-stable lineage repair and run-005 opened

- Date: 2026-07-22
- Status: accepted exact remaining-only preclaim engineering repair
- Authority: PI consolidated repair-governance goal, D-0045, D-0056, and
  immutable run-004 preclaim evidence

The run-004 CPU preparation stopped before its claim or run directory because
the validator hashed one separator newline appended after D-0055 as if the
decision's semantics had changed. The immutable failure receipt is
`provenance/state/sa3_state_run004_preclaim_failure_v1.json`, SHA-256
`2c0866666b481c49a2534a4fdf2cd3a0556b1f8a03e41cfbfa954cc3f2829dc7`.
It records zero workers, calls, outputs, and GPU seconds and proves the
run-004 claim and directory are absent.

The repair canonicalizes an append-only decision block as `rstrip()` plus one
newline before comparing the block SHA-256. The launch-time whole-decisions
hash remains immutable provenance. The canonical D-0055 hash remains
`05ce6b48161cd3d0d74ccd9a868f7908aef1f00560a513e95bf0ba3db57848cb`
after later decisions are appended; D-0056 is likewise bound at canonical
SHA-256 `f8813161060cdde685c0a496caeaf3fc4beea66d13d995bc4bff0529b170ca2e`.

Fresh run `sa3-state-v2-restricted-rerun-005` retains the exact completed
exclusion and 47-group / 141-unit / 423-action remaining package. It uses
an12 GPU4, TP1, R1 with the corrected scheduler. No completed, STOP,
cancelled, or supplemental unit may execute; no scientific input or
threshold changed.

| Item | SHA-256 |
| --- | --- |
| run-004 preclaim failure | `2c0866666b481c49a2534a4fdf2cd3a0556b1f8a03e41cfbfa954cc3f2829dc7` |
| completed exclusion | `b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566` |
| remaining manifest | `fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33` |
| `src/state_capture/sa3_restricted_rerun.py` | `dd464e330d8f4a7a92e33b31abd7b8d41fa889e46661683166b1b9890ef6ba18` |
| `src/state_capture/sa3_worker.py` | `425823a15716cb03de8cec7731bef47a95c0b03b83b4335a35c1e72752cb7bd2` |
| worker script | `adf4eb31cc73535d64a7c92ef5aca8a075c0c34ee896f243442819aaac3ed2de` |

`SA3_STATE_REMAINING_REPAIR_AUTHORIZED = YES`

`SA3_STATE_REMAINING_REPAIR_RUN_ID = sa3-state-v2-restricted-rerun-005`

`SA3_STATE_REMAINING_REPAIR_PREDECESSOR_SHA256 = 2c0866666b481c49a2534a4fdf2cd3a0556b1f8a03e41cfbfa954cc3f2829dc7`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_EXCLUSION_SHA256 = b1328f35fe0a96647d90a489f152743dc3716d19ec39921e92275c29c8b88566`

`SA3_STATE_REMAINING_REPAIR_MANIFEST_SHA256 = fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33`

`SA3_STATE_REMAINING_REPAIR_PLACEMENT = an12:[4];TP1;R1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_GROUP_COUNT = 1`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_COUNT = 3`

`SA3_STATE_REMAINING_REPAIR_REMAINING_GROUP_COUNT = 47`

`SA3_STATE_REMAINING_REPAIR_REMAINING_UNIT_COUNT = 141`

`SA3_STATE_REMAINING_REPAIR_REMAINING_ACTION_COUNT = 423`

`SA3_STATE_REMAINING_REPAIR_VALIDATION_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_COMPLETED_UNIT_RERUN = NO`

`SA3_STATE_REMAINING_REPAIR_SUPPLEMENTAL_AUTHORIZED = NO`

`SA3_STATE_REMAINING_REPAIR_SCIENTIFIC_DESIGN_CHANGED = NO`

`SA3_STATE_REMAINING_REPAIR_CONFIG_SHA256 = 67a210fb63f078aff9d3d43d41bf05a6b3a18a04c2c21ddce3e7ee2f2a3087d2`

`SA3_STATE_REMAINING_REPAIR_QUEUE_MANIFEST_SHA256 = 5aca81acc9eb9043a7e2e8e538d2843bd145dc11796c037a9175278e54095be3`

`SA3_STATE_REMAINING_REPAIR_STAGE1_RESULT_SHA256 = 5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157`

`SA3_STATE_REMAINING_REPAIR_STAGE1_SUMMARY_SHA256 = 7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121`

`SA3_STATE_REMAINING_REPAIR_ATTEMPT_CLAIM_PATH = /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sa3-state-restricted-rerun-v2/sa3-state-v2-restricted-rerun-005.claim.json`

## D-0059 — Stable Audio Open first completed shard scoring opened

- Date: 2026-07-22
- Status: accepted exact four-row completed-shard automatic scoring opening
- Authority: PI automatic-endpoint-scoring authorization, D-0029, D-0054,
  and D-0057

The live SAO core run remains untouched on an12 GPU7. Its immutable first
completed shard contains exactly four successful rows, ledger tail SHA-256
`2670d83061f4668cb1383c27cc55dccd07d2930a99a419d4c790a63309c444b4`,
and completed-prefix SHA-256
`19d3436d5899d723884af8697776f54c33ec0419274960698c16fb5717508662`.
Only this sealed prefix may enter scoring run
`automatic-scoring-v2-sao-benchmark-core-v2-sao-20260722t165200z-shards-001`.
Later live shards are outside this opening.

The scorer uses the frozen v2 automatic instruments and writes fresh tables
with exact watermark `AUTOMATIC-INSTRUMENT OUTCOMES`. It may use only idle,
disjoint capacity after excluding the live SAO GPU7 and SA3 state GPU4
allocations; queue-don't-preempt remains mandatory. This opening authorizes
no generation, state execution, human-gold claim, evaluator-accuracy claim,
or packet assembly. SAO remains an incomplete primary prefix until all 1,536
ordinary-core rows are generated and scored.

| Item | SHA-256 |
| --- | --- |
| scoring config | `5d6fe8de0efe4f591fb1b85fd4bd2e77c84ae40b6ea6296da0452e7adafb5871` |
| SAO shard 000000 | `15bb331113670c8c3107b696067d89a4a4b2cf41f7ac020254b2d91761c4fe88` |
| shard heartbeat snapshot | `b72ce184f1e0ff51dbacdc8dc0eba43336c40beeb76eb9e61af35e65e792b22e` |
| scoring builder | `f6dbe0f3c47b0cc4a3cd2c2860408d5b1da9257b9998f724f7c7f672c28efdbb` |
| config loader | `c41c3c37db01affdc26d75b37089adcf9b255e333e528272329ab7e34088b778` |
| snapshot implementation | `75163d657f2203888e74f56f497e16748ca0441f3ebfc0942639879c9ed0dfbe` |
| publication validator | `b0165d5b2b1dade3333e31586d85fb5aadb1fc94aa0118083098734b6b8468b3` |

`SAO_AUTOMATIC_SCORING_AUTHORIZED = YES`

`AUTOMATIC_ENDPOINT_SCORING_RUN_ID = automatic-scoring-v2-sao-benchmark-core-v2-sao-20260722t165200z-shards-001`

`AUDIO_GENERATION_AUTHORIZED_BY_SCORING = NO`

`QUEUE_DO_NOT_PREEMPT = YES`

`AUTOMATIC_ENDPOINT_SCORING_CONFIG_PATH = configs/automatic_scoring_v2_sao_shard_000000.json`

`AUTOMATIC_ENDPOINT_SCORING_CONFIG_SHA256 = 5d6fe8de0efe4f591fb1b85fd4bd2e77c84ae40b6ea6296da0452e7adafb5871`

`AUTOMATIC_ENDPOINT_SCORING_COMPLETED_SHARDS = 1`

`AUTOMATIC_ENDPOINT_SCORING_SAO_ROWS = 4`

`AUTOMATIC_ENDPOINT_SCORING_PREFIX_SHA256 = 19d3436d5899d723884af8697776f54c33ec0419274960698c16fb5717508662`

`AUTOMATIC_ENDPOINT_SCORING_WATERMARK = AUTOMATIC-INSTRUMENT OUTCOMES`

`AUTOMATIC_ENDPOINT_SCORING_HUMAN_GOLD_CLAIMS = NO`
