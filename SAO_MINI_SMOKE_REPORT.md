# Stable Audio Open mini-smoke report

## Outcome

`sao-mini-smoke-v2-003` is `PASS_MEASURED_READY`. The run used the
official offline `stabilityai/stable-audio-open-1.0` snapshot at revision
`f21265c1e2710b3bd2386596943f0007f55f802e`, the dedicated
`sao-env-v2-002` environment, and one preflight-idle A800 on an12 physical
GPU 7 (TP1, one replica). It made exactly three authorized model calls and
retained all three outputs. It scored no benchmark endpoint, made no human-
gold claim, did not attempt state capture, and did not expand eligibility.

The run started at `2026-07-22T16:00:12.617374Z` and finished at
`2026-07-22T16:03:33.666901Z`. All Hugging Face token variables were removed
from the process environment, provider networking was disabled, and the
receipt-bound local snapshot was used throughout.

## Per-call measurements

| Call | Seed | Actual NFE | Wall seconds | Peak allocated / reserved VRAM | Decoded duration | Sanity | Decoded-waveform SHA-256 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 0, reproducibility | S-0011 / 73193011 | 100 | 61.332309 | 8,519,924,736 / 10,710,155,264 B | 29.953741 s | PASS | `c83f50f1e3ef8abf8c2a5b53f4e271af13b7788b342709490ad64e589c291d30` |
| 1, reproducibility | S-0011 / 73193011 | 100 | 19.241406 | 8,528,122,368 / 10,724,835,328 B | 29.953741 s | PASS | `c83f50f1e3ef8abf8c2a5b53f4e271af13b7788b342709490ad64e589c291d30` |
| 2, resident cost | S-0012 / 73193012 | 100 | 19.285982 | 8,538,524,672 / 10,733,223,936 B | 29.953741 s | PASS | `4d949a5e8ebea8384f079f85b2762bcd3e59a600a704bf72884ceefe89ff32fc` |

The two fixed-seed reproducibility calls have identical decoded-waveform
hashes. Every output is finite, active, stereo at 44.1 kHz, unclipped under
the frozen sanity rule, and inside the 0.25-second duration tolerance. The
native output is 1,320,960 samples (29.953741 s); the registered duration
policy adjudicates the exact-sample-count diagnostic without changing the
requested duration or threshold.

Measured model-load wall time is `100.22443418204784 s`. The frozen cost
rule therefore gives `c = 161.5567436106503 s`,
`u = 19.28598228469491 s`, and the conservative 1,536-call cap
`c + 1535 * (2u) = 59,369.522357624024 GPU-s` (`16.491533988228895 GPU-h`).

## Evidence and provenance

- PASS terminal: `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/sao-live-v2/mini-smoke/sao-mini-smoke-v2-003/sao-mini-smoke-terminal.json`, SHA-256 `825eac8e43583871fbb2a4b59f73226e68d5577fecb9255fe82b62dd6945a692`.
- Three-row generation ledger: the same run's `generation-ledger.jsonl`, SHA-256 `cfb5cb32a015fd174f9f061556db29c9e715e89e3715371a91cbf858aa1317c9`.
- Run manifest: the same run's `manifest.json`, SHA-256 `1481056390932b6456743756a56addb1a63aca04b3d7180b491cca12a328f295`.
- D-0050 engineering claim: `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/claims/sao-live-v2/sao-mini-smoke-v2-003.engineering-repair.claim.json`, SHA-256 `173c6bd534730e8da01aa5b3c5afef73b709389ed1c39a6d64a328c1c7ce4f7c`.
- Complete launch log: `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/logs/sao-live-v2/sao-mini-smoke-v2-003.log`, SHA-256 `62e4bb7e567d3a81cc4d38234f01aa05cea2fc3cc76ac57ca1f42be5d9e38c98`.
- Environment manifest: `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/sao-live-v2/engineering/sao-engineering-env-v2-002/provenance/environment-manifest.json`, SHA-256 `45a688fc8fb13cb81abc3da1267c0d90d6475244ca342ac30df9173ba2dc4e4f`.
- Access receipt: `/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/benchmark_v2_runtime/runs/sao-live-v2/acquisition/sao-acquisition-recovery-v2-002/access-receipt.json`, SHA-256 `41f4ac3200c5292ac4f93a992e789031f7a7180f372fb1c3c32a605b91f37b52`.

The earlier ABI-failed smoke and CPU-factory failure remain retained at their
previous hashes. Two subsequent zero-call core-package preparation failures
are separately recorded in
`provenance/b2/sao_core_preparation_engineering_failures_v2.json`; neither
published a config nor consumed GPU or generation authority.
