"""Minimal intra-function register taint to locate on-disk-derived index sites.

Threat model (FINDINGS.md:6457-6467): the audited function parses a single APFS
block read off disk, so EVERY value it loads from memory is attacker-controlled.
We seed taint on every load, propagate it through data-processing instructions,
and report the instructions that use a tainted value as a memory index or an
address scale — e.g. the `madd x26, x24, #0x28, x19` stride (FINDINGS.md:6388)
or `ldr w8, [x26, xIdx]`. Those are the accesses that a missing capacity check
turns into an out-of-bounds read.

This is deliberately a heuristic. It does not model calls precisely, aliasing,
or memory. It surfaces candidate index sites for a human to confirm; it is not a
proof of reachability. Everything here is pure text reasoning over `Insn`s.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .asm import Insn
from .idiom import reg_num

_LOADS = frozenset({
    "ldr", "ldrb", "ldrh", "ldrsb", "ldrsh", "ldrsw",
    "ldur", "ldurb", "ldurh", "ldursw", "ldp", "ldpsw", "ldtr", "ldxr", "ldar",
})
# Data-processing ops that propagate taint from any source operand to ops[0].
_PROP = frozenset({
    "add", "sub", "adds", "subs", "and", "orr", "eor", "bic", "orn",
    "lsl", "lsr", "asr", "ror", "mul", "madd", "msub", "mneg", "umaddl",
    "umull", "smull", "smaddl", "mov", "mvn", "neg",
    "ubfx", "sbfx", "ubfm", "sbfm", "bfi", "bfxil",
    "sxtb", "sxth", "sxtw", "uxtb", "uxth", "uxtw", "lsl.", "add.",
})
# Mnemonics with no GPR destination (never a taint sink via ops[0]).
_NO_DEST = frozenset({
    "cmp", "cmn", "tst", "ccmp", "ccmn",
    "str", "strb", "strh", "stur", "sturb", "sturh", "stp", "stxr", "stlr",
    "cbz", "cbnz", "tbz", "tbnz", "b", "bl", "br", "blr", "ret", "nop",
})

_BRACKET_SEP = re.compile(r"[,\s!]+")


@dataclass(frozen=True)
class IndexSite:
    """A memory access or address computation that uses a tainted value as an
    index/scale — i.e. on-disk data steering a pointer."""

    addr: int
    insn: Insn
    index_regs: tuple  # the tainted register keys used as index/scale
    kind: str          # "load-index" | "store-index" | "madd-stride" | "add-scaled"


def _mem_regs(operand: str) -> list:
    """Register keys appearing inside a [...] memory operand, in order."""
    if "[" not in operand:
        return []
    inner = operand[operand.index("[") + 1: operand.rindex("]")] if "]" in operand else ""
    out = []
    for tok in _BRACKET_SEP.split(inner):
        # fullmatch via reg_num: "#0x08" and "lsl"/"#1" are rejected, so the
        # 'x08' substring of a hex immediate is never mistaken for register x8.
        r = reg_num(tok)
        if r is not None:
            out.append(r)
    return out


def _is_load(insn: Insn) -> bool:
    return insn.mnemonic in _LOADS


def _dest(insn: Insn):
    if insn.mnemonic in _NO_DEST or not insn.ops:
        return None
    return reg_num(insn.ops[0])


def _src_regs(insn: Insn) -> list:
    """Source register keys: all register operands except the destination, plus
    registers inside any memory operand."""
    regs = []
    ops = insn.ops
    start = 0 if _dest(insn) is None else 1
    for op in ops[start:]:
        r = reg_num(op)
        if r is not None:
            regs.append(r)
        regs.extend(_mem_regs(op))
    # a store's ops[0] is a source value, not a dest
    if insn.mnemonic.startswith(("str", "stp", "stur")):
        r0 = reg_num(ops[0]) if ops else None
        if r0 is not None:
            regs.append(r0)
    return regs


def find_index_sites(insns: list[Insn]) -> list[IndexSite]:
    """Taint-propagate over `insns` and return on-disk-derived index sites."""
    tainted: set = set()
    sites: list[IndexSite] = []

    for insn in insns:
        m = insn.mnemonic
        dest = _dest(insn)

        # --- detect a tainted index/scale use at THIS instruction (pre-update) ---
        if _is_load(insn) and len(insn.ops) >= 2:
            idx = [r for r in _mem_regs(insn.ops[-1])[1:] if r in tainted]
            if idx:
                sites.append(IndexSite(insn.addr, insn, tuple(idx), "load-index"))
        elif m.startswith("str") and len(insn.ops) >= 2:
            idx = [r for r in _mem_regs(insn.ops[-1])[1:] if r in tainted]
            if idx:
                sites.append(IndexSite(insn.addr, insn, tuple(idx), "store-index"))
        elif m in ("madd", "mul", "umull", "smull", "umaddl", "smaddl") and len(insn.ops) >= 3:
            factors = [reg_num(insn.ops[1]), reg_num(insn.ops[2])]
            idx = [r for r in factors if r in tainted]
            if idx:
                sites.append(IndexSite(insn.addr, insn, tuple(idx), "madd-stride"))
        elif m in ("add", "sub") and len(insn.ops) >= 4 \
                and any(k in " ".join(insn.ops) for k in
                        ("lsl", "lsr", "uxtw", "sxtw", "uxth", "sxth")):
            # e.g. `add x0, x19, x8, lsl #1`: ops = [x0, x19, x8, "lsl #1"].
            # dest=ops[0], base=ops[1]; a tainted register operand after the base
            # is a scaled index into the structure.
            idx = [r for r in (reg_num(o) for o in insn.ops[2:])
                   if r is not None and r in tainted]
            if idx:
                sites.append(IndexSite(insn.addr, insn, tuple(idx), "add-scaled"))

        # --- update taint state ---
        if _is_load(insn):
            # loads bring attacker-controlled data in; taint the dest(s).
            if m in ("ldp", "ldpsw") and len(insn.ops) >= 2:
                for o in insn.ops[:2]:
                    r = reg_num(o)
                    if r is not None:
                        tainted.add(r)
            elif dest is not None:
                tainted.add(dest)
        elif m in ("mov", "movz") and dest is not None and len(insn.ops) >= 2 \
                and reg_num(insn.ops[1]) is None:
            tainted.discard(dest)  # mov of an immediate -> clean
        elif m in _PROP and dest is not None:
            if any(s in tainted for s in _src_regs(insn)):
                tainted.add(dest)
            else:
                tainted.discard(dest)
        elif dest is not None:
            tainted.discard(dest)  # unknown op producing a value -> treat clean

    return sites
