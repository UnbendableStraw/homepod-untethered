# WHERE WE ARE — start of 2026-11-28
*Written at the end of the 11-27/28 night session. Read this first, then R118.*

## The one thing that changed everything last night

`dst = bufEnd − compressedLength` is what makes the write underflow. The inflate
wrapper at `0xdcdd08` **rejects exactly that geometry** — input below output with
its tail inside the output — returning `0x3e8` before parsing any stream
(`0xdcdd5c`–`0xdcdd70`). So:

```
a successful inflate needs  L <= allocSize
the overflow write needs    L >  allocSize
=> MUTUALLY EXCLUSIVE
=> a run that WRITES can never return status 0
=> EXACTLY ONE overflow write per read() call, always the last run executed
```

No payload construction changes this. That retires the N-writes-per-boot model
(R98, R99.1, R104.3, their SS62) and the 256/N kslide amortisation (R111.2).

## Steps 1–3 still stand; step 4 is where we are

Root code exec on unassisted cold boot is unchanged (`hdik` at
`/usr/libexec/UserEventAgent` + our UDIF at `/(System)`). The write primitive
works and is reproducible. What we do not have is a way to take MORE THAN ONE
write per read() call.

## What is solid now (measured, not inferred)

* **CD at element+0x1c** — four confirmations, twice directly from registers
  (`x12 − x10 = 28`) at two different heap addresses under two different slides.
* **V's lower neighbour is reproducibly a 1508-byte code-signing blob** under the
  reach-1671 geometry — `x11 = 0x5e4` in both boots. First repeatable live forge
  target the project has had. (R110's "free in 6 of 7" was the old geometry.)
* **Both CD gates pass on our own bytes** — `CD+0x04` length reads BE as our
  smalloc magic byte-swapped (1902338378) against a ~940M scatterOffset, 2×
  margin. The kernel validates our forgery against itself and walks into
  `ldr w4,[x17]`.
* **`far = CD_base + scatterOffset`, exact, twice.** scatterOffset is a full 32
  bits of ours, so the read is steerable across ~4 GB above CD_base; the handler
  distinguishes where it lands (X: "Kernel data abort"; Y: "Unexpected fault in
  kernel static region", same instruction, same ESR).
* **kslide ≈ 8 bits**, moves every boot, always a 2 MB multiple.
* **A ramdisk NVRAM write does not survive a cold boot** — 2 for 2. The NVRAM
  groom cannot be part of an untether, which by definition survives a dirty power
  loss. Their SS64.3 plist-teardown route needs no persistence and is the only
  grooming primitive left.
* **The free-list cookie is stamped only in `free_to_zone`**, and the cached free
  path skips it. So elements below V need only be OFF THE FREELIST, not live
  (their SS66, the half that survives).

## Next, in priority order

1. **COUNT THE read() CALLS.** How many separate `read()` calls does one boot make
   against our image, and how many can be made to end on a poisoned run? Known
   plural sites: the GPT header probe's two 512-byte reads at sectors 0 and 1
   (R97), the partition-entry array read, and each other partition scheme's probe
   (`IOFDiskPartitionScheme`, `IOApplePartitionScheme`). **Offline-answerable.**
   This replaces "N runs per boot" as the quantity that sets the boot budget.
2. **Does a short transfer make the prober retry?** `x22` is untouched on the stop
   path and `x28` (sectors actually transferred) reaches the caller's out-param at
   `0xdcb91c`, so the caller sees the short count directly. If a short read makes
   the prober re-read, one call may yield more than one write. Offline.
3. **Is `kalloc.1664` cached?** (their SS64.5) Gating for the plist groom. The
   flag at `zone->flags+0x110` is a runtime value, so this needs hardware — but
   design the discriminator carefully: their SS66 attempt was a null instrument
   because it read the regime off "run 2 advances", which can never happen.
4. Only then: aim. The forge path is the live one; R110.4's advice to pause the
   vptr lottery still stands.

## Rules added last night (all in JOB-PREFLIGHT)

* **R112** — every run in a multi-run recipe must be built by `make_stream()`,
  which asserts length and round-trip. A constraint in prose is not a constraint.
* **R116** — check a discriminator is REPORTABLE by the channel we will read, not
  merely present in memory. An instrument validated only on negatives is not
  validated: always run a positive control.
* **R117** — `pod-sh` passes NO arguments (`pod_ssh 'sh -s' < file`). One mode per
  file; never a `case "$1"` dispatch in a pod script.
* **R118** — when the question is "why did this call fail", DISASSEMBLE THE
  CALLEE. Budget the attack in read() calls, never in runs.

## Tools
`route2/zstream.py` (exact-length valid zlib, content at the front — still needed
for BENIGN runs), `route2/decodeX.py` (two-recipe paniclog decoder, tests each
half natively AND byte-swapped, refuses to name a run from non-identifying
fields), `route2/lintjob.sh` (comment-aware pod-script lint),
`route2/nvpcheck.sh`, `route2/mkrecipeX.py`, `route2/mkrecipeY.py`,
`route2/genswapX.py` / `genswapY.py` (derive every gate constant from the built
image).

## Pod state
In the SSH ramdisk, queue empty, NVRAM at its 10 baseline variables. Recipe Y is
still armed at `/(System)`, so a cold boot will crash until it is re-armed or the
volume restored.
