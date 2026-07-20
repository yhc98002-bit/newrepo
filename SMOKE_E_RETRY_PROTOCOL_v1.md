# Smoke E bounded repair retry protocol v1

Status: frozen prospectively by D-0019. This protocol authorizes exactly one
engineering retry of Smoke E. It does not authorize Smokes A–D, a benchmark,
formal Section 11 captures, detectors, constraint experiments, or policy work.

## Failure and repair boundary

The immutable D-0017 run failed because each fresh official child supplied a
disposable FP16 initial noise tensor while the saved post-transition latent was
FP32. The checkpoint itself was valid. The reviewed repair exports the evolved
latent in its runtime dtype and, on resume, moves that saved latent to the
runtime device without a dtype cast. The fresh noise values and dtype are
recorded but are not substituted for checkpoint state. A cast of checkpoint
state back to FP16 is forbidden because it would alter the numerical path.

## Frozen execution

- Use the pinned foundation v2 generation configuration and S-0007 =
  `73193007` unchanged: 30 seconds, 50 Euler transitions, CFG 7, Euler sampler,
  six seconds of duration padding, chunked decode, and the frozen prompts.
- Execute one fresh uninterrupted official generation, exporting checkpoints
  after 15/30/40 completed transitions (30/60/80%).
- Resume each checkpoint through the official `StableAudioModel.generate` API
  in three sequential, fresh Python processes. Expected remaining actual DiT
  calls are 35/20/10.
- Exact authorized plan: four official calls and four generated WAVs, all Smoke
  E / S-0007. No implicit retry and no fifth call.
- Hard guards: `MAX_GENERATIONS = 8`, `MAX_CLIP_SECONDS = 30`, `MAX_GPUS = 1`,
  and `MAX_GPU_SECONDS = 540`. The 540-second claim-bound residency limit is
  stricter than the PI's 600-second maximum. Each child is additionally limited
  to 120 seconds or the smaller remaining claim allowance. The live command is
  wrapped in a 600-second process-group deadline; D-0019 supersedes D-0013's
  finish-the-current-call behavior for this retry only.
- Run on `an12`, physical GPU 4, TP1, one replica. Hold the device-specific lock
  throughout; immediately before claim creation verify one visible A800, no
  compute process, at least 60,000 MiB free, and no more than 5% utilization.
- Claim creation is the retry-consumption boundary. The fixed claim is never
  deleted or reused.

## PASS rule

Smoke E passes only if every condition below passes:

1. The reference exports exactly three no-clobber checkpoints at 15/30/40 with
   valid file/tensor hashes, full schedule, conditioning/config identities,
   adjacent `latent_checkpoint` provenance, and an observed FP32 runtime latent
   dtype.
2. Each child has a unique PID distinct from the parent, validates its rebuilt
   full schedule, records fresh initial dtype FP16, preserves checkpoint/resume
   dtype FP32 without a cast, uses official sampler injection, and measures
   exactly 35/20/10 remaining DiT forwards.
3. The reference and every resumed WAV are retained, finite, non-silent,
   stereo, 44.1 kHz, and 30 seconds, with valid adjacent
   `synthetic_model_output` provenance.
4. Each resumed decoded waveform has maximum absolute error `<= 1e-5` and SNR
   `>= 80 dB` versus the uninterrupted reference. Zero error is infinite SNR
   and passes.
5. The shared budget terminates PASS with exactly four calls, four generated
   and ledgered outputs, no failed call, positive measured NFE/wall/VRAM for
   each call, one visible GPU, and both measured call time and conservative
   residency within 540 seconds.

If any condition is absent or fails after claim creation, the one retry is
exhausted: `SMOKE_E = FAIL` and `SA3_STATE_CAPABILITY = NOT_IDENTIFIABLE`.
There is no second retry. On PASS, `SMOKE_E = PASS` and
`SA3_STATE_CAPABILITY = PASS`. Either branch leaves benchmark execution closed
and preserves the original five-smoke `FAIL_ESCALATED` run as history.

## Evidence and retention

The immutable run retains the retry config and protocol identities, Git state,
environment and weights provenance, live placement probe, claim, budget state,
hash-chained generation ledger, model-config resolutions, requests, checkpoints,
results, WAVs, adjacent provenance, sanity checks, waveform comparisons,
measured NFE/wall/VRAM, terminal manifest, and terminal result. The project
report, append-only decision/ledger records, and preregistration factual
state-capability rows are updated only after the run is terminal.
