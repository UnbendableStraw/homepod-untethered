# What to try when the pod is back

Living list. Ordered by risk to the pod, lowest first. Last updated 2026-11-25.
Everything above the "needs the bench" line can be done with the pod in boot ROM
DFU, upside down, with a Kasa cycle to recover.

Canonical gaster order, always: **`pwn` -> `gaster-reset` -> `send`**.
`rom-peek`/`rom-poke`/`rom-call` now refuse to run if the payload is dead, so a
clobbered session can no longer produce a meaningless result.

---

## Tier 0 — reads only, cannot hurt anything

### 0.1 (ANSWERED 2026-11-25, no pod needed) Boot source is 2 -> even
My mistake: I listed this as unmeasured. It was already in the log
(job 432): `[0x2_0E029000] = 0x01380203`, selector **2**, BORD 0x38.
Selector 2 gives `w20 = 0`, handle flags `0xb`, bit 1 set, so on this board as
strapped the ROM hard-fails at `0x1000078b4` before it ever looks at CPFM.
**CPFM 00 alone would not give unsigned boot from flash.** It would also need
selector 3: GPIO 6/6 (flat 0x36) high during the ROM's 100 us strap sample,
which keeps NAND `read_llb` as the boot device and sets `flag2 = 1`.
Nothing to do here unless a CPFM route ever appears; then see B.4.

### 0.2 (DONE 11-25, job 501) Dump the whole chipid block `0x2_0E02A000` .. `0x2_0E02A2FF`
Aligned bulk read via `rom-call` on the ROM's own accessors (direct MMIO reads
are width/alignment sensitive and will fault). We have only ever looked at five
offsets out of a 768-byte register file. Map it.

### 0.3 (DONE 11-25) Confirm the production-mode lock at `0x2_0E02A004`
We measured bit 31 clear in DFU. Re-confirm, and check whether any *other* bit
in `+0x004` looks like a write-enable.

### 0.4 (WITHDRAWN) BMA282 confirmation test
Wrong premise. The Nov 23 hardware work already showed stage 2 reads the
accelerometer over I2C and asks the top-panel MCU to reset into DFU. GPIO 4/0
and 4/1 are most likely that MCU's force-DFU lines.

---

## Tier 1 — writes that a power cycle undoes

### 1.1 (DONE 11-25: writes ignored) Try clearing bit 1 at the **raw** aperture `0x2_0E02A200`
**Never attempted.** We assumed `+0x200` was read-only and only ever wrote
`+0x000`. The ROM has `chipid_get_raw_production_mode`/`_raw_secure_mode`
reading `+0x200`, so the aperture exists; nobody has tested whether it is
writable. Cheap, and if it works it is the whole ballgame.

### 1.2 (DONE 11-25: clear-only) Is `+0x000` clear-only or read/write?
Demote 03 -> 02 with `chipid_clear_production_mode` (`rom-call 0x10000a030`),
then try to **set bit 0 back to 1** with the store gadget.

* Comes back -> the register is R/W and bit 1 has its own dedicated interlock.
* Does not -> the register is one-way-clear, and bit 1 needs something else
  entirely.

Either answer narrows the problem, and it costs one power cycle.

### 1.3 Re-measure CPFM after a demote using the registers, never the banner
The DFU serial descriptor is built at enumeration and will keep saying
`CPFM:03` after a live demote. It lied to us once already.

---

## Tier 2 — touches NVRAM or the boot partition

### 2.1 The empty-SET IM4R cold-boot test
Write the 12 bytes `A1 0A 30 08 16 04 'IM4R' 31 00` into the LLB on `asp0n2`
and cold boot. Settles whether the uninitialised-stack BNCN lookup at
`0x100012150`/`0x100012184` is live on the flash path. Deferred since we found
it; still unanswered.

Before touching NVRAM: **`ls` the recover path's file list first.** Run 1 died
on a missing `/boot/boot/sep-firmware` and an `ls` would have predicted it.

### 2.2 Re-bank the 13.4.8 and 18.3 blobs against a known generator
Needs a kernelcache patch clearing `p.Bits.KernelOnly` on
`com.apple.System.boot-nonce` and `com.apple.System.sep.art`, plus a change to
the app's ticket vault so it sets the generator before fetching. Prerequisite
for anything Newport-shaped.

---

## Needs the bench, not just the pod

### B.1 / B.2 (WITHDRAWN) mic-board photos and DFU switch
Not needed. "Restart into DFU" already does it in software (six bytes to the
MCU at I2C3 0x55), and the external I2C jig from the Nov 24 notes covers a hung
pod.

### B.3 If glitching is ever tried: the target is `0x10000781c`, not the fuse latch
Fault simulation (findings log, 2026-11-25 afternoon) shows a single skipped
`cbnz` at `0x10000781c` makes the ROM accept an arbitrary unsigned image, with
CPFM and the strap irrelevant. Develop it in plain DFU first (no checkm8): send
an unsigned image, trigger off the end of the USB transfer, sweep delay. Needs
a crowbar on the A8 core rail (inductor column between PMIC `338S00100-AZ` and
the A8 on `820-00960-04`) and a scope. Cold-boot use would need a fitted
glitcher, so this is a hardware route.

### B.4 Find GPIO 6/6 (flat 0x36) on the board
The selector bit 0 strap. Internal pull-down during the sample; the pad reverts
to its normal function afterwards, so a permanent hard pull-up may break
whatever that signal does. Only worth chasing together with a CPFM route.

---

### R2.0 (DONE 11-25 16:17, pod runs 13.4.8) Build and restore 13.4.8 with `multipod/makeipsw13/makeipsw13.sh`
Untested draft. Run it on the Mac with the 17M61 OTA, the Apple TV 13.4.8 IPSW
as donor and `firmware_keys_17M61.zip`. Send me the log from the first failure;
the README lists where I expect it. Needed before R2.1.

### R2.1 Route 2 gate: does an edited 13.4.8 system volume boot and run our daemon?
On a working pod restored to 13.4.8, from the SSH ramdisk: mount the system
volume read-write, add one LaunchDaemon plist that runs a shipped binary with a
visible side effect (for example `/usr/sbin/nvram some-test-var=1`), cold boot,
read the variable back. Note how the root snapshot is selected and whether it
has to be renamed first. Everything in route 2 depends on this.

### R2.3 racoon on a real pod: four runs that settle the unknowns
On 13.4.8 with serial console and crash logs, run racoon with `-f` on the
configs in `multipod/route2/` (unpack `racoon-repro.tgz` and `racoon-d1.tgz`):
1. `R2-sainfo-from-uninit.conf`, 10 times: the faulting address gives the stale
   slot value; the image list gives the slide range.
2. `R2c-steer-uninit-pointer.conf`: fault address should be `0x13344112f`.
   Confirms the parser is reached and the pointer is ours.
3. `t_genlist.conf`, 20 times: is the heap pointer's low part repeatable?
4. `t_compose.conf`: allocator abort message, or survival.

### R2.2 Does a dead-SEP board on 13.4.8 reach launchd?
dead-sep-pod already has the 5540 loaders. Needs the 13.4.8 kernel and system volume
installed; watch UART for launchd. Decides whether route 2 can ever help the
boards that most need it.

### P.1 Decrypt the prototype loaders on a pod
`~/ProtoPod/HomePod_rdisk3.img` (LLB) and `rdisk2.img` (iBoot), iBoot-4076.30.43.
`gaster decrypt` on any b238a pod. Check the build type string and what reads
the `faus` manifest property. Tooling value only.

---

## Not pod work, but still owed

* `./scripts/build-app.sh` — the four UI-side edits from the agents are still
  uncompiled.
* `swift build` for the Nicotine `ReleaseIBoot.swift` fix.
* The tree is still uncommitted, deliberately, for you.

---

## Closed — do not redo these

* **`chipid_clear_secure_mode` does not exist.** One writer to CPFM in the
  whole ROM (`0x10000a030`, bit 0 only) plus the lock. Confirmed by exhaustive
  search, not by sampling.
* **There is no pad, resistor or trace on `820-00960-04` that demotes the SoC.**
  CPFM bit 1 is in the effective shadow inside the A8 die, loaded from on-die
  fuses at reset.
* **The RSA modulus overflow is unreachable.** Real bug, full EL3 PC control in
  isolation, but emulation of the genuine chain proves the ROM verifies cert[0]
  against its built-in root *before* importing any modulus. See the findings log.
* **CPFM:02 does not break signed boot.** It requires an EPRO=0 ticket. Our
  job-453 reading was wrong.
* **IM4R on the USB path** — closed, BNCN is ignored there.
* **The PSoC is the touch controller**, nothing to do with DFU.

## R2.1 update, 2026-11-25 16:45
- The ramdisk's `reboot` does NOT reset the SoC on this pod: job 513 ended at "AppleSEPManager: Received Paging off
  notification" with the ramdisk kernel still running (amp-controller spam, USB mux down, no iBoot banner for 5 min).
  The earlier "edit stopped the boot" reading was wrong: 13.4.8 was never given the chance to boot.
- Working exit from DFU to a normal boot with no hands on the pod (job 514): pwn, gaster-reset, send sshramdisk
  iBSS, send iBEC, `cmd reboot` from recovery. Pod was back as audioOS (pid 0x12B0) within 45 s.
- 13.4.8 BOOTS with the root snapshot renamed to `orig-fs`, the extra LaunchDaemon plist and the marker in place.
- Still unread: NVRAM `r2-gate`. Job 515 (sshrd + gate-check.sh) is queued, waiting for boot ROM DFU.
- To exit the ramdisk afterwards: power cycle (or try `halt`/a ramdisk without `wdt=-1`; untested).

## R2.1 RESULT, 2026-11-25 16:55: gate A is CLOSED (launchd only runs cached system services)
- Job 515: after ~3 min of audioOS 13.4.8 uptime, NVRAM has no `r2-gate`. Snapshot is still `orig-fs`, plist and marker intact.
- Why (static, launchd 1738.140.1 from 17M61): byte `0x10004e8a1` = "kern.bootargs contains `rd=md0`" (set at
  `0x100031f04`-`0x100031f1c`). `0x10000fc88` returns (byte == 0) = "system services must be in cache". On a normal
  boot the byte is 0, so LaunchDaemons come only from `mrm.plist` (183 jobs, 40 start at boot), and a missing or
  unparsable cache is fatal ("No service cache" -> crash at `0x10000fc54`). DO NOT delete/rename mrm.plist on a pod
  you want to boot.
- The cache is validated by `/usr/libexec/launchd_cache_loader`: detached code signature `mrm.plist.sig`, cdhash
  checked against the trust cache through AMFI. Job definitions (ProgramArguments etc.) come from the cache, so
  editing the on-disk plists does nothing either.
- Not separately excluded: an NVRAM write lost by the power cut. The launchd logic above is enough on its own.
- Still true and useful: 13.4.8 boots with the root snapshot renamed (job 514), so unsigned DATA files on the
  system volume are ours to change.
- New R2.1b: entry must be a CACHED boot-time job reading a file we can change. Candidates to audit (all start at
  boot, root first): configd, UserEventAgent-System (plugin/plist dirs), wifid, lockdownd, locationd, powerd, logd,
  syslogd (/etc/asl.conf, /etc/asl/*), keybagd, containermanagerd, CrashHousekeeping, DumpPanic. racoon is cached
  but RunAtLoad=false, socket `/var/run/vpncontrol.sock`: needs something to connect.

## R2.1b audit, first pass, 2026-11-25 17:30 (offline, from the 17M61 root)
- syslogd: `/etc/asl.conf` + `/etc/asl/*` are plain text on the system volume. They can make root syslogd create
  and append log files at paths we name on the Data volume (`file`/`>` rules, `format=` under our control). That is
  a file-write primitive into a volume the ramdisk cannot mount, not code execution. Not tested on the pod.
- No shell, no interpreter. `/etc/fstab` is a stale hfs file. `/etc/ppp` is empty. pppd and racoon are present.
- SQLite in the dyld shared cache is 3.28.0 (source id 2019-04-15, Apple build), with FTS3/4/5, RTREE, JSON1,
  DBSTAT, SESSION compiled in. Apple's tvOS 14.0 notes list SQLite fixes (CVE-2020-13434, -13435, -13630, -13631,
  -15358, -9849, -9991) that this 13.4.8 build therefore predates. Whether each one is actually reachable in
  Apple's 3.28.0 build is NOT verified.
- SQLite databases that sit on the system volume (so we can replace them from the ramdisk):
  CoreLocation `factory_minimum.db`, `Support/factory.db`, `Support/timezone.db` (rtree tables);
  Security `Certificates.bundle/valid.sqlite3`; CoreAnalytics `marketMap.sqlite` (rtree); AppSupport `CityInfo.db`;
  `/usr/libexec/topicsmap.db`; WebKit `HTTPSUpgradeList.db`; CallKit template; HID `cblight.sqlite`.
- locationd (root, RunAtLoad, KeepAlive, in the launchd cache) has the path
  `/System/Library/Frameworks/CoreLocation.framework/Support/` and store types `factory`, `factory_minimum`,
  `timezone`; it runs `SELECT * FROM DatabaseIdentifier;` and `PRAGMA table_info(` through its CLSqliteDatabase
  class. It imports no `sqlite3_db_config` and no `sqlite3_set_authorizer`, so nothing restricts what a schema in
  one of those files may do. NOT verified: that these three files are opened at boot on a HomePod, and with which
  statements.
- Open questions before this is a route: (1) which daemon opens which file at boot, (2) a way to see the result on
  the live OS (we have no log or crash-report channel yet; the kernel is silent on serial), (3) a usable SQLite
  defect in Apple's build. configd not looked at yet.

## R2.1c next steps, 2026-11-25 17:25 (bluetoothd / SQLite route)
- R2.4 OBSERVABILITY FIRST (blocking everything else): with the pod booted normally, try
  `pymobiledevice3 usbmux list` then `pymobiledevice3 syslog live` (pair with `pymobiledevice3 lockdown pair` if asked).
  Fallback: runner `info` action (ideviceinfo), available after the runner's next restart.
  Without a log channel every test below is blind - the Data volume is NOT readable from the ramdisk.
- R2.5 PROBE (ready to run, non-destructive, no crash): plant `route2/pincode_defaults.probe.db` over
  `/Library/Application Support/BTServer/pincode_defaults.db` on disk1s1, boot, and look for bluetoothd logging an
  SQLite error ("no such table: makes"). That answers whether the file is read at boot, and when.
  Job shape: `wait romdfu` / `sshrd` / `pod-sh multipod/route2/sysvol-mount.sh` /
  `pod-put multipod/route2/pincode_defaults.probe.db "/mnt1/Library/Application Support/BTServer/pincode_defaults.db"` /
  `pod-sh multipod/route2/sysvol-finish.sh`. Restore with `pincode_defaults.orig.db` the same way.
- R2.6 If the probe fires: build the two-statement hijack (statement A stores the tokenizer pointer, statement B
  connects an fts3 table with that name). Needs a fake sqlite3_tokenizer_module at a known address - the 1-arg leak
  plus SQL arithmetic is the only address source so far.
- R2.7 If the probe does NOT fire: next candidates in the same style, all on the System volume -
  locationd (root, RunAtLoad, KeepAlive) with `CoreLocation.framework/Support/{factory,factory_minimum,timezone}.db`;
  trustd (_securityd, on demand) with `Security/Certificates.bundle/valid.sqlite3`;
  TTS `MacinTalk.speechbundle/LexerResources/TuplesEng` and VoiceResources `pron_dict.db`/`phon_map.db` (SQLite with no
  extension - found by header scan, 18 SQLite files on the System volume in total).
- Do NOT delete or rename mrm.plist. Do NOT mount the Data volume from the ramdisk.
- R2.5b PLAN B PROBE (if there is no log channel): `route2/pincode_defaults.hang.db` (sha256 3dd5b028...604) is the
  stock file with `makes` rewritten as a view over an endless recursive CTE, so every one of bluetoothd's three
  statement shapes wedges instead of returning. Verified locally against SQLite 3.28.0: shapes 1 and 3 both spin
  forever, the other 227 device rows and the rest of the schema are untouched. Effect is behavioural and visible
  without logs: bluetoothd never finishes its query, so Bluetooth stays dead and the pod should not appear for
  Home-app setup. Fully reversible by re-planting `pincode_defaults.orig.db`.

## R3: the binary-substitution foothold, 2026-11-25 18:40 (THIS IS THE LIVE ROUTE)
Primitive proven: put any trust-cached Apple binary's bytes at a path the stock launchd cache launches at boot, and
it runs as root. Nothing integrity-protected is touched. See FINDINGS 2026-11-25 18:35 for the evidence.
- R3.1 Does the sandbox follow the HOST JOB or the BINARY? Substitute the same binary into a second host job and
  compare the denials. Decides whether a more permissive host job exists. (One boot.)
- R3.2 Pair with a binary that neither forks nor needs argv, and that parses a System-volume file we own:
  * syslogd + /etc/asl.conf and /etc/asl/* (ours already)
  * pppd + /etc/ppp/options (/private/etc/ppp is EMPTY - the whole file would be ours)
  * wifiFirmwareLoader + its firmware blobs on the System volume
- R3.3 Enumerate cached boot jobs by argv shape, so a substituted binary can be paired with useful arguments it
  already receives (we cannot change argv - the cache is protected).
- R3.4 Leftover on the pod right now: racoon's bytes are at /usr/libexec/CrashHousekeeping. Harmless (crash-log
  tidying is skipped). `subst-undo.sh` restores it from /usr/libexec/CrashHousekeeping.stock.
- R3.5 Still open on the cache itself: stock cache + renamed launchd_cache_loader (the isolating control we skipped),
  and whether neutering mrm.plist.sig changes anything. Low priority now that R3 does not need the cache.
- WITHDRAWN: racoon.conf parsing (D1) - iOS racoon is configured through SCPreferences on the Data volume, not that
  file. The 12 SQLite probes are also a closed negative: nothing reads those files at boot in setup mode.
- R4 WIFI FIRMWARE PATH (verified data path, now the lead): our bytes on the System volume reach the kernel's
  Broadcom driver at every boot. R4.1 read the driver's firmware-load code in the kernelcache offline before testing
  anything malformed. R4.2 the missing config file the loader stat()s each boot is a path we can create.
  R4.3 `/Library/Managed Preferences/mobile/com.apple.wifiFirmwareLoader.plist` is plantable and explicitly allowed
  by the loader's own sandbox - may redirect which blob is loaded (binary contains a `wifi-nvram-path` key).
  Restore with route2/wifi-restore.sh. Observability: the loader logs file sizes and the mapped buffer lengths.
- R4.4 READ the kernel's "normalize NVRAM" routine: error site 0xfffffff0080b59d8 in kernelcache.b238.macho
  (function ends 0xfffffff0080b5994). That is host-kernel code processing our nvram text with an explicit length.
  Easiest with a decompiler: carve AppleBCMWLANCore to a standalone Mach-O first (__PRELINK_INFO is binary, not a
  plist, so boundaries must come from it). Close the retained Hopper document on the Mac before reopening.
- R4.5 Do NOT expect crush.trx edits to work: BCMWLANFirmware4357_Hashstore + IOImageLoader verify firmware images.
  Check that properly (one boot with a single byte changed in crush.trx, backup is already on the pod) before
  building anything on it.

## R4 CLOSED 2026-11-26 — do not reopen without a new reason
- R4.4 DONE, negative. `normalizeNVRAM` (0xfffffff0080b5438) is a correct sanitizer. Write bounds are right, the
  LEN+2 buffer has deliberate slack, the output index can never pass it. It also DELETES any line keyed
  `macaddr`/`il0macaddr`/`nvramver`/`moduleid`/`nocrc`, so `nocrc=1` can never reach the firmware from our file.
  Only flaw is a 2-byte heap over-READ into the firmware buffer — no attacker control, wrong direction, useless.
- R4.5 DONE, negative by inspection — no boot needed, and the one-byte crush.trx test is no longer worth a boot.
  `prepareImageMap` (0xfffffff00808e500) range-checks all seven userspace size fields with both a floor and a
  ceiling before allocating, and demands structureInputSize==0x1c / structureOutputSize==0x58 exactly. The
  "imageSize is too small" string is a post-allocation assertion, not a trusted length. Needs
  `com.apple.wlan.userclient` to reach at all.
- R4.1/R4.2/R4.3 superseded by R5 below — the plist plant is unnecessary if the NVRAM override works.

## R5: DOES RETAIL iBOOT HONOUR THE `boot-args` NVRAM VARIABLE?  (next, and it is the important one)
Why this matters more than anything in R4: the project's goal is UNTETHERED unsigned boot. Tethered already works
(we boot our own iBSS/iBEC + ramdisk over checkm8 every session). The whole gap is persistence across a cold boot
with no host attached. If the NOR iBoot honours `boot-args` from NVRAM, a very large class of attacks opens up
untethered — including, at minimum, every boot-arg-gated debug path in the kernel.

We now have a perfect canary for it, found in R4: boot-arg `wlan.debug.enable=1` unlocks NVRAM variables
`wifi-fw-path` / `wifi-nvram-path`, and the kernel then loads the Wi-Fi nvram text from ANY path we name
(gate 0xfffffff00808cb50, reader 0xfffffff00808e134, `/options` = the NVRAM node). The effect is a NUMBER in the
log we have already proven is not redacted: `nvrambuffer len` == filesize + 16.

- R5.1 ONE JOB, ONE BOOT (`route2/bootargs-test.sh`): plant an alternate nvram text of a DISTINCT size, point
  `wifi-nvram-path` at it, set `boot-args=wlan.debug.enable=1`, snapshot-swap, read nvram back.
  Then one cold boot and read `nvrambuffer len` from the log:
    len 6416  -> boot-args ARE honoured. Huge. Go straight to AMFI/codesign boot-args next.
    len 6216  -> boot-args are ignored (our current 6200-byte file still in use). R5 dead, and so is every
                 boot-arg-gated idea; fall back to R3 (binary substitution) as the only untethered foothold.
    no line   -> inconclusive, the loader did not run; re-check the capture window before concluding anything.
  Padding is NUL bytes, which normalizeNVRAM skips in state 0 (`cmp #0x21; b.lo`), so the effective Wi-Fi config is
  byte-for-byte unchanged and only the size differs. Nothing about Wi-Fi should break either way.
- R5.2 The same job dumps the FULL `nvram -p`. Read it: which variables already exist tells us what the boot policy
  looks like and whether `boot-args` is already present/permitted.
- R5.3 If R5.1 is positive, the follow-ups in order: `cs_enforcement_disable=1`, `amfi_get_out_of_my_way=1`,
  `amfi=0x80`, `-v`. Any one of those landing is the end of the signed-userland problem.
- R5.4 Recovery: if a bad boot-args value stops the boot, clear it from recovery (`cmd setenv boot-args` empty then
  `cmd saveenv`) or from the ramdisk (`nvram -d boot-args`). Keep `boot-args` to one benign flag per test.
- R5.5 ProtoPod folder holds `dev_ibss.img4` / `dev_ibec.img4`. A dev-fused prototype boots unsigned firmware by
  design — worth knowing as a COMPARISON baseline for what a positive R5 looks like, not as the retail target.

## R5 PROVISIONAL (NOT closed) 2026-11-26 — see job 539 first. Retail iBoot *appears* to ignore NVRAM boot-args.
CONFOUND: job 538 wrote NVRAM from the ramdisk and read it back in the SAME session, which only proves the
in-memory proxy changed, not that it reached NOR. Job 539 dumps nvram from a fresh ramdisk to settle it. If the
variables are gone, redo the test by writing boot-args from the BOOTED OS (R3 foothold), which is the only path we
have actually shown persists (the r2-gate receipt).
`iBoot-5540.140.12` does not pass the NVRAM `boot-args` variable to the kernel. Proven: `bootargs is` EMPTY in all
7 boot sessions of bootarchive8.txt, nvrambuffer len never left 6216, no `updated NVRAM path` line, while the
ramdisk read both NVRAM variables straight back out of NOR. So R5.1 and R5.3 are closed and every boot-arg-gated
idea is dead untethered. Beware: `grep -c 6416` says 19 but all 19 are substrings of UUIDs, not buffer lengths.
- CLEANUP OWED: `route2/bootargs-undo.sh` clears wifi-nvram-path/wifi-fw-path and restores the empty boot-args
  from /mnt1/boot-args.stock. Harmless to leave (iBoot ignores them), but do it on the next ramdisk session so the
  pod is not carrying stray NVRAM. alt-nv.txt is inert and can stay.

## R6 (next): missing-path probes by privileged daemons — see FINDINGS 2026-11-26 03:40 for detail
- R6.1 BEST LEAD. mDNSResponder (root, 20 entitlements) dlopen()s WiFiAwareD2DPlugin every boot and fails only
  because `/System/Library/PrivateFrameworks/WiFiPeerToPeer.framework/WiFiPeerToPeer` is MISSING — on the System
  volume, which we can write. First step costs one boot: plant an invalid file there and see whether the dlopen
  error changes from "not found" to a signature rejection. That alone tells us which wall we are at.
  The big question it opens: does AMFI accept an Apple-signed dylib that is not in THIS build's trust cache?
  Check first whether WiFiPeerToPeer.framework exists in the IPSWs we hold (18.3, 26.0.1, AppleTV5,3 13.4.8).
- R6.2 Unredact the path wifiFirmwareLoader stat()s 173x per archive (from the binary's strings, not the log).
  It re-stats every ~10s forever, so there is no shortage of attempts once we know it.
- R6.3/R6.4 wifid's com.apple.wifid.configure.plist and AirMusic's missing ICDelegateAccountStore.db are both on
  the Data volume — need the R3 root foothold to write, do NOT try to mount disk1s2 from the ramdisk.
- R6.6 Try to turn off os_log `<private>` redaction; check the plist path is really on the System volume first.

## R3.3 CLOSED 2026-11-26 — NEGATIVE
No cached boot job passes a file path as an argument (only 16 of 183 pass anything at all, all flags/labels), and
the cache is integrity-enforced so we cannot add one. Substitution is only useful with binaries that read a
HARDCODED config path (R3.2's list). Also: RunAtLoad is 29 jobs, not 40 as earlier noted; 11 of them run as root
(CrashHousekeeping, DumpPanic, containermanagerd, IOMFB_bics_daemon, locationd, logd, keybagd, lockdownd,
runningboardd, wifiFirmwareLoader, wifid). OTACrashCopier's bare program name is NOT a plant site — it resolves to
a real binary and runs (pid 56 in bootarchive8).

## R7: iBoot-5540.140.12 is readable offline — the pod's own iBoot (homepod/oldfw/17M61/iBoot.dec)
Base 0x830000000, flat, file offset == VA - base. iBoot uses ADR for strings, so adrp-only scanners give false
zeros. Tools: /home/claude/ib5/{refs,ibdis,fstart,strs}.py (rebuild if the container is gone).
- R7.1 DONE, negative: the env parser (0x224f0, the only '=' compare at 0x2256c) clamps name to 0x40 and value to
  0x261 and copies through a size-asserting helper. No length bug.
- R7.2 DONE, negative: load_bank_partitions (0x273f0) checks cursor+size*16 <= 0x2000 before the memcpy. It walks
  NOR for the `APL,OSXPanic` partition.
- R7.3 NEXT: find the code that copies env vars into the DT /chosen node. It reaches `boot-args` through the
  name-pointer table near file 0x40500, not by string, so follow the table. THAT is where any
  production/debug-enabled gate on boot-args lives, and it decides whether R5 can ever work.
- R7.4 Unexplored iBoot surfaces for untethered: img4/ASN.1 parsing, the device tree, the boot/storage path
  (APFS metadata), SysCfg. Bigger jobs than R7.3, and img4 parsing is the classic one.
- R7.5 `boot-command`, `one-time-boot-command`, `*-path` (alamo/rtos/rbm/diags) are all NVRAM variable names in
  iBoot's list. If NVRAM vars other than boot-args ARE honoured (auto-boot clearly is), these select alternate boot
  targets/images. Still img4-verified, but worth knowing which are honoured once 539 settles persistence.
