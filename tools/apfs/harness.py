"""Differential R14 harness: forge malformed btree nodes, see what catches them.

The offline, software-only half of the R14 harness loop (FINDINGS.md:6294). For
each malformation the forge can build, it answers two independent questions:

  1. Does it pass Fletcher-64 integrity?  (It always does — that is R13.2: the
     checksum is unkeyed, so we recompute it. Integrity does NOT stop us.)
  2. Does the clean-room reference validator (validate.py) reject it?

The gap between the two is the whole point: every malformation is integrity-valid
yet structurally out of bounds, so a walker that checks only the checksum and not
the structure indexes outside the node. These are the exact inputs to drive
through iBoot on the hardware loop (FINDINGS.md:6296); here we characterise them
offline, with no pod and no Apple code.

The reference validator's two node-level invariants were reverse-engineered this
session from iBoot-5540's real node validator at 0x16b38..0x16d68.
"""
from __future__ import annotations

from dataclasses import dataclass

from .btree import (
    BTreeNode,
    forge_key_offset_past_node,
    forge_nkeys_exceeds_toc,
    forge_value_length_underflow,
)
from .fletcher import verify_object
from .validate import validate_btree_node


@dataclass(frozen=True)
class Case:
    name: str
    block: bytes
    fletcher_valid: bool
    violations: tuple  # tuple[Violation, ...]

    @property
    def integrity_only_gap(self) -> bool:
        """True when a Fletcher-only parser would wrongly accept this node."""
        return self.fletcher_valid and bool(self.violations)


def control_node(block_size: int = 0x1000) -> BTreeNode:
    """A small, well-formed variable-kv root/leaf node used as the baseline."""
    return BTreeNode(
        block_size=block_size,
        entries=[(b"key01", b"val01"), (b"key02", b"val02")],
    )


def run(block_size: int = 0x1000) -> list[Case]:
    """Build the control node plus every forge malformation and characterise each."""
    good = control_node(block_size)
    specs = [
        ("well_formed", good.build()),
        ("nkeys_exceeds_toc", forge_nkeys_exceeds_toc(good)),
        ("value_length_underflow", forge_value_length_underflow(good)),
        ("key_offset_past_node", forge_key_offset_past_node(good)),
    ]
    return [
        Case(name, block, verify_object(block), tuple(validate_btree_node(block)))
        for name, block in specs
    ]


def format_report(cases: list[Case]) -> str:
    lines = [
        f"{'case':<24} {'fletcher':<9} {'structural':<11} violated invariant(s)",
        "-" * 74,
    ]
    for c in cases:
        struct_state = "valid" if not c.violations else "REJECT"
        codes = ", ".join(v.code for v in c.violations) or "-"
        lines.append(f"{c.name:<24} {'valid' if c.fletcher_valid else 'BAD':<9} "
                     f"{struct_state:<11} {codes}")
    gap = sum(c.integrity_only_gap for c in cases)
    lines += [
        "",
        f"=> {gap} malformation(s) pass Fletcher-64 but fail structural validation.",
        "   A walker that trusts only the (unkeyed) checksum would index out of",
        "   bounds on these. They are the inputs to drive through iBoot's node",
        "   validator (audited at 0x16b38; FINDINGS.md:6294).",
    ]
    return "\n".join(lines)


def main(argv: "list[str] | None" = None) -> int:
    print(format_report(run()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
