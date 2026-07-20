# Stable Audio 3 foundation smoke — terminal report

`SA3_FOUNDATION_RUN_STATUS = FAIL_ESCALATED`

`SMOKE_STATUS = FAIL_ESCALATED`

This is the terminal engineering record for the single authorized foundation
run. Smokes A, B, C, and D passed. Smoke E failed because each fresh
separate-process resume was rejected before its first resumed diffusion
transition. The run is therefore not a five-smoke PASS, and its incomplete
Smoke E evidence must not be represented as successful checkpoint/resume
equivalence.

The one-shot authorization and claim are consumed. This report does not
authorize a repair run, benchmark generation, or any other model call.

## 1. Run identity and disposition

| Field | Obtained value |
|---|---|
| Run ID | `sa3-foundation-20260719T134821.040493Z-9ea9d06209d6` |
| Overall status / exit | `FAIL_ESCALATED` / `1` |
| Started | `2026-07-19T13:48:02.941838+00:00` |
| Ended | `2026-07-19T13:52:25.241974+00:00` |
| End-to-end elapsed | `262.300136 s` |
| Immutable run directory | `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/runs/sa3-foundation-20260719T134821.040493Z-9ea9d06209d6` |
| Git checkout | detached, clean `ae251c62e2ba2bae025ec4413aae875df967b021`; exactly matched `origin/main` at execution |
| Node / physical GPU | `an12` / GPU `4` |
| Visible device | one `NVIDIA A800 80GB PCIe`, exposed to the program as `cuda:0` by `CUDA_VISIBLE_DEVICES=4` |
| Parallel placement | one node, one GPU, TP1, one replica |
| Parent run PID | `1952771` |
| Parent model-load result | PASS; one attempt, one successful load, offline-only |
| Parent model-load wall time | `74.00555063411593 s` |

Recorded model command:

```text
/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m sa3_smoke.run_foundation --config /HOME/paratera_xy/pxy1289/sa3_foundation_runtime/checkouts/foundation-ae251c6/configs/foundation_v2.json --repository-root /HOME/paratera_xy/pxy1289/sa3_foundation_runtime/checkouts/foundation-ae251c6
```

The recorded process environment has SHA-256
`930a63f4b0859312a8f6ab774b7d1b70b90ccf32dd91546aab1a0fc0b21652e4`.
It records `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`HF_HUB_DISABLE_PROGRESS_BARS=1`, `PYTHONUNBUFFERED=1`, and the checkout's
`src` directory as `PYTHONPATH`. The immutable evidence records the inner
model command and argv exactly; it does not serialize an exact outer shell
launcher string, so no unrecorded launcher spelling is asserted here.

## 2. Frozen inputs and provenance

The executable v2 config changed only placement from v1; its `supersedes`
record binds v1 SHA-256
`42e99699e7c3f8fb56d615086684b10afd4fdc1a8b3f162e37818ec462814a14`.
Sampling remained the frozen 50-step Euler path with CFG 7, 6 s duration
padding, chunked decode, at most 30 s output, stereo 44.1 kHz FLOAT WAV, and
the registered prompts and seeds.

| Provenance object | SHA-256 / frozen identity | Validation |
|---|---|---|
| `SMOKE_PROTOCOL.md` | `84f15494462b99de2d8f8e71b0c90f7cecccbd17e92599d036b2a4785e4e70c6` | exact expected hash |
| `configs/foundation_v2.json` | `d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f` | exact expected hash |
| `SEED_REGISTRY.md` | `fcdcd09c6474fe2cfba477a0a0e70fcbfa6205ab10e3f8c9f460440850cad8d5` | PASS; all seven rows used in authorized scope |
| authorization-time `DECISIONS.md` | `315fd4204eca3a45b8ae1efff4c979220a0608f320921b0960bb7c219cd4993c` | latest assignment authorized the bounded run and caps |
| GPU-placement record | `a76eb1fc11eac87238ecd9fcc11e1070968b6a423e9c650698445d45a631229a` | PASS |
| package freeze | `da6aae61a6189ee8fc3842fa76652359ff802c6252ce191a199bad5953f98eab` | 89 distributions; no drift, missing, or unapproved extra |
| `uv.lock` | `c61a7fa1375d6766cceed983b56051b5b3ea7f3dba3769a5ffde1561f05f2b8c` | frozen resolver lock |
| installed-license inventory | `10f99624b8438c1dbc385ca2cec9bebac73ecb96cfe1098af32f4b9be8bd3294` | 84 inventory entries |
| runtime record | `b0e3c4d2dcb9023d862f80518a0bbb1a32f9541ab7c430e0ba7be8fd41fbec70` | PASS |
| local weights manifest v1 | `3c120446c854e814a172d499af4757a2ed86c985ba9e45f36674ad0242ca1803` | PASS |
| cross-provider verification v2 | `905bac35a86f98b5db961b7258a31ca2f7a9c47d67760fb9ca110f83013f7dfb` | PASS; 16 files cross-provider verified |
| one-shot execution claim | `ad71f0300d27ca84b2092981ac3283faaef9f24490097c1b7ad23394da09a6ac` | consumed; retained read-only |

Model identity:

- model: `stabilityai/stable-audio-3-medium-base`;
- ModelScope revision:
  `a9c479f5f28ee89f6fbdaca57b683e6b6c160314`;
- Hugging Face revision:
  `b32993f73c3bdc3864043a72d8032606bba737c8`;
- main `model.safetensors` SHA-256:
  `c443fcc4d491475064cd0ff3eb92459b1e5f5060e86d96d016f048e528e24195`;
- `svd_bases.pt` SHA-256:
  `d62c8d3855998fea824fb651885d220f216d2d6a86d14b19224f806ddb125692`;
- embedded T5Gemma `model.safetensors` SHA-256:
  `9b05ea5a4f211d023832f706fb2c0e83e4fc721b6da35ab69ceb0b55eb7800d3`.

Acquisition used ModelScope first at the pinned mirror revision. Weight
fallback was not required. The official public Hugging Face revision was then
queried unauthenticated through the declared proxy only to verify substantive
content. It reported `gated=false` and `private=false`; no token, interactive
acceptance, or license-gate workaround was used.

Pinned source and license identity:

| Component | Version / commit | License record |
|---|---|---|
| `stable-audio-3` | 0.1.0 / `0385302ea26522f00c80392c4b708df5ebf1adf5` | MIT code license; installed file SHA-256 `16bd922f0deee6f11a76f5582258fdc3abdf67c6b8719dbcafbc34dee31979a6` |
| `stable-audio-tools` | 0.0.20 / `3241adba4fc2a85cf5b29d9eb68d42f40a28e820` | MIT top-level code license; installed file SHA-256 `a1fac33b7bcd791b74fb33aeb439f825e7277e239fc119fb7d2ab6f084a0c101` |
| SA3 weights | ModelScope and Hugging Face revisions above | Stability AI Community License Agreement, pinned `LICENSE.md` SHA-256 `d6f6b1a4dce5c852bd6d7d9482d002baf0ccdb71e662250b73be9eec8764ee8d` |
| embedded T5Gemma | embedded in the pinned model snapshot | Gemma Terms and Prohibited Use Policy; pinned `LICENSE_GEMMA.md` SHA-256 `e77acc0d3163bb7534675045c584b4d04b387b529239fc4b3647da0a01ba4745`, `NOTICE` SHA-256 `66f856d7da72797f528fca46b7c80634ab481f917bfe020960e123d84b19f75f` |

Live snapshot verification passed for the exact 18-file set, totaling
`14,287,668,350` bytes. The only runtime config resolution replaced the
conditioner's upstream `repo_id`/`subfolder` with the verified embedded local
T5Gemma path. The original, resolved, diff, and resolution-manifest hashes are,
respectively:

- `27e2a299f0bda6ff742d3387398f929299575642f2c6a4d4c4f94830928fd0d5`;
- `6a19cb5379383a5e4d4b6bcac836ea0875eac1ee365a703b85278f1ea88c81d8`;
- `167424a9324c0afd5d063dd8e67329f27b10b6298369305bbea5b95077c58651`;
- `d33927913dc3130b2baeca76c2bfffd5984a28ac9aa07b73b9892469afb36b82`.

The final paragraph of `THIRD_PARTY_LICENSES.md` is a retained v1-era
narrative and says tokenizer metadata was not independently checked. It is
historical, not authoritative for the final provider comparison. The
append-only v2 overlay above supersedes only the v1 cross-provider flags and
verifies all 16 common substantive files, including the three tokenizer files;
provider-specific metadata remains explicitly excluded. No acquisition record
or downloaded byte was overwritten.

Runtime versions were Python 3.10.12, PyTorch 2.7.1+cu126, torchaudio
2.7.1+cu126, Flash Attention 2.6.3, CUDA runtime 12.6, and NVIDIA driver
535.104.12. Installed-license checks passed for `stable-audio-3`,
`stable-audio-tools`, and `flash-attn`. Model artifacts remain subject to the
Stability AI Community License Agreement and Gemma Terms; they are not MIT
artifacts.

The frozen environment is recreated with:

```text
UV_PROJECT_ENVIRONMENT=/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env scripts/with_proxy.sh uv sync --frozen --all-groups
```

The proxy wrapper is required for a cache-miss recreation because the lock
contains pinned GitHub artifacts. `environment/licenses.json` contains 84
entries; five bootstrap/license-tool distributions present in the complete
89-distribution package freeze (`pip-licenses`, `prettytable`, `setuptools`,
`tomli`, and `wcwidth`) are not inventory rows. The required SA3,
stable-audio-tools, Flash Attention, weight, and embedded T5Gemma license
records are present and hash-verified; no 89-entry license-inventory claim is
made.

## 3. Hard-cap and generation accounting

| Constraint | Cap | Obtained | Result |
|---|---:|---:|---|
| Generation slots | `<=20` | `14` reserved | respected |
| Official generation calls | exact frozen plan | `11` reserved | all planned calls reached a terminal row |
| Successful official calls | — | `8` | 11 model WAVs retained |
| Failed official calls | — | `3` | three Smoke E resumes; no WAVs produced |
| Model-generated audio duration | — | `250 s` | 11 outputs |
| Derived audio duration | — | `10 s` | Smoke B source prefix; no model call |
| Retained audio | — | 12 WAVs / `260 s` | all retained; none stored in Git |
| Per-clip duration | `<=30 s` | maximum `30 s` | respected |
| Visible GPUs | `1` | `1` | respected |
| Synchronized official-call wall | `<=1800 GPU-s` | `46.01308351755142 GPU-s` (`0.012781412088 GPU-h`) | respected |
| Conservative one-GPU residency bound | `<=1800 GPU-s` | `244.181992349 GPU-s` (`0.067828331208 GPU-h`) | respected |

The frozen plan is nevertheless marked `exact_plan_completed=false` because
three reserved outputs terminated as failures rather than generated artifacts.
Likewise, `measurement_evidence_complete=false`: actual attempted-call NFE was
measured as zero for each rejection, but no post-transition/remaining-path NFE,
equivalence, or output sanity exists for those three resumed outputs. Neither
the time cap nor the residency cap was reached.

## 4. Per-smoke outcome and measured cost

“Actual DiT NFE” is the number of actual DiT forward-pre-hook invocations.
“Synchronized official-call wall time” is the sum of the budget wrapper's
CUDA-synchronized `StableAudioModel.generate` timings. “Peak VRAM” reports the
maximum process-local PyTorch CUDA allocated and reserved bytes observed in a
call for that smoke; it is not a node-wide NVML maximum.

| Smoke | Status | Calls / reserved slots | Actual DiT NFE | Synchronized official-call wall time | Peak VRAM allocated / reserved | Terminal evidence |
|---|---|---:|---:|---:|---:|---|
| A | PASS | 2 / 2 | 100 | `19.62547130137682 s` | `5,437,102,080 / 9,839,837,184 B` (`5.064 / 9.164 GiB`) | decoded hashes equal exactly |
| B | PASS | 1 / 1 | 50 | `3.911749802529812 s` | `5,441,078,272 / 9,839,837,184 B` (`5.067 / 9.164 GiB`) | 10–30 s continuation and both sanity checks passed |
| C | PASS | 2 / 2 | 100 | `7.432163719087839 s` | `5,439,922,176 / 9,839,837,184 B` (`5.066 / 9.164 GiB`) | single and multi masks and output sanity passed |
| D | PASS | 2 / 5 | 100 | `8.44560094177723 s` | `5,890,185,728 / 10,464,788,480 B` (`5.486 / 9.746 GiB`) | batch-one and batch-four checks passed |
| E | FAIL | 4 / 4 | 50 | `6.598097752779722 s` | `5,440,120,832 / 10,464,788,480 B` (`5.067 / 9.746 GiB`) | reference passed; three resumes failed at `NFE=0` |
| **Run** | **FAIL_ESCALATED** | **11 / 14** | **400** | **`46.01308351755142 s`** | **`5,890,185,728 / 10,464,788,480 B`** | four smokes passed; one failed |

Per-call evidence, without rounding the recorded measurements:

| Call | Smoke | Status | Batch x duration | Seed | NFE | Budget-wrapper wall (s) | Peak allocated / reserved (B) |
|---|---|---|---:|---|---:|---:|---:|
| `call-01` | A | generated | 1 x 30 s | S-0001 | 50 | `15.963723801076412` | `5,437,102,080 / 9,839,837,184` |
| `call-02` | A | generated | 1 x 30 s | S-0001 | 50 | `3.6617475003004074` | `5,437,102,080 / 9,839,837,184` |
| `call-03` | B | generated | 1 x 30 s | S-0002 | 50 | `3.911749802529812` | `5,441,078,272 / 9,839,837,184` |
| `call-04` | C | generated | 1 x 30 s | S-0003 | 50 | `3.7271576449275017` | `5,439,922,176 / 9,839,837,184` |
| `call-05` | C | generated | 1 x 30 s | S-0004 | 50 | `3.7050060741603374` | `5,439,922,176 / 9,839,837,184` |
| `call-06` | D | generated | 1 x 30 s | S-0005 | 50 | `3.604426071047783` | `5,439,723,520 / 9,839,837,184` |
| `call-07` | D | generated | 4 x 10 s | S-0006 | 50 | `4.841174870729446` | `5,890,185,728 / 10,464,788,480` |
| `call-08` | E | generated reference | 1 x 30 s | S-0007 | 50 | `3.901632107794285` | `5,440,120,832 / 10,464,788,480` |
| `call-09` | E | `MODEL_CALL_FAILED` | 1 x 30 s reserved | S-0007 | 0 | `0.9084690026938915` | `5,280,795,648 / 9,837,740,032` |
| `call-10` | E | `MODEL_CALL_FAILED` | 1 x 30 s reserved | S-0007 | 0 | `0.8786124475300312` | `5,281,319,936 / 9,837,740,032` |
| `call-11` | E | `MODEL_CALL_FAILED` | 1 x 30 s reserved | S-0007 | 0 | `0.9093841947615147` | `5,281,319,936 / 9,837,740,032` |

### Smoke D timing scopes

Smoke D also measured timing immediately outside each official call. Those
values are distinct from the budget wrapper values above. They are not summed
with the wrapper values and are not substituted into the run-wide cap total.

| Observation | Budget-wrapper timing | Smoke-D outer timing | Outer-timing-derived throughput |
|---|---:|---:|---:|
| batch one, 30 s | `3.604426071047783 s` | `3.642550054937601 s` | not registered |
| batch four, 4 x 10 s | `4.841174870729446 s` | `4.866168051958084 s` | `0.8220020265001845 items/s`; `8.220020265001844 audio-s/s` |

Both scopes use CUDA synchronization at their boundaries and an already
loaded model; their small difference reflects the different measurement
boundaries. The model-load-plus-first-A-call arithmetic is
`74.00555063411593 + 15.963723801076412 = 89.96927443519234 s`. These are
singleton engineering observations, not medians or p95 estimates.

## 5. Functional results

### A — fixed-seed decoded-waveform comparison: PASS

Both 30 s calls used S-0001 (`73193001`). Their decoded-waveform SHA-256 was
identically
`b224f27d374209cfa76ed73b680cede18e9b7920677dbfc0be6afaa2d2a2b387`.
The arrays were exactly equal, maximum absolute error and RMS error were zero,
and SNR was infinite by zero-error interpretation. Both WAVs passed common
audio sanity. Different container-file hashes do not change the decoded-array
result.

The frozen nondeterminism inventory was CUDA reduction order, Flash Attention
kernels, PyTorch kernel selection, hardware/driver changes, and half-precision
arithmetic. Environment and device identity were frozen or validated, but
these remain potential sources rather than guarantees. Smoke A's acceptance
rule had no approximate substitute: a decoded-waveform hash mismatch remained
FAIL. The retained `max_abs <= 1e-5` and `SNR >= 80 dB` thresholds were
diagnostic only if hashes differed. Here the stricter exact criterion passed.
The differing WAV-file hashes were caused only by the timestamp-bearing PEAK
container chunk.

### B — continuation from a 10 s clip: PASS

The retained 10 s prefix passed common audio sanity. The official continuation
mask was exactly 10–30 s, the 30 s output passed common audio sanity, and its
continuation region was non-silent (`active_fraction=0.9997930839002268`). The
prefix comparison was diagnostic only and was not a PASS criterion.

### C — inpainting: PASS

The generated Smoke A run-one clip was the retained inpainting source. The
single mask `[8,12]` s and multi-mask `[4,6]` plus `[20,23]` s both passed mask
validation through the official API. The source, single-inpaint output, and
multi-inpaint output all passed common audio sanity. Masked and unmasked
waveform differences were retained as diagnostic evidence only.

### D — cost and batch-four throughput: PASS

Both the batch-one 30 s call and batch-four 10 s call recorded exactly 50 DiT
forwards and 50 sampler callbacks. The batch-four call produced four valid
outputs, all passing common audio sanity. Measured throughput was positive;
the exact timing-scope distinction is recorded above.

### E — checkpoint export and separate-process resume: FAIL

The uninterrupted 30 s reference itself passed common audio sanity and
exported valid checkpoints after 15, 30, and 40 of 50 transitions (30%, 60%,
and 80%). Before launching children, the parent moved all 972 registered model
parameters and 25 registered buffers to CPU, released the reference output and
final latent, cleared the CUDA cache, and verified zero parent model tensors
remaining on CUDA.

Three distinct child processes (`1959026`, `1961040`, `1962942`) were launched
sequentially for expected remaining NFE 35, 20, and 10. All loaded the fresh
official path and then failed before the first resumed DiT transition with:

```text
CheckpointValidationError: fresh official latent dtype torch.float16 != checkpoint torch.float32
```

Consequently each resume's actual NFE was zero. No resumed WAV or resume-result
PT file exists. The waveform tolerances (`max_abs <= 1e-5`, `SNR >= 80 dB`)
were not evaluated, so this is a pre-transition implementation failure, not an
observed equivalence mismatch. Child config-resolution directories were
retained, but the manifest correctly marks
`all_child_config_resolution_evidence_retained=false` because no successful
child result returned the complete evidence bundle.

The single model-load count and 74.006 s measurement in Section 1 refer only
to the parent. Each E child separately constructed and loaded the fresh
official runtime before sampler entry. Child load/setup time is outside the
roughly 0.9 s per-call budget-wrapper values, was not isolated as a separate
measurement, and is covered only by the run's 262.300 s end-to-end time and
244.182 s conservative one-GPU residency bound.

## 6. Audio retention and sanity validation

The run directory contains 12 WAVs: 11 model outputs and one 10 s derived
source. All 11 successful ledger outputs and the derived source have finite
stereo 44.1 kHz samples, exact expected sample counts/durations, valid
provenance sidecars, and `sanity.pass=true`. A read-only post-run rehash found
zero mismatches among the 11 ledger audio hashes; the derived WAV and sidecar
also match the hashes below.

| ID | Retained WAV | Seconds | File SHA-256 | Decoded-waveform SHA-256 | Provenance SHA-256 | Sanity |
|---|---|---:|---|---|---|---|
| generation-01 | `a_fixed_seed_run1.wav` | 30 | `d51ba6038216f22b5ca6ef86d11371393b357444a90353d61bb716e2328d98db` | `b224f27d374209cfa76ed73b680cede18e9b7920677dbfc0be6afaa2d2a2b387` | `ed0d482dc80e560a8c5c4aaf84e5dd975367ca6555e0fc2f51502550768248cf` | PASS |
| generation-02 | `a_fixed_seed_run2.wav` | 30 | `4d40ab211db8e10eb1b222093214a3539985917fb71d009006a17fcc4df53729` | `b224f27d374209cfa76ed73b680cede18e9b7920677dbfc0be6afaa2d2a2b387` | `5ee5584a43005273906b6ad3c91976bde9bb206983a8616dbdbb7da393d5f26e` | PASS |
| generation-03 | `b_continuation_30s.wav` | 30 | `23786b4ae87d5ab856af48473f342365cefe29187adb7c47cb5cb95f2713e5a7` | `74f25307c1eabcbaf5f6a81f9d2a3075cb620063d1856482048dfaaba75baa71` | `d9ea648fb87746b0553c2ff067a5018df8ba067f4e20b7e5c11e1269748763d4` | PASS |
| derived | `b_source_10s.wav` | 10 | `09cb40495c52ad9e91afdeb0077e8170263de256802b0e2cea9af2c192cac4d9` | `e1317b838a838ba78e4748ea66f6f42c4ba29ce42a5d5cfac0a20a33bca3b305` | `d0c939e4da22272466b7960d15503da92a728434716f2475d735351bef3f74f4` | PASS |
| generation-04 | `c_inpaint_single_8_12s.wav` | 30 | `84f07feb44a27ac23e794467116070d7807e59be032dd26870e23c3a153ecc61` | `62be74d5ed68c5701cc3cf3cbe250819da8cf26db40383e7dd0f11c41c08d84c` | `1e0f13838f018b0d1492badb66cd99d0bb0f7c9552968e764ec93f1e2e6365d2` | PASS |
| generation-05 | `c_inpaint_multi_4_6_20_23s.wav` | 30 | `f226278085a110282e6fdc3f9b481699eedf4ea54a1a62adf94f3d20a90b1c74` | `3dda440f7c20966a0d8e5b188f1ffe198dbef949f5d0cf12ab071c82e3614748` | `dca396e66957b065312f90d296540c6d1aaa6c716ba33ac31e7de5eb67be68f2` | PASS |
| generation-06 | `d_cost_batch1_30s.wav` | 30 | `e818caa68e6e33a85981b8f6a2831d08f0fbdd471970650a3c120c06486ced9a` | `9ac1e0f79ab4a1ca12ce8bab819d332d483546d97ba40793114dc4423d36fd17` | `ef5d54018b8e8d0801cea22277adc5dde983246c1cf65b283c96691c7d62e3fc` | PASS |
| generation-07 | `d_throughput_batch4_10s_1.wav` | 10 | `d4cd4d427ee654410dfee9b4f6343cdd6be279d2203baf85b4d7cd54a8d2da3d` | `85bf032642a445f452c59e0317efbce9fcdbe598b4ac5af03a4e2b488e1b2699` | `28dd2ef176d897b55757c0077c5b2acc302a18017ba9f2e2c8f1a6a20c5123b5` | PASS |
| generation-08 | `d_throughput_batch4_10s_2.wav` | 10 | `4cf5aafa48a57f5b3fa0b2253ac7bfd3af862c3a2dd8214e2adc1fbcbcef0f93` | `c2928cb631797fe8bcebc2d5656595cd82a29ed8cee4a20c6b5d25985a4d9f7b` | `89555e434f53fbfc1ed13b289e5349bc4fd07ef7eb151dea53237cdbffe1ca6c` | PASS |
| generation-09 | `d_throughput_batch4_10s_3.wav` | 10 | `f240e6aee2a2c8f1baafbcbd3a374ab0f39be558d79c19138f24174a11ce11d5` | `37960f1313fd99c22d20d50ffa22798982e2ae6ba2a9cbb7bc41a41aceaf6571` | `69da92fb5f178da5518b46eb7a598e40b23ce55bf3217c80275ea229621d7d39` | PASS |
| generation-10 | `d_throughput_batch4_10s_4.wav` | 10 | `1325ccd12c685f61825d9a9be8f1e29f793a055b5ff6a17b83792d2bac26e0a0` | `c68ec24805b2afd5b8788e755b799f293033d30e974c3577c6357ea605679b90` | `c08b2aa6760bf55e3783f094df05756b81b9573e7dad64aedbcefb5889b59332` | PASS |
| generation-11 | `e_reference_30s.wav` | 30 | `476aaea35e40de0cdd8983ec95f02403f46f74f56610b5af98255e1fedf2fecc` | `536b203214fed0e49a52d2debf09f8f84ab7b8a16509dbb2b2786aa9c23ee00d` | `3a3e480461de55d6b0c37c901dfa5137537517030d56cca4faf95a5053acd577` | PASS |

The three failed reserved generations have no audio path, audio hash,
provenance sidecar, or sanity record. They are not counted as generated WAVs.

## 7. Checkpoint validation

All three checkpoint files, their provenance sidecars, and state metadata are
retained. All checkpoints record latent shape `[1,256,388]`, latent dtype
`torch.float32`, schedule dtype `torch.float32`, and schedule SHA-256
`f54e6d1e2964d2a81db05216a4181ade6c1355fbf3572a682f4b01bff79ea21f`.
Their conditioning SHA-256 is
`0c45143f0115c2afd1b64d8d262a0bd07ab4bcbaf6524db913731d36a4713d4a`.

| Fraction / step | Checkpoint SHA-256 | Latent SHA-256 | Provenance-file SHA-256 | State-file SHA-256 | Provenance |
|---|---|---|---|---|---|
| 30% / 15 | `52acec3c52d4f580978222a6f392fe9577cb6e1094719a1505cfd6a62671eee1` | `9793f784ce92d6f8dd08418c6540d72681b8857db5b2685fb990c290a97849cf` | `39a27c461e7444464df632cf4295f437abc8d982e0d77853d1323b787ddd154c` | `340dd59a1c6adf5c4b8bf0c5f9625a05774604c1b8d8899c076b35c4fed985cd` | valid |
| 60% / 30 | `95b31c86f4ae909f7009739fe20705cf0cd6c957c857c2cb303583b38b77033d` | `f3ac60f71460ae423307343c0877d31db2286e7ba9786f549ec89a899b77ae1e` | `7821e45665d8b875f31e8b59e6d23d6186278140a8310aaec2812d723d22d2b0` | `758922d2c38bd790bb13070b0c4d980fee5836f91192dee3e13c9425453e1e1c` | valid |
| 80% / 40 | `acadb11a0d17204370c41d120b09af322bc10388ba7a20600481191a1dc589f5` | `a8376c1c28dc5ddab4533bcdb587dce6ef7fc2382704713487246d005e3dad45` | `c9929a49e10f6d706b97d1d6605bb48d0b5095e4196b84196084da68ddb10d43` | `aff545dbd426fd338222d4edf33af969e0c645577c7cc88d300464970928d82c` | valid |

The three child request-file SHA-256 values for steps 15, 30, and 40 are
`7f1a2e5ccdea80e5ef75198d8624775b78a4c78b3f7cea4d43fac44c76406f66`,
`41e8d85feed92a1e1e6fc2ef9bef7a6704abd89101f7b0347be79d83a79bfd3a`,
and `2ae216174499058b6490f1723b27d399235da7c616d7bdbdc2059104c8c45af1`.
These validate the retained requests, not successful continuation.

## 8. Ledger and immutable evidence

`generation-ledger.jsonl` contains 14 terminal, hash-chained rows: 11 `PASS`
and three `MODEL_CALL_FAILED`. A read-only audit recomputed every row hash and
every predecessor link with zero mismatches. Its terminal row hash
`8ec8fea21c5e0c56e3a24004e50a0199a99b6af8995ca59fc708640fd0b16cd2`
matches `execution-budget.state.json`.

| Generation | Call | Status | Row SHA-256 |
|---|---|---|---|
| generation-01 | call-01 | PASS | `73f21714fba3b225f726038f0f228acdd6aa4bd3e535ee7a74cc837b2b8e4011` |
| generation-02 | call-02 | PASS | `364852b8edfd81d2b4284cc5181c91f73a2630b9c273526b8c737dbf517dd615` |
| generation-03 | call-03 | PASS | `33f27a80fc906a099de3cb04ba10a34b892ea60688f9a9e8d0ba47edf7747523` |
| generation-04 | call-04 | PASS | `e5ccd6428d15b700ba7e2ebf655d7bf8b5eb991cf8ff723e1b413d21c7a949bf` |
| generation-05 | call-05 | PASS | `c11bc5b4fba8e848bf3bb8660ec96e9de7f5104fb65b1bffd2721989e53a08d9` |
| generation-06 | call-06 | PASS | `013fd869e422e11b3bdc039d296811951e5b3596ac9bd12176030a1aac663bcd` |
| generation-07 | call-07 | PASS | `21c172d14d11b105146963399af762716cc74d0d0a4df967afec460a0241a1a3` |
| generation-08 | call-07 | PASS | `cf0342a1dfb0ed9f5daa0c520096b1e53bf6768d6c245a648894048fe63fd9ee` |
| generation-09 | call-07 | PASS | `7e6191a7763aeaeee4db34e296bc29b0f1b134ebce1dac0101d87932958542ad` |
| generation-10 | call-07 | PASS | `1809e53a58afbaead20ed8b07309d112a05a27f7e5b1b6905923c3d20a0bd161` |
| generation-11 | call-08 | PASS | `99aa8d0f380b6f3522df2f97ea4d330d5ccec6d2053f64d451d79f5a56412769` |
| generation-12 | call-09 | `MODEL_CALL_FAILED` | `332395d7bd83f41a05153988b1aa929e16da7a780e595ed34834d9ad654f6e4b` |
| generation-13 | call-10 | `MODEL_CALL_FAILED` | `c2ff4bde152380ba9c9a7a856736cece4327819458858cb71a2fb769da9a4898` |
| generation-14 | call-11 | `MODEL_CALL_FAILED` | `8ec8fea21c5e0c56e3a24004e50a0199a99b6af8995ca59fc708640fd0b16cd2` |

Root evidence hashes:

| Artifact | SHA-256 |
|---|---|
| `result.json` | `65adbde1e8abe9e744749a52745243d7c4bb572e778284d76827f98a05b6d912` |
| `execution-budget.state.json` | `055ab5c565f6f1f071aa73e7dbcc8fa04739efcbe87e867db5644d43eda130ac` |
| `generation-ledger.jsonl` | `7caafac155c3e04519633749bb89a31d4a86f8d118926aabd0bcdd0130626a2c` |
| Smoke A manifest / budget snapshot | `3f04c863c3420fb6e4635ea2f41ced25e27a95e168f27010ab9809ab9ed373d2` / `b15c0b0536ce4af14c7ef5a3ff2ce3a064d7c964a2d2e2b9dbe17bfa0f4350ed` |
| Smoke B manifest / budget snapshot | `0f465bedecd611f6c3d3030a84a09615a461d481fd0ec58118edc0bda7e36442` / `32ecfcb5757f0b6bde5ba20a5a04b0335c21cd29434a2f4167e16803e906de5a` |
| Smoke C manifest / budget snapshot | `f2f568225de66d63a1889d40b98142af742dae585dd6530d81c1f9981b58b210` / `513ba44590c29a90598cd784d7fe82e26e21f1355dab7f5fc715970473228074` |
| Smoke D manifest / budget snapshot | `2a7923fa0bf4be95ca18beb3082c483b4d91fd55d1d0118f22c1f0107042f8ec` / `76c60e35a8d4922ced073e992e23d43abb66695d553b3885be076ebe80c79a65` |
| Smoke E manifest / budget snapshot | `7d5a25e083e5cdf2385c3505b1896e8e512efc1f78a3082bc76d347a85103495` / `bc0799f295679d812b45b67251035a678e4a77597dfd44c7fdc96a614f6d709a` |
| production preflight log | `7f6abdff81ebe4fd0bc2eb07b6d8937c9f6aa6a82515d517c4facc45090c85cb` |
| production terminal log | `3b7024920a8e14b4430239f64731bf56579948c0e55579fd35c4e2adab07f307` |
| post-run permission audit | `5375fb7c4ca1d9538a04c70d43d27044bc868183e1b01ffa0743b7e422869a5f` |

The post-run permission audit found zero writable entries, mode `0555` on the
run directory, mode `0400` on the claim, and mode `0444` on the production
preflight and terminal logs. No immutable run output, checkpoint, or audio
artifact was deleted, retried, overwritten, or stored in the repository.

## 9. Failure root cause and OOM assessment

The reference official call started from half-precision noise, but the pinned
Euler/model path produced an evolved latent stored as `torch.float32`. Every
fresh official child call again allocated its disposable initial latent as
`torch.float16`. The resume adapter required that fresh, soon-to-be-discarded
initial latent to have the same dtype as the validated saved checkpoint. It
therefore rejected all three resumes before running the saved state through a
DiT transition.

This was not an OOM. Pre-execution placement validation recorded physical GPU
4 at 5 MiB used, 81,223 MiB free, and 0% utilization. The largest recorded
official-call process-local CUDA peak was 5,890,185,728 allocated bytes and
10,464,788,480 reserved bytes (5.486 and 9.746 GiB). No CUDA OOM,
`OutOfMemoryError`, process eviction, or allocator-cap failure appears in any
terminal record; all three terminal errors are the dtype validation error
above.

The run used physical GPU 4, disjoint from the recorded neighboring job on
GPUs 0–3, and did not terminate, migrate, or reconfigure that job. The retained
evidence does not continuously instrument every neighboring process, so this
report does not claim an end-to-end proof of neighbor health; it establishes
idle disjoint placement, ample observed headroom, and no OOM in this run.

## 10. Prospective repair — unit-tested, not model-executed

A narrowly scoped prospective repair is included in this post-run repository
change set. It:

1. Continues to validate checkpoint file/hash, checkpoint metadata dtype,
   shape, schedule hash, conditioning hash, config hash, and next-step index.
2. Does not require the fresh official call's disposable initial-noise dtype to
   equal the checkpoint latent dtype.
3. Moves the verified checkpoint latent to the runtime device without casting
   it to the disposable noise dtype; assert and record that the checkpoint
   dtype is preserved.
4. Records `fresh_initial_latent_dtype`, `checkpoint_latent_dtype`, and a
   `resume_latent_dtype_preserved` check in child evidence.
5. Adds CPU regression coverage in which float16 initial noise becomes a
   float32 evolving state, then verifies a resumed path is bitwise equal to the
   uninterrupted path while preserving float32.
6. Separates the public live entry point from the private CPU-test boundary.
   Live execution hardcodes the canonical config hash and clean-Git check and
   always retains the one-shot claim/budget path; both boundaries reject a
   dependency-mode mismatch before creating a run directory.

The CPU regression passes and verifies exact uninterrupted/resumed tensor
equality while preserving the checkpoint's float32 state across a disposable
float16 initial-noise boundary. This is code-level evidence only. The repair
has not been executed against the model, has produced no repair audio, and has
no empirical waveform-equivalence result. Smoke E remains `FAIL`; no result or
artifact above was modified. A retry would require an explicit new PI decision
naming this failure and reviewed fix, a fresh immutable config and claim, and
fresh repair caps. The consumed claim must not be removed or reused.

## 11. Limitations and gates

`SA3_COST_OBSERVATION_STATUS = MEASURED_SINGLETON`

- The cost observations are singletons. They do not estimate medians, p95,
  model-wide benchmark coefficients, or multi-backbone GPU budgets.
- Smoke E supplies a reference-generation cost only. Each rejected resume has
  measured pre-transition NFE zero; resumed-transition/remaining-path NFE,
  wall cost after transition, and waveform equivalence remain unmeasured.
- Peak CUDA allocated/reserved measurements are process-local PyTorch
  allocator observations, not node-wide NVML peaks.
- The objective sanity checks do not constitute a human perceptual review.
- No benchmark audio or benchmark result was produced. All retained WAVs are
  bounded foundation engineering artifacts outside Git.
- Smoke B's named budget snapshot was captured after Smoke C and therefore
  contains combined A+B+C counters. Per-call B timing/NFE, its manifest, WAV,
  provenance, sanity, and ledger row remain valid; the snapshot is not claimed
  as an immediate post-B state.
- Smoke E's manifest has a null top-level `terminal_failure` summary even
  though its status is `FAIL`. The three nested child error records, three
  `MODEL_CALL_FAILED` hash-chained ledger rows, zero-NFE measurements, and
  aggregate `FAIL_ESCALATED` result are retained and authoritative; no null
  summary is interpreted as success.
- Smoke E's aggregate `child_pids` and `remaining_forward_calls` arrays are
  null and its `remaining_forward_calls_are_35_20_10` check is false because
  each launcher raised before returning a success summary. The budget call
  records retain the three actual child PIDs, while the nested resume records
  retain the expected 35/20/10 remaining transitions; the failed attempts
  executed zero of them.

`FOUNDATION_COST_SMOKE_AUTHORIZATION_STATUS = CONSUMED`

`FOUNDATION_COST_SMOKE_AUTHORIZED = NO`

`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO`

`BENCHMARK_PREREG_V1_FROZEN = NO`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`

## 12. Verification

The final repository test command is:

```text
/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env/bin/python -m pytest -q
```

Result: `90 passed, 98 subtests passed`. The suite includes environment and
provenance drift rejection, governance markers, all smoke harnesses, retained
report assertions, the mixed-dtype checkpoint regression, and the public live
entry-point authorization-boundary regression. Ruff lint and `git diff
--check` also pass for the changed Python and repository files. This section
records command results, not an external transcript artifact.

`FINAL_TEST_STATUS = PASS`

## 13. Scope closure

All five requested smoke statuses are terminal. No detector, constraint, or
policy execution occurred in the foundation run, and no scientific result was
imported. The terminal status is `FAIL_ESCALATED` solely because the required
separate-process reload-and-continue path did not produce equivalence evidence.

## 14. D-0019 Smoke E retry addendum — PASS

This append-only-style addendum supersedes Sections 10–13 only for the latest
Smoke E engineering capability evidence. It does not rewrite the original
five-smoke run: `SA3_FOUNDATION_RUN_STATUS = FAIL_ESCALATED` and its Smoke E
FAIL remain the historical D-0017 outcome.

`SA3_SMOKE_E_RETRY_STATUS = PASS`

`SMOKE_E = PASS`

`SA3_STATE_CAPABILITY = PASS`

### 14.1 Retry identity and frozen boundary

| Field | Obtained value |
|---|---|
| Run ID | `sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24` |
| Result / exit | PASS / `0` from the E-only Python runner |
| Started / ended | `2026-07-20T14:01:53.979437Z` / `2026-07-20T14:06:22.169536Z` |
| Immutable run directory | `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/smoke-e-retry-runs/sa3-smoke-e-retry-20260720T140212.582413Z-1e639ad82b24` |
| Git | clean `dd65740782f268e0df21a2a22efe9faa3ab12962`, equal to `origin/main` at execution |
| Node / placement | `an12`, physical GPU 4, one visible A800, TP1, one replica |
| Live placement | lock held; zero compute processes; 81,223 MiB free; 0% utilization immediately before claim |
| Seed | S-0007 = `73193007` for reference and all resumes |
| Retry config | `39553c595659e29e3c0fa691c0d47f344421548ca3ac12157c01fac32a716c84` |
| Retry protocol | `1a2892b70029bea1e36722145dceea32a814e5a00d917a98c0cb17d4582cd0a0` |
| Foundation call config | `d26985d3a5fb6280fd93b30fa7dea575abed0eb3c4b28caada292ca10585d69f` |
| Fixed claim | `32bd53e6e6421acede70f2f01e07e50c55abb4a918ee5ef6c2b50b6c3a6fc092`; consumed, mode `0400` |

The targeted fix used the runtime-state path, not a tolerance cast. The
official reference began with disposable FP16 noise, while each evolved latent
exported at 15/30/40 steps was FP32. Each child ignored the disposable fresh
noise values, moved the verified checkpoint latent to the runtime device
without changing FP32, and continued from that state. Casting the saved latent
to FP16 was rejected prospectively because it would lose precision and change
the path.

The exact authorized plan was reached with no other smoke: four official
Smoke-E/S-0007 calls and four generated outputs. The hard cap allowed at most
eight generations, 30 seconds per clip, one GPU, and 540 seconds of claim-bound
GPU residency (stricter than the PI's 600-second limit). No detector,
constraint, policy, benchmark, or formal Section 11 generation ran.

### 14.2 Checkpoints, separate processes, and equivalence

All checkpoints have shape `[1, 256, 388]`, dtype `torch.float32`, and schedule
SHA-256
`f54e6d1e2964d2a81db05216a4181ade6c1355fbf3572a682f4b01bff79ea21f`.
Their latent hashes equal the corresponding valid D-0017 exports, while their
serialized file hashes differ because run IDs and creation metadata are new.

| Fraction / step | Checkpoint SHA-256 | Latent SHA-256 | State / provenance SHA-256 |
|---|---|---|---|
| 30% / 15 | `066c6a4673fa0a37751c5de115c31fb43149dcfc2c335c65b33da4fcfda78582` | `9793f784ce92d6f8dd08418c6540d72681b8857db5b2685fb990c290a97849cf` | `f54791630203d5d99656adb41855fabbffd577cffed6d38de9122ff33037f736` / `3c8c57b57db22ad2bdc21de7be108e304057ffb4823f7d8961eeda1d3fb0d3a0` |
| 60% / 30 | `25e11b2770b568f5e1d7187667581eaf96989a7cd28245b5d422ddbbe5b4b011` | `f3ac60f71460ae423307343c0877d31db2286e7ba9786f549ec89a899b77ae1e` | `3740ed899871fe34d46597ed226a3ee323e45851f959253a683e3b4c2c6b86b4` / `a5750c360817d863ee73c80cf714045778bc91ad2e5c39cac256e0568130a6df` |
| 80% / 40 | `64564ee934755a131d33ca56e0725b361167f3d3ec4c90d1cc4a853fdb429ffc` | `a8376c1c28dc5ddab4533bcdb587dce6ef7fc2382704713487246d005e3dad45` | `ca25d99685ee7f12a48a02469d8f430a2b4c98f97aafce857c6d706185344236` / `da55cda13a7f765e26a095bc2e84f02de9e6d8a6c3c8b310e5fe907bd4e2d4e3` |

The reference parent PID was `904512`; fresh child PIDs were `910089`,
`911878`, and `913671`. Every child validated the full rebuilt schedule and
conditioning/config hashes, recorded fresh dtype FP16 and checkpoint/resume
dtype FP32, used official sampler injection, and measured exactly 35, 20, and
10 remaining actual DiT calls.

The frozen decoded-waveform gate was maximum absolute error `<= 1e-5` and SNR
`>= 80 dB`. All three resumes were stricter than required: each decoded array
was exactly equal to the uninterrupted reference, with maximum and RMS error
zero and infinite SNR under the registered zero-error interpretation. The
common decoded-waveform SHA-256 was
`536b203214fed0e49a52d2debf09f8f84ab7b8a16509dbb2b2786aa9c23ee00d`.

| Output | WAV SHA-256 | Sanity / provenance |
|---|---|---|
| reference | `6bda5c51ee57c952badce63827c5c11e2be2edded1ce92c984ba240b9aa3dd0f` | PASS / valid |
| resume 15 | `60680081e5efda91b12e25505e0ed16c81a5234d28982d523c96d20d4dc7e859` | PASS / valid |
| resume 30 | `1cff775d63c9d69d4f526ae3d208ce7c17b12c878d64fb35b7b7ecd4fff3c663` | PASS / valid |
| resume 40 | `725c9881394a602580d8b53b1a83f8fc08377e79d7b9428c3e1dd73b85a31dc5` | PASS / valid |

Every output is finite, non-silent, stereo, 44.1 kHz, and exactly 30 seconds.
All four WAVs, all three checkpoints, and all three resume-result tensors have
valid adjacent provenance. All audio remains outside Git in the immutable run.

### 14.3 Measured cost and immutable evidence

| Call | Path | Actual DiT NFE | Synchronized wall | Peak allocated / reserved VRAM |
|---|---|---:|---:|---:|
| 01 | uninterrupted reference | 50 | `25.023961771279573 s` | `5,438,810,112 / 9,839,837,184 B` |
| 02 | resume from 15 | 35 | `3.7141848169267178 s` | `5,437,499,392 / 9,839,837,184 B` |
| 03 | resume from 30 | 20 | `2.7067666836082935 s` | `5,437,499,392 / 9,839,837,184 B` |
| 04 | resume from 40 | 10 | `1.8672252222895622 s` | `5,437,499,392 / 9,839,837,184 B` |
| **Retry** | **four calls** | **115** | **`33.31213849410415 s`** | **`5,438,810,112 / 9,839,837,184 B` maximum** |

Model-load wall was `91.32002927735448 s`. Conservative one-GPU residency was
`249.481707109 s`, below both 540 and 600 seconds. The exact plan,
measurement-evidence, call/output, sanity, and ledger gates all terminated
PASS; failed calls = 0. These remain singleton engineering observations and do
not satisfy the benchmark appendix's repetition requirements.

| Root evidence | SHA-256 |
|---|---|
| `result.json` | `10a14bf3fc0d5cddf4dcc8edd07ac0cca2ab8336fab572204ada21d77cb2f117` |
| Smoke E manifest | `27978939dbdef2276f5892f222eeaf9263122c4850cfe21a8f72baffc1da070f` |
| generation ledger | `b9c70678a6198530d2c913d873b3033ebc5ca88dbcc79f11b4961c28695a3024` |
| budget state | `3b80d6e27fa6baed9cc6628c2483a0c7f324a9ad5c1c91d315ac624d128960e7` |
| live placement | `a72bf9c0e996a2d8b856d0b3ffb315755732e6bbc163a279db2f5969c849a1b0` |
| operational log | `0054143ae79877097c890c5e3df11bf001c5bc08e614f3a152cef887152b6579` |

The four-row generation ledger's terminal row hash is
`b8cb48dafad6006e4f5a472608500ea26abd54aedae450cc799966e32f0333b9`.
A read-only audit recomputed every row/predecessor hash, artifact hash, passing
sanity record, checkpoint state hash, and ten adjacent data-provenance records.
The run has 51 files, zero writable entries, directory mode `0555`, file mode
`0444`, and claim mode `0400`.

The outer shell returned 1 only after the E-only Python runner had written its
PASS result and released the GPU: its optional operational-log sidecar used an
unsupported `operational_log` label and omitted `created_at_utc`. The log
itself is retained read-only and hashed above. This packaging defect made no
model call, changed no run artifact, and is not one of the frozen Smoke E PASS
conditions; it is recorded as a deviation rather than hidden or retried.

### 14.4 Terminal scope

This PASS establishes the PI-authorized SA3 foundation/preflight technical
state-capability classification. It does not retroactively make the original
five-smoke run PASS and does not execute Section 11's formal per-axis 25/50/75
captures. Benchmark cost calibration remains insufficiently replicated.

`SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZATION_STATUS = CONSUMED`

`SA3_SMOKE_E_SINGLE_RETRY_AUTHORIZED = NO`

`FOUNDATION_COST_SMOKE_RETRY_AUTHORIZED = NO`

`FOUNDATION_COST_SMOKE_AUTHORIZED = NO`

`BENCHMARK_PREREG_V1_FROZEN = NO`

`BENCHMARK_EXECUTION_AUTHORIZED = NO`
