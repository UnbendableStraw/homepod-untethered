# Soft DFU, signed restores and NAND settings: findings of Nov 23 2026

Pod used: the healthy one on Nicotine
build 116 over USB. Its NAND backup is in `~/homepod/nand-backups/`.

## Verified on the pod (all read-only)

- The NAND driver works with the release boot loaders: RTKit protocol 12.0, ASP
  endpoint 32, "Write enable OK". (knowledge-transfer 16.4 had this as unconfirmed.)
- This pod's NAND holds audioOS 27.2 (24K122); LLB and iBoot are iBoot-15391.
- The user area has two GPT partitions, both APFS containers readable in the
  clear at container level: "Container" (15.7 GB) and "RecoveryOSContainer"
  (275.6 MB). (16.3 describes one partition.)
- RecoveryOSContainer holds one unencrypted volume "Recovery" (role 0x4) with an
  Apple-signed recovery system personalised for this pod: kernel cache, device
  tree, iBEC (iBoot-15391), static trust cache, SEP firmware, root hash, apticket;
  version.plist says variant "Recovery Customer Update Install". Copy:
  `recoveryos-container.bin` in the backup folder.
- Written sizes the controller reports: SYSCFG 131072, NVRAM 8192, EFFACE 4096,
  CTRLBITS 8192, DM 49152, FW 835584, LLB 212992, UTILDM 4096, PANICLOG never
  written (reads as zeros). The small areas are variable-length elements.
- NVRAM is plain CHRP: "nvram" header, "common" partition (2048 bytes), with
  auto-boot=true, com.apple.System.sep.art, boot-breadcrumbs and others.
- Largest single request on asp0n10 is 2032 KiB, so a whole 1 MiB area fits in
  one command.
- PMU boot state before any test: errors 1 (stage 0x20), stage 0x2F, DFU request none.
- Accelerometer upright: y about -2035 (-1 g). Kernel driver bma280 is bound.
- No kexec in this kernel (CONFIG_KEXEC off). Both CPUs use spin-table, so arm64
  kexec would refuse with two CPUs online anyway.

## Why soft DFU cannot start today's restore

Today's restore IPSW boots a tvOS restore ramdisk through patched iBSS/iBEC.
Only a pwned SecureROM accepts those, and gaster only works in SecureROM DFU.
Soft DFU is LLB's DFU, so it takes Apple-signed images only.

## Lead: an Apple-signed "update" restore

Apple's own OTA BuildManifest for AudioAccessory1,1 (checked: 18.6 / 22M84) has
one identity, variant "Customer Software Update", RestoreBehavior "Update", and
its manifest lists iBSS, iBEC, RestoreDeviceTree, RestoreKernelCache,
RestoreRamDisk (`arm64SURamDisk.dmg`), RestoreTrustCache and RestoreSEP. Apple's
signing server therefore signs a complete restore boot chain for the HomePod,
with the update ramdisk from the OTA instead of the tvOS one.
Untested: whether that ramdisk carries out a USB-driven update with
idevicerestore (no `-e`, no gaster). If it does, a restore needs no exploit and
would work from SecureROM DFU, soft DFU and recovery mode alike. An update
restore keeps the data volume, so it would not replace the erase restore for
every fault.

## Untethered boot

No route found. SecureROM checks LLB, LLB checks iBoot, iBoot checks the kernel,
each against a ticket Apple signed for this pod. The only break in that chain is
checkm8, and it is triggered from a USB host on every power-up.

Ideas that remove the flip but not the host:
- find what drives the force-DFU line (fliplog.py records every GPIO while the
  pod is turned over);
- for pods that will never run audioOS again: an invalid LLB makes SecureROM fall
  into DFU on every power-up. Needs an LLB write, which the rules forbid today.

## Prepared, not yet tested on hardware

- Kernel #100 (in the repo working tree): asp0n10 writable when
  /sys/module/asp/parameters/paniclog_rw is Y and the write starts at sector 0.
  Source change: `asp-paniclog-v1.patch`.
- `homepod-nvstore` (here): two-slot settings store for that area. Tested against
  a file on the pod; a real export is about 3 KB.
- `softdfu-test.command` (here): runs knowledge-transfer 17.4 steps 1-4 from the Mac.

## Open

- Is a whole-area write atomic in the controller? If a torn write can leave the
  area shorter than before, two slots in one area do not protect against a power
  cut during a save. Needs power-pull tests.
- Does audioOS clear the panic log area when it boots?

---

# Update, later on Nov 23 (kernel #100 booted on the healthy pod)

## NAND settings area: verified on hardware

- Kernel #100 boots. `/sys/module/asp/parameters/paniclog_rw` exists, asp0n10 is
  no longer read-only at the block layer.
- Refused, as intended: a write while not armed; an armed write that does not
  start at sector 0; any write to SysCfg (asp0n9 is still read-only).
- An armed write from sector 0 works. A whole-area write (256 sectors) and a
  2-sector write both read back correctly.
- **Every write replaces the whole element.** After a 256-sector write, a
  1-sector write left the area at "written size=4096" and the other 255 sectors
  read as zeros. There is no partial update.
- An 8 KiB write plus flush takes about 13 ms.
- `homepod-nvstore` v3 therefore writes only what it needs: the copy that was
  current, unchanged, followed by the new copy (8 KiB for ordinary settings).
  It also carries blobs of other kinds (the LLB backup) along unchanged.
- Not yet known: whether a save survives a power cut in the middle, and whether
  audioOS clears the area when it boots.

## Signed update restore: checked on paper, not worth a pod

`makeipsw.sh` has to patch `asr` in the tvOS ramdisk ("Image failed signature
verification"), because the root filesystem image it builds from the OTA is not
the image Apple signed. Apple's own update ramdisk has an unpatched `asr`, and
nothing unsigned can be changed in it without checkm8. So the signed chain would
boot, and then refuse our OS image. Apple's signed OS image for the HomePod was
never published. Dropped unless that image turns up.

## Always-DFU: design

- `homepod-dfu-mode on` inverts the first byte of the LLB (0x30 -> 0xCF). The
  boot ROM then finds no valid LLB and should fall into DFU at every power-up.
  The rest of the LLB stays in place, so `off` inverts the byte back and does
  not depend on a backup. A backup is still stored in the settings area (kind
  "llb") and in /tmp.
- Needs kernel #101 (`llb_rw` switch, off after boot). Tested only against a
  file copy of a real LLB so far. First hardware test belongs on a dead-SEP
  board.
- Unverified assumptions: that the boot ROM enters DFU on an invalid LLB without
  the upside-down power-up, and that gaster then works as usual.

## What went wrong with the first flip and soft-DFU test

`softdfu-test.command` needed ssh from the Mac to the pod. At 19:29 that timed
out although the Mac still listed the pod on USB, so neither the flip log was
saved nor the soft-DFU test run, and the reboot erased the log (it was in RAM).
Cause of the timeout unknown. Replaced by:
- `fliplog3.py` on the pod: stores its log in the settings area when the pod
  goes upside down and when it is back, and 60 s later sets the DFU request and
  resets the pod by itself (AUTO_DFU=1).
- `softdfu-watch.command` on the Mac: only watches USB; also records whether
  the Mac can reach the pod.

## From the author

Hard DFU (upside-down power-up) also needs 5 V on the USB line.

---

# Update, Nov 23 evening: soft DFU measured, reboot hang found

## Soft DFU (answers knowledge-transfer 17.6)

Done on the healthy pod, kernel #101: `homepod-pmu dfu-on-reset`, then a
watchdog reset. Log: `softdfu-watch-20261123-203836.log`.

- The PMU scratch survives a watchdog reset; LLB acts on 0x4014 = 0xA0.
- USB product ID 0x1227, name "Apple Mobile Device (DFU Mode)", same as real DFU.
- Serial string: `SDOM:01 CPID:7000 CPRV:11 CPFM:03 SCEP:01 BDID:38 ECID:… IBFL:1D`.
  No SRTG, and no PWND possible. Boot ROM DFU on the same pod:
  `CPID:7000 CPRV:11 CPFM:03 SCEP:01 BDID:38 ECID:… IBFL:1C SRTG:[iBoot-1992.0.0.1.19]`.
  Tell them apart by SRTG (present only in boot ROM DFU); also SDOM prefix and IBFL 1D vs 1C.
- `irecovery -q` works there (SRTG: N/A, MODE: DFU, a fresh NONC).
- `gaster pwn` does not fail, it hangs. It had to be killed after 25 s; the pod
  stayed in soft DFU afterwards. The app must not start gaster on a DFU device
  without SRTG.
- Not tested: whether LLB clears 0x4014 by itself (the power was pulled).

## `reboot` hangs under Nicotine

- `reboot -f` (kernel_restart) never resets the pod: the Mac keeps listing the
  Linux USB device, the pod is dead until the power is pulled. Seen 19:56.
- Writing the watchdog directly from user space resets at once:
  WD1_CTRL (0x2_0E02_701C) = 4, WD1_BITE (…7014) = 0, WD1_CUR (…7010) = 0.
  These are the same writes as the kernel's restart handler, so the hang is on
  the way there, most likely in a driver's shutdown hook. Prime suspect:
  `apple-asp` uses its whole remove path as `.shutdown`. No UART, so not proven.
- `homepod-reset` (here) does the direct write. `echo b > /proc/sysrq-trigger`
  should work too (it skips the shutdown hooks); not tried yet.
- Nicotine's web UI has no restart button today, so nobody had hit this.

## Flip log (two flips, `fliplog-from-nand-attempt1.txt`)

- Accelerometer: upright y = -2036, upside down y = +2100.
- No SoC GPIO with its input enabled changed with orientation, and neither did
  the PMU GPIO configuration bytes 0x0400-0x043F.
- About half of the SoC pins have their input buffer off (config 0x0007200e,
  bit 9 clear), so their level cannot be seen without switching it on.
  A second pass would do that and also diff a wider PMU register range.
- The log itself survived in the NAND settings area across three power cuts,
  next to the two settings copies.

## Settings area after three power cuts

Both settings copies still valid (generation 4 and 5); the stored backup
unpacks as a normal `homepod-config` archive. Power was never cut during a save.

## Not explained

At 19:29 and 19:55 the Mac could not reach 172.16.42.1 (ping, ssh) although it
listed the pod's USB device and had 172.16.42.2 on <USB_IFACE>. At 20:23 it could.
The 19:55 case may simply be the reboot hang (timing is within a minute of it).

---

# Update, Nov 23 night: always-DFU proven; 13.4.8 is still signed

## Always-DFU on the dead-SEP board (serial ends dead-sep-pod), kernel #101

- Before: LLB iBoot-13822.80.422.0.2 (210368 bytes), NVRAM auto-boot=false with
  restore boot-args (left mid-restore), user area unformatted, panic log area
  never written. All nine small areas backed up in
  `~/homepod/nand-backups/<SERIAL_POD1>-2026-11-23/` (plus `llb-original.img4`).
- `homepod-dfu-mode on --yes`: LLB backup stored in the settings area (54
  sectors), LLB rewritten (52 sectors) with its first byte 0x30 -> 0xCF.
- Watchdog reset 20:53:03 -> 20:53:04 boot ROM DFU, upright, untouched:
  `CPID:7000 … IBFL:1C SRTG:[iBoot-1992.0.0.1.19]`.
- The app's gaster pwned it; Nicotine up 20:54:54. NAND driver works as before.
- Power pulled 20:55:16, plugged in upright -> boot ROM DFU at 20:55:25, Nicotine
  up 20:56:14 (49 s from plug-in).
- Left ON. Undo: `homepod-dfu-mode off` (or `off --from-backup`).
- Side fact for the app: during every checkm8 boot the uploaded iBSS also shows
  up for a few seconds as 0x1227 with `SDOM:01 … IBFL:1D` and no SRTG, the same
  string as soft DFU. A "soft DFU" warning must not fire while a boot or restore
  job is running on that port.

## Apple's signing server, checked 21:06 with tsschecker 0.341

- 13.4.8 (17M61): SIGNED. Boot chain iBoot-5540.140.12 (July 2020), which
  predates Apple's memory-safe iBoot build (iOS 14 and later).
- 18.3 (22K557): signed. 18.6 (22M84): not signed.
- ipsw.me also lists 12.1.3 (16D39) as signed, but Apple's download server
  answers Access Denied for every 12.1.3 file, so no manifest to test with.
- Tickets saved for both pods in `~/homepod/tickets/tickets/<ECID>/`
  (13.4.8 and 18.3). The 13.4.8 boot files (LLB, iBoot, device tree, SEP
  firmware, manifest) are in `~/homepod/oldfw/17M61/`. Apple's files: private.
- The 13.4.8 OTA is still on Apple's CDN (full: 1.63 GB, URL in ipsw.me's list).

## Lead for booting without a host (research, not a result)

Install the 13.4.8 LLB and iBoot with a fresh ticket (the boot ROM accepts them:
valid signature for this ECID, no nonce check when booting from flash), then
find a bug in that 2020 iBoot that can be reached from what it reads off the
flash before or without a signature check (file system, NVRAM, partition
table, SysCfg, effaceable lockers). We control all of those from Nicotine and
can watch iBoot run under checkm8. Nothing found yet; no public bug known to me.

---

# Update, Nov 23 late: how the flip works, real DFU from Linux, 2020 chain on flash

All on the dead-SEP board (serial ends dead-sep-pod), with UART.

## The 13.4.8 boot chain installs and runs with a ticket fetched today

- LLB: IMG4 = Apple's `LLB.b238a.RELEASE.im4p` (17M61) + the IM4M from the saved
  ticket, no IM4R. Written to asp0n2 (44 sectors). After a reset the boot ROM ran
  it: UART shows it scanning the firmware area, USB shows soft DFU. No nonce
  check for a boot from flash, as expected.
- Firmware area: `[ibot IMG4][dtre IMG4]` back to back (that is the whole layout;
  the old one was ibot 0xc5f98 + dtre 0x5a4a). Written with kernel #102 (`fw_rw`).
- After `reboot -f`: LLB 5540 -> "iBootStage2 … Local boot … iBoot-5540.140.12"
  -> "Entering recovery mode" (this board's NVRAM says auto-boot=false). USB:
  Recovery Mode, IBFL:1D. So Apple's 2020 boot loaders now start from this pod's
  flash with no host.
- Decrypted on the pod with gaster: `~/homepod/oldfw/17M61/LLB.dec`, `iBoot.dec`.
- Files built for this ECID: `~/homepod/oldfw/17M61/dead-sep-pod/`.

## How "upside down" becomes DFU (read from iBoot-13822 stage 2, confirmed on hardware)

- The boot ROM does not look at orientation. With the 2020 LLB but no matching
  second stage, a flipped power-up never reached boot ROM DFU (UART: the LLB ran
  every time).
- The second stage (iBoot / iBEC) does it, in its platform init at 0x8700155f4
  (iBoot-13822.80.422.0.2, base 0x870000000):
  - reads the accelerometer chip ID (I2C2, 0x18, reg 0x00 == 0xFB);
  - writes reg 0x16 = 0xC0, waits 10 ms, then reads reg 0x0C ten times, 100 ms
    apart; every reading must satisfy `(value & 0xB0) == 0x30`;
  - clears the word at 0x2_0E02_9004;
  - sends six bytes to the top-panel MCU ("Peppy", I2C3, 0x55):
    `21 01 00 00 5A 84` = command 0x21, one data byte 0x5A, in the framing
    peppy.py already documents (cmd, len, seq 0, 0, data, checksum).
- The MCU then resets the SoC itself with force-DFU asserted: real DFU, SRTG
  present. It is one-shot: the next reset boots normally.
- The first stage only reads the result: bit 5 of 0x2_0E02_9000 (valid when
  bit 6 is set) is the force-DFU state latched by the ROM; if set, it enters its
  own DFU without trying to boot.
- Sent from Linux (`homepod-realdfu`, here): the pod was in boot ROM DFU one
  second later, upright, LLB valid and untouched. The app booted Nicotine from
  it. This is "Restart into DFU" for any pod running Nicotine.
- The 2020 second stage has the same logic: Apple's signed 13.4.8 iBSS + iBEC,
  loaded through soft DFU with a ticket for the current nonce while the pod was
  upside down, bounced it into boot ROM DFU (`signed-stage2.command`). That is a
  route from soft DFU to real DFU that uses no exploit.

## `reboot` fixed

Kernel #102: the ASP driver's shutdown hook only flushes. `reboot -f` now prints
"reboot: Restarting system" and the pod restarts. The old hook (the whole
remove path) was the hang.

## State of the board now

LLB 5540 + iBoot 5540 on flash, sitting in iBoot recovery mode. Its original
LLB and firmware area are in `~/homepod/nand-backups/<SERIAL_POD1>-2026-11-23/`
and the LLB also in its settings area. A flipped power-up gives boot ROM DFU
again (the 2020 second stage handles it).

---

# Update, night of Nov 23 to 24 (runner, Kasa plug, build 117, power-cut tests)

## Working without a person at the bench

- `~/homepod/multipod/runner/hp-runner.command`: started once on the Mac, runs job files from
  `queue/` and writes `out/<job>.log`. Fixed list of actions (state, wait, pwn, gaster-reset,
  boot-nicotine [image], signed-iboot, send, cmd, ticket, img4, decrypt, sleep); every acting step
  needs an `only <ECID/serial>` line and refuses while any other HomePod is connected. Never runs a
  restore. `usb-events.log` records every change of the USB device list.
- Kasa HS110 "<SMART_PLUG_NAME>" at <PLUG_IP_1> powers the dead-SEP board (<PLUG_IP_2> is some
  other device). `runner/tools/kasa.py IP info|on|off|cycle|power` (local protocol, TCP 9999).
  Power drawn: DFU 1.4 W, Nicotine idle 3.8 to 5.5 W.
- With DFU at every power-up on, a cycle from the plug has the board in boot ROM DFU 7 s later,
  upright. Boot through the runner takes about 60 s to the USB network.

## The flip check, once more

- Booting Nicotine with the pod still upside down fails: the release second stage (from audioOS
  16.4) makes the same check and asks the MCU for DFU again, so the pod is back in boot ROM DFU
  and the rest of the boot files go nowhere. There is no "already forced" gate. The app's DFU
  guide already says to turn it upright first; now the reason is known.
- So: upside down is only for getting to DFU. A second stage without that check would let a pod
  boot in any position (not done).

## Build 117 on the dead-SEP board (all through the runner and the plug)

- `/init` puts the settings back from the flash 1.8 s after it starts (kernel time 2.66 to 4.48 s),
  before WiFi, AirPlay, Bluetooth and the speaker service.
- Change on the pod, power cycle, boot: the change is there with no Mac involved.
- `homepod-config.sh restore --auto` against such a pod: "settings=kept", the Mac's copy refreshed,
  the old file kept as `.prev`. With nothing on the flash the backup goes in as before.
- "Restart into DFU" (`startup.cgi`, `homepod-realdfu`) with DFU-at-power-up OFF and a valid LLB on
  the flash: boot ROM DFU 3 s after the request, upright. The same with it on.
- `dfu_on` / `dfu_off` / the LLB download / `keep.cgi` on, off, save: all exercised on the board.

## What a power cut does to a write (the open question from the morning: answered)

Tests: `b117/nvstress.py` rewrites the area in a loop, announcing every write on the kernel log;
`b117/cutcycle3.sh` cuts the power from the plug at a random moment, boots again and looks.
Results in `b117/cut-results.txt` and `cut-results-v4.txt`. The UART log gives the timing
("panic log area: writing N sectors" when the command goes out, the controller's
"element=PANICLOG written size=…" line when it is done: 17 ms for 2 sectors. 300 to 400 KiB took
about 50 ms from Python, read-back included).

| cut | image | where the cut fell | after |
|-----|-------|--------------------|-------|
| 2   | 364 KiB | after "start", before the controller began | old content intact |
| 3   | 216 KiB | during the write | first 32 KiB of the new image, rest zeros: every copy lost |
| A1  | 8 KiB | as the command went out | old content intact |
| A2  | 8 KiB | after "start", before the command | old content intact |
| A3  | 8 KiB | during the write | area empty (all zeros): every copy lost |
| B1  | 8 KiB | between writes | intact |
| 1   | about 350 KiB | not known (the UART log was read too early) | intact |

- So a write to the area is **not atomic**. The controller drops the old element when the write
  starts and the new content appears piece by piece; "written size" keeps the old value until the
  end. Two copies inside the area protect nothing.
- A write that does not start at sector 0 is refused by the controller itself (test kernel #103
  with the driver's own check lifted: I/O error for LBA 1, for LBA = written size, and beyond). No
  appending, no second slot. Kernel #103 was only for this test; the repo stays at #102.
- `homepod-nvstore` v4 (in build 117) therefore keeps one copy per kind, settings first (they fit
  the first sector), no "previous" copy, and says so. The LLB backup is no longer put into the area
  by default (`homepod-dfu-mode on --flash-backup` still can): it made every settings save 45 times
  larger. The window that remains is the 10 to 20 ms of a save; then the pod starts with the
  built-in settings and the Mac's backup goes in.
- The same holds for the LLB area: a cut during the half second of `on`/`off` can leave no usable
  LLB (ROM DFU at every power-up; `off` cannot rebuild it; `off --from-file`, or a restore, can).
  Not tested with a cut; the app saves a copy of the LLB before it switches.

## State of the pods at the end of the night

- Dead-SEP board (dead-sep-pod): LLB + iBoot 5540 (13.4.8) on the flash, DFU at every power-up ON, settings
  area holds one settings copy (no LLB backup any more), running Nicotine 117 (test image
  `runner/files/k117f.img4`, same root filesystem as the repo's new skeleton), upright, on the plug.
  The original 13822 LLB is in `nand-backups/<SERIAL_POD1>-2026-11-23/`.
- Healthy pod: not touched tonight.

## In the repo working tree (uncommitted)

Nicotine build 117 (`rootfs-skeleton.tar.gz`, `homepod-config.sh`, READMEs, `docs/nicotine-boot.md`)
and the app side (`NicotineStartup.swift`, `TicketVault.swift`, the Nicotine page's two buttons,
automatic ticket saving, the boot-loader-DFU check). The core builds and its tests pass on Linux;
the four app-target files were only syntax-checked there.

---

# Update, Nov 24 after midnight (the upside-down check as a scripted patch)

- The release second stage the app builds is iBoot-8422.100.650 (audioOS 16.4, build 20L497). Its
  encrypted im4p files are in `~/homepod/oldfw/20L497/`; decrypted on the dead-SEP board through
  the runner: `runner/files/iBEC-20L497.dec` (762432 bytes), `iBSS-20L497.dec` (194800).
- The check is one function (file offset 0x15188 in that iBEC): chip id 0xFB, reg 0x16 = 0xC0,
  10 ms, ten reads of reg 0x0C 100 ms apart needing `(v & 0xB0) == 0x30`, then the frame
  `21 01 00 00 5A 84` to the MCU, built on the stack from the constants 0x121 and 0x845A. The
  call that sends it is at 0x1528C.
- That pair of constants followed by a call is there exactly once in every second stage at hand:
  iBoot-5540 (0x11354), the 655936-byte iBEC in SSHRD_Script/work (0x10460), iBoot-8422 (0x1528C),
  iBoot-13822 (0x15728). Not in any LLB / iBSS.
- Test on the board, upside down (the pod's own accelerometer, read from Linux with reg 0x16 set
  to 0xC0, gave 0x0C = 0x30, the value the check wants), the app's patched iBSS first, then:
  - A, the decrypted 16.4 iBEC wrapped as it is: banner on the UART ("Remote boot … iBoot-8422"),
    boot ROM DFU again within 12 s.
  - B, the same with the call at 0x1528C made a no-op: "Entering recovery mode, starting command
    prompt", still in recovery mode 32 s later.
  (`runner/files/ibec-164-plain.img4`, `ibec-164-noflip.img4`; jobs 017 and 018.)
- In the repo working tree: `IBootFlipCheck.swift` (the finder and the four-byte change),
  called by `ReleaseIBootBuilder` after hBootPatcher for the iBEC; the Boot loaders card says when
  the loaders on the Mac still have the check. Nothing of Apple's is stored for it.
- Reading the orientation from Linux the way the boot loader does:
  `i2cset -f -y 1 0x18 0x16 0xc0; i2cget -f -y 1 0x18 0x0c` (0x30 = upside down as the check sees
  it; put 0x16 back to 0x00 afterwards). Raw: y about +2100 upside down, -2040 upright.
- A request for access to the app's "Nicotine Release iBoot" folder in Library was refused by the
  session's policy; not needed in the end.
- Whole chain, 00:28 on Nov 24: app rebuilt, release boot loaders rebuilt in it, "Boot Nicotine" with the
  dead-SEP board upside down. USB: boot ROM DFU, first stage, recovery mode at 00:28:12 (the second
  stage stayed), Linux at 00:28:47; accelerometer y = +2098 with Nicotine running. The app-target
  Swift of both rounds compiled on the Mac (app bundles of 23:42 and 00:26).

## Untether leads from the 13.4.8 boot loader strings (noted 2026-11-24 08:35, hunt NOT started)

Source: the author's strings dumps of the decrypted LLB and iBoot (iBoot-5540.140.12).
Everything below comes from reading strings only. Nothing has been disassembled
or tested yet.

- No switch in there. It is a RELEASE build, and every boot path the strings
  name (fsboot, diags, upgrade, recover, memboot, the *-path variables) is
  expected to check the signature before running anything. The "Permission
  Denied" string is probably the guard on restricted variables and commands;
  not traced.
- What the strings do give: the list of things this boot loader reads from
  flash, all of which Nicotine can now write.

Leads, in the order to try them:

1. upgrade / recover path. Mounts a partition and reads an iBEC, a ticket and
   an OS image from /boot on it. Reachable by setting boot-command or
   one-time-boot-command in NVRAM. First thing to confirm: is the signature
   checked only after the filesystem has been parsed? If yes, the filesystem
   code is handling data we control.
2. NVRAM parsing (bank loading, the max name/data size variables). We control
   every byte of that area.
3. SysCfg into the device tree (the syscfg/, macaddr/, string/, zeroes/
   property sources). Flash data copied into fixed-size properties.
   Research board only; SysCfg writes stay off limits on working pods.

Side test: bootdelay ("hit enter" prompt). One UART test. At best a prompt
during a flash boot, not an untether.

Where to start: disassemble ~/homepod/oldfw/17M61/iBoot.dec (base 0x830000000),
lead 1, on the dead-SEP board through the runner and the Kasa plug. Waiting for
the author to say "start the hunt".

Open risk to settle before flash-boot tests: a flash state that hangs before
the upside-down check has no proven way back to DFU.

## Untether hunt, 2026-11-24 — results of a parallel audit of the whole boot chain

Method: a shared brief plus sixteen parallel agents, each auditing one surface and
required to cite an address or a file offset for every claim. Ghidra 12.2 and angr
were both running in the cloud container; unicorn was used to demonstrate findings
by emulation rather than by argument. Every negative below was reached by reading
the code and quoting the check, not by failing to find something.

### RETRACTED 2026-11-24 — see the correction at the end of this file.
### (claimed lead) pre-authentication heap overflow in the SEP firmware file path

iBoot loads `/usr/standalone/firmware/sep-firmware.img4` with handle flag 0x100 set
(`sep_load_image` 0x83002fe18, flag set at 0x83002fec4). Inside the image worker
0x8300093ec that flag is tested at 0x8300095e0 (`ldrb w8,[x26,#0xd]` / `tbnz w8,#0`)
and the whole Img4Decode-and-verify block is **skipped**: the file is copied to the
destination raw and the function returns success. **iBoot never verifies that file.**

The raw bytes are then parsed by 0x83002fa64, which runs Img4DecodeInit on them and
extracts a DER property of length L, then hex-decodes it:
  0x83002fb3c  malloc((L+1)>>1)
  0x83002fb50  scan loop over hex digits — NO upper bound, walks past the DER item
  0x83002fb8c  guard: cmp (N+1)>>1, L   — compares the DECODED BYTE COUNT to the
                                          STRING LENGTH, not the digit count to it
  0x83002fbe4  write loop: strb w0,[x19,x8]  — writes ceil(N/2) bytes
Off by a factor of two. The guard accepts N up to 2L, so the write is **exactly
double the allocation**: overflow = floor(L/2), for any attacker-chosen L, and every
byte is arbitrary 0x00-0xFF because each passes through strtoul of a hex pair.
The buffer is then free()d on the error path at 0x83002fc60, so forged heap metadata
is consumed immediately.

Demonstrated by emulation on real iBoot bytes. The control is the convincing part:
Apple's genuine 17M61 version string is 76 hex digits, allocates 38 bytes and writes
38 — an exact fit, which is why this never fires on real firmware.

Untethered reachability: default `boot-command` is fsboot (set at 0x8300038c0) ->
dispatcher 0x8300030cc -> fsboot 0x830002098 -> 0x830001ed8 -> snprintf("/boot%s",
sepfw-path) -> 0x83003003c -> fs_load_file -> 0x83002fe18 -> 0x83002fa64. **SEP is
the first file fsboot loads**, before kernelcache, ramdisk, device tree and trust
cache. Nicotine writes that file freely. No USB, no host, survives power cycles.
`sepfw-path` itself is NOT settable from NVRAM (absent from both whitelists, at file
0x404f8 and 0x40520) — it is baked in, which is fine since the file is ours.

Fixed in audioOS 16.4, three independent ways, at iBEC-20L497 0x830037408-0x8300747c:
the scan loop is bounded by L (0x830037428), an odd digit count is rejected
(0x830037470), and the shift became N>>1 (0x830037474).

**Failure behaviour is clean**: a malformed file returns an error, fsboot returns
negative, and the dispatcher's caller at 0x830002de4 sets stage "recm" and enters
iBoot's recovery console over USB. No panic, no hang — recoverable with irecovery.

TETHERED ROUTE, no flash write at all: the `rsepfirmware` command (table entry at
file 0x40780 -> 0x83003020c -> 0x83003015c) feeds the same loader from a USB upload,
taking loadaddr and filesize from env. filesize is set by iBoot's own upload
completion handler (0x83001ede8, set at 0x83001eec0 with flags=0, so no whitelist
applies) and is zeroed at transfer start and on failure. Verified on hardware today:
a live tsschecker ticket, Apple's unmodified 17M61 iBSS and iBEC sent, pod reached
recovery mode with iBoot-5540.140.12 RELEASE on the UART, and `rsepfirmware` with
nothing uploaded returned cleanly and left the pod alive.

### Both memory-corruption mitigations on this platform are defeated offline
- **Stack canary is a build-time constant** in the signed image, not per-boot:
  iBoot-5540 0x8300483d8 = 0x4752400444303631 (526 loads, zero stores); LLB-5540
  0x1803aa298 the same value; iBSS/iBEC-20L497 0x1803af8b0 / 0x830059a10 =
  0x4752440044303631. No ASLR, load addresses fixed. Any stack overflow is a direct
  saved-LR overwrite.
- **Heap cookie is SipHash-2-4 over a static image constant.** Key at iBoot
  0x8300487a8 = 2f 32 32 31 78 6b 63 64 fc 17 79 36 2e 3a fa a7, i.e. k0 =
  0x64636b783132322f, k1 = 0xa7fa3a2e367917fc — the first eight bytes are ASCII
  "/221xkcd". Hash at 0x830020444; cookie = SipHash(key, header+0x08,
  (header[0x28] & 1) ? 0x48 : 0x38), computed at 0x830023e80, verified at
  0x830023bf0. A Python reimplementation matches iBoot's own emulated code on 7 of 7
  inputs. Heap-base randomisation derives from the same constant. Header is 0x40
  bytes, payload at +0x40; free() (0x830023c70) validates the arena pointer against
  two literals, checks two-way adjacency, and a descending-byte redzone.
  => The step from memory corruption to code execution is already solved here.

### Mix-and-match across builds is permitted untethered
MMIO 0x2_0E029000 bit 3 is the mix-and-match prevention bit (read 0x83000dad4,
written 0x83000daec); +0x40..0x53 holds a 20-byte boot manifest hash. Enforcement at
0x830009790-0x830009808: if the inherited bit is set and the manifest lacks AMNM, the
image's manifest SHA-1 must equal the latched hash. Publication at 0x830009bc8 only
sets the bit if the image came via the nonce/DFU path or already matched — so on a
cold flash boot it is never set. Apple's 17M61 manifests carry no AMNM at all. There
is no per-component version or ordering field; only CHIP/ECID/CEPO/BORD/SDOM/CPRO/
CSEC/DGST and the type 4CC bind. **So each component can be the oldest version Apple
ever signed for b238a, chosen independently.** One read-only register read from
Nicotine (bits 1/3/4 and the 20 bytes at +0x40) confirms the whole model.

### Demotion: CLOSED, measured on hardware
[0x20E02A000] bit0 is effective-production-status-ap; 0x83000e6d0 is a clear-only
demote primitive; 0x83000e790 sets the one-way lock [0x20E02A004] |= 0x80000000 and
panics (0x299) if it does not stick. LLB always takes that lock before entering iBoot
(gate 0x18038dc38 is `mov w0,#1; ret`), and LLB-4076 has the same lock at 0x18038fa74,
so an older signed LLB does not help. gaster gives code execution before LLB — so the
question was whether the boot ROM had already locked it.
Measured: a patched iBSS-20L497 with its own lock write neutered (0x1803908e8 -> ret)
and the IBFL getter (0x18038e598, single caller) replaced by a probe. Control run
reported IBFL:1D as predicted; the probe reported [0x20E02A004] = **0xA0000000**.
Bit 31 set => **the boot ROM sets the lock before any DFU-loaded code runs.** The
clear was ignored (demote-before and demote-after both read 1). No runtime AP
demotion, therefore no AP JTAG/SWD by that route. Bit 29 is also set — an unidentified
sibling bit. DPRO is absent from every manifest we hold including a live TSS ticket,
and DSEC appears in none of the four binaries, so the ticket route is dead too.

### Well-evidenced negatives — do not re-audit these
- **DER/IMG4 container layer, three builds, three rounds: clean.** Apple's libDER here
  is strict by default; the single permissive decode (allow_partial=1, only two sites,
  both inside image4_get_type) is immediately clamped by der_cursor_clamp
  (5540 0x18038b948, 4076 0x18038c820) to min(L, real_remaining). The 5540 ptr+len
  overflow guard exists but uses an `mvn`/`cmp` idiom, which is why an encoding-level
  version diff missed it. 4076 genuinely lacks two such guards (LLB-4076 0x18039d72c)
  but the value that would exploit them is clamped before it ever reaches the add, so
  the chain does not compose. The LLB 0x18038c428 "return success with no
  verification" path is dead code: x26 is the image handle, the byte is bit 8 of a
  flags u32 written at only two sites, and all 15 callers pass {0,1,9,0x200}.
- **Digest boundary**: DGST is SHA-1 over the **complete IM4P element, tag and length
  bytes included** — proven arithmetically against three genuine Apple images. The
  KBAG is inside it (covered), so the keybag path is not attacker-controlled; the IM4R
  element is outside the hash but read by nothing; slack after the outer SEQUENCE is
  bzero'd. No unhashed byte feeds a length anywhere. The decompressor is therefore
  dead as a surface: every input to it is inside the digest, and all five call sites
  are downstream of verification.
- **SysCfg -> device tree: clean.** Every copy site bounded; the one 32-bit width
  candidate needs a source length of ~0xFFFFFF6D while the source is hard-capped at
  0x20000. 16.4 is structurally identical, so nothing was quietly fixed.
- **NVRAM: clean in 5540**, bank walk and per-variable parser both. In 4076 the
  per-variable parser is missing two bounds (`cmp` against the length inside the name
  and value scans, present in 5540 at 0x83002255c and 0x8300225a0) — a real OOB
  **read**, demonstrated under emulation, leaking up to 255 bytes of heap into a
  variable that iBoot then writes back to flash. No write primitive. NVRAM remains
  valuable as a *control* surface: `auto-boot=false` reaches the iBoot command prompt
  ungated, and `boot-device`/`boot-partition`/`boot-command` choose which filesystem
  gets mounted and parsed pre-verification.
- **Filesystem chain: exhausted and clean.** GPT/LwVM/MBR, APFS container superblock,
  checkpoint map, object map, B-tree node validator, B-tree search/iterate, both
  record accessors, inode/dirent/extent decoders, and the entire HFS+ driver. One OOB
  read (the 0xFFFE value-length sentinel at 0x830017130 bypassing the capacity check,
  consumer 0x830015d6c, ~61 KiB of heap readable) with no write sink — the leaked
  value only makes a load shorter or fail. Machine-checked: 4000 random nodes, 25675
  accessor results, 2000 randomised multi-level trees, zero out-of-buffer accesses
  besides that sentinel. GPT is the loosest code (neither CRC32 is ever read, entry
  count and LBAs unchecked) but reads are clamped, so it is a primitive, not a bug.
- **ANS/ASP storage coprocessor**: its firmware is a raw `fwsg` blob appended inside
  the iBoot image (descriptor at file 0x407a8 = {0x830049000, 0x60240}, ending exactly
  at sizeof(iBoot.dec)), so it is covered by iBoot's own signature and cannot be
  swapped. It parses the raw NAND metadata before anything is readable, and has no
  DART in front of it — one real 8-byte OOB write found in DM_Decompress's v100->v101
  upgrade path (blob 0x118a3-0x119d3; the header grows 0x2c->0x34 but the bound is
  computed on the pre-transform size), demonstrated by emulation, landing on band[0]
  and band[1] of flow 0 at 0x92028. Escalation unproven: those slots sit above
  `count` and no consumer appears to read them. CTRLBITS is not parsed by this
  firmware at all (the iPCB magic appears nowhere in it, nor in iBoot or LLB).
- **checkm8 cannot be made persistent**: the bug is in the DFU io-buffer lifetime and
  USB transfer globals, which nothing on the flash path touches, and its effect is
  RAM-only against mask ROM. No published iBoot bug exists for this generation.

### Safety correction to earlier notes — important
The upside-down force-DFU check (0x830011228, called from 0x83000d008 at 0x83000d048,
from the boot task at 0x830002c10) runs **after** NVRAM parsing (0x830002b44), the
asp_fw/SysCfg parse (0x830002b48) and the 'logo' load (0x830002bd0). So a corrupted
NVRAM, SysCfg, asp_fw or LLB element can hang the pod before that recovery path is
reached. The research board is safe today only because its LLB first byte is inverted
(0xCF), which makes the ROM fail the container parse and drop to DFU in ~7 s — and
that is also why it cannot be used to test flash-boot behaviour. Any real flash-boot
experiment needs that byte back at 0x30, and at that moment the guaranteed fallback is
gone. Build the external I2C force-DFU jig first: six bytes `21 01 00 00 5A 84` to
device 0x55 on i2c3 (SDA GPIO port10.6 flat 0x56, SCL GPIO port10.7 flat 0x57), which
works even with the AP hung. Note also the frame does not exist as a byte string in any
blob — it is built from immediates (`mov w8,#0x121` at 0x830011334, `mov w8,#0x845a`
at 0x83001133c), so the scripted flip-check patch matching instruction encodings is
correct and a byte-string search would find nothing.
Relief: a panic is not a hang. panic() (0x83000f998) arms the watchdog at 0x2_0E027010
and spins, giving an observable reboot loop; three panics in one boot hard-hangs.

### Also worth keeping
- A physical debug strap exists: **GPIO port 13 pin 5** (flat 0x6d, named in the device
  tree as both `wdt function-panic_notify` and `apcie function-debug_gpio`). LLB reads
  it at 0x18038d01c and sets bit 5 of 0x20E029000; iBoot caches it at 0x8300133a0 and
  **sixteen** call sites consume it, including the choice between the restricted
  three-entry boot-command table (0x830047000) and the full eight-entry one
  (0x830047040, which adds alamo/rtos/rbm/diags/fsboot). Never tested.
  `upgrade`/`recover`/`recover-once` are in both tables, so they are honoured either way.
- The NAND element write restrictions — writes only from LBA 0, element max size, "core
  is not writable" — are **software checks inside the ASP firmware**
  (`src/aspcore/core/util.c`, strings at blob 0x464e4 / 0x46531 / 0x4657a), and that
  firmware rides inside iBEC. A tethered boot with a patched iBEC could lift them,
  which would address the "two copies are impossible on this flash" finding.
- iBoot registers `asp_fw` as 8 MiB (0x800000, block 0x1000) at 0x830006144-0x830006210,
  but our dumps are 4 MiB. One dd settles whether we have been reading half of it.
- The SysCfg container sits at offset 0x4000 of the 0x24000 `nand_syscfg` element, so
  the existing 128 KiB syscfg.bin backups do **not** include the element's first
  0x4000. A restore from them today would be incomplete. Dump that first.
- The ASP firmware is the best-symbolised thing in the project: its log format is
  "%s:<text>" with %s the function name, and asserts are "%s:%d assert failed:" with
  the source file and line, giving src/aspcore/core/{dm,format,gc,duster,update,band,
  util,boot,bg}.c with line numbers.
- Tooling note: iBoot references most strings with `adr`, not `adrp`+`add`, and
  register allocation and mov/movk ordering differ between builds — so identifying code
  by byte or encoding patterns produces confident false negatives. It did so three
  times today. Read instructions. Also, outlined tail-thunks mean a bl-only call graph
  misses real call edges.

## CORRECTION, 2026-11-24 — the SEP hex-decode overflow is UNREACHABLE

The section above headed "pre-authentication heap overflow in the SEP firmware file
path" overstated its case and is retracted on the reachability claim. The defect is
real; it cannot be reached through that file.

What was wrong: the emulation that demonstrated the overflow entered the function at
0x83002fb08, i.e. it handed the hex-decode loop a synthetic property DERItem {ptr, L}
chosen by hand. That proves the defect in the loop. It does not prove that any
container can produce such an item. Emulating the whole of 0x83002fa64 from its
entry, with the real Img4DecodeInit (0x830033c64) and the real property extraction
(0x830032ff8) running on crafted containers, shows it cannot.

Why it is gated. An overflow needs N > L, i.e. hex-ASCII bytes immediately after the
version string's content. Img4DecodeInit enforces the IM4P schema strictly: omit the
payload OCTET STRING and it returns 5; append anything after the outer SEQUENCE and
it returns 7; insert a foreign element anywhere and it returns 2. An exhaustive sweep
of all 256 tag values for the element following the version string found that **only
0x04 is accepted**, and 0x04 is not a hex-ASCII character, so the unbounded scan
always stops exactly at the end of the version content. Therefore N == L
unconditionally, and writes = ceil(L/2) while the allocation is (L+1)>>1 = ceil(L/2)
— equal for every L, even and odd. Confirmed at the genuine 76-digit string (38 into
38), at L=0x400 and at odd L=0x401, plus 350 structural length mutations, none of
which produced N > L. The clamping decoder only ever reduces L, which makes the guard
easier to pass but leaves allocation >= writes. The hex-digit mask 0x3f0000003f occurs
exactly once in iBoot-5540, so there is no second ungated caller.

Apple still hardened that exact loop three independent ways in 16.4 (bound the scan by
L at 0x830037428, reject odd digit counts at 0x830037470, N>>1 instead of (N+1)>>1 at
0x830037474). Either they reached it by a route not found here, or they fixed it
defensively. Unresolved.

What stands from that work, and it is worth keeping:
- **iBoot parses the SEP firmware file itself, raw and pre-trust.** `flags |= 0x100` at
  0x83002fec4 makes image_load skip the Image4 parse and verify entirely and copy the
  file raw (test at 0x8300095e0, branch 0x8300095e4); 0x83002fa64 then runs
  Img4DecodeInit, property extraction and the manifest/trust path (0x830032b9c,
  0x830033b50) on attacker bytes before any trust decision. The surface is real even
  though this particular bug is not reachable.
- **A tethered injection point into that parser, confirmed on hardware.** A live
  tsschecker ticket wraps Apple's unmodified 17M61 iBSS and iBEC; the pod reaches
  recovery mode running iBoot-5540.140.12 RELEASE (UART banner captured); then
  `irecovery -f <file>` followed by `irecovery -c rsepfirmware` feeds arbitrary bytes
  straight into 0x83002fa64. Zero flash writes, power-cycle recoverable, and the build
  under test is genuine and unmodified. `filesize` is set by iBoot's own upload handler
  (0x83001ede8 -> 0x83001eec0, flags=0, so no whitelist applies) and is zeroed at
  transfer start and on failure, so a stale value is safe.
- The SipHash heap-cookie oracle (verified 7/7 against iBoot's own emulated code) is
  reusable for any future heap bug.

Operational notes learned while testing:
- The RELEASE command set has **no memory-read or dump command**: bootx, memboot, go,
  reboot, reset, bgcolor, setpicture, firmware, devicetree, getenv, saveenv, setenv,
  setenvnp, ramdisk, rsepfirmware (table at file 0x40440-0x40780). Heap effects cannot
  be observed directly from the prompt.
- 0x83002fa64 prints nothing on the wire in any outcome. 0x83003085c / 0x8300308d4 are
  breadcrumb ring-buffer writers (formats at file 0x4036d / 0x40373, ring at
  0x8300b1328, flushed to `boot-breadcrumbs` by 0x830030a74), not UART.
- The UART line `ea0f64a4253252:308` seen during testing is 0x830011a54 and is not on
  the rsepfirmware path.
- `ticket NAME` in the job runner appends its own `.shsh2`, so the resulting file is
  `files/NAME.shsh2`; passing `NAME.shsh2` yields `NAME.shsh2.shsh2`.
- Booting Apple's signed iBSS and iBEC needs a ticket for the **live** nonce, so fetch
  it in the same job as the boot. A stale ticket gets iBSS through a pwned ROM but iBSS
  then rejects iBEC itself and the pod resets.

Methodological note, recorded because it cost real time three separate times today:
a demonstration that enters a function partway and supplies its own arguments proves a
defect, never reachability. Version-diff hits and partial-entry emulations both need an
end-to-end path from attacker-controlled input before they are worth hardware.

## CLOSED, 2026-11-24 — the ASP defect-map overflow is unexploitable, and two near-misses

The out-of-bounds write in the ASP firmware's DM_Decompress v100->v101 upgrade path is
real (blob 0x118a3-0x119d3, 8 bytes past the 0x14000 buffer at 0x7e028, landing on
band[0] and band[1] of flow 0 at 0x92028, demonstrated by emulation). A count-ignoring
reader for those slots was then found and confirmed: the duster compaction loop at blob
0x1e77e reads band[0..9] on a fixed bound of 10, compacts non-zero words to the front,
and at 0x1e79c **rewrites `count`** to cover them. The write primitive was demonstrated
too: the dequeue at 0x1f634 (`str.w ip,[r2,r5,lsl #2]`) uses the band number as an
unchecked index, giving `*(u32*)(0x75b80 + 4*band) = 0xffffffff`, twice, plus an
arbitrary byte write at 0x1f65c on its keep branch. On a core with no DART.

**It is nevertheless dead, for a structural reason in the firmware's own control flow.**
An overflow always implies the DM is rejected (overflow needs size > 0x13ff8; acceptance
needs numProb + hopIdx < 0x3ff4 — mutually exclusive). The reject path stamps a state
field: 0x11cb6 `str.w r0,[r8,#0x30]` writes **5** into `[sp+0x7c]+0x30`. Later, on both
paths, 0x121b0 reloads that field and 0x121b2/0x121b4 branch away unless it is **4**, to
0x12250 and thence 0x128e0 — past the entire band-reconstruction block 0x12390..0x128b0.
That block has exactly one entry edge (0x122c4), and it holds the only four calls to the
band allocator 0x10a30, which is the only setter of bit 2 of the per-band flags byte at
0x710b0. Both enqueue gates require that bit (0x1e59a and 0x1e7ba, `== 4`). So on a
failed-DM boot nothing is ever enqueued, `count` stays 0, and the duster's guard at
0x1e714 skips both loops — the count-ignoring reader never runs. It cannot be deferred to
a later boot either: DM_Decompress runs once per boot and the ASP bss is re-zeroed every
boot because iBoot re-pushes the firmware. **Overflow and a usable queue cannot coexist.**

The duster itself is not in the BG task, incidentally — the ASP task table at blob 0x404f4
(stride 12, {entry, name, stack}) registers eight tasks: Null 0x3007d, Update 0x3dc19,
Cmd 0x3ad1d, BG 0x10c75, Push 0x2214d, PreNand 0x3b9ad, PostNand 0x38e21, and
**Timer 0x13879**, which ticks flow 0 unconditionally. The tick survives the failure; the
precondition for it to do anything does not.

### Two near-misses worth keeping — both would have cost the board
1. **Do not raise `eSize[DM]` in UtilDM.** It was proposed as the way to make the
   overflowing bytes come from our flash rather than adjacent staging heap (the DM read
   stages only `eSize[DM]` = 12 pages = 0xC000, while the upgrade memcpy reads 0x13fd4,
   so today the overflow data is uncontrolled). UtilDM has **no per-element start-LBA
   array**: it holds major/minor at +0x00/+0x01, `eSize[0..9]` as u16 at +0x02..0x15, an
   **ordered element-index list** `02 03 04 05 06 07 0b 0c` at +0x1a..0x21, geometry at
   +0x9a, and a u32 generation at +0xac. Element starts are derived by **accumulating
   eSize over that list**, so bumping DM from 12 to 20 pages shifts CTRLBITS, EFFACE,
   NVRAM and SYSCFG by 8 pages and the ASP would then read NVRAM and SysCfg from the
   wrong offsets. UtilDM is the authority for the element layout; there is no ASP-side
   registration table comparable to iBoot's 0x830006144-0x830006210.
   Generation selection, reusable: 0x2ec44/0x2ec48 load the candidate and accepted
   generations from +0xac, 0x2ec4c compares, 0x2ec4e `bhs` — unsigned, highest wins, ties
   accept.
2. **The hazard in that write primitive was never the 4-byte write.** The injected word is
   consumed as a *band number* by erase machinery: the dequeue returns it to its caller for
   erase (0x1f5dc) and publishes it to 0x92098+0x19c (0x1f6e8). No ASP bss address is
   provably inert from static analysis — 405 distinct global bases are referenced from
   literal pools in [0x48000,0xF0BC4), but large arrays are referenced only by their base
   (0x7e028 alone spans 0x14000), so a gap between bases is not free space. The only
   idempotent-looking class is slots the firmware already fills with -1 (0x120da, for
   i = DM[8]..DM[0x10]) and those are **valid band numbers**, so writing them risks a real
   band erase.
3. **Any future ASP-firmware experiment must be a tethered iBEC boot, not a flash boot.**
   The ASP firmware rides inside iBoot/iBEC, so with the research board's LLB first byte
   inverted (iBoot never runs) the firmware is never loaded and the DM is never parsed by
   it at all. A tethered iBEC boot needs no LLB restore and so preserves the 7-second
   ROM-DFU fallback. Evidence the blob is in iBEC: only iBoot.dec contains the `fwsg`
   magic in cleartext, at file offset 692768 = 0x49000 + 0x60220, and
   iBEC.b238a.RELEASE.im4p and iBoot.b238a.RELEASE.im4p are both 692959 bytes — the iBEC
   im4p shows no `fwsg` only because it is still encrypted.

### Methodological note, the third of the day
Graph reachability is not path reachability. A CFG walker reported the band allocator
reachable from the failure path because it explores both sides of every conditional,
including both sides of the 0x121b4 branch that the state value pins. Edge analysis
found the kill. Use edge analysis on questions of the form "can this state reach that
code".

## Pattern sweep of the AArch64 loaders, 2026-11-24 — clean negative with stated coverage

Three bug shapes were generalised from the day's real findings and swept mechanically:
(1) a length written back through a caller's out-pointer on a path that does not write
the data; (2) a bound computed on a size a later transform changes; (3) a sentinel
special-cased so that it skips a bounds test. Each detector was calibrated to
independently rediscover the finding it came from before its output was trusted.

**Result: the pattern does not recur. The two known AArch64 instances are isolated.**
LLB is clean of all three shapes in both build trains.

Coverage, which is where a mechanical sweep's value lives. `dis/*.funcs.tsv`'s
bl-target boundaries own only 54,638 of 92,413 decodable iBoot-5540 instructions, with
2,032 claimed by more than one body — unusable for this. A proper ownership pass
(bl targets; 64-bit words pointing at an instruction whose predecessor is a terminator
or data, which is what finds indirect-call-only functions such as the filesystem op
table at 0x830046838; unowned branch targets; post-terminator instructions; heads of
remaining runs) reached **zero unowned instructions** in all six binaries:
  iBoot-5540          65725 insns, 4205 funcs
  LLB-5540            36736 insns, 1736 funcs
  iBoot-4076-15C4097d 56823 insns, 3124 funcs
  LLB-4076-15C4097d   35683 insns, 1419 funcs
  iBEC-20L497         80515 insns, 4983 funcs
  iBSS-20L497         42446 insns, 1951 funcs

Variant 1: 982 out-param integer stores in iBoot-5540, 779 triples, 69 consumed by any
caller — and in the precise form (store reachable both through and around its own
capacity guard) 18 candidates reduce to **one real**, N1, plus two Mach-O load cursors
and fifteen LZFSE state saves. 4076 has the same single instance at 0x830016c54.
**LLB-5540 and LLB-4076: zero.** Worth noting `image_load 0x830011ecc` is the *correct*
form of this shape — its error path writes `str xzr,[x19]`, a zero, not the requested
size — and `fs_load_file 0x83002301c` writes the size only after confirming the read
returned exactly the requested count.

Variant 2: the allocator was located mechanically in all six binaries by its n*size
guard idiom; 292 allocation sites examined, 13 rescale hits, and **the SEP hex-decode
at 0x83002fa64 is the only bug** (and it is unreachable — see the correction above).
The other twelve are correct, including three genuinely expanding allocations in the
4076 USB descriptor builders that are exactly sized. A second probe for the ASP-species
shape (len <= cap checked but copied to base+off) found 58 such copies in iBoot-5540 and
20 in LLB-5540, all bounded — notably 0x830009c7c inside the verify worker, which
carries full 64-bit wrap checks at 0x830009c44 and 0x830009c4c immediately before.

Variant 3: 17 asymmetric sentinel comparisons in iBoot-5540, 3 in LLB-5540, 11 in
iBoot-4076, **0 in LLB-4076**; the only real ones are the 0xFFFE sentinel at
0x830017134 and its source in get_val 0x830017408, plus the 4076 twins. The rest are
memcmp/strcmp byte-difference idioms, a NUL test in the APFS path walker, a two-value
enum check, a hardware status word, and correct `cmp #0xff / b.hi -> error` bounds.

Limitations, so the coverage claim is not over-read: the dataflow is intraprocedural;
an out-param produced by a nested call is not modelled; loop-carried values appear as
their initial value; the call graph has direct and tail-call edges only, so the
zero-unowned figure is about **code ownership**, which is complete, not call-graph
reachability, which is not; MMIO-sourced values were treated as not attacker-controlled.

### Incidental facts from the sweep, worth keeping
- **ASP blob descriptors, located mechanically** (a {addr,size} pair where
  (addr-base)+size == filesize): iBoot-5540 file 0x407a8 = {0x830049000, 0x60240};
  iBoot-4076-15C4097d file 0x3e4b0 = {0x83003f000, 0x60240}; **iBoot-4076-15D59
  file 0x3e4b0 = {0x83003f000, 0x61240}**; iBEC-20L497 file 0x4d1b8 =
  {0x83005a000, 0x60240}. No such descriptor in LLB-5540, LLB-4076 or iBSS-20L497.
  Two consequences: iBEC-20L497 does carry an ASP blob, at 0x83005a000 — the
  address-level confirmation that the firmware rides inside iBEC; and **15D59 ships a
  different-sized ASP firmware from every other build here**, so diffing the blob
  between the two 11.2-era builds is a cheap way to see what Apple changed in it.
- **A latent 32-bit-store / 64-bit-read hazard at 0x830031850** (Img4 property lookup).
  Its 0x18-byte output struct is seeded from a poison template at 0x8300452f0
  (`aa aa aa aa aa aa aa aa` x3), the type and length fields are filled with 32-bit
  stores (`str w17,[sp,#0x18]`), and the struct is copied out with 64-bit stores
  (`stp x10,x9,[x2,#8]` at 0x830031938). So the returned length carries 0xAAAAAAAA in
  its top 32 bits, harmless only because both current callers read it with `ldr w` and
  clamp. Any future `ldr x` consumer would see ~0xAAAAAAAA00000000 as a length.
- LLB-5540's calloc guard is 0x18039a170 (not 0x18039a168); malloc 0x180399fbc.

### Where that leaves the hunt
The premise that the remaining bug would be a recurring pattern rather than a specific
place is **not supported for the AArch64 loaders**. The one body of pre-verification
code this sweep structurally could not reach is the ARM32 ASP/ANS RTKit blob
(iBoot-5540 file 0x49000-0xa9240) — and that is where the only other real instance of
variant 2 actually lives. Only the defect-map, UtilDM and SysCfg parsers inside it have
been read; the PANICLOG and CLOG elements it also parses, both writable from Linux, have
not. That blob is now the last unaudited surface on the device.

## Fuzzing the Image4/DER subtree, 2026-11-24 — no findings, and the coverage honestly stated

A coverage-guided, memory-safety-instrumented fuzzer was built against iBoot-5540's
Image4/DER parsing and driven end-to-end from container bytes. Harness: poisoned guard
bands after every heap allocation, the container placed flush against an unmapped guard
page so any read past its end is reported exactly, a per-basic-block iteration ceiling
as an unbounded-loop detector, an absurd-allocation detector, and basic-block coverage.
It flags out-of-bounds reads and writes, not only faults. Validated both ways before
use: a genuine container runs clean (one 38-byte allocation, no findings), and an
injected positive control is detected (OOB-WRITE-HEAP at 0x83002fbe4).

Two entry points were driven: the SEP parse at 0x83002fa64, and the generic image path
via image_load 0x830011ecc with a 'Memz' handle whose flags omit 0x100, so the full
worker 0x8300093ec runs including the IM4P peek at 0x83000879c with allow_partial=1.

Result after ~214,000 executions, ~58,000 of them past the schema gate: **zero
out-of-bounds reads, zero out-of-bounds writes, zero unbounded loops, zero absurd
allocations** — at a measured **19.0% (SEP path) and 26.3% (generic path) of 1250
reachable Image4/DER basic blocks**. The denominator was computed, not asserted: the
call-graph closure of the two entry points, following both bl edges and outlined
tail-thunks, is 578 functions / 5872 blocks, intersected with the Image4/DER ranges.
**That coverage is not high enough for the negative to carry weight, and it should not
be read as one.**

Two things that moved coverage and one that did not: un-stubbing 0x830032b9c (manifest
property compare) and 0x830033b50 (trust evaluation) took the control from 160 to 245
blocks but did not move fuzz coverage at all; **seeding the corpus from a real container
was the bigger lever**, because a grammar generator alone never reaches the depth a
genuine container does. A purely structural mutator managed 104,000 executions at only
188 blocks — it was dying at the schema gate, so that figure was close to meaningless.

### Closed by this work
- **iBoot-4076's three IM4P-peek callers all carry the size recheck.** The peek
  0x830007a58 stores the total with a 32-bit `str w8,[x20]` at 0x830007ac4, and each
  caller bounds it before use: caller A 0x8300083e0 (in 0x83000830c, image registration)
  rechecks with `ldr w8,[sp,#0x10] / cmp x8,x27 / b.hi`, load width matching store width;
  caller B 0x8300087e8 (in 0x8300085f0, the worker — note the identical raw-flag bypass
  `ldrb w8,[x26,#0xd]; tbnz w8,#0` at 0x8300087d0) rechecks 64-bit at 0x83000882c with
  `ldr x8,[sp,#0x70] / subs x1,x27,x8 / b.hs`, failing closed if the slot's upper half is
  not pre-zeroed; caller C 0x830008fec (in 0x830008f08) rechecks with
  `ldr w8,[sp,#0x14] / cmp x8,x19 / b.ls`. In every case the attacker can only
  **understate** the total, never overstate it. The "three callers instead of one"
  hypothesis is dead.
- **4076 has no SEP firmware path at all** — `sepfw-path`, `sep-firmware` and
  `rsepfirmware` are all absent from it. That surface is a 5540-era feature, so 4076 is
  only interesting via the generic image path.
- **The decompressor is post-authentication, confirmed from a second direction.** In the
  worker 0x8300093ec the trust verify `bl 0x830033e38` is at 0x83000973c and failure
  branches straight to the error sink at 0x830009748; the payload fetch
  (0x830009828 bl 0x830032f0c) and every compression branch (0x830009af0, 0x830009b24,
  lzss 0x830026878, lzfse 0x83003a79c) are all downstream of it.
- A harness lesson for anyone emulating this code: it reads the MMIO fuse/chip-ID block
  at 0x2_0E02A000 from 0x83000e738, so the 0x2_0E0x_xxxx register range must be mapped
  or whitelisted. A fault there is a harness gap, not a finding.

### The one piece left on this surface
The uncovered three-quarters is overwhelmingly the **trust-evaluation and X.509
certificate-chain subtree below 0x830033e38** (LLB 0x18039ecf0). The previous harness
emitted random bytes for the IM4M slot, so they died at the first structural check and
the certificate parsing is essentially untouched. Reaching it needs a grammar that emits
**structurally plausible manifests** — the signed SET and its property dictionaries, the
certificate chain as a SEQUENCE of certificates, and inside each certificate the real
X.509 shape (version, serial, algorithm OIDs, issuer/subject RDNs, validity, an RSA
SubjectPublicKeyInfo, extensions with OIDs and critical flags). **It does not need valid
signatures, only valid structure, because this DER parsing runs before the signature
math.** That is a large body of ASN.1 parsing over fully attacker-controlled bytes on the
path every image takes, and it is the last unaudited part of this surface.

## The ASP/ANS firmware, audited whole, 2026-11-24 — negative. The convergent lead is closed.

Three detectors rebuilt for ARM32 Thumb-2 and run over **98.40% of the firmware's
__TEXT** (289,082 of 293,776 bytes owned by a recovered instruction; of the 4,694
unowned bytes, 4,164 are pointer tables, 490 are sub-4-byte inter-function padding, 16
are zero runs, and only **24 bytes in 6 runs** are unclassified). angr alone owned only
80.26%, so two growing passes were needed before any coverage claim was worth making:
128,799 instructions, 2,019 function starts, 1,950 functions analysed per detector.

Calibration was stronger than on the AArch64 side. The net-growth detector, run with no
hint where to look, reported exactly one hit and it was the known defect-map bug —
bound on the root size, length `S-0x2c`, destination `+0x34`, net `+8` — and mutating
only the destination immediate in the real blob moved the reported net to `+20`
(`0x34`->`0x40`) and to **zero hits** when the bug is removed (`0x34`->`0x2c`). A
positive and a negative control on the real binary. The sentinel detector independently
landed on the same bug from the other side, at `0x11902 cmp r0,#0x65`, the on-flash DM
version word — a magic value that makes two versions place different bounds on the same
copied size.

**Result: no new instance of any of the three shapes.** 544 bulk-copy and allocation
sites reduce to the one known bug; 1,338 equality tests on loaded values reduce to that
same version word plus one detector artefact; and the out-pointer shape is **absent
entirely** — all 14 precise-shape hits resolve to fields of one long-lived
element-read descriptor struct threaded through `Util_Read` -> `Util_Find_Fast_Scan`
-> `Util_Find_SysCfg` -> `Util_Erase`, and those fields are an LBA, a packed op/status
word and a packed error halfword, not lengths. This layer keeps lengths inside the
descriptor (`+0x10` eSize, `+0x14` staging page) where the same code writes and consumes
them.

### Element-by-element inventory — which elements buy parser reach at all
Name table re-read from the image at blob `0x4c990`; the type argument resolved by
dataflow at all 7 call sites of the descriptor helper `0x2e100`.
  0 LLB       — content not interpreted; write path only
  1 FW        — not interpreted; the "unrecognized tag" assert is not an on-flash parse
                (the tag is a descriptor field required to be 0xb0/0x85)
  2 UTILDM    — interpreted heavily; has the validation gap behind R-1 below
  3 DM        — interpreted; the known bug, chain proven dead
  4 CTRLBITS  — opaque handle, not interpreted
  5 EFFACE    — opaque handle, not interpreted (new; extends the CTRLBITS negative)
  6 NVRAM     — opaque handle; iBoot is the only NVRAM parser
  7 SYSCFG    — location only: length capped at 0x100 sectors, LBA must be 0, and the
                descriptor size must *equal* UtilDM's eSize[SYSCFG]
  8 PANICLOG  — **write-only from the ASP's side.** Util_PanicLog's only trace is a slot
                allocation failure; nothing reads the element back. **Writing the
                panic-log element from Linux buys no ASP parser reach — strike it off.**
  9 CLOG      — a whole subsystem, and a closed door on provenance: eSize[CLOG]=0, the
                clog lives in bands found by scanning page metadata for LBA_TOKEN_CLOG
                and written by the ASP itself, so its content is not in an element we can
                write; and the only clog inputs we can choose are two UtilDM bytes,
                clogMajor `+0x1b4` (must equal 0xf exactly) and clogMinor `+0x1b5` (must
                be >= 2), and clogMinor is read in exactly four places firmware-wide and
                **never selects a structure layout or a size**. So the legacy-migration
                path cannot be used to reinterpret band bytes under a different layout.
                Worth recording because CLOG has both features that produced the DM bug
                — a media-vs-firmware version and a legacy migration path.

### Cross-build diff of the ASP blob, 15C4097d vs 15D59 — nothing
The 0x1000 size difference is not new code: __TEXT grew by exactly **0x20 bytes** and the
rest is padding because __TEXT crossed a page boundary and pushed __DATA from 0x48000 to
0x49000. Every one of 102,774 instructions was compared at its shifted address in four
layers: 87,429 identical, 1,580 same-instruction, 1,290 data/pointer relocations, 622
mapped literal/branch, 45 movw relocations, **32 real differences** — three of them
decoder artefacts and all 29 others inside one function (15C `0x1f591`, whose 5540 twin
asserts against `src/aspcore/core/gc.c`), of which 26 are a register renumbering and a
stack-local swap. The substance is 28 inserted bytes, and it is **not a security fix**:
the polarity is wrong (it adds a way to *reach* a work block, so 15D does strictly more
work — a bounds fix narrows a path, this widens one), the index it introduces was
already bounded identically in 15C (`cmp r1,#0x3f / bhi`), and it is gated on TLC
(`geom[0x234]==3`) which neither real pod is. Reading: a GC policy addition for TLC
parts. Don't spend more on the 4076 ASP blobs.

### R-1, a new out-of-bounds write, reported without inflation
UtilDM's validated set, enumerated from `UtilDM_PostProcess 0x2eabc`, is `[0]==8`,
`[1] <= *(g+0x74)`, `+0x9c`/`+0x9e`/`+0x9f` equal to chip geometry, the descriptor LBA
and the generation. **Not validated: `+0x9a` (u16), `+0xa2` (u8), the `+0x1a` slot list,
and eSize[].** In the utility-region commit worker `0x2c760`:
  0x2c9e2 ldrb.w r0,[r8,#0xa2]       ; slot number, from flash
  0x2c9ec bl 0x2e055 -> 0x2d4a4      ; adds a skip count bounded only by UtilDM[0x9a]
  0x2c9fc strh.w r1,[r4,r0,lsl #1]   ; *(u16*)(UtilDM+0xb4 + 2*idx) += 1
The array is pinned at 0x80 u16 entries (`+0xb4`..`+0x1b4`) by its own initialiser
(`0x2ea2a cmp r2,#0x80`). `UtilDM[0xa2]=0xff` alone gives idx ~0x206; a large skip count
takes the write out of the 0x1000 copy into the adjacent bss struct at a 2-byte-aligned
offset of choice. It is a real omission: every *other* consumer of `0x2d4a4`'s return is
either truncated to 8 bits or bounded (the real capacity check elsewhere is
`cmp #0x840 / bhs` at `0x12930` and `0x2d27a`); these two sites are the only raw uses.
Reachability resolved: `0x2c760` is posted as a work item, run on a panic-log save, LLB
write, FW write, Util_Expand or clog clear, all triggerable from Linux, and the ordering
edge analysis confirms the flash values reach `0xdb1f0` before the load sites.
**Why it is not a win**: the primitive is `+1` to a chosen u16 — not a pointer, not a
length, not an arbitrary value — and no consumer has been found that a monotone
increment breaks; it needs a UtilDM write, so research board only; and it is reachable
only while the AP already runs our Linux, making it win-condition 3 at best, not an
untether. The cheap next step, if anyone wants it, is a field inventory of the struct at
`0xdc1f0` looking for a length or flag word that a `+1` would break.
Also recorded: a boot-reachable OOB **read** at `0x11488`, a loop bounded only by the
same unvalidated `UtilDM[0x9a]`, reading up to ~0xF000 bytes past the 0x1000 copy —
harmless because the product is truncated to 8 bits and stored as a status byte.

### Corrections
- iBoot-4076-15C4097d's ASP blob is the **same size as 5540's (0x60240) but not
  byte-identical**; `fwsg` footers at `0x60220`/`0x61220`; the 4076 segment tables report
  `memsz=0` where 5540 reports real values.
- Decode-layer traps for anyone reusing ARM32 tooling: `blo`/`bls`/`blt`/`ble` get
  misclassified as calls by a naive `bl` prefix test, which truncates every function body
  at the first such branch; the bl-target boundary heuristic breaks inside the big inlined
  parser at `0x10c75`, so angr's partition is the authority for body membership; and a
  dataflow worklist that merges a node's input with its own previous value silently drops
  offsets on linear values.

## The trust-evaluation / X.509 subtree, 2026-11-24 — negative, and the best-covered one

The last unaudited parsing on the device. Result: **0 out-of-bounds reads, 0 out-of-bounds
writes, 0 unbounded loops, 0 wrap traps hit**, at 91.6% coverage of the
pre-authentication half, with every remaining uncovered block individually accounted for.
(The agent's own execution totals were lost when the session restarted mid-sentence; the
verdict and the coverage figures below are from its notes, written as it went, at
/home/claude/hunt/notes/S-manifest.md.)

### The structural finding worth keeping: the certificate chain is unauthenticated
`IM4M ::= SEQUENCE { IA5String "IM4M", INTEGER(<=2), SET body, OCTETSTRING sig,
SEQUENCE certs }` — schema table at iBoot `0x8300458d0`, 24-byte DERItemSpec stride, with
field [2] carrying DER_DEC_SAVE_DER. In `Img4DecodeEvaluateTrust 0x830033e38`:
`0x830033f74` digests field **[2] only**, and `0x830033f9c` verifies that digest against
field [3]. **Field [4], the certificate chain, is never digested.** So a genuine signed
IM4M can keep its body and signature byte-identical while its entire certificate chain is
replaced with arbitrary DER — and the chain parse at `0x830034338` runs at **step 3** of
the evaluator, strictly before the signature math at step 5. Genuinely attacker-controlled
pre-authentication DER.
It is a parsing surface and not a trust surface, because the chain is verified
cert-by-cert against an Apple Root CA baked into the image: a 1215-byte DER certificate at
`0x830045308` (length at `*(0x8300457c8) = 0x4bf`) sits at index 0 of the chain array, and
`0x8300348fc` digests each TBSCertificate and calls the parent's signature check at
`0x830034a20`.
Order inside the evaluator, for reference: 1 digest the whole IM4M -> ctx+0x148
(`0x830033ee8`); 2 cached-hash shortcut (`0x830033f08`); **3 cert-chain parse
(`0x830033f48 blr` -> `0x830034338`)**; 4 digest the body SET (`0x830033f74`);
5 RSA signature check (`0x830033f9c` -> `0x8300342a4`); 6 manifest body decode
(`0x830033fbc`); 7 per-object property lookup (`0x830033ff4`, tag `0xE0000000|type`);
8 digest the IM4P (`0x830034060`); 9 property iteration (`0x830034080`/`0x830034098`).
Two vtables drive it: policy ops at `0x8300407f0` {+0x00 `0x830008ab0` property callback,
+0x08 `0x830009108` cached-hash lookup, +0x10 **NULL**} and crypto ops at `0x830040f20`
{+0x00 digest `0x830034aa8`, +0x08 cert chain `0x830034338`, +0x10 sigverify `0x8300342a4`,
+0x18 record-trusted `0x830033928`, +0x20 digest descriptor `0x830040f08`, whose value must
be <= 0x30}.

### Hand audit of the pre-authentication certificate path — strict everywhere
No instance of any of the five shapes that produced real defects on this project. The
chain splitter `0x830034b18` calls the DER decoder in **strict** mode (x2 = NULL, so an
over-long declared length is rejected, not clamped), bounds the index with `cmp w19,
w21,uxth / b.ls` and then requires `index == 3` at the end — i.e. **exactly two attacker
certificates, no more and no fewer** — and caps each at `< 0x20000`. `0x830034694` has
four `mvn`/`cmp`/`b.hi -> brk #1` wrap traps per iteration and passes explicit
output-struct sizes (0x30/0xa0/0x20). `DERParseSequenceContent 0x8300352b0` zeroes its
output first, bounds the index by the schema item count, and takes the **store offset from
an image constant** (`mul x9,x8,#0x18 ; ldr x9,[x19,x9]`) — nothing from the container
reaches a destination offset; end-of-sequence is exact, with no trailing bytes tolerated.
The signature-algorithm parameters must be exactly DER NULL. The RSA path truncates three
lengths to 32 bits (`0x8300342b0`/`b8`/`c0`, and `0x830034394` on the chain length) but
every matching load is also 32-bit and the sources are bounded well below 2^32, so the
store/load width mismatch that bit elsewhere does not bite; the modulus is bounded to
`nwords <= 0x40` with **four** independent overflow guards on `2*nwords*8`. The one place a
certificate-derived length meets a differently-sized buffer — the RSA exponent import
`0x83003c648` — returns -7 unless every excess leading byte is zero, and both callers
check it.

### Coverage, with the denominator earned rather than asserted
A `funcs.tsv`-based closure reports **0 blocks** for the cert-chain parser, the digest and
the signature verifier, because the whole evaluator dispatches through those two vtables
with `blr x8` and none of those functions is ever a `bl` target. A recursive-descent CFG
was built instead. Figures: D_DER 417 blocks (crypto vtable closure, the parser proper),
D_PRE 296 (reachable before the signature check), D_POST 121, D_CC 208 (the chain parser
subtree). A third figure, D_LIB 588, includes the policy callbacks and was explicitly
**not** quoted as the answer, because their closures drag in printf, the environment and
the device tree — graph reachability is not path reachability, and that is what it looks
like in numbers.
Reached: D_DER 87.1%, D_PRE 89.5% raw and **91.6% corrected**, D_POST 81.0%, D_CC 92.8%.
The correction is sound: the CFG splits blocks at every branch *target*, while unicorn only
reports blocks actually jumped to, so 6 of the 31 nominally-uncovered D_PRE blocks are
fall-through artefacts (each verified: the preceding instruction is not a branch and the
straight-line run into it executed).
**All 25 remaining uncovered pre-authentication blocks were accounted for individually, and
none is reachable from container bytes**: 4 are `brk #1` wrap traps whose reachability
would itself be the finding; 2 are the stack-check stub; 3 are null-argument tails on image
constants; `0x830034114` is the 3072-bit RSA branch, dead because its only caller passes
`w4 = 0x1000`; `0x830033f10`/`0x8300340b8` are the cached-hash shortcut, gated on a flag in
iBoot's own stack frame; `0x830033fe4`/`0x830033ff0` are gated on a vtable slot that is NULL
in this image; `0x830034e2c`/`0x830034e34` are the non-strict decoder path, and every caller
here is strict; the rest are error tails. One block was genuinely missed and then hit
deliberately — `0x830034fdc`, the `len <= 1` branch of the BIT STRING unused-bits extractor
— with four variants (len 0, and len 1 with unused = 0 / 7 / 255), all clean.

### Two harness lessons that would otherwise produce wrong answers
1. **The parse runs on a copy, not on the input.** The worker copies the container out of
   the handle into the destination buffer (`0x830009578 bl 0x830009d88`) and *everything*
   downstream parses `dst` — the peek at `0x8300095f0`, Img4DecodeInit at `0x83000965c`,
   the IM4M decode, the chain. A guard page placed only after the original input would let
   an over-read past the container end land in mapped memory and be missed silently. The
   destination has to be the guarded buffer.
2. **A fixed-size stub write manufactures fake findings.** Stubbing the digest with a fixed
   0x40-byte write produced a stack-cookie failure on a perfectly valid container. The
   digest length here is `*(0x830040f08) = 0x14` (SHA-1), checked at `0x830034af0`, and some
   destinations are 20-byte stack slots. Stubs must honour the real length.
Also: `maxlen` must be >= the container size (`0x830011f30` and `0x830009480`), and
`ntypes = 0` skips the caller's allowed-type list (`0x8300096bc cbz w23`), which lets one
driver feed containers of any declared type.

### What actually moved coverage, for anyone fuzzing this code again
Two measured things. **The mutator must re-encode ancestor lengths** — editing bytes in
place changes a node's size without updating its parents, so the container dies at the
peek's `total <= handle->size` test long before the manifest code runs; a parse-mutate-
reserialise mutator got **98% of mutated inputs into the chain parser against 17% for the
grammar generator alone**. And **long-form DER lengths must be suppressed at the outer
three levels** — the peek `0x83000879c` uses a strict canonical-length decoder, so a
redundant long-form length on the outer SEQUENCE, the "IMG4" string or the IM4P SEQUENCE is
rejected with 0x40040021: 0 of 150 generated containers reached the chain with long-form
allowed everywhere, 70 of 150 with it suppressed outside the IM4M. Separately, narrow
per-address unicorn hooks instead of one callback per instruction gave a measured **47x
speedup** (0.89 s/exec -> 0.019 s/exec), and the crypto is ~90% of the emulated instruction
count (751,638 of 828,334 instructions for one genuine container sit in the bignum helpers
`0x83003b900`/`0x83003c600`), so stopping at the signature-verify entry buys ~20x.

---

## 2026-11-24 (late) — the SecureROM aperture is closed before a loaded image runs

Three measurements, all on the research pod, ECID <ECID_POD1>.

### 1. SRAM 0x1800a0000 + 0x20000 (T2c) holds nothing

Dumped and checksum-verified on device (`@@ROMDUMP END 0000000000020000
<SRAM_CKSUM>`, 8192/8192 lines, sha256
<SRAM_SHA256>). Entropy is
7.9-8.0 bits/byte in every 8 KiB block, the longest run that disassembles as
AArch64 without hitting an undefined encoding is 20 bytes, and there is not one
printable string of 6+ characters in 128 KiB. gaster's `boot_tramp_end =
0x1800E1000` does say the ROM stages a handoff trampoline just below that
address, but whatever was there is not resident by the time our payload runs.
Not ROM code. Lead closed.

### 2. The t3 fault was DC IVAC against read-only text

`esr=0x9600014f` -> EC 0x25 (data abort, same EL), DFSC 0x0f (permission fault,
level 3), WnR=1, `far=0x1803a8d40`, `elr=0x1803a84c0`. 0x1803a84c0 is the
`dc ivac, x20` in the late-print path and 0x1803a8d40 is the `ecap` buffer: both
sit in LLB's class-7 text mapping [0x180380000, 0x1803a9000), which is read-only
at EL1 with WXN set, and **DC IVAC requires write permission** (DC CVAC/CVAU
need only read, but a clean would write the stale line back over the data).
Fix: delete the invalidate from the print path. The entry stub already
invalidates the range before storing into it, and it runs with the MMU off, so a
cached read later cannot see a stale line from the ROM's image load. One-line
change; the run then completed.

### 3. The pod enters a loaded image at EL3 with the MMU off — and the ROM is already gone

Captured by the first instruction of the image (entry hook at file 0x0, printed
later from the 0x110bc hook):

    sctlr_el1 = 0x30d50800     M=0, C=0, I=0  -> MMU OFF, caches off
    ttbr0_el1 = 0x0
    ttbr1_el1 = 0x0
    tcr_el1   = 0x180000000    reset value
    vbar_el1  = 0x0
    CurrentEL = 0x0c           -> EL3
    sp        = 0x0
    entry pc  = 0x180380000

Two things follow. First, **the boot ROM hands off at EL3 with physical
addressing and no stack.** LLB installs its own tables, drops to EL1, sets WXN,
and then deliberately `eret`s to EL0 for most of its work — which is why every
`mrs` later in the image is undefined and why `svc #0` was needed to get back to
EL1. At entry none of that applies: EL3, flat physical, nothing read-only.

Second, with that unrestricted physical access:

    phys 0x180080000  ->  00500c80 01000000 00000408 02000000     (real SRAM;
                          63000000 ffffffff 24000000 27000000      byte-identical
                                                                   to the earlier
                                                                   0x180080000 dump)
    phys 0x100000000  ->  256 bytes of 0x00

So the zeros we saw at 0x100000000 from EL1 under LLB's tables were not a
mapping problem. **The SecureROM aperture is closed before the first instruction
of a loaded image executes.** No payload, at any exception level, with any page
tables, can read the ROM after handoff. This is the same pattern as the demotion
lock (`[0x20E02A004] = 0xA0000000` measured with our own lock neutered): the ROM
latches its lockdowns before it jumps.

### What this leaves

The ROM can only be read while the ROM is the running code — i.e. from inside
checkm8. gaster's request handler
(`payload_handle_checkm8_request.S`) already has the primitive: its MEMC command
reads dst/src/len from `insecure_memory_base+0x10/+0x18/+0x20`, calls the ROM's
own `memcpy` (0x100010E70 on cpid 0x7000), and ships `insecure_memory_base` back
over EP0. Pointing src at an arbitrary address and dst at
`insecure_memory_base+0x10` reads that address with the ROM's tables live. For
cpid 0x7000 gaster does no TTBR0 patching at all (that is A11-only), so the
ROM's own mapping — in which 0x100000000 is readable and executable — is what is
active.

Added as `gaster peek ADDR LEN OUT` in ~/homepod/multipod/rompeek (a copy of the
gaster tree with ~90 lines added: `gaster_memcpy` + `gaster_peek`, 0x1000 per
request, nothing else changed), and as a `rom-peek ADDR LEN OUT` action in
hp-runner.command. Read-only in both.

---

## 2026-11-24 (night) — THE SECUREROM IS DUMPED

`gaster peek` worked first try. 131072 bytes from 0x100000000, read with the boot
ROM still the running code.

    SecureROM for t7000si, Copyright 2013, Apple Inc.     @ 0x100000200
    RELEASE                                              @ 0x100000240
    iBoot-1992.0.0.1.19                                  @ 0x100000280

    sha256 5c4fc92ba4a023978dfed91720ceea824d8896e1fb10bb617223a8b7923d83d8
    -> ~/homepod/multipod/rom/   (Apple's code: never commit, never post)

Verification, four independent ways:
* two separate reads, byte-identical;
* 0x100020000 reads all zero, so the ROM is exactly 128 KiB; content ends at
  0x1000197c4;
* five of the six symbol addresses gaster hardcodes for
  `SRTG:[iBoot-1992.0.0.1.19]` land exactly on `stp x29, x30, [sp, #-0x10]! ;
  mov x29, sp` prologues — aes_crypto_cmd 0x10000DA90,
  usb_create_string_descriptor 0x10000E074, usb_core_do_transfer 0x10000EBB4,
  handle_interface_request 0x10000EEE4, memcpy 0x100010E70 (whose third
  instruction is `sub x3, x0, x1`);
* `patch_addr` 0x100007E98 lands on the `mov x0, #0` that checkm8 patches.

419 functions by our indexer, 489 by Ghidra; full decompilation in
hunt/dis/SecureROM.decomp.c.

### The ROM's boot path

`0x1000004e8` is the boot task. It probes boot devices and dispatches through a
4-entry jump table at 0x100000824 (targets 0x100000698 / 0x1000006ac /
0x1000006ec / 0x100000708).

**Flash arm, 0x1000006ac** — the path that runs on every cold power-on:

    bl 0x100001b14
    read_llb(dst = 0x180380000, size = 0x80000)        ; 0x100001b4c
      -> result must be <= 0x80000 (else panic at 0x10000080c) and non-zero
    img4_open(0x180380000, read_len, flags = 4)        ; 0x10000f610
    [sp+0x2c] = 'illb' (0x696c6c62)
    [handle+0x10] |= ((flag & 1) << 1) ^ 0xb
    img4_eval(handle, &type4cc, 1, 0, &payload_ptr, &payload_len = 0x80000)  ; 0x10000f52c
    img4_close(handle)                                 ; 0x10000f65c
    -> bl 0x10000bd7c ; bl 0x100008a84
    -> handoff: 0x10000ab7c(0, ret, 0x180380000, 0)

**USB/DFU arm, 0x100000708** — the same funnel with three differences:

    usb_dfu_recv(0x180380000, 0x80000)                 ; 0x10000edbc
      -> length checked >= 0 and <= 0x80000
    img4_open(0x180380000, recv_len, flags = 0)
    [sp+0x2c] = 'ibss' (0x69627373)
    img4_eval(..., payload_len = the actual received length)

Note the asymmetry: **the flash path hands img4_eval the constant 0x80000, the
USB path hands it the real length.** Under audit.

So both paths load to 0x180380000 — the same address as a DFU image and the same
address gaster uses for `insecure_memory_base`.

### read_llb takes all of its bounds out of unauthenticated flash

Before reading LLB, the ROM reads one flash page into SRAM at **0x180082050** — a
UtilDM structure — and prints its revision. It then uses:

    [0x180082050 + 0x02]  halfword  "written size" in 4 KiB pages; the requested
                                    page count is clamped DOWN to it
                                    ("Trimmed size to written size of %5d")
    [0x180082050 + 0x9e]  byte      max pages per block-read request, used as
                                    w22 = min(remaining, this) in the loop at
                                    0x100001c4c..0x100001c84

Block read: `0x100001720(w0, w1, arg2, count, dst, desc)`; selector written to
[0x180083050] is 0x0ff00004 for UtilDM and 0x0ff00002 for LLB. The loop advances
arg2 by exactly 1 per iteration while advancing dst by count<<12 — whether arg2
is an LBA or a chunk index is under audit.

This is the earliest attacker-controlled data in the device's life: a flash page
we can write, parsed before anything is authenticated.

### The ROM parses the full manifest property set

From MOVZ/MOVK immediate pairs (the `X-1` spellings are switch lowering):

    DGST 0x100007c70/0x100007c98   BNCH 0x100007ee0/0x10000802c   BNCN 0x100007fa8
    AMNM 0x100007cf0/0x100007d00   ECID 0x100007df8/0x100007e0c   CHIP 0x100007f6c/0x100007f80
    BORD 0x100007ef0/0x100007f04   CPRO 0x100007f44/0x100007f58   CSEC 0x100007f10/0x100007f24
    EPRO 0x100007db0/0x100007dc8   ESEC 0x100007e54/0x100007e6c   SDOM 0x100007d80/0x100007d94
    EKEY 0x100007da0/0x100007e24   DPRO 0x100007d40/0x100007d50   CEPO 0x100007fe4/0x100007ffc

DER container tags: IMG4 0x100011b50, IM4P 0x100011bbc, IM4M 0x100011c40,
IM4R 0x100011cd0.

**AMNM and BNCH are both parsed by the ROM.** That makes the no-nonce-on-flash
result sharper rather than softer: the ROM knows how to read BNCH, so whatever
makes a cold flash boot ignore it is a deliberate branch with an address, and
finding that branch is now a concrete task rather than an inference from
observation.

### No decompressor

`complzss`, `bvx2` and `lzss` appear nowhere in the 128 KiB. The ROM does not
decompress LLB. Any future "decompression bug in the ROM" lead is refuted unless
it can show the code without relying on a string.

### Tooling added

* `~/homepod/multipod/rompeek` — gaster plus a `peek ADDR LEN OUT` command
  (~90 lines: `gaster_memcpy` + `gaster_peek`; 0x1000 bytes per request; drives
  the MEMC command already present in `payload_handle_checkm8_request.S`).
  Read-only.
* `hp-runner.command` gained a `rom-peek ADDR LEN OUT` action, documented in its
  header. Previous script kept as `hp-runner.command.pre-rompeek`.

---

## 2026-11-24 (night, cont.) — the ROM audit: four verdicts, and one claim killed on hardware

Four parallel audits of the fresh ROM dump. **No untether.** But the ROM is now
mapped, and three things we only knew by observation now have addresses.

### The headline: DGST *is* enforced, proven by paired experiment

One audit reported that the ROM computes the payload digest, compares it, and
discards the answer — i.e. a genuine IM4M would authenticate an arbitrary
payload. The instruction reading is correct as far as it goes:
`FUN_1000080f8` (0x1000080f8) returns 0 on match / -1 on mismatch, and its only
call site, 0x100007ca8 in the manifest-property callback `FUN_100007c20`,
branches at 0x100007cac to an epilogue whose `mov x0, #0` at 0x100007e98 is
unconditional. (The stack-cookie `cmp x8, x9` at 0x100007e94 has no `b.ne` after
it either, which is itself a sign our control-flow model of that function is
wrong somewhere.)

**Refuted on hardware.** The test needs no NAND write, because DGST covers the
*complete* IM4P TLV — including the version IA5String, which is outside both the
payload OCTET STRING and the KBAG. So one byte there breaks the digest while
leaving every executable byte bit-identical:

    oldfw/17M61/iBSS.b238a.RELEASE.im4p, file offset 0x23: '2' -> '3'
    iBoot-5540.140.12 -> iBoot-5540.140.13      (one byte, same length)
    payload + KBAG byte-identical: True

Two runs, four minutes apart, each with its own freshly fetched ticket for the
live nonce, pod in **unpwned** boot ROM DFU both times:

    genuine im4p   + fresh ticket  -> mode=softdfu, SRTG: N/A   ACCEPTED
    version-flipped + fresh ticket  -> mode=romdfu,  SRTG: 1992  REJECTED

So the discarded return value is not the channel the check travels on, and the
real enforcement site is somewhere none of the four audits located. **Open
question, and the only one left with real upside.** The method is worth keeping:
a one-byte version-string flip plus a fresh ticket is a clean, non-destructive,
two-minute oracle for "does this stage bind payload to manifest", and it works on
any stage we can send over DFU.

Procedural note that cost one run: `rom-peek` leaves the pod pwned, and a `send`
after `pwn` without a `gaster-reset` is silently ignored. Any signature-behaviour
test must start from a power-cycled, unpwned ROM — check for the absence of
`PWND:[checkm8]` in the USB serial first.

### The ROM's only accept-an-unverified-image path, and why it is shut

`FUN_100007574` at 0x1000078ac: if the trust evaluation fails, the ROM hard-fails
only when handle flag bit 1 is set (0x1000078b4) **or** `FUN_100011910`
(0x100011910) returns 1 (0x1000078c0). Otherwise it continues at 0x1000078c4
with trusted=false and **boots the image anyway**.

* Flag bit 1 = `1 - flag2`, and `flag2` is bit 0 of the boot-device selector, i.e.
  **GPIO port 6 pin 6, flat id 0x36**. Selector 2 (our board) gives flags 0xf,
  bit 1 set, hard fail. Selector **3** — the same NAND boot device, one strap
  pin high — gives flags 0xd, bit 1 clear, and arms the soft path.
* `FUN_100011910` returns 1 if `[0x2_0E02A000] bit1` is set, else returns
  `bit0`. Both must be 0 for the soft path to open.

Measured: **`[0x2_0E02A000] = 0x00010297`** -> bit0 = 1, bit1 = 1. Both gates
shut. And those two bits are exactly what the pod prints in its own USB serial
string: **`CPFM:03`**. The ROM's accept-unverified path needs `CPFM:00`, a
demoted/dev-fused part. Every retail HomePod is CPFM:03, so this is closed for
anyone who cannot blow fuses — and anyone can check their own unit by reading
CPFM off the DFU serial. Also measured from the same word: SDOM 1, CEPO 1,
BORD high bits 1 (giving BORD 0x38, matching `BDID:38`).

### Boot-device selection and board ID are GPIO straps, re-sampled every boot

`FUN_1000082a4` (0x1000082a4) sets 8 pads to input with an internal **pull-down**,
waits 100 us, reads them, restores mode 4, and composes `[0x2_0E029000]`. The gate
is bit 0 of that register, which `FUN_10000a164` zeroes immediately before — so
sampling always happens and no software-written value survives a reset.

    selector bit 0 (= flag2)  GPIO 6/6  flat 0x36      <- the F2 arm
    selector bit 1            GPIO 8/4  flat 0x44
    selector bit 2            GPIO 8/5  flat 0x45
    BORD bit 0                GPIO 7/4  flat 0x3c
    BORD bit 1                GPIO 7/5  flat 0x3d
    BORD bit 2                GPIO 7/6  flat 0x3e
    BORD bit 3                GPIO 6/4  flat 0x34
    BORD bit 4                GPIO 8/6  flat 0x46
    BORD bits 5..7            [0x2_0E02A000] bits 4..6 (fuse)

GPIO id -> flat id proven at 0x100002aa4: `((id>>8 & 0x1f) << 3) | (id & 7)`.
Decode of the selector: 0/1/7 -> SPI NOR (`nor0`); **2/3 -> NAND `read_llb`**;
4/5 -> `nvme_firmware0`; 6 and >=8 -> no boot device and **no DFU fallback, hangs
forever**. Measured `[0x2_0E029000] = 0x01380203` -> selector **2**, BORD 0x38.
Odd selectors set `flag2 = 1`.

Pulling a strap high fights the internal pull-down, and outside the 100 us sample
window these pads revert to their normal alternate function — so a permanent hard
pull-up on a functional signal can break that function. GPIO 13/5 (flat 0x6d),
the strap in the earlier notes, is an **output** in the ROM: `gpio_write(0xd05,1)`
at 0x1000089c0, called only from 0x10000070c, the first instruction of the DFU
arm. It is a DFU-entry status indicator, changes no ROM policy, and the
3-vs-8-entry boot-command-table behaviour is iBoot's, not the ROM's. The ROM has
exactly 11 gpio_read and 5 gpio_write sites in total.

### Why a cold flash boot ignores the nonce — the decision has an address

0x100007f9c, in the manifest-property callback:

    0x100007f90  ldrb w8,[x10,#0x2c]   ; flag bit 3 - always 1, so BNCH IS evaluated
    0x100007f98  ldrb w8,[x10,#0x2a]   ; flag bit 2 - "booting from flash"
    0x100007f9c  cbz  w8, 0x10000800c  ; USB  -> hardware nonce from FUN_1000088e0
    0x100007fb4  bl   0x100012184      ; FLASH -> fetch BNCN from the MANIFEST
    0x100007fc4  cmp  w8,#8 / b.ne     ; require exactly 8 bytes

Flag bit 2 is `img4_open`'s third argument: 4 on the flash path (0x1000006dc),
0 on USB (0x100000740). So on flash the ROM compares BNCH against SHA-1 of
**BNCN read out of the same manifest** — both inside the signature-covered body,
so every genuine manifest is self-consistent and the check passes regardless of
the hardware nonce. Bit 2 also suppresses the hardware-nonce fetch entirely
(0x1000076a0). That is the mechanism behind "a cold flash boot checks no APTicket
nonce", and it is a design decision, not a bug: it grants mix-and-match and
nothing more.

### Mix-and-match: the ROM never enforces it, and sets it at handoff

Enforcement lives in the block at 0x100007838, gated on a byte written at
0x100007680 which is only populated when flag bit 3 is **clear** (0x100007674) —
and bit 3 is set on every path (flags are 0xf/0xd on flash, 0xb/0x9 on USB). So
`FUN_100008c6c`, the one reader of `[0x2_0E029000] bit 3`, never runs, and AMNM
(parsed at 0x100007cf0) is moot. Separately, on a successful evaluation the ROM
*sets* bit 3 for the next stage via 0x10000bd58 -> 0x10000bd7c -> 0x100008c84,
and publishes the 20-byte boot-manifest hash to 0x2_0E029040..0x50 with bit 4.
Our earlier "bit 3 is never set on a cold flash boot" was measured in DFU, i.e.
before handoff, and is consistent: measured again tonight, bit3 = 0, bit4 = 0.

### The lockdowns, located — both unconditional, both after the verdict

    ROM aperture close   [0x2_00000900] |= 1   at 0x100009038, executed at
                         0x1800E0038 in the trampoline FUN_100008a84 relocates
                         from ROM 0x100009000 (0x174 bytes); read back at
                         0x100009040 and `wfe` forever if it did not stick.
                         Then [0x2_00000904] = 0 at 0x10000909c.
    production lock      [0x2_0E02A004] |= 0x80000000 at 0x10000a130, inside
                         FUN_100008548 reached from the handoff FUN_10000ab7c at
                         0x10000aba4; dsb, read back at 0x10000a140, panic at
                         0x10000a160 if bit 31 did not stick.
    fabric disable       [0x2_02240008] &= ~(1<<41) at 0x10000278c.

`FUN_10000a118(1)` is called with a literal immediate at 0x1000085bc, which is
the join point of both branches above it — **no input can skip it**. Fail-closed
in both cases (panic or permanent `wfe`), never fail-open. The trampoline is
relocated to SRAM precisely because it must outlive the aperture.

Refinement of earlier ground truth: measured in ROM DFU tonight,
**`[0x2_0E02A004] = 0x20000000` — bit 31 is NOT yet set.** The earlier 0xA0000000
came from a loaded stage, i.e. after handoff. So the lock is applied at handoff,
not before DFU code runs; the production bits are still writable in ROM context,
but the ROM never re-evaluates an image after that point, so the window buys
nothing. Demotion remains closed: `[0x1800885b4] = 0x302c0000`, bit 24 (demote)
clear, and setting it needs an Apple-signed manifest carrying `DPRO == 1`.

A second aperture close exists at 0x10000d9c4 that does **not** set the
production lock. Nothing in the ROM branches to it; it is only stored at
ctx+0x120 (0x10000d968) in the shared boot context at [0x180080570] as a service
pointer for a later stage. Worth remembering when auditing LLB's handoff.

### The NAND geometry, settled

A NAND page is **16 KiB = 4 sectors of 4 KiB**. `arg2` of 0x100001720 is a page
(row) address, `count` is sectors, and `UtilDM[+0x9e]` is sectors-per-page — so
`add w20,w20,#1` at 0x100001c78 advances one page while the destination advances
4 x 4 KiB at 0x100001c7c/0x100001c80. Page address and destination move in
lockstep: no overlap, no gap. (An earlier "overlapping reads" finding was
withdrawn once the measured `[+0x9e] = 4` made the sector reading the only one
consistent with the device booting.)

Live UtilDM page, measured in situ: revision **8.1**, written size **44 sectors**
(180224 bytes, 11 NAND pages — our own LLB img4 is 179276), sectors-per-page
**4**, and the tag word at 0x180083050 = **0x0ff00002**, the LLB selector. So
UtilDM is page 0 sector 0; LLB is pages 1..11, absolute sectors 4..47; sectors
1..3 of page 0 are never read. The page is 4096 bytes and only **three** fields
of it are ever read anywhere in the ROM (+0x00/+0x01, +0x02, +0x9e); the other
4089 bytes are inert. An exhaustive model over all 2^24 combinations of the two
fields that matter shows a maximum end offset of exactly 0x80000 — no overflow,
no infinite loop (count==0 is rejected at 0x100001760), no 32-bit shift wrap
(the value is a `ldrb`, so <= 0xff).

Per-sector spare area: the ROM reads 4 words per sector from [[ctx+8]+0x1c0] and
**compares only word 0** against the expected tag; words 1-3 land in the same
register and are destroyed by the next load. A tag mismatch **terminates** the
read (0x100001c70 exits the loop, and `remaining` is not decremented), so the
accepted region is always a prefix — you cannot accept page 1 and page 5 while
rejecting 2-4. The spare area therefore buys nothing that `[+0x02]` does not
already give at finer granularity. Also: the 512 KiB window at 0x180380000 is
bzeroed before every boot attempt (0x10000bb10 from 0x10000067c, w0=1 ->
0x100011020), so there is no stale content to control.

### Dead ends, closed with evidence

* **Boot case 3 (`nvme_firmware0`) is dead code on a cold boot.** The only
  function that registers `nvme_*` device nodes (0x100004070) is not reachable
  pre-authentication; the registry is empty when 0x10000063c runs, so the lookup
  returns NULL and the ROM falls to DFU. Confirmed by measurement: the registry
  head at 0x1800888b8 reads 0, and the populated IRQ table shows no NVMe handler.
* **The ROM never loads ASP firmware, pre- or post-auth.** Its storage access is
  a self-contained raw-NAND driver (contexts at 0x1800889c8, bases
  0x2_0880_0000 / 0x2_0890_0000 — both confirmed by measurement). The NVMe/ASP
  cluster is entered on a cold boot only through the handoff's quiesce path. No
  unauthenticated flash bytes reach the ANS core. That untether hypothesis is
  disproven for the ROM.
* **IRQ table bound mismatch — unreachable, by measurement.** The dispatcher masks
  the vector to 9 bits (0x10000131c `and w19, w8, #0x1ff`) against a table of
  only 0x103 entries ending exactly at 0x180082048, so indices 260..429 would
  take their handler pointer from inside the UtilDM page — flash bytes becoming a
  code pointer at EL3. But the AIC info register says otherwise:
  **`[0x2_0E100004] = 0x00020100` -> nIRQ = 256, nCPU = 2.** No hardware vector
  can exceed 0xff < 0x103. Measured the table too: populated only at 0x61, 0x64,
  0x98-0x9b (the four SPI handlers), 0xb6; spurious counter 0; slack bytes zero.
* **No decompressor in the ROM**, confirmed independently of strings by scanning
  every MOVZ/MOVK imm16 for the halves of complzss/bvx2/lzss/lzfse/pbzx.
* **Flag bit 8 of the img4 handle is a total verification bypass** (0x10000775c
  -> return success before any parsing or crypto) and is **unreachable**: the only
  two `img4_open` call sites pass 4 or 0, and the OR mask is 0xb/0x9, so flags
  never exceed 0xf. Recorded as the single highest-value bit in the ROM if any
  other writer of handle+0x10 is ever found.
* The ROM is **stricter** than LLB-5540 in several places: DER long-form length
  capped at 4 bytes (so a declared length can never exceed 32 bits, killing the
  whole 64->32 truncation class), the header+content total carry-checked in 32
  bits rather than checked-then-truncated, `payload_len >= total` fatal rather
  than merely skipping a bzero, and property value tags restricted to
  {BOOLEAN, INTEGER, OCTET STRING} where LLB also admits IA5String.

### The one genuine memory-safety defect in the ROM

`FUN_100012ff4` (0x100012ff4) bounds the RSA modulus word count at 0x100
(0x1000130b4, `mov x8,#0x100` at 0x10001302c) against a **fixed stack arena** of
791 bytes that only admits 35 words; the three writes reach `0x18 + 24n` bytes,
so n >= 39 overwrites the saved LR at [x29+8] with modulus bytes — a return-address
overwrite at EL3 with the MMU off. It looks like 0x100 was meant as a byte count.
LLB-5540 accepts only 0xc00 or 0x1000 bits and then allocates `nwords*24 + 0x20`
from the heap, sized from nwords, so it cannot overflow.

**Not reachable.** `nwords` comes only from a certificate's modulus length, and
the two call sites use slot i-1 (slot 0 being the ROM-resident Apple Root CA at
0x100017e30, length 0x4bf, 2048-bit) and the leaf, each only after the previous
link verified. Getting an oversized modulus in requires a certificate already
bearing a valid Apple Root CA signature, and n >= 35 trips the stack cookie
before the corrupted return address is used. Real defect; no path.

### Trust-anchor notes

Anchor is a whole embedded X.509 certificate, not a bare modulus: pointer built
at 0x100012978, length from the ROM constant at 0x1000182f0 = 0x4bf. Self-signed
Apple Root CA, serial 2, 2006-04-25 to 2035-02-09, 2048-bit modulus at
0x100017f57, exponent 65537. It is used, not compared, and its own self-signature
is never verified (the chain loop starts at index 1). Chain shape is pinned to
exactly root + 2. **No basicConstraints check, no keyUsage check, no validity or
expiry check, no extension-criticality handling** — mitigated to unreachable by
the rigid chain length plus the intermediate's commonName being pinned
byte-for-byte to "Apple Secure Boot Certification Authority" (0x100017e00, len
43, OID match 0x100012ef0, name match 0x100012f20). PKCS#1 v1.5 padding
verification at 0x1000148fc is complete: prefix, 0xFF run, separator, DigestInfo
and AlgorithmIdentifier tags and lengths, the full OID TLV memcmp'd, NULL params,
OCTET STRING tag and length 20, and the digest. Nothing missing.

### Addresses worth keeping

    boot task                 0x1000004e8      jump table 0x100000824
    read_llb                  0x100001b4c      block read 0x100001720
    UtilDM page               0x180082050      tag word 0x180083050
    img4_open/eval/close      0x10000f610 / 0x10000f52c / 0x10000f65c
    container tags            IMG4 0x100011b50 IM4P 0x100011bbc
                              IM4M 0x100011c40 IM4R 0x100011cd0
    DER decoder (the only one) 0x100011300     unbounded only at 0x10000714c,
                                               0x1000071d4 (30-byte window)
    manifest-property callback 0x100007c20     iterator 0x100012560
    cmp_int/bool/digest        0x100008040 / 0x1000080ac / 0x1000080f8
    trust evaluation           0x100012724     chain 0x10001292c
    RSA verify / PKCS#1        0x100014a94 / 0x1000148fc   modexp 0x100014a68
    SHA-1                      0x10001290c
    Apple Root CA              0x100017e30 len 0x4bf
    handoff                    0x10000ab7c -> trampoline 0x1800E0000
    stack cookie               0x180080198
    boot strap register        0x2_0E029000     fuses 0x2_0E02A000/04
    AIC                        0x2_0E100000     nIRQ 256

---

## 2026-11-24 (night, cont.) — CORRECTION: the dump contained gaster's patch, and that explains checkm8

The "DGST is enforced" hardware result stands. The reason the static reading
disagreed with it is that **our ROM dump is not pristine.** It was read with the
boot ROM running inside checkm8, so gaster's own one-word patch is in the bytes:

    file offset 0x7e98 (VA 0x100007e98)
      as dumped : 00 00 80 d2   mov x0, #0        <- gaster
      real ROM  : 81 0b 00 54   b.ne 0x100008008  <- cookie-failure stub

My own brief cited that exact address as evidence the dump was genuine —
"patch_addr (0x100007E98) lands on the mov x0,#0 that checkm8 patches" — and
then I read straight past it and spent a round treating the patch as ROM code.
gaster applies it in `payload_notA9.S`: `mov w0, #0xD2800000; ldr x1, =patch_addr;
str w0, [x1]`, and 0xD2800000 is `mov x0, #0`.

Restored, the epilogue of `FUN_100007c20` is canonical and, tellingly, has **no**
`mov x0, <reg>` before the `ret` — x0 already holds the return value:

    0x100007e8c  ldr  x8, [x22]          ; stack cookie
    0x100007e90  ldur x9, [x29, #-0x28]
    0x100007e94  cmp  x8, x9
    0x100007e98  b.ne 0x100008008        ; -> bl 0x10000af58, cookie failure
    0x100007e9c  sub  sp, x29, #0x20
    ...          ret

The reconstruction is forced, not guessed: nothing in the ROM branches to
0x100008008, the distance is exactly 92 words so b.ne/NE encodes to 0x54000b81,
every other cookie epilogue in the ROM has this shape, and the restored word
reproduces the bench result under emulation while the dumped word does not. A
scan of all 131 cookie epilogues found 0x100007e98 to be the only anomaly of
this class. Files are now:

    rom/SecureROM-...PRISTINE.bin  sha256 8fd1d787415146bac809291521d1752dd07ebb971278f0fd2cec672b8232d201
    rom/SecureROM-....bin          sha256 5c4fc92b... (as dumped, patched)

**Lesson, worth keeping: a dump taken through an exploit contains the exploit.**
Two byte-identical reads prove the read path, not the pristineness of the source.
Any gaster-hardcoded address in a checkm8-context dump is suspect until checked
against the payload source.

### So the DGST channel is the return register, and it works

`FUN_1000080f8` (0x1000080f8) returns 0/-1 -> `FUN_100007c20` tail returns x0
unchanged -> `FUN_100012560` `cbz w0, 0x1000125b0` at 0x100012640 ->
`FUN_100012724` `cbnz w0` at 0x1000128ec -> `FUN_100007574` `cbnz w0,
0x1000078ac` at 0x10000781c. Every switch arm that performs a value comparison
falls through to the tail without touching w0; every arm that wants success sets
`mov w0, #0` explicitly first (eleven sites). There is no seen-mask and no
required-property set; the return register is the only channel. The digest at
struct+0x1e has exactly two consumers in the whole ROM: written by
`FUN_100011f70` via 0x100007c90, read by `FUN_1000080f8`'s memcmp via
0x100007ca8.

### What checkm8 actually is on this chip

One word at 0x100007e98 makes every IM4M property comparison report success:
**DGST** (the payload-to-manifest binding), **CHIP, ECID, BORD, SDOM, CEPO,
CPRO, CSEC** (every device binding), **BNCH** (the nonce), and the **AMNM/BMH**
path — while leaving the certificate chain, the commonName pinning, the RSA
verify and the PKCS#1 padding check **completely intact**. That is the whole
explanation of our tethered pipeline: a pwned ROM still requires a genuinely
signed IM4M — any one, ever signed, for any device — and nothing the manifest
*says* matters afterwards. The only property checks the patch does not reach are
EPRO (0x100007880) and ESEC (0x1000078a4), which sit outside the callback. It is
the minimal possible patch for the job.

### Nonce, corrected and emulation-backed

On a cold flash boot the ROM compares the signed BNCH against SHA-1 of a nonce
taken from the image's **own IM4R** (0x100007fa8-0x100007fb4, via
`FUN_100012184` -> `FUN_100012150` reading ctx+0x158), never against the hardware
nonce at 0x2_0E029038, because handle flag bit 2 is set on the flash path
(`mov w2,#4` at 0x1000006dc) and steers 0x100007f9c away from the hardware branch
at 0x10000800c. And the check is **skipped outright** unless that BNCN is present
and exactly 8 bytes (`cmp w8,#8 / b.ne` at 0x100007fc4). Emulated on restored ROM
bytes, flash path, handle flags 0xd:

    no BNCH in manifest            -> accept
    BNCH, no IM4R at all           -> accept, BNCH never compared
    BNCH, IM4R present but empty   -> accept, BNCH never compared
    BNCH + 8-byte BNCN, SHA-1 ok   -> accept
    BNCH + 8-byte BNCN, SHA-1 bad  -> REJECT
    BNCH + 4-byte BNCN             -> accept, BNCH never compared
    BNCH + 16-byte BNCN            -> accept, BNCH never compared

**The IM4R is outside every signature** (the IM4M signs only its own body SET,
field [2]). So on a cold boot the IM4R is attacker-controlled with no crypto
involved: deleting it, emptying it, or giving BNCN any length but 8 disables the
nonce check. That is a stronger and more precise grounding for "mix-and-match
works untethered" than "Apple's manifests carry no AMNM" — each shipped firmware
carries its own self-consistent IM4R and therefore satisfies its own BNCH
forever, and we can also simply remove it.

### Minor, from the same work

* `FUN_1000080f8` uses the **manifest's own** declared length as the memcmp
  length with no check that it is 0x14, and `FUN_100011160` returns 0 for length
  0 — so a zero-length DGST OCTET STRING would compare equal. Now live (the
  result is no longer discarded) but the DGST sits inside the signed body, so it
  needs an Apple signature. NOT-REACHABLE.
* `FUN_100011300` rejects a multi-byte DER length whose first length byte is zero
  (`82 00 61` refused, `81 61` accepted) — partial, not full, canonical-length
  enforcement. No attack follows.
* A reusable emulation harness now exists at `/home/claude/work-rom/` in the
  analysis container: `mkimg.py` builds IMG4/IM4P/IM4M/IM4R to the ROM's exact
  grammar, `emu_eval.py` runs `FUN_100007574` on real ROM bytes with the chain
  and RSA stubbed. It turns "is this field enforced" into a two-second local
  experiment. It only has authority over the ROM with the corrected dump.

---

## 2026-11-24 (night, cont.) — the n-day pivot: three generations in hand

### What is actually reachable

Apple signs exactly two builds for b238a, and we hold genuine per-ECID tickets
for both. Because a cold flash boot checks no nonce, those tickets are good
forever.

| build  | version | iBoot version      | signable now | tickets held |
|--------|---------|--------------------|--------------|--------------|
| 17M61  | 13.4.8  | iBoot-5540.140.12  | YES          | 2 ECIDs      |
| 22K557 | 18.3    | iBoot-11881.80.57  | YES          | 2 ECIDs      |
| 22M84  | 18.6    | -                  | no           | -            |
| 23J362 | 26.0.1  | iBoot-13822.3.2    | no (status 94) | -          |

Tested tonight: 26.0.1's IPSW contains a b238aap build identity, but Apple
answers status 94 "This device isn't eligible for the requested build", so it
cannot be ticketed. No other saved blobs exist anywhere.

**So 23J362 is not a target — it is the answer key.** Every memory-safety fix
Apple made between 11881 and 13822 is a live bug in 11881, and 11881 boots
untethered forever. The same logic runs 5540 -> 11881. We are not hunting a
0-day; we are reading Apple's patch history for bugs that can never be patched
on hardware we control.

### Extraction: 18.3 and 26.0.1 ship their boot loaders UNENCRYPTED

No KBAG element in the IM4P at all — four elements only (IM4P, type, version,
payload) — and the payload begins `00 00 00 90 00 00 00 91` = `adrp x0, #0 /
add x0, x0, #0`, plaintext AArch64. `gaster decrypt` fails on them for exactly
that reason: there is no KBAG to unwrap. So no pod is needed; a plain IM4P
payload extraction is the whole job. (5540 and the 4076-era builds *are*
encrypted and still need GID0.)

    build   image  type  version              bytes    base
    22K557  LLB    illb  iBoot-11881.80.57    199312   0x180380000
    22K557  iBoot  ibot  iBoot-11881.80.57    787008   0x870020000
    23J362  LLB    illb  iBoot-13822.3.2      205016   0x180380000
    23J362  iBoot  ibot  iBoot-13822.3.2      801456   0x870020000

iBoot's load base moved from **0x830000000** (5540) to **0x870020000** (11881 and
13822) — a 0x40000000 shift in where stage 2 lives. Base established by solving
for the value that makes the most 64-bit literals land on `bl` targets: a clear
peak at 0x870020000 (129 hits for 13822, 13 for 11881, versus 6-8 at
0x870000000). LLB's base is not inferred — the SecureROM loads flash LLB to
0x180380000 (`mov x0, #0x180380000` at ROM 0x1000006b4).

**The iBSS/iBEC pairing changed.** In 5540, `iBSS.dec` was byte-identical to
`LLB.dec` and `iBEC.dec` to `iBoot.dec`. In 11881 and 13822 they are the same
size but different bytes. That difference is the flash-vs-DFU policy split made
concrete, and the ROM's equivalent (handle flag bit 2 steering the nonce source)
was the most interesting thing in the ROM — so it is being chased.

Indexed: LLB-11881 1129 funcs / 49828 insn; LLB-13822 1202 / 51254;
iBoot-11881 2119 / 196752; iBoot-13822 2258 / 200364. Ghidra decompilation of
all four under way. LLB-13822 calls itself `iBootStage1 for b238a, Copyright
2007-2025, Apple Inc.` and its strings gain `boot-args` and
`disable-boot-breadcrumbs`, neither of which appears in LLB-11881 — a stage-1
boot-args consumer that reads NVRAM would matter, since we write NVRAM.

### Four hunts running

1. **LLB 11881 vs 13822.** LLB is the only stage the ROM verifies and the ROM is
   now clean, so a reachable bug in LLB-11881 is a permanent untether on its own.
   Also: what differs between iBSS-11881 and LLB-11881, and what 13822's stage-1
   `boot-args` handling does.
2. **iBoot 11881 vs 13822**, prioritised by what we write: NVRAM, SysCfg ->
   DeviceTree, boot-args/boot-command, the kernelcache load path (header,
   compression, mach-o walk, trust cache), the IMG4/IM4R path, the filesystem
   code.
3. **Cross-version mixing** — the surface that exists only because of the missing
   nonce check. LLB-5540 -> iBoot-11881 and the reverse have never been shipped
   or tested by anyone, and each iBoot can be handed either generation's
   DeviceTree, SysCfg, NVRAM, kernelcache or trust cache. The 0x830000000 vs
   0x870020000 base difference alone may mean a position-dependent image running
   at the wrong base, which is a primitive in itself.
4. **5540 re-opened with the answer key.** Today's exhaustive audit found 5540
   clean on every flash-reachable path, but it had no answer key. Every check
   11881 or 13822 has that 5540 lacks is a place a human looked and found nothing
   while Apple's engineers evidently found something. A lead there is worth more
   than one in 11881, because 5540 is the build we understand best.

### Standing note on the research pod

Its SEP is dead, so it cannot complete a full cold boot — a chain failure and a
SEP failure are indistinguishable on it. Fine for DFU-stage work (the ticket
oracle, decryption, ROM peeks). Any end-to-end cold-boot validation of flash
mix-and-match needs a functional pod.

### The oracle, worth reusing

Take a genuine image, edit the bytes in question, re-wrap with a freshly fetched
ticket, send over DFU to an **unpwned** ROM: accepted or rejected in about two
minutes, non-destructively. It answers "is this field actually enforced" without
argument. Critically, a test run through checkm8 answers nothing, because the
patch at ROM 0x100007e98 makes every manifest property comparison report success.

---

## 2026-11-24 (late night) — two n-day hunts done: both negative, plus a material-integrity correction

### CORRECTION: the 18.3 and 26.0.1 IPSWs on this Mac are CUSTOM builds

`homepodstuff/18.3.ipsw` and `homepodstuff/26.0.1.ipsw` are **not stock Apple
IPSWs.** Their DFU stages have been replaced with ra1nsn0w-patched copies. Two
hunts flagged it independently; verified here against Apple's own per-object
`Digest` values in the BuildManifest, which is the authoritative check:

    22K557   DeviceTree  MATCH      LLB  MATCH     iBoot MATCH   kernelcache MATCH
             iBSS  MISMATCH (expected c48bd57a451b2e6a54c4b0d20049ae37307f7e7b)
             iBEC  MISMATCH (expected dafdec855cbde9ebd737a7a8818a01ac19c43871)
    23J362   DeviceTree  MATCH      LLB  MATCH     iBoot MATCH
             iBSS  MISMATCH (expected bc78373585ad84d2e1ff9747058a9b5fa765e991)
             iBEC  MISMATCH (expected 107615ef4d9f1948b820cc027bda973e778f5d52)

Both iBEC files contain `"Entering ra1nsn0w mode, starting command prompt"`
where Apple's says `"Entering recovery mode, ..."` — an in-place patch, same
length. The iBSS/iBEC sigpatch is a single instruction: `mov x0, x20` ->
`mov x0, #0` at LLB-11881 `0x18038d26c` (13822: `0x18038afec`; iBoot-11881:
`0x87002af6c`), the return-value load in the epilogue of the image4
property-evaluation function. `w20` is -1 on every reject path and 0 only on
success, so forcing x0 to 0 makes every property comparison report success —
**the same semantic as checkm8's ROM patch, applied one layer up in flash
code.** Independent confirmation that all of ECID/CHIP/BORD/SDOM/CEPO/AMNM/DGST
enforcement in LLB funnels through w0 at that one instruction.

**So my "the iBSS/iBEC pairing changed, that is the flash-vs-DFU policy split
made concrete" claim was wrong** — it was an artifact of patched files, and I
asserted it in the hunt brief before verifying the digests. Second artifact
error of the night from the same root cause: believing bytes without checking
their provenance.

### ...and the genuine files recovered, with proof

The genuine `iBSS` im4p is the genuine `LLB` im4p with its type 4CC swapped
`illb` -> `ibss`, and `iBEC` is `iBoot` with `ibot` -> `ibec`. Doing exactly
that reproduces **Apple's published SHA-1 for all four files, both builds**:

    22K557 LLB  -> iBSS : c48bd57a451b2e6a54c4...  MATCHES MANIFEST
    22K557 iBoot-> iBEC : dafdec855cbde9ebd737...  MATCHES MANIFEST
    23J362 LLB  -> iBSS : bc78373585ad84d2e1ff...  MATCHES MANIFEST
    23J362 iBoot-> iBEC : 107615ef4d9f1948b820...  MATCHES MANIFEST

So **iBSS is byte-identical to LLB and iBEC to iBoot in 11881 and 13822, exactly
as in 5540.** The pairing never changed, there is no flash-vs-DFU code split in
Apple's firmware, and we now hold digest-verified genuine copies of all four
without needing stock IPSWs. Written to
`oldfw/{22K557,23J362}/{iBSS,iBEC}.b238a.RELEASE.GENUINE.im4p`.

**Standing rule from this: verify every extracted firmware object against the
BuildManifest `Digest` before analysing it.** It is one line of Python and it
would have saved two agents a chunk of work and me two wrong claims.

### Hunt 1 — LLB-11881 vs LLB-13822: NEGATIVE

Three HARDENING changes in five years, all unreachable:
* `0x1803a19e0` (13822 `0x1803a2744`): 13822 adds `digest_len <= 0x30` before the
  SHA callback writes into a 48-byte stack buffer. The length comes from a
  read-only in-image table (`*0x1803aa4b0 == 0x14`) and the hash callback at
  `0x1803a364c` additionally refuses unless the requested length *equals* that
  constant. 5540 is identical here (`0x18039e23c`), so not a 5540 lead either.
* `0x1803a21dc` (13822 `0x1803a2c38`): 13822 rejects DER OCTET-STRING lengths
  that do not fit in 32 bits. The only consumer (`0x18038e380`) rejects any
  length != 0x14 first, the outer item length is already 32-bit-checked at
  `0x1803a2618`, and DER lengths are bounded by the enclosing buffer, which is
  capped at 0x1400000 for iBoot and 0x80000 for LLB by the ROM.
* `0x1803a1194`: 13822 initialises an output field 11881 leaves untouched. The
  single caller zeroes the whole 48-byte record before the loop
  (`0x1803a257c`), and nothing ever reads that field.
Everything else is FEATURE (a new `exrm` manifest property; exception-handler
diagnostics) or REFACTOR (assert renumbering, machine-outliner regrouping, and a
build-wide `x != 0` -> `x == 1` sweep on booleans whose producers all `cset`).

Two useful negatives from the same hunt:
* **LLB has no environment/NVRAM store in any of the three builds.** 13822 links
  in `boot_args_find`/`boot_args_get_uint` (`0x180399828`, `0x18039992c`) but
  the only call site is the breadcrumb gate asking for
  `disable-boot-breadcrumbs`, and `env_get` is a hard stub (`0x18039e314`:
  `mov x0,#0 ; ret`; same in 11881 at `0x18039e5bc`). No `nvram`/`SysCfg`/
  `effaceable` string appears in any LLB. **There is no stage-1 NVRAM reader to
  attack.**
* **LLB never re-reads the ROM's UtilDM scratch.** Zero references to any
  `0x1800xxxxx` address in either LLB build.
* The IM4R *is* parsed by LLB pre-auth (`0x1803a1118`, `'IM4R'` at
  `0x1803a1164`) but its contents are consumed by nobody outside the ROM.

### Hunt 2 — 5540 re-opened with the answer key: NEGATIVE, verdict stands

74 checks enumerated across NVRAM, SysCfg, the SysCfg->DeviceTree merge, the
DeviceTree parser, the kernelcache path, IMG4/DER, the trust cache, GPT and the
allocator. **Exactly one semantic check exists in 11881/13822 that 5540 lacks:**
the DER minimal-length-encoding reject (long-form length `< 0x80` -> error 3;
11881 iBoot `0x870064e38`, LLB `0x1803a3be8`; absent in 5540 at
`0x830034e38`-`eac`). It is reachable — the IM4R is outside every signature, so
we can re-spell its length in long form — but it buys nothing: 5540 clamps the
parsed span to the remaining buffer in both encodings (`min(uVar7,uVar5)` at
`0x830034e9c`), and the SecureROM's own decoder is *also* lax, so the only
differential runs lax->strict, i.e. in the rejecting direction. Declining to
round it up.

Everything else is defence-in-depth over invariants that already hold, a
parameterisation, surface that only the newer builds have, or — in four places —
**a place where 5540 is strictly tighter than 11881**: env name/value caps of
0x40/0x261 with truncating `strlcpy` (11881 removed the fixed buffers), `off +
0x14 < size` vs `<=`, array-allocation overflow capped at 2^32 vs 2^64, and
paniclog header validation that 11881 dropped.

Three gaps persist identically in all three generations and are therefore *not*
answer-key leads, but are worth recording: the mach-o load-command walk advances
by `cmdsize` with no zero-check and no `sizeofcmds` bound (5540
`FUN_83000c920`, 11881 `0x87004bbb4`); the segment copy's source range
`base+fileoff`/`filesize` is never checked against the image length; and GPT
header and entry-array CRC32 are ignored everywhere. The first two are
unreachable because the kernelcache is `'krnl'`-verified first.

### An important scoping correction to our own threat model

The DeviceTree, kernelcache, trust cache and SEP firmware are **IMG4-verified
before any parsing** — 5540 reaches `FUN_83002083c(buf,len)` only via
`FUN_830021938`/`FUN_830021b70`, each of which calls
`FUN_830012294(buf, max, &len, 'dtre', 0)` first and parses only on success.
So on a cold flash boot we cannot *author* those bytes; we can only substitute
the other signed generation's well-formed copy. Our standing "everything on
flash is attacker-controlled pre-auth" is too strong for those four. What
remains genuinely unauthenticated: **NVRAM, SysCfg, the IM4R of every image, the
UtilDM page, the per-sector NAND spare area, and the filesystem.**

### Mitigations: nothing changed in five years

| | 5540 | 11881 | 13822 |
|---|---|---|---|
| stack canary | build constant `0x4752400444303631` (iBoot `0x8300483d8`, LLB `0x1803aa298`) | build constant `0x4752440044303631` (iBoot `0x87007fd10`, LLB `0x1803b0a40`) | same constant as 11881 (iBoot `0x870082db0`) |
| randomised per boot/device | no | no | no |
| heap cookie | SipHash-2-4 over a 16-byte static key `2f323231786b6364fc1779362e3afaa7` at `0x8300487a8` | **byte-identical key** at `0x87007fe70` | **byte-identical key** at `0x870082e60` |
| derived from entropy | no | no | no |
| ASLR / slide | none, fixed 0x830000000 | none, fixed 0x870020000 | none, fixed 0x870020000 |

The same 16-byte heap key appears exactly once per image in all six images, five
years apart. So exploitation primitives are equally defeated offline in every
generation, and target choice rests purely on bug reachability. 11881 did widen
canary *coverage* and added an exception-reporting path (`Invalid SP (%p) in
exception handler`, `_validate_sp`, `PC Alignment`, `Stacktrace:`), which makes a
crash noisier but no harder to achieve; and 11881's canary value differs from
5540's, so a leak does not transfer between builds.

### Where the remaining upside is

Both hunts named the same gap, independently: **the APFS/HFS reader iBoot uses
to find the kernelcache.** It is the only place on the cold-boot path where
genuinely attacker-authored bytes and an unaudited parser coincide — the
filesystem is not a signed object, we write the partition, and iBoot must parse
it before any signed material is in play. Today's audit claimed to have closed
"the whole filesystem chain", but the hunt that looked covered only the MBR and
GPT layers (~35%) and explicitly did not read the filesystem reader in any
build. That claim needs reconciling, and a dedicated hunt is now on it.

---

## 2026-11-24 (late night) — RETRACTION: cross-version mix-and-match is BLOCKED by manifest-digest pinning

This overturns a standing ground-truth line we have carried all week. The
no-nonce result survives intact; the mix-and-match conclusion drawn from it does
not.

### The mechanism, verified at instruction level

The ROM latches the verified LLB's IM4M digest into PMGR scratch and turns on
enforcement for everything after it:

    0x2_0E029000 +0x00 bit 3   enforce manifest pinning
    0x2_0E029000 +0x00 bit 4   pinned digest valid
    0x2_0E029000 +0x40..+0x53  the 20-byte pinned IM4M SHA-1

ROM side: the boot image's descriptor gets flag bit 3 set unconditionally
(`mov w27,#0xb` at `0x100000654`, OR'd into `[desc+0x10]` at `0x1000007b8`),
which means "exempt *this* image from pinning but switch pinning on for
everything after it" — the ROM skips its own pin check at `0x100007674`, and on
success publishes the digest via `0x10000bd1c` -> `FUN_10000bd7c` ->
`FUN_100008b7c` (digest + bit 4) and `FUN_100008c84(1)` (bit 3). Two independent
hunts reached this same conclusion from different directions.

LLB side, which I verified myself in `bin/LLB.dec`:

    0x1803815f8  mov  w2, #0            ; registry flags for the 'ibot' image = 0
    0x18038c358  ldr  w8, [x26, #0xc]   ; read those flags
    0x18038c364  ubfx w9, w8, #3, #1    ; -> [sp+0x16f]
    0x18038c36c  tbnz w8, #3, ...       ; bit 3 CLEAR, so not taken:
    0x18038c370  bl   0x18038d9ec       ;   enforce = scratch bit 3  -> [sp+0x16e]
    0x18038c384  bl   0x18038d904       ;   digest_valid = scratch bit 4 -> [sp+0x16c]
    ...
    0x18038c58c  ldrb w8, [sp, #0x16e]  ; enforce?
    0x18038c594  ldrb w8, [sp, #0x122]  ; AMNM? -> if clear, fall to the compare
    0x18038c6b4  ldrb w8, [sp, #0x16c]  ; digest_valid? if clear -> reject 0x18038c558
    0x18038c6c8  bl   0x18039c0b8       ; memcmp(pinned, this_image_digest, 0x14)
    0x18038c6cc  cbnz w0, 0x18038c558   ; mismatch -> REJECT

The identical gate is present and unchanged in all six images: ROM
`0x100007674`, LLB-5540 `0x18038c36c`, iBoot-5540 `0x830009524`, LLB-11881
`0x18038d66c`, iBoot-11881 `0x87000b42c` (at the corrected base), LLB-13822
`0x18038b3ec`, iBoot-13822 `0x870009748`.

### The AMNM escape does not exist

The only exemption is an `AMNM` ("allow mix and match") property in the loaded
image's manifest. Checked all four genuine tickets we hold, both ECIDs, both
builds:

    <ECID_POD2>/13.4.8-17M61.shsh2   4820 B   AMNM: absent
    <ECID_POD2>/18.3-22K557.shsh2    5070 B   AMNM: absent
    <ECID_POD1>/13.4.8-17M61.shsh2   4820 B   AMNM: absent
    <ECID_POD1>/18.3-22K557.shsh2    5070 B   AMNM: absent

17M61 tag set: BNCH BORD CEPO CHIP CPRO CSEC DGST ECID EKEY EPRO ESEC IM4M MANB
MANP OBJP SDOM + 19 object types. 22K557 adds three object types — **isys, msys,
love** — and nothing else. No AMNM, no BMH, no bmhs anywhere.

### Where our reasoning went wrong

The old line read "Apple's 17M61 manifests carry no AMNM" as *support* for
mix-and-match being permitted. It means the opposite: AMNM is the property that
*allows* mixing, so its absence is what makes pinning bite. We had the polarity
backwards. The `[0x2_0E029000] bit 3 = 0` measurement was real but was taken in
ROM DFU, i.e. **before** the handoff that sets it — and in the DFU path the
loaded stage is never pin-checked at all, because the ROM gives it the same
exempt descriptor. Pinning only bites at stage 2 and later on a flash boot.

### What survives, and what dies

**Survives, and it is still the foundation:** a cold flash boot checks no nonce,
so **any complete, self-consistent signed set boots from flash forever.** Both
13.4.8 (17M61) and 18.3 (22K557) remain permanently installable with the tickets
we hold. That is unchanged.

**Dies:** cross-version stage mixing, and cross-generation substitution of any
signed object (DeviceTree, kernelcache, trust cache, SEP firmware) — the
mismatched object is rejected before a single byte of it is parsed. The
"never-tested combinations" surface does not exist.

A confirmation run is still worth doing on a working pod when convenient: write
the genuine 17M61 LLB and the genuine 22K557 iBoot to `anc_firmware` and cold
boot. Predicted: reject at `0x18038c558` with no stage-2 execution. If
iBoot-11881 banners on the UART instead, the pinning analysis is wrong and the
mixed surface is live again — which is exactly why the run has value.

### Correction: the iBoot base was wrong by 0x20000

`bin/iBoot-11881.dec` and `bin/iBoot-13822.dec` are based at **0x870000000**,
not 0x870020000. The image carries its own link address as a literal:
`[0x300] = 0x870000000` and `[0x308] = 0x8700c0240` = base + file size exactly
(13822: `0x8700c3ac0` = base + size). 5540 has the same convention at
`0x318/0x320` (`0x830000000`, `0x8300a9240`). Stage 2 is **position-independent
and relocates itself** to its link address, so LLB's staging address
(`0x8_3EC00000` for 5540, `0x8_7EC00000` for 11881) is not the base — which is
what fooled my pointer-histogram solve. Lesson: when an image might be
self-relocating, read its link-address literal before solving statistically.

Consequence, now fixed: all `dis/iBoot-{11881,13822}.*` artifacts were 0x20000
high and have been regenerated; the old ones are kept as `*.WRONGBASE.*`.
Addresses cited by the earlier hunts for those two images need 0x20000
subtracted. LLB at 0x180380000 and iBoot-5540 at 0x830000000 were always right.

Related correction: the LLB->iBoot handoff enters stage 2 with the **MMU off**.
Both LLBs copy a ~0x940-byte trampoline into SRAM page `0x1801FF000` and enter
at `0x1801FF790`; it sets `SCTLR_EL1 = 0`, `smc #0` to EL3, `SCTLR_EL3 = 0`,
cleans and invalidates D-cache by set/way, zeroes x1-x29, SP, TTBR0, VBAR, ELR
and SPSR for all ELs, then `ret` to the entry. **Stage 2 is entered at EL3, MMU
off, x0 = 0, SP = 0, with no structure pointer, no boot-args block, no magic and
no version field** — so there is nothing in the register/memory channel for
either side to validate or mismatch. The real inter-stage channel is the PMGR
scratch above.

### The new best lead: iBoot-11881 replaced the NVRAM subsystem wholesale

NVRAM is **unsigned**, fully attacker-authored on the NAND, and `nvram_init`
runs at the top of iBoot's main boot task before any image is verified. It is
one of the few genuinely unauthenticated inputs left (with SysCfg, the IM4R, the
UtilDM page, the NAND spare area and the filesystem).

* iBoot-5540 is IODTNVRAM **V1 only**: `load_bank_partitions`, `checksum
  failure`, `partition len out of range`, header name `nvram`, partitions
  `common`/free. Parser `0x8300273f0`, bounded: CHRP header checksum,
  `adler32(buf+0x14, 0x1fec)` vs `[buf+0x10]`, per-partition checksum,
  `len != 0`, `off + len*0x10 <= 0x2000`. `env_unpack` `0x8300224d4` caps the
  name at 0x3f and the value at 0x261 into fixed stack buffers.
* iBoot-11881 and 13822 have **none** of those strings and instead carry
  `2nvram`, `2common`, `2system`, `system`, `nvram-migrate` — the **V2** store
  format, a 0x70 "system" partition, and a V1->V2 migration path. The value
  codec has three encodings including a **run-length one with a 0xFF escape**
  that does not exist in 5540 at all. 11881 also removed 5540's fixed-size
  name/value buffers entirely, and publishes `nvram-bank-size` /
  `nvram-bank-count` / `nvram-current-bank` into `/chosen`.
* Located so far: serializer `0x87002dd8c`, header validator `0x87002e344`
  (which now checks the header *name*, something 5540 never did), value codec
  `0x87002d7b4`. **The V2 variable unserializer has not been found or read.**
  All addresses in that paragraph are at the wrong base and need 0x20000
  subtracted.

This is new code that the exhaustive 5540 audit never covered, it consumes
unsigned attacker-authored bytes before any verification, and 13822 is the
answer key for it. Also new in 22K557: the object types **isys, msys, love**,
which imply parsers that do not exist in 5540 at all.

Older parser given a newer store fails safe, for the record: iBoot-5540 accepts
the header (no name check), parses the 0x71/0x70/0x7f partitions, then looks for
a partition named `common`, finds only `2common`, and boots on defaults. No
corruption.

---

## 2026-11-24 (late) — iBoot stage-2 diff: negative on hardening, but two real findings

### Negative on the diff itself

No HARDENING change in iBoot between 11881 and 13822 is both real and reachable
from NAND bytes on a cold flash boot. 1889 function pairs established (75.7% of
11881) by string literals and call-graph shape, machine-diffed twice (normalised
decompiled bodies; instruction-level guard signatures), with every
assert-gaining pair and every priority-area pair with a new immediate guard read
by hand. Everything resolved to REFACTOR or FEATURE, several of which read as
hardening in the decompiler and were not.

**The NVRAM V2 unserializer is found and it is clean.** 11881 `0x87002d9e0`
(235 insn), 13822 `0x87002b3c8` (164 insn), reached from `nvram_init` via the
partition loader at `0x87002dd8c` call sites `0x87002e29c`/`0x87002e2e0`. Two-pass
RLE decode with a 0xFF escape: pass 1 sums run lengths into a 64-bit accumulator
with both byte fetches bounded against the value length; the allocation is
`alloc(total+1)` with the NUL written in bounds; pass 2 re-checks the same two
bounds and computes `remaining = capacity - written` with a `csel`-clamped
`subs`, then calls a genuinely bounded memset (`cmp x2,x3 / csel x2,x2,x3,lo`),
so a pass-1/pass-2 disagreement cannot write out of bounds. Aligned guard diff
over the real function boundaries: 28 guard sites in 11881, 21 in 13822, and
**the set of guards present only in 13822 is empty.** The answer key says this
function was not fixed. That lead is closed.

### Finding 1 — Apple deleted the HFS+/HFSX driver between 18.3 and 26.0.1

In 11881 both filesystems are registered: `apfs` at index 0, `hfs` at index 1
(`{name @0x8700368fa, ops @0x87005fdc0}` at `0x87005fe30`; driver
`0x87001dc00`-`0x87001f300`). In 13822 there is no `hfs` string at all and the
registration array has one entry. `mount_boot_partition` (`0x87000128c`) loops
over registered filesystems **by index** (`0x870026dd0`, array bounded
`0x87005e5d0`..`0x87005e5e0`) and mounts by name with `"/boot"` until one
succeeds — so HFS runs only when the APFS mount fails, which we can arrange by
zeroing the APFS container superblock.

Reachable, with concrete bytes: zero the first 0x1000 of the boot partition,
then at partition offset 0x400 write an HFS+ volume header with signature `48 2B`
or `48 58`, a power-of-two `blockSize` in [0x200, 0x10000], non-zero
`totalBlocks`, and catalog/extents fork descriptors whose B-tree header nodes
satisfy `nodeSize >= 0x200 && popcount(nodeSize) <= 1` and
`logicalSize/nodeSize == totalNodes` (validator `0x87001e3ac`, popcount helper
`0x87001f160`). Entry `0x87001f1cc` -> `0x87001df2c` reads 0x200 bytes at offset
0x400 and requires the signature.

**But the 11881 HFS code is bounded on every write path audited**: node buffer
allocated at `nodeSize` (`0x87001f154`); record-offset fetch `0x87001f084`
bounds `idx*2+2` against `nodeSize` with a wrap check, then requires
`record <= node_end-1` and `record + 2 + keyLength <= node_end-1`; catalog key
bound `0x87001f0f0` requires `record+6 + nameLength*2 + 2 <= end` before the
UTF-16 compare loop; record copy `0x87001ef5c` requires
`record_data + record_size <= node_end` before the memcpy (the decompiler
renders this as a tautology; the instruction is correct). The fork/extent mapper
`0x87001e150` has a 32-bit `blockCount*blockSize` that can wrap and a fully
attacker-chosen 64-bit device offset, but the copy length is
`min(avail, requested-written)` and the loop accumulates exactly `requested`, so
the destination cannot be overrun — and an arbitrary read offset into a NAND we
already own is not a primitive. So the deletion reads as **attack-surface
reduction, not a fix for a specific defect.**

The more valuable target is the one the diff *cannot* see: **APFS is index 0, so
it parses our bytes on every cold boot, and both builds keep it.** Ops tables
11881 `0x87005fd40` and 13822 `0x870042de0` align 1:1; container open
`0x87001a8cc`, volume-by-role `0x87001b018`, default volume `0x87001b390`.
Ghidra recovers that region badly, so it needs disassembly-first treatment. The
GPT parser (11881 `0x8700312b0`, 13822 `0x87002f210`) is also unaudited and runs
before any filesystem. The dedicated hunt has been redirected there.

### Finding 2 — iBoot-5540 has a `recovery-boot-args` path that 18.3 and 26.0.1 deleted

This is a **capability**, not a memory-safety bug, and it is on a build we can
install permanently.

    set_bootargs_allowed(bool)   iBoot-5540 0x83000ffd0
      and w10,w9,#0xffbfffff / orr w9,w9,#0x400000 / csel     ; policy bit 22
    called with w0=1 from        0x8300041c8  (in 0x8300040bc)
                                 0x830004410  (in 0x8300042a0)
    both are boot-command handlers; the tables at 0x830047000 and 0x830047040
    map "recover" -> 0x830004284 -> 0x8300042a0
    and "recover" -> 0x8300040a0 -> 0x8300040bc
    consumer: kernel boot-args assembler 0x83000c0d4-0x83000c138
      nvram_get("recovery-boot-args") -> cbz skip
      -> bl 0x83000ffec (bit-22 accessor) -> cbz skip
      -> strlen(buf)+strlen(val)+2 <= 0x260
      -> strcat(buf," ") ; strcat(buf,val)   into 0x8300aad9c (0x260 bytes)

Handler strings: `/boot/boot/iBEC`, `auto-boot`, `boot-command`,
`recovery-breadcrumbs` for one; `/boot/boot/OS.dmg`, `/boot/boot/kernelcache`,
`/boot/boot/devicetree`, `arp0=file:///boot/OS.dmg` for the other.

In 11881 and 13822 bit 22 is never set: policy word initialised to `0x222c0000`
at `0x870014428`, and no `orr` with bit 22 exists anywhere in either image, so
both read `recovery-boot-args` and discard it. Verified at instruction level
against every writer of that word.

NVRAM is unsigned and ours to write; 13.4.8 is signable and permanently
installable. So the concrete ask is `boot-command=recover` plus
`recovery-boot-args=<args>` in the V1 NVRAM store. **The bound is correct, so
there is no overflow here — the question is entirely what the args buy on a
production (CPFM:03) kernel**, and most security-relevant boot-args are gated in
the kernel on exactly that state. A dedicated hunt is on it, including whether
`arp0=`/`rd=` can change which root device or kernel is booted, which would not
need to defeat kernel policy at all. Treat as promising and unproven.

### Mitigations, independently re-measured and agreeing exactly

Stack canary is a single in-image 8-byte constant loaded by a literal-pool `ldr`:
5540 `0x8300483d8` holds `31 36 30 44 04 40 52 47`; 11881 `0x87005fd10` and
13822 `0x870062db0` both hold `31 36 30 44 00 44 52 47`; LLB-11881 `0x1803b0a40`,
LLB-13822 `0x1803b1a60`. Changed once between 5540 and 11881, never randomised.
Heap cookie is SipHash-2-4 (rotation constants and 2-round loop at `0x870023520`:
`ror #51/#48/#43/#47/#32`, `mov w17,#2`) keyed from a static 16-byte in-image key
`2f 32 32 31 78 6b 63 64 fc 17 79 36 2e 3a fa a7` that is **byte-identical in
all six images** — iBoot-5540 `0x8300487a8`, LLB-5540 `0x1803aa548`, iBoot-11881
`0x87005fe70`, LLB-11881 `0x1803b0a68`, iBoot-13822 `0x870062e60`, LLB-13822
`0x1803b1a88`. Chunk check `0x870028380`. No ASLR anywhere.

### Hardware: the IM4R is attacker-authored and the ROM accepts it

img4tool emits no IM4R at all, so rather than mutate one I added one. Built a
private-class `BNCN` property by copying the exact encoding out of a genuine
17M61 ticket (`ff 84 92 b9 86 48 1e 30 1c 16 04 'BNCH' 04 14 ...`) and patching
the final tag digit `48` -> `4e`, since `BNCH` and `BNCN` differ only in the low
7 bits:

    IM4R = A1 len { 30 len { 16 04 "IM4R", 31 len { <BNCN elements> } } }
    BNCN = ff 84 92 b9 86 4e 12 30 10 16 04 'BNCN' 04 08 <8 bytes>

Appended to a genuine 17M61 iBSS IMG4 with a freshly fetched ticket, outer
SEQUENCE length adjusted, **not one byte of the IM4P or IM4M touched**. Sent to
an unpwned ROM:

    x-dup (IM4R with BNCN duplicated, +62 bytes)  ->  ACCEPTED, mode=softdfu

Only the first send in a job is meaningful: once an image is accepted the pod
leaves ROM DFU, so the later sends in that job go to iBSS, not the ROM. So the
result is: **the unpwned ROM accepts a genuinely-signed image carrying 62 bytes
of our own DER in an IM4R, including a duplicated property.** That confirms the
IM4R is outside every signature and is attacker-authored on the signed path.

It does **not** yet show the IM4R's SET is walked pre-auth on the USB path — on
USB the ROM takes the hardware-nonce branch (handle flag bit 2 clear at
`0x100007f9c`) and may never fetch BNCN. The discriminating follow-up is a
*malformed* IM4R (truncated inner length, or an invalid tag): rejected means the
parser walks it and the IM4R DER is a live pre-auth surface; accepted means it is
ignored entirely on USB and the surface exists only on the flash path.

**Two process notes from this run.** The first attempt was uninformative because
I wrapped a 22K557 iBSS with a 17M61 ticket — the `ticket` action defaults to the
17M61 manifest — and the digest mismatch correctly rejected all three images
including the control. The control is what caught it immediately; without one I
would have read three rejections as a finding. Second: that accidental run is one
more independent confirmation of DGST enforcement across builds.

---

## 2026-11-24 (late) — filesystem hunt: no write primitive in any build; the open APFS experiment answered statically

### The result

The filesystem metadata-parsing core of iBoot-11881 and iBoot-13822 is
**check-for-check identical to iBoot-5540's**. No memory-corruption write
primitive anywhere in the APFS container/B-tree/record path, the HFS+ driver, or
the GPT parser, in any of the three builds. A 50-row bound table was built with
every entry verified by reading the instruction in both the old and the new
build; every size delta between builds resolved to codegen or to stack canaries
11881 added, never to a lost bound.

Reachability of the mount loop, established by control flow and matching 5540's
`0x830001e08`: `fs_driver_name` `0x870026dd0` bounds the index against exactly
two entries; `mount_at_boot` `0x87000128c` loops upward calling it and then
`fs_mount(..., "/boot", ...)` until one succeeds. **Index 0 is apfs, index 1 is
hfs**, so APFS parses our bytes on every cold boot.

Driver registration, from the data rather than from code references:

                    registry            apfs struct / ops / name
    5540    0x830046838,0x830046840     0x830048618 / 0x8300485b8 / 0x83003f8dd
    11881   0x87005e5d0,0x87005e5d8     0x87005fdb0 / 0x87005fd40 / 0x8700568c6
    13822   0x870061d48 (ONE entry)     0x870062e50 / 0x870062de0 / 0x870059ca5

13822's deletion of HFS+ is confirmed four independent ways: no `hfs` string, no
`H+`/`HX` signature constants (5540 `0x830017da0/da8`, 11881
`0x87001df84/df8c`), no `0xfe00` blockSize bound, and a one-entry registry.

### The open APFS experiment is now answered, with no hardware needed

`notes/N-apfs.md` left X-1 open: is the 0xFFFE value-length sentinel (N1) a bug
Apple would fix, or a design decision? **It is present and unchanged in all
three builds including 26.0.1**, so by that note's own stated criterion it is a
design decision — the APFS `kvloc` sentinel — not a hardening lead.

N1 in 11881 for the record: `get_val` `0x87001d2f8` yields `val_len = 0xFFFE`
either from `toc[idx].v.off == 0xfffe` (NULL pointer, `0x87001d378/d384`) or from
a legal `v.off` with the record's `v.len == 0xfffe` (`0x87001d3fc-400`).
`btree_lookup` `0x87001cc30` special-cases it at `0x87001cfc8-d0`: sets the
memcpy length to 0, jumps to the *key*-length check at `0x87001d044`, **skipping
the value capacity check at `0x87001d038`**, returns success, and writes
`*vallen_io = 0xFFFE` back to the caller at `0x87001d084`. The inode decoder
`0x87001bc38` reads that back at `0x87001bd4c` and derives its xfield-walk bound
from it. 13822 identical at `0x87001dfa4-ac` / `0x87001e01c` / `0x87001cd18`.

On-disk cost: **two bytes plus a checksum fix** — in the filesystem-tree leaf
node holding the inode record, with `BTNODE_FIXED_KV_SIZE` clear, set
`v.len = 0xFFFE` at `node + 0x38 + 8*idx + 6` and recompute the block's
fletcher64. Reach about 61 KiB past a 0x1220 allocation from a non-zeroing
bucket allocator. **Primitive: out-of-bounds heap read / uninitialised-heap
disclosure into a reported file size.** The size sink only shortens or fails the
subsequent load, so it is not an untether, and there is no write, so neither the
known canary nor the static heap cookie is in play.

### GPT looseness carried forward unchanged into 26.0.1

No header CRC32, no entry-array CRC32, no `partitionEntryLBA` range check, no
`endingLBA >= startingLBA` (11881 `0x8700313d4-dc`, `0x870031588-98`). That
yields an arbitrary (offset, length) sub-bdev — a primitive, not corruption, and
downstream sub-bdev reads clamp. Apple left this alone across two generations
while deleting the whole of HFS+, which is itself evidence they consider it
contained.

### Four apparent regressions, all false — recorded so nobody re-chases them

1. HFS record accessor 32 -> 27 insns (`0x830018e08` -> `0x87001f084`):
   `ldrh`+`rev16` replaces `ldrb`/`ldrb`/`bfi`, one `ccmp` folds two
   `cset`+`orr`. Both bounds present at `0x87001f0dc-e4`.
2. 5540's `adds`/`b.lo` u64 overflow test on `off+len` (`0x830018594-98`) absent
   in 11881: **it was dead code** — `len <= 0xFFFFFFFF` and `off <= 0xFFFFFFFF`
   are enforced first, so the sum can never carry out of 64 bits.
3. HFS volume header loses a `blockSize != 0` check: redundant, because the
   range test rejects 0 (`0 - 0x200` underflows to `0xFFFFFE00 > 0xFE00`).
4. Catalog node-kind `ldrsb` -> `ldrb`: equivalent comparison against 0xff vs -1.

Two genuine small hardenings, both NOT-REACHABLE: 5540's `fs_driver_name` uses
`sxtw`/`b.ge` so a negative index would read before the registry array (11881
uses `b.hs`), but the sole caller starts at 0 and only increments; and 5540's
HFS b-tree header `sdiv` (`0x8300181d4`) fails closed where 11881's `udiv` is
merely tidier.

### Correction to our own record

My framing that "nobody read the filesystem reader in any build" was **wrong for
5540**. `notes/E-upgradefs.md` S12.4 reads the whole 5540 HFS+ driver function by
function with addresses, and `notes/N-apfs.md` reads the APFS b-tree
search/iterate, the accessors and the inode/dirent decoders. It was correct for
11881 and 13822, which nobody had read, and that was the real gap.

The earlier verdict was overstated in exactly one respect: E-upgradefs S12.5 says
"no memory-safety bug in the filesystem or partition layer" and the chain was
called "closed", while N-apfs had already found N1, a live out-of-bounds read in
that same chain. **"No write primitive in the filesystem" was accurate; "clean"
was not.** Worth keeping as a calibration note on our own language.

### Second-order address error, mine

When I relayed warm-start addresses from the iBoot diff, three were wrong in the
*opposite* direction: the diff hunt translated its whole address list by
-0x20000 when the base was corrected, but **pointer values stored in the image
were always correct absolute link-time values and should not have been
adjusted.** Only computed VAs shift. Verified by direct byte inspection:

    0x8700568c6 -> b'apfs\x00Update\x00'      (correct)
    0x8700368c6 -> b"\xff\x97'\x00\x00\x94..."  (what I relayed: garbage)
    0x87005fdb0 = {name=0x8700568c6, ops=0x87005fd40}   apfs registration
    0x87005fe30 = {name=0x8700568fa, ops=0x87005fdc0}   hfs  registration
    13822 apfs ops table = 0x870062de0 (slot0 0x87001e3bc), NOT 0x870042de0

Also corrected: the volume-by-role bounded copy is 0x10 into 0x16, not 0x10/0x14.
And do not reuse 5540's ops slot->role map on 11881: the ops ABI was
reorganised, 11881's HFS slot +0x20 is NULL, and 11881's apfs slot +0x20 is a
4-instruction accessor, not 5540's read-op shape.

**Rule: when fixing a base error, translate computed addresses only. Values read
out of the image were already absolute.**

---

## 2026-11-24 (end of session) — the recovery-boot-args capability: gated, and my brief was wrong about why

### CORRECTION, and it is the exact failure my own brief warned about

**"Both 18.3 and 26.0.1 deleted the `recovery-boot-args` capability" is false.** It
is intact in all three builds:

    set_bootargs_allowed(bool)   5540  0x83000ffd0   policy word 0x8300ab554
                                 11881 0x870014778   policy word 0x8700c2720
                                 13822 0x870014ebc   policy word 0x8700c5068
    getters                      0x83000ffec / 0x870014798 / 0x870014edc
    recovery-boot-args consumer  0x83000c0d4 / 0x87000e3c0 / 0x87000c794

Each setter has exactly two callers, both inside the recover handlers (11881:
`0x870003ce0` in `0x870003ba0`, `0x870003fb4` in `0x870003e30`). 11881's handler 2
still does `nvram_set("recovery-boot-args","arp0=file:///boot/OS.dmg")`.

The earlier hunt concluded deletion by grepping for `orr w9,w9,#0x400000`. 11881
and 13822 emit `mov w10,#0x400000 / csel x10,x10,xzr,ne / orr x9,x9,x10` instead.
**That is hard rule 3 — never identify code by byte or encoding pattern across
builds — biting exactly as the brief predicted it would on a diff task.** I wrote
the rule into the brief and then relayed a finding that broke it. The lesson is
not "add the rule"; it is that the rule needs *checking* when a hunt reports a
deletion, because "absent" is the easiest wrong answer in a cross-build diff.

So this is not an unpatchable n-day. It is a standing, deliberately gated Apple
feature, present today.

Also corrected: 5540's policy word is `0x8300ab554`, initialised to `0x202c0000`
at `0x83000fc7c` (11881's `0x222c0000` differs only in bit 25).

### The gate nobody had seen: `anrd`

Both recover handlers call the apticket loader at `0x83000467c` **before** setting
bit 22. It reads `/boot/boot/apticket.der` and requires the manifest property
**`anrd` present and DER BOOLEAN TRUE** (`0x830004794`-`0x8300047ec`), failing at
`0x8300047a4` with UART line **164** otherwise.

`anrd` is in neither of our genuine tickets, and — checked tonight across all
three BuildManifests, every b238a build identity — **`anrd` appears nowhere, zero
raw hits in any manifest.** So TSS will never return it for these builds, and the
"ask Apple for a ticket with `anrd`" experiment is answered negatively, offline,
without a request.

### The one live crack, and it collides with digest pinning

`/boot/boot/apticket.der` is **DER-parsed but never signature-verified**:
`0x830033d48` is a pure tag/length walk, `0x830034d7c` contains no crypto, and
`0x830033374` then takes SHA-1 over exactly the walked bytes. No chain, no RSA,
no PKCS#1. **So `anrd` is forgeable** — splice one DER BOOLEAN `0xFF` element into
a genuine IM4M's `MANP` set and re-length the enclosing SEQUENCEs.

But the same file supplies the 20-byte digest that handler 1 **re-pins into PMGR**
before loading anything:

    0x8300041c0  bl 0x83000fe04(&digest)   ; policy |= bit26, store at 0x8300ab580
    0x8300041c8  bl 0x83000ffd0(1)         ; bit 22
    0x8300041cc  bl 0x830010078 -> 0x83000da6c ; write PMGR 0x40..0x50, set bit 4
    0x83000420c  bl 0x83001209c("/boot/boot/iBEC", ...)

So the recover path re-pins the manifest digest mid-boot from an unsigned file we
author — which means forging `anrd` changes the pin, and given digest pinning the
subsequent genuine `ibec`/`krnl` loads should then fail. Handler 2 instead
*requires* `SHA1(apticket.der IM4M) == pinned` (`0x830004348`). The two
requirements look mutually exclusive. **One cold boot decides it** (below).

### Even if the gate opened, the ceiling is not code execution

Measured and traced, not assumed. On CPFM:03 the kernel's boot-arg parser is
**ungated** — `PE_parse_boot_argn` `0xfffffff007868a40` into
`PE_parse_boot_argn_internal` `0xfffffff007868a60`, no whitelist, no
`debug_enabled` check, every argument parsed, 208 call sites. What *is* gated is
`PE_i_can_has_debugger` `0xfffffff00786a954`, a one-line read of `debug_enabled`
`0xfffffff00714fc74`. Of the 12 adrp references to that global, exactly one is
write-capable: `PE_init_platform` `0xfffffff00786a668`, which copies it from
**`/chosen/debug-enabled`** in the DeviceTree. 17M61's DeviceTree has that
property at offset 0xd70, length 4, value **0**. iBoot raises it only via policy
bit 5, set only at `0x83000fcf4`, guarded by `0x830031e3c` = `((*[0x2_0E02A000] &
1) << 8) | 1` — **the production fuse.** This pod is `0x00010297`, bit 0 set. So
`debug-enabled` is 0 and nothing on the NAND changes it.

Consequence:
* `cs_enforcement_disable` **panics the boot** rather than being ignored — AMFI
  `0xfffffff005e17944` parses it, then calls `PE_i_can_has_debugger`, and on 0
  branches to a noreturn assert at `0xfffffff005e17c28`. The global it would set
  has no reader in the image anyway.
* `amfi_get_out_of_my_way`, `amfi_allow_any_signature`,
  `cs_library_validation_disable`, `-unsafe_kernel_text`, `csr-active-config` —
  **zero occurrences** in the 40 MB image. Compiled out of this build.
* Honoured on a production part: the imageboot/root-device family (`rp0`, `arp0`,
  `rp`, `root-dmg`, `auth-root-dmg`, `rp1`, `container-dmg`, `rd`, `rootdev`,
  `boot-uuid`), `-restore`, `-s`, `-x`, `serial`, `keepsyms`, `wdt`, `jtag`,
  `maxmem`, `cpus` and roughly 190 tuning knobs.

So the ceiling is **a root filesystem we author, running only Apple-signed or
trust-cached binaries, with attacker-chosen argv/env and launchd plists.** Real
and useful; not arbitrary native code. (Caveat kept: that kernel analysis is
18.3's kernelcache — decompressed and adler32-verified by the hunt from the
`complzss` IM4P — while the capability is in 5540's iBoot, and digest pinning
means the two can never run together. If this lead survives the hardware test it
must be redone against 17M61's own kernelcache, which is not staged.)

Note also: **iBoot-5540 never reads the NVRAM `boot-args` variable at all.** The
string appears once, in `nvram_set` at `0x8300221f4`, only to clamp the stored
length. `recovery-boot-args` behind bit 22 is the *only* NVRAM-to-kernel-command-
line channel in the image.

### Resolved: the open question in notes/C-nvram.md S4b

Bit 5 of `0x2_0E029000` is **not a fuse** — it is a GPIO strap. The ROM clears
bits 5 and 6 when it initialises the word; **LLB** then sets them at
`0x18038d01c` (one caller, `0x1803817a4`): `gpio_read(0xd05)` -> bit 5, and bit 6
= valid, always. iBoot's `0x83000d060` is only a fallback for when bit 6 is clear.
Bit 5 selects the restricted 3-entry boot-command table at `0x830047000` versus
the full 8-entry one at `0x830047040` — which also corrects the earlier "two
2-quadword tables" description. `recover` is in **both** tables, so reachability
does not depend on the strap: bit 5 = 0 goes to handler 1 (`0x8300040bc`), which
sets bit 5 and chainloads iBEC, whose restricted table then reaches handler 2
(`0x8300042a0`); bit 5 = 1 goes straight to handler 2.

### The one-boot test, fully specified

iBoot prints `d5edb06dfba10593:<line>` on every failure, so a single cold boot
reports exactly where it stopped. Needs a **working pod** — the bench pod's dead
SEP cannot complete a cold boot.

NVRAM: `auto-boot=true`, `boot-command=recover`, `boot-device=asp_nand`,
`bootdelay=0`, `recovery-boot-args=-v serial=3`. On `asp_nand` partition 1,
mounted at `/boot`: the genuine 17M61 `apticket.der`, `iBEC`, `devicetree`,
`kernelcache`, `applelogo`, `iboot_firmware/`, and **no `OS.dmg`** (if it opens,
`0x830004558` overwrites `recovery-boot-args` with `arp0=file:///boot/OS.dmg`).
Do not press Enter during the delay.

    run 1, genuine ticket     expect line 164  (anrd absent) -> confirms the trace
                              line 186 instead = boot-device name wrong
                                                 (asp_nand is inferred from the
                                                  bdev registration at 0x8300060c4,
                                                  not observed in a live NVRAM)
    run 2, anrd spliced in    line 225 or 310  = digest pinning holds, LEAD CLOSED
                              line 393 or boot = pinning not enforced on this path,
                                                 apticket.der is a full bypass

The DFU oracle cannot answer this: it tests what the ROM enforces, and this gate
is in iBoot stage 2 on the flash path.

---

## 2026-11-24 (late) — the IM4R chased on hardware: parsed, strict, robust. Lead closed.

Pod: the working unit, ECID `<ECID_POD3>`, SRNM `<SERIAL_POD2>`, CPFM:03,
entered boot ROM DFU by the upside-down trick and still unpwned (no
`PWND:[checkm8]`). Ticket `pod3-13.4.8-17M61.shsh2` fetched at nonce
`<APNONCE_REDACTED>` (job 403) and still live for every
send below — the pod did not reboot between 21:01 and 21:29.

Builder: `multipod/im4rlab/build_im4r.py` (ROM round) and `build_ibec.py`
(stage-1 round). Both append an IM4R `[1]` to a genuine, validly-ticketed IMG4
and re-spell only the outer SEQUENCE length. **Not one byte of the IM4P or the
IM4M is touched** except where a variant deliberately corrupts the IM4P payload,
which is stated per variant.

### Round 1 — the unpwned SecureROM, USB path (job 405)

Genuine 17M61 iBSS + live ticket, one IM4R variant per send, malformed first so
a rejection keeps the ROM-DFU session alive:

    trunc      inner SEQUENCE declares 0x20 more bytes than are present  -> REJECTED
    badname    name string "XM4R" instead of "IM4R"                      -> REJECTED
    badtag     name tag 0x17 (T61String) instead of 0x16 (IA5String)     -> REJECTED
    overlong   BNCN OCTET STRING declares 0x7fffffff bytes, supplies 0   -> ACCEPTED, mode=softdfu

**The SecureROM walks the IM4R DER on the USB path.** This was the open question
from the 2026-11-23 round and it is now answered. Three different structural
defects each turn an otherwise perfectly valid, live-ticketed image into a
rejection, which cannot happen if the IM4R is ignored on USB.

**And the decoder is strict about containers but lax about primitive lengths.**
`overlong` is the variant whose every container is self-consistent and whose only
fault is an OCTET STRING claiming 2 GiB. It booted. That is the `min(uVar7,
uVar5)` clamp at `0x830034e9c` behaving as read statically: the span is clamped
to the remaining buffer rather than rejected, BNCN then is not 8 bytes, and the
BNCH comparison is skipped under the `cmp w8,#8` gate at `0x100007fc4`.

### Round 2 — stage 1 (iBSS), USB path (job 408)

Acceptance costs the session, so the battery is built on a **deliberately
corrupted IM4P payload** (one byte flipped at body offset 346485, lengths
untouched) — the digest check must fail, so none of these can be accepted and
all of them are free to fire. Genuine 17M61 iBEC + live ticket otherwise.

    b-noim4r   no IM4R at all                                    -> rejected
    b-wf       well-formed IM4R, 8-byte BNCN                     -> rejected
    b-trunc    inner SEQUENCE overruns by 0x20                   -> rejected
    b-badname  name string "XM4R"                                -> rejected
    b-deep     300 nested SEQUENCEs in the property value        -> rejected, no hang
    b-many     SET of 3000 BNCN properties (75 KB IM4R)          -> rejected, no hang
    b-huge     BNCN OCTET STRING declares 0xffffffffffff bytes   -> rejected, no hang
    g-trunc    GOOD signature + inner SEQUENCE overruns by 0x20  -> REJECTED
    g-wf       GOOD signature + well-formed IM4R                 -> ACCEPTED, mode=recovery

**Stage 1 behaves exactly like the ROM**: `g-trunc` versus `g-wf` is a clean
pair — same image, same ticket, same nonce, differing only in the IM4R's
declared inner length — and only the well-formed one boots. That is the
hardware confirmation of the static read at `0x1803a1118` / `'IM4R'` at
`0x1803a1164`.

**The parser is robust.** 300-deep nesting, 3000 properties and a 2^48-byte
declared length all produce a clean rejection in about a second. No hang, no
crash, no timing anomaly, nothing needing a power cycle. The obvious DER attacks
on this surface do not work.

**On the USB path the IM4R's BNCN is ignored.** `g-wf` carried an 8-byte BNCN
that is not the preimage of the live BNCH, and it was accepted. So the
image-supplied-nonce behaviour is flash-only, as the handle-flag read at
`0x100007f9c` said.

### Verdict

The IM4R is attacker-authored, is parsed pre-emptively on every path we can
reach, and holds. **Closing it as a lead.** It was the last of the two
unverified inputs identified on 2026-11-23; `anrd` in `apticket.der` is the
other and is still open, pending the cold-boot test.

### What this round could NOT settle

Whether the IM4R parse runs *before* or *after* the digest check. Every
bad-signature variant rejects identically whatever its IM4R, and there is no
side channel to separate them: **`irecovery -f` returned exit 0 for accepted and
rejected images alike**, so the only oracle is the USB mode change, which is
binary. Given that the parser survived everything thrown at it, the ordering no
longer decides anything.

### Process notes

* The ROM-DFU session is a consumable. Once an image is accepted the pod leaves
  boot ROM DFU and `gaster reset` does **not** bring it back (job 406, confirmed:
  still softdfu after 25 s). Re-entering needs the physical upside-down DFU
  trick. Order every battery malformed-first, and build the bad-signature
  variants that can never be accepted when you want to fire many probes.
* Corrupting the IM4P payload to guarantee rejection is what made the stage-1
  battery cheap. Worth reusing: it converts a destructive oracle into a free one.
* `img4tool`, `gaster` and `irecovery` are macOS binaries; the bridge shell is a
  Linux VM and cannot run them. Everything that touches the pod goes through
  hp-runner; byte surgery is done in Python on the Linux side.

### The `anrd` gate exists in all three builds — the cold-boot test can run on 18.3

`anrd` is never stored as the ASCII bytes `616e7264`; a raw string search finds
zero hits in all six images, which is why earlier greps missed it. The 4CC is
materialised as a 32-bit immediate:

    movz wN, #0x7264 ; movk wN, #0x616e, lsl #16      -> w = 0x616e7264 = 'anrd'

Encoding-matched across all six images (movz `0x528E4C80|Rd`, movk
`0x72AC2DC0|Rd`): **three sites in each iBoot, two in each LLB, in every
generation.** No literal-pool copy anywhere.

13.4.8 / iBoot-5540, disassembled and confirming the 2026-11-23 claim exactly:

    0x830004794  mov  w2, #0x7264
    0x830004798  movk w2, #0x616e, lsl #16
    0x83000479c  bl   0x8300334c4          ; property lookup
    0x8300047a0  cbz  w0, 0x8300047e8      ; found -> ldrsb the boolean, sub #1
    0x8300047a4  mov  w8, #0xa4            ; 164  <- anrd absent
    0x8300047a8  bl   0x830004800          ; log

18.3 / iBoot-11881, structurally identical:

    0x870003b28  mov  w2, #0x7264
    0x870003b2c  movk w2, #0x616e, lsl #16
    0x870003b30  bl   0x870042bb0          ; property lookup
    0x870003b34  cbz  w0, 0x870003b74      ; found -> read the boolean
    0x870003b38  mov  w8, #0xf6            ; 246  <- anrd absent
    0x870003b3c  bl   0x8700044e4          ; log

**So the one-boot test does not need a 13.4.8 IPSW.** We hold the 18.3 IPSW
already (`homepodstuff/18.3.ipsw`) and an 18.3 ticket is banked for the bench
pod. Run it on 22K557 and expect **line 246** where the 5540 spec said 164.

The downstream expectations (5540's 225 / 310 / 393) do not need porting by
hand: `multipod/bootlog/` has iBoot-11881 indexed, so whatever line it stops on
decodes to a source file and subsystem directly. Getting *past* 246 is the
discriminator; the decoder reads the rest.

Caveat on method: the constant search is an encoding match, so a negative would
not have been conclusive (a compiler may use a literal pool instead). It was
positive in all six, and both sites above were then disassembled and read, so
the conclusion rests on the disassembly, not on the pattern.

### Ready and waiting for the cold boot

* `multipod/im4rlab/splice_anrd.py` — splices a DER BOOLEAN TRUE `anrd` into a
  genuine IM4M's MANP set and re-lengths every enclosing container by rebuilding
  the DER tree. Two self-tests gate it: the 4CC->private-tag encoder must
  reproduce BNCH's known `ff8492b98648`, and parse+reserialise of the untouched
  ticket must be byte-identical. Both pass.
* `multipod/im4rlab/apticket-anrd.der` (4839 B) and `.genuine` (4818 B), built
  from the bench pod's banked 17M61 ticket. `anrd` verified present exactly
  once, outer length consistent, sorted into DER SET order between SDOM and
  snon: `ff868bb9e464 0b 30 09 16 04 'anrd' 01 01 ff`.
* MANP on this ticket holds BNCH BORD CEPO CHIP CPRO CSEC ECID SDOM snon srvn —
  **no AMNM**, as on every genuine ticket we hold. `snon`/`srvn` confirm
  lowercase 4CCs are ordinary in that set, so `anrd` is not anomalous in form.
* Re-splice against the 18.3 ticket before the 22K557 run; the script takes the
  .shsh2 directly and pulls ApImg4Ticket out of the plist.

Still blocked on a physical step: the bench pod spent its ROM-DFU session, and
re-entering needs the upside-down trick.

---

## 2026-11-24 (late) — `anrd` is genuinely issued by Apple. The forging premise was wrong.

The bench pod (`<ECID_POD3>`) turns out to be running **27.0 / 24J361 with
iBoot-15387**, newer than any firmware we hold. Booted the SSH ramdisk on it
(hp-runner gained `sshrd`, `pod-sh`, `pod-put`, `pod-get` for this) and read its
boot volume.

### Where `/boot` actually is

The 2026-11-23 spec said "asp_nand partition 1", inferred from the bdev
registration at `0x8300060c4` and never observed. Observed now:

    /dev/disk0s2 -> container /dev/disk1 -> volume /dev/disk1s1

a small APFS volume whose entire contents are one `boot/` directory. iBoot
mounts it at `/boot`, so `/boot/boot/apticket.der` resolves exactly. Contents:

    apticket.der                      3851 B
    devicetree                       21756 B
    iBEC                            809977 B
    iboot_firmware/staticTrustCache   11208 B
    kernelcache                   22725040 B
    OS.dmg                       205964098 B      <- present
    version.plist   -> 27.0 / 24J361, "Recovery Customer Update Install"

Note the BSD numbering differs from `docs/homepod-nand-map.md` again: here the
main APFS container is disk2 (via disk0s1), Firmware is disk3 and LLB is disk4.
Identify by content, never by disk number.

### The finding that overturns the plan

**That genuine apticket.der already contains `anrd`.** Its MANP set:

    BNCH BORD CEPO CHIP CPRO CSEC ECID SDOM anrd apmv love nrde ostp pndp
    prtp sdkp snon srvn tagt tatp tstp     (AMNM absent, as everywhere)

So the 2026-11-23 conclusion — "`anrd` is in neither of our genuine tickets and
appears in no BuildManifest, so TSS will never return it, and the experiment is
answered negatively offline" — was right about the three builds we had and
**wrong as a general claim**. `anrd` is a normal property of a *recovery /
update-install* ticket. We had only ordinary boot tickets, so we never saw one.

Consequence: there is nothing to forge. On this pod the gate is simply open,
legitimately. The whole "forge `anrd` into an unverified file, then collide with
digest re-pinning" line of attack is moot here, and the interesting question
becomes the one underneath it: **with the gate genuinely open, is
`recovery-boot-args` — an unauthenticated NVRAM variable — honoured on a stock,
fully signed, CPFM:03 pod with no exploit at all?**

### iBoot-15387 recovered, in the clear

`dd` of disk3 (Firmware) and disk4 (LLB), plus `/boot/iBEC`. **No KBAG in any of
them** — 15387 ships plaintext like 18.3 and 26.0.1. iBoot and iBEC payloads are
byte-identical at 806076 bytes and differ only in the 4CC, which is one more
confirmation of the type-swap reconstruction trick.

Staged at `multipod/im4rlab/{iBoot,LLB,iBEC}-15387.payload`.

The `anrd` gate in 15387, same shape as 5540 and 11881 (file offsets):

    0x3b88  movz w2,#0x7264
    0x3b8c  movk w2,#0x616e,lsl#16
    0x3b90  bl   0x43f70            ; property lookup
    0x3b94  cbz  w0, 0x3bbc         ; found -> read the boolean
    0x3b98  movz w8,#0xfd           ; 253  <- anrd absent
    0x3b9c  bl   0x4520             ; log

**The anrd-absent line by build: 5540 -> 164, 11881 -> 246, 15387 -> 253.**
Three `anrd` sites in each iBoot and two in each LLB, in every generation.
(The other two iBoot sites are a 4CC switch at 0x8c28 comparing against 'anrd',
'codp', 'mrd?' and a second lookup at 0x8f04; not the gate.)

Note the link-base literal is NOT at `[0x300]`/`[0x308]` in 15387 — those hold
the ASCII "iBoot-15387". Do not carry the 18.3 offsets forward blind.

### The experiment this leaves

Reversible, and it needs no forging and no firmware write:

1. Move `OS.dmg` aside. Without this, `0x830004558` overwrites
   `recovery-boot-args` with `arp0=file:///boot/OS.dmg` and the measurement is
   lost. It also stops the recover path actually installing anything, which is
   what keeps the test cheap.
2. NVRAM: `boot-command=recover`, `recovery-boot-args=-v serial=3`,
   `bootdelay=0`, `auto-boot=true`. Current NVRAM on the pod is
   `auto-boot=true`, empty `boot-args`, and no boot-command/boot-device/
   bootdelay/recovery-boot-args set at all.
3. Cold boot on the smart outlet, read UART.
4. Past line 253 and a verbose kernel on serial = unauthenticated boot-args
   injection on a stock signed pod. Stopping at 253 = the gate is stricter than
   the ticket's `anrd` alone.
5. Put `OS.dmg` and NVRAM back.

The ceiling is unchanged and already measured: boot-args parse ungated on
CPFM:03, but `debug_enabled` comes from `/chosen/debug-enabled` in the
DeviceTree, so this is not code execution. It would still be verbose boot and
serial on a stock pod with no checkm8, which is worth having in the shop.

### Run 1 on hardware: the gate opened, and the recover path died on a missing file

Set `boot-command=recover`, `recovery-boot-args=-v serial=3`, `bootdelay=0`,
`auto-boot=true`; renamed `OS.dmg` aside; cold-booted on the smart outlet.

The pod boot-loops: iBootStage1 -> iBootStage2 "Local boot" -> iBootStage2
"Remote boot" (IBFL:1C, i.e. the chainloaded iBEC = handler 2) -> reset. It
never enumerates on USB in any mode during the loop, checked over two full
minutes, so **undoing this needs the physical upside-down DFU trick.**

Decoded with the boot-log tooling after indexing the freshly dumped firmware
(`tags/iBoot-15387.tags.tsv`, `tags/LLB-15387.tags.tsv`): 34 distinct tags,
**34/34 resolved to a known source file.** The failure is

    d5edb06fba10593:725

and tag `d5edb06fba10593` is the logger at iBoot-15387 file offset `0x4520` --
the same helper the `anrd` gate at `0x3b98` calls, so the gate and the failure
are in one source file. **Line 253 (`anrd` absent) never fired: the gate passed,
exactly as the genuine ticket's `anrd` property predicts.**

Line 725 disassembled:

    0x0040b0  movz w1,#0
    0x0040b4  bl   0x38f5c                  ; open "/boot/boot/sep-firmware"
    0x0040b8  tbnz w0,#31, 0x40e0           ; negative return -> fail
    0x0040c0  movz w8,#721 ; bl 0x4540      ; success path
    ...
    0x0040e0  movz w8,#725 ; bl 0x4540      ; <- what we saw
    0x0040e8  movz w0,#1   ; bl 0xdedc

**`/boot/boot/sep-firmware` does not exist on this pod**, and neither does
`applelogo`. The staged recovery set is incomplete, so this abort is a
pre-existing property of the pod, not something we caused. Moving `OS.dmg` aside
is irrelevant to it -- the path dies earlier.

So `recovery-boot-args` was never reached and the question it was meant to answer
is still open. Answering it needs a *complete* matched `/boot` set, which rules
out mixing in 17M61's `sep-firmware.b238a.RELEASE.im4p` (digest pinning). The
clean run is on 18.3/22K557, where we hold the whole IPSW and a live ticket.

### Bonus: the bdev names, observed at last

The iBoot-15387 string table settles the 2026-11-23 inference outright:

    asp_nand  asp_llb  asp_effaceable  nand_syscfg  paniclog  nvram

plus the complete recover file list: `/boot/boot/{apticket.der, iBEC, applelogo,
iboot_firmware, devicetree, kernelcache, sep-firmware, OS.dmg}`, the
`recovery-boot-args` name, and the `arp0=file:///boot/OS.dmg` override string.
**`boot-device=asp_nand` was right.**

### Undo, staged

`multipod/im4rlab/restore-pod.sh` deletes the three NVRAM variables we added
(`boot-command`, `recovery-boot-args`, `bootdelay`; `auto-boot` was already
true) and renames `OS.dmg.aside` back. Original NVRAM is in
`multipod/im4rlab/nvram-before.txt`. Needs the ramdisk, so it needs ROM DFU.

---

## 2026-11-24 (late) — Newport: SEP anti-replay, and why our banked blobs are banked wrong

the author surfaced `feiyehua/Newport`: **blackbird on A8 + ART forgery = untethered
downgrade with saved blobs.** Tested by its author on `iPad5,1` / `j96ap` --
**iPad mini 4, A8 / T7000, the same SoC as HomePod 1st gen.** Restore to 11.4
from 15.8.8, confirmed working.

### What it is, precisely

It does **not** break code signing. It defeats **anti-replay**, so firmware
Apple signed *at some point* can be restored again later. You still need valid
blobs. So it does nothing for Nicotine, which is unsigned: Nicotine stays
checkm8-tethered. What it changes is the repair business.

Mechanism: checkm8 -> PongoOS -> **blackbird** (SEPROM bug, misaligned view of
protected memory between AP and SEP) -> code execution in SEP -> read `Key_ART`.
On A8 the anti-replay token lives in NVRAM as `com.apple.System.sep.art`,
DER-encoded, holding a counter, manifest hash, sleep hash, restore nonce and
subcounters, authenticated by `mac32 = HMAC-SHA256(Key_ART, body_DER)`. With
`Key_ART` in hand the ART is forgeable: set the manifest hash to your target's
and the restore nonce to your blob's SNON, recompute the MAC, and SEP boots the
old SEPOS.

The restore-nonce path exists because of OTA: SEP accepts an rsep whose ticket
SNON matches **either** the SEPROM's TRNG SNON for this boot **or** the ART's
restore nonce. Blackbird can't touch SEPROM, so it takes the second branch.

### The part that matters for us, and it is time-critical

From their write-up: the SEP nonce (SNON) **does not** need to be reproducible,
because the ART forgery supplies it. **The AP nonce does.** You set a known
generator in `com.apple.System.boot-nonce`, the device derives APNonce from it,
and your blob stays usable forever.

**Our banked blobs have no generator.** Every ticket in
`~/homepod/tickets/tickets/` was fetched with `tsschecker -N <live nonce>`
against whatever random nonce the ROM had that boot. Those APNonces cannot be
reproduced, so those blobs are **not usable for an untethered restore** -- only
for a tethered DFU boot, which is what we have been using them for.

Only 13.4.8/17M61 and 18.3/22K557 still sign. **Every pod banked without a
generator is banked wrong, and the window is closing.**

### Tested on hardware tonight

* Set `com.apple.System.boot-nonce` from the stock SSH ramdisk ->
  **`privilege violation`**. That is the `p.Bits.KernelOnly` permission bit, and
  it is exactly why Newport's Part II patches the kernelcache.
* Set it from iBoot in recovery (`irecovery -c setenv` + `saveenv`) -> accepted
  silently but **did not take**: NONC was still a fresh random value after the
  reset (`<NONCE_1>...` -> `<NONCE_2>...`, neither equal to
  SHA1(0x1111111111111111) = `3a88b7c3802f2f0510abc432104a15ebd8bd7154`).
* Control, same mechanism, ordinary variable: `setenv auto-boot true` +
  `saveenv` + `reset` -> **worked**, the pod booted into audioOS. So `setenv`
  is fine; the `com.apple.System.*` namespace is specifically protected at both
  the iBoot and the kernel layer.
* `seputil` is present on the SSH ramdisk at `/usr/libexec/seputil` (186 KB),
  so the `--art get` tooling is already there.
* `com.apple.System.sep.art` is **not set** in this pod's NVRAM. Newport's
  pongoterm log shows "Using art read from device tree", so there is a
  device-tree path as well. Worth pinning down before assuming NVRAM is the
  only store.

So the kernelcache patch is genuinely required. SSHRD_Script already builds the
ramdisk; the patch is to clear `p.Bits.KernelOnly` on `com.apple.System.boot-nonce`
and `com.apple.System.sep.art`.

### A workflow win worth more than it sounds

**`auto-boot=false` + `reboot` puts the pod in recovery mode in about 6 seconds**,
with no upside-down DFU trick. Recovery is USB-controllable (`irecovery -c`),
and from there `setenv auto-boot true` + `saveenv` + `reset` returns it to a
normal boot. That removes the "ROM DFU is a consumable" bottleneck that cost us
most of tonight -- the physical trick is now only needed to reach *boot ROM*
DFU specifically (for checkm8), not to regain control of a pod.

### Runner correction

`mode_of` mapped USB product `0x12B0` to `ramdisk`. Wrong: **0x12B0
"AudioAccessory" is both the SSH ramdisk and the normally booted OS** -- the
ramdisk's USB serial is its build date (`ramdisk tool Aug 14 2022 ...`), the
OS's is a 40-hex-char UDID. Fixed in `hp-runner.command`; takes effect at the
next runner restart.

### Next

1. Patch an SSHRD kernelcache to clear the KernelOnly bits.
2. Set one fixed generator on every pod that passes through the shop.
3. Re-bank 13.4.8 and 18.3 blobs against SHA1(generator) for all three ECIDs.
4. Change the app's ticket vault to set the generator *before* it fetches --
   as built tonight it banks blobs that are tethered-only.
5. Only then is blackbird itself worth attempting, and PongoOS will need a
   HomePod target (the atera1n fork is Apple TV; the submodule is not cloned).

---

## 2026-11-24 (late) — demotion traced end to end in the ROM: closed, twice over

Asked directly whether we could demote production pods. Traced it in the
pristine ROM rather than assuming.

**The demote routine exists in SecureROM:**

    0x10000a030  mov  x8, #0x200000000
    0x10000a034  movk x8, #0xe02, lsl #16
    0x10000a038  movk x8, #0xa000          ; x8 = 0x2_0E02A000 (CPFM)
    0x10000a03c  ldr  w9, [x8]
    0x10000a040  and  w9, w9, #0xfffffffe  ; clear bit 0 = production
    0x10000a044  str  w9, [x8]
    0x10000a048  ret

**The full chain, each link with exactly one caller:**

    0x10000a030   demote (above)
      <- b    0x100008a80   one-instruction thunk
      <- bl   0x10000bd98   inside the policy applier at 0x10000bd7c:
                              ldr  w8, [x19,#4]        ; x19 = 0x1800885b0
                              tbz  w8, #0x18, skip     ; bit 24 = demote
                              bl   0x100008a80
      <- bl   0x1000007ec   from the boot task

and bit 24 is set in exactly one place:

    0x100007bb0  ldrb w0, [sp,#0x40]
    0x100007bb4  bl   0x10000bca8     ; csel: w0 != 0 -> set bit 24, else clear

`0x100007bb4` sits **inside the IM4M property evaluator** — the same stack frame
as the EPRO/ESEC comparisons at `0x100007880` / `0x1000078a4`, where
`[sp,#0x40]` and `[sp,#0x41]` hold the ticket's EPRO and ESEC and `[sp,#0x45]` /
`[sp,#0x47]` their presence flags. On mismatch `0x1000078ac` does
`str xzr,[sp,#0x40]`, clearing both values and both presence flags in one
64-bit store, and falls into the CPFM gate (`0x1000078b4` + `FUN_100011910`),
which rejects unless the chip is *already* CPFM:00.

**So demotion is a ticket-driven decision: Apple-signed EPRO/ESEC properties in
the IM4M.** Two independent reasons that is closed for us:

1. **checkm8 does not reach it.** The one-word patch at `0x100007e98` makes the
   property *callback* report success for DGST, CHIP, ECID, BORD, SDOM, CEPO,
   CPRO, CSEC, BNCH — but **EPRO and ESEC are evaluated outside that callback**
   (noted 2026-11-23, confirmed here by their position in the frame). Forging
   them needs a genuine Apple signature over a demotion ticket for our ECID.
2. **It would not persist anyway.** The effect is a write to the CPFM
   fuse-shadow MMIO register at `0x2_0E02A000`, which the hardware reloads from
   the fuse array at every reset — and the ROM sets the lock
   `[0x2_0E02A004] |= 0x80000000` unconditionally later in the same boot
   (`0x10000a130`, read-back-or-panic at `0x10000a140`). A successful demote
   would last exactly one power cycle, i.e. it would still be tethered. (The
   volatility is an inference from the shadow-register pattern and the presence
   of a per-boot lock bit, not a measurement.)

**Verdict: demotion is not a route to untethered on retail silicon.**

### Also mapped: 0x1800885b0 is the ROM's boot-policy block

Nine accessors, all in `0x10000bb24`-`0x10000bd88`. Offset +4 is a 32-bit flags
word: bit 24 demote, bit 25 set at `0x10000bd58`, bit 26 set at `0x10000bd20`
alongside a **0x14-byte copy into +0x18 — the 20-byte manifest digest**, which
is the SRAM-side companion to the PMGR latch at `0x2_0E029000+0x40`. Bits 18
and 19 gate calls to `0x100008604`. `0x10000bc3c` resets the word to `0x20`.
This is the structure iBoot-15387 refers to in
`target_pass_boot_manifest() used without target_init_boot_manifest()`.

### The blind spot in Hunt 2, stated plainly

Hunt 2 was **differential**: 5540 against 11881/13822, using Apple's own patches
as an answer key. That method can only find bugs Apple found and fixed. **A bug
Apple never found is invisible to it.** The ROM is 128 KiB, we now hold it
pristine, and its pre-auth surface is small: the DER walk, the X.509 chain
parse, RSA, and the PKCS#1 padding check. A direct, non-differential audit of
those four is the highest-value untethered hunt left and has not been done.

### Not yet enumerated: the other three boot-strap modes

`FUN_1000082a4` samples three GPIOs (6/6 flat 0x36, 8/4 flat 0x44, 8/5 flat
0x45) into a selector indexing the **4-entry jump table at `0x100000824`**. We
identified the flash arm (`0x1000006ac`) and never looked at the other three.
Straps are physical and permanent, so if any of the other arms has a different
policy it is a hardware mod rather than an exploit. Worth an hour.

### The four boot-strap modes, enumerated: all of them verify

The selector at `0x100000680` is `sub w8, w22, #1 ; cmp w8, #3 ; b.hi` -- so the
strap value must be 1..4. The table at `0x100000824` is **four 32-bit signed
offsets relative to the table's own address**, not pointers:

    0x100000824: 0xfffffe74  -> 0x100000698   ARM 0
    0x100000828: 0xfffffe88  -> 0x1000006ac   ARM 1  (flash, the one we knew)
    0x10000082c: 0xfffffec8  -> 0x1000006ec   ARM 2
    0x100000830: 0xfffffee4  -> 0x100000708   ARM 3

What each does:

* **ARM 0** `0x100000698`: `bl 0x10000de28` with x23, then a string at
  `0x100015780`, then joins ARM 2's tail.
* **ARM 1** `0x1000006ac`: init `0x100001b14`, `read_llb(0x180380000, 0x80000)`
  at `0x100001b4c`, size-capped at `0x80000`, then **`img4_open(..., flags=4)`
  at `0x10000f610`**.
* **ARM 2** `0x1000006ec`: `mov x0, x21 ; bl 0x100000834`, the shared loader.
* **ARM 3** `0x100000708`: `bl 0x1000089b4(1)`, then a **different** reader
  `0x10000edbc(0x180380000, 0x80000)`, same `0x80000` cap.

**All four converge.** Arms 0 and 2 meet at `0x1000006f0`/`0x1000006f4`, arm 1
at `0x1000006f4`, and every path reaches the `'illb'` type check at
`0x1000006fc` (`w8 = 0x696c6c62`) and then the same `img4_eval` at
`0x1000007c8`. The strap chooses **where the image comes from**, never whether
it is verified.

**So the straps are not a route to untethered.** Worth one line for another
purpose though: ARM 3 reads the same address range through a different function
(`0x10000edbc` vs flash's `0x100001b4c`), so there is at least one alternative
boot medium the ROM will load a *signed* LLB from. That could matter for
recovery work on pods with dead NAND -- it does not help with unsigned code.

---

## 2026-11-25 — the non-differential ROM audit: no untethered, but four real defects

Three independent audits of the pristine SecureROM, deliberately **not**
differential, to cover the blind spot in Hunt 2 (which could only find bugs
Apple had already fixed). Scopes: the DER/ASN.1 library, the X.509 chain and
RSA/PKCS#1, and the IM4M property evaluator. Combined coverage 56%, 74% and 84%
of their subtrees read instruction by instruction.

**Headline: all three independently found no way to boot non-Apple-signed code
on an unexploited ROM, and no pre-authentication memory corruption.** The
verification core is bounded and fails closed. What follows is what they did
find.

### Corrections to our own notes, found by the audits

* **`BRIEF-ROM.md` cited the wrong sha256 for the pristine ROM** -- it quoted
  `5c4fc92b...`, which is the *checkm8-patched* dump. Pristine is
  `8fd1d787...`. Two agents caught it independently. Corrected.
* **`0x100006ab4` is `malloc`, not the DER parser.** The real DER library is
  `0x1000112f8`-`0x100013400`; the IMG4 evaluator is `0x100007574`. My scoping
  of the audit was wrong and both agents re-derived the subtree correctly rather
  than running with it.
* **`0x1000102b4` is `31 - clz(x)` and `0x100010344` is `vsnprintf`** -- neither
  is crypto. Also mis-scoped by me.
* **checkm8's patched word is the stack-cookie-mismatch branch** in the epilogue
  of the property callback `0x100007c20`, not a property comparison branch.
  Forcing `x0 = 0` there makes every comparison report success *and* disables
  that function's cookie check.
* **Our "the ROM clamps an over-long length" reading was wrong.** There is
  exactly one clamp (`0x100007304`), it is in the header peek, and the declared
  total is re-validated against the real buffer at `0x100007700`/`0x100007784`.
  The hardware result (an over-long BNCN booting) is better explained by the
  strict decoder erroring, BNCN then being unavailable, and the BNCH check being
  skipped under the length-8 gate. Same outcome, different and better-evidenced
  mechanism.

### 1. The stack cookie is a hard-coded ROM constant: `"DRAG"`

Found independently by two audits. Every `__stack_chk` site in the ROM (30 of
them) loads `[0x180080198]`; **nothing in the 128 KiB ever stores to it.** It is
initialised by the reset vector's `.data` copy from ROM `0x100019198`, verified
in the image: `44 52 41 47 00 00 00 00` = `0x47415244`, "DRAG". Zero entropy,
identical on every boot, on every pod.

**Not a bug you can fire, but it means the ROM has no real stack-overflow
mitigation.** Any linear overflow can simply write the cookie back. That raises
the value of every overflow find, including the three already recorded in
LLB/iBoot **if those builds share the constant -- worth checking.**

Cheap confirmation when a pod is next pwned: `gaster peek 0x180080198 8`,
expect `44 52 41 47 00 00 00 00`.

### 2. RSA modulus limb count is bounded 8x too loose -- latent EL3 code execution

`0x1000130b4`. `rsa_verify` has a fixed `0x360` frame with room for **32 limbs**
(2048-bit). The only guard admits **256**:

    0x1000130ac  lsr x23, x8, #3      ; nlimbs = ceil(modulus_bytes/8)
    0x1000130b4  cmp x23, x8          ; x8 = 0x100
    0x1000130b8  b.hi 0x100013128     ; the ONLY bound

Context extent is `0x18 + 24n`; the frame holds `0x328`. Measured by unicorn
emulation: 2048-bit writes nothing past the frame, 2816-bit writes 120 bytes
past entry sp, 4096-bit 600 bytes, 16384-bit 5208 bytes. **At >= ~2500 bits it
overwrites the saved LR**, at EL3 with the MMU off. The furthest-reaching array
is the **exponent**, a free DER INTEGER in the certificate, so the overflow
content is fully attacker-chosen -- and with the fixed "DRAG" cookie the canary
is no obstacle.

**Not exploitable today.** Both call sites take a key that is either the
ROM-embedded Apple Root CA or a certificate Apple has already signed. Triggering
it needs an Apple-issued Secure Boot certificate with a key of >= ~2500 bits.

Worth recording precisely because the authentic configuration sits *exactly* on
the edge: Apple's current certs are 2048-bit, n=32, which fits with 16 bytes
spare. **If a 3072-bit Apple Secure Boot certificate ever appears for any
device, this becomes a full EL3 compromise of an unexploited ROM.**

**Measured, 2026-11-25:** every certificate in every ticket we hold is
**2048-bit** -- three ECIDs x both signed builds, plus the bench pod's own
27.0/24J361 recovery ticket (which is the newest Apple signing we have sight
of, from iBoot-15387). So n=32 everywhere, 16 bytes spare, and the defect is
dormant. It arms the day Apple moves this chain to 3072-bit.

### 3. Uninitialised-stack BNCN lookup -- reachable on a cold flash boot

The best new finding. `0x100012150` (IM4R property lookup) returns **0 =
success without writing the caller's output struct** on two paths:

    0x100012164  cbz x9, 0x10001217c     ; IM4R SET ptr NULL  -> success
    0x100012170  cbz w9, 0x10001217c     ; IM4R SET len zero  -> success

The caller `0x100012184` trusts the return code and reads its own
never-zeroed frame:

    0x1000121cc  ldr x8, [sp, #0x18]     ; UNINITIALISED -> BNCN pointer
    0x1000121d4  ldr w8, [sp, #0x20]     ; UNINITIALISED -> BNCN length

Then in the callback, `0x100007fc4 cmp w8,#8 / b.ne 0x100007e8c` -- **if the
stale length is not 8, the BNCH check is silently skipped.**

Reachable on the flash path specifically: `img4_open` is called with `w2 = 4`
at `0x1000006dc`, setting handle-flag bit 2, which selects the IM4R-BNCN branch.
DFU passes 0 and uses the latched hardware nonce instead. The IM4R is IMG4
field[3], optional, and outside the IM4M signature. Two triggers, both of which
leave the manifest untouched and still valid:

* delete the IM4R entirely, or
* keep a well-formed one with an empty SET: 12 bytes,
  `A1 0A 30 08 16 04 'IM4R' 31 00`.

The tell that this is an oversight rather than design: an IM4R that is *present
with a non-empty SET but no BNCN* is **fatal**, while an *absent* IM4R is
"success with garbage".

**What it is worth, honestly.** It does not boot unsigned code -- the manifest
is still Apple-signed and DGST still binds the payload. It is an anti-replay
bypass that needs neither the nonce nor the generator. On top of a nonce
mechanism that was already vacuous on this path (finding 4 below), so the
marginal gain is small. **One cold boot settles it**: write the empty-SET IM4R
variant to `asp0n2` and see whether it boots (stale length != 8, check skipped)
or fails (stale length happened to be 8).

### 4. BNCH on a cold flash boot is structurally vacuous -- with its address

The decision is `0x100007f9c`. With handle-flag bit 2 set (flash), BNCN is read
from the **IM4R**, which is unsigned and travels in the same file; the ROM
compares the signed BNCH against SHA-1 of 8 bytes the image itself supplies.
With bit 2 clear (DFU) it uses the hardware-latched nonce at
`0x2_0E029038/3c`. This is the mechanical explanation of the ground truth we
established on hardware, now with an address.

### 5. What closes the "skip-on-absent" hole: the certificate constraint list

Every one of the 14 ROM-evaluated properties is skip-on-absent at the callback
level -- `0x100012560` only invokes the callback for elements that are present,
and nothing in `0x100007574` requires DGST to exist. **A DGST-less `illb`
object would boot an arbitrary payload under a valid signature.**

That is closed one layer up by `0x100012338`, which had to be reversed to find
and is not in our previous notes. The leaf certificate carries a constrained-
property extension (OID 1.2.840.113635.100.6.1.15) which the ROM enforces. For
Apple's real b238a signing cert it makes **DGST, EPRO, ESEC, BORD, ECID, CPRO,
CSEC and BNCH mandatory-present**, and pins CHIP, CEPO and SDOM to exact values.

Two caveats nobody resolved: an **empty** constraint SET returns success
outright (`0x1000123a4`), and the check is one-directional -- properties present
in the manifest but absent from the certificate's list are not rejected.

### 6. Two hardening gaps that are Apple's problem, not a route for us

* **`e = 1` is accepted.** No exponent whitelist, no minimum, no odd-ness check.
  In the modexp `0x10001558c`, `cmp x22,#1 / b.eq 0x100015710` returns the base
  unchanged, so the "signature" is used verbatim as the PKCS#1 encoded message.
* **The chain walk enforces no CA constraints**: no basicConstraints, no
  keyUsage, no validity period; the `critical` flag is parsed and never read.
  Any Apple-Root-issued certificate whose subject CN DER byte-equals the pinned
  43-byte `"Apple Secure Boot Certification Authority"` can serve as the
  intermediate.

Both are walled off by the requirement that Apple signed the certificate.

### 7. The `str xzr,[sp,#0x40]` lead I handed them: dead, and closed by proof

The 8-byte store clears `{DPRO, unused, EKEY, AMNM, EPRO-val, EPRO-seen,
ESEC-val, ESEC-seen}`. Each clear fails safe: DPRO cleared means the demote bit
is *not* set; EKEY cleared skips AES and hands over an encrypted payload; AMNM's
only reader executes earlier in program order; nothing reads `+0x44..0x47`
afterwards.

More decisively, the path cannot succeed at all on a retail part, and this was
settled **without a hardware read**: the genuine b238a manifest has `EPRO=TRUE`
and no `DPRO`, the device demonstrably cold-boots it, therefore
`[0x2_0E02A000].bit0 = 1`, therefore `0x100011910()` returns 1, therefore
`0x1000078c0` always branches to the hard fail. The lenient path is
CPFM:00-only.

### 8. What was verified sound -- the negatives that matter

* **PKCS#1 v1.5 is complete and strict.** Proven by emulation, not just
  reading: all 384 single-byte mutations of a 128-byte block rejected; a
  Bleichenbacher-style `00 01 FF 00 DigestInfo || garbage` block rejected; a
  zero-filled PS rejected. The DigestInfo is byte-compared against a ROM
  template rather than re-parsed, so there is no BERserk-style parameter
  wiggle room, and the structure is anchored to `emLen` with no slack. **This
  was the most promising target and it is closed properly.**
* **Signature length is pinned** to exactly the modulus byte length
  (`0x100014b14`); modulus leading zeros are stripped before the limb count is
  derived, so zero-padding cannot inflate `n`.
* **Chain depth is exactly 3**, root pinned **by value** (the full 1215-byte
  Apple Root CA is in ROM at `0x100017e30`; serial 2, 2048-bit, e=65537).
  Emulated: 1, 3 and 4 certs all rejected.
* **No recursion anywhere in the DER/IMG4 parsers.** The grammar is fixed-depth
  and table-driven, so deep nesting is rejected positionally -- which is why our
  300-deep hardware test rejected cleanly.
* **The DER decoder is careful**: minimality enforced, indefinite length
  rejected, two tag-number overflow guards, long form capped at 4 octets,
  leading-zero length rejected. The lenient mode has exactly one caller and its
  result is re-validated twice.
* **Ordering is sound.** Nothing attacker-derived is acted on before
  verification; every boot-policy write to `0x1800885b0` happens after.
* **Return codes**: all 103 call sites of the 41 status-returning functions
  check or propagate, with one benign exception.

### Bottom line

The ROM's verification core is in good shape and the untethered-via-ROM-bug
route is, on this evidence, closed. The four defects are real but each is walled
off by requiring an Apple signature somewhere upstream. The two things worth
carrying forward are the **"DRAG" cookie** (it devalues every future overflow
mitigation claim, in the ROM and possibly in LLB/iBoot) and the **latent RSA
modulus overflow** (armed the day a larger Apple cert appears).

### Open, cheap, not yet done

1. `gaster peek 0x180080198 8` -- confirm the cookie is `DRAG` at runtime.
2. ~~Modulus bit lengths~~ -- done, all 2048-bit, see finding 2.
3. Do LLB and iBoot share the `0x47415244` cookie constant? If so, the three
   known defects there are worth re-rating.
4. One cold boot with the empty-SET IM4R to settle finding 3.

### Answered immediately: NO stage of this boot chain has a real stack cookie

Open question 3 above, closed by inspection of all nine images we hold:

    SecureROM     "DRAG" = 0x47415244            ROM file offset 0x19198
    LLB-5540      0x4752400444303631             0x2a298
    iBoot-5540    0x4752400444303631             0x483d8
    LLB-11881     0x4752440044303631             0x30a40
    iBoot-11881   0x4752440044303631             0x5fd10
    LLB-13822     0x4752440044303631             0x31a60
    iBoot-13822   0x4752440044303631             0x62db0
    LLB-15387     0x4752440044303631             0x31a98
    iBoot-15387   0x4752440044303631             0x62dd8

Every one is a **fixed build constant with zero entropy**. The ROM's differs
from the firmware's, and 5540's differs from the rest, but **11881, 13822 and
15387 share the identical value** -- Apple has not rotated it across 18.3,
26.0.1 and 27.0, i.e. over the whole span of firmware we have sight of,
including the September 2026 build.

**Consequence: every stack-overflow mitigation in this boot chain is cosmetic.**
Any linear overflow can write the correct cookie back. The three defects
previously recorded in LLB/iBoot should be re-rated on that basis, and so should
the ROM's RSA modulus overflow (finding 2 above) -- the canary there is not an
obstacle either, and the overflowing bytes are the attacker-chosen exponent.

This does not by itself give unsigned boot. It changes the price of every future
overflow find in this chain from "needs a canary leak as well" to "needs
nothing else".

---

## 2026-11-25 — DFU entry is two GPIO pins, measured on the live pod

### The decision, in the boot task

    0x100000520  bl 0x1000089c4   ; x19 = (gpio 0xd04 != 0)
    0x100000528  bl 0x1000089e4   ; w0  = (gpio 0x401 == 0)
    0x10000052c  mov w20, #1
    0x100000530  cbz w0, 0x10000053c      ; gpio 0x401 != 0  -> w20 stays 1
    0x100000534  bl 0x100008a04   ; w0 = (gpio 0x400 == 0)
    0x100000538  eor w20, w0, #1          ; w20 = (gpio 0x400 != 0)
    0x10000054c  mov w0, #0
    0x100000550  cbz w19, 0x100000558     ; gpio 0xd04 == 0 -> skip
    0x100000554  bl 0x1000089a0           ; else w0 = extra condition
    0x100000558  orr w8, w0, w20
    0x10000055c  tbnz w8, #0, 0x100000628 ; -> DFU

**A normal boot requires GPIO 4/0 == 0 AND GPIO 4/1 == 0.** Either one high
forces DFU. A third path exists: if GPIO 13/4 is high, `0x1000089a0` ->
`0x100002648` reads **bit 8 of MMIO `0x2_0C000034`** and that can force DFU too.

### gpio_read decoded

`0x100002aa4`: id = `(bank << 24) | (port << 8) | pin`.

    offset = (((port << 3) & 0xf8) | pin) << 2        ; i.e. "flat" << 2
    base   = [0x180080690 + bank*0x18]
    return   [base + offset] & 1

Measured `[0x180080690]` on the pod = **`0x2_0E300000`** (GPIO bank 0 base).

### Live read, pod in ROM DFU (rom-peek 0x20E300000 +0x200)

    gpio  4/0  off 0x080  0x00070201  level=1   <- DFU condition A
    gpio  4/1  off 0x084  0x00070201  level=1   <- DFU condition B
    gpio 13/4  off 0x1b0  0x00070280  level=0
    gpio 13/5  off 0x1b4  0x00070283  level=1   (DFU indicator, driven by ROM)
    gpio  6/6  off 0x0d8  0x0007000e  level=0   strap selector bit 0
    gpio  8/4  off 0x110  0x0007000e  level=0   strap selector bit 1
    gpio  8/5  off 0x114  0x0007000e  level=0   strap selector bit 2
    gpio  7/4,7/5,7/6,6/4,8/6         0x0007000e  level=0   BORD bits

Register bit 0 is the pin level (what `gpio_read` returns). Bit 7 appears to be
output-enable: set on 13/4 and 13/5 (both `0x02 8x`), clear on 4/0 and 4/1
(`0x02 01`), so **4/0 and 4/1 are inputs currently reading high.** The straps
carry a different configuration byte entirely (`0x00 0e`).

### What this means

**The upside-down DFU trick asserts GPIO port 4, pins 0 and 1.** It is not an
accelerometer decision made in software -- it is two pins the SecureROM samples
before anything else runs. Pull them high at power-on and the ROM enters DFU.

That is the missing piece for an automated bench fixture: a board that asserts
two pins and then speaks checkm8 over USB takes a pod from cold to Nicotine with
no laptop and no hand-flipping. The remaining work is purely physical -- find
which pads on the b238a board carry GPIO 4/0 and 4/1.

**Honest limit on this result:** we can only `rom-peek` while the pod is in ROM
DFU, so we measured the DFU state and not the normal-boot state. The claim
"high forces DFU" rests on the ROM code above plus this one measurement showing
both pins high while in DFU. Confirming they read 0 on a normal boot needs a
different method (a scope on the pads, or Nicotine reading the same registers).

---

## 2026-11-25 — a write primitive, and why the demotion test is NOT yet answered

### Live register reads in ROM DFU (pod pwned, read-only)

    0x2_0E02A000 = 0x00010297   CPFM bits0/1 = 3 (production+secure)
                                SDOM=(>>2)&3 = 1   CEPO=(>>9)&0x7f = 1
    0x2_0E02A004 = 0x20000000   production LOCK bit31 = 0   <-- NOT set in DFU
    0x2_0E029000 = 0x01380203   enforce(bit3)=0  digest-valid(bit4)=0
                                BORD=(>>16)&0xff = 0x38  (matches BDID:38)
                                nonce +0x38: <NONCE_REDACTED>
                                digest +0x40..53: all zero
    0x1800885b4  = 0x302c0000   demote(24)=0 bit25=0 digest-valid(26)=0
                                bits 18,19,21,28,29 set; digest +0x18: all zero

SDOM=1 and CEPO=1 match exactly the values the audit found **pinned by Apple's
signing certificate** (`CEPO = INT 01`, `SDOM = INT 01`). Independent
confirmation of that certificate-constraint work.

The zeroed digest and cleared enforce/digest-valid bits are expected: this power
cycle went straight to DFU and never did a flash boot, so the ROM never latched
anything.

**The production lock is open in DFU.** That is what made the demotion test look
testable.

### gaster gained a `poke`, and it works

`multipod/rompeek/gaster.c` now has `gaster_poke` plus a `poke addr bytes` CLI,
and hp-runner has a `rom-poke ADDR BYTES` action (original saved as
`gaster.c.pre-poke`). The request buffer is staged at `insecure_memory_base`, so
bytes appended after the 5-quadword command struct are already in device memory
at `insecure_memory_base + 0x28`; the poke just points the payload's memcpy at
them.

**Validated on scratch SRAM:** wrote `deadbeefcafe1234` to `0x180381000`, read
it straight back. The primitive is sound.

### The CPFM write faulted -- and the cause is UNRESOLVED

`rom-poke 0x20E02A000 96020100` (clear CPFM bit 0, keep the rest) returned
failure and the pod **reset and booted normally**. No damage; it was back in
audioOS seconds later.

The obvious reading is "CPFM is write-protected despite the lock being clear".
**That reading is not supported, and the next test is why.** Attempting
`rom-peek 0x20E3001B4 0x8` -- a *read*, of a GPIO register inside the same
0x200-byte window that had been **read successfully 20 minutes earlier** as part
of a bulk aligned read from `0x20E300000` -- also faulted and reset the pod.

So **MMIO access through the ROM's `memcpy` is fragile and
alignment/width-sensitive**: a page-aligned bulk read works, an 8-byte read at
offset 0x1B4 does not. `memcpy` is simply the wrong instrument for a device
register; it has no reason to emit a single aligned 32-bit access.

Therefore the CPFM write failure may be protection, or it may be the same
artifact. **We cannot tell yet, and the earlier reasoning that treated the
failure as evidence about demotion is withdrawn.**

### The correct next step

Stop using `memcpy` for MMIO. gaster already carries an **exec** primitive
(`EXEC_MAGIC`, `func_gadget`, `exec_cmd.x[0..]`) used for `aes_crypto_cmd`. The
right tool is a tiny gadget that performs one `ldr w` / `str w` at a given
address, invoked through that path, so the access width and alignment are ours
to choose. Then:

1. 32-bit read of `0x2_0E02A000` through exec -- confirm it matches the bulk read.
2. 32-bit write clearing bit 0; read back.
3. If CPFM reads 00, send a deliberately **unsigned** image and see whether the
   unexploited accept-unverified path at `0x1000078b4` opens.

That sequence settles soft demotion properly. It is still volatile either way --
the shadow register reloads from fuses at every reset -- so it would confirm the
model, not deliver untethered. But it would reduce "untethered" to exactly one
sentence: make CPFM:00 survive a power cycle.

### Process note

I aimed an untested write primitive at the most sensitive register on the chip
before validating it on scratch. The validation took one job and should have
come first. Cost: two DFU sessions and two hand-flips.

---

## 2026-11-25 — SOFT DEMOTION WORKS on bit 0. Bit 1 unresolved.

The memcpy-based poke was the wrong instrument (previous section). The right one
is **calling the ROM's own code**: gaster already has an exec primitive, so
`gaster_call(func, x0, x1) -> x0` was added (`call` CLI, `rom-call` runner
action). It invokes Apple's routines, so every register access keeps the width
and alignment the ROM intended.

### The result (job 441, clean run, everything else in the job working)

    rom-call 0x10000a000   -> 1      ; ROM's own "read CPFM bit 0"
    rom-call 0x10000a04c   -> 1      ; ROM's own "read CPFM bit 1"
    rom-peek 0x20E02A000   =  0x00010297    CPFM = 03
    rom-call 0x10000a030             ; the ROM's own DEMOTE routine
    rom-call 0x10000a000   -> 0      ; bit 0 now CLEAR
    rom-call 0x10000a04c   -> 1      ; bit 1 still set
    rom-peek 0x20E02A000   =  0x00010296    CPFM = 02

**Soft demotion of CPFM bit 0 works on this chip**, confirmed two independent
ways in the same run. The production lock at `0x2_0E02A004` bit 31 is clear in
DFU, and the ROM's own `0x10000a030` happily clears the production bit.

**It does not open the gate.** `FUN_100011910` is

    bit1 ? 1 : bit0

so with bit 1 (secure mode) still set it returns 1, and `0x1000078c0` still
branches to the hard fail. An image with a deliberately corrupted IM4M RSA
signature (genuine 17M61 iBSS, valid live ticket, one byte flipped at
signature+10) was sent at CPFM:02 and **rejected**, as the gate predicts.

### Bit 1: attempted, NOT established

Found the only store gadget in the ROM: `0x10000b890` = `str w1,[x0,#4] ; ret`.
Called with `x0 = 0x20E029FFC` it writes `0x2_0E02A000`. The call returned, but
a read-back still showed `0x00010296` -- bit 1 unchanged.

**That is not yet a finding, and must not be recorded as one.** Immediately
afterwards the whole peek/exec machinery degraded: reads of scratch SRAM, of
unmapped pages, and finally **of the ROM itself at `0x100000000`** all began
failing, while the pod still enumerated as romdfu. Something in that sequence
(the MMIO store, or repeated re-exploitation across many gaster invocations)
left the payload non-functional. So the bit-1 read-back may have been taken from
an already-broken state.

What we can say: **bit 0 is clearable, and that alone is not enough.** Whether
bit 1 is hardware-locked or merely wasn't written is open.

### How to settle it next time

1. Fresh power cycle into ROM DFU, and **minimise gaster invocations** -- each
   `rom-call`/`rom-peek` re-enters checkm8, and the accumulation is what appears
   to have degraded the payload. A single job with one exploit and several
   commands would be better than many jobs.
2. Validate the store gadget on known-good scratch (`0x180381000` is mapped;
   `0x180382000` and `0x1803A1000` are NOT -- the writable window is narrow)
   **before** aiming it at CPFM.
3. Then the bit-1 write, read-back, and only then the unsigned-image send.
4. Add a cheap liveness check at the top of every job: peek `0x100000000` and
   compare against the known ROM bytes. If that fails, the payload is dead and
   every later result in the job is void. This would have caught tonight's
   degradation immediately.

### Where this leaves demotion

Half-answered, and much better specified than this morning. The ROM contains a
working demote for the production bit and we can invoke it at will. The gate
checks secure mode first, so demotion is only useful if bit 1 can also be
cleared -- and that is the single open question. Even if it can, it stays
volatile: the shadow register reloads from fuses at every reset, so it would
confirm the model rather than deliver untethered.

---

## 2026-11-25 — corrected: what kills the payload, and CPFM bit 1 settled

### The previous section's diagnosis was wrong

I blamed "accumulated re-exploitation". **It is not that.** `gaster_checkm8`
already detects a pwned device and skips the exploit (`checkm8_check_usb_device`
-> `pwned` -> `STAGE_PWNED`), which is why every invocation printed "Now you can
boot untrusted images." without running the stages.

**The killer is `send`.** `irecovery -f` writes the image into the DFU buffer at
**`0x180380000`** -- which is `insecure_memory_base`, exactly where the checkm8
payload and its command structs live. One send destroys the pwned state. The pod
keeps enumerating as romdfu because the ROM's own USB stack is untouched; only
our payload is gone, so every later peek/call fails.

**Rule: in any job, all `rom-peek` / `rom-poke` / `rom-call` work comes FIRST and
`send` comes LAST.** Nothing after a send is meaningful.

This also rehabilitates the earlier bit-1 read-back: in job 442 it was taken
*before* the send, so that state was healthy after all.

### Liveness check, now standard

Put `rom-peek 0x100000000 0x8 liveN.bin` at the top and bottom of every job.
Healthy payload returns **`0000009000000091`** (the ROM's first two
instructions). Anything else means the payload is dead and every result in that
job is void.

### CPFM bit 1 is hardware write-protected — controlled result (job 450)

One job, no send, liveness verified at both ends (`0000009000000091` both
times), and the write primitive proven effective **in the same run**:

    rom-peek 0x100000000            -> 0000009000000091      (payload healthy)
    rom-peek 0x180381000            -> 0000000000000000
    rom-call 0x10000b890 0x180380FFC A5A5A5A5                (the store gadget)
    rom-peek 0x180381000            -> a5a5a5a500000000      <-- GADGET WRITES
    rom-peek 0x20E02A000            -> 0x00010297   CPFM 03
    rom-call 0x10000a030                                     (ROM's own demote)
    rom-call 0x10000b890 0x20E029FFC 0x10294                 (try to clear bit 1)
    rom-call 0x10000a000            -> 0                     bit 0 CLEAR
    rom-call 0x10000a04c            -> 1                     bit 1 STILL SET
    rom-peek 0x20E02A000            -> 0x00010296   CPFM 02
    rom-peek 0x100000000            -> 0000009000000091      (payload still healthy)

The gadget is demonstrably functional, the write to `0x2_0E02A000` executed, and
**bit 1 did not move.** The same store that puts `a5a5a5a5` into SRAM cannot
clear CPFM bit 1.

**Conclusion: on T7000, CPFM bit 0 (production) is software-clearable via the
ROM's own `0x10000a030`; bit 1 (secure mode) is locked in hardware.** The
accept-unverified gate `FUN_100011910` is `bit1 ? 1 : bit0`, so it tests secure
mode first and demotion can never open it. **Soft demotion is not a route to
unsigned boot on this chip, and that is now measured rather than inferred.**

### Working unattended: the pod re-enters DFU on a power cycle

With the pod left **upside down**, a Kasa power cycle brings it back to **boot
ROM DFU in about 5 seconds** -- confirmed. No hand-flip needed.

Two consequences. First, a dead payload is now self-recoverable: power cycle and
carry on. Second, it is an independent confirmation of the GPIO finding --
orientation decides DFU entry at power-on, exactly as `0x100000520`-`0x10000055c`
reads it from GPIO 4/0 and 4/1.

---

## 2026-11-25 — what CPFM:02 gets you: nothing, and it breaks signed boot

Controlled pair, same genuine 17M61 iBSS, each with its own freshly fetched
ticket for that boot's nonce, same `pwn -> gaster-reset -> send` order, differing
in exactly one step.

**Control (job 452), CPFM:03:**

    ticket + img4 wrap, pwn, gaster-reset, send genuine  ->  ACCEPTED, mode=softdfu

**Test (job 453), CPFM:02:**

    ticket + img4 wrap
    rom-peek 0x100000000   -> 0000009000000091     (payload healthy)
    rom-call 0x10000a000   -> 1
    rom-call 0x10000a030                            (demote)
    rom-call 0x10000a000   -> 0
    rom-peek 0x20E02A000   -> 0x00010296  CPFM 02
    gaster-reset, send genuine                 ->  REJECTED, mode=romdfu

**Demoting to CPFM:02 turns a genuine, validly-ticketed Apple image from
accepted into rejected.** This is what the ROM predicts: `0x10000bccc` derives
the *expected* EPRO from the production bit, the ticket carries `EPRO = TRUE`,
clearing production makes expected = 0, the comparison at `0x100007880`
mismatches, and the mismatch falls to `0x1000078ac` -> the CPFM gate -> which is
shut because bit 1 is still set.

### So the answer to "what can we do with soft demotion" is: nothing

* It does **not** open the accept-unverified path -- bit 1 is locked in hardware.
* It **does** break genuine signed boot.
* It is volatile regardless; the shadow register reloads from fuses at reset.

Soft demotion on T7000 is a strictly negative capability. Closing it.

### Two procedural facts worth more than the result

1. **`send` after pwning is silently ignored unless `gaster-reset` comes
   first.** Job 451 sent a genuine image with a fresh ticket to a pwned ROM and
   it did nothing -- the pod sat in romdfu. The canonical order is
   `pwn` -> `gaster-reset` -> `send`, which is what `boot-nicotine` has always
   done. **This voids the "unsigned image rejected" result from job 442**: that
   send was ignored, not rejected. Any send-based oracle must prove itself with
   a positive control in the same session.
2. **The DFU serial string does not reflect a live demote.** After demoting, the
   USB serial still advertised `CPFM:03` while the register read `0x00010296`
   (CPFM 02) -- the descriptor is built at enumeration, before any of our code
   runs. Read the register, never the banner, when CPFM matters.

---

## 2026-11-25 — where to probe for the DFU pins: it is not an accelerometer

### The teardowns rule out orientation sensing

iFixit (teardown 103133) and TechInsights both enumerate every chip in the
HomePod. **Neither finds an accelerometer, gyroscope, IMU or any orientation
sensor.** iFixit: "Accelerometer or motion sensor: None is identified."
TechInsights: "does not mention an accelerometer, gyroscope, IMU, or any
orientation sensor"; the only extra sensor named is an ambient light sensor.

So **"upside-down DFU" is not the device detecting that it is upside down.**
Nothing in it can tell the SoC which way up it is, and SecureROM in any case
reads two raw GPIOs (4/0 and 4/1) long before any I2C sensor could be brought up.

### What is actually asserting those pins — the two candidates

**1. The capacitive touch surface, via the Cypress PSoC (most likely).**
The touch/LED board carries a **Cypress PSoC 4 CY8C4245LQI-483** (ARM Cortex-M0)
driving a grid of capacitive divots on the top surface. A PSoC is a
general-purpose MCU with its own GPIOs and it boots in milliseconds -- it is
exactly the part that would assert a "DFU requested" line to the SoC when the
touch surface is held at power-on. **Placing the HomePod face-down on a table
covers the entire capacitive grid, which is electrically the same as holding
it** -- which is the conventional way to force DFU on this device. That explains
the trick without any orientation sensing, and it predicts the pins are driven
from the touch board over its ribbon cable to the main logic board.

**2. The 14-pin factory port under the rubber foot.**
iFixit Step 5 finds a **14-pin port under the base foot**, "probably used to
test or program HomePods on Pogo pins during assembly." A factory programming
port is the other natural home for a force-DFU strap, and it is the one that
matters for a fixture -- it is already where the Table_Dock pogo pins land.

### How to find them on the bench, cheapest first

1. **Probe the touch-board ribbon during a power-on.** Meter or scope on each
   ribbon conductor; compare a normal power-on against the face-down power-on.
   Two lines should differ. That is a handful of contacts rather than a BGA
   ball-out, and it needs no chip-level work.
2. **Probe the 14-pin base port the same way.** If the signals appear there too,
   the fixture is purely a dock -- no soldering inside the pod at all, which is
   the best possible outcome for a bench tool.
3. Only if both come up empty does this become an A8 ball-out problem, and the
   A8's GPIO ball map is not public.

### Why this matters beyond convenience

If the pins are reachable at the base port, a dock can assert them at power-on
and then speak checkm8 over USB -- cold pod to Nicotine, no laptop, no flipping,
nothing opened. The ROM work is done; this is the remaining piece and it is a
continuity-test problem, not a reverse-engineering one.

**Caveat:** the PSoC attribution is a deduction from the parts list and the
ROM's two-GPIO read, not something measured. The probe in step 1 is what
confirms or kills it.

### The 14-pin base port, seen

Pulled the teardown images at full resolution (iFixit guide 103133 via their
API; saved under `multipod/teardown/`, **iFixit's copyrighted photos -- research
reference only, keep them out of any public repo**).

**Step 5 (`Hg5pHVAHohkoCYX1`) shows the port clearly: 14 gold pads in two rows of
seven, in a rounded-rectangle recess, dead centre of the base** under the glued
foot. No connector body -- bare pads, i.e. a pogo landing. This is the same
place the Table_Dock already contacts.

14 pins is a sensible count for USB (VBUS, D+, D-, GND) + UART (TX, RX, GND) +
a few control/strap lines + spares. **If two of those control lines are the
force-DFU straps, a dock can assert them with no soldering and nothing opened.**

**Step 10 (`DG4Alma1eZGcQkXQ`) shows the touch/LED board**: the Cypress PSoC
(bottom centre), five TLC5971 LED drivers in a plus-shape, the load switch and
step-down at the top, and -- the relevant part -- a **fine-pitch board-to-board
connector just left of the LED cluster**, plus two vertical columns of round
gold test pads flanking the centre module. That connector is the touch board's
link to the main logic board and is the second probe target.

### The decisive bench test, and it needs no disassembly to start

The two hypotheses make different predictions, and one measurement separates
them:

* **If the trigger is the capacitive grid** (PSoC asserting a line when the whole
  top surface is covered), then covering the top with a hand or a flat object
  while powering on, **with the pod upright**, should also enter DFU.
* **If the trigger is the base port** (something in the rig contacting those
  pads), then the pod upright with its top covered will boot normally, and only
  contact at the base will do it.

**That test costs one power cycle and no tools.** Worth doing before any
probing, because it decides which of the two targets to meter.

Then, whichever it is: meter each candidate contact during a normal power-on
versus a DFU power-on and find the two that differ. GPIO 4/0 and 4/1 are both
asserted in DFU and both low on a normal boot, so the signature is two lines
changing together.

**Open caveat:** it is not established how the current trick asserts the pins.
"Upside down" with no accelerometer in the device means something else is doing
it, and the one-power-cycle test above is the cheapest way to find out what.

---

## 2026-11-25 — gaster fixed: a liveness gate on every operation

The real failure mode, restated: **a clobbered checkm8 payload still advertises
`PWND:[checkm8]` in the USB serial.** `gaster_checkm8` sees "pwned", skips the
exploit, and every subsequent peek/poke/call then fails or returns nonsense --
silently, with no indication that the results are void. That is how several
hours of results tonight became unreliable.

`multipod/rompeek/gaster.c` now has `payload_alive()`: a tiny probe read of
`insecure_memory_base` run immediately after `gaster_checkm8`, gating **peek,
poke and call**. A live payload answers; a clobbered one cannot, because the
payload code is what services the request. On failure it prints:

    checkm8 payload is not responding -- it was almost certainly clobbered.
    Anything that writes insecure_memory_base (notably `irecovery -f`) destroys it.
    Power-cycle the pod back into boot ROM DFU and re-run; results after this
    point would be meaningless.

Chip-independent -- it probes whatever `insecure_memory_base` is for the
detected cpid, so it works on every target gaster supports.

**Verified both ways on hardware.** Against the pod left over from job 453 (whose
payload the send had destroyed) it refused with the message above instead of
returning garbage -- a real catch on its first run. After a power cycle it passed
and the probe returned `0000009000000091`, the ROM's first two instructions.

Source backups: `gaster.c.pre-poke` (before the write primitive),
`hp-runner.command.pre-podsh` (before the SSH actions).

### The operating rules that fall out of tonight

1. **All `rom-peek` / `rom-poke` / `rom-call` work first; `send` last.** A send
   ends the measurement session.
2. **Every send-based oracle needs a positive control in the same session.**
   Job 451 proved why: a genuine image with a fresh ticket sent to a pwned ROM
   did nothing, because `send` after `pwn` needs `gaster-reset` first. Without a
   control that looks identical to a rejection.
3. **Canonical send order is `pwn` -> `gaster-reset` -> `send`**, which is what
   `boot-nicotine` always did.
4. **Read registers, not the DFU banner.** The serial descriptor is built at
   enumeration and will happily keep saying `CPFM:03` after a demote.
5. **Leave the pod upside down.** A Kasa power cycle then returns it to boot ROM
   DFU in about 5 seconds, so a dead payload costs 20 seconds instead of a
   hand-flip.

---

## 2026-11-25 — The chipid driver: raw vs effective CPFM, and the exact
## unsigned-boot gate

Static work on `SecureROM-t7000si.bin` (pristine copy, sha256
`8fd1d787…32d201`). No pod needed for any of this.

### The complete chipid driver

SecureROM carries Apple's `chipid` driver at `0x10000a000`. Twelve accessors,
and the important thing is that there are **two apertures**:

* `0x2_0E02A000` — the **effective** copy. Writable (we have cleared bit 0).
* `0x2_0E02A200` — the **raw fuse** copy. Never touched by us.

| addr | what it does | aperture |
|---|---|---|
| `0x10000a000` | `get_production_mode` → `[+0x000] & 1` | effective |
| `0x10000a018` | `get_raw_production_mode` → `[+0x200] & 1` | **raw** |
| `0x10000a030` | `clear_production_mode` → `[+0x000] &= ~1` | effective |
| `0x10000a04c` | `get_secure_mode` → `([+0x000]>>1)&1` | effective |
| `0x10000a064` | `get_raw_secure_mode` → `([+0x200]>>1)&1` | **raw** |
| `0x10000a07c` | `get_security_domain` → bits 2–3 | effective |
| `0x10000a094` | `get_minimum_epoch` → bits 4–6 | effective |
| `0x10000a0ac` | CEPO → bits 9–15 | effective |
| `0x10000a0c4` | `get_chip_id` → constant `0x7000` | — |
| `0x10000a0cc` | `get_chip_revision` → `[+0x010]` | — |
| `0x10000a0f0` | `get_ecid` → `[+0x080/+0x084]` | — |
| `0x10000a118` | `set_production_mode_lock` → `[+0x004] |= 0x8000_0000`, `dsb sy`, **panic if it did not stick** | — |

**`0x10000a030` is the only instruction in the whole ROM that writes a CPFM
bit.** There is no `clear_secure_mode`. Not hidden, not behind a flag — the
function does not exist. Grep-proof: the only other store anywhere in the
`0x2_0E02Axxx` block is the lock at `0x10000a138`.

### The unsigned-boot gate, exactly

Four shims sit above the driver:

```
0x1000118e4  eff_production()      -> chipid_get_production_mode()
0x1000118f8  raw_production()      -> chipid_get_raw_production_mode()
0x100011910  require_signature()   -> get_secure_mode() ? 1 : get_production_mode()
0x100011934  require_signature_raw()-> get_raw_secure_mode() ? 1 : get_raw_production_mode()
```

The IMG4 evaluator's failure path at `0x1000078ac`:

```
0x1000078ac  str  xzr, [sp,#0x40]        ; clear demote-request bytes
0x1000078b0  ldrb w8, [x25,#0x10]
0x1000078b4  tbnz w8, #1,  0x100007b0c   ; handle flag bit1 -> hard fail
0x1000078b8  bl   0x100011910            ; require_signature()
0x1000078bc  mov  w9, #0
0x1000078c0  tbnz w0, #0,  0x100007b0c   ; signature required -> hard fail
0x1000078c4  ...                          ; FALL THROUGH = accept unverified
```

So the ROM really does have an accept-anything path, and the condition is
exactly:

> **effective_secure == 0 AND effective_production == 0**, i.e. **CPFM 00**.

Note it reads the **effective** aperture, not the raw one. Fuses are not in the
way of the decision — only of our ability to change the shadow.

### What the EPRO/ESEC comparison actually computes

```
0x10000bccc  expected_EPRO(demote_req) = eff_production()      & ~demote_req
0x10000bcf4  expected_ESEC(demote_req) = require_signature()    & ~demote_req
```

`demote_req` is a per-property byte the **manifest** supplies, and when set the
ROM later honours it for real: `0x10000bca8` sets bit 24 of the boot-policy
flags at `0x1800885b4`, and the applier `0x10000bd7c` tests bit 24 and tail-calls
`0x100008a80` → `chipid_clear_production_mode()`.

**That is Apple's demotion mechanism: a signed ticket property.**

### Correction to the 2026-11-24 entry

We recorded job 452/453 as "CPFM:02 breaks genuine signed boot". That is the
wrong reading. What happened is:

* We cleared effective production → `expected_EPRO` became 0.
* We presented a retail ticket carrying `EPRO=1`.
* `cmp w19, w0` at `0x100007880` mismatched → reject.

Soft demotion did exactly what it is designed to do. The ticket was simply
wrong for the new state. The accurate statement is:

> **CPFM:02 requires an EPRO=0 ticket.** It does not break signed boot.

That does not get us anything by itself — Apple will not sign EPRO=0 for a
retail ECID — but the record should not say demotion is broken, because it
isn't.

### Where this leaves untether

The whole thing reduces to **one bit**: bit 1 of `0x2_0E02A000`.

* Clearable in software: no. No ROM writer, and the measured write is ignored
  (store gadget `0x10000b890` verified live against scratch in the same run).
* Clearable by Apple's own signed demotion: also no. The demote path only ever
  clears bit 0.
* So the accept-unverified path at `0x1000078c4` is, on retail A8 silicon,
  reachable only on parts whose secure-mode fuse was never blown — Apple's own
  internal units. It is live code we can read and cannot reach.

### Cheap experiments still unrun (all low risk, pod in DFU)

1. **Dump `0x2_0E02A000`–`0x2_0E02A2FF`** with an aligned bulk read and map the
   whole register file. We have only ever looked at five offsets.
2. **Try clearing bit 1 at `+0x200`.** Never attempted. We assumed the raw
   aperture was read-only; we never tested it.
3. **Is `+0x000` clear-only or read/write?** Demote 03→02, then try to set bit 0
   back to 1. If it returns, writes land and bit 1 has its own interlock; if it
   does not, the register is one-way-clear and bit 1 needs something else
   entirely. Either answer narrows the problem.
4. **`+0x004`** — is bit 31 the only defined bit, or is there a write-enable?

---

## 2026-11-25 — BMA282, and what the teardown images do and do not show

### Correction to the record

Earlier entries said both teardowns show no accelerometer, and I built a
PSoC/capacitive-grid hypothesis for the upside-down DFU trick on top of that.
**Both are wrong.** There is a **BMA282 on the microphone board**; iFixit snapped
it off during disassembly, which is why it appears in neither teardown's chip
list. The PSoC hypothesis is retracted.

### The mechanism that fits the cold-boot evidence

BMA282 is not publicly documented, but it is a Bosch BMA2x2-family part
(BMA220/222/250/280 share the pinout, the 12-pin LGA and the register map).
Two facts from that family's datasheets decide this:

* **POR wipes configuration.** "The device contains a power-on reset (POR)
  generator. It resets the logic part and the register values after powering-on
  VDD and VDDIO… all application specific settings which are not equal to the
  default settings… must be re-set to its designated values after POR."
* **Dedicated mode needs no host at all.** "The dedicated mode allows the sensor
  to be operated as a standalone device in a simple µC-less system without
  abandon of the interrupt functionality. No digital interface is needed." It is
  selected purely by strapping: **if PS (pin 11) floats at power-on, dedicated
  mode is entered**; a defined digital state on PS selects general (I²C/SPI)
  mode instead.

In dedicated mode with the orientation sub-mode selected, the pins become
orientation outputs directly:

| pin | signal |
|---|---|
| 1 (SDO) | orient1-detect |
| 2 (SDx) | orient0-detect |
| **5 (INT1)** | **orient2-detect** |
| **6 (INT2)** | **flat-detect** |
| 10 (CSB) | sub-mode select |
| 12 (SCx) | GND |

This is the only documented BMA2x2 arrangement that produces live orientation
bits with zero software, and that is what our evidence demands: a **Kasa power
cycle removes mains entirely**, so the accelerometer takes a POR too, and the
pod still lands in boot ROM DFU in ~5 s when inverted. SecureROM reads GPIO 4/0
and 4/1 long before any host code could configure an I²C sensor.

NVM does not rescue the general-mode alternative: BMA2x2 NVM backs up offset and
trim registers, not the interrupt engine.

**Working hypothesis:** GPIO 4/0 and 4/1 are **INT1 (orient2-detect, the Z
up/down bit) and INT2 (flat-detect)**. Those are the two that change together
between upright and inverted, which matches the measured signature exactly —
both read 1 with the pod upside down in DFU, and normal boot requires both 0.

Open: whether Apple's BMA282 variant is strapped to dedicated mode (PS floating)
or whether audioOS also talks to it over I²C. The two are mutually exclusive on
a stock BMA2x2, and a custom part number leaves room for a variant that does
both.

### Confirmation test (next time there is a pod)

Read GPIO 4/0 and 4/1 via `rom-call` in DFU, upright and inverted. Both flip
together → accelerometer-driven, hypothesis holds. Only one flips, or neither →
it is not the orientation outputs and the hypothesis is dead.

### What the eight iFixit images actually contain

Worth writing down so nobody re-derives it. **The mic board is not in them.**
The round annotated board is the **top touch / LED board, `639-03906`**:

* **Cypress CY8C4146** PSoC 4 — capacitive touch controller (this is the PSoC I
  was hypothesising about; it is the touch controller, nothing to do with DFU).
* **5× TI TLC5971** — 12-channel LED drivers for the top display.
* The two small parts iFixit boxed near the top edge are a **TI 62135** buck
  converter and a small regulator. **Neither is an accelerometer.**

Main logic board **`820-00960-04`**:

* **A8 — APL1011 / 339S00421**, PoP, centre-left, inside the shield frame.
  Dense 0201 decoupling fields on its left and right edges, **top side**.
* **PMIC — 338S00100-AZ (1748EHBD)**, right of the A8 inside the same shield.
* Between PMIC and A8: a column of ~6 buck inductors, each with its output caps
  adjacent — one per rail, all top side and exposed.
* Crystal **A741L** below the PMIC.
* **Toshiba THGBX4G7D2LLDYC** NAND, lower-left.
* Shielded can outside the frame, top: the BCM4357 Wi-Fi/BT module.
* Bottom edge: the large board-to-board connector plus a smaller FPC connector.

### Probe / mod plan

**For the DFU straps (useful, low risk, worth doing):**
Find INT1/INT2 on the BMA282 footprint on the mic board — on the author's pod the part
is still fitted, so this needs his own photos of that board, not iFixit's. Trace
them to the mic-board flex and on to the logic board. Breaking those two lines
out to a toggle switch gives a **no-flip DFU button**, which is worth having on
the bench regardless of whether untether ever lands.

**For CPFM demotion — say it plainly: there is no pad to probe.**
Bit 1 lives in the effective CPFM shadow *inside the A8 die*, loaded from the
on-die fuse array during reset. Nothing on `820-00960-04` carries it. There is
no strap, no resistor, no trace to cut, and no amount of board photography will
produce one.

The only board-level route is **fault injection during the fuse→shadow load**,
in the window just after the PMIC releases SoC reset:

* **Injection point:** the A8 fixed/always-on rail — the security block that
  latches CPFM runs off it, not off VDD_CPU. Tap at the output cap of whichever
  inductor in that column feeds it; identify it by scoping which rail comes up
  first on a cold start.
* **Trigger:** the PMIC's reset output to the A8, or GPIO 13/5 (the ROM-driven
  DFU indicator we already measured at `0x00070283`).
* **Tooling:** fast MOSFET crowbar plus a scope with sub-100 ns resolution —
  ChipWhisperer class.

Honest odds: low. The window is sub-microsecond, and nobody has publicly glitched
CPFM on an Apple SoC. The fallback is die-level work (decap + FIB), which is
destructive and lab-grade. Worth knowing the target is *one bit* and we know
exactly which one — but worth not pretending the board gives us a way in.

---

## 2026-11-25 (later) — The RSA modulus overflow: real, exploitable, and
## unreachable. Plus a full offline model of the ROM's trust decision.

Pure static + emulation work, no pod. Harness saved to `multipod/romemu/`.

### The bug

`FUN_100012ff4(key_der, hash, sig)` — "verify this hash with this RSA public
key" — imports the modulus into a stack bignum before calling PKCS#1 verify:

```
0x1000130a8  add  x8, x2, #7
0x1000130ac  lsr  x23, x8, #3      ; x23 = ceil(modulus_bytes / 8) = limbs
0x1000130b0  ldr  x8, [sp]         ; capacity, initialised to 0x100 at 0x10001302c
0x1000130b4  cmp  x23, x8
0x1000130b8  b.hi 0x100013128      ; only guard: fail if limbs > 256
```

`bignum_import` (`0x100014528`) then writes exactly `capacity * 8` bytes at
`sp+0x10`. The frame is 0x360 bytes:

| what | at | limb index |
|---|---|---|
| bignum data start | `sp+0x10` | 0 |
| stack cookie | `sp+0x358` (`x29-0x58`) | 105 |
| saved x19..x28 | `sp+0x360` | 108 |
| **saved LR** | `sp+0x3B8` (`x29+8`) | **117** |

So the guard permits 256 limbs and the frame holds 117. **An attacker-chosen
modulus of 118+ limbs overwrites the saved return address with its own bytes.**

The earlier note said "frame holds 32" — that was wrong, the real figure is 117.
Conclusion unchanged, arithmetic corrected.

### The cookie does not help

`0x180080198` holds `0x47415244` = `"DRAG"`, a build-time constant, not random.
The overflow data *is* the modulus, so the attacker simply places `DRAG` at limb
105 and the check at `0x100013134` passes untouched.

### Proven under emulation

`multipod/romemu/rsa_overflow_poc.py`, Unicorn 2.1.4, pristine ROM:

```
stack cookie @0x180080198 = 0x47415244  (b'DRAG\x00\x00\x00\x00')
   ('guard', 119, 256)
   ('rsa_verify_failed_path',)
   ('cookie_check_PASSED',)
   ('*** LANDED ON TARGET ***')
RESULT: PC CONTROL AT EL3
```

Note the RSA verify *failing* is irrelevant — both the success and failure exits
share the epilogue, so the corrupted LR is taken either way. The signature never
has to be valid.

### Why it is nevertheless unreachable

`multipod/romemu/chain_emulator.py` runs the **real** chain verifier
`FUN_10001292c` against your genuine apticket, nothing stubbed but the hash
engine (its descriptor lives in BSS that ROM init sets up; the harness computes
the real SHA-1 instead). Output:

```
sha1(ticket+0xa03, 740 bytes)
ENTER verify_with_key  key_der@0x100017f4f len=270     <- ROM's built-in root
   guard: limbs=32  max=256
   -> RSA verify   <- verify OK
sha1(ticket+0xdff, 959 bytes)
ENTER verify_with_key  key_der@ticket+0xb3a len=270    <- cert[0]'s key
   -> RSA verify   <- verify OK
ENTER verify_with_key  key_der@ticket+0xf39 len=270    <- cert[1]'s (leaf) key
   -> RSA verify   <- verify OK
```

The order is correct:

1. cert[0] is verified with the **ROM-resident root key at `0x100017f4f`** — not
   attacker data.
2. Only then is cert[0]'s modulus imported, to verify cert[1].
3. Only then is cert[1]'s modulus imported, to verify the manifest.

Every modulus that reaches the vulnerable import has already been authenticated
by a signature chaining to the ROM. To exploit it Apple would have to sign a
certificate carrying an oversized modulus. `FUN_100012ff4` has no other callers
(`0x100012dd8` and `0x100012f6c`, both inside `FUN_10001292c`, whose only caller
is the chain verifier).

**Verdict: real memory-safety bug, full EL3 code execution in isolation,
structurally unreachable without an Apple signature.** That is a better answer
than the old "our tickets happen to be 2048-bit" — we now know *why*, and we
know not to spend more time on it.

### Worth keeping: the emulator

The side effect of all this is the first full-fidelity offline model of
SecureROM's trust decision. Manifest and chain mutations can now be tested
against the real code with no pod at all. That is the tool to reach for before
any future NVRAM or boot-partition experiment.

---

## 2026-11-25 (later) — Two more gates named

### Handle flag bit 1 — the gate *before* `require_signature()`

`0x1000078b4` hard-fails on bit 1 of `[handle+0x10]` before the CPFM check is
ever reached. That word is built just before `img4_eval`:

```
0x1000007a4  ldr  w8, [x24, #0x10]
0x1000007a8  lsl  w9, w20, #1
0x1000007ac  and  w9, w9, #2
0x1000007b0  eor  w9, w9, w27        ; w27 = 0xb  (set at 0x100000654)
0x1000007b4  orr  w8, w8, w9
0x1000007b8  str  w8, [x24, #0x10]
0x1000007c8  bl   0x10000f52c        ; img4_eval
```

So the flags word becomes **`9`** when `w20 & 1 == 1` (bit 1 **clear**,
accept-unverified reachable) or **`0xb`** when `w20 & 1 == 0` (bit 1 **set**,
foreclosed). Same for all four boot arms — they converge before this point.

`w20` comes from the boot-source enumerator `0x10000870c`:

```
w10 = ([0x2_0E029000] >> 8) & 0xff      ; boot source, 0..7
jump table at 0x1000087cc
  source 0 -> arm 1, w20 = 0        source 4 -> arm 3, w20 = 0
  source 1 -> arm 1, w20 = 1        source 5 -> arm 3, w20 = 1
  source 2 -> arm 2, w20 = 0        source 6 -> invalid
  source 3 -> arm 2, w20 = 1        source 7 -> arm 1, w20 = 1
```

**Odd boot sources give `w20 = 1`; even ones give `w20 = 0`.**

This is a second, independent condition on unsigned boot that we did not know
about. CPFM 00 alone is not sufficient — the boot source must also be odd.
`[0x2_0E029000]` is a plain register read, so this is settleable in one cheap
measurement. It is now item 0.1 in `TODO-POD.md`.

### DPRO / DSEC — Apple's demotion request, named

The two bytes feeding `expected_EPRO`/`expected_ESEC` come from manifest
properties decoded in the callback at `0x100007c20`:

* **`DPRO`** (`0x100007d40`) -> `[x20+0]` -> `sp+0x40`
* **`DSEC`** -> `[x20+1]` -> `sp+0x41`

with `EPRO` at `+4/+5`, `ESEC` at `+6/+7`, `EKEY` at `+2`, and `SDOM`, `BORD`,
`CSEC`, `CPRO`, `CHIP`, `CEPO`, `BNCH` handled in the same dispatch.

Note which aperture each is compared against: **`CPRO`/`CSEC` compare to the raw
fuse values** (`sp+0xa0`/`sp+0xa1`, from `0x2_0E02A200`), **`EPRO`/`ESEC` to the
effective ones** (`0x2_0E02A000`). That is the whole raw-vs-effective design in
one place.

So Apple's demotion is: a ticket carrying `DPRO`, which makes `expected_EPRO`
zero and sets boot-policy bit 24, which the applier turns into a real
`chipid_clear_production_mode()`. `DSEC` does the same bookkeeping for `ESEC` —
**but there is no `chipid_clear_secure_mode()` for it to drive.** Even Apple's
own signed demotion cannot clear effective secure mode through this ROM. `DSEC`
only changes what the manifest is expected to say; it does not change the chip.

### Correction, same day: the boot source was already measured

I wrote above that `[0x2_0E029000]` bits 8-15 still needed measuring. Wrong: job
432 read `0x01380203`, selector 2, and the 2026-11-24 strap section already says
"odd selectors set flag2 = 1". What is new today is only the consequence:
`flag2` is the `w20` that builds handle-flag bit 1, and bit 1 is tested at
`0x1000078b4` ahead of `require_signature()`.

So on this board as strapped (selector 2, flags `0xb`):

> the ROM's accept-unverified path is closed on flash boot **even at CPFM 00**.

Reaching it needs both CPFM 00 and selector 3 (GPIO 6/6, flat 0x36, high during
the 100 us sample; NAND `read_llb` stays the boot device). Two physical
conditions, not one. The fuse-latch glitch idea is correspondingly weaker.

The uninitialised-stack BNCN item stays where the earlier entry left it: an
anti-replay bypass on a path where the nonce is already vacuous. Not worth
emulation time; the one-cold-boot test in TODO 2.1 remains the way to settle it.

---

## 2026-11-25 (afternoon) — Fault simulation: one branch decides everything

Emulation only (`multipod/romemu/glitch_skip_sim.py`). Fault model: a single
instruction is skipped once. This is a model, not a measurement of real glitch
behaviour.

Input: a self-made IMG4 (`illb`, flash flags `0xf`, our own manifest, empty cert
chain, garbage signature). Unfaulted, the evaluator `FUN_100007574` rejects it
after 4257 instructions (1097 distinct addresses). Each of those 1097 addresses
was then skipped at its first and last occurrence and the run repeated.

Six addresses made the evaluator return 0. Five are prologue `mov x29, sp` or a
`mov w0,#-1` whose skip returns 0 with a wrong or empty output descriptor, so
they are not usable as they stand. One gives output identical to a genuinely
accepted image (payload pointer and length correct):

    0x10000781c  cbnz w0, 0x1000078ac     ; result of the chain/signature verify

Skipping it also bypasses DGST, EPRO, ESEC and every other manifest property,
because those are evaluated inside `0x100012724` and nothing re-checks them
afterwards: a manifest with a deliberately wrong DGST was accepted the same way.
CPFM and the boot-source strap are irrelevant on this route, since the code never
reaches the failure path where they are tested.

What this is and is not:

* It is a precise glitch target: one conditional branch, reached about 4000
  instructions into evaluation of an image that fails fast.
* It can be developed in DFU without checkm8: send an unsigned image, glitch,
  see whether the ROM runs it. USB transfer completion is a usable trigger.
* It is not a software untether. From cold boot the glitch has to land on every
  boot, which means a fitted glitcher (modchip), i.e. hardware.
* Real voltage glitches do not always behave as clean skips; success rate and
  timing are unknown until tried on silicon.

---

## 2026-11-25 (afternoon) — Review of this whole log: three of today's entries are wrong

Re-read the full file end to end. Corrections first, all to entries I wrote today.

### 1. The BMA282 "dedicated mode drives GPIO 4/0 and 4/1" hypothesis is WRONG

It contradicts what this log already established on hardware on Nov 23
("How upside down becomes DFU"):

* The boot ROM does not look at orientation at all.
* Stage 2 (iBoot/iBEC) reads the accelerometer **over I2C** (I2C2, addr 0x18,
  chip id 0xFB, reg 0x16 = 0xC0, ten reads of reg 0x0C), so the part is in
  general mode, not dedicated mode. Linux's bma280 driver binds to it too.
* Stage 2 then sends `21 01 00 00 5A 84` to the top-panel MCU ("Peppy", I2C3,
  0x55), and **the MCU resets the SoC with force-DFU asserted.**

So GPIO 4/0 and 4/1 reading high in DFU are almost certainly the MCU's force-DFU
lines, not accelerometer interrupt pins. "Upside down + Kasa cycle -> DFU in 5 s"
is LLB -> iBoot -> accelerometer check -> MCU reset, not the ROM sampling
orientation; it is not independent confirmation of anything about the ROM.
The Cypress PSoC on the touch board is very likely that MCU, so retracting the
PSoC's involvement this morning was also wrong (its role is MCU-asserted
force-DFU, not capacitive sensing).

Consequences: TODO items 0.4, B.1 and B.2 are withdrawn. A no-flip DFU already
exists in software (`homepod-realdfu`, "Restart into DFU") and as the six-byte
I2C jig described on Nov 24.

### 2. "A second lock we did not know about" was already in this log

The Nov 24 ROM audit already recorded: flag bit 1 = 1 - flag2, flag2 = selector
bit 0 = GPIO 6/6, selector 2 -> bit 1 set -> hard fail, selector 3 arms the soft
path. Today's work re-derived it. Nothing new except the jump-table listing.

### 3. RSA overflow arithmetic: the earlier audit was right, my "correction" was not

The context is three n-limb arrays (extent 0x18 + 24n), so the saved LR is
reached at n >= 39 limbs (about 2500 bits), as the Nov 25 audit said. My
"frame holds 117" counted only the first array. My PoC at 119 limbs is valid but
far above the real threshold. Reachability verdict unchanged.

---

## 2026-11-25 (afternoon) — ProtoPod raw dump (`~/ProtoPod`), checked for untether value

Contents: raw NAND images of the prototype (rdisk0 16 GB user area with an APFS
container, rdisk2 firmware area, rdisk3 LLB area) and `dev_ibss`/`dev_ibec`
(byte-for-byte the LLB and firmware areas; iBoot-4076.30.43, encrypted payloads).

* All three IM4Ms (LLB, ibot, dtre) are the same 5155-byte ticket: CHIP 7000,
  BORD 38, CEPO 1, SDOM 1, CPRO/CSEC true, ECID present, BNCH, plus one
  property not seen elsewhere, `faus` = TRUE. Every object has EPRO/ESEC true.
  No DPRO, no DSEC, no AMNM.
* Certificate chain: **same intermediate** as retail tickets (byte-identical);
  **different leaf** (OU=ETS, 2048-bit), but its constraint extension is the
  same size and names the same tag set as the retail leaf (BNCH BORD CEPO CHIP
  CPRO CSEC DGST ECID EPRO ESEC SDOM snon). So the internal signer is not
  looser than the retail one.

Verdict: nothing in it boots untethered on another pod. The ticket is bound to
that unit's ECID by the same rules, and the unit itself is production-fused.
Value is tethered tooling and knowledge only: the 4076.30.43 loaders (build type
unknown until decrypted on a pod), diag/console/hammer/rbm payloads, and the
internal 11.2.1 root filesystem. `faus` is worth one lookup in the decrypted
loaders to see what it switches.

---

## 2026-11-25 (afternoon) — Route 2 scoped: a userland untether on audioOS 13.4.8

Premise: 13.4.8 (17M61) is still signed and its boot chain runs from flash
without a nonce, so it can be installed for good. If something we control on its
filesystem leads to code execution at boot, that is an untether that needs no
boot loader bug.

### Staged
The 17M61 OTA (1,634,140,137 bytes, Apple CDN) is at
`~/homepod/oldfw/17M61/ota/ota-17M61.zip`, root filesystem unpacked to
`ota/root/` (2.9 GB, 16,891 entries, listing in `ota/list.txt`). Apple's files:
private, never in the repo. The 2020 `payloadv2` format is pbzx-wrapped records
with a 30-byte big-endian header (size at +6, name length at +22, uid, gid,
mode), not AppleArchive.

### What the filesystem shows (observed)
* No sealed-volume artefacts: no root hash, no mtree, and the 17M61 manifest has
  no `isys`/`msys` objects (18.3 added those). Consistent with an unsealed
  system volume. NOT yet confirmed on a pod: how the kernel picks the root
  snapshot, and that an edited volume boots.
* launchd is configured by 185 individual plists in
  `/System/Library/LaunchDaemons` (no consolidated cache file). These are plain
  data files, so a daemon entry running any shipped binary as root with chosen
  arguments looks addable. Not yet tested.
* No shell and no interpreter anywhere on the image (no sh, bash, python, perl,
  jsc). `/bin` holds `df` and `ps` only. So "run a script" is not available;
  code execution has to come from a memory-safety bug in a signed binary.
* Shipped binaries that parse a file named on their command line or at a fixed
  path: `racoon` (IPsec-tools, with `/etc/racoon/racoon.conf`, 635 KB),
  `pppd` (ppp-862.140.2), `hdik`, `mount`, `mount_hfs`, `mount_nfs`, `nvram`.
  racoon carries a sandbox-profile entitlement.

### Public facts that bear on it (from Apple advisories and jailbreak notes)
* racoon's known config-file bug, CVE-2020-3840, was fixed in iOS 13.3.1, so it
  should be patched here. A new racoon bug, or one fixed after July 2020, is
  needed.
* Public kernel exploits covered iOS 13.5.1-13.7 on A8 devices (oob_events,
  later cicuta_virosa for 13.0-13.7). 17M61 is from that period. Whether this
  exact kernel has those bugs is being checked from the binary.

### The chain it would take
1. Boot-time entry: a launchd plist that starts a signed binary on a crafted
   file. (Pod test.)
2. Userland code execution in that binary, as a ROP/data-only payload since no
   unsigned code can be mapped. (Needs a bug: the uncertain link.)
3. Kernel compromise from inside that process and its sandbox. (Known-era bugs,
   but must be done without native code.)
4. Hand-off from XNU to the Nicotine loader. (New engineering; nobody has done
   this on a HomePod.)

### Limits to state up front
* audioOS has to boot far enough to run launchd. A dead-SEP board may never get
  there, and dead-SEP boards are where Nicotine is most wanted. Unknown until
  tried.
* The pod must be on 13.4.8. Fine while Apple signs it; after that only pods
  with a banked ticket.
* Weeks of work even if every link holds, and link 2 may not exist.

### Running now
* racoon: source-level fuzz of the config parser plus a check of the device
  binary, and its entitlements.
* 17M61 kernel: which public, since-fixed bugs are still present.

---

## 2026-11-25 (afternoon) — LLB/iBoot-15387 audit: no write primitive on the cold-boot paths examined

Agent audit, static plus function-level emulation; I spot-checked three of its
quoted instruction sequences and the NVRAM allow-list against the payload and
they match. Bases read from the images: LLB `0x180380000`, iBoot `0x870000000`
(link literal at file 0x380 in both). Not checked against a manifest digest.

Found, none of it a write:
* LLB `0x1803883a4`: UtilDM `u16[page+0x9a]` unchecked, reads up to ~61 KiB past
  the 4 KiB page (emulated). Result is only a page index.
* IMG4 decode traps (`brk`) on an empty top-level SEQUENCE: iBoot `0x8700432d8`,
  LLB `0x1803a2168`. A panic at most; no path from disk shown.
* iBoot `0x870004284`: the recovery-ticket parser returns success on a truncated
  IM4M, skipping trust evaluation. Both callers then need `anrd` from the zeroed
  context and fail (line 253). Neutralised, by reading; not emulated end to end.
* iBoot `memmove` with n=0 and unaligned pointers runs away only while the MMU
  flag `0x8700ced60` is clear. Latent.

Useful facts:
* **iBoot-15387 hides most NVRAM variables.** Allow-list of 33 names at
  `0x870055788`. `recovery-boot-args`, `boot-args`, `boot-device`, `boot-path`,
  `boot-partition`, `bootdelay` are NOT on it, so the getters return nothing for
  them. That closes "inject recovery-boot-args on a stock 27.0 pod". On the list
  and not yet traced: `debug-uarts`, `security-mode-change-enable`,
  `dev-unset-debug-enabled`, `recovery-boot-mode` (compared with "panicmedic"),
  `is-tethered`, `upgrade-fallback-boot-command`.
* `boot-command` is matched against {fsboot, upgrade, recover, recover-once,
  checkerboard, repair}; not interpreted.

Audited clean (fuzzed under emulation with bounds tracking): NVRAM store parser
(4000 inputs), breadcrumb merge, IMG4/DER layer (30,000 inputs), APFS B-tree
node checks and lookup (44,000 runs). Read only: GPT/MBR, SysCfg, APFS superblock.

NOT examined, so not cleared: the X.509/RSA code in 15387, the recovery prompt
and what `debug-uarts` enables, storage drivers, the `upgrade`/`checkerboard`/
`repair` flows, consumers of 13 allow-listed variables, anything end to end.
Scripts are in the analysis container at `/home/claude/fw15387/`.

---

## 2026-11-25 (afternoon) — Route 2, kernel link: the 13.4.8 kernel still has the public 2020-21 bugs

Agent patch-status check of `kernelcache.release.b238` from the 17M61 OTA,
static only; I confirmed the version string and the unlocked increment myself.

* `xnu-6153.143.1~3/RELEASE_ARM64_T7000`, built 26 June 2020 (Darwin 19.6.0).
* **CVE-2021-1782** (the cicuta_virosa bug): fix absent. `user_data_get_value`
  increments the count at `0xfffffff007665a28`-`a30` with no lock. Verified.
* **CVE-2020-27950** and **CVE-2020-27932**: fixes absent. Verified by
  instruction against source.
* oob_events bugs: one inferred unfixed, one not located.
* Control, **CVE-2020-9859**: fixed, as a July 2020 build should be.
* Protections: KPP only (a 0xc000 KPP image follows the kernel; `smc #0x11`
  lockdown call). No PAC, no PPL segments, no KTRR. `zone_require` present.
* The relevant Mach traps, voucher manager and graphics kexts are compiled in.
  Whether they are reachable from racoon's sandbox on this board is unknown.

So link 3 of route 2 has known material. Link 2 (a userland bug in a
boot-launchable signed binary) is still the open one.

---

## 2026-11-25 — Route 2, userland link: a config-reachable defect in the device's racoon

Agent audit (source fuzz + device binary); full report and reproducers in
`multipod/route2/`. I confirmed the two instruction sites below in the 17M61
binary myself; the rest is the agent's work as labelled in its report.

* The binary is Apple ipsec-326.120.2. CVE-2020-3840 is fixed in it.
* **New defect:** `sainfo anonymous from address {` with no value after the
  type. `set_identifier()` returns 0 without writing its output, and the parser
  then dereferences, copies from and frees an uninitialised stack pointer:

      0x100050d78  add x0, sp, #0xa0
      0x100050d7c  bl  0x10000f834          ; set_identifier
      0x100050d80  cbnz w0, fail
      0x100050d84  ldr x8, [sp, #0xa0]      ; never written on this path
      0x100050d88  ldr x8, [x8]

* **The same stack slot is the `include` statement's path buffer**
  (`0x1000513b8 add x0,sp,#0xa0 ; mov w1,#0x400`), and an include that matches
  no file only warns. So earlier `include "...";` lines choose the pointer's
  bytes. The agent ran the device's own arm64 parser under emulation and got a
  chosen pointer value, followed by `free()` on what it points to.
* Not known: what iOS's allocator does with it, how to get past ASLR without a
  leak, and what racoon's sandbox profile allows. Nothing was run on a device
  and no exploit was attempted.
* Lesser defects: an include-depth off-by-one (lands in padding, harmless here),
  double frees that need a signal we cannot send, several over-reads.
* Fuzzing: 11.6 M executions, 149 of 168 grammar actions covered; the fuzzer's
  own crashes were all a Linux artefact, and the real bugs were found by reading.
* racoon needs euid 0 and a working PF_KEY socket before it parses anything.

Status of route 2: link 3 (kernel) has known unpatched bugs; link 2 now has a
real candidate rather than nothing. Whether it can be turned into control
without an address leak is the next question. Links 1 and 4 are untested.

---

## 2026-11-25 — ROM pre-signature fuzzing: no memory-safety fault

Agent run, report at `multipod/romemu/ROMFUZZ-REPORT.md`. Real chain verifier,
key import and PKCS#1 code; only the hash engine replaced.

* 2,435,608 attacker-reachable executions (evaluator, chain verifier, outer
  parser; plus 384,293 with the genuine ticket untouched and only IM4R/IM4P/
  container mutated): **0 faults**.
* Coverage: DER library, outer parser and chain walker 94 %; the evaluator
  itself only 357 of 691 instructions; 41 of 134 in-scope functions never hit.
  Nothing past a DGST match was reached, because no run could match the digest.
* One logic defect (I confirmed the discarded return at `0x1000077b8`): with a
  zero-length IM4P payload, `0x100011f04` returns without writing and the
  evaluator takes the image type from stale stack at `sp+0xe4`. Every run still
  rejected, since an empty payload cannot match a signed digest. No consequence
  shown.
* With signatures forced valid (not attacker-reachable) the only crashes were
  the known RSA modulus overflow.
* Side result: on flash flags with the genuine ticket, BNCH passes when the IM4R
  is absent, an empty SET, or has a zero-length BNCN, with no dependence on
  stack contents in emulation. That points to the empty-IM4R cold-boot test
  (TODO 2.1) passing for a structural reason rather than by luck.

---

## 2026-11-25 — Why makeipsw.sh cannot build 13.4.8, and a draft that addresses it

the author downloaded the Apple TV HD 13.4.8 IPSW (`AppleTV5,3_13.4.8_17M61_Restore.ipsw`,
same build number, same A8) as the donor. Compared it and the pod OTA against
`makeipsw.sh` line by line. Five concrete blockers: old pbzx payload format,
non-empty `data_payload` (the `/private/var` skeleton), four manifest keys that
did not exist in 2020, encrypted loaders with no 17M61 entry in the shared keys
file, and two donor Info keys. Draft and notes in `multipod/makeipsw13/`
(`makeipsw13.sh`, `ota_payload_extract.py`, `firmware_keys_17M61.zip`,
`README.md`). The extractor is tested; the script is NOT, because no macOS tool
runs on the cloud side. Open risks are listed in the README.

A working 13.4.8 install is the prerequisite for route 2's first pod test.

---

## 2026-11-25 — The racoon defect, characterised: a controlled free, not yet more

Agent work under emulation of the device binary with modelled heap and libSystem;
I checked the copy/free instructions at `0x100050dc8`-`dd8` and `vfree` at
`0x10003e3d4` in the binary. Test configs in `multipod/route2/racoon-d1.tgz`.

What the code does with the chosen address A: reads 16 bytes there (a length L
and a pointer V), allocates L+4, copies L bytes from V into the sainfo's
identifier, then `free(V)` (if non-zero) and `free(A)`.

* **Steering:** includes of decreasing length compose a 64-bit value; every byte
  except 0x00 (terminator only) and 0x22 is available; the lowest byte run
  always contains `/` unless a port statement writes it. A remote block can
  leave a live heap pointer in the slot, and a following port statement can
  overwrite its low 16 bits, giving an address in that object's own heap
  neighbourhood with no address guess.
* **The read is not usable:** the copied bytes only affect a compare, an exit
  status and a log string that is probably redacted. The config is static, so a
  read cannot feed a later pointer.
* **The free is the primitive.** Pointing A at the sainfo being built frees it
  while the parser keeps writing into it and links it into the global list; the
  parse then returns success (emulated). That is a use-after-free with
  config-chosen 8-byte writes at +0x18.
* **Not shown:** that the heap layout repeats from boot to boot, that iOS's
  allocator accepts the free and reuses the block for something we control, or
  that any later write lands on a pointer that is then used. No object to aim
  at was identified. The binary has no PAC and has writable lazy-symbol
  pointers at a fixed offset from its slide, which re-randomises per launch.
* Restart-on-crash gives repeated tries of one fixed guess, with no feedback.

Verdict: real and steerable, currently a controlled free with an unproven path
beyond it. The next facts can only come from a pod (TODO R2.3).

---

## 2026-11-25 15:36 — Pod back: the chipid experiments, run and closed (jobs 500, 501)

Bench pod in pwned ROM DFU, payload alive at both ends of each job.

    raw getters   0x10000a018 -> 1, 0x10000a064 -> 1
    [+0x000] = 0x00010297   [+0x200] = 0x00010297   (raw mirrors effective)
    store 0x10295 to +0x200  -> reads 0x00010297     raw aperture IGNORES writes
    store 0x10296 to +0x200  -> reads 0x00010297
    demote (0x10000a030)     -> [+0x000] = 0x00010296, [+0x200] still 0x00010297
    store 0x10297 to +0x000  -> reads 0x00010296     bit 0 CANNOT be set back

So: the raw aperture is read-only, and the effective register is one-way-clear
for bit 0 with bit 1 not clearable at all. TODO 1.1 and 1.2 answered; the
software CPFM question is finished.

Block map from a 0x300 bulk read (`runner/files/t501-chipid.bin`): +0x000 CPFM
word, +0x004 `0x20000000`, +0x008 `0x170`, +0x010 `0x00090011`, +0x014
`<FUSE_WORD_1>`, +0x01c `<FUSE_WORD_2>`, +0x020 `<FUSE_WORD_3>`, +0x080 ECID, +0x104
`0x01000000`, +0x200.. a copy of +0x000..+0x023 (with the undemoted CPFM).
Everything else zero.

Note: the pod was left at CPFM 02 after job 501. It needs a power cycle before
any signed image is sent (EPRO would mismatch).

### 2026-11-25 15:47 — Demotion changes what the GID key produces

Measured by accident, then with a control. `gaster decrypt_kbag` on the same
iBSS/iBEC key bags gave different, wrong IV/key pairs while the pod was at
CPFM 02 (after `0x10000a030`), and correct ones after a power cycle at CPFM 03
(LLB control matched its Nov 23 value; iBSS and iBEC results decrypt to valid
iBoot-5540 images). So clearing the production bit alters or disables the GID
key in the AES engine, with no error reported. **Never decrypt on a demoted
pod.** 17M61 iBSS/iBEC keys are in `makeipsw13/firmware_keys_17M61.zip`; note
iBSS/iBEC use different key bags from LLB/iBoot even though the plaintext is
identical.

### 2026-11-25 16:05 — 13.4.8 restore: first attempt reached asr, and my "asr has no check" was wrong

`makeipsw13.sh` built an IPSW after four fixes found by running it (argument
quoting; iBSS/iBEC keys; dropped `--ipatch-no-force-dfu` and
`--kpatch-always-get-task-allow`, whose finders fail on this build; no trust
cache swap, since the app checks digests). The restore booted the patched
loaders and kernel, ran the Apple TV 13.4.8 ramdisk on the pod, created the APFS
volumes and streamed the image to 98 %, then:

    ASR: Image failed signature verification
    ASR: Could not restore - Authentication error

Cause: restored runs `asr ... --expectedhash <Apple's OS image SHA-1>` and asr
memcmps the computed image hash against it. I had said the 13.4.8 asr has no
such check; that was a truncated `strings | head` on my side. The string is
there without a trailing full stop, which is also why binrider's search failed.
The check: `0x100024698 bl memcmp ; 0x10002469c cbnz w0, fail`. The script now
NOPs `0x10002469c` (file offset 0x2469c, bytes `20110035`) after confirming the
bytes, then re-signs. The APFS image made by current macOS was accepted by the
2020 asr up to that point.

### 2026-11-25 16:17 — audioOS 13.4.8 restored on the bench pod and working

With the asr hash-compare patch the restore completed. the author set the pod up in the
Home app and reset it from there; it reset itself and came back. So the image
built on current macOS (APFS and all) is accepted by the 2020 system, the
patched restore kernel survived the whole restore, and the installed OS is
Apple's signed 13.4.8 chain with Apple's files. `multipod/makeipsw13/` is the
working recipe (script, extractor, keys). Route 2's prerequisite is met.

## 2026-11-25, route 2: launchd gate closed, SQLite surface opened

### Gate A (boot-time launch of our own plist) is CLOSED
- Job 515: after ~3 min of 13.4.8 uptime, NVRAM has no `r2-gate`; snapshot still `orig-fs`, plist and marker intact.
- launchd 1738.140.1 (17M61), static: byte `0x10004e8a1` = "kern.bootargs contains `rd=md0`", set at `0x100031f04`-`0x100031f1c`.
  `0x10000fc88` returns (byte==0) -> the "system services must be in cache" branch at `0x100021000`. On a normal boot the
  byte is 0, so system LaunchDaemons come ONLY from the signed MRM cache; the disk is searched only in a restore ramdisk.
- `/System/Library/Caches/com.apple.xpc.launchd/mrm.plist`: 183 daemon jobs, 40 start at boot. Validated by
  `/usr/libexec/launchd_cache_loader` (detached sig `mrm.plist.sig`, cdhash checked through AMFI). Job definitions come
  from the cache, so editing Apple's on-disk plists has no effect either. A missing cache is fatal ("No service cache"
  -> `0x10000fc54`): do NOT remove mrm.plist from a pod you want to boot.

### Confirmed good: the live System volume boots
- Job 514: 13.4.8 booted with the root snapshot renamed to `orig-fs` plus two added files, and came back on USB in <45 s.
  So non-executable files we place on the System volume are live at runtime. Executables are not (trust cache/AMFI).
- Exit from DFU to a normal boot with no hands on the pod: pwn, gaster-reset, send sshramdisk iBSS + iBEC, `cmd reboot`
  from recovery. The SSH ramdisk's own `reboot` does NOT reset the SoC (that was the 16:26 "hang": the ramdisk kernel
  stayed up with USB down; nothing was wrong with the edits).

### Data volume is NOT reachable from the SSH ramdisk
- `mount_apfs -o rdonly /dev/disk1s2 /mnt2` hangs the ssh session hard (twice: recon13.sh and job 516; the runner's
  300 s alarm did not kill it, the runner had to be restarted). Almost certainly the APFS encryption on /private/var.
- Consequence: no crash reports, no `/var/db/diagnostics`, no ASL from the ramdisk. Volume layout is disk1s1 (System),
  disk1s2, disk1s3. Do not retry this; it costs a runner restart each time.

### audioOS 13.4.8 ships SQLite 3.28.0 with fts3_tokenizer ENABLED (verified in Apple's binary)
- `/usr/lib/libsqlite3.dylib` in the 17M61 dyld shared cache: image at `0x180ba7000`, __TEXT `0x180ba7000 +0x184000`.
  Its own __TEXT carries "3.28.0" and the compile-option list incl. ENABLE_FTS3, FTS3_PARENTHESIS, **FTS3_TOKENIZER**,
  FTS4, FTS5, JSON1, RTREE, DBSTAT_VTAB, SESSION, PREUPDATE_HOOK, API_ARMOR, OMIT_LOAD_EXTENSION. No DEFAULT_DEFENSIVE.
- Not inference: the single site that materialises the default `db->flags` is `0x180ba95d0`
  (`movz w10,#0x8070; movk w10,#0x444,lsl#16` -> `0x4448070`) = LegacyAlter|**Fts3Tokenizer(0x400000)**|EnableTrigger|
  AutoIndex|ShortColNames|CacheSpill|CkptFullFSync. So EVERY connection in 13.4.8 starts with fts3_tokenizer(2) on.
- In 3.28.0 both forms are gated by `fts3TokenizerEnabled() || sqlite3_value_frombind(argv[N])`
  (ext/fts3/fts3_tokenizer.c:82,109), so with the flag on, SQL that comes from the database file itself may use them.
  Primitives: 1-arg = read a live tokenizer-module pointer (ASLR leak, usable inside the query); 2-arg = store an
  arbitrary 8-byte pointer; an fts3 table with `tokenize=<name>` then calls through it (CVE-2015-7036 shape).
- Reproduced locally in a matching build (SQLite 3.28.0 + Apple's options, `/home/claude/sq/sqlite328` in the container):
  1-arg returned a pointer from a plain literal, 2-arg accepted `x'4142434445464748'` and echoed it back.

### Query hijack works against bluetoothd's own statement (local reproduction)
- `/Library/Application Support/BTServer/pincode_defaults.db` is on the **System volume** (root/admin 0644, 73728 bytes,
  sha256 95c0d2e1...863) and so is plantable from the ramdisk or at IPSW build time. Schema has
  `CREATE TABLE makes (id INTEGER UNIQUE NOT NULL, name TEXT, common_abbreviation TEXT, PRIMARY KEY (id))` and already
  contains four VIEWs, so a view in this file is unremarkable.
- bluetoothd (`/usr/sbin/bluetoothd`, 17M61, sha256 d2e9100d...e07; cached job `com.apple.bluetoothd`, RunAtLoad,
  UserName **mobile**): DB path string `0x10040275a` stored by the ctor at `0x1001a8414`; the statement
  `SELECT makes.name, makes.common_abbreviation FROM makes WHERE makes.name IS NOT NULL` (`0x10040235b`) is prepared by
  the helper at `0x1001a8810` with **sqlite3_prepare** (legacy), which logs `sqlite3_errmsg` through os_log on failure.
- Two further statements exist, both parameter-bound and both joining `makes`: one over
  `devices, manufacturers, matching_rules_oui, oui_assignments, makes` (?1 oui, ?2 name) and one over
  `devices, matching_rules_did, makes` (?1..?4 vid_src/vid/pid/version). Those run on device discovery/pairing.
- Local proof: with `pragma writable_schema=ON`, deleting the orphan `sqlite_autoindex_makes_1` row and rewriting the
  `makes` row to `type='view', rootpage=0, sql='CREATE VIEW makes(name, common_abbreviation) AS SELECT ...'`, a fresh
  connection running bluetoothd's exact query executed OUR SQL and returned a leaked pointer.

### Ordering constraint (important)
- A virtual table is instantiated at **prepare** time, so `tokenize=x` fails ("unknown tokenizer: x") before a subquery
  in the same statement can set `x`. PC control therefore needs TWO statements on one connection: statement A (the
  `makes` query) stores the pointer, statement B (prepared later) connects an fts3 table with that tokenizer name and
  calls through it. bluetoothd's helper prepares afresh on each call, and there are three statement shapes, so this is
  satisfiable - but which of them runs at boot is NOT yet known.

### Open / NOT verified
- Whether bluetoothd opens and queries this file **at boot** on a HomePod. The `makes` query's callers
  (`0x1001a8ee4` <- `0x100241b04`, `0x100241e78`, `0x1002cb824`) are not yet traced to a startup entry point.
- That the deref yields useful PC control: we have a leak and an arbitrary pointer store, but no fake
  `sqlite3_tokenizer_module` at a known address yet. A8 has no PAC, which helps.
- Observability on a booted pod. Next test: pymobiledevice3 (installed on the Mac) for `syslog live` / crash reports
  over USB; a HomePod has no Trust prompt, so pairing may just work. The runner now has an `info` action (ideviceinfo)
  as a fallback check, available after its next restart.
- Non-destructive probe is built and waiting: `multipod/route2/pincode_defaults.probe.db` is the stock file with
  `makes` renamed to `makes_probe`, so bluetoothd's prepare fails and it logs an SQLite error. Stock copy kept as
  `pincode_defaults.orig.db` (same sha256 as the OTA original).

## 2026-11-25 17:55, THE ONE THAT MATTERED: the OS boots the APFS snapshot, not the live volume

This invalidates several earlier results. Established with pymobiledevice3 (installed on the Mac, pod pairs over
USB with no Trust prompt) giving full DEBUG syslog plus `syslog collect` for the persisted log.

- Kernel, every boot: `handle_snapshot_mount:490: mounting snapshot w/snap_xid 26 and sblock oid 0x3aa02f`, then
  `apfs_vfsop_mount:1489: mounted volume: System`. Renaming the root snapshot to `orig-fs` did NOT change what the
  kernel mounts - it resolved and mounted that snapshot anyway. So **everything written to the live volume from the
  SSH ramdisk is invisible to the running OS**, and it is not erased either (verified: our planted probes were still
  byte-present on the live volume after a full boot).
- Therefore VOID, to be re-tested: (1) gate A - the `com.example.r2gate` plist was never visible to launchd, so the
  NVRAM result proved nothing by itself (the launchd MRM-cache finding still stands on the disassembly alone);
  (2) the bluetoothd pincode probe - no `no such table: makes` because the file the OS read was Apple's, not ours.
  bluetoothd is NOT ruled out. A setup attempt with a phone nearby was also void for the same reason.
- Also seen once, from the post-restore boot at 16:16:05 (NOT every boot):
  `MobileSoftwareUpdate.CleanupPreparePathService: reverting system`, `handle_revert_to_snapshot:4208: On next mount,
  volume will revert to snapshot 'com.apple.os.update-<MANIFEST_HASH_1_SHORT>'`, `revert_to_snapshot:1156: Reverting to snapshot
  w/xid 26` (freed 0 blocks). Worth remembering: iOS can revert the live volume to the snapshot on its own.

### Fix applied (job 525)
`snaputil` on the SSH ramdisk supports -l/-c/-n/-d/-r/-s/-o. Deleted `orig-fs` and created a new snapshot named
`com.apple.os.update-<MANIFEST_HASH_1>` **from the live volume**, so planted files are inside
the root snapshot. (`snaputil -o` prints the RAMDISK's own original name, 63F4C020..., not the target volume's - do
not use it for the pod.) The long-term approach is to plant inside myrootfs.dmg so the restore's own snapshot
contains the files; the swap is for fast iteration.

### Corrections to things I said earlier today
- I claimed makeipsw13's OTA extractor drops all 89 symlinks, and that this explained the pod booting into setup
  mode every time. **Both wrong.** The pod's System volume has exactly 89 symlinks, including `var -> private/var`,
  `etc -> private/etc`, `tmp -> private/var/tmp` and `Library/Keychains -> ../private/var/Keychains`. The extracted
  copy under ~/homepod/oldfw looks symlink-free only because the desktop folder bridge does not expose symlinks to
  the Linux side (`find -type l` = 0 there, 89 on the pod). There is no extractor bug. The setup-mode-every-boot
  symptom is still unexplained.
- The bluetoothd "Nbmatchrules=2" / "ADD_ADV_MATCHING_RULE" log lines are BLE advertisement filters programmed into
  the Broadcom controller, not SQL `matching_rules_*` lookups. No relation to pincode_defaults.db.

### `/Library/Keychains` is not plantable
trustd at boot: `open(/Library/Keychains/pinningrules.sqlite3) - No such file or directory` then
`SecPinningDb: unable to initialize db: "preparev2: [1] no such table: admin"`, every boot, ~11 s in, as _securityd.
A tempting target (a SQLite file that does not exist, queried for table `admin`) but `/Library/Keychains` is a
symlink to `../private/var/Keychains`, i.e. the Data volume, which the ramdisk cannot mount. Only reachable by
replacing the symlink with a real directory, which would also redirect securityd's `keychain-2.db` to a read-only
location and break the keychain. Not done. A probe DB is built and parked at
`route2/pinningrules.probe.sqlite3` (view `admin` over a missing table `zzpPINPROBE`) in case that changes.

### What the boot log says about SQLite at boot (setup mode, stock files)
Processes that open SQLite DBs during boot: homed, locationd, medialibraryd, identityservicesd, itunesstored, trustd,
migrationpluginwrapper, securityd, awdd, AirMusic. **Every path is under /var (Data volume)** except trustd's two
`/Library/Keychains/*` ones. locationd opened only `/var/root/Library/Caches/locationd/consolidated.db` and logs
every statement via `sqlite3_profile`, which makes it a very good observation target if it ever reads a plantable file.

### Probes now planted (all on the live volume, now inside the root snapshot)
`pincode_defaults.db` (table `makes` -> `makes_probe`) plus 11 more with every table prefixed `zzp_`, so any read
produces `malformed database schema (zzp_<table>)` naming the file: CoreLocation factory_minimum (both copies),
factory.db, timezone.db; Security valid.sqlite3; CoreAnalytics marketMap.sqlite; AppSupport CityInfo.db;
usr/libexec/topicsmap.db; HIDPlugins cblight.sqlite; TTS TuplesEng; WebKit HTTPSUpgradeList.db. Stock copies of all
of them are in `route2/probes/*.orig.db`; `route2/restore-all-job.txt` puts everything back.

## 2026-11-25 18:35, FOOTHOLD: launchd will run any trust-cached Apple binary from a path we control

### The primitive (works, verified on the pod)
AMFI validates a binary by its **cdhash against the trust cache, not by its path**. The launchd service cache
`/System/Library/Caches/com.apple.xpc.launchd/mrm.plist` names `Program` paths. So: leave the cache byte-identical to
Apple's, and instead put a *different* Apple-signed binary's bytes at a path the cache already launches at boot.
- Job 534: copied `/usr/sbin/racoon` (635616 bytes) over `/usr/libexec/CrashHousekeeping` (55152 bytes, cached job
  `com.apple.CrashHousekeeping`, RunAtLoad, root, non-essential), re-snapshotted, booted.
- The pod booted normally, and pid 35 - named CrashHousekeeping, launched from Apple's unmodified cache - ran racoon:
  `create <SCPreferences> {name = racoon, id = com.apple.ipsec.plist}`, `configd: open: Unknown(35):racoon`,
  `plogsetlevel: about to set racoon's log level 7, mask 1ff`.
- So we have: **arbitrary trust-cached Apple binary, as root, at boot, with no modification to any protected file.**
  Backups on the pod: `/usr/libexec/CrashHousekeeping.stock`, `/private/etc/racoon/racoon.conf.stock`;
  `route2/subst-binary.sh` / `subst-undo.sh` do and undo it.

### Two limits of the primitive
1. The hijacked process is sandboxed: `Sandbox: CrashHousekeepin(35) deny(1) process-fork`, and denials for
   `file-read-data /usr/libexec` and `file-read-metadata /usr/libexec/CrashHousekeeping`. racoon tried to daemonize,
   was refused, and got no further. Whether the profile comes from the host job or from racoon's own entitlements is
   NOT yet established - that decides whether a different host job would be less restricted.
2. Arguments come from the host job's cached `Program`/`ProgramArguments`, which we cannot change (see below), so the
   substituted binary runs with whatever argv the host job has - for CrashHousekeeping that is argv[0] only.

### racoon on iOS does NOT read racoon.conf
It is configured through SCPreferences `/Library/Preferences/SystemConfiguration/com.apple.ipsec.plist`
(`SCPreferences() access: ... com.apple.ipsec.plist, size=0`). Like `/Library/Keychains`, `/Library/Preferences`
resolves onto the Data volume, so it is not plantable. **The racoon.conf parser defect D1 from earlier does not apply
on this platform** - that avenue is withdrawn unless racoon can be forced to use a file via `-f`.

### mrm.plist is integrity-enforced - established with a proper control
Modifying the service cache at all breaks boot into a ~3 s loop (37+ iBoot banners in 2 min, never enumerates on USB;
contrast a healthy boot: enumerates in ~13 s, one extra reboot from the MSU snapshot revert, then stable).
- stock bytes + our snapshot cycle -> **boots** (job 531, 18:27) <- the control that matters
- one byte changed inside a label string, same size, same encoding -> **loops** (job 530)
- structurally injected job (7 appended objects, 2 bytes patched in Apple's region) -> **loops** (job 529)
- in-place argv hijack (identical size, no objects moved) + `launchd_cache_loader` renamed -> **loops** (job 532)
launchd itself cannot be the enforcer: it links only libSystem and libobjc and imports **no** hashing or crypto
symbols at all (only `csops`/`csops_audittoken`, which inspect a process). Renaming the one validator we found,
`/usr/libexec/launchd_cache_loader` (which does link Security: SecStaticCodeCheckValidity,
SecCodeSetDetachedSignature, AMFI cdhash check), did not help - though that test is ambiguous because we never
checked whether the rename alone is survivable. Leading hypothesis: the file's hash is in the static trust cache and
the kernel refuses the mapping when it changes, which would mean no edit is ever possible without Apple's key.
NOT tested: stock cache + renamed loader (the isolating control), and deleting/corrupting `mrm.plist.sig`.

### Tooling corrections worth keeping
- `snapswap.sh` must delete snapshots **by their actual current name** (`snaputil -l` first). The first version
  hardcoded `orig-fs`, silently failed after the first swap, and nearly produced a false negative.
- The snapshot cycle itself is innocent: stock content + the same delete/create cycle boots fine.
- A healthy boot on this install reboots itself once (MSU reverts the live volume to the root snapshot) and then
  settles. That is not a fault and must not be read as a loop.

### Next candidates for the primitive (pair a host job with a substituted binary)
Needed: a binary that does not fork and parses a file we can write on the System volume.
- `/usr/sbin/syslogd` with `/etc/asl.conf` and `/etc/asl/*` (both on the System volume, already ours to edit).
- `/usr/sbin/pppd` with `/etc/ppp/options` - `/private/etc/ppp` exists and is **empty**, so the file is purely ours.
- `/usr/libexec/wifiFirmwareLoader`, which loads firmware blobs from the System volume (4 ENOENTs at boot).
Also worth settling first: whether the sandbox follows the host job or the binary, by substituting into a different
host job and comparing the denials.

### R3.1 ANSWERED STATICALLY: the sandbox follows the BINARY, via its code signature
Neither racoon nor CrashHousekeeping references `sandbox_init`, and only three `.sb` files ship on the volume
(com.apple.contextstored, com.apple.homed, com.apple.siri.ClientFlow.ClientScripter) - none for either. The profile
comes from the `seatbelt-profiles` entitlement in the binary's own code signature, which AMFI applies. Parsed from
the LC_CODE_SIGNATURE entitlements blob of each candidate (17M61):

    racoon              seatbelt = racoon      (6 entitlements)   <- the source of the job 534 denials
    cfprefsd            seatbelt = cfprefsd    (7)
    logd                seatbelt = logd        (3)
    syslogd             seatbelt = NONE        (0 entitlements)
    pppd                seatbelt = NONE        (2)
    nvram               seatbelt = NONE        (0)
    aslmanager          seatbelt = NONE        (0)
    notifyd             seatbelt = NONE        (0)
    distnoted           seatbelt = NONE        (0)
    fseventsd           seatbelt = NONE        (1)
    wifiFirmwareLoader  seatbelt = NONE        (2)
    keybagd             seatbelt = NONE        (31)
    mDNSResponder       seatbelt = NONE        (20)
    CrashHousekeeping   seatbelt = NONE        (4)

So choosing a different HOST JOB cannot loosen the sandbox - choosing a different SUBSTITUTED BINARY can. racoon was
simply an unlucky first pick. Several useful binaries run with no profile at all.

### Next experiment queued (job 535): syslogd substitution
syslogd has no seatbelt profile, no fork/daemon references, and parses `/etc/asl.conf` plus every file in `/etc/asl/`
- all on the System volume and all ours. Substituting it into `/usr/libexec/CrashHousekeeping` should therefore give
an **unsandboxed root process at boot parsing a configuration file we fully control**. The probe plants
`/etc/asl/zzpASLPROBE` (additive; stock asl.conf untouched so logging keeps working) with a `>` directive aimed at a
read-only System path, which must fail loudly and name the marker, plus one on the writable Data volume. Proof shape
is the same as job 534: log lines whose process name is `CrashHousekeeping` but whose content is syslogd's.
Why it matters: asl.conf `>` sets path, uid, gid and mode, and `format=` controls the bytes written, which together
approximate creating files as root at chosen paths with chosen contents.

### CORRECTION to the seatbelt table: an absent entitlement does NOT mean unsandboxed
`/usr/libexec/wifiFirmwareLoader` shows `seatbelt-profiles` = NONE in its entitlements, but it carries its **own
sandbox profile compiled into the binary** and applies it itself (it has one `sandbox_init` reference). The inline
profile is visible as a string: `(version 1)(deny default)(import "system.sb")` ... `(allow file-read* (subpath
"/usr/share/firmware/wifi"))`, `(allow file-read-data (literal "/Library/Managed Preferences/mobile/
com.apple.wifiFirmwareLoader.plist"))`, `(allow iokit-open (iokit-user-client-class "AppleBCMWLANUserClient"))`,
`(allow file-write* (literal "/private/var/logs/wifiFirmwareLoader.log"))`. So the entitlement table only rules out
the *AMFI-applied* profile; a binary may still self-sandbox. syslogd/pppd/nvram showed no `sandbox_init` reference,
so for those the conclusion stands, but it should be checked per binary.

### NEW VECTOR: Wi-Fi firmware and nvram blobs are on the System volume and are parsed by the KERNEL driver
At boot, `wifiFirmwareLoader` (root, RunAtLoad, its own job - no substitution needed) reads from
`/usr/share/firmware/wifi/C-4357__s-B1/`:
    crush.trx                        1033393 bytes   (Broadcom firmware image)
    P-crush_M-TBRG_V-u__m-{4.1,4.3,4.5,5.1,5.3}.txt   6186 bytes each  (Broadcom "nvram" text config)
and hands the buffers to the kernel through `AppleBCMWLANUserClient` /
`WiFiUserClientPrepareMapping return %x firmwarebuffer len %lld nvrambuffer len %lld reg len %lld`. One config file
stat()s missing at every boot (`Error: Could not stat <private> (No such file or directory)`), so there is also a
path we could *create* rather than modify.
Why this is the best surface found so far: the data is ours (plain files on the System volume, no integrity check -
the 12 SQLite probes proved that), it is consumed automatically at every boot with no substitution trick, and the
parsing happens in the **kernel's Broadcom driver** and on the Wi-Fi chip rather than in a sandboxed userland
process. That skips the whole userland-to-kernel step the untether would otherwise need.
Observability, and this is the neat part: os_log redacts the paths as `<private>` but NOT the sizes -
`Get size of "<private>", size = 1033393 bytes`. So changing a file's size gives a receipt we can read straight from
the live syslog, with no Data-volume access and no crash needed.
Also plantable and explicitly allowed by its sandbox: `/Library/Managed Preferences/mobile/
com.apple.wifiFirmwareLoader.plist` (that directory is a real one on the read-only System volume - cfprefsd logs
"Failed to repair permissions on /Library/Managed Preferences ... Read-only file system"), and the binary contains a
`wifi-nvram-path` key, so the plist may let us redirect which blob is loaded.

### VERIFIED 2026-11-25 18:54: a file we write on the System volume reaches a kernel buffer at every boot
Job 536 appended `zzpprobe=1234\n` to all five `P-crush_M-TBRG_V-u__m-*.txt` nvram configs (6186 -> 6200 bytes),
restored the genuine CrashHousekeeping, re-snapshotted. The pod booted normally and the persisted log shows:
    wifiFirmwareLoader[26]: Get size of "<private>", size = 6200 bytes
    wifiFirmwareLoader[26]: Copying "<private>", file size = 6200 bytes
    wifiFirmwareLoader[26]: WiFiUserClientPrepareMapping return 0 firmwarebuffer len 1033393 nvrambuffer len 6216 reg len 10101
With the stock file the same line reads `nvrambuffer len 6202`; ours is 6216, i.e. grown by exactly the 14 bytes
added. So: **our bytes are read at boot and mapped into the kernel's Broadcom driver, automatically, every boot**,
and the size in the log is a reliable receipt that needs no Data-volume access. Wi-Fi still worked and the unknown
key was tolerated. Other buffers seen on the same path: firmware `crush.trx` 1033393, regulatory blob 10101, plus one
config that stat()s missing every boot (`config full name <private> size 0`) - a path we could create.

Caveat on what this does NOT prove: the nvram text is most likely parsed by the Wi-Fi chip's own firmware rather
than by the host kernel, so a defect there would yield control of the chip, not of the host. What we want is a flaw
in how the **driver** handles these buffers (lengths it trusts, copies it makes) or in the chip-to-host path. The
`crush.trx` image is the more promising of the two for that, being header/length/offset driven.

NEXT (offline, no pod, no risk): disassemble the Broadcom firmware-load path in
`~/homepod/oldfw/17M61/ota/kernelcache.release.b238` and read how the nvram and trx buffers are consumed and
validated before deciding to feed it anything malformed. Backups of every blob are on the pod beside the originals
(`*.stock`) and `route2/wifi-restore.sh` puts them all back.

### Kernel side of the Wi-Fi firmware path (offline analysis of kernelcache.release.b238)
The OTA kernelcache is IM4P-wrapped `complzss`; decompressed with a classic lzss.c implementation to a 24945952-byte
arm64 Mach-O (tooling: `/home/claude/kc/unlzss.py`, copy committed to `route2/kernelcache.b238.macho`). Kexts are
merged into the main image (`__PRELINK_TEXT` is empty, `__PRELINK_INFO` is binary, not XML). Relevant kexts by
bundle id: `com.apple.driver.AppleBCMWLANCore`, `AppleBCMWLANBusInterfacePCIe`, `com.apple.iokit.IO80211Family`,
and **`com.apple.driver.BCMWLANFirmware4357.Hashstore`**.

**The firmware image looks hash-verified; the nvram text does not.** There is an `IOImageLoader` family in the
kernel with `IOImageLoaderHashstore`, and a kext `BCMWLANFirmware4357_Hashstore` (class of the same name) that
matches on provider `IOImageLoader` with `consumer-id = com.apple.driver.AppleBCMWLANCore`. Its code paths are
`requestImageVerify[imageDict ...] _datastoreSet count:%u, _hashstoreSet count:%u` and
`processImageVerify[... ] verified:%d`, plus `%s:%d: Not a Datastore or Hashstore, bailing`. So expect `crush.trx`
to be rejected if modified - that needs its own check before anyone spends a boot on it.
Empirically, though, our 14-byte addition to the nvram text was accepted: the buffer was mapped
(`nvrambuffer len 6216`), `AppleBCMWLANCore::getFeatures()` ran and wifid came up normally on that boot. No
ImageVerify or hashstore lines appear in the log at all (those strings are DEBUG-prefixed and seem not to be
emitted). So the nvram text is either outside the hashed set or the verification is not blocking.

**Host-kernel parsing of our nvram text does exist**, which is the part that matters: the driver has
`%s@%d: Failed to normalize NVRAM: nvram length[%zu]` (string at `0xfffffff007328018`, referenced from code at
`0xfffffff0080b59d8`) and a second variant `Failed to normalize NVRAM\n` (string `0xfffffff007306083`, referenced
from `0xfffffff008035700`), plus `%s@%d: kernel alloc imageSize is too small! imageSize->firmwareSize %d
imageMap->firmwareBufferLength %d` (string `0xfffffff00731f27a`, referenced from `0xfffffff00808e8bc`) and
`imageSize->nvramSize %d imageMap->nvramBufferLength %d ... regSize ... txCapSize ...`. The error site sits in a
function with a 0x120-byte frame ending `ret` at `0xfffffff0080b5994`.
So there is a kernel-resident "normalize NVRAM" step over attacker-controlled text with an explicit length in play -
the right thing to read next.

Tooling note: Hopper (via the rea tools) timed out on the 25 MB kernelcache at its 120 s startup limit and left a
retained document - worth closing it on the Mac before reopening anything. Carving `AppleBCMWLANCore` out to a small
standalone Mach-O would make the decompiler usable, but `__PRELINK_INFO` is binary here so the kext boundaries need
reading from that structure rather than from a plist. My own capstone-based scanners are in `/home/claude/kc/`
(`kcfind2.py` finds string references via a rolling adrp/add map; `kcref.py` does it per-adrp with capstone;
`kcdis.py` disassembles a range). Note for next time: the format strings start with `%s@%d`, so a reference search
must target the start of the string, not the readable text inside it - that cost me three failed scans.

## 2026-11-26 03:40 — R4.4/R4.5 CLOSED: the Wi-Fi kernel path is hardened. New primitive found instead.

All offline, from `route2/kernelcache.b238.macho` (24945952-byte Mach-O, b238a). Tooling: `kc/kcdis.py` (range
disassembler), `kc/kcref.py` (adrp/add string-reference finder). Segments: `__TEXT` vm 0xfffffff007004000,
`__TEXT_EXEC` vm 0xfffffff007640000 file 0x63c000.

### normalizeNVRAM — 0xfffffff0080b5438 .. 0xfffffff0080b5994. A clean sanitizer, not a bug.

Fully decoded. Arguments: x21=arg0, x25=arg1, x24=arg2; `[x24+0x20]`=source pointer, `[x24+0x28]`=LEN.

    x20 = LEN + 2 ; x19 = kalloc(x20) ; bzero(x19, x20)      <- output buffer
    x22 = LEN + 2 ; x23 = kalloc(x22) ; bzero(x23, x22)      <- working copy
    require LEN >= 3, x20 >= LEN, x22 >= LEN
    memcpy(x23, src, x22)                                     <- 0xfffffff0080b5550
    require x20 >= 5, x22 >= 3
    x27 = x20 - 2   (== LEN)                                  <- the output bound

Both kalloc sizes are the *requested* LEN+2 (kalloc here is 0xfffffff007b7bdf0, returns only a pointer), so there
is no rounded-up-size confusion. Parser loop 0xfffffff0080b55cc .. 0xfffffff0080b587c:
- loop guard `cmp x27, w21, uxtw ; b.ls` — continues only while output index w21 < LEN.
- `ldrsb w9,[x23,x10] ; tbnz w9,#0x1f` — any byte >= 0x80 aborts the whole routine.
- 3-state machine in w8 over 0x23 '#', 0x21 '!', 0x09, 0x0a, 0x0c, 0x0d, 0x20. One output byte per input byte at
  most; stores are `strb w10,[x19,x11]` with x11 = w21.
- WRITE BOUNDS ARE CORRECT. Max in-loop index is LEN-1; the post-loop terminator at 0xfffffff0080b5810 writes index
  w9+1 where w9 == x27 == LEN at most, i.e. index LEN+1 — the last legal byte of the LEN+2 buffer. The two extra
  bytes are deliberate slack. No off-by-one anywhere in the loop.
- `x19` is advanced by the token start (`add x19,x19,w13,uxtw` at 0xfffffff0080b56a4) only for the key comparison,
  and EVERY exit from that comparison reloads it from `[sp,#0x70]` (0xfffffff0080b5724, 0xfffffff0080b5744). Checked
  all four exits. Not a bug — I thought this was one at first.

What it actually does: strips comments and whitespace, rewrites the text as a NUL-separated key=value list, and
DELETES any line whose key matches one of five names. The table is built on the stack at sp+0x80 from
0xfffffff007328154 `macaddr`, 0x15c `nocrc`, 0x162 `il0macaddr`, 0x16d `nvramver`, 0x176 `moduleid`. On a match the
output index is rewound to the token start (0xfffffff0080b5710: `x9 = x13`), so the line vanishes. The kernel
supplies those five itself from SysCfg.
>>> `nocrc=1` CANNOT be smuggled to the firmware through our nvram text. It is filtered by name, deliberately.

Only defect found: `memcpy(x23, src, x22)` copies LEN+2 bytes from a source whose declared length is LEN, and the
parse loop's input bound is also x22, so two bytes of adjacent kernel heap get parsed as nvram text and forwarded to
the firmware. A 2-byte over-read, direction away from us, no attacker control of the two bytes. Not useful.

### AppleBCMWLANUserClient::prepareImageMap — 0xfffffff00808e500 .. 0xfffffff00808e910. Hardened.

Source line numbers are passed to the logger (0xfffffff007ef8dfc) as `__LINE__`: 405, 412, 413. Strings live at
0xfffffff00731f1ff `prepareImageMap`, 0x20f `verifyFileSelect`, 0x22b `fActiveChipImage alloc fail`, 0x24f
`ChipImage prepareMapping fail:0x%x`, 0x27a `kernel alloc imageSize is too small! ...`, 0x2e4 the nvram/reg/txcap
variant, 0x38f `completeImageMap`.

x2 is IOExternalMethodArguments. Hard-gated on exact struct sizes: `[x2+0x38]` (structureInputSize) must == 0x1c and
`[x2+0x60]` (structureOutputSize) must == 0x58, else immediate bail. The input is seven u32 sizes read at
0xfffffff00808e584..598. Every one is range-checked with BOTH a minimum and a maximum before anything is allocated:

    firmwareSize  w24: <= 0x200000 and >= 0x19000     (err +0x1dd / +0x1dc)
    nvramSize     w21: <= 0x8000  and >= 0x64         (err +0x1df / +0x1e8)
    [sp+0x48]  w9: <= 0x10000 and >= 0x21             (err +0x1e0 / +0x1e1)
    regSize       w23: <= 0x4000                       (err +0x1e4)
    ... same shape continues for the rest

So the "imageSize is too small" message at line 412 is a post-allocation consistency assertion (defence in depth),
NOT a trusted-length bug. There is no size confusion to exploit here. The userclient also requires the
`com.apple.wlan.userclient` entitlement in `initWithTask` (0xfffffff00731f0ed `entitlement check failed`).

>>> R4.4 and R4.5 are both closed. The premise behind them — that the kernel parses our Wi-Fi bytes sloppily — is
>>> wrong. This code has been audited. Do not spend more boots on malformed nvram text or crush.trx edits.

### THE ACTUAL FIND: kernel-honoured NVRAM overrides for the firmware and nvram paths

Function 0xfffffff00808e134 .. 0xfffffff00808e3c4 reads IORegistry properties off `/options` — which IS the NVRAM
node — and uses them to override which files the Wi-Fi stack loads:

    gate  = 0xfffffff00808cb50
    entry = IORegistryEntry::fromPath("/options", ...)        <- 0xfffffff00726b6f9, call 0xfffffff007b857f0
    getProperty("wifi-fw-path")      -> OSDynamicCast<OSString> -> override firmware path
    getProperty("wifi-nvram-path")   -> OSDynamicCast<OSString> -> override nvram path
    also `RequestedFilesOverride` at 0xfffffff00731f1b5 (0xfffffff00808e348)
    log lines: 0xfffffff00731f17a `updated FW path: %s`, 0x196 `updated NVRAM path: %s`

The gate at 0xfffffff00808cb50, decoded in full:

    static once-flag at 0xfffffff0087863a0, value at 0xfffffff0087863a4
    if (!once) { if (!PE_parse_boot_argn("wlan.debug.enable", &val, 4)) val |= PE_i_can_has_debugger(NULL); once=1; }
    return val != 0;

`PE_parse_boot_argn` is 0xfffffff007c1c9cc (identified because normalizeNVRAM's own prologue calls it with
"wlan.debug.enable" / 1 byte). `PE_i_can_has_debugger` is 0xfffffff007c1ede8, returning the global at
0xfffffff007033b00 — zero on a production boot.

>>> So: boot-arg `wlan.debug.enable=1` unlocks NVRAM variables `wifi-fw-path` and `wifi-nvram-path`, and the KERNEL
>>> will then load the Wi-Fi firmware and nvram text from ANY filesystem path we name. No file needs to be at an
>>> Apple-chosen path, and no snapshot surgery is needed to change which bytes are used.

This is a privilege-free redirect — but it is gated on a boot-arg, and that reframes what is worth testing next.

## 2026-11-26 03:35 — iBoot versions on this pod, and why the static R5 answer is not available yet

Tried to answer R5 statically instead of with a boot. Partly a dead end, but it pinned down facts worth keeping.

From the UART capture of a real boot (`diags_archive/screenlog.0`, 2026-11-25 19:22):
- `iBoot-5540.140.12` — the pod's OWN NOR iBoot. Banner `iBootStage2 for b238a, Copyright 2007-2019`,
  `Local boot, Board 0x38 (b238aap)/Rev 0xa`. THIS is the one that decides whether NVRAM boot-args are honoured,
  and therefore the only one R5 is about.
- `iBoot-10151.120.138` — the Supervisor iBoot we send over USB for the ramdisk. Banner `Supervisor iBootStage2 ...
  Copyright 2007-2024`, `Remote boot`. Newer, from the 18.3/26.0.1 IPSW the sshramdisk is built from. Irrelevant
  to R5 because it only exists while a host is attached.
- `RELEASE` appears 6x; both of the above are RELEASE builds.

`diags_archive/iBootDec.im4p` is NOT either of them. It is a flat decrypted image (no IM4P wrapper despite the
name, starts straight at ARM64 code), base 0x830000000, and its own version strings are `iBoot-4076.30.43` and
**`DEVELOPMENT`** (pool refs at file 0x3180/0x31a4 -> 0x830000280 / 0x830000240). A DEVELOPMENT iBoot honours
boot-args by construction, so reading it would have told us nothing about the retail path — and I nearly drew a
conclusion from it before checking the version. Where that image came from is worth knowing (ProtoPod is the
obvious guess, see R5.5); it is not the pod's firmware.

Useful mechanics learned on that image anyway, for whenever we do get iBoot-5540.140.12 decrypted:
- Base is 0x830000000 and the image is flat, so file offset == VA - base. Confirmed by the one pointer to the
  `boot-args` name (file 0x43c00 -> 0x8300391d9, and `boot-args` really is at file offset 0x391d9).
- iBoot references strings with **ADR**, not adrp+add: 4929 ADR vs 4450 ADRP, and with ADR's +/-1MB reach covering
  the whole 688KB image there is no need for adrp. An adrp-only reference scanner returns zero hits on strings that
  are certainly referenced (validated against `UpdateDeviceTree: failed to find the /chosen node` at 0x3af20) — so
  a null result from one of those scanners means nothing. `kc/ibref*.py` are adrp-only and must not be trusted for
  iBoot; add ADR decoding before reusing them.
- NVRAM variable names live in a flat NULL-terminated array of bare name pointers at file 0x43be0..0x43cb0, wedged
  between two chunks of the iBoot command table (command entries are 5 qwords: name, handler, help, 0, 0). Members:
  alamo-path, rtos-path, rbm-path, auto-boot-usb, boot-args, bootdelay, diags-path, reconfig-behavior, emu,
  root-live-fs, enable-upgrade-fallback, auto-boot, backlight-level, boot-command, com.apple.System.boot-nonce,
  debug-uarts, device-material, display-rotation, idle-off, is-tethered, darkboot, ota-breadcrumbs,
  boot-breadcrumbs, com.apple.System.tz0-size, com.apple.System.rtc-offset, pwr-path.
- `debug-enabled` (file 0x3af64) is NOT an NVRAM variable here. It sits in a cluster of device-tree property names
  next to `chosen`, `nvram-proxy-data`, `consistent-debug-root`, `development-cert`, `production-cert`,
  `secure-boot`, `certificate-production-status`, `certificate-security-mode`,
  `effective-production-status-ap`, `effective-security-mode-ap`, and the string
  `UpdateDeviceTree: failed to find the /chosen node`. So iBoot DERIVES debug-enabled from the boot policy and
  writes it into DT /chosen; that is where the kernel's `debug_enabled` global (0xfffffff007033b00, read by
  PE_i_can_has_debugger 0xfffffff007c1ede8) comes from. It is not something we can set.

### Observability correction that would have cost a boot
`nvrambuffer len` is an os_log line from the *userspace* `wifiFirmwareLoader` daemon reporting what
WiFiUserClientPrepareMapping returned. It appears ONLY in the `syslog collect` + `log show --archive` captures
(`route2/bootarchive{,2,6,7}.txt` have 4/1/3/6 hits). It is in NO UART screenlog, and NOT in `podsyslog.txt`
(live syslog attaches ~10-15s in, after the loader has already run). Because the archive is the *persisted* log,
there is no need to race the boot — collect after the pod settles:
    pymobiledevice3 syslog collect bootN.logarchive
    log show --archive bootN.logarchive --info --debug --style compact > bootarchiveN.txt
Secondary tell, if boot-args ARE honoured: UART does carry kernel IOLog/kprintf (`spaceman_datazone_init`,
`constructing idle task`, `IOPortFamily::registerService()` all appear), and `wlan.debug.enable=1` opens the
driver's log-level gate (`[x8+8] >= 4`), so expect extra AppleBCMWLAN chatter on UART too.

### Job 538 — armed and verified, 2026-11-25 19:25
alt-nv.txt 6400 bytes root:wheel 644 at /usr/share/firmware/wifi/C-4357__s-B1/; snapshot recreated from the live
volume; unmounted clean. NVRAM writes from the ramdisk DO stick and read back:
    wifi-nvram-path   /usr/share/firmware/wifi/C-4357__s-B1/alt-nv.txt
    boot-args         wlan.debug.enable=1
Prior boot-args was EMPTY (saved to /mnt1/boot-args.stock). Awaiting one cold boot: nvrambuffer len 6416 = honoured,
6216 = ignored.

## 2026-11-26 03:40 — R5 ANSWERED, NEGATIVE: retail iBoot drops the NVRAM boot-args variable

Evidence from `route2/bootarchive8.txt` (36 MB, 7 boot sessions, collected 19:31 after job 538 armed the NVRAM):
- `nvrambuffer len` is **6216** on every line. Never 6416. The override did not apply.
  (`grep -c 6416` returns 19, but ALL 19 are coincidental substrings inside UUIDs — `FB86416D-...`,
  `D0C0306A-6416-...`, `E64164CB...`. None is a buffer length. Checked each one; do not be fooled by that count.)
- `SoundBoard: bootargs is` — with NOTHING after it — in **all 7** boot sessions, alongside
  `doCheckBadBootArgs: 1, _hasBadBootArgs: 0`. Userspace sees an EMPTY boot-args string.
- No `updated NVRAM path` / `updated FW path` line anywhere in the archive.
- The NVRAM write itself is fine: the ramdisk read both variables straight back out of NOR (job 538 output).

>>> CONCLUSION: `iBoot-5540.140.12` (the pod's own NOR iBoot) does NOT pass the NVRAM `boot-args` variable to the
>>> kernel. The variable persists in NOR; iBoot simply ignores it. Therefore the gate at 0xfffffff00808cb50 stays
>>> shut on an untethered boot, the `wifi-fw-path`/`wifi-nvram-path` overrides are unreachable, and EVERY
>>> boot-arg-gated idea is dead untethered — including R5.3 (cs_enforcement_disable, amfi_get_out_of_my_way, amfi,
>>> -v). Do not spend further boots on boot-args. R5.1 closed, R5.3 closed.
Tethered is unaffected: we set boot-args freely on the iBEC we send over USB, which is how the ramdisk works.

Incidental, worth knowing: audioOS ships a whole `BadBootArgs` app and SoundBoard actively checks for bad
boot-args at every boot, which only makes sense on units where boot-args CAN be set. Consistent with dev-fused
hardware existing (see ProtoPod below) and with retail being locked.

### Not a lead, recorded so nobody chases it again
`isInternal: 1` appears 7x in SoundBoard's log and looks exciting. It is NOT a device flag: `isInternal: 0` appears
7x too, in a different SoundBoard line on the same boots, so it is a local variable reused by two unrelated checks.
`InternalBuild = false` (4x) is the authoritative answer — this is a retail build. The 37 `AppleInternal` hits are
all `Loaded 0 HID plugins (/AppleInternal/Library/HIDPlugins...)`, i.e. empty-directory probes, normal on retail.

### ProtoPod is dev-fused — confirmed by the author
The `iBoot-4076.30.43 DEVELOPMENT` image in diags_archive is ProtoPod's. So ProtoPod is a development-fused
prototype and boots unsigned firmware by design. That makes it a REFERENCE PLATFORM: anything we build can be
proven there, where the boot chain is not fighting us, before attacking retail `iBoot-5540.140.12`. It does not
make retail easier, but it removes "is our payload itself correct?" as a variable from every future test.

## R6: missing-path probes by privileged daemons (mined from bootarchive8.txt, offline)
Every boot, root daemons try to open paths that do not exist. Each is a plant site. Ranked by what they could give:

- R6.1 **mDNSResponder dlopen of a missing dylib on the SYSTEM volume — the best new lead.** 7x per archive:
  `mDNSResponder (CoreFoundation) Error loading .../DeviceToDeviceManager.framework/PlugIns/WiFiAwareD2DPlugin.bundle/WiFiAwareD2DPlugin:`
  `dlopen(..., 0x0106): dependent dylib '/System/Library/PrivateFrameworks/WiFiPeerToPeer.framework/WiFiPeerToPeer'`
  `not found for '.../WiFiAwareD2DPlugin'`
  mDNSResponder is root with 20 entitlements (earlier survey) and it dlopens a plugin bundle at every boot. The
  dlopen fails ONLY because a dependent dylib is absent, and that absent path is on the System volume, which we
  mount rw and snapshot-swap routinely. So this is a root daemon's code-loading path with a writable hole in it —
  structurally far better than anything in R4, which was only ever a data path.
  HONEST CAVEAT, do not skip it: code signing still gates this. AMFI requires a loaded dylib be platform-signed,
  and library validation requires the same team. Our substitution trick works because trust-cached Apple binaries
  keep a valid cdhash whatever path they sit at — but an arbitrary Apple dylib will not export the symbols
  WiFiAwareD2DPlugin needs, so dlopen would then fail on symbol resolution instead. The real questions, in order:
    (a) does `WiFiPeerToPeer.framework` exist in any firmware we hold (18.3, 26.0.1, AppleTV5,3 13.4.8 17M61)?
    (b) if so, does AMFI accept an Apple-signed dylib that is NOT in THIS build's static trust cache? That is the
        single most valuable unknown in the whole project right now, because the answer also decides whether any
        signed-but-foreign Apple binary can be planted anywhere.
    (c) cheap first probe: plant a deliberately invalid file at that path and see whether the dlopen error CHANGES
        (signature rejection vs not-found). A changed error proves the path is reached and tells us which wall we
        hit, and it costs one boot and no uncertainty.
- R6.2 `wifiFirmwareLoader: Error: Could not stat <private> (No such file or directory)` — **173x in one archive**.
  This is R4.2's path. Still redacted. Note the loader respawns every ~10.05s forever (launchd's minimum throttle;
  PIDs 26 -> 287 across 24 minutes, and the same 10s spacing is in bootarchive7, so it is pre-existing and NOT
  caused by us). That means this stat() repeats every 10 seconds indefinitely — an unlimited number of attempts at
  whatever we eventually put there. Unredact the path from the binary's strings rather than from the log.
- R6.3 `wifid: __WiFiManagerLoadDeviceSettings: failed to open`
  `file:///private/var/Managed%20Preferences/mobile/com.apple.wifid.configure.plist` — full UNREDACTED path, and
  wifid is privileged. Data volume, so not plantable from the ramdisk (never mount it, it hangs); would need our
  R3 root foothold to write at runtime. Data only, no code exec.
- R6.4 `AirMusic: os_unix.c:43353: (2) open(/var/mobile/Library/com.apple.iTunesCloud/ICDelegateAccountStore.db)`
  `- No such file or directory` — a MISSING SQLite database that is actually opened at every boot. This is exactly
  the shape our proven fts3_tokenizer/query-hijack primitive wants, and unlike the 12 System-volume DBs we probed
  (all closed negatives — nothing read them), this one IS read. Data volume; AirMusic is probably not root.
- R6.5 Lower value: `SoundBoard: Directory for secure file path (<private>) does not exist, will try to create now`
  (14x); `com.apple.datamigrator: Failed to open boot count file [2]`; `analyticsd: [File Config] Failed to load
  config for reason 'file does not exist'`; locationd's 5 "not found, skipping migration" bundles.
- R6.6 Unredacting os_log `<private>` would make all of this much easier. The logging preference
  `Enable-Private-Data` in a logging plist is the usual route; check whether the path lands on the System volume
  (note `/Library/Keychains` is a symlink to ../private/var/Keychains, so /Library subdirs must each be checked)
  before assuming it is plantable.

## 2026-11-26 03:45 — R3.3 CLOSED, NEGATIVE, and the definitive boot-job target list (offline, from mrm.orig.plist)

Parsed `route2/mrm.orig.plist` (256299 bytes) with plistlib. Top-level keys: AppExtensions, LaunchDaemons,
AppRemovalServices, SystemLibraryTreeState, VersionNumber. LaunchDaemons holds 183 jobs.

### R3.3 is a dead end
Only **16 of 183** jobs pass any argument beyond argv[0], and **not one of them is a file path** — every single one
is a flag or a label string:
  keybagd `-t 15`; AssetCacheLocatorService `-d`; BlueTool `-R`; OTATaskingAgent `server-init`;
  ReportCrash `com.apple.ReportCrash.SimulateCrash`; seputil `--daemonize-update-timer`;
  UserEventAgent `(System)`; cfprefsd `daemon`; afcd `-r`; ctkd `-tsw`; distnoted `daemon`;
  notification_proxy `-i`; osanalyticshelper `com.apple.osanalytics.osanalyticshelper`; racoon `-D`;
  hostapd `-l`; xpcroleaccountd `-launchd`.
So the R3.3 hope — pair a substituted binary with a useful file-path argument the host job already receives — is
impossible. Since the cache is integrity-enforced we cannot add arguments either. A substituted binary is therefore
only ever useful if it reads a **hardcoded** config path, which is what R3.2 already listed. R3.3 closed.

### COUNT CORRECTION
Earlier notes say "183 LaunchDaemons jobs, 40 RunAtLoad". The 183 is right; **RunAtLoad is 29, not 40** — recheck
whatever produced 40 before relying on it. Of the 29, **11 run as root** and are the real substitution hosts:
  CrashHousekeeping (our proven host), DumpPanic, containermanagerd, IOMFB_bics_daemon, locationd (KeepAlive),
  logd (KeepAlive), keybagd, lockdownd, runningboardd (KeepAlive), wifiFirmwareLoader (KeepAlive), wifid (KeepAlive).
The other 18 run as mobile/_installd/_timed: AirMusic, AirPodcasts, OTACrashCopier, SiriHeadlessService, SoundBoard,
SoundScapes, amsaccountsd, assistantd, bluetoothd, familynotificationd, homed, identityservicesd, installd,
softwareupdated, mobiletimerd, sharingd, timed, tvairplayd.

### Checked and closed: OTACrashCopier's bare program name
`com.apple.OTACrashCopier` is the one job whose Program is a BARE NAME (`OTACrashCopier`), not an absolute path, so
launchd resolves it through PATH (/usr/bin:/bin:/usr/sbin:/sbin — all on the writable System volume). That looked
like a free plant site needing only file CREATION rather than overwriting. It is not: the archive shows
`OTACrashCopier[56:2b5]` running as pid 56, so the name resolves to a real binary already. No hole. Closed.

## 2026-11-26 03:50 — The pod's REAL iBoot is readable, and its NVRAM parsing is clean

### We already had it
`homepod/oldfw/17M61/iBoot.dec` — 692800 bytes, decrypted on 2026-11-24 by `decrypt-oldfw.command` (gaster
decrypt_kbag + decrypt on the pod itself in DFU). Version strings: **`iBoot-5540.140.12` / `RELEASE`** — exactly
the banner the pod prints on a Local boot. `LLB.dec` (173440 bytes) is the matching LLB, same version. No need to
decrypt anything again. NOTE the IPSW to use is `homepodstuff/HomePod-13.4.8-17M61.ipsw` (b238a);
`AppleTV5,3_13.4.8_17M61_Restore.ipsw` is **j42d = Apple TV 4K**, the wrong device — do not analyse that one.
Keys: `multipod/makeipsw13/firmware_keys_17M61.zip` -> `firmware/AudioAccessory1,1/0x7000/17M61`.

### Mechanics for reading it (tools in /home/claude/ib5, rebuild as needed)
- Flat image, base **0x830000000**, page-aligned, so **file offset == VA - base**. Confirmed by the single pointer
  to the `boot-args` name (file 0x40500 -> 0x83003e210, and `boot-args` is at file offset 0x3e210).
- `iBootStrings.txt` in diags_archive was made from THIS image (its 0x3e210 for boot-args matches exactly), NOT
  from ProtoPod's dev iBoot. Earlier note to the contrary was wrong.
- iBoot addresses strings with **ADR**, not adrp+add. An adrp-only scanner returns ZERO hits on strings that are
  definitely referenced — validated against `load_bank_partitions: checksum failure`. `refs.py` now decodes ADR and
  ADRP+{ADD,LDR}; `ibdis.py` disassembles by file offset and prints both offset and VA; `fstart.py` finds the
  nearest prologue; `strs.py` dumps strings with offsets.

### load_bank_partitions (0x273f0) — correctly bounded, and it is the PANIC-LOG walker, not env
Reads 0x2000-byte banks via a function pointer at `[arg0+0x28]`, 0x14-byte bank header, checksum byte at `+1`
(computed by 0x2797c) and a 32-bit payload checksum at `+0x10` over 0x1fec bytes (0x20124). Partition cursor starts
at 0x20; per partition: header checksum byte at `+1`, type byte at `+0`, 0x7f = end marker, and a **halfword size
in 16-byte units at `+2`**. Bounds are right: size==0 is rejected (`load_bank_partitions: partition len out of
range`), and `cursor + size*16 <= 0x2000` is checked with 64-bit compares BEFORE use, so the
`memcpy(malloc(size*16-0x10), bank+cursor+0x10, size*16-0x10)` is in range. The name it matches is
`APL,OSXPani[c]` (0xc bytes at 0x3fb56), so this call walks NOR for the panic-log partition. No bug.

### The env-variable parser (0x224f0) — correctly bounded. Limits are 0x40 and 0x261.
Only ONE instruction in the whole image compares against `'='` (0x3d): file offset 0x2256c. That is the parser.
Frame 0x2d0, with a 0x261-byte buffer at sp+0x1f pre-filled with 0xaa (`memset(sp+0x1f, 0xaa, 0x261)`).
- Name scan and value scan are both bounds-checked against the BLOB length (`x19`) on every iteration.
- Name length `x21`: if >= 0x40 it logs an assert and sets the result to 0; the copy length is then clamped —
  `csinc x2, 0x40, x21, hs` — and copied with `f_25c64(dst=x29-0xa0, src, len, dstsize=0x40)`.
- Value length: if >= 0x261 it logs an assert; copy length clamped with `csel x2, x23, 0x261, lo`.
- `0x25c64` is a size-ASSERTING copy: `cmp x3, x2; b.lo` -> only copies when dstsize >= len, else logs and bails.
- `0x2292c` is not a panic: it stores the magic 0x0e2846af5eb52553 and returns, and the caller logs `%llx:%d\n`
  (0x3e05a) = magic:line. A compact assert/warn. Over-long variables are TRUNCATED and flagged, never overflowed.
So `max-env-var-name-size` = 0x40 (64) and `max-env-var-data-size` = 0x261 (609) are the real limits, and the
parser honours them. >>> No length bug in iBoot's NVRAM env parsing. That closes the obvious untethered idea.
Also: `setenv` (0x22213c..) special-cases `boot-args` ONLY to cap it — strlen >= 0x260 gets a NUL written at
offset 0x25f (cap 607 chars) plus an assert at line 0x10d. That single reference at 0x221f4 is the ONLY place the
`boot-args` string is used, so the code that would copy it into the DT /chosen node reaches it through the variable
table (the name-pointer list near file 0x40500), not by name. `debug-enabled` is referenced once, at 0xaa08.

## !! R5's NEGATIVE IS NOT PROVEN — a confound I missed, job 539 queued to settle it
Job 538 wrote `boot-args` and `wifi-nvram-path` FROM THE RAMDISK and read them back **in the same ramdisk
session**. That only demonstrates the in-memory IODTNVRAM proxy changed — note iBoot even has an
`nvram-proxy-data` string (0x3eea1), which is how NVRAM is hashed over to the kernel. It does NOT demonstrate the
write was flushed to NOR. If it never reached NOR then iBoot never saw `boot-args` at all, and
"retail iBoot ignores NVRAM boot-args" is UNPROVEN rather than wrong.
What we do know: an OS-written variable persists — the `r2-gate=ran` receipt was written by the hijacked job in the
booted OS and read back from a LATER ramdisk boot. We have never shown that a RAMDISK-written variable persists.
- Job 539 (`route2/nvram-verify.sh`, read-only) dumps nvram from a FRESH ramdisk after the OS has cold-booted.
    both variables still present -> the write is in NOR, iBoot really does ignore boot-args, R5 negative STANDS.
    variables GONE -> the ramdisk write never persisted; R5 must be redone by setting boot-args from the BOOTED OS
      via the R3 substitution foothold (which is the path we already know persists), not from the ramdisk.
Do not treat R5, or anything that depends on it, as settled until 539 reports.

## !!! 2026-11-26 03:55 — THE POD OBLITERATES ITSELF EVERY BOOT. This invalidates R5 and breaks all persistence.

Job 539 dumped NVRAM from a fresh ramdisk after the OS had cold-booted. Full contents:

    backlight-nits          0x00cd0000
    boot-breadcrumbs        <long iBoot breadcrumb trail, 3 boots worth>
    obliteration            handle_message: Obliteration Complete%0a
    SystemAudioVolumeSaved  true
    backlight-level         3286109
    bootdelay               0
    recovery-breadcrumbs    <BOOT> 1c002b(2007d00) 4011000c <COMMIT>
    boot-args               (EMPTY)
    auto-boot               true
    oblit-begins            OblitType: ObliterateDataPartition. Reason: Device was left in a partially-setup state

>>> `oblit-begins` / `obliteration` are the headline. The pod runs an **ObliterateDataPartition** every boot,
>>> because "Device was left in a partially-setup state" — HomeKit setup has never been completed on this pod.

What that destroys:
- `wifi-nvram-path` — GONE entirely (job 538 set it 25 minutes earlier).
- `boot-args` — present but EMPTY (job 538 set it to `wlan.debug.enable=1`).
- `r2-gate` — GONE. This one matters: it was written by the booted OS in an earlier session and read back
  successfully from a ramdisk then. So it DID persist once, and has since been wiped.
Surviving variables are all ones written during or after the obliteration (obliteration, oblit-begins,
breadcrumbs by iBoot, auto-boot/bootdelay/backlight/SystemAudioVolumeSaved by iBoot or the OS). That is consistent
with the obliteration resetting NVRAM, not with a name whitelist — several survivors (`obliteration`,
`SystemAudioVolumeSaved`, `backlight-nits`, `recovery-breadcrumbs`, `oblit-begins`) are NOT in iBoot's variable
name list, so nothing is pruning by name.

### Consequences — several earlier conclusions need re-reading in this light
1. **R5 IS INVALID, not negative.** We cannot tell whether iBoot ever saw `boot-args=wlan.debug.enable=1`: the
   obliteration may have wiped it before or after that boot, and bootarchive8 merged 7 boots. The "bootargs is
   empty in all 7 sessions" evidence is consistent with BOTH "iBoot ignores boot-args" AND "the variable was wiped
   before those boots". Treat R5 as open.
2. **This explains "the pod boots in setup mode every time"** (the author observed this on 2026-11-25 and flagged it as
   possibly significant — he was right).
3. **It is probably a second cause of the extra reboot per boot.** We attributed that entirely to the MSU
   snapshot revert (`revert_to_snapshot:1156`). An obliteration also forces a reboot. Both may be happening; the
   MSU explanation should not be treated as the sole cause any more.
4. **Every Data-volume plant is futile while this continues** — R6.3 (wifid's configure.plist) and R6.4
   (AirMusic's missing SQLite DB) both live on a partition that is erased every boot.
5. **NVRAM-based persistence is futile while this continues**, which removes NVRAM as a persistence substrate.
6. System-volume work is UNAFFECTED — that is why R3 binary substitution kept working: we write disk1s1 and
   snapshot-swap, and obliteration only targets the Data partition.

### The fix is to complete HomeKit setup (the author's call — it pairs the pod to his home)
Completing setup should stop the obliteration and give us a stable Data partition AND stable NVRAM. That is a
prerequisite for any NVRAM or Data-volume persistence experiment. Until then, only System-volume work is sound.

### Job 540 — the clean R5 redo, queued, no proxy ambiguity
Instead of writing NVRAM from the ramdisk (where a read-back in the same session only proves the in-memory
IODTNVRAM proxy changed), job 540 writes it with **iBoot's own setenv/saveenv** over irecovery:
    pwn -> gaster-reset -> send sshramdisk iBSS -> send iBEC (stop at recovery, no ramdisk)
    cmd printenv                                  <- iBoot's own view of NOR before
    cmd setenv boot-args wlan.debug.enable=1
    cmd saveenv                                   <- iBoot's nvram_save writes NOR
    cmd printenv                                  <- did it take, per iBoot itself
    cmd reboot
iBoot consumes boot-args before the kernel starts, so even though the OS will obliterate later, the kernel's
boot-args string is already set for that boot and SoundBoard logs it ~9s in. After the pod settles:
    pymobiledevice3 syslog collect boot9.logarchive
    log show --archive boot9.logarchive --info --debug --style compact > bootarchive9.txt
    grep -E 'bootargs is|nvrambuffer' bootarchive9.txt
`bootargs is wlan.debug.enable=1` -> iBoot DOES honour NVRAM boot-args and R5 flips POSITIVE.
`bootargs is` empty, with printenv having confirmed the write -> iBoot genuinely drops it, R5 negative for real.

## *** 2026-11-26 04:00 — R5 FLIPS POSITIVE. RETAIL iBOOT *DOES* HONOUR NVRAM boot-args. ***

Job 540 (19:54, verified correct: `romdfu after 56s`, gaster pwn OK, iBSS+iBEC sent, all four irecovery commands
rc=0, ended `mode=recovery`) set the variable with **iBoot's own setenv/saveenv** instead of from the ramdisk:
    cmd printenv ; cmd setenv boot-args wlan.debug.enable=1 ; cmd saveenv ; cmd printenv ; cmd reboot

In the resulting boot (bootarchive9, new pid 66, timestamps 16:00:23/16:00:25 — distinct from every earlier boot):

    SoundBoard[66:322] [com.apple.soundboard:log] bootargs is <private>

Every one of the 7 boots in bootarchive8 logged `bootargs is` with NOTHING after it. This boot logs `<private>`,
which is os_log redacting a non-empty dynamic string argument. (An absent/NULL argument renders as nothing; a
present string renders as `<private>`.) So this boot had a boot-args value and the earlier ones did not, and the
only thing that changed is job 540.

>>> CONCLUSION: `iBoot-5540.140.12` DOES pass the NVRAM `boot-args` variable to the kernel. The earlier negative
>>> was an artefact of the write method — a ramdisk `nvram` write does NOT reach NOR (or does not survive), while
>>> iBoot's own `setenv` + `saveenv` does. Every boot-arg-gated idea is BACK ON: the `wifi-fw-path` /
>>> `wifi-nvram-path` overrides, and R5.3 (`cs_enforcement_disable`, `amfi_get_out_of_my_way`, `amfi=0x80`, `-v`).
>>> This is the single most important result of the session.

Two caveats held open deliberately:
- `nvrambuffer len` is still 6216 in this boot, which is EXPECTED and not a contradiction: job 540 set only
  `boot-args`. It did not set `wifi-nvram-path` (that variable had been wiped by the obliteration), so the kernel
  used the default path. The override itself is still untested.
- The `<private>` reading is an inference from os_log redaction behaviour. It wants one independent confirmation:
  `wlan.debug.enable=1` opens the wlan driver's log-level gate (`[x8+8] >= 4` in the kernelcache), so bootarchive9
  should show MORE AppleBCMWLAN chatter than bootarchive8, and possibly `updated NVRAM path` / `updated FW path`.
  Need bootarchive9.txt moved somewhere readable to check. Until that is done, call this STRONG, not proven.

### Method note, important
`irecovery -c` does not capture iBoot's console output — `printenv`'s text goes to UART, not the job log. To see
what iBoot thinks NVRAM contains, capture the UART screenlog during the recovery-mode job.

### Lesson for the notes
The ramdisk-write confound was real and it inverted a conclusion. Any future NVRAM test must write through iBoot
(`setenv`+`saveenv` over irecovery), not through `nvram` in the ramdisk. Reading a variable back in the same
ramdisk session proves only that the in-memory IODTNVRAM proxy changed.

## 2026-11-26 04:10 — Why setup cannot complete: a teardown/network deadlock. NOT caused by our changes.

the author tried setup from several phones and from a hotspot; all reported the pod could not connect to Wi-Fi.
From `route2/setup-live.txt` (80 MB, 591515 lines, `pymobiledevice3 syslog live` during the attempts):

    SoundBoard{SetupAssistantSB}[66]: -[SASBTouchRemoteSetupManager
        disassociateNetworkAndSignoutOfAllAccountsWithCompletion:]: Signing out of iCloud
        ..._block_invoke: Signing out of iTunes Account
        ..._block_invoke: Error Signing out of iTunes Account [Error Domain=com.apple.AppleID.Error Code=-1001]
        ..._block_invoke: Disassociating WiFi        <- 6x each

The pod is in a partially-setup state, so each setup attempt first runs the TEARDOWN path
(`disassociateNetworkAndSignoutOfAllAccounts`): sign out of iCloud and iTunes, then disassociate Wi-Fi. The
sign-out needs the internet, Wi-Fi is not up, AppleID returns -1001 (network timeout), and the cleanup
disassociates Wi-Fi anyway. Closed loop — no phone or hotspot can break it. Also present and consistent:
`apsd: is WiFi associated? NO`, `locationd: WifiMgr, queryAssoc, fail`, and 444x
`wifid: WiFiManagerGetUserAutoJoinState: user auto join state 1`.

### Our Wi-Fi nvram edit is NOT the cause (checked before blaming it)
The modification is a single appended line `zzpprobe=1234` (14 bytes, 6186 -> 6200). It is an unknown key, which
normalizeNVRAM keeps (not one of its five stripped names) and the firmware ignores. The Wi-Fi symptoms in
bootarchive8 (`Init interface not found (*)` 3377x, `en0 does not exist in dynamic store`,
`is WiFi associated? NO`) are what an UNPAIRED pod with no credentials looks like, not evidence of a broken radio.
I nearly attributed this to our files on the strength of those lines; they do not support it.
Restoring the stock blobs anyway (job 541) because it is owed cleanup and removes a variable.

### Consequence for strategy — setup is parked, and that is OK
A clean fix is a full restore followed immediately by setup, which costs the System-volume plants and is not worth
tonight. We do NOT need setup to continue: iBoot `setenv`+`saveenv` works (proven by job 540), so boot-args can be
set tethered before each boot. The obliteration wipes NVRAM every boot, so each test needs one recovery-mode step
first. Setup only matters for DEMONSTRATING untethered persistence, which is the finish line, not the next step.

## 2026-11-26 04:25 — Job 542: boot-args PERSISTS in /options. wifi-nvram-path is REJECTED by iBoot setenv.

Job 542 (ramdisk, read-only, 20:22) dumped /options via `nvram -p`:

    boot-args                wlan.debug.enable=1      <- UNREDACTED, still there since job 541 at 20:13
    wifi-nvram-path          match count: 0           <- NOT PRESENT AT ALL

So:
1. `boot-args` set by iBoot `setenv`+`saveenv` persists in NOR and IS exported into the IORegistry /options node,
   and it survived the setup flow and several reboots. NVRAM persistence for this variable works.
2. `wifi-nvram-path` never made it. iBoot's `setenv` appears to accept only names from its own variable list (the
   name-pointer array near file 0x40500 in iBoot.dec: boot-args, auto-boot, bootdelay, alamo-path, rtos-path,
   rbm-path, diags-path, auto-boot-usb, reconfig-behavior, emu, root-live-fs, enable-upgrade-fallback,
   backlight-level, boot-command, com.apple.System.boot-nonce, debug-uarts, device-material, display-rotation,
   idle-off, is-tethered, darkboot, ota-breadcrumbs, boot-breadcrumbs, com.apple.System.tz0-size,
   com.apple.System.rtc-offset, pwr-path). `wifi-nvram-path` is NOT on that list.
>>> So the override did not fail because the gate was shut. The variable cannot be DELIVERED by iBoot setenv at all,
>>> so the kernel's getProperty("wifi-nvram-path") on /options could never have found it. To test the override the
>>> variable must be written from the BOOTED OS via /usr/sbin/nvram (the route that worked for `r2-gate`), since
>>> IODTNVRAM accepts arbitrary names - note `obliteration`, `oblit-begins`, `SystemAudioVolumeSaved`,
>>> `backlight-nits`, `recovery-breadcrumbs` are all non-whitelist names present in /options.
REVISION: my earlier claim that obliteration wiped `wifi-nvram-path` and `r2-gate` is probably wrong for
wifi-nvram-path - it was never stored. Obliteration remains the likely explanation for r2-gate (OS-written).
NOTE: the `oblit-begins`/`obliteration` variables are still in /options, but they are STALE values; their presence
does not prove an obliteration ran again. boot-args surviving 20:13 -> 20:22 is evidence NVRAM is no longer wiped.

## 2026-11-26 04:25 — THE OBSERVABILITY BREAKTHROUGH: launchd prints boot-args to UART, unredacted

From `diags_archive/screenlog.0` (2752 lines; read the first 800 directly, then grepped the remainder for
boot-args / boot banners / AMFI / obliteration). Note the log contains binary bytes, so **grep needs `-a`** or it
silently reports nothing.

    line 538: com.apple.xpc.launchd <Notice>: boot-args = rd=md0 debug=0x2014e -v wdt=-1 nand-enable-reformat=1 -restore serial=3

launchd logs the kernel's boot-args verbatim, with NO os_log redaction, to the serial console. That is the
authoritative readout we have been lacking all night - far better than SoundBoard's `bootargs is <private>`.

But there is exactly ONE such line in the whole capture, and it belongs to the ramdisk (`Remote boot`). The SEVEN
`Local boot` banners (lines 32, 132, 190, 2338, 2439, 2495, 2551) produce NO kernel or launchd output on UART at
all - only iBoot's own banner and hash:line markers.
>>> Reason: the ramdisk boot is verbose because WE pass it `-v` and `serial=3`. The installed OS has neither, so
>>> the installed kernel's serial console is OFF by default.
>>> THAT IS A PERFECT BINARY TEST. Set `boot-args=-v serial=3 wlan.debug.enable=1` on the NOR path and reboot:
>>>   UART fills with verbose kernel output and a launchd `boot-args = -v serial=3 wlan.debug.enable=1` line
>>>       -> PROVEN, unredacted: retail iBoot passes NVRAM boot-args to the INSTALLED kernel. Breakthrough confirmed.
>>>   UART stays quiet (iBoot banner only)
>>>       -> iBoot stores boot-args in NVRAM but does NOT hand them to the installed kernel, and SoundBoard's
>>>          `<private>` was reading NVRAM (/options), not the kernel command line. R5 would then be negative
>>>          after all, for a reason we could finally name.
Job 543 queued to run exactly this. `-v serial=3` is harmless and reversible by clearing boot-args.

### Also seen in the ramdisk boot (restore environment only - do NOT generalise to the installed OS)
- line 398: `AMFI: developer mode is force enabled on this platform`
- line 571/613: `AMFI: Launch Constraint Violation (not enforcing)`
Both are in the `-restore` ramdisk environment, which is expected to be permissive. Whether anything similar holds
on a Local boot is unknown and is exactly what job 543's verbose output would let us read.

## 2026-11-26 04:40 — CORRECTION: R5 is NEGATIVE again, and my "flips positive" call was wrong

I reported R5 POSITIVE from `SoundBoard: bootargs is <private>`. That was wrong, and the mechanism is now clear:
- `/options` holds the NVRAM VARIABLES. iBoot exports them there and userspace can read them. `nvram -p` confirmed
  `boot-args wlan.debug.enable=1` sitting in /options, unredacted, persisting across boots.
- The kernel's actual command line is the device-tree `/chosen/boot-args`, which iBoot populates only if policy
  allows. `PE_parse_boot_argn` reads THAT, not /options.
These are different things and I conflated them. SoundBoard reading a non-empty value from /options says nothing
about whether the kernel got a command line.
Evidence now all consistent with "iBoot stores and exports NVRAM boot-args but does NOT put them on the installed
kernel's command line":
  1. /options has the value (job 542).                                   2. SoundBoard reports non-empty.
  3. The wlan driver's debug gate never opened (BCMWLAN density 1.61 -> 1.91 per 10k lines, i.e. unchanged).
  4. `-v serial=3` produced ZERO kernel serial output across three Local boots (jobs 543, 544).
  5. `debug-uarts 3` (a whitelisted iBoot variable) did not open the channel either.
  6. launchd's `boot-args = ...` line appears ONLY in ramdisk boots, never in a Local boot, and is absent from
     every log archive (launchd's early lines do not persist).
STILL NOT PROVEN either way - UART is dark on Local boots regardless, so it cannot discriminate. The one clean
read left is the device tree: `pymobiledevice3 diagnostics ioregistry --plane IODeviceTree` and look for
/chosen/boot-args. The bare `ioregistry` command returns null; the plane argument has not been tried yet.

## 2026-11-26 04:40 — Job 545: AMFI cdhash enforcement CONFIRMED live. But the test could not prove what I built it for.

Job 545 planted a 4-byte-NOP-patched copy of `/usr/libexec/CrashHousekeeping` (55152 bytes, patched at offset
16384, stock preserved at .stock) and set `boot-args=cs_enforcement_disable=1 amfi_get_out_of_my_way=1 amfi=0x80`.
Test boot confirmed present in bootarchive13: `"uptime":175` at 20:38:07 => boot at 20:35:12, matching 545's
reboot at 20:35:08.
RESULT: the modified binary NEVER LAUNCHED. No CrashHousekeeping process in the test boot at all, while the stock
binary logs 27 times in earlier boots.
>>> So: trust-cached binary at any path RUNS (racoon->CrashHousekeeping, proven earlier); one-byte-modified binary
>>> is REFUSED. A clean controlled pair. AMFI validates by cdhash against the static trust cache and that
>>> enforcement is live. This also retroactively proves the dd patch DID land (the ramdisk has no `cmp`, so I could
>>> not verify it directly - but the stock binary runs reliably, so a behavioural change proves the bytes changed).
>>> DESIGN ERROR, mine: `cs_enforcement_disable` and `amfi_get_out_of_my_way` are macOS/x86-era boot-args and are
>>> NO-OPS on arm64 iOS even when passed. So "modified binary rejected" is equally consistent with "boot-args never
>>> reached the kernel" AND "boot-args arrived but those flags do nothing here". The test cannot discriminate.
>>> Do not treat 545 as evidence about boot-args. It is only evidence about AMFI enforcement.

## 2026-11-26 04:40 — NEW: the OS verifies the System volume against a manifest, and sees our .stock files
From bootarchive13, MobileSoftwareUpdate.UpdateBrainService during an OTA prepare:
    './usr/libexec/CrashHousekeeping.stock' has been added
    './usr/libexec/CrashHousekeeping.stock' did not verify and is not on the exception list.
    Error Domain=MobileSoftwareUpdateErrorDomain Code=3, MSUFullReplacementRecommened=true
    failureReason: "MSU 3 ('./usr/libexec/CrashHousekeeping.stock' has been added)"
So every `.stock` backup we have scattered on disk1s1 is detectable by a System-volume manifest check. It only
blocks OTA updates (which we do not care about), but:
- it is an integrity mechanism we did not know was there, and it is content-aware (added files, not just modified);
- future plants should keep backups OFF the System volume (keep them on the Mac, or restore from the IPSW) if we
  ever want the pod to look clean;
- it is worth checking whether this manifest check gates anything at BOOT, not just OTA. If it does, it is a
  second enforcement surface alongside AMFI.
Unrelated but noted: the same report shows `NRD 220 (Failed to update recoveryOS, not enough space for the new
partition)` - the pod cannot install a recoveryOS. Not our concern tonight.

## !!! 2026-11-26 04:50 — METHODOLOGY: the persisted log LAGS ~5+ MINUTES. Early-boot lines are missing from
## any archive collected soon after a reboot. This has silently corrupted results all evening.

Proof, same boot, two collections:
- `bootarchive13.txt` collected 20:39 — the 20:36:14 boot's early lines are ABSENT. No `bootargs is` line for it,
  and `CrashHousekeeping` in the 20:35-20:38 window: **0 hits**.
- `bootarchive14.txt` collected 20:47 — the same boot's early lines are PRESENT: `bootargs is` at 20:36:20,
  353 `kernel[` lines at 20:36, and `CrashHousekeeping` in that window: **6 hits**.
`syslog collect` pulls what logd has FLUSHED TO DISK. The most recent few minutes, including the first ~45s of a
boot, are still in memory and are simply not in the archive.
>>> RULE: for any boot-time observation, WAIT 5+ MINUTES after the reboot before `syslog collect`, and verify the
>>> boot is captured by checking for its own marker (`SoundBoard ... bootargs is`, or a `kernel[...] iBoot version:`
>>> line) BEFORE interpreting anything. An absence in a freshly collected archive means nothing.
This invalidated two conclusions tonight (see below). It is also the likely reason launchd's `boot-args = ...` line
never appeared in any archive - it is logged in the first second of boot, the worst part of the window.

## *** 2026-11-26 04:50 — JOB 545 RESULT, CORRECTED: AMFI kills the modified binary with reason CODESIGNING ***

Re-checked in the caught-up archive (bootarchive14, 20:35-20:38 window):

    osanalyticshelper: Saved type '109' report at
        /private/var/mobile/Library/Logs/CrashReporter/CrashHousekeeping-1969-12-31-160024.000.ips
    ReportCrash: com.apple.stability.crash {"exceptionCodes":"UNKNOWN_0x32 at 0x0000000100d704c4",
        "process":"CrashHousekeeping","terminationReasonExceptionCode":"0x2",
        "terminationReasonNamespace":"CODESIGNING"}

So the 4-byte-patched binary WAS exec'd and then KILLED by code-signing validation. I had reported "never
launched" from bootarchive13, which was a false negative from the collection lag. The corrected result is
stronger and gives us a precise instrument:
>>> SIGNAL FOR FUTURE TESTS: a codesign-invalid binary at a cached job's path produces a crash report with
>>> `terminationReasonNamespace: CODESIGNING`. That is a positive, unambiguous readout - far better than
>>> inferring from the absence of a process. Use it, not absence, for every enforcement test from now on.
Note the SAME crash shape appears at 20:33:03 (`UNKNOWN_0x32 at 0x0000000100c144c4`, different ASLR slide), i.e.
BEFORE job 545's plant at 20:34:17. So whatever was at /usr/libexec/CrashHousekeeping was ALREADY codesign-invalid
at 20:33. `subst-undo.sh` may not have fully restored it in an earlier session - worth checking. It does not
change the conclusion (invalid binary -> CODESIGNING kill) but it means 545 had no clean pre-state.
Still unchanged: `cs_enforcement_disable` / `amfi_get_out_of_my_way` / `amfi=0x80` are macOS/x86-era no-ops on
arm64 iOS, so 545 says NOTHING about whether boot-args reached the kernel. It only proves AMFI enforcement is live.

## 2026-11-26 04:50 — io=0x3f test (job 546) is PENDING, not negative
546 set `boot-args=io=0x3f` and rebooted at 20:44:36. I reported kernel-line counts of 196 (test window) vs 502
(previous boot) and called it negative. **That was wrong for the same reason**: bootarchive14 has no boot marker
after 20:36:20, so the 20:44:40 boot's early phase is not in it, and I compared an incomplete window against a
complete one. Re-collect at 20:52+ as bootarchive15 and only then compare, anchoring on the boot's own marker.

## 2026-11-26 05:10 — OPERATIONAL RULE (cost jobs 549 and 550): the pod must be UPRIGHT to boot the ramdisk

The pod falls back to boot ROM DFU if it is left UPSIDE DOWN. Upside-down is only how you ENTER DFU. Sequence:
    1. unplug, turn upside down, plug in  -> pod enters boot ROM DFU
    2. FLIP IT RIGHT-SIDE UP and leave it upright
    3. then let the job run
Symptom when you get this wrong: `sshrd` sends iBSS/iBEC/ramdisk/devicetree/trustcache/kernelcache, prints
`bootx sent`, and then `dropbear did not answer on 127.0.0.1:2222 within 120s`, and the job ends `mode=romdfu`
(the pod reset itself back to DFU). UART shows the Supervisor iBoot banner (iBoot-10151.120.138) and then NOTHING -
no `Entering recovery mode`, no `loaded ramdisk at ...`, just NUL bytes. That signature means "it fell back", NOT
"the ramdisk is broken".
Jobs 549 and 550 both failed this way. I misread 549 as a transient USB hiccup and requeued it without saying
anything, so 550 failed identically. the author flagged the real cause.
NOT the cause, checked: the leftover NVRAM from jobs 544/546 (`debug-uarts 3`, `boot-args io=0x3f`) is harmless -
jobs 547 and 548 both booted the ramdisk fine at 20:54 and 20:58 with both of those already set.

## 2026-11-26 05:10 — Jobs 547/548 did reveal real System-volume surprises (before 549/550 failed)
From job 548's listing with only /dev/disk1s1 mounted at /mnt1:
- `/mnt1/Library` IS a real directory (15 entries) and contains `Managed Preferences`, but **`/Library/Preferences`
  DOES NOT EXIST** on the System volume. So the standard unredaction path
  `/Library/Preferences/Logging/com.apple.system.logging.plist` is NOT plantable there - it is almost certainly an
  APFS firmlink into the Data volume, resolving only when System+Data are mounted as a unified root.
- **`/mnt1/System/Library/Caches/com.apple.xpc.launchd/mrm.plist` DOES NOT EXIST**, and neither does
  `/mnt1/mrm.plist.stock`. Same firmlink explanation is likely (`/System/Library/Caches` -> Data volume).
  >>> CONSEQUENCE: our "backup" of the service cache may not be where the notes claim, and any mrm.plist write we
  >>> did from the ramdisk may have landed on a path that resolves differently at runtime. The R3 substitution
  >>> results stand (verified behaviourally by a process actually running), but do NOT trust any
  >>> "we have a .stock backup" claim without re-verifying it. Job 551 enumerates what actually survives.
- `/mnt1/Library/Application Support/BTServer/pincode_defaults.db` is also gone, which is why the old
  `sysvol-mount.sh` now exits 1 and aborts jobs. Use `sysvol-mount2.sh` instead (mounts, reports, always exit 0).
- **`/mnt1/System/Library/Preferences/Logging` DOES exist** on the System volume - so per-SUBSYSTEM unredaction
  (`Subsystems/<subsystem>.plist` with DEFAULT-OPTIONS -> Enable-Private-Data) is the plantable route. Job 551
  plants it for `com.apple.soundboard` (logs `bootargs is <private>`) and `com.apple.cltm` (thermalmonitord's
  `retrieved current device boot-args: <private>`).
- REMINDER I violated again: the ramdisk root is READ-ONLY, so here-documents fail with
  `cannot create temp file for here document`. Use `printf` to write files. Also still missing on the ramdisk:
  `cmp`, `tr`, `strings`, `readlink`, `basename`, `od`, `df`.

## ***** 2026-11-26 05:30 — BREAKTHROUGH: retail NOR iBoot EXECUTES NVRAM BOOT-COMMANDS UNTETHERED *****

Job 554 set `one-time-boot-command=recover` via iBoot setenv+saveenv, then rebooted. UART, from
`diags_archive/screenlog.0` lines 129-152:

    :: iBootStage2 for b238a, Copyright 2007-2019, Apple Inc.
    ::   Local boot, Board 0x38 (b238aap)/Rev 0xa
    ::   BUILD_TAG: iBoot-5540.140.12
    ::   BUILD_STYLE: RELEASE
    Delaying boot for 0 seconds. Hit enter to break into the command prompt...
    Entering recovery mode, starting command prompt

**Local boot. iBoot-5540.140.12. The pod's OWN NOR iBoot** - not our 10151 iBEC - read
`one-time-boot-command` out of NVRAM and changed its control flow, with no host attached.
>>> So the NVRAM -> iBOOT channel is OPEN, and it is CONTROL FLOW, not data. Pre-kernel, pre-AMFI.
>>> The earlier boot-args negative was specific to iBoot forwarding boot-args to the KERNEL's command line.
>>> iBoot itself acts on NVRAM perfectly well. Those are two different questions and I had conflated them.
`one-time-boot-command` self-clears, so this is also a safe, repeatable probe.

### iBoot's two command tables (from iBoot.dec, base 0x830000000)
CONSOLE commands, table ~0x40440:
    bootx(0x1998) memboot(0x1c18) go(0x21c8) reboot/reset(0x3398) bgcolor(0x33cc) setpicture(0x3408)
    devicetree(0x37dc) firmware(0x36d8) getenv(0x2274c) saveenv(0x37e0) setenv(0x227bc) setenvnp(0x228c4)
    ramdisk(0x37e4) rsepfirmware(0x3020c)
BOOT commands, table ~0x47000 - these are what boot-command / one-time-boot-command dispatch into:
    upgrade(0x3d08) recover(0x4284) recover-once(0x45b8) alamo(0x171c) rtos(0x1840) rbm(0x1868)
    diags(0x1890) fsboot(0x2098)
Each of alamo/rtos/rbm/diags has a matching NVRAM path variable (alamo-path, rtos-path, rbm-path, diags-path),
all of which are on iBoot's whitelist, so `setenv` will accept them (unlike `wifi-nvram-path`).

### THE ATTACK SURFACE: iBoot loads and PARSES an attacker-named file BEFORE authenticating it
`diags` (0x1890) loads 4CC 'diag' and calls the generic path-boot routine 0x1744 with env var name
"diags-path" (string 0x3e081). 0x1744 decodes as:

    path = env_get("diags-path")            ; 0x21ecc, NULL -> error line 0x16b
    snprintf(buf, "/boot%s", path)          ; format string 0x3e0a7 = '/boot%s'
    load_and_boot(buf, 0x810000000, 0xbe00000, &flags, &tag, 1, 0, 0)   ; 0x1209c
                                            ; error -> string 0x3e0af '/boot', line 0x188

and 0x1209c decodes as:

    read file into memory at 0x800000000    ; 0x2301c  <-- LOAD HAPPENS FIRST
    if (size > max 0xbe00000) -> error
    hdr = parse(0x800000000, ...)           ; 0x12050  <-- PARSE BEFORE AUTH
    result = validate_and_boot(hdr, tag, 1, 0, loadaddr, max, flags)   ; 0x11ecc
    cleanup 0x121d8 ; on failure memset(0x800000000, 0x10000000) at 0x121a4

Validation-related strings in iBoot: `IMG4` (0x3ed5c), **`/boot/apticket.der`** (0x3ebe2),
`/boot/boot/apticket.der` (0x3ec09), `verify boot manifest hash` (0x3eb0a), `boot-manifest-hash` (0x3f002),
`system-trusted` (0x3ef9d), `chosen/manifest-properties` (0x3ed9e), `Trustcache` (0x3e1fb).

>>> PUT TOGETHER: we can make the retail NOR iBoot, untethered, read a file from a path WE choose and parse it
>>> with its IMG4/ASN.1 code BEFORE any signature check. That is a complete pre-authentication attack surface
>>> reachable with no host. This is the most promising thing found in the whole project so far.
>>> Next: (1) locate the `/boot` namespace (job 555 - which volume holds apticket.der);
>>>       (2) point diags-path at a garbage file and read iBoot's UART errors to map how far it gets;
>>>       (3) audit 0x12050 (parse) and 0x11ecc (validate) offline for a memory-safety defect.
>>> UART is a WORKING channel for this, unlike the installed kernel's serial - iBoot prints freely.

### NEAR MISS, recorded so it is not repeated
My first version of findboot.sh looped `for n in 1 2 3 4 5 6` mounting every /dev/disk1s$n. That would have
mounted **/dev/disk1s2, the encrypted Data volume, which hangs the ramdisk ssh hard and costs a runner restart** -
an explicit standing rule in these notes. Caught before running. The loop now skips n=2.

## ***** 2026-11-26 06:10 — THE FSBOOT CHAIN, fully mapped. We supply ALL THREE files iBoot loads. *****

Everything below is from the pod's own iBoot (iBoot.dec, base 0x830000000) plus live `getenv` at the NOR iBoot
recovery prompt and ramdisk inspection of /dev/disk1s1.

### iBoot has TWO NVRAM namespaces
`nvram -p` from the ramdisk reads the IORegistry /options node and showed: backlight-nits, boot-breadcrumbs,
obliteration, SystemAudioVolumeSaved, backlight-level, debug-uarts, recovery-breadcrumbs, boot-args, auto-boot,
oblit-begins. It did NOT show boot-command, and `nvram boot-command` reports
"(iokit/common) data was not found" - yet iBoot's own `getenv boot-command` returns `fsboot`.
The reason: a 4-entry pointer array at file 0x404f8..0x40510 lists **auto-boot, boot-args, debug-uarts, pwr-path**
- exactly the iBoot-owned variables that appear in /options. That array is iBoot's EXPORT-TO-KERNEL list.
>>> So iBoot keeps boot-command, one-time-boot-command, diags-path, boot-path, boot-device, boot-partition,
>>> dt-path, sepfw-path PRIVATE. `nvram`/`nvram -d` from the OS or ramdisk cannot read or delete them.
>>> The ONLY reader/writer for those is `getenv`/`setenv` at an iBoot prompt.
>>> This also retro-explains job 538: `wifi-nvram-path` did not "fail to persist", it is simply never exported.
CORRECTION to earlier notes: the whitelist I was reasoning from (alamo-path, rtos-path, ... pwr-path) came from
ProtoPod's DEVELOPMENT iBoot-4076, NOT from 5540. Do not reuse it for this pod.

### Live values at the NOR iBoot prompt (authoritative for the private namespace)
    boot-device      asp_nand
    boot-partition   0
    dt-path          /usr/standalone/firmware/devicetree.img4
    sepfw-path       /usr/standalone/firmware/sep-firmware.img4
    boot-path        /System/Library/Caches/com.apple.kernelcaches/kernelcache
    auto-boot        true
    boot-command     fsboot        (we set this; it persists across many boots)
`getenv` on a SET variable prints the value; on an UNSET variable irecovery reports `getenv: Broken pipe`.
`printenv` is not a command in this build. `fsboot` typed at the console prompt does nothing - it is only
reachable via boot-command dispatch, not as a console command.

### fsboot (0x2098) decoded, and WHY it was failing
    buf = alloc (0x2374)
    p   = env_get("boot-path")                 ; 0x3e174, NULL -> err 0x215c
    gate1 = 0x1b5c   -> env_get("boot-device") then env_get("boot-partition")   ; opens the boot filesystem
    gate2 = 0x1ed8   -> env_get("dt-path") then env_get("sepfw-path"),
                        snprintf("/boot%s"), load each                          ; fsboot-only
    snprintf(buf, "/boot%s", p)
    load_image(buf, 'krnl')                    ; 0xb7a8   <-- our kernelcache would be read HERE, LAST
All four gate variables ARE set, so the gates are not the blocker. The blocker is the FILES:
    /mnt1/usr/standalone/firmware/            EXISTS (subdirs STDP2700, aeac, peppy)
    /mnt1/usr/standalone/firmware/devicetree.img4     **MISSING**
    /mnt1/usr/standalone/firmware/sep-firmware.img4   **MISSING**
    /mnt1/System/Library/Caches/com.apple.kernelcaches/  EXISTS, was EMPTY
So gate2 fails on the missing device tree and fsboot bails BEFORE ever opening the kernelcache. That is why the
planted garbage kernelcache produced no new UART output.

### `/boot` IS THE SYSTEM VOLUME ROOT
dt-path/sepfw-path/boot-path are all real System-volume paths, and iBoot prefixes them with "/boot" via format
string 0x3e0a7 ('/boot%s'). boot-device=asp_nand, boot-partition=0. There is no /boot directory on disk1s1, so
iBoot mounts the boot volume AT /boot in its own namespace.
>>> CONSEQUENCE: all three files iBoot loads at boot live on /dev/disk1s1, which we mount read-write from the
>>> ramdisk in every single job. We supply the DEVICE TREE, the SEP FIRMWARE and the KERNELCACHE.

### Confirmed plant survival
The 4111-byte garbage kernelcache (30 82 0f fe "TESTPROBE01") planted in job 560 was still present and intact in
job 561 after a snapswap and several boots. So System-volume plants in this directory DO persist - unlike the
files that vanished earlier tonight (CrashHousekeeping, the .stock backups, alt-nv.txt), which remains unexplained.

### Job 562 (queued): the actual pre-auth parser test
Plant ASN.1-headed garbage at devicetree.img4 and sep-firmware.img4 (loaded FIRST, before the kernelcache, so no
valid signature is needed to reach the parser), set boot-command=fsboot, reboot, read UART.
A NEW error site = iBoot parsed our bytes pre-authentication, untethered. Same old 7ab90c923dae682:949 = the model
is still wrong and 0x1ed8 needs re-reading.

## R8 — iBoot's TWO env tables found. The setenv wall is FOUR NAMES. (CODE-PROVEN)

Triggered by Levin's iBoot chapter noting RELEASE builds carry two whitelist
tables. Found both by scanning iBoot.dec for runs of >=3 consecutive qwords
pointing at C strings (`ptrarr.py`). Supersedes the earlier claim that
boot-command et al are "iBoot-private, only settable at an iBoot prompt" —
that was reasoned from ProtoPod's DEVELOPMENT iBoot-4076 and is WRONG.

### Table 1 — file 0x404f8, 4 entries. THE CONSOLE setenv GATE.
    auto-boot, boot-args, debug-uarts, pwr-path

Walker at **0x2a54**, loop bound `cmp x20,#0x20` (4*8). Returns 0 if the name
is in the list, 1 if it ran off the end. Takes a flag in w1:

    0x2a64  cbz w1, #0x2a90   -> 0x2a90: mov w0,#0 ; return 0   (list NOT consulted)

Callers:
  * getenv (0x2274c) calls it at 0x22784 with **w1=0** -> returns 0 always ->
    the list is bypassed. getenv therefore works for ANY set variable and
    returns -1 only when the lookup at 0x21e6c fails. THAT is the
    `getenv: Broken pipe` case: it means UNSET, nothing more.
  * setenv (0x227bc) calls it at 0x22808 with **w1=1** -> list IS enforced.
    `tbz w0,#0, 0x22830` proceeds only on a match; otherwise `mov w0,#-1`.

Both handlers additionally call **0x22724**, a 17-byte strncmp against
`"com.apple.System."` (str 0x3f9dd), and REJECT on match (`tbnz w0,#0`).
That is what shields com.apple.System.boot-nonce from the console.

**CONSEQUENCE: `setenv` at the NOR iBoot prompt can write exactly four names,
ever. `setenv boot-command ...` and `setenv diags-path ...` have NEVER worked.**
The `fsboot` that `getenv boot-command` echoes back is the HARDCODED DEFAULT,
not our 21:41 write. The one "success" at 21:41 was an illusion: the default
was already fsboot, so setting it to fsboot was indistinguishable from a no-op.
The four later "failures" were not a regression, not NVRAM exhaustion, and not
a full env partition — the gate rejected all five attempts identically.

### Table 2 — file 0x40520, 20 entries. An ATTRIBUTE list, not a gate.
    auto-boot, backlight-level, boot-command, com.apple.System.boot-nonce,
    ramrod-kickstart-aces, debug-uarts, device-material, display-rotation,
    display-vsh-comp, idle-off, is-tethered, darkboot, ota-breadcrumbs,
    boot-breadcrumbs, recovery-breadcrumbs, com.apple.System.tz0-size,
    com.apple.System.rtc-offset, pwr-path, upgrade-retry,
    upgrade-fallback-boot-command

Walker at **0x2aa4**, bound `cmp x20,#0xa0` (20*8), same 0/1 polarity. Neither
call site uses it as permission — both only set a flag:
  * 0x22168: `cmp w0,#0` / `csel w19,w8,w19,ne` where `w8 = w19|2`
    -> NOT-in-list sets bit 1.
  * 0x22694: `csinc w2,w8,wzr,ne` with w8=#3 -> passes mode 1 (in list) or
    3 (not) to the print helper 0x2213c, which getenv tail-calls with mode 0.
PROVISIONAL reading: "NVRAM-backed / persistable", used to annotate a dump.
Do not over-claim — one-time-boot-command is absent yet demonstrably
self-clears, so this is not the complete persistable set.

### Path variables are in NO table
diags-path (0x3e081), boot-path (0x3e174), sepfw-path (0x3e150),
dt-path (0x3e148), boot-device (0x3e128), boot-partition (0x3e139),
one-time-boot-command (0x3e18d): searched for pointers to each string's VA
across the whole image — **zero holders each**. ADR-referenced only from
their own code sites. Not console-settable and not in the attribute list.

### R8.1 — the `diags` route is CLOSED (no default path)
0x1890 (`diags` boot-command) loads `w0 = 0x6469'6167` = 'diag' 4CC, then
`adr x1, #0x3e081` = "diags-path", calls 0x1680 -> 0x1744.
0x1744: `mov x19,x1` ; `bl 0x21ecc` (env_get) ; **`cbz x0, #0x17f0` = bail.**
There is NO hardcoded fallback and no default string. diags-path is unset
(proven: `getenv diags-path` -> Broken pipe) and cannot be set. So
boot-command=diags can never reach 0x1209c.
This kills the queued "shortest route to the pre-auth parser" plan outright.
Caught offline, before spending pod cycles on it.

Contrast: `getenv boot-path` DOES return a value, so boot-path has a default
that env_get supplies while diags-path has none.

### What this leaves
Reachable, actually-settable levers are now: `boot-args`, `debug-uarts`,
`auto-boot`, `pwr-path` from the console; and whatever the ramdisk can write
into NVRAM that iBoot reads (the 949-marker evidence says boot-command is read
from NVRAM, which is a DIFFERENT write path from the console gate and is
unaffected by it). The *-path variables are fixed at their defaults, which is
survivable because /boot is the System volume root and we already have write
access to every file fsboot loads.

Corrected next experiment: stop planting garbage at the FIRST gate. fsboot
loads sepfw first (0x3003c) and ours dies 949 before the chain ever reaches
'krnl'. Restore the REAL sep-firmware.img4 and devicetree.img4 from 17M61,
plant malformed input ONLY at the kernelcache path, and the chain should
advance past 949 to the 'krnl' load at 0xb7a8 — the parser we actually want.

## R9 — THE BOOT CHAIN IS NOT ON ANY MOUNTED VOLUME (job 565). Supersedes "/boot = System volume root".

Job 565 mounted /dev/disk1s3 read-only and mapped it. Result:

  * /mnt3/Firmware is **EMPTY**. Bounded walk returns only the directory itself.
  * find over all of disk1s3 (maxdepth 5) for *.img4 / kernelcache* / *apticket* /
    *.im4p returns **NOTHING**.
  * disk1s3 holds only Hardware/Battery, Controller/{MSUEarlyBootTask,NeRD},
    db/UpdateMetrics, MobileAsset, lastOTA, restore.log, softwareupdate scratch.
  * On disk1s1, /usr/standalone/firmware/ contains the REAL peripheral firmware
    dirs (aeac, STDP2700, peppy) -- and the ONLY sep-firmware.img4 and
    devicetree.img4 present are **the garbage we planted in job ~556**.
    Likewise the only kernelcache is **our garbage** from the plant job.
  * Job 555 already established: no apticket.der on disk1s1 or disk1s3, at the
    root or under /boot.

So: no kernelcache, no devicetree, no SEP firmware and no APTicket exist on
disk1s1, s2 or s3 -- yet the pod cold-boots audioOS reliably every time.

### Conclusion: iBoot boots from a RAW ASP NAND BOOT PARTITION that the OS never mounts.
`boot-device = asp_nand` and `boot-partition = 0` are not decoration. They name a
raw block device and a partition INDEX. `boot-path` is then a path within a
filesystem on THAT partition, which iBoot prefixes with the '/boot%s' format
(0x3e0a7). That filesystem is not disk1s1/s2/s3.

### This retroactively explains EVERY null result of the session
  * The kernelcache directory on the System volume was empty because the booting
    kernel was never there.
  * Every file we planted (kernelcache, devicetree.img4, sep-firmware.img4) is
    INERT. iBoot never reads those paths. That is why nothing we planted ever
    changed boot behaviour, and why the pod kept booting normally with
    deliberately malformed "boot images" sitting on the System volume.
  * The MSU manifest verification noticing our added files is consistent: that
    check is an OS-level manifest audit of the System volume, unrelated to boot.
  * Nothing was being "ignored" and no signature check was silently swallowing
    our input. We were writing to the wrong storage device.

### Corrections this forces
  * "/boot = the System volume root" (earlier section): **WRONG**. It was a
    deduction from dt-path/sepfw-path/boot-path looking like real disk1s1 paths.
    They are real paths, but on the boot partition's filesystem, not disk1s1.
  * "we can write all three files fsboot loads": **WRONG** for the same reason.
    We can write files at those pathnames on disk1s1; iBoot reads neither.
  * Any claim resting on planted-file experiments (the inert plants) is void.
    This includes the reasoning that the 949 SEP-firmware marker was caused by
    our garbage sep-firmware.img4 -- 949 predates and is independent of it.

### Open and now correctly posed
Where is the ASP NAND boot partition, and can the ramdisk reach it? The ramdisk
sees only /dev/disk1, disk1s1, disk1s2, disk1s3 -- notably **no disk0**. Either
the boot partition is not exposed as a block device in the ramdisk, or it needs
ASP-level access. Job 566 enumerates every /dev block node, ioreg storage/ASP
nodes, partition maps, and reads raw first-sectors looking for an IMG4 (30 82)
signature. STRICTLY read-only; no ASP FORMAT, ever.

If the boot chain lives on a raw partition that the ramdisk CAN write, that is
the untethered path, and the blocker tonight was never signature enforcement.

## R10 — FOUND THE REAL BOOT STORAGE: raw IMG4 firmware partitions (jobs 566/567)

### The device list was incomplete all session
findboot.sh (job 555) reported only /dev/disk1, disk1s1, disk1s2, disk1s3.
Job 566 listed /dev directly: there are EIGHT block devices --
**disk0, disk0s1, disk1, disk1s1, disk1s2, disk1s3, disk2, disk3, disk4**
(plus matching rdisk* character nodes). disk0, disk0s1, disk2, disk3 and disk4
had never been read. Every "the boot chain isn't anywhere" conclusion earlier
tonight rests on a device list that silently omitted five devices.

### Job 567: raw reads, offset 0
    /dev/disk2  30 83 0a a5 e0 16 04 "IMG4" 30 83 0a 92 da 16 04 "IM4P" 16 04 "ibot" 16 11 "iB..."
    /dev/disk3  30 83 02 b9 20 16 04 "IMG4" 30 83 02 a6 1a 16 04 "IM4P" 16 04 "illb" 16 11 "iB..."
    /dev/disk0, disk0s1 : high-entropy, NO fs magic at 0 or 0x400
    /dev/disk4 : reads empty

**disk2 = iBoot ('ibot'), disk3 = LLB ('illb'), stored as bare IMG4 at byte 0 of
plain writable block devices.** This is the signed boot chain in the flesh. It
matches the binary: format 0x3ed66 `image %p: bdev %p type %c%c%c%c offset
0x%llx len 0x%x` -- images are addressed by 4CC at RAW OFFSETS on a bdev, not
by filename. bdev name strings present: asp_nand (0x3ed1e), asp_llb (0x3ed2d),
asp_effaceable (0x3ed35), asp_fw (0x3e1a6), nand_syscfg (0x3e1ad).

### How iBoot names the boot bdev  (gate 0x1b5c, decoded)
    0x1b8c  adr x0,#0x3e128 "boot-device"     -> env_get (0x21ecc); NULL -> bail 0x1be8
    0x1ba0  adr x0,#0x3e139 "boot-partition"  -> env_get_int (0x21ee8)
    0x1bb0  and w8,w0,#0xff
    0x1bb4  add w8,w8,#0x61        <-- partition NUMBER becomes a LETTER ('a'+n)
    0x1bb8  adr x4,#0x3e134 = "%s%c"
    0x1bc0  stp x19,x8,[sp]
So boot-device=asp_nand + boot-partition=0 -> bdev **"asp_nanda"**, and
`/boot%s` (0x3e0a7) prefixes boot-path onto THAT filesystem.
=> fsboot's `/boot/System/Library/Caches/com.apple.kernelcaches/kernelcache`
   was never a disk1s1 path. Another reason every plant was inert.

### load_bank_partitions (0x27490..0x275ec) -- the partition table format
16-byte entries, table starts at buffer offset 0x20:
    [0]    type byte (0x7f = end marker)
    [1]    checksum (computed by 0x2797c; mismatch -> "checksum failure" 0x3fafc)
    [2:4]  length in 16-BYTE UNITS (used as len<<4; 0 or OOB -> "partition len
           out of range" 0x3fb24)
    [4:16] 12-byte name, strncmp n=0xc via 0x265c8
Name constants in that cluster: 'APL,OSXPani'(0x3fb56, the panic partition --
what this function hunts), 'iBootIm'(0x3fb62), **'EFI PART'(0x3fb6a = GPT
header magic, used at 0x29328)**. So iBoot can parse a GPT, consistent with
boot-partition being an index.

### Why this is the untethered lever
The boot chain is raw IMG4 on block devices the ramdisk can WRITE. Each stage is
authenticated by the previous one (BootROM->LLB->iBoot), so an unsigned image
there should fail to DFU rather than execute -- but DFU is fully recoverable via
checkm8 on this A8, so the experiment is safe to run on the bench pod.
NOT YET ATTEMPTED. Writing disk2/disk3 is the first genuinely destructive step
of the project; get explicit go-ahead and save a full read-back of both devices
BEFORE any write.

### Tooling discipline (cost us 2 jobs tonight)
`ioreg -l -w0` (job 566) and `tr` (job 567, not present) each killed dropbear
mid-script -- 5th and 6th SSH deaths. Rules now: cheapest/highest-value commands
FIRST so a crash can't take the payload; no bare `ioreg -l`; no find over a whole
volume; no ls -lR; absent on ramdisk: cmp, tr, strings, readlink, basename, od,
df, sort, uniq. hexdump IS present.

## R11 — firmware partitions fully parsed; APTicket extracted; kernelcache still unlocated

Pulled /dev/disk2 (4194304 B) and /dev/disk3 (1036288 B) off the pod with
`pod-get` (it runs `cat REMOTE` over ssh, so it reads device nodes directly).
Saved as runner/files/fw-disk2-firmware.bin, fw-disk3-llb.bin.
md5 <MD5_DISK2> / <MD5_DISK3>.
**These are a restorable backup of the stock signed boot chain.** disk4
(PanicLog, 1 MB) read back 0 bytes -- genuinely blank.

### disk2 = "Apple Firmware Media" = bdev asp_fw. 815 KB of 4 MB used.
    0x00000  IMG4/IM4P 'ibot'  697829 B  "iBoot-5540.140.12"  <- the binary we disassemble
    0xaa5e5  IMG4/IM4P 'dtre'  ~100 KB   B238aAP / AudioAccessory1,1
    0xc6197  IMG4/IM4P 'dtre'  ~23 KB    version "2661.3.4", payload LZFSE ('bvx2')
    0xcbc34..0x400000 : ALL ZERO (3.36 MB unused)
(The "50-byte image 2" in my first parse was a bad DER length read; it is the
LZFSE-compressed devicetree.)

### disk3 = "Apple LLB Media" = bdev asp_llb. 205 KB of 1012 KB used.
    0x00000  IMG4/IM4P 'illb'  "iBoot-5540.140.12"
    0x33615.. : ALL ZERO (826 KB unused)

### bdev <-> /dev mapping now complete
    asp_nand       -> disk0 (16 GB, GUID_partition_scheme), disk0s1 = Partition ID 1 = APFS container
    asp_fw         -> disk2 (Apple Firmware Media)
    asp_llb        -> disk3 (Apple LLB Media)
    (paniclog)     -> disk4 (Apple PanicLog Media; matches 'APL,OSXPani')
    asp_effaceable, nand_syscfg : NOT exposed as IOMedia
APFS volumes: disk1s1 System@1, disk1s2 Data@2, disk1s3 **Update@3** (not Firmware).

### APTicket EXTRACTED  (fw/apticket-17M61.im4m, 4818 B, from img0 IM4M @0xa92ee)
Manifest covers 20 image types:
    snon srvn dtre ftap ftsp ibec ibot ibss illb krnl
    rdsk rdtr rfta rfts rkrn rosi rsep rtsc sepi trst
This is the pod's personalized manifest for the installed 17M61, including a
**krnl digest** and **snon (SEP nonce)** -- directly relevant to the
atera1n/Blackbird untethered route (R-research).

### Corrected iBoot env DEFAULTS (global scan of env_set_default calls to 0x2213c)
    boot-device        = asp_nand
    boot-partition     = **1**   (NOT 0 -- my earlier note was wrong; 1 matches
                                  disk0s1 being GPT Partition ID 1)
    auto-boot          = false
    idle-off           = false
    upgrade-retry      = 0
    recovery-boot-args = **arp0=file:///boot/OS.dmg**
So /boot is a namespace holding an OS.dmg, addressed as a URL.

### Negative: iBoot cannot be asked to dump its image list
The image enumerator (0x9ef8, format 0x3ed66 `image %p: bdev %p type %c%c%c%c
offset 0x%llx len 0x%x`) is reached only by the thunk at 0x12048, and **no
pointer to 0x830012048 exists anywhere in the image** -- it is in no command
table. Image lookup by 4CC is the thunk at 0x1204c -> 0x93ac (called from the
loader at 0x122c8). The list itself is built by the scanner 0x9120 (called from
0x11e50) which reads a **512-byte block** from a bdev and parses up to 31
entries. Console command table (stride 0x28 from 0x40440) contains no image cmd.

### STILL UNRESOLVED: where the kernelcache comes from
Ruled out, with evidence:
  * System volume: job 571 -- only kernelcache present is OUR 4111-byte garbage;
    no PrelinkedKernels, no System/Library/Kernels, /private/preboot empty;
    only files >3 MB are dyld shared caches.
  * The boot snapshot: job 560 deleted the original
    com.apple.os.update-<MANIFEST_HASH_1> and rebuilt it
    from the live volume; the pod has cold-booted cleanly a dozen times since.
  * Update volume Firmware/: empty (job 565).
  * disk2 / disk3: fully parsed above, no krnl.
Yet the manifest carries a krnl digest and the breadcrumbs show
`3000c(726b726e)` = an image load of type 'krnl'.
Next: job 572 reads the FRESH breadcrumb trail (cleared 22:26) after one clean
normal boot, to see which images iBoot actually loads and in what order.

## R12 — CLEAN 13.4.8 RESTORE (23:38). Baseline log corrections. RETRACTIONS.

Pod fully restored to 13.4.8/17M61 and set up. Full UART capture of restore+setup
saved by the author (clean13.4.8restore.screenlog.0, 12334 lines). Use as THE baseline.

### Why the restore was needed (own this)
Job 580: on disk1s1 **/sbin, /bin, /usr/sbin, /usr/bin all had 0 entries**;
/usr/lib had 10; no launchd, dyld, libSystem or sh. /System/Library/LaunchDaemons
(269) and Frameworks (153) were intact. The snapshot had the same holes.
Kernel panic (from the pulled paniclog, disk4):
    panic(cpu 0 caller 0xfffffff02542dec8):
      "Process 1 exec of /sbin/launchd failed, errno 2"     (ENOENT)
    OS version: Not set yet   secure boot?: YES
Sequence: something deleted the binaries from the LIVE volume between 20:34 and
21:19 (still unexplained). APFS snapshots share blocks, so the ORIGINAL sealed
snapshot still held the only copies and the pod kept booting from it. Then job
560's snapswap.sh deleted that snapshot and recreated it from the live volume,
destroying the last copy. **Deleting the only snapshot on a volume known to be
losing files is a destructive op and needed a backup first.** Everything after
22:00 (empty kernelcache dir, the disk0/disk2/disk3 hunt) was investigating
self-inflicted damage.

### RETRACTION 1 — the `%llx:%d` UART markers are FILE-HASH:LINE, not error codes
The baseline log shows `7ab90c923dae682:514`, `:479`, `:1043` etc. from the SAME
file hash as the `7ab90c923dae682:949` we chased all session. Format 0x3e05a
`%llx:%d` = <source-file hash>:<line number> -- ordinary log/assert sites.
**So "949 = SEP firmware load failed", "969 = boot-ramdisk failed", "916 = early
bail" are WRONG and withdrawn.** The whole error-site decode table built on them
is void. 949 is just line 949 of that file.

### RETRACTION 2 — iBoot DOES print its image list on every Local boot
I claimed it was unreachable because no pointer to the 0x12048 thunk exists.
Baseline log, normal boot:
    image <ptr>: bdev <ptr> type ibot offset 0x0      len 0xaa5e5
    image <ptr>: bdev <ptr> type dtre offset 0xaa5e5  len 0x18738
(format 0x3ed66). Independently confirms our measurements: ibot 0xaa5e5 =
697,829 B and dtre 0x18738 = 100,152 B -- exactly the sizes we derived, and
exactly the size of the devicetree IMG4 we rebuilt byte-identically.
Only TWO entries are listed, though disk2 holds a third image (LZFSE dtre at
0xc6197) -- so the bank list is not simply "every IMG4 present".

### Baseline facts from the clean log
  * Banner: "Local boot, Board 0x38 (b238aap)/Rev 0xa", iBoot-5540.140.12 RELEASE,
    IBFL:1D in normal boot; the sshrd/ra1nsn0w boot shows "Remote boot" IBFL:1C.
  * `secure boot?: YES`.
  * Darwin Image4 Validator 2.2.0 (AppleImage4-61.60.4~3419) runs in-kernel.
  * Darwin Bootstrapper 7.0.0 (libxpc_executables-1738.140.1~27/launchd) = PID 1
    starting, i.e. a healthy boot.
  * Restore path used ra1nsn0w ("Entering ra1nsn0w mode, starting command prompt").

### What survived the night and is still good
  * setenv gate = 4 names (0x404f8), code-proven at 0x2a54; getenv ungated (w1=0).
  * Storage map; disk2/disk3 backed up (md5 <MD5_DISK2_SHORT>/<MD5_DISK3_SHORT>).
  * APTicket extracted (apticket-17M61.im4m) + IM4R/BNCN <BNCN_REDACTED>.
  * **Validated IMG4 builder** (reproduces stock iBoot AND stock devicetree
    byte-for-byte). Built kernelcache/sep/dtre/trustcache IMG4s with it.
  * fsboot loads FOUR files (defaults at 0x38c0): boot-path kernelcache,
    dt-path devicetree.img4, sepfw-path sep-firmware.img4,
    tc-path /usr/standalone/firmware/FUD/StaticTrustCache.img4
  * Snapshot resolution order: NVRAM root-live-fs != 0 -> LIVE volume; else
    apfs_root_to_xid (apfs_superblock_t @0x3C8); else snapshot named
    com.apple.os.update-<40 hex of boot-manifest-hash>.
  * bdev = boot-device + ('a'+boot-partition) = **asp_nandb** (boot-partition=1).

## R13 — THE PROOF: a saved APTicket + public payloads == Apple's exact personalised boot chain

Job 582 pulled the freshly-restored disk2 and all five of Apple's just-written
personalised boot files. Offline, the APTicket (IM4M) was extracted from the
restored disk2 (4818 B, md5 <MD5_APTICKET>) and each component
rebuilt as IMG4 { "IMG4", IM4P, [0] IM4M } -- **no IM4R** (Apple omits it on
filesystem images; that is the 37-byte delta we saw earlier).

    COMPONENT              OURS       APPLE'S    BYTE-IDENTICAL
    devicetree           100,115      100,115    YES
    kernelcache       12,909,820   12,909,820    YES
    sep-firmware       1,618,875    1,618,875    YES
    StaticTrustCache      17,595       17,595    YES

Inputs used: the PUBLIC stock IPSW/OTA payloads (kernelcache.release.b238,
DeviceTree.b238aap.im4p, sep-firmware.b238a.RELEASE.im4p,
038-50758-064.dmg.trustcache) and the device's own APTicket. Nothing else --
no Apple server, no secret.

**=> A saved blob is a complete and sufficient recipe to reconstruct bootable,
signed, per-device firmware. Demonstrated on four independent components by
exact md5 match, not by argument.** This is the concrete answer to "prove it is
worth saving blobs".

Note the 37-byte rule: firmware-partition images (disk2/disk3) DO carry
[1] IM4R with BNCN; filesystem images (kernelcache, devicetree, sep-firmware,
StaticTrustCache) do NOT. Build accordingly.

## R13.1 — HARD NEGATIVE: iBoot does NOT honour NVRAM `boot-command` (controlled test)

Job 583: on a clean restored pod, `boot-command` and
`upgrade-fallback-boot-command` did not exist at all (iBoot uses its hardcoded
fsboot default). Set from the ramdisk: upgrade-fallback-boot-command=fsboot,
then boot-command=upgrade. Both persisted in /options. Cold booted.

The UART marker sequence of that cold boot is **IDENTICAL, line for line**, to
the final Local boot in the clean-restore baseline log:
    1766514c6672593:348 / 3974bfd3d441da3:1045 / "Delaying boot for 0 seconds"
    / dce7b01f6ef60a3:347 / :389 / a60aa294185a059:313
    / e51893b627f0e6e:1228 x2 / dce7b01f6ef60a3:1043 / 7ab90c923dae682:479
    / 8d3ff3cd3759614:366 x2 / :378 x2 / 6476b5993bf0843:102
No Update-volume mount, no /boot/kernelcache lookup, no fallback message.

**=> NVRAM boot-command is inert on iBoot-5540.140.12 RELEASE. The `upgrade` and
`recover` targets are NOT reachable from NVRAM on a production unit.**
This supersedes and disproves the earlier "NOR iBoot executes NVRAM
boot-commands untethered" claim (which had rested on the 949 marker, itself
since retracted as a file:line log point).
CONSEQUENCE: fsboot on the FIRST volume (System) is the only path iBoot takes.
Any APFS pre-auth probing must target disk1s1, where failure = non-booting pod
= full restore (~10 min, now a rehearsed cost).
OWED: delete boot-command / upgrade-fallback-boot-command (harmless but untidy).

## R13.2 — APFS pre-auth surface IS reachable: integrity is unkeyed Fletcher-64
iBoot's object integrity check: 0x1636c -> 0x16290 -> 0x162c8.
0x162c8 is plain Fletcher-64 (`tst x1,#3` alignment, `lsr x10,x1,#2` word count,
`lsr x8,x2,#0x20` / `and x9,x2,#0xffffffff` dual 32-bit accumulators), seed 0,
covering the object from +8. **Unkeyed. No secret.** Error paths pass line
numbers 0x38/0x3e to the %llx:%d logger (further confirming R12's retraction).

=> We can forge valid checksums for arbitrary APFS structures, so every
superblock / omap / btree node / directory record iBoot parses BEFORE it
authenticates anything is fully attacker-controlled, integrity-valid input.
APFS code map: nx_superblock validator 0x14078 (magic @+0x20, block size
bounded [0x1000,0x10000], checksum, range checks); volume open/snapshot 0x15270;
snapshot-name resolve 0x15798; path walk 0x15a18 (splits on '/'); record lookup
by j_key_t 0x15d6c (0x3<<60 | oid); allocator 0x16150.
Public analyses cover iBoot's *Image4* parser (judged sound) -- NOT its APFS
reader, and not the A8-era 5540.x build. This is the remaining candidate surface
for an unsigned-boot primitive. It is a campaign, not a one-night job.

## R14 — APFS PRE-AUTH AUDIT: target list and harness design (START HERE NEXT SESSION)

### Why this surface
Image4 is closed (two independent public analyses + our own reading). But iBoot
MUST parse APFS to find the four files it loads, and that parsing is entirely
pre-authentication. Integrity is unkeyed Fletcher-64 (R13.2), so we can forge
valid checksums for arbitrary structures. No public audit exists of iBoot's APFS
reader, and none at all of the A8-era 5540.x build.

### Verified code map (file offsets in iBoot.dec, base 0x830000000)
    0x14078  nx_superblock validator. CAREFUL: block size must be
             [0x1000,0x10000]; magic 'NXSB' @+0x20; nx_block_size @+0x24 must
             equal caller's; Fletcher check; then several range checks.
             Returns 0x16 (EINVAL) on bad size. Do not expect a win here.
    0x1636c  object checksum verify -> 0x16290 -> 0x162c8 (plain Fletcher-64,
             seed 0, covers obj+8). Size must be >=8 else err 0x21.
             Error line numbers 0x38 / 0x3e go to the %llx:%d logger.
    0x15270  volume open / snapshot selection. Iterates
             nx_superblock.nx_fs_oid[] (nx_max_file_systems @+0xB4, array @+0xB8).
             With name==NULL takes index 0 WITHOUT comparing. Reads
             apfs_superblock.apfs_volname @+0x2C0, apfs_fs_flags @+0x108,
             apfs_incompatible_features @+0x38, apfs_root_to_xid @+0x3C8.
    0x15798  snapshot-name -> XID resolve.
    0x15a18  PATH WALK. Splits on '/' (cmp #0x2f). Frame `sub sp,sp,#0xa0`.
             *** Prime target: per-component copy into a stack frame. ***
    0x15d6c  record lookup by j_key_t (0x3<<60 | oid). Allocates 0x1220 via
             0x16150; context at +0x340.
    0x16150  allocator.
    btree_node_phys_t field loads found at 0x14310, 0x144fc, 0x14be8, 0x16894
             (btn_nkeys @+0x24) and 0x15068, 0x15548, 0x15b74, 0x15c34, 0x15c70
             (btn_table_space @+0x28).
             CHECKED: 0x16894's loop IS bounded (cmp w9,w10 / b.hs exit, umaddl
             stride index, self-consistent with the count). Not a win.
             NOT YET CHECKED: 0x14310, 0x144fc, 0x14be8, and all five
             table_space sites. **Audit these first.**

### The question to answer at each site
Is the attacker-controlled count/offset validated against the NODE/BUFFER SIZE,
or only used self-consistently? btn_nkeys and btn_table_space{off,len} come
straight off disk. The classic APFS parser bug is nkeys or a table entry
off/len that is not checked against nx_block_size, letting the toc/key/value
area index outside the 4096-byte node.

### Harness design (and its cost, honestly)
Constraint from R13.1: NVRAM boot-command is INERT, so `upgrade` (Update volume)
and `recover` (Recovery volume) are NOT reachable. fsboot on the FIRST volume
(System, disk1s1) is the only path. So corruption experiments hit the volume the
pod boots from: a failure = non-booting pod = full restore. Restore is rehearsed
(~10 min) and we can rebuild all four boot files byte-identically (R13), so the
cost is bounded and known -- but it is not free, and each iteration needs the author.

Loop:
  1. Offline: build a modified APFS structure; recompute Fletcher-64 over obj+8
     (0x162c8 algorithm) so it passes integrity.
  2. Ramdisk: dd it onto disk1s1 at the right block. Keep a pristine copy of
     every block overwritten so we can revert from the ramdisk without a restore.
  3. Cold boot; read UART + boot-breadcrumbs.
  4. Signature to look for: a NEW %llx:%d file:line marker, a hang before the
     `image ... type ibot` lines, or a panic in disk4 (keep disk4 blank between
     runs so any content is attributable).
  REVERT-FIRST RULE: never write a block without saving the original bytes to
  runner/files/ first. Tonight's lesson: the snapshot delete had no backup.

### Reference points for detecting any change
  * Healthy cold-boot marker sequence (baseline, clean13.4.8restore.screenlog.0
    final Local boot AND job583 cold boot -- byte-identical to each other):
      1766514c6672593:348 / 3974bfd3d441da3:1045 /
      "Delaying boot for 0 seconds" / dce7b01f6ef60a3:347 / :389 /
      a60aa294185a059:313 / e51893b627f0e6e:1228 x2 / dce7b01f6ef60a3:1043 /
      7ab90c923dae682:479 / 8d3ff3cd3759614:366 x2 / :378 x2 / 6476b5993bf0843:102
  * Healthy image list, every Local boot:
      image <ptr>: bdev <ptr> type ibot offset 0x0      len 0xaa5e5
      image <ptr>: bdev <ptr> type dtre offset 0xaa5e5  len 0x18738
  * Snapshot name now: com.apple.os.update-<MANIFEST_HASH_2>
  * Apple's personalised file sizes: kernelcache 12909820, devicetree 100115,
    sep-firmware 1618875, StaticTrustCache 17595, RestoreTrustCache 8399.

### Realistic expectation
Finding a memory-safety bug here is a campaign of days, not one night. Apple's
code in the parts we did read is carefully bounds-checked. The value of tonight
is that the surface is now MAPPED, provably REACHABLE (forgeable checksums), and
we have a baseline precise enough to detect a single changed code path.

## R14.1 — first audit pass on the APFS count sites (results)

CORRECTION to R14's labelling: obj_phys_t is {o_cksum@0x00, o_oid@0x08,
o_xid@0x10, o_type@0x18, o_subtype@0x1c}, so +0x20 is the type-specific body.
For nx_superblock that is nx_magic@0x20, **nx_block_size@0x24**,
nx_block_count@0x28. So the "btn_nkeys@0x24 / btn_table_space@0x28" labels in
R14 are wrong for these sites -- they are nx_superblock fields, not btree node
fields. The btree node walker has NOT been located yet.

Audited this pass:

  0x14310  CHECKED, SAFE. `ldr w8,[x20,#0x48]` (cached block size) vs
           `ldr w9,[x19,#0x24]` (on-disk nx_block_size), `cmp`/`b.eq`;
           mismatch logs line 0xad and errors out. Cross-validates the cached
           value against the on-disk one.

  0x14be8  PROVENANCE, not a bug. `ldr w8,[x20,#0x24]` -> `str w8,[x19,#0x48]`:
           this is where the on-disk nx_block_size is cached into the context
           field that 0x14310 later checks. Also copies nx_block_count
           (`ldr x8,[x20,#0x28]`).

  0x16894  CHECKED, SAFE (R14). Loop bounded `cmp w9,w10`/`b.hs`, umaddl stride
           index self-consistent with the count.

  0x15068, 0x15548  NOT count sites. These are 32-bit loads of a field at +0x28
           used as FLAGS: `tbnz w8,#0x1f` / `tbnz w8,#0x1e` bit tests, and
           0x15560 does `and w8,w8,#0xffff`. Type/flag dispatch, no indexing.

  **0x144fc  TOP CANDIDATE -- needs follow-up.**
           0x144f8  cbnz w25, #0x14788
           0x144fc  ldr  w8, [x19, #0x24]        ; nx_block_size, FROM DISK
           0x14500  cmp  x24, x8
           0x14504  b.hs #0x14788                ; index must be < that value
           0x14508  mov  w11, #0x28
           0x1450c  madd x26, x24, x11, x19      ; x19 + index*0x28
           0x14510  ldr  w8, [x26, #0x28]!
           0x14514  and  w9, w8, #0xc0000000
           The index is bounded only by **nx_block_size**, then scaled by 0x28
           and added to x19. If x19 is a single block, an index approaching
           block_size yields reads up to block_size*0x28 (4096*40 = 163 KB)
           past the base. UNRESOLVED: what x19 actually points at and how large
           that allocation is -- it may legitimately be the mapped checkpoint
           descriptor area (nx_xp_desc_blocks * block_size), in which case this
           is fine. **Next step: determine x19's provenance and allocation size
           at 0x144fc (walk back to the caller and the 0x16150 allocation), and
           whether nx_block_size is re-validated on that path.** Do not report
           this as a bug until that is settled.

STILL TO DO: locate the actual btree_node_phys_t walker (btn_nkeys and
btn_table_space{off,len} come off disk and bound the toc/key/value areas inside
a single node -- that remains the classic bug shape and we have not found that
code yet). Candidates to sweep: 0x1489c, 0x149d4, 0x14ae8, 0x1589c, 0x15f9c,
0x163cc, 0x164a8, 0x167b4, and the ldrh sites at 0x15b74/0x15c34/0x15c70.

## R14.2 — 0x144fc RESOLVED: SAFE. And we now have the validation IDIOM to hunt for.

The function at 0x14418 validates a **checkpoint_map_phys_t**:
  * x19 = caller-supplied buffer; checksummed over [x0+0x48] bytes = ONE BLOCK
    (`ldr w1,[x0,#0x48]` then `bl 0x1636c` at 0x14468).
  * `ldp w11,w12,[x19,#0x18]` = o_type/o_subtype, compared against
    w10 = **0x4000000c** = OBJECT_TYPE_CHECKPOINT_MAP | OBJ_PHYSICAL.
  * So +0x20 = cpm_flags, **+0x24 = cpm_count**, +0x28 = cpm_map[], and each
    checkpoint_mapping_t is exactly 40 bytes (0x28) -- matching the
    `madd x26, x24, #0x28, x19` stride. (My R14 "btn_nkeys" and R14.1
    "nx_block_size" labels for THIS site were both wrong; it is cpm_count.)

**cpm_count IS bounds-checked, correctly:**
    0x144c8  cbz w8, #0x144e4          ; count == 0 -> failure
    0x144cc  ldr w9, [x20, #0x48]      ; cached block size
    0x144d0  sub x9, x9, #0x28         ; minus header/flags/count
    0x144d8  udiv x9, x9, #0x28        ; = max entries that FIT
    0x144dc  cmp x9, x8                ; capacity vs on-disk cpm_count
    0x144e0  b.hs #0x144e8             ; proceed only if capacity >= count
    0x144e4  add w25, w25, #1          ; else count a validation failure
    0x144f8  cbnz w25, #0x14788        ; ANY failure -> bail before the loop
Then the loop at 0x144fc is `index < cpm_count` with the 0x28 stride, which is
safe given the capacity check. **0x144fc is SAFE. Candidate closed.**

### The idiom to hunt (this is the real takeaway)
This author's pattern for an on-disk count is:
    capacity = (buffer_size - header_size) / element_size   (sub + udiv)
    if (capacity < on_disk_count) -> fail
    accumulate failures in one register, test it ONCE before using the data
So when sweeping the remaining functions, grep for the shape
**`sub` then `udiv` then `cmp` then a `b.hs`/`b.lo` guard** near any on-disk
count, and treat its ABSENCE as the bug signature. A count that is only used
self-consistently (`index < count`) with no capacity comparison anywhere on the
path is the thing worth chasing.

### Running tally of the APFS audit
  SAFE / cleared: 0x14310, 0x14418+0x144fc (checkpoint map), 0x14be8
                  (provenance only), 0x16894.
  Not count sites: 0x15068, 0x15548 (flag bit-tests; `and w8,w8,#0xffff`).
  STILL UNSWEPT: 0x1488c, 0x149d4, 0x14ae8, 0x1589c, 0x15f9c, 0x163cc, 0x164a8,
                 0x167b4, and the ldrh sites 0x15b74 / 0x15c34 / 0x15c70.
  The btree_node_phys_t walker (btn_nkeys@+0x24, btn_table_space@+0x28 relative
  to the NODE, which is also one block) is STILL NOT LOCATED. It is the highest
  value remaining target: a node's toc/key/value areas are bounded by on-disk
  u16 offsets, which is a richer bug shape than a single count.

## R14.3 — BTREE CODE LOCATED. Audit it here next.

Only TWO full 32-bit o_type constants exist in the whole image
(0x1c60 -> 0x10000001 NX_SUPERBLOCK virtual, 0x14478 -> 0x4000000c
CHECKPOINT_MAP physical). The btree check is a **masked 16-bit compare**, which
is why a 32-bit-constant scan missed it:

    0x150a4  and w8, w8, #0xffff      ; mask o_type low 16 bits
    0x150a8  cmp w8, #2               ; == OBJECT_TYPE_BTREE (root)
    0x15560  and w8, w8, #0xffff
    0x15564  cmp w8, #2               ; second site, same check

Sibling tree-type checks nearby:
    0x150fc  cmp w2, #16   OBJECT_TYPE_SNAPMETATREE
    0x15684  cmp w9, #11   OBJECT_TYPE_OMAP
    0x1595c  cmp w8, #15   OBJECT_TYPE_BLOCKREFTREE
    0x14264 / 0x14274 / 0x1491c / 0x14984  cmp #2 (more btree-root paths)

**CORRECTION to R14.1/R14.2:** the sites 0x15068 and 0x15548, which I wrote off
as "flag bit-tests, not count sites", are in fact the **B-TREE OBJECT
VALIDATORS**. They read a field at +0x28 as flags (`tbnz #0x1f`, `tbnz #0x1e`),
then a few instructions later mask o_type and compare it to 2. They are the
entry points to the btree handling, not dead ends.

=> **The btree root/node handling lives in the function starting at 0x14ae8**
(next prologue after it is 0x15270), spanning roughly 0x14ae8-0x1526c, which
contains 0x14be8, 0x14dd0, 0x14de8, 0x14ec8, 0x14f20, 0x15028, 0x15068,
0x150a4-0x150fc. A ~1.9 KB function -- the right size for a btree lookup.
A second btree path is around 0x15548-0x15684 (inside 0x15270's function, the
volume-open/snapshot code).

### Exact next action
Disassemble 0x14ae8..0x1526c and, for every on-disk-derived count or offset
(btn_nkeys, btn_table_space{off,len}, btn_free_space, and the toc entry
off/len pairs), check for the validation idiom from R14.2:
    sub (buffer_size - header) ; udiv by element size ; cmp ; b.hs/b.lo guard
**Its ABSENCE on a path that then indexes node+0x38+offset is the bug.**
Note the richer shape here vs the checkpoint map: a btree node's toc entries are
PAIRS of u16 (offset,length) relative to the key/value areas, so there are
several independent values to check, and a missed check on any one of them is
exploitable. Also: keys and values grow from OPPOSITE ends of the node, so a
value offset is subtracted from the node end -- an unchecked value length is the
classic underflow there.

## R15 — Fletcher-64 CONFIRMED ON HARDWARE (2026-11-26). PR #2 reviewed.

### Community PR #2 (UnbendableStraw/homepod-untethered)
"Add offline APFS structure forge for the R14 pre-auth audit" — 17 new files,
2459 insertions, **zero modifications to existing files**:
  tools/apfs/{fletcher,objects,superblock,checkpoint_map,btree,cli}.py + tests
  tools/findings/{validate.py,findings.toml} (42 findings) + tests
  tools/run_checks.sh
Review performed:
  * SAFETY: clean. No network, no subprocess/os.system, no device writes, no
    eval/exec, no base64 blobs. Only `rm -rf` is a tmpdir trap on its own temp
    dir; only `dd` is a commented-out READ example in a README. It asks the
    maintainer to run nothing against the pod.
  * EPISTEMICS: findings.toml preserves our retractions rather than reasserting
    them — 6 entries marked status="retracted" incl. `nor-iboot-boot-commands`
    with a supersedes link to R13.1, and the 949 decode explicitly called out as
    log/assert sites not error codes. Status taxonomy: 10 confirmed,
    9 proven_static, 11 closed_negative, 6 retracted, 6 open.
  * MATH: their check-word derivation verified INDEPENDENTLY — with the check
    words appended AFTER the body, both accumulators land on (0,0) across 8
    random 4088-byte trials. (My first test wrongly PREPENDED the checksum and
    appeared to fail; the tell was s1==0 while only s2 broke, i.e. an order
    error in my test, not their code.)
  * Could not execute their pytest suite (sandbox classifier denied it). Not a
    gap: the independent reimplementation below is stronger evidence.

### HARDWARE CONFIRMATION (job 584/585)
Pulled the first 1 MB (256 x 4096-byte blocks) of /dev/disk0s1 — the live APFS
container on this pod — read-only, staged to /mnt1/private/var/tmp and removed
afterwards. Recomputed Fletcher-64 over obj[8:] for every block with an
independent implementation:
    **256 / 256 CHECKSUM-VALID, 0 invalid, 0 all-zero.**
Contents are the CHECKPOINT DESCRIPTOR AREA ring:
    blk 0  o_type 0x80000001 NX_SUPERBLOCK (ephemeral)  o_oid 1   o_xid 621
    blk 1  o_type 0x4000000c CHECKPOINT_MAP (physical)  o_oid 1   o_xid 573
    blk 2  NX_SUPERBLOCK o_xid 573 ... alternating, xid ascending 573..579
    (sample o_cksum blk0 = 0xfb57367e86c0b936)

=> **The unkeyed-Fletcher-64 forging capability (R13.2) is CONFIRMED against
real Apple-written objects from this device, not just inferred.** We can mint
checksum-valid arbitrary APFS objects. PR #2's forge is correct and on-target.
=> Independently corroborates R14.2: these ARE checkpoint_map_phys_t objects of
exactly the shape the 0x14418 validator expects.

### Note for the next pull
The 1 MB sample contains NO btree nodes (only NX_SUPERBLOCK + CHECKPOINT_MAP).
To exercise the btree walker at 0x14ae8 with real data we need objects of
o_type OMAP (0xb) / BTREE (0x2) / BTREE_NODE (0x3), which live via the
container omap and the volume's fstree — not in the checkpoint descriptor area.
Next pull should follow nx_omap_oid from blk 0's superblock rather than dd'ing
a flat range.

## R16 — THE BTREE TOC PARSER IS CORRECTLY BOUNDS-CHECKED. (first public audit of this code)

### Localisation correction (R14.3 was half wrong)
0x14ae8-0x1526c contains the btree OBJECT type checks but NOT the node/toc
parsing: there is **not a single ldrh in that whole range**, and nloc_t/toc
fields are u16. The real node+toc parser is at **0x16c40-0x174ff**, found by
following the record-lookup's callees (0x15d6c -> 0x16d68) and by scanning for
ldrh at btree_node_phys_t offsets.

### Verified field map (btree_node_phys_t, offsets from node base)
    +0x20 btn_flags      read at 0x16c5c, 0x16c78, 0x17408, 0x1748c, 0x16e68
    +0x22 btn_level      read at 0x16cbc, 0x16cd4, 0x16e64
    +0x24 btn_nkeys      read at 0x1741c
    +0x28 table_space.off 0x16cf8     +0x2a table_space.len 0x16d04, 0x173b4
    +0x2c free_space.off  0x16d40, 0x173a8, 0x173e0, 0x17430
    +0x2e free_space.len  0x16d4c, 0x17438
    +0x38 btn_data (toc base)   0x17444
    toc entry: kvoff_t (4B, FIXED_KV_SIZE) index*4 at 0x17448, v at +2 (0x1744c)
               kvloc_t (8B)             index*8 at 0x17450, v.off at +4 (0x17454),
                                        k.off +0 (0x173a4), k.len +2 (0x173cc),
                                        v.len +6 (0x17494)

### KEY side — CHECKED
    0x173a4  ldrh w8,[x8]        ; key_off from toc
    0x173a8  ldrh w11,[x1,#0x2c] ; free_space.off = end of key area
    0x173ac  cmp w8,w11 / b.hs -> err 0x5c      ; key_off must be < free_space.off
    0x173b8  key addr = base + table_space.len + key_off
    0x173c8  tbnz flags,#2       ; FIXED_KV -> fixed key size, else k.len from toc
    0x173e4  sub w8, free_space.off, key_off     ; remaining space
    0x173e8  cmp w8, w9, uxth / b.ge             ; remaining >= key_len, else err 0x5c

### VALUE side — CHECKED, including the backwards-offset underflow
    0x1741c  ldr w9,[x1,#0x24] ; btn_nkeys
    0x17420  cmp w9,w2 / b.le  -> err 0x16       ; index < nkeys  (and 0x17418 rejects negative)
    value area size computed into w14:
    0x1742c  add w9, node_size, (ROOT ? -0x28 : 0)   ; minus btree_info_t on a root
    0x17434  sub w9, w9, free_space.off
    0x1743c  sub w9, w9, free_space.len
    0x17440  sub w14, w9, #0x38                      ; minus the header
    0x17460  ldrh w8,[x8]       ; val_off from toc
    0x17468  cmp w8,#0xfffd
    0x1746c  ccmp w14, w8, #2, ls                    ; area_size vs val_off
    0x17470  b.lo -> 0x17504 ERROR                   ; val_off must be <= area size
    0x1747c  sub x10, node_end(+adj), val_off        ; the backwards address
    0x17484  csel x10, xzr, x10, lo                  ; belt-and-braces NULL if area < val_off
    val_len:
    0x174b8  val_off==0xffff (BTOFF_INVALID) -> len 0
    0x174c4  val_off==0xfffe -> sentinel handled
    0x174e0  tst flags,#2 ; INTERNAL node -> val size FORCED to 8 (oid_t), toc not trusted
    0x174f0  cmp val_len, val_off
    0x174f4  b.ls -> OK                              ; require val_len <= val_off

Because the value lives at (node_end - val_off) and extends forward by val_len,
`val_off <= value_area_size` AND `val_len <= val_off` together confine it to the
value area. **That is the correct invariant. The hypothesised underflow (R14.3)
does not exist here.**

### VERDICT
**CLOSED NEGATIVE.** iBoot-5540.140.12's btree toc parser validates key_off,
key_len, index/nkeys, val_off (incl. the backwards-offset underflow) and
val_len, handles the 0xffff/0xfffe sentinels, and refuses to trust the toc's
value size on internal nodes. Same careful style as the checkpoint_map validator
(R14.2). This was the single highest-value remaining hypothesis for a pre-auth
unsigned-boot primitive, and it does not hold.

### Corpus captured (jobs 584/585/586) — keep for any future fuzzing
  runner/files/apfsblocks.bin  1 MB, blocks 0..255 of disk0s1: the checkpoint
    descriptor ring (alternating NX_SUPERBLOCK ephemeral 0x80000001 /
    CHECKPOINT_MAP physical 0x4000000c), 256/256 checksum-valid.
  runner/files/omapwin.bin     256 KB, blocks 3842745..3842808: **37 real
    BTREE_NODE objects**, plus OMAP (0x4000000b), BTREE roots (0x40000002) and
    three FS/apfs_superblock (0xd) objects. All checksum-valid.
  Container facts: nx_block_size 4096, nx_block_count 3906239,
    nx_xp_desc_base 1 len 104, nx_xp_data_base 105 len 9744,
    nx_omap_oid 3842753 -> om_tree_oid 3842756, nx_max_file_systems 30,
    nx_fs_oid[0..2] = 1026, 2268, 2270 (System/Data/Update).
  Real node examples: omap root 3842756 ROOT|LEAF|FIXED_KV nkeys=3 ts.len=448;
    3842760 LEAF|FIXED_KV nkeys=63; 3842745 LEAF (variable kvloc_t) nkeys=22
    ts.len=192, key/val free lists = 0xffff (BTOFF_INVALID appears in real data).

### What is still unaudited on this surface
  * The node-level validator around 0x16c40-0x16d60: does it check
    nkeys*entry_size <= table_space.len, and table_space/free_space within the
    node? (The toc accessor above is safe REGARDLESS, since it bounds each
    access individually -- so a missing node-level check is likely not
    exploitable on its own, but worth closing.)
  * omap lookup / snapshot resolution (0x15270, 0x15798).
  * Path walk 0x15a18 (splits on '/', frame 0xa0) -- per-component copy.
  * The j_* record interpretation after a successful lookup (drec/inode/extent),
    i.e. what consumes the key/value once bounded.

## R16.1 — path walk + btree search copy-out: ALSO SAFE. The APFS lookup chain is closing.

### Path tokenizer 0x15a18 — bounded, and not attacker-controlled anyway
    0x15ac8  cmp x9,#0x2fd / b.hi    ; total path length capped at 765
    0x15ad4  cmp w10,#0x2f           ; skip '/' runs
    0x15b00  cmp x28,#0x2fd / b.hi   ; per-component length capped at 765
    0x15b20  cmp x28,#0x2fd / b.hi -> 0x15d1c error
The string being tokenised is iBoot's OWN hardcoded boot-path, not on-disk data,
so even an unbounded tokenizer would not be attacker-reachable here.
It then builds a DIR_REC key: `mov x11,#-0x7000000000000000` (type 9 =
APFS_TYPE_DIR_REC) + `bfxil x11,x25,#0,#0x3c` (oid in low 60 bits),
sizes it `add x19,x28,#0xd`, and calls the btree search at 0x16d68.

### btree search copy-out 0x1712c-0x171ac — CAPACITY-CHECKED both sides
0x026270 is **memcpy** (overlap check `sub x3,x0,x1; cmp x3,x2; b.lo`, then bulk
ldp/stp), NOT memcmp. The search copies the found key and value into
caller-provided buffers, and checks BOTH against the caller's capacities:
    value side:
      0x1712c ldr w20,[sp,#0x50]      ; val_len from the value accessor (0x17408)
      0x17134 cmp w20,#0xfffe / b.ne  ; sentinel -> w22 = 0
      0x17150 cbz x8 -> error         ; NULL value pointer rejected
      0x17158 ldr w8,[x23]            ; caller's value buffer capacity
      0x17160 cmp w20,w8 / b.ls       ; else 0x17168 mov w28,#0x22 ERROR
    key side:
      0x17174 ldr w21,[sp,#0x54]      ; key_len
      0x1717c cmp w21,w8 / b.ls       ; vs caller capacity, else err 0x22
      0x17198 bl memcpy(dst,src,w21)
      0x171a8 bl memcpy(dst2,src2,w22)
Indirect key comparators are the two `blr x8` at 0x1709c and 0x172f8 (per-tree
comparison callbacks) — NOT yet audited, see below.

### VERDICT so far on the APFS lookup chain
SAFE: nx_superblock validator (0x14078), checkpoint_map validator (0x14418),
btree toc accessor key+value bounds (0x173a4-0x174ff), btree search copy-out
capacity checks (0x1712c-0x171ac), path tokenizer (0x15a18), the 0x16894 loop.
This code is consistently defensive: every on-disk length is compared against a
computed capacity before use, sentinels (0xffff/0xfffe/BTOFF_INVALID) are
special-cased, internal-node value sizes are forced rather than trusted, and
failures accumulate into one register tested once before any data is touched.
**The hypothesis that iBoot's APFS reader contains an easy pre-auth
memory-safety bug is now substantially weakened.**

### Still open on this surface (narrowing)
  * The two indirect key comparators at 0x1709c / 0x172f8 — what do they read
    from an on-disk key, and do they trust a name_len inside it? (A j_drec_key
    carries {j_key_t hdr, u16 name_len, u8 name[]}; the toc accessor bounds the
    key BUFFER, but a comparator that trusts name_len could over-read within or
    past it.) **This is the best remaining APFS lead.**
  * btree node-level validator ~0x16c40-0x16d60 (agent auditing).
  * omap/snapshot resolution 0x15270 / 0x15798 and omap_val_t ov_paddr
    validation (agent auditing).
  * GPT parser at 0x29328 (agent auditing) — note GPT has only CRC32s, which are
    forgeable, so it is a genuine pre-auth surface too.

## R16.2 — iBoot's APFS B-TREE IS CLOSED ON EVERY KNOWN BUG CLASS. (complete negative)

Driven by a research agent's checklist (A-K) distilled from every public APFS
parser bug: CVE-2026-40025 (Sleuth Kit keybag), CVE-2026-111133 (libfsapfs KEK
`len > end - cursor` underflow), Sleuth Kit OSS-Fuzz 36025/36027/471605916 and
commits 910512f/a650e0f/58c8b60/a3ac2c2, the Linux apfs-oot module's checks,
apfs-fuse's near-total absence of checks (unfixed at HEAD 66b86bd), and the two
historical iBoot HFS+ code-exec bugs (p0sixninja iOS 5 HFS heap overflow;
xerub "De Rebus Antiquis" B-tree recursion -> memalign metadata -> PC).
Apple's APFS Reference contains NO validation guidance at all, which is why
every independent implementation got this wrong at least once.

### Node validator 0x16c30-0x16d64 (args: tree ctx x1, node x2, is_root w3,
### expected_level w4) — returns 0 or 0x5c; failures accumulated in w9/w8
    0x16c30 o_subtype must == tree's expected subtype ([x1,#8])
    0x16c50 is_root ? o_type==BTREE(2) : o_type==BTREE_NODE(3)
    0x16c7c NON-root node carrying the ROOT flag -> failure          [closes F]
    0x16c8c ROOT: footer btree_info_fixed_t read at node_end-0x24..-0x1c
            bt_node_size, bt_key_size, bt_val_size must EQUAL the tree
            context ([x1,#0xc],[x1,#0x10],[x1,#0x14])              [closes G/K]
    0x16cbc LEAF flag => btn_level must == 0
    0x16cc8 expected_level == 0xf00f is the "unknown" sentinel (root entry)
    0x16cd8 cmp btn_level, expected_level -> failure if !=          [closes H]
    0x16ce4 usable = node_size - 0x38 - (ROOT ? 0x28 : 0)
            (mov w11,#-0x60 / mov w12,#-0x38 / csel)
    0x16cfc table_space.off must == 0                               [closes B]
    0x16d08 table_space.len <= usable                               [closes B]
    0x16d10 entry size: FIXED_KV ? mask 3 / shift 2 : mask 7 / shift 3
    0x16d28 table_space.len must be a multiple of entry size
    0x16d34 lsr w11,w11,w12  ; capacity = table_space.len / entry_size
    0x16d38 nkeys <= capacity                                       [closes A]
    0x16d44 free_space.off <= remaining
    0x16d50 free_space.len <= remaining - free_space.off
    0x16d58 compiler-folded "failures==0 AND free space fits" -> 0 else 0x5c
STRICTER than the open-source readers: libfsapfs has its free_space.len check
commented out ("TODO this check fails on some container"); the Linux module
does not enforce entry-size alignment. iBoot does both.

### Descent 0x16d68 — iterative, strictly level-decrementing        [closes H]
    0x16e38 bl 0x1751c  read node into x19 (ONE reused buffer)
    0x16e44 is_root = (oid == tree root oid [x24,#0x18])
    0x16e60 depth starts at node's btn_level (w22, read [x19,#0x22])
    The loop reads the next child, calls the 0x16c30 validator each iteration
    with expected_level = parent_level - 1, and the validator rejects any node
    whose btn_level != expected. Level is u16 and strictly decremented, so the
    descent cannot loop or exceed ~65535 iterations, and a self- or back-pointer
    fails the level check. ONE node buffer is reused (no per-level memalign), so
    there is no heap-growth-per-descent analogue of xerub's HFS+ bug.

### VERDICT: CLOSED NEGATIVE across the entire agent checklist A-K.
    A nkeys vs capacity .......... CHECKED (0x16d38)
    B table_space off/len ........ CHECKED (0x16cfc off==0; 0x16d08 len<=usable)
    C key_off + key_len .......... CHECKED (0x173ac, 0x173e8)  [R16]
    D val_off underflow .......... CHECKED (0x1746c, double-guarded)  [R16]
    E val_len / internal size .... CHECKED (0x174f0; internal forced to 8)  [R16]
    F root-flag consistency ...... CHECKED (0x16c7c)
    G/K cross-block footer trust . CHECKED (0x16c8c footer must equal ctx)
    H level/recursion/cycle ...... CHECKED (0x16cd8 + strict decrement)
    I free-list walk ............. NOT PRESENT (no ldrh at +0x30/+0x34; iBoot
                                   does not walk btn_key/val_free_list at all)
    J nkeys==0 ................... benign here (bounded loop, read-only)
    copy-out key/val capacity .... CHECKED (0x1717c, 0x17160, err 0x22)  [R16.1]

iBoot-5540.140.12's APFS B-tree reader is, field for field, STRICTER than every
public open-source APFS parser. This appears to be the first audit of this code
and the result is that the "easy pre-auth APFS memory-safety bug" hypothesis is
DEAD for the B-tree path. The remaining unaudited APFS code (omap/snapshot
0x15270/0x15798, the two indirect key comparators 0x1709c/0x172f8) is being
checked by a parallel agent, but given how uniformly defensive this code is, the
prior should now be LOW. Pivot recommendation: the non-APFS pre-auth surfaces
(GPT parser 0x29328, USB/DFU) and the hardware checkm8-injector route are now
the higher-EV paths to the untethered goal.

## R17 — GPT parser (0x2929c): NO memory-safety bug. Two non-corruption findings.

Full field-by-field audit (agent, verified against disassembly). GPT parser is
bounds-safe BY CONSTRUCTION: no on-disk value participates in address
arithmetic. Output index bounded by a CONSTANT (cmp x23,#7); header read into
memalign(0x60) with hardcoded length 0x60; each entry read into its own
memalign(0x80) with hardcoded length 0x80; output array exactly 8*0x20 on stack
with the stack cookie immediately above it (an off-by-one would smash it; it
doesn't). Classic shapes all absent: no nkeys*size mult, SizeOfPartitionEntry
used only as a disk-offset delta (not an in-memory stride; <0x80 rejected),
HeaderSize/PartitionName never read.
Reached via: protective-MBR gate (MBR[0].type==0xEE) -> 0x2929c. Only GPT parser
in the image ('EFI PART' @0x3fb6a has one ref).
Unchecked but NOT corruption: StartingLBA/EndingLBA never range-checked and no
End>=Start check, but the block layer (0x1fcb4/0x1f60c/0x1fdb0) clamps every
read to the real device size -> forged partitions yield SHORT/ZERO reads, not
OOB. Partition base/size are attacker-controlled into the APFS probe, but that
probe (0x14ae8) is the B-tree reader already audited safe (R16/R16.2).

### R17.1 — two verified non-memory-safety findings
(a) NO integrity check on the GPT at all. Neither CRC32 field is read; 0x2034c
    (the CRC-32 this binary DOES have, poly 0xEDB88320, used for LwVM) is never
    called from the GPT path. Attacker needs not even forge CRCs.
(b) Reachable PRE-AUTH assert/panic (DoS). A single crafted GPT with
    PartitionEntryLBA or StartingLBA = 0x8000000000000000>>blockshift sets bit63
    of a byte offset -> 0x1f62c/0x1fcb4 tbnz x2,#0x3f -> ASSERT (0x3f92c) ->
    0xf998 panic; 3rd panic -> hang. Not code-exec, but a crafted boot medium
    can brick-to-hang pre-auth. (Low value for our goal; recorded for honesty.)

### R17.2 — NEW LEAD: LwVM-style parser at 0x294e0 runs BEFORE GPT
Same caller (0x298c4), tried first; if it returns >0, GPT is never parsed. Only
PARTIALLY audited by the agent. 0x1000 buffer; two type-GUID variants:
  - 0x44dd4 (6A9088CF-...): CRC-32-verified (0x295e8), count<=8
  - 0x44de4 (B189A519-...): NO CRC, count<9
Chunk-map copy 0x296a4-0x296b8 bounded by a MASK (and x10,#0x3ff) not a compare;
agent called it "tight but correct" (max write +0x884 < alloc 0x888). Count is
RE-READ from the attacker buffer each iteration (0x29760) after one validation
-- agent says not a TOCTOU today because the loop body doesn't write that
buffer. This is the least-scrutinised pre-auth filesystem-ish parser on the
boot path. WORTH a direct second look at the mask-vs-bounds copy and the
re-read. (The B189A519 no-CRC variant means no checksum forge needed either.)

## R18 — APFS PRE-AUTH SURFACE: COMPREHENSIVELY CLOSED (independent 2nd audit)

Second agent audited the remaining paths and independently CONFIRMED my node
validator reading, cross-checked against all 37 real on-disk nodes in
omapwin.bin (all 37 pass, incl. invariants only this reading predicts:
table_space.off==0 everywhere; avail=4040 non-root vs 4000=4096-0x60 for the one
ROOT node; entry_size 4 on the FIXED_KV node vs 8 elsewhere; its btree_info_t =
bt_flags 18, bt_node_size 4096, bt_key_size 16, bt_val_size 16).

NEW structures pinned (verified from the sole constructor 0x16c18):
  btree ctx: +0x00 storage type, +0x04 obj type, +0x08 expected subtype,
             +0x0c BLOCK SIZE (from trusted side), +0x10 fixed key size,
             +0x14 fixed val size, +0x18 root oid, +0x20 comparator fn
  container ctx 0x14ae8 (0xf8 B) has a SELF-POINTER at +0 (0x14b28)
  ctx+0x38 = nx_block_count, ctx+0x48 = nx_block_size (0x14be8-0x14bf4, a STP --
  which is why a naive `str x,[x,#0x38]` scan misses it)

CLOSED this pass:
  * nx_max_file_systems / nx_fs_oid[] -- CHECKED. 0x14078's final accumulator
    bounds it to <=100 (0x014284 cmp w8,#0x64 / csetm / csel), and the bound is
    enforced on the SAME buffer the loop reads (ctx+0xf0, validated at
    0x14e64). Array span 0xb8+100*8=984 < 0x1000 minimum block size.
  * apfs_volname @+0x2C0 -- CHECKED. Touched in exactly 2 places (0x151d4,
    0x152d8); both use **strncmp (0x14000, NUL-terminating -- not memcmp)** with
    length = strlen(CALLER's name)+1, i.e. the non-attacker side sets the length.
    **The volname is NEVER COPIED anywhere.** The "256-byte field with no NUL"
    attack has no sink. (Residual: would need a caller name >= 3391 bytes;
    resolved callers pass NULL/"Update"/"Recovery".)
  * apfs_fs_flags/+0x108, apfs_incompatible_features/+0x38, apfs_root_to_xid
    /+0x3C8 -- scalar reads, no index/length/allocation sink.
  * 0x15798 snapshot name->xid -- CHECKED incl. copy-out. strnlen caps the name
    at 255 (0x157e0); one 0x1220 alloc split 0x340 key + 0xee0 value (exactly);
    0x16d68's copy-out bounds BOTH on-disk lengths against those capacities
    before either memcpy (err 0x22).
  * **ov_paddr -- CHECKED TWICE.** At the call site (0x16ac0 cmp vs
    nx_block_count -> err 0x5c) and unconditionally in the low-level reader
    0x164a8 with a complete overflow-safe 3-way range check
    (0x164d0-0x164e0: count vs start, count vs nblocks, count-nblocks vs start).
    **The "arbitrary block read primitive" hypothesis is NEGATIVE.** Also covers
    the physical-storage path where oid==paddr and there is no omap check.
  * ov_size -- unchecked but UNUSED (read length comes from ctx+0x48).

Hardening-only observations (explicitly non-exploitable): short omap value leaves
0xAAAA.. poison in the stack buffer -> rejected by the block-count check; the
snapshot key _chk bound (0x1216) is looser than the 0x340 sub-region but
unreachable via strnlen; 0x14078 called with w2=1 skips the block_size==buffer
equality test (0x140b4) but checksum + range checks still apply.

### VERDICT: the APFS pre-auth parser in iBoot-5540.140.12 is CLEAN.
Audited clean: 0x14078, 0x14418, 0x16c30, 0x16894, 0x173a4-0x174ff,
0x1712c-0x171ac, 0x15270, 0x15798, 0x1589c, 0x164a8, 0x15a18.
Two independent audits, one cross-validated against real device data, against a
checklist distilled from every public APFS parser bug. **This line of attack is
retired.** Do not spend more budget here.

## R19 — LwVM parser (0x294e0): CLEAN. The last open storage-reachable iBoot parser.

Extent 0x294e0-0x297b0, exactly ONE entry point (bl from 0x29918) so every path
is gated by header validation. Buffers: 0x1000 header buf (fill length is the
CONSTANT 0x1000 at 0x29590, verified exactly 0x1000 returned); 0x888 per-partition
object; 0x20 stack name buf (cookie immediately above).

**Every length passed to a memory primitive in this function is a compile-time
constant**: 0x1000 (bzero/read/crc32), 0x10 and 0xe (memcmp), 0x888 (calloc),
0x20 (vsnprintf), 0x10 (strlcpy). The only disk-derived value crossing a call
boundary is `end-begin`, and it lands in a SIZE FIELD, never a length arg.

The two suspicious shapes both verified SOUND:
  * chunk-map `and x10,x10,#0x3ff` (0x296b4) -- mask decoded by hand through
    DecodeBitMasks (N=1,immr=0,imms=9 => exactly 0x3ff). Source loop exits at
    x8==0x3ff so max load is buf+0xFFE..0xFFF = the final 2 bytes of the 0x1000
    buffer, NO off-by-one. Max write x23+0x882..0x883 vs alloc 0x888. The mask is
    sound ONLY because both sides are compile-time constants (0x3ff <-> 1024
    slots, 0x888 is a MOVZ immediate); the map is always 1024 slots and the
    device-geometry math produces chunk SIZE, never map LENGTH. Fragile style,
    not a bug in this image.
  * count re-read at 0x29760 -- it is compiler spill recovery (x23 is clobbered
    at 0x2965c to hold the new object). NOT re-validated against 8, so a changed
    value >8 WOULD give a 0x80-granular OOB read via `add x8,x20,x24,lsl #7`.
    Verified negative: x20 is never passed to any callee in the loop body; all
    depth-2 callees enumerated (allocator, vsnprintf->stack only, 0x1f570 writes
    only obj+0x08..0x6f, memcmp is a store-free leaf, 0x1f2ac touches one global);
    the device read at 0x29594 is synchronous; the remapping handler is only
    INSTALLED during the scan, never invoked. No TOCTOU today. Latent fragility.
Entry fields: count CHECKED <=8 on both paths (0x295cc cmp #9/b.hs;
0x295f8 cmp #8/b.ls). Stride 0x80 is constant, max entry byte 0x5C5 < 0x1000.
On-disk partition NAME is never copied (memcmp 0xe vs UTF-16 "Update" only).
Installed read handler 0x297b4 also audited: bounds-checks chunk index against
the monotonic populated count (<=0x400) at 0x297f4 before indexing the map.

### R19.1 — HARDENING GAP (real, but no corruption behind it)
The **B189A519-4F59-4B1D-AD44-1E127AAF4539** variant has NO checksum at all
(verified by control flow: the only `bl 0x2034c` crc32 is at 0x295e8, reachable
only via `cbz w0` on the FIRST memcmp at 0x295b0). The type GUID is bytes 0..0xF
of the unauthenticated 4 KiB block read off NAND at offset 0, pre-auth, so the
**attacker chooses the variant and the checksum-free path costs zero CRC work.**
The entire parser body is reachable with an arbitrary 4 KiB block whose first 16
bytes are that GUID and whose dword at +0x28 is <= 8. Correct framing for a
writeup: the CRC is not a security control. No corruption found behind the door.

### R19.2 — non-security correctness bug
The backup-header attempt (w24==1) is dimensionally inconsistent: 0x2953c
applies `>>0xa` to BYTES then 0x29574 shifts LEFT by blockshift, giving
`device_size*blocksize/1024 - blocksize` (~4x device size on a 4K-page NAND),
which 0x1f60c rejects. So only the primary header at offset 0 is ever parsed.
Reduces surface. Correct only if blocksize==1024.

### R19.3 — the one residual thread
`[obj+0x18]` = unchecked `end-begin` as a u64 partition size, and `[obj+0x10]` =
that value >> blockshift **truncated to 32 bits** (`stp w8,w0,[x22,#0x10]` in
0x1f570). Consumers of those two fields are OUTSIDE this function. If any
consumer allocates or loops on them, this unchecked subtraction is the source.
That is the only remaining pull-thread on the iBoot storage surface.

## ===== STRATEGIC CHECKPOINT (2026-11-26) =====
The pre-auth, storage-reachable attack surface of iBoot-5540.140.12 is now
COMPREHENSIVELY AUDITED AND CLEAN: APFS (11 functions, two independent audits,
cross-validated against 37 real on-disk nodes), GPT (0x2929c), LwVM (0x294e0 +
its read handler), load_bank_partitions (0x27490), the NVRAM env parser, and the
breadcrumb accumulator (0x308f8 `sub`/`cmp #9`/`b.lt` headroom check).
USB/DFU surface is deliberately EXCLUDED: any USB bug still needs a host, i.e.
it is just checkm8 again, and does not serve the untethered goal.
=> "Find a pre-auth iBoot memory-safety bug" is EXHAUSTED at our resource level.
   This is itself a novel, publishable negative result: nobody had audited this
   code, and the answer is that Apple hardened it.
=> Remaining live routes to the goal, in order:
   1. Userspace-first: trust cache validates Mach-O cdhashes, NOT scripts;
      mrm.plist is a DATA file we can write. Then A8 has NO PAC/NO PPL on an
      xnu-6153.143.1 (iOS 13.4-era) kernel with public exploits. Job 587 +
      research agent in flight. OPEN QUESTION the agent must answer: does
      kernel r/w actually get us BOOTING LINUX, or only running our code under
      audioOS each boot? Those are very different outcomes.
   2. Hardware MCU checkm8 injector (user deferred; Colobus/tcmini prior art).
   3. atera1n/Blackbird SEP route: untethered boot of SIGNED code with blobs.

## R20 — CORRECTION TO R19's "COMPREHENSIVELY AUDITED". iBoot HAS A SECOND FS DRIVER: HFS+.

**My R18/R19 claim that the storage-reachable pre-auth surface was comprehensively
audited was WRONG.** I audited the APFS driver exhaustively and never checked
whether iBoot registers other filesystem drivers. It does.

VERIFIED (inventory agent): the filesystem-type table at **0x46838-0x46848** has
exactly TWO entries, read at 0x22a60-0x22a74:
    0x46838 -> reg struct 0x485b8, name ptr 0x48618 = "apfs" (0x3f8dd)
    0x46840 -> reg struct 0x48628, name ptr 0x48688 = **"hfs"  (0x3f8f2)**
HFS vtable fn ptrs at 0x48628-0x48690: 0x18f54, 0x18ffc, 0x19000, 0x19018,
0x19158, 0x191b0, 0x191c8, 0x19210, 0x19214, 0x19310, 0x19470, 0x19478.

**And mount tries EVERY registered driver in turn on the boot partition,
pre-auth**: 0x1e08 loops i=0.., fetches the i-th FS name via 0x23174 and calls
0x22a1c(dev, fsname, "/boot", flags) at 0x1e40-0x1e74. Corroborated by the
device logs showing the ramdisk mounting as HFS.

### Why HFS+ is a BETTER target than APFS ever was
  * **NO CHECKSUMS AT ALL.** Weaker than APFS's unkeyed Fletcher-64 -- there is
    nothing even to forge. 100% attacker-controlled bytes.
  * **Variable-length UTF-16 strings are the core of the key format**
    (HFSUniStr255 catalog names, up to 255 code units).
  * Big-endian **byteswap arithmetic** on length fields.
  * Storage-reachable => serves the UNTETHERED goal.
  * **It is the same driver and the same bug class that gave xerub iBoot code
    execution on 32-bit iBoot ("De Rebus Antiquis"), and p0sixninja's iOS 5 HFS
    heap overflow.** Both yielded full iBoot code exec. Levin notes no 64-bit
    iBoot FS vulnerabilities are publicly known -- nobody has looked at this.

### Known internals (verified, starting points)
  0x17d38 hfs_mount, frame 0x40: reads 0x200 bytes from byte offset 0x400
    (0x17d6c-0x17d78), byteswaps the volume header (0x17f18) into global 0xad628,
    then 0x17da0-0x17db0 signature must be 0x4858 'HX' or 0x482b 'H+';
    0x17db4-0x17dcc blockSize in [0x200,0x10000] and a power of two.
    (Front door is checked -- the interior is the question.)
  **0x18a18, frame 0xb0 -- B-tree header/node walk.** nodeSize = be16 @hdr+0x12
    (0x18aa0-0x18aa8); node buffer = malloc(nodeSize) (0x18f08 -> 0x23908);
    binary search over numRecords = be16 @node+0xa (0x18b30-0x18b3c).
  0x18f48 -> 0x18e08 record accessor.
  0x18e88 catalog-key validator: DOES check key+2<=end, key+keyLength<=end,
    key+6+nameLength*2+2<=end (looks correct -- verify independently).
  0x18bf0-0x18c58 UTF-16 catalog-key comparison loop, uses
    min(searchNameLen, recordNameLen), byteswaps per code unit.
  Other HFS fns w/ frames: 0x17f68(0xb0 node read), 0x18258(0x70),
    0x18488(0x60 extent/fork), 0x185d4(0xa0), 0x188ec, 0x19018(0x60),
    0x19214(0x50), 0x19310(0x60).

## R20.1 — REAL MEMORY-SAFETY DEFECT FOUND: decompress_lzss (0x26878) ignores its
## destination-capacity argument. Currently POST-auth in iBoot.
VERIFIED byte-level:
    0x26878  b    #0x2687c
    0x2687c  mov  x9, sp
    0x26880  mov  x12, x0          ; save dst for return length
    0x26884  lsr  x1, x9, #4       ; <-- x1, the dstlen ARG, DESTROYED before use
    0x26890  sub  sp, x1, #1,lsl#12 ; 4 KiB LZSS ring buffer on stack
    0x26900  strb w5, [x0], #1     ; literal out -- NO bound on x0
    0x26944  strb w5, [x0], #1     ; match out   -- NO bound on x0
Loop terminates ONLY on input exhaustion (0x268d4/0x268ec/0x26910). Ring buffer
is correctly masked (w11=0xfff); only the OUTPUT pointer is unbounded. Max
expansion ~8.5x-16x. That x1 is a real capacity param is confirmed by caller
0xbf68 passing literal w1=0xbe00000 (max kernel size).
Three callers, ALL post-auth, all doing only a too-late `cmp w0,expected`:
  0x9c9c (image_load payload), 0xbf68 (kernelcache complzss), 0x28004 (iBootIm).
Signature ordering re-verified: IMG4 parse -> cert/sig -> AES -> **LZSS**.
=> Not useful for untethered as-is. **MUST be checked in LLB.dec and iBEC.dec**
   (/home/claude/fw/fwimg/) -- iBEC runs the restore USB stack and may have a
   pre-auth caller. That would be a genuine iBoot-family code-exec primitive.

## R20.2 — memboot (0x1c18) is a severity multiplier (tethered only)
getenv_uint("filesize") rejected >=0x10000001; range-checked via 0xff50; then
0x1fdc4 registers a **memory-backed block device over the attacker's buffer at
0x800000000**, and 0x11ddc->0x9120 (image scanner), 0x29ed8 (GPT), then the FS
layer all run against it. So a USB-only attacker in recovery can point the
ENTIRE storage-parsing stack (image scanner, GPT, APFS, HFS+) at fully
controlled memory with NO NAND access. Needs a host => does not itself serve
untethered, but it multiplies the severity of every storage parser bug.

## R20.3 — useful negatives from the inventory
  * **No LZFSE/LZVN anywhere in iBoot** (no bvx1/bvx2/bvxn magic, no matching
    immediates). LZSS (0x26878) is the ONLY decompressor. (So my earlier note
    about the LZFSE-compressed devicetree refers to data iBoot does not itself
    decompress with LZFSE -- recheck that claim.)
  * **No network stack.** bootp-response/ipaddr/gateway/ethernet appear ONLY as
    device-tree property names in the DT fixup. No TFTP/DHCP/BOOTP client.
  * **The serial console cannot inject commands in this build.** command_interpret
    (0x30260) has exactly ONE caller chain, all from the "usb req" task; no
    pointer to it exists elsewhere. Serial can only abort autoboot into recovery.
  * SysCfg (0x31584/0x31850/0x31734) is WELL bounded, incl. an explicit integer
    -overflow check (dataOff+len >= dataOff). Good reference for "correct here".
  * USB EP0 (0x1d9d8) and the command interpreter (0x30260) audited bounded.
  * No unbounded strcpy/strcat primitive in the image.

## R21 — USERSPACE GROUND TRUTH (job 587 + offline trust cache parse)

### NO SCRIPT INTERPRETER EXISTS ON THIS DEVICE. The cheap path is dead.
/bin has exactly TWO entries: **df, ps**. No sh/bash/zsh/dash, no perl, python,
lua, awk, osascript, PlistBuddy, env. So "trustcached interpreter + unsigned
script" -- which would have given untethered root code execution with no exploit
at all -- is NOT available here. Any code execution must come from corrupting a
signed binary's execution, or from abusing a signed binary's intended function.

### Complete binary inventory (live device, 2026-11-26)
/bin (2): df ps
/sbin (14): fsck fsck_apfs **fsck_hfs** ifconfig launchd mount mount_apfs
  **mount_hfs** mount_nfs mount_tmpfs newfs_apfs **newfs_hfs** route umount
/usr/bin (23): afktool ampctl codecctl csfdiagnose fm footprint hidutil
  hpmdiagnose kbdebug lsdiagnose ltop meminfo minidisplaytool modelcatalogdump
  modelmanagerdump nfsstat swift-inspect sysdiagnose taskinfo truncate umtool
  vm_stat zprint
/usr/sbin (29): BTAvrcp BTLEServer BlueTool absd addNetworkInterface arp
  aslmanager bluetoothd cfprefsd ckksctl distnoted fairplayd.T2
  filecoordinationd **hdik** ioreg mDNSResponder mDNSResponderHelper ndp netstat
  notifyd nvram otctl **pppd** **racoon** rtadvd skywalkctl spindump syslogd wifid
/usr/libexec: 227 entries (full list pending job 588)
/System/Library/LaunchDaemons: 269 plists. Frameworks: 153.

Notable parsers running as root, all trustcached:
  **hdik** (attaches disk images -- DMG/UDIF parser on data we control)
  **fsck_hfs / mount_hfs / newfs_hfs** (a crafted HFS+ volume has TWO consumers:
    these AND iBoot's own HFS+ driver -- see R20)
  **pppd** (CVE-2020-8597-era EAP overflow lineage), **racoon** (IPsec/KAME lineage)
  mDNSResponder, bluetoothd, wifid, syslogd, cfprefsd
  **nvram** (lets us set NVRAM vars from a boot-time daemon)
  mount_nfs + route/ifconfig/addNetworkInterface/rtadvd (an NFS-root or
    network-config-at-boot angle would move the surface to something we own)

### Static trust cache: EXACTLY 578 ENTRIES
Parsed offline from apple-StaticTrustCache.img4 (the Apple-personalised copy):
  payload 12740 bytes; version=1; uuid fc7918cf917b408f9b49432ba3c40906;
  entry_count=578; **22 bytes/entry = 20-byte cdhash + 2-byte flags (0x0002)**
  first cdhashes: 00c23931bf223c4b54cbbf0c1b730e89ec31493b,
                  00c59e2041a1d0eee179ac11956b1cbf4558f119,
                  00f8ee99603ec14871f7cae7a496bff30d0e1e7c
=> 578 is the COMPLETE allowlist of executable images (binaries + dylibs) on the
System volume. Anything not in it cannot run, which is why placing our own
Mach-O is useless and why the interpreter question mattered so much.

### The resulting attack shape (no interpreter available)
our data on the System volume -> parsed by a trustcached ROOT daemon that
launchd starts with arguments WE choose from mrm.plist -> memory corruption ->
ROP/JOP (**A8 has NO PAC, so no pointer-auth to defeat**) -> kernel bug ->
kernel r/w. Long chain, but it is the standard iOS jailbreak shape and every
link has public prior art on this era.
OPEN QUESTION being researched: does kernel r/w on iOS 13 actually let us BOOT
LINUX, or only run our code under audioOS each boot? Very different outcomes.

## R22 — KERNELCACHE EXTRACTED + DECOMPRESSED. The architecture question is ANSWERED.

### We now have the real kernel
apple-kernelcache.img4 -> IM4P 'krnl' -> payload `complzss` (adler 0x60e16085,
ulen 24945952, clen 12855398, type 1 = LZSS) -> **decompressed to
runner/files/kernel.macho, 24,945,952 bytes, ARM64 Mach-O (cffaedfe).**
Decompressor: runner/files/lz.py (standard Apple LZSS, N=4096 F=18 THR=2,
data starts at payload+0x180). Reproducible.
Confirmed: `Darwin Kernel Version 19.6.0: Fri Jun 26 21:16:39 PDT 2020;
root:xnu-6153.143.1~3/RELEASE_ARM64_T7000`. 155 distinct prelinked kext ids.
**AMFI is prelinked inside it** (com.apple.driver.AppleMobileFileIntegrity,
65/77 string hits) -- so AMFI's iOS-13 implementation, which no public source
documents, is available to us to read. Agent is disassembling it.

### tachy0n's portability blocker is REMOVED (verified)
All of tachy0n's heap-shaping dependencies are present in this kernelcache:
  IOSurfaceRoot 47, IOSurface 1091, IOGraphicsAccelerator2 23,
  IOAccelContext2 20, IOAccelerator 131, AGXAccelerator 44,
  IOMobileFramebuffer 343, and `lio_listio` present.
So the HomePod DOES ship the graphics stack. (cicuta_virosa's internal symbol
names are absent as strings, which is expected in a stripped release kernel and
proves nothing either way.)

### LIVE KERNEL BUGS on this exact build (research agent, with source diffs)
  * **CVE-2020-9859 / tachy0n** -- lio_listio race/double-free. Siguza:
    "iOS 13.0-13.5", "A8 through A13". We are on 13.4.8. Patched in 13.5.1.
    **Public MIT source: github.com/Siguza/tachy0n.** Reachable from the app
    sandbox, so a root launchd daemon is a superset. PRIMARY CANDIDATE.
  * **CVE-2021-1782 / cicuta_virosa** -- ipc_voucher UAF. Agent VERIFIED by
    source diff: in xnu-6153.141.1 `MACH_VOUCHER_ATTR_REDEEM` does
    `elem->e_made++` with NO lock; xnu-7195.81.3 wraps it in
    user_data_lock()/unlock(). **Never fixed in the 13.x branch.** Public code:
    github.com/ModernPwner/cicuta_virosa. Pure mach-voucher API, no entitlements.
  * **CVE-2020-27932 / CVE-2020-27950** -- fixed in 14.2 and backported to
    12.4.9, but **the 13.x branch ENDED at 13.7 (Sept 2020), before those
    November 2020 fixes** => every kernel bug fixed after Sept 2020 is a
    PERMANENT 0-day on this device. 27950 has public code (synacktiv) but is
    info-leak only.
  * OUT: oob_timestamp (fixed 13.3.1), sock_puppet/sock_port (<=12.x).
  * A8 has NO PAC (arrived with A12) and NO PPL => corrupted kernel-data
    function pointers are directly callable; P0's survey confirms non-PAC
    exploits are "substantially simpler". The tax we DO pay is **KPP**
    (watches __TEXT and __DATA.__const, panics on mismatch) => data-only
    patching. Irrelevant in the checkm8 flow since a pwned iBoot never loads
    the KPP monitor.

### ===== THE ARCHITECTURE, ANSWERED =====
Kernel exploitation does NOT give unsigned COLD boot -- the chain re-verifies
from mask ROM every power-on and nothing written to NAND is trusted. CONFIRMED
consistent with all public Linux-on-A8 work being tethered.
**BUT: kexec does.** Precedent = **axi0mX/ios-kexec-utils (`kloader`)**: "boot
LLB/iBoot/iBSS/iBEC image from a jailbroken iOS kernel", arm64 for iOS 7.0-8.4.1
with tfp0, auto-wake after 2s. So the shape that actually reaches the goal is:
    power on -> SIGNED audioOS boots -> our launchd job -> native code ->
    kernel exploit (tachy0n / cicuta) -> kexec m1n1/Linux
From the user's point of view the pod boots Nicotine by itself, no host. The
payload is never signature-checked because secure boot only gates the COLD path.
Costs/unknowns (agent's assessment, flagged as such): needs kernel CODE EXEC not
just r/w (realistic on non-PAC A8); **KPP is the biggest unknown** -- a kexec
must run code and tear down the MMU while KPP periodically checks; kloader's
arm64 support stopping at 8.4.1 is consistent with KPP-era friction; and the
m1n1 boot environment (boot-args struct, ADT pointer, memory map) must be
rebuilt from inside a running XNU rather than received from iBEC.

### THE STRUCTURAL GAP (the real blocker, stated honestly)
Trust cache = 578 cdhashes of Mach-Os. BLOCKED on iOS 13: inserted dylibs,
dylib hijacking, dlopen'd plugins, shared-cache patching, modified system
binaries, ad-hoc signed binaries -- every path needing OUR native code mapped
executable. WORKS: writing data/config files consumed by trusted binaries;
relocating trust-cached binaries (the cache is path-independent, hash-keyed);
launchd jobs with arbitrary Program/ProgramArguments/EnvironmentVariables/
UserName=root. PROBABLY WORKS but unverified: unsigned `#!` scripts via a
trust-cached interpreter (XNU's exec_shell_imgact never signs the script;
evasi0n did exactly this on iOS 6 with `#!/bin/launchctl`) -- **but R21 found
there is NO interpreter on this device anyway.**
=> A script/orchestration primitive cannot reach NATIVE code execution, which is
   what every kernel exploit needs. Bridging that gap requires one of:
   (a) a dyld-closure / loader LOGIC bug -- Fugu14 class (Linus Henze turned a
       dyld closure cache read from a writable path into unsigned code exec);
       dyld3 closures DO exist in 13.x. **Best remaining no-kernel-bug lead.**
   (b) a parser bug in a trustcached root daemon reading our file (agent on it).
   (c) accept one userland exploit as the launcher.
   (d) the iBoot HFS+ bug (R20) -- which would bypass this entire chain.

================================================================================
R23 — THREE PARALLEL AGENT AUDITS LAND. THE ARCHITECTURE CHANGES.
     2026-11-26 evening. Agents: HFS+ driver, LZSS reachability, userspace daemons.
================================================================================

R23.0 THE HEADLINE
------------------
The blocker recorded in R22 was: every kernel exploit needs native code, and the
trust cache blocks every route to mapping our own native code. That blocker is
now BYPASSED, not solved. The route is:

    launchd job -> a TRUST-CACHED Apple binary -> our file -> IN-KERNEL parser

No native code of ours is needed to reach a kernel parser. The data IS the
exploit. Three such binaries are confirmed present on this device.

R23.1 CONFIRMED PRESENT ON THIS DEVICE (job 587, System volume, /usr/sbin)
---------------------------------------------------------------------------
  hdik      <- attaches a disk image straight to the in-kernel DiskImages driver
  pppd      <- `notty` makes it read PPP frames from fd 0
  racoon    <- `-f <file>` = yacc/lex config parser, and it does NOT sandbox
               itself on iOS (sandbox_init is wrapped in
               `#if !(TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR)`)
  mount_hfs, fsck_hfs, mount_apfs, newfs_hfs, mount_tmpfs, mount_nfs  (/sbin)
  syslogd, aslmanager, absd, bluetoothd, BTLEServer, BlueTool, wifid, cfprefsd
  /usr/bin: afktool ampctl codecctl fm hidutil minidisplaytool modelcatalogdump
            modelmanagerdump swift-inspect umtool truncate

** CORRECTION TO MYSELF, recorded so I do not repeat it: I briefly concluded from
`fw/ros_files.txt` that pppd and racoon were absent. That file is a PARTIAL OTA
asset listing (1,428 entries; /usr/libexec shows 48 there vs 227 on the device).
It CANNOT be used to prove absence of anything. Job 587's device-side inventory
is the authority. **

R23.2 KERNEL-SIDE PREREQUISITES — ALL CONFIRMED FROM OUR OWN KERNELCACHE
-------------------------------------------------------------------------
The daemon agent listed three "device checks that cost one boot each". All three
answered for free from /home/claude/kc/kernel.macho (our decompressed, signed
17M61 kernelcache). ZERO boots spent.

  com.apple.driver.DiskImages                  IOHDIXController.kext v493.0.0,
                                               OSBundleRequired=Root
  com.apple.driver.DiskImages.KernelBacked     IOHDIXHDDriveInKernel,
                                               KDIDiskImageNub
  com.apple.driver.DiskImages.UDIFDiskImage    <-- THE COMPRESSED-DMG PARSER
  com.apple.driver.DiskImages.FileBackingStore KDIFileBackingStore on KDIURL
  com.apple.driver.DiskImages.RAMBackingStore  KDIRAMBackingStore, scheme "ram"
  com.apple.driver.DiskImages.ReadWriteDiskImage
  classes: KDIUDIFEncoding KDIUDIFCacheBuffer KDIUDIFCacheObject KDIEncoding
           KDISecondaryEncoding KDIDiskImageNubUserClient KDIBackingStore
  "UDIF" string present x5.

  com.apple.nke.ppp / .l2tp / .pptp  started by AppleBSDKextStarterVPN
  ptmx present.  com.apple.filesystems.hfs present (in-kernel HFS).
  com.apple.driver.AppleMobileFileIntegrity present (AMFI prelinked).

So the UDIF/DMG chunk-table parser runs IN THE KERNEL on this exact build, and
hdik is the trust-cached front door to it.

R23.3 UNPATCHED CVEs AT 13.4.8 (= tvOS 13.4.8 = the iOS 13.6 fix set, 15 Jul 2020)
-----------------------------------------------------------------------------------
Anything first fixed in iOS/tvOS 14.0 (16 Sep 2020) or later is LIVE here.
The 13.x branch ended at 13.7 (Sept 2020), so every kernel bug Apple fixed after
that date is a permanent 0-day on this device.

  *** CVE-2020-9965 / CVE-2020-9966  -- "Disk Images", Proteas. Both:
      "An application may be able to execute arbitrary code with kernel
      privileges. An out-of-bounds read was addressed with improved input
      validation." Fixed tvOS 14.0 / iOS 14.0. UNPATCHED HERE.
      No public PoC or writeup exists. Reachable via hdik + our DMG.
      -> THIS IS THE PRIMARY TARGET. Agent now drilling the kernelcache for it.

  *** CVE-2020-27932 -- XNU turnstile / special-reply-port type confusion,
      Ian Beer, exploited in the wild Oct 2020. SOURCE-VERIFIED unpatched in the
      xnu-6153 series this device runs:
        xnu-6153.141.1 host_notify.c host_request_notification():
          if (!ip_active(port) || port->ip_tempowner ||
              ip_kotype(port) != IKOT_NONE)
        xnu-7195.50.7.100.1 (iOS 14), same function:
          if (!ip_active(port) || port->ip_tempowner || port->ip_specialreply ||
              ip_is_kolabeled(port) || ip_kotype(port) != IKOT_NONE)
      The added ip_specialreply test IS the patch. Absent in 6153.
      MIG routine takes plain host_t (mach_host_self()) -> NO entitlement,
      NO sandbox escape, NO privilege required. NVD lists fixes in 12.4.9 /
      14.2 / 10.15.7 -- no 13.x release ever carried it.
      PoC: Project Zero tracker issue 2107; RCA at
      googleprojectzero.github.io/0days-in-the-wild/0day-RCAs/2020/CVE-2020-27932.html
      Being re-verified against the compiled kernel binary now (source-level
      inference about which XNU tag Apple shipped is NOT the bytes on the device).

  Companions, all fixed only in 14.0+: CVE-2020-27950 (kernel memory disclosure,
  the info-leak partner of 27932), CVE-2020-9975 (kernel UAF, Tielei Wang),
  CVE-2020-10013 (Wi-Fi logic -> kernel privs, Yu Wang), CVE-2020-27930
  (FontParser, in-the-wild; NVD lists only 12.4.9 and 14.2, never 13.x),
  CoreAudio CVE-2020-9954/9960/10017/27908/27909, Audio CVE-2020-27910/27916,
  libxml2 CVE-2020-9981/27911, Crash Reporter CVE-2020-10003 (symlink).
  tachy0n/CVE-2020-9859 (13.0-13.5) also still live; heap-shaping deps verified
  present in R22.

R23.4 THE pppd notty DELIVERY TRICK  (the best non-kernel idea)
----------------------------------------------------------------
  Helpers/pppd/tty.c:271 registers `notty`.
  tty.c:808  } else if (notty) { if (!start_charshunt(0, 1)) return -1; }
  => fd 0 / fd 1. ZERO TARGET_OS_* guards anywhere in tty.c.
  launchd.plist StandardInPath maps an arbitrary file to the job's stdin;
  StandardOutPath/StandardErrorPath are created if absent (free log sink).

  Net effect: pppd's entire REMOTE attack surface -- LCP, IPCP, CCP, PAP, CHAP,
  MS-CHAPv2, EAP, ACSP/ACSCP (Apple-only), multilink -- becomes a LOCAL
  FILE-PARSING surface in an unsandboxed root process at every cold boot, with
  no network, no peer and no hardware.

  Apple's eap.c is NOT upstream pppd's: 1,413 lines, $Id eap.c,v 1.25 2005 ...
  lindak, Apple functions EapReceiveRequest/EapReceiveResponse/EAPServerProcess/
  EAPClientProcess. Upstream's eap_request/eap_response do not exist in it.
  Apple-private, never publicly audited. Candidate flagged but NOT confirmed:
  BCOPY(eap_out->data, outp, eap_out->data_len) at eap.c:1048 and :1184 into the
  fixed outpacket_buf. Agent now settling it, plus tag-diffing for silent fixes.

  NOTE: options_from_file() is `#if TARGET_OS_OSX` and a no-op on iOS, so
  /etc/ppp/options and peers/* are NOT a surface. Everything goes on argv.
  BUT auth.c reads /etc/ppp/pap-secrets and /etc/ppp/chap-secrets on iOS with no
  guard -- and we can write those too. Two attacker files feeding one process.

R23.5 TRUST CACHE IS cdhash-KEYED, NOT PATH-KEYED  (useful lemma, INFERRED)
-----------------------------------------------------------------------------
Apple: the static trust cache stores each binary "as a sorted code directory
hash"; "If the hash is in the trust cache, the executable mappings created for
the binary will be granted platform privileges." Nothing binds a cdhash to a
path. INFERENCE: a COPY of a trust-cached binary at an arbitrary path should
execute. That would satisfy hard-coded-path execs. It does NOT manufacture an
interpreter: execle("/bin/sh","sh","-c",cmd) hands our binary argv
["sh","-c","<string>"], which nothing in our inventory does anything with.
UNTESTED on device. Worth one cheap experiment.

R23.6 HARD NEGATIVES ADDED THIS ROUND — stop spending effort here
------------------------------------------------------------------
(a) LZSS / ALL iBoot DECOMPRESSORS: POST-AUTH EVERYWHERE. CLOSED.
    decompress_lzss is byte-identical in LLB at file 0x1c274 (LLB base VA
    0x180380000, derived from absolute pointers in data, not assumed).
    iBEC.dec md5 == iBoot.dec md5 == 4060846107b8369243acbbdc8368b647, same
    692,800 bytes -> **iBEC ADDS ZERO NEW CODE SURFACE**.
    Complete entry-point sets (no indirect dispatch, no pointer in data):
      iBoot 0x26878 <- 0x9c9c, 0xbf68, 0x28004
      LLB   0x1c274 <- 0xc770 only
    Every one sits behind an UNCONDITIONAL RSA manifest check: iBoot
    0x973c bl 0x33e38 / LLB 0xc550 bl 0x1ecf0 (160/160 mnemonics identical,
    same `cmp x4,#0xc00` RSA modulus dispatch). Exhaustive branch-edge scan:
    no edge bypasses the gate. image_load has exactly one entry in both images.
    The applelogo picture is VERIFIED FIRST, THEN decompressed.
    ** CORRECTION: the earlier note that 0x3306c/0x34d74/0x35198/0x351b4/0x3504c
    are the signature step is WRONG. Those five are inside a block skipped by
    `0x9874 ldrb w8,[sp,#0x131]; 0x9878 cbz w8,#0x9af0`; [sp,#0x131] is
    struct+0x39, written only by the IMG4 'EKEY' tag handler. That block is
    PAYLOAD KEY-UNWRAP + AES-CBC DECRYPT and is skipped for an unencrypted
    payload. Reading it as "the signature check" would wrongly suggest an
    unencrypted image skips authentication. It does not; it skips decryption. **
    ** RETRACTION: "no LZFSE in iBoot" was WRONG. iBoot has a full codec
    framework (0x3a79c scratch-size, 0x3a7f4 decode) dispatching LZ4 0x100,
    LZ4-raw 0x101, zlib/deflate 0x205/0x505, LZFSE/LZVN/LZFSE_IBOOT
    0x801/0x802/0x891, plus 0x8a1/0x900/0x901. The bvx1/bvx2/bvx-/bvxn magics
    are mov/movk immediate PAIRS (0x7662 + 0x3178 etc.), not ASCII -- which is
    exactly why grepping for "bvx" found nothing. Also post-auth (two callers,
    zero ADR refs). LLB has no second decompressor and hard-rejects any
    compression type but LZSS (0xc720 ldr w8,[sp,#0xe8]; cbnz -> fail). **
    The defect itself is real and documented for completeness: the loop has no
    notion of an output limit (x1/dstlen is never used -- the
    `lsr x1,x9,#4 / sub sp,x1,#0x1000` is just the alloca idiom), max expansion
    ~8.47x, so a holder of a VALID SIGNED image can overrun by ~7.4x the
    destination. Relevant to downgrade/mix-and-match, NOT a secure-boot break.

(b) iBoot HFS+ DRIVER (0x17d38-0x19600): three defects, NO WRITE PRIMITIVE.
    It explicitly blocks xerub's bug class with a panic and implements the
    B-tree capacity idiom correctly, including a 32-bit overflow guard
    (0x18e08: `ccmp w9,w2,#2,hs` then `b.hi` rejects the wrap).
    F1. Heap OOB READ up to 0x5e bytes: 0x185d4 (readdir) hands a raw record
        pointer to 0x188ec with no `dataPtr + recordSize <= nodeEnd` check,
        where the analogous 0x18a18 path DOES check (0x18d08-0x18d14).
        BUT: readdir is reached only from 0x3ed0 ("/boot/iboot_firmware") and
        0x444c, both AFTER a 20-byte boot-manifest hash comparison -> NOT
        pre-auth. And the only in-image consumer (0x24a0) reads just dirent+8
        and dirent+0xa, discarding the leaked size/mtime. Leaves a 1-bit
        panic oracle on adjacent heap, nothing more.
    F2. Heap OOB READ <= 9 bytes, PRE-AUTH: 0x18b74 `cbz w25` routes only the
        catalog path to the key validator 0x18e88; the extents path falls
        through and dereferences recStart+4 and +8 with keyLength attacker-set
        to 0. Values only steer the binary search. No disclosure, no write.
    F3. Unbounded iteration x2 -> pre-auth BOOT HANG (DoS, no corruption):
        extent walk 0x17fe8-0x1807c has no cap and no progress requirement on
        w20 (zero blockCount extents spin forever); readdir leaf-chain
        0x18878-0x188a4 has no fLink cycle detection and never checks the node
        kind byte. Explicitly NOT xerub's primitive: the overflow-extent buffer
        is allocated ONCE (0x18010 cbnz guard), so there is no heap-growth
        engine, and re-entry is cut by a panic (0x18028 `cmp w24,#3` -> 0x18180),
        max recursion depth 2.
    Verified clean: nodeSize validated (power-of-two, >=0x200) before any use;
    alloc size == read length everywhere; p0sixninja's blockCount bug ABSENT
    (read length always clamped to the caller's buffer); UTF-16 conversions both
    bounds-checked; path recursion capped at 48; B-tree descent structurally
    cycle-proof via a height/kind invariant.
    => The 8th storage surface is NOT clean, but what is wrong with it is two
    bounded OOB READS and two hangs. No 64-bit De Rebus Antiquis. Not
    exploitable for code exec on this target.

(c) Everything that popen()s or shells out is DEAD (no /bin/sh): pppd
    connect/disconnect/pty/welcome/init all execle("/bin/sh",...) at main.c:2260;
    syslogd popen(_PATH_WALL).
(d) Every plugin/bundle/dylib-from-config path needs the trust cache: pppd
    plugin/plugin2 -> sys_loadplugin -> CFBundleCreate/CFBundleLoadExecutable
    (sys-MacOSX.c:3428); eapplugin -> sys_eaploadplugin (:3465). A system
    executable has no Team ID and "can link only to libraries that ship with
    the system". Confirmed dead.
(e) syslogd/aslmanager load NO code from config -- whole tree grepped, only the
    two popen(_PATH_WALL) sites, no dlopen, no module path.
(f) CVE-2020-8597 (pppd EAP rhostname overflow) DOES NOT APPLY, despite Apple's
    patchlevel.h declaring VERSION "2.4.2": rhostname appears only in upap.c:409
    (slprintf) and chap.c:463 (explicitly clamped), and eap_request/eap_response
    do not exist anywhere in Apple's tree. Being independently re-verified.
(g) CVE-2020-3840 (racoon config-file off-by-one -> code exec) is PATCHED at
    13.3.1. Patch located by tag diff ipsec-326.40.1 -> 326.81.1, cfparse.y
    addrwins rule: `> MAXWINS` -> `>= MAXWINS`. One character. The parallel
    dns4_index/MAXNS check is already `>=` in every tag, so no free sibling.
    Keep 3840 as the TEMPLATE, not the target: cfparse.y + cftoken.l remain
    ~2,300 lines of grammar over a file we control in an unsandboxed root
    daemon where Apple has already shipped one code-exec bug.
(h) Bluetooth-era CVEs all patched at or below 13.6. bluetoothd/BTLEServer/
    BlueTool are a poor bet. No Apple mDNSResponder CVE found 2018-2021.
(i) A root daemon compromise is ONLY a stepping stone: already root; cannot
    write the System volume at runtime (snapshot-mounted; the published APFS
    work presupposes kernel R/W); cannot load unsigned code. Its sole value is
    as a ROP host. Which is fine -- Project Zero's own "Remote iPhone
    Exploitation Part 3" states that for "devices without pointer
    authentication (PAC), namely the iPhone X and earlier" the approach is to
    "Perform a stack pivot and implement a payload in ROP". A8 is squarely in
    the non-PAC bucket, and the needed chain is short: mach_host_self ->
    host_request_notification -> mach_msg -> receive, all ordinary libsystem
    exports already linked into pppd/racoon/hdik.

R23.7 WHAT IS QUEUED / RUNNING
-------------------------------
Job 588 (queued, waiting romdfu): full /usr/libexec 227-entry inventory +
  launchd caches + live mrm.plist.
Job 589 (queued behind it, READ-ONLY, no cold boot): the decisive cheap
  experiments -- (Q0) the RAMDISK's own binary inventory, (Q0b) restore-kernel
  identity + boot-args, (Q3) AMFI/codesign enforcement sysctls on the restore
  kernel [if relaxed, we get native code exec immediately], (Q1) can the ramdisk
  EXEC a System-volume binary at all (hdik/pppd/racoon/mount_hfs cross-volume),
  (Q2) hdik's full usage, (Q4) bounded `ioreg -c IOHDIXController` + /dev nodes,
  (Q5) which Data-volume paths are writable for DMG staging.
Agents drilling: (1) the in-kernel UDIF/blkx chunk parser for 9965/9966;
  (2) CVE-2020-27932 against the compiled kernel + the ipc_port offsets an
  exploit must hardcode; (3) Apple's private eap.c + ACSP, incl. tag-diffing
  for silent fixes.

================================================================================
R24 — JOBS 588/589 + THE AMFI VERDICT.  ONE ALARM, ONE BIG GREEN LIGHT.
      2026-11-26 ~19:50 PST
================================================================================

R24.0 *** ALARM: THE POD IS ALMOST CERTAINLY NOT ON 13.4.8 ANY MORE ***
-------------------------------------------------------------------------
Everything in R23 was aimed at audioOS 13.4.8 / 17M61. Three independent pieces
of evidence from jobs 588 and 589 say the System volume on the bench pod is a
CURRENT audioOS build (tvOS 26/27 era, late 2026):

  1. /usr/libexec (job 588, 227 entries) contains **alwaysonexclavesd**, plus
     betaenrollmentd, aidearlyboot, BiomeSync, centaurid, aonsensed.
     Exclaves are a 2024+ (iOS/tvOS 18+) feature. They did not exist in 13.x.
  2. Job 589, running System-volume binaries under the ramdisk:
       /mnt1/usr/sbin/pppd   -> dyld: Symbol not found: _CFAllocatorAllocateTyped
                                "(built for tvOS 27.2 which is newer than
                                 running OS)"
       /mnt1/usr/sbin/racoon -> dyld: Library not loaded: NetworkExtension
                                "(built for tvOS 27.2 ...)"
     A 13.4.8 binary would report tvOS 13.4, which is OLDER than the ramdisk's
     17.5 -- dyld would not say "newer".
  3. System-volume mtimes are Nov 6 2026 and Nov 26 2026. The only snapshot is
     com.apple.os.update-8AD664B27CAE667B82D0274EC1D1AC20B4220C5D.

MOST LIKELY CAUSE: the pod was restored to 13.4.8 and then SET UP with a phone.
HomePods force an OTA update during/after setup. It updated itself out from
under us. (Consistent with the earlier observation that it kept rebooting into
setup mode, and with nvram `obliteration ... Reason: HomePodSetup-AuthInProgress`
seen back in job 414.)

CONSEQUENCE: every unpatched CVE lined up in R23 -- 9965/9966 (Disk Images),
27932/27950 (XNU Mach), 9975, 10013, tachy0n/9859 -- is PATCHED on a current
build. The whole R23 attack plan is aimed at a version the pod is no longer
running.

NOT YET 100% CONFIRMED: I have not yet read SystemVersion.plist. Job 590 is
queued to do exactly that and settle it. Treat R24.0 as very strong evidence,
not yet proof. **Do not discard the R23 work -- it is correct FOR 17M61.**

WHAT TO DO ABOUT IT:
  (a) Restore to 17M61 using the SAVED APTICKET. This is precisely the payoff of
      the blob work: R21 proved a saved APTicket + public stock IPSW payloads
      reconstructs Apple's per-device personalized chain BYTE-IDENTICALLY (four
      components, four exact md5 matches). Apple no longer signs 17M61; the
      ticket is the only way back.
  (b) *** NEW OPERATIONAL RULE: AFTER RESTORING TO 17M61, DO NOT COMPLETE SETUP
      AND DO NOT LET THE POD REACH THE INTERNET. *** No phone handoff, no wifi
      credentials. Setup is what triggers the OTA. If we need it "set up", do it
      on a network with no route out, or block it at the UDM.
  (c) Re-verify the AMFI result (R24.1) on whatever build we end up on, because
      the instruction-level proof below is specifically AMFI-367.140.2 / 17M61.

R24.1 *** AMFI VERDICT: THE SCRIPT PRIMITIVE IS REAL. VERIFIED, NOT INFERRED ***
---------------------------------------------------------------------------------
Question asked: does AMFI on this build block execution of an UNSIGNED `#!`
script whose interpreter is a legitimately trust-cached binary?

ANSWER: **NO. It cannot.** AMFI's mpo_vnode_check_exec is TEN instructions and
has no failing path at all.

  AMFI build string from the binary: AppleMobileFileIntegrity-367.140.2,
  CFBundleVersion 1.0.5, SDK appletvos13.4.internal, DTSDKBuild 17M59.
  kernel.macho sha256 335179715ad4d3cfb78bffd09746f78660ee13bc2f9eb95d6d4859d336cf60da

  AMFI mpo_vnode_check_exec = VA 0xfffffff007c9c400, FILE OFFSET 0xc98400:
    00c98400: fd7b bfa9 fd03 0091 e700 00b4 e800 40b9
    00c98410: 0805 1832 e800 00b9 0000 8052 fd7b c1a8
    00c98420: c003 5fd6 be01 0094
      stp x29,x30,[sp,#-0x10]!
      mov x29,sp
      cbz x7, 0x...c424          ; csflags==NULL -> assert (dead code, see below)
      ldr w8,[x7]
      orr w8,w8,#0x300           ; |= CS_HARD|CS_KILL   (0x32180508 hand-decoded:
                                 ;  N=0 immr=24 imms=1 -> bits 8,9 -> 0x300)
      str w8,[x7]
      mov w0,#0                  ; return 0 == ALLOW
      ldp x29,x30,[sp],#0x10
      ret
  x2 (scriptvp) and x4 (scriptlabel) are NEVER read. Nor x0,x1,x3,x5,x6.
  The function touches ONLY x7. The set of conditions under which it returns
  non-zero is EMPTY. The one non-zero exit is assert(csflags) at
  AppleMobileFileIntegrity.cpp:1934 -- and it is unreachable because the kernel
  always passes x7 = &imgp->ip_csflags.

  Located rigorously, not guessed:
   - kmod_info entry 2 -> com.apple.driver.AppleMobileFileIntegrity v1.0.5;
     AMFI text = [0xfffffff007c95ec0, 0xfffffff007c9cb40).
   - mac_policy_ops = 0xfffffff0074ce8c0 (file 0x4ca8c0, __DATA_CONST.__const),
     registered at 0xfffffff007c9a714 bl mac_policy_register.
   - ANCHOR CHECK: 0x74ce8c0 + 0xa78 = 0x74cf338 = mac_policy_conf, and
     struct mac_policy_ops in xnu-6153.141.1 has exactly 335 fn ptrs = 0xa78
     bytes. Layout anchored exactly.
   - mpo_vnode_check_exec is field 258 -> ops+0x810; stored once at
     0xfffffff007c9a688 `str x9,[x8,#0x810]` with x9 = adr 0xfffffff007c9c400.
     Only ONE code ref to the ops base exists anywhere in __TEXT_EXEC, and AMFI's
     mpo_policy_initbsd (0xfffffff007c9c1e0) is a bare `ret`, so no late rebind.
   - Independently cross-checked three ways: (i) the kernel-side
     mac_vnode_check_exec at 0xfffffff007c2a7d8 loads ops+0x810 and marshals the
     exact 10-arg prototype (x2=imgp->ip_scriptvp @+0x2c8, x4=ip_scriptlabelp
     @+0x2c0, x7=&ip_csflags @+0x2d0); (ii) Sandbox's statically-initialised ops
     table at 0xfffffff00755e648 decodes to 139 sensible hook names with the same
     field order -- 139 independent confirmations; (iii) AMFI's own 18-hook set
     is internally coherent.

  The script path is fully present and reached:
   - execsw at 0xfffffff0074b1698 has an "Interpreter Script" entry;
     exec_shell_imgact = 0xfffffff007a2932c checks '#'(0x23) then '!'(0x21),
     refuses nesting on IMGPF_INTERPRET, parses the interpreter path up to
     IMG_SHSIZE 0x200. **It contains no code-signing, cdhash, trust-cache or
     MACF call whatsoever.** The script's bytes are consumed as DATA.
   - exec_activate_image's -3 handler (0xfffffff007a2cc2c..0xfffffff007a2cca8)
     sets imgp->ip_scriptvp = ip_vp and branches back to `again:`, so
     mac_vnode_check_exec runs a SECOND time with scriptvp set -- and AMFI
     ignores it and returns 0.
   - mac_vnode_check_signature (0xfffffff007c2ad38) has exactly two callers,
     both in the ubc_subr.c CS-blob region. It is never reached for a shebang
     file, because exec_mach_imgact bails on the bad magic before any
     ubc_cs_blob_add.
  Preconditions that DO still apply: the script file needs the execute bit and a
  mount that is not noexec (exec_check_permissions, inlined ~0xfffffff007a2ca60).
  Setuid is stripped for interpreted images.

R24.2 BUT STEP 3 IS RED: A SCRIPT CANNOT REACH NATIVE CODE ON THIS BUILD
--------------------------------------------------------------------------
AMFI mpo_file_check_mmap = 0xfffffff007c99c60:
    bl cs_enforcement ; tbz w23,#2 -> skip   ; !(prot & VM_PROT_EXECUTE)
    bl 0xfffffff007c99ce4                   ; validate mapping
    tbnz w0,#0 -> allow ; mov w0,#1          ; <-- DENY
  and on the non-exec path:
    ldr w8,[x19] ; and w8,w8,#0xfffffffb ; str w8,[x19]   ; maxprot &= ~EXEC
So: cannot mmap a file PROT_EXEC without a valid cdhash, AND mapping it non-exec
strips VM_PROT_EXECUTE from *maxprot*, so it can never be mprotect'd to exec
later. Deny reasons (strings): "mapped file has no cdhash, completely unsigned?
Code has to be at least ad-hoc signed.", "mapped file has wrong signer type",
"mapped file has no Team ID and is not a platform binary".
  mpo_proc_check_mprotect = 0xfffffff007c9c2f0 is two instructions:
    ubfx w0,w4,#5,#1 ; ret     ; deny iff VM_PROT_TRUSTED(0x20) requested
  mpo_proc_check_map_anon = 0xfffffff007c9c2f8: returns 0 unless flags&0x800
    (VM_FLAGS_MAP_JIT); the MAP_JIT path then needs device-unlocked + entitlement.
=> The script primitive gives LAUNCH and ORCHESTRATION of signed components. It
   does NOT give shellcode. Native code still requires a memory-corruption bug
   in an already-trust-cached binary (which is exactly why hdik/pppd/eap.c are
   the targets) or an iBoot-side bug.

R24.3 cs_debug_* SYSCTLS: WRONG DIRECTION, CLOSED
---------------------------------------------------
vm.cs_force_kill / cs_force_hard / cs_debug / cs_debug_fail_on_unsigned_code /
cs_all_vnodes are all RW-by-root, no entitlement, present in RELEASE (backing
vars 0xfffffff008774b18..b30, handler sysctl_handle_int). But
cs_debug_fail_on_unsigned_code has exactly two consumers, both in AMFI, and both
ADD a kill for unsigned code. Clearing it (the default) permits nothing.
The real knob, cs_enforcement_disable, is a BOOT-ARG parsed in AMFI init
(0xfffffff007c9a4f4 PE_parse_boot_argn) and is gated on a dev/internal check
that PANICS otherwise -- and boot-args is unreachable on this unit anyway
(console setenv is gated to 4 names; see the R-series setenv work).
CONFIRMED BY JOB 589 on the restore kernel: all of
security.mac.amfi.get_out_of_my_way, vm.cs_enforcement_disable,
security.mac.amfi.allow_everything, kern.cs_enforcement_disable are
"unknown oid". vm.cs_force_kill=0, vm.cs_all_vnodes=0, vm.cs_debug=0.

R24.4 LOADABLE TRUST CACHE: DEAD END, CLOSED
----------------------------------------------
AppleMobileFileIntegrityUserClient::loadTrustCache, dispatch ~0xfffffff007c960d8,
selectors 2 (plain) and 7 (with external manifest). Gate at 0xfffffff007c961f4:
requires com.apple.private.amfi.can-load-trust-cache, else kIOReturnNotPrivileged
(0xe00002c1). Requires device-unlocked or it forces dry_run=1 ("AMFI: Trying to
load a trust cache while device is locked, only performing dry run."). And the
blob must carry a REAL Apple Image4 signature validated against the SoC:
"AMFI: Failure validating Image4 trust cache, error: %d", plus AppleImage4's
"Image4: Invalid board id / Invalid chip id / Invalid ecid / Invalid epoch /
Manifest hash check failed / Payload hash check failed", plus an anti-replay
nonce domain com.apple.private.img4.nonce.trust-cache.
The literal "com.apple.private.amfi.can-load-trust-cache" occurs EXACTLY ONCE in
the whole 24 MB kernelcache -- AMFI's own string -- so no kext holds it.
(can-execute-cdhash / can-load-cdhash also appear, but in __TEXT.__const as part
of the compiled Sandbox profile collection's string tables, i.e. names used in
sandbox predicates, NOT entitlements granted to anything.)
Even a binary holding the entitlement would not help: the Image4 manifest is
ECID/chip/board/production personalised and not forgeable offline.
Open item folded into job 590: an on-disk entitlement sweep with the ramdisk's
own `ldid`.

R24.5 JOB 589 FACTS WORTH KEEPING
-----------------------------------
*** THE RESTORE RAMDISK RUNS A MODERN KERNEL, NOT 13.4.8: ***
  kern.version: Darwin Kernel Version 23.5.0: Wed Apr 17 21:50:54 PDT 2024;
                root:xnu-10063.123.2~1/RELEASE_ARM64_T7000
  kern.osversion 21L569   kern.osrelease 23.5.0   (= tvOS 17.5)
  hw.machine AudioAccessory1,1   hw.model B238aAP
  kern.bootargs: rd=md0 debug=0x2014e -v wdt=-1 nand-enable-reformat=1
                 -restore serial=3
  sshrd boots: iBSS 200974, iBEC 788750, logo 33014, ramdisk 154932945,
               devicetree 23001, trustcache 10913, kernelcache 19488170
=> The ramdisk is NOT a test vehicle for any 13.4.8 kernel bug. A 2024 kernel
   has all of them patched. Kernel-bug testing MUST happen on the real audioOS
   boot. The ramdisk is for staging, inspection and pipeline validation only.
   (It does prove the pod will boot a signed 17.x kernelcache tethered.)

*** "NO INTERPRETER ON THIS DEVICE" APPLIES TO THE SYSTEM VOLUME ONLY. ***
The RAMDISK has a full toolbox. Correcting R21's phrasing, which was about
audioOS /bin (df, ps only):
  /bin (21): bash cat chmod cp date dd expr hostname kill launchctl ln ls mkdir
             mv pwd rm rmdir sh sleep stty sync
  /sbin (14): apfs_hfs_convert fsck fsck_apfs fsck_hfs halt launchd mount
             mount_apfs mount_hfs mount_tmpfs newfs_apfs newfs_hfs reboot umount
  /usr/bin (68): TiSerialFlasher ampctl arch binbag chflags clear cut du false
             file find fs_usage grep gunzip gzip head hexdump hostinfo id
             img4 img4tool killall ldid ldid2 less login lsmp more
             mount_filesystems nano nohup nvmefwupdater passwd peppytool
             plconvert printf renice reset rnano sc_usage scp screen script sed
             seq sftp snaputil split sqlite3 stat sw_vers syslog tail tar tee
             time true tset uname update_mcdp29xx usbcfwflasher vm_stat w wc
             what which xargs xxd
  /usr/sbin (12): asr chown hdik ioreg joreg kextstat ltop mtree netstat nvram
             sysctl syslogd
  /usr/local/bin (16): dbclient dropbear dropbear.orig dropbearconvert
             dropbearkey filemon jlutil lsdtrip.arm64 netbottom procexp
             restored_external restored_update shaihulud ssh syscfg_read wget
  /usr/libexec (7)
NEW TOOLS THIS UNLOCKS: ldid/ldid2 (entitlement dump AND pseudo-signing),
img4/img4tool, snaputil, sqlite3, plconvert, xxd, hexdump, file, find, grep,
sed, tar, split, stat, kextstat, sysctl, asr. `hdik` is on the ramdisk too.
So R20's "no `tr`/`strings`/`cmp`/`od`" stands, but `sed`, `cut`, `xxd` and
`hexdump` are all available as substitutes.

CROSS-VOLUME EXEC FROM THE RAMDISK -- partial, and the limit is LINKING, not
code signing:
  /mnt1/usr/sbin/hdik      RAN. "hdik: no image specified" + full usage.
  /mnt1/sbin/mount_hfs     RAN (symlink -> /System/Library/Filesystems/hfs.fs/)
  /mnt1/usr/sbin/nvram     RAN, full usage incl. `-b` (set var from binary file)
  /mnt1/usr/sbin/pppd      dyld: missing _CFAllocatorAllocateTyped
  /mnt1/usr/sbin/racoon    dyld: NetworkExtension not loaded, "no dyld cache"
=> The trust cache did NOT block any of these. pppd/racoon fail only because the
   ramdisk has no dyld shared cache for the System volume's (newer) frameworks.

hdik's REAL option set (from the device, not the man page):
  hdik [options] <image> | hdik -e <device> | hdik -help
  options: -nomount | -drivekey <key>=<value> | -encryption <enckey+hmacsha1key>

/dev: disk0 disk0s1 disk1 disk1s1 disk1s2 disk1s3 disk2 disk3 disk4,
      ptmx + ptyp0..ptype  (so pppd's pty requirement is satisfiable)
Writable for staging: /mnt1/private/var/tmp, /mnt1/private/var/mobile/Media,
      /mnt1/private/var/root.  /mnt2 is READ-ONLY.
(Script nit: my Q5 printf/echo interleaved the /mnt2 and /var/root lines; the
 values above are correct, read in order.)

R24.6 STILL RUNNING / NEXT
----------------------------
Job 590 QUEUED (read-only, needs one DFU cycle): SystemVersion.plist +
  RestoreVersion.plist to settle R24.0; `file` on System binaries for their
  build version; bounded `ldid -e` entitlement sweep for
  can-load-trust-cache / can-execute-cdhash / can-load-cdhash; bounded grep of
  /usr/sbin + /usr/libexec for the same literal; a LaunchDaemon plist as a
  template; /usr/standalone/firmware/FUD listing.
Agents still drilling: in-kernel UDIF/blkx parser for 9965/9966; CVE-2020-27932
  against the compiled kernel + ipc_port offsets; Apple's private eap.c + ACSP
  with tag-diffing for silent fixes.

================================================================================
R24.7 *** CORRECTION TO R24.0 — I JUMPED TO THE WRONG CONCLUSION ***
       2026-11-26 20:05 PST.  Nic pushed back with better evidence.
================================================================================
Nic's Home app reports the pod is STILL ON 13.4.8, and from running a HomePod
repair business he has NEVER seen a 13.4.8 pod successfully self-update — the
known behaviour is that they look like they are trying, indefinitely.

Re-auditing my own R24.0 evidence:
  - The mtimes (Nov 6 / Nov 26 2026) were WORTHLESS as evidence. A restore writes
    every file, so the mtime is just when Nic last restored. Retracted.
  - That leaves `alwaysonexclavesd` et al. and the dyld "built for tvOS 27.2"
    message. BOTH came from the same mount: /mnt1.

And /mnt1 is NOT what boots. sysvol-mount2.sh does:
    mount_apfs /dev/disk1s1 /mnt1        <-- the LIVE volume
But our own earlier work on the boot path established the root is resolved as:
    NVRAM root-live-fs != 0 -> live volume
    else apfs_root_to_xid (apfs_superblock +0x3C8)
    else the snapshot com.apple.os.update-<40 hex of boot-manifest-hash>
=> THE POD BOOTS THE SNAPSHOT. WE HAVE ONLY EVER READ THE LIVE VOLUME.

NEW LEADING HYPOTHESIS (fits every observation simultaneously):
  An OTA was DOWNLOADED AND STAGED INTO THE LIVE VOLUME and never applied. That
  is exactly how an iOS/audioOS OTA works: the updater writes the new system into
  the volume and creates a new snapshot; the device keeps booting the OLD
  snapshot until the switchover completes. So:
    - Home app says 13.4.8          -> correct, it runs the old snapshot
    - /mnt1 holds modern binaries    -> staged OTA payload in the live volume
    - old pods "update forever"      -> they stage fine, the switchover fails
  If this holds, our ENTIRE 13.4.8 ATTACK SURFACE IS VALID. R23 stands.

TWO CONSEQUENCES THAT MATTER MORE THAN THE VERSION QUESTION:
  1. *** EVERY FILE WE HAVE READ, INVENTORIED OR PLANTED AT /mnt1 MAY NOT BE
     WHAT BOOTS. *** The /usr/libexec 227-entry list (job 588), the /usr/sbin
     list that found hdik/pppd/racoon (job 587), the dyld failures (job 589) —
     all of that describes the LIVE volume, which may be staged OTA content, not
     the running 17M61 system. Every one of those inventories needs re-taking
     against the snapshot before we build on it.
  2. This is a strong candidate explanation for TWO earlier mysteries: the boot
     loops, and the "files disappearing from the volume" that preceded the
     job 560 snapswap disaster. If the live volume and the snapshot have diverged,
     then writing to /mnt1 and then booting would show exactly that pattern.
     (Job 560 deleted the only snapshot on a volume already losing files. If the
     snapshot was the real 13.4.8 system and the live volume was staged OTA
     content, deleting the snapshot would destroy the ONLY copy of the working
     system — which is precisely the panic we got:
     "Process 1 exec of /sbin/launchd failed, errno 2".)

DECISION: do NOT re-restore yet. A re-restore would destroy the evidence that
answers both the customer-facing question and mystery (2) above. Job 590 is
read-only and cheap; run it first.

JOB 590 REWRITTEN (110 lines) to settle it:
  A0 snaputil -l, parse the com.apple.os.update-* name
  A1 LIVE volume SystemVersion.plist + RestoreVersion.plist
  A2 mount the BOOTED SNAPSHOT read-only at /mnt3 via
     `mount_apfs -o ro -s <snap> /dev/disk1s1 /mnt3` and read ITS
     SystemVersion.plist   <<< THE ANSWER >>>
  A3 LIVE vs SNAPSHOT presence table for alwaysonexclavesd / betaenrollmentd /
     aidearlyboot / centaurid / pppd / racoon / hdik / amfid, plus /usr/libexec
     and /usr/sbin counts on each side, plus `file` on the SAME binary on each
     side to compare build versions
  A4 updater leftovers: /private/var/MobileSoftwareUpdate, installd, MobileAsset,
     and the root-live-fs / boot-manifest / update NVRAM vars
  A5 bounded `ldid -e` entitlement sweep (the AMFI audit's open item)
  A6 a LaunchDaemon plist template
  A7 FUD / static trust cache listing on each side
  Never touches /dev/disk1s2. Unmounts /mnt3 at the end.

ALSO: Nic notes automatic updates were never turned off on this pod, and he
intends to turn them off. Worth doing on any 17M61 unit we care about,
independently of whether the staging hypothesis is right.

================================================================================
R25 — APPLE PPP AUDIT. TWO PATCH-DIFF-PROVEN UNPATCHED BUGS, NEITHER A
      CODE-EXEC PRIMITIVE. PLUS TWO CORRECTIONS THAT MATTER.
      Tag audited: ppp-862.140.2.  2026-11-26 ~20:10 PST
================================================================================

R25.0 TAG SELECTION — our earlier assumption was off by one train
------------------------------------------------------------------
Correct tag for audioOS 13.4.8 is **ppp-862.140.2**, NOT ppp-884.
  - PPP_VERSION.h exists only in 862.x and says CURRENT_RELEASE_TAG "862.140.2";
    it is GONE from 877.40.2 onward (877 is a different major train).
  - ppp-862.140.2 published 2020-07-29 = macOS 10.15.6, released 15 Jul 2020,
    THE SAME DAY as iOS/tvOS 13.6. ppp-877.40.2 published 2020-11-19 =
    macOS 11.0.1, the 14.0 train.
  => 862.140.2 is the 13.6 fix set, and 862.140.2 -> 877.40.2 IS our
     "fixed in 14.0" boundary. ppp-884 is a macOS 12-era tag, far newer.

R25.1 *** THE EAP BCOPY IS CLEAN. NEGATIVE RESOLVED. STOP LOOKING THERE. ***
-----------------------------------------------------------------------------
main.c:202   u_char outpacket_buf[PPP_MRU+PPP_HDRLEN] __attribute__((aligned(4)));
             u_char inpacket_buf [PPP_MRU+PPP_HDRLEN] ...
ppp_defs.h:56,58  PPP_HDRLEN 4, PPP_MRU 1500  => both buffers EXACTLY 1504 bytes.

eap.c:1037-1049 (EAPClientAction) and eap.c:1175-1184 (EAPServerAction) are
identical and BOTH carry the bound check:
    case EAP_ACTION_SEND:
        if (eap_out->data == 0 ||
            eap_out->data_len < EAP_HEADERLEN ||
            eap_out->data_len > PPP_MRU) {              <-- THE CHECK
            error("EAP plugin tries to send a packet with with incorrect data");
            break;
        }
        outp = outpacket_buf;
        MAKEHEADER(outp, PPP_EAP);        /* advances outp by PPP_HDRLEN = 4 */
        BCOPY(eap_out->data, outp, eap_out->data_len);
Max write end = 4 + 1500 = 1504 = sizeof(outpacket_buf), exactly. data_len is
u_int16_t (eap_plugin.h:126) so no sign/promotion escape. PROPERLY BOUNDED.

eap.c is BYTE-IDENTICAL (md5 67e40d3ca3...) across EVERY tag from 862.120.2 to
1027.121.1. Whatever is in eap.c on the pod is also in macOS today.
Whole-file audit of all 9 copy/index sites found nothing exploitable:
  :428-443 EapInput length handling correct (rejects len<EAP_HEADERLEN and
           len>packet_len, trusts the SMALLER of declared/received)
  :728-732 peer_identity copy preceded by `if (len >= MAX_NAME_LENGTH)
           len = MAX_NAME_LENGTH - 1;`  (MAX_NAME_LENGTH 256) - correct
  :586     our_identity copy bounded by OPT_STATIC MAXNAMELEN truncation
           (max write end 261 << 1504) - checked specifically as a possible
           self-overflow via argv, which WE control. Closed.
  :920,929,1137,1146  mppe key copies use MIN(..., MPPE_MAX_KEY_LEN) - bounded
  :1273-1337 EapPrintPkt guards code/req indices and len - correct
  :757-758 (NAK branch) GETCHAR with no `len >= 1` check -> 1-byte read past the
           EAP packet but INSIDE the 1504-byte global, len goes to -1 then
           unused. Real but unexploitable.
ALSO: the reachable EAP surface is tiny. Everything past IDENTITY/NOTIFICATION/
NAK dispatches into cstate->client_ext / server_ext, which exist only if an EAP
plugin bundle was loaded via `eapplugin` (eap.c:1377 -> sys_eaploadplugin), and
that needs a SIGNED bundle. Without one, EapReceiveResponse dead-ends at
error("No EAP server protocol available") (eap.c:739). `require-eap` buys the
identity exchange and nothing deeper.

R25.2 *** CORRECTION: chap.c IS NOT COMPILED. NEITHER IS multilink.c. ***
--------------------------------------------------------------------------
VERIFIED from ppp.xcodeproj/project.pbxproj. Both pppd targets' Sources phase:
  auth.c ccp.c chap_ms.c demand.c fsm.c ipcp.c lcp.c magic.c main.c options.c
  sys-MacOSX.c tdb.c tty.c upap.c utils.c eap.c ecp.c ipv6cp.c eui64.c
  acscp.c acsp.c chap-new.c pppcrypt.c chap-md5.c
**chap.c, multilink.c and cbcp.c are ABSENT.** chap.c is dead legacy code; live
CHAP is chap-new.c + chap_ms.c + chap-md5.c. HAVE_MULTILINK is not defined, so
the whole fragment-reassembly line of enquiry is MOOT.
Live defines: lint DEBUGUPAP DEBUGCHAP DEBUGLCP DEBUGIPCP HAVE_PATHS_H CHAPMS
PLUGIN EAP MPPE USE_CRYPT INET6 **ACSCP**.  MSLANMAN is NOT defined.
(=> my earlier note "chap.c:463 clamps rhostname correctly, so look elsewhere"
 was about a file that never links. And CVE-2020-8597 is re-confirmed NOT
 APPLICABLE independently: `grep -rn "eap_request\|eap_response\|eap_input"`
 returns ZERO hits in the whole Helpers/pppd tree; rhostname occurs only in
 chap.c (not compiled) and upap.c:409/478 where it is slprintf-bounded.
 patchlevel.h's VERSION "2.4.2" is cosmetic.)

R25.3 *** SILENT FIXES — THE HEADLINE. BOTH IN APPLE-PRIVATE acsp.c. ***
-------------------------------------------------------------------------
Both land ONLY in ppp-1027.121.1 (published 2026-06-05, macOS 26 train).
So both were LIVE ON EVERY SHIPPING APPLE OS FROM ~2019 TO 2025, and are live
on 13.4.8. No CVE was ever assigned. The patch diff is free proof.
In the whole 862.140.2 -> 1027.121.1 window only 7 files in Helpers/pppd changed
at all, and only acsp.c and options.c changed for security reasons.

(A) acsp_printpkt() CI_DOMAINS  -- acsp.c:2513-2571  *** TOP CANDIDATE ***
    char domain_name[255 + 1];                     /* 256 bytes */
    len = ntohs(pkt->len);                         /* THE PACKET'S OWN FIELD */
    ...
    while (len >= sizeof(acsp_domain_data)) {      /* int vs size_t */
        memcpy(&domain_data_aligned, ptr, sizeof(acsp_domain_data));
        slen = ntohs(domain_data_aligned.len);
        domain_name_len = MIN(slen, sizeof(domain_name));   /* OFF BY ONE */
        if (slen) memcpy(domain_name, ((acsp_domain_data*)(void*)ptr)->name,
                         domain_name_len);
        domain_name[domain_name_len] = 0;          /* domain_name[256] */
        len -= (ACSP_DOMAIN_DATA_HDRSIZE + slen);
        ptr += (ACSP_DOMAIN_DATA_HDRSIZE + slen);
    }
    THREE defects, VERIFIED BY EXECUTION UNDER ASAN:
      1. 1-byte stack OOB WRITE: slen>=256 => domain_name_len==256 =>
         domain_name[256]=0, one NUL past a 256-byte stack array. ASAN:
         "stack-buffer-overflow ... WRITE of size 1 ...
          [64, 320) 'domain_name' <== Memory access at offset 320"
         1027 fixes it to MIN(slen, sizeof(domain_name) - 1).
      2. Trusts pkt->len over plen. plen is only checked >= 8. Set
         pkt->len=0xFFFF and the loop gets a 65527-byte budget over a 20-byte
         frame.
      3. Signed/unsigned: len is int, sizeof() is size_t, so len is promoted
         unsigned. Once `len -= (6+slen)` goes negative the condition is TRUE
         FOREVER and ptr only advances => guaranteed wild forward read to
         SIGSEGV. Observed: iter1 len=10 slen=256; iter2 len=-252; iter3
         len=-258; ... 1027's `if (slen > len) break;` kills it.

    *** REACHABILITY IS THE BEST PART: FIRST FRAME, NO HANDSHAKE, NO AUTH. ***
    acsp_printpkt is acscp_protent.printdatapkt (acscp.c:217-227), dispatched
    from utils.c:544-545 in format_packet <- utils.c:926 dbglog("%s %P") in
    dump_packet <- **main.c:1455 dump_packet("rcvd", p, len)** -- which runs
    BEFORE the LCP-OPENED check at main.c:1464 and before the phase check. And
    format_packet's data-protocol branch does NOT test enabled_flag.
    PPP_ACSCP 0x8235 & ~0x8000 = 0x235 = PPP_ACSP (ppp_defs.h:85,94).
    => ONE PPP frame with protocol 0x0235 and the `debug` option. Nothing else.

(B) acsp_plugin_read() CI_DOMAINS -- acsp.c:1201-1223
    while (len > 2) {
        memcpy(&domain_data, inPtr, ACSP_DOMAIN_DATA_HDRSIZE);  /* 6B, len may be 3 */
        domain_len = ntohs(domain_data.len);                    /* 0..65535 UNCHECKED */
        domain->name = malloc(domain_len + 1);
        memcpy(domain->name, inPtr + ACSP_DOMAIN_DATA_HDRSIZE, domain_len);  /* <-- */
    Destination is correctly sized; the SOURCE read runs up to 65535 bytes past
    the 1504-byte inpacket_buf, and the bytes land in a list installed as DNS
    search domains => info disclosure of adjacent globals. len is compared
    signed here so no runaway. 1027 adds `if (domain_len > len) return -1;`.
    Reachability harder: needs lcp OPENED, past PHASE_AUTHENTICATE, and ext_list
    populated by acsp_init_plugins. Client-side neg_domains defaults to 1 when
    serverid==0 (acsp.c:563-567), so the CI_DOMAINS context does exist.

(C) acsp.c:2137 acsp_ipdata_start_dhcp_client gained
    `bzero(outpacket_buf, sizeof(outpacket_buf));` -- and THIS one landed at
    ppp-877.40.2, i.e. the 14.0 boundary, and is the ENTIRE security content of
    that diff. Uninitialised-memory leak into an outgoing DHCP packet. Live on
    13.4.8, fixed in 14.0.

R25.4 *** CORRECTION: /etc/ppp/options IS A LIVE SURFACE ON 13.4.8 ***
-----------------------------------------------------------------------
The `#if TARGET_OS_OSX` neutering of options_from_file(), options_from_user()
and options_for_tty() was added ONLY in ppp-1027.121.1. In 862.140.2 these are
UNCONDITIONAL, and main.c:417-422 runs them on every platform:
    if (!options_from_file(_PATH_SYSOPTIONS, !privileged, 0, 1)
        || !options_from_user()
        || !parse_args(argc-1, argv+1)
    #ifdef __APPLE__
        || ((controlled) && !options_from_controller())
        || !options_from_file(_PATH_SYSPOSTOPTIONS, 0, 0, 1)
    #endif
grep for TARGET_OS_OSX/IPHONE/EMBEDDED in 862.140.2 Helpers/pppd hits ONLY
auth.c (keychain) and sys-MacOSX.c (kext paths) -- NONE in options.c.
=> On our device /etc/ppp/options, /etc/ppp/postoptions, /etc/ppp/options.<dev>,
   ~/.ppprc and /etc/ppp/peers/* (via file/call) are ALL live writable option
   sources. Simpler launchd plist, and a SECOND attacker-controlled file input.
   This supersedes R23.4's claim that they are not a surface.
   UNCLOSED CAVEAT: pathnames.h:39-46 has `#ifndef _ROOT_PATH / #define
   _ROOT_PATH /* empty */`. Did not verify the embedded build doesn't redefine
   it. Cheap on-device test: put a syntax error in /etc/ppp/options and see
   whether pppd exits with an option error.

R25.5 OTHER CANDIDATES (ranked, lower value)
----------------------------------------------
  acscp.c:560-566 acscp_nakci: `while (len > CILEN_VOID) { GETCHAR(citype,p);
    GETCHAR(cilen,p); if ((len -= cilen) < 0) goto bad; p = p + cilen - 2; }`
    With cilen==0 both p and len are unchanged => INFINITE LOOP, wedged root
    process. lcp.c:1303-1308 has the missing `cilen < CILEN_VOID` guard;
    acscp.c does not. Unchanged in every tag to 2026. DoS only.
  chap_ms.c:612,657 ascii2hex(status_pkt+3, sizeof(challenge), ...) reads
    2*MAX_CHALLENGE_LEN = 128 bytes regardless of remaining length -> heap OOB
    read <=128B past chap_saved_packet. GATED on the Dialogs plugin (unknown
    whether present on device).
  acsp.c:2095 DHCP static-route masklen: addrlen (<=31) not checked against
    optlen; also 0xFFFFFFFF << (32-masklen) is UB for masklen 0 or >32. Needs
    use-dhcp. Low impact.
  acsp.c:1193-1199 CI_ROUTES `while (len > 4)` but reads 12 -> 4-byte OOB read.
  acscp.c:905-913 reads 4 bytes when olen==2 -> 4-byte OOB read.
  acscp.c:600-607 reads p[0],p[1] before any len>=2 test -> 2-byte OOB read.

R25.6 CLEAN NEGATIVES — do not spend hardware time here
---------------------------------------------------------
eap.c entire (R25.1). upap.c upap_rauth (len arithmetic correct, slprintf
bounded). fsm.c fsm_input (rejects len<HEADERLEN and len>l). lcp.c / ipcp.c /
ipv6cp.c option walks (all three have `if (cilen < CILEN_VOID ||
(len -= cilen) < 0) goto bad;`). ccp.c:1179. acscp.c:700-706 reqci (correct
triple test). lcp.c:1878-1891 CI_EPDISC. auth.c:1047-1050 peer_authname.
auth.c:2188-2195 get_secret (exact fit vs MAXSECRETLEN 256) and the
/etc/ppp/{pap,chap}-secrets parser scan_authfile/getword - NO overflow found.
chap_ms.c MS-CHAPv2 verify (both reject unless response_len is exact;
ascii2unicode exact fit; MSLANMAN not compiled). chap-new.c:583-645 and
:794-799. acsp.c log_dhcp / acsp_ipdata_print (optlen u_int8_t <=255 into
char str[2048]); the acsp_plugin_add_domains stack pointers are consumed and
freed before return, NOT a use-after-return.

R25.7 HONEST BOTTOM LINE ON pppd
----------------------------------
We got exactly what we asked for -- two unpatched, patch-diff-proven
memory-safety bugs reachable purely by feeding bytes to an unsandboxed root
process, one of them on the VERY FIRST FRAME with no handshake, auth or peer.
BUT: **neither is a plausible code-execution primitive.**
  (A) is a WRITE of ONE fixed byte, value 0x00, at a FIXED stack offset. No
      length control, no content control, no index control. Canary trip or
      padding no-op. Not a ROP pivot.
  (B) and the rest are READS. (acscp_nakci) is a hang.
The one thing with attacker-controlled length AND content reaching a
fixed-size destination would have been the EAP BCOPY, and it is bounded.
=> For MAPPING OUR OWN CODE, /usr/sbin/pppd is a DEAD END on this evidence.
   What it IS good for: a cheap, deterministic, repeatable in-process crash in
   a root process at boot = a layout/ASLR ORACLE. The fault address tells us
   where inpacket_buf lives, and whether this build has a stack canary and
   where it sits. Worth one cold boot, not a campaign.
   The most PRACTICALLY useful finding from this audit is R25.4
   (/etc/ppp/options is open), not the bugs.

R25.8 READY-TO-RUN TEST (held until job 590 resolves the volume question)
--------------------------------------------------------------------------
NOT QUEUED YET, DELIBERATELY. We must not plant a launchd job into /mnt1 until
we know whether /mnt1 is what boots (R24.7). Planting into the wrong volume is
exactly the class of mistake that killed the System volume in job 560.

ProgramArguments (every option confirmed present in 862.140.2's tables):
  /usr/sbin/pppd notty nodetach noauth -all receive-all debug
  logfile /tmp/pppd-dbg.log nodefaultroute noipdefault
  lcp-echo-interval 0 lcp-echo-failure 0 lcp-restart 2
  StandardInPath=/var/root/ppp_in.bin
  StandardOutPath=/var/root/ppp_out.bin  StandardErrorPath=/var/root/ppp_err.log
WHY EACH:
  notty -> tty.c:808 start_charshunt(0,1); also sets default_device so
    nodetach=1 and devnam stays empty, so connect_tty never open()s a device.
  **logfile IS MANDATORY**: tty.c:560 `if (notty && log_to_fd <= 1)
    log_to_fd = -1;` -- with notty there is NO debug output at all unless
    setlogfile already raised log_to_fd. Without it we are blind.
  debug -> utils.c:905 `if (!debug) return;` in dump_packet. THIS IS THE
    TRIGGER for (A). Level 1 is enough.
  -all -> lcp.c:117 noopt -> BZEROs lcp_wantoptions/allowoptions, making our
    Configure-Request empty and DETERMINISTIC (no random magic number).
  receive-all -> rasyncmap = 0, so control chars are not discarded.
WILL BAIL BEFORE READING STDIN: a device name as first arg (tty.c:545 exit);
  `pty`/`socket` with notty (tty.c:549-556); `demand` without connect/pty;
  `noload` when the family isn't attached (exit EXIT_NO_KERNEL_SUPPORT);
  **`noacsp` (acscp.c:168) clears acscp_protent.enabled_flag and KILLS (A)-(D)
  -- DO NOT PASS IT**; not being root (EXIT_NOT_ROOT).

FRAME A (289 bytes on the wire). Kernel framing rules (ppp_serial.c:730-770,
815-830, 855-895): 0x7E flags, 0x7D escape with ^0x20, FCS-16 little-endian,
bad FCS dropped, ilen < PPP_HDRLEN+PPP_FCSLEN dropped, inlen > mru+6 dropped
(mru hard-wired 1500 at lcp.c:500-501). With -all, SC_REJ_COMP_AC is set so
EVERY frame must literally begin ff 03.
  ff 03 | 02 35 | 02 | 00 | ff ff | 00 00 | 00 00 | 7f 00 00 01 | ff ff | 'A'x256
   addr/ctl  proto  type seq   len   flags  reserved   server      slen    name
  FCS 38 f4
Generator (FCS table VERIFIED identical to the kernel's own fcstab at
Family/ppp_serial.c:245-249, and fcs16(frame||FCS)==0xf0b8==PPP_GOODFCS):
  python3 -I - <<'PYEOF' > ppp_in.bin
  import sys
  t=[]
  for b in range(256):
      v=b
      for _ in range(8): v=(v>>1)^0x8408 if v&1 else v>>1
      t.append(v)
  info=bytes([0xff,0x03,0x02,0x35,0x02,0x00,0xff,0xff,0x00,0x00,0x00,0x00,
              0x7f,0x00,0x00,0x01,0xff,0xff])+b'A'*256
  f=0xffff
  for c in info: f=(f>>8)^t[(f^c)&0xff]
  f=(~f)&0xffff
  frame=info+bytes([f&0xff,(f>>8)&0xff])
  out=bytearray([0x7e])
  for c in frame:
      if c in (0x7e,0x7d) or c<0x20: out+=bytes([0x7d,c^0x20])
      else: out.append(c)
  out.append(0x7e)
  sys.stdout.buffer.write(bytes(out))
  PYEOF
WHAT HAPPENS: len = 0xFFFF-8 = 65527. Iter1: slen=65535,
domain_name_len=256, 256-byte memcpy (in bounds - that is why we supply exactly
256 'A's), then domain_name[256]=0 -> the off-by-one. Then len = -14 and
ptr += 65541, so iter2 memcpy's 8 bytes at &inpacket_buf + 12 + 65541 =
&inpacket_buf + 0x10011, i.e. 0xFA31 (64049) bytes past the end of the
1504-byte global, and the negative len keeps the loop alive.
Optional LCP bring-up to prepend for the (B) path (pppd's first
Configure-Request is id==1: fsm_init sets f->id=0, fsm.c:834 f->reqid=++f->id):
  B1 our empty LCP ConfReq id=0x42: 7e ff 7d 23 c0 21 7d 21 42 7d 20 7d 24 c3 5c 7e
  B2 LCP ConfAck for pppd's req id=0x01: 7e ff 7d 23 c0 21 7d 22 7d 21 7d 20 7d 24 7d 3c 90 7e
Do NOT repeat B1 after LCP opens. stdin is a regular file so the charshunt
blasts it all at once then hits EOF, which pppd reads as "Modem hangup"
(main.c:1436-1446) -- fine for FRAME A since the crash is on the first frame.
If slack is needed, pad the head with ~2 KB of bare 0x7e (zero-length frames
are silently dropped at ppp_serial.c:758).

HOW TO RECOGNISE A WIN, in order of likelihood:
 1. SIGSEGV / KERN_INVALID_ADDRESS on a READ, PC inside acsp_printpkt, faulting
    address ~= &_inpacket_buf + 0x10011. Report at
    /var/mobile/Library/Logs/CrashReporter/pppd-*.ips (or /Library/Logs/
    CrashReporter/, or /var/logs/CrashReporter/). If faulting_addr minus the
    slid address of inpacket_buf == 0x10011, that is candidate (A)/(2) and
    nothing else. THE CLEAN WIN.
 2. __stack_chk_fail / SIGABRT with abort_with_payload and __stack_chk_fail
    below acsp_printpkt => the NUL landed on the canary, i.e. the canary sits
    immediately after domain_name. That single layout fact decides whether the
    off-by-one is ever more than a crash.
 3. No crash at all - entirely possible, the compiler may have padded after
    domain_name[256]. Then use FRAME A' (slen = 0x0100 = 256, advances 262
    bytes/iteration and fires the write on every iteration).
 4. CHECK THIS FIRST, before chasing crashes: the log should contain
      rcvd [ACSP data <payload len 65527, packet seq 0, CI_DOMAINS, flags:>
          <domain: name AAAA...AAAA, server 127.0.0.1>
    The literal "<payload len 65527" PROVES pkt->len was trusted over plen and
    that we are inside the vulnerable loop. If instead we see "rcvd
    [proto=0x235]", ACSCP was not compiled into this pppd -- stop and check
    `strings /usr/sbin/pppd | grep -i 'ACSP plugin'` (that string exists only
    if acsp.c was linked).
 5. UART shows nothing specific to this bug. Channels are the logfile,
    StandardErrorPath, the crash report, and launchd's record of how pppd died
    (dying by signal rather than exiting cleanly is itself a signal).
 6. Hang at 100% CPU with no crash = acscp_nakci (R25.5), if we got as far as
    ACSCP negotiation.

TWO THINGS THE AUDIT COULD NOT CLOSE: whether _ROOT_PATH is redefined in the
embedded build settings (R25.4 caveat), and whether the Dialogs plugin that
gates the chap_ms.c candidate exists on the device at all.

PUBLICATION NOTE for the GitHub repo: (A) and (B) are fixed in Apple's current
release (ppp-1027.121.1, June 2026), so writing up a diff of an already-patched
bug is ordinary practice -- but they are still live on every un-updated device
in the field, and no CVE was ever assigned. Nic's call on timing and framing.

================================================================================
R26 — JOB 590: THE STAGING HYPOTHESIS IS CONFIRMED. 13.4.8 SURFACE IS VALID.
      2026-11-26 20:04 PST
================================================================================
R24.0 is FULLY RETRACTED. R24.7's hypothesis is CONFIRMED. The pod IS on 13.4.8.

PROVEN BY JOB 590:
  snapshots on disk1s1: exactly ONE,
    com.apple.os.update-8AD664B27CAE667B82D0274EC1D1AC20B4220C5D
  LIVE (/mnt1, mount_apfs /dev/disk1s1) vs SNAPSHOT (/mnt3, mount_apfs -o ro -s):
    /usr/libexec count      live 227   snap 132
    /usr/sbin count         live  29   snap  28
    usr/libexec/alwaysonexclavesd   live YES   snap NO
    usr/libexec/betaenrollmentd     live YES   snap NO
    usr/libexec/aidearlyboot        live YES   snap NO
    usr/libexec/centaurid           live YES   snap NO
    usr/sbin/pppd, racoon, hdik, usr/libexec/amfid   present on BOTH
  => The live volume holds a MODERN STAGED SYSTEM. The snapshot holds 13.4.8.
     They are two different operating systems on one APFS volume.
  NVRAM: `root-live-fs` IS NOT SET (only auto-boot=true present). Per the boot
     resolution order established earlier (root-live-fs != 0 -> live volume;
     else apfs_root_to_xid; else the com.apple.os.update-<hash> snapshot), the
     pod therefore BOOTS THE SNAPSHOT. Home app reporting 13.4.8 is correct.
  /mnt1/private/var/MobileSoftwareUpdate EXISTS (as do installd, MobileAsset).
  /usr/standalone/firmware/FUD on BOTH sides is identical:
     RestoreTrustCache.img4 8399 B, StaticTrustCache.img4 17595 B
     => THE TRUST CACHE WAS NOT UPDATED for the staged system.

WHY THE POD NEVER FINISHES UPDATING (mechanism, PROVEN part):
  The download and stage step WORKS - the new OS is physically written into the
  live volume. What never happens is the SWITCHOVER: sealing a new snapshot for
  the new system and pointing the boot root at it. So every boot re-resolves to
  the old 13.4.8 snapshot, the OS reports 13.4.8, the updater sees it is still
  out of date, and it starts over. Hence "looks like it is trying, forever".
  It is not a download failure. It is a COMMIT failure.
INFERRED, NOT PROVEN - why the commit fails:
  Candidates, in order of plausibility: (a) the switchover needs a matching
  Apple-SIGNED StaticTrustCache.img4 plus personalised firmware (iBoot/SEP/
  kernelcache) written to the firmware partitions, personalised by TSS for THIS
  ECID; if any part of that personalisation cannot be obtained or applied the
  updater will not flip the snapshot - and we can see the trust cache was NOT
  replaced, which is consistent; (b) the seal/space step fails.
  DISCRIMINATING TEST, one read-only job if we want the final answer: list
  /private/var/MobileSoftwareUpdate and read the MSU logs.
  *** Do NOT claim a root cause beyond (a)/(b) without that job. ***

*** OPERATIONAL CONSEQUENCE, THE BIG ONE: ***
EVERY INVENTORY WE HAVE TAKEN AT /mnt1 DESCRIBES THE STAGED MODERN SYSTEM, NOT
THE 17M61 SYSTEM THAT BOOTS. Specifically invalidated as descriptions of 13.4.8:
  - job 587's /usr/sbin + /usr/bin + /sbin inventory (the one that found
    hdik/pppd/racoon - though 590 confirms all three ALSO exist in the snapshot)
  - job 588's 227-entry /usr/libexec list (the snapshot has 132)
  - job 589's dyld "built for tvOS 27.2" failures for pppd/racoon - those were
    the STAGED binaries, which is exactly why they were too new for the ramdisk
Anything we plant for a cold-boot test MUST go into the booted snapshot's view,
not into /mnt1. Writing a launchd job into /mnt1 would be written into a system
that never runs. THIS IS ALSO THE LIKELY EXPLANATION FOR THE JOB 560 DISASTER:
deleting "the only snapshot" deleted the only copy of the WORKING 13.4.8 system
and left the pod booting a staged system whose cdhashes are not in the trust
cache -> "Process 1 exec of /sbin/launchd failed, errno 2". It also explains the
boot loops and the files that appeared to vanish.
HOW TO PLANT CORRECTLY - unresolved, needs thought before any write job. An APFS
snapshot is read-only by design. Options to evaluate: (1) set NVRAM root-live-fs
so the pod boots the LIVE volume, then plant there - but the live volume is the
staged modern system whose binaries are not in the trust cache, so it probably
will not boot; (2) delete the staged content and re-seal - destructive, needs a
full restore as the fallback; (3) restore to 17M61 clean, immediately disable
automatic updates BEFORE anything stages, and then plant into a volume that has
only one system on it. (3) IS THE SAFE PATH and is what Nic already intends.

R26.1 BONUS: THE AMFI AUDIT'S OPEN ITEM IS ANSWERED (ldid sweep)
------------------------------------------------------------------
Something on disk DOES hold the trust-cache entitlement:
  /usr/libexec/MobileStorageMounter:
      com.apple.private.amfi.can-load-trust-cache
      com.apple.private.pmap.load-trust-cache
      (+ security.mac.amfi.developer_mode_status)
  /sbin/launchd:
      com.apple.private.amfi.can-allow-non-platform
      com.apple.private.pmap.load-trust-cache
  /usr/libexec/amfid:
      com.apple.private.amfi.developer-mode-control
      com.apple.private.amfi.set-demo
      com.apple.private.security.storage.amfid
  /usr/sbin/hdik: NO entitlements at all
  /usr/libexec/MSUEarlyBootTask: none matched
This does NOT open the door by itself - R24.4 established the blob still needs
an ECID/chip/board-personalised Apple Image4 manifest, which is not forgeable
offline. But MobileStorageMounter is now a named, entitled front door worth
reading: it is the thing that calls loadTrustCache, it takes PATHS, and it is
reachable from launchd. Worth an audit pass of its own.
NOTE `launchd` holding can-allow-non-platform is interesting in its own right.

R26.2 TOOLING NIT
-------------------
`plconvert -x <file>` failed on every plist with NSCocoaErrorDomain error 3840
(NSPropertyListReadCorruptError), including LaunchDaemon plists and
SystemVersion.plist. Either wrong invocation for this build or the files need a
different reader. Use `xxd`/`grep` on the raw bplist, or find the right
plconvert/plutil invocation, next time. We got the answer from the file-presence
comparison instead, so it did not block us.

================================================================================
R27 — IN-KERNEL UDIF PARSER AUDIT. TWO MISSING BOUNDS CHECKS, ONE OF THEM A
      WRITE PRIMITIVE WITH ATTACKER-CONTROLLED LENGTH *AND* CONTENT.
      kernel.macho md5 2593a5529ba361d393a8c1365166bc98 (UNMODIFIED)
================================================================================
fileoff = va - 0xfffffff007004000 throughout.

KEXT MAP (VERIFIED; symtab is stripped, nsyms=0, and the prelink plist has no
_PrelinkExecutableLoadAddr, so this was recovered via __kmod_info/__kmod_start
and the retained inline MH_KEXT_BUNDLE headers):
  DiskImages (IOHDIXController)   __text 0xfffffff007d93418-0xfffffff007d98ea0
  DiskImages.KernelBacked                0xfffffff007d98f70-0xfffffff007d9b3e0
  **DiskImages.UDIFDiskImage**           0xfffffff007dcb090-0xfffffff007dd3a88
  RAMBackingStore 0xfffffff007fc3700+ / FileBackingStore 0xfffffff008560f28+
  ReadWriteDiskImage 0xfffffff00859ca50+
  All six: CFBundleVersion 493.0.0, internal kmod_info version 559.100.2 (both
  numbers are real, the mismatch is not an extraction error).
** TRAP WORTH RECORDING: kmod_info here is PACKED/4-byte-aligned, so start_fn is
   at +0xb4 and stop_fn at +0xbc, NOT the textbook +0xb8/+0xc0. **
Key functions (addresses VERIFIED, names INFERRED from behaviour):
  0xfffffff007dcb3bc  KDIUDIFDiskImage::read  (chunk dispatch + decompression)
  0xfffffff007dcbd68  build chunk table (fetch all blkx resources)
  0xfffffff007dcbf38  merge_blkx (two-pass merge into one native-endian table)
  0xfffffff007dcc268  findChunk (branchless binary search)
  0xfffffff007dcd0cc  KDIUDIFEncoding::probe (koly magic + version, score 200)
  0xfffffff007dcdd08  zlib uncompress wrapper
  0xfffffff007dd3848  compression_decode_buffer (LZFSE STATICALLY LINKED here)
TWO THINGS THAT COST THE AGENT TIME AND WOULD COST US TIME:
  - `blkx` and `koly` are NEVER strings. Built as immediates (0x626c6b78 at
    0xfffffff007dcbdb8/0xdcbe3c; 0x6b6f6c79 at 0xdcd174/0xdcd2e4/0xdcd38c).
    Grepping ASCII finds nothing.
  - `mish` is NEVER COMPARED. There is no check of fUDIFBlocksSignature
    anywhere. The 'mish'+version constant at 0xfffffff0070537c0 is loaded into
    d8 and STORED into the merged table, never tested. Put anything in blkx[0:4].

*** CANDIDATE A (high confidence = CVE-2020-9965/9966): blocksRunCount is
    trusted as the sole loop bound and OSData::getLength() IS NEVER CALLED. ***
  merge_blkx takes only OSData::getBytesNoCopy (vtable +0xd8) and indexes raw
  bytes. `ldr x8,[x8,#0xd8]` occurs EXACTLY ONCE in the whole UDIFDiskImage
  kext; there is no getLength() call on a blkx OSData anywhere.
  fileoff 0xdc8060:
    ldr  w9, [x22, #0xc8]     ; blocksRunCount - ATTACKER CONTROLLED
    rev  w9, w9
    subs w9, w9, #1           ; n = runCount - 1
    b.eq ...
    add  x19, x22, #0xcc      ; first entry
    mov  w27, w9              ; loop limit
  loop (0xdcc080): ldp q0,q1,[x19] ; ldr x8,[x19,#0x20]  (40 bytes/entry)
        ... add x19,x19,#0x28 ; cmp x23,x27 ; b.lo loop
  Reads up to 0xcc + (runCount-1)*0x28 bytes from an allocation whose size is
  never consulted. A 4-byte blkx <data> already reads OOB at +0x20 and +0xc8.
  "An out-of-bounds read was addressed with improved input validation" fits
  exactly. Fix would be a one-line getLength() compare.

*** CANDIDATE B (NOT on my original list of six shapes - THE AGENT FOUND IT
    INDEPENDENTLY): compressedLength is never bounded against the decompression
    buffer. THIS IS A CONTROLLED HEAP UNDERFLOW *WRITE*. ***
  The compressed bytes are read into the TAIL of the output buffer and the
  source pointer is bufEnd MINUS the attacker's compressedLength, unguarded.
  zlib path, fileoff 0xdc767c:
    add  x8, x20, x19         ; bufEnd = buf + allocSize
    ldp  x2, x1, [sp, #0x58]  ; x2 = compressedLength, x1 = compressedOffset
    sub  x19, x8, x2          ; src = bufEnd - compressedLength   <-- NO BOUND
    ...
    mov  x4, x19              ; DESTINATION of the backing-store read = src
    blr  x8                   ; read(off, len, &actual, dst=x4, flags)
  LZFSE path identical at fileoff 0xdc7760 (`sub x4,x8,x2`).
  EXHAUSTIVE PROOF OF ABSENCE: the agent enumerated EVERY compare/test in
  KDIUDIFDiskImage::read (0xdcb3bc-0xdcb96c) - 18 of them, all listed in its
  report - and [sp,#0x58] (compressedLength) appears at only 0xdcb680,
  0xdcb6ac, 0xdcb768, 0xdcb7a0: four loads, ZERO comparisons.
  => compressedLength > decompressBufferRequested*512 puts src BELOW the
     allocation and the backing store writes compressedLength ATTACKER BYTES
     starting there. Attacker-controlled length AND content. This is the write
     primitive every other surface we have audited lacked.
  CODEC CHOICE MATTERS: the zlib wrapper has an overlap guard at
  0xfffffff007dcdd5c-0xdcdd88 (cmp src,dst then add/sub/cmp, b.hs err) which
  errors out once src < dst - so inflate never runs on the OOB pointer, BUT THE
  WRITE AT 0xdcb6a0 HAS ALREADY HAPPENED. The LZFSE path has NO overlap guard,
  so entryType 0x80000007 gives the OOB write AND an OOB read by the decoder.
  Use zlib (0x80000005) to isolate the write; LZFSE (0x80000007) for both.

CLEAN NEGATIVES - STOP LOOKING (each with the enforcing instruction):
  Shape 1 (decompressBufferRequested vs per-chunk sectorCount): CHECK PRESENT,
    both codecs. 0xdcb5fc lsl x20,x9,#9 (needed, 64-bit no truncation); guard
    and kalloc use the SAME expression (0xdcb618 cmp x20,x8 / 0xdcb660 kalloc).
    And merge_blkx CLAMPS decompressBufferRequested <= 0x400000 at 0xdcc194
    (cmp w8,#0x400,lsl#12), which also kills the lsl w8,w8,#9 truncation.
  Shape 3 (compressedOffset+compressedLength vs file size): CHECK PRESENT in
    KDIFileBackingStore::read at 0xfffffff0085617cc (tbnz sign, ldr filesize,
    add, cmp, ccmp, b.gt -> 0xe00002c2). Practical effect: our DMG must actually
    be >= compressedOffset+compressedLength bytes. A sparse file is fine.
  Shape 4 (sector geometry): CHECK PRESENT, three layers - request clamp at
    0xdcb400-0xdcb410; merge_blkx forces CONTIGUOUS + MONOTONIC and clips
    straddling entries; gap-fill + 0xFFFFFFFF terminator synthesis at
    0xdcc1a4-0xdcc1e4; allocation umull so no overflow.
    *** SUBTLETY THAT PREVENTS A WRONG CONCLUSION: the entryType filter at
    0xdcc0bc-0xdcc10c that rejects bit-31 types is ONLY reached when an entry
    straddles the cursor and needs clipping; the normal in-order case branches
    past it at 0xdcc0ac b.ge. Compressed chunks ARE accepted on the normal path.
    Reading merge_blkx top-down without tracing that b.ge wrongly concludes
    compressed DMGs cannot attach at all. ***
  Shape 5 (sparse/UDSP band index, shadow files): NOT PRESENT IN THIS BUILD. No
    sprs/sdmg/UDSP/Info.bckup strings anywhere. Only UDIF, raw/kernel-backed,
    RAM-backed, file-backed, read-write. No sparse parser to audit. Deprioritise.
  Shape 6 (UDIFChecksum.size as a loop bound): NOT PRESENT. swap_koly
    (0xfffffff007d9b280) is fully unrolled, swaps only type/size at +0x50/+0x54
    and +0x160/+0x164, never touches the 128-byte data arrays. No in-kernel
    checksum verification at all.
  koly trailer read and XML plist read: both size-checked (file >= 0x201 at
    0xdcd254; XMLOffset <= fileSize at 0xdcd618; XMLOffset+XMLLength <= fileSize
    at 0xdcd628; kalloc(XMLLength+1), NUL at actual bytes read).
  Decompressor OUTPUT bounding: clean for both codecs.
  *** ADC (0x80000004) AND BZIP2 (0x80000006) ARE UNREACHABLE. *** fileoff
    0xdc7500: tbz w10,#31 / add w10,w10,#-0x80000000 / cmp w10,#8 / b.hi /
    mov w8,#1 / lsl w8,w8,w10 / mov w11,#0x15f / tst w8,w11 / b.eq decompress.
    Mask 0x15F rejects sub-types 0,1,2,3,4,6,8. ONLY 0x80000005 (zlib) and
    0x80000007 (LZFSE) reach a decompressor. My instruction to give ADC extra
    attention was MOOT on this build.

*** CORRECTION: KDIDiskImageNubUserClient DOES NOT EXIST AS A CLASS. ***
  The string is at 0xfffffff0072908d2 but a full __TEXT_EXEC scan found exactly
  ONE reference (0xfffffff007d9a8cc, a setProperty("IOUserClientClass",...)
  style use). No OSMetaClass registration, no vtable. KDIDiskImageNub advertises
  a user-client class that isn't implemented; IOServiceOpen on it will FAIL.
  There is no dispatch table there to audit.
THE REAL IOKIT SURFACE IS IOHDIXControllerUserClient (0xf0 bytes, vtable
  0xfffffff00751d148, 194 slots):
  GATE: initWithTask (slot 171, 0xfffffff007d95348) requires
    copyClientEntitlement("com.apple.private.diskimages.kext.user-client-access")
    and returns 0 without it. hdik HAS this entitlement. Also a UID-spoof guard
    ("WARNING: UID spoofing detected (and defeated)").
  getTargetAndMethodForIndex = slot 182 (0xfffffff007d952f8): cmp w2,#1 / b.hi
    reject => EXACTLY 2 SELECTORS. IOExternalMethod table at 0xfffffff007051f30
    (fileoff 0x4df30), stride 0x30.
    Selector 0: virtual vtable+0x5d0 = 0xfffffff007d957c8, flags 3
      (kIOUCStructIStructO), structureInputSize FIXED 0x100, output 4.
      Input struct = { u32 magic = 0xBEEFFEED; u8 flag; ...; u64 userPtr @ +0x08;
      u64 userLen @ +0x10 }. Handler reads only +0x00/+0x04/+0x08/+0x10.
    Selector 1: 0xfffffff007d959d8 = `mov w0,#0xe00002c7; ret` - A STUB.
  NO MISSING SIZE CHECK: count0 is a fixed 0x100 which externalMethod enforces,
  and copyUserBuffer (slot 190, 0xfffffff007d95520) bounds the user length to
  1..0x7FFFFFFE (cmp x9,#0x7FFFFFFD / b.hi) before
  IOMemoryDescriptor::withAddressRange. The user client is NOT the bug - it is
  just the delivery path that hands our file to the UDIF parser, exactly as
  assumed.

*** SECOND ROUTE INTO THE SAME PARSER, NO USER CLIENT, NO ENTITLEMENT: ***
  IOHDIXController::_di_root_image implements the `di-root-image` /
  `di-root-ram-file` BOOT-ARG path (strings 0xfffffff00726db26,
  0xfffffff00726dbfd, 0xfffffff00726db63; log fmt 0xfffffff007290355). It
  attaches a root disk image at boot with no user client and no entitlement at
  all. Cheaper to drive than hdik IF we can set boot-args - which on this unit
  we cannot (console setenv gated to 4 names). Keep for the Nicotine boot story.

TEST RECIPES (exact bytes in the agent's report; summary here)
  Shared koly trailer, last 512 bytes, BIG-ENDIAN. Enforced fields only:
    +0x000 'koly' (0xdcd2ec/0xdcd180); +0x004 = 4 (cmp w8,#4 at 0xdcd2f8);
    +0x0d8 XMLOffset <= fileSize; +0x0e0 XMLLength != 0 and
    XMLOffset+XMLLength <= fileSize; +0x1e8 imageVariant <= 2 (0xdcbdd8);
    +0x1ec sectorCount (u64, DELIBERATELY UNALIGNED - read via
    `add x8,x0,#0x1ec; ldr x8,[x8]`). File must be >= 513 bytes.
  RESOURCE ID NUMBERING (decoded from the shift table 0xdcbdf0-0xdcbe14):
    imageVariant 2 or 0 -> blkx IDs 0..count-1; imageVariant 1 -> -1..count-2.
    USE imageVariant = 2 AND A SINGLE blkx WITH ID "0".
  RECIPE A (Candidate A): Data = exactly 0xCC bytes, header only, no entries,
    blocksRunCount = 0x01000000. Walk reads ~640 MB past a ~208-byte alloc ->
    first unmapped page faults. Expect a synchronous data abort with pc on
    0xfffffff007dcc080 (ldp q0,q1,[x19]) or 0xdcc084, esr 0x96000006, DURING
    hdik ATTACH, before any partition probe or mount. Match on the offset from
    the kext base, not the absolute pc (the cache slides).
    *** RUN VARIANT 1 FIRST: blocksRunCount = 2 with the same 0xCC-byte Data.
    Reads exactly ONE 40-byte entry past the end, lands in adjacent kalloc data,
    almost certainly survives. NON-CRASHING CONFIRMATION that the bound is
    missing. Safest possible first test. ***
  RECIPE B (Candidate B): Data = 0x11C bytes; decompressBufferRequested = 1
    (allocSize 512); blocksRunCount = 2; entry[0] entryType 0x80000007 (LZFSE),
    sectorNumber 0, sectorCount 1, compressedOffset 0,
    compressedLength = 0x10000000. File must be >= 256 MiB (sparse is fine).
    GENTLER VARIANT FIRST: compressedLength = 0x1000, file ~8 KB. Writes 4096
    FULLY ATTACKER-CHOSEN bytes starting 3584 bytes before a kalloc.512
    element. Expect no immediate fault but a DELAYED zone-integrity panic
    ("a freed zone element has been modified in zone kalloc.512", zone_require
    failure, or a corrupted-pointer abort seconds later). Fill with 0x41424344
    repeating so the panic log's corrupted-value field confirms the source.
    Use entryType 0x80000005 (zlib) with this to get the write WITHOUT the
    decoder read (overlap guard returns 0x3e9) - that separates the two
    primitives cleanly.
  Both recipes fire during attach / first read of sector 0, before any mount, so
  the data fork can be all zeros - no mountable filesystem needed inside.

WHAT WOULD CLOSE THIS OUT (highest value first)
  1. *** DIFF AGAINST A 14.0 KERNELCACHE *** (any A8 tvOS/audioOS 14.0, or even
     iOS 14.0 - the UDIF kext is shared). If merge_blkx gains an
     OSData::getLength() call before the 0xdcc060 analogue, Candidate A is
     CONFIRMED as 9965/9966. If KDIUDIFDiskImage::read gains a compare against
     [sp,#0x58] before the `sub`, Candidate B is confirmed. Cheap - the agent's
     kc.py/kdisasm.py in /home/claude/dmgaudit/ load another cache as-is.
  2. Recipe A variant 1 on the bench unit (non-destructive).
  3. UNVERIFIED: whether hdik actually routes through IOHDIXControllerUserClient
     selector 0 vs a sysctl/boot path. The agent audited the kernel side only
     and did not look at the hdik binary. Attach /usr/sbin/hdik from the IPSW to
     settle it.
  4. UNVERIFIED: KDIRAMBackingStore and KDIReadWriteDiskImage (shadow files),
     only skimmed. Small (0x640 and 0x288 bytes of text).

COMPARISON WITH THE pppd RESULT (R25): pppd gave us a 1-byte fixed-value write
and some reads - no good. **Candidate B here gives attacker-controlled LENGTH
AND CONTENT into a heap underflow. That is categorically better and is the best
code-execution lead in the project so far.**

================================================================================
R28 — KERNEL AUDIT AGAINST THE COMPILED BINARY. CVE-2020-27932 CONFIRMED
      VULNERABLE. tachy0n IS PATCHED (RETRACTS R22). zone_require BLOCKS THE
      NAIVE PRIMITIVE.
================================================================================
R28.0 KERNEL IDENTITY — VERIFIED, and the version numbering matters
--------------------------------------------------------------------
file offset 0x2fb04:
  @(#)VERSION: Darwin Kernel Version 19.6.0: Fri Jun 26 21:16:39 PDT 2020;
  root:xnu-6153.143.1~3/RELEASE_ARM64_T7000
Corroborated by build paths e.g. .../xnu/xnu-6153.143.1/bsd/net/bpf.c @0x22f24c.
cputype = plain arm64 (NO PAC, confirmed in the binary). No LC_DYLD_CHAINED_FIXUPS.
LC_SYMTAB present but **nsyms = 0** (stripped). LC_FUNCTION_STARTS present ->
65,119 functions in __TEXT_EXEC (vm 0xfffffff007640000, file 0x63c000, size
0xffc000). __TEXT,__thread_starts present => __DATA* pointers are iOS-12-style
threaded rebase: va = (raw & 0x7ffffffffff) | 0xffffff8000000000.
__PRELINK_TEXT is ZERO-LENGTH: all 143 prelinked kexts are merged into the one
__TEXT_EXEC, so kext code is in the same function-starts list.
*** CORRECTION TO MY OWN PREMISE: xnu-6153.143.1 (2020-06-26) is NUMERICALLY
LATER than iOS 13.6's xnu-6153.141.1. Every "13.x never got this fix" assumption
has to be re-checked against that date. One of them bites - see R28.2. ***

R28.1 *** CVE-2020-27932: CONFIRMED VULNERABLE IN THE COMPILED KERNEL ***
--------------------------------------------------------------------------
Not inferred from the XNU tag - read out of the bytes on this device.
host_request_notification = **0xfffffff00767c194** (len 0x1ec), located three
independent ways that all converge:
 (a) zone name "host_notify" @0xfffffff007224083 has ONE code xref ->
     host_notify_init 0xfffffff00767c0f4, which does queue_init x2,
     lck_grp_init("host_notify"), zinit(0x18, 0x18000, ...). That yields the
     globals: host_notify_queue 0xfffffff0087aee90, host_notify_zone
     0xfffffff0087aeeb8, host_notify_lock 0xfffffff00872eb98.
 (b) only one function in the cluster references the zone twice (zalloc+zfree)
     AND the queue base AND takes host_notify_lock.
 (c) MIG: its only caller 0xfffffff0076dd0d8 = _Xhost_request_notification; a
     data pointer to that stub sits at 0xfffffff0074a7460 =
     routine[17].stub_routine of the mach_host subsystem table (header
     0xfffffff0074a7190: server 0xfffffff0076dc374, start 200, end 235,
     maxsize 0x430, routine[0] 0xfffffff0074a71b0, stride 40).
     (0xfffffff0074a7458-0xfffffff0074a71b0)/40 = 17 => **msgh_id = 217**,
     argc 3, max_reply_msg 0x2c.
     (A naive mach_host.defs parse says 218 and is WRONG: the #if KERNEL/#else
      pair at defs 107-111 makes host_page_size/_host_page_size ONE routine.)

THE CONDITION CHAIN - ONLY THREE TERMS:
  0xfffffff00767c254  bl   0xfffffff00765a098   ; ipc_object_lock(port)
  0xfffffff00767c258  ldr  w8, [x21]            ; io_bits (+0x00)
  0xfffffff00767c25c  tbz  w8, #0x1f, ...c274   ; !ip_active -> FAIL
  0xfffffff00767c260  ldr  w9, [x21, #0x98]     ; bitfield word
  0xfffffff00767c264  and  w9, w9, #8           ; bit 3 == ip_tempowner
  0xfffffff00767c268  and  w8, w8, #0x3ff       ; io_bits & IO_BITS_KOTYPE
  0xfffffff00767c26c  orr  w8, w9, w8
  0xfffffff00767c270  cbz  w8, ...c29c          ; both zero -> SUCCESS
= verbatim `if (!ip_active(port) || port->ip_tempowner ||
             ip_kotype(port) != IKOT_NONE)`.
**NO test of bit 6 (ip_specialreply). NO ip_is_kolabeled test.** The latter is
AFFIRMATIVELY EXCLUDED: `and w8,w8,#0x3ff` masks OFF bit 10
(IO_BITS_KOLABEL = 0x400), which the patched xnu-7195 condition would have had
to include. Both xnu-7195 patch terms are absent. The agent looked specifically
for the negative result (a `tbz/tbnz w9,#6` or a `#0x7ff` mask) and it is not
there.
Success path 0xfffffff00767c29c: `str x21,[x19,#0x10]` (entry->port = port) then
inlined ipc_kobject_set_atomically: kotype <- 0x10 = **IKOT_HOST_NOTIFY**
(`orr w9,w9,#0x10` @0xfffffff00767c2a8), kdata(+0x68) <- entry,
io_bits |= 0x800 (IO_BITS_KOBJECT).

ipc_port_adjust_special_reply_port_locked = **0xfffffff00765d7f4** (len 0x4bc),
found by scanning for `ubfx wD,wS,#7,#3` (the ip_sync_link_state extraction);
identification overdetermined by the ip_specialreply test, the UNLINK_THREAD /
RESET_BOOSTRAP_CHECKIN flag handling, filt_machport_stash_port
(0xfffffff0076611b0) and turnstile_complete (0xfffffff0076c5c00).
THE UNGUARDED READ:
  0xfffffff00765d9b0  ubfx w10, w8, #7, #3     ; sync_link_state
  0xfffffff00765d9c4  cmp  w10, #1             ; PORT_SYNC_LINK_PORT
  0xfffffff00765d9c8  b.ne ...d9e0
  0xfffffff00765d9cc  ldr  x22, [x19, #0x68]   ; ip_sync_inheritor_port
                                               ; <-- NO kobject re-check
Between the +0x98 load and the +0x68 load there is NO ip_kotype,
ip_is_kobject or zone check of any kind. CONFIRMED UNGUARDED.
Consumed at the tail: 0xfffffff00765dafc bl ipc_port_send_turnstile_complete,
then inlined ip_release (`ldr w9,[x8,#4]!`), then on reaching zero
`ldrh w8,[x22,#2]` (io_otype), `ldr x0,[x24,x19,lsl#3]` (ipc_object_zones[]),
`bl 0xfffffff0076d28bc` = zfree.

R28.2 *** RETRACTION OF R22: tachy0n / CVE-2020-9859 IS **PATCHED** HERE ***
-----------------------------------------------------------------------------
R22 said tachy0n was live and that its heap-shaping deps were present. The deps
ARE present, but THE BUG IS FIXED. VERIFIED.
The fix was first pinned from Apple's own source: diffing bsd/kern/kern_aio.c
between xnu-6153.121.1 (iOS 13.5, vulnerable) and xnu-6153.141.1 (13.6, fixed)
gives exactly the lio_listio context-ownership change - the "lio_context
ownership rules" comment, three `lio_context->io_issued--` ->
`if (--lio_context->io_issued == 0) { free_context = TRUE; }`, a new
`if (free_context) goto ExitRoutine;`, removal of the
`case LIO_NOWAIT: if (io_issued == 0) free_context = TRUE;` arm, and
`io_waiter = 0` moved into the EINTR handoff branch.
lio_listio in THIS binary = **0xfffffff007a0530c** (len 0x590), found via the
msleep wait-channel string "lio_listio" @0xfffffff0072575b1 (single xref
0xfffffff007a057b0). It is the POST-FIX version at every point:
  all three decrement sites (0xfffffff007a05598, ...56e8, ...5760):
    ldr w8,[x19,#4] ; subs w8,w8,#1 ; str w8,[x19,#4]
    csinc w28,w28,wzr,ne            ; if (result == 0) free_context = TRUE
  0xfffffff007a05790  cbnz w28, ...580c      ; if (free_context) goto Exit  <-- FIX ONLY
  0xfffffff007a05794  ldr  w8,[x24] ; cmp w8,#2   ; single if (mode==LIO_WAIT),
                                                 ; not the old switch
  0xfffffff007a057f8  mov  w28,#0            ; old io_issued==0 arm GONE
  0xfffffff007a05850  str  wzr,[x19]         ; io_waiter=0 in the else-branch
*** DO NOT BUILD ON tachy0n FOR THIS DEVICE. *** Consistent with the dates once
read correctly: this kernel is xnu-6153.143.1 built 2020-06-26, AFTER the
13.5.1 fix (2020-06-01). "iOS 13.0-13.5" does not cover this audioOS build.
(aio_lio_context layout, incidental: io_waiter +0x00, io_issued +0x04,
io_completed +0x08, size 0x0c.)

R28.3 struct ipc_port OFFSETS — sizeof = 0xa8, VERIFIED FROM INSTRUCTIONS
--------------------------------------------------------------------------
zinit @0xfffffff007652714: `mov w0,#0xa8` ; `mul x1,ipc_port_max,#0xa8` ;
x3 = "ipc ports" ; str x0,[ipc_object_zones+0]. With ip_sorights at 0xa4 (4 B)
the struct closes exactly at 0xa8, leaving NO spare bytes - which is what makes
the two INFERRED rows safe.
  0x00 io_bits        VERIFIED  bit31 ACTIVE, bits0-9 KOTYPE, bit10 KOLABEL,
                                bit11 KOBJECT, bit15 PREALLOC, bits16-30 OTYPE
  0x04 io_references  VERIFIED  ldr w9,[x8,#4]! in inlined ip_release
  0x08 io_lock_data   VERIFIED
  0x10 ip_messages    VERIFIED fields / size 0x50 INFERRED
       waitq lock +0x18/+0x1c, imq_set_id +0x20, waitq_ts +0x30,
       ikmq_base +0x40, imq_seqno +0x48, imq_receiver_name +0x4c,
       imq_msgcount +0x50 (u16), imq_qlimit +0x52 (u16),
       imq_srp_owner_thread +0x58  => ends 0x60
  0x60 data.receiver/destination/timestamp   INFERRED (forced - only slot left)
  **0x68 kdata: ip_kobject / ip_kolabel / ip_imp_task /
       ip_sync_inheritor_port/_knote/_ts**   VERIFIED
  0x70 ip_nsrequest   VERIFIED     0x78 ip_pdrequest   VERIFIED
  0x80 ip_requests    VERIFIED (ipc_port_finalize 0xfffffff00765f848)
  0x88 kdata2: ip_premsg / ip_send_turnstile   VERIFIED
  0x90 ip_context     VERIFIED (mach_port_set_context 0xfffffff00766cf5c)
  **0x98 bitfield word**  VERIFIED
  0x9c ip_mscount  0xa0 ip_srights  0xa4 ip_sorights   all VERIFIED
  0xa8 sizeof         VERIFIED
BITFIELD AT +0x98 (cross-checked independently via
mach_port_get_attributes/RECEIVE_STATUS at 0xfffffff00766d994, which maps bits
to the public MACH_PORT_STATUS_FLAG_* values and so pins declaration order):
  bit 0,1  ip_sprequests, ip_spimportant      INFERRED (decl order)
  bit 2    ip_impdonation                     VERIFIED
  **bit 3  ip_tempowner**                     VERIFIED
  bit 4    ip_guarded                         VERIFIED
  bit 5    ip_strict_guard                    VERIFIED
  **bit 6  ip_specialreply**                  VERIFIED
  **bit 7-9 ip_sync_link_state**              VERIFIED
  bit 10   ip_sync_bootstrap_checkin          VERIFIED
  bit 11   ip_immovable_receive               VERIFIED
  bit 12   ip_no_grant                        VERIFIED
  bit 13   ip_immovable_send                  INFERRED
  bit 14-31 ip_impcount                       INFERRED
ip_srp_lost_link / ip_srp_msg_sent are DEVELOPMENT||DEBUG only and are ABSENT
from this RELEASE build (consistent with sizeof 0xa8).
OTHER CONSTANTS, all VERIFIED:
  IKOT_HOST_NOTIFY = 0x10
  sizeof(host_notify_entry) = 0x18, .port at +0x10 => the element is just
    { queue_chain_t entries; ipc_port_t port; } - NO type field
  ipc_object_zones[] = 0xfffffff00872e190 ([0]="ipc ports",[1]="ipc port sets")
  sizeof(ipc_pset) 0x60, sizeof(ipc_kmsg) 0x100, kmsg prefix 0x58,
    ikm_header at kmsg+0x18, ikol_kobject at +0x08
  MAX_TRAILER_SIZE 0x44, MACH_MSG_TRAILER_MINIMUM_SIZE 8
  helpers: ipc_object_lock 0xfffffff00765a098, zalloc 0xfffffff0076d2190,
    zfree 0xfffffff0076d28bc, zinit 0xfffffff0076d0068,
    zone_require 0xfffffff0076cfd44, panic 0xfffffff008639a28,
    ipc_kmsg_alloc 0xfffffff007652a00,
    ipc_kmsg_get_from_kernel 0xfffffff007653760,
    mach_msg_send_from_kernel_proper 0xfffffff00767ed64,
    ipc_port_send_turnstile_complete 0xfffffff00765dcb0,
    ipc_port_finalize 0xfffffff00765f848

R28.4 TRIGGER SEQUENCE FOR 27932 ON THIS BUILD — ORDER IS THE WHOLE TRICK
--------------------------------------------------------------------------
 1. host_t host = mach_host_self();   plain host NAME port. The MIG stub only
    does convert_port_to_host (bl 0xfffffff00767ce3c) on msgh_remote_port and
    NEVER consults the task => no entitlement, no sandbox exception, no privilege.
 2. thread_get_special_reply_port(&srp);  -> ip_specialreply=1 (bit 6 @+0x98),
    ip_sync_link_state = PORT_SYNC_LINK_ANY (0), ip_kotype = IKOT_NONE,
    ip_tempowner = 0, ip_active = 1.
 3. **LINK IT FIRST.** Put the port in PORT_SYNC_LINK_PORT (1) with a BLOCKING
    sync-IPC send that uses srp as the reply port:
    mach_msg(..., MACH_SEND_MSG|MACH_RCV_MSG|MACH_RCV_SYNC_WAIT, ...) with
    msgh_local_port = srp / MACH_MSG_TYPE_MAKE_SEND_ONCE, to a port whose
    receive right is held by another thread or process we control so the send
    actually blocks. Kernel then sets ip_sync_link_state <- 1 and
    kdata(+0x68) <- dest_port.
 4. **THEN** host_request_notification(host, HOST_NOTIFY_CALENDAR_CHANGE /*0*/,
    srp). The gate only looks at ip_active / ip_tempowner / ip_kotype, all of
    which still pass, so it OVERWRITES kdata(+0x68) with the 24-byte
    host_notify_entry*, sets kotype = IKOT_HOST_NOTIFY and IO_BITS_KOBJECT, and
    LEAVES ip_sync_link_state == 1 UNTOUCHED. That mismatch IS the bug, and is
    exactly what the missing ip_specialreply term would have blocked.
    ON THE WIRE (VERIFIED from the stub): msgh_id 217, msgh_size 0x40,
    MACH_MSGH_BITS_COMPLEX REQUIRED (tbz w8,#0x1f @0xfffffff0076dd100),
    msgh_descriptor_count == 1 (@0xfffffff0076dd108), and the port descriptor's
    disposition byte must be MACH_MSG_TYPE_MOVE_SEND_ONCE = 18 with descriptor
    type 0 (ldrh w8,[x20,#0x2e]; cmp w8<<16,#0x120000 @0xfffffff0076dd11c).
    The stock MIG stub satisfies this: it declares mach_port_make_send_once_t,
    so userspace passes the receive-right name with MAKE_SEND_ONCE and copyin
    rewrites it to MOVE_SEND_ONCE kernel-side. Request layout: header 0x00-0x20,
    msgh_body 0x20, port descriptor 0x24-0x34 (port at 0x24), NDR 0x34-0x3c,
    notify_type at 0x3c. Wrong disposition -> MIG_TYPE_ERROR (-300); malformed
    -> -304.
 5. Drive ipc_port_adjust_special_reply_port_locked: let the blocked mach_msg
    complete, the reply land, or the thread exit. It reads kdata(+0x68) - now a
    host_notify_entry* - as dest_port.

R28.5 *** zone_require WILL PANIC THE NAIVE PRIMITIVE. PLAN AROUND IT. ***
---------------------------------------------------------------------------
The first consumer of the confused pointer, ipc_port_send_turnstile_complete
0xfffffff00765dcb0, OPENS with inlined ipc_object_validate -> zone_require:
  0xfffffff00765dccc  ldr  w8,[x19],#0x1c
  0xfffffff00765dcd0  and  w8,w8,#0x7fff0000      ; io_otype
  0xfffffff00765dcd4  cmp  w8,#0x10,lsl #12       ; == IOT_PORT_SET ?
  0xfffffff00765dce4  ldr  x1,[x9,w8,uxtw #3]     ; ipc_object_zones[otype]
  0xfffffff00765dce8  bl   0xfffffff0076cfd44     ; zone_require
zone_require bounds-checks the zone map (0xfffffff008731db0/db8), indexes the
metadata region (0xfffffff008731dc0, stride 0x18), reads the 10-bit zindex at
metadata+0x16 and compares with zone->index at zone+0x118; on mismatch panics
via 0xfffffff0076cfe04 with 0xfffffff0072276ac:
  "Address not in expected zone for zone_require check (addr: %p, zone: %s)"
Our host_notify_entry lives in the 24-byte "host_notify" zone, while io_otype
is read out of entry->entries.next (the queue-chain pointer enqueue_tail just
installed, e.g. 0xfffffff0087aee90) -> masked 0x087a0000 != 0x00010000 ->
selects ipc_object_zones[0] = "ipc ports". MISMATCH => that panic, naming our
entry's address and zone "ipc ports". Sibling string 0xfffffff00722766e
("Address not in zone map ...") fires if the pointer is outside the zone map.
=> zone_require, a xnu-6153-era mitigation, is COMPILED IN on this RELEASE
   build and sits directly across the obvious
   PORT_SYNC_LINK_PORT -> ip_release -> zfree cross-zone-free primitive.

THREE WAYS ROUND, in the agent's order of preference:
 1. *** USE THE OTHER UNGUARDED READ IN THE SAME FUNCTION. *** The
    inheritor-computation switch at **0xfffffff00765dbcc** (reached when
    get_turnstile == FALSE, port still active and special-reply, and it has a
    receive turnstile - checked 0xfffffff00765da54-da60) does, for case
    PORT_SYNC_LINK_PORT: `ldr x9,[x19,#0x68]` (confused pointer),
    `ldrb w9,[x9,#1]; tbz w9,#7` (ONLY an IP_BITS_PREALLOC test), then
    `ldr x1,[x9+0x88]` or `ldr x8,[x9+0x88]; ldr x1,[x8+0x50]`, and hands x1
    straight to turnstile_update_inheritor(..., flags=9) at 0xfffffff0076c721c
    - **with NO zone_require anywhere on that path**, and it executes BEFORE
    the dest_port release at 0xfffffff00765daf8. A fake-turnstile /
    controlled-inheritor primitive is the better door. Reach it via
    ipc_port_adjust_special_reply_port(port, flags), the wrapper that passes
    get_turnstile = FALSE.
 2. GROOMING LEVER: both offsets the confused path touches beyond the 24-byte
    element - +0x88 (turnstile) and +0x04 (io_references) - read ADJACENT
    host_notify-ZONE memory, i.e. neighbouring host_notify_entry elements. We
    can allocate and partly control those by registering many notifications
    (each host_request_notification call allocates one 24-byte element and
    writes a port pointer at +0x10). That is the realistic way to control what
    the confused dereference sees.
 3. Making io_otype select a matching zone index is a DEAD END - we only
    influence entries.next through the queue structure itself. The field we
    genuinely control, entry->port at +0x10, is NOT read by the confused path.
QUIETER FAILURE MODE to recognise: if the word at entry+0x04 (the high half of
entries.next, typically 0xfffffff0) is not 1, ip_release just decrements it and
returns, silently corrupting that queue pointer. The panic then arrives LATER
from the next host_notify_all/remqueue as "Invalid queue element pointers for
%p: next %p prev %p" (0xfffffff00726bae1) or "Invalid queue element linkage for
%p" (0xfffffff00726bb1a). On the path as written, zone_require fires first.

R28.6 OTHER CVEs — HONEST STATUS
----------------------------------
CVE-2020-27950: vulnerable SHAPE present, FIX ABSENT (VERIFIED absent) /
  exploitable INFERRED. The fix was identified by diffing osfmk/ipc/ipc_kmsg.c
  6153.141.1 -> 7195.50.7.100.1: an added `bzero(trailer, sizeof(*trailer));`
  immediately before the msgh_trailer_type/size init (7195 lines 2043 and 2150,
  absent at the corresponding 6153 lines 1698/1804). Neither
  REQUESTED_TRAILER_SIZE_NATIVE*/GET_RCV_ELEMENTS nor ipc_kmsg_add_trailer
  changed between those tags, so the bzero IS the fix.
  Three trailer-init sites examined in this binary (found by scanning for
  `add w?,w?,#0x44` feeding ipc_kmsg_alloc): 0xfffffff007653760
  (= ipc_kmsg_get_from_kernel, first callee of
  mach_msg_send_from_kernel_proper, itself reached from host_notify_all),
  0xfffffff00766b240, 0xfffffff00767f29c.
  **NONE of the three contains a bzero/memset of the 0x44-byte trailer.** In
  each, +0x08 (msgh_seqno) and +0x34..+0x44 keep whatever the zone element
  previously held. OPEN: the specific 4-byte leak was NOT reproduced, the exact
  invalid MACH_RCV_TRAILER_ELEMENTS value was NOT pinned, and
  ipc_kmsg_add_trailer (the read-out side) was NOT located. ~1 hour of work if
  we need this as a working infoleak rather than a "fix is absent" finding.
CVE-2020-9975  (Tielei Wang, kernel UAF): **COULD NOT DETERMINE.** No public
  patch diff, no P0 RCA, no PoC; Apple's advisory names no subsystem. With no
  known patch to look for there is nothing to compare against. Date-based
  inference only (first fixed 14.0; this kernel 2020-06-26) => INFERRED likely
  present, NOT VERIFIED. Recorded as undetermined rather than dressed up.
CVE-2020-10013 (Yu Wang, Wi-Fi logic): **COULD NOT DETERMINE**, same reason.
  What IS verified: the surface is prelinked here. __PRELINK_INFO,__info
  (file 0x1744848, 0x6e286 bytes) lists 143 kexts including
  com.apple.driver.AppleBCMWLANCore, AppleBCMWLANBusInterfacePCIe,
  com.apple.iokit.IO80211Family and BCMWLANFirmware4357.Hashstore. Because
  __PRELINK_TEXT is zero-length those driver functions are in the same
  65,119-entry function-starts list and are reachable with /home/claude/kaudit/
  tooling IF we later get a patch reference to diff against.
CVE-2020-27930 (FontParser): **NOT APPLICABLE to this binary.** FontParser is
  USERLAND (libFontParser.dylib via CoreGraphics/CoreText). Zero matches for
  FontParser / libType1Scaler / CGFont anywhere in kernel.macho, and no
  font-parsing kext in the prelink list. Status on this device can neither be
  confirmed nor refuted from the kernelcache - would need the dyld shared cache
  from the same build. It is also the Safari-side RCE in the P0 chain, so it is
  NOT on the path from signed boot to kexec on a bench device we already have
  code execution on. Drop it from the plan.

R28.7 NET EFFECT ON THE PLAN
------------------------------
  - 27932 is CONFIRMED on the device, with the exact msgh_id, wire format and
    struct offsets an exploit must hardcode. The kernel step is real.
  - tachy0n is OUT (patched). R22 retracted.
  - 27930 is OUT (userland, wrong layer).
  - 9975 / 10013 are UNKNOWN and will stay unknown without a patch reference.
  - The kernel step now has a KNOWN MITIGATION IN THE WAY (zone_require) and a
    KNOWN WAY AROUND IT (the turnstile-inheritor path at 0xfffffff00765dbcc).
  - Still unchanged: we need NATIVE CODE EXECUTION in userland first. The
    27932 trigger is pure Mach IPC (mach_host_self +
    thread_get_special_reply_port + mach_msg + host_request_notification, all
    ordinary libsystem exports), so the ROP budget is small - but it is still
    ROP, and the bridge to it is still the open problem. R27's UDIF Candidate B
    (attacker-controlled length AND content heap underflow write, in the KERNEL,
    reachable from trust-cached hdik with no code of ours) remains the best
    route and does not need userland native code at all.

================================================================================
R29 *** root-live-fs IS AN NVRAM VARIABLE, NOT A BOOT-ARG. THIS IS THE
    PLANTING LEVER WE HAVE BEEN MISSING. *** 2026-11-26 20:20 PST
================================================================================
Verified locally against /home/claude/kc/kernel.macho (no pod time spent).

The string "root-live-fs" is at file offset 0x3f4b43 (VA 0xfffffff0073f8b43),
in the APFS kext's string table next to "enable-remap-mode" and
"no-effaceable-storage". It has EXACTLY ONE code xref: 0xfffffff0084983c0.

THE READ SITE (VERIFIED, disassembled):
  0xfffffff0084983ac  bl   0xfffffff007c1d728     ; precondition; tbz w0,#0 -> bail
  0xfffffff0084983b4  adrp x0, 0xfffffff00726b000
  0xfffffff0084983b8  add  x0, x0, #0x6f9         ; x0 = "/options"
  0xfffffff0084983bc  adrp x1, 0xfffffff0073f8000
  0xfffffff0084983c0  add  x1, x1, #0xb43         ; x1 = "root-live-fs"
  0xfffffff0084983c4  add  x2, sp, #8             ; x2 = &out
  0xfffffff0084983c8  bl   0xfffffff0084982a4     ; the lookup helper
  0xfffffff0084983cc  cbz  w0 -> bail
  0xfffffff0084983d0  ldr  x0, [sp, #8]           ; the returned OSObject*
  0xfffffff0084983dc  ldr  x1, [x8, #0x180]       ; a metaclass
  0xfffffff0084983e0  bl   0xfffffff007b3224c     ; OSMetaClassBase::safeMetaCast
  0xfffffff0084983e4  cbz  x0 -> bail
  0xfffffff0084983e8  ldr  x8, [x0]
  0xfffffff0084983ec  ldr  x8, [x8, #0xf0]        ; virtual +0xf0
  0xfffffff0084983f0  adrp x1, 0xfffffff0072c8000
  0xfffffff0084983f4  add  x1, x1, #0x2cc         ; x1 = "0"
  0xfffffff0084983f8  mov  w2, #1
  0xfffffff0084983fc  blr  x8                     ; isEqualTo("0", 1)
  0xfffffff008498400  eor  w19, w0, #1            ; result = !isEqualTo("0")
THE LOOKUP HELPER 0xfffffff0084982a4 (VERIFIED):
  ldr  x1, [x8, #0x8d0]          ; a global = gIODTPlane
  mov  x2,#0 ; x3,#0 ; x4,#0
  bl   0xfffffff007b857f0        ; IORegistryEntry::fromPath(path, plane, ...)
  cbz  x0 -> fail
  ldr  x8,[x0] ; ldr x8,[x8,#0x148] ; mov x1, <name> ; blr x8   ; copyProperty
  str  x21,[x20]                 ; *out = result
  ... release both
STRINGS CONFIRMED by reading them out of the file:
  0xfffffff00726b6f9 = "/options"      0xfffffff0072c82cc = "0"
  0xfffffff0073f8b43 = "root-live-fs"

=> The kernel resolves this as an **IOREGISTRY PROPERTY ON THE DEVICE-TREE
   /options NODE, WHICH IS NVRAM**. It is NOT PE_parse_boot_argn, so it is NOT
   a boot-arg. The iBoot console `setenv` gate (4 names only) is IRRELEVANT
   here - that gate is iBoot-side, and this is the kernel reading NVRAM.
=> SEMANTICS: boot the LIVE volume if the value is ANYTHING OTHER THAN the
   string "0". Absent => the `cbz` after the lookup bails => snapshot. Which
   matches job 590: root-live-fs is not set, and the pod boots the snapshot.
=> `/usr/sbin/nvram` exists on BOTH the ramdisk and the System volume, we run as
   root on the ramdisk, and job 589 captured its full usage including
   `-b <name> <binary file>` and `-d <name>` to delete.

*** WHY THIS MATTERS: IT SOLVES THE PLANTING PROBLEM. ***
Up to now every cold-boot test was blocked because an APFS snapshot is
read-only by design and the booted system IS the snapshot, so anything we wrote
to /mnt1 would be written into a system that never runs (see R26). With
root-live-fs set, the pod boots the LIVE volume, which IS writable from the
ramdisk. That is the bridge for every cold-boot experiment we have queued up:
the hdik/UDIF test (R27), the pppd/ACSP test (R25), and the AMFI shebang-script
primitive (R24.1).

THE CATCH, and it is a real one: the live volume currently holds the STAGED
MODERN SYSTEM (227 /usr/libexec entries, exclaves daemons, tvOS 27.2 binaries).
Its cdhashes are NOT in the StaticTrustCache (which job 590 showed is identical
on both sides, 17595 bytes). Booting it as-is would fail at launchd exactly as
job 560 did: "Process 1 exec of /sbin/launchd failed, errno 2". So the live
volume must first be made into a 13.4.8 system.
THREE WAYS, safest last:
 (a) copy the snapshot over the live volume from the ramdisk (tar / cp / asr are
     all present). Big operation, could fail partway, recoverable by restore.
 (b) `snaputil` revert, IF this build's snaputil supports reverting the live
     volume to a snapshot. Far cleaner than a manual copy. Usage capture is in
     job 591 (B5).
 (c) *** RESTORE TO 17M61 CLEAN, DISABLE AUTOMATIC UPDATES IMMEDIATELY, and
     never let it stage anything. Then live volume == snapshot content, there is
     nothing to undo, and root-live-fs just works. THIS IS THE SAFE PATH and it
     is the restore Nic was already planning. ***

R29.1 JOB 591 QUEUED (read-only, one cycle, answers both things at once)
-------------------------------------------------------------------------
  B0 FULL `nvram -p` dump as a baseline BEFORE we ever write NVRAM
  B1 df / volume space (a full volume would itself explain a failed apply)
  B2 /private/var/MobileSoftwareUpdate staging state, incl. softwareupdated,
     Updates, mobileassetd, log, preflight subdirs
  B3 any readable MSU/update log text (tail), /private/var/logs listing, and a
     bounded `find` to depth 3
  B4 raw `grep -a` over the staged plists for ProductVersion /
     ProductBuildVersion / Fail* / Error* - plconvert returns error 3840 on
     every plist on this ramdisk (R26.2), so grep the bytes instead
  B5 `snaputil` usage - does it support revert? (decides option (b) above)
  B6 read-only probe: `nvram root-live-fs` and
     `ioreg -p IODeviceTree -n options`
  B7 FUD trust-cache sizes on both sides
  Plus a pod-get of restore.log if it exists.
  NOTHING IS WRITTEN. No cold boot needed.

R29.2 STANDING REMINDERS NOT TO LOSE (consolidated, since a lot is in flight)
-------------------------------------------------------------------------------
OWED / UNDONE ON THE POD:
  - Delete the now-inert `boot-command` and `upgrade-fallback-boot-command`
    NVRAM variables we set earlier (job 583 proved them inert).
  - Turn OFF automatic updates (Nic's note; never done on this unit).
  - Do NOT use `clearenv` - it would reset com.apple.System.boot-nonce and
    invalidate the saved SHSH blobs.
  - Save `nvram -p` before any NVRAM write (job 591 B0 does this).
  - Never mount /dev/disk1s2 (encrypted Data volume - hangs the ramdisk).
  - Revert-first rule: never write a block without saving the original bytes to
    runner/files/ first.
OPEN QUESTIONS STILL UNANSWERED:
  - Does `hdik` route through IOHDIXControllerUserClient selector 0, or a
    sysctl/boot path? (R27 item 3 - needs the hdik binary from the IPSW)
  - Is _ROOT_PATH redefined in Apple's embedded ppp build settings? If not,
    /etc/ppp/options is live on 13.4.8 (R25.4). Cheap test: syntax error in
    that file, see if pppd exits with an option error.
  - Does the Dialogs plugin that gates the chap_ms.c candidate exist on device?
  - CVE-2020-27950: the fix (a trailer bzero) is absent at all three sites, but
    the 4-byte leak was never reproduced and ipc_kmsg_add_trailer was never
    located. ~1 hour to turn into a working infoleak.
  - CVE-2020-9975 / CVE-2020-10013: undeterminable without a patch reference.
    The Wi-Fi surface IS prelinked here (AppleBCMWLANCore,
    AppleBCMWLANBusInterfacePCIe, IO80211Family, BCMWLANFirmware4357).
  - KDIRAMBackingStore and KDIReadWriteDiskImage (shadow files) only skimmed.
  - MobileStorageMounter holds can-load-trust-cache and takes PATHS; never
    audited. It is the entitled front door to loadTrustCache (R26.1).
  - The `di-root-image` / `di-root-ram-file` BOOT-ARG path into the same UDIF
    parser, no user client and no entitlement (R27). Unreachable while we cannot
    set boot-args, but it is the natural Nicotine boot mechanism if we ever can.
AGENT RUNNING: 14.0 kernelcache diff, to confirm whether merge_blkx gains a
  getLength() call and KDIUDIFDiskImage::read gains a compressedLength compare
  => would confirm R27's candidates ARE CVE-2020-9965/9966. Also cross-checks
  host_request_notification in 14.0 to validate the patch-diff method itself.
PUBLICATION: the two acsp.c bugs (R25.3) are fixed in Apple's current release
  but live on every un-updated device, and never got a CVE. Nic's call.

================================================================================
R30 — JOB 591. *** I MUST RETRACT THE "STAGED OTA" EXPLANATION. *** PLUS THE
      REVERT TOOL WE NEED, AND A BOOT-ARGS FACT I GOT WRONG EARLIER.
      2026-11-26 20:18 PST
================================================================================
R30.0 *** RETRACTION: THERE IS NO STAGED OTA ON THIS POD. ***
---------------------------------------------------------------
  /mnt1/private/var/MobileSoftwareUpdate  =>  total 0  (just . and ..,
      dated Nov 6 2026). Every subdir probed (softwareupdated, Updates,
      mobileassetd, log, preflight) does not exist. A bounded `find` to depth 3
      returns the directory itself and nothing else.
  /mnt1/private/var/logs => empty (WindowServer, hidfw-crashlogs, mediaserverd,
      all empty, Nov 6).
=> R26's mechanism ("the OTA downloads and stages into the live volume, then
   fails to commit") is NOT SUPPORTED BY THE EVIDENCE and is RETRACTED. There is
   no staged payload on disk and no updater log to read.
=> **I CANNOT TELL NIC WHY A 13.4.8 POD NEVER FINISHES UPDATING.** The pod has
   no record of ever having tried. Do not give him the staging story as an
   answer - it was my inference, and this job falsified it.

WHY THE LOGS ARE GONE, and it is in NVRAM (VERIFIED, job 591 B0):
  oblit-begins  = "OblitType: ObliterateDataPartition. Reason: Device was left
                   in a partially-setup state"
  obliteration  = "handle_message: Obliteration Complete%0a"
The Data partition was obliterated because the device was left part-way through
setup. That wipes /private/var, which is exactly where the updater's state and
logs would have lived. So this pod cannot answer the question even in principle
until it is allowed to attempt an update with the Data partition intact.

SO WHAT DOES EXPLAIN THE LIVE-vs-SNAPSHOT SPLIT? Best remaining explanation,
labelled INFERRED: a RESTORE ARTIFACT, not an OTA. The live volume holds a
newer system (227 /usr/libexec entries, exclaves daemons, tvOS 27.2 binaries,
many files dated Nov 6 2026) while the booted snapshot holds 13.4.8 (132
entries). Mixed mtimes within one volume (Nov 6 AND Nov 26) say it was written
at two different times. Most likely the 13.4.8 downgrade installed 13.4.8 as the
com.apple.os.update-* snapshot over a volume whose live state still held the
newer system from an earlier restore. NOT VERIFIED - and we do not need to
settle it to proceed.

R30.1 *** snaputil CAN REVERT. THIS IS THE TOOL WE NEEDED. *** (VERIFIED)
--------------------------------------------------------------------------
Full usage captured from the ramdisk:
  snaputil -l <vol>                   List all snapshots
  snaputil -c <snap> <vol>            Create snapshot
  snaputil -n <snap> <newname> <vol>  Rename snapshot
  snaputil -d <snap> <vol>            Delete snapshot
  snaputil -r <snap> <vol>            **Revert to snapshot**
  snaputil -s <snap> <vol> <mntpnt>   Mount snapshot
  snaputil -o                         Print original snapshot name
=> `snaputil -r com.apple.os.update-8AD664B2... /mnt1` should make the LIVE
   volume match the 13.4.8 snapshot. Combined with root-live-fs (R29) that gives
   us a WRITABLE, BOOTABLE 13.4.8 system - the planting capability that has
   blocked every cold-boot test.
*** DANGER, AND IT IS THE JOB-560 DANGER AGAIN: we do not know whether
    `snaputil -r` CONSUMES or DELETES the source snapshot. If it deletes
    com.apple.os.update-8AD664B2... and the revert does not complete, we have
    destroyed the only copy of the working 13.4.8 system - precisely the job 560
    failure ("Process 1 exec of /sbin/launchd failed, errno 2"). MITIGATION,
    MANDATORY BEFORE ANY REVERT: `snaputil -c pre-revert-<date> /mnt1` first,
    and confirm with -l that TWO snapshots exist. Also note -n (rename) exists,
    so a copy can be made by name. ***

R30.2 *** CORRECTION: boot-args IS one of the four settable setenv names. ***
------------------------------------------------------------------------------
R24.3 and R29.2 both said boot-args is "unreachable on this unit because console
setenv is gated to 4 names". That reasoning was WRONG: the four permitted names
we code-proved are **auto-boot, boot-args, debug-uarts, pwr-path** - boot-args
IS one of them. And job 591 B0 shows `boot-args` present in NVRAM with an EMPTY
value, alongside `debug-uarts 3` which we set ourselves and which demonstrably
works (we get UART output).
WHAT IS STILL UNKNOWN, and is the real question: whether a PRODUCTION iBoot and
kernel HONOUR boot-args content on a non-demoted unit, or parse and ignore it.
That is cheaply testable (set boot-args=-v, cold boot, look for extra verbosity
on UART) and worth one cycle, because if boot-args ARE honoured it unlocks:
  - `di-root-image` / `di-root-ram-file` (R27): a boot-arg route into the very
    same in-kernel UDIF parser that holds R27's Candidate A and B, with NO user
    client and NO entitlement. That would let us hit the kernel DMG bug without
    hdik, without a launchd job, and without planting anything on the System
    volume at all.
  - `-v`, `serial=3`, and the rest of the usual debugging surface.
DO NOT claim boot-args are honoured until tested. But stop recording them as
unreachable - that was my error, twice.

R30.3 OTHER JOB 591 FACTS
---------------------------
  nvram root-live-fs -> "Error getting variable - 'root-live-fs':
    (iokit/common) data was not found". CONFIRMED ABSENT, consistent with the
    pod booting the snapshot (R29).
  The /options node IS present and is class IODTNVRAM, visible under
    device-tree in IORegistry - confirming the exact path the kernel's
    IORegistryEntry::fromPath("/options", gIODTPlane) lookup uses.
  Full NVRAM baseline captured (B0) before we write anything. Variables present:
    backlight-nits, boot-breadcrumbs, obliteration, SystemAudioVolumeSaved,
    backlight-level, debug-uarts(3), bootdelay(0), recovery-breadcrumbs,
    boot-args(empty), auto-boot(true), oblit-begins.
  *** NOTE: `boot-command` and `upgrade-fallback-boot-command` are NOT in the
    dump. Either they were never committed or something cleared them. The debt
    recorded in R23.7/R29.2 to delete them appears already discharged - but
    verify before claiming it. ***
  boot-breadcrumbs ends with ... 400d0008 20023(3) <DONE> <COMMIT>, i.e. the
    last boot completed. Breadcrumb 4CCs seen: 7264736b rdsk, 72647472 rdtr,
    74727374 trst, 726b726e rkrn, 73657069 sepi - all the restore-path ones.
  SCRIPT BUGS, mine, for next time: (1) `df` is NOT on the ramdisk - 589's
    inventory shows /bin has no df (that was the SYSTEM volume's /bin). Use
    `diskutil info` or read the APFS superblock instead. (2) B7 referenced
    /mnt3 but sysvol-mount2.sh does not mount it (verchk.sh mounted and
    unmounted it). (3) The job's final `pod-get` of restore.log failed rc=1 and
    STOPPED the job - a pod-get of a file that may not exist must be the last
    step or guarded. It was last, so nothing was lost, but the job reported rc=1.

R30.4 THE PLAN THAT FOLLOWS FROM ALL OF THIS
----------------------------------------------
The focus returns to untethered. The sequence that is now unblocked:
  STEP 1 (one job, careful): `snaputil -c pre-revert-<date> /mnt1`, confirm two
    snapshots with -l, then `snaputil -r com.apple.os.update-8AD664B2... /mnt1`,
    then verify the live volume is now 13.4.8 (expect /usr/libexec to drop from
    227 to 132 and alwaysonexclavesd/betaenrollmentd/aidearlyboot/centaurid to
    disappear). Read-only verification afterwards.
  STEP 2: plant into the now-13.4.8 LIVE volume: a LaunchDaemon plist plus its
    payload. Two payloads are ready to go:
      - R27 Recipe A variant 1 (hdik + a blkx with blocksRunCount=2 and a
        0xCC-byte Data) - NON-DESTRUCTIVE, proves the missing bound without a
        panic. DO THIS FIRST.
      - R25.8 FRAME A (pppd notty + StandardInPath) - the ACSP layout oracle.
  STEP 3: `nvram root-live-fs=1` (baseline already captured), cold boot, read
    the log back from the ramdisk next cycle.
  IN PARALLEL, no pod needed: test whether boot-args are honoured (R30.2). If
    they are, `di-root-image` reaches the same UDIF bug with no planting at all,
    and STEP 1 and 2 become unnecessary for that test.

================================================================================
R31 — 14.0 DIFF RESULT: OUR TWO UDIF BUGS ARE **NOT** CVE-2020-9965/9966.
      THEY ARE STILL PRESENT AND UNPATCHED THROUGH tvOS 14.3. POSSIBLY
      UNREPORTED. 2026-11-26 20:30 PST
================================================================================
R31.0 WHAT WAS COMPARED (VERIFIED)
------------------------------------
  tvOS 14.0 / 18J386  AppleTV5,3 (Apple TV HD, j42dap) xnu-7195.1.3~2/
                      RELEASE_ARM64_T7000, Aug 26 2020, decompressed md5
                      8fcec3cfab6776acb3b73a3a8215d2c2
  tvOS 14.2 / 18K57   xnu-7195.40.143~11, Oct 11 2020
  tvOS 14.3 / 18K561  xnu-7195.63.1~3,  Nov 12 2020
All plain arm64 (cputype 0x0100000C, cpusubtype 0), all **RELEASE_ARM64_T7000**
- Apple TV HD is the SAME SoC as the HomePod, so this is the closest publicly
obtainable comparison. AudioAccessory1,1 has no IPSWs on ipsw.me, so audioOS 14
was not obtainable.
*** METHOD WORTH KEEPING: kernelcaches pulled from updates.cdn-apple.com by
HTTP RANGE REQUEST - tail 64 KB -> ZIP64 EOCD -> central directory -> the
kernelcache member (~13.5 MB deflated) -> raw inflate -> IM4P complzss ->
unlzss.py. NO full IPSW ever downloaded; peak extra disk ~45 MB; ~90 s each.
This matters a lot given we sit at 1.9 GB free. Tooling in /home/claude/kc14s/
(gkc.py is a parameterised KC(path) that loads ANY of the four caches and
replaces the hardcoded dmgaudit/kaudit kc.py). /home/claude/kc/kernel.macho md5
unchanged at 2593a5529ba361d393a8c1365166bc98. ***

R31.1 QUESTION A — blocksRunCount: NO CHECK ADDED IN 14.0. VERIFIED.
----------------------------------------------------------------------
14.0 UDIF kext __text 0xfffffff007ee0090-0xfffffff007ee8b08; merge_blkx at
0xfffffff007ee0f3c, size 0x324 (ours 0x330 - it got SMALLER).
  13.4.8 @0xdc8060              14.0 @0xedd068
  b940cac9 ldr w9,[x22,#0xc8]   b940cac9 ldr w9,[x22,#0xc8]
  5ac00929 rev w9,w9            5ac00929 rev w9,w9
  71000529 subs w9,w9,#1        71000529 subs w9,w9,#1
Byte-identical bound computation. Only the induction variable changed form
(13.4.8 counts up with cmp/b.lo; 14.0 counts down with subs/b.ne) = ONE FEWER
comparison, not one more.
  - getLength() NOT added: the complete multiset of OSData-range virtual-call
    offsets (ldr xN,[xM,#0xc0..#0xe8]) is IDENTICAL between versions
    (0xc0 x3, 0xc8 x2, 0xd0 x2, 0xd8 x1, 0xe0 x1). `ldr x8,[x8,#0xd8]`
    (getBytesNoCopy) still occurs EXACTLY ONCE kext-wide.
  - merge_blkx has exactly 4 bl in both, in 1:1 positional correspondence. No
    validation helper introduced.
  - Comparison census: 17 in 13.4.8, 16 in 14.0.

R31.2 QUESTION B — compressedLength: NO CHECK ADDED IN 14.0. VERIFIED.
-----------------------------------------------------------------------
14.0 KDIUDIFDiskImage::read at 0xfffffff007ee03c4, size 0x5ac (ours 0x5b0).
  13.4.8 @0xdc767c                  14.0 @0xedc680
  add x8,x20,x19   ; bufEnd         add x8,x27,x26   ; bufEnd
  ldp x2,x1,[sp,#0x58]              ldp x2,x1,[sp,#0x58]
  sub x19,x8,x2    ; NO BOUND       sub x4,x8,x2     ; NO BOUND
Identical but for the sub destination register. Same at the LZFSE site.
[sp,#0x58] touched in exactly 4 loads and 0 comparisons in BOTH versions.
Comparison census 19 in both, with IDENTICAL immediates in IDENTICAL order
(#8,#1,#1,#2,#0,#0,#0x3b,#5,#0x54 plus register compares). Call count identical
(40 bl + 7 blr).
  CORRECTION to R27: the backing-store read dispatches through vtable **+0x590**
  (ldr x8,[x8,#0x590]), same slot in both versions - not +0x588.

R31.3 FAMILY-WIDE: NOT ONE DiskImages KEXT GAINED VALIDATION. VERIFIED.
-------------------------------------------------------------------------
13.4.8 DiskImages kexts are 559.100.2; tvOS 14.0's are **595** - a real major
version bump, so this IS the right diff pair. Conditional-instruction counts
(cmp/cmn/tst/subs/ccmp/ands/tbz/tbnz/cbz/cbnz) over each kext's whole __text:
  DiskImages              548 -> 547   (-1)
  UDIFDiskImage           935 -> 935   ( 0)
  KernelBacked            178 -> 175   (-3)
  RAMBackingStore          34 ->  34   ( 0)
  FileBackingStore         80 ->  79   (-1)
  ReadWriteDiskImage        8 ->   8   ( 0)
The two DiskImages functions that did GROW have identical comparison counts and
identical compare immediates - the growth is register allocation and string/
vtable offsets. (com.apple.driver.AppleDiskImages2 v1.0.0d1 is NEW in 14.0 and
absent from 13.4.8 - a new subsystem, not a patch. WORTH A LOOK LATER: if Apple
"fixed" 9965/9966 by introducing a replacement subsystem rather than patching
the old one, that would reconcile everything - but the old code is still there
and still reachable, so it would not help Apple's users and does not change
ours.)
Also carried forward: the UDIF __text is 0x8a78 in ALL THREE of 14.0, 14.2
(595.40.1) and 14.3, with the merge_blkx bound computation and both read `sub`
sites byte-identical in every one. 14.0 vs 14.3 differ in only 8 of 8862
instruction slots, all nop<->add linker-stub padding.

R31.4 METHOD CROSS-VALIDATION: IT DETECTS REAL PATCHES. VERIFIED.
-------------------------------------------------------------------
host_request_notification, same three-term condition in 13.4.8, tvOS 14.0
(0xfffffff00772f8d4) and tvOS 14.2 (0xfffffff00775f8dc) - byte-identical
encodings. Expected: CVE-2020-27932 shipped in the 7195.6x branch and 14.2's
kernel is 7195.40.143 frozen Oct 11 2020, before that fix.
*** tvOS 14.3 (xnu-7195.63.1) @0xfffffff007763ee8 - PATCHED, EXACTLY AS R28
PREDICTED: ***
  b94002a8 ldr  w8,[x21]
  36f800e8 tbz  w8,#0x1f, ...
  b9409aa9 ldr  w9,[x21,#0x98]
  5280090a mov  w10,#0x48      <-- NEW: ip_tempowner(bit3) | ip_specialreply(bit6)
  0a0a0129 and  w9,w9,w10      <-- NEW: register form
  12002908 and  w8,w8,#0x7ff   <-- WIDENED from #0x3ff: bit 10 KOLABEL included
  2a090108 orr  w8,w8,w9
  34000268 cbz  w8,<success>
Both predicted elements present. NICE DETAIL TO REMEMBER: 0x48 is NOT an
encodable AArch64 logical immediate, which is why the compiler materialised it
into w10 - relevant if we ever pattern-scan for this shape.
=> The patch-diff method demonstrably FINDS added input validation when it is
   there. It reports NONE in the two DiskImages candidates. The method is not
   at fault.

R31.5 THE DECISIVE EXTERNAL CROSS-CHECK
-----------------------------------------
Apple's own tvOS 14 advisory (local copy /home/claude/ib5/adv-tvos14.html),
"Released September 16, 2020", build **18J386** - the exact kernelcache
disassembled above:
  Disk Images - Available for: Apple TV 4K and Apple TV HD - Impact: An
  application may be able to execute arbitrary code with kernel privileges -
  Description: An out-of-bounds read was addressed with improved input
  validation. CVE-2020-9965: Proteas / CVE-2020-9966: Proteas
Identical entry in adv-ios14.html for iPhone 6s and later.
=> Apple places 9965/9966 in tvOS 14.0 = 18J386, and in THAT build the
   DiskImages family gained ZERO comparisons and both candidate functions are
   byte-equivalent to 13.4.8. Both facts cannot describe the same bugs.

R31.6 CONCLUSION, AND WHAT IT CHANGES
---------------------------------------
**Our two candidates are NOT CVE-2020-9965/9966. Confidence ~90%.**
RESIDUAL ~10%: the comparison was tvOS 14.0 (xnu-7195.1.3, Aug 26 2020), not
iOS 14.0 (18A373, a different tag built ~Sept 2020). If the fix landed only on
the iOS branch and the tvOS advisory was generated from a shared CVE list, tvOS
14.0 could lack it. Substantially weakened by 14.2 and 14.3 carrying identical
UDIF code while demonstrably receiving other security fixes, but not excluded.
ONE REMAINING TEST TO CLOSE IT: the iOS 14.0 18A373 kernelcache for iPhone8,1,
URL recorded by the agent, ~2 minutes with the range-request pipeline.

*** WHAT THIS CHANGES FOR US: NOTHING OPERATIONALLY, AND IT MAY BE BETTER. ***
The bugs stand on their own code analysis (exhaustive compare enumeration in
both versions). They are still present on 13.4.8, still reachable from
trust-cached hdik, still the best code-exec lead in the project. The CVE label
was never the point. What we LOSE is external corroboration that Apple ever
thought this code was buggy. What we GAIN is the real possibility that these are
**unreported** rather than merely unpatched-on-13.4.8.

*** TWO THINGS TO SETTLE BEFORE SPENDING HARDWARE TIME - BOTH MY OWN DOUBTS ***
 1. DOES merge_blkx CLAMP compressedOffset / compressedLength WHEN IT COPIES
    ENTRIES INTO THE MERGED TABLE? The exhaustive compare enumeration that
    proved Candidate B was performed **inside KDIUDIFDiskImage::read only**. If
    merge_blkx validates those two fields while building the table, Candidate B
    does not exist. R27 listed merge_blkx's guards as entryType (only on the
    clipping path) and sector geometry, and did NOT mention compressedOffset or
    compressedLength - but absence from a report is not proof of absence in the
    code. **VERIFY THIS BEFORE THE HARDWARE TEST.** A six-year-old unreported
    heap-underflow write with attacker-controlled length AND content is a strong
    claim and deserves the extra pass.
 2. IS EITHER BUG STILL LIVE IN A CURRENT APPLE OS? The range-request pipeline
    makes this cheap. This decides the DISCLOSURE question below.

*** DISCLOSURE NOTE - NIC'S CALL, BUT HE NEEDS THE FACTS ***
Nic is publishing scrubbed notes to github.com/UnbendableStraw/homepod-untethered.
The R25.3 acsp.c bugs are different: Apple fixed those in ppp-1027.121.1 (June
2026), so writing up an already-patched bug is ordinary practice. These two UDIF
bugs may be a different situation: if they are unreported AND still present in a
shipping Apple OS, then publishing a byte-level recipe is publishing a live
vulnerability, and reporting to Apple first (product-security@apple.com) is the
right order. If they are fixed by now, publication is fine. **We do not yet know
which, and the check is cheap - do it before anything about these goes public.**
Reachability caveat that may lower the stakes: the in-kernel path needs root
plus com.apple.private.diskimages.kext.user-client-access (which hdik holds),
and macOS uses a userspace diskimages-helper rather than the in-kernel parser -
so unprivileged reachability on a current OS is unestablished either way.

================================================================================
R32 — PROCESS RULE I BROKE, AND JOB 592's RESULT SO FAR
================================================================================
*** STANDING RULE, FROM NIC AT JOB 580, WHICH I FAILED TO CARRY FORWARD:
    "Just let me know if you expect me to do cold boot after any of these jobs."
    EVERY job must state, AT QUEUE TIME, whether a cold boot is needed
    afterwards and what to watch. I queued 592 without saying so; Nic put the
    pod back into DFU and the cold boot was lost. No data lost, just a cycle.
    => From now on, every job description ends with one of:
       "NO COLD BOOT NEEDED" or
       "COLD BOOT REQUIRED AFTER: <what to do> / <what to watch>". ***

JOB 592 (the NVRAM write) SUCCEEDED:
  before: boot-args   (present, empty)
  write:  nvram boot-args=-v   -> rc=0, sync attempted
  after:  boot-args   -v       (read back confirmed)
  Nothing else in NVRAM changed: backlight-nits 0x00cd0000, obliteration,
  SystemAudioVolumeSaved true, backlight-level 3286109, debug-uarts 3,
  bootdelay 0, recovery-breadcrumbs, auto-boot true, oblit-begins - all as in
  the 591 baseline.
  The value PERSISTS in NVRAM, so the test does not need re-arming - only the
  cold boot.
PENDING: cold boot right-side-up with a fresh screenlog. The UART log IS the
  result.
    boot-args HONOURED  -> visibly more kernel output than the clean 13.4.8
      baseline: driver matching, IOKit registration chatter before audioOS.
    boot-args IGNORED   -> log indistinguishable from the baseline.
REVERT AT ANY TIME from a ramdisk session: `nvram -d boot-args`

IF HONOURED, THE NEXT TWO TRIES IN ORDER (these would shortcut the whole
project - unsigned code with no DMG bug, no kernel exploit, no ROP, no planting):
  1. amfi_get_out_of_my_way=1     <- gentler, try first
  2. cs_enforcement_disable=1     <- WARNING: per R24.3, AMFI's init parses this
     at 0xfffffff007c9a4f4 (PE_parse_boot_argn), logs "%s: cs_enforcement
     disabled by boot-arg", then calls 0xfffffff007c1ede8 with x0=0 and PANICS
     at 0xfffffff007c9a780 if that returns 0 - i.e. it is gated on a
     dev/internal check. Expect a panic on a production unit. Recoverable by
     clearing the variable from the ramdisk, and the panic itself localises the
     gate, so it is still worth doing - just second.
  Also worth trying if honoured: amfi=0xff.
IF IGNORED, fall back to the R29/R30.4 route: snaputil -c a safety snapshot,
  snaputil -r to make the LIVE volume 13.4.8, plant the non-destructive hdik
  test (R27 Recipe A variant 1), nvram root-live-fs=1, cold boot.

================================================================================
R33 — I TRIED TO KILL THE UDIF WRITE PRIMITIVE AND COULD NOT. IT SURVIVES,
      MACHINE-CHECKED. PLUS TWO CORRECTIONS TO MY OWN NOTES AND A BONUS BUG.
      2026-11-26 20:45 PST
================================================================================
An agent was briefed specifically to FALSIFY the finding (my objection: the
exhaustive compare enumeration had only covered KDIUDIFDiskImage::read, not
merge_blkx, which builds the merged chunk table). Verdict: **the bug stands.**

R33.1 merge_blkx DOES NOT CLAMP EITHER FIELD. VERIFIED, MACHINE-CHECKED.
-------------------------------------------------------------------------
merge_blkx = 0xfffffff007dcbf38, size 0x330, fileoff 0xdc7f38. Capstone decoded
204/204 instructions - the whole function, no gaps.
Signature (from its single call site 0xfffffff007dcbe80 in the chunk-table
builder): merge_blkx(x0=KDIUDIFDiskImage*, x1=resourceObj, x2=blkx**, x3=nBlkx).

EVERY memory access using the source-entry base x19 - exactly TWO, both loads,
no compares:
  0xdcc080  ldp q0, q1, [x19]     ; +0x00..0x1f (compressedOffset rides at +0x18)
  0xdcc084  ldr x8, [x19, #0x20]  ; +0x20 = compressedLength
compressedLength path, VERBATIM copy, byte-swap only:
  0xdcc084  ldr x8,[x19,#0x20]    ; raw BE
  0xdcc088  str x8,[sp,#0x50]
  0xdcc094  bl  swap_BLKXChunkEntry
  0xdcc124  ldr x8,[sp,#0x50]
  0xdcc128  str x8,[x20,#0x20]    ; <-- THE ONLY WRITER of merged +0x20
  0xdcc158  add x24,x8,x24        ; only other use: running sum for gap entries
x8 is not compared anywhere between 0xdcc124 and 0xdcc128.
compressedOffset path - copied, then ONE UNGUARDED 64-bit add, never compared:
  0xdcc144  ldr x9,[x22,#0x18]    ; BLKXTable.dataOffset
  0xdcc148  rev x9,x9
  0xdcc14c  ldr x10,[x20,#0x18]
  0xdcc150  add x9,x10,x9         ; no overflow check
  0xdcc154  str x9,[x20,#0x18]
ALL 29 flag-setting instructions in merge_blkx were enumerated and classified
(pass counter x6, kalloc results x3, resource/loop counters x5, sector gap x2,
abs sector vs cursor x2, entryType dispatch x7, buffersNeeded max x2,
decompressBufferRequested x1, free paths x2). **ZERO of the 29 touch
compressedOffset or compressedLength.**
swap_BLKXChunkEntry (0xfffffff007d9b364, 0x40 bytes, 16 instructions) is pure
rev+str on w@0,w@4,x@8,x@0x10,x@0x18,x@0x20 then ret. NO compare, branch or
csel anywhere - it cannot be hiding the check.

*** TRAP THAT LOOKS LIKE A CLAMP AND IS NOT: `ldr w8,[x22,#0x20]` at 0xdcc014
is +0x20 of the BLKXTable HEADER (buffersNeeded), a DIFFERENT struct from the
40-byte BLKXChunkEntry whose +0x20 is compressedLength. Base registers differ:
x22 = table, x19 = entry. Confusing these would "find" a clamp that does not
exist. ***

R33.2 THE [sp,#0x58] PROVENANCE CHAIN, AND THE FIELD DIRECTION IS CORRECT
--------------------------------------------------------------------------
[sp,#0x58] is an OUT-PARAMETER slot passed as x7 to the findChunk virtual call:
  0xdcb4b8 ldr x8,[x8,#0x5c8]   ; vtable +0x5c8 = findChunk
  0xdcb4bc sub x2,x29,#0x68     ; chunk index
  0xdcb4c0 sub x3,x29,#0x64     ; entryType
  0xdcb4c4 add x4,sp,#0x70      ; chunk sectorNumber
  0xdcb4c8 add x5,sp,#0x68      ; chunk sectorCount (geometry-derived)
  0xdcb4cc add x6,sp,#0x60      ; compressedOffset
  0xdcb4d0 add x7,sp,#0x58      ; compressedLength
findChunk's tail writes them:
  0xdcc2e4 ldr x9,[x8,#0x18] ; 0xdcc2e8 str x9,[x6]   ; -> sp+0x60
  0xdcc2ec ldr x8,[x8,#0x20] ; 0xdcc2f0 str x8,[x7]   ; -> sp+0x58
=> `ldp x2,x1,[sp,#0x58]` gives x2 = compressedLength, x1 = compressedOffset.
   AS PREVIOUSLY REPORTED - the direction is NOT inverted.
INDEPENDENT CONFIRMATION from the raw/uncompressed path, which nails it: the
UDIF_RAW branch uses ONLY sp+0x60 and uses it AS A FILE OFFSET -
  0xdcb54c ldr x8,[sp,#0x60] ; 0xdcb550 add x1,x8,x27,lsl #9
A length would never be shifted-added like that, and sp+0x58 is never touched in
the raw path at all. (The raw path is therefore SAFE: dst = the caller's bounded
buffer.)
NO INTERVENING WRITER: across all 364 instructions of read, the only accesses to
sp+0x58 / sp+0x60 are FIVE LOADS AND ZERO STORES (0xdcb54c, 0xdcb680, 0xdcb6ac,
0xdcb768, 0xdcb7a0). findChunk is the sole writer.
NO STACK ALIASING: &actualLength is `sub x3,x29,#0x58` and x29 = sp+0xe0, i.e.
sp+0x88 - a DIFFERENT slot from sp+0x58. (#0x58 appears as both an sp+ and an
x29- displacement in the same function. Easy trap.)
findChunk (0xfffffff007dcc268, 0x90, 36 instructions, fully decoded) is a pure
binary search; its only compares are sector comparisons. NOT CLAMPED.
  NOTE: the sectorCount findChunk returns is NOT the entry's own field - it is
  derived from geometry (0xdcc2d4: next entry's sectorNumber minus this one's).
  THAT is what the monotonic/contiguous enforcement buys: it bounds the
  DECOMPRESSED size only, and has no relationship to compressedLength.
Chunk-table builder 0xfffffff007dcbd68 (0x1d0, fully read) never dereferences a
BLKXChunkEntry at all, so it cannot validate +0x18/+0x20 either.
=> TRUST BOUNDARY: raw DMG bytes -> swap_BLKXChunkEntry -> merged table ->
   findChunk -> sub -> write. FOUR HOPS, ZERO CHECKS on these two fields.

R33.3 THE PRIMITIVE, EXACTLY
------------------------------
  0xdcb5fc lsl x20,x9,#9        ; decompressedSize = sectorCount * 512
  0xdcb610 ldr w8,[x8,#0x20]    ; decompressBufferRequested
  0xdcb614 lsl w8,w8,#9         ; allocSize = dbr * 512
  0xdcb618 cmp x20,x8 ; b.ls    ; THE ONLY SIZE CHECK: DECOMPRESSED <= allocSize
  0xdcb660 bl  kalloc           ; buf = kalloc(allocSize)
  0xdcb67c add x8,x20,x19       ; bufEnd = buf + allocSize
  0xdcb680 ldp x2,x1,[sp,#0x58] ; x2 = compressedLength, x1 = compressedOffset
  0xdcb684 sub x19,x8,x2        ; src = bufEnd - compressedLength
  0xdcb698 mov x4,x19           ; DESTINATION = that
  0xdcb6a0 blr x8               ; read(this, off=x1, len=x2, &actual=x3, dst=x4, flags)
**The register that becomes the LENGTH argument is x2 - the same register,
loaded by the same ldp, that is subtracted from bufEnd to form the DESTINATION.
One load, one value, two uses.** Neither x1 nor x2 is modified between 0xdcb680
and the blr.
Because dst = bufEnd - len and the length is len, the write region is always
exactly [bufEnd - len, bufEnd). There is NEVER a high-side overflow - it is a
pure LOW-SIDE UNDERFLOW of (len - allocSize) bytes, distance fully
attacker-chosen, contents fully attacker-chosen (raw file bytes at
compressedOffset).
WORKED EXAMPLE, confirmed: dbr = 1 -> allocSize = 0x200 = 512.
compressedLength = 0x1000 -> dst = buf + 512 - 4096 = buf - 3584, write span
[buf-3584, buf+512) = 3584 bytes below a kalloc.512 element. Needs a DMG of only
~4 KB. Requires decompressedSize = sectorCount*512 <= 512, i.e. a 1-sector
chunk - satisfiable.
The corruption happens BEFORE any error is checked (cbnz w0 at 0xdcb6a8 is after
the blr). The inflate that follows is itself bounded and irrelevant.
CODEC CHOICE: zlib (0x80000005) gives the WRITE only (the wrapper's overlap
guard at 0xfffffff007dcdd5c errors out once src < dst, returning 0x3e9, so
inflate never runs on the OOB pointer). LZFSE (0x80000007) has NO overlap guard
=> write AND an OOB read by the decoder. Use zlib to isolate the write.
BACKING-STORE SIDE re-verified: KDIFileBackingStore::read = 0xfffffff00856178c.
Guards: `tbnz x1,#0x3f` at 0xfffffff0085617b4 rejects NEGATIVE offsets (a guard
we did not have before), then from 0xfffffff0085617c4 `ldr x8,[x0,#0xb0]` (file
size), add, cmp, ccmp, b.gt. Constrains the FILE, not the destination buffer.
The 32-bit truncations at 0x5617e4/0x5617fc feed ONLY a kernel_debug trace; the
real transfer loop (0x561874-0x5618e8: uio_reset / uio_addiov / VNOP_READ) uses
the FULL 64-bit length in x21, so compressedLength is NOT truncated.

R33.4 *** TWO CORRECTIONS TO MY OWN EARLIER NOTES ***
-------------------------------------------------------
(a) R31's claim that "the UDIF code is byte-identical across 13.4.8 / 14.0 /
    14.2 / 14.3" is **FALSE**. Only findChunk is byte-identical (fileoffs
    0xdc8268, 0xedd260, 0xf1dc20, 0xf27f20). merge_blkx and read DIFFER in
    register allocation and frame layout. 14.0's read site is
    0xfffffff007ee0680 `add x8,x27,x26 / ldp x2,x1,[sp,#0x58] / sub x4,x8,x2`
    using x27/x26 where 13.4.8 uses x20/x19; 14.0's merge_blkx writes merged
    +0x20 at 0xfffffff007ee1124 `str x8,[x27,#0x20]`.
    **THE FINDING IS STILL CONFIRMED SEMANTICALLY IN ALL FOUR CACHES** (14.0's
    merge_blkx has the identical ldp/ldr/str/stp staging sequence at
    0xfffffff007ee1084 and no clamp). But DO NOT transfer offsets between
    caches, and do not rely on a byte-for-byte diff for these two functions.
(b) R31's "correction" that the vtable slot is +0x590 and not +0x588 was itself
    WRONG - both numbers are right, for DIFFERENT classes:
      KDIUDIFDiskImage vtable base 0xfffffff00752d1f8:
        +0x588 = KDIUDIFDiskImage::read (0xfffffff007dcb3bc)
        +0x5c0 = chunk-table builder   (0xfffffff007dcbd68)
        +0x5c8 = findChunk             (0xfffffff007dcc268)
      KDIFileBackingStore vtable base 0xfffffff00760d1b8:
        +0x590 = KDIFileBackingStore::read (0xfffffff00856178c)
    The +0x590 in read's dispatch is the BACKING STORE's slot. Record both.
(c) Minor: the decompressBufferRequested <= 0x400000 test at 0xdcc194 is a
    **REJECT** (b.ls ok, else err 0x6b), not a clamp, and it applies to the MAX
    across all blkx tables (csel at 0xdcc024), not per-table. So we cannot make
    a value above 0x400000 stick, but we can freely choose anything at or below
    it, including 1.

R33.5 BONUS: A THIRD UNBOUNDED READ, FOUND IN PASSING (INFERRED, not chased)
-----------------------------------------------------------------------------
  0xdcc068  subs w9, w9, #1 ; b.eq
If BLKXTable.numberBlocks == 0, w9 becomes 0xffffffff and the inner loop bound
x27 becomes 0xffffffff - roughly four billion iterations walking 40 bytes at a
time over memory past the resource. No numberBlocks upper bound exists in either
merge_blkx or the builder at 0xdcbd68. Cheap, deterministic DoS at minimum;
possibly an info-leak vector via the synthesized gap entries.
ALSO NOTED (correctness, not security): the clipping path at 0xdcc10c-0xdcc114
adjusts sectorNumber/sectorCount but leaves compressedOffset/Length describing
the UNCLIPPED range, and 0xdcc140 then adds the table base sector to a value
0xdcc114 already stored in absolute form. Looks like double-counting.

R33.6 WHERE THIS LEAVES US
----------------------------
We now have, verified at instruction level and having survived a dedicated
attempt to falsify it: **a kernel heap-underflow write with attacker-controlled
distance AND contents, reachable by handing a file to a trust-cached
Apple-signed binary, needing no code execution of our own at any point.** That
is strictly better than everything else in this project: the pppd bugs give a
single fixed 0x00 byte, and CVE-2020-27932 needs native code first and runs into
zone_require.
AND it is present in tvOS 14.0, 14.2 and 14.3, and is NOT CVE-2020-9965/9966.
*** DISCLOSURE, NOW MORE PRESSING: this is looking like an unreported live bug,
not an old patched one. Before ANY of R27/R33's byte-level recipes go into the
public repo, check a CURRENT Apple kernelcache with the range-request pipeline
(/home/claude/kc14s/zipcd.py + getmem.py, ~90 s). If still present, Apple's
product-security@apple.com comes before publication. If fixed, publication is
ordinary practice. Nic's call, but he should make it with this in hand. ***
NEXT HARDWARE STEP IS UNCHANGED AND IS NON-DESTRUCTIVE: R27 Recipe A variant 1
(blocksRunCount = 2 with a 0xCC-byte Data) to prove the missing bound without a
panic, then R33.3's gentle variant (compressedLength = 0x1000, ~8 KB file,
zlib) to demonstrate the write. Both still need the planting route that job 593
is deciding.

================================================================================
R34 — THE FIRST HARDWARE ATTEMPT AT THE UDIF BUG. MECHANISM DID NOT FIRE.
      PLUS: I PANICKED THE POD WITH MY OWN ioreg. 2026-11-26 21:07 PST
================================================================================
R34.0 *** ioreg IS BANNED ON THE RAMDISK, IN EVERY FORM ***
-------------------------------------------------------------
Job 596's verdict.sh ran `ioreg -c IOMedia`. It PANICKED THE RESTORE KERNEL and
killed the ssh session (job ended rc=255, mode=none).
  panic(cpu 0 caller 0xfffffff021c4161c): Kernel data abort.
    at pc 0xfffffff021b40544, lr 0xfffffff021b40528, esr 0x96000005, far 0x0
  Panicked task: pid 47: ioreg
  OS release type: Restore      OS version: 21L569
  Kernel version: Darwin 23.5.0 ... xnu-10063.123.2~1/RELEASE_ARM64_T7000
  Boot args: rd=md0 debug=0x2014e -v wdt=-1 nand-enable-reformat=1 -restore serial=3
Preceded by a long run of `System Policy: ioreg(47) deny(1)
iokit-open-user-client <X>` / `IOUC <X> failed MACF in process pid 47, ioreg`
for RootDomainUserClient, ASPUserClient, AppleAPFSUserClient,
AppleEffaceableStorageUserClient, AppleSmartIOUserClient,
IOAESAcceleratorUserClient, IOHIDLibUserClient, AppleAVEUserClient,
IODARTClient, IODARTMapperClient, IOSurfaceAcceleratorClient.
*** THIS PANIC IS OURS, NOT A FINDING. It is the 2024 restore kernel dying on
an unentitled ioreg walk. It is NOT the UDIF bug. Do not ever present it as
one. ***
R20 recorded "bare ioreg -l kills dropbear" and I wrongly assumed `-c <class>`
was safely bounded. It is not. NEW RULE: **no ioreg on the ramdisk at all.**
Use dd on the block devices, grep -a on binaries, and sysctl instead.

R34.1 THE ACTUAL RESULT OF THE hdik TEST: MECHANISM DID NOT FIRE
-----------------------------------------------------------------
Job 595 planted everything correctly (see R34.2). After the cold boot, job 596
found:
  nvram nicsfix-mark  -> "data was not found"      <-- OUR DAEMON NEVER RAN
  /dev/disk4 (Apple PanicLog Media) -> dd returned NOTHING,
      "disk4: invalid argument"
  keyword grep over the panic region: panic 0, Backtrace 0, UDIF 0, KDI 0,
      HDIX 0, DiskImages 0, kalloc 0, zone_require 0
  Both the 595 and 596 ramdisk boots logged
      "[ANS:client1] Util_Host: attempting to read element=PANICLOG not yet
       written, returning ERR_AB..."
=> audioOS did NOT panic, and our LaunchDaemon did not run. The bug was never
   reached. This says NOTHING about whether the bug is real - R33 settled that
   at instruction level. It says our DELIVERY MECHANISM is not working yet.

R34.2 WHAT DID WORK, VERIFIED (job 595)
-----------------------------------------
  snaputil -r rc=0, and the APFS layer confirmed it on UART:
    handle_revert_to_snapshot:8007: disk1s1 On next mount, volume will revert
      to snapshot 'com.apple.os.update-8AD664B2...' w/snap xid 27
    revert_to_snapshot:1605: Reverting to snapshot w/xid 27, old sblock oid 3842100
    revert_extents_iterator:1369: free'ing allocated extents for snap_xid 890
    revert_to_snapshot:1705: DONE reverting to snapshot w/xid 27
    fs_insert_snapshot_metadata:249: snap_name='nicsfix-134-good' snap_xid 896
  *** snap_xid 890 was nicsfix-pre-revert-ThuJan1000044U (confirmed from 594's
  UART: fs_insert_snapshot_metadata snap_name='nicsfix-pre-revert-...'
  snap_xid 890). SO `snaputil -r` CONSUMED/FREED THE NEWER SNAPSHOT. Creating
  nicsfix-134-good AFTER the revert was what actually gave us insurance; the
  "safety" snapshot taken BEFORE would have been gone exactly when needed. ***
  live /usr/libexec went 69 -> 132, alwaysonexclavesd absent, hdik/nvram/
  launchd/LaunchDaemons all present, gate PASSED.
  nf.dmg landed at /mnt1/usr/standalone/nf.dmg, 1802 bytes confirmed on the pod.
  Both plists written (427 B and 462 B) and read back correct.
  root-live-fs=1 written and read back.
  The cold boot produced a UART log IDENTICAL in shape to the clean baseline:
  iBoot-5540.140.12, "Delaying boot for 0 seconds", handoff, then silence.

R34.3 ANOMALY, RECORDED NOT CONCLUDED
---------------------------------------
At 595 step 2, BEFORE the revert, the live volume had **69** /usr/libexec
entries and alwaysonexclavesd was ALREADY absent. Job 590 measured **227** with
exclaves present. So the live volume shrank a lot between 590 and 595, across
three normal cold boots. Nic's instruction stands: do not conclude anything
about the update behaviour yet - this may well be an artifact of why the pod
cannot update itself. Logged as an observation only.

R34.4 LEADING HYPOTHESIS FOR THE SILENCE: THE COMPILED LAUNCHD CACHE
----------------------------------------------------------------------
On iOS 13, launchd does not read /System/Library/LaunchDaemons/*.plist when a
COMPILED CACHE exists - it loads the cache and ignores drop-ins. The restore
ramdisk's own launchd says as much on UART: "No MRM cache found" / "Unable to
load cache" / "Unable to open /System/Library/xpc/launchd.plist".
Job 588 checked /mnt1/System/Library/Caches/com.apple.xpc.launchd/ and got
"No such file or directory" - BUT that was the STAGED MODERN volume. On the
reverted 13.4.8 volume the cache very likely exists, which would make our two
plists dead weight regardless of root-live-fs.
TWO STACKED UNKNOWNS, now being separated by job 597:
  U1 does 13.4.8 launchd read drop-ins at all, or only the cache?
  U2 did root-live-fs=1 actually boot the LIVE volume?

R34.5 JOB 597 QUEUED (COLD BOOT REQUIRED AFTER)
-------------------------------------------------
  1 confirm our plants survived; snapshot list; libexec count
  2 look for the compiled cache at
      System/Library/Caches/com.apple.xpc.launchd[/launchd.plist]
      private/var/db/com.apple.xpc.launchd
    and count drop-in LaunchDaemons
  3 grep -a /mnt1/sbin/launchd for its own path literals
    (xpc.launchd, LaunchDaemons, launchd.plist, MRM, mrm.plist, Caches) and
    extract /System/Library/Caches/... and /private/var/db/... strings with
    grep -ao  -- no strings(1) on this ramdisk
  4 ACTION: if the cache dir exists, `mv` it to .nicsfix-off (reversible) so
    launchd must read drop-ins
  5 write /mnt1/usr/standalone/nf-live.txt as a LIVE-volume marker the snapshot
    cannot contain, so the two trees become distinguishable
  6 nvram state
  NO ioreg anywhere.

R34.6 IF THE CACHE IS NOT THE ANSWER — OTHER WAYS IN, RANKED
--------------------------------------------------------------
 (a) Inject into the launchd cache itself rather than dropping a plist beside it.
 (b) Replace the ProgramArguments of an EXISTING trust-cached daemon's entry
     (edit its plist in place) rather than adding a new one - no new Label for
     launchd to reject, and it inherits a daemon that is already started.
 (c) Hijack a path an existing daemon already execs or reads, so no plist change
     is needed at all.
 (d) Test root-live-fs independently and destructively: rename /mnt1/sbin/launchd
     on the LIVE volume. If root-live-fs works the pod cannot boot ("Process 1
     exec of /sbin/launchd failed, errno 2"); if it boots fine, root-live-fs is
     being ignored and the whole planting route is dead. Reversible by renaming
     back from the ramdisk. Decisive, and cheap.
 (e) Check whether audioOS can even WRITE nvram - our marker depends on it. If
     /usr/sbin/nvram needs an entitlement at runtime the marker would be silent
     even on a successful run. Pick a second, independent signal.

================================================================================
R35 — DISCLOSURE QUESTION SETTLED. BOTH UDIF DEFECTS ARE **FIXED** IN CURRENT
      APPLE OS. THEY WERE LIVE FOR FIVE AND A HALF YEARS.
      2026-11-26 21:15 PST
================================================================================
R35.0 THE TIMELINE (every row from a real cache, fetched, analysed, deleted)
-----------------------------------------------------------------------------
 audioOS   build    xnu                built        Defect1   Defect2   'mish'
 13.4.8    17M61    6153.143.1         2020-06-26   present   present   absent
 tvOS 14.0 18J386   7195.1.3           2020-08-26   present   present   absent
 14.4      18K802   7195.80.35         2021-01-05   present   present*  absent
 17.0      21J354   10002.3.3          2023-08-15   present   present   absent
 18.0      22J357   11215.3.3          2024-08-06   present   present   absent
 26.0      23J353   12377.3.3          2025-08-05   present   present   absent
 26.3      23K620   12377.83.1         2026-01-22   present   present   absent
 26.4      23L243   12377.103.8        2026-03-05   present   present   absent
 26.5      23L471   12377.123.3        2026-04-23   present   present   absent
 **26.6**  23L773   12377.163.4        2026-07-11   FIXED     FIXED     absent
 **27.2.1**24K157   13432.43.4         2026-10-07   FIXED     FIXED     present
 (*14.4 Defect 2 is INFERRED from the detector plus confirmed presence in
  17.0/18.0/26.x; Defect 1 there is VERIFIED and quoted.)
 LAST BUILD CONFIRMED VULNERABLE: audioOS 26.5 / 23L471 / xnu-12377.123.3,
   released 2026-05-11.  NEWEST BUILD CHECKED: 27.2.1 / 24K157, 2026-11-13.
 => THE CODE WAS UNTOUCHED FROM 13.4.8 THROUGH 26.5. FIVE AND A HALF YEARS,
    xnu-6153 -> xnu-12377.123.3. Fixed roughly FOUR MONTHS AGO.
 This independently reinforces R31: these were never CVE-2020-9965/9966, since
 that code was not touched in 14.0 or at any point until 26.6.

R35.1 WHAT THE FIX LOOKS LIKE (VERIFIED, 27.2.1, kext __text 0xfffffff00912de80
      size 0xb684 - the kext GREW ~32% from 13.4.8's 0x89f8)
--------------------------------------------------------------------------------
Defect 1, merge_blkx now at 0xfffffff00912f05c, gains a VALIDATION PRE-PASS over
every blkx resource, and the merge loop re-validates independently:
  0xfffffff00912f0cc  ldr   x8,[x16,#0xd8]!   ; getBytesNoCopy  (PAC dispatch)
  0xfffffff00912f0f4  ldr   x8,[x16,#0xa0]!   ; <-- SECOND virtual call = LENGTH
  0xfffffff00912f100  cmp   w0,#0xf4          ; length >= header size
  0xfffffff00912f10c  cbz   w8,fail           ; <-- ZERO-COUNT CHECK
  0xfffffff00912f11c  umull x10,w8,w21        ; (count-1) * 0x28
  0xfffffff00912f120  add   x10,x10,#0xf4
  0xfffffff00912f124  cmp   x10,x9            ; vs ACTUAL LENGTH
  0xfffffff00912f128  b.hi  fail              ; <-- THE MISSING BOUND
  0xfffffff00912f130  cmp   w9,w24            ; w24 = 0x6873696d = 'mish'
  0xfffffff00912f134  b.ne  fail              ; <-- SIGNATURE CHECK (27.x only)
  0xfffffff00912f154  cmn   w8,#1             ; last entry must be the terminator
Defect 2, KDIUDIFDiskImage::read now 0xfffffff00912e328..0xfffffff00912e900. The
`bufEnd - compressedLength` subtraction IS STILL THERE, but both compressed
paths now gate it with a fused compare:
  0xfffffff00912e4dc  lsl   w27,w8,#9         ; allocSize
  0xfffffff00912e4e8  ldr   x8,[sp,#0x48]     ; compressedLength
  0xfffffff00912e4ec  cmp   x21,x27           ; decompressed vs allocSize
  0xfffffff00912e4f0  ccmp  x8,x27,#2,ls      ; AND compressedLength vs allocSize
  0xfffffff00912e4f4  b.hi  fail              ; <-- THE MISSING BOUND
  (path B identical in shape at 0xfffffff00912e704-70c)
Extra 27.x-only hardening in merge_blkx: a 4 MiB cap on per-chunk decompressed
size (0xfffffff00912f380 lsl x10,x8,#9 / cmp x10,#0x400,lsl#12 / b.gt) and a cap
on aggregate decompressBufferRequested (0xfffffff00912f444 cmp w19,#0x400,lsl#12).
The 'mish' + version + terminator validation and the caps arrived in the 27
cycle, i.e. LATER than the bounds fixes - that pattern looks like an internal
audit pass, not a response to a single report.
ALSO FIXED by the same `cbz w8`: the numberBlocks==0 loop-bound underflow from
R33.5. It was still present verbatim in audioOS 14.4 at 0xfffffff008145128.

R35.2 THE KEXT STILL EXISTS - IT WAS NOT REPLACED
---------------------------------------------------
com.apple.driver.DiskImages.UDIFDiskImage is present in 27.2.1 as an
LC_FILESET_ENTRY at va 0xfffffff0076d63e0, with all five classes
(KDIUDIFDiskImage, KDIUDIFEncoding, KDIUDIFCacheBuffer, KDIUDIFCacheObject,
KDISecondaryEncoding). com.apple.driver.AppleDiskImages2 also exists but has
NOT replaced it. So the R31 speculation that Apple might have sidestepped the
old subsystem is wrong - they patched it, just five and a half years later.

R35.3 *** RECOMMENDATION: HISTORICAL, NOT LIVE. PUBLICATION IS DEFENSIBLE. ***
-------------------------------------------------------------------------------
No pre-publication report to product-security@apple.com is required on the
merits: both defects are patched in the current shipping OS and have been since
the 26.6 cycle (July 2026) - four months and two major releases, across six
subsequent public releases.
THREE THINGS FOR NIC TO WEIGH, his call:
 1. 26.x IS STILL A SUPPORTED BRANCH. Apple shipped 26.7.3 on 2026-11-09. The
    fix is VERIFIED in 26.6 but 26.7.x was NOT checked; a regression would be
    very surprising, but it is unverified. HomePods update slowly and a
    non-trivial installed base is plausibly still on <= 26.5. Publishing a
    CODE ANALYSIS is clearly fine; publishing a WORKING EXPLOIT lands on real
    unpatched devices. Ordinary disclosure hygiene, not a notify-first duty.
 2. NO CVE IS ATTRIBUTABLE. The tvOS 26.6 advisory has NO "Disk Images"
    component at all - 20 generic "Kernel" entries. Shape-compatible candidates
    exist (CVE-2026-43739 "out-of-bounds write ... improved bounds checking",
    CVE-2026-43817 "out-of-bounds read ... improved bounds checking") but their
    impact text is "An app may be able to..." and nothing ties either to this
    kext. TREAT THE CVE AS UNKNOWN. These may have been fixed silently.
 3. A courtesy informational note to Apple that we are publishing on something
    they appear to have fixed silently in 26.6 is an option, not an obligation.
NO BOUNTY WINDOW REMAINS - that closed around July 2026. The research value and
the publication are unaffected.

R35.4 WHAT IT MEANS FOR THE PROJECT: NOTHING CHANGES
------------------------------------------------------
We target 13.4.8, where both defects are present and VERIFIED. The bug remains
the best code-execution lead. R34's hardware failure was a DELIVERY problem
(our LaunchDaemon never ran), not a problem with the bug.

R35.5 TOOLING WORTH KEEPING (in /home/claude/kccur/t/)
-------------------------------------------------------
  grab.py   one-shot: `python3 -I grab.py <ipsw-url> <outdir>` -> kernel.macho.
            Range-requests the ZIP64 central directory, pulls ONLY the
            kernelcache member, handles BOTH LZFSE (bvx2) and Apple LZSS
            (complzss). Supersedes zipcd.py + getmem.py + unlzss.py.
  check.py  packaging-agnostic defect detector: finds the UDIF kext via
            LC_FILESET_ENTRY *or* legacy __kmod_info, disassembles its __text,
            prints the fix markers. Distinguishes PAC vtable dispatches
            (`ldr x,[x16,#0xa0]!` / `#0xd8]!`) from plain field loads at the
            same offsets - that distinction is what made the analysis possible.
  fsk.py/fs.py/show.py  MH_FILESET + arm64e parser. A modern cache is
            filetype 12 (MH_FILESET, 173 LC_FILESET_ENTRY), cpusubtype
            0xc0000002 (arm64e ptrauth ABI), chained fixups where
            VA = 0xfffffff007004000 + (ptr & 0xffffffff). gkc.py does NOT work
            on these - there is no __PRELINK_INFO/__kmod_info at all.
  scan.py   whole-__TEXT_EXEC semantic signature scan, for iOS-14-era merged
            caches with empty prelink segments and no per-kext headers.
  udif271.asm  full disassembly of 27.2.1's UDIF kext, 11,681 instructions.
  dev_AudioAccessory5_1.json  54-entry firmware URL list - any row of the
            timeline is re-fetchable in ~90 s.
  trie.py/vt.py/vt2.py  symbol-recovery attempts that DID NOT work; kept only
            so nobody repeats them. Both caches have nsyms=0 and the top-level
            cache has only a 0x3a6-byte LC_DYLD_EXPORTS_TRIE.

================================================================================
R36 — NON-ENGLISH RESEARCH SWEEP. THE STRATEGIC PICTURE CHANGES.
      2026-11-26 21:35 PST.  Nic's call to search Chinese sources paid off.
================================================================================
R36.0 *** THE BIG ONE: "CANNOT MAP OUR OWN CODE" IS NOT A SEPARATE BLOCKER ***
-------------------------------------------------------------------------------
Alibaba Security Pandora Lab (阿里安全潘多拉实验室, 耀刺/黑雪),
https://developer.aliyun.com/article/642626 — verbatim Chinese + translation:
  "内核中AMFI使用trust cache快速校验ad-hoc的binary，它是一个链表式的数据结构，
   并且**存放的位置不受限于KPP/AMCC的保护**"
   = AMFI uses the trust cache to validate ad-hoc binaries; it is a LINKED LIST
     and ITS STORAGE IS NOT COVERED BY KPP/AMCC PROTECTION.
  "**内核中有2个trust cache chain**...**只要通过其中一个校验即可**...
   上述static trust cache chain无法修改，**但是另外一个依然可以修改**！
   并且**binary通过trust cache的校验后，无需再进行CMS校验**！"
   = THERE ARE TWO TRUST CACHE CHAINS. Passing EITHER is sufficient. The static
     chain (const data, checked by pmap_lookup_in_static_trust_cache) cannot be
     modified, BUT THE OTHER ONE STILL CAN. And once a binary passes the trust
     cache check, NO CMS VALIDATION IS REQUIRED.
Corroborated independently by Soulghost (blog.asm.im), who analysed this on an
**iPad Air 2 (A8X) running iOS 13.1.1** - the closest configuration to ours in
any language:
  https://blog.asm.im/2020/06/14/iOS-Jailbreak-Principles-0x02-codesign-and-amfid-bypass/
  - static cache = sorted cdhash array, binary search
  - dynamic cache = LINKED LIST of nodes each holding sorted cdhashes, looked up
    at **pmap_lookup_in_loaded_trust_caches** (the iOS 13 symbol)
  - "我们只需要找到 dynamic cache 的全局变量，为这个链表增加一个结点即可"
    = we need only find the dynamic cache's global and add a node to the list.
    The global is located by XREF from that function.
  - He enumerates exactly three routes to unsigned code: trust-cache poisoning,
    CoreTrust bypass, amfid exception-handler hijack.
  - Companion posts: "通过 String XREF 定位内核数据" (patchfinder-style data
    location) and "通过 IOTrap 实现内核任意代码执行" - IOTrap is a **non-PAC**
    kernel-code-execution technique, i.e. applies to A8.

*** WHAT THIS MEANS FOR OUR PLAN ***
R24.4 concluded the loadable trust cache was a dead end because
AppleMobileFileIntegrityUserClient::loadTrustCache needs the
can-load-trust-cache entitlement AND an ECID-personalised Image4 manifest. That
is true of the KERNEL API PATH. It is NOT the only path: with kernel write we
append a node to the loadable chain's list head DIRECTLY, never calling the
API, and the structure sits OUTSIDE KPP - which matters enormously on A8 where
KPP is live and we had been assuming data-only patching everywhere.
=> The project is now ONE problem, not two: **get kernel read/write.** After
   that, code signing is a data patch and KPP is not in the way. Our UDIF bugs
   and CVE-2020-27932 are the whole job.
   NEXT CONCRETE STEP when we have kernel write: locate the dynamic-trust-cache
   global by XREF from pmap_lookup_in_loaded_trust_caches in our kernelcache.
   That is a local analysis task, doable now, before we have the primitive.

R36.1 *** CVE-2020-9971 — A LAUNCHD PRIMITIVE THAT MAY SOLVE OUR CURRENT WALL **
-------------------------------------------------------------------------------
Zhipeng Huo (霍植鹏, @R3dF09) @ Tencent Security Xuanwu Lab 玄武实验室,
https://xlab.tencent.com/en/2021/01/11/cve-2020-9971-abusing-xpc-service-to-elevate-privilege/
launchd's access check for adding a service to ANOTHER process's process domain
never compared the caller's PID against the domain owner's. THREE independent
ways through, and we already satisfy two of them:
  (1) service path under the target's subdirectory - checked with strncmp, so
      "../" traversal defeats it
  (2) **the caller is root**                                  <-- WE ARE
  (3) sandbox_check_by_audit_token("forbidden-launchd-control") returns 0,
      true for any unsandboxed process                        <-- WE ARE
Huo used xpc_add_bundles_for_domain to register a service into
systemsoundserverd's domain, and added a SOCKET LISTENER to the service plist so
connecting to the port made launchd start it as root.
VERSION TIMELINE per the post: works before iOS 13.5; **13.5 switched to a
resolved-real-path API, blocking ../ but STILL allowing services to be added
into subdirectories of the target**; **iOS 14.0 added the actual owner check.**
=> Our build is 13.4.8, i.e. BEFORE 13.5. Potentially the full unmitigated bug.
=> This is a documented way to get launchd to honour a plist we supply WITHOUT
   touching the signed MRM cache - exactly the wall we hit in R34.
THE AGENT'S OWN CAVEAT, which I share: does the service's EXECUTABLE still need
to pass a signature check? Huo's payload was a legitimately signed binary so the
post does not say. **For us this may not matter: our payload IS /usr/sbin/hdik,
already trust-cached.** We only need launchd to run a signed binary with OUR
ARGUMENTS and OUR FILE.
OPEN PROBLEM: calling xpc_add_bundles_for_domain needs code running on the
booted audioOS, which is what we do not have - circular. UNLESS the registration
persists on disk. Job 597 found /mnt1/private/var/db/com.apple.xpc.launchd/config/
EXISTS (empty, Jun 30 2020). If launchd reads service definitions from there at
boot, that is a SECOND writable plant location that is not the signed cache.
CAVEAT: /private/var is the DATA volume at runtime, so a write to the System
volume's copy may be shadowed. Needs checking against the launchd binary.

R36.2 THE MRM CACHE: WHAT THE SIGNATURE ACTUALLY IS
-----------------------------------------------------
https://github.com/Lakr233/vphone-cli/pull/807 (mpass99; Lakr233 is a Chinese
developer; not indexed by any English jailbreak venue). iOS-18-era, so transfer
is UNCERTAIN, but it documents the modern descendant of our mrm.plist/.sig:
  - injectLaunchDaemons edits /System/Library/xpc/launchd.plist and keeps
    Apple's launchd.plist.sig
  - **launchd_cache_loader validates the plist against that DETACHED SIGNATURE**
    and then asks AMFI whether the signature's cdhash is in a trust cache, via
    isCdhashInTrustCache
  - before their fix this failed, which is why the project had a boot-arg-style
    escape hatch named **launchd_cache_loader_unsecure_cache_gate**
  - their fix: read the cdhashes out of Apple's existing .sig, re-sign the
    edited cache, write it root:admin 0644, and add the new cdhashes to the
    trust cache
  - "Apple's static trust caches are version 2 and carry a category for every
    CDHash" (v1 entries 22 bytes - MATCHES our 578-entry v1 finding; v2 entries
    24 bytes with a constraint_category field)
=> ACTION: grep our /sbin/launchd for `launchd_cache_loader` and anything like
   `..._unsecure_cache_gate`. If a 13.x equivalent exists it is far cheaper than
   re-signing. Also fetch CustomFirmwareDetachedSignature.swift from that repo -
   the agent could not (the PR diff page truncates at ~104 KB) and it holds the
   exact blob format.

R36.3 A8 SEPROM — REAL, A8-SPECIFIC, BUT NOT AN UNTETHER
----------------------------------------------------------
Pangu (盘古) / windknown, "Attack Secure Boot of SEP", MOSEC 2020:
https://raw.githubusercontent.com/windknown/presentations/master/Attack_Secure_Boot_of_SEP.pdf
(full text saved by the agent at /home/claude/cnres/sepboot.txt)
  - A8 TZ0/TZ1 in AMCC: TZ0 base/end 0x2_0000_0480/0484, TZ1 0488/048C, locks
    0490/0494. Measured A8: TZ0 0x0/0xBFF, TZ1 0x3_F580-0x3_F5FF.
  - SEPROM and AMCC compute the protected range with DIFFERENT INTEGER WIDTHS;
    offsetting TZ0 by 0x10_0000 makes AMCC protect the wrong range => AP can
    read AND WRITE SEP's external RAM after `boot tz0`.
  - Two SEP pages are NOT encrypted (0x8_00BF_0000, 0x8_00BF_F000) and the 24
    random bytes seeding the TZ0 AES-XEX keys live at 0x8_00BF_F018/F048 in
    AP-writable memory => key pinning by writing constants.
  - Review slide, verbatim: "**A8/A9 - Load arbitrary SEPOS**"; A7/A11 not
    vulnerable.
  - *** POST-TALK ADDENDUM, the most actionable line: "An attendee told me that
    **A8 SEPROM is not checking TZ0 lock !** And I found out this is TRUE.
    **Patch iBoot not to set TZ0 lock -> accessing SEP memory**" - so on A8 the
    0x10_0000 offset trick is not even needed. ***
  - Full SEP mailbox protocol documented (endpoint 255 to SEPROM; opcodes 1/2
    ping, 3 gen nonce, 4 report nonce, 5 boot TZ0, 6 boot SEPOS, 7 ART,
    8 resume, 9 set flag, 10 panic, 14 TEST, 15 seed DPA, 16 random A9+,
    201 status, 255 panic). Mailbox IO: AP 0x2_0DA0_4000, SEP VA 0xCDA0_0B80.
HONEST APPLICATION: the deck says plainly "AP and SEP have separated secure boot
chains." Owning SEPOS does NOT relax AP-side Image4 verification. It needs
checkm8 + an iBoot patch, i.e. TETHERED. Value to us: (a) it is the enabler for
UNTETHERED DOWNGRADE on A8/A9 (SEP version pairing stops being a constraint),
and (b) if Nicotine ever needs SEP cooperation (keybags, effaceable storage,
UID-key ops) we would have arbitrary SEPOS on exactly our SoC.
blackbird (windknown + littlelailo, independently): affects A8/A9/A10/T2; on A8
and A9 it gives KEY PINNING. **checkra1n's open-source pongoOS implementation
covers only A10 and T2 - the A8/A9 variant has NEVER been published as open
source.** That is a real gap we could fill from the Pangu deck.
turdus merula does untethered downgrade WITH a valid APTicket - but covers
A9(X)/A10(X) only. For A8, LukeZGD's status gist says only: downgrade with
SHSH blobs via futurerestore, tethered restores via surrealra1n.

R36.4 HARD NEGATIVES FROM THIS SWEEP — STOP SPENDING TIME
-----------------------------------------------------------
 - **CoreTrust multiple-signer / TrollStore class: DEAD on iOS 13.** theapplewiki:
   "iOS 12 and 13 share the underlying bug, but it isn't exploitable there.
   CoreTrust works differently on those versions, and the App Store Fast Path
   that makes the bypass work was introduced in iOS 14.0 beta 2."
 - **Chinese HomePod repair-industry firmware lore: does not exist.** Searched
   52audio, mydigit.cn 拆机乐园, bilibili teardowns, Mobile01, and the NAND
   programmer ecosystem (JC P13, iRepair P10-P12, MagicCFG, NAND-Pro).
   Everything on HomePod 1st gen is board-level electrical repair. The
   programmer ecosystem documents SysCfg/NAND work for iPhones, not HomePod,
   and nothing addresses NVRAM boot-args filtering or production fusing.
 - **No non-English source addresses iBoot 5540.x or A8/A9 iBoot bugs at all**
   beyond re-describing checkm8. Chinese "iBoot 源码泄露" coverage is all 2018
   news-cycle reporting on the iOS 9 leak.
 - **Nothing in any language on NVRAM boot-args filtering / CPFM / demotion on
   A8** beyond tool source (ipwndfu, NyanSatan's checkm8_bootkit demotion flag).
 - **Nothing in any language on the launchd MRM cache on iOS 13.** R36.2 is the
   only substantive material anywhere and it is iOS-18-era.
 - **No non-English work on xnu-6153.x bugs outside the CVE record.** 安全客's
   iOS corpus is overwhelmingly translated P0/ZecOps/Google material.
 - *** NO NON-ENGLISH SOURCE DESCRIBES AN UNTETHERED BOOT OF UNSIGNED CODE ON A
   PRODUCTION-FUSED A8. *** Not a gap in the search - it follows from the
   architecture, which the Chinese sources state plainly. Every "完美越狱" in
   that literature means code that re-runs automatically from the filesystem
   after a normal, Apple-SIGNED boot. Pandora Lab's own definition:
   "完美越狱和非完美越狱的主要区别在于重启过程中是否能自动执行越狱代码".
   => OUR UNTETHER IS A PERSISTENCE-PLUS-CHAIN PROBLEM, NOT A BOOT-CHAIN
      PROBLEM. That reframing is the most valuable thing in this report.

R36.5 PEOPLE AND VENUES
-------------------------
Worth following: windknown (盘古, github.com/windknown/presentations);
littlelailo; 阿里安全潘多拉实验室 (耀刺, 黑雪, cererdlong/龙磊, eakerqiu);
Xiaolong Bai 白小龙 + Min "Spark" Zheng 郑旻 @ Alibaba; Zhipeng Huo @R3dF09
@ Tencent Xuanwu; **Soulghost (blog.asm.im) - the only author found working on
A8X/iOS 13.1.1**; Liang Chen 陈良 @ Keen (his MOSEC 2020 "iOS in 2020" is where
zone_require was discussed from the attacker side); Wang Yu (MOSEC 2020 SEP
runtime, sks keystore); a1exdandy / DSEC (the Unicorn/uEmu checkm8 heap-grooming
analysis on habr - but it says NOTHING about persistence or demotion, flagged so
we do not re-read it hoping); NyanSatan (checkm8_bootkit has demotion and KBAG
decryption options; mostly pre-A7 targets but the demotion plumbing is relevant).
UNCONFIRMED: "Ghost Wolf Lab (@Snow_Wo1f)" on iBoot SMMU bypass - could not
substantiate, and it is Apple-Silicon-era anyway.
COULD NOT REACH, i.e. UNEXPLORED NOT EMPTY: blog.pangu.io (connection failure);
paper.seebug.org (521 + JS challenge; /1065/ is a Chinese checkm8 analysis);
**bbs.kanxue.com 看雪 (captcha) - the biggest gap, most likely home for A8-era
KPP/iBoot detail, thread-220915 on KPP unread**; xz.aliyun.com 先知 (results
render client-side; effectively unsearched); blog.csdn.net; freebuf;
**tttang.com/archive/284 - a Chinese iOS 8.1.2 UNTETHER analysis, the single
most on-point unread document found, because iOS 8 was the last true-untether
era AND the A8 era**; secrss.com; media.weibo.cn; mosec.org; x.com/Weibo/WeChat.
Agent's odds if we do one more pass with a captcha-capable browser: ~60/40 that
看雪 + 先知 yield one more R36.0-grade finding; near-zero that any of them
yields a production-fused A8 boot-chain untether.

R36.6 INCIDENTAL
------------------
The agent surfaced github.com/OrchardLinux/gpu issue #6: "A8 (T7000) GPU: RGX
hang cause on iPhone 6 was PMGR MiscACG; firmware boots and compute jobs
complete". Flagging in case that is Nic's own project or a sibling effort - it is
publicly indexed under these search terms.

---

## R37 - Job 601 + the launchd fleet report: why every drop-in plant was dead, and the one-substring way around it

### R37.0 Provenance note (this matters for everything below)

The launchd analysis in this section was done against a **pristine copy of
audioOS 13.4.8 (17M61)** pulled from Apple's still-live no-prereq OTA for
`AudioAccessory1,1` (1.63 GB, `updates.cdn-apple.com`, range-request friendly,
streamed through a `pbzx`/XZ `payloadv2` parser without storing the archive).

The two files we had already pulled off the bench pod hash **identical** to the
OTA copies:

| file | SHA256 | |
|---|---|---|
| `/sbin/launchd` (365,776 B) | `cb96819393bb497c334a08cce8c4e90c388e85d2a7e366645b4ba9f31e8b8059` | match |
| `mrm.plist` (256,299 B) | `652b1feac6ea57d96964aa8e96d71e600bc921c769cc8ec54ea4453c67408651` | match |

So every claim below is verified against the device's own bytes, **and the bench
pod's `mrm.plist` is pristine** (untouched since 2020-06-30). Also verified: the
**SU restore ramdisk's `/sbin/launchd` is the same file** (same SHA256). Ramdisk
launchd and system launchd are one binary; the difference is purely runtime
state. That is the whole answer to R37.2.

Earlier `grep -c` string counts in R36 were misleading: `-c` counts **lines**,
and a Mach-O string table has almost no newlines. `launchd_cache_loader` is 3
lines but `xpc.launchd` is 34 **occurrences**. Nothing was missing. Correct
R36's counts accordingly.

### R37.1 Every drop-in LaunchDaemon plant in jobs 595/597/599/601 was dead on arrival

**VERIFIED.** On a normal boot launchd takes every job from the signed MRM cache
and **never scans `/System/Library/LaunchDaemons`**. The cache is keyed by
**absolute plist path** and the value is the **fully merged job dictionary**
including `ProgramArguments`:

```python
'/System/Library/LaunchDaemons/com.apple.ABDatabaseDoctor.plist': {
    'Label': 'com.apple.ABDatabaseDoctor',
    'ProgramArguments': ['/System/Library/Frameworks/AddressBook.framework/Support/ABDatabaseDoctor'],
    'MachServices': {'com.apple.ABDatabaseDoctor': True},
    'UserName': 'mobile', 'POSIXSpawnType': 'Interactive', ... }
```

Consequences:
- **All 185 on-disk daemon plists are inert.** Editing one in place does nothing.
  There is no "best victim" among them. **This route is DEAD; stop spending
  cycles on it.**
- Related useful negative: **0 of 183 cached daemons has a
  `Program`/`ProgramArguments[0]` that does not exist on disk.** There is no
  dangling daemon binary to create.
- `nicsfix-mark` never being set in job 601 is fully explained. It was never a
  failure of planting, persistence, or `root-live-fs`.

`mrm.plist` top level: `LaunchDaemons` (183), `AppExtensions` (48),
`SystemLibraryTreeState` (45), `AppRemovalServices` (0), `VersionNumber` 7.
`SystemLibraryTreeState`'s keys are **framework binary paths** that export
XPCServices, not directory mtimes - so there is **no "tree changed, rescan
disk" lever** there. `_imagePathToInfo` is inserted at runtime, not stored.

### R37.2 THE GATE: one BSS byte set by `strstr(kern.bootargs, "rd=md0")`

**VERIFIED**, `launchd` 0x100031f00-0x100031f1c:

```
ldr  x0, [x22, #0xc18]       ; the kern.bootargs string
adr  x1, "rd=md0"
bl   _strstr
cmp  x0, #0
cset w8, ne
strb w8, [x9, #0x8a1]        ; flag = (bootargs CONTAINS "rd=md0")
```

The byte lives at **0x10004e8a1 in `__common` (BSS)**, so it defaults to 0, and
that is the **only** write to it. `try_mrm()` at 0x10000f8e8 consults it at four
sites; the `launchctl` dump path at 0x100020ff4 renders it as the two strings
that name the behaviour exactly:

```
csel x2, "system services must be in cache", "disk will be searched for uncached services", ne
```

- **flag 1** (ramdisk/restore boot, `rd=md0` present): missing cache tolerated,
  launchd synthesises empty dicts, boots off drop-in plists. *This is why our
  2024 SU ramdisk logs "No MRM cache found" and boots fine from the same binary.*
- **flag 0** (normal boot from the System volume): a missing, truncated,
  non-dictionary or key-incomplete `mrm.plist` is **`_os_crash` in PID 1**, via
  `"No service cache"` / `"No daemons in cache"` / `"No tree state entry in
  cache"` / `"No frameworks in cache"`.

**>>> HARD SAFETY RULE: NEVER rename, move or truncate
`/System/Library/Caches/com.apple.xpc.launchd`. On a normal boot that is an
unbootable PID 1 crash. Job 599 did exactly this and the pod survived only
because an APFS revert undid the rename before the cold boot. <<<**

**THE BYPASS.** It is `strstr`, a **substring** test, not a boot-arg token
lookup. Job 601 read NVRAM and found `boot-args  -v serial=3` **still live from
job 593** - boot-args are writable (one of the four `setenv` names iBoot
permits, see R30.2) and persistent. The kernel resolves boot args by name via
`PE_parse_boot_argn`, which matches `"rd"` exactly, so a token spelled
**`xrd=md0z`** is ignored by the kernel but **matched by launchd's `strstr`**.

```
nvram "boot-args=-v serial=3 xrd=md0z"
```

should put launchd in "disk will be searched for uncached services" mode **with
the signed cache fully intact** - no cdhash problem, no `.sig` forgery, no edit
to `mrm.plist`. Queued as job 602 lever B. *Open question sent back to the
fleet: with flag 1 AND a valid cache present, does launchd scan drop-ins in
ADDITION to using the cache, or does "Using MRM cache" short-circuit the walk?*

### R37.3 The `.sig` is real, enforced, and not forgeable - and re-signing is pointless

launchd's own cache read at 0x10000f7b8 is `open` + `fstat` +
`dispatch_data_create`. **No `.sig` read, no `SecStaticCode*`, no AMFI.**
Enforcement lives in **`/usr/libexec/launchd_cache_loader`** (libxpc-1738.140.1,
53,456 B), a separate boot task with `RequireRun=true, RequireSuccess=true`.

`mrm.plist.sig` (3,666 B) decoded: Mach-O `CSMAGIC_EMBEDDED_SIGNATURE`
SuperBlob `0xfade0cc0`, 5 blobs. CodeDirectory `version 0x00020100`,
**`flags = 0x00000002` = CS_ADHOC**, `nCodeSlots 63`, **`codeLimit = 0x3e92b =
256299`, exactly the file size**, SHA1, 4 KiB pages, identifier
`mrm-8c7b070fa7c62fd55d6686f9e95a2b07a046625e`; alternate SHA256 CodeDirectory
at 0x5b1; **`CSSLOT_SIGNATURESLOT` is 8 bytes - an empty CMS blob.**

- `codeLimit == file size` ⇒ **no unhashed slack**; the plist cannot be appended
  to or padded.
- The signature is **ad-hoc**, so there is no key to forge *and no key that
  would help*. What gates it is the **cdhash trust-cache lookup**.
- Every loader failure branch - including `cdhash: %s is not in trust cache` -
  converges on 0x100002d88: `mov w0,#7; mov w1,#1; b _abort_with_reason`
  (`OS_REASON_LIBSYSTEM`, code 1), which with `RequireSuccess` fails the boot.

**No `launchd_unsecure_cache` escape hatch exists on 13.4.8** (clean negative):
the loader contains no `unsecure`/`gate`/`boot`/`arg`/`env`/`sysctl`/`variant`/
`skip`/`force`/`override`/`internal` strings and imports no `getenv`, `sysctl`,
`sysctlbyname`, `os_variant_*` or `csops`. That boot-arg was added **after**
13.4.8. Editing `mrm.plist` therefore stays blocked until we have kernel write
and can append a loadable trust cache (R36) - at which point it becomes the
nicest persistence mechanism on the device.

Best single diagnostic for this whole subsystem:
**`/var/log/com.apple.xpc.launchd/launchd_cache_loader.log`** - the loader
writes `abort: <reason>` there with mode `"w"`.

### R37.4 THE OTHER WAY IN: three DANGLING boot-task `Program` paths

launchd's `__TEXT,__config` embedded plist holds a `Boot` dictionary of boot
tasks run in a hardcoded order (0x10002dea4-0x10002e098):

```
fsck -> mount-phase-1 -> data-protection -> finish-obliteration -> restore-datapartition
-> mount-phase-2 -> MSUEarlyBootTask -> fips -> keybag -> xpcroleaccountd
-> init_featureflags -> fud -> tzinit -> finish-restore -> finish-demo-restore
-> sysstatuscheck -> prng_seedctl
-> [launchd opens+mmaps mrm.plist: 0x10000f7b8]
-> launchd_cache_loader  (RequireRun, RequireSuccess)
-> [try_mrm: 0x10000f8e8] -> "Early boot complete. Continuing system boot."
```

The same `__config` declares the drop-in search paths as
**`/System/Library/LaunchDaemons` and `/AppleInternal/Library/LaunchDaemons`
only** - note `/Library/LaunchDaemons` is **not** a bootstrap path on stock
audioOS 13.4.8.

Three of those `Program` paths **do not exist on a stock 17M61 System volume**
(checked against a complete 16,802-path OTA file list):

| boot task | Program (DANGLING) | flags | runs on normal boot? |
|---|---|---|---|
| `sysstatuscheck` | `/usr/libexec/sysstatuscheck` | `PerformAfterUserspaceReboot`, **`RebootOnSuccess`** | **yes** |
| `finish-restore` | `/usr/libexec/FinishRestoreFromBackup` | **`RequireSuccess`**, `PerformAfterUserspaceReboot` | **yes** |
| `restore-datapartition` | `/usr/libexec/HorizonSetup` | `PerformInRestore`, `RequireSuccess` | no (restore only) |

Why `sysstatuscheck` is the best target on the device:

- launchd, **PID 1, root**, from launchd's **own signed `__TEXT` config** - no
  Label for launchd to reject, no plist to edit, **and it runs BEFORE
  `launchd_cache_loader`**, so the MRM cache and the `.sig` are irrelevant to it.
- It is #16 of 17: **after `mount-phase-2`** (so `/private/var` is mounted and
  writable) and **before** the cache is validated.
- Nothing forces it to exist, so its absence today is silent.
- **`RebootOnSuccess=true` makes a non-zero exit the desired outcome**: exit 0
  reboots the device, non-zero lets the boot continue completely normally. That
  is the ideal first test - a pod that boots to audioOS as usual while having
  run our code. **`finish-restore` is the opposite (`RequireSuccess`), so do
  NOT plant there.**
- Corroboration that these fire on a non-restore boot: third-party iOS 16
  research logs `tzinit, finish-restore, finish-demo-restore, sysstatuscheck,
  prng_seedctl` all running on a normal boot. VERIFIED on iOS 16 by others,
  INFERRED for 13.4.8 from the same `__config` keys in the disassembled binary.

**What to plant there.** Trust caches are keyed by **cdhash, not path** - the
loader's own AMFI call passes one scalar plus a cdhash struct and no path. So:

- **(a) a byte-for-byte copy of an already-trust-cached binary.**
  `cp /usr/sbin/racoon /usr/libexec/sysstatuscheck` execs as a platform binary
  and keeps racoon's entitlements. argv is only the program path, but several
  such binaries read attacker-controlled config from fixed paths regardless of
  args (`racoon` -> `/etc/racoon/racoon.conf`, `pppd` -> `/etc/ppp/options`,
  and per R25 `/etc/ppp/options` IS live on 13.4.8). That turns a dangling boot
  task into "root parses our file at early boot".
- **(b) a `#!` script - the way to inject ARGUMENTS into a trust-cached
  binary.** XNU's shell imgact gives interpreter + **one** optional argument,
  with the script path appended. Rests on our own verified finding that this
  build's `mpo_vnode_check_exec` **cannot deny** (R-AMFI), and a script is not
  a Mach-O so there is no signature to check.
  Job 602 uses `#!/usr/sbin/nvram nicsfix-sys=ran`, giving
  `argv = [nvram, nicsfix-sys=ran, /usr/libexec/sysstatuscheck]` - sets the
  marker, then fails on the path as an unknown variable, exits non-zero.
- **(b') the construction worth trying once (b) is proven:** a **single file
  that is simultaneously a valid `#!` script and a valid disk image.** A UDIF
  image carries its `koly` trailer at the **END** of the file, so the first
  1024 bytes are free for `#!/usr/sbin/hdik -nomount\n`. `hdik` is then handed
  **our own image** as its last argument and walks the in-kernel UDIF parser
  (R-UDIF defects 1-3) as root at early boot. Strictly better than the raw
  HFS+ variant for us, because our parser work is on `KDIUDIFDiskImage`.
  INFERRED - `hdik`'s argument parsing is unverified.

### R37.5 Lower-value unsigned-input-at-boot surfaces (parsers, not exec)

- **The only two on-disk plists launchd parses by path outside the cache:**
  `/System/Library/LaunchDaemons/com.apple.jetsamproperties.B238.plist` and
  `...B238a.plist` - the two of 185 absent from the cache (launchd hardcodes the
  `com.apple.jetsamproperties` prefix + board name). **Unsigned, read by PID 1,
  every boot.** Jetsam config only, no exec. Memory-corruption target.
  *Note b238a is our board, so `...B238a.plist` is the live one.*
- **`/private/var/db/com.apple.xpc.launchd/{disabled.plist, disabled.migrated,
  overrides.plist}` and `/private/var/db/launchd.db`** (0x100032660). On a normal
  boot launchd `stat`s `disabled.migrated`; if **absent** it `fts_open`s
  `launchd.db` and reads legacy `overrides.plist`/`disabled.plist` per
  subdirectory. Unsigned plists parsed by PID 1 at boot, on the **Data volume**.
  Believed to carry only `Disabled` state, so no `Program` override - INFERRED.
- **`/etc/bluetool/*.script`** read by `/usr/sbin/BlueTool` (1.4 MB, launched by
  `com.apple.BlueTool.plist`), with `RunExternalScript`/`RunBuiltinScript`/
  `Using alternate script %s`. **BlueTool is NOT an interpreter** - its "script"
  language is HCI/ACI chip commands (download HCD firmware, set baud, configure
  I2S/PCM, power-cycle the BT/WiFi chip). It cannot exec, open arbitrary paths,
  or evaluate logic. **Scratch it as an exec route**; keep it as a root parser
  of our files.

### R37.6 CVE-2020-9971: PARKED, and the reason is firm

**Clean negative.** `/sbin/launchd` (17M61) contains **no** string matching
`add_bundles`, `bundles_for_domain`, `process domain` or `subdirector*`. The one
matching string is **`forbidden-launchd-control`**, which confirms the
sandbox-check leg is present. `xpc_add_bundles_for_domain` is a **libxpc client
API**; the launchd side is a mach/XPC routine and the resulting process-domain
registration lives in launchd's **in-memory** domain state.

Decisive: launchd's **complete** set of `/private/var/db` path strings is
exactly two - `/private/var/db/com.apple.xpc.launchd` and
`/private/var/db/launchd.db`. **There is no `config` component anywhere in the
binary** and no code path reading
`/private/var/db/com.apple.xpc.launchd/config/`. That directory is a later-OS
`launchctl config` artifact. The circularity stands unbroken: 9971 needs code
already running on the booted OS, which is the thing we lack.

(That also resolves R36's `var/db` count question: one string used as the `%s`
prefix for the three plists, plus a separate `launchd.db` string that the
line-count collapsed.)

Generalisable caveat: **`/private/var` is the Data volume at runtime**, so
anything written to the System volume's `/private/var/*` through the ramdisk is
shadowed at boot. Conversely the Data volume is writable from the ramdisk, which
is where R37.5's `launchd.db` surface lives.

### R37.7 No interpreter exists on this build (clean negative, as strong as the name list)

Grepped the full 16,802-path System-volume list for perl, python, ruby, lua,
tclsh, osascript, node, jsc, awk, sed, sh, bash, dash, zsh, csh, ksh, expect,
PlistBuddy, plutil, defaults. **None.**
`/bin` is `df`, `ps`. `/sbin` is `launchd`, `pfctl`, `fsck` (+2 symlinks),
`mount` (+4 symlinks), `mount_nfs`, `umount`.
(`CoreNLP.framework/python` is a data **directory**, not a binary.)

This is why the `#!` route matters: there is no shell to point a shebang at, so
the interpreter has to be a non-shell trust-cached binary that does something
useful with one argument.

### R37.8 Second-best exec route: the `fsck` helper symlinks

`fsck` is boot task **#1** with **both** `RequireRun` and `RequireSuccess`, and
`/sbin/fsck` execs per-filesystem helpers through symlinks on the **writable**
System volume:

```
/sbin/fsck_apfs -> ../System/Library/Filesystems/apfs.fs/fsck_apfs
/sbin/fsck_hfs  -> /System/Library/Filesystems/hfs.fs/Contents/Resources/fsck_hfs
```

Repointing a symlink at a copy of a trust-cached binary gets us exec'd **even
earlier** than `sysstatuscheck`. But `RequireSuccess` means a non-zero exit
**kills the boot**, and this runs **before `mount-phase-2`** so `/private/var`
is not yet available. Strictly worse for a first test; the right tool only if we
need to be pre-mount.

### R37.9 Job 601 results (ramdisk, 2026-11-26 21:48)

```
nvram nicsfix-mark   -> not found      (explained by R37.1, not a plant failure)
nvram root-live-fs   -> not found      <- WE SET IT TO 1. The boot CONSUMED it.
nvram boot-args      -> "-v serial=3"  <- still ours from job 593. PERSISTENT.
/usr/libexec entries -> 132            (volume healthy)
snapshots            -> only com.apple.os.update-8AD664B2...  (nicsfix-planted gone)
```

- **`root-live-fs` is confirmed read-and-cleared on boot.** Whether it actually
  switched the boot root is still unknown, because the plants could not have run
  either way.
- **The revert flag is NOT armed any more.** A probe file written to `/mnt1`
  survived a full `umount`/`mount_apfs` cycle. Earlier losses (595/597) were the
  unclean-unmount bug (R30.1) plus one `snaputil -r` revert catching mid-flight;
  **do not use `snaputil -r` on the live volume again.** Plants persist now.
- `dd if=/dev/disk4` produced nothing, so no panic log was readable. `/dev/disk4`
  may not exist in this ramdisk; find the real panic-log device by `dd` probing,
  never `ioreg`.
- NVRAM also carries `obliteration: "Obliteration Complete"` and
  `oblit-begins: "OblitType: ObliterateDataPartition. Reason: Device was left in
  a partially-setup state"` - consistent with the Data partition having been
  obliterated, and relevant to the still-open "why does it never update" question.

### R37.10 Job 602 design (queued): three levers, three markers, one boot

| lever | mechanism | marker if it fires |
|---|---|---|
| A | shebang at `/usr/libexec/sysstatuscheck` -> `nvram nicsfix-sys=ran` | `nicsfix-sys=ran` |
| B | `boot-args=-v serial=3 xrd=md0z` flips the `strstr` flag -> drop-ins scanned | `nicsfix-mark=ran` |
| C | `root-live-fs=1` boots the live volume, where A and B live | (prerequisite for both) |

Neither marker ⇒ C is the failure, and C gets tested alone next.
**No UDIF/hdik payload this round** - `runcount.dmg` could panic the boot kernel
before any marker is readable. Prove execution first, then exploit.

Known risk accepted: if the `RebootOnSuccess` polarity is the reverse of what
the flag name implies, lever A reboot-loops the pod. Recoverable via DFU by
clearing the plant and boot-args. Confirmation requested from the fleet
(boot-task runner at 0x10002d1dc).

### R37.11 Rules added

- **NEVER rename/move/truncate `/System/Library/Caches/com.apple.xpc.launchd`.**
  On a normal boot that is `_os_crash` in PID 1 and the pod will not boot.
- **Never plant at `/usr/libexec/FinishRestoreFromBackup`** - `RequireSuccess`,
  so any non-zero exit kills the boot.
- **Do not use `snaputil -r` on the live System volume.** Reverts have cost us
  three jobs' worth of plants.
- `grep -c` on Mach-O string tables counts lines, not occurrences. Use `grep -o
  | wc -l` for string-presence work.

---

## R38 - Job 603: four jobs of nulls, one cause. The live volume is destroyed, and the boot has never been reading it.

### R38.0 The verdict reads (job 603, ramdisk, 2026-11-26 22:02)

```
LEVER A  nicsfix-sys   : not found
LEVER B  nicsfix-mark  : not found
LEVER C  root-live-fs  : not found          (consumed by the boot, as in 601)
         boot-args     : -v serial=3        <- WE SET "-v serial=3 xrd=md0z"
```

The pod booted normally and worked. Neither marker fired.

### R38.1 THE CAUSE: the live System volume is decaying, not reverting

Job 603 mounted `/dev/disk1s1` and found **everything gone**, including files
that are not ours:

```
usr/libexec/sysstatuscheck                        GONE
System/Library/LaunchDaemons/com.nicsfix.mark.plist  GONE
usr/standalone/nf.dmg                             GONE
usr/standalone/nf-armed.txt                       GONE
System/Library/Caches/com.apple.xpc.launchd/mrm.plist      MISSING
System/Library/Caches/com.apple.xpc.launchd/mrm.plist.sig  MISSING
```

**`mrm.plist` is the proof.** It is Apple's file, part of the stock 17M61
system, and job 602 verified it present at **256,299 B after a fresh
`umount`/`mount_apfs` cycle**. A revert to the `com.apple.os.update-8AD664B2...`
snapshot would **restore** it, because it exists in that snapshot. Instead it
**vanished**. So this is not the revert-on-mount behaviour of R37.9 - it is the
**progressive file-shedding cascade first seen in R30.1** (`227 -> 69 -> 132 ->
54` libexec entries, `/sbin/launchd` disappearing). The volume's object map was
left inconsistent by the `snaputil -r` half-revert and it drops more content on
every mount cycle.

**Therefore the pod has been booting the SNAPSHOT the entire time**, and nothing
planted on the live volume was ever read. That single fact explains every null
across jobs **599, 601, 602 and 603** - four cycles. The plants were never
executed; they were never even looked at.

It also means **lever A was never tested.** The dangling-boot-task route
(R37.4) remains completely unevaluated, not refuted. Same for lever B.

Corollary on lever C: `root-live-fs=1` is consumed on every boot but the device
still boots fine with a *damaged* live volume. Two readings, both consistent
with the data, and we cannot yet separate them:
- (i) `root-live-fs` does not actually switch the boot root on this build, or
- (ii) it does, the damaged live volume fails to mount, and the kernel falls
  back to the snapshot.
Either way the live volume must be **healthy** before `root-live-fs` can be
judged. **Any further conclusion about `root-live-fs` drawn from jobs 599-603 is
invalid.**

### R38.2 iBoot STRIPS unrecognised boot-arg tokens (new, and it blocks lever B as built)

Sequence, all verified by readback:

```
job 602 (ramdisk):  nvram "boot-args=-v serial=3 xrd=md0z"
job 602 readback :  boot-args  -v serial=3 xrd=md0z      <- accepted, stored
   ... cold boot, pod boots and works ...
job 603 readback :  boot-args  -v serial=3               <- xrd=md0z GONE
```

`-v` and `serial=3` survived; `xrd=md0z` was removed. Nothing in userspace has
any reason to rewrite that variable, so the most likely mechanism is **iBoot
sanitising the `boot-args` value per token against an allowlist of accepted
token NAMES, and dropping tokens it does not recognise.** This is consistent
with R30.2 (`boot-args` is one of the four permitted `setenv` names) - being
allowed to *set* the variable is not the same as the whole string reaching
`kern.bootargs`. **INFERRED**, mechanism not yet located in iBoot; sent to the
fleet.

Note this is *not* in tension with the silent UART: `-v` survived in the string,
so verbose logging is presumably on, but the serial **console** is separately
disabled on `CPFM:03`, so verbose output has nowhere to go. See R38.3.

**Consequence for the R37.2 bypass.** The naive
`strstr(kern.bootargs, "rd=md0")` gate is still naive and still the right idea,
but we cannot smuggle an arbitrary token. We need the substring `rd=md0` to ride
inside a token whose **name** is allowlisted. Best candidate to try next:

```
nvram "boot-args=-v serial=3rd=md0"
```

The token name is `serial`, which demonstrably survives. The kernel's integer
parse of the value yields `3`, so serial behaviour is unchanged. And the
resulting `kern.bootargs` string **contains the literal substring `rd=md0`**,
which is all launchd's `strstr` asks for. Untested.

(Do **not** try a bare `rd=md0`: that is the real token and would tell the
kernel to use a nonexistent md0 as the root device.)

### R38.3 The system kernel's UART console is dead on CPFM:03 regardless of boot-args

`job602normalbootscreenlog.0` is **1,522 bytes** and ends immediately after
iBootStage2's banner plus a handful of hashed `<hash>:<line>` log lines. The
kernel emitted **nothing**. `debug-uarts 3` is set, `-v` was in boot-args, and
the restore-ramdisk kernel chatters freely over the same wire - so the hardware
and the cable are fine and the difference is the boot path.

**Conclusion: on a production-fused part the system kernel's serial console
stays shut whatever we put in boot-args. Do not plan any test around reading
system-kernel UART output.** NVRAM markers are the only channel off a normally
booted pod, which is why the lever payloads are `nvram` writes. (Ramdisk UART is
unaffected and remains useful.)

### R38.4 Two ramdisk-environment corrections

- **`/tmp` does not exist on the restore ramdisk.** `mount_apfs -s ... /tmp/snap`
  failed with `mount_apfs: /tmp: No such file or directory`, so the snapshot
  read-only cross-check never ran.
- This **retroactively explains job 601's failed panic-log read**: that command
  was `dd if=/dev/disk4 ... of=/tmp/p.bin`, and the `ls: /tmp/p.bin: No such
  file` was `/tmp` missing, **not** `/dev/disk4` being absent. R37.9's note that
  disk4 may not exist is **withdrawn** - disk4 is untested. Use `/mnt1/...` or a
  path under the ramdisk root for scratch files, and `mkdir` any mountpoint
  first.

### R38.5 Decision: restore to 17M61 before anything else

The live volume cannot be repaired by us and will keep shedding files. We hold
what we need for a clean slate:

```
~/homepod/homepodstuff/HomePod-13.4.8-17M61.ipsw
~/homepod/tickets/tickets/000024EA009A60A6/13.4.8-17M61.shsh2   (bench pod ECID)
~/homepod/tickets/BuildManifest-13.4.8-17M61.plist
```

The runner **deliberately never restores** (`hp-runner.command:59` - "It never
runs a restore (idevicerestore is not used)"), so the restore is a manual step
in HomePod Hospital.

After the restore, and **before the first normal boot**, the open question is how
to make the boot read a volume state containing our plant. Options sent to the
fleet for ranking against the kernel:

| option | plant target | lever |
|---|---|---|
| (i) | live volume | `root-live-fs=1` (now testable for the first time on a healthy volume) |
| (ii) | live volume | delete Apple's `com.apple.os.update-*` snapshot so the boot must fall back to live |
| (iii) | live volume | create a snapshot whose name matches the expected `com.apple.os.update-<40 hex>` pattern, then delete Apple's |

(iii) is the interesting one and hinges on whether the chosen snapshot's name or
XID is authenticated against the APTicket / img4 manifest or a sealed-volume
hash. If it is not, the boot snapshot is attacker-selectable on a device we can
write the System volume of, and that is a far cleaner primitive than
`root-live-fs`.

### R38.6 Rules added

- **Never use `snaputil -r` on the live System volume.** It has now cost us a
  volume outright, on top of three jobs' worth of plants. Promoted from R37.11
  to a hard rule.
- **Do not design a test around system-kernel UART output on this device.**
  NVRAM markers only.
- **`/tmp` does not exist on the restore ramdisk** - `mkdir` any scratch dir or
  mountpoint before use.
- **Verify a plant's target volume is the one that actually boots** before
  concluding anything from a missing marker. Four jobs were spent on this.

---

## R39 - RETRACTION: lever A is a boot-killer, lever B does not scan, and our evidence channel is unverified

### R39.1 *** RETRACTED: the dangling-boot-task route (R37.4) is DEAD and DANGEROUS ***

**VERIFIED** in `/sbin/launchd` 0x10002d6dc-0x10002d7f0 (pristine 17M61):
launchd **verifies the code-signing identity of every boot task it spawns**, and
`_os_crash`es PID 1 on mismatch.

```
posix_spawnp(&pid, program, &file_actions, &attrs, argv, envp)
        ; spawnattr flags = 0x408c
        ;   0x4000 CLOEXEC_DEFAULT | 0x0080 START_SUSPENDED | 0x0008 SETSIGMASK | 0x0004 SETSIGDEF
csops(pid, CS_OPS_STATUS=0, &flags, 4)
  err                       -> "boot task is not a platform binary" -> _os_crash  (FATAL, PID 1)
  tbz flags,#26 (CS_PLATFORM_BINARY 0x04000000 clear)
                            -> "boot task is not a platform binary" -> _os_crash  (FATAL)
<get signing identity of pid>
  NULL  -> "failed to get the code signing identity for a boot-task (%s, %s)"     -> _os_crash
expected = CSIdentityOverride ?: sprintf("com.apple.%s", basename(Program))
strcmp(expected, actual) != 0
        -> "code signing identity mismatch for a boot-task (%s, %s, %s, %s)"      -> _os_crash
kill(pid, SIGCONT)      <-- the payload's FIRST INSTRUCTION only runs here
```

A boot task must be `CS_PLATFORM_BINARY` **and** carry signing identity exactly
`com.apple.<basename of Program>`. For `/usr/libexec/sysstatuscheck` that is
`com.apple.sysstatuscheck`. (This is why the config has two `CSIdentityOverride`
entries: `init_data_protection` is a symlink to `seputil`, and
`xpcroleaccountd` -> `com.apple.xpc.roleaccountd`.)

Both payload shapes we had planned fail it:
- **copy of a trust-cached binary** -> identity `com.apple.hdik`/`com.apple.nvram` -> os_crash
- **`#!` script** -> after the shebang exec the process image **is** the
  interpreter, so the identity is the interpreter's -> os_crash

And because the child is **START_SUSPENDED** and `SIGCONT`ed only after both
checks pass, **the payload never executes at all. There is no window.**

A content scan of **every file in the 17M61 image** (dyld shared cache included)
for `com.apple.sysstatuscheck`, `com.apple.HorizonSetup` and
`com.apple.FinishRestoreFromBackup` returned **zero hits**. No identity squat is
available.

**>>> HARD RULE: plant NOTHING at any boot-task `Program` path. The failure mode
is asymmetric and it is a landmine: <<<**

| planted at a dangling boot-task path | result |
|---|---|
| nothing (stock) | `"<task>: optional boot task not present"`, boot continues |
| unsigned Mach-O | `posix_spawnp` fails (AMFI) -> `RequireRun` unset -> **benign** |
| **shebang script** | spawn succeeds -> identity mismatch -> **os_crash, PID 1, boot dies** |
| **copy of a platform binary** | spawn succeeds -> identity mismatch -> **os_crash, PID 1, boot dies** |

Never plant at `/usr/libexec/FinishRestoreFromBackup` either (`RequireSuccess`),
nor `/usr/libexec/HorizonSetup`.

**Note R38.1 still stands: lever A was never actually tested on-device** (the
plant sat on a volume that never booted). It is refuted by static analysis, not
by experiment - but the static analysis is instruction-level and conclusive.

### R39.2 Boot-task runner semantics, settled (VERIFIED 0x10002d1dc-0x10002dc08)

- **flags word (w1)**: bit 0 = *ignore* `RequireRun`/`RequireSuccess`/
  `RebootOnSuccess`/`RebootOnExitCode` (0x10002d2f4 -> 0x10002d384 zeroes all
  four). **Never set.** Every call site passes 0 except `launchd_cache_loader`,
  which passes **4**. Bit 2 (=4) is unrelated: at 0x10002d634 it means *hand the
  child the mapped `mrm.plist` as `xpc_shmem`*
  (`dispatch_data_create_map` on the global at 0x10004f9d8 -> `xpc_shmem_create`),
  the `"Skipping setting up shared memory with cache loader"` string.
  **So the loader validates the exact bytes launchd already mapped - the
  validate/parse race is not available.**
- `PerformAfterUserspaceReboot` (0x10002d244): consulted only when the
  `XPC_USERSPACE_REBOOTED` env flag (0x10004e8b8, `getenv` at 0x100031ed0) is
  set. **Ignored entirely on a cold boot.**
- `PerformInLeanTestEnvironment` (0x10002d290): gated on 0x10004e830 ->
  `"%s not set, Skipping boot-task: %s"`.
- **exit handling** (0x10002d8a0-0x10002dac8), in order:
  1. `WEXITSTATUS == RebootOnExitCode` -> reboot. Key absent ⇒ set to **-1** at
     0x10002d394, and a wait status is 0-255, so it can never match. Safe.
  2. exit **0** + `RebootOnSuccess` -> `"%s: rebooting after success"` -> reboot.
  3. exit **non-zero** (or death by signal - `WIFEXITED` false takes the same
     branch) + no `RequireSuccess` + no `FallbackTask` -> **benign, boot continues**.
  4. exit non-zero + `RequireSuccess=true` -> `"boot task failure: %s - %s"` -> fatal.
  5. program absent -> `"<task>: required|optional boot task not present"`;
     `RequireRun=true` -> fatal; unset -> benign.

So our assumed polarity for `RebootOnSuccess` **was correct** (exit 0 reboots,
non-zero continues silently). It simply never matters.

**Separate landmine worth recording:** `"File Radar to: [ launchd | missing
executable ]. Set boot-arg launchd_missing_exec_no_panic=1 to work around. Job:
'%s' Executable: '%s'"` - launchd **panics** when a cached *job* (not boot task)
has a missing executable. That retroactively explains R37.1's "0 of 183 cached
daemons has a nonexistent Program": it would panic otherwise. **If we ever add a
cache entry, set `launchd_missing_exec_no_panic=1` first.**

### R39.3 *** RETRACTED/REVISED: `rd=md0` sets TWO bytes, and the second one cripples the boot ***

`kern.bootargs` is `strstr`'d in launchd in exactly **three** places, all in one
init function (VERIFIED, full `_strstr` call-site enumeration):

| site | needle | sets |
|---|---|---|
| 0x100031f0c | **`rd=md0`** | 0x10004e8a1 **and** 0x10004e8a2 |
| 0x100031f48 | `-v` | 0x10004e8a4 |
| 0x100031f68 | `-no-corpses` | 0x10004e8bb |

Nothing else in launchd substring-matches boot-args (`launchd_sync_interval=`
and `launchd_missing_exec_no_panic=` go through a proper `name=` parser at
0x100032b98).

```
100031f1c: strb w8, [x9,  #0x8a1]    ; cache-optional
100031f24: strb w8, [x23, #0x8a2]    ; RESTORE ENVIRONMENT
100031f28: bl  _os_variant_is_darwinos
100031f30: cbz w0, 0x100031f38
100031f34: strb wzr, [x23, #0x8a2]   ; cleared ONLY on darwinOS
```

0x10004e8a2 is read by the boot-task runner at 0x10002d2d8:

```
ldrb w8, [0x10004e8a2] ; cset w8, ne ; bic w8, w8, w23   ; w23 = PerformInRestore
tbnz w8, #0, <SKIP TASK>
```

**If 0x8a2 is set, launchd skips every boot task lacking
`PerformInRestore=true`** - on this build that is all of them except
`restore-datapartition`, whose Program is itself dangling. So injecting `rd=md0`
would skip `fsck`, `mount-phase-1`, `mount-phase-2`, `data-protection`, `fips`,
`keybag`, `MSUEarlyBootTask`, `xpcroleaccountd`, `init_featureflags`, `fud`,
`tzinit`, `finish-restore`, `finish-demo-restore`, `sysstatuscheck`,
`prng_seedctl` **and `launchd_cache_loader`**. No `mount -P 1`/`-P 2` ⇒ **no
Data volume, no preboot**; no `keybagd --init`. launchd would still start the 183
cached daemons, into a userspace with no `/private/var`. Not a normal boot.

Whether the gate bites depends entirely on `os_variant_is_darwinos()`, which is
in libSystem inside the 1 GB shared cache and was **not** resolved.
`/System/Library/CoreServices/SystemVersion.plist` on 17M61 says
`ProductName = "Apple TVOS"`, which is not the DarwinOS variant, so the gate is
**expected to bite** - INFERRED, not verified.

**However**, per R38.2 our injected token was stripped before the kernel ever
saw it, so this risk was probably never live on the actual boot. Any future
attempt must use a token whose **name** survives the iBoot filter, e.g.
`serial=3rd=md0`.

### R39.4 *** RETRACTED: the cache-optional flag does NOT scan the drop-in directories ***

The cache-optional byte has exactly **two** code consumers outside `try_mrm` and
logging (full xref enumeration): the getter at 0x10000fc88, called from
0x100020ff4 (the `launchctl` dump text) and **0x10000a8e4**, which is the whole
story:

```
; service lookup request handler
bl   0x10000fc88              ; w0 = (flag == 0) i.e. "must be in cache"
cbz  w0, 0x10000a930          ; flag != 0 -> b 0x10000bcd4  == THE DISK PATH
ldr  x0,[x19,#0x38]           ; else cache-only
bl   0x10000f208              ; path validation
bl   0x10000f260              ; cached-entry classifier
cbz  w0, <return NOT FOUND>   ; cache miss -> give up, never touches disk
```

and 0x10000bcd4 is `xpc_bundle_create(<path>)` dispatched to a global queue - a
**per-path, on-demand** bundle load. Corroboration: launchd's only
`opendir`/`readdir` pair is the `/var/run` cleanup, and its three `fts_open`
sites are the `disabled.migrated` migration plus two unrelated walks. The
`Bootstrap/Paths` array (0x10004e880, from `__config`) is handed to the domain
object at 0x1000228c8 as **search paths**, not a directory to enumerate.

**So "disk will be searched for uncached services" is literal: *uncached*,
*searched*, *on demand*.** Consequences:
- a planted drop-in plist with **`RunAtLoad: true` will NOT fire** - nothing
  enumerates the directory, so the job is never constructed.
- it could only fire via a **`MachServices` name lookup**, for a name that
  something actually looks up on a normal boot **and** is not already in the
  cache - and the cache wins for every real system service.
- `/AppleInternal/Library/LaunchDaemons` is the second search path and
  **`/AppleInternal` does not exist on this build at all** (0 entries).

**Net: lever B does not short-circuit, but it does not scan either. Neither
lever works as designed. R37.2's bypass is mechanically real and strategically
near-worthless on its own.**

### R39.5 Whole-OS boot-args consumer scan (16,802 files, content-level)

Files containing the literal **`rd=md0`**:
`sbin/launchd`, `usr/libexec/PurpleReverseProxy`,
`System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64` (unattributed).

Files reading **`kern.bootargs`**: `usr/lib/dyld`, the shared cache,
`sbin/launchd`, `usr/libexec/keybagd` (boot task `keybag`),
`usr/libexec/cc_fips_test` (boot task `fips`),
`usr/libexec/mobile_obliterator` (boot task `finish-obliteration`),
`usr/libexec/watchdogd`, `usr/libexec/thermalmonitord`,
`usr/libexec/mobileactivationd`, `usr/libexec/NRDUpdated`,
`usr/libexec/PurpleReverseProxy`,
`MobileSoftwareUpdate.framework/Support/softwareupdated`,
`ColourSensorFilterPlugin`.

### R39.6 `/usr/sbin/nvram` exits 1 on BOTH legs (VERIFIED, system_cmds-854.100.3)

Both error strings converge on one helper at 0x100003020:
`mov w0,#1 ; b _errx` - `errx(1, ...)`, prints to stderr, `exit(1)`, no
continuation.
- `"Error setting variable - '%s': %s"` (3 sites) -> `errx(1)`
- `"Error getting variable - '%s': %s"` with
  `mach_error_string(0x0E0002F0 = kIOReturnNotFound)` -> `errx(1)`

For `#!/usr/sbin/nvram nicsfix-sys=ran` ⇒
`argv = [nvram, "nicsfix-sys=ran", "<script path>"]`:
- the `=` arg is processed **first** (set). **If the NVRAM write filter rejects
  the name, `errx(1)` fires immediately and argv[2] is never read - the marker
  is not written.**
- if the set is permitted, argv[2] has no `=` ⇒ get of a nonexistent variable ⇒
  `errx(1)`. Marker written, exit 1.

Either way exit status is **1**. **Consequence: `nvram` can never be the payload
at a `RequireSuccess` exec site**, because it cannot exit 0.

### R39.7 *** OUR EVIDENCE CHANNEL IS UNVERIFIED - this is the critical path ***

**We have never once confirmed a successful write+readback of a CUSTOM NVRAM
variable name on this device.** Every read of `nicsfix-sys`/`nicsfix-mark`
across jobs 599-603 returned `kIOReturnNotFound`, and the **write** side was
never checked. The only names confirmed writable are `root-live-fs` and
`boot-args` - both names Apple's own code already knows.

So every "no marker" result may mean *"that variable can never exist"* rather
than *"our code did not run"*. **Stacked on top of R38.1's wrong-volume
confound, jobs 599-603 carry no information about code execution whatsoever.**

Compounding it, the other candidate channel is also in doubt. Boot tasks get
`/dev/console` as stdio (0x10002d5a0,
`posix_spawn_file_actions_addopen(..., 0, "/dev/console", 0x20000, 0)`) and
launchd logs `"Doing boot task: %s"` per task - but per **R38.3** the system
kernel emitted **zero** UART lines on a normal boot with `-v serial=3` set. If
the `/dev/console` tty shares that gate, there is no channel at all. Untested.

**Job 604 probes the NVRAM half with zero boots and zero volume writes.** Until
it passes, do not design any experiment whose only output is an NVRAM marker.

### R39.8 THE LEADING ROUTE NOW: launchd only checks the processes **it** spawns

The identity check applies to launchd's **direct children**. Anything those
children exec is **unchecked by launchd**. Two boot tasks exec helpers by path:

- **`/sbin/fsck`** (boot task `fsck`, `ProgramArguments: [fsck, -q]`, identity
  `com.apple.fsck` OK). Imports `_fork`, `_execv`, `_waitpid`; builds the helper
  name with the format string **`fsck_%s`**. Helpers are **symlinks on the
  writable System volume**:
  ```
  /sbin/fsck_apfs -> ../System/Library/Filesystems/apfs.fs/fsck_apfs                 (358,560 B)
  /sbin/fsck_hfs  -> /System/Library/Filesystems/hfs.fs/Contents/Resources/fsck_hfs  (256,496 B)
  ```
  Repoint the symlink or replace the target: the exec'd file is launchd's
  **grandchild** - no platform-binary check, no identity check. It must still
  satisfy AMFI to exec, and per our own verified finding a `#!` script with a
  trust-cached interpreter does.
  **Constraints, all real:** `fsck` has **both** `RequireRun` and
  `RequireSuccess`, so the replacement must exist **and exit 0** or the boot
  dies; it runs **before `mount-phase-1`**, so `/private/var` is not mounted and
  `/` is read-only; and it must leave the volumes mountable for the following
  `mount -P 1/2`.
- **`/sbin/mount`** (boot tasks `mount-phase-1`/`-2`, identity `com.apple.mount`
  OK) is richer - `_fork`, `_execv`, `_posix_spawn`, format strings
  `exec: mount_%s`, `%s/mount_%s`, `%s/%s.fs/%s/mount_%s`, plus
  `/sbin/mount_apfs` and `/sbin/mount_hfs` symlinks. Same grandchild property,
  same `RequireRun`+`RequireSuccess` constraint, and breaking a mount is a
  harder failure than breaking `fsck -q`.

**`/sbin/mount` -> `hdik`, the most promising thing in the whole report:**
`"Failed to find executable hdik at location %s"` and `"Encountered ramdisk
definition for location %s - will be created during mount."` - **`/sbin/mount`
execs `hdik` for ramdisk definitions in the filesystem table, with no shebang
and no identity check.** If a ramdisk definition in a file on the writable
System volume makes early-boot `mount` attach an image of ours, that is a direct
line from a file we control to the **in-kernel UDIF parser where our three
defects live** (R-UDIF). Path, parse site, syntax and failure semantics sent back
to the fleet.

**`/usr/local/bin/mount_internal`** is a dangling exec path from `mount`
(`/usr/local` does not exist on this build, 0 entries) but it is **gated**
(VERIFIED 0x100003a84):
```
adr x0,"com.apple.filesystems.apfs" ; bl _os_variant_has_internal_content
cbz w0,<skip>                        ; not internal -> the stat is never reached
adr x0,"/usr/local/bin/mount_internal" ; bl _stat ; cbz w0,<re-exec>
```
Needs `os_variant_has_internal_content()` true. INFERRED to be kernel-pinned
(`kern.osvariant_status`) on a production-fused part and therefore not
flippable - **unresolved**. If it *were* flippable it would also enable
`/AppleInternal/Library/LaunchDaemons` as a search path and
`PerformInLeanTestEnvironment`, so it is worth an hour. launchd calls the same
API for `"com.apple.libxpc.launchd"` at 0x100031ef0, storing to 0x10004e8a3.

**UDIF-as-script note:** the `koly` trailer sits at EOF, so the first 1024 bytes
are free for a shebang and one file can be both a valid script and a valid UDIF
image. But it now wants an **unchecked** exec site (fsck/mount helper), never a
boot-task path.

### R39.9 Revised order of work

1. **Job 604: prove the NVRAM marker channel exists.** No boots, no volume
   writes. Everything else is blocked on this.
2. **Restore to clean 17M61** (R38.5). The live volume is unrecoverable.
3. **Build the primitive at `/sbin/fsck_apfs`** (or its target) - payload must
   exit 0, and we need a trust-cached interpreter that does so when handed one
   arbitrary path as argv[1]. `nvram` cannot (R39.6).
4. **The `/sbin/mount` -> `hdik` ramdisk-definition path**, then the
   UDIF-as-script construction behind that same unchecked exec site.

### R39.10 Rules added

- **Plant NOTHING at any boot-task `Program` path** - identity mismatch is
  `_os_crash` in PID 1 (R39.1).
- **Never use `nvram` as a payload at a `RequireSuccess` exec site** - it always
  exits 1 (R39.6).
- **Set `launchd_missing_exec_no_panic=1` before adding any MRM cache entry.**
- **Do not design an experiment whose only output is an NVRAM marker** until
  job 604 proves custom names are writable (R39.7).

---

## R40 - `/bin/sh` DOES NOT EXIST, and five cached daemons call `system(3)`. Plus three more clean kills.

### R40.1 *** THE BEST PLANTABLE PATH ON THE DEVICE: create `/bin/sh` ***

`/bin` on 17M61 is **`df` and `ps`, full stop**. **`/bin/sh` does not exist.**
And libc's `system(3)` execs `/bin/sh -c <cmd>`.

Daemon-program scan over all 180 distinct cached daemon binaries (in-stream from
the OTA, no disk), checking exec imports then testing every absolute path
literal against the complete file list:

| daemon program | exec import | notable DANGLING path |
|---|---|---|
| `usr/libexec/timed` | **`_system`** | **`/bin/sh`**, `/var/db/timezone/localtime` |
| `usr/libexec/securityd` | `_system` | - |
| `usr/libexec/sharingd` | `_system` | - |
| `usr/libexec/terminusd` | `_system` | - |
| `usr/sbin/bluetoothd` | `_system` | - |
| `usr/sbin/racoon` | `_execve` | **`/etc/racoon/racoon.conf`**, `/etc/motd` |
| `usr/libexec/seputil` | `_posix_spawnp` | **`/bin/bash`**, `/usr/local/bin/kpgo`, `/usr/bin/llvm-cov`, `/usr/bin/llvm-profdata` |
| `usr/libexec/keybagd` | `_posix_spawn` | **`/bin/bash`** |
| `usr/libexec/mobile_obliterator` | `_posix_spawn` | `apfs.fs/hfs_convert` |
| `watchdogd`, `powerd`, `sysdiagnose` | `_posix_spawn` | log/temp dirs only |

Confirmed **absent** on 17M61: `/bin/sh`, `/bin/bash`,
`apfs.fs/hfs_convert`, `/usr/bin/llvm-cov`, `/usr/bin/llvm-profdata`,
`/usr/local/bin/{mount_internal,kpgo}`.

Why `/bin/sh` beats everything else we have found:

1. **`system(3)` execs `/bin/sh -c <cmd>`** - whatever command string the daemon
   passes, **the interpreter is ours**.
2. **No launchd code-signing check applies.** It is a grandchild
   (daemon -> `system()` -> `/bin/sh`). The platform-binary +
   `com.apple.<basename>` identity check (R39.1) lives **only** in the boot-task
   runner at 0x10002d1dc and covers only processes launchd itself spawned.
   Corroboration that this family of paths is live code: launchd's own boot-task
   runner special-cases a 127 exit against the literal `"/bin/bash"` at
   0x10002d83c - Apple's internal builds shelling out.
3. **Daemons run after `mount-phase-2`**, so a writable filesystem exists.
4. **The exit-code constraint vanishes.** Not a `RequireSuccess` boot task - the
   payload may exit any way it likes, crash, or be SIGKILLed, and the boot is
   unaffected. This removes the hardest constraint at the `fsck` site.
5. **Creating it breaks nothing.** `/bin/sh` is absent today, so every `system()`
   call on this device currently **fails**. We are adding a path, not
   overwriting Apple's. Worst case: a previously-failing call now succeeds.
6. Natural long-term persistence target - once anything of ours runs, a real
   `/bin/sh` makes every later step trivial.

**Payload shape.** `argv` will be `["/bin/sh", "-c", "<daemon's command
string>"]`, so the payload must tolerate junk args.
**>>> NEVER plant a COPY of `nvram` at `/bin/sh`: `argv[1]` is literally `-c`,
which is nvram's DELETE-ALL-VARIABLES flag. That would wipe `boot-args` and
`auto-boot`. <<<**
A shebang is safe *and* writes a marker: `/bin/sh` containing
`#!/usr/sbin/nvram nicsfix-sh=ran` gives
`argv = [nvram, "nicsfix-sh=ran", "/bin/sh", "-c", "<cmd>"]`; nvram processes the
`=` arg first (marker written), then `errx(1)`s on `/bin/sh` as an unknown
variable, so `-c` at argv[3] is never reached. **Conditional on nvram parsing
strictly left-to-right rather than sweeping flags in a first pass** - sent to
the fleet to confirm, because if flags are swept first this shape wipes NVRAM.

**Unverified and decisive:** whether any of those five daemons actually
*reaches* its `system()` call on a normal boot. `system()` is often on an error
path. One cheap non-destructive boot settles it.

Fallbacks in order: `/etc/racoon/racoon.conf` (racoon is a cached daemon that
`execve`s, config path dangling, and per R25 `/etc/ppp/options` is live on this
build so this family works), then `/bin/bash` (`keybagd` is **boot task #9**,
i.e. *after* `mount-phase-2` - the earliest writable-filesystem unchecked exec
site in the whole chain, though the `/bin/bash` path there is likely gated
behind internal checks).

### R40.2 *** THE OBSERVABLE PROBLEM: we cannot read the Data volume ***

The fleet's recommended observable was "payload writes under `/private/var`,
read it from the ramdisk". **We cannot do that.** `/private/var` is
`/dev/disk1s2`, the encrypted Data volume, and mounting it **hangs the restore
ramdisk** (standing hard rule). It is encrypted at rest and from the ramdisk we
have no keybag, so even `dd` + grep for a magic string returns ciphertext.

Current state of all three candidate channels:

| channel | status |
|---|---|
| NVRAM custom variable names | **UNVERIFIED** - job 604 probes it, no boots needed |
| `/dev/console` / UART | argued dead (R40.4) |
| Data-volume files | payload can write them, **we cannot read them** |

**So the critical path is unchanged and it is job 604.** If custom NVRAM names
are not writable, we have no observation channel at all and the `/bin/sh` plant,
however good, is unfalsifiable. Open request to the fleet: find ANY writable,
unencrypted, ramdisk-readable location at runtime (is the System volume really
RO in production even when `root-live-fs=1` boots the live filesystem? are
Preboot/Recovery writable and unencrypted?).

### R40.3 Three more clean kills

**(a) `/sbin/mount` -> `hdik` is DEAD, on two independent counts.**

*Count 1 - the ramdisk definition is not in a file.* VERIFIED, `/sbin/mount`
0x1000030a0: the filesystem table is read from
**`IODeviceTree:/filesystems/fstab`** - the I/O Registry device tree, i.e. from
`DeviceTree.b238aap.im4p`, an **Image4-signed boot object**. Not a file on any
volume, not writable on a production-fused part. Strings:
`"failed to get filesystem info"`, `"failed to get filesystem entry count"`,
`"failed to create filesystem entry iterator - %s"`, `"ramdisk"` (the matched
property value, 0x1000070e3, 3 xrefs). A stock HomePod almost certainly has no
fstab node at all, so this code never runs today.

*Count 2 - hdik is never handed an image.* VERIFIED, 0x1000059f0-0x100005a40,
argv is built literally:
```
snprintf(buf, 1024, "ram://%zu", size)
argv = { "/usr/sbin/hdik", "-nomount", buf, NULL }
```
`ram://<size>` is a **blank** RAM-backed device; `mount` then builds a
filesystem on it from scratch (`"Failed to construct the apfs volume on the
ramdisk."`). **No path to an image file is ever passed, so the in-kernel UDIF
parser is never reached.** There is no line from a file we control to the R-UDIF
defects here. (R39.8's "most promising thing in the report" is **withdrawn**.)

**(b) No daemon program resolves through a symlink: 0 of 183.** VERIFIED over
all cached entries, checking every path component for `S_IFLNK`. There are 89
symlinks on the System volume and none lies on any daemon's program path. The
`fsck_apfs` pattern does not repeat.

**(c) The `fsck` site can exec but cannot carry a trace.** `fsck` is boot task
#1 of 17, before `mount-phase-1`: the System volume is mounted read-only and the
Data volume is not mounted until `mount-phase-2` (#6). Writes to the System
volume -> `EROFS`; writes under `/private/var` -> the path does not exist yet.
So nothing both exits 0 **and** leaves an on-disk trace there.
*For the record, the exit-0 half is easy:* `#!/bin/df -h` gives
`argv = [df, "-h", "/sbin/fsck_apfs"]`, `df` is trust-cached, the path argument
always exists (it is the script itself), root is mounted, so it prints and
**exits 0**. Useful only as a **harmlessness control** - proof that planting at
`/sbin/fsck_apfs` does not break the boot. `truncate` cannot be used (`EROFS`),
`nvram` cannot (R39.6).

**One live scrap:** `/sbin/mount`'s helper search list is `/sbin`, `/usr/sbin`,
`/System/Library/Filesystems`, `/Library/Filesystems`, combined as
`%s/mount_%s` and `%s/%s.fs/%s/mount_%s` with `Contents/Resources`.
**`/Library/Filesystems` exists on 17M61 as an empty directory (mode 40775)**,
so `/Library/Filesystems/apfs.fs/Contents/Resources/mount_apfs` is a
**createable** exec path that overwrites nothing. Useless for the boot mounts
(`/sbin/mount_apfs` is earlier in the list and exists, so the search stops), but
keep it for any fstype whose helper is absent.

### R40.4 `/dev/console` is the SAME GATE as kernel printf - so it is dead too

INFERRED (architectural, strong), not verified. On XNU these are not independent
paths: `/dev/console` is not a UART driver, it is the **kernel console exposed
as a tty**. A userspace `write(2)` goes `cnwrite` -> `cnputc` ->
`console_write` (`osfmk/console/serial_console.c`), the **same sink**
`printf`/`kprintf` use. It fans out to the registered console ops, and
`serial_putc` does nothing unless `serial_init()` succeeded. `serial_init()`
runs only when `serialmode & SERIALMODE_OUTPUT`, and `serialmode` comes from
`PE_parse_boot_argn("serial", ...)`. On a production-fused part booting through
unpatched iBoot, `debug_enabled` is false and XNU restricts
`PE_parse_boot_argn` to a short whitelist, so `serial` is never honoured.

**One coherent story for all three observations:** the system kernel emitted zero
lines (R38.3); `serial=3` was inert; and the checkm8-booted restore ramdisk
chatters freely over the same wire with the same kernelcache because there iBoot
**is** patched and `debug_enabled` **is** set.

**Authorized follow-up:** pull `AssetData/boot/kernelcache.release.b238`
(**12.9 MB**, same OTA, not the 1 GB shared cache) and read `serial_init` /
`console_write` / `cnwrite` directly - plus the `PE_parse_boot_argn` whitelist,
which is the actual mechanism behind R38.2's token stripping and tells us what
we can smuggle for the rest of the project.

### R40.5 `serial=3rd=md0` - DO NOT. It is now actively harmful.

The token stripping (R38.2) is also why the `xrd=md0z` boot was harmless: the
token was stripped, byte 0x10004e8a2 was never set, the boot tasks ran, the pod
came up. **That was luck in our favour.**

`serial=3rd=md0` removes the luck. The name `serial` survives the filter, so
`kern.bootargs` would literally contain `rd=md0`, and launchd's `strstr` at
0x100031f0c sets **both** bytes - including the restore-environment byte that
skips every boot task without `PerformInRestore=true`. We would lose `fsck`,
both `mount` phases, `keybag`, `data-protection`, `fips`, `tzinit` and
`launchd_cache_loader`: **no Data volume, no keybag.** And per R39.4 the reward
is only lazy per-path lookups, which a `RunAtLoad` plist cannot trigger.
**Abandoned.**

### R40.6 Standing precondition, restated because it invalidated four jobs

**iOS 13 boots the System volume from a sealed APFS snapshot.** Every
System-volume write made from the ramdisk - a renamed cache, a planted plist, a
repointed symlink, a new `/bin/sh` - is **invisible to the booted OS** unless
that boot uses the live filesystem. Therefore:

- **`root-live-fs=1` must be re-armed from the ramdisk immediately before every
  boot we want to test.** It is one-shot and consumed on boot.
- Or delete the root snapshot so the boot must fall back to live.
- `/private/var` is the Data volume and is **not** snapshotted, so traces there
  survive - but per R40.2 we cannot read them.

### R40.7 Lever status table

| lever | verdict |
|---|---|
| plant at the three dangling boot-task paths | **dead** - platform-binary + identity check, child START_SUSPENDED (R39.1) |
| edit `mrm.plist` | blocked on a trust-cache cdhash; clean once kernel write exists |
| edit a daemon's on-disk plist | dead - cache holds the merged job dict (R37.1) |
| daemon program via symlink | **dead - 0 of 183** (R40.3b) |
| `/sbin/mount` -> `hdik` ramdisk | **dead** - device-tree source, `ram://<size>`, never an image (R40.3a) |
| `/sbin/fsck_apfs` symlink/target | works as an exec site; **cannot carry a trace**; `RequireSuccess` ⇒ must exit 0 (R40.3c) |
| **create `/bin/sh`** | **BEST AVAILABLE** - grandchild, no identity check, post-mount, free exit code, zero regression risk; unverified whether a `system()` call is reached at boot |
| create `/etc/racoon/racoon.conf` | second - racoon is a cached daemon that `execve`s, config path dangling |
| create `/bin/bash` | third - `keybagd` (boot task #9, earliest writable unchecked site), `seputil`; likely internal-gated |
| `/Library/Filesystems/...` | createable but unreachable for apfs; in pocket |

### R40.8 Rules added

- **Never plant a copy of `nvram` at `/bin/sh`** - `argv[1]` is `-c`, which
  deletes every NVRAM variable including `boot-args` and `auto-boot`.
- **Re-arm `root-live-fs=1` from the ramdisk immediately before every test
  boot.** It is one-shot. A test boot without it proves nothing.
- `/Library/Filesystems` exists and is writable; `/usr/local`, `/AppleInternal`
  and `/bin/sh` do not exist at all.

---

## R41 - THE BOOT ROOT IS OURS TO CHOOSE. And NVRAM `boot-args` has been inert this whole time.

Source: full disassembly of **`/home/claude/kc/kernel.macho`** (apfs kext
**apfs-1412.140.3**) and of the matching decrypted production bootloader
**`/home/claude/ib5/iBoot.dec` = iBoot-5540.140.12 "iBootStage2 for b238a",
base 0x830000000**, with ready-made disasm/decomp at
`/home/claude/hunt/dis/iBoot-5540.{dis,decomp.c,strxref.tsv,funcs.tsv}`.
Legend: **[V]** instructions read, **[I]** inference on top of [V], **[U]** undetermined.

### R41.1 *** NO APFS SEALING ON THIS BUILD - our System-volume writes are legitimate *** [V]

apfs-1412.140.3 contains **zero** occurrences of `integrity_meta`, `sealed`,
`root hash`, `APFS_TYPE_INTEGRITY`, `integrity-meta` or `ROOT_HASH`. **There is
no sealed-volume support at all.** SSV arrives in apfs-1677 / iOS 14.

This was the single most load-bearing unverified assumption in the project and
it holds: a file written to the System volume from the restore ramdisk is
accepted by a subsequent normal signed boot. (A second agent is corroborating
independently.)

### R41.2 How the boot root is actually chosen (both stages) [V]

Containing function **`apfs_vfsop_mount` @ 0xfffffff0084c2750**
(`__func__` string at 0xfffffff007401bb8). Precedence as the code runs:

```
0xfffffff0084c390c  bl  0xfffffff00849839c   ; should_root_live_fs()  (NVRAM root-live-fs)
0xfffffff0084c3910  tbz w0,#0, 0xfffffff0084c3b38   ; not live -> snapshot selection
0xfffffff0084c3914  mov x23,#0               ; live: snap xid = 0
; ---- snapshot selection ----
0xfffffff0084c3b3c  ldr x8,[x8,#0xd0]        ; -> on-disk apfs_superblock_t
0xfffffff0084c3b40  ldr x23,[x8,#0x3c8]      ; apfs_root_to_xid
0xfffffff0084c3b44  cbnz x23, 0xfffffff0084c3d80  ; nonzero -> USE THAT XID DIRECTLY
0xfffffff0084c3b58  bl  0xfffffff008498438    ; get_boot_manifest_hash()
0xfffffff0084c3b64  add x0,x0,#0x9b           ; "com.apple.os.update-"
0xfffffff0084c3bc8  add x12,x12,#0x3f0        ; "0123456789ABCDEF"  <- UPPERCASE
0xfffffff0084c3c1c  bl  0xfffffff0084804e4    ; apfs_snap_lookup_by_name(exact)
0xfffffff0084c3d6c  ldr x23,[x1,#0x10]        ; x23 = snapshot XID
```

**The snapshot name is `com.apple.os.update-` + UPPERCASE hex of the device-tree
`/chosen` property `boot-manifest-hash`.** The getter at 0xfffffff008498438 uses
the same IORegistry helper as `root-live-fs` (0xfffffff0084982a4) but with
`"/chosen"` (0xfffffff00726b3e4) + `"boot-manifest-hash"` (0xfffffff00729 1e0e)
instead of `"/options"` + `"root-live-fs"`.

**`boot-manifest-hash` = SHA1(APTicket), hardware-latched** [V]: iBoot publishes
it in `UpdateDeviceTree` (FUN_83000a7d0) at 0x83000ac74-0x83000ac8c from
FUN_83000d9ec, into a **20-byte** buffer. FUN_83000d9ec computes nothing - it
copies 5 words from **SoC sticky registers 0x20E029040..0x20E029053**, gated on
bit 4 of 0x20E029000 (setter FUN_83000da6c, used by the earlier stage). Proof it
is SHA1 of the IM4M: iBoot's own cross-check in the `upgrade` path
(FUN_830003d08) loads `/boot/apticket.der`, pulls the `IM4M` (0x494d344d), takes
a **0x14-byte** digest and compares, printing *"failed to verify boot manifest
hash"* on mismatch.

**Lookup is an EXACT-NAME B-tree lookup - no enumeration, no prefix match, so no
tie-break question exists** [V]. 0xfffffff0084804e4: key type **0xb =
APFS_TYPE_SNAP_NAME**, name len <= 0x100 else ENAMETOOLONG, snap-meta tree at
`[x20+0x108]`, `btree_lookup` mode 3. iBoot does the identical thing in
FUN_830015798 (`*key = 0xbfffffffffffffff`).

### R41.3 *** THE CRUX: nothing authenticates the snapshot's identity or contents *** [V]

The resolved XID goes to **`apfs_mount_snapshot` @ 0xfffffff0084c63ec**
(`__func__ = "handle_snapshot_mount"`). On a root mount the user mount-args
pointer is NULL and the whole 0x11c-byte struct is memset to 0
(0xfffffff0084c2814-0xfffffff0084c2824), so the name is `""`, and:

```
0xfffffff0084c64ac  cbz  x23, 0xfffffff0084c6518   ; no name
0xfffffff0084c64b4  cbz  w8,  0xfffffff0084c6518   ; empty name
0xfffffff0084c6524  bl   0xfffffff008480614        ; lookup BY XID
```

**The boot root is selected purely by XID.** The only strings referenced in
0xfffffff0084c63ec..0xfffffff0084c68b0 are `"handle_snapshot_mount"` and
`"%s%s%s"` - no hash, no manifest, no integrity check.

**So: delete Apple's snapshot, create our own named
`com.apple.os.update-<40 uppercase hex of SHA1(APTicket)>`, and the kernel
mounts ours.** Only the *name string* is tied to the ticket, and we can compute
that name ourselves because we hold the APTicket we restored with. And
`apfs_root_to_xid` skips even that.

**A failed name lookup FALLS BACK TO THE LIVE VOLUME in both stages** [V]:
kernel 0xfffffff0084c3d48 -> 0xfffffff0084c3d80 leaves `w25 == 0`, and
0xfffffff0084c364c `cbz w25` is the live-mount branch. iBoot's FUN_830015798
leaves `*snap_xid` at its pre-initialised `sb[0x14]` (= `apfs_revert_to_xid`,
normally 0).

### R41.4 *** `apfs_root_to_xid` is an ON-DISK SUPERBLOCK FIELD, sticky and persistent *** [V]

**Not NVRAM, not a boot-arg.** It is `apfs_superblock_t + 0x3C8`, a bare
little-endian `uint64 xid_t`. `0` = root to live FS; nonzero = root to that
snapshot xid, **taken at face value with no name check and no bounds check at
mount time**.

- Read site: 0xfffffff0084c3b38-0xfffffff0084c3b44 (`[mount+0xd0]` -> superblock).
- Write site: `handle_root_to_snapshot`, 0xfffffff0084c5d98 `str x22,[x8,#0x3c8]`,
  guarded only at set time by 0xfffffff0084c5d34 (`<= apfs_revert_to_xid`, string
  *"can't set apfs_root_to_xid to xid (%llu) > apfs_revert_to_xid (%llu)"*).
  Log strings: *"SET root_to_xid - on next boot, volume will root to snapshot
  \"%s\" w/snap xid %lld"* and *"UNSET root_to_xid - on next boot, volume will
  root to live file system"*. Sibling `handle_revert_to_snapshot` writes
  `apfs_revert_to_xid`/`apfs_revert_to_sblock_oid` at +0xa0/+0xa8
  (0xfffffff0084c5ce0) - **that is the `snaputil -r` mechanism that destroyed
  our live volume (R38.1)**.
- **It is NOT consumed or cleared at mount** - the mount path only loads it,
  there is no store anywhere in `apfs_vfsop_mount`. Unlike `root-live-fs`, this
  is a persistent boot-root override that also survives an NVRAM wipe.

Offset confirmation, four independent matches [V]: +0xa0/+0xa8 revert pair;
+0x3C8 root_to_xid; iBoot's `sb[0x79]` == 0x3C8; iBoot's `sb+0x58*8` == 0x2C0 =
`apfs_volname`; `sb[7]` == 0x38 = `apfs_incompatible_features`; `sb[0x21]&1` ==
0x108 = `apfs_fs_flags` (`APFS_FS_UNENCRYPTED`, required by iBoot).

Setting it: on-device via `handle_root_to_snapshot` (the APFS side of the
`fs_snapshot` root op; `fs_snapshot` is present at file off 2441175 - **the
entitlement requirement is [U]**), or offline by writing 8 bytes at +0x3C8 and
recomputing the object's fletcher64 at offset 0 of the block [I].

### R41.5 *** NVRAM `boot-args` IS INERT ON THIS iBOOT. It never reaches the kernel. *** [V]

This is the big correction, and it retroactively explains several results.

All 29 env-getter call sites in iBoot-5540.140.12 were enumerated and the name
argument recovered at each. **The complete set of NVRAM variables this iBoot
reads is:**

```
tc-path, boot-device, dt-path, sepfw-path, boot-ramdisk, boot-path,
one-time-boot-command, boot-command, upgrade-fallback-boot-command,
gateway, ethaddr, network-type, recovery-boot-args, cmd-results,
com.apple.System.boot-nonce      + root-live-fs (uint getter in FUN_830015270)
```

**`boot-args` is not in that list.** Its only two appearances in the whole image
are a length check in the NVRAM *setter* (FUN_83002213c truncates `boot-args`
values over 0x25f) and a pointer in a static name list.

`boot_args.CommandLine` is at **0x8300aad9c** (struct base 0x8300aad30, +0x6c,
size 0x260) and has exactly **six** writes, all in FUN_83000b8c4:
1. 0x83000bff8 `snprintf(CommandLine,0x260,"%s",x21)` where x21 is **`""`** (no
   ramdisk) or `csel` of **`"rd=md0 -progress -restore"` / `"rd=md0 -restore"`**
   (ramdisk loaded, `[0x8300b1288] != 0`).
2. 0x83000c0bc re-render as `"%s backlight-level=%d"`.
3. 0x83000c0d4 `env_get("recovery-boot-args")`; appended **only if**
   FUN_83000ffec() (bit 22 of the word at 0x8300ab554) is set - and that bit is
   set only by FUN_83000ffd0(1), called from 0x8300041c8 and 0x830004410, both
   **recovery-mode entry** paths.
4. 0x83000c1b0/0x83000c1d4 are *reads* only (`-s`, `-v`, `debug=`).

**Consequences:**
- **`-v serial=3` was never doing anything on a normal boot.** R38.3's silent
  UART is fully explained, and R40.4's `/dev/console` architecture argument,
  while probably right, was not even needed.
- **The entire `strstr`/`xrd=md0z`/`serial=3rd=md0` family is dead at the
  source** - we can never inject into `kern.bootargs` on a normal boot. R37.2,
  R38.2 and R40.5 are superseded: the bypass was never reachable.
- **`recovery-boot-args` is the one variable that reaches `kern.bootargs`**, and
  only in recovery mode. Unexplored.
- iBoot itself legitimately sets `rd=md0 ... -restore` when a ramdisk is loaded,
  which is why launchd's restore-environment byte is set in the SU ramdisk.
- **R38.2's "iBoot strips unrecognised tokens" is WITHDRAWN.** There is no
  per-token sanitizer in either iBoot-5540.140.12 or the kernelcache. The
  kernel's `"boot-args"` string (0xfffffff00726be3c) has exactly 4 xrefs: two in
  IODTNVRAM init/limit (0xfffffff007bd5778, 0xfffffff007bd57ac - if absent,
  `setProperty("boot-args","")`), one length reject at 0xfffffff007bd779c
  (> 0x25f), one `strcmp` in the **Sandbox** kext property-write policy
  (0xfffffff007fa98e8). **What actually deleted `xrd=md0z` is [U]** - most
  likely a userspace rewrite of the whole variable on first boot [I], unproven.

### R41.6 iBoot's two NVRAM name lists [V]

Used by FUN_830002a54 (A) and FUN_830002aa4 (B):
- **List A** @ 0x8300404f8, 4 entries, the `cmd-results` echo gate
  (FUN_83002274c): `auto-boot, boot-args, debug-uarts, pwr-path`.
- **List B** @ 0x830040520, 20 entries - **the allowlist of variables an
  untrusted writer (the OS-written NVRAM blob) may set over an iBoot default**:
  `auto-boot, backlight-level, boot-command, com.apple.System.boot-nonce,
  ramrod-kickstart-aces, debug-uarts, device-material, display-rotation,
  display-vsh-comp, idle-off, is-tethered, darkboot, ota-breadcrumbs,
  boot-breadcrumbs, recovery-breadcrumbs, com.apple.System.tz0-size,
  com.apple.System.rtc-offset, pwr-path, upgrade-retry,
  upgrade-fallback-boot-command`.

Mechanism (FUN_83002213c + blob parser near 0x8300225d4): blob entries get
`flags = 3` if the name is **not** in list B, else `flags = 1`; a set with bit 1
is **rejected** if a node for that name already exists without bit 1 (an iBoot
default). Name field 0x40 bytes, value 0x261.

Practical upshot: **`boot-path`, `tc-path`, `dt-path`, `sepfw-path` have iBoot
defaults and are NOT overridable from NVRAM**; `boot-command` and
`upgrade-fallback-boot-command` **ARE**; `root-live-fs` and `boot-args` have no
default so they are accepted into the environment.

### R41.7 What iBoot loads out of the root we selected [V]

Defaults set in FUN_8300038c0; `boot-command` default = `fsboot`:

```
boot-path   = /System/Library/Caches/com.apple.kernelcaches/kernelcache
tc-path     = /usr/standalone/firmware/FUD/StaticTrustCache.img4
dt-path, sepfw-path
```

**iBoot reads these out of whatever root we selected and verifies them as IMG4
against the APTicket whose SHA-1 is latched in 0x20E029040.** So the filesystem
is ours to shape, but the kernelcache and the static trust cache are **not**
swappable along this path, and AMFI still gates userspace execution. The boot-
root options buy **arbitrary file content in the booted System volume state** -
the code-execution primitive must still come from elsewhere (i.e. R40.1's
`/bin/sh`).

### R41.8 NEW LEAD: `boot-command` is OS-settable AND read by iBoot [U]

`boot-command` and `upgrade-fallback-boot-command` are in list B (so the OS, and
therefore we, can set them) **and** are read by iBoot (FUN_830003d08,
0x830012e38), while `boot-path` is not settable. Default is `fsboot`. **Whether
the production command interpreter will act on an arbitrary `boot-command` is
unchecked** and is now the hottest open question on the iBoot side.

### R41.9 Ranked boot-root levers (revised)

| # | lever | verdict |
|---|---|---|
| **1** | **set `apfs_root_to_xid` to a snapshot of our modified live volume** | **most reliable.** Beats the name lookup in precedence, so no SHA1(APTicket) needed and Apple's snapshot stays intact. Persistent, never cleared at mount, survives an NVRAM wipe. Honoured identically by iBoot (`sb[0x79]`) and the kernel. Cost: root is a read-only snapshot, so each content change needs a new snapshot + xid write. Best for pinning one durable state. |
| 2 | plant into live + **delete Apple's `com.apple.os.update-*` snapshot** | best for **iterative** work - fall-back-to-live is verified in both stages, no NVRAM dependency, and every later live edit is picked up with no further action. Risks: destructive and noisy (`softwareupdated`/OTA expects that snapshot and an update recreates and re-pins it), and we lose our known-good fallback. |
| 3 | plant into live + `root-live-fs=1` | simplest, least durable. Honoured by both stages; iBoot accepts it from the NVRAM blob (no iBoot default node, so the list-B rejection does not fire). But it is one-shot per our device evidence, and **no code in either iBoot or the kernel clears it** - both xrefs are reads - so the clearing mechanism is **[U]** and cannot be relied on. Use as the cheap reversible first experiment; do not build on it. |
| 4 | create a matching-name snapshot + delete Apple's | works but strictly dominated by #1. |

### R41.10 Rules added

- **`snaputil -r` writes `apfs_revert_to_xid` at superblock +0xa0/+0xa8.** That
  is the on-disk field behind the volume destruction in R38.1. Never use it.
- **Never plan anything around NVRAM `boot-args` on a normal boot** - this iBoot
  does not read it. `recovery-boot-args` (recovery mode only) is the only
  channel to `kern.bootargs`.
- `boot-path`, `tc-path`, `dt-path`, `sepfw-path` cannot be overridden from
  NVRAM; `boot-command` and `upgrade-fallback-boot-command` can.

---

## R42 - THE BOOTSTRAP IS COMPLETE. Two files on the System volume, no prior code execution.

### R42.1 The chain

```
/System/Library/LaunchDaemons/com.apple.jetsamproperties.B238a.plist   <- we edit
      (one of only 2 of the 185 daemon plists that are NOT in the signed MRM
       cache; launchd hardcodes the com.apple.jetsamproperties prefix + board
       name and parses it UNSIGNED off the System volume on EVERY boot)
   -> Version4/Daemon/Override/<victim label>/ActiveSoftMemoryLimit = 1
   -> victim daemon instantly breaches its jetsam SOFT limit
   -> kernel raises a NON-FATAL EXC_RESOURCE / RESOURCE_TYPE_MEMORY
   -> ReportCrash (root, the registered Mach ExceptionServer) handles it
   -> -[CrashReport captureDiagInfo:] -> runDiagTool @0xfffffff... 0x10000d460
   -> popen(cmd,"r") @0x10000d5a8
   -> popen(3) ALWAYS execs /bin/sh -c <cmd>
/bin/sh                                                                 <- we create
   -> OUR CODE, AS ROOT, grandchild of launchd
```

**Both inputs are files on the writable System volume. No exploit, no prior code
execution, no signature forged.** This is a bootstrap, not a second-stage tool.

### R42.2 ReportCrash gate conditions (VERIFIED, instruction level)

```
0x1000031f8  cmp w9, #0xb        ; EXC_RESOURCE (11)          HARD REQUIREMENT
0x100003200  and x9, x8, #0xe000000000000000
0x100003204  mov x10, #0x6000000000000000
0x100003208  cmp x9, x10         ; code>>61 == 3 = RESOURCE_TYPE_MEMORY  HARD
0x10000321c  cbz w9, skip        ; third ivar (@0x10001e42c) non-zero  UNIDENTIFIED
0x100003258  @"/usr/bin/vmmap"   0x100003264 @"/usr/bin/heap"
0x1000032ac  bl objc_msgSend     ; -[x19 captureDiagInfo:]    SEND SITE 1
```

- `ReportCrash` job: `MachServices = { com.apple.ReportCrash: { ExceptionServer: {} } }`,
  **no `UserName` key, so it runs as ROOT**.
- `disableDiagInfo` comes from **`_OSAGetDATaskingValue`** (server-pushed DA
  tasking, NOT a local plist). Absent -> nil -> boolValue 0 -> **not disabled**.
  The feature is ON by default; only a tasking payload turns it off. **Polarity
  is in our favour.**
- `ExcDiagToolTimeout` / `ExcDiagToolExtras`, domain **`com.apple.CrashReporter`**,
  are optional. `ExcDiagToolExtras` sets the tool list, i.e. we can choose the
  command string if we want - but we do not need to, because our `/bin/sh`
  ignores `-c` entirely.
- **No feature-flag gate** (`FeatureFlags/Domain/OSAnalytics.plist` holds only
  `JSONCrashLogs` and `denyLegacyCrashLogs`, both `Enabled: False`).
- **No internal-build gate found** on this path, though `InternalBuild`,
  `appleInternal`, `_AppAnalyticsEnabled` all exist in the binary.
- `/usr/bin/{vmmap,heap,leaks,malloc_history}` are **all absent** - irrelevant,
  because `popen` execs the shell *before* the shell looks for the tool.

An ordinary crash (`EXC_CRASH` 10, `EXC_BAD_ACCESS` 1) does **NOT** reach this.
It must be a **soft** jetsam limit breach: soft -> EXC_RESOURCE and the process
lives; hard -> it is killed.

### R42.3 The jetsam plists (the trigger we control)

`com.apple.jetsamproperties.B238.plist` / `...B238a.plist`. **Our board is
b238aAP, so B238a is the live one.** `Version4` dict keys include:

```
ActiveSoftMemoryLimit   InactiveSoftMemoryLimit   ActiveHardMemoryLimit
InactiveHardMemoryLimit KernelHighWaterMark       JetsamPriority
UserReclaimableLimit    EnablePressuredExit       ExecuteAllowed   ThreadLimit
```

with per-label `Override` dicts under `Daemon`, `App`, `SystemApp`,
`XPCService`, `SystemXPCService`, `Extension`, `System`. Apple's own examples:

```
Version4/SystemXPCService/Override/com.apple.AXMediaUtilitiesService/ActiveSoftMemoryLimit = 60
Version4/SystemXPCService/Override/com.apple.accounts.dom/ActiveSoftMemoryLimit            = 20
```

Victim choice: a `RunAtLoad`+`KeepAlive` daemon whose death is harmless.
`com.apple.sharingd` and `com.apple.bluetoothd` both qualify (user `mobile`);
a **soft** limit should not kill them at all. **Avoid anything with
`_PanicOnCrash`.** Apple's shipped file already contains entries for
`com.dropbear.sshd` / `com.dropbear.sshd2` (an Apple-internal leftover), which
usefully shows the file tolerates labels with no corresponding job.

### R42.4 *** CORRECTION: only TWO binaries import `_system`, and NEITHER is root ***

VERIFIED by full `LC_SYMTAB` nlist parse of all **574** System-volume Mach-Os
(387 MH_EXECUTE, 169 MH_BUNDLE, 16 MH_DYLIB, 1 kext, 1 dyld):

| binary | user |
|---|---|
| `/usr/libexec/timed` | **`_timed`** |
| `/usr/libexec/terminusd` | **`mobile`** |

`securityd`, `sharingd` and `bluetoothd` do **not** import `_system` - those were
substring false positives (`_sqlite3_exec`, `_sqlite3_system_errno`,
`_ccrng_system_init`, `_container_system_group_path_for_identifier`). **R40.1's
five-daemon table is superseded twice over.** And since neither real importer is
root, an `nvram` write from a `/bin/sh` exec'd by either would have failed anyway.

**Root `UserName` distribution across the 183 cached jobs:** `mobile` 103,
**unset (= root) 67**, `_securityd` 3, `_networkd` 2, and one each of
`_wireless, _analyticsd, nobody, _mdnsresponder, _reportmemoryexception,
_distnote, _timed, _installd`. All 20 boot tasks are root.

### R42.5 THE OTHER ROOT `/bin/sh` CONSUMER: `wifivelocityd`

`/usr/libexec/wifivelocityd`, **`UserName` unset = root**. Two call sites, both
fully reconstructed:

- `-[W5WiFiPerfLoggingManager __setupWatchdogTask]` - dispatch 0x10000e3b8, `@"/bin/sh"` at 0x10000e3a4
- `-[W5WiFiSniffManager __setupWatchdogTask]` - dispatch 0x10005bd70, `@"/bin/sh"` at 0x10005bd5c

```objc
cmd = [NSString stringWithFormat:@"CHILDPIDS=%@; while kill -0 %d; do sleep 10; done; ..."];
[self runTaskWithLaunchPath:@"/bin/sh" arguments:@[@"-c", cmd] ...];
```

An `NSTask` child, so a grandchild of launchd - no identity check. Reachability
on an unattended boot is UNVERIFIED (`LaunchEvents` are notifyd matches on
`com.apple.wifivelocity-wake-120/240/600/86400`).

### R42.6 Only 10 root binaries import ANY exec-family symbol (VERIFIED)

`/sbin/mount` (boot task x2, every boot), `/sbin/fsck` (boot task x2),
`/usr/libexec/keybagd`, `/usr/libexec/mobile_obliterator`,
`/System/Library/CoreServices/ReportCrash` (**the only root binary on the whole
volume importing `popen` or `system`**), `powerd`, `/usr/libexec/watchdogd`,
`/usr/bin/sysdiagnose`, `/usr/libexec/seputil`, `/usr/sbin/racoon`.

**`/usr/local/bin/mount_internal`** - `/sbin/mount` main, 0x100003a84:
```c
if (os_variant_has_internal_content("com.apple.filesystems.apfs"))
    if (stat("/usr/local/bin/mount_internal", &st) == 0) execv(...);  // argv: ["...","mount","-P","1"]
```
`/usr/local` does not exist (0 of 16,802 paths) - fully creatable, root, EVERY
boot, no identity check. **Gate `os_variant_has_internal_content` is UNVERIFIED**
(lives in the shared cache). **>>> DANGER: `mount-phase-1` is `RequireSuccess`.
A payload planted there that exits non-zero KILLS THE BOOT, because `execv`
REPLACES mount. Do not plant an exiting payload at this path. <<<**

`/AppleInternal` (absent, one `mkdir`) is a **shared pivot** that would
simultaneously affect `mount_internal`, launchd's second bootstrap path
`/AppleInternal/Library/LaunchDaemons`, wifivelocityd's profile paths,
`lockdownd`'s `.hactivateoff`, and `sysdiagnose`. Untested; it also risks
changing boot behaviour, so it gets its own job, never bundled with another test.

### R42.7 Corrections to earlier sections

- **R25 is INVERTED. `/etc/ppp/options` is NOT present on this build** - there is
  no `private/etc/ppp` directory at all. Conversely **`/etc/racoon/racoon.conf`
  IS present** (3,639 B), not dangling. `/private/etc` holds exactly 18 files.
- **`/sbin/mount` and `/sbin/fsck` do NOT read `/etc/fstab`** - literal
  `etc/fstab` occurs **0** times in either binary; both read
  `IODeviceTree:/filesystems/fstab`. Any plan built on adding an fstab line is
  dead. (Confirms R40.3a from a second direction.)
- **"launchd only checks boot tasks" is too strong.** launchd also carries
  `"unexpected exec of non-platform binary: %s: %s [%d]"` and
  `"%s: bad code signature"`, which are **not** boot-task-scoped. This does not
  threaten the grandchild thesis (all our sites are grandchildren) nor shebang
  payloads (after exec the process carries the *interpreter's* signature, so it
  is a platform binary), but do not rely on the stronger claim.
- **The OTA file list is the System volume only.** It has no `/private/var`, so
  thousands of apparent "dangling" `/var/...` and `/Library/Preferences/...`
  hits are **not** dangling - they live on the Data volume. `/etc` IS on the
  System volume (`/etc -> private/etc`).
- `filelist.txt.gz` is a **multi-member gzip**; Python's `gzip` truncates it at
  3,870 lines, `gzip -dc` reads all 16,802. Any earlier scan using the Python
  module under-reports.

### R42.8 Other root-parses-our-file targets (parser-bug surface)

- **`/System/Library/FeatureFlags/Domain/*.plist`** - 16 plists on the writable
  System volume, parsed by **`/usr/libexec/init_featureflags`, a root BOOT
  TASK**. `{Global,Profiles,Settings}.plist` do not exist and are creatable.
  **Best parser target found.**
- **`/System/Library/LocationBundles/{AppleWatchFaces,AppleWatchWorkout,
  LocationPerformance,RemindersAlerts,Routine,Wea}.bundle`** - six named,
  missing bundle paths scanned by **root `locationd`** (RunAtLoad+KeepAlive).
  Code inside stays AMFI-blocked; the `Info.plist` parse does not.
- **`/Library/UserEventPlugins`** - creatable, scanned by root `UserEventAgent`
  (KeepAlive).
- `/private/etc/racoon/*` - richest hand-rolled parser in `/etc` (yacc/lex
  grammar), but racoon is `RunAtLoad=false`, socket-activated.
- `/System/Library/Obliteration/GlobalPreferences.plist` -> root
  `mobile_obliterator`.

### R42.9 Dangling dylib/framework paths are a DEAD CATEGORY

5,812 apparent "missing `LC_LOAD_DYLIB`" hits are **essentially all false
positives**: on audioOS 13 every framework lives inside
`dyld_shared_cache_arm64` and is not a file on disk (only 60 `.dylib` files and
16 `MH_DYLIB` Mach-Os exist on the whole volume). Creating a file at a cached
dylib's path does **not** get it loaded - dyld resolves against the cache first.
Doubly blocked, by that and by AMFI's `mpo_file_check_mmap`. Only the data-only
sub-case (R42.8's bundle `Info.plist` parses) is live.

### R42.10 Rules added

- **Never plant an exiting payload at `/usr/local/bin/mount_internal`** -
  `execv` replaces `mount`, and `mount-phase-1` is `RequireSuccess`.
- `/AppleInternal` gets its own job, never bundled with another test.
- Pick jetsam victims with no `_PanicOnCrash`; use **soft** limits only.
- Use `gzip -dc`, never Python's `gzip` module, on `filelist.txt.gz`.

---

## R43 - Two NEW UDIF kernel bugs, an arbitrary-heap-write primitive, and APFS comes back hardened

### R43.1 *** NEW BUG: a SECOND `compressedLength` underflow, in the LZFSE branch *** [V]

R-UDIF defect 2 was the zlib branch (chunk type `0x80000005`) at
`0xfffffff007dcb684`. The **LZFSE branch (type `0x80000007`) carries the
identical defect at a different address, against a different allocation**:

```
0xfffffff007dcb630  ldr  x8,[x24,#0xb0]     ; this->chunkTable
0xfffffff007dcb634  ldr  w8,[x8,#0x20]      ; decompressBufferRequested  <- DISK FIELD
0xfffffff007dcb638  lsl  w26,w8,#9          ; bufSize = field * 512
0xfffffff007dcb644  cmp  x20,x26            ; x20 = DEcompressed size only
0xfffffff007dcb648  b.ls 0xfffffff007dcb734 ;   compressedLength NEVER compared
0xfffffff007dcb73c  bl   0xfffffff007b7bdf0 ; IOMalloc(bufSize)
0xfffffff007dcb74c  bl   0xfffffff007c40700 ; bzero(buf,bufSize)
0xfffffff007dcb754  bl   0xfffffff007b7bdf0 ; IOMalloc(scratch)   <- 2nd alloc, 2nd grooming knob
0xfffffff007dcb764  add  x8,x8,x26          ; x8 = buf + bufSize (buffer END)
0xfffffff007dcb768  ldp  x2,x1,[sp,#0x58]   ; x2 = compressedLength, x1 = compressedOffset
0xfffffff007dcb76c  sub  x4,x8,x2           ; *** dest = bufEnd - compressedLength ***
0xfffffff007dcb788  blr  x8                 ; backingStore->read(off,len,&actual,dest)
```

`x2` comes from the chunk lookup at `0xfffffff007dcc2ec`, straight from the
merged chunk table, which `merge_blkx` copied verbatim from the on-disk
`BLKXRun` at `run+0x20`. Nothing on the path compares it to `bufSize` or to
`sectorCount<<9`.

### R43.2 *** THE LEVER: we choose the allocation size too *** [V]

`bufSize` comes from `table+0x20`, set by `merge_blkx` at
`0xfffffff007dcbfd8` to the `max()` over every `blkx` table of the **big-endian
u32 at `blkx+0x20` = `decompressBufferRequested`** (`0xfffffff007dcc014`:
`ldr w8,[x22,#0x20]; rev w8; csel w9,w8,w9,lo`). The only bound is
`0xfffffff007dcc194`: `cmp w8,#0x400,lsl #12` -> <= `0x400000` **sectors**, so
bufSize ranges over [0, 0x8000_0000] in 512-byte steps. The allocator is
IOMalloc/IOFree (`0xfffffff007b7bdf0` -> `kalloc_ext` `0xfffffff007684e84`),
so **we pick the kalloc zone.**

**Net primitive, entirely from file contents:**

| we control | field |
|---|---|
| target allocation size | `decompressBufferRequested * 512`, 512-byte granularity |
| write start | `allocation_end - compressedLength`, arbitrary negative displacement |
| write length | `compressedLength`, a 64-bit field |
| write contents | raw bytes at `compressedOffset` in our file, byte-exact |

Both chunk table and buffers are kalloc heap, so **KPP is irrelevant** (it hashes
only `__TEXT` and `__DATA::__const`). Assessed **exploitable**, and the strongest
thing found in the whole audit.
Unverified caveat: whether `KDIFileBackingStore`'s read at `[bs_vtable+0x590]`
clamps a length past EOF - make the file large and the question does not arise.

### R43.3 *** NEW BUG: the chunk lookup is an unbounded, unindexed search *** [V]

`0xfffffff007dcc268`, reached via `blr [x24+0x5c8]` at `0xfffffff007dcb4dc`:

```
0xfffffff007dcc270  ldr w10,[x8,#0xc8]   ; nChunks
0xfffffff007dcc274  lsr w10,w10,#1       ; step = nChunks/2
0xfffffff007dcc278  add x8,x8,#0xcc      ; cur = &chunks[0]
 loop:  ldr x12,[x8,#8] / ldr x13,[x8,#0x10]
        madd x8,x12,x11,x8               ; cur += +-step * 0x28
        lsr  w10,w10,w12                 ; step floors at 1
        b    loop                        ; NO iteration cap, NO bound on x8
```

Termination needs an entry with `start <= req < start+count`. The sorted,
gapless invariant it relies on is **broken by `merge_blkx` itself**: at
`0xfffffff007dcc118` it advances the expected-sector cursor by `sectorCount`
instead of setting it to `abs_start + sectorCount`, so gaps *between runs inside
one blkx* are never filled and the cursor falls permanently behind. The trailing
ZERO fill at `0xfffffff007dcc1a4` then emits an entry starting at the stale
cursor **after** a higher-starting entry - a genuinely **non-monotonic table**.

Two outcomes, both from file contents alone:
- **non-monotonic** -> the search oscillates between two indices forever: an
  unkillable in-kernel loop (watchdog panic). Worked example:
  `firstSectorNumber=0`, runs `{RAW,0,1}` and `{RAW,100,1}` -> table
  `[{0,1},{100,1},{2,N-2},{N,0}]`; a read of sector 1 ping-pongs 0<->1.
- **monotone-but-offset** -> every step is -1 and it **walks backward out of the
  IOMalloc'd table**, reading `[x8+8]`/`[x8+0x10]` from neighbouring heap
  objects until a pair satisfies containment. On "success" it returns `type`,
  `sectorCount`, `compOffset` and `compLength` **read out of bounds** and feeds
  them directly into the R43.1 write primitive.

Also `0xfffffff007dcc2d4`: the returned count is `next->sectorStart -
cur->sectorStart`, **not** `cur->sectorCount`. On a non-monotonic table that can
be **negative**, and it propagates through a **signed** `csel` at
`0xfffffff007dcb4f0` to `lsl x2,x11,#9` at `0xfffffff007dcb534` on the RAW path -
a negative-turned-enormous length handed to the backing-store read with the
*caller's* buffer as destination. The compressed branches reject it (`b.ls`
unsigned at `0xfffffff007dcb648`); **the RAW branch does not.** Whether the
backing store clamps it is UNVERIFIED - worth one test, because if not it is a
second write primitive.

### R43.4 The three known defects re-confirmed, with two corrections

- `merge_blkx` trusts `blocksRunCount`: **CONFIRMED** (`0xfffffff007dcc060`
  `ldr w9,[x22,#0xc8]; rev w9; subs w9,w9,#1`; bound `0xfffffff007dcc170`).
- `blocksRunCount == 0` -> `w9 = -1`, and `mov w27,w9` is 32-bit so
  `x27 = 0xffffffff`: **CONFIRMED**.
- Low-side underflow at `0xfffffff007dcb684`: **CONFIRMED**, plus R43.1.
- **Correction, do not chase:** the table-size arithmetic at
  `0xfffffff007dcbfa4` (`umull x8,w25,#0x28; add x0,x8,#0xf4`) is 32x32->64 and
  **cannot overflow**; both passes read the same bytes under the same
  conditions, so there is no pass-mismatch overflow. The only table issue is the
  OOB *read* of runs.
- Not memory-unsafe but worth knowing: the front-clip path at
  `0xfffffff007dcc10c` rewrites `sectorStart`/`sectorCount` and leaves
  `compOffset`/`compLength` unadjusted, so a clipped RAW run reads the wrong file
  bytes. Correctness only.

### R43.5 *** APFS IS HARDENED - a negative result that redirects us *** [V]

Contrary to expectation. The b-tree read path is bounds-checked at **three**
levels:
1. **Per node, every cache-in.** `obj_init` (`0xfffffff00850b0e4`) validates
   `o_type`/`o_subtype`/`o_oid`/`o_xid`, then calls the object class's hook
   (`blr x8` at `0xfffffff00850b224`, `x8 = [classdesc+0x18]`). The class table
   is in `__DATA_CONST`: at `0xfffffff007600d68` the entry for `o_type == 3`
   (BTREE_NODE) has `+0x18 = 0xfffffff0084f3af8`, which calls
   `btree_node_sanity_check` and **bails without setting up any node range
   pointers** if it fails. fletcher64 runs before this, in `obj_read` ->
   `0xfffffff00850bd54`.
2. **`btree_node_sanity_check` (`0xfffffff0084f402c`) is thorough**: enforces
   `btn_table_space.off == 0`; `table_space.len <= nodeSize - 0x38 - (root?0x28:0)`;
   TOC alignment; **`btn_nkeys <= table_space.len >> (fixed?2:3)`** - so an entry
   count larger than the node IS caught; free-space bounds; `nodeSize %
   blockSize == 0`; `o_type` low half 2/3.
3. **Per entry, every read.** Key accessor `0xfffffff0084f46e0` checks
   `nkeys > index` then `btree_node_key_range_validate` (`0xfffffff0084f479c`):
   `key_off < free_space.off` and `roundup8(key_len) <= free_space.off - key_off`.
   Value accessor `0xfffffff0084f3db4` likewise via
   `btree_node_val_range_validate` (`0xfffffff0084f3f00`).

**A name longer than the buffer and an entry count larger than the node are both
caught.** Those validators are called from the write paths too, which is why an
earlier pass mistook them for write-only.

Also sound: `nx_check_checkpoint_map_block` (`0xfffffff008502b5c`) bounds
`cpm_count <= (blockSize - 0x28)/0x28`; the snapshot-name key builder
(`0xfffffff0084804e4`) is `<= 0x100` with `__memcpy_chk`; `apfs_mount` does not
copy `apfs_volname`, it stores a pointer (`0xfffffff0084eaa54`), so a
non-terminated name is at worst a 4 KiB-bounded over-read.

**So the kernel's APFS metadata is a poor target on this build. HFS+ is the
better one** - `hfs-522.100.5`, effectively unaudited, and `/sbin/mount_hfs`
is on the volume (53,600 B) so an HFS+ image attached by `hdik` reaches it.

### R43.6 `exec_shell_imgact` is clean [V]

`0xfffffff007a2932c`: both forward scans clamp at `0x200`
(`0xfffffff007a293d4`, `0xfffffff007a2942c`) returning ENOEXEC; the backward
whitespace trim's character set is `{0x09,0x0a,0x20,0x23}` and `vdata[1]=='!'`
(0x21) is not in it, so it cannot walk past index 1; destination `imgp+0x98` is
pinned at 0x200 and both copy loops are bounded by `vdata+0x1ff`. **No bug, and
shebang support is confirmed a third time.**

### R43.7 Reachability claim that CONTRADICTS our device results - treat with care

The audit asserts `/System/Library/xpc/launchd.plist` has
`Bootstrap -> Paths = ["/System/Library/LaunchDaemons",
"/AppleInternal/Library/LaunchDaemons"]` and concludes that **dropping one
plist is enough** to run `/usr/sbin/hdik -nomount /path/evil.dmg` at boot.

**Our own hardware results contradict this.** Jobs 599-605 planted
`com.nicsfix.mark.plist` in `/System/Library/LaunchDaemons` with `RunAtLoad` and
it never ran, and R39.4 showed the cache-optional path does a per-path
**on-demand** `xpc_bundle_create`, not a directory enumeration. Whether launchd
scans the bootstrap paths when the MRM cache validates was left UNVERIFIED then
and is still unresolved. **Do not build on the drop-in plist claim until it is
settled on hardware.**

What IS newly confirmed and useful: **`/usr/sbin/hdik` exists on this firmware**
(`100755 56832 usr/sbin/hdik`), carries
`com.apple.private.diskimages.kext.user-client-access`, and supports
`-encryption <key>` -> `image-secrets`, a second unaudited kernel surface. So
the UDIF-as-shebang construction (`#!/usr/sbin/hdik -nomount`, with the file
also being a valid UDIF image since `koly` sits at EOF) hands hdik **our own
file** and reaches every bug above - *if* we can get anything of ours to exec.

### R43.8 Next targets named by this audit

- **HFS+** (`hfs-522.100.5`): `hfs_swap_BTNode` /
  `hfs_swap_HFSPlusBTInternalNode`, `BTIterateRecords`, catalog/attribute keys,
  journal replay `hfs_journal_replay` (`0xfffffff0083297b4`). Unaudited.
- UDIF remainder: koly trailer parse (`0xfffffff007dcd7bc`), the XML
  resource-fork plist via kernel `OSUnserializeXML`, inflate
  (`0xfffffff007dcdd08`), LZFSE entry (`0xfffffff007dd3848`) and its size oracle
  (`0xfffffff007dd37e0`), `KDIUDIFCacheObject`, and the whole `-encryption`
  path.
- APFS remainder: the **j-object record content parsers above the validated
  accessors** - `j_drec_key.name_len`, `j_xattr_val.xdata_len`,
  `j_snap_metadata_val.name_len`, symlink targets. The b-tree layer hands them a
  correct `(ptr, len)`; whether each parser prefers the redundant embedded
  length is the open question.
- Mach-O load-command parsing vs the AMFI verdict ordering: unverified here.

---

## R44 - iBoot's APFS parser: NO memory-corruption bug. A well-evidenced negative.

Audit of `/home/claude/ib5/iBoot.dec` (iBoot-5540.140.12, base 0x830000000).
**Result: no memory-corruption bug found in iBoot's pre-authentication APFS
path.** The implementation is systematically bounds-checked in an
"accumulate an error counter, reject if non-zero" style. Both hypotheses this
project raised are **disproved**.

### R44.1 Both of our hypotheses were wrong [V]

- **`com.apple.os.update-` name construction is NOT unbounded.** `hashlen` from
  `FUN_830026c34(0x900,...)` is a **compile-time constant**: the static property
  registry spans `0x830046628`-`0x830046838`, and the descriptor for id `0x900`
  at `0x830042210` has `type=3`, `flags=0x00` (immediate, not a pointer or
  callback) and `value=0x14` = **20**. So `0x83001549c bfi x8,x27,#1,#0x3f`
  yields 41, plus 20 for the prefix = **61 bytes allocated for 20 + 40 + NUL**.
  An exact fit, with no attacker path to the value. **RETRACTED.**
- **The name-length field at `+8` in `FUN_830015798` is bounded.**
  `0x8300157e0 mov w1,#0xff; bl strnlen` caps at 255, and the copy is
  `memcpy_chk(key+0xa, name, len+1, 0x1216)` at `0x830015820`. It also builds
  the **search** key from iBoot's own string - the on-disk name only ever
  reaches a comparison, never a copy here. **RETRACTED.**

### R44.2 The one real finding: an infinite loop (DoS only) [V]

`FUN_830015f9c` (APFS extent read), `0x830015f9c`-`0x830016150`. The per-iteration
copy is `n = min(extent_avail, remaining)`; with `n == 0`,
`sub x19,x19,x25` is a no-op and the back edge at `0x8300160f4` re-enters at
`0x83001601c` (the error test) rather than the loop head, with `err` forced to 0
at `0x8300160e4`. **Never terminates.**

`n == 0` needs `extent_avail == 0`, and the `ext_end > offset` sanity check at
`0x830016070`/`0x830016074` is **conditionally skipped**: when `delta == 0` the
`ccmp` loads `nzcv = #2` (C=1, Z=0) so `b.ls` is not taken and a zero-length
extent passes. Attacker input: one `j_file_extent_val_t` for the kernelcache's
`private_id` with `logical_addr = 0`, `len_and_flags = 0`, `phys_block_num = 0`
(the sparse branch, the deterministic variant), plus a non-zero `j_dstream_t`
size on the inode.

Fires on a normal unassisted boot, from disk contents alone, **before** the
kernelcache IMG4 verification. **But it is a hard hang with no code execution
and no info leak - of no use for untether.** Worth knowing as a **brick risk we
could trip by accident while hand-authoring extents.**

### R44.3 What was verified as bounded (so we stop re-checking it) [V]

- **Container superblock** `FUN_830014078`: `0x1000 <= nx_block_size <= 0x10000`
  (`0x830014100`-`0x83001410c`), plus bounds on `nx_next_oid`, `xp_desc_blocks`,
  `xp_desc_base`/`xp_data_base`, the `*_next`/`*_index` fields, `*_len`,
  `nx_spaceman_oid`, `nx_omap_oid`, and `nx_max_file_systems <= 0x64`. Final
  gate `0x830014290` returns success only on error count 0.
- **B-tree node TOC** `FUN_830016c30`, called after **every** node read:
  `table_space.off == 0`; `ts.len <= node_size - hdr`; TOC alignment;
  `btn_nkeys <= ts.len / entry_size`; free-space bounds. Net invariant
  `hdr + ts.len + fs.off + fs.len <= node_size`.
- **`btn_get_val` `FUN_830017408`** cannot underflow its value-area size because
  `btn_validate` uses the identical `btn_flags & 1` test and header sizes.
  **`btn_get_key` `FUN_830017378`**: index `< nkeys`, `k_off < fs.off`,
  `fs.off - k_off >= k_len`.
- **Key/value copy-out** `0x83001712c`-`0x8300171a8`: both lengths compared
  unsigned against the caller's maxima (`0x340` key / `0xee0` value, matching
  the `0x1220` allocation split at every call site) and **both fail closed**.
- **Directory-record names** `FUN_830015950` validates `name_len` against the
  key length on **both** keys before any `memcmp`.
- **Path walk** `FUN_830015a18` caps components at `0x2fd` and pre-checks the
  total against the key buffer.
- **Inode xfield parser** `FUN_830015d6c` `0x830015eac`: the fit check is
  **exact** (the fixed `j_inode_val_t` part is `0x5c`, not `0x60`).
- **`nx_read_blocks`** checks `paddr + nblocks <= nx_block_count` without
  overflow; block cache bounded; `obj_verify_cksum` requires `size >= 8`; every
  `btree_init` call site passes `block_size` so buffer size and bound always
  agree; checkpoint map bounded.
- **nvram** `FUN_8300273f0` (also NAND-resident, also pre-auth): bounded.
- **boot-args**: every writer goes through `snprintf_chk`/`strlcat_chk` with
  `0x260`; the `recovery-boot-args` concat is pre-checked at `0x83000c108`.
- **IMG4/DER** `FUN_830034d7c`: `len >= 2`, multi-byte tag overflow test,
  long-form `nbytes <= 8` with `remaining >= nbytes` and leading-zero rejection,
  and in **both** forms the stored content length is `min(declared, remaining)`.
  `FUN_830032dd0` handles pointer-arithmetic overflow explicitly.
- **Load sizing**: `fs_load_file` caps at `0x10000000`, `FUN_83001209c` rejects
  `> 0xbe00000`; staging at `0x800000000` cannot reach `0x810000000` or iBoot.

Systematic sweep: all **248** call sites of `memcpy`/`memcpy_chk`/`strlcpy_chk`/
`strlcat_chk`/`snprintf_chk`/`memset`/`bzero` scanned, the **28** with a
memory-loaded size argument hand-reviewed. Every one had an explicit comparison
or clamp.

### R44.4 Useful secondary observations

1. **`apfs_root_to_xid` (+0x3C8) is taken with NO validation** and
   short-circuits the snapshot lookup entirely (`0x830015448`-`0x830015454`).
   Confirms R41.4's lever from a second direction: the binding between the boot
   manifest hash and the root tree is **a single unsigned u64 we control**.
   It does not weaken the kernelcache IMG4 check.
2. **The fletcher64 check on the FIRST superblock read is skipped when
   `nx_block_size != 0x1000`** (`0x8300140b4`-`0x8300140c0`). Not a security
   property - we can compute a valid fletcher64 anyway - but it saves work if we
   hand-author a non-4096 container.
3. `nx_block_size` may legitimately be anything in `[0x1000, 0x10000]` and iBoot
   reallocates to match. **A large, under-tested configuration space** - the one
   knob worth fuzzing on hardware, since `0x10000` exercises offset arithmetic a
   4096-byte filesystem never touches.
4. File sizes are **truncated to 32 bits** (`0x830015f24`). Consistent
   throughout, so not exploitable.
5. `memcpy_chk` at `0x830024918` **silently clamps**; `strlcpy_chk` at
   `0x830025c64` panics. Explains any short copy seen instead of a crash.

### R44.5 Still unaudited in iBoot

Spaceman and free-queue btrees; snapshot-metadata record parsing
(`FUN_8300177ec`, `FUN_8300178a4`); the upper VFS layer (`FUN_830018a18`,
`FUN_830018f48`, `FUN_8300195c0`, `FUN_8300197ac`, and `0x83001a000`-`0x83001b000`);
`FUN_830033d48`/`FUN_830033e10` bodies; USB/DFU request handling; and the
**`FUN_830035488`/`FUN_830039ae4`/`FUN_8300383c0` cluster**, which has
unexplained loaded-size copies at `0x830035e38`, `0x830035ef8`, `0x830035f20`
and FourCC-style constants near `0x830035e00` - **the auditor's own pick for the
next pass.**

### R44.6 Where this leaves the untether effort

iBoot's APFS parser is **closed as a code-execution target**. The live kernel
write primitive is R43.1/R43.2 (UDIF, `decompressBufferRequested` +
`compressedLength`), reached via `hdik`. The blocker is unchanged and is not an
analysis problem: **nothing of ours has yet been observed to execute on the
booted OS**, across six boots and three independent mechanisms.

---

## R45 - JOBS 604-615 ENTERED THE LOG. The evidence channel was never validated on the booted OS, and the shebang route is gated by an unaudited sandbox operation. 2026-11-27 00:50 PST

### R45.0 Provenance and coverage [V]

Jobs 604-615 ran 2026-11-26 22:07-23:52 PST and **had no entry in this log at
all** before now; R44 closed with "six boots" while twelve further jobs had
already run. Everything in R45.1 is read from `runner/done/*.job` and
`runner/out/*.log` directly. The static work in R45.4-R45.6 is mine, against
`route2/kernelcache.b238.macho` and `runner/files/launchd-13.4.8.bin`.

Read in full for this entry: R12, R13, R24.1-R24.2, R34, R37-R44, and the
twelve job logs. **Not** read line-by-line: R1-R33 bodies. A parallel review by
another agent supplied three of the corrections below; where it did, that is
stated, and each was independently verified here before being written down.

### R45.1 What the twelve jobs actually did

| job | kind | result |
|---|---|---|
| 604 | ramdisk | every custom NVRAM name shape set+read back PASS, **on the restore ramdisk** |
| 605 | ramdisk | ABORT: fresh-restored live volume incomplete (49 `/usr/libexec`) |
| 606 | ramdisk | live=49 vs snapshot=132 -> **the system lives in the SNAPSHOT** |
| 607 | ramdisk | ABORT: `/nfstash` never created (no `mkdir`) |
| 608 | ramdisk + boot | planted `/bin/sh`, `/bin/bash`, our jetsam plist; **DELETED Apple's snapshot** |
| 609 | ramdisk | `nicsfix-sh` absent, `nicsfix-pre` present, no snapshots, live=132, pod booted |
| 610 | ramdisk | same after a longer boot; `pod-get` of mrm.copy FAILED (file left 0 bytes) |
| 611 | ramdisk + boot | shebangs planted at `CrashHousekeeping` and `DumpPanic`, backups saved |
| 612 | ramdisk | `nicsfix-ch`/`nicsfix-dp`/`nicsfix-sh` all absent |
| 613 | ramdisk + boot | vehicles re-pointed at **existing** names (`debug-uarts=7`, `bootdelay=5`) |
| 614 | ramdisk + boot | corrected jetsam override installed, baselines reset |
| 615 | ramdisk | `debug-uarts` still 3, `bootdelay` still 0, `nicsfix-sh` absent |

**Genuine progress, and it is substantial:**
- **Apple's snapshot is deleted and the pod boots the live volume** (608 Q5;
  confirmed by 609/612/615 showing an empty snapshot list and a working boot).
  R38.5 option (ii) WORKS. Our plants are now on the volume that boots - the
  R38.1 confound is gone.
- Three vehicles are in place right now, `exec-ok`, root:wheel, mode 755, with
  `.nicsfix-orig` backups: `/bin/sh`, `/usr/libexec/CrashHousekeeping`,
  `/System/Library/CoreServices/DumpPanic`.
- `CrashHousekeeping` and `DumpPanic` are **confirmed `RunAtLoad`, root** cached
  jobs whose `Program` is exactly where we planted (parsed from
  `route2/mrm.orig.plist`: 183 entries; neither carries `UserName`, so both are
  root; CrashHousekeeping also has `LaunchOnlyOnce`). launchd should have
  spawned both on every boot.
- **The OS was fully up.** `runner/usb-events.log` shows the booted audioOS
  enumerating with its 40-hex UDID serial `2e2d3aea...` (the runner's own
  convention: ramdisk serial is a build date, the OS's is a 40-char UDID),
  including at 23:50:33, inside the 611-615 window. So lockdownd was running and
  the pod was pairable. Supplied by the parallel review; verified here.

### R45.2 *** CORRECTION, MINE: THE EVIDENCE CHANNEL HAS NEVER BEEN VALIDATED ON THE BOOTED OS *** [V]

My first draft of this section argued that `nicsfix-pre` surviving cold boots
proved the marker channel, and concluded that "no marker" therefore means "no
execution". **That was wrong, and it is the same error as R39.7 one level
deeper.**

- Every `nicsfix-pre` write was performed **from the restore ramdisk** (608 Q7,
  611 Q6, 613 Q5, 614 Q5). Reading it back after a cold boot proves NOR
  persistence of a *ramdisk-written* variable. It says nothing about whether a
  process on audioOS 13.4.8 can write NVRAM.
- Job 604 likewise ran entirely on the **2024 restore kernel** (`-restore`,
  and per the Nov-26 04:25 entry `AMFI: developer mode is force enabled on this
  platform`). Its PASSes are evidence about that kernel, not about 13.4.8.

**And the belief that it HAD been validated rests on a fabricated receipt.**
Line 4731 records job 515 finding **no** `r2-gate` in NVRAM after ~3 min of
13.4.8 uptime - a failure. Lines 5358, 5387, 5521 and 5525 then cite `r2-gate`
as a receipt that *was* written by the booted OS and read back, and build on it.
That inversion is the origin of the whole premise. **RETRACTED: no process on a
signed audioOS 13.4.8 boot has ever been observed to write an NVRAM variable.**
Caught by the parallel review; verified here against all five line references.

Consequence: **every null in jobs 609-615 is equally consistent with "the
shebang ran as root and the write was denied".** Jobs 613/614 switching to
existing names (`debug-uarts`, `bootdelay`) does not escape it - a restricted
list would cover exactly those. The kernelcache's Sandbox kext carries
`nvram-set` / `nvram-get` / `nvram-delete` as operations
(`0xfffffff0072ee008`..`01f`, confirmed present here) and `/usr/sbin/nvram`
carries no entitlements at all.

### R45.3 *** NEW AND VERIFIED: THE SHEBANG ROUTE IS GATED BY `process-exec-interpreter`, WHICH NOBODY AUDITED *** [V]

R24.1 proved exhaustively that **AMFI's** `mpo_vnode_check_exec` has an empty
failure set. It also noted, in passing, that Sandbox has a statically
initialised ops table at `0xfffffff00755e648` decoding to 139 hook names. MACF
calls **every** registered policy; any one of them can deny. Sandbox's hook was
never read.

Chain of evidence, all from `route2/kernelcache.b238.macho`:

1. **Sandbox registers a non-null `mpo_vnode_check_exec`.** Field 258 of its ops
   table = `ops+0x810`; the chained-fixup pointer there unpacks to
   **`0xfffffff007face28`**. (`mpo_vnode_check_signature` at `ops+0x818` =
   `0xfffffff007facfb0`.)
2. **That hook selects its operation from `scriptvp`**, the third MACF argument
   (`mpo_vnode_check_exec(cred, vp, scriptvp, ...)`), at
   `0xfffffff007faceb8`:
```
0xfffffff007faceb8  cmp   x21, #0      ; x21 = arg2 = scriptvp
0xfffffff007facebc  mov   w8, #0x65    ; 101
0xfffffff007facec0  cinc  w1, w8, ne   ; w1 = scriptvp ? 102 : 101
0xfffffff007faced0  bl    0xfffffff007fb1cec   ; policy eval, operation in w1
```
3. **The operation-name table is at `0xfffffff00755f268`**, 114 entries, op 0 =
   `default`, pointers into the `0xfffffff0072ed000` cstring region:
```
   op 100 -> process-codesigning-status-get
   op 101 -> process-exec*
   op 102 -> process-exec-interpreter
   op 103 -> process-fork
```

So: **a normal Mach-O exec is judged as `process-exec*`; a shebang exec is
judged as `process-exec-interpreter`.** R24.1 itself documented that
`exec_activate_image`'s -3 handler sets `imgp->ip_scriptvp` and branches back to
`again:`, so `mac_vnode_check_exec` runs a **second** time with `scriptvp` set -
and recorded that *AMFI* ignores it. Sandbox does not ignore it; it switches
operation. The platform profile applies to every process, root daemons included.

**This single mechanism would explain all three silent vehicles at once**, and
it sits at a layer no audit in this log has touched. Hypothesis raised by the
parallel review; the ops table, the hook and the dispatch verified here.

**STILL OPEN, and it is now the top static question:** what the compiled
platform profile actually returns for op 102 for a root platform daemon. That is
a profile-decode job, not a disassembly job, and it has not been done.

### R45.4 The R42 chain has an unreconciled fork: `ReportMemoryException` [V]

`route2/mrm.orig.plist` contains `com.apple.ReportMemoryException`, with
`ProgramArguments = ['/usr/libexec/ReportMemoryException']` and
**`UserName = '_reportmemoryexception'` - not root**, plus MachServices
`com.apple.ReportMemoryException` and `.CacheDelete`, both
`DrainMessagesOnCrash: All`. Verified here by parsing the plist.

So a memory `EXC_RESOURCE` on this build may be delegated to a **non-root**
helper instead of, or before, reaching `-[CrashReport captureDiagInfo:]` ->
`popen`. The `cbz w9` on the unidentified third ivar at `0x10000321c` (R42.2) is
a plausible site for exactly that switch. **Settle this statically before
spending another boot on the jetsam trigger** - if the memory path routes to
`_reportmemoryexception`, R42's chain never reaches a root `popen` and `/bin/sh`
loses its only proven root consumer. Raised by the parallel review; the plist
entry verified here, the switch hypothesis NOT yet verified.

### R45.5 `exec_shell_imgact` passes ONE optional argument, not whitespace-split args [U]

The parallel review suggested XNU splits the shebang line on whitespace (noting
it was from recollection). **My reading does not support that.** At
`0xfffffff007a2932c`: `w9` starts at 2, a jump-table loop skips whitespace, a
second loop finds the path end on `\n` or `#`, a trailing trim over
`{0x09,0x0a,0x20,0x23}` runs, and then the copy loop at `0xfffffff007a29484`
copies bytes into `imgp+0x98` **terminating on tab (0x09) or space (0x20)** -
i.e. one token, the interpreter path. A single bulk copy of the remainder
follows at `0xfffffff007a294f0`. That is XNU's documented "interpreter + at most
one argument (the rest of the line)".

Marked [U] because this was a partial read and I did not follow
`0xfffffff007a29580` (the arg-append callee). **Do not design multi-argument
shebang payloads until someone confirms it.** R37.4's original "one optional
argument" assumption stands for now.

### R45.6 What survives of my boot-task refutation, and its scope [V]

R39.1's identity check still excludes execution for **lever A only** (the
shebang at `/usr/libexec/sysstatuscheck`, jobs 602/603): a boot-task shebang
whose interpreter identity is `com.apple.nvram` rather than
`com.apple.sysstatuscheck` is `_os_crash` in PID 1, so the pod booting normally
proves it did not exec. That argument is channel-independent and stands.

**It does NOT extend to jobs 608-615.** Those planted at *cached daemon*
`Program` paths and at `/bin/sh`, where R39.1's identity check - which is
boot-task-scoped - does not apply. I over-generalised it in my draft. For those
jobs the sandbox hypothesis is fully alive, per R45.2 and R45.3.

### R45.7 Corrections to earlier sections [V]

- **R38.1 is wrong about cause.** Job 605 found the live volume incomplete (49
  `/usr/libexec`, no `launchd`, no `mrm.plist`) **immediately after a clean
  restore, before any snapshot surgery**, and job 606 confirmed the snapshot
  holds the full system (132 / 185 LaunchDaemons). A stock restore leaves live
  sparse and the snapshot complete. The "progressive file-shedding cascade"
  story should not be chased as corruption. Raised by the parallel review;
  matches what jobs 605/606 show directly.
- **`root-live-fs` contradiction, unresolved.** R37.9/R38 record it as consumed
  and cleared on every boot; jobs 609/612/615 show it persisting at `1` across
  boots. One reading is wrong. Harmless now (no snapshot exists and the pod
  boots live), but the clearing mechanism was already [U] and should not be
  relied on.
- **`snaputil -r` was used again** in job 607's `bootswap.sh` ("the revert in Q1
  rewrites the live volume") despite the hard rule in R38.6/R41.10. It happened
  to work. The rule stands.
- **Job 610's `pod-get` failed**, leaving `runner/files/mrm.plist` and
  `mrm-live.plist` at **0 bytes**. Any analysis pointed at those files is
  analysing nothing. Use `route2/mrm.orig.plist` (256,299 B, verified parseable,
  183 daemon entries).

### R45.8 The next job is a diagnostic, not a plant

The instruments that produced every real result on Nov 25-26 - `pymobiledevice3
syslog` over lockdownd, and the CODESIGNING crash-report signal - were dropped
after job 607 in favour of blind NVRAM markers. R45.1 establishes lockdownd was
up on every test boot, so that channel was available the whole time. One
collection distinguishes, in a single boot, with **no new plants** (all three
vehicles are already in place and `exec-ok`):

| what the log shows | conclusion |
|---|---|
| `Sandbox: ... deny(1) process-exec-interpreter` | R45.3 confirmed; shebang route dead, need a non-interpreter vehicle |
| `Sandbox: nvram(...) deny ... nvram-set` | code ran as root; R45.2 confirmed; redesign the marker, not the vehicle |
| AMFI `... killed ... CODESIGNING` | AMFI after all, contra R24.1's scope |
| launchd spawns CrashHousekeeping, no denial, no effect | something subtler; re-examine argv and the interpreter |
| no CrashHousekeeping spawn line at all | launchd never got there; the cached-job assumption is wrong |

Two operational points for that boot:
- **Leave the pod up 5+ minutes before DFU.** The 608->609 turnaround was ~60 s
  (booted 23:14:19, romdfu 23:15:20). The persisted log lags 5+ minutes (the
  Nov-26 04:50 methodology entry), and the jetsam -> ReportCrash chain needs the
  victim daemon up and breaching. A minute is marginal for both.
- **Keep the boot silent** - no music, no Siri, no touching the top panel.
  `audio_active` suppresses the `EXC_RESOURCE` the jetsam trigger depends on
  (job 614's own note).

### R45.9 Also worth doing, in rough value order

- Decode the platform profile for op 102 and for `nvram-set` (R45.3, R45.2).
- Settle the `ReportMemoryException` switch at `0x10000321c` (R45.4).
- **A non-NVRAM marker: the Update volume.** Job 565 mounted `/dev/disk1s3`
  read-only from the ramdisk with no hang, and it is unencrypted. If it is
  mounted writable at runtime, a payload leaves a file marker readable from the
  ramdisk with no NVRAM and no Data-volume mount. Needs its runtime mountpoint
  (device-tree fstab, which is what `/sbin/mount` reads per R42.7) and whether
  it is rw. Raised by the parallel review; not investigated here.
- **`boot-command` / `recovery-boot-args`, the contradiction worth closing.**
  R13.1 calls NVRAM `boot-command` inert by controlled test; R41.6 has it in
  list B as overridable; R41.8 calls it the hottest open question; and job 554's
  UART showed `Local boot ... Entering recovery mode` after a console
  `one-time-boot-command=recover`, which R8's setenv gate should have rejected.
  One of those is wrong. It matters because `recovery-boot-args` is now the only
  identified channel into `kern.bootargs` (R41.5), and if it is honoured then
  `boot-command=recover` + a `recovery-boot-args` disk-image argument would
  reach the UDIF write primitive (R43.1/R43.2) **with no userland execution at
  all** - which would route around this entire blocker. Raised by the parallel
  review. Speculative, unverified, and the highest-upside item on this list.

### R45.10 Rules added

- **A channel is validated only on the kernel and in the security context where
  the test will run.** A ramdisk write proves nothing about the booted OS. The
  restore kernel has AMFI developer mode force-enabled and no platform sandbox;
  treat every result obtained there as restore-only.
- **Before citing an earlier finding as a receipt, re-read the line it came
  from.** The `r2-gate` inversion (R45.2) cost four sections and the premise of
  two nights' work.
- **MACF calls every registered policy.** An audit of one policy's hook is not
  an audit of the hook. Name the policy in the finding.
- **Prefer a diagnostic boot over a plant boot when the last boot was a null.**
  A null with no log tells you nothing; the log channel was available all along.
- **Leave the pod up 5+ minutes** on any boot whose evidence is a persisted log,
  and keep it silent when the trigger is jetsam.
- Never analyse `runner/files/mrm.plist` or `mrm-live.plist` - job 610 left both
  at 0 bytes. Use `route2/mrm.orig.plist`.

================================================================================
R47 - THE PLATFORM SANDBOX PROFILE DENIES `process-exec-interpreter`
      UNCONDITIONALLY. Shebang scripts cannot be exec'd by ANY userland process
      on audioOS 13.4.8. That is why jobs 608-615 were silent. nvram-set is NOT
      the blocker. (static, kernelcache.b238.macho md5 2593a552..., no pod)
      2026-11-27 ~01:10 PST  [second session; R46 is the other session's hook read]
================================================================================

R47.0 One line
--------------
Sandbox-1217.140.4's compiled PLATFORM profile (applied to every process except
the kernel) maps operation 102 `process-exec-interpreter` straight to the DENY
terminal, with no filter, no entitlement exception and no path exception. The
AMFI result in R24.1 was right and irrelevant: MACF asks every policy, and
Sandbox says no. **No `#!` script can execute on this build, as root or
otherwise.** Every shebang plant (R37.4, R39.8, R40.1, R42, jobs 608-615) was
dead before it reached AMFI.

R47.1 How the profile was decoded (VERIFIED, reproducible)
-----------------------------------------------------------
Sandbox's init (0xfffffff007faa0f0, the function that panics with "failed to
initialize platform sandbox") loads two blobs:
  builtin collection   data 0xfffffff0070a4720  size 0x84fe2  -> global 0xfffffff00755e570
  **platform profile** data 0xfffffff007099c50  size 0xaac2   -> global 0xfffffff00755f1f0
The loader 0xfffffff007fb5934 defines the layout (read from the instructions,
not guessed):
  [0]  s16 flags (0)      [2]  u16 node count = 2637 (0x0a4d)
  [4]  u8  ops count = 0x92 = 146 (must match; else panic)
  [8]  u16 regex count = 2   [0xa] u8 vars = 1   [0xb] u8 = 0x1e (30 entries)
  ops table  at 0xc + 2*regex + 2*vars + 2*0x1e = **offset 78**, 146 x u16 (node index per op)
  node base  = (78 + 292 + 7) & ~7 = **376**, 8 bytes per node
  string base = 376 + 2637*8 = **21472**; node args for string filters are
               offsets in 8-byte units from there, u16 length + bytes
Node format: byte0 = 0 non-terminal {u8 filter, u16 arg, u16 match, u16 unmatch}
             byte0 = 1 terminal {u8 flags, ...}; flags bit0 set = DENY.
Op numbering is the kernel's operation-name table at 0xfffffff00755f268
(146 entries, op 0 = default): 101 process-exec*, **102 process-exec-interpreter**,
103 process-fork, 93/94/95 nvram-delete/get/set, 52 iokit-set-properties.
Calibration (so the decode is trusted): op 9 `dynamic-code-generation` decodes
to  entitlement "dynamic-codesigning" == true ? allow : deny with message
"MAP_JIT requires the dynamic-codesigning entitlement"; op 16
`file-map-executable` decodes to the known get-task-allow / Containers /
can-execute-cdhash / signing-identifier rule set. Both match the public iOS 13
platform profile text exactly.

R47.2 The verdicts (VERIFIED)
-----------------------------
  op 102 process-exec-interpreter -> node 1865 = TERMINAL flags 0x5 = **DENY**
                                      (1865 is the same deny leaf the profile
                                       uses for e.g. file-write-create under
                                       /AppleInternal)
  op 101 process-exec*            -> node 172: path-pattern denies, then
                                      container-required / no-container /
                                      no-sandbox entitlement checks, otherwise
                                      allow (why racoon-as-CrashHousekeeping ran
                                      in job 534)
  op 103 process-fork             -> 2636 = allow
  op 95  nvram-set                -> 2636 = **allow**
  op 94  nvram-get                -> 2636 = allow
  op 93  nvram-delete             -> 2636 = allow
  op 52  iokit-set-properties     -> 2636 = allow
Reachability of the verdict: Sandbox's mpo_vnode_check_exec = ops slot +0x810
= 0xfffffff007face28 (agrees with R46). It stores the cred at ctx+0x20 and calls
the evaluator 0xfffffff007fb1cec. The evaluator (0xfffffff007fb1d64-0xfffffff007fb1da0)
evaluates the PLATFORM profile for every subject whose cred is not the kernel's,
BEFORE and independently of any per-process profile; a platform deny is final.
So root, unsandboxed, launchd-spawned, grandchild - none of it matters.

Kernel flow for a shebang: exec_shell_imgact (0xfffffff007a2932c) returns -3,
exec_activate_image sets ip_scriptvp and re-runs mac_vnode_check_exec with
scriptvp != NULL -> Sandbox picks op 102 -> deny -> execve fails EACCES.
Expected syslog signature on a diagnostic boot:
  `Sandbox: launchd(1) deny(1) process-exec-interpreter /usr/sbin/nvram` (or the
  spawning daemon's name) plus launchd's spawn failure for the job. That is the
  line to look for in the archive of any of the 608-615 boots.

R47.3 nvram-set was never the problem (VERIFIED)
------------------------------------------------
- Platform profile: nvram-set / nvram-get / nvram-delete all allow (above).
- Sandbox's only in-kernel nvram evaluator is the get-property hook (slot 0xa70,
  0xfffffff007faed0c, op 0x5e nvram-get). The nvram-SET checker exists
  (0xfffffff007fa9870, with the "boot-args" token special case R41.5 saw, and
  its wrapper 0xfffffff007faedf0) but has **zero** callers, branches, adrp/adr
  refs or data pointers anywhere in the kernelcache - dead code. No
  mpo_iokit_check_nvram_set is registered on this build.
- IODTNVRAM::setProperty = 0xfffffff007bd7598: gate is only
  getOFVariablePerm(key): perm != UserWrite needs
  clientHasPrivilege(current_task,"root"); perm == KernelOnly needs kernel_task
  (that is the `com.apple.System.*` "privilege violation"); "aapl,panic-info"
  rejected; "boot-args" value capped at 0x25f. **No MAC call, no entitlement
  check, custom names accepted from any root process.**
- The AMFI code referencing `com.apple.private.security.restricted-nvram-
  variables.heritable` (0xfffffff007c99e70) is the entitlement->csflags mapper
  run at exec, not an NVRAM gate.
=> A root process that actually runs CAN write a custom NVRAM marker on the
   booted OS. The channel is fine. Nothing of ours has run.

R47.4 Correction to R46 item 3: XNU DOES split the shebang line into multiple argv (VERIFIED)
--------------------------------------------------------------------------------------------
exec_shell_imgact only SAVES the whole interpreter line (one copy into
ip_interp_buffer at imgp+0x98, 0xfffffff007a2953c-0xfffffff007a29574). The
tokenising happens later in exec_extract_strings' IMGPF_INTERPRET branch,
0xfffffff007a26de4-0xfffffff007a26f44: find token end at tab/space, NUL it
(0xfffffff007a26e90), copy it out as one user string, bump ip_argc
(0xfffffff007a26f3c), skip whitespace (0xfffffff007a26f10-f20), loop
(`cbnz x8, 0xfffffff007a26dec`). macOS/XNU behaviour, not Linux's. Moot now
that interpreter exec is denied, but recorded so it is not re-argued.

R47.5 What this kills, and what survives
----------------------------------------
DEAD on 13.4.8 (platform profile, not fixable by any file we can write):
  - every `#!` payload: /bin/sh shebang (R40.1, R42), CrashHousekeeping and
    DumpPanic shebangs (jobs 611-614), `#!/bin/df -h` harmlessness control
    (R40.3c), the "UDIF-as-script" construction (R37.4 b', R39.8, R43.7).
  - R24.1's "the script primitive is real" as a usable primitive. AMFI's hook
    cannot deny; Sandbox's does. R24.2 ("a script cannot reach native code")
    stands, trivially.
SURVIVES:
  - R3's substitution primitive: a byte-for-byte copy of a TRUST-CACHED Mach-O
    at any path execs (op 101 allows it; job 534 proved it). The payload must be
    a Mach-O Apple shipped and trust-cached, and it receives whatever argv the
    exec site passes.
  - the exec SITES found since: launchd cached jobs (argv fixed, R37.1),
    /sbin/fsck_apfs symlink (grandchild, must exit 0, pre-mount, R39.8/R40.3c),
    ReportCrash -> popen -> /bin/sh (argv = [sh, -c, <ExcDiagToolExtras cmd>],
    R42), wifivelocityd NSTask /bin/sh -c (R42.5), keybagd/seputil
    posix_spawn /bin/bash (R40.1, internal-gated?).
  - the NVRAM marker channel (R47.3) and the hdik/UDIF kernel bugs (R27/R33/R43).
THE REFRAMED PROBLEM: we need a trust-cached Mach-O that does something useful
when exec'd with the argv one of those sites gives it. For the popen sites that
argv is `["/bin/sh","-c","<string we choose via ExcDiagToolExtras>"]`.
  - NEVER a copy of nvram there: `-c` = clear all variables (R40.8 stands).
  - Candidates to audit for "-c <string>" semantics: every trust-cached binary
    whose getopt accepts -c, or which ignores unknown flags and acts on argv[2]
    as a path. hdik takes `<image>` positionally but rejects `-c`; needs a read.
    This is now a small, well-defined audit over the 578-entry trust cache.
  - For the launchd-job sites (argv = program path only), the useful binaries
    are the ones with hardcoded config paths (racoon /etc/racoon/racoon.conf -
    present on 13.4.8 per R42.7 - and pppd IF /etc/ppp/options is live, which
    R42.7 says it is not). racoon's `-f` is not reachable there.

R47.6 Why the diagnostic boot is still worth one cycle
------------------------------------------------------
Everything above is static. One `pymobiledevice3 syslog collect` taken 5+ min
after a boot with the job-614 plants still in place should show the
`deny(1) process-exec-interpreter` line. That turns a static verdict into a
hardware one and costs nothing we have not already spent four times.

R47.7 Tooling (in the container; copies committed to multipod/sbprof/)
----------------------------------------------------------------------
  kc.py      kernelcache helper: segments, VA<->file, funcstarts, capstone,
             adrp/add + data-pointer xrefs (threaded rebase: VA = 0xfffffff000000000
             | (raw & 0xffffffff) for this cache)
  sbprof.py  platform-profile parser (ops at 78, nodes at 376, strings at 21472)
  ops.json   the 146 operation names in kernel order
  R47-platform-profile-dump.txt  full decode of every op's tree
Re-run: `python3 -I sbprof_dump.py` prints the verdict table.

R47.8 Rules added
-----------------
- **No shebang payloads on 13.4.8, ever.** Platform profile denies
  process-exec-interpreter with no exception. Payloads are trust-cached
  Mach-O copies only.
- **When a MACF question comes up, decode the platform profile, not just a
  hook.** The profile is 43 KB and parses in a second with sbprof.py.
- A ramdisk (2024 Sandbox) verdict does not transfer to 13.4.8's Sandbox-1217;
  decode the profile from the kernel that will run.

---

## R46 - THE POD FACTORY-RESETS ITSELF. A third explanation for every null, and four instrument faults found in one hour. 2026-11-27 01:12 PST

### R46.0 *** THE POD RE-OBLITERATES ON BOOT. Every "test boot" may have been a setup/reset cycle, not a normal boot. *** [V, observed by Nic]

At ~01:04 the pod was booted normally for a diagnostic capture. UART went
silent after `End of iBootStage2 serial output`; the pod then **factory reset
itself**, observed directly at the unit.

NVRAM has been carrying the evidence the whole time, in every verdict dump from
job 604 onward:
```
obliteration   handle_message: Obliteration Complete%0a
oblit-begins   OblitType: ObliterateDataPartition. Reason: Device was left in a
               partially-setup state
```
Combined with the 2026-11-26 04:10 entry - *"Why setup cannot complete: a
teardown/network deadlock. NOT caused by our changes"* - the picture is a loop:
**setup cannot complete -> the device judges itself partially set up ->
it obliterates the Data partition -> setup cannot complete.** `finish-obliteration`
(`/usr/libexec/mobile_obliterator`) is boot task #4 of 17, so this is handled
early in every boot.

**This is a third candidate cause for all ten nulls, and nobody has controlled
for it.** The other two are R45.2 (the `nvram-set` write may be denied on the
booted OS) and R45.3 (`process-exec-interpreter` may be denied). This one is
different in kind: it says the boots were never the steady-state environment the
tests assumed. Corroboration already in the log: R3's SQLite probes were closed
as a negative with the qualifier *"nothing reads those files at boot **in setup
mode**"* - the same qualifier, never generalised.

Open and now important: whether launchd's `RunAtLoad` cached daemons
(`CrashHousekeeping`, `DumpPanic` - both confirmed root in R45.1) actually start
during an obliteration/setup boot, and whether the pod reboots mid-cycle inside
the window we were measuring. Job 617 is queued to assess what the reset did to
the volume; **it does not answer this**, and until it is answered no plant-boot
result can be trusted either way.

### R46.1 *** READING RULE: UART silence after iBootStage2 is a SUCCESSFUL boot on this pod *** [V]

The reset was initially read as a hang, because the UART capture ends at
`End of iBootStage2 serial output` with nothing after it. Per R38.3 the system
kernel's serial console is **shut on a production-fused (CPFM:03) part whatever
is in boot-args**, so silence after the iBootStage2 handoff is the signature of
every successful boot here, not a fault.

The `<hash>:<line>` markers in that tail must not be read as error codes -
R12's RETRACTION 1 established they are `<source-file-hash>:<line number>`
ordinary log/assert sites, and voided an entire error-decode table built on the
other reading. Do not re-derive it.

**What DOES tell you the pod booted** (all three available without UART):
- a USB enumeration with the 40-hex UDID serial (`runner/usb-events.log`);
- `mode()` reporting `audioos`;
- the `info` action returning rc=0, i.e. lockdownd answered a query.

At 01:07:44, while the boot was being called a hang, `info` returned **rc=0**
and the pod was enumerating. Both facts were in the runner's own files.

### R46.2 *** INSTRUMENT FAULT 1: the booted OS also enumerates as USB PID 0x12AC *** [V]

Job 616 aborted at `info` with `refused: no HomePod on USB`, `mode=none`, while
the pod sat fully booted. Cause: at 01:03:46 the pod's product ID changed
**0x12B0 -> 0x12AC**, same UDID serial. The runner's filter was
`pods() { usb | grep -E 'pid=0x1227|pid=0x1281|pid=0x12B0|HomePod'; }`, which
matches nothing for 0x12AC, so `mode()` returned `none` and the `only` guard
refused correctly on bad input.

**Fixed** (backup `hp-runner.command.pre-12ac`): `pods()` now also matches
`pid=0x12AC`, and `mode_of()` has an explicit `*0x12AC*) echo audioos` branch
rather than relying on the `*)` fallback.

Secondary observation, worth confirming rather than assuming: 0x12B0 appears to
be an earlier-boot USB configuration and 0x12AC the fuller one - the pod was
0x12B0 at 00:54:45 and 00:57:37, then 0x12AC from 01:03:46. If that holds,
**0x12AC is a free boot-progress signal** stronger than the UDID alone, since it
implies the OS re-enumerated. [U] - one observation, and it is now entangled
with the reset, so it needs a clean boot to confirm.

### R46.3 INSTRUMENT FAULT 2: the `only` guard cannot match a booted pod [V]

With 0x12AC recognised, job 616b then failed `refused: a HomePod other than the
one this job names is connected`. The guard matches each USB line against the
`only` tokens; the booted OS's serial is the **40-hex UDID**
(`2e2d3aea2a9d916d96366ebba9c827f9dd1d9e6b`), which contains neither the ECID
`000024EA009A60A6` nor the device serial `DLXW5B84HQK8`.

**No runner change needed** - the guard uppercases both sides (`p="$(pods | tr
'[:lower:]' '[:upper:]')"` against an already-uppercased `ONLY`), so adding the
UDID as a third `only` token matches and keeps the guard's protection intact:
```
only 000024EA009A60A6 DLXW5B84HQK8 2e2d3aea2a9d916d96366ebba9c827f9dd1d9e6b
```
**Every job that acts on a BOOTED pod needs the UDID on its `only` line.** Jobs
that only touch DFU/recovery/ramdisk do not.

### R46.4 INSTRUMENT FAULT 3: `pymobiledevice3` says "Device is not connected" while `ideviceinfo` succeeds [U]

Job 616c: `info` returned rc=0, then
`pymobiledevice3 syslog collect` failed with `ERROR Device is not connected.`
So lockdownd answers libimobiledevice but pymobiledevice3's usbmux layer does
not see the pod - plausibly because 0x12AC is unexpected there too, or a pairing
record exists only for one stack. Unresolved.

Mitigations added to the runner's `syslog` action (backup
`hp-runner.command.pre-diagfix`), all read-only:
- print `pymobiledevice3 usbmux list` first, so we see what it thinks is there;
- retry `syslog collect` with an explicit `--udid` scraped from the USB serial;
- **pull crash reports with `idevicecrashreport`** - an AMFI `CODESIGNING` kill
  persists there, so this is a second, independent instrument for R45.8's
  discriminator and does not depend on os_log at all.

### R46.5 INSTRUMENT FAULT 4: my own bug, and it is the kind that fakes a result [V]

The first version of the `syslog` action declared
`local out="${1:-syslog}" arch="files/$out.logarchive" ...` in a single `local`
statement. Bash expands all words before the builtin runs, so `$out` was empty
and the archive path became `files/.logarchive`. Split into separate `local`
statements. Noted because it belongs to the same family as everything else in
this entry: **the instrument produced a wrong path and would have reported a
missing archive as a failed collection.**

Related, caught before it ran: the first draft of the disk4 blankness check in
job 604's successor reported a **failed read** (`size=0`) as "BLANK - good
baseline", because `od | tr -d '0' | wc -c` returns 0 for empty input. Any
disk4 check must test size > 0 before calling a log blank. Carried into
`verdict8.sh` Q8, which now prints `READ FAILED (not 'blank')`.

### R46.6 Score for the hour

Four instrument faults, zero device findings. Jobs 616, 616b and 616c produced
no information about the pod - they produced information about the runner. That
is the same pattern as jobs 599-603 (wrong volume) and 604-615 (unvalidated
channel): **the dominant failure mode on this project is not the target's
hardening, it is measuring with an uncalibrated instrument.** Six of the last
nineteen jobs tested the device; the rest tested our tools.

### R46.7 Rules added

- **UART silence after `End of iBootStage2` means a SUCCESSFUL boot on CPFM:03.**
  Never read it as a hang. Confirm boot via UDID enumeration, `mode()=audioos`,
  or `info` rc=0 - never via UART.
- **Put the pod's 40-hex UDID on the `only` line of every job that touches a
  booted pod.** ECID and device serial do not appear in its USB serial.
- **`pid=0x12AC` is the booted OS too.** Any tooling that enumerates pods must
  match it alongside 0x12B0.
- **Treat `oblit-begins` in an NVRAM dump as a red flag on the whole boot.**
  While the pod self-obliterates, no plant-boot result is interpretable. Check
  for it in every verdict script before reading any marker.
- **Never declare a block device blank without checking size > 0 first.**
- In shell, never reference a variable in the same `local` statement that
  declares it.

---

## R47 - THE POD OTA'd ITSELF 17M61 -> 24K157. And the obliteration loop has a one-rename, verified-benign off switch. 2026-11-27 01:20 PST

### R47.0 *** THE POD IS NO LONGER ON 13.4.8. IT COMPLETED AN OTA DURING THE 00:54-01:11 BOOT. *** [V]

Not a factory reset. NVRAM from job 618 states it outright:
```
ota-original-base-os-version   17M61        ota-os-version     24K157
ota-original-os-version        17M61        ota-brain-version  24K157
ota-result                     success      ota-outcome        success
ota-uuid        14D0E486-5FFC-4699-9232-45D311BC7070
ota-breadcrumbs 2:BDCoAFGKlgPmRaebSTUWXZ    ramrod-nvram-sequence 1065
OTA-fsck-metrics  dev= vers=3288.43.1 default_ans=y result=0 ...
ramrod-nvram-shadow-path  /mnt2/nvram.plist
```
Corroborated by the volume itself (job 617/618, all against 17M61's figures):

| measure | now | 17M61 |
|---|---|---|
| `/usr/libexec` entries | **227** | 132 |
| `/System/Library/LaunchDaemons` | **299** | 185 |
| `/sbin/launchd` | **588,512 B** | 365,776 B |
| exclaves in `/usr/libexec` | **2** | 0 |
| `jetsamproperties.B238a.plist` | **67,466 B** | 55,009 B |
| `jetsamproperties.B238.plist` | **absent** | present |
| launchd job cache | `/System/Library/xpc/launchd.plist` (756,594 B) + `.sig` | `Caches/com.apple.xpc.launchd/mrm.plist` (256,299 B) |
| snapshot | `com.apple.os.update-2207559B...` | `...3E3FF731...` |
| `hdik` | present, 58,480 B | 56,832 B |

**Consequences, and they are large:**
- **Every address, offset and structural finding in R27-R46 is 17M61-specific and does not describe this pod's current state.** The UDIF write primitive especially: R35 established both defects are **fixed** in current audioOS. The kernel write primitive does not exist on 24K157.
- All three vehicles, both `.nicsfix-orig` backups, `/bin/sh`, `/bin/bash` and our jetsam override are **gone** - replaced by the new system volume.
- `mrm.plist` is gone as a concept here; the whole R37/R39/R40 launchd-cache analysis is 17M61-only.
- **`nicsfix-pre=v614` SURVIVED the OTA.** Custom NVRAM names persist across an OS upgrade. (Still a ramdisk-written variable, so R45.2's point about the *write* leg on a booted OS is untouched.)

**This also retroactively explains three open items.** The long-standing "why does it never update" question is answered - it does, given network and uptime. R24.0's alarm ("the pod is almost certainly not on 13.4.8 any more") was **retracted** at R24.7/R26 as a staging artifact; that retraction now looks wrong, or at least premature. And R34.3's anomaly - job 590 measuring **227** `/usr/libexec` entries with exclaves present - is exactly today's figure, so the pod had already been on the modern OS once.

Mechanism not settled: whether the OTA was pre-staged on disk (R26's staging hypothesis, retracted at R30.0) or downloaded live in those 17 minutes. `/mnt1/usr/standalone/update` exists and `usr/standalone/firmware` is dated today. [U]

### R47.1 *** THE OBLITERATION LOOP: an off switch, verified benign *** [V]

Parsed from `/sbin/launchd`'s own `__TEXT,__config` embedded bplist
(`0x100046071`, 0x1555 bytes - launchd's signed configuration, not a file we
edit):
```
finish-obliteration  {'RebootOnExitCode': 89,
                      'Program': '/usr/libexec/mobile_obliterator',
                      'ProgramArguments': ['mobile_obliterator', '--init']}
```
**It carries neither `RequireRun` nor `RequireSuccess`**, and `RebootOnExitCode:
89` is the loop's engine - R39.2 verified that `WEXITSTATUS == RebootOnExitCode`
makes launchd reboot. So: obliterator runs, exits 89, device reboots, setup still
cannot complete, repeat.

R39.2 case 5, verified at `0x10002d8a0`-`0x10002dac8`: *program absent ->
`"<task>: optional boot task not present"`; `RequireRun=true` -> fatal; **unset
-> benign**.*

**Therefore renaming `/usr/libexec/mobile_obliterator` disables obliteration and
the boot continues normally.** One rename, reversible from the ramdisk.

**>>> DO NOT CONFUSE THIS WITH R39.1. <<<** R39.1's hard rule is *plant nothing
EXECUTABLE at a boot-task `Program` path* - a shebang or a copied platform
binary there fails the identity check and is `_os_crash` in PID 1. Making the
program **absent** is the opposite operation and is explicitly the benign branch.
Rename; never substitute.

**Same applies to the update machinery:**
```
MSUEarlyBootTask  {'Program': '/usr/libexec/MSUEarlyBootTask'}
```
No flags at all, so also safely absent. That is MobileSoftwareUpdate's
early-boot task.

**Do NOT use this on cached daemons.** R39.2's separate landmine: launchd
*panics* when a cached job's executable is missing
(`"File Radar to: [ launchd | missing executable ]... Set boot-arg
launchd_missing_exec_no_panic=1"`). Boot tasks are benign when absent; cached
daemons are fatal. The OTA *daemons* must therefore be left alone - block the
update at the network instead.

### R47.2 Other boot tasks, now fully enumerated with flags [V]

The complete `Boot` dictionary (20 entries; execution order still comes from
launchd's ordered table at `0x10002dea4`-`0x10002e098`, not from this dict):

| task | Program | flags |
|---|---|---|
| `fsck` | `/sbin/fsck` `-q` | RequireSuccess, RequireRun |
| `fsck-safe` | `/sbin/fsck` `-qy` | RequireSuccess |
| `mount-phase-1` / `-2` | `/sbin/mount` `-P 1`/`2` | RequireSuccess, RequireRun |
| `data-protection` | `/usr/libexec/init_data_protection` | RequireSuccess, **CSIdentityOverride com.apple.seputil** |
| `finish-obliteration` | `/usr/libexec/mobile_obliterator --init` | **RebootOnExitCode 89**, nothing else |
| `restore-datapartition` | `/usr/libexec/HorizonSetup` | PerformInRestore, RequireSuccess |
| `fips` | `/usr/libexec/cc_fips_test` | RequireSuccess, RequireRun |
| `keybag` | `/usr/libexec/keybagd --init` | PerformAfterUserspaceReboot |
| `finish-restore` | `/usr/libexec/FinishRestoreFromBackup` | RequireSuccess, PerformAfterUserspaceReboot |
| `finish-demo-restore` | `/usr/libexec/finish_demo_restore` | RequireSuccess, **RequireRun: False** |
| `sysstatuscheck` | `/usr/libexec/sysstatuscheck` | RebootOnSuccess, PerformAfterUserspaceReboot |
| `recovery-mode` | `/usr/sbin/nvram` `auto-boot=false` | RequireSuccess |
| `tzinit`, `prng_seedctl`, `MSUEarlyBootTask` | as named | **no flags** |
| `fud` | `MobileAccessoryUpdater.framework/Support/fud --early-boot` | no flags |
| `xpcroleaccountd` | `/usr/libexec/xpcroleaccountd -boot` | CSIdentityOverride com.apple.xpc.roleaccountd |
| `init_featureflags` | `/usr/libexec/init_featureflags --boot` | PerformAfterUserspaceReboot |
| `launchd_cache_loader` | `/usr/libexec/launchd_cache_loader` | RequireRun, RequireSuccess, PerformAfterUserspaceReboot |

Note `recovery-mode` exists as a boot task and its whole job is
`nvram auto-boot=false` - worth remembering for the recovery-path work in R45.9.

### R47.3 Correction: job 617's NVRAM section was MY bug, not a pod change [V]

`verdict8.sh` reported `nvram: command not found` and `tr: command not found`
for every query. Cause: the script did not `export PATH`. Every working script
in `route2/` begins with
`export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin:/usr/libexec`.
Job 617's Q1, Q2, Q8 and Q9 are therefore void; job 618 re-ran them correctly.
Also void for the same reason: the earlier "awk: command not found" in job 608
Q3 and "tr: command not found" in job 613 Q3 - those steps did not run either,
and 613's "do these daemons exist in the cache" question was answered only later
by 614.

**Rule: every `pod-sh` script starts with the PATH export.** The ramdisk's
default PATH does not include `/usr/sbin`.

Also: the ramdisk's **root filesystem is read-only** - `mkdir /nf617` failed
with `Read-only file system`. Use `/mnt1/nf` (or test a list of candidates, as
`whatami.sh` now does). And disk4 read 0 bytes again with a correct path, so the
paniclog channel remains **unproven on this pod** (R45.2 caveat 1 stands).

### R47.4 The plan this implies

A stable 17M61 surface is now a prerequisite for everything in R42-R46, and it
needs three things, in this order:

1. **Restore to 13.4.8/17M61.** Assets confirmed present:
   `~/homepod/homepodstuff/HomePod-13.4.8-17M61.ipsw`,
   `~/homepod/tickets/tickets/000024EA009A60A6/13.4.8-17M61.shsh2`,
   `~/homepod/tickets/BuildManifest-13.4.8-17M61.plist`. The runner deliberately
   never restores, so this is a manual HomePod Hospital step.
2. **Before the first boot, from the ramdisk:** rename
   `/usr/libexec/mobile_obliterator` and `/usr/libexec/MSUEarlyBootTask`
   (keep both originals in place as `.nicsfix-orig`), then re-plant the vehicles.
   Both renames are benign per R47.1 and reversible.
3. **Keep the pod off WiFi.** Nothing in this work needs network, and the OTA is
   what cost us the 17M61 surface. Consider also `ota-retry-enabled=false`
   (an Apple-known NVRAM name, already present and therefore writable).

Only then do marker results mean anything - and even then R45.2 still applies:
the *write* leg of the NVRAM channel on a booted OS has never been demonstrated.

### R47.5 Rules added

- **Every `pod-sh` script must `export PATH=/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin:/usr/libexec` as its first line.**
- **The ramdisk root filesystem is read-only.** Scratch goes in `/mnt1/nf`.
- **Never leave the pod booted with network for more than a few minutes.** It
  will OTA itself off the analysed build. Our tests need ~5 minutes; the OTA
  took 17.
- **To disable a BOOT TASK, rename its Program (benign when it lacks
  `RequireRun`). To disable a CACHED DAEMON, do not - a missing cached
  executable panics launchd.** Check the flags in launchd's `__TEXT,__config`
  bplist at `0x100046071` first, every time.
- **Record the build in every verdict script** (`/usr/libexec` count, launchd
  size, snapshot name). Four jobs' worth of conclusions were drawn tonight
  without once checking the pod was still on the build we were analysing.

---

## R48 - [renumbered from R47, second session] THE PLATFORM SANDBOX PROFILE DENIES `process-exec-interpreter` UNCONDITIONALLY

*Filed as R48: this section was authored as R47 by the second session, but R47
was already taken by the OTA/obliteration entry above. Content is that
session's, verbatim below. Tooling and full dumps in `multipod/sbprof/`.*

*Cross-check: R45.3 (first session) independently derived the same operation
table base `0xfffffff00755f268` and the same `cinc w1, w8, ne` dispatch in
Sandbox's `mpo_vnode_check_exec` at `0xfffffff007face28` selecting op 101 vs
102 on `scriptvp`. Two independent derivations agree on the op numbering; this
section supplies the verdict those ops resolve to.*


================================================================================
R47 - THE PLATFORM SANDBOX PROFILE DENIES `process-exec-interpreter`
      UNCONDITIONALLY. Shebang scripts cannot be exec'd by ANY userland process
      on audioOS 13.4.8. That is why jobs 608-615 were silent. nvram-set is NOT
      the blocker. (static, kernelcache.b238.macho md5 2593a552..., no pod)
      2026-11-27 ~01:10 PST  [second session; R46 is the other session's hook read]
================================================================================

R47.0 One line
--------------
Sandbox-1217.140.4's compiled PLATFORM profile (applied to every process except
the kernel) maps operation 102 `process-exec-interpreter` straight to the DENY
terminal, with no filter, no entitlement exception and no path exception. The
AMFI result in R24.1 was right and irrelevant: MACF asks every policy, and
Sandbox says no. **No `#!` script can execute on this build, as root or
otherwise.** Every shebang plant (R37.4, R39.8, R40.1, R42, jobs 608-615) was
dead before it reached AMFI.

R47.1 How the profile was decoded (VERIFIED, reproducible)
-----------------------------------------------------------
Sandbox's init (0xfffffff007faa0f0, the function that panics with "failed to
initialize platform sandbox") loads two blobs:
  builtin collection   data 0xfffffff0070a4720  size 0x84fe2  -> global 0xfffffff00755e570
  **platform profile** data 0xfffffff007099c50  size 0xaac2   -> global 0xfffffff00755f1f0
The loader 0xfffffff007fb5934 defines the layout (read from the instructions,
not guessed):
  [0]  s16 flags (0)      [2]  u16 node count = 2637 (0x0a4d)
  [4]  u8  ops count = 0x92 = 146 (must match; else panic)
  [8]  u16 regex count = 2   [0xa] u8 vars = 1   [0xb] u8 = 0x1e (30 entries)
  ops table  at 0xc + 2*regex + 2*vars + 2*0x1e = **offset 78**, 146 x u16 (node index per op)
  node base  = (78 + 292 + 7) & ~7 = **376**, 8 bytes per node
  string base = 376 + 2637*8 = **21472**; node args for string filters are
               offsets in 8-byte units from there, u16 length + bytes
Node format: byte0 = 0 non-terminal {u8 filter, u16 arg, u16 match, u16 unmatch}
             byte0 = 1 terminal {u8 flags, ...}; flags bit0 set = DENY.
Op numbering is the kernel's operation-name table at 0xfffffff00755f268
(146 entries, op 0 = default): 101 process-exec*, **102 process-exec-interpreter**,
103 process-fork, 93/94/95 nvram-delete/get/set, 52 iokit-set-properties.
Calibration (so the decode is trusted): op 9 `dynamic-code-generation` decodes
to  entitlement "dynamic-codesigning" == true ? allow : deny with message
"MAP_JIT requires the dynamic-codesigning entitlement"; op 16
`file-map-executable` decodes to the known get-task-allow / Containers /
can-execute-cdhash / signing-identifier rule set. Both match the public iOS 13
platform profile text exactly.

R47.2 The verdicts (VERIFIED)
-----------------------------
  op 102 process-exec-interpreter -> node 1865 = TERMINAL flags 0x5 = **DENY**
                                      (1865 is the same deny leaf the profile
                                       uses for e.g. file-write-create under
                                       /AppleInternal)
  op 101 process-exec*            -> node 172: path-pattern denies, then
                                      container-required / no-container /
                                      no-sandbox entitlement checks, otherwise
                                      allow (why racoon-as-CrashHousekeeping ran
                                      in job 534)
  op 103 process-fork             -> 2636 = allow
  op 95  nvram-set                -> 2636 = **allow**
  op 94  nvram-get                -> 2636 = allow
  op 93  nvram-delete             -> 2636 = allow
  op 52  iokit-set-properties     -> 2636 = allow
Reachability of the verdict: Sandbox's mpo_vnode_check_exec = ops slot +0x810
= 0xfffffff007face28 (agrees with R46). It stores the cred at ctx+0x20 and calls
the evaluator 0xfffffff007fb1cec. The evaluator (0xfffffff007fb1d64-0xfffffff007fb1da0)
evaluates the PLATFORM profile for every subject whose cred is not the kernel's,
BEFORE and independently of any per-process profile; a platform deny is final.
So root, unsandboxed, launchd-spawned, grandchild - none of it matters.

Kernel flow for a shebang: exec_shell_imgact (0xfffffff007a2932c) returns -3,
exec_activate_image sets ip_scriptvp and re-runs mac_vnode_check_exec with
scriptvp != NULL -> Sandbox picks op 102 -> deny -> execve fails EACCES.
Expected syslog signature on a diagnostic boot:
  `Sandbox: launchd(1) deny(1) process-exec-interpreter /usr/sbin/nvram` (or the
  spawning daemon's name) plus launchd's spawn failure for the job. That is the
  line to look for in the archive of any of the 608-615 boots.

R47.3 nvram-set was never the problem (VERIFIED)
------------------------------------------------
- Platform profile: nvram-set / nvram-get / nvram-delete all allow (above).
- Sandbox's only in-kernel nvram evaluator is the get-property hook (slot 0xa70,
  0xfffffff007faed0c, op 0x5e nvram-get). The nvram-SET checker exists
  (0xfffffff007fa9870, with the "boot-args" token special case R41.5 saw, and
  its wrapper 0xfffffff007faedf0) but has **zero** callers, branches, adrp/adr
  refs or data pointers anywhere in the kernelcache - dead code. No
  mpo_iokit_check_nvram_set is registered on this build.
- IODTNVRAM::setProperty = 0xfffffff007bd7598: gate is only
  getOFVariablePerm(key): perm != UserWrite needs
  clientHasPrivilege(current_task,"root"); perm == KernelOnly needs kernel_task
  (that is the `com.apple.System.*` "privilege violation"); "aapl,panic-info"
  rejected; "boot-args" value capped at 0x25f. **No MAC call, no entitlement
  check, custom names accepted from any root process.**
- The AMFI code referencing `com.apple.private.security.restricted-nvram-
  variables.heritable` (0xfffffff007c99e70) is the entitlement->csflags mapper
  run at exec, not an NVRAM gate.
=> A root process that actually runs CAN write a custom NVRAM marker on the
   booted OS. The channel is fine. Nothing of ours has run.

R47.4 Correction to R46 item 3: XNU DOES split the shebang line into multiple argv (VERIFIED)
--------------------------------------------------------------------------------------------
exec_shell_imgact only SAVES the whole interpreter line (one copy into
ip_interp_buffer at imgp+0x98, 0xfffffff007a2953c-0xfffffff007a29574). The
tokenising happens later in exec_extract_strings' IMGPF_INTERPRET branch,
0xfffffff007a26de4-0xfffffff007a26f44: find token end at tab/space, NUL it
(0xfffffff007a26e90), copy it out as one user string, bump ip_argc
(0xfffffff007a26f3c), skip whitespace (0xfffffff007a26f10-f20), loop
(`cbnz x8, 0xfffffff007a26dec`). macOS/XNU behaviour, not Linux's. Moot now
that interpreter exec is denied, but recorded so it is not re-argued.

R47.5 What this kills, and what survives
----------------------------------------
DEAD on 13.4.8 (platform profile, not fixable by any file we can write):
  - every `#!` payload: /bin/sh shebang (R40.1, R42), CrashHousekeeping and
    DumpPanic shebangs (jobs 611-614), `#!/bin/df -h` harmlessness control
    (R40.3c), the "UDIF-as-script" construction (R37.4 b', R39.8, R43.7).
  - R24.1's "the script primitive is real" as a usable primitive. AMFI's hook
    cannot deny; Sandbox's does. R24.2 ("a script cannot reach native code")
    stands, trivially.
SURVIVES:
  - R3's substitution primitive: a byte-for-byte copy of a TRUST-CACHED Mach-O
    at any path execs (op 101 allows it; job 534 proved it). The payload must be
    a Mach-O Apple shipped and trust-cached, and it receives whatever argv the
    exec site passes.
  - the exec SITES found since: launchd cached jobs (argv fixed, R37.1),
    /sbin/fsck_apfs symlink (grandchild, must exit 0, pre-mount, R39.8/R40.3c),
    ReportCrash -> popen -> /bin/sh (argv = [sh, -c, <ExcDiagToolExtras cmd>],
    R42), wifivelocityd NSTask /bin/sh -c (R42.5), keybagd/seputil
    posix_spawn /bin/bash (R40.1, internal-gated?).
  - the NVRAM marker channel (R47.3) and the hdik/UDIF kernel bugs (R27/R33/R43).
THE REFRAMED PROBLEM: we need a trust-cached Mach-O that does something useful
when exec'd with the argv one of those sites gives it. For the popen sites that
argv is `["/bin/sh","-c","<string we choose via ExcDiagToolExtras>"]`.
  - NEVER a copy of nvram there: `-c` = clear all variables (R40.8 stands).
  - Candidates to audit for "-c <string>" semantics: every trust-cached binary
    whose getopt accepts -c, or which ignores unknown flags and acts on argv[2]
    as a path. hdik takes `<image>` positionally but rejects `-c`; needs a read.
    This is now a small, well-defined audit over the 578-entry trust cache.
  - For the launchd-job sites (argv = program path only), the useful binaries
    are the ones with hardcoded config paths (racoon /etc/racoon/racoon.conf -
    present on 13.4.8 per R42.7 - and pppd IF /etc/ppp/options is live, which
    R42.7 says it is not). racoon's `-f` is not reachable there.

R47.6 Why the diagnostic boot is still worth one cycle
------------------------------------------------------
Everything above is static. One `pymobiledevice3 syslog collect` taken 5+ min
after a boot with the job-614 plants still in place should show the
`deny(1) process-exec-interpreter` line. That turns a static verdict into a
hardware one and costs nothing we have not already spent four times.

R47.7 Tooling (in the container; copies committed to multipod/sbprof/)
----------------------------------------------------------------------
  kc.py      kernelcache helper: segments, VA<->file, funcstarts, capstone,
             adrp/add + data-pointer xrefs (threaded rebase: VA = 0xfffffff000000000
             | (raw & 0xffffffff) for this cache)
  sbprof.py  platform-profile parser (ops at 78, nodes at 376, strings at 21472)
  ops.json   the 146 operation names in kernel order
  R47-platform-profile-dump.txt  full decode of every op's tree
Re-run: `python3 -I sbprof_dump.py` prints the verdict table.

R47.8 Rules added
-----------------
- **No shebang payloads on 13.4.8, ever.** Platform profile denies
  process-exec-interpreter with no exception. Payloads are trust-cached
  Mach-O copies only.
- **When a MACF question comes up, decode the platform profile, not just a
  hook.** The profile is 43 KB and parses in a second with sbprof.py.
- A ramdisk (2024 Sandbox) verdict does not transfer to 13.4.8's Sandbox-1217;
  decode the profile from the kernel that will run.

---

## R49 - RECONCILIATION: the shebang DENY is the whole answer, my R46.0 and R45.5 are wrong, and the 17M61 surface is gone from the pod. 2026-11-27 01:25 PST

### R49.0 The null streak is SOLVED, and it is R48 [V]

R45.3 found that Sandbox's `mpo_vnode_check_exec` dispatches op **102
`process-exec-interpreter`** when `scriptvp` is set. R48 decoded the platform
profile and found op 102 maps to the **DENY terminal, unconditionally** - one of
only **two** DENY terminals in the entire profile - with no filter, no
entitlement and no path exception, applied to every process except the kernel.

**Therefore no `#!` script can execute on audioOS 13.4.8, as root or otherwise.**
Jobs 608-615 were dead before AMFI was ever consulted. R24.1's AMFI result was
correct and irrelevant.

**Dead, all of it:** R37.4(b) and (b'), R39.8's shebang note, R40.1's
`/bin/sh`-as-shebang, R42's chain as implemented, and the UDIF-as-script
construction. Every vehicle in jobs 608-615 was a shebang.

**And R45.2 is resolved NEGATIVE:** R48 reports ops 92-95
(`nvram*`/`nvram-delete`/`nvram-get`/`nvram-set`) as **ALLOW**, Sandbox's
nvram-set checker as dead code with zero callers, and `IODTNVRAM::setProperty`
as requiring root only for names outside `com.apple.System.*`. **The NVRAM
marker channel was never the problem.** My worry in R45.2 that the write leg
might be denied was reasonable on the evidence then and is now closed on better
evidence. The nulls were real nulls: nothing of ours ever ran.

### R49.1 *** RETRACTED: R46.0's "obliteration explains the nulls" *** [V]

R46.0 offered the self-obliteration loop as "a third explanation for every
null". **That was wrong** - R48 supplies the actual and sufficient cause, and it
is a static property of the build, not a state of the pod. The obliteration loop
is a real obstacle to a *stable test surface* (R47.1 gives its off switch) but it
explains none of the nulls. Keep R47.1; discard R46.0's causal claim.

### R49.2 *** RETRACTED: my shebang argv claim in R45.5/R46 *** [V]

R45.5 argued from a partial read of `exec_shell_imgact` that XNU passes the
interpreter **one** optional argument, and explicitly contradicted the parallel
reviewer's recollection that XNU splits on whitespace. **The reviewer was
right and I was wrong.** R48 locates the splitting in `exec_extract_strings`
(`0xfffffff007a26de4`-`f44`); `exec_shell_imgact` only *saves* the line, which
is why reading that function alone produced the wrong answer. Moot now that
shebangs cannot exec, but the methodological lesson is not: **I marked it [U]
and said not to design payloads on it, then still asserted the reviewer was
wrong.** A partial read is not grounds for contradicting someone.

### R49.3 *** THE 17M61 SURFACE IS GONE FROM THE POD. Both volumes are modern. *** [V]

Nic's reading was that the pod never successfully updates, and the log does
carry that as an open question. **The device disagrees, and this is not R24.0's
trap.** Job 620 mounted the boot snapshot read-only and measured it:

| measure | live `disk1s1` | snapshot `...2207559B` | 17M61 |
|---|---|---|---|
| `/usr/libexec` | 227 | **227** | 132 |
| LaunchDaemons | 299 | **299** | 185 |
| `launchd` bytes | 588,512 | **588,512** | 365,776 |
| `mrm.plist` | absent | **absent** | 256,299 |
| `xpc/launchd.plist` | 756,594 | **756,594** | n/a |
| `jetsamproperties.B238.plist` | n/a | **absent** | present |
| exclaves in `/usr/libexec` | 2 | **2** | 0 |

R24.0's situation was live=modern, snapshot=13.4.8, which is why it was
retracted at R24.7/R26. **Here both are modern, so there is no 13.4.8 on the pod
to boot.** With NVRAM's `ota-original-os-version 17M61` / `ota-os-version
24K157` / `ota-result success`, R47.0 stands.

**The one way Nic's reading can still be right:** we have not observed a boot
*since* the OTA. "Never successfully updates" could mean the installed modern
build fails to boot and the device loops or rolls back. That is untested and
costs one boot. It does not change the operative fact: **13.4.8 is no longer
installed, so nothing in R27-R48 is testable on this pod until it is restored.**

Job 619 note: its "snapshot: NONE" line was my bug - `tr` does not exist on this
ramdisk even with PATH exported, so the snapshot name parsed empty. Use
`grep -a 'com.apple.os.update' | head -1` and `sed`, as job 606 did. `sed`
exists; `tr` and `awk` do not.

### R49.4 What survives, and the revised order of work

**The surviving primitive is R3, and it was proven on hardware.** Op 101
`process-exec*` is `conditional(root 172)`, not denied, and job 534 ran racoon's
bytes from `/usr/libexec/CrashHousekeeping` as pid 35 from Apple's unmodified
cache. So: **a byte-for-byte copy of a trust-cached Mach-O at a path an exec
site hits still executes as root.** No shebang, no modification, no forged
signature.

The problem is now a bounded offline audit, not a hardware question: **which of
the 578 trust-cached Mach-Os does something useful given the argv the available
exec sites actually pass?**
- launchd cached jobs pass **argv[0] only** (R3.3: 0 of 183 passes a file path;
  16 of 183 pass anything at all, all flags/labels).
- `popen` sites pass `[sh, -c, <string>]`, and per R42.2 that string is
  selectable via `ExcDiagToolExtras` in domain `com.apple.CrashReporter`.
- So the useful binaries are those that read a **hardcoded** config path on the
  System volume (R3.2's list: `syslogd` + `/etc/asl.conf`, `pppd` +
  `/etc/ppp/options` - but note R42.7 inverted that one: `/private/etc/ppp` does
  **not** exist on 17M61 while `/etc/racoon/racoon.conf` does).

**Hard rule from R48: never place `nvram`'s bytes at `/bin/sh`** - the argv is
`[sh, -c, ...]` and `nvram -c` **clears every NVRAM variable**, `auto-boot`
included. That is a bench-recovery event, not a failed test.

Revised order:
1. **Offline, no pod:** the trust-cached-Mach-O/argv audit above. This is the
   whole critical path now and it needs no hardware.
2. **Restore to 13.4.8/17M61** (manual; the runner never restores). Assets at
   `~/homepod/homepodstuff/HomePod-13.4.8-17M61.ipsw` +
   `~/homepod/tickets/tickets/000024EA009A60A6/13.4.8-17M61.shsh2`.
3. **Before the first boot**, from the ramdisk: rename
   `/usr/libexec/mobile_obliterator` and `/usr/libexec/MSUEarlyBootTask`
   (R47.1 - both lack `RequireRun`/`RequireSuccess`, so absent is benign; keep
   the originals as `.nicsfix-orig`). Then plant the chosen trust-cached binary.
4. **Keep the pod off WiFi.** The OTA is what cost us the analysed build.

### R49.5 Rules added

- **No shebang payloads on audioOS 13.4.8, ever.** op 102 is an unconditional
  DENY in the platform profile (R48). Substitute a trust-cached Mach-O instead.
- **Never place `nvram`'s bytes at a `popen`/`system` exec site.** argv[1] is
  `-c`, which clears NVRAM including `auto-boot`.
- **`tr` and `awk` do not exist on the restore ramdisk; `sed` does.** Exporting
  PATH does not conjure them.
- **Do not contradict a reviewer from a partial read.** If a finding is marked
  [U], it is not strong enough to overturn someone else's claim either.
- **Measure the build in every job that draws a conclusion** - `/usr/libexec`
  count, `launchd` size, snapshot name. Both volumes changed under us tonight
  and four jobs' worth of reasoning assumed they had not.

