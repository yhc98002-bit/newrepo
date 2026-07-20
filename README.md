# Prospective audio benchmark engineering

This repository contains the frozen Stable Audio 3 foundation smoke and the
prospectively frozen benchmark-v2 design, instruments, backbone gates, prompt
sets, rater builders, and fail-closed execution harness.

The project obeys three invariants:

1. Rules are frozen before results.
2. Artifacts and records are superseded, never overwritten.
3. Every data artifact carries a provenance label.

Key records are:

- `BENCHMARK_PREREG_v2.md` — frozen prospective benchmark design;
- `BENCHMARK_LAUNCH_REPORT.md` — Phase A/B receipts and ordinary-core launch
  milestone;
- `BENCHMARK_CORE_PROTOCOL_v2.md` — immutable queues, placement, ledger,
  heartbeat, and no-retry rules;
- `SA3_FOUNDATION_REPORT.md` — terminal foundation-smoke evidence;
- `DECISIONS.md` and `LEDGER.md` — append-only governance and execution state.

Generated audio, weights, logs, and latent checkpoints live in ignored,
immutable directories on persistent project storage. Committed manifests and
reports identify them by path and SHA-256. Core generation does not itself
score a benchmark endpoint, and human-audit packet assembly remains gated on
timing-pilot ingestion.
