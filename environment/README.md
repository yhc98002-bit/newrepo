# Frozen runtime environment

The environment is recreated only from committed `pyproject.toml` plus
`uv.lock`:

```bash
UV_PROJECT_ENVIRONMENT=/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env \
  uv sync --frozen --all-groups
```

- Python: CPython 3.10.12 (`.python-version`)
- PyTorch: 2.7.1, selected by both upstream packages
- torchaudio: 2.7.1, selected by both upstream packages
- CUDA wheel channel: cu126, the upstream default
- Flash Attention: 2.6.3 cu126/torch2.7/cp310 prebuilt wheel, SHA-256
  `85909aa24df69b530111cde4c878bb866538211911af46c21676ef48437c0307`
- Runtime path: `/HOME/paratera_xy/pxy1289/sa3_foundation_runtime/env`
- Validated node/GPU: `an12`, GPU 0, NVIDIA A800 80 GB, TP1, one replica
- Observed driver before installation: 535.104.12

The GPU 0 row above is the immutable environment-creation validation. Before
model execution, a normal neighboring job occupied physical GPUs 0-3, so
`environment/gpu-placement-v2.json` and `configs/foundation_v2.json`
superseded only the execution placement to idle physical GPU 4. The process
uses `CUDA_VISIBLE_DEVICES=4` and addresses that sole visible device as
`cuda:0`; TP1 and one replica are unchanged.

CUDA 12.x minor-version compatibility was verified empirically on `an12`: a
CUDA tensor allocation and a Flash Attention 2 kernel both passed. It is not
inferred from the login node, which has no visible GPU.

`environment/package-freeze.txt`, `environment/licenses.json`, and their
SHA-256s were generated after the frozen sync. No secrets are stored in the
environment or repository.

The requested `/XYFS02` repository received project ID `2228473301` with no
writable block quota (a 1 MiB write failed while the repository occupied only
528 KiB). The live checkout and runtime were therefore placed in the declared
`/HOME` allocation and the exact requested path now symlinks to that checkout.
The original checkout is preserved, not deleted, at
`../newrepo.xyfs-project-quota-backup-20260719T113200Z`.
