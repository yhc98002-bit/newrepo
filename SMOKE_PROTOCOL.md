# SA3 foundation smoke protocol v1 (frozen)

- Frozen: 2026-07-19, before model results
- Target: `stabilityai/stable-audio-3-medium-base`
- Official interface: `stable-audio-3`
- Base path: 50 steps, Euler sampler, CFG 7.0, 30 s unless stated
- Expected decoded audio: stereo, 44,100 Hz
- Placement: one A800, one process, TP1, one replica; the 1.4B model fits on a
  single A800 and no cross-node execution is justified.

This file is immutable. A changed criterion requires a new protocol document
that explicitly supersedes version 1.

## Terminal status rules

Each smoke terminates as `PASS`, `FAIL`, or `BLOCKED_ON_LICENSE`. The report is
`PASS` only if all five smokes pass and the repository test suite passes. It is
`FAIL_ESCALATED` if any executed smoke or required test fails. It is
`BLOCKED_ON_LICENSE` when a required file in the exact requested base snapshot
needs interactive terms acceptance or a token. At that gate, do not
authenticate, accept terms, or use an alternate copy to evade the gate. Stop
model acquisition/execution, record the HTTP/provider evidence and exact human
steps, and mark every unstarted smoke terminally blocked. An immutable local
config copy may resolve the verified conditioner already embedded in that exact
public base snapshot; the original, diff, and hashes must be retained and the
loading deviation reported.

## Common artifact and audio checks

Every run must have an immutable manifest containing node, GPU IDs, TP width,
replica count, placement justification, exact command, repository Git hash,
configuration SHA-256, seed ID/value, package freeze SHA-256, model artifact
SHA-256s, start/end timestamps, artifact paths, and deviations.

Every output WAV is retained and re-opened from disk. It passes sanity only if:

- decoding succeeds and all samples are finite;
- sample rate is exactly 44,100 Hz and channels are exactly two;
- sample count is exactly `round(requested_seconds * 44100)`;
- full-waveform RMS is greater than `1e-5`, peak absolute amplitude is greater
  than `1e-4`, and at least `0.1%` of samples have magnitude greater than
  `1e-4`;
- the WAV has a valid adjacent provenance record whose recorded SHA-256 matches.

Canonical decoded-waveform hashes cover sample rate, tensor shape, and
little-endian contiguous float32 sample bytes after WAV reload. File hashes are
recorded separately. Clipping fraction and DC offset are measured but are not
pass/fail criteria in this engineering smoke.

## A — Fixed-seed text-to-audio

Run the 30 s base path twice with seed S-0001 and identical frozen arguments.
Both WAVs must pass common checks. PASS requires identical canonical decoded
waveform SHA-256s. If hashes differ, report maximum absolute error, RMS error,
and SNR; `max_abs <= 1e-5` and `SNR >= 80 dB` define diagnostic numerical
closeness only and do not turn a hash mismatch into PASS. Potential sources to
record include CUDA reduction order, Flash Attention kernels, PyTorch kernel
selection, hardware/driver changes, and half-precision arithmetic.

## B — Official continuation API

Create and retain an exactly 10 s `derived_audio` source clip, then call the
official inpainting/continuation parameters with mask `[10, 30]` and output
duration 30 s using S-0002. The full output and the continuation region from
10–30 s must independently meet the non-silence thresholds; the full WAV must
pass all common checks. Record prefix error metrics without imposing a fidelity
threshold because that would be a model-quality experiment outside this smoke.

## C — Official inpainting API

On a retained generated 30 s source, run one repair with mask `[8, 12]` using
S-0003 and one repair with masks `[4, 6]` and `[20, 23]` using S-0004. Both
official API calls, mask validation, common checks, and provenance must pass.
Record masked and unmasked error metrics as diagnostics only.

## D — NFE and cost instrumentation

For a batch-one 30 s, 50-step base run using S-0005, count actual Python-level
invocations of the diffusion backbone and actual sampler callbacks; do not infer
either from requested steps. Synchronize CUDA around `perf_counter` wall-time.
Reset CUDA peak statistics immediately before generation and record baseline,
peak allocated, and peak reserved bytes. Retain its audio.

Run one batch-four, 10 s, 50-step base measurement using S-0006 on the same A800.
Record measured wall-time, peak memory, items/s, and generated-audio-seconds/s;
retain and validate all four WAVs. PASS requires complete measured fields,
positive counts/times/throughput, four valid outputs, and provenance. No assumed
NFE or hardware estimate may substitute for a measurement.

## E — Latent checkpoint/reload

Use S-0007 and the upstream Euler transition. Export no-clobber sampler state
after completed steps 15, 30, and 40 (30%, 60%, and 80% of 50), including the
current latent, full schedule, next step index, dtype/shape, conditioning/config
identity, and hashes. For each checkpoint, launch a separate OS process that
loads the model and checkpoint, recomputes the identical conditioning, performs
only the remaining transitions, decodes, and writes a retained WAV.

Compare each reloaded result with one uninterrupted reference. PASS requires
all three child process IDs differ from the reference process, every checkpoint
and WAV has provenance, common audio checks pass, and each waveform has
`max_abs <= 1e-5` and `SNR >= 80 dB`. Exact hashes are recorded when achieved;
the numerical tolerance accounts only for process-local floating-point kernel
variation.
