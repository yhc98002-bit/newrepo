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
