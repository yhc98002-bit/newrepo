#!/usr/bin/env python3
"""Emit strict JSON evidence for one physical-GPU SA3 placement."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physical-gpu-id", required=True)
    args = parser.parse_args()

    physical_gpu_id = str(args.physical_gpu_id)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible != physical_gpu_id:
        raise RuntimeError(f"CUDA_VISIBLE_DEVICES must be {physical_gpu_id!r}, got {visible!r}")

    import flash_attn
    import torch
    from flash_attn import flash_attn_func

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("placement validation requires exactly one visible CUDA GPU")
    query = subprocess.run(
        [
            "nvidia-smi",
            f"--id={physical_gpu_id}",
            "--query-gpu=index,name,driver_version,memory.used,memory.free,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    index, name, driver, memory_used, memory_free, utilization = (
        item.strip() for item in query.split(",")
    )

    query_tensor = torch.randn((1, 16, 3, 64), device="cuda:0", dtype=torch.float16)
    output = flash_attn_func(query_tensor, query_tensor, query_tensor)
    torch.cuda.synchronize()
    evidence = {
        "capability": list(torch.cuda.get_device_capability(0)),
        "cuda_visible_devices": visible,
        "device_name": torch.cuda.get_device_name(0),
        "driver": driver,
        "flash_attn": flash_attn.__version__,
        "flash_kernel_finite": bool(torch.isfinite(output).all().item()),
        "memory_free_mib": int(memory_free),
        "memory_used_mib": int(memory_used),
        "node": socket.gethostname().split(".", maxsplit=1)[0],
        "nvidia_smi_name": name,
        "physical_gpu_id": int(index),
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda,
        "utilization_percent": int(utilization),
        "visible_device_count": torch.cuda.device_count(),
        "visible_index": 0,
    }
    print(json.dumps(evidence, allow_nan=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
