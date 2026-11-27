# Findings registry

A machine-readable distillation of [`FINDINGS.md`](../../FINDINGS.md) so a reader
— or a tool — can see each finding's **final** status without re-reading the
6,400-line notebook, and so retractions are explicit and nobody builds on a
disproven result.

`FINDINGS.md` is an append-only lab notebook that must be read bottom-up and
contains breakthroughs that were later disproven (see `README.md` lines 7-8).
This registry pins the final state of each thread and links retractions to the
entry that killed them.

> **Not a source of truth.** `FINDINGS.md` and the top-level `README.md` remain
> authoritative. Every entry here cites them by `FILE:LINE`. When the two
> disagree, fix the registry — not the notebook.

## Files

| File | Purpose |
| :--- | :--- |
| `findings.toml` | the registry: one entry per finding |
| `validate.py`   | structural validator (stdlib only) |
| `test_validate.py` | unittest suite for the validator |

## Requirements

Python **3.11+** only (stdlib `tomllib`, `unittest`). No third-party packages,
no network. `python3 validate.py` and the tests run first try.

## Usage

```sh
# validate the registry against the live source documents
python3 tools/findings/validate.py

# run the tests
python3 -m unittest discover -s tools/findings
```

`validate.py` exits `0` when the registry is well-formed, `1` with a list of
`FAIL …` lines otherwise, and `2` if the Python runtime is too old.

## Entry schema

```toml
[[findings]]
id = "R14.3"                        # unique, stable handle (R-number or slug)
status = "open"                     # see vocabulary below
evidence = ["FINDINGS.md:6425"]     # FILE:LINE anchors into the source docs
title = '''one-paragraph summary of the finding'''
# optional cross-references:
related       = ["R14", "R14.2"]    # loosely-coupled entry ids
supersedes    = ["old-id"]          # this entry replaces another (reciprocated)
superseded_by = ["new-id"]          # this entry was replaced
retracted_by  = "FINDINGS.md:6199"  # FILE:LINE of what disproved this entry
history       = '''what intermediate claim was withdrawn, and why'''
```

### `status` vocabulary

| value | meaning |
| :--- | :--- |
| `confirmed` | proven on hardware or by exact byte/MD5 match |
| `proven_static` | proven by instruction-level static analysis (no pod needed) |
| `open` | active, not yet resolved |
| `closed_negative` | a real avenue tested and shown to be a dead end |
| `retracted` | a claim recorded and later disproven; kept so it is not re-attempted |

## What the validator checks

- **schema** — required keys present and correctly typed.
- **ids** — unique and non-empty.
- **status** — drawn from the vocabulary above.
- **evidence** — every `FILE:LINE` anchor names a file that exists and a line
  within that file's length.
- **references** — `supersedes` / `superseded_by` / `related` resolve to real
  entries; `retracted_by` is a resolvable anchor.
- **hygiene** — a `retracted` entry has a `retracted_by`; supersede links are
  reciprocated.

### What it deliberately does *not* check

Whether a `confirmed` entry is actually contradicted by a later retraction. That
is a **semantic** judgement about the research and cannot be made mechanically
from line anchors. Keeping it human is intentional: this tool guards the
registry's structure, not the correctness of the science.

## Maintaining it

Line anchors drift when the source documents are edited. After editing
`FINDINGS.md` / `README.md` / `TODO.md`, re-run `validate.py`; it flags any
anchor that now falls outside its file (it does **not** detect an anchor that
still lands in-file but now points at different text — that re-check is manual).
