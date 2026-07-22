# Stable Audio Open dedicated-environment repair report

Status: `CPU_VALIDATED_READY_FOR_GOVERNED_MINI_SMOKE`.

This report records engineering validation only. It is not a model-capability result, no
benchmark endpoint was scored, and no Stable Audio Open output was generated during this repair.
The complete machine-readable receipt is
`provenance/b2/sao_environment_repair_v2.json`.

## Outcome

The official `stabilityai/stable-audio-open-1.0` snapshot at revision
`f21265c1e2710b3bd2386596943f0007f55f802e` is now usable from a dedicated offline
environment:

`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/environments/sao-v2/sao-env-v2-002`

The CPU gate passed NumPy, PyWavelets, Stable Audio Tools, the model factory, the SAO adapter,
all required audio/conditioner imports, and an actual CPU construction of the official model
graph. The graph had 1,213,337,474 parameters, sample rate 44,100 Hz, and factory construction
took 31.749 s with peak RSS 6,611,600 KiB. CUDA remained unavailable, the checkpoint was not
loaded, and generation calls remained zero.

The exact 85-package freeze is retained at:

`/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/sao-live-v2/engineering/sao-engineering-env-v2-002/provenance/package-freeze.txt`

Its SHA-256 is
`705a0c9d8be50b23b118422e00256661ac837780dec544755dec9dce228dd108`.
The environment manifest includes every installed distribution's version, source URL,
requirements, metadata hash, RECORD hash, and import location. Its SHA-256 is
`45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f` and its internal
identity is `43af5c1f9979dc2873dc7d1ac7fb98812d3e4d0cb98dc43f37981eaeaf23bf1c`.

## Root causes and narrow repairs

The retained `sao-mini-smoke-v2-002` attempt reached one model-call boundary but emitted no
audio. Its terminal receipt records the PyWavelets 1.4.1 / NumPy 2.2.6 binary-ABI error and is
unchanged at SHA-256
`3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097`.
This is a pre-scientific engineering failure, not a Stable Audio Open outcome.

The registered Stable Audio Tools 0.0.20 source archive at commit
`3241adba4fc2a85cf5b29d9eb68d42f40a28e820` pins PyWavelets 1.4.1. The repaired environment
therefore retains that exact PyWavelets version and installs the official NumPy 1.26.4 CPython
3.10 manylinux wheel (SHA-256
`ffa75af20b44f8dba823498024771d5ac50620e6915abac414251bd971b4529f`) to preserve the
matching NumPy 1.x C ABI. No PyWavelets upgrade or scientific dependency substitution was made.

The first dedicated environment, `sao-engineering-env-v2-001`, then exposed a separate factory
import defect before graph construction: the registered Stable Audio Tools commit imports LoRA
training callbacks unconditionally while declaring `pytorch-lightning` only in the `train`
extra. That immutable failure receipt has SHA-256
`cb7df87510b2314361b2d5fa177fbc196870d64962d82ce27e994f9781c0a6ac`.

The second environment applies
`environment/sao/stable_audio_tools_inference_import.patch`, SHA-256
`df732865be587fa63fca797cdc19679254b15a86c30b0575b701a0a51c3677c1`.
The patch only makes the absent `pytorch_lightning` training callback optional for inference;
it re-raises every other callback import error and leaves the LoRA loader, model math, weights,
prompts, seeds, sampler, step count, duration, and acceptance rules unchanged. The upstream file
changed from SHA-256
`ec32c74f7884a0928889aaef90a054229a8fa2354eb001fae9f8e9222775cbf1` to
`104174f6acabb438e652fe3c76889988dee4b9e5f38b8d2d9893a47f01ace595`.

## Offline and secret hygiene

Both environment construction and CPU validation used local caches/artifacts only. The official
snapshot had already been acquired; no Hugging Face token was read, restored, printed, logged,
or committed. The CPU manifest explicitly records `network_used=false`, `token_used=false`,
`gpu_used=false`, and `generation_calls=0`.

The access receipt for the accepted Stability AI Community License has SHA-256
`41f4ac3200c5292ac4f93a992e789031f7a7180f372fb1c3c32a605b91f37b52` and binds the official
snapshot-manifest SHA-256
`68e9e340df05259ba0510bfcaad4ed697ee6fdb9ecc79d479e71898169726e81`.

## Governed next attempt

The intended next run is `sao-mini-smoke-v2-003`; at report time neither its run directory nor
its claim exists. It must be opened in one new append-only decision after these exact sources are
integrated and pushed cleanly. `scripts/run_sao_engineering_retry_v2.py` validates the CPU
manifest and old failure lineage before reserving a device, verifies the offline adapter
preflight before CUDA use, and writes an atomic one-shot claim only after an idle-device check.
The old D-0042 runner is deliberately unchanged.

The v2-003 claim fixes this attempt's run ID and exact three-call schedule. It does not reinstate
a blanket engineering stop: a later pre-scientific engineering failure remains repairable only
through another sequential run ID, immutable predecessor record, append-only opening, and new
claim. A valid end-to-end capability failure remains a scientific stop for PI review.
