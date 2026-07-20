# B2 ACE-Step v1 Engineering Mini-Smoke Protocol v2

Status: `PREPARED_NOT_AUTHORIZED`

This protocol prepares a one-shot engineering cost measurement. It is not a
benchmark endpoint, is never scored by a benchmark instrument or human rater,
and contributes no benchmark outcome. Merely committing this protocol does not
authorize a model call.

## 1. Exact scope and hard stops

The complete plan is exactly two ACE-Step v1 text-to-audio calls and exactly two
retained 30.0-second WAV outputs. There is no retry, replacement, adaptive
prompt, best-of-N selection, or hidden call. The shared B2 ceiling remains ten
generations, while this package reserves only two. One physical GPU, TP1, one
replica, and at most 1,800 GPU-seconds are allowed. A terminal failure consumes
the one-shot claim and is reported; it does not reopen the package.

The following are outside scope and forbidden: benchmark prompt rows, benchmark
scoring, evaluator calls, endpoint selection, continuation, inpainting,
state-resume, model or source download, weight modification, and deletion or
replacement of any retained artifact.

## 2. Frozen calls

Both calls use `ACE-Step/ACE-Step-v1-3.5B`, the content-pinned local checkpoint,
the exact clean upstream ACE-Step source revision and tree, and the sampler settings in
`configs/backbones/ace_step_v1.json`: 30 inference steps, CFG 5, `cfg`, Euler,
guidance interval 0.5, scheduler shift 3.0, BF16, stereo 48 kHz WAV.

The checkpoint binding is a 17-file, no-exclusion full-tree manifest with
canonical tree SHA-256
`124f8267d6c19f992e8b79880cc59e1ec1104439e6150312ebc94d7563d260fc`.
It covers every weight, all transformer/DCAE/vocoder/root configuration files,
the UMT5 configuration, tokenizer JSON, tokenizer configuration, special-token
map, and provider metadata/README files. Preflight rejects an omitted, extra,
linked, size-drifted, or hash-drifted entry before the global claim. The same
full checkpoint tree and source identity are revalidated immediately before
each durable call claim, closing ordinary preflight-to-call drift.

| Call | Engineering prompt ID | Prompt | Seed ID | Seed | Output |
|---:|---|---|---|---:|---|
| 0 | `b2-mini-smoke-engineering-ace-01` | A steady instrumental engineering test passage led by piano, upright bass, and brushed drums, with continuous sound and a clean ending. | `S-0008` | 73193008 | `audio/call-00.wav` |
| 1 | `b2-mini-smoke-engineering-ace-02` | A steady instrumental engineering test passage led by acoustic guitar, warm bass, and hand percussion, with continuous sound and a clean ending. | `S-0009` | 73193009 | `audio/call-01.wav` |

These prompt IDs are reserved solely for B2 engineering cost calibration and
must remain absent from every benchmark prompt manifest. Seeds are the exact
append-only `S-0008` and `S-0009` rows in `SEED_REGISTRY.md`; the runner checks
both identifiers, integers, intended-use text, and the committed registry
SHA-256. The required DECISIONS authorization must name both prompt IDs and seed
rows as non-benchmark reservations. This does not add either prompt to a
benchmark pool.

## 3. Authorization and origin gate

Execution requires all of the following at the same instant:

1. The live `BENCHMARK_PREREG_v2.md` has status
   `FROZEN_PROSPECTIVE_DESIGN`, its own latest
   `BENCHMARK_PREREG_V2_FROZEN = YES` marker, and is frozen by a later
   append-only DECISIONS entry with the same file hash.
2. That same or a later entry contains every exact
   `B2_MINI_SMOKE_V2_*` assignment printed in the authorization template, with
   authorization set to `YES` and hashes matching the live committed files.
3. A completed external authorization JSON, derived from
   `provenance/b2/b2_mini_smoke_authorization.template.json`, binds the live
   DECISIONS hash, preregistration hash, config/protocol/runner hashes, exact
   clean origin commit, selected node, selected physical GPU, and fixed run ID.
4. The repository is on `main`, has no tracked or untracked changes, and local
   `HEAD` equals local `origin/main` and the authorized commit. No network fetch
   is performed by this runner.
5. The config, executable timeout wrapper, ACE adapter/config, backbone package
   initializer, contracts, I/O and runtime modules, common mini-smoke runner,
   factory, audio/provenance helpers, append-only seed registry, protocol,
   runner, ACE runtime identity, and authorization template all pass SHA-256
   validation before a claim or model load.

The runner is inert without the explicit execute phrase. Authorization records
or DECISIONS text containing a placeholder are rejected.

## 4. Placement and neighbor safety

The selected node must be `an12` or `an29`; the authorization record binds one
physical GPU ID from 0 through 7. `CUDA_VISIBLE_DEVICES` must contain exactly
that physical ID; the process-facing device is always `cuda:0`. Provenance
records the physical ID, literal `CUDA_VISIBLE_DEVICES`, process-visible index
0, and the mapping between them. The placement is TP1 with one replica because ACE-Step v1 fits on
one A800 and this two-call serial measurement does not benefit from replication.

Before the one-shot claim, the runner acquires a nonblocking per-device lock and
requires an A800 with at least 60,000 MiB free, no compute processes, and at
most 5% utilization. Immediately before each call it probes again. Call 0 still
requires no process; call 1 may see only the runner's own PID and requires at
least 16,000 MiB free. Any neighboring PID, insufficient headroom, lock
conflict, node mismatch, or changed GPU state stops without killing, moving, or
preempting another process. The lock is advisory and remains held through
execution.

## 5. Claims, deadline, and immutable storage

Run, log, and claim roots are absolute persistent paths outside the repository.
The fixed run ID is `b2-ace-v1-mini-smoke-v2-001`. Every run artifact and log is
created with exclusive/no-clobber semantics. A global authorization claim is
durably written and fsynced before adapter execution. A distinct call claim is
durably written and fsynced immediately before each model call. For both claim
classes, the newly created file **and its parent directory** are fsynced before
control advances. Claims are
never deleted; therefore a crash cannot silently restore budget.

Production must enter through the executable frozen wrapper
`scripts/run_b2_mini_smoke_v2_with_timeout.py`. Its recorded production argv is
the exact audio-prm Python, wrapper, frozen config, resolved external
authorization, fixed run ID, and execute phrase. The wrapper then `execve`s the
following exact outer argv (with the resolved authorization path in `AUTH`):

```text
/usr/bin/timeout -k 30s 1800s /HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python -B -X pycache_prefix=/tmp/pxy1289-b2-mini-smoke-v2-disabled-pycache /XYFS01/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/repository/scripts/run_b2_mini_smoke_v2.py --config /XYFS01/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/repository/configs/b2_mini_smoke_v2.json --authorization AUTH --run-id b2-ace-v1-mini-smoke-v2-001 --execute I_UNDERSTAND_THIS_MAKES_EXACTLY_TWO_NON_BENCHMARK_MODEL_CALLS
```

The runner checks `/proc/<ppid>/exe`, the NUL-delimited parent argv, GNU
coreutils identity, wrapper path/hash evidence, and both recorded argv vectors
before authorization validation or GPU work. The Python `setitimer` deadline
remains an inner defense only; the exact GNU `timeout -k 30s 1800s` process
boundary is mandatory. Once the global claim is consumed, the command must not
be rerun under a different run ID or authorization record.

## 6. ACE runtime environment

The production interpreter and prefix are fixed to
`/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python` and
`/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm`. The SA3 foundation package
freeze is not evidence for ACE and is not used here. A standalone `conda`
executable is not available on the launch PATH, so the runner records this
limitation explicitly and deterministically snapshots every
`conda-meta/*.json` file plus `conda-meta/history`. It also captures a sorted
`pip freeze --all` from the exact interpreter. Their aggregate hashes must equal
the config and authorization record before the claim; the full snapshots are
written with exclusive creation into the external run evidence. This detects
environment drift but cannot reconstruct an unavailable channel-level
`conda --explicit` export.

The upstream source is fixed at commit
`1bee4c9f5b43e30995f8d4d33b3919197ce1bd68` and Git tree
`a526413e5791e8b3bca32c0246701adaf7626f2b`. Preflight checks tracked changes,
ordinary untracked files, ignored files, and untracked symlinks. The only narrow
filesystem exception is existing CPython-3.10 `__pycache__/*.pyc`. Those cache
files are not behavior inputs: production uses `-B`, requires the alternate
pycache prefix shown above to be absent, and verifies `sys.pycache_prefix`, so
imports cannot read the retained in-tree caches. Any other ignored/untracked
entry fails closed.

## 7. Retention, sanity, provenance, and cost result

Every produced WAV is retained even if sanity fails. Each call is appended and
fsynced to a SHA-256-chained JSONL ledger. Each output receives an adjacent
provenance record and the common audio checks require the exact 30-second
duration, 48 kHz, stereo, finite samples, and non-silence. No output is scored.

A passing outer result has `MEASUREMENT_STATUS = MEASURED` and
`MEASUREMENT_SCOPE = B2_MINI_SMOKE_NON_BENCHMARK`. It reports, per call,
requested steps, measured actual NFE, synchronized call wall time, peak
allocated and reserved VRAM, audio/provenance hashes and sanity, plus total
elapsed one-GPU residency. Placement records include node, physical and visible
GPU IDs, TP width 1, replica count 1, and the placement justification. Full
provenance includes Git/config/protocol/runner/DECISIONS/prereg/seed-registry/
environment hashes and adapter preflight evidence.

Any call, sanity, hash-chain, cap, or provenance failure is terminal
`FAIL_ESCALATED`; partial measurements remain labeled with their factual state
and are not converted into `MEASURED` rows.

Every caught wrapper or runner CLI failure emits one strict standardized terminal JSON object. A failure
before the global claim is `REFUSED_PREFLIGHT` with zero model calls; after the
claim it is `FAIL_ESCALATED`, preserves factual call-claim/output counts, and
marks the exact call count indeterminate unless the retained ledger establishes
it. Failures after run-directory creation also retain the terminal JSON there;
an external `SIGKILL`, host loss, or power loss is represented by retained
claims/logs rather than a falsely synthesized terminal result.
