"""Clean-room reference validator for a btree node block — the harness oracle.

This encodes the structural invariants a CORRECT APFS btree-node parser must
enforce before it indexes the node's TOC, key and value areas. Two of them were
reverse-engineered this session from the real iBoot-5540 node validator at
0x16b38..0x16d68 (the `btree_node_phys_t` walker FINDINGS.md:6420 could not
locate); the per-entry bounds are the classic shape from FINDINGS.md:6461-6467.

It is the oracle half of the R14 harness loop (FINDINGS.md:6294): the forge
builds malformed nodes with valid Fletcher-64, and this says which structural
invariant each one breaks. A parser that checks only Fletcher-64 (R13.2) would
accept every one of them — that is exactly the gap R14 is probing.

No hardware, no Apple binaries. Pure stdlib. Offsets cited to FINDINGS.md and to
the audited iBoot addresses.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .btree import (
    BTNODE_FIXED_KV_SIZE,
    BTNODE_ROOT,
    BTREE_INFO_SIZE,
    DATA_OFF,
)
from .objects import OBJECT_TYPE_BTREE, OBJ_TYPE_MASK

HEADER_TO_DATA = DATA_OFF  # 0x38: obj_phys + btn header up to btn_data[]


@dataclass(frozen=True)
class Violation:
    """One broken invariant. `code` is stable for tests; `detail` is for humans."""

    code: str
    detail: str


def _u16(b: bytes, off: int) -> int:
    return struct.unpack_from("<H", b, off)[0]


def _u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def validate_btree_node(block: bytes) -> list[Violation]:
    """Return the structural invariants `block` violates ([] = well-formed).

    Integrity (Fletcher-64) is NOT checked here — that is the harness's separate
    axis. This is purely the structural bounds a correct walker must enforce.
    """
    v: list[Violation] = []
    block_size = len(block)
    if block_size < HEADER_TO_DATA:
        return [Violation("block_too_small", f"block {block_size} < header {HEADER_TO_DATA}")]

    o_type = _u32(block, 0x18)
    flags = _u16(block, 0x20)
    nkeys = _u32(block, 0x24)
    ts_off = _u16(block, 0x28)
    ts_len = _u16(block, 0x2A)

    is_root = bool(flags & BTNODE_ROOT)
    is_fixed = bool(flags & BTNODE_FIXED_KV_SIZE)
    entry_size = 4 if is_fixed else 8  # kvoff_t (fixed) vs kvloc_t (variable)

    # Node geometry (iBoot 0x16cf4: usable = block_size - 0x38 - (0x28 if root)).
    footer = BTREE_INFO_SIZE if is_root else 0
    value_area_end = block_size - footer
    toc_base = HEADER_TO_DATA + ts_off
    usable = value_area_end - HEADER_TO_DATA  # space for TOC + keys + values

    if (o_type & OBJ_TYPE_MASK) != OBJECT_TYPE_BTREE:
        v.append(Violation("wrong_o_type",
                           f"o_type&0xffff=0x{o_type & OBJ_TYPE_MASK:x} != OBJECT_TYPE_BTREE"))

    # INV-A (iBoot 0x16d08): btn_table_space must fit in the usable area.
    if ts_off + ts_len > usable:
        v.append(Violation("table_space_overflows_node",
                           f"table_space off+len {ts_off}+{ts_len} > usable {usable}"))

    # INV-B (iBoot 0x16d2c-0x16d3c): btn_nkeys must not exceed TOC capacity.
    capacity = ts_len // entry_size
    if nkeys > capacity:
        v.append(Violation("nkeys_exceeds_toc_capacity",
                           f"nkeys {nkeys} > capacity {capacity} (ts_len {ts_len} / {entry_size})"))

    # Per-entry bounds (FINDINGS.md:6462-6467). Only meaningful for variable
    # (kvloc) nodes, where each TOC entry is {key nloc, val nloc}. Walk the
    # entries that actually fit in the TOC (a correct parser stops at capacity).
    if not is_fixed:
        key_area_base = HEADER_TO_DATA + ts_off + ts_len
        key_area_size = value_area_end - key_area_base
        for i in range(min(nkeys, capacity)):
            pos = toc_base + i * 8
            if pos + 8 > len(block):
                break
            k_off, k_len, val_off, val_len = struct.unpack_from("<HHHH", block, pos)
            # key grows forward from key_area_base
            if k_off + k_len > key_area_size:
                v.append(Violation("key_out_of_bounds",
                                   f"entry {i}: key off+len {k_off}+{k_len} > key area {key_area_size}"))
            # value grows backward from value_area_end; start must stay >= key area
            if val_off > key_area_size:
                v.append(Violation("value_offset_underflow",
                                   f"entry {i}: val off {val_off} > value area {key_area_size} (underflow)"))
            elif val_len > val_off:
                v.append(Violation("value_length_overflow",
                                   f"entry {i}: val len {val_len} > val off {val_off}"))

    return v


def is_well_formed(block: bytes) -> bool:
    return not validate_btree_node(block)
