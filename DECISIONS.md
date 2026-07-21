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
