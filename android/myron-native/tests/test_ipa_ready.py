#!/usr/bin/env python3
"""Exercise production uC-ready publication, notification and stop ordering."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--modules-root', type=Path, required=True)
    a = p.parse_args()
    source = (a.modules_root/'qcom/opensource/wlan/qca-wifi-host-cmn/ipa/core/src/wlan_ipa_core.c').read_text()
    start = source.index('static void wlan_ipa_uc_loaded_handler(struct wlan_ipa_priv *ipa_ctx);')
    body = source[start:source.index('\nstruct wlan_ipa_priv *wlan_ipa_get_obj_context', start)]
    pre = r'''
#include <assert.h>
#include <stdbool.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
struct work {bool pending;};
struct wlan_ipa_priv {
 pthread_mutex_t uc_ready_lock,ipa_lock;
 int deinit_in_prog;
 bool uc_ready_seen,uc_ready_work_enabled,uc_loaded,uc_op_work_enabled;
 struct work uc_ready_work;
 int calls;
};
#define ipa_info(...) ((void)0)
#define ipa_err(...) ((void)0)
#define qdf_mutex_acquire(p) assert(pthread_mutex_lock(p)==0)
#define qdf_mutex_release(p) assert(pthread_mutex_unlock(p)==0)
#define qdf_spin_lock_irqsave qdf_mutex_acquire
#define qdf_spin_unlock_irqrestore qdf_mutex_release
#define qdf_atomic_read(p) __atomic_load_n(p,__ATOMIC_SEQ_CST)
#define qdf_atomic_set(p,n) __atomic_store_n(p,n,__ATOMIC_SEQ_CST)
static bool recovering;
static bool qdf_is_recovering(void){return recovering;}
static bool ipa_cb_is_ready(void){return true;}
static void qdf_sched_work(int id,struct work *w){(void)id;w->pending=true;}
static void qdf_cancel_work(struct work *w){w->pending=false;}
/* This test verifies dispatch, not the firmware/setup implementation. */
static void wlan_ipa_uc_loaded_handler(struct wlan_ipa_priv *ctx){
 assert(!ctx->deinit_in_prog);ctx->calls++;ctx->uc_loaded=true;
}
'''
    tests = r'''
static void init(struct wlan_ipa_priv *c){
 memset(c,0,sizeof(*c));assert(!pthread_mutex_init(&c->uc_ready_lock,NULL));
 assert(!pthread_mutex_init(&c->ipa_lock,NULL));
}
static void fini(struct wlan_ipa_priv *c){
 assert(!pthread_mutex_destroy(&c->uc_ready_lock));
 assert(!pthread_mutex_destroy(&c->ipa_lock));
}
static void drain(struct wlan_ipa_priv *c){
 if(c->uc_ready_work.pending){c->uc_ready_work.pending=false;wlan_ipa_uc_ready_work(c);}
}
static int cases;
/* Exhaust all sequences of early/duplicate notification, publish, run and
 * stop. The model is independent of work-list layout and allocators. */
static void sequence(int code,int length){
 struct wlan_ipa_priv c;init(&c);
 bool seen=false,enabled=false,closing=false,pending=false;
 int expected_calls=0;
 for(int n=0;n<length;n++,code/=4){
  switch(code%4){
  case 0:
   wlan_ipa_uc_loaded_uc_cb(&c);
   if(!closing){seen=true;if(enabled)pending=true;}break;
  case 1:
   wlan_ipa_uc_ready_start(&c);enabled=true;
   if(seen && !closing)pending=true;
   break;
  case 2:
   drain(&c);if(pending && !closing)expected_calls++;pending=false;break;
  case 3:
   wlan_ipa_uc_ready_stop(&c);closing=true;enabled=false;pending=false;break;
  }
  assert(c.uc_ready_seen==seen && c.uc_ready_work_enabled==enabled);
  assert(c.uc_ready_work.pending==pending && c.calls==expected_calls);
 }
 wlan_ipa_uc_ready_stop(&c);fini(&c);cases++;
}
static void *notify(void *p){wlan_ipa_uc_loaded_uc_cb(p);return NULL;}
static void *publish(void *p){wlan_ipa_uc_ready_start(p);return NULL;}
int main(void){
 for(int n=0;n<4096;n++)sequence(n,6);
 for(int n=0;n<256;n++){
  struct wlan_ipa_priv c;pthread_t a,b;init(&c);
  assert(!pthread_create(&a,NULL,notify,&c));
  assert(!pthread_create(&b,NULL,publish,&c));
  assert(!pthread_join(a,NULL));assert(!pthread_join(b,NULL));
  assert(c.uc_ready_work.pending && !c.uc_loaded);
  wlan_ipa_uc_loaded_uc_cb(&c); /* duplicate while work is pending */
  assert(!c.uc_loaded);drain(&c);assert(c.calls==1);
  wlan_ipa_uc_ready_stop(&c);wlan_ipa_uc_loaded_uc_cb(&c);
  assert(!c.uc_ready_work.pending);fini(&c);cases++;
 }
 struct wlan_ipa_priv c;init(&c);wlan_ipa_uc_ready_start(&c);
 recovering=true;wlan_ipa_uc_loaded_uc_cb(&c);drain(&c);assert(!c.calls);
 recovering=false;wlan_ipa_uc_loaded_uc_cb(&c);drain(&c);assert(c.calls==1);
 wlan_ipa_uc_ready_stop(&c);fini(&c);cases++;
 wlan_ipa_uc_loaded_uc_cb(NULL);
 printf("PASS: %d IPA ready ordering cases, including 256 concurrent publish/notify pairs\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as d:
        c, exe = Path(d)/'test.c', Path(d)/'test'
        c.write_text(pre+body+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                        '-fsanitize=undefined','-pthread',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    main()
