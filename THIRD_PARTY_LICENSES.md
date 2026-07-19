# Third-party source and license record

## Stable Audio 3 source code

- Package: `stable-audio-3` 0.1.0
- Repository: https://github.com/Stability-AI/stable-audio-3
- Commit: `0385302ea26522f00c80392c4b708df5ebf1adf5`
- Code license file: MIT, copyright Stability AI (2026)
- Installed code-license SHA-256:
  `16bd922f0deee6f11a76f5582258fdc3abdf67c6b8719dbcafbc34dee31979a6`
- Model weights are not covered by this code license; see the weight record
  below.

## stable-audio-tools source code

- Package: `stable-audio-tools` 0.0.20
- Repository: https://github.com/Stability-AI/stable-audio-tools
- Commit: `3241adba4fc2a85cf5b29d9eb68d42f40a28e820`
- Top-level code license: MIT, copyright Stability AI (2023)
- Installed top-level license SHA-256:
  `a1fac33b7bcd791b74fb33aeb439f825e7277e239fc119fb7d2ab6f084a0c101`
- The upstream repository includes additional component license files under
  `LICENSES/`; installed package metadata and dependency licenses are captured
  in `environment/licenses.json`.

## Flash Attention binary

- Runtime package: `flash-attn` 2.6.3
- Upstream source: https://github.com/Dao-AILab/flash-attention
- Source license: BSD-3-Clause
- Installed license-file SHA-256:
  `8c9ccb96c065e706135b6cbad279b721da6156e51f3a5f27c6b3329af9416d73`
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
  `LICENSE.md`, SHA-256
  `d6f6b1a4dce5c852bd6d7d9482d002baf0ccdb71e662250b73be9eec8764ee8d`
- Embedded T5Gemma terms: model-pinned `LICENSE_GEMMA.md` and `NOTICE`, plus
  the Gemma Prohibited Use Policy; file SHA-256s
  `e77acc0d3163bb7534675045c584b4d04b387b529239fc4b3647da0a01ba4745`
  and `66f856d7da72797f528fca46b7c80634ab481f917bfe020960e123d84b19f75f`
- Canonical terms: https://stability.ai/community-license-agreement and
  https://ai.google.dev/gemma/terms

The ModelScope organization identifies itself as “Stability AI - Mirror”; it is
not labelled as the upstream publisher. Every acquired file is pinned and
verified against the recorded ModelScope revision by byte size and SHA-256.
The two weight files, optional SVD bases, and three license/notice files marked
`cross_provider_verified: true` in `provenance/weights.manifest.json` also
match the official public Hugging Face base revision; metadata and tokenizer
files not independently checked across providers are explicitly marked false.
The community license and Gemma terms are use agreements, not permissive
open-source licenses.
