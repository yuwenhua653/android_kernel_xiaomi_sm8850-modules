#!/usr/bin/env python3
"""Fault-inject the production IPA uC initializer and check resource unwinding."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--modules-root', type=Path, required=True)
    p.add_argument('--source', type=Path)
    a = p.parse_args()
    base = a.modules_root/'qcom/opensource/wlan/qca-wifi-host-cmn/ipa/core'
    source = (a.source or base/'src/wlan_ipa_core.c').read_text()
    start = source.index('QDF_STATUS wlan_ipa_uc_ol_init(')
    body = source[start:source.index('\n/**', start)]
    start = source.index('QDF_STATUS wlan_ipa_uc_ol_deinit(')
    body += source[start:source.index('\n/**', start)]
    header = (base/'inc/wlan_ipa_priv.h').read_text()
    enum = re.search(r'enum wlan_ipa_uc_op_code \{.*?\};', header, re.S)[0]
    pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
typedef int QDF_STATUS;
typedef void *qdf_device_t;
#define QDF_STATUS_SUCCESS 0
#define QDF_STATUS_E_FAILURE 1
#define QDF_STATUS_E_NOMEM 2
#define QDF_IS_STATUS_ERROR(s) ((s)!=0)
#define WLAN_IPA_MAX_SESSION 8
#define WLAN_IPA_MAX_IFACE 4
#define WLAN_IPA_MSG_LIST_SIZE_MAX 16
#define WLAN_IPA_FLAG_MSG_USES_LIST 1
#define WLAN_IPA_STATE_PIPE_CONNECTION_DONE 3
#define WLAN_IPA_STATE_DEINIT 0
#define IPA_DEF_PDEV_ID 0
#define ipa_err(...) ((void)0)
#define ipa_debug(...) ((void)0)
#define ipa_log_err(...) ((void)0)
#define ipa_log_debug(...) ((void)0)
#define ipa_log_info(...) ((void)0)
'''
    mocks = r'''
struct msg_elem {int value;};
struct op_msg_list {int lock,list_size;struct msg_elem *entries;};
struct work {int ready;};
struct uc_op_work_struct {
 void *osdev,*msg,*ipa_priv_bp;struct op_msg_list *msg_list;int flag;struct work work;
};
struct wlan_ipa_priv {
 int config,dp_soc,ipa_init_state,tx_pipe_handle,rx_pipe_handle,hdl;
 int deinit_in_prog,ipa_lock;
 bool uc_loaded,uc_load_handled;
 uint8_t vdev_to_iface[WLAN_IPA_MAX_SESSION];
 bool vdev_offload_enabled[WLAN_IPA_MAX_SESSION],disable_intrabss_fwd[WLAN_IPA_MAX_SESSION];
 struct uc_op_work_struct uc_op_work[WLAN_IPA_UC_OPCODE_MAX];struct work mcc_work;
};
static int allocations,alloc_call,fail_alloc,locks,registered,setup_error,map_error;
static int created_work;
static int connected,disconnects,sys_teardown,resource_error,cases;
static void *qdf_mem_malloc(size_t n) {
 if(++alloc_call==fail_alloc)return NULL;
 void *p=calloc(1,n);assert(p);allocations++;return p;
}
static void qdf_mem_free(void *p) {if(p){assert(allocations>0);allocations--;free(p);}}
static void qdf_spinlock_create(int *p){assert(!*p);*p=1;locks++;}
static void qdf_spinlock_destroy(int *p){assert(*p==1);*p=0;locks--;}
static void qdf_create_work(int id,struct work *w,void (*cb)(void *),void *arg){
 (void)id;(void)cb;(void)arg;assert(!w->ready);w->ready=1;created_work++;
}
static void qdf_cancel_work(struct work *w){assert(w->ready==1);w->ready=0;}
static void wlan_ipa_uc_fw_op_event_handler(void *p){(void)p;}
static void wlan_ipa_uc_op_event_handler(void *p){(void)p;}
static bool wlan_ipa_uc_is_enabled(int c){return c&1;}
static bool wlan_ipa_uc_sta_is_enabled(int c){return c&2;}
static int cdp_ipa_get_resource(int soc,int id){(void)soc;(void)id;return resource_error;}
static int wlan_ipa_reg_flt_cbs(struct wlan_ipa_priv *p){(void)p;return 0;}
static int wlan_ipa_wdi_setup(struct wlan_ipa_priv *p,void *dev){
 (void)p;(void)dev;if(setup_error)return setup_error;connected++;return 0;
}
static int cdp_ipa_tx_buf_smmu_mapping(int soc,int id,const char *fn,int line){
 (void)soc;(void)id;(void)fn;(void)line;return map_error;
}
static int __attribute__((unused)) cdp_ipa_cleanup(int soc,int id,int tx,int rx,int hdl){
 (void)soc;(void)id;(void)tx;(void)rx;(void)hdl;
 assert(connected==1);connected--;disconnects++;return 0;
}
static void wlan_ipa_teardown_sys_pipe(struct wlan_ipa_priv *p){(void)p;sys_teardown++;}
static void cdp_ipa_set_doorbell_paddr(int soc,int id){(void)soc;(void)id;}
static void wlan_ipa_init_metering(struct wlan_ipa_priv *p){(void)p;}
static int wlan_ipa_init_perf_level(struct wlan_ipa_priv *p){(void)p;return 0;}
static void cdp_ipa_register_op_cb(int soc,int id,void (*cb)(void *),void *p){
 (void)soc;(void)id;(void)cb;(void)p;registered++;
}
static void wlan_ipa_uc_disable_pipes(struct wlan_ipa_priv *p,bool force){(void)p;(void)force;}
static void cdp_ipa_deregister_op_cb(int soc,int id){(void)soc;(void)id;assert(registered==1);registered--;}
#define qdf_atomic_set(p,n) (*(p)=(n))
#define qdf_mutex_acquire(p) (++*(p))
#define qdf_mutex_release(p) (--*(p))
static void cdp_ipa_iounmap_doorbell_vaddr(int soc,int id){(void)soc;(void)id;}
static int cdp_ipa_tx_buf_smmu_unmapping(int soc,int id,const char *fn,int line){
 (void)soc;(void)id;(void)fn;(void)line;return 0;
}
static void wlan_ipa_cleanup_pending_event(struct wlan_ipa_priv *p){(void)p;}
QDF_STATUS wlan_ipa_uc_ol_deinit(struct wlan_ipa_priv *p);
static void assert_unwound(struct wlan_ipa_priv *p){
 assert(!allocations && !locks && !registered && !connected);
 for(int i=0;i<WLAN_IPA_UC_OPCODE_MAX;i++){
  assert(!p->uc_op_work[i].work.ready && !p->uc_op_work[i].msg_list);
 }
}
static void release_success(struct wlan_ipa_priv *p){
 assert(allocations==4 && locks==2 && registered==1);
 assert(wlan_ipa_uc_ol_deinit(p)==0);
 assert(!p->uc_load_handled && !p->ipa_lock && p->deinit_in_prog==1);
 assert_unwound(p);
}
'''
    tests = r'''
int main(void){
 struct wlan_ipa_priv ctx;
 for(int fail=1;fail<=4;fail++){
  memset(&ctx,0,sizeof(ctx));ctx.config=1;fail_alloc=fail;alloc_call=0;created_work=0;
  assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==QDF_STATUS_E_NOMEM);
  assert_unwound(&ctx);assert(!created_work);cases++;
  fail_alloc=0;alloc_call=0;
  assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==0);
  assert(ctx.ipa_init_state==WLAN_IPA_STATE_PIPE_CONNECTION_DONE);
  release_success(&ctx);cases++;
 }
 for(int sta=0;sta<=1;sta++){
  memset(&ctx,0,sizeof(ctx));ctx.config=1+2*sta;ctx.uc_loaded=true;ctx.mcc_work.ready=sta;
  alloc_call=0;map_error=7;disconnects=sys_teardown=0;
  assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==7);
  assert_unwound(&ctx);assert(disconnects==1 && sys_teardown==sta);
  assert(!ctx.uc_load_handled && !ctx.mcc_work.ready);cases++;
 }
 memset(&ctx,0,sizeof(ctx));ctx.config=1;ctx.uc_loaded=true;
 map_error=0;setup_error=1;alloc_call=0;
 assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==QDF_STATUS_E_FAILURE);assert_unwound(&ctx);cases++;
 memset(&ctx,0,sizeof(ctx));ctx.config=1;ctx.uc_loaded=true;
 setup_error=0;alloc_call=0;
 assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==0 && ctx.uc_load_handled && connected==1);
 release_success(&ctx);cases++;
 memset(&ctx,0,sizeof(ctx));ctx.config=1;alloc_call=0;
 assert(wlan_ipa_uc_ol_init(&ctx,NULL)==QDF_STATUS_E_FAILURE && !alloc_call);cases++;
 resource_error=1;
 assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==QDF_STATUS_E_FAILURE && !alloc_call);cases++;
 ctx.config=0;
 assert(wlan_ipa_uc_ol_init(&ctx,&ctx)==0 && !alloc_call);cases++;
 printf("PASS: %d IPA lifecycle cases; allocation failures/retry; work/lock cleanup; SMMU unwind; teardown readiness\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c,exe=Path(tmp)/'test.c',Path(tmp)/'test'
        c.write_text(pre+enum+mocks+body+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                        '-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__ == '__main__':
    main()
