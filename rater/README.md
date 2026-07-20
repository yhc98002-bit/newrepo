# Blinded rater and timing-pilot tools

The offered v2 timing pilot is an immutable nine-presentation packet copied
from retained foundation WAVs. It makes zero model calls and is not benchmark
evidence. Open this file directly in a browser:

`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo_runtime/timing-pilot-bundles/benchmark-v2-blinded-timing-pilot-04-51ebc904242e/index.html`

Complete all items, choose **Export response JSON**, and return only that JSON.
The page embeds its public bundle data and uses relative audio URLs, so it works
under `file://` without a web server. The public directory contains no source
paths, automatic values, conditions, seeds, strata, or repeat identities. Its
private administrative map is stored in the separate restricted
`timing-pilot-admin` tree.

Bundles 01–03 are retained for provenance but are
`SUPERSEDED_RETAINED_DO_NOT_USE`. Do not rate them. Bundle 04 adds the frozen
intentional-musical-content response and strict PI-attestation workflow.

## Ingestion and the human-packet gate

`ingest_timing_pilot.py` accepts only a complete schema-v2 response in exact
packet order plus a separate strict PI attestation passed with
`--attestation`. The attestation binds the bundle/build/response hashes,
required identity and matching typed signature, UTC signing time, exact UI
minutes, usability PASS, an empty deviation list, and the affirmation frozen
in `schema_v2.json`. Missing or inconsistent attestation fails before a
receipt is created. Response validation rejects ambiguous JSON, nonfinite
values, short playback, decreasing or out-of-window taps, insufficient taps,
mismatched tap counts, and labels outside the frozen sets. Integrity responses
carry defect labels and an independent intentional-musical-content Boolean.
The resulting immutable receipt binds the attestation hash and records the
full session time, including instructions and pauses.

Human-packet assembly remains
`BLOCKED_ON_TIMING_PILOT_INGESTION`. Benchmark generation is independent of
that gate. After a valid receipt exists, `build_human_packet.py` recomputes the
conservative PI-time projection and stops if it exceeds 180 minutes.

The future selector consumes a strict automatic-only candidate index with
top-level keys `schema_version`, `primary_backbones`,
`source_ledger_sha256`, and `rows`. Its row contract is exported as
`CANDIDATE_ROW_KEYS` in `build_human_packet.py`. It implements the frozen voice
and tempo slots, defect-separated integrity flagged/clean-side strata, two
sharp/percussive controls, three blocks, and the per-backbone 2/2/1 hidden
repeats. Empty integrity strata are recorded as `STRATUM_EMPTY` and never
cross-filled. Public packet artifacts and the blinded administrative map are
written to separate no-clobber roots.

Voice candidates transport mixture RMS, Demucs vocal-energy ratio, and PANNs
maximum; the builder reloads the canonical hash-bound promotion artifact and
recomputes the gate-aware combined margin. Integrity candidates transport the
raw DSP scalars plus each dropout constraint vector; the builder recomputes
every defect flag and normalized margin. Any supplied-result mismatch is
rejected, and severity/distance ranks before cluster tie-breaking.
