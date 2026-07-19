# Execution ledger (append-only)

Entries are appended in identifier order. Existing bytes are never edited or
deleted. Corrections use a new entry with `Supersedes` and retain the original.
Planned work, diagnostic evidence, completed execution, and claimed results are
labelled distinctly. A smoke result is not valid unless its immutable run
manifest and artifacts are named here with SHA-256 digests.
