## Reuse Policy

Adopt only cross-project operational practice (workflow structure, verification,
file-change safety, environment recording, review protocol, skill boundaries).
Do not import another project's domain facts, results, method names, frozen-file
lists, decisions, approvals, datasets, or metrics unless the user says they apply
here.

## Working Rules

- Inspect local files before assuming.
- Keep edits scoped to the request and the smallest relevant file set; never
  revert unrelated user changes.
- Prefer project-local instructions and skills over global defaults.
- Distinguish proposal / plan / diagnostic evidence / completed experiment /
  claimed result; never present planned, hypothetical, or borrowed results as
  obtained.
- Record assumptions that affect downstream work; verify with the narrowest
  useful check and state what stays unverified.

## Environment

No runtime environment declared yet. Identify it from local files (`README`,
`pyproject.toml`, `requirements.txt`, `environment.yml`, `Makefile`) before
running code, and document any environment you create.

## Operational defaults:

- Do not overwrite checkpoints, generated data, or evaluation outputs.
- Use Hugging Face and GitHub through explicit proxy wrappers only when needed.
- Long-running jobs must write logs under `logs/` or immutable run directories.
- Record node, command, git hash, config hash, seed, artifact path, and deviations.
- Prioritize downloading models from ModelScope.
## Node split:

- `an12`: 8* A800 GPU , NO TIME LIMITS
- `an29`: 8* A800 GPU, NO TIME LIMITS

## GPU placement rules:
- Single-node placement for every job unless it genuinely requires >8 GPUs.
  Never split one training or serving job across an12/an29.
- Tensor parallelism no wider than the model requires: TP1 for models <=7B ¡ª
  for throughput, prefer N independent TP1 replicas with requests sharded
  across them. TP2/TP4 only for models that cannot fit on one GPU (32B/72B).
- Synchronous RL (EasyR1/GRPO) always runs colocated on one node; never
  disaggregate rollout from training across nodes at our scale.
- Every run manifest records: node, GPU ids, TP width, replica count, and one
  line justifying the placement.
- Colocating disjoint-GPU jobs on one node is normal; the researcher's own
  processes are normal neighbors, never anomalies.

## storage status:

  For user pxy1289, usable persistent storage is:

  - /XYFS02/HDD_POOL/paratera_xy/pxy1289: 474.1G / 1.5T used, about 1.0T available.
  - /HOME/paratera_xy/pxy1289: 70G / 100G used, about 31G available.

  Temporary local storage on current node:

  - /tmp or /var/tmp: about 329G available.
  - /dev/shm: about 126G available.


## Pause only at the gates listed in the project prompt.

update to remote github main branch in every prompt round
