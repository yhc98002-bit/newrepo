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

## L-0011 — B2 ACE-Step v1 an29 preclaim placement refusal

- Time: 2026-07-21T01:17:07+08:00
- Kind: completed preflight refusal; no model result
- Authority: D-0021 bounded B2 engineering package
- Git: `d70a66959eed819dbfb3808ec59767bd5c096b26`, clean and equal to
  `origin/main`
- Node: `an29`; intended physical GPU ID: `4`; TP: 1; replicas: 1
- Placement evidence: GPU 4 was an idle A800 with 81,226 MiB free and 0%
  utilization, but node-local `/tmp` had only 20 KiB and 348 inodes free
- Result: `REFUSED_PREFLIGHT` before device lock; zero global claims, zero
  per-call claims, zero model calls, and zero outputs
- Authorization SHA-256:
  `4fd2016a2ec5342e2cd09dec56e30040b7381755180c220c305846a6a8a7dcec`
- Refusal record SHA-256:
  `2b6315e08152e3f4f414ee854aeebbd6bb2dcf9dd645a2f5156285b5dbf933be`
- Deviations: the same still-unconsumed plan was relocated to `an12`; no
  generation, call retry, or artifact replacement occurred in this row
- Supersedes: none

## L-0012 — B2 ACE-Step v1 terminal failed-sanity cost row

- Time: 2026-07-21T01:24:12+08:00
- Kind: completed terminal engineering mini-smoke result; not a benchmark
- Authority: D-0021; global one-shot claim consumed, no retry
- Git: `d70a66959eed819dbfb3808ec59767bd5c096b26`, clean and equal to
  `origin/main` at execution
- Node: `an12`; physical GPU ID: `4`; TP: 1; replicas: 1
- Placement: one idle A800 with 81,226 MiB free and 0% utilization before
  lock/claim; neighboring GPU 0–3 processes were not changed
- Seed: S-0008 = `73193008`; call 1 / S-0009 was not reached
- Run: `b2-ace-v1-mini-smoke-v2-001`
- Global/call claim SHA-256s:
  `deb9d1c3bff85f96fe162f624a52e54b3b9cc94f84e620efd58d65152a545084` /
  `93fc96218ef13524237f3a67d2313fed6e18e6dd55c9a919cabcc63198ae0123`
- Artifact: retained `call-00.wav` SHA-256
  `1a86fb30dceeb03f5da4e0bcb1cbf488aa2fc7490ac1c8297125e451635bd458`;
  adjacent provenance SHA-256
  `881f09abeb1b4aa103db37125dc3017aa289f6a8b0e6d493b5f15568eaa70f4b`
- Result: `FAIL_ESCALATED` — finite, non-silent 48-kHz stereo audio had
  1,435,551 frames (`29.9073125 s`) instead of the exact 1,440,000-frame
  requirement; no automatic evaluator or human label was run
- Measured failed-call cost: actual NFE 45; CUDA-synchronized wall
  `27.25068249553442 s`; load wall `182.45191994681954 s`; peak
  allocated/reserved VRAM `8,371,735,040 / 10,085,203,968 B`;
  ledger `cost_status = MEASURED`, excluded from launch calibration
- Generation ledger / terminal result SHA-256s:
  `d6b9aa821f8a4031b370ec267c864a3bbe5d68f8fb8fed26efad4cdc58b9c627` /
  `66c4aafd3dc1d7c8da774d539f003fe03c94ae276e248d85386411461a693df0`
- Budget: one of at most two calls, one of at most two outputs, one GPU,
  30-second request, no retry; all D-0021 caps respected
- Placement justification: ACE-Step v1 fits one A800 and the serial
  engineering smoke uses TP1/R1; no wider placement was needed
- Supersedes: the pre-generation ACE cost status only; terminal queue status
  is `BLOCKED_ON_ENGINEERING_FAILURE`

## L-0013 — Ordinary-core pre-call runtime-validation stop

- Time: 2026-07-21T01:35:32+08:00
- Kind: completed fail-closed diagnostic execution; no model result
- Authority: D-0023 ordinary SA3 core launch
- Git: `c537c124ecd77fc34a20a21df64f2de159ff23b9`, clean and equal to
  `origin/main` at launch
- Node: `an12`; physical GPU ID: `4`; TP: 1; replicas: 1
- Placement: the worker held only the selected idle-GPU lease; no neighboring
  process was changed
- Seed: none claimed
- Command: `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python
  -B scripts/run_benchmark_core_worker.py --config
  configs/benchmark_core_v2.json --model-id
  stabilityai/stable-audio-3-medium-base --run-dir
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
  benchmark_v2_runtime/runs/core-v2/benchmark-core-v2-20260720t173000z`
- Config SHA-256:
  `d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61`
- Launch claim / run manifest SHA-256s:
  `f10484ff52460ba53e808f97d8cfa3ef67dba09367e2c2e21cea7c083fa18652` /
  `d8ca94d445326a87b1bf07813438b8a24ea5088649f242616e6f10e19d2ea0cb`
- Terminal heartbeat / worker log SHA-256s:
  `dcd1b7160aa163e7f3ffb57a74770ef17ec33c661cd3d2839f92c784c7185915` /
  `2d12fbf3aa01e27edaf1c4c9639dc76a73611ceaa2dd64058987509b242f8404`
- Result: `FAILED_STOPPED` before adapter load because public torch and
  torchaudio distribution metadata was incorrectly compared to each imported
  module's CUDA local-build identity
- Budget: zero request claims, zero model calls, zero outputs, zero-byte
  shared ledger, and zero synchronized call wall
- Deviations: validator representation defect corrected and reviewed under
  D-0024; this retained run is never reused
- Supersedes: none

## L-0014 — Benchmark v2 ordinary core first ledgered batch

- Time: 2026-07-21T01:51:56+08:00
- Kind: completed launch milestone with retained benchmark audio; no endpoint
  has been scored and the resident run continues
- Authority: D-0024 exact fresh-run recovery package
- Git: `f8a44fedf4a466d8dea43c81f58bc6fdb2f8bae1`, clean and equal to
  `origin/main` at launch
- Node: `an12`; physical GPU ID: `4` exposed as logical GPU `0`; TP: 1;
  replicas: 1
- Placement: one A800 is sufficient for SA3. Before launch the selected card
  had 81,226 MiB free, no compute PID, and 0% utilization; GPU 0–3 neighbors
  were not changed
- Seeds: roots 0–3 = `378480600`, `964092279`, `2141492646`, `1908270312`,
  derived from frozen `prompts/v2/seed_registry.json`
- Command: `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python
  -B scripts/run_benchmark_core_worker.py --config
  configs/benchmark_core_v2.json --model-id
  stabilityai/stable-audio-3-medium-base --run-dir
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
  benchmark_v2_runtime/runs/core-v2/benchmark-core-v2-20260720t174500z`
- Config / launch claim / run manifest SHA-256s:
  `d45e9c6c2ab6326b6dc4cf4c23b55845db59417f3553d00832b33cb8b29e8b61` /
  `b03e25ec7ab098d3c563169626c5b1888c7c0aad619e978575b28090cba096fa` /
  `e3d6e8a11bc4a0dd47cd454823463cb699c76b79671ec4aadc09b4799428f56c`
- Queue: 1,536 ordinary rows, SHA-256
  `afedee0bb422c27c2cad64e7be9dc960384f706f8f9201bbea95e8f2418c7bf4`;
  the 432-row initial and 432-row supplemental state queues remain closed
- First-shard snapshot SHA-256:
  `e0cbcec63a1c400b6798ec0e14b747c65f1c73f51944315a07dc591deb30bea3`
- Result: `LAUNCHED_FIRST_LEDGERED_BATCH` — four completed, zero failed;
  each output is an exact 30-second, 44.1-kHz stereo WAV with sanity,
  provenance, and commit records
- Output WAV SHA-256s:
  `7ebab84222e3498d18e194fed6422ac990550a7b05b691c0921b3c38d3617e88`,
  `d250377495c13ad9bc1b5fdb4399d4cb84b740df9fca93559fbe5f9d7d4ac46e`,
  `a9d6a65e96e48416c721b3dce0684e4518e5299f062bd87658f46593d0d8d3a7`,
  and `4334ed0f55a9b78cc87e613206a56cc95a6715991445ec8db91e1127e86fea43`
- Measured cost at the boundary: load `72.65626287087798 s`; synchronized
  calls `29.783272966742516 s`; NFE 200; peak allocated/reserved VRAM
  `5,437,102,080 / 9,839,837,184 B`
- Budget: one GPU, TP1/R1, four of 1,536 calls completed; full-run cap
  `76,939.90662887692 GPU-s`; no retry or replacement
- Deviations: an initial SSH submission lost its shell variables and was
  rejected before worker creation. The same unconsumed run was started with
  absolute paths; the rejected submission created no request claim, model
  call, ledger row, or audio
- Supersedes: L-0013 only as the latest ordinary-core operational status; the
  failed run and its evidence remain retained

## L-0015 — ACE-Step v1 duration confirmation PASS

- Time: 2026-07-21T16:49:13+08:00
- Kind: completed terminal B2 engineering confirmation; not a benchmark
- Authority: D-0026 sole duration-confirmation call; no retry
- Git: `549f6942599047a579d7561af823adc20154a8d5`, clean and equal to
  `origin/main` at execution
- Node: `an12`; physical GPU ID: `4` exposed as logical GPU `0`; TP: 1;
  replicas: 1
- Placement: GPU 4 was an idle A800 with 81,226 MiB free, no compute PID,
  and 0% utilization immediately before execution; the measured peak
  allocated/reserved VRAM was `8,371,731,968 / 10,085,203,968 B`
- Seed: S-0009 = `73193009`; prompt ID
  `b2-mini-smoke-engineering-ace-02`
- Run: `b2-ace-v1-duration-confirmation-v1-001`
- Result: `PASS` — the 30-second request decoded to 1,435,551 stereo frames
  at 48 kHz (`29.9073125 s`), an exact `0.0926875 s` deviation within the
  inclusive per-backbone `0.25 s` tolerance; all other frozen sanity checks
  passed
- Measured cost: actual NFE `45`; CUDA-synchronized call wall
  `30.9385858848691 s`; load wall `241.99800701066852 s`; one-GPU residency
  `281.0608921535313 s`
- Authorization / authorized-attempt / global / call claim SHA-256s:
  `d0a166c349eb30298d61679f2645b2b5a79b326494363c424fa9facfc3253530` /
  `be7c10cfd2f8240e15b70ccd89957955ee6c18f75a2acf4388004c47fc50e4ef` /
  `bdbde44981fdca3578580dd64256089c6b53b7f7530931ac282940d5e138de25` /
  `2ce0b8c1da213e86fa388ae3e2d64f30c924b5b2d5ce8699dfd26315149e64c5`
- Manifest / generation ledger / terminal result / operational-log SHA-256s:
  `a0ecd2229575e2702dc55c9bc1bb4b679300ddb7a9ec8d8ba6933b4a25af1ce1` /
  `714c40d22ee6f8285feb64e0102d03eef5923d4face628b2c0fb957f913d562e` /
  `213ab5fa2937ae263a1c2fbee1276774755a69d60a0e0032f388ed7677720f75` /
  `34cfe3ba1cf785eebc52ae57ad3fa29e41fb0cf74ca4f8741ad74e7d08308e72`
- Retained WAV / provenance SHA-256s:
  `5070dc1b8916cc0cdc7d8fdf533968e72b5fe4198829546bd01fed4525b3a052` /
  `b1c141a59d3eebded4f7cf587d9325c46328bf4fc9d4d459af10321cec08fe67`
- Budget: exactly one model call, one retained output, one GPU, a 30-second
  request, 281.061 GPU-seconds, and zero retries; all D-0026 caps were
  respected and the authorization is now consumed
- Terminal calibration across both valid ACE observations:
  `u_m = 30.9385858848691 s`, `c_m = 272.93659289553762 s`, and the
  conservative 1,536-call cap is `95,254.39525944367462 GPU-s`
  (`26.459554238734354 GPU-h`)
- Supersedes: L-0012 only for ACE-Step v1 queue eligibility; its original
  exact-frame failure record remains immutable and is re-adjudicated under
  D-0026 rather than rewritten

## L-0016 — ACE-Step v1 incremental core first ledgered batch

- Time: 2026-07-21T17:21:40+08:00
- Kind: completed launch milestone with retained benchmark audio; no endpoint
  has been scored and the resident worker continues
- Authority: D-0027 exact ACE-only incremental launch
- Git: `79d9193b7e67944242395600576d0a3762503ea6`, clean and equal to
  `origin/main` at launch
- Node: `an12`; physical GPU ID: `4` exposed as logical GPU `0`; TP: 1;
  replicas: 1; detached worker PID at launch: `3426125`
- Placement: GPU 4 was an idle A800 with 81,226 MiB free, no compute PID,
  and 0% utilization before launch; no neighboring process was changed
- Run: `benchmark-core-v2-ace-20260721t091500z`
- Command: `/HOME/paratera_xy/pxy1289/.conda/envs/audio-prm/bin/python -B
  scripts/run_benchmark_core_worker.py --config
  configs/benchmark_core_v2_ace_incremental.json --model-id
  ACE-Step/ACE-Step-v1-3.5B --run-dir
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
  benchmark_v2_runtime/runs/core-v2/
  benchmark-core-v2-ace-20260721t091500z`
- Config / launch claim / run manifest SHA-256s:
  `6e4886b235474ea08083b9a01d24d6cddaad8443ce3e0ab3fef49dedfe5ef23f` /
  `9ae7640d42198cd0a985f092d40a06afb63affbdb9963a7ead6c70249ce8a990` /
  `776cf4ed9bd14a6bc1712d3edc85cf21c27694861810fd8353d3895882aab64d`
- Generation queue: 1,536 ACE-only rows, SHA-256
  `db4ce65dabee9219e30a5c22c0eb56ed7b0a6f9e3ebaf98302f725cb8e8fd37f`;
  SA3 is excluded through its COMPLETE receipt
- Initial / supplemental state queues: 432 / 432 prior-SA3 rows, SHA-256s
  `bc03a333e9cb096747ca7d9392a1a33a1c781315b1c1c698b20c888f74ca00c8` /
  `e7eb055e53183f2f6f85bd6ede586e9ed22a390a07cc149bdb121261961da8c1`;
  closed / locked
- First-shard heartbeat / shard record SHA-256s:
  `b76fb604e0151bb88ccda1bc7badfc566db71bd21638143c5606fda8efc93a6f` /
  `1466cec9a528e157a7ead46fcfde879eba357ef10f3149c2af4858e1d41d5ac2`
- Result: `ACE_INCREMENTAL_LAUNCHED_FIRST_LEDGERED_BATCH` — four completed,
  zero failed; each output is 48-kHz stereo at `29.9073125 s`, within the
  inclusive `0.25 s` rule, with sanity, provenance, and commit records
- First-shard seeds: `227666909`, `423452959`, `2008097831`,
  `1601745438` for BASE roots 0–3 of `voice-frame-01-vocal`
- Output WAV SHA-256s:
  `563473b06c7d84a9e550e8ff6ba761d7aa3e82a9945cef12caf33cfd9bd0a5ec`,
  `f2cf0ef8142404b83e3f74d3411a44fbbff4987718d3b4cc63b817fa33ac1f9b`,
  `080659bc3e5ae984604132f0227dd1d475e6b2c47d1ef6cfdce8f3386df7f7ca`,
  and `746610fd7d90029ca45954cbd8378e6db17503bac3a1faa95ba9a04936d32831`
- Measured cost at the boundary: load `123.0669956356287 s`; synchronized
  calls `11.75711365789175 s`; NFE 180; peak allocated/reserved VRAM
  `8,544,569,856 / 10,085,203,968 B`
- Ledger tail at the immutable boundary:
  `4d0a91627c3b4175ee5891ded72ea52f30f4447f5fbb23a9a3d77acb60631fab`
- Budget: one GPU, TP1/R1, four of 1,536 calls completed at the boundary;
  full-run cap `95,254.39525944367462 GPU-s`; no retry or replacement
- Supersedes: L-0015 only for latest ACE ordinary-core operational status;
  the B2 confirmation evidence remains retained

## L-0017 — Stage-1 bounded outcome screen and exact state partition

- Time: 2026-07-22T14:59:07Z
- Kind: completed CPU-only automatic-instrument outcome screen; no model or
  generation call
- Authority: D-0046 policy freeze on pushed
  `5d686cb50eb310557d153fb14d8916d84a37c5c5`
- Node: `ln206`; GPUs: none; TP: none; replicas: none
- Placement: CPU-only because the gate reads existing immutable automatic
  outcome rows and creates only statistical/cancellation artifacts
- Run: `stage1-outcome-gates-v2-001`
- Command: `.venv/bin/python scripts/run_stage1_outcome_gates.py --config
  configs/stage1_outcome_gates_v2.json --decisions DECISIONS.md --output-root
  /XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
  benchmark_v2_runtime/runs/stage1-outcome-gates-v2/
  stage1-outcome-gates-v2-001`
- Config / decision-block SHA-256s:
  `913a87d8286ba91094d2916b3ac9a601afe7e99fa3701803001b13557cca55eb` /
  `6e2ba70431d5aad40e78f288161214f003dc2cdcb54058dbda0901b05c1ab566`
- Result / cancellation-summary / execution-receipt SHA-256s:
  `5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157` /
  `7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121` /
  `3778acf7f495d6036f7a8dabf075996a4d77f34269e264cf27e01be53a559d7c`
- Result: ACE integrity and SA3 vocal/instrumental
  `OUTCOME_SCREEN_PASS`; the other four cells `STOP_AXIS_STAGE1`
- State partition: 144 exact survivor units for ACE, 144 for SA3, and 576
  immutable `CANCELLED_STAGE1` events prohibiting `EXECUTE` and `SCORE`
- ACE / SA3 survivor-units SHA-256s:
  `6ae0d8e13f625bd935e9a285b98c79c24f2469b68706ad7e1ae2e576cb637a1f` /
  `f5d31edfc177d013f240d83540b3d0274eea0a799f9b76fe0ff02395cff1c600`
- Cost: 8.46 CPU wall-seconds, 80,572 KiB maximum RSS, zero GPU-seconds,
  zero model calls, zero generation calls, zero failures, zero repairs
- Retention: 586 material files, all mode 0444; tree SHA-256 excluding the
  append lock
  `e58b6c9722157465cfb922f5a27aa1c67abf05ad64c07dafae3e25815931c958`
- Scientific wording: `AUTOMATIC-INSTRUMENT OUTCOMES`; no human-gold or
  evaluator-accuracy claim

## L-0018 — SA3 state run-001 stopped by zero-call placement audit

- Time: 2026-07-22T15:38:45Z
- Kind: immutable pre-model engineering failure; no scientific outcome
- Authority: D-0035, D-0045, and D-0047
- Git repair boundary: `7e96169802ace009e12fb648e35099a09fa62b5f`, clean
  and equal to `origin/main` before the failure receipt was sealed
- Node: prepared/audited on `ln206`; intended execution node `an12`; GPUs,
  TP, and replicas: none because no worker launched
- Run: `sa3-state-v2-restricted-rerun-001`
- Failure: `PLACEMENT_PUBLICATION_MISSING`; the claim and run manifest did
  not publish exact GPU placement, so the pre-call audit stopped the attempt
- Calls/outputs/GPU time: 0 / 0 / 0 seconds
- Inventory: no worker directory, heartbeat, state ledger, or audio file
- Claim / run-manifest / failure-terminal SHA-256s:
  `0368708a1727043d6c7eac4a52bd0e00b3e2c1e35a7437ddfc1c885bc8ef8ea4` /
  `913e83b2fbd7c1e3ceed5a6944211a3a399929f4ca650b9701cb382016aecf1b` /
  `edd63740e402f3d91224ffb16872ba62f6482c5bfe5a8220174ae2b0e35689ec`
- Disposition: failed attempt retained mode 0444; D-0048 opens only a new
  sequential claim/run with identical scientific bindings

## L-0019 — ACE state run-001 stopped by zero-call path/placement audit

- Time: 2026-07-22T15:38:45Z
- Kind: immutable pre-model engineering failure; no scientific outcome
- Authority: D-0036, D-0045, and D-0047
- Git repair boundary: `7e96169802ace009e12fb648e35099a09fa62b5f`, clean
  and equal to `origin/main` before the failure receipt was sealed
- Node: prepared/audited on `ln206`; intended execution node `an12`; GPUs,
  TP, and replicas: none because no assignment or worker launched
- Run: `ace-state-formal-v2-001`
- Failure: `PLACEMENT_PUBLICATION_MISMATCH_AND_PATH_ALIAS_VALIDATOR`; the
  claim named GPUs 4–7 instead of exact GPUs 5–6, and the validator rejected
  the known hash-identical `/HOME` and `/XYFS01/HOME` mount aliases
- Calls/outputs/GPU time: 0 / 0 / 0 seconds
- Inventory: no supervisor assignment, worker directory, heartbeat, formal
  state ledger, or audio file
- Claim / run-manifest / failure-terminal SHA-256s:
  `cbea38b9123fa27eefefb1b594303fb98fb32b750e3b36831d4ed214d519e960` /
  `3c1339bb4d46f15e0ecb8e61c462490059c1f246273ab9276913343cf0459e26` /
  `4e647f1c3154ea59ad2e2478ba846f5e0c4b41303e8318d52f01368cf2da34dd`
- Disposition: failed attempt retained mode 0444; D-0049 opens only a new
  sequential claim/run with identical scientific bindings

## L-0020 — Stable Audio Open dedicated offline environment validated

- Time: 2026-07-22T15:31:21Z
- Kind: completed CPU-only engineering repair validation; no scientific
  model outcome and no benchmark endpoint
- Authority: D-0045; D-0050 is the separate later GPU opening
- Node: `an12`; GPUs hidden/unavailable; TP and replicas: none
- Environment: `sao-env-v2-002`, Python 3.10.12, 85 installed packages;
  package-freeze SHA-256
  `705a0c9d8be50b23b118422e00256661ac837780dec544755dec9dce228dd108`
- ABI repair: NumPy 1.26.4 official wheel SHA-256
  `ffa75af20b44f8dba823498024771d5ac50620e6915abac414251bd971b4529f`
  with retained PyWavelets 1.4.1
- Optional-import repair: upstream LoRA initializer SHA-256
  `ec32c74f7884a0928889aaef90a054229a8fa2354eb001fae9f8e9222775cbf1`
  to inference-only patched SHA-256
  `104174f6acabb438e652fe3c76889988dee4b9e5f38b8d2d9893a47f01ace595`;
  patch SHA-256
  `df732865be587fa63fca797cdc19679254b15a86c30b0575b701a0a51c3677c1`
- CPU gate: imports PASS; factory graph PASS; 1,213,337,474 parameters;
  44.1-kHz model; 31.749 s factory wall; 6,611,600 KiB maximum RSS
- Official model: `stabilityai/stable-audio-open-1.0`, revision
  `f21265c1e2710b3bd2386596943f0007f55f802e`
- Calls/outputs/GPU time: 0 / 0 / 0 seconds; checkpoint not loaded
- Network/token: no network and no token read, restored, printed, logged, or
  committed
- Environment manifest / report / machine receipt SHA-256s:
  `45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f` /
  `f2142dc09dd75800684c2273f67301f6cc67dff12545d38ede730ed00a4dc932` /
  `85fee0b21917aaad30006e3d71bc1ea29bacc8617e1e6251fb54b49527f6f1e6`
- Historical failures retained: mini-smoke v2-002 terminal SHA-256
  `3944b835ee5224b9b2156ff8049fc4d641fdf7da95b13acbb6814af65da17097`;
  CPU factory optional-import failure SHA-256
  `cb7df87510b2314361b2d5fa177fbc196870d64962d82ce27e994f9781c0a6ac`

## L-0021 — Stable Audio Open repaired mini-smoke completed

- Time: 2026-07-22T16:03:33Z
- Kind: exact three-call non-benchmark engineering smoke; measured PASS
- Authority: D-0045 and D-0050
- Node/placement: `an12`, physical GPU 7, TP1, one replica; preflight saw
  85,171,634,176 free bytes, 0% utilization, and no compute neighbor
- Run: `sao-mini-smoke-v2-003`; official revision
  `f21265c1e2710b3bd2386596943f0007f55f802e`; environment
  `sao-env-v2-002`
- Calls/outputs: 3 / 3, exactly 30 seconds requested and 100 actual NFE per
  call; all sanity checks PASS under the 0.25-second duration rule
- Reproducibility: calls 0/1 decoded-waveform SHA-256
  `c83f50f1e3ef8abf8c2a5b53f4e271af13b7788b342709490ad64e589c291d30`,
  exact match
- Measured cost: cold-plus-first `161.5567436106503 s`; resident unit
  `19.28598228469491 s`; 1,536-call cap `59,369.522357624024 GPU-s`
  (`16.491533988228895 GPU-h`)
- Peak allocated/reserved VRAM: `8,538,524,672 / 10,733,223,936 B`
- Terminal / ledger / manifest / claim SHA-256s:
  `825eac8e43583871fbb2a4b59f73226e68d5577fecb9255fe82b62dd6945a692` /
  `cfb5cb32a015fd174f9f061556db29c9e715e89e3715371a91cbf858aa1317c9` /
  `1481056390932b6456743756a56addb1a63aca04b3d7180b491cca12a328f295` /
  `173c6bd534730e8da01aa5b3c5afef73b709389ed1c39a6d64a328c1c7ce4f7c`
- Token/network: all HF token variables absent and provider networking
  disabled; no token value was read, printed, logged, ledgered, or committed
- Scope: benchmark endpoints 0; human-gold claims 0; state capability
  `NOT_ATTEMPTED`; eligibility expansion false

## L-0022 — Stable Audio Open core package sealed after two engineering failures

- Time: 2026-07-22T16:21:20Z
- Kind: CPU-only core-package preparation and validator repair; no model call
- Authority: D-0045 and D-0051
- Attempts 001/002: respectively wrong interpreter dependency selection and
  incorrect hard-coded v2-001/v2-002 path invariant; both failed before
  output publication with 0 GPU seconds, 0 calls, and 0 audio outputs
- Immutable combined failure receipt SHA-256:
  `215df0f7e4deb9e7f806113f611861a333e5fac02ceae8dc5a539644ac37e9b5`
- Attempt 003: PASS after exact D-0050 v2-003 claim/environment/decision/
  prior-failure lineage validation; scientific settings changed: no
- Core authorization / Phase-B terminal / core-config SHA-256s:
  `01c93e72bf6d110a310442cf20a8d5c7ab1991db6915b0dc82400f5c290f7b84` /
  `e51057d133684b607473629f8791244216b8cbc18939f47558753fd16949e977` /
  `4e96142e35553d391f89ad98b6c8bd055a5583746d15b2461f145713297a7713`
- Calls/outputs/GPU time across all three package attempts: 0 / 0 / 0 seconds

## L-0023 — Stable Audio Open core preclaim invariant repaired

- Time: 2026-07-22T16:42:00Z
- Kind: immutable CPU-only launch-preparation failure followed by a targeted
  pre-scientific validator repair; no model call
- Authority: D-0045, D-0052, and D-0053
- Failed run: `benchmark-core-v2-sao-20260722t162200z`; stopped before the
  global claim, run-directory publication, GPU use, or output creation
- Failure: the validator rejected the ACE completion receipt because it
  contained the exact completed-shard counts (`384` shard records and `384`
  heartbeat snapshots) in addition to the required 1,536 commit, claim, and
  WAV counts
- Immutable failure receipt SHA-256:
  `4b94cd78c6066bc8eec2f82e9bfd242206234c5b81a69501b1840feffc11cea5`
- Repair: accept only the exact legacy three-count receipt or those same
  counts plus exactly 384 shard records and 384 heartbeat snapshots; a
  regression test rejects any other count
- Fresh authorized run: `benchmark-core-v2-sao-20260722t164200z`; placement
  remains `an12:[7];TP1;R1`
- Calls/outputs/GPU time in the failed preparation: 0 / 0 / 0 seconds
- Scientific settings changed: no; prompts, seeds, model revision, sampler,
  steps, duration, evaluators, endpoints, and thresholds are unchanged

## L-0024 — Stable Audio Open deferred-state validator repaired

- Time: 2026-07-22T16:50:00Z
- Kind: immutable CPU-only launch-validation failure followed by a targeted
  pre-scientific metadata-invariant repair; no model call
- Authority: D-0045, D-0053, and D-0054
- Failed run: `benchmark-core-v2-sao-20260722t164200z`; stopped before the
  global claim, run-directory publication, GPU use, or output creation
- Failure: the ordinary-core loader conflated ACE's launch-time
  `AUTOMATIC_OUTPUT_ONLY` state metadata with ACE's later, separately
  authorized eligibility lane
- Immutable failure receipt SHA-256:
  `7d9f62a5f29ccfb9fe10c873f0f0c75e66e08e5d0e81642fca60bf3cac6c6b41`
- Repair: keep eligibility IDs a subset of READY generation backbones and
  admit only ACE's deferred state readiness while ordinary-core state launch
  remains exactly `CLOSED_AT_ORDINARY_CORE_LAUNCH`; SAO and all other
  non-ready-state models remain excluded
- Fresh authorized run: `benchmark-core-v2-sao-20260722t165200z`; placement
  remains `an12:[7];TP1;R1`
- Calls/outputs/GPU time in the failed validation: 0 / 0 / 0 seconds
- Scientific settings changed: no; model, prompts, seeds, sampler, steps,
  duration, evaluators, endpoints, thresholds, and eligibility scope are
  unchanged

## L-0025 — SA3 one-root validation retained and remaining queue opened

- Time: 2026-07-22T17:00:02Z
- Kind: completed bounded validation plus immutable continuation-launch
  failures and exact remaining-only repair opening
- Authority: D-0035, D-0045, and D-0055
- Validation run: `sa3-state-v2-restricted-rerun-002`, an12 GPU4, TP1, one
  replica; one group, three units, four calls/outputs, zero failed units
- Validation measured synchronized GPU time: `122.49368649721146 s`; peak
  allocated/reserved VRAM: `9,342,266,368 / 9,839,837,184 B`
- Validation marker / heartbeat SHA-256s:
  `74870f74b948becc9ca5314279010f40e6220062123b33fb1578f4072324870e` /
  `c04289df35c8838034501367f20c379a57a884b53cd5778387c18a4caee7dcaa`
- Continuation attempts 001/002 failed before a new claim, worker, model call,
  output, or GPU use; immutable receipt SHA-256s:
  `91f775be763aabdabfa42b5245c0b822a112874a84da60b292cc2805ecc7a253` /
  `7f9796c77cc820fd30ef48749576aa5811c3b81f65684aea936996b4866f7615`
- Corrected terminal receipt SHA-256:
  `3279b95bac56f75e074e60e79e4020272e8a60e0506d852410a4348721eadb7c`;
  superseded receipt `fa5a55bea280305af08ded88edebdebaba045341432506ea31d5e986833622e2`
  remains immutable
- Remaining package: one completed group/three units excluded; exact
  47 groups, 141 units, and 423 actions retained in original order; manifest
  SHA-256 `fb8068ee7335901ab2f4d9b5caf870971c2c024843bf356813324b94fe1afb33`
- Fresh run: `sa3-state-v2-restricted-rerun-003`, an12 GPU4, TP1, one
  replica; supplemental roots remain locked and STOP units prohibited
- Scientific settings changed: no; completed valid units will not rerun

## L-0026 — SA3 run-003 stopped pre-model; exact run-004 repair opened

- Time: 2026-07-22T17:13:34Z
- Kind: immutable zero-call engineering failure and targeted scheduler repair
- Authority: D-0045, D-0055, and D-0056
- Failed run: `sa3-state-v2-restricted-rerun-003`; unique claim and manifest
  were published, but no worker, GPU use, model call, ledger, staging payload,
  or output was created
- Failure: R1 placement had not been propagated to the worker scheduler,
  which would have used R4 capacity and covered only a subset of 47 groups
- Failure receipt / claim / manifest SHA-256s:
  `a58875bf6e5327437be0ce0eb98bf2a6858045c4851b36e0c69aba1db267c2f7` /
  `0b78f71420700a70e0bae28adfd760b3c035df2ac500bc7321bb39aceb93ddfd` /
  `5aa66e467fd6bd93ba81fc1242baccba1bbc7a66b710bab50a574c0177717f29`
- Repair: propagate exact `execution_replica_count=1`; regression proves all
  47 remaining groups map to the sole R1 worker
- Fresh run: `sa3-state-v2-restricted-rerun-004`, an12 GPU4, TP1, one
  replica; new claim required
- Calls/outputs/GPU time in run-003: 0 / 0 / 0 seconds
- Scientific settings changed: no; same completed exclusion, remaining
  manifest, prompts, roots, checkpoints, actions, features, folds, and costs

## L-0027 — Watermarked packet watcher replacement frozen

- Time: 2026-07-22T17:13:34Z
- Kind: CPU-only publication-contract and watcher-config repair; no packet
  assembly and no model call
- Authority: D-0038, D-0045, and D-0057
- Fresh automatic tables require watermark
  `AUTOMATIC-INSTRUMENT OUTCOMES` and reject human-gold/accuracy language
- New watcher config SHA-256:
  `008334d32b4e94f9613bf32e8a9167f6b7183271dd351d08344f8d3c3a171060`
- Gates remain conjunctive: timing-pilot ingestion plus exact three-backbone
  scored strata with tested cross-instrument disagreement coverage
- Current gate status: timing-pilot absent and all-primary scoring incomplete;
  packet assembly remains prohibited

## L-0028 — SA3 run-004 preclaim stopped; append-stable run-005 opened

- Time: 2026-07-22T17:16:47Z
- Kind: immutable zero-call CPU preclaim failure and decision-block validator
  repair
- Authority: D-0045, D-0056, and D-0058
- Failed run: `sa3-state-v2-restricted-rerun-004`; no claim or run directory,
  worker, GPU use, call, output, ledger, or staging artifact was created
- Failure: an append-only separator newline after D-0055 changed the raw
  block hash despite unchanged semantic bytes
- Failure receipt SHA-256:
  `2c0866666b481c49a2534a4fdf2cd3a0556b1f8a03e41cfbfa954cc3f2829dc7`
- Repair: compare canonical `block.rstrip() + "\n"`; retain whole-file launch
  hash as provenance; regression proves later decision appends are accepted
  while semantic drift still fails
- Fresh run: `sa3-state-v2-restricted-rerun-005`, an12 GPU4, TP1, R1;
  same 47 remaining groups / 141 units / 423 actions
- Calls/outputs/GPU time in run-004: 0 / 0 / 0 seconds
- Scientific settings changed: no; supplemental roots remain locked

## L-0029 — Stable Audio Open first core shard completed and scoring opened

- Time: 2026-07-22T17:00:24Z
- Kind: first immutable ordinary-core batch plus prospective automatic
  completed-prefix scoring opening
- Authority: D-0054, D-0057, and D-0059
- Generation run: `benchmark-core-v2-sao-20260722t165200z`, an12 GPU7, TP1,
  one replica; official revision
  `f21265c1e2710b3bd2386596943f0007f55f802e`
- First shard: 4/4 successful rows, 0 failures, 4 retained WAVs; shard / heartbeat
  SHA-256s `15bb331113670c8c3107b696067d89a4a4b2cf41f7ac020254b2d91761c4fe88` /
  `b72ce184f1e0ff51dbacdc8dc0eba43336c40beeb76eb9e61af35e65e792b22e`
- First-shard synchronized GPU time: `78.23330856487155 s`; peak allocated /
  reserved VRAM: `8,544,626,176 / 10,741,612,544 B`
- First-shard ledger tail:
  `2670d83061f4668cb1383c27cc55dccd07d2930a99a419d4c790a63309c444b4`
- Scoring run:
  `automatic-scoring-v2-sao-benchmark-core-v2-sao-20260722t165200z-shards-001`;
  exact four-row prefix only, config SHA-256
  `5d6fe8de0efe4f591fb1b85fd4bd2e77c84ae40b6ea6296da0452e7adafb5871`
- Scoring generation authority: none; human-gold/accuracy claims: none;
  watermark required; queue-don't-preempt applies

## L-0030 — Eligibility analysis contract frozen before live outcome access

- Time: 2026-07-22T17:34:51Z
- Kind: prospective CPU-only analysis/code freeze; no scored state-action row
  opened and no model or evaluator call
- Authority: D-0045 and D-0060
- Analysis config / row-schema SHA-256:
  `f4bab82b22fa0822ab83f70af4aae07d9c95c1f21b70dd17ee58933d218ddb07` /
  `6e189ca2f609163e93e01c279d72b440ea5b93737f05bc93e43c214272610c35`
- Four-way gate: `ELIGIBLE`, `REPLICATION_ONLY`,
  `INCONCLUSIVE_UNDERPOWERED`, `STOP_AXIS`; deviation-share requirement
  `0.10`; one doubling and one re-gate only for `INCONCLUSIVE_UNDERPOWERED`
- Opening remains fail-closed until these exact bytes and D-0060 are pushed to
  `origin/main`; supplemental execution remains locked

## L-0031 — Eligibility time-budget mapping frozen before live input access

- Time: 2026-07-22T18:05:26Z
- Kind: prospective CPU-only budget operationalization; no state/evaluator/
  outcome input opened, no model call, and no generation
- Authority: D-0060 and D-0061
- Config / schema SHA-256:
  `3457cc27c36796d87edd956688fecd1ed1246739a9621938cb852abf84e68b81` /
  `2aa44c9cad0191251fcdece20f59a66ce303eaaf099f50d723d7cba6318d9e08`
- Mapping: same-root BASE core synchronized wall time as total, partitioned by
  the registered cumulative/native NFE ratio; KEEP gets remaining budget and
  restarts get full budget
- Scope: initial Stage-1 survivors only; STOP/cancelled and supplemental units
  prohibited; human gold and evaluator rows prohibited
- Opening remains fail-closed until the exact implementation and D-0061 are
  pushed to `origin/main`

## L-0032 — ACE initial-survivor time budgets assembled

- Time: 2026-07-22T18:07:27Z
- Kind: outcome-blind CPU-only deterministic assembly; zero evaluator/model/
  generation calls
- Authority: D-0060 through D-0062
- Cell: ACE-Step v1 acoustic integrity, 12 prompts × 4 initial roots × 3
  checkpoints = 144 units; 48 same-root BASE core calls bound
- Manifest / evidence / measured-cost SHA-256:
  `7cd5ae63c222b44676c8b24dc41cbbb1aaae8abc4d5954b6b76749ceb3a6dfa1` /
  `95221d7ea7e7bb57085938a16d6945dcddd3878bc5d79f971eb3b3d25a722c37` /
  `81272a2a78e6af9357afa56b12fc790735a73dd7e2133cc3850c8e22b44eb1b1`
- Human gold, evaluator rows, state outcomes, supplemental roots, and
  STOP/cancelled units used: none
- All three published files are mode 0444
