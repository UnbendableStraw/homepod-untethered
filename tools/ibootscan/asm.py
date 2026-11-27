"""Tolerant ARM64 disassembly-listing parser (stdlib only).

The R14.3 audit (FINDINGS.md:6456) works over a disassembly of a function range
that the researcher produces from *their own* extracted iBoot with whatever tool
they have. Those tools format the same instruction differently, so this parser
accepts all of the common shapes and normalises them to `Insn`:

    llvm-objdump -d        14ae8: a9 0c 53 f3  \tstp\tx19, x20, [sp, #-0x20]!
    llvm-objdump (no-raw)  14ae8:             \tstp\tx19, x20, [sp, #-0x20]!
    otool -tV              0000000000014ae8\tstp\tx19, x20, [sp, #-0x20]!
    GNU objdump            14ae8:\ta90c53f3 \tstp\tx19, x20, [sp, #-32]
    radare2 pd             0x00014ae8  a90c53f3  stp x19, x20, [sp, -0x20]!
    FINDINGS.md notation   0x144d0  sub x9, x9, #0x28

The unifying idea: after the leading address, machine-code bytes appear as either
2-hex-digit pairs or one 8-hex-digit word; the first token that is NOT that shape
is the mnemonic. A 3-char mnemonic such as `adc` (itself valid hex) is safe
because it is neither 2 nor 8 hex digits long.

This module only *parses* text; it never decodes raw bytes, so it needs no
third-party disassembler and carries no Apple code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# A leading address: optional 0x, hex digits, optional trailing colon, then space.
_ADDR = re.compile(r"^\s*(?:0x)?([0-9a-fA-F]+):?\s+(.*)$")
# A machine-code token: one 32-bit word, or a single byte pair.
_RAWWORD = re.compile(r"^[0-9a-fA-F]{8}$")
_RAWBYTE = re.compile(r"^[0-9a-fA-F]{2}$")
# Comment lead-ins used by the various tools.
_COMMENT = re.compile(r"\s*(?:;|//|@|#\s(?!0x)).*$")


@dataclass(frozen=True)
class Insn:
    """One decoded listing line.

    addr      integer instruction address
    mnemonic  lower-cased, e.g. "sub", "udiv", "b.hs", "ldrh"
    ops       operand strings, split on top-level commas, e.g. ["x9","x9","#0x28"]
    raw       the original operand text (comments stripped), for reporting
    """

    addr: int
    mnemonic: str
    ops: tuple[str, ...]
    raw: str = ""
    # cc is the condition suffix for a branch ("hs","lo",...) or "" otherwise.
    cc: str = field(default="")


def _split_ops(operand_text: str) -> list[str]:
    """Split operands on commas that are not inside [] or {} brackets."""
    ops: list[str] = []
    depth = 0
    cur = []
    for ch in operand_text:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            ops.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    tail = "".join(cur).strip()
    if tail:
        ops.append(tail)
    return ops


def parse_line(line: str) -> "Insn | None":
    """Parse one listing line, or return None if it holds no instruction."""
    m = _ADDR.match(line)
    if not m:
        return None
    addr = int(m.group(1), 16)
    rest = m.group(2)

    # Strip a trailing comment (llvm uses "; ...", r2 uses ";", some use "//").
    rest = _COMMENT.sub("", rest).strip()
    if not rest:
        return None

    # Tokenise and drop a leading run of machine-code bytes/words.
    tokens = rest.split()
    i = 0
    while i < len(tokens) and (_RAWWORD.match(tokens[i]) or _RAWBYTE.match(tokens[i])):
        i += 1
    if i >= len(tokens):
        return None  # address + raw bytes only, no mnemonic (e.g. data)

    mnemonic = tokens[i].lower()
    # Rebuild operands from the remaining tokens rather than str.split on the
    # mnemonic: a mnemonic made only of hex chars (e.g. "add") could otherwise
    # match earlier inside the raw-byte prefix and mis-split the line.
    operand_text = " ".join(tokens[i + 1:])

    cc = ""
    if "." in mnemonic:  # conditional branch: b.hs, b.lo, b.cc, ...
        cc = mnemonic.split(".", 1)[1]

    return Insn(
        addr=addr,
        mnemonic=mnemonic,
        ops=tuple(_split_ops(operand_text)),
        raw=operand_text,
        cc=cc,
    )


def parse_listing(text: str) -> list[Insn]:
    """Parse a full listing, skipping blank/label/non-instruction lines."""
    out: list[Insn] = []
    for line in text.splitlines():
        insn = parse_line(line)
        if insn is not None:
            out.append(insn)
    return out


def in_range(insns: list[Insn], lo: int, hi: int) -> list[Insn]:
    """Return instructions with lo <= addr < hi (hi exclusive), in order."""
    return [i for i in insns if lo <= i.addr < hi]
