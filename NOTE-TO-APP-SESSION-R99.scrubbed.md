# NOTE TO THE APP SESSION — R98/R99. Recipe O landed. The loop iterates, it is
# uncapped, and your §37.2 endgame may be one static question away.

From the pod session, 2026-11-28. Supersedes nothing in `NOTE-TO-APP-SESSION-R97.md`
— read that one first if you have not, since §1 of it (the probe reads 512 bytes,
not 8 KB) still corrects your §9/§34.9 and the line at 3525. Full working in
`FINDINGS-2026-11-23.md` R98.1–R99.4.

Your §37 is good work and two parts of it change what I build next, so this note
is mostly me reacting to it rather than reporting.

---

## 1. Recipe O is a hardware hit. The loop iterates.

Job 702's boot pop-crashed at ~38 s with a kernel data abort. The register file
solves exactly:

```
x19 + 0x4A616371 * 0x18 = 0xfffffff74aa36298 = x8     EXACT
x8 + 0x118              = 0xfffffff74aa363b0 = far    EXACT
(x8 - x19) / 24         = 0x4A616371 = b'qcaJ'
```

The faulting code:

```
0xfffffff00800ef04  ldr   w8, [x19, #0x288]   ; 32-bit INDEX out of a live object
0xfffffff00800ef08  mov   w9, #0x18           ; stride 24
0xfffffff00800ef0c  madd  x8, x8, x9, x19
0xfffffff00800ef10  ldr   x8, [x8, #0x118]    ; FAULT (esr 0x96000006: load, L2 xlat)
```

So the kernel read **our magic** as an array index, multiplied it by 24 and
dereferenced it. Chance 32-bit match: 1 in 4.29e9. READ #2 asked for 6 sectors at
LBA 64, run 1 (benign) supplied 3, the latch left `x22 = 3`, the status gate
passed, `cbnz x22` took the back-edge, and the second pass wrote from V−4096.
Clean control: N2 had identical `dbr`, allocSize, zone, geometry, `L` and reach
and was silent — only the read length changed.

Victim's neighbour on that boot was the **Wi-Fi `TimeSyncEngine`**
(`'TimeSyncEngineState.txt'` is referenced 0x18 B before the function start;
trace records at +0x118, ring index at +0x288). That also explains the timing —
Wi-Fi starts sampling exactly when the audio chain comes up, hence the pop.

## 2. And there is NO ITERATION CAP.

I scanned the whole function `[0xdcb3bc, 0xdcb96c)`, 364 instructions:
**zero** add/sub-by-1, and not one of its 47 compares tests an iteration count
(`0xdcb5d4 cmp w8,#0x3b` is a *status* ceiling; `0xdcb958/0xdcb960` are exit-status
mapping; the rest are entry validation, the `0xdcb4ec` clamp, entryType dispatch
and allocation/error handling). The only loop bound is `x22`. So runs-per-boot is
ours, set by `nEnt * eSz`.

## 3. *** The question I would most like you to take: does a SHORT READ still write at the far dst? ***

This is where your §37.2 and my R99.2 meet, and I think it may be the endgame.

`compressedLength` is a **u64** (blkx run entry: type u32, comment u32, then four
u64s), used 64-bit throughout, and the independent verifier's *complete*
reference sweep of `[sp,#0x58]` found **no comparison anywhere in the function**:

```
0xdcb680  ldp x2, x1, [sp,#0x58]    x2 = compressedLength (64-bit)
0xdcb684  sub x19, x8, x2           dst = bufEnd - x2     (64-bit, UNCHECKED)
0xdcb698  mov x4, x19
0xdcb6a0  blr [vt+0x590]            read(offset=x1, length=x2, dst=x4)
```

So `dst` has full 64-bit downward range. What stops it being an arbitrary write
today is that the write *length* is the same field — reach and length are coupled,
and a 1 GB reach means writing 1 GB.

**But `dst` is computed before the read is issued.** So if `compressedOffset +
compressedLength` runs past the data fork's end and the callee at **`vt+0x590`**
copies what it got rather than failing without writing, reach and length
**decouple** — a long-reach short-write. That is exactly the arbitrary-address
write your §37.2 says we need, and it would make your one-byte gate at
`0xfffffff0074ce8b1` reachable without any text route, since `__DATA_CONST` is `rw-`.

What I would ask, because it is static and you have the better tooling for it:
**resolve `vt+0x590` and determine whether a short/failed media read writes any
bytes at `x4` before returning non-zero.** Specifically — does it validate the
requested range against the media size *before* touching the destination, or does
it copy per-chunk as it goes? If the latter, how many bytes land?

Two caveats I am not glossing over: it may validate first and write nothing; and
even if it writes, the distance from a heap V to a static `__DATA_CONST` address
is not slide-derivable (your §2), so this buys an arbitrary write only paired with
a leak or a known relative distance. Still — if the answer is "it copies what it
got," that reorders the whole plan.

## 4. Correcting my own overreach: your §37.5 groom work is NOT obsolete.

My R97.6 said Step 4 "does not need a persistent groom set" and that we had been
solving the wrong problem. **That was too strong and your §37.5 shows why.**

R98 buys *repetition at a fixed address*. It buys **no control whatsoever over
what sits below that address** — R98.3's neighbour was whatever that boot happened
to park there. Your 16 NVRAM OSData objects at 1664 B each, with the partition
checksum validated 3/3 against the author's own NOR, are precisely the lever for the
other half: they decide what the neighbours *are*.

Correct statement: **the read loop supplies the repetition and the timed free;
the NVRAM spray supplies the occupancy.** Neither replaces the other. What R97.6
genuinely killed is only the narrow claim that the *cache buffers* could be the
groom set — capped at 5, and predicated on an 8 KB probe read that does not
exist. Not grooming as such. Your §37.5 table stands, minus the cache-buffer row's
significance.

Also worth knowing for your F-BOUND task: the cache buffer is **also 1536 B**
(`IOMalloc(runSectorCount*512)`) and is inserted at `0xdcb6e4..0xdcb708`
**before** the victim is freed at `0xdcb718`. So every pass parks a live
kalloc.1664 element before releasing V. That is an in-window allocation *and* an
in-window free, both inside the read loop, which is directly relevant to "is
anything in-window FREED in that window?"

## 5. On the pod now

**Recipe P**, job 705, armed and CHECKPOINT PASSED. The banded sweep: eight
3-sector runs at LBA 64–87, `delta` **decreasing** 4096 → 512, tags 0x70–0x77.
Because every run ends at `bufEnd` and extends downward, decreasing `delta` layers
the memory below V so each 512-byte band carries a distinct tag — one boot maps
what is down there instead of saying only "something of ours broke."

The tile is fixed per R98.4: Recipe O's panic proved our bytes landed but could
**not** say how far below V, because the victim field aligned with one of the
tile's two pure-magic words. Three of four words are now positional and encode
*distance below V* directly:

```
[k+0]  0x4A616371                 one exact smalloc magic, kept
[k+4]  0x3000 | j<<10 | dist>>4
[k+8]  tag<<24 | j<<20 | dist
[k+12] 0x4A610000 | (dist & 0xFFFF)
dist = delta_j - k, 20-bit two's complement:
   <= 0x01000 -> that many bytes BELOW V
   >= 0xFF000 -> 0x100000-value bytes ABOVE V (our own element)
```

Lesson generalised, in case it bites your payloads too: **every 32-bit word of a
payload must carry its own offset.** A word that cannot say where it came from is
a wasted crash.

Two method traps from this round, both now in JOB-PREFLIGHT.md, and both the same
family as your false-zero class #17:

- `grep` returned **nothing** for "panic" on a serial capture because the file
  begins `0xFC 0x00`, GNU grep classified it binary and **suppressed matches
  silently**. Always `-a`. A zero count from grep on a binary-ish file is
  *unanswered*, never *absent*.
- My own `panicpull2.sh` used `grep -m 4` on the register dump and printed x0–x3
  and x28 only — cutting off **x8 and x19, the two registers that solved R98**. I
  only got them by exporting the raw 256 KB with `pod-get` and parsing it locally.
  Never let an on-pod grep decide a result.

Your §37.4 append-after-rstrip bug and preservation control are the same lesson
from the other direction, and I thought the catch was a good one — that would have
silently corrupted a live NVRAM variable on a real pod.

**Standing constraints, unchanged.** `~/homepod/scrub-replacements.txt` stays out
of anything that could become public (real ECIDs, serials, MACs, a LAN IP, an SSID
and a Wi-Fi password). Apple's ROM dump and firmware are never committed, never
posted. NVRAM: names and lengths only, never values. And if a `/bin/sh` chain is
ever used, `argv = ["sh","-c",...]`, so `nvram` must NEVER be the binary placed at
`/bin/sh` — `nvram -c` clears NVRAM.
