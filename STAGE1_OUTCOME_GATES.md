# Stage-1 outcome gates

Status: **BLOCKED_MISSING_FROZEN_THRESHOLDS**
Watermark: **AUTOMATIC-INSTRUMENT OUTCOMES**

## Outcome

No Stage-1 cell verdict has been computed. No cancellation ledger has been created.
Consequently, this report does not label any axis/backbone cell
`OUTCOME_SCREEN_PASS` or `STOP_AXIS_STAGE1`, and it does not authorize SA3 or
ACE state execution.

The requested gate requires two numerical thresholds: the minimum BASE
failure rate and the minimum mixed-outcome prompt share. Neither threshold is
defined in the frozen v2 preregistration (SHA-256
`77c8d17d91088ffe9a9c2a47a4af4bb97ffb9d7b7313b4ca0e7e707232a946aa`)
or `configs/statistics_v2.json` (SHA-256
`d2397bee6fa5b93bfde7287fda08c5b804fcf080448bc8ed1a8abb9feaffe36d`).
Repository-wide and full-history searches found no earlier Stage-1 outcome
screen or mixed-outcome threshold. Section 11.4's `0.10` threshold is the
later cross-fitted policy-deviation requirement; substituting it here would
change its meaning and is not permitted.

## Cell table

| Axis | Backbone | BASE failure rate (95% CI) | Mixed-outcome prompt share (95% CI) | Verdict |
| --- | --- | ---: | ---: | --- |
| Integrity | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Integrity | ACE-Step v1 | Not computed | Not computed | Not computed |
| Tempo, primary 5% band | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Tempo, primary 5% band | ACE-Step v1 | Not computed | Not computed | Not computed |
| Vocal/instrumental automatic instrument | stable-audio-3-medium-base | Not computed | Not computed | Not computed |
| Vocal/instrumental automatic instrument | ACE-Step v1 | Not computed | Not computed | Not computed |

“Not computed” is a specification status, not a statistical result or an
`INCONCLUSIVE` verdict.

## Implemented fail-closed evaluator

`src/stage1/gates.py` and `scripts/run_stage1_outcome_gates.py` implement the
CPU-only calculation without inventing the missing thresholds. The runner
validates the policy before reading any scored row or state queue. It requires:

- an explicit decision ID and `status = FROZEN`;
- both thresholds as finite values in `[0,1]`;
- the exact 12 eligibility prompts per axis from
  `configs/statistics_v2.json`, BASE condition, and roots `0..7`;
- the registered primary automatic outcome: integrity failure, tempo success
  at the primary 5% tolerance, or vocal/instrumental automatic-instrument
  success;
- 10,000 deterministic stratified prompt-cluster/matched-root bootstrap
  draws at the frozen v2 seed; and
- immutable SHA bindings for the scored rows and both materialized initial
  state queues.

Once valid thresholds are frozen, a cell passes only if both point estimates
meet their respective minima. Each STOP cell produces exactly 144
`CANCELLED_STAGE1` unit events (12 prompts × four initial roots × three
checkpoints) in an append-only SHA-256 chain. Every cancellation prohibits
both `EXECUTE` and `SCORE`; queue incompleteness, duplicate identities, or hash
drift is fatal before artifact creation.

## Current evidence and required resolution

The machine-readable readiness record is
`provenance/stage1/stage1_outcome_gate_readiness.json`. The blocked template is
`configs/stage1_outcome_gates_v2.json`. Its threshold fields are deliberately
`null`, so an accidental invocation fails before it can create a result or
cancellation directory.

A new PI decision must explicitly freeze
`baseline_failure_rate_minimum` and
`mixed_outcome_prompt_share_minimum`. Until that happens, all formal SA3 and
ACE state queues remain closed at Stage-1; this report supplies no survivor
set.
