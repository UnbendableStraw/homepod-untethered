"""checkpoint_map_phys_t builder.

This is the structure validated at iBoot 0x14418, which R14.2 proved is bounds-
checked CORRECTLY (FINDINGS.md:6381-6401). We build it here for two reasons:
  1. it is a worked, forgeable example end to end (valid checksum + layout);
  2. it is the reference implementation of the "capacity-check idiom" the btree
     audit (increment 3 / R14.3) hunts for by its ABSENCE.

Layout (OBJECT offsets; body begins at 0x20 = HEADER_SIZE), all verified:

    0x00  obj_phys_t                                        (o_type == 0x4000000c)
    0x20  cpm_flags   u32                                   (FINDINGS.md:6386)
    0x24  cpm_count   u32   number of cpm_map[] entries     (FINDINGS.md:6387)
    0x28  cpm_map[]   checkpoint_mapping_t, 40 bytes each   (FINDINGS.md:6388)

The validator's capacity check (FINDINGS.md:6392-6400):

    if cpm_count == 0:            fail                      (0x144c8)
    capacity = (block_size - 0x28) / 0x28                   (0x144cc-0x144d8)
    if capacity <  cpm_count:    fail                       (0x144dc-0x144e0)

0x28 = 0x20 (header) + 4 (cpm_flags) + 4 (cpm_count); i.e. the fixed prefix
before cpm_map[]. Each mapping is exactly 40 bytes, so capacity is the number of
whole mappings that fit after that prefix.

NOTE on the mapping INTERNALS: the repo pins down the 40-byte STRIDE from the
disassembly, but not the individual field layout within a mapping. We therefore
model a mapping as an opaque 40-byte value by default. `CheckpointMapping`
offers the conventional Apple field names for convenience, but those inner
offsets are NOT independently verified against this iBoot build — only the
40-byte size is.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .objects import CHECKPOINT_MAP_OTYPE, HEADER_SIZE, build_object

MAPPING_SIZE = 0x28  # 40 bytes, verified stride (FINDINGS.md:6388)

# Fixed prefix before cpm_map[]: obj_phys_t (0x20) + cpm_flags (4) + cpm_count (4).
PREFIX_SIZE = 0x28  # matches the validator's `sub x9, x9, #0x28` (FINDINGS.md:6394)

_OFF_FLAGS = 0x20 - HEADER_SIZE   # body 0x00
_OFF_COUNT = 0x24 - HEADER_SIZE   # body 0x04
_OFF_MAP = 0x28 - HEADER_SIZE     # body 0x08


def capacity(block_size: int) -> int:
    """Max whole mappings that fit — exactly the validator's computation."""
    return (block_size - PREFIX_SIZE) // MAPPING_SIZE


def is_within_capacity(count: int, block_size: int) -> bool:
    """Mirror of the 0x14418 validator's accept condition (count in [1,cap])."""
    return 1 <= count <= capacity(block_size)


@dataclass
class CheckpointMapping:
    """A 40-byte checkpoint_mapping_t.

    Only the 40-byte SIZE is verified against this iBoot build. The field names
    below follow the Apple APFS reference and are a convenience for populating
    plausible entries; do not treat their offsets as confirmed for 5540.x.
    """

    cpm_type: int = 0
    cpm_subtype: int = 0
    cpm_size: int = 0
    cpm_fs_oid: int = 0
    cpm_oid: int = 0
    cpm_paddr: int = 0

    def pack(self) -> bytes:
        raw = struct.pack(
            "<IIQQQ",  # type, subtype, size, fs_oid, oid  = 4+4+8+8+8 = 32
            self.cpm_type,
            self.cpm_subtype,
            self.cpm_size,
            self.cpm_fs_oid,
            self.cpm_oid,
        ) + struct.pack("<Q", self.cpm_paddr)  # + paddr = 40 bytes total
        assert len(raw) == MAPPING_SIZE
        return raw


def _as_bytes(mapping: object) -> bytes:
    if isinstance(mapping, CheckpointMapping):
        return mapping.pack()
    if isinstance(mapping, (bytes, bytearray)):
        if len(mapping) != MAPPING_SIZE:
            raise ValueError(
                f"each mapping must be {MAPPING_SIZE} bytes, got {len(mapping)}"
            )
        return bytes(mapping)
    raise TypeError(f"mapping must be CheckpointMapping or 40 bytes, got {type(mapping)}")


def build_checkpoint_map(
    *,
    o_oid: int = 1,
    o_xid: int = 1,
    mappings: "list | tuple" = (),
    flags: int = 0,
    block_size: int = 0x1000,
    force_count: "int | None" = None,
) -> bytes:
    """Forge a checkpoint_map_phys_t with a valid Fletcher-64.

    `mappings` is a list of CheckpointMapping or raw 40-byte entries.
    `force_count` overrides the cpm_count FIELD independently of how many entries
    are actually present — use it to build an over-count probe (cpm_count >
    capacity) that the 0x14418 validator is expected to REJECT. With force_count
    left None, cpm_count = len(mappings) and the result is a well-formed map.
    """
    entries = b"".join(_as_bytes(m) for m in mappings)
    if PREFIX_SIZE + len(entries) > block_size:
        raise ValueError(
            f"{len(mappings)} mappings need {PREFIX_SIZE + len(entries)} bytes but "
            f"block_size is only {block_size}"
        )
    count = len(mappings) if force_count is None else force_count

    body = bytearray(block_size - HEADER_SIZE)
    struct.pack_into("<I", body, _OFF_FLAGS, flags)
    struct.pack_into("<I", body, _OFF_COUNT, count)
    body[_OFF_MAP : _OFF_MAP + len(entries)] = entries

    return build_object(
        o_oid=o_oid,
        o_xid=o_xid,
        o_type=CHECKPOINT_MAP_OTYPE,
        body=bytes(body),
        block_size=block_size,
    )
