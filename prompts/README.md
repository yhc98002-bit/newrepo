# Benchmark v2 prompt package

`v2/` is generated once by `build_v2_prompts.py` and then frozen by SHA-256 in
`DECISIONS.md`. The builder uses exclusive creation and will not replace an
existing prompt artifact. Each JSON row contains the exact base prompt and the
exact fixed-intervention suffix used by every eligible backbone.

The seed rule is model-, prompt-, and root-specific. Equal root indices align
the registered design but are not described as common random noise across
architectures.
