"""Command-line front end for IMG4 reconstruction (R13).

    # reconstruct a personalised filesystem image from public payload + APTicket
    python3 -m img4 build --im4p kernelcache.release.b238 \\
        --im4m apticket-17M61.im4m -o kernelcache.img4

    # firmware-partition image: add the restore info (the 37-byte rule)
    python3 -m img4 build --im4p iboot.im4p --im4m tkt.im4m --im4r bncn.im4r -o iboot.img4

    # inspect / decompose an existing IMG4
    python3 -m img4 inspect some.img4
    python3 -m img4 strip-im4r partition.img4 -o filesystem.img4

Inputs are your own files; this tool fetches nothing and contacts no server.
The reconstruction uses only a PUBLIC .im4p plus YOUR saved APTicket, exactly as
R13 demonstrated (FINDINGS.md:6171).
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from . import build_img4, parse_img4, to_filesystem_image


def _emit(data: bytes, out: "str | None") -> None:
    if out in (None, "-"):
        sys.stdout.buffer.write(data)
    else:
        Path(out).write_bytes(data)
        sys.stderr.write(f"wrote {len(data)} bytes to {out}\n")


def _cmd_build(args: argparse.Namespace) -> int:
    im4p = Path(args.im4p).read_bytes()
    im4m = Path(args.im4m).read_bytes() if args.im4m else None
    im4r = Path(args.im4r).read_bytes() if args.im4r else None
    _emit(build_img4(im4p, im4m, im4r), args.output)
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    data = Path(args.path).read_bytes()
    parts = parse_img4(data)
    print(f"IMG4: {len(data)} bytes  md5={hashlib.md5(data).hexdigest()}")
    for name in ("im4p", "im4m", "im4r"):
        part = parts[name]
        if part is None:
            print(f"  {name}: (absent)")
        else:
            print(f"  {name}: {len(part)} bytes  md5={hashlib.md5(part).hexdigest()}")
    kind = "firmware-partition image" if parts["im4r"] else "filesystem image"
    print(f"  => {kind} (37-byte rule, FINDINGS.md:6195)")
    return 0


def _cmd_strip_im4r(args: argparse.Namespace) -> int:
    data = Path(args.path).read_bytes()
    _emit(to_filesystem_image(data), args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="img4", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="assemble an IMG4 from payload + APTicket")
    b.add_argument("--im4p", required=True, help="public .im4p payload (required)")
    b.add_argument("--im4m", help="APTicket .im4m (manifest)")
    b.add_argument("--im4r", help="restore info .im4r (firmware-partition images only)")
    b.add_argument("-o", "--output", help="output file (default: stdout)")
    b.set_defaults(func=_cmd_build)

    i = sub.add_parser("inspect", help="decompose an IMG4 and report its parts")
    i.add_argument("path")
    i.set_defaults(func=_cmd_inspect)

    s = sub.add_parser("strip-im4r", help="produce the filesystem-image form (drop [1] IM4R)")
    s.add_argument("path")
    s.add_argument("-o", "--output", help="output file (default: stdout)")
    s.set_defaults(func=_cmd_strip_im4r)

    return parser


def main(argv: "list[str] | None" = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
