# Provenance policy

## Required labels

Every data artifact must be classified as exactly one of:

- `external_upstream`: acquired without transformation from an identified
  upstream revision (for example model weights or configuration).
- `synthetic_model_output`: waveform produced by the declared model and run.
- `derived_audio`: deterministic transform of named parent audio, such as the
  10 s continuation source clip.
- `latent_checkpoint`: sampler state exported from a named parent run.

Every weight file is listed in an immutable `weights.manifest.json`. Every WAV
and latent checkpoint has an adjacent `<filename>.provenance.json`. Each record
contains the label, SHA-256, byte size, creation time, creating command/run ID,
upstream or parent identifiers, model revision, license identifier, and any
transformation. Missing provenance is a smoke failure.

## Source order and gates

Use ModelScope first. Hugging Face is a fallback only when the exact official
artifact is absent or unverifiable on ModelScope. Record repository ID, immutable
revision, resolved URL/provider, upstream filename, and SHA-256; a mutable name
alone is insufficient. Interactive license acceptance and token-gated access
are human gates and must not be bypassed.

## Immutability

Run directories use a unique UTC timestamp plus random suffix and are created
with no-clobber semantics. Artifact writers use exclusive creation. A rerun
creates a new directory and provenance chain; it never reuses an output path.
Superseding records name their predecessors without modifying them.
