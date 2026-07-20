#!/usr/bin/env bash
set -euo pipefail

readonly REPOSITORY_ROOT="/XYFS02/HDD_POOL/paratera_xy/pxy1289/HaocunYe/Research/newrepo"
readonly RUNTIME_ROOT="/HOME/paratera_xy/pxy1289/sa3_foundation_runtime"
readonly PYTHON_BIN="${RUNTIME_ROOT}/env/bin/python"
readonly RETRY_CONFIG="${REPOSITORY_ROOT}/configs/smoke_e_retry_v1.json"
readonly LOG_ROOT="${RUNTIME_ROOT}/logs"

mkdir -p "${LOG_ROOT}"
readonly START_STAMP="$(${PYTHON_BIN} -c 'from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))')"
readonly LOG_PATH="${LOG_ROOT}/smoke-e-retry-d0019-${START_STAMP}.log"

cd "${REPOSITORY_ROOT}"
export CUDA_VISIBLE_DEVICES=4
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HUB_DISABLE_PROGRESS_BARS=1
export TOKENIZERS_PARALLELISM=false
export SA3_EXECUTION_LOG_PATH="${LOG_PATH}"

set +e
timeout --signal=TERM --kill-after=10s 600s \
  "${PYTHON_BIN}" -m sa3_smoke.run_smoke_e_retry \
  --config "${RETRY_CONFIG}" \
  --repository-root "${REPOSITORY_ROOT}" 2>&1 | tee "${LOG_PATH}"
readonly RUN_STATUS="${PIPESTATUS[0]}"
set -e

"${PYTHON_BIN}" - "${LOG_PATH}" <<'PY'
import subprocess
import sys
from pathlib import Path

from sa3_smoke.artifacts import write_adjacent_provenance

log_path = Path(sys.argv[1]).resolve(strict=True)
git_hash = subprocess.run(
    ["git", "rev-parse", "HEAD"],
    check=True,
    capture_output=True,
    text=True,
).stdout.strip()
write_adjacent_provenance(
    log_path,
    {
        "label": "operational_log",
        "creating_command": "scripts/run_smoke_e_retry_d0019.sh",
        "run_id": log_path.stem,
        "source_ids": [
            f"repository_git_hash:{git_hash}",
            "retry_config_sha256:39553c595659e29e3c0fa691c0d47f344421548ca3ac12157c01fac32a716c84",
        ],
        "model_revision": "b32993f73c3bdc3864043a72d8032606bba737c8",
        "license_identifier": (
            "Stability AI Community License Agreement (2024-07-05) + Gemma Terms of Use"
        ),
        "transformation": "captured stdout and stderr for the one D-0019 execution",
    },
)
PY

exit "${RUN_STATUS}"
