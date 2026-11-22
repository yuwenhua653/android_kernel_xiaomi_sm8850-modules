#!/usr/bin/env python3
"""Exercise production IPA ready callback lifetime and WDI instance cleanup."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(s, name):
    m=re.search(r'(?:static\s+)?(?:void|int)\s+'+name+r'\s*\([^;]*?\)\s*\{',s,re.S)
    start=s.index('{',m.start());i,depth=start+1,1
    while depth:
        depth+=(s[i]=='{')-(s[i]=='}');i+=1
    return s[m.start():i]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--modules-root',type=Path,required=True)
    a=p.parse_args()
    root=a.modules_root/'qcom/opensource/dataipa/drivers/platform/msm/ipa'
    s=(root/'ipa_v3/ipa_uc_wdi.c').read_text()
    client=(root/'ipa_clients/ipa_wdi3.c').read_text()
    body='\n'.join(function(s,n) for n in ['ipa3_uc_reg_rdyCB','ipa3_uc_dereg_rdyCB',
        'ipa3_uc_dereg_rdyCB_by_priv','ipa3_uc_wdi_loaded_handler'])
    body+=function(client,'ipa_wdi_cleanup_per_inst')
    pre=r'''
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
struct owner {int calls;bool dead;};
struct ipa_wdi_uc_ready_params {void (*notify)(void *);void *priv;bool is_uC_ready;};
struct ipa_context {struct {void (*uc_ready_cb)(void *);void *priv;}uc_wdi_ctx;};
static struct ipa_context ctx,*ipa3_ctx=&ctx;
static pthread_mutex_t ipa_uc_wdi_ready_lock=PTHREAD_MUTEX_INITIALIZER;
#define spin_lock_irqsave(l,f) do{(f)=0;assert(!pthread_mutex_lock(l));}while(0)
#define spin_unlock_irqrestore(l,f) do{(void)(f);assert(!pthread_mutex_unlock(l));}while(0)
#define IPAERR(...) ((void)0)
#define IPA_WDI_ERR(...) ((void)0)
#define IPA_WDI_DBG(fmt,...) debug_instance(__VA_ARGS__)
static void debug_instance(int h,int i){assert(h>=0 && i>=0);}
static int ready;
static int ipa3_uc_state_check(void){return __atomic_load_n(&ready,__ATOMIC_SEQ_CST)?0:-1;}
static void callback(void *p){struct owner *o=p;assert(!o->dead);o->calls++;}
#define IPA_WDI_INST_MAX 4
#define IPA_WDI_1 1
#define IPA_WDI_3 3
typedef int ipa_wdi_hdl_t;
struct ipa_wdi_intf_info {int link;};
struct ipa_wdi_context {int inst_id,wdi_version,head_intf_list,lock,clk_lock;};
static struct ipa_wdi_context *ipa_wdi_ctx_list[IPA_WDI_INST_MAX];
static struct {void *priv;int is_xr_opt_dp_cb_registered,is_opt_dp_cb_registered;
 int is_ctrl_cb_registered,num_ctrl_pkts,ipa_ep_idx_rx,ipa_ep_idx_tx;}opt_dpath_info[IPA_WDI_INST_MAX];
#define list_for_each_entry_safe(e,n,h,m) for((void)(h),(e)=NULL,(n)=NULL;(e)!=NULL;(e)=(n))
#define list_del(p) ((void)(p))
#define kfree free
#define atomic_set(p,n) (*(p)=(n))
#define mutex_destroy(p) ((void)(p))
'''
    tests=r'''
static int cases;
static void *deliver(void *p){(void)p;ipa3_uc_wdi_loaded_handler();return NULL;}
static void *remove_owner(void *p){ipa3_uc_dereg_rdyCB_by_priv(p);((struct owner *)p)->dead=true;return NULL;}
static void *register_owner(void *p){assert(ipa3_uc_reg_rdyCB(p)==0);return NULL;}
static void *become_ready(void *p){(void)p;__atomic_store_n(&ready,1,__ATOMIC_SEQ_CST);ipa3_uc_wdi_loaded_handler();return NULL;}
int main(void){
 struct owner a={0},b={0};
 struct ipa_wdi_uc_ready_params pa={callback,&a,false},pb={callback,&b,false};
 assert(ipa3_uc_reg_rdyCB(NULL)==-EINVAL);cases++;
 assert(!ipa3_uc_reg_rdyCB(&pa) && !pa.is_uC_ready);
 assert(ipa3_uc_reg_rdyCB(&pb)==-EBUSY);
 ipa3_uc_dereg_rdyCB_by_priv(&b);ipa3_uc_wdi_loaded_handler();
 ipa3_uc_wdi_loaded_handler();assert(a.calls==1 && !b.calls);cases++;
 assert(!ipa3_uc_reg_rdyCB(&pb));assert(!ipa3_uc_dereg_rdyCB());
 ipa3_uc_wdi_loaded_handler();assert(!b.calls);cases++;
 for(int n=0;n<256;n++){
  struct owner o={0};struct ipa_wdi_uc_ready_params p={callback,&o,false};pthread_t x,y;
  ready=0;assert(!ipa3_uc_reg_rdyCB(&p));
  assert(!pthread_create(&x,NULL,deliver,NULL));assert(!pthread_create(&y,NULL,remove_owner,&o));
  assert(!pthread_join(x,NULL));assert(!pthread_join(y,NULL));
  assert(o.dead && o.calls<=1 && !ctx.uc_wdi_ctx.uc_ready_cb);cases++;
  o=(struct owner){0};p.is_uC_ready=false;ready=0;
  assert(!pthread_create(&x,NULL,register_owner,&p));assert(!pthread_create(&y,NULL,become_ready,NULL));
  assert(!pthread_join(x,NULL));assert(!pthread_join(y,NULL));
  assert((p.is_uC_ready && !o.calls) || (!p.is_uC_ready && o.calls==1));
  assert(!ctx.uc_wdi_ctx.uc_ready_cb);cases++;
 }
 assert(ipa_wdi_cleanup_per_inst(-1)==-EFAULT);
 assert(ipa_wdi_cleanup_per_inst(4)==-EFAULT);
 assert(ipa_wdi_cleanup_per_inst(2)==-EPERM);cases+=3;
 ready=0;b=(struct owner){0};assert(!ipa3_uc_reg_rdyCB(&pb));
 ipa_wdi_ctx_list[2]=calloc(1,sizeof(*ipa_wdi_ctx_list[2]));assert(ipa_wdi_ctx_list[2]);
 ipa_wdi_ctx_list[2]->inst_id=2;ipa_wdi_ctx_list[2]->wdi_version=3;
 opt_dpath_info[2].priv=&b;
 opt_dpath_info[0].ipa_ep_idx_rx=11;opt_dpath_info[0].ipa_ep_idx_tx=12;
 opt_dpath_info[2].ipa_ep_idx_rx=21;opt_dpath_info[2].ipa_ep_idx_tx=22;
 assert(!ipa_wdi_cleanup_per_inst(2));b.dead=true;
 ipa3_uc_wdi_loaded_handler();assert(!b.calls && !ctx.uc_wdi_ctx.uc_ready_cb);
 assert(!ipa_wdi_ctx_list[2] && !opt_dpath_info[2].priv);
 assert(!opt_dpath_info[2].ipa_ep_idx_rx && !opt_dpath_info[2].ipa_ep_idx_tx);
 assert(opt_dpath_info[0].ipa_ep_idx_rx==11 && opt_dpath_info[0].ipa_ep_idx_tx==12);cases++;
 printf("PASS: %d IPA provider lifetime/registration/instance cleanup cases\n",cases);
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        c,exe=Path(tmp)/'test.c',Path(tmp)/'test';c.write_text(pre+body+tests)
        subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-pthread','-fsanitize=undefined',str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':
    main()
