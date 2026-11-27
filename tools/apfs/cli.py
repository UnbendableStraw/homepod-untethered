"""Command-line front end for the APFS forge toolkit.

Emit a forged, checksum-valid APFS block to a file (ready to `dd` onto a block
of disk1s1 in the R14 harness loop, FINDINGS.md:6296) or inspect the objects in
an existing image.

    python3 -m apfs superblock --block-count 0x4000 -o /tmp/nxsb.bin
    python3 -m apfs checkpoint-map --mappings 2 -o /tmp/cpm.bin
    python3 -m apfs btree --entry k=v --malform value-underflow -o /tmp/node.bin
    python3 -m apfs inspect /tmp/node.bin

SAFETY: this tool only writes the file you name with -o (or stdout). It never
touches a device. Writing the block onto hardware is a separate, deliberate `dd`
the operator runs — and the R14 REVERT-FIRST rule (FINDINGS.md:6302) says to
back up every block you overwrite first.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from . import (
    CHECKPOINT_MAP_OTYPE,
    NX_SUPERBLOCK_OTYPE,
    BTreeNode,
    CheckpointMapping,
    build_checkpoint_map,
    build_nx_superblock,
    forge_key_offset_past_node,
    forge_nkeys_exceeds_toc,
    forge_value_length_underflow,
    verify_object,
)

# low-16 o_type -> name, for `inspect` (only names the repo/this toolkit uses).
_OTYPE_NAMES = {
    0x01: "NX_SUPERBLOCK",
    0x02: "BTREE",
    0x0B: "OMAP",
    0x0C: "CHECKPOINT_MAP",
    0x0F: "BLOCKREFTREE",
    0x10: "SNAPMETATREE",
}

_MALFORM = {
    "none": lambda node: node.build(),
    "nkeys": forge_nkeys_exceeds_toc,
    "value-underflow": forge_value_length_underflow,
    "key-oob": forge_key_offset_past_node,
}


def _int(text: str) -> int:
    """Parse an int accepting 0x.. hex or plain decimal."""
    return int(text, 0)


def _emit(data: bytes, out: "str | None") -> None:
    if out in (None, "-"):
        sys.stdout.buffer.write(data)
    else:
        Path(out).write_bytes(data)
        sys.stderr.write(f"wrote {len(data)} bytes to {out}\n")


def _cmd_superblock(args: argparse.Namespace) -> int:
    blk = build_nx_superblock(
        block_size=args.block_size,
        block_count=args.block_count,
        o_oid=args.oid,
        o_xid=args.xid,
        fs_oids=tuple(args.fs_oid or ()),
    )
    _emit(blk, args.output)
    return 0


def _cmd_checkpoint_map(args: argparse.Namespace) -> int:
    mappings = [CheckpointMapping() for _ in range(args.mappings)]
    blk = build_checkpoint_map(
        o_oid=args.oid,
        o_xid=args.xid,
        mappings=mappings,
        flags=args.flags,
        block_size=args.block_size,
        force_count=args.force_count,
    )
    _emit(blk, args.output)
    return 0


def _cmd_btree(args: argparse.Namespace) -> int:
    entries = []
    for item in args.entry or ["k=v"]:
        key, _, value = item.partition("=")
        entries.append((key.encode(), value.encode()))
    node = BTreeNode(
        o_oid=args.oid,
        o_xid=args.xid,
        entries=entries,
        block_size=args.block_size,
    )
    blk = _MALFORM[args.malform](node)
    _emit(blk, args.output)
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    data = Path(args.path).read_bytes()
    bs = args.block_size
    shown = 0
    for off in range(0, len(data) - bs + 1, bs):
        block = data[off : off + bs]
        otype = struct.unpack_from("<I", block, 0x18)[0]
        name = _OTYPE_NAMES.get(otype & 0xFFFF)
        if args.known_only and name is None:
            continue
        ok = verify_object(block)
        label = name or f"type={otype:#010x}"
        extra = ""
        if (otype & 0xFFFF) == 0x02:  # btree
            nkeys = struct.unpack_from("<I", block, 0x24)[0]
            extra = f" nkeys={nkeys}"
        elif (otype & 0xFFFF) == 0x0C:  # checkpoint map
            cnt = struct.unpack_from("<I", block, 0x24)[0]
            extra = f" cpm_count={cnt}"
        print(f"{off:#010x}  {label:<16} verify={ok}{extra}")
        shown += 1
    if shown == 0:
        sys.stderr.write("no matching objects found\n")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apfs", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--block-size", type=_int, default=0x1000)
        p.add_argument("--oid", type=_int, default=1)
        p.add_argument("--xid", type=_int, default=1)
        p.add_argument("-o", "--output", help="output file (default: stdout)")

    sp = sub.add_parser("superblock", help="emit a forged nx_superblock")
    add_common(sp)
    sp.add_argument("--block-count", type=_int, default=0)
    sp.add_argument(
        "--fs-oid", type=_int, action="append", help="volume oid (repeatable)"
    )
    sp.set_defaults(func=_cmd_superblock)

    cp = sub.add_parser("checkpoint-map", help="emit a forged checkpoint_map")
    add_common(cp)
    cp.add_argument("--mappings", type=int, default=0, help="number of entries")
    cp.add_argument("--flags", type=_int, default=0)
    cp.add_argument(
        "--force-count",
        type=_int,
        default=None,
        help="override cpm_count (build an over-count probe)",
    )
    cp.set_defaults(func=_cmd_checkpoint_map)

    bt = sub.add_parser("btree", help="emit a forged btree node")
    add_common(bt)
    bt.add_argument(
        "--entry", action="append", help="KEY=VALUE TOC entry (repeatable)"
    )
    bt.add_argument(
        "--malform",
        choices=sorted(_MALFORM),
        default="none",
        help="malformation to apply (default: none)",
    )
    bt.set_defaults(func=_cmd_btree)

    ins = sub.add_parser("inspect", help="list APFS objects in a file and verify")
    ins.add_argument("path")
    ins.add_argument("--block-size", type=_int, default=0x1000)
    ins.add_argument(
        "--known-only",
        action="store_true",
        help="only show objects whose type this toolkit names",
    )
    ins.set_defaults(func=_cmd_inspect)

    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
