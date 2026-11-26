#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the actual Nezha CSI control parser/state with host service doubles."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'drivers/cam_sensor_module/cam_csiphy/cam_nezha_csi.c').read_text()
start=s.index('#define NEZHA_PHY_COUNT');end=s.index('static struct kobj_attribute csi_attr')
body=s[start:end].replace('static struct kobject *csi_kobj;','')
pre=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <pthread.h>
#include <sys/types.h>
#include <limits.h>
typedef uint8_t u8; typedef uint32_t u32; typedef unsigned long long u64;
#define DEFINE_SPINLOCK(n) pthread_mutex_t n = PTHREAD_MUTEX_INITIALIZER
#define spin_lock_irqsave(p,f) do { (f)=0; pthread_mutex_lock(p); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f); pthread_mutex_unlock(p); } while(0)
#define BIT_ULL(n) (1ULL<<(n))
#define min_t(t,a,b) ((t)(a)<(t)(b)?(t)(a):(t)(b))
#define READ_ONCE(x) __atomic_load_n(&(x),__ATOMIC_RELAXED)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x),(v),__ATOMIC_RELAXED)
#define GFP_KERNEL 0
#define sysfs_emit(b,f,v) sprintf(b,f,v)
struct kobject { int dummy; }; struct kobj_attribute { int dummy; };
static int allocs, fail_alloc;
static void *kmemdup_nul(const void *s,size_t n,int unused) {
 if(fail_alloc) return NULL;
 char *p=malloc(n+1); assert(p);memcpy(p,s,n);p[n]=0;allocs++;return p;
}
static void kfree(void *p){if(p){allocs--;free(p);}}
static int kstrtou64(const char *s,int base,u64 *value) {
 char *end; unsigned long long n;
 if(!*s || *s=='-')return -EINVAL;
 errno=0;n=strtoull(s,&end,base);if(errno || end==s)return -EINVAL;
 if(*end=='\n')end++;if(*end)return -EINVAL;
 *value=n;return 0;
}
'''
errors=(root/'drivers/cam_isp/isp_hw_mgr/include/cam_isp_hw_mgr_intf.h').read_text()
pre += '\n'.join('#define '+name+' '+value for name,value in re.findall(r'(CAM_ISP_HW_ERROR_CSID_\w+)\s*=\s*(0x[0-9a-fA-F]+)',errors))+'\n'
csid=(root/'drivers/cam_isp/isp_hw_mgr/isp_hw/ife_csid_hw/cam_ife_csid_hw_ver2.c').read_text()
a=csid.index('static u32 cam_ife_csid_nezha_rx_masks');b=csid.index('static inline int cam_ife_csid_ver2_rx_err_process_top_half',a)
helper=csid[a:b]
# Keep event enum values from the actual hardware header.
header=(root/'drivers/cam_isp/isp_hw_mgr/isp_hw/ife_csid_hw/cam_ife_csid_common.h').read_text()
name='CAM_IFE_CSID_RX_ERROR_CRC';i=header.index(name);a=header.rfind('enum ',0,i);b=header.index('};',i)+2
pre += header[a:b]+'\n#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))\n#define BIT(n) (1U<<(n))\n'
body += helper

test=r'''
static ssize_t command(const char *s) { return csiphy_umd_paras_store(NULL,NULL,s,strlen(s)); }
static void *worker(void *p) {
 unsigned int phy=(uintptr_t)p;
 for(int i=0;i<10000;i++) {
  cam_nezha_csi_crc(phy);
  assert(cam_nezha_csi_choice(phy,2)==(i%2?0:1));
 }
 return NULL;
}
int main(void) {
 char buf[128]; pthread_t threads[8];
 assert(cam_nezha_csi_choice(0,2)==0);
 assert(cam_nezha_csi_crc_divisor(8)==8);
 assert(command("0x1000,0")==-ERANGE);
 assert(command("0x1000,65536")==-ERANGE);
 assert(command("0x1000,1")>0 && cam_nezha_csi_crc_divisor(8)==1);
 assert(command("0x1000,65535")>0 && cam_nezha_csi_crc_divisor(8)==65535);
 assert(command("0x1001,2")==-ERANGE);
 assert(command("0x1001,1")>0 && cam_nezha_csi_full_recovery());
 assert(command("0x1002,1")>0);
 cam_nezha_csi_crc(3); assert(cam_nezha_csi_choice(0,2)==0);
 assert(cam_nezha_csi_choice(3,2)==1); assert(cam_nezha_csi_choice(3,2)==1);
 cam_nezha_csi_crc(3); assert(cam_nezha_csi_choice(3,2)==0);
 assert(command("0x1004,192")>0); /* PHY3 backup choice 3 clamps to 1 */
 assert(cam_nezha_csi_choice(3,2)==1 && cam_nezha_csi_choice(0,2)==0);
 assert(command("0x1004,65536")==-ERANGE);
 assert(command("0x1004,0")>0);
 assert(command("0x1003,0")>0);
 assert(command("0x1003,0x100000000")==-ERANGE);
 assert(command("0x1005,1")==-EINVAL);
 assert(command("0x1005,0")==-EINVAL);
 assert(command("0x1005,0x1000000010000")==-EINVAL); /* overlap */
 u32 fatal=0x200,recover=0x10000;
 assert(!cam_nezha_csi_error_policy(&fatal,&recover));
 assert(command("0x1005,0x1000000000200")>0); /* CRC fatal, FIFO recoverable */
 assert(cam_nezha_csi_error_policy(&fatal,&recover));
 assert(fatal==0x10000 && recover==0x200);
 u8 bits[64]={0};bits[CAM_IFE_CSID_RX_ERROR_CRC]=12;
 bits[CAM_IFE_CSID_RX_LANE0_FIFO_OVERFLOW]=4;
 u64 events=BIT_ULL(CAM_IFE_CSID_RX_ERROR_CRC) | (0xfULL<<CAM_IFE_CSID_RX_LANE0_FIFO_OVERFLOW);
 fatal=0xf0;recover=0x1000;
 assert(cam_ife_csid_nezha_rx_masks(events,bits,&fatal,&recover)==0xf0);
 assert(fatal==0x1000 && recover==0xf0 && (fatal|recover)==0x10f0);
 /* Unspecified event bits survive; absent/unsubscribed and bad positions do not change. */
 fatal=0xf000;recover=0x20000;
 cam_ife_csid_nezha_rx_masks(events,bits,&fatal,&recover);
 assert(fatal==0xf000 && recover==0x20000);
 fatal=0xf0;recover=0x1000;bits[CAM_IFE_CSID_RX_ERROR_CRC]=32;
 cam_ife_csid_nezha_rx_masks(0,bits,&fatal,&recover);
 assert(fatal==0xf0 && recover==0x1000);
 const char *bad[]={"", "0x1002", "0x1002,", "0x1002,1,0", "0x1002,-1", "0x1002,no", "0x1002,18446744073709551616"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);i++)assert(command(bad[i])<0);
 assert(csiphy_umd_paras_store(NULL,NULL,"0x1002,1\0bad",12)==-EINVAL);
 memset(buf,'1',sizeof(buf));assert(csiphy_umd_paras_store(NULL,NULL,buf,sizeof(buf))==-EINVAL);
 fail_alloc=1;assert(command("0x1002,1")==-ENOMEM);fail_alloc=0;
 cam_nezha_csi_crc(8);cam_nezha_csi_crc(UINT_MAX);assert(cam_nezha_csi_choice(8,2)==0);
 for(uintptr_t i=0;i<8;i++)assert(!pthread_create(&threads[i],NULL,worker,(void *)i));
 for(int i=0;i<8;i++)assert(!pthread_join(threads[i],NULL));
 assert(csiphy_umd_paras_show(NULL,NULL,buf)==1 && !strcmp(buf,"0"));
 assert(!allocs);
 puts("PASS: parser/ranges, backup priority/clamp, retry wrap, invalid PHY, 8 concurrent PHYs x 10000 retries, allocation cleanup, CSID disjoint policy and IRQ-mask mapping");
}
'''
with tempfile.TemporaryDirectory(prefix='nezha-csi-test-') as t:
 c=Path(t)/'test.c';exe=Path(t)/'test';c.write_text(pre+body+test)
 subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O1','-g','-pthread','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
