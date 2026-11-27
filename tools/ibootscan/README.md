# ibootscan — R14.3 APFS btree-walker audit aid

A static-analysis helper for the **R14.3** task in `FINDINGS.md` (lines
6425-6467): sweep iBoot's APFS btree/node handling for on-disk-derived counts
and offsets whose use is **not** guarded by the R14.2 capacity-check idiom. That
missing check is the documented bug signature (`FINDINGS.md:6461`).

It turns a manual sweep — the "STILL UNSWEPT" candidate list at
`FINDINGS.md:6418-6419` — into a repeatable, testable script.

## The idiom it hunts

`FINDINGS.md:6403-6412` records this author's bounds-check pattern for an on-disk
count:

```
capacity = (buffer_size - header_size) / element_size   ; sub  then udiv
if (capacity < on_disk_count) -> fail                   ; cmp  then b.hs/b.lo
```

The tool finds every occurrence of that guard, finds every place an
attacker-controlled (on-disk-loaded) value is used as a memory index or address
scale, and grades each index site:

| Verdict | Meaning |
| :--- | :--- |
| `UNGUARDED` | On-disk-derived index with **no** capacity guard earlier in the range. The bug signature — audit first. |
| `GUARDED?` | A capacity guard precedes the site. Likely safe, but **confirm by hand** that the guard's count actually bounds *this* index — the `?` is deliberate. |

## What it is NOT

It is a **triage aid, not a prover**. It reasons over the text of a disassembly
listing with a deliberately small, intraprocedural taint model. It does not model
calls, aliasing, memory, or reachability, and it does not prove exploitability.
`UNGUARDED` means "worth a human's time," not "confirmed vulnerability." Treat
its output as a worklist for manual confirmation against the real code.

Its taint model assumes **the scanned function parses an on-disk structure**
(every load is attacker-controlled). Point it at the specific APFS functions
(e.g. `0x14ae8..0x1526c`), not arbitrary code, or it will over-report.

## Zero dependencies, bring your own binary

Pure stdlib, Python 3.11+. It **decodes no raw bytes** and **ships no Apple
code** — it consumes a disassembly listing *you* produce from *your own*
extracted iBoot, with whatever disassembler you have. Parsed dialects:
`llvm-objdump`, `otool -tV`, GNU `objdump`, radare2, and the `0xADDR  mnemonic
ops` notation used inside `FINDINGS.md`.

## Usage

`tools/` is the import root, so run with `PYTHONPATH=tools`:

A decrypted iBoot is a **raw ARM64 image, not a Mach-O**, so `otool`/`nm` and
Apple's `llvm-objdump` (which has no raw-binary mode) do not apply. Disassemble
it as raw aarch64 **at base 0**, so the printed addresses equal the file offsets
this audit uses (`FINDINGS.md` cites `0x14ae8` etc. as file offsets):

```sh
# 1. disassemble your extracted, DECRYPTED iBoot as raw aarch64 at base 0.
#    radare2 (brew install radare2):
r2 -a arm -b 64 -qc 's 0x14ae8; pd 600' iBoot.dec > iboot.lst
#    ...or GNU binutils (brew install binutils); note the g-prefix on macOS:
gobjdump -D -b binary -maarch64 iBoot.dec > iboot.lst

# 2. scan the btree-walker range from FINDINGS.md:6449-6450
PYTHONPATH=tools python3 -m ibootscan scan iboot.lst --lo 0x14ae8 --hi 0x1526c

# just list the capacity guards it recognises (e.g. over the checkpoint-map
# validator, to sanity-check against the known-safe site at 0x144fc)
PYTHONPATH=tools python3 -m ibootscan guards iboot.lst --lo 0x14418 --hi 0x14790
```

(If you ever point it at a Mach-O instead, any disassembler's output works —
`otool -tV`, `objdump -d`, radare2 — the parser accepts them all. The raw-binary
note above is specific to iBoot/LLB images.)

`scan` exits **2** when any `UNGUARDED` site is found (0 otherwise), so it can
gate a script or CI step.

## Modules

| File | Contents |
| :--- | :--- |
| `asm.py` | tolerant ARM64 listing parser → `Insn(addr, mnemonic, ops)` |
| `idiom.py` | R14.2 capacity-guard detector (register dataflow) |
| `taint.py` | intraprocedural taint → on-disk-derived index sites |
| `scan.py` | pairs guards with sites → graded `Report` |
| `cli.py`, `__main__.py` | `python3 -m ibootscan {scan,guards}` |
| `test_ibootscan.py` | `unittest`: parser dialects, idiom gold, taint, scan |

## Correctness

Grounded on the one site the researcher verified by hand:

- **Idiom gold** — the checkpoint-map validator at `0x144c8-0x144e0`
  (`FINDINGS.md:6391-6401`), proven SAFE. The detector must classify it as a
  guard with `element_size=0x28`, `header=0x28`, `count=w8`, `b.hs`; a mutant
  with the idiom deleted must yield **zero** guards (the bug signature).
- **Parser** is checked against all five listing dialects **and** real
  `otool -tV` output.
- **Scan** is checked against a synthetic btree-toc walk in the shape
  `FINDINGS.md:6462-6467` describes, guarded and mutated.

```sh
PYTHONPATH=tools python3 -m unittest discover -s tools/ibootscan
```

## Scope

Software-only, offline, no device. Contains no Apple binaries or device
identifiers. It reads a text listing and emits a worklist; it does not sign,
verify, patch, execute, or touch hardware.
