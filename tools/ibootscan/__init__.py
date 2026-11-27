"""ibootscan — a static-analysis aid for the R14.3 APFS btree-walker audit.

Software-only, offline, zero third-party dependencies (Python 3.11+). It consumes
a disassembly listing the researcher produces from their OWN extracted iBoot and
flags on-disk-derived counts/offsets whose use is not guarded by the R14.2
capacity-check idiom (FINDINGS.md:6403-6412, 6456-6467). It ships no Apple code
and decodes no raw bytes; it reasons over text a disassembler already produced.
"""
from __future__ import annotations

from . import asm, idiom, taint, scan

__all__ = ["asm", "idiom", "taint", "scan"]
