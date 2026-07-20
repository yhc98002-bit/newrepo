# Benchmark v2 core generation protocol

- Version: 2
- Date authored: 2026-07-20
- Scope: generation and engineering validation only; benchmark endpoints are
  not scored by this launcher
- Authorization state in this file: none; an append-only `DECISIONS.md`
  launch entry is required

## Preconditions

The launcher fails closed unless all of the following are true:

1. `BENCHMARK_PREREG_v2.md` and this protocol are frozen by exact SHA-256 in
   `DECISIONS.md`, and a later entry says
   `BENCHMARK_CORE_GENERATION_AUTHORIZED = YES`.
2. The committed prompt, seed, evaluator, adapter, statistics, queue, ledger,
   environment, and license identities match `configs/benchmark_core_v2.json`.
   That config binds `provenance/b2/build_status_terminal_v2.json` by exact
   path, SHA-256, and terminal status. Its model map must contain exactly SA3,
   stable-audio-open-1.0, and ACE-Step v1 and must exactly match the queue
   statuses in the config. SA3 is `READY`; stable-audio-open-1.0 is
   `BLOCKED_ON_LICENSE`; ACE-Step v1 is either `READY` after a measured
   mini-smoke PASS or `BLOCKED_ON_ENGINEERING_FAILURE` after terminal
   `FAIL_ESCALATED`.
3. The integrity synthetic-injection validation is terminal `PASS` before the
   first model call.
4. The selected backbone is `READY`. `BLOCKED_ON_LICENSE` and
   `BLOCKED_ON_ENGINEERING_FAILURE` create no queue row and are never treated
   as zero cost.
5. The launch checkout is a clean committed `origin/main` revision.

The later launch decision binds exact config, protocol, queue, claim, ledger,
heartbeat, placement, artifact, adapter-bridge, worker, and runner SHA-256
values. It does not attempt a self-referential commit hash. After that commit
is pushed, the CPU-only preparer observes `HEAD == refs/remotes/origin/main`
and an empty worktree, then creates an external `O_EXCL` launch claim binding
the observed commit, decision ID, config hash, frozen runner hashes, absolute
run directory, and the byte hashes and row counts of the generation, closed
initial-state, and locked supplemental-state queues and manifests. Every
worker recomputes and validates that complete bundle before adapter creation
or GPU preflight.

The timing-pilot response is not a generation precondition. Human-audit packet
assembly remains fail-closed until its matching ingestion receipt exists.

## Frozen corpus and queue

For each `READY` backbone, the immutable queue contains exactly 1,536
30-second rows: 384 vocal/instrumental `BASE` plus positive-only `FIXED`, 96
instrumental `NEGATION_DIAGNOSTIC`, 480 tempo `BASE` plus `FIXED`, 288
integrity `BASE` plus `FIXED`, and 288 exploratory structure `BASE` plus
`FIXED`. Conditions are ordered `BASE`, `FIXED`, then the instrumental-only
diagnostic; roots are ordered `0..7`. The deterministic queue builder verifies
all prompt hashes, derives registered seeds, and gives every request a
content hash. An actual queue is created once inside a new immutable run
directory and receives its own manifest hash.
The queue files, manifests, and their containing directories are fsynced
before their identities enter the launch claim.

One model request is one model call and one expected output. Operational
shards contain four consecutive queue rows. A shard is a scheduling and
heartbeat unit only: it does not alter prompts, seeds, model calls, or the
prompt-cluster analysis. The first ledgered batch is the first completed
four-row shard. There is no automatic retry, favorable replacement, prompt
rewrite, seed substitution, or duration reduction. A failed row remains a
reason-coded missing row.

The formal eligibility workload is not part of this 1,536-row queue. Two
separate, ledgered state-capture plans are materialized but closed at ordinary
core launch. `INITIAL` contains exactly 36 prompts x roots `0..3` x
checkpoints `25/50/75%` = 432 capture/resume calls per state-capable backbone.
Every row binds the matching core prompt/root request and names only that
root's checkpoint, decoded preview, and resumed terminal output.
`SUPPLEMENTAL` contains the corresponding 432 rows for roots `4..7` and is
labeled
`SUPPLEMENTAL_LOCKED_UNLESS_INITIAL_GATE_IS_INCONCLUSIVE_UNDERPOWERED`.
Opening either plan requires a separate budget, decision, ledger, and worker;
the ordinary backbone bridge rejects state contracts. D-0020 is capability
evidence only, not a completed formal 25/50/75 capture.

Every WAV, adjacent provenance record, sanity record, queue, manifest, and
ledger is retained outside Git in the declared run directory. Nothing is
overwritten. The one exception is each model worker's namespaced
`workers/<model>/heartbeat.json`, which is mutable liveness state and is
replaced atomically; periodic immutable heartbeat snapshots are retained at
shard boundaries. Concurrent model workers never share heartbeat or shard
paths.

## Placement and do-not-preempt rule

Every worker is single-node, one visible A800, TP1, replica count one. A model
call never spans `an12` and `an29`. Before model load, the worker acquires an
exclusive per-device lock, confirms the expected physical device, confirms
that no compute process occupies it, and checks the configured free-memory
floor. The pre-load observation must identify an NVIDIA A800 by name, show no
compute PID, meet the free-memory floor, and be at or below the frozen idle
utilization threshold (at most 5%). After load it permits only the worker's
own PID and checks the configured reserve before the first and every later
call. No probe sends a signal.

Checkpoint/content preflight may be long. The worker therefore repeats the
same no-process, identity, free-memory, and idle-utilization probe after
preflight and immediately before model load. A transient lock, neighbor,
utilization, or headroom condition keeps the process alive in
`QUEUED_WAITING_FOR_SAFE_GPU` with a current heartbeat; it releases any held
lease, sleeps, and checks again. A permanent node, visible-device, or A800
identity mismatch fails closed. No waiting path changes another process.

The worker never terminates, signals, pauses, migrates, or reconfigures an
existing process. If a safe device is unavailable, its queue stays waiting.
If memory headroom becomes insufficient, the worker writes
`PLACEMENT_HEADROOM_BLOCKED`, stops assigning calls, unloads when safe, and
leaves all existing work untouched.

## Hard caps and stop semantics

No worker may exceed 1,536 calls, 1,536 outputs, one GPU, TP1, one replica, or
30.0 seconds per clip. For model `m`, the committed config records measured
`c_m`, duration-normalized `u_m`, scheduled `n_m`, and the preregistered cap:

```text
CORE_GPU_HOUR_CAP_m = [c_m + max(n_m-1,0) * (2*u_m)] / 3600
```

For TP1/one replica, reservations decompose that expression exactly: model
load reserves `c_m-u_m`, the first call reserves `u_m`, and each later call
reserves `2*u_m`. All `n_m` claims therefore sum exactly to the frozen
numerator; load is not added twice. Before assigning another row, the worker
atomically checks and reserves the next bound and stops if it would cross the
cap. Load/cold time and every
CUDA-synchronized call time are measured separately; the ledger never labels
an estimate as observed. A process interruption does not create permission to
rerun an attempted model row. Recovery requires an append-only administrative
decision after inspecting whether a model call began and whether an artifact
was committed.

## Heartbeat, ledger, and terminal states

One resident worker acquires one device lease, reserves and loads once, then
processes consecutive four-row shards. It does not exit after the first
shard; `FIRST_LEDGERED_BATCH` is a milestone while that same process
continues. An active worker atomically refreshes `heartbeat.json` at least
every 60 seconds, including during model load. It contains run ID, node, physical and
logical GPU, PID, Git/config/prompt hashes, current shard and row, completed
and failed counts, cumulative synchronized GPU seconds, peak allocated and
reserved VRAM, last ledger hash, and UTC timestamp. At every shard boundary a
hash-named immutable copy is retained. A stale heartbeat makes a supervisor
stop assigning work; it does not kill a call. The resident worker itself
checks the frozen stale threshold before every placement attempt and again
immediately before every durable request claim, so this rule does not depend
on an advisory observer.

Immediately before any adapter call, the worker creates a hash-named claim by
`O_EXCL`, fsyncs it and its directory, and appends fsynced `CLAIMED` and
`CALL_STARTED` ledger transitions. A claim is never removed and forbids an
automatic retry even if the process stops before the first ledger transition.
Valid state paths are `CLAIMED -> CALL_STARTED -> SUCCEEDED/FAILED` or
`CLAIMED -> ABORTED_BEFORE_ADAPTER`; a terminal request cannot transition
again. Recovery requires a new append-only administrative decision and is
not exposed as an automatic worker option.

Every success commits a WAV, adjacent provenance, sanity, and commit marker
without replacement; the marker is last. Partial artifacts remain audit
evidence. Sanity fully decodes the waveform and requires finite, non-silent,
exactly 30-second stereo audio by exact native-sample frame count at the
adapter's frozen native sample rate
(44.1 kHz SA3; 48 kHz ACE-Step v1). Provenance requires actual NFE,
CUDA-synchronized wall time, peak allocated/reserved VRAM, and all relevant
hashes. Failures retain their stage/error and safely committed artifacts. A
strict production bridge maps only the registered content-pinned B2 adapters
into this contract. Concurrent model workers share a race-safe, fsynced,
hash-chained ledger but have disjoint model claim, heartbeat, log, shard, and
artifact paths. The worker states are:

```text
QUEUED_WAITING_FOR_SAFE_GPU
LOADING
RUNNING
PLACEMENT_HEADROOM_BLOCKED
HARD_CAP_REACHED
FAILED_STOPPED
COMPLETE
```

Neither this protocol nor the launcher runs the automatic evaluators, selects
best-of-N, samples human-audit clips, or claims a benchmark result.
