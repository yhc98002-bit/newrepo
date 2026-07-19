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
