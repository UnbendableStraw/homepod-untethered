"""Detect the R14.2 capacity-check idiom in a parsed instruction stream.

FINDINGS.md:6403-6412 names the author's bounds-check pattern for an on-disk
count:

    capacity = (buffer_size - header_size) / element_size   ; sub then udiv
    if (capacity < on_disk_count) -> fail                   ; cmp then b.hs/b.lo

Its *absence* on a path that then indexes off the structure is the bug signature.
This module finds every occurrence of the guard so the scanner can ask, per
index site, "is a capacity guard present for this count?".

Why dataflow and not text matching: the four instructions need not be adjacent,
and registers thread them together (the `sub` feeds the `udiv` feeds the `cmp`
feeds the branch). We keep a tiny symbolic state over the stream. ARM64 `udiv`
has no immediate form, so a divisor is resolved as a literal immediate (the
FINDINGS shorthand) OR a register previously set by `mov rD, #imm`.

No raw bytes are decoded; this reasons purely over parsed `Insn`s.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .asm import Insn

# Unsigned condition codes that form a real capacity guard. The compare is
# capacity-vs-count, so the taken/‘fall-through-to-fail’ branch is unsigned.
# A signed cc (ge/lt/gt/le) comparing sizes is suspicious but still a guard; we
# record it and let the caller flag the signedness separately.
GUARD_CC_UNSIGNED = frozenset({"hs", "cs", "lo", "cc", "hi", "ls"})
GUARD_CC_SIGNED = frozenset({"ge", "lt", "gt", "le"})
GUARD_CC = GUARD_CC_UNSIGNED | GUARD_CC_SIGNED

# Immediate operand. The leading '#' is optional: llvm-objdump/otool/objdump and
# the FINDINGS.md notation write '#0x28', but radare2 writes a bare '0x28'.
_IMM = re.compile(r"^#?(-?)(?:0x([0-9a-fA-F]+)|(\d+))$")

# Mnemonics that do NOT write a general-purpose register (so they never clear a
# tracked role via a destination). Everything else is assumed to write ops[0].
_NO_GPR_DEST = frozenset({
    "cmp", "cmn", "tst", "ccmp", "ccmn",
    "stp", "str", "strh", "strb", "stur", "sturh", "sturb",
    "cbz", "cbnz", "tbz", "tbnz",
    "b", "bl", "br", "blr", "ret", "nop", "pacibsp", "autibsp",
    "svc", "brk", "dmb", "dsb", "isb",
})

# Flag-setting instructions. The guard branch must consume the flags set by the
# capacity `cmp` with no other flag-setter in between.
_FLAG_SETTERS = frozenset({"cmp", "cmn", "tst", "subs", "adds", "ands", "ccmp", "ccmn"})


def reg_num(tok: str) -> "int | str | None":
    """Normalise a register token to a key shared by its w/x views.

    x9 and w9 are the same physical register -> 9. Returns "zr" for the zero
    register, "sp" for the stack pointer, or None if tok is not a register.
    """
    t = tok.strip().lower()
    if t in ("xzr", "wzr"):
        return "zr"
    if t in ("sp", "wsp"):
        return "sp"
    m = re.fullmatch(r"[wx](\d{1,2})", t)
    if m:
        n = int(m.group(1))
        return n if 0 <= n <= 30 else None
    return None


def imm_val(tok: str) -> "int | None":
    """Parse an immediate operand like '#0x28' or '#40' -> int, else None."""
    m = _IMM.match(tok.strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    if m.group(2) is not None:
        return sign * int(m.group(2), 16)
    return sign * int(m.group(3))


@dataclass(frozen=True)
class CapacityGuard:
    """One detected `(buf-hdr)/elem` capacity check guarding a count.

    count_reg is the register holding the on-disk count that this guard bounds;
    the scanner matches it against the count feeding an index site.
    """

    udiv_addr: int
    cmp_addr: int
    branch_addr: int
    capacity_reg: "int | str"
    count_reg: "int | str"
    element_size: int
    header: int
    cc: str

    @property
    def signed(self) -> bool:
        return self.cc in GUARD_CC_SIGNED


def _dest_reg(insn: Insn) -> "int | str | None":
    if insn.mnemonic in _NO_GPR_DEST or not insn.ops:
        return None
    return reg_num(insn.ops[0])


def find_capacity_guards(insns: list[Insn]) -> list[CapacityGuard]:
    """Return every R14.2 capacity guard found in `insns`, in address order."""
    consts: dict = {}          # reg -> immediate value (from mov/movz)
    sub_hdr: dict = {}         # reg -> header immediate (from `sub reg, src, #imm`)
    capacity: dict = {}        # reg -> (element_size, header, udiv_addr)
    pending = None             # (capacity_reg, count_reg, cmp_addr) awaiting branch
    last_flag_setter_is_cmp = False
    guards: list[CapacityGuard] = []

    for insn in insns:
        m = insn.mnemonic
        dest = _dest_reg(insn)

        # --- recognise the guard branch first (consumes pending + flags) ---
        if m.startswith("b.") and insn.cc in GUARD_CC and pending is not None \
                and last_flag_setter_is_cmp:
            cap_reg, count_reg, cmp_addr = pending
            es, hdr, udiv_addr = capacity[cap_reg]
            guards.append(CapacityGuard(
                udiv_addr=udiv_addr, cmp_addr=cmp_addr, branch_addr=insn.addr,
                capacity_reg=cap_reg, count_reg=count_reg,
                element_size=es, header=hdr, cc=insn.cc,
            ))
            pending = None
            # fallthrough to role bookkeeping below

        # A new flag-setter that is not our capacity cmp invalidates a pending
        # guard (the NZCV it would branch on is no longer the capacity compare).
        if m in _FLAG_SETTERS and m != "cmp":
            last_flag_setter_is_cmp = False
            pending = None
        elif m != "cmp" and not (m.startswith("b.")):
            # non-flag, non-branch instruction between cmp and branch: NZCV
            # survives (data ops don't set flags unless the 's' form), so leave
            # last_flag_setter_is_cmp as-is.
            pass

        # --- compute any new role from the PRE-clear state (sources may equal
        #     the destination, e.g. `udiv x9, x9, #0x28`), then clear, then set.
        new_const = new_sub_hdr = new_capacity = None
        if m in ("mov", "movz") and dest is not None and len(insn.ops) >= 2:
            v = imm_val(insn.ops[1])
            if v is not None:
                new_const = v

        elif m == "sub" and dest is not None and len(insn.ops) == 3:
            hdr = imm_val(insn.ops[2])
            if hdr is not None:
                new_sub_hdr = hdr  # dest = src - hdr (buffer_size - header)

        elif m == "udiv" and dest is not None and len(insn.ops) == 3:
            n = reg_num(insn.ops[1])
            if n in sub_hdr:
                es = imm_val(insn.ops[2])
                if es is None:
                    es = consts.get(reg_num(insn.ops[2]))
                if es:
                    new_capacity = (es, sub_hdr[n], insn.addr)

        # --- clear roles for an overwritten destination, then apply the new one.
        if dest is not None:
            consts.pop(dest, None)
            sub_hdr.pop(dest, None)
            capacity.pop(dest, None)
            if new_const is not None:
                consts[dest] = new_const
            if new_sub_hdr is not None:
                sub_hdr[dest] = new_sub_hdr
            if new_capacity is not None:
                capacity[dest] = new_capacity

        if m == "cmp" and len(insn.ops) >= 2:
            a, b = reg_num(insn.ops[0]), reg_num(insn.ops[1])
            if a in capacity:
                pending = (a, b, insn.addr)
            elif b in capacity:
                pending = (b, a, insn.addr)
            else:
                pending = None
            last_flag_setter_is_cmp = pending is not None

    return guards
