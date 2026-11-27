"""Tests for the findings registry validator (stdlib unittest — no dependency).

Run any of:
    python3 tools/findings/test_validate.py
    python3 -m unittest discover -s tools/findings
    cd tools/findings && python3 -m unittest

Covers two things:
  1. the REAL registry (findings.toml) is valid against the live source docs;
  2. each individual check actually fires on a crafted-bad registry (so the
     validator cannot silently rot into a no-op).
"""
from __future__ import annotations

import sys
import textwrap
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
REAL_REGISTRY = HERE / "findings.toml"

# Allow `python3 test_validate.py` from any cwd by importing the sibling module.
sys.path.insert(0, str(HERE))
import validate  # noqa: E402


class RealRegistryTests(unittest.TestCase):
    """The committed registry must be valid against the committed source docs."""

    def test_real_registry_is_valid(self):
        errors = validate.validate(REAL_REGISTRY, REPO_ROOT)
        self.assertEqual(errors, [], "live registry should validate cleanly")

    def test_every_status_is_represented(self):
        # Guards against a future edit that accidentally drops a whole category.
        with REAL_REGISTRY.open("rb") as fh:
            data = tomllib.load(fh)
        seen = {e["status"] for e in data["findings"]}
        self.assertTrue(
            validate.ALLOWED_STATUS <= seen,
            f"missing status categories: {validate.ALLOWED_STATUS - seen}",
        )


class CheckFiringTests(unittest.TestCase):
    """Each validator check must actually fire on a crafted-bad registry."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        # A source doc with a known length: exactly 10 lines.
        (self.repo / "FINDINGS.md").write_text(
            "\n".join(str(n) for n in range(1, 11))
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _registry(self, body: str) -> Path:
        path = self.repo / "findings.toml"
        path.write_text(textwrap.dedent(body))
        return path

    def _validate(self, body: str) -> list[str]:
        return validate.validate(self._registry(body), self.repo)

    def test_duplicate_id(self):
        errors = self._validate(
            """
            [[findings]]
            id = "dup"
            status = "open"
            title = "first"
            evidence = ["FINDINGS.md:1"]

            [[findings]]
            id = "dup"
            status = "open"
            title = "second"
            evidence = ["FINDINGS.md:2"]
            """
        )
        self.assertTrue(any("duplicate id" in e for e in errors), errors)

    def test_bad_status(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "probably-true"
            title = "t"
            evidence = ["FINDINGS.md:1"]
            """
        )
        self.assertTrue(any("status" in e for e in errors), errors)

    def test_missing_evidence(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "open"
            title = "t"
            evidence = []
            """
        )
        self.assertTrue(any("evidence" in e for e in errors), errors)

    def test_anchor_line_out_of_range(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "open"
            title = "t"
            evidence = ["FINDINGS.md:999"]
            """
        )
        self.assertTrue(any("outside" in e for e in errors), errors)

    def test_anchor_missing_file(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "open"
            title = "t"
            evidence = ["NOPE.md:1"]
            """
        )
        self.assertTrue(any("missing file" in e for e in errors), errors)

    def test_unknown_reference(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "open"
            title = "t"
            evidence = ["FINDINGS.md:1"]
            related = ["ghost"]
            """
        )
        self.assertTrue(any("unknown id 'ghost'" in e for e in errors), errors)

    def test_retracted_without_retracted_by(self):
        errors = self._validate(
            """
            [[findings]]
            id = "x"
            status = "retracted"
            title = "t"
            evidence = ["FINDINGS.md:1"]
            """
        )
        self.assertTrue(any("no 'retracted_by'" in e for e in errors), errors)

    def test_supersede_reciprocity(self):
        errors = self._validate(
            """
            [[findings]]
            id = "new"
            status = "open"
            title = "t"
            evidence = ["FINDINGS.md:1"]
            supersedes = ["old"]

            [[findings]]
            id = "old"
            status = "retracted"
            title = "t"
            evidence = ["FINDINGS.md:2"]
            retracted_by = "FINDINGS.md:2"
            """
        )
        self.assertTrue(any("superseded_by" in e for e in errors), errors)

    def test_well_formed_registry_passes(self):
        errors = self._validate(
            """
            [[findings]]
            id = "new"
            status = "open"
            title = "t"
            evidence = ["FINDINGS.md:1"]
            supersedes = ["old"]

            [[findings]]
            id = "old"
            status = "retracted"
            title = "t"
            evidence = ["FINDINGS.md:2"]
            retracted_by = "FINDINGS.md:2"
            superseded_by = ["new"]
            """
        )
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
