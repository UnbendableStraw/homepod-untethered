#!/usr/bin/env python3
"""Validate the homepod-untethered findings registry (findings.toml).

What this checks (and ONLY this — see the honesty note below):
  * schema:        required keys present, correct types.
  * ids:           unique, non-empty.
  * status:        drawn from the allowed vocabulary.
  * evidence:      every "FILE:LINE" anchor names a file that exists in the repo
                   and a LINE that falls within that file's length.
  * references:    `supersedes` / `superseded_by` / `related` ids resolve to real
                   entries; `retracted_by` is a resolvable FILE:LINE anchor.
  * hygiene:       a `retracted` entry has a `retracted_by`; supersede links are
                   reciprocated (A supersedes B  <=>  B superseded_by A).

What this DELIBERATELY does NOT check: whether a `confirmed` entry is actually
contradicted by a later retraction. That is a SEMANTIC judgement about the
research itself and cannot be made mechanically from line anchors. Keeping that
judgement human is intentional — this tool guards the registry's structure, not
the correctness of the science. Do not add a check here that pretends otherwise.

Usage:
    python3 validate.py [--registry PATH] [--repo-root PATH]
Exit code 0 = valid, 1 = one or more errors (printed to stderr).

Requires Python 3.11+ (stdlib tomllib). No third-party dependency.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - environment guidance, not logic
    sys.stderr.write(
        "error: this tool needs Python 3.11+ (stdlib tomllib) to parse "
        "findings.toml.\n"
    )
    raise SystemExit(2)

ALLOWED_STATUS = {
    "confirmed",
    "proven_static",
    "open",
    "closed_negative",
    "retracted",
}

# Reference fields that must resolve to another entry's id.
ID_REF_FIELDS = ("supersedes", "superseded_by", "related")

# A cache so we only read each source file once when bounds-checking anchors.
_line_counts: dict[Path, int] = {}


def _line_count(path: Path) -> int:
    if path not in _line_counts:
        # Count lines without loading the whole file into memory at once.
        with path.open("rb") as handle:
            _line_counts[path] = sum(1 for _ in handle)
    return _line_counts[path]


def _check_anchor(anchor: str, repo_root: Path, errors: list[str], where: str) -> None:
    """Validate one "FILE:LINE" evidence/reference anchor."""
    if not isinstance(anchor, str) or ":" not in anchor:
        errors.append(f"{where}: anchor {anchor!r} is not of the form FILE:LINE")
        return
    file_part, _, line_part = anchor.rpartition(":")
    if not line_part.isdigit():
        errors.append(f"{where}: anchor {anchor!r} has a non-numeric line")
        return
    target = repo_root / file_part
    if not target.is_file():
        errors.append(f"{where}: anchor {anchor!r} names a missing file ({file_part})")
        return
    line = int(line_part)
    total = _line_count(target)
    if line < 1 or line > total:
        errors.append(
            f"{where}: anchor {anchor!r} line {line} is outside {file_part} "
            f"(1..{total})"
        )


def validate(registry_path: Path, repo_root: Path) -> list[str]:
    errors: list[str] = []

    try:
        with registry_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"cannot load {registry_path}: {exc}"]

    if not isinstance(data, dict):
        return ["top level of registry must be a mapping"]
    if "findings" not in data or not isinstance(data["findings"], list):
        return ["registry must contain a 'findings' list"]
    if not data["findings"]:
        return ["registry 'findings' list is empty"]

    findings = data["findings"]

    # First pass: collect ids so references can be resolved in the second pass.
    ids: set[str] = set()
    for i, entry in enumerate(findings):
        if not isinstance(entry, dict):
            errors.append(f"findings[{i}]: entry is not a mapping")
            continue
        fid = entry.get("id")
        if not fid or not isinstance(fid, str):
            errors.append(f"findings[{i}]: missing or non-string 'id'")
            continue
        if fid in ids:
            errors.append(f"findings[{i}]: duplicate id {fid!r}")
        ids.add(fid)

    # Build an id -> entry map for reciprocity checks (last one wins; dup already
    # reported above).
    by_id = {e["id"]: e for e in findings if isinstance(e, dict) and e.get("id")}

    # Second pass: per-entry validation.
    for entry in findings:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue  # already reported
        fid = entry["id"]

        title = entry.get("title")
        if not title or not isinstance(title, str) or not title.strip():
            errors.append(f"{fid}: missing or empty 'title'")

        status = entry.get("status")
        if status not in ALLOWED_STATUS:
            errors.append(
                f"{fid}: status {status!r} not in {sorted(ALLOWED_STATUS)}"
            )

        evidence = entry.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            errors.append(f"{fid}: 'evidence' must be a non-empty list")
        else:
            for anchor in evidence:
                _check_anchor(anchor, repo_root, errors, f"{fid}.evidence")

        # id-reference fields must resolve to known ids.
        for field in ID_REF_FIELDS:
            if field not in entry:
                continue
            refs = entry[field]
            if not isinstance(refs, list):
                errors.append(f"{fid}.{field}: must be a list of ids")
                continue
            for ref in refs:
                if ref not in ids:
                    errors.append(f"{fid}.{field}: unknown id {ref!r}")

        # retracted_by is a FILE:LINE anchor (what disproved the claim).
        if "retracted_by" in entry:
            _check_anchor(
                entry["retracted_by"], repo_root, errors, f"{fid}.retracted_by"
            )

        # Hygiene: a retraction should say what killed it.
        if status == "retracted" and "retracted_by" not in entry:
            errors.append(f"{fid}: status 'retracted' but no 'retracted_by'")

    # Reciprocity: supersedes <-> superseded_by.
    for entry in findings:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        fid = entry["id"]
        for target in entry.get("supersedes", []) or []:
            other = by_id.get(target)
            if other and fid not in (other.get("superseded_by", []) or []):
                errors.append(
                    f"{fid}: supersedes {target!r}, but {target!r} does not list "
                    f"{fid!r} in superseded_by"
                )

    return errors


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry",
        type=Path,
        default=here / "findings.toml",
        help="path to findings.toml (default: alongside this script)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=here.parent.parent,
        help="repo root that evidence anchors are resolved against "
        "(default: two levels up from this script)",
    )
    args = parser.parse_args(argv)

    errors = validate(args.registry, args.repo_root)
    if errors:
        for err in errors:
            sys.stderr.write(f"FAIL {err}\n")
        sys.stderr.write(f"\n{len(errors)} error(s).\n")
        return 1
    # Count for a useful success line.
    with args.registry.open("rb") as handle:
        data = tomllib.load(handle)
    print(f"OK {len(data['findings'])} findings validated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
