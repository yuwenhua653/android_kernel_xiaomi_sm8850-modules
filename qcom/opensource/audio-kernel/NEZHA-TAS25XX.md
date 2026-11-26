# Nezha TAS25xx port

Source: TI UDA_0.0.20_K6.1, GPL-2.0, from Google's public amplifier repository:
https://android.googlesource.com/kernel/google-modules/amplifiers/+/ad7b4721f9fcea714dd0e36f0bfbc1a2cc07b641/tas25xx/

OS4.0.7's module identifies itself as UDA_0.0.21_7_K6.1. This port is not a claim
that all private changes in that version have been recovered.

`Kbuild.canoe` builds `tas25xx_dlkm` for CONFIG_TARGET_PRODUCT_NEZHA. The card
resolves the enabled `ti,tas25xx` node, and connects both Primary TDM directions
to `tas25xx ASI1`, matching the stock machine module's relocations. Existing DT
provides addresses 0x4a/0x48, reset GPIOs 54/56, IRQ 47 and receiver GPIO 174.
The receiver mixer control is `Enable RCV Pin Control` (0=sleep, 1=active).
No Linux I2C adapter number is hardcoded. Other product links are unchanged.

The port uses per-channel managed I2C clients/regmaps, propagates probe deferral,
rejects duplicate addresses/instances, and bounds firmware-worker and IRQ/work
lifetime. Probe/control failures are reported. Firmware is loaded synchronously
inside the existing worker, rather than through a detached completion callback.
The firmware parser prevalidates all block lengths, commands, counts, names,
channel count and indexes before allocating or retaining data pointers. Partial
allocations are unwound; malformed input does not reach register programming.

## Firmware contract

- Name: `tismartpa_driver_tuning.bin`; stock path `/odm/firmware/`.
- Size: 12631 bytes.
- SHA-256: `03ad1ce1e80b7ba9287d32711f245648280c4592c384f95b6174e7873e008680`.
- Source: China OS4.0.7.0.XPACNXM OTA, selected ODM operations 0/59/1516/1519
  individually checked against payload SHA-256. No full ODM checksum claim.
- Version 7, two channels, four profiles, 16 controls, 19 interrupt entries per
  channel, empty optional DFREG blocks. Tuning reference addresses 0x48/0x4b do
  not override the board DT's actual I2C clients.

The ROM vendor package already lists this ODM file. Its runtime availability via
firmware loader/ueventd must still be tested. No stock binary is distributed here.
Factory misc/register-debug interfaces and the old QDSP6 AFE algorithm backend
are not enabled. Basic ALSA paths remain; OEM calibration/debug user-space
contracts require separate evidence before enabling those transports.

## Reproducible host validation

Run from this audio-kernel directory (C compiler with ASan/UBSan required):

```sh
python3 tools/test-tas25xx-bin.py /path/to/tismartpa_driver_tuning.bin
python3 tools/test-tas25xx-parser.py /path/to/tismartpa_driver_tuning.bin
python3 tools/test-nezha-tas-links.py
```

Tests use actual production parsing/link code, not copied substitutes. They cover
all firmware truncations and 20000 mutations, all 92 stock-parser allocation
failure points with explicit allocation accounting, profile bounds and OF
reference cleanup. LeakSanitizer is disabled due to the host tracer restriction.
These checks do not exercise physical I2C, ASoC probe/unbind, IRQ delivery,
DSP speaker protection, playback/capture, temperature or suspend/resume.


Full host validation also built `tas25xx_dlkm.ko`, `machine_dlkm.ko` and all other
selected audio modules against the same 6.12.118 Module.symvers. Whole-module
modpost and imported symbol CRC checks passed. The host used Clang 19 and C
Binder; this is not an Android production-toolchain or hardware qualification.
