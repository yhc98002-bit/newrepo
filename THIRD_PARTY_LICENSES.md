# Third-party source and license record

## Stable Audio 3 source code

- Package: `stable-audio-3` 0.1.0
- Repository: https://github.com/Stability-AI/stable-audio-3
- Commit: `0385302ea26522f00c80392c4b708df5ebf1adf5`
- Code license file: MIT, copyright Stability AI (2026)
- Model weights are not covered by this code license; see the weight record
  below.

## stable-audio-tools source code

- Package: `stable-audio-tools` 0.0.20
- Repository: https://github.com/Stability-AI/stable-audio-tools
- Commit: `3241adba4fc2a85cf5b29d9eb68d42f40a28e820`
- Top-level code license: MIT, copyright Stability AI (2023)
- The upstream repository includes additional component license files under
  `LICENSES/`; installed package metadata and dependency licenses are captured
  in `environment/licenses.json`.

## Flash Attention binary

- Runtime package: `flash-attn` 2.6.3
- Upstream source: https://github.com/Dao-AILab/flash-attention
- Source license: BSD-3-Clause
- Binary builder/release: `mjun0812/flash-attention-prebuild-wheels` tag
  `v0.7.16` (community build recommended by the pinned Stable Audio 3 README)
- Wheel: `flash_attn-2.6.3+cu126torch2.7-cp310-cp310-linux_x86_64.whl`
- Size: 184,923,350 bytes
- SHA-256: `85909aa24df69b530111cde4c878bb866538211911af46c21676ef48437c0307`

## Stable Audio 3 Medium Base weights

- Model ID: `stabilityai/stable-audio-3-medium-base`
- ModelScope mirror revision: `a9c479f5f28ee89f6fbdaca57b683e6b6c160314`
- Official Hugging Face verification revision:
  `b32993f73c3bdc3864043a72d8032606bba737c8`
- Weight license: Stability AI Community License Agreement, model-pinned
  `LICENSE.md`
- Embedded T5Gemma terms: model-pinned `LICENSE_GEMMA.md` and `NOTICE`, plus
  the Gemma Prohibited Use Policy
- Canonical terms: https://stability.ai/community-license-agreement and
  https://ai.google.dev/gemma/terms

The ModelScope organization identifies itself as “Stability AI - Mirror”; it is
not labelled as the upstream publisher. Every acquired file is verified by
SHA-256 against the official public base repository before use. The community
license and Gemma terms are use agreements, not permissive open-source licenses.
