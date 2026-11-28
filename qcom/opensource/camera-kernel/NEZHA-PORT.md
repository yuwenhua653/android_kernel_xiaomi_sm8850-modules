# Nezha camera port: OS4.0.7.0.XPACNXM

## Source and scope

The zoom driver, SEM1218S firmware protocol and device-protection helper are
ported from [MiCode camera-kernel songyuan-w-oss](https://github.com/MiCode/vendor_qcom_opensource_camera-kernel/tree/798f548761f381b056f2e1fe615f9db930aa5c7e),
commit `798f548761f381b056f2e1fe615f9db930aa5c7e`.
Only CONFIG_TARGET_PRODUCT_NEZHA builds/registers the new drivers through
Kbuild.canoe. Existing QCOM command definitions and the generic sensor query
ABI are retained. Device-protection module parameters retain upstream defaults
(disabled); this port does not enable I2C-error masking.

Nezha factory camera.ko SHA-256:
`9c5f719297511f0e54c03dbe225acd1d179c2b83deb5fff8997dd5b7e2d39774`.
The stock sensor query writes zoom_slot_id at offset 40. Its zoom-info parser
rejects lengths <= 92, reads the firmware flags at offset 92, and copies the
64-byte name from offset 28. These match the imported 93-byte packed structure.
The generic query stays 40 bytes; Nezha CAM_QUERY_CAP returns 44 bytes.

The existing Nezha DT already has qcom,zoom, cell-index 3, CCI master 0,
shared clocks/GPIOs, supplies and the sensor zoom-src phandle. This change adds
the previously missing driver and parses that phandle into the HAL query.

## Integration changes

- Platform/I2C component registration, CRM zoom device ID, V4L2 entity type,
  zoom packet opcodes and capability query, with Nezha-only registration.
- CAM_ZOOM uses debug bit 40, preserving the newer QCOM CAM_WORKER bit 39.
- Optional upstream CCI debugfs and per-register diagnostic trace hooks are
  omitted; transport, power, request scheduling and firmware operations remain.
- Preserve the DT-parsed CCI master, validate cell-index before array access,
  release transport resources on unbind and clear stale driver pointers.
- Check declared command-buffer lengths/alignment before parsing HAL packets.
- Firmware loading checks file size and returns signed errno. Allocation and
  all update I/O failures release buffers; failed writes never proceed to CRC
  commit/reset. Device-reported update errors and version mismatch return EIO.
  Firmware binaries remain supplied by the matching vendor installation.
- Fix the common sensor resource helper to return the clock's PTR_ERR, including
  EPROBE_DEFER, instead of inspecting an unrelated regulator pointer.

## Verification on 2026-11-26

- ARM64 Clang 19, kernel 6.12.118, Canoe + Nezha configuration: complete camera.o
  compilation/link passed, including all new zoom and protection objects.
  No warnings/errors in the final incremental build.
- Real UAPI headers compile with size/offset assertions: 40/44-byte sensor
  queries, 8-byte zoom query, 93-byte zoom info, name offset 28, flag offset 92.
- Host tests extract the actual firmware routines and replace device services:
  200 I/O failure points, both allocation failures, missing/short firmware,
  CRC/version errors, successful update and skip paths pass ASan/UBSan.
  Allocation counters and firmware-reference counters balance on every path.
  LeakSanitizer cannot run under the host tracer; run here with:

  ```sh
  ASAN_OPTIONS=detect_leaks=0 python3 tools/test-nezha-zoom.py
  ```

This is not a full kernel build or modpost/signature/CRC qualification. No real
firmware update, camera probe, optical motion, image streaming, reopen or
multi-camera switching was tested. Keep these as hardware acceptance items.

## CSI AutoEQ / CRC recovery integration (2026-11-26)

The same official camera revision supplies the UMD command protocol and backup
EQ settings. Nezha now registers `/sys/csiphy_umd_paras/csiphy_umd_paras` and
implements commands 0x1000 through 0x1005: CRC divisor, CRC-event full recovery,
AutoEQ enable, per-PHY retry state, backup selection and CSID error classification.
Command 0x1005 uses the upper 32 bits for fatal errors and the lower 32 bits for
recoverable errors. Zero, overlapping and unknown masks fail. Unlike a wholesale
replacement, unspecified errors retain their existing classification. RX masks
are local snapshots, preserve the subscribed IRQ union and map only events
present in the selected hardware table. The manager applies the same policy to
logical errors; this does not add new path IRQ sources. Unknown commands and
malformed values fail.

Changes relative to that source:

- Serialize sysfs/IRQ updates with a spinlock, validate all PHY indices and
  command ranges, and unwind failed sysfs creation. No writable module globals.
- Choose EQ once per PHY configuration, then apply the same choice to every
  lane. CRC retry markers cannot change the choice halfway through the lanes.
- Associate forced full recovery with the current CSID CRC event, avoiding a
  shared sticky flag that could affect another camera's unrelated error.
- Retain all 29 OS4.0.7 default rates. The 3.0 Gsps backup uses the 12-register
  OS4.0.7 table; omit the later songyuan common write at 0x108c, whose addition
  is not supported by the matching factory table. Do not substitute a new
  kernel's register programming merely because it has the same device name.
- Compile/register the sysfs provider only for CONFIG_TARGET_PRODUCT_NEZHA.
  Other products select default choice zero and retain their CRC fallback.

Validation: complete ARM64 camera.o compilation/link passed. The actual compiled
ELF matches the factory's 29 baseline rates, PHY/variant references, nine
register arrays (including backup EQ), and lane offsets. The host test extracts
the actual CSI source and passes ASan/UBSan for parsing/ranges, allocation and
initialization cleanup, backup priority/clamping, retry wrap, invalid PHY and
eight concurrent PHYs with 10,000 CRC/retry iterations each:

```sh
ASAN_OPTIONS=detect_leaks=0 python3 tools/test-nezha-csi.py
```

These are host checks, not on-device AutoEQ/IRQ or HAL acceptance. Remaining:
the remaining OEM HAL/OIS/actuator contracts, and real probe/firmware,
zoom motion, streaming, reopen, multi-camera switching and suspend/resume.

The host test also checks 0x1005 CRC/FIFO reclassification, overlapping/unknown
masks, absent hardware events and unchanged IRQ subscription. Camera compilation
is separate from real interrupt delivery, mixed-error recovery and HAL testing.

## 2026-11-27: flash query compatibility and OIS transfer failures

References reviewed:
- MiCode camera `songyuan-w-oss`, commit
  `798f548761f381b056f2e1fe615f9db930aa5c7e`: public U-series camera commands,
  OIS/actuator and flash ABI. The Nezha flash query is 8 bytes: cmd_type at 3,
  query_current_ma at 4. Generic ABI remains 12 bytes, current at 6.
- MiCode camera `xuanyuan-v-oss`, commit
  `be696c290bb4d6276810613c6b35e39e0ba5a366`: older Ultra OIS implementation
  reviewed for comparison; its chip-specific firmware/registers are not copied.
- Community https://github.com/mweinbach/lineage-os-xiaomi17u,
  `docs/camera-baseline.md`: the document describes OS3 xiaomi.eu APK/static
  dependencies, explicitly not a working Evolution X camera port. Useful for
  separating app/HAL requirements from drivers; not evidence of OSS OIS support.

Changes:
- Nezha accepts the official 8-byte current query using explicit descriptor
  length and cmd_type, alongside the unchanged generic 12-byte query. Errors
  and absent LED providers leave output untouched. Descriptor bounds apply to
  PMIC command parsing; spare allocation bytes are not part of a command.
- OIS V2 validates the parameter table before reading entries, then subtracts
  each payload length from remaining bytes. The version-data cursor advances
  even if those settings have already been parsed (both parser versions).
- Validate firmware names, data width, operation, sizes and register arithmetic
  before transfer. Handle the final partial chunk and unaligned word data.
  Propagate I/O errors and stop before finalization; reject out-of-range firmware
  slices without unsigned underflow. A failed version read no longer triggers
  a blind download. No embedded firmware or new flash-write protocol added.

Run `python3 tools/test-nezha-camera-command-paths.py` from camera-kernel.
Both generic/Nezha host C builds pass ASan/UBSan with fault injection, exact-size
truncated allocations, firmware chunk and ownership assertions. Kernel I/O is
modeled. This revision has no full ARM64 camera/module build or device pass.

Still open: 64-byte OEM OIS names/extended opcode ABI, SEM1218S OIS firmware
protocol (separate from the integrated zoom), private OIS/actuator park and
voltage commands, complete stock HAL contract, open/reopen/multi-camera/flash
hardware tests. No claims about image quality or stabilization are made.

## OIS, actuator voltage and parking transactions (2026-11-28)

The same pinned MiCode revision `798f548761f381b056f2e1fe615f9db930aa5c7e`
supplies the OEM OIS slave-info layout, SEM1218S transport, actuator voltage
command and OEM parking opcodes. This batch makes the following integration:

- Only Nezha uses 64-byte OIS names and the 29-byte extended opcode. Packed
  slave-info is 101 bytes (opcode offset 72); generic builds retain the original
  32-byte name, 16-byte opcode and 56-byte slave-info. Reject short declared
  buffers, missing name terminators and unsupported flags before mutation.
- SEM1218S uses the official 48 KiB image, update registers, chunk sizes and CRC
  polynomial. All transfer errors abort before CRC commit/reset; device error
  and post-reset version are checked. Respect HAL's firmware-update opt-in.
  Firmware binaries are still provided by the matching vendor installation;
  none are added here. The fw_mem_store hint is accepted but does not add a
  persistent firmware cache.
- Actuator SET_VOLTAGE opcode 6 / command type 19 parses packed 8-byte entries.
  Validate the complete list, pin types, regulators, supported voltage and old
  voltage before any write; release imported memory before regulator calls.
  Roll back the failed entry and preceding entries, retain the first errno.
  Voltages are HAL requests subject to regulator constraints, not invented DT
  replacements or raised limits.
- OEM actuator park opcode 5 and OIS park opcode 4 parse into owned local I2C
  lists, apply the sequence, attempt power-down even after movement failure,
  retain the first error, and free the lists on every path. Reject empty input
  and overlapping generic actuator parking. State changes follow power-down
  acknowledgment.
- Generic actuator park enqueue failure releases partial settings and completes
  waiters. Its worker completes on every path and retains power sequences after
  a failed power-down. Shutdown waits for a running park operation before freeing
  those sequences, instead of ignoring a 100 ms timeout.

OEM parking deliberately executes synchronously under the existing device mutex,
not in the official private background thread. This preserves ownership and
cleanup, but HAL timeout behavior, shared CCI/rail sequencing, mechanical travel,
close/reopen and simultaneous devices require hardware verification. No physical
firmware programming, optical movement or camera streaming was performed.

Seven host scripts cover actual UAPI headers (generic and Nezha), zoom, CSI,
command bounds, OIS SEM1218S, actuator voltage and parking. The new OIS test injects
196 transfer failures and checks a separately calculated CRC; voltage and parking
tests inject parser, regulator, movement and power-down failures. ASan/UBSan are
used for executable host models; LeakSanitizer is disabled under the host tracer.
Exact source hashes, build commands and results accompany the kernel's
`android/nezha-native/mca-wireless-camera-validation-20261128.json`.

Final build result: full kernel Image and 401 in-tree modules passed strict
modpost. The hw_fence, synx, securemsm and mmrm dependency modules and camera.ko
then passed ARM64 Kbuild and strict external-module modpost against the same
Module.symvers. No warning/error occurred in the final camera build; securemsm
prints four pre-existing qseecom header deprecation notices. Local validation
uses LLVM 19.1.7 with CFI/MODVERSIONS; Rust, BTF and automatic module signing
are disabled only in the output configuration. This is not signed production
DLKM/boot-image qualification or hardware acceptance.

## OS4.0.7 session release and shared CCI power

Nezha sensor, zoom, OIS and actuator power transitions now use a lock for their
physical CCI device/master pair. The four-device, three-master table follows the
published Nezha camera source. Power changes on different masters may proceed
concurrently. The HAL session mutex still owns each device's command sequence.

A short userspace copy now fails acquisition. A failed handle copy-out unwinds
the handle. Release checks for a live CRM link before powering down, retains a
failed power-down or handle destruction for retry, and frees actuator power
settings after parking or an acquire-only session. OIS releases its parsed
firmware/version data before the next acquire. Nezha actuator park handles up to
20 moves and the OEM settling delays. OIS park observes the OEM 100-tick budget.
A failed poll now terminates the movement and propagates the error.

Eight camera host tests exercise these entry points, staged failures and
same/different-master locking. ARM64 Kbuild linked camera.ko against the kernel
and its external dependencies with strict modpost. Mechanical motion, HAL timing,
camera switching and flash still require a phone running the matching firmware.
