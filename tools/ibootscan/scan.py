"""Tie the parser, idiom detector, and taint pass into a per-site audit report.

For the audited address range this answers the R14.3 question (FINDINGS.md:6461):
for each on-disk-derived index site, is a capacity-check guard present before it?

Verdicts, deliberately conservative:
  UNGUARDED  on-disk-derived index with NO capacity guard anywhere earlier in the
             range. The bug signature — audit these first.
  GUARDED?   a capacity guard precedes the site. Likely safe, but a human must
             confirm the guard's count actually bounds THIS index (the tool does
             not prove that link from a text listing — hence the '?').

The tool triages; it does not prove reachability or exploitability.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import asm
from .idiom import CapacityGuard, RangeCheck, find_capacity_guards, find_range_checks
from .taint import IndexSite, find_index_sites


@dataclass(frozen=True)
class SiteVerdict:
    site: IndexSite
    verdict: str                    # "UNGUARDED" | "GUARDED?"
    preceding_guards: tuple         # CapacityGuards before the site, in range
    range_checks: tuple = ()        # RangeChecks bounding this index, before it


@dataclass(frozen=True)
class Report:
    lo: int
    hi: int
    insn_count: int
    guards: tuple
    verdicts: tuple                 # SiteVerdicts in address order

    @property
    def unguarded(self) -> list:
        return [v for v in self.verdicts if v.verdict == "UNGUARDED"]


def scan(insns: list, lo: "int | None" = None, hi: "int | None" = None) -> Report:
    """Produce a Report for insns, optionally restricted to [lo, hi)."""
    if lo is not None or hi is not None:
        lo = lo if lo is not None else min((i.addr for i in insns), default=0)
        hi = hi if hi is not None else (max((i.addr for i in insns), default=0) + 4)
        window = asm.in_range(insns, lo, hi)
    else:
        window = list(insns)
        lo = min((i.addr for i in window), default=0)
        hi = max((i.addr for i in window), default=0) + 4

    guards = find_capacity_guards(window)
    rchecks = find_range_checks(window)
    sites = find_index_sites(window)

    verdicts = []
    for s in sites:
        before = tuple(g for g in guards if g.branch_addr < s.addr)
        # a range check only clears a site if it bounds one of ITS index regs
        rc = tuple(c for c in rchecks
                   if c.branch_addr < s.addr and c.reg in s.index_regs)
        verdict = "GUARDED?" if (before or rc) else "UNGUARDED"
        verdicts.append(SiteVerdict(site=s, verdict=verdict,
                                    preceding_guards=before, range_checks=rc))

    return Report(
        lo=lo, hi=hi, insn_count=len(window),
        guards=tuple(guards), verdicts=tuple(verdicts),
    )


def format_report(report: Report) -> str:
    """Human-readable summary for the CLI."""
    lines = []
    lines.append(f"range 0x{report.lo:x}..0x{report.hi:x}  "
                 f"({report.insn_count} instructions)")
    lines.append(f"capacity guards found: {len(report.guards)}")
    for g in report.guards:
        sgn = " [SIGNED cmp]" if g.signed else ""
        lines.append(f"  guard @0x{g.branch_addr:x}  "
                     f"(buf-0x{g.header:x})/0x{g.element_size:x} vs count  "
                     f"b.{g.cc}{sgn}  [udiv@0x{g.udiv_addr:x}]")
    lines.append("")
    lines.append(f"on-disk-derived index sites: {len(report.verdicts)}")
    for v in report.verdicts:
        s = v.site
        idx = ",".join(str(r) for r in s.index_regs)
        lines.append(f"  [{v.verdict:9}] @0x{s.addr:x}  {s.insn.mnemonic} "
                     f"{s.insn.raw}   (tainted idx x{idx}, {s.kind})")
        if v.preceding_guards:
            addrs = ", ".join(f"0x{g.branch_addr:x}" for g in v.preceding_guards)
            lines.append(f"              capacity guard(s): {addrs} "
                         f"— confirm they bound this index")
        if v.range_checks:
            rc = ", ".join(f"0x{c.cmp_addr:x} (<= 0x{c.bound:x})"
                           for c in v.range_checks)
            lines.append(f"              range check(s) on this index: {rc}")
    lines.append("")
    n = len(report.unguarded)
    if n:
        lines.append(f"=> {n} UNGUARDED site(s): on-disk index with no preceding "
                     f"capacity check. Audit first (FINDINGS.md:6461).")
    elif report.verdicts:
        lines.append("=> no UNGUARDED sites in range "
                     "(every on-disk index has a preceding guard or range check).")
    else:
        lines.append("=> no on-disk-derived index sites in range.")
    return "\n".join(lines)
