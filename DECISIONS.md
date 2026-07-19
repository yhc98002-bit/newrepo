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
