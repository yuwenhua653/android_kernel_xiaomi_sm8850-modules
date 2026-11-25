#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check production CNSS system suspend failure rollback without firmware mocks of success."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--modules-root',type=Path,required=True)
p.add_argument('--source',type=Path)
a=p.parse_args()
s=(a.source or a.modules_root/'qcom/opensource/wlan/platform/cnss2/pci.c').read_text()
m=re.search(r'static int cnss_pci_suspend\(struct device \*dev\)',s)
start=s.index('{',m.end());end=start+1;depth=1
while depth:
 depth+=(s[end]=='{')-(s[end]=='}');end+=1
fn=s[m.start():end]
code=r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#include <stdio.h>
#define cnss_pr_err(...) ((void)0)
#define cnss_pr_dbg(...) ((void)0)
#define cnss_pr_info(...) ((void)0)
#define CNSS_POWER_CTRL_SCMI 1
#define CNSS_MHI_INIT 0
#define CNSS_IN_COLD_BOOT_CAL 0
#define CNSS_DRIVER_LOADING 1
#define CNSS_DRIVER_UNLOADING 2
#define CNSS_DRIVER_IDLE_RESTART 3
#define CNSS_DRIVER_IDLE_SHUTDOWN 4
#define CNSS_IN_SUSPEND_RESUME 5
#define DISABLE_DRV 0
#define test_bit(n,p) (!!(*(p)&(1UL<<(n))))
#define set_bit(n,p) (*(p)|=1UL<<(n))
#define clear_bit(n,p) (*(p)&=~(1UL<<(n)))
struct device {int unused;};
struct pci_dev {struct device dev;};
struct cnss_plat_data {int pwr_ctrl_mode,rc_pm_control; unsigned long driver_state;struct {unsigned long quirks;}ctrl_params;};
struct cnss_pci_data {struct cnss_plat_data *plat_priv;int mhi_state,drv_supported,drv_connected_last,disable_pc,bus_lock;};
static struct cnss_plat_data plat;
static struct cnss_pci_data priv;
static struct pci_dev pci;
static int powered,driver_rc,bus_rc,save_rc,connected;
static int suspended,resumed,bus_calls,save_calls,monitor_calls;
#define to_pci_dev(d) (&pci)
#define cnss_get_pci_priv(p) (&priv)
static bool cnss_is_device_powered_on(struct cnss_plat_data *p) {(void)p;return powered;}
static bool cnss_should_suspend_pwroff(struct pci_dev *p) {(void)p;return true;}
static int cnss_suspend_pci_link(struct cnss_pci_data *p) {(void)p;return 0;}
static void cnss_power_off_device(struct cnss_plat_data *p) {(void)p;}
static int cnss_pci_get_drv_connected(struct cnss_pci_data *p) {(void)p;return connected;}
static int cnss_pci_suspend_driver(struct cnss_pci_data *p) {(void)p;suspended++;return driver_rc;}
static int cnss_pci_resume_driver(struct cnss_pci_data *p) {(void)p;resumed++;return 0;}
static int cnss_pci_suspend_bus(struct cnss_pci_data *p) {(void)p;bus_calls++;return bus_rc;}
static int pci_save_state(struct pci_dev *p) {(void)p;save_calls++;return save_rc;}
static void cnss_pci_set_monitor_wake_intr(struct cnss_pci_data *p,bool v) {(void)p;assert(!v);monitor_calls++;}
static void mutex_lock(int *p) {assert(!*p);*p=1;}
static void mutex_unlock(int *p) {assert(*p);*p=0;}
'''
code+=fn+r'''
static void reset(void) {
 plat=(struct cnss_plat_data){.rc_pm_control=1};
 priv=(struct cnss_pci_data){.plat_priv=&plat,.mhi_state=1,.drv_supported=1};
 powered=connected=1;driver_rc=bus_rc=save_rc=0;
 suspended=resumed=bus_calls=save_calls=monitor_calls=0;
}
int main(void) {
 const int failures[]={-ENOMEM,-EIO,-EBUSY};int cases=0;
 for(unsigned i=0;i<sizeof(failures)/sizeof(*failures);i++) {
  reset();priv.disable_pc=1;save_rc=failures[i];
  assert(cnss_pci_suspend(&pci.dev)==save_rc);
  assert(suspended==1&&resumed==1&&save_calls==1&&!bus_calls&&!monitor_calls);
  assert(!test_bit(CNSS_IN_SUSPEND_RESUME,&plat.driver_state)&&!priv.drv_connected_last);cases++;
  reset();bus_rc=failures[i];
  assert(cnss_pci_suspend(&pci.dev)==bus_rc);
  assert(suspended==1&&resumed==1&&bus_calls==1&&!save_calls&&!priv.bus_lock);cases++;
  reset();driver_rc=failures[i];
  assert(cnss_pci_suspend(&pci.dev)==driver_rc);
  assert(suspended==1&&!resumed&&!bus_calls&&!save_calls);cases++;
 }
 for(int disable=0;disable<2;disable++) {
  reset();priv.disable_pc=disable;assert(!cnss_pci_suspend(&pci.dev));
  assert(suspended==1&&!resumed&&monitor_calls==1);
  assert(save_calls==disable&&bus_calls==!disable);
  assert(test_bit(CNSS_IN_SUSPEND_RESUME,&plat.driver_state));cases++;
 }
 reset();connected=0;assert(cnss_pci_suspend(&pci.dev)==-EAGAIN);assert(!suspended);cases++;
 reset();set_bit(CNSS_DRIVER_LOADING,&plat.driver_state);
 assert(cnss_pci_suspend(&pci.dev)==-EAGAIN);assert(!suspended);cases++;
 reset();powered=0;assert(!cnss_pci_suspend(&pci.dev));assert(!suspended);cases++;
 printf("PASS: %d CNSS suspend rollback, success and unchanged veto cases\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';e=Path(d)/'test';c.write_text(code)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=undefined',str(c),'-o',str(e)],check=True)
 subprocess.run([str(e)],check=True)
