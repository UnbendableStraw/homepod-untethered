"""APFS Fletcher-64 object checksum: compute, forge, verify.

Why this exists
---------------
iBoot-5540.140.12 parses the APFS container on disk1s1 BEFORE it authenticates
any IMG4 payload, and the only integrity protection on those on-disk structures
is an UNKEYED Fletcher-64 (FINDINGS.md R13.2, line 6224). Because it is unkeyed
and seeded with 0, anyone can recompute a valid checksum for an arbitrary,
attacker-controlled structure. This module is the tool that does that — it is
step 1 of the R14 audit harness loop (FINDINGS.md:6294, "recompute Fletcher-64
over obj+8 (0x162c8 algorithm) so it passes integrity").

What the repo pins down (verified, FINDINGS.md:6227)
----------------------------------------------------
The verifier at iBoot 0x162c8 is "plain Fletcher-64 (tst x1,#3 alignment,
lsr x10,x1,#2 word count, lsr x8,x2,#0x20 / and x9,x2,#0xffffffff dual 32-bit
accumulators), seed 0, covering the object from +8" — i.e. it checksums the
object body starting at byte offset 8 (just past the 8-byte o_cksum field) as a
stream of little-endian 32-bit words, with two 32-bit accumulators.

Correctness status (confirmed)
------------------------------
The modular-reduction form below is the standard APFS fletcher64 (Apple File
System Reference). It is CONFIRMED BYTE-EXACT against real Apple-written data:
`verify_object()` accepts the stored o_cksum of genuine APFS container
superblocks (proven against 3 NXSB blocks in a throwaway `hdiutil`-created APFS
image; reproduce with the gold test, see test_apfs.py / README). It is also
internally self-consistent by construction (verify(apply(obj)) is always True).

Remaining inference: that iBoot-5540.140.12's reader at 0x162c8 uses this same
algorithm. This is strongly supported — the repo's own disassembly describes
0x162c8 as "plain Fletcher-64 (dual 32-bit accumulators), seed 0, covering the
object from +8" (FINDINGS.md:6227), which is exactly this function — but it is an
inference from matching descriptions, not from executing iBoot's code directly.
"""
from __future__ import annotations

import struct

# Fletcher-64 modulus. The APFS variant reduces each accumulator modulo
# 2**32 - 1 (0xFFFFFFFF), not 2**32.
_MOD32 = 0xFFFFFFFF

# The object checksum (o_cksum) occupies the first 8 bytes of every APFS object
# (obj_phys_t.o_cksum, FINDINGS.md:6327). The checksum covers everything AFTER
# it, i.e. object bytes [8:].
CKSUM_SIZE = 8


def _words_le(data: bytes) -> tuple[int, ...]:
    """Interpret `data` as a stream of little-endian uint32 words."""
    if len(data) % 4 != 0:
        raise ValueError(
            f"Fletcher-64 input must be a multiple of 4 bytes, got {len(data)}"
        )
    return struct.unpack(f"<{len(data) // 4}I", data)


def _accumulate(words: tuple[int, ...]) -> tuple[int, int]:
    """The two 32-bit running sums (the 'dual accumulators' of 0x162c8)."""
    sum1 = 0
    sum2 = 0
    for word in words:
        sum1 = (sum1 + word) % _MOD32
        sum2 = (sum2 + sum1) % _MOD32
    return sum1, sum2


def fletcher64(body: bytes) -> int:
    """Compute the 8-byte APFS Fletcher-64 check value for an object `body`.

    `body` is the object bytes AFTER the 8-byte o_cksum field (i.e. obj[8:]),
    which is exactly the range iBoot's 0x162c8 covers ("from +8"). Returns the
    64-bit value to store, little-endian, in o_cksum.
    """
    sum1, sum2 = _accumulate(_words_le(body))
    # The two check words are chosen so that a subsequent accumulation over the
    # body *plus* these words lands on zero — the self-annihilating property
    # that makes the stored checksum verifiable.
    check1 = _MOD32 - ((sum1 + sum2) % _MOD32)
    check2 = _MOD32 - ((sum1 + check1) % _MOD32)
    return (check2 << 32) | check1


def compute_object_checksum(obj: bytes) -> int:
    """Return the o_cksum value for a full object (first 8 bytes = the slot)."""
    if len(obj) < CKSUM_SIZE + 4:
        raise ValueError(f"object too small ({len(obj)} bytes) to checksum")
    return fletcher64(obj[CKSUM_SIZE:])


def apply_checksum(obj: bytes) -> bytes:
    """Return `obj` with a freshly-forged, valid o_cksum in its first 8 bytes.

    This is the forge primitive: hand it any object whose body you have
    tampered with, and it returns bytes that pass iBoot's integrity check.
    """
    cksum = compute_object_checksum(obj)
    return struct.pack("<Q", cksum) + obj[CKSUM_SIZE:]


def verify_object(obj: bytes) -> bool:
    """True if `obj`'s stored o_cksum matches a recomputation over obj[8:]."""
    stored = struct.unpack("<Q", obj[:CKSUM_SIZE])[0]
    return stored == compute_object_checksum(obj)
