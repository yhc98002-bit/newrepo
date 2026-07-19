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
