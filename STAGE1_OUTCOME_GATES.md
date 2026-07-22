# Stage-1 outcome gates

Status: **STAGE1_OUTCOME_GATES_COMPLETE**

Watermark: **AUTOMATIC-INSTRUMENT OUTCOMES**

Human-gold claims: **NO**

## Frozen rule and execution order

D-0046 froze the policy on pushed commit
`5d686cb50eb310557d153fb14d8916d84a37c5c5` before the CPU runner opened
the scored outcome JSONL:

```text
OUTCOME_SCREEN_PASS iff
0.10 <= BASE failure rate <= 0.60
AND mixed-outcome prompt share >= 0.20
```

A mixed-outcome prompt is a registered BASE prompt with at least one success
and at least one failure among its eight registered roots. The gate uses point
estimates; the 95% intervals are reported but do not change a verdict.
Intervals use 10,000 deterministic stratified prompt-cluster/matched-root
bootstrap replicates.

## Verdict table

| Axis | Backbone | BASE failure rate (95% CI) | Mixed-outcome prompt share (95% CI) | Verdict |
| --- | --- | ---: | ---: | --- |
| Acoustic integrity | ACE-Step v1 | 0.3333 [0.1250, 0.5625] | 0.5833 [0.1667, 0.6667] | `OUTCOME_SCREEN_PASS` |
| Acoustic integrity | stable-audio-3-medium-base | 0.8229 [0.7083, 0.9271] | 0.6667 [0.2500, 0.8333] | `STOP_AXIS_STAGE1` |
| Tempo, primary 5% band | ACE-Step v1 | 0.8958 [0.8125, 0.9688] | 0.5833 [0.1667, 0.6667] | `STOP_AXIS_STAGE1` |
| Tempo, primary 5% band | stable-audio-3-medium-base | 0.7604 [0.6458, 0.8646] | 0.8333 [0.4167, 0.9167] | `STOP_AXIS_STAGE1` |
| Vocal/instrumental automatic instrument | ACE-Step v1 | 0.6458 [0.4583, 0.8125] | 0.7500 [0.4167, 0.9167] | `STOP_AXIS_STAGE1` |
| Vocal/instrumental automatic instrument | stable-audio-3-medium-base | 0.5104 [0.2604, 0.7500] | 0.5000 [0.0833, 0.6667] | `OUTCOME_SCREEN_PASS` |

These are automatic-instrument outcome screens, not human findings or
evaluator-accuracy estimates.

## Survivor and cancellation partition

Exactly two cells survive:

- ACE-Step v1: acoustic integrity only, 144 initial state units;
- stable-audio-3-medium-base: vocal/instrumental only, 144 initial state
  units.

The other four cells contain 576 initial state units in total. Every one has an
immutable `CANCELLED_STAGE1` event that prohibits both `EXECUTE` and
`SCORE`. Supplemental roots 4–7 remain locked.

The immutable run root is:

```text
/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/
benchmark_v2_runtime/runs/stage1-outcome-gates-v2/
stage1-outcome-gates-v2-001
```

Key identities:

| Artifact | SHA-256 |
| --- | --- |
| Machine-readable verdict table | `5e9d2e7ee1132733a31b64e05900774a1f6f29e6e19ab3f828027ebba48d7157` |
| Cancellation summary | `7234e464b263191400fb42a48ef628fafa3478fa0261e88cbf61d71aad807121` |
| Cancellation manifest | `b0b115721e1b72654bb63dfc0daaa31b04b1176d56ba25c6b327f41c35de0e60` |
| Cancellation units JSONL | `c230acba809f6df98ce1552db2da8439c197a3147565e86ea57862d036f699e1` |
| Survivor index | `c762a51961784629df43a01ef61f901bfd5cafebef796bb32c3e34ef6fafdf79` |
| ACE survivor manifest | `f7d2dcd8acc274625de392f29178926f76bd2f67344713ecef6cec313b29ce67` |
| ACE survivor units | `6ae0d8e13f625bd935e9a285b98c79c24f2469b68706ad7e1ae2e576cb637a1f` |
| SA3 survivor manifest | `df6ddd9730346db172140ad24c6af86d0347a7820c020499bfd92b84b15cee68` |
| SA3 survivor units | `f5d31edfc177d013f240d83540b3d0274eea0a799f9b76fe0ff02395cff1c600` |
| Execution receipt | `3778acf7f495d6036f7a8dabf075996a4d77f34269e264cf27e01be53a559d7c` |

All 586 material files in the run tree are mode 0444. The deterministic tree
digest excluding the append-lock file is
`e58b6c9722157465cfb922f5a27aa1c67abf05ad64c07dafae3e25815931c958`.
Deep terminal validation recomputed the policy, all six cells, the complete
cancellation chain, and the immutable source bindings.

## Cost

This lane was CPU-only on `ln206`: 8.46 seconds wall time, 80,572 KiB
maximum RSS, zero GPU-seconds, zero model calls, zero generation calls, and no
engineering failure or repair.

## Historical blocked record

`provenance/stage1/stage1_outcome_gate_readiness.json` remains the immutable
pre-D-0046 record showing why the earlier runner was blocked. It is superseded
for current status by
`provenance/stage1/stage1_outcome_gate_policy_freeze_v2.json` and
`provenance/stage1/stage1_outcome_gates_terminal_v2.json`; it was not
rewritten.
