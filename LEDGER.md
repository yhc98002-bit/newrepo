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
