"""Offline APFS structure forge for the R14 pre-authentication audit.

This package builds attacker-controlled APFS structures with valid, forged
Fletcher-64 checksums — the offline half of the R14 harness loop
(FINDINGS.md:6294). It touches no hardware, no HomePod, and no Apple binaries;
every structure offset it uses is cited to a verified line in FINDINGS.md.

Public API:
    fletcher64, compute_object_checksum, apply_checksum, verify_object
    ObjPhys, build_object, and the OBJECT_TYPE_* / *_OTYPE constants
    build_nx_superblock
"""
from __future__ import annotations

from .fletcher import (
    apply_checksum,
    compute_object_checksum,
    fletcher64,
    verify_object,
)
from .objects import (
    CHECKPOINT_MAP_OTYPE,
    HEADER_SIZE,
    NX_SUPERBLOCK_OTYPE,
    OBJ_PHYSICAL,
    OBJ_STORAGECLASS_MASK,
    OBJ_TYPE_MASK,
    OBJ_VIRTUAL,
    OBJECT_TYPE_BLOCKREFTREE,
    OBJECT_TYPE_BTREE,
    OBJECT_TYPE_CHECKPOINT_MAP,
    OBJECT_TYPE_NX_SUPERBLOCK,
    OBJECT_TYPE_OMAP,
    OBJECT_TYPE_SNAPMETATREE,
    ObjPhys,
    build_object,
)
from .checkpoint_map import (
    CheckpointMapping,
    MAPPING_SIZE,
    build_checkpoint_map,
    capacity,
    is_within_capacity,
)
from .btree import (
    BTNODE_FIXED_KV_SIZE,
    BTNODE_LEAF,
    BTNODE_ROOT,
    BTreeNode,
    DATA_OFF,
    KVLOC_SIZE,
    Kvloc,
    Nloc,
    build_btree_node,
    forge_key_offset_past_node,
    forge_nkeys_exceeds_toc,
    forge_value_length_underflow,
)
from .superblock import build_nx_superblock

__all__ = [
    "fletcher64",
    "compute_object_checksum",
    "apply_checksum",
    "verify_object",
    "ObjPhys",
    "build_object",
    "HEADER_SIZE",
    "OBJ_TYPE_MASK",
    "OBJ_STORAGECLASS_MASK",
    "OBJ_PHYSICAL",
    "OBJ_VIRTUAL",
    "OBJECT_TYPE_NX_SUPERBLOCK",
    "OBJECT_TYPE_BTREE",
    "OBJECT_TYPE_CHECKPOINT_MAP",
    "OBJECT_TYPE_OMAP",
    "OBJECT_TYPE_BLOCKREFTREE",
    "OBJECT_TYPE_SNAPMETATREE",
    "NX_SUPERBLOCK_OTYPE",
    "CHECKPOINT_MAP_OTYPE",
    "build_nx_superblock",
    "build_checkpoint_map",
    "CheckpointMapping",
    "MAPPING_SIZE",
    "capacity",
    "is_within_capacity",
    "BTreeNode",
    "build_btree_node",
    "Nloc",
    "Kvloc",
    "KVLOC_SIZE",
    "DATA_OFF",
    "BTNODE_ROOT",
    "BTNODE_LEAF",
    "BTNODE_FIXED_KV_SIZE",
    "forge_nkeys_exceeds_toc",
    "forge_value_length_underflow",
    "forge_key_offset_past_node",
]
