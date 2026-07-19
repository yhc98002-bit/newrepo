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
