"""Minimal nx_superblock (container superblock) builder.

This builds a PARTIAL nx_superblock — only the fields iBoot's validators are
known to read — not a complete Apple container superblock. It is enough to
exercise the nx_superblock validator at iBoot 0x14078 and the volume-open code
at 0x15270, and to demonstrate the forge end-to-end.

Fields and offsets (OBJECT offsets, i.e. from the start of obj_phys_t; the body
begins at 0x20):

    0x20  nx_magic              'NXSB'                     (FINDINGS.md:6329)
    0x24  nx_block_size   u32   must be in [0x1000,0x10000](FINDINGS.md:6252)
    0x28  nx_block_count  u64                              (FINDINGS.md:6330,6344)
    0xB4  nx_max_file_systems u32                          (FINDINGS.md:6261)
    0xB8  nx_fs_oid[]     u64[] volume object ids          (FINDINGS.md:6261)

The 0x14078 validator also requires nx_block_size to equal the block size the
caller already believes in and checks several further ranges; we set the ones
the repo documents and leave the rest zero. Extend this as more of the structure
is audited.
"""
from __future__ import annotations

import struct

from .objects import HEADER_SIZE, NX_SUPERBLOCK_OTYPE, build_object

NX_MAGIC = b"NXSB"  # FINDINGS.md:6329

# Block-size bounds enforced by the 0x14078 validator (FINDINGS.md:6252).
MIN_BLOCK_SIZE = 0x1000
MAX_BLOCK_SIZE = 0x10000

# OBJECT offsets from the repo, translated to BODY offsets (body starts at 0x20).
_OFF_MAGIC = 0x20 - HEADER_SIZE          # 0x00
_OFF_BLOCK_SIZE = 0x24 - HEADER_SIZE     # 0x04
_OFF_BLOCK_COUNT = 0x28 - HEADER_SIZE    # 0x08
_OFF_MAX_FS = 0xB4 - HEADER_SIZE         # 0x94
_OFF_FS_OID = 0xB8 - HEADER_SIZE         # 0x98


def build_nx_superblock(
    *,
    block_size: int = 0x1000,
    block_count: int = 0,
    o_oid: int = 1,
    o_xid: int = 1,
    fs_oids: tuple[int, ...] = (),
) -> bytes:
    """Forge a one-block nx_superblock with a valid Fletcher-64.

    `fs_oids` populates nx_max_file_systems and nx_fs_oid[] so the forged
    container can point the volume-open code (0x15270) at chosen volume object
    ids. Returns exactly `block_size` bytes that pass fletcher.verify_object().
    """
    if not (MIN_BLOCK_SIZE <= block_size <= MAX_BLOCK_SIZE):
        raise ValueError(
            f"block_size {block_size:#x} outside the [0x1000,0x10000] range the "
            "0x14078 validator enforces (FINDINGS.md:6252)"
        )

    body = bytearray(block_size - HEADER_SIZE)
    body[_OFF_MAGIC : _OFF_MAGIC + 4] = NX_MAGIC
    struct.pack_into("<I", body, _OFF_BLOCK_SIZE, block_size)
    struct.pack_into("<Q", body, _OFF_BLOCK_COUNT, block_count)

    if fs_oids:
        struct.pack_into("<I", body, _OFF_MAX_FS, len(fs_oids))
        need = _OFF_FS_OID + 8 * len(fs_oids)
        if need > len(body):
            raise ValueError(
                f"{len(fs_oids)} fs_oids need {need} body bytes but block_size "
                f"only leaves {len(body)}"
            )
        for i, oid in enumerate(fs_oids):
            struct.pack_into("<Q", body, _OFF_FS_OID + 8 * i, oid)

    return build_object(
        o_oid=o_oid,
        o_xid=o_xid,
        o_type=NX_SUPERBLOCK_OTYPE,
        body=bytes(body),
        block_size=block_size,
    )
