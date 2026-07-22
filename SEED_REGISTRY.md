# Seed registry (append-only)

Registry version 1 was frozen on 2026-07-19 before results. Existing rows are
never edited or removed; a new row may supersede one only by identifier.

| Seed ID | Integer | Intended use | Supersedes |
| --- | ---: | --- | --- |
| S-0001 | 73193001 | Smoke A, both fixed-seed 30 s generations | none |
| S-0002 | 73193002 | Smoke B, 10 s source and continuation | none |
| S-0003 | 73193003 | Smoke C, single-segment inpainting | none |
| S-0004 | 73193004 | Smoke C, multi-segment inpainting | none |
| S-0005 | 73193005 | Smoke D, 50-step batch-one cost run | none |
| S-0006 | 73193006 | Smoke D, batch-four throughput run | none |
| S-0007 | 73193007 | Smoke E, uninterrupted and resumed paths | none |
| S-0008 | 73193008 | B2 ACE-Step v1 mini-smoke job 1, non-benchmark cost calibration | none |
| S-0009 | 73193009 | B2 ACE-Step v1 mini-smoke job 2, non-benchmark resident-call cost calibration | none |
| S-0010 | 73193010 | ACE-Step v1 state preflight reference/export/resume equivalence, non-benchmark | none |
| S-0011 | 73193011 | Stable Audio Open 1.0 mini-smoke calls 0/1, identical-seed reproducibility pair, non-benchmark | none |
| S-0012 | 73193012 | Stable Audio Open 1.0 mini-smoke call 2, resident-call cost calibration, non-benchmark | none |
