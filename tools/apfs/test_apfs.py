"""Tests for the APFS forge toolkit (stdlib unittest — no dependency).

Run any of:
    python3 tools/apfs/test_apfs.py
    python3 -m unittest discover -s tools/apfs

Correctness layers, weakest to strongest:
  1. self-consistency      forge -> our own verify accepts (always holds)
  2. hand-computed vectors two Fletcher values worked out by hand (non-circular)
  3. GOLD fixture          a REAL APFS object verifies (byte-exact proof)

Layer 3 is the byte-exact proof. It runs when APFS_GOLD_OBJECT points at a real
APFS image/volume (it scans for NXSB container superblocks and verifies each).
This has been run green against a throwaway `hdiutil` APFS image — our Fletcher
accepts Apple's real stored checksums. Re-run it any time to re-confirm; see the
README for the one-line hdiutil recipe (userspace, no sudo).
"""
from __future__ import annotations

import os
import struct
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # put tools/ on the path to import `apfs`

from apfs import (  # noqa: E402
    BTNODE_LEAF,
    BTNODE_ROOT,
    CHECKPOINT_MAP_OTYPE,
    DATA_OFF,
    HEADER_SIZE,
    KVLOC_SIZE,
    MAPPING_SIZE,
    NX_SUPERBLOCK_OTYPE,
    OBJECT_TYPE_BTREE,
    BTreeNode,
    CheckpointMapping,
    ObjPhys,
    apply_checksum,
    build_btree_node,
    build_checkpoint_map,
    build_nx_superblock,
    build_object,
    capacity,
    fletcher64,
    forge_key_offset_past_node,
    forge_nkeys_exceeds_toc,
    forge_value_length_underflow,
    is_within_capacity,
    verify_object,
)
from apfs.superblock import NX_MAGIC  # noqa: E402
from apfs.cli import main as cli_main  # noqa: E402
from apfs.validate import validate_btree_node, is_well_formed  # noqa: E402
from apfs import harness as harness_mod  # noqa: E402


def _read_btree_header(block):
    flags, level = struct.unpack_from("<HH", block, 0x20)
    nkeys = struct.unpack_from("<I", block, 0x24)[0]
    ts_off, ts_len = struct.unpack_from("<HH", block, 0x28)
    return flags, level, nkeys, ts_off, ts_len


class FletcherTests(unittest.TestCase):
    def test_multiple_of_four_required(self):
        with self.assertRaises(ValueError):
            fletcher64(b"\x00\x00\x00")  # 3 bytes

    def test_hand_vector_all_zero_word(self):
        # body = one zero word -> sum1=sum2=0 -> check1=MOD, check2=MOD.
        # checksum = (0xFFFFFFFF << 32) | 0xFFFFFFFF.
        self.assertEqual(fletcher64(b"\x00\x00\x00\x00"), 0xFFFFFFFFFFFFFFFF)

    def test_hand_vector_single_one_word(self):
        # body = u32 value 1 -> sum1=1,sum2=1
        #   check1 = MOD - (1+1)       = 0xFFFFFFFD
        #   check2 = MOD - (1+check1)%MOD = 1
        # checksum = (1 << 32) | 0xFFFFFFFD.
        self.assertEqual(
            fletcher64(struct.pack("<I", 1)), (1 << 32) | 0xFFFFFFFD
        )

    def test_forge_then_verify_roundtrips(self):
        obj = b"\x00" * 8 + os.urandom(4088)  # 4096-byte object, cksum slot zero
        forged = apply_checksum(obj)
        self.assertTrue(verify_object(forged))

    def test_tamper_is_detected(self):
        forged = apply_checksum(b"\x00" * 8 + b"\xAA" * 4088)
        tampered = bytearray(forged)
        tampered[100] ^= 0xFF  # flip a body byte, leave o_cksum alone
        self.assertFalse(verify_object(bytes(tampered)))

    def test_reforge_defeats_integrity(self):
        # The R13.2 claim: tamper the body, recompute, and it passes again.
        forged = apply_checksum(b"\x00" * 8 + b"\x11" * 4088)
        tampered = bytearray(forged)
        tampered[100] ^= 0xFF
        self.assertFalse(verify_object(bytes(tampered)))
        reforged = apply_checksum(bytes(tampered))
        self.assertTrue(verify_object(reforged))


class ObjectHeaderTests(unittest.TestCase):
    def test_header_is_32_bytes(self):
        self.assertEqual(HEADER_SIZE, 0x20)
        self.assertEqual(
            len(ObjPhys(o_oid=1, o_xid=1, o_type=2).pack()), 0x20
        )

    def test_header_field_offsets(self):
        h = ObjPhys(o_oid=0x1122, o_xid=0x3344, o_type=0x55, o_subtype=0x66, o_cksum=0x77)
        raw = h.pack()
        self.assertEqual(struct.unpack_from("<Q", raw, 0x00)[0], 0x77)   # o_cksum
        self.assertEqual(struct.unpack_from("<Q", raw, 0x08)[0], 0x1122)  # o_oid
        self.assertEqual(struct.unpack_from("<Q", raw, 0x10)[0], 0x3344)  # o_xid
        self.assertEqual(struct.unpack_from("<I", raw, 0x18)[0], 0x55)    # o_type
        self.assertEqual(struct.unpack_from("<I", raw, 0x1C)[0], 0x66)    # o_subtype

    def test_header_roundtrip(self):
        h = ObjPhys(o_oid=9, o_xid=8, o_type=7, o_subtype=6, o_cksum=5)
        self.assertEqual(ObjPhys.unpack(h.pack()), h)

    def test_build_object_shape_and_checksum(self):
        obj = build_object(o_oid=3, o_xid=4, o_type=2, body=b"hello", block_size=0x1000)
        self.assertEqual(len(obj), 0x1000)
        self.assertTrue(verify_object(obj))
        parsed = ObjPhys.unpack(obj)
        self.assertEqual((parsed.o_oid, parsed.o_xid, parsed.o_type), (3, 4, 2))
        self.assertEqual(obj[HEADER_SIZE : HEADER_SIZE + 5], b"hello")
        self.assertEqual(obj[HEADER_SIZE + 5 :], b"\x00" * (0x1000 - HEADER_SIZE - 5))

    def test_build_object_rejects_oversize_body(self):
        with self.assertRaises(ValueError):
            build_object(o_oid=1, o_xid=1, o_type=1, body=b"x" * 0x1000, block_size=0x1000)


class SuperblockTests(unittest.TestCase):
    def test_minimal_superblock(self):
        sb = build_nx_superblock(block_size=0x1000, block_count=0x4000, o_oid=1, o_xid=1)
        self.assertEqual(len(sb), 0x1000)
        self.assertTrue(verify_object(sb))
        self.assertEqual(ObjPhys.unpack(sb).o_type, NX_SUPERBLOCK_OTYPE)
        # nx_magic @ object 0x20, nx_block_size @ 0x24, nx_block_count @ 0x28.
        self.assertEqual(sb[0x20:0x24], NX_MAGIC)
        self.assertEqual(struct.unpack_from("<I", sb, 0x24)[0], 0x1000)
        self.assertEqual(struct.unpack_from("<Q", sb, 0x28)[0], 0x4000)

    def test_fs_oids_populate_array(self):
        sb = build_nx_superblock(block_size=0x1000, fs_oids=(0xAAA, 0xBBB))
        self.assertEqual(struct.unpack_from("<I", sb, 0xB4)[0], 2)      # nx_max_file_systems
        self.assertEqual(struct.unpack_from("<Q", sb, 0xB8)[0], 0xAAA)  # nx_fs_oid[0]
        self.assertEqual(struct.unpack_from("<Q", sb, 0xC0)[0], 0xBBB)  # nx_fs_oid[1]
        self.assertTrue(verify_object(sb))

    def test_block_size_bounds_enforced(self):
        with self.assertRaises(ValueError):
            build_nx_superblock(block_size=0x800)   # below 0x1000
        with self.assertRaises(ValueError):
            build_nx_superblock(block_size=0x20000)  # above 0x10000


class CheckpointMapTests(unittest.TestCase):
    def test_capacity_matches_validator_formula(self):
        # (block_size - 0x28) // 0x28  (FINDINGS.md:6394-6396)
        self.assertEqual(capacity(0x1000), (0x1000 - 0x28) // 0x28)  # == 101
        self.assertEqual(capacity(0x1000), 101)

    def test_within_capacity_bounds(self):
        self.assertFalse(is_within_capacity(0, 0x1000))      # count==0 fails
        self.assertTrue(is_within_capacity(1, 0x1000))
        self.assertTrue(is_within_capacity(101, 0x1000))
        self.assertFalse(is_within_capacity(102, 0x1000))    # over capacity

    def test_mapping_is_40_bytes(self):
        self.assertEqual(MAPPING_SIZE, 0x28)
        self.assertEqual(len(CheckpointMapping(cpm_oid=7, cpm_paddr=9).pack()), 0x28)

    def test_valid_checkpoint_map(self):
        maps = [CheckpointMapping(cpm_oid=1, cpm_paddr=0x10),
                CheckpointMapping(cpm_oid=2, cpm_paddr=0x20)]
        blk = build_checkpoint_map(o_oid=3, o_xid=4, mappings=maps, flags=0xAB)
        self.assertEqual(len(blk), 0x1000)
        self.assertTrue(verify_object(blk))
        self.assertEqual(ObjPhys.unpack(blk).o_type, CHECKPOINT_MAP_OTYPE)
        self.assertEqual(struct.unpack_from("<I", blk, 0x20)[0], 0xAB)   # cpm_flags
        self.assertEqual(struct.unpack_from("<I", blk, 0x24)[0], 2)      # cpm_count
        self.assertEqual(blk[0x28 : 0x28 + MAPPING_SIZE], maps[0].pack())

    def test_force_count_builds_overcapacity_probe(self):
        # A probe the 0x14418 validator is expected to REJECT: cpm_count beyond
        # capacity, while the object itself still carries a valid checksum.
        blk = build_checkpoint_map(mappings=[], force_count=200, block_size=0x1000)
        self.assertEqual(struct.unpack_from("<I", blk, 0x24)[0], 200)
        self.assertFalse(is_within_capacity(200, 0x1000))
        self.assertTrue(verify_object(blk))  # checksum is valid; the COUNT is the lie

    def test_raw_mapping_accepted_and_size_enforced(self):
        blk = build_checkpoint_map(mappings=[b"\x5A" * MAPPING_SIZE])
        self.assertEqual(blk[0x28 : 0x28 + MAPPING_SIZE], b"\x5A" * MAPPING_SIZE)
        with self.assertRaises(ValueError):
            build_checkpoint_map(mappings=[b"\x00" * 10])  # wrong size

    def test_too_many_mappings_rejected(self):
        with self.assertRaises(ValueError):
            build_checkpoint_map(
                mappings=[CheckpointMapping()] * 200, block_size=0x1000
            )


class BTreeNodeTests(unittest.TestCase):
    def test_header_layout_and_checksum(self):
        blk = build_btree_node(
            o_oid=5, o_xid=6, entries=[(b"key0", b"value0"), (b"k1", b"v1")]
        )
        self.assertEqual(len(blk), 0x1000)
        self.assertTrue(verify_object(blk))
        self.assertEqual(ObjPhys.unpack(blk).o_type & 0xFFFF, OBJECT_TYPE_BTREE)
        flags, level, nkeys, ts_off, ts_len = _read_btree_header(blk)
        self.assertEqual(flags, BTNODE_ROOT | BTNODE_LEAF)
        self.assertEqual(level, 0)
        self.assertEqual(nkeys, 2)
        self.assertEqual(ts_off, 0)
        self.assertEqual(ts_len, 2 * KVLOC_SIZE)

    def test_well_formed_places_keys_and_values(self):
        blk = build_btree_node(entries=[(b"KEY", b"VAL")])
        _, _, _, ts_off, ts_len = _read_btree_header(blk)
        # TOC[0] = kvloc{key{off=0,len=3}, val{off=3,len=3}}
        koff, klen, voff, vlen = struct.unpack_from("<HHHH", blk, DATA_OFF + ts_off)
        self.assertEqual((koff, klen, voff, vlen), (0, 3, 3, 3))
        key_base = DATA_OFF + ts_off + ts_len
        self.assertEqual(blk[key_base : key_base + 3], b"KEY")
        # ROOT node: value area ends at block_size - btree_info(0x28); value sits
        # just below that end.
        value_end = 0x1000 - 0x28
        self.assertEqual(blk[value_end - 3 : value_end], b"VAL")

    def test_forge_nkeys_is_oob_by_construction(self):
        node = BTreeNode(entries=[(b"k", b"v")])
        blk = forge_nkeys_exceeds_toc(node, extra=8)
        self.assertTrue(verify_object(blk))  # checksum valid; the COUNT is the lie
        _, _, nkeys, _, ts_len = _read_btree_header(blk)
        # A walker that strides KVLOC_SIZE per claimed key runs past the TOC area.
        self.assertGreater(nkeys * KVLOC_SIZE, ts_len)

    def test_forge_value_underflow_is_oob_by_construction(self):
        node = BTreeNode(entries=[(b"k", b"v")])
        blk = forge_value_length_underflow(node, index=0, bad_len=0xFFFF)
        self.assertTrue(verify_object(blk))
        _, _, _, ts_off, _ = _read_btree_header(blk)
        _, _, voff, vlen = struct.unpack_from("<HHHH", blk, DATA_OFF + ts_off)
        value_end = 0x1000 - 0x28  # ROOT node
        # value start = value_end - voff lands below the header (underflow), and
        # the length cannot fit the node either way.
        self.assertLess(value_end - voff, DATA_OFF)
        self.assertGreater(vlen, 0x1000)

    def test_forge_key_oob_is_oob_by_construction(self):
        node = BTreeNode(entries=[(b"k", b"v")])
        blk = forge_key_offset_past_node(node, index=0, bad_off=0xFFFF)
        self.assertTrue(verify_object(blk))
        _, _, _, ts_off, ts_len = _read_btree_header(blk)
        koff, klen, _, _ = struct.unpack_from("<HHHH", blk, DATA_OFF + ts_off)
        key_base = DATA_OFF + ts_off + ts_len
        self.assertGreater(key_base + koff + klen, 0x1000)

    def test_all_forgeries_keep_valid_checksum(self):
        # The R13.2 point: every malformation still passes integrity.
        node = BTreeNode(entries=[(b"aa", b"bb"), (b"cc", b"dd")])
        for blk in (
            forge_nkeys_exceeds_toc(node),
            forge_value_length_underflow(node),
            forge_key_offset_past_node(node),
        ):
            self.assertTrue(verify_object(blk))


class CLITests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _emit(self, *argv) -> bytes:
        out = self.dir / "block.bin"
        rc = cli_main([*argv, "-o", str(out)])
        self.assertEqual(rc, 0)
        return out.read_bytes()

    def test_superblock_command(self):
        blk = self._emit("superblock", "--block-count", "0x4000", "--fs-oid", "0x402")
        self.assertEqual(len(blk), 0x1000)
        self.assertTrue(verify_object(blk))
        self.assertEqual(blk[0x20:0x24], NX_MAGIC)

    def test_checkpoint_map_command(self):
        blk = self._emit("checkpoint-map", "--mappings", "2")
        self.assertTrue(verify_object(blk))
        self.assertEqual(struct.unpack_from("<I", blk, 0x24)[0], 2)

    def test_btree_malform_command(self):
        for mode in ("none", "nkeys", "value-underflow", "key-oob"):
            blk = self._emit("btree", "--entry", "k=v", "--malform", mode)
            self.assertTrue(verify_object(blk), f"malform {mode} broke the checksum")

    def test_inspect_command(self):
        import contextlib
        import io

        target = self.dir / "node.bin"
        cli_main(["btree", "--entry", "k=v", "-o", str(target)])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["inspect", str(target)])
        self.assertEqual(rc, 0)
        self.assertIn("BTREE", buf.getvalue())
        self.assertIn("verify=True", buf.getvalue())


class GoldFixtureTest(unittest.TestCase):
    """The byte-exact proof: a REAL APFS object must verify under our Fletcher.

    Provide a real object block via the APFS_GOLD_OBJECT environment variable,
    e.g.:
        sudo dd if=/dev/diskXsY bs=4096 count=1 of=/tmp/nxsb.bin   # a superblock
        APFS_GOLD_OBJECT=/tmp/nxsb.bin python3 -m unittest discover -s tools/apfs
    (Reading a raw APFS device needs privileges and is the user's call — this
    toolkit never does it automatically.)
    """

    def test_real_object_verifies(self):
        fixture = os.environ.get("APFS_GOLD_OBJECT")
        if not fixture:
            self.skipTest("set APFS_GOLD_OBJECT to a real APFS image/object to run")
        data = Path(fixture).read_bytes()
        self.assertGreaterEqual(len(data), 0x1000, "expected at least one block")

        # Scan every 4096-aligned block for a container superblock (nx_magic
        # 'NXSB' at object offset 0x20) and verify each candidate. A real image
        # (hdiutil .dmg or a raw volume) has GPT/other data at block 0, so we
        # cannot assume the superblock is first.
        block_size = 0x1000
        checked = 0
        for off in range(0, len(data) - block_size + 1, block_size):
            block = data[off : off + block_size]
            if block[0x20:0x24] != NX_MAGIC:
                continue
            checked += 1
            self.assertTrue(
                verify_object(block),
                f"real NXSB object at offset {off:#x} failed our Fletcher-64 — "
                "the algorithm or coverage boundary is wrong; see fletcher.py",
            )
        self.assertGreater(
            checked, 0, "no NXSB container superblock found in the fixture"
        )


class ReferenceValidatorTests(unittest.TestCase):
    """The clean-room oracle: well-formed nodes pass, each forge malformation
    trips the specific invariant reverse-engineered from iBoot 0x16b38."""

    def _good(self):
        return BTreeNode(entries=[(b"key01", b"val01"), (b"key02", b"val02")])

    def test_well_formed_node_has_no_violations(self):
        self.assertTrue(is_well_formed(self._good().build()))

    def test_nkeys_exceeds_toc_capacity(self):
        block = forge_nkeys_exceeds_toc(self._good())
        codes = {v.code for v in validate_btree_node(block)}
        self.assertIn("nkeys_exceeds_toc_capacity", codes)

    def test_key_offset_past_node(self):
        block = forge_key_offset_past_node(self._good())
        codes = {v.code for v in validate_btree_node(block)}
        self.assertIn("key_out_of_bounds", codes)

    def test_value_length_underflow(self):
        block = forge_value_length_underflow(self._good())
        codes = {v.code for v in validate_btree_node(block)}
        self.assertIn("value_offset_underflow", codes)

    def test_table_space_overflow_is_caught(self):
        # claim a TOC larger than the node can hold (no real entries, just the lie)
        block = BTreeNode(entries=[], table_space_len_override=0x4000).build()
        codes = {v.code for v in validate_btree_node(block)}
        self.assertIn("table_space_overflows_node", codes)


class HarnessTests(unittest.TestCase):
    def test_every_malformation_is_fletcher_valid_but_structurally_rejected(self):
        cases = {c.name: c for c in harness_mod.run()}
        # the control passes both axes
        self.assertTrue(cases["well_formed"].fletcher_valid)
        self.assertEqual(cases["well_formed"].violations, ())
        # the three malformations: integrity passes, structure rejects
        for name in ("nkeys_exceeds_toc", "value_length_underflow",
                     "key_offset_past_node"):
            self.assertTrue(cases[name].fletcher_valid, f"{name} should pass Fletcher")
            self.assertTrue(cases[name].violations, f"{name} should be rejected")
            self.assertTrue(cases[name].integrity_only_gap)

    def test_report_renders(self):
        text = harness_mod.format_report(harness_mod.run())
        self.assertIn("pass Fletcher-64 but fail structural validation", text)

    def test_cli_harness_runs(self):
        self.assertEqual(cli_main(["harness"]), 0)


if __name__ == "__main__":
    unittest.main()
