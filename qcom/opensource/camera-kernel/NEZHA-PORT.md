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

## Remaining official-source work

- CSI PHY AutoEQ/backup-EQ requires the HAL sysfs/control interface and CSID
  error reporting to be ported together. Keep the existing stock-verified
  default -1 tables until that path is reviewed. The new upstream backup table
  also writes a common register; it is not a drop-in default table replacement.
- Audit the remaining OEM camera commands (including OIS/actuator behavior)
  against the OS4.0.7 HAL ABI rather than replacing the entire newer UAPI file.
