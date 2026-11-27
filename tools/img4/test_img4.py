"""Tests for the IMG4 reconstruction toolkit (stdlib unittest — no dependency).

    python3 -m unittest discover -s tools/img4

Correctness layers:
  1. DER encode/decode vectors (hand-checked)
  2. build/parse round-trip and the 37-byte IM4R rule
  3. GOLD: reproduce a REAL Apple file byte-for-byte from a public .im4p + a
     saved APTicket (the actual R13 proof) — runs only when IMG4_GOLD_DIR is set.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))  # tools/ on path to import `img4`

from img4 import build_img4, parse_img4, to_filesystem_image  # noqa: E402
from img4 import der  # noqa: E402
from img4.cli import main as cli_main  # noqa: E402


def _seq(*parts: bytes) -> bytes:
    return der.tlv(der.TAG_SEQUENCE, b"".join(parts))


# Synthetic but structurally-valid IM4P/IM4M/IM4R objects (opaque to the tool).
IM4P = _seq(der.ia5string("IM4P"), der.ia5string("krnl"), b"\x04\x03abc")
IM4M = _seq(der.ia5string("IM4M"), b"\x04\x02mm")
IM4R = _seq(der.ia5string("IM4R"), b"\x04\x02rr")


class DerTests(unittest.TestCase):
    def test_encode_length_short_and_long(self):
        self.assertEqual(der.encode_length(0), b"\x00")
        self.assertEqual(der.encode_length(5), b"\x05")
        self.assertEqual(der.encode_length(0x7F), b"\x7f")
        self.assertEqual(der.encode_length(0x80), b"\x81\x80")
        self.assertEqual(der.encode_length(0x100), b"\x82\x01\x00")
        self.assertEqual(der.encode_length(0xFFFF), b"\x82\xff\xff")

    def test_length_roundtrip(self):
        for n in (0, 1, 0x7F, 0x80, 0x1234, 0xFFFF, 0x10000):
            enc = der.encode_length(n)
            got, off = der.read_length(enc, 0)
            self.assertEqual((got, off), (n, len(enc)))

    def test_read_tlv_and_truncation(self):
        blob = der.tlv(der.TAG_IA5STRING, b"IMG4")
        tag, value, nxt = der.read_tlv(blob)
        self.assertEqual((tag, value, nxt), (der.TAG_IA5STRING, b"IMG4", len(blob)))
        with self.assertRaises(ValueError):
            der.read_tlv(blob[:-1])  # value runs past end

    def test_indefinite_length_rejected(self):
        with self.assertRaises(ValueError):
            der.read_length(b"\x80", 0)


class Img4Tests(unittest.TestCase):
    def test_build_requires_payload(self):
        with self.assertRaises(ValueError):
            build_img4(b"")

    def test_marker_is_first_child(self):
        img = build_img4(IM4P)
        _, body, _ = der.read_tlv(img)
        tag, value, _ = der.read_tlv(body, 0)
        self.assertEqual((tag, value), (der.TAG_IA5STRING, b"IMG4"))

    def test_full_roundtrip(self):
        img = build_img4(IM4P, IM4M, IM4R)
        parts = parse_img4(img)
        self.assertEqual(parts["im4p"], IM4P)
        self.assertEqual(parts["im4m"], IM4M)
        self.assertEqual(parts["im4r"], IM4R)
        self.assertEqual(
            build_img4(parts["im4p"], parts["im4m"], parts["im4r"]), img
        )

    def test_filesystem_image_omits_im4r(self):
        # filesystem image: no IM4R (the 37-byte rule, FINDINGS.md:6195)
        fs = build_img4(IM4P, IM4M)
        self.assertIsNone(parse_img4(fs)["im4r"])
        # partition image carries IM4R; stripping it yields exactly the fs form
        partition = build_img4(IM4P, IM4M, IM4R)
        self.assertEqual(to_filesystem_image(partition), fs)
        # and the size delta is exactly the [1]-wrapped IM4R
        self.assertEqual(len(partition) - len(fs), len(der.explicit(1, IM4R)))

    def test_parse_rejects_non_img4(self):
        with self.assertRaises(ValueError):
            parse_img4(der.tlv(0x04, b"not a sequence"))  # OCTET STRING
        with self.assertRaises(ValueError):
            parse_img4(_seq(der.ia5string("NOPE"), IM4P))  # wrong marker


class CLITests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "p.im4p").write_bytes(IM4P)
        (self.dir / "m.im4m").write_bytes(IM4M)
        (self.dir / "r.im4r").write_bytes(IM4R)

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_filesystem_image(self):
        out = self.dir / "fs.img4"
        rc = cli_main(
            ["build", "--im4p", str(self.dir / "p.im4p"),
             "--im4m", str(self.dir / "m.im4m"), "-o", str(out)]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out.read_bytes(), build_img4(IM4P, IM4M))

    def test_build_partition_then_strip(self):
        part = self.dir / "part.img4"
        cli_main(
            ["build", "--im4p", str(self.dir / "p.im4p"),
             "--im4m", str(self.dir / "m.im4m"),
             "--im4r", str(self.dir / "r.im4r"), "-o", str(part)]
        )
        self.assertEqual(parse_img4(part.read_bytes())["im4r"], IM4R)
        fs = self.dir / "fs.img4"
        cli_main(["strip-im4r", str(part), "-o", str(fs)])
        self.assertIsNone(parse_img4(fs.read_bytes())["im4r"])

    def test_inspect_reports_kind(self):
        part = build_img4(IM4P, IM4M, IM4R)
        p = self.dir / "part.img4"
        p.write_bytes(part)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli_main(["inspect", str(p)])
        self.assertEqual(rc, 0)
        self.assertIn("firmware-partition image", buf.getvalue())
        self.assertIn("im4m:", buf.getvalue())


class GoldReproductionTest(unittest.TestCase):
    """The R13 proof: reproduce Apple's exact file from public inputs.

    Set IMG4_GOLD_DIR to a directory holding:
        payload.im4p   -- a PUBLIC stock .im4p (e.g. kernelcache.release.b238)
        apticket.im4m  -- your device's saved APTicket
        expected.img4  -- Apple's installed FILESYSTEM image for that component
    The test asserts build_img4(payload, apticket) reproduces expected byte-for-
    byte (md5). These are YOUR artifacts; this toolkit never fetches them.
    """

    def test_reproduces_apple_file(self):
        gold = os.environ.get("IMG4_GOLD_DIR")
        if not gold:
            self.skipTest("set IMG4_GOLD_DIR (payload.im4p, apticket.im4m, expected.img4)")
        base = Path(gold)
        im4p = (base / "payload.im4p").read_bytes()
        im4m = (base / "apticket.im4m").read_bytes()
        expected = (base / "expected.img4").read_bytes()
        rebuilt = build_img4(im4p, im4m)
        self.assertEqual(
            hashlib.md5(rebuilt).hexdigest(),
            hashlib.md5(expected).hexdigest(),
            "reconstruction does not match Apple's file byte-for-byte",
        )


if __name__ == "__main__":
    unittest.main()
