"""IMG4 reconstruction toolkit (R13).

Reassemble Apple's personalised, signed boot files from a PUBLIC .im4p payload
plus a saved APTicket (.im4m) — byte-for-byte, with no Apple server and no
secret (FINDINGS.md:6171). Pure stdlib DER assembly; no third-party dependency.

Public API:
    build_img4, parse_img4, to_filesystem_image   (img4.py)
    der.*                                          (minimal DER helpers)
"""
from __future__ import annotations

from .img4 import MAGIC, build_img4, parse_img4, to_filesystem_image

__all__ = ["build_img4", "parse_img4", "to_filesystem_image", "MAGIC"]
