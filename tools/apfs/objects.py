"""APFS object header (obj_phys_t) and object-type constants.

Every physical/virtual APFS object begins with a 32-byte obj_phys_t header.
Layout (verified, FINDINGS.md:6327 — the R14.1 correction):

    offset  size  field
    0x00    8     o_cksum      Fletcher-64 over obj[8:]  (see fletcher.py)
    0x08    8     o_oid        object id
    0x10    8     o_xid        transaction id
    0x18    4     o_type       storage-class flags (high) | type (low 16)
    0x1c    4     o_subtype
    0x20    ...   type-specific body begins here

Object-type constants below are taken ONLY from values the repo actually
observed in iBoot.dec; each cites its source line. We do not import the wider
APFS type enumeration from memory.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .fletcher import apply_checksum

HEADER_SIZE = 0x20  # obj_phys_t is 32 bytes (FINDINGS.md:6327)

# --- o_type bit layout -------------------------------------------------------
# The low 16 bits select the object type; high bits are storage-class flags.
# Masks are the ones iBoot's code actually applies:
OBJ_TYPE_MASK = 0x0000FFFF        # btree check: `and w8,#0xffff; cmp #2` (FINDINGS.md:6432)
OBJ_STORAGECLASS_MASK = 0xC0000000  # `and w9,w8,#0xc0000000` at 0x14514 (FINDINGS.md:6361)
OBJ_PHYSICAL = 0x40000000         # implied by CHECKPOINT_MAP|PHYSICAL = 0x4000000c
OBJ_VIRTUAL = 0x00000000

# --- object types (low 16 bits), each as observed in the repo -----------------
OBJECT_TYPE_NX_SUPERBLOCK = 0x0001   # from full constant 0x10000001 (FINDINGS.md:6428)
OBJECT_TYPE_BTREE = 0x0002           # `cmp #2` btree root (FINDINGS.md:6433)
OBJECT_TYPE_CHECKPOINT_MAP = 0x000C  # from full constant 0x4000000c (FINDINGS.md:6385)
OBJECT_TYPE_OMAP = 0x000B            # `cmp #11` (FINDINGS.md:6439)
OBJECT_TYPE_BLOCKREFTREE = 0x000F    # `cmp #15` (FINDINGS.md:6440)
OBJECT_TYPE_SNAPMETATREE = 0x0010    # `cmp #16` (FINDINGS.md:6438)

# --- full o_type constants exactly as the repo found them in the image --------
# Only TWO full 32-bit o_type constants exist in the whole image (FINDINGS.md:6427).
NX_SUPERBLOCK_OTYPE = 0x10000001     # "NX_SUPERBLOCK virtual" (FINDINGS.md:6428)
CHECKPOINT_MAP_OTYPE = 0x4000000C    # CHECKPOINT_MAP | OBJ_PHYSICAL (FINDINGS.md:6385)


@dataclass
class ObjPhys:
    """The 32-byte obj_phys_t header."""

    o_oid: int
    o_xid: int
    o_type: int
    o_subtype: int = 0
    o_cksum: int = 0  # filled in when the object is checksummed

    def pack(self) -> bytes:
        return struct.pack(
            "<QQQII",
            self.o_cksum,
            self.o_oid,
            self.o_xid,
            self.o_type,
            self.o_subtype,
        )

    @classmethod
    def unpack(cls, data: bytes) -> "ObjPhys":
        cksum, oid, xid, otype, subtype = struct.unpack("<QQQII", data[:HEADER_SIZE])
        return cls(o_oid=oid, o_xid=xid, o_type=otype, o_subtype=subtype, o_cksum=cksum)


def build_object(
    *,
    o_oid: int,
    o_xid: int,
    o_type: int,
    body: bytes,
    o_subtype: int = 0,
    block_size: int = 0x1000,
) -> bytes:
    """Assemble a one-block APFS object and forge a valid Fletcher-64.

    The header is written with o_cksum=0, the body is appended and the block is
    zero-padded to `block_size`, then a valid checksum is computed over bytes
    [8:] and written into o_cksum. The returned bytes are exactly `block_size`
    long and pass fletcher.verify_object().
    """
    if block_size % 4 != 0:
        raise ValueError(f"block_size must be a multiple of 4, got {block_size}")
    header = ObjPhys(o_oid=o_oid, o_xid=o_xid, o_type=o_type, o_subtype=o_subtype)
    raw = header.pack() + body
    if len(raw) > block_size:
        raise ValueError(
            f"header+body ({len(raw)} bytes) exceeds block_size ({block_size})"
        )
    raw = raw.ljust(block_size, b"\x00")
    return apply_checksum(raw)
