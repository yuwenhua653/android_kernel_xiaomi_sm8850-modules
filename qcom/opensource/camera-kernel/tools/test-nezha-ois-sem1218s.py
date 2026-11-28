#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Real OIS slave-info ABI parser and SEM1218S writer under ASan/UBSan.
Vendor firmware and physical I2C are not used. All 196 transfer/finalize failure
points, reported device error, version mismatch and buffer bounds are modeled.
"""
from pathlib import Path
import os,re,subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=(r/'drivers/cam_sensor_module/cam_ois/cam_ois_core.c').read_text();h=(r/'include/uapi/camera/media/cam_sensor.h').read_text()
def fn(n):
 m=re.search(r'static\s+int\s+' +n+r'\([^;]*?\)\s*\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
def st(n):return re.search(r'struct '+n+r' \{.*?\} __attribute__\s*\(\(packed\)\);',h,re.S)[0]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t __u8;typedef uint32_t __u32;
#if CONFIG_TARGET_PRODUCT_NEZHA
#define MAX_OIS_NAME_SIZE 64
#else
#define MAX_OIS_NAME_SIZE 32
#endif
#define CCI_MASTER 1
#define I2C_MASTER 2
#define CAMERA_SENSOR_I2C_TYPE_BYTE 1
#define CAMERA_SENSOR_I2C_TYPE_WORD 2
#define CAM_SENSOR_I2C_WRITE_SEQ 2
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define array_size(a,b) ((a)*(b))
#define SEM1218S_APP_SIZE (48*1024)
#define SEM1218S_FW_CTRL 0x1000
#define SEM1218S_FW_ERR 0x1001
#define SEM1218S_APP_VER 0x1008
#define SEM1218S_FW_CRC 0x1010
struct cci_client {int i2c_freq_mode,sid,retries,id_map;};struct i2c_client {int addr;};struct qup_client {struct i2c_client *i2c_client;};
struct camera_io_master {int master_type;struct cci_client *cci_client;struct qup_client *qup_client;};
struct cam_sensor_i2c_reg_array {uint32_t reg_addr,reg_data,delay,data_mask;};
struct cam_sensor_i2c_reg_setting {struct cam_sensor_i2c_reg_array *reg_setting;uint32_t size,addr_type,data_type,delay;};
'''+''.join(st(n) for n in ['cam_ois_opcode','cam_cmd_ois_info','cam_cmd_ois_fw_param'])+r'''
struct cam_ois_ctrl_t {struct camera_io_master io_master_info;int ois_fw_flag,is_ois_calib;char ois_name[MAX_OIS_NAME_SIZE];struct cam_ois_opcode opcode;};
static int allocations,alloc_fail,steps,fail_at,chunks,crc_writes,resets,device_error,version_error;
static uint32_t sent_crc;
static uint8_t *image;
static void *vzalloc(size_t n){if(alloc_fail)return NULL;void *p=calloc(1,n);assert(p);allocations++;return p;}
static void vfree(void *p){if(p){allocations--;free(p);}}
static void msleep(int ms){(void)ms;}
static uint32_t get_unaligned_le32(const void *p){const uint8_t*b=p;return b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);}
static void put_unaligned_le32(uint32_t v,void *p){uint8_t*b=p;for(int k=0;k<4;k++)b[k]=v>>(k*8);}
static int camera_io_dev_write_continuous(struct camera_io_master *io,struct cam_sensor_i2c_reg_setting *s,int op){
 (void)io;assert(op==CAM_SENSOR_I2C_WRITE_SEQ&&s->addr_type==2&&s->data_type==1);if(++steps==fail_at)return -EIO;
 if(s->reg_setting[0].reg_addr==0x1100){assert(s->size==256);for(int k=0;k<256;k++){assert(s->reg_setting[k].reg_addr==0x1100+(unsigned)k);assert(s->reg_setting[k].reg_data==image[chunks*256+k]);}chunks++;}
 else if(s->reg_setting[0].reg_addr==SEM1218S_FW_CRC){assert(chunks==192&&s->size==4);sent_crc=0;for(int k=0;k<4;k++)sent_crc|=s->reg_setting[k].reg_data<<(8*k);crc_writes++;}
 else {assert(s->reg_setting[0].reg_addr==SEM1218S_FW_CTRL&&s->size==1&&s->reg_setting[0].reg_data==0x80&&crc_writes==1);resets++;}
 return 0;
}
static int camera_io_dev_read_seq(struct camera_io_master *io,uint32_t addr,uint8_t *data,int at,int dt,uint32_t n){
 (void)io;assert(at==2&&dt==1);if(++steps==fail_at)return -EIO;
 if(addr==SEM1218S_FW_ERR){assert(n==1&&crc_writes==1&&!resets);data[0]=device_error;}
 else{assert(addr==SEM1218S_APP_VER&&n==4&&resets==1);put_unaligned_le32(version_error?0:0x12345678,data);}
 return 0;
}
static void reset(void){assert(!allocations);steps=fail_at=chunks=crc_writes=resets=device_error=version_error=0;}
'''
body=fn('cam_ois_slaveInfo_pkt_parser')+'\n#if CONFIG_TARGET_PRODUCT_NEZHA\n'+''.join(fn(n) for n in ['cam_ois_sem1218s_param_check','cam_ois_sem1218s_write','write_ois_fw_sem1218s'])+'\n#endif\n'
# Independent fixed reference CRC for the exact test image.
b=bytearray(i%251 for i in range(48*1024));b[-12:-8]=(0x12345678).to_bytes(4,'little');crc=0
for x in b:
 crc^=x<<24
 for _ in range(8):crc=((crc<<1)^(0x04c11db7 if crc&0x80000000 else 0))&0xffffffff
main=r'''
int main(void){
 _Static_assert(sizeof(struct cam_cmd_ois_info)==(CONFIG_TARGET_PRODUCT_NEZHA?101:56),"slave ABI");
 _Static_assert(sizeof(struct cam_ois_opcode)==(CONFIG_TARGET_PRODUCT_NEZHA?29:16),"opcode ABI");
 _Static_assert(offsetof(struct cam_cmd_ois_info,opcode)==(CONFIG_TARGET_PRODUCT_NEZHA?72:40),"opcode offset");
 struct cci_client cci={.sid=9};struct cam_ois_ctrl_t ctrl={.io_master_info={.master_type=CCI_MASTER,.cci_client=&cci}};
 size_t size=sizeof(struct cam_cmd_ois_info);struct cam_cmd_ois_info *cmd=calloc(1,size);assert(cmd);cmd->slave_addr=0xa0;memset(cmd->ois_name,'a',MAX_OIS_NAME_SIZE-1);cmd->opcode.prog=0x11223344;
 for(size_t n=0;n<size;n++){void *shortbuf=malloc(n?n:1);memcpy(shortbuf,cmd,n);assert(cam_ois_slaveInfo_pkt_parser(&ctrl,shortbuf,n)==-EINVAL&&cci.sid==9);free(shortbuf);}
 assert(!cam_ois_slaveInfo_pkt_parser(&ctrl,(void*)cmd,size)&&cci.sid==0x50&&ctrl.opcode.prog==0x11223344);assert(strlen(ctrl.ois_name)==MAX_OIS_NAME_SIZE-1);
 memset(cmd->ois_name,'b',MAX_OIS_NAME_SIZE);assert(cam_ois_slaveInfo_pkt_parser(&ctrl,(void*)cmd,size)==-EINVAL);free(cmd);
#if CONFIG_TARGET_PRODUCT_NEZHA
 image=malloc(SEM1218S_APP_SIZE);assert(image);for(int k=0;k<SEM1218S_APP_SIZE;k++)image[k]=k%251;put_unaligned_le32(0x12345678,image+SEM1218S_APP_SIZE-12);
 struct cam_cmd_ois_fw_param p={.fw_size=SEM1218S_APP_SIZE,.fw_data_type=1,.fw_addr_type=2,.fw_len_per_write=256,.fw_reg_addr=0x1100};
 reset();assert(!write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)&&steps==196&&sent_crc==GOLDEN_CRC&&!allocations);
 for(int f=1;f<=196;f++){reset();fail_at=f;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EIO&&steps==f&&!allocations);if(f<=192)assert(!crc_writes&&!resets);if(f<=194)assert(!resets);}
 reset();device_error=1;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EIO&&!resets&&!allocations);reset();version_error=1;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EIO&&!allocations);
 reset();alloc_fail=1;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-ENOMEM&&!steps);alloc_fail=0;
 p.fw_size--;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EINVAL&&!steps);p.fw_size++;p.fw_len_per_write=0;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EINVAL);p.fw_len_per_write=256;p.fw_reg_addr=0xffff;assert(write_ois_fw_sem1218s(image,&p,ctrl.io_master_info)==-EINVAL);free(image);
 puts("PASS: 101-byte OEM OIS ABI, 64-byte names, 196 SEM1218S I/O failures, golden CRC, device/version errors, allocation and bounds");
#else
 puts("PASS: unchanged 56-byte generic OIS ABI, 32-byte names, every truncated command rejected");
#endif
}
'''.replace('GOLDEN_CRC',hex(crc)+'u')
with tempfile.TemporaryDirectory() as d:
 for config in [0,1]:
  c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+main)
  subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',f'-DCONFIG_TARGET_PRODUCT_NEZHA={config}',str(c),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
