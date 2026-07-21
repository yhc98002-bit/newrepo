"""Automatic endpoint scoring for the frozen benchmark-v2 outputs.

The package deliberately separates immutable completed-shard discovery from
GPU-backed feature extraction.  The latter may only provide raw, hash-bound
features; all frozen decisions are recomputed by :mod:`instruments` here.
"""

__all__: list[str] = []
