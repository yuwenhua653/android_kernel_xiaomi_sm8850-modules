#!/usr/bin/env python3
"""Exercise actual firmware parser and every allocation failure with a stock bin.
The firmware is input only and is not copied to the source tree.
"""
import os,sys,subprocess,tempfile,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'asoc/codecs/tas25xx'
s=(root/'src/tas25xx-regbin-parser.c').read_text()
def function(name):
 m=re.search(r'^(?:static )?[^\n;=]+\b'+name+r'\([^;]*?\)\n\{',s,re.M);assert m,name
 start=m.start();a=s.index('{',m.start());level=1;b=a+1
 while level:
  level+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[start:b]+'\n'
pre=r'''
#define _GNU_SOURCE
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdarg.h>
#include <assert.h>
typedef uint8_t u8;typedef uint32_t u32;typedef uint64_t u64;
#define MAX_CHANNELS 2
#define GFP_KERNEL 0
#define IS_ENABLED(x) 0
#define unlikely(x) (x)
#define dev_info(...) do{}while(0)
#define dev_dbg(...) do{}while(0)
#define dev_err(...) do{}while(0)
#define dev_warn(...) do{}while(0)
#define atomic_set(p,v) (*(p)=(v))
#define atomic_read(p) (*(p))
#define wake_up(p) do{}while(0)
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define TAS25XX_DSP_FW_NONE 0
#define TAS25XX_DSP_FW_TRYLOAD 1
#define TAS25XX_DSP_FW_PARSE_FAIL 2
#define TAS25XX_DSP_FW_OK 3
struct device {int unused;};
struct i2c_client {int addr;struct device dev;};
struct linux_platform {struct device *dev;};
struct soc_enum {int unused;};
struct snd_kcontrol_new {int unused;};
struct soc_mixer_control {int unused;};
struct firmware {const u8 *data;size_t size;};
static int allocations,fail_at,live,released;
static void *kzalloc(size_t n,int flags){allocations++;if(allocations==fail_at)return NULL;void *p=calloc(1,n?n:1);assert(p);live++;return p;}
static void kfree(void *p){if(p){live--;free(p);}}
static void *kmemdup(const void *p,size_t n,int flags){void *q=kzalloc(n,flags);if(q)memcpy(q,p,n);return q;}
static char *kasprintf(int flags,const char *fmt,...){char tmp[256];va_list ap;va_start(ap,fmt);vsnprintf(tmp,sizeof(tmp),fmt,ap);va_end(ap);return kmemdup(tmp,strlen(tmp)+1,flags);}
static void release_firmware(const struct firmware *fw){released++;}
#include "tas25xx-bin-validate.h"
#define get_unaligned_le32(p) tas_bin_le32((const u8 *)(p))
'''
h=(root/'inc/tas25xx.h').read_text();types=h[h.index('struct tas25xx_intr_info {'):h.index('#if IS_ENABLED(CONFIG_TAS25XX_IRQ_BD)',h.index('struct tas25xx_intr_info {'))]
priv=r'''
struct channel {int mn_addr;};
struct tas25xx_priv {
 void *platform_data;u8 *fw_data;size_t fw_size;int fw_state,fw_wait_complete,fw_wait;
 int ch_count,dev_revid,mn_iv_width,curr_mn_iv_width,mn_vbat,curr_mn_vbat;
 int playback_volume_left_index,playback_volume_right_index,codec_lock;
 struct channel *devs[2];
 struct tas25xx_interrupts intr_data[2];struct tas_block_op_data_t block_op_data[2];
};
'''
priv += r'''
struct snd_kcontrol {struct tas25xx_priv *tas;};
struct snd_ctl_elem_value {struct {struct {unsigned int item[1];}enumerated;}value;};
#define snd_soc_kcontrol_component(c) ((c)->tas)
#define snd_soc_component_get_drvdata(c) (c)
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
static void mutex_lock(int *v){assert(!*v);*v=1;}
static void mutex_unlock(int *v){assert(*v);*v=0;}
'''
head=(root/'inc/tas25xx-regbin-parser.h').read_text()
head=head[:head.index('int32_t tas25xx_load_firmware')]+ '\n#endif\n'
globals=s[s.index('#define TAS25XX_BINFILE_NAME'):s.index('static int32_t change_endian')]
funcs='int32_t tas25xx_remove_binfile(struct tas25xx_priv *);\n'
for name in ('header_check','get_block_size_noadvance','find_block_for_channel','tas25xx_read_size_bytes','tas25xx_parse_init_params','tas25xx_parse_hw_params','tas25xx_parse_profiles','tas25xx_parse_block_data','tas25xx_parse_interrupts','tas25xx_parse_kcontrols','tas25xx_parse_algo_data','tas25xx_remove_binfile','tas25xx_fw_ready','tas25xx_profile_get','tas25xx_profile_put'):funcs+=function(name)
test=r'''
int main(int argc,char **argv){
 FILE *f=fopen(argv[1],"rb");assert(f);fseek(f,0,SEEK_END);size_t n=ftell(f);rewind(f);
 u8 *b=malloc(n);assert(b);assert(fread(b,1,n,f)==n);fclose(f);
 struct firmware fw={b,n};struct i2c_client client={.addr=0x4a};struct linux_platform plat={.dev=&client.dev};
 struct channel channels[2]={{0x4a},{0x48}};
 int total=0;
 for(int trial=0;trial<=total;trial++){
  struct tas25xx_priv tas={.platform_data=&plat,.ch_count=2,.devs={&channels[0],&channels[1]}};
  allocations=0;fail_at=trial;released=0;g_tas25xx=&tas;
  tas25xx_fw_ready(&fw,&tas);
  assert(released==1 && tas.fw_wait_complete==1);
  if(!trial){assert(tas.fw_state==TAS25XX_DSP_FW_OK);total=allocations;
   assert(g_no_of_profiles==4 && g_no_of_kcontrols==16);
   assert(tas.intr_data[0].count==19 && tas.intr_data[1].count==19);
   struct snd_kcontrol control={&tas};struct snd_ctl_elem_value value={0};
   value.value.enumerated.item[0]=3;assert(tas25xx_profile_put(&control,&value)==1);
   assert(!tas25xx_profile_put(&control,&value));
   value.value.enumerated.item[0]=4;assert(tas25xx_profile_put(&control,&value)==-EINVAL);
   value.value.enumerated.item[0]=UINT32_MAX;assert(tas25xx_profile_put(&control,&value)==-EINVAL);
   assert(!tas25xx_profile_get(&control,&value) && value.value.enumerated.item[0]==3);

  } else assert(tas.fw_state==TAS25XX_DSP_FW_PARSE_FAIL);
  tas25xx_remove_binfile(&tas);assert(live==0);
 }
 free(b);printf("PASS: actual stock firmware parse + all %d allocation-failure paths, explicit zero live allocations (ASan/UBSan)\n",total);
}
'''
with tempfile.TemporaryDirectory(prefix='tas-parser-test-') as d:
 t=Path(d);(t/'test.c').write_text(pre+types+priv+head+globals+funcs+test)
 subprocess.run([os.getenv('CC','cc'),'-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(root/'inc'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test'),sys.argv[1]],env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'),check=True)
