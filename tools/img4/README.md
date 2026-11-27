# IMG4 reconstruction toolkit (R13)

Reassemble Apple's personalised, signed boot files from a **public** `.im4p`
payload plus a **saved APTicket** (`.im4m`) — byte-for-byte, with no Apple
server and no secret. This packages R13 (`FINDINGS.md:6171-6197`), the repo's
strongest result, as a reusable, tested tool.

## What R13 showed

Public stock `17M61` payloads + the device's own 4,818-byte APTicket reproduce
Apple's installed `devicetree`, `kernelcache`, `sep-firmware` and
`StaticTrustCache` with an exact MD5 match (`FINDINGS.md:6179-6192`). The
reconstruction is pure DER assembly:

```
IMG4 ::= SEQUENCE {
    "IMG4"   IA5String,
    im4p     IM4P,              -- the public payload, verbatim
    im4m     [0] EXPLICIT IM4M, -- the saved APTicket
    im4r     [1] EXPLICIT IM4R  -- OPTIONAL
}
```

**The 37-byte rule** (`FINDINGS.md:6195`): filesystem images (kernelcache,
devicetree, …) OMIT `[1] IM4R`; firmware-partition images (disk2/disk3: iBoot,
LLB) carry it. Here that is simply whether `--im4r` is supplied.

## Why no dependency

The inputs are already complete DER objects; building an IMG4 means concatenating
them with the right context tags under a SEQUENCE header — minimal DER
length-encoding, pure stdlib (`der.py`). No `pyimg4`/`asn1` needed. Python 3.11+.

## Modules

| File | Contents |
| :--- | :--- |
| `der.py` | minimal DER: length encode/decode, TLV read, explicit-tag wrap |
| `img4.py` | `build_img4`, `parse_img4`, `to_filesystem_image` (the 37-byte transform) |
| `cli.py`, `__main__.py` | `python3 -m img4 {build,inspect,strip-im4r}` |
| `test_img4.py` | `unittest`: DER vectors, round-trip, IM4R rule, CLI, gold fixture |

## Usage

`tools/` is the import root, so run with `PYTHONPATH=tools`:

```sh
# reconstruct a filesystem image (kernelcache, devicetree, ...)
PYTHONPATH=tools python3 -m img4 build \
    --im4p kernelcache.release.b238 --im4m apticket-17M61.im4m -o kernelcache.img4

# firmware-partition image: include the restore info
PYTHONPATH=tools python3 -m img4 build \
    --im4p iboot.im4p --im4m ticket.im4m --im4r bncn.im4r -o iboot.img4

# inspect / decompose
PYTHONPATH=tools python3 -m img4 inspect kernelcache.img4
PYTHONPATH=tools python3 -m img4 strip-im4r iboot.img4 -o iboot.fs.img4
```

## Correctness

- **DER codec** is checked against hand-computed length vectors and validated
  against real long-form DER (a system X.509 certificate round-trips byte-for-
  byte) — the same encoding Apple's multi-MB payloads use.
- **Round-trip**: `build_img4(**parse_img4(x)) == x`, and the 37-byte transform
  is exact.
- **Gold (the real R13 proof)** — reproduce an actual Apple file from public
  inputs. Set `IMG4_GOLD_DIR` to a directory with `payload.im4p`,
  `apticket.im4m`, `expected.img4` (a filesystem image) and run the tests; it
  asserts `build_img4(payload, apticket)` matches `expected` by MD5. These are
  **your** artifacts — the toolkit fetches nothing.

```sh
IMG4_GOLD_DIR=/path/to/artifacts python3 -m unittest discover -s tools/img4
```

## Scope

Software-only, offline, no device. Contains no Apple binaries or device
identifiers. It assembles/parses containers; it does not sign, verify signatures,
or touch hardware.
