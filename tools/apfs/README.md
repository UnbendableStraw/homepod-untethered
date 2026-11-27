# APFS forge toolkit

Offline tooling to build attacker-controlled APFS structures with valid, forged
**Fletcher-64** checksums — the offline half of the R14 pre-authentication audit
harness (`FINDINGS.md` R14, line 6242; harness loop step 1, line 6294).

## Why this is the right target

`iBoot-5540.140.12` mounts and walks the APFS container on `disk1s1` to find the
four files it loads (`kernelcache`, `devicetree.img4`, `sep-firmware.img4`,
`StaticTrustCache.img4`) **before it authenticates any IMG4 payload**. The only
integrity protection on those on-disk structures is an **unkeyed Fletcher-64**
seeded with 0 (`FINDINGS.md` R13.2, line 6224). Unkeyed means forgeable: given
any tampered structure, recompute the checksum and iBoot accepts it. This
toolkit is that recompute primitive, plus typed builders for the structures the
R14 audit targets.

## Safety / scope

- **No hardware.** Touches no HomePod, no USB device, no raw disk. Pure byte
  manipulation in memory and files you pass it.
- **No Apple IP.** Ships no Apple binaries, firmware, or device data. Every
  structure offset it encodes is cited to a verified line in `FINDINGS.md`.
- The malformation generators (increment 3) emit *offline test inputs*; they do
  not write to any device.

## Correctness status

**Confirmed byte-exact.** The Fletcher-64 here is the standard Apple File System
Reference formulation, and `verify_object()` accepts the stored checksum of
**real Apple-written APFS container superblocks** (proven against 3 NXSB blocks
in a throwaway `hdiutil` APFS image). Reproduce the gold check — userspace, no
`sudo`, no device:

```sh
# make a throwaway APFS image (real Apple superblocks live inside it)
hdiutil create -size 16m -fs APFS -volname GOLD -layout GPTSPUD /tmp/gold.dmg
# the gold test scans it for NXSB blocks and verifies each
APFS_GOLD_OBJECT=/tmp/gold.dmg python3 -m unittest discover -s tools/apfs
# (a real volume works too, if you have the privileges:)
# sudo dd if=/dev/diskXsY bs=4096 count=1 of=/tmp/nxsb.bin
```

The one remaining **inference** is that iBoot's reader at `0x162c8` uses this same
algorithm — strongly supported by the repo's own disassembly of it ("plain
Fletcher-64, seed 0, covering obj+8", `FINDINGS.md:6227`), but not executed
directly. Structure offsets are independently grounded in `FINDINGS.md`.

## Modules

| File | Contents |
| :--- | :--- |
| `fletcher.py` | Fletcher-64 compute / `apply_checksum` (forge) / `verify_object` |
| `objects.py` | `obj_phys_t` header (`ObjPhys`), `build_object`, object-type constants |
| `superblock.py` | `build_nx_superblock` (minimal container superblock) |
| `checkpoint_map.py` | `build_checkpoint_map`, `capacity`/`is_within_capacity` — the correctly-bounded validator from R14.2, incl. an over-count probe builder |
| `btree.py` | `BTreeNode` + `forge_nkeys_exceeds_toc` / `forge_value_length_underflow` / `forge_key_offset_past_node` — the R14.3 attack-surface node and its malformation generators |
| `cli.py`, `__main__.py` | `python3 -m apfs …` front end: emit a forged block, or inspect an image |
| `test_apfs.py` | `unittest` suite (self-consistency, hand vectors, checkpoint-map, btree, CLI, gold fixture) |

(`../run_checks.sh` runs the validator, both test suites, and the gold check in one go — suitable for CI; the gold check is skipped automatically off macOS.)

## Requirements

Python **3.11+**, standard library only. No third-party packages, no network.

## Usage

```python
from apfs import build_nx_superblock, verify_object, apply_checksum

# Forge a container superblock that points volume-open at chosen volume oids:
sb = build_nx_superblock(block_size=0x1000, block_count=0x4000, fs_oids=(0x402,))
assert verify_object(sb)          # passes iBoot's integrity check (modulo the
                                  # correctness-boundary note above)

# Forge a checksum over any tampered object body:
tampered = bytearray(sb); tampered[0x400] ^= 0xFF
reforged = apply_checksum(bytes(tampered))
assert verify_object(reforged)    # the R13.2 "integrity is forgeable" claim
```

Run the tests:

```sh
python3 -m unittest discover -s tools/apfs
```

## CLI

The package has `tools/` as its import root, so run it with `PYTHONPATH=tools`:

```sh
# emit forged, checksum-valid blocks (ready to dd onto a block in the R14 loop)
PYTHONPATH=tools python3 -m apfs superblock --block-count 0x4000 -o nxsb.bin
PYTHONPATH=tools python3 -m apfs checkpoint-map --mappings 2 -o cpm.bin
PYTHONPATH=tools python3 -m apfs btree --entry k=v --malform value-underflow -o node.bin

# inspect the objects in a file (or a dumped block) and verify each checksum
PYTHONPATH=tools python3 -m apfs inspect node.bin
```

`--malform` is one of `none`, `nkeys`, `value-underflow`, `key-oob`.

> The CLI only writes the file you pass to `-o` (or stdout). It never touches a
> device. Writing a block onto hardware is a separate, deliberate `dd` the
> operator runs — and the R14 **revert-first** rule (`FINDINGS.md:6302`) says to
> back up every block you overwrite first.

## Status / roadmap

- **Increment 1 ✓** Fletcher-64 (gold-proven) + `obj_phys_t` + `nx_superblock`.
- **Increment 2 ✓** `checkpoint_map_phys_t` + capacity idiom (R14.2); real Apple
  checkpoint maps verify and obey the capacity bound.
- **Increment 3 ✓** `btree_node_phys_t` + three malformation generators for the
  R14.3 attack shapes (over-count `btn_nkeys`, value-length underflow, key
  offset past node). Node header layout verified against real Apple btree nodes;
  each forgery is out of bounds by construction and keeps a valid Fletcher-64.
- **Increment 4 ✓** `python3 -m apfs` CLI (emit a forged block / inspect an
  image) and `run_checks.sh` (validator + both suites + gold check), CI-ready.

All four increments complete. What this toolkit does NOT do, by design: audit
iBoot (that is the human R14.3 task of reading `0x14ae8..0x1526c` and checking
each on-disk offset for the capacity idiom), or touch any device.

The capacity-check idiom encoded in increment 2 (`is_within_capacity`) is the
thing the btree walker at `0x14ae8` is being audited for the *absence* of; the
generators here produce the exact inputs that an unchecked walker mis-handles.

### Convention caveat for btree nodes

The node HEADER offsets (`btn_nkeys@0x24`, `btn_table_space@0x28`, data at
`0x38`) are verified against real Apple nodes and the repo. The exact ORIGIN of
the TOC key/value offsets (relative to the key-area start / value-area end)
follows the Apple APFS reference; iBoot's TOC walk at `0x14ae8` is R14.3's open
audit task and is not yet confirmed. The malformation generators do not depend
on that convention — they exceed the node bounds unconditionally.
