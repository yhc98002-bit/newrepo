# Execution ledger (append-only)

Entries are appended in identifier order. Existing bytes are never edited or
deleted. Corrections use a new entry with `Supersedes` and retain the original.
Planned work, diagnostic evidence, completed execution, and claimed results are
labelled distinctly. A smoke result is not valid unless its immutable run
manifest and artifacts are named here with SHA-256 digests.

## L-0001 — Governance freeze

- Time: 2026-07-19T19:09:24+08:00
- Kind: completed governance action; no model result
- Git: `0d1318557f05870641aff953abc87820d29be568`
- Node: `ln206`; GPU IDs: none; TP: not applicable; replicas: not applicable
- Seed: not applicable
- Command: `git commit -m 'freeze foundation smoke governance'`
- Config: `SMOKE_PROTOCOL.md` SHA-256
  `84f15494462b99de2d8f8e71b0c90f7cecccbd17e92599d036b2a4785e4e70c6`
- Artifact: frozen protocol and seed registry in the named Git commit
- Deviations: none
- Supersedes: none

## L-0002 — Environment sync and A800 import smoke

- Time: 2026-07-19T19:40:00+08:00
- Kind: completed environment verification; no model result
- Git: `0d1318557f05870641aff953abc87820d29be568`
- Node: `an12`; GPU IDs: `0`; TP: 1; replicas: 1
- Placement: one A800 is sufficient for the 1.4B model; no wider TP justified
- Seed: not applicable
- Command: frozen `uv sync --all-groups`, followed by CUDA allocation and
  `flash_attn_func` kernel execution (exact logs in `environment/runtime.json`)
- Config: `pyproject.toml` SHA-256
  `70ba55cccb73e7cb763faa20bcd94d6c46b0f447cbb7863aa63fdf563513aeb8`;
  `uv.lock` SHA-256
  `c61a7fa1375d6766cceed983b56051b5b3ea7f3dba3769a5ffde1561f05f2b8c`
- Artifacts: `environment/package-freeze.txt` SHA-256
  `da6aae61a6189ee8fc3842fa76652359ff802c6252ce191a199bad5953f98eab`;
  `environment/licenses.json` SHA-256
  `10f99624b8438c1dbc385ca2cec9bebac73ecb96cfe1098af32f4b9be8bd3294`
- Result: PASS — torch 2.7.1+cu126, A800 capability 8.0, finite Flash
  Attention output
- Deviations: runtime relocated to `/HOME` after verified Lustre project-quota
  failure; original checkout retained
- Supersedes: none

## L-0003 — ModelScope-first base-weight acquisition

- Time: 2026-07-19T19:56:32+08:00
- Kind: completed acquisition and cryptographic verification; no model result
- Git: `2b968906a899d044e5c2549beb8aab1184c077d4`
- Node: `ln206`; GPU IDs: none; TP: not applicable; replicas: not applicable
- Seed: not applicable
- Command: `python -m sa3_smoke.acquire <snapshot> <snapshot>/weights.manifest.json`
  after the pinned ModelScope CLI download at revision
  `a9c479f5f28ee89f6fbdaca57b683e6b6c160314`
- Config: `configs/foundation_v1.json` SHA-256
  `42e99699e7c3f8fb56d615086684b10afd4fdc1a8b3f162e37818ec462814a14`
- Artifacts: `provenance/weights.manifest.json` SHA-256
  `3c120446c854e814a172d499af4757a2ed86c985ba9e45f36674ad0242ca1803`;
  18 files, 14,287,668,350 bytes; core `model.safetensors` SHA-256
  `c443fcc4d491475064cd0ff3eb92459b1e5f5060e86d96d016f048e528e24195`
- Logs: ModelScope download SHA-256
  `70ac4170429756d850b3df7eac06f096be6ffc8de9adf133a46797dde9bc93f6`;
  verification SHA-256
  `b6703c2d574bc04cbd17a6cf68451ab00aa5b8510f2ce1ea3a852f431457e3e4`
- Provenance: ModelScope organization label `Stability AI - Mirror` (MIRROR);
  official Hugging Face revision
  `b32993f73c3bdc3864043a72d8032606bba737c8` (UPSTREAM) used for public
  cross-provider file verification only
- Licenses: Stability AI Community License Agreement (weights); Gemma Terms of
  Use and prohibited-use policy (embedded T5Gemma conditioner), with exact
  license hashes in the manifest and canonical links in
  `THIRD_PARTY_LICENSES.md`
- Result: PASS — every expected file matched its frozen byte size and SHA-256
- Deviations: ModelScope mirror source is explicitly labelled; no gated,
  differently named model and no credential were used
- Supersedes: none

## L-0003 — Benchmark cost-evidence and no-audio audit

- Time: 2026-07-19T19:58:19+08:00
- Kind: completed diagnostic evidence; no model result
- Git: `2b968906a899d044e5c2549beb8aab1184c077d4`
- Node: `ln206`; GPU IDs: none; TP: not applicable; replicas: not applicable
- Seed: not applicable
- Commands: repository/report/timing search, process audit, run-directory
  inventory, audio-extension inventory, and remote-ref verification
- Config: `BENCHMARK_PREREG_v1.md` SHA-256
  `2e3d4fc50b8d020953bdbfad861f561fb95d461dc39667e16befc1b61bedbe38`
- Evidence: zero entries under the declared foundation `runs/` directory; zero
  audio files in the repository; no active smoke/generation process; no
  committed foundation report, immutable timing row, or successful
  project-local cost row for any requested benchmark backbone
- Result: `GPU_BUDGET_STATUS = UNMEASURED`; no audio generated
- Deviations: model acquisition/verification logs exist but are not generation
  timings and are not used as benchmark-cost evidence
- Supersedes: none

## L-0004 — Public-upstream cross-provider verification

- Time: 2026-07-19T20:15:04+08:00
- Kind: completed provenance verification; no model result
- Git: `3ca49a6247603a6541ac76cdd190f3a8d68b0e80`
- Node: `ln206`; GPU IDs: none; TP: not applicable; replicas: not applicable
- Seed: not applicable
- Command: unauthenticated `huggingface_hub` metadata and exact-file reads
  through `scripts/with_proxy.sh` at the pinned public revision
- Config: `provenance/weights.manifest.json` SHA-256
  `3c120446c854e814a172d499af4757a2ed86c985ba9e45f36674ad0242ca1803`
- Artifact: `provenance/weights.cross-provider-verification.v2.json`
  SHA-256
  `905bac35a86f98b5db961b7258a31ca2f7a9c47d67760fb9ca110f83013f7dfb`
- Evidence: official Hugging Face revision
  `b32993f73c3bdc3864043a72d8032606bba737c8` reported
  `gated=false`, `private=false`; all 16 substantive files common to the
  mirror and upstream matched byte size and SHA-256
- Provider metadata: root `.gitattributes` differs by provider;
  `configuration.json` is ModelScope-only; embedded-T5 `.gitattributes` is
  Hugging-Face-only. None is loaded by the runtime.
- Logs: final verification SHA-256
  `fd76776b092a56896c8cb3d940f693d9da1e5f952d3193af01dac07886a2c335`;
  official metadata SHA-256
  `b15c79e0ea18c04122cff66d76d0dd2308b33dccdae1177168b203ac449c1c47`
- Result: PASS — the D-0005 cross-provider prerequisite is satisfied without
  a token or interactive acceptance
- Deviations: the earlier diagnostic SHA-256
  `5dadb4d0d2e8e3998b4baf1522352e664a269bbc8e144409f6682db81b2972db`
  stopped on provider metadata and is superseded by the final verification
- Identifier note: two concurrent append-only entries used L-0003. Both remain;
  future references use identifier plus title, and numbering continues here.
- Supersedes: `provenance/weights.manifest.json` only for
  `cross_provider_verified` status; no prior bytes are changed

## L-0005 — Smoke A fixed-seed repeat

- Time: 2026-07-19T21:49:56+08:00
- Kind: completed engineering smoke result
- Git: `ae251c62e2ba2bae025ec4413aae875df967b021`
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: one idle disjoint A800, exposed as `cuda:0`; the 1.4B model fits
  TP1 and no wider placement is justified
- Seed: S-0001 = `73193001`, used for both frozen calls
- Command: frozen production command recorded in `SA3_FOUNDATION_REPORT.md`
- Config: `configs/foundation_v2.json` SHA-256
  `d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`;
  protocol SHA-256
  `84f15494462b99de2d8f8e71b0c90f7cecccbd17e92599d036b2a4785e4e70c6`
- Run: `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`
- Manifest: `smoke-a/manifest.json` SHA-256
  `3f04c863c3420fb6e4635ea2f41ced25e27a95e168f27010ab9809ab9ed373d2`
- Artifacts: `a_fixed_seed_run1.wav` SHA-256
  `d51ba6038216f22b5ca6ef86d11371393b357444a90353d61bb716e2328d98db`;
  `a_fixed_seed_run2.wav` SHA-256
  `4d40ab211db8e10eb1b222093214a3539985917fb71d009006a17fcc4df53729`;
  adjacent `synthetic_model_output` provenance valid
- Result: PASS — both decoded-waveform SHA-256 values are
  `b224f27d374209cfa76ed73b680cede18e9b7920677dbfc0be6afaa2d2a2b387`;
  exact samples, zero error, infinite SNR; both 30 s, 44.1 kHz stereo and
  non-silent
- Measured calls: 100 actual DiT forwards across two 50-step official calls;
  `19.62547130137682 s` cumulative synchronized inner-call wall
- Deviations: WAV container hashes differ because of a timestamp-bearing PEAK
  chunk; decoded audio is identical
- Supersedes: none

## L-0006 — Smoke B official continuation

- Time: 2026-07-19T21:50:00+08:00
- Kind: completed engineering smoke result
- Git: `ae251c62e2ba2bae025ec4413aae875df967b021`
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: one idle disjoint A800, exposed as `cuda:0`
- Seed: S-0002 = `73193002`
- Command/config/protocol: same frozen production command and hashes as L-0005
- Run: `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`
- Manifest: `smoke-b/manifest.json` SHA-256
  `0f465bedecd611f6c3d3030a84a09615a461d481fd0ec58118edc0bda7e36442`
- Artifacts: `b_source_10s.wav` (`derived_audio`) SHA-256
  `09cb40495c52ad9e91afdeb0077e8170263de256802b0e2cea9af2c192cac4d9`;
  `b_continuation_30s.wav` (`synthetic_model_output`) SHA-256
  `23786b4ae87d5ab856af48473f342365cefe29187adb7c47cb5cb95f2713e5a7`;
  adjacent provenance valid
- Result: PASS — official `[10,30]` second continuation mask, valid non-silent
  30 s / 44.1 kHz / stereo output, and non-silent generated region
- Measured call: 50 actual DiT forwards; synchronized inner-call wall
  `3.911749802529812 s`
- Deviations: B's named budget snapshot was captured after C and contains
  combined A+B+C counters; it is not claimed as an immediate post-B snapshot
- Supersedes: none

## L-0007 — Smoke C single- and multi-segment inpainting

- Time: 2026-07-19T21:50:09+08:00
- Kind: completed engineering smoke result
- Git: `ae251c62e2ba2bae025ec4413aae875df967b021`
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: one idle disjoint A800, exposed as `cuda:0`
- Seeds: S-0003 = `73193003` for `[8,12]`; S-0004 = `73193004` for
  `[4,6]` plus `[20,23]`
- Command/config/protocol: same frozen production command and hashes as L-0005
- Run: `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`
- Manifest: `smoke-c/manifest.json` SHA-256
  `f2f568225de66d63a1889d40b98142af742dae585dd6530d81c1f9981b58b210`
- Artifacts: `c_inpaint_single_8_12s.wav` SHA-256
  `84f07feb44a27ac23e794467116070d7807e59be032dd26870e23c3a153ecc61`;
  `c_inpaint_multi_4_6_20_23s.wav` SHA-256
  `f226278085a110282e6fdc3f9b481699eedf4ea54a1a62adf94f3d20a90b1c74`;
  adjacent `synthetic_model_output` provenance valid
- Result: PASS — both masks valid; both outputs non-silent, 30 s, 44.1 kHz,
  stereo, finite, and provenance-valid
- Measured calls: 100 actual DiT forwards; `7.432163719087839 s`
  synchronized inner-call wall
- Deviations: masked/unmasked sample comparisons are frozen diagnostics, not
  preservation acceptance gates
- Supersedes: none

## L-0008 — Smoke D measured NFE and throughput

- Time: 2026-07-19T21:50:18+08:00
- Kind: completed measured engineering cost result; singleton, not a benchmark
- Git: `ae251c62e2ba2bae025ec4413aae875df967b021`
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: one idle disjoint NVIDIA A800 80 GB PCIe, exposed as `cuda:0`
- Seeds: S-0005 = `73193005` for batch one; S-0006 = `73193006` for batch four
- Command/config/protocol: same frozen production command and hashes as L-0005
- Run: `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`
- Manifest: `smoke-d/manifest.json` SHA-256
  `2a7923fa0bf4be95ca18beb3082c483b4d91fd55d1d0118f22c1f0107042f8ec`
- Artifacts: one 30-second and four 10-second `synthetic_model_output` WAVs,
  all retained with hashes and provenance in the manifest/report
- Result: PASS — both official 50-step paths measured exactly 50 actual DiT
  forwards and 50 sampler callbacks
- Batch-one measurement: `3.642550054937601 s` synchronized end-to-end wall;
  peak allocated/reserved VRAM `5,439,723,520` / `9,839,837,184` bytes
- Batch-four measurement: `4.866168051958084 s` synchronized end-to-end wall;
  peak allocated/reserved VRAM `5,890,185,728` / `10,464,788,480` bytes;
  `0.8220020265001845` items/s and `8.220020265001844` audio-s/s
- Deviations: inner budget-proxy walls are `3.604426071047783 s` and
  `4.841174870729446 s`; the end-to-end values include measured wrapper overhead
- Supersedes: no prior measured SA3 row; earlier UNMEASURED state remains as
  historical evidence

## L-0009 — Smoke E checkpoint/resume failure

- Time: 2026-07-19T21:52:25+08:00
- Kind: completed terminal engineering smoke result
- Git: `ae251c62e2ba2bae025ec4413aae875df967b021`
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: one idle disjoint A800; parent fully offloaded to CPU before
  sequential children
- Seed: S-0007 = `73193007` for the reference and all three resume calls
- Command/config/protocol: same frozen production command and hashes as L-0005
- Run: `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6`
- Manifest: `smoke-e/manifest.json` SHA-256
  `7d5a25e083e5cdf2385c3505b1896e8e512efc1f78a3082bc76d347a85103495`
- Artifacts: valid 30-second reference WAV SHA-256
  `476aaea35e40de0cdd8983ec95f02403f46f74f56610b5af98255e1fedf2fecc`;
  valid `latent_checkpoint` files after 15/30/40 steps with SHA-256s
  `52acec3c52d4f580978222a6f392fe9577cb6e1094719a1505cfd6a62671eee1`,
  `95b31c86f4ae909f7009739fe20705cf0cd6c957c857c2cb303583b38b77033d`,
  and `acadb11a0d17204370c41d120b09af322bc10388ba7a20600481191a1dc589f5`
- Result: FAIL — child PIDs `1959026`, `1961040`, and `1962942` each stopped
  with `CheckpointValidationError` because fresh official FP16 noise did not
  equal the saved FP32 post-transition latent dtype; each had actual resumed
  DiT NFE `0`
- Tolerance: max absolute error `<= 1e-5` and SNR `>= 80 dB`; unmeasured
  because no resumed waveform exists, not reported as a numerical mismatch
- Budget: all 11 calls and 14 slots consumed; eight calls succeeded, three
  failed; final synchronized official-call wall `46.01308351755142 s` and
  conservative one-GPU residency `244.181992349 s`; all hard caps respected
- Deviations: the manifest's top-level `terminal_failure` summary is null, but
  all three nested errors and terminal ledger rows are retained; no retry or
  overwrite occurred
- Supersedes: none; aggregate status is `FAIL_ESCALATED`

## L-0010 — Smoke E bounded dtype-boundary retry PASS

- Time: 2026-07-20T22:06:22+08:00
- Kind: completed terminal engineering repair smoke; not a benchmark result
- Authority: D-0019; fixed claim consumed, no second retry
- Git: `dd65740782f268e0df21a2a22efe9faa3ab12962`, clean and equal to
  `origin/main` at execution
- Node: `an12`; physical GPU IDs: `4`; TP: 1; replicas: 1
- Placement: device lock held; immediately before claim, one visible A800 had
  zero compute processes, 81,223 MiB free, and 0% utilization
- Seed: S-0007 = `73193007` for the fresh reference and all three children
- Command: `scripts/run_smoke_e_retry_d0019.sh`; inner recorded command is
  `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m
  sa3_smoke.run_smoke_e_retry --config
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo/configs/smoke_e_retry_v1.json
  --repository-root
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo`
- Config: retry control SHA-256
  `39553c595659e29e3c0fa691c0d47f344421548ca3ac12157c01fac32a716c84`;
  retry protocol SHA-256
  `1a2892b70029bea1e36722145dceea32a814e5a00d917a98c0cb17d4582cd0a0`;
  generation config SHA-256
  `d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f`
- Run: `sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24`
- Claim SHA-256:
  `32bd53e6e6421acede70f2f01e07e50c55abb4a918ee5ef6c2b50b6c3a6fc092`
- Result / manifest SHA-256:
  `10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117` /
  `27978939dbdef2276f5892f222eeaf9263122c4850cfe21a8f72baffc1da070f`
- Checkpoints: fresh exports at 15/30/40 steps, FP32 shape `[1,256,388]`,
  SHA-256s
  `066c6a4673fa0a37751c5de115c31fb43149dcfc2c335c65b33da4fcfda78582`,
  `25e11b2770b568f5e1d7187667581eaf96989a7cd28245b5d422ddbbe5b4b011`,
  and `64564ee934755a131d33ca56e0725b361167f3d3ec4c90d1cc4a853fdb429ffc`;
  latent hashes match the corresponding D-0017 checkpoint states
- Outputs: reference plus step-15/30/40 resumes have WAV SHA-256s
  `6bda5c51ee57c952badce63827c5c11e2be2edded1ce92c984ba240b9aa3dd0f`,
  `60680081e5efda91b12e25505e0ed16c81a5234d28982d523c96d20d4dc7e859`,
  `1cff775d63c9d69d4f526ae3d208ce7c17b12c878d64fb35b7b7ecd4fff3c663`,
  and `725c9881394a602580d8b53b1a83f8fc08377e79d7b9428c3e1dd73b85a31dc5`
- Result: PASS — fresh initial dtype FP16, checkpoint/resume dtype FP32
  preserved without cast, distinct child PIDs, exact remaining NFE 35/20/10,
  and exact decoded-array equality for all three resumes (zero error, infinite
  SNR); every WAV is finite, non-silent, stereo, 44.1 kHz, 30 seconds, and
  provenance-valid
- Measured cost: actual NFE `50/35/20/10` = 115 total; synchronized call wall
  `25.023961771279573/3.7141848169267178/2.7067666836082935/
  1.8672252222895622 s` = `33.31213849410415 s`; peak allocated/reserved VRAM
  `5,438,810,112 / 9,839,837,184 B`; model load `91.32002927735448 s`;
  conservative one-GPU residency `249.481707109 s`
- Budget: exactly four E calls and four outputs, zero failures, four PASS
  hash-chained ledger rows; ledger SHA-256
  `b9c70678a6198530d2c913d873b3033ebc5ca88dbcc79f11b4961c28695a3024`;
  caps 8 generations, 30 seconds, one GPU, 540 GPU-seconds all respected
- Deviations: after the Python runner wrote PASS and released the GPU, the
  outer wrapper returned 1 because its optional operational-log provenance
  record omitted a timestamp and used a non-policy label. The read-only log is
  retained at SHA-256
  `0054143ae79877097c890c5e3df11bf001c5bc08e614f3a152cef887152b6579`;
  no model call or immutable run artifact was retried or changed
- Supersedes: L-0009 only for latest foundation/preflight state-capability
  evidence; the original failure and five-smoke `FAIL_ESCALATED` run remain
