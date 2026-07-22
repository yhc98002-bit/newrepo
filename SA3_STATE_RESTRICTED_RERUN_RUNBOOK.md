# SA3 restricted state rerun runbook

This runbook describes the D-0035 control plane. It does not authorize a run by
itself. The Stage-1 result and cancellation summary must exist at the absolute
paths frozen in `configs/sa3_state_restricted_rerun_v2.json`, and D-0035 must
bind those prospective paths plus the config SHA-256 exactly. Preparation
verifies and records the observed Stage-1 hashes at launch; D-0035 does not
predeclare hashes for artifacts that do not yet exist.

## 1. CPU-only preparation

From a clean, pushed `main` checkout, using the project Python 3.10 environment:

```bash
PYTHONPATH=src:. python scripts/prepare_sa3_state_restricted_rerun_v2.py \
  --decision-id D-0035
```

Preparation performs no CUDA probe and no model import. It validates the
original queue/failure evidence, the Stage-1 result, and every cancellation
event, then creates the sole fixed run ID and an `O_EXCL` attempt claim. If the
Stage-1 terminal files are absent or any binding differs, it stops before the
run or claim is usable.

## 2. One-root validation

Read `control/stage1-survivor-execution-plan.json`. Locate
`validation_group_request_sha256` in the immutable source
`prefix-groups.jsonl`; its owner is `(group_sequence - 1) % 4`. On `an12`, use
one safely idle GPU from 4–7 and the matching replica index:

```bash
CUDA_VISIBLE_DEVICES=<gpu> PYTHONPATH=src:. python \
  scripts/run_sa3_state_restricted_rerun_v2.py \
  --run-dir <fixed-run-dir> \
  --phase validation \
  --replica-index <owner> \
  --physical-gpu-id <gpu>
```

Continuation remains closed until all three resume units and their prefix group
are `SUCCEEDED` in the new hash-chained ledger and
`control/one-root-validation.pass.json` exists.

## 3. Survivor continuation

After validation PASS, up to four independent TP1 workers may run on idle
`an12` GPUs 4–7, one static replica index per GPU:

```bash
CUDA_VISIBLE_DEVICES=<gpu> PYTHONPATH=src:. python \
  scripts/run_sa3_state_restricted_rerun_v2.py \
  --run-dir <fixed-run-dir> \
  --phase continuation \
  --replica-index <0..3> \
  --physical-gpu-id <gpu>
```

`--max-new-groups N` may bound a continuation batch. This is batching within
the same authorized run, not another repair. STOP-axis groups and units never
enter a worker allowlist. Any execution failure writes the global immutable
`restricted-rerun-failure.terminal.json`; all later claims and commits fail
closed, and the fixed run ID plus attempt claim prevent a third repair.
