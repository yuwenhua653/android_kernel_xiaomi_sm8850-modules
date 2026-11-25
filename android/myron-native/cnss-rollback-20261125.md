# CNSS system-suspend rollback

When the host-driver suspend has succeeded, `disable_pc && rc_pm_control`
uses `pci_save_state()`. If that operation fails, the old `clear_flag` jump
returned without undoing the driver's suspend. Route it through the existing
`resume_driver` unwind instead. Preserve the error and all DRV, firmware,
loading/unloading and host-driver suspend vetoes.

`tests/test_cnss_suspend_rollback.py --modules-root <modules>` passes 14 UBSan
cases; pre-change `pci.c` fails the missing-resume assertion. The modified
`cnss2/pci.o` compiles for ARM64 with the native Myron config, Clang 19.1.7,
CFI and MODVERSIONS. This is not complete external-module modpost or device
suspend qualification, and does not establish the cause of earlier `-11` logs.

Paired kernel checkpoint:
[232f1e875744](https://github.com/yuwenhua653/android_kernel_xiaomi_sm8850/commit/232f1e8757440841e61783f4831dc5ad1b46f279).
Its `android/myron-native/runtime-gap-followup-20261125.md` tracks remaining
thermal/charging gaps. Libperfmgr is deferred; this is not a compile/flash request.
