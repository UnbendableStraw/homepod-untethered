"""Command-line front end for the R14.3 APFS btree-walker audit aid.

    # A decrypted iBoot is a RAW aarch64 image (not Mach-O): disassemble it at
    # base 0 so addresses equal the file offsets FINDINGS.md cites, then scan:
    r2 -a arm -b 64 -qc 's 0x14ae8; pd 600' iBoot.dec > iboot.lst
    PYTHONPATH=tools python3 -m ibootscan scan iboot.lst --lo 0x14ae8 --hi 0x1526c

    # or pipe a disassembly straight in (GNU binutils; g-prefixed on macOS):
    gobjdump -D -b binary -maarch64 iBoot.dec | python3 -m ibootscan scan - --lo 0x14ae8 --hi 0x1526c

    # just list the capacity guards it recognises:
    python3 -m ibootscan guards iboot.lst --lo 0x14418 --hi 0x14790

The listing is YOUR artifact; the tool reads nothing else, fetches nothing, and
ships no Apple code. UNGUARDED findings are candidates to confirm by hand, not
proven bugs (FINDINGS.md:6456-6467).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import asm
from .scan import scan, format_report


def _read_listing(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text()


def _int0(s: "str | None"):
    return None if s is None else int(s, 0)  # accepts 0x.. or decimal


def _cmd_scan(args: argparse.Namespace) -> int:
    insns = asm.parse_listing(_read_listing(args.listing))
    report = scan(insns, _int0(args.lo), _int0(args.hi))
    print(format_report(report))
    # exit 2 when there is something to audit, so CI/scripts can gate on it.
    return 2 if report.unguarded else 0


def _cmd_guards(args: argparse.Namespace) -> int:
    from .idiom import find_capacity_guards
    insns = asm.parse_listing(_read_listing(args.listing))
    lo, hi = _int0(args.lo), _int0(args.hi)
    if lo is not None or hi is not None:
        insns = asm.in_range(insns,
                             lo if lo is not None else 0,
                             hi if hi is not None else (1 << 64))
    guards = find_capacity_guards(insns)
    print(f"capacity guards: {len(guards)}")
    for g in guards:
        sgn = " [SIGNED]" if g.signed else ""
        print(f"  @0x{g.branch_addr:x}  (buf-0x{g.header:x})/0x{g.element_size:x}"
              f"  b.{g.cc}{sgn}  udiv@0x{g.udiv_addr:x}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ibootscan", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="report on-disk index sites and their guard status")
    s.add_argument("listing", help="disassembly listing file, or '-' for stdin")
    s.add_argument("--lo", help="range start address (0x.. or decimal)")
    s.add_argument("--hi", help="range end address, exclusive")
    s.set_defaults(func=_cmd_scan)

    g = sub.add_parser("guards", help="list only the R14.2 capacity guards found")
    g.add_argument("listing", help="disassembly listing file, or '-' for stdin")
    g.add_argument("--lo", help="range start address")
    g.add_argument("--hi", help="range end address, exclusive")
    g.set_defaults(func=_cmd_guards)

    return p


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
