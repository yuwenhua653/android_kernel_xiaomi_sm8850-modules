#!/usr/bin/env python3
"""Exercise the production periodic IPA bandwidth entry point before pipe setup."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modules-root', type=Path, required=True)
    args = parser.parse_args()
    source = (args.modules_root / 'qcom/opensource/wlan/qca-wifi-host-cmn/'
              'ipa/core/src/wlan_ipa_main.c').read_text()
    function = source[source.index('QDF_STATUS ipa_rm_set_perf_level('):
                      source.index('\nvoid ipa_uc_info(')]
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef int QDF_STATUS;
#define QDF_STATUS_SUCCESS 0
#define QDF_STATUS_E_FAILURE 1
#define ipa_debug(...) ((void)0)
#define ipa_err(...) ((void)0)
struct wlan_objmgr_psoc { int unused; };
struct wlan_objmgr_pdev { struct wlan_objmgr_psoc *psoc; };
struct wlan_ipa_priv { bool config; bool uc_load_handled; };
static struct wlan_ipa_priv ctx, *available = &ctx;
static bool enabled = true, ready = true;
static int calls, vote_result;
static struct wlan_objmgr_psoc *wlan_pdev_get_psoc(struct wlan_objmgr_pdev *p) {
 return p->psoc;
}
static bool ipa_config_is_enabled(void) { return enabled; }
static bool ipa_cb_is_ready(void) { return ready; }
static struct wlan_ipa_priv *ipa_psoc_get_priv_obj(struct wlan_objmgr_psoc *p) {
 (void)p; return available;
}
static bool wlan_ipa_uc_is_enabled(bool config) { return config; }
static int wlan_ipa_set_perf_level(struct wlan_ipa_priv *p, uint64_t tx, uint64_t rx) {
 assert(p == &ctx && tx == 40 && rx == 60); calls++; return vote_result;
}
'''
    cases = r'''
int main(void) {
 struct wlan_objmgr_psoc psoc;
 struct wlan_objmgr_pdev pdev = { &psoc };
 ctx.config = true;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 0 && calls == 0);
 ctx.uc_load_handled = true;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 0 && calls == 1);
 vote_result = 17;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 17 && calls == 2);
 ctx.uc_load_handled = false;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 0 && calls == 2);
 ctx.config = false;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 17 && calls == 3);
 ready = false;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 0 && calls == 3);
 ready = true; available = NULL;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == QDF_STATUS_E_FAILURE && calls == 3);
 enabled = false;
 assert(ipa_rm_set_perf_level(&pdev, 40, 60) == 0 && calls == 3);
 puts("PASS: production IPA periodic entry; pre-connect; ready; reset; legacy; real errors");
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c, exe = Path(tmp) / 'test.c', Path(tmp) / 'test'
        c.write_text(harness + function + cases)
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                        str(c), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == '__main__':
    main()
