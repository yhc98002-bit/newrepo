# SA3 Foundation Smoke

Engineering-only validation for `stabilityai/stable-audio-3-medium-base`.
This repository contains no detector, constraint, policy, or scientific
experiment work. Acceptance rules are frozen in `SMOKE_PROTOCOL.md` before any
model result is produced.

The repository obeys three project invariants:

1. Rules are frozen before results.
2. Artifacts and records are superseded, never overwritten.
3. Every data artifact carries a provenance label.

See `SA3_FOUNDATION_REPORT.md` for the terminal smoke status. Generated audio,
weights, logs, and latent checkpoints live in ignored immutable directories on
persistent project storage; committed manifests and the report identify them
by path and SHA-256.
