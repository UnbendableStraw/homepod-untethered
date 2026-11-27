"""Tests for the R14.3 iBoot APFS audit aid (stdlib unittest — no dependency).

    PYTHONPATH=tools python3 -m unittest discover -s tools/ibootscan

Layers:
  1. asm: parse every listing dialect the researcher might feed in, incl. the
     exact disassembly notation used in FINDINGS.md.
  (idiom / taint / scan layers are added in later increments.)
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # tools/ on path to import `ibootscan`

from ibootscan import asm  # noqa: E402
from ibootscan import idiom  # noqa: E402
from ibootscan import taint  # noqa: E402
from ibootscan import scan as scanmod  # noqa: E402
from ibootscan.cli import main as cli_main  # noqa: E402

# A synthetic btree-node toc walk in the shape FINDINGS.md:6462-6467 describes:
# btn_nkeys and a toc offset come off the node and index the key/value areas.
# GUARDED form includes the R14.2 capacity idiom before the indexed loads.
BTREE_GUARDED = """
0x100  ldrh w8, [x19, #0x24]        ; btn_nkeys off the node (on-disk)
0x104  ldr w9, [x19, #0x08]         ; node buffer size
0x108  sub x9, x9, #0x38            ; minus node header
0x10c  udiv x9, x9, #0x4            ; / toc entry size
0x110  cmp x9, x8                   ; capacity vs nkeys
0x114  b.hs #0x120                  ; guard: proceed only if capacity >= nkeys
0x118  add w25, w25, #1             ; (failure path)
0x120  ldrh w10, [x19, x8, lsl #1]  ; toc offset indexed by nkeys
0x124  ldr w11, [x19, x10]          ; value load indexed by on-disk offset
"""
# MUTANT: identical but with the capacity idiom (0x104-0x114) deleted.
BTREE_UNGUARDED = """
0x100  ldrh w8, [x19, #0x24]        ; btn_nkeys off the node (on-disk)
0x120  ldrh w10, [x19, x8, lsl #1]  ; toc offset indexed by nkeys, UNCHECKED
0x124  ldr w11, [x19, x10]          ; value load indexed by on-disk offset
"""


class ParseLineTests(unittest.TestCase):
    def test_findings_notation(self):
        # The exact idiom lines quoted in FINDINGS.md:6392-6400.
        i = asm.parse_line("0x144d0  sub x9, x9, #0x28")
        self.assertIsNotNone(i)
        self.assertEqual(i.addr, 0x144D0)
        self.assertEqual(i.mnemonic, "sub")
        self.assertEqual(i.ops, ("x9", "x9", "#0x28"))

    def test_conditional_branch_cc(self):
        i = asm.parse_line("0x144e0  b.hs #0x144e8")
        self.assertEqual(i.mnemonic, "b.hs")
        self.assertEqual(i.cc, "hs")
        self.assertEqual(i.ops, ("#0x144e8",))

    def test_llvm_objdump_with_raw_bytes(self):
        i = asm.parse_line("   14ae8: a9 0c 53 f3  \tstp\tx19, x20, [sp, #-0x20]!")
        self.assertEqual(i.addr, 0x14AE8)
        self.assertEqual(i.mnemonic, "stp")
        # the memory operand stays a single token despite its inner comma
        self.assertEqual(i.ops, ("x19", "x20", "[sp, #-0x20]!"))

    def test_llvm_objdump_no_raw_bytes(self):
        i = asm.parse_line("   14ae8:      \tstp\tx19, x20, [sp, #-0x20]!")
        self.assertEqual(i.addr, 0x14AE8)
        self.assertEqual(i.mnemonic, "stp")

    def test_otool_tv(self):
        i = asm.parse_line("0000000000014dd0\tldr\tw8, [x19, #0x24]")
        self.assertEqual(i.addr, 0x14DD0)
        self.assertEqual(i.mnemonic, "ldr")
        self.assertEqual(i.ops, ("w8", "[x19, #0x24]"))

    def test_gnu_objdump_word(self):
        i = asm.parse_line("   14dc:\ta90c53f3 \tstp\tx19, x20, [sp, #-32]")
        self.assertEqual(i.addr, 0x14DC)
        self.assertEqual(i.mnemonic, "stp")

    def test_radare2(self):
        i = asm.parse_line("0x00014ae8      a90c53f3       stp x19, x20, [sp, -0x20]!")
        self.assertEqual(i.addr, 0x14AE8)
        self.assertEqual(i.mnemonic, "stp")

    def test_mnemonic_that_is_valid_hex_not_eaten_as_raw(self):
        # "adc" is a real mnemonic AND valid hex; must not be consumed as bytes.
        i = asm.parse_line("0x1000  adc x0, x1, x2")
        self.assertEqual(i.mnemonic, "adc")
        self.assertEqual(i.ops, ("x0", "x1", "x2"))

    def test_add_mnemonic_after_raw_bytes_not_mis_split(self):
        # raw prefix contains hex that could spuriously match the mnemonic "add".
        i = asm.parse_line("14ae8: a9 0c ad d0  \tadd\tx8, x9, #0x38")
        self.assertEqual(i.mnemonic, "add")
        self.assertEqual(i.ops, ("x8", "x9", "#0x38"))

    def test_ldrh_memory_operand(self):
        i = asm.parse_line("0x15b74  ldrh w8, [x19, w9, uxtw #1]")
        self.assertEqual(i.mnemonic, "ldrh")
        self.assertEqual(i.ops, ("w8", "[x19, w9, uxtw #1]"))

    def test_comment_stripped(self):
        i = asm.parse_line("0x150a4  and w8, w8, #0xffff   ; mask o_type low 16")
        self.assertEqual(i.mnemonic, "and")
        self.assertEqual(i.ops, ("w8", "w8", "#0xffff"))
        self.assertNotIn(";", i.raw)

    def test_radare2_graph_art_stripped(self):
        # r2 prefixes branch-adorned lines with box-drawing/arrow graph art.
        i = asm.parse_line("  ┌─< 0x000144c8      e8000034       cbz w8, 0x144e4")
        self.assertIsNotNone(i)
        self.assertEqual(i.addr, 0x144C8)
        self.assertEqual(i.mnemonic, "cbz")
        i2 = asm.parse_line("       │└─> 0x000144e4      39070011       add w25, w25, 1")
        self.assertEqual((i2.addr, i2.mnemonic), (0x144E4, "add"))

    def test_radare2_bare_immediate(self):
        # r2 writes immediates without a leading '#'.
        i = asm.parse_line("0x000144d0      29a100d1       sub x9, x9, 0x28")
        self.assertEqual((i.mnemonic, i.ops), ("sub", ("x9", "x9", "0x28")))
        self.assertEqual(idiom.imm_val("0x28"), 0x28)   # bare immediate parses
        self.assertEqual(idiom.imm_val("#0x28"), 0x28)  # '#'-prefixed still parses

    def test_blank_and_label_lines_skipped(self):
        self.assertIsNone(asm.parse_line(""))
        self.assertIsNone(asm.parse_line("   "))
        self.assertIsNone(asm.parse_line("_apfs_btree_lookup:"))
        self.assertIsNone(asm.parse_line("Disassembly of section __TEXT:"))


# The checkpoint-map capacity-check idiom, verbatim from FINDINGS.md:6392-6400.
# Reused by later idiom/taint tests; parsed here to prove the parser handles the
# exact text the audit is grounded in.
CHECKPOINT_IDIOM = """
0x144c8  cbz w8, #0x144e4
0x144cc  ldr w9, [x20, #0x48]
0x144d0  sub x9, x9, #0x28
0x144d8  udiv x9, x9, #0x28
0x144dc  cmp x9, x8
0x144e0  b.hs #0x144e8
0x144e4  add w25, w25, #1
"""


class ParseListingTests(unittest.TestCase):
    def test_parses_checkpoint_idiom_block(self):
        insns = asm.parse_listing(CHECKPOINT_IDIOM)
        self.assertEqual(len(insns), 7)
        self.assertEqual(insns[0].addr, 0x144C8)
        self.assertEqual([i.mnemonic for i in insns],
                         ["cbz", "ldr", "sub", "udiv", "cmp", "b.hs", "add"])

    def test_in_range_is_half_open(self):
        insns = asm.parse_listing(CHECKPOINT_IDIOM)
        got = asm.in_range(insns, 0x144D0, 0x144E0)  # sub, udiv, cmp (b.hs excluded)
        self.assertEqual([i.mnemonic for i in got], ["sub", "udiv", "cmp"])


class IdiomGoldTests(unittest.TestCase):
    """GOLD: the one hand-verified site. FINDINGS.md:6391-6401 proves the
    checkpoint-map count at 0x144fc is SAFE because of the capacity idiom at
    0x144c8-0x144e0. The detector MUST find exactly that guard."""

    def test_detects_the_checkpoint_map_guard(self):
        insns = asm.parse_listing(CHECKPOINT_IDIOM)
        guards = idiom.find_capacity_guards(insns)
        self.assertEqual(len(guards), 1, "should find exactly the R14.2 guard")
        g = guards[0]
        self.assertEqual(g.udiv_addr, 0x144D8)
        self.assertEqual(g.cmp_addr, 0x144DC)
        self.assertEqual(g.branch_addr, 0x144E0)
        self.assertEqual(g.element_size, 0x28)   # checkpoint_mapping_t stride
        self.assertEqual(g.header, 0x28)         # flags+count header
        self.assertEqual(g.count_reg, 8)         # w8 = on-disk cpm_count
        self.assertEqual(g.cc, "hs")
        self.assertFalse(g.signed)

    def test_detects_guard_in_real_radare2_output(self):
        # The actual r2 -n disassembly of iBoot-5540's checkpoint-map guard
        # (0x144c8-0x144e0): graph art, bare immediates, register divisor. This
        # is the exact text read from a real decrypted iBoot; the detector must
        # recover the same guard the hand audit found (FINDINGS.md:6392-6401).
        real = (
            "        ┌─< 0x000144c8      e8000034       cbz w8, 0x144e4\n"
            "        │   0x000144cc      894a40b9       ldr w9, [x20, 0x48]\n"
            "        │   0x000144d0      29a100d1       sub x9, x9, 0x28\n"
            "        │   0x000144d4      0a058052       mov w10, 0x28\n"
            "        │   0x000144d8      2909ca9a       udiv x9, x9, x10\n"
            "        │   0x000144dc      3f0108eb       cmp x9, x8\n"
            "       ┌──< 0x000144e0      42000054       b.hs 0x144e8\n"
            "       │└─> 0x000144e4      39070011       add w25, w25, 1\n"
        )
        guards = idiom.find_capacity_guards(asm.parse_listing(real))
        self.assertEqual(len(guards), 1)
        g = guards[0]
        self.assertEqual((g.branch_addr, g.udiv_addr), (0x144E0, 0x144D8))
        self.assertEqual((g.element_size, g.header, g.count_reg, g.cc),
                         (0x28, 0x28, 8, "hs"))

    def test_mutant_without_idiom_is_unguarded(self):
        # Remove the sub/udiv/cmp/b.hs: the count (w8) is now used unchecked.
        mutant = """
        0x144c8  cbz w8, #0x144e4
        0x144cc  ldr w9, [x20, #0x48]
        0x144e4  add w25, w25, #1
        """
        guards = idiom.find_capacity_guards(asm.parse_listing(mutant))
        self.assertEqual(guards, [], "no idiom -> no guard (the bug signature)")

    def test_real_arm64_udiv_via_register_divisor(self):
        # Real ARM64 has no immediate udiv; element size arrives via a register.
        block = """
        0x2000  ldr w9, [x20, #0x48]
        0x2004  sub x9, x9, #0x28
        0x2008  mov w10, #0x28
        0x200c  udiv x9, x9, w10
        0x2010  cmp x9, x8
        0x2014  b.hs #0x2100
        """
        guards = idiom.find_capacity_guards(asm.parse_listing(block))
        self.assertEqual(len(guards), 1)
        self.assertEqual(guards[0].element_size, 0x28)
        self.assertEqual(guards[0].count_reg, 8)

    def test_intervening_flag_setter_breaks_the_guard(self):
        # A second compare between the capacity cmp and the branch means the
        # branch no longer tests capacity-vs-count: not a valid guard.
        block = """
        0x3000  sub x9, x9, #0x28
        0x3004  udiv x9, x9, #0x28
        0x3008  cmp x9, x8
        0x300c  cmp w0, #0
        0x3010  b.hs #0x3100
        """
        self.assertEqual(idiom.find_capacity_guards(asm.parse_listing(block)), [])

    def test_cmp_not_involving_capacity_is_ignored(self):
        block = """
        0x4000  sub x9, x9, #0x28
        0x4004  udiv x9, x9, #0x28
        0x4008  cmp w0, w1
        0x400c  b.hs #0x4100
        """
        self.assertEqual(idiom.find_capacity_guards(asm.parse_listing(block)), [])

    def test_signed_guard_is_flagged_signed(self):
        block = """
        0x5000  sub x9, x9, #0x28
        0x5004  udiv x9, x9, #0x28
        0x5008  cmp x9, x8
        0x500c  b.lt #0x5100
        """
        guards = idiom.find_capacity_guards(asm.parse_listing(block))
        self.assertEqual(len(guards), 1)
        self.assertTrue(guards[0].signed)


class RegHelperTests(unittest.TestCase):
    def test_reg_num_aliases_w_and_x(self):
        self.assertEqual(idiom.reg_num("w9"), idiom.reg_num("x9"))
        self.assertEqual(idiom.reg_num("xzr"), "zr")
        self.assertEqual(idiom.reg_num("sp"), "sp")
        self.assertIsNone(idiom.reg_num("#0x28"))

    def test_imm_val_hex_and_dec(self):
        self.assertEqual(idiom.imm_val("#0x28"), 0x28)
        self.assertEqual(idiom.imm_val("#40"), 40)
        self.assertEqual(idiom.imm_val("#-0x10"), -0x10)
        self.assertIsNone(idiom.imm_val("x9"))


class TaintTests(unittest.TestCase):
    def test_load_then_indexed_load_is_a_site(self):
        sites = taint.find_index_sites(asm.parse_listing(BTREE_UNGUARDED))
        kinds = {(hex(s.addr), s.kind) for s in sites}
        # 0x120 indexes by tainted w8; 0x124 indexes by tainted w10.
        self.assertIn(("0x120", "load-index"), kinds)
        self.assertIn(("0x124", "load-index"), kinds)

    def test_untainted_index_is_not_a_site(self):
        # x9 here comes from a mov-immediate (clean), so no site.
        block = """
        0x10  mov x9, #4
        0x14  ldr w0, [x19, x9]
        """
        self.assertEqual(taint.find_index_sites(asm.parse_listing(block)), [])

    def test_madd_stride_with_tainted_factor(self):
        block = """
        0x10  ldr w24, [x19, #0x24]     ; on-disk count -> tainted
        0x14  madd x26, x24, x27, x19   ; stride multiply-add by tainted factor
        """
        sites = taint.find_index_sites(asm.parse_listing(block))
        self.assertEqual([s.kind for s in sites], ["madd-stride"])

    def test_add_scaled_index(self):
        block = """
        0x10  ldrh w8, [x19, #0x24]
        0x14  add x0, x19, x8, lsl #1
        """
        sites = taint.find_index_sites(asm.parse_listing(block))
        self.assertEqual([s.kind for s in sites], ["add-scaled"])


class ScanGoldTests(unittest.TestCase):
    def test_guarded_btree_sites_are_graded_guarded(self):
        report = scanmod.scan(asm.parse_listing(BTREE_GUARDED))
        self.assertEqual(len(report.guards), 1)
        self.assertTrue(report.verdicts, "should find index sites")
        self.assertEqual(report.unguarded, [],
                         "with the idiom present, no site is UNGUARDED")
        self.assertTrue(all(v.verdict == "GUARDED?" for v in report.verdicts))

    def test_unguarded_btree_sites_are_flagged(self):
        report = scanmod.scan(asm.parse_listing(BTREE_UNGUARDED))
        self.assertEqual(len(report.guards), 0)
        self.assertEqual(len(report.unguarded), 2,
                         "both indexed loads lack a preceding capacity guard")
        for v in report.unguarded:
            self.assertEqual(v.verdict, "UNGUARDED")

    def test_range_filter_restricts_scan(self):
        insns = asm.parse_listing(BTREE_GUARDED)
        # Restrict to the indexed loads, excluding the guard AND the load that
        # seeds w8. Taint is window-local, so w8 (loaded at 0x100, out of range)
        # is unknown here; only 0x124 — whose index w10 is loaded in-window at
        # 0x120 — is flagged. This under-reports on sub-ranges by design; the
        # intended use is scanning a whole function (README notes this).
        report = scanmod.scan(insns, 0x120, 0x200)
        self.assertEqual(len(report.guards), 0)
        self.assertEqual(len(report.unguarded), 1)
        self.assertEqual(report.unguarded[0].site.addr, 0x124)

    def test_format_report_mentions_verdicts(self):
        report = scanmod.scan(asm.parse_listing(BTREE_UNGUARDED))
        text = scanmod.format_report(report)
        self.assertIn("UNGUARDED", text)
        self.assertIn("index sites", text)


class CLITests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_scan_exit_code_2_when_unguarded(self):
        lst = self.dir / "u.lst"
        lst.write_text(BTREE_UNGUARDED)
        self.assertEqual(cli_main(["scan", str(lst)]), 2)

    def test_scan_exit_code_0_when_all_guarded(self):
        lst = self.dir / "g.lst"
        lst.write_text(BTREE_GUARDED)
        self.assertEqual(cli_main(["scan", str(lst)]), 0)

    def test_guards_subcommand(self):
        import contextlib, io
        lst = self.dir / "c.lst"
        lst.write_text(CHECKPOINT_IDIOM)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["guards", str(lst)])
        self.assertEqual(rc, 0)
        self.assertIn("capacity guards: 1", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
