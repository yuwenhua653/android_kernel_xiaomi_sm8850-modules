#!/usr/bin/env python3
"""Fault-inject production IPA reservation pairs and message publication."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(s,name):
    m=re.search(r'(?:static\s+)?(?:void|QDF_STATUS)\s+'+name+r'\s*\([^;]*?\)\s*\{',s,re.S)
    start=s.index('{',m.start());i,depth=start+1,1
    while depth:
        depth+=(s[i]=='{')-(s[i]=='}');i+=1
    return s[m.start():i]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--modules-root',type=Path,required=True)
    p.add_argument('--source',type=Path)
    a=p.parse_args();base=a.modules_root/'qcom/opensource/wlan/qca-wifi-host-cmn/ipa/core'
    s=(a.source or base/'src/wlan_ipa_core.c').read_text()
    enum=re.search(r'enum wlan_ipa_uc_op_code \{.*?\};',(base/'inc/wlan_ipa_priv.h').read_text(),re.S)[0]
    body='\n'.join(function(s,n) for n in ['wlan_ipa_uc_op_event_handler','wlan_ipa_wdi_opt_dpath_notify_flt_rsvd','wlan_ipa_get_alt_pipe'])
    pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#define ipa_err(...) ((void)0)
#define ipa_info(...) ((void)0)
#define qdf_unlikely(x) (x)
#define WLAN_IPA_MAX_SESSION 8
#define WLAN_IPA_MAX_IFACE 4
typedef int QDF_STATUS;
#define QDF_STATUS_SUCCESS 0
#define QDF_STATUS_E_INVAL 1
'''
    mocks=r'''
struct op_msg_type {int op_code,rsvd;};
struct work {bool pending;};
struct uc_op_work_struct {struct op_msg_type *msg;struct work work;};
struct wlan_ipa_iface_context {uint8_t session_id;bool alt_pipe;};
struct wlan_ipa_priv {
 uint8_t vdev_to_iface[WLAN_IPA_MAX_SESSION];
 struct wlan_ipa_iface_context iface_context[WLAN_IPA_MAX_IFACE];
 int uc_ready_lock,dp_soc;bool uc_op_work_enabled;
 struct uc_op_work_struct uc_op_work[WLAN_IPA_UC_OPCODE_MAX];
};
static struct wlan_ipa_priv *gp_ipa;
static void *allocs[8];static int calls,fail,live,shared,mapped,ready_calls,cases;
static void *qdf_mem_malloc(size_t n){
 if(++calls==fail)return NULL;
 void *p=calloc(1,n);assert(p);
 for(int i=0;i<8;i++)if(!allocs[i]){allocs[i]=p;live++;return p;}
 abort();
}
static void qdf_mem_free(void *p){
 if(!p)return;
 for(int i=0;i<8;i++)if(allocs[i]==p){allocs[i]=NULL;live--;free(p);return;}
 assert(!"double free or unowned message");
}
#define qdf_spin_lock_irqsave(p) do{assert(!*(p));*(p)=1;}while(0)
#define qdf_spin_unlock_irqrestore(p) do{assert(*(p));*(p)=0;}while(0)
static bool ipa_get_shared_smmu_enable(void){return shared;}
static void cdp_ipa_set_smmu_mapped(int soc,int state){(void)soc;mapped=state;}
static void qdf_sched_work(int id,struct work *w){(void)id;w->pending=true;}
static void __attribute__((unused)) wlan_ipa_uc_loaded_uc_cb(void *p){assert(p==gp_ipa);ready_calls++;}
static void drain(struct wlan_ipa_priv *ctx){
 for(int i=0;i<WLAN_IPA_UC_OPCODE_MAX;i++){
  struct uc_op_work_struct *w=&ctx->uc_op_work[i];
  assert(w->work.pending==!!w->msg);
  qdf_mem_free(w->msg);w->msg=NULL;w->work.pending=false;
 }
 assert(!live && !ctx->uc_ready_lock);
}
'''
    tests=r'''
int main(void){
 for(int response=0;response<2;response++)for(shared=0;shared<2;shared++){
  for(int closed=0;closed<2;closed++)for(int f=0;f<3;f++){
   struct wlan_ipa_priv ctx={0};gp_ipa=&ctx;ctx.uc_op_work_enabled=!closed;
   fail=f;calls=mapped=0;
   wlan_ipa_wdi_opt_dpath_notify_flt_rsvd(response);
   int count=1+(response && !shared);
   bool accepted=!closed && !(f>0 && f<=count);
   assert(live==(accepted?count:0));
   assert(mapped==(accepted && count==2));
   assert(!!ctx.uc_op_work[WLAN_IPA_FILTER_RSV_NOTIFY].msg==accepted);
   if(accepted){
    void *old=ctx.uc_op_work[WLAN_IPA_FILTER_RSV_NOTIFY].msg;
    fail=0;wlan_ipa_wdi_opt_dpath_notify_flt_rsvd(response);
    assert(live==count && old==ctx.uc_op_work[WLAN_IPA_FILTER_RSV_NOTIFY].msg);
   }
   drain(&ctx);cases++;
  }
 }
 struct wlan_ipa_priv ctx={0};gp_ipa=&ctx;ctx.uc_op_work_enabled=true;fail=0;
 for(int code=0;code<=WLAN_IPA_UC_OPCODE_MAX;code++){
  struct op_msg_type *m=qdf_mem_malloc(sizeof(*m));m->op_code=code;
  wlan_ipa_uc_op_event_handler((uint8_t *)m,&ctx);
  if(code==WLAN_IPA_UC_OPCODE_UC_READY || code==WLAN_IPA_UC_OPCODE_MAX)assert(!live);
  else {
   assert(live==1 && ctx.uc_op_work[code].msg==m);
   struct op_msg_type *dup=qdf_mem_malloc(sizeof(*dup));dup->op_code=code;
   wlan_ipa_uc_op_event_handler((uint8_t *)dup,&ctx);
   assert(live==1 && ctx.uc_op_work[code].msg==m);
  }
  drain(&ctx);cases++;
 }
 assert(ready_calls==1);
 ctx.uc_op_work_enabled=false;
 struct op_msg_type *m=qdf_mem_malloc(sizeof(*m));m->op_code=WLAN_IPA_FILTER_REL_NOTIFY;
 wlan_ipa_uc_op_event_handler((uint8_t *)m,&ctx);assert(!live);cases++;
 m=qdf_mem_malloc(sizeof(*m));wlan_ipa_uc_op_event_handler((uint8_t *)m,NULL);assert(!live);cases++;
 wlan_ipa_uc_op_event_handler(NULL,&ctx);gp_ipa=NULL;
 wlan_ipa_wdi_opt_dpath_notify_flt_rsvd(true);assert(!live);cases++;
 for(int id=0;id<256;id++){
  bool alt=false;ctx.iface_context[0].alt_pipe=true;
  assert(wlan_ipa_get_alt_pipe(&ctx,id,&alt)==(id<8?0:1));
  assert(alt==(id<8));cases++;
 }
 bool alt=false;
 ctx.vdev_to_iface[0]=4;assert(wlan_ipa_get_alt_pipe(&ctx,0,&alt)==1);cases++;
 ctx.vdev_to_iface[0]=0;ctx.iface_context[0].session_id=8;
 assert(wlan_ipa_get_alt_pipe(&ctx,0,&alt)==1);cases++;
 assert(wlan_ipa_get_alt_pipe(NULL,0,&alt)==1);cases++;
 assert(wlan_ipa_get_alt_pipe(&ctx,0,NULL)==1);cases++;
 printf("PASS: %d IPA notification/vdev ownership/duplicate/closing cases\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c,exe=Path(tmp)/'test.c',Path(tmp)/'test';c.write_text(pre+enum+mocks+body+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()
