#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Actual flash/OIS functions under host sanitizers with modeled I/O.
Not an ARM64 camera module build, HAL or hardware verification.
"""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
h=(root/'include/uapi/camera/media/cam_sensor.h').read_text()
def struct(name):
 return re.search(r'struct '+name+r' \{.*?\} __attribute__\s*\(\(packed\)\);',h,re.S)[0]+'\n'
structs=''.join(struct(n) for n in ['cam_flash_query_curr','cam_flash_query_curr_nezha','cam_cmd_ois_fw_param','cam_cmd_ois_fw_info_v2'])
s=(root/'drivers/cam_sensor_module/cam_ois/cam_ois_core.c').read_text()
check=s[s.index('int cam_ois_fw_info_input_check'):s.index('static int cam_ois_fw_info_pkt_parser_v2')]
body=s[s.index('static int cam_ois_validate_fw_param'):s.index('/**\n * cam_ois_pkt_parse')]
f=(root/'drivers/cam_sensor_module/cam_flash/cam_flash_core.c').read_text()
flash=f[f.index('static int cam_flash_pmic_query_current'):f.index('int cam_flash_pmic_pkt_parser')]
assert 'remain_len = cmd_desc->length;' in f
assert 'switch (cam_flash_is_nezha_query(cmd_buf, remain_len) ?' in f
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint32_t __u32;typedef uint16_t __u16;typedef uint8_t __u8;
#define MAX_OIS_NAME_SIZE 32
#define CAM_OIS_FW_VERSION_CHECK_MASK 1
#define OIS_ENDIANNESS_MASK_FW 15
#define IS_ENABLED(x) (x)
#define IS_REACHABLE(x) (x)
#define CONFIG_LEDS_QCOM_FLASH 1
#define CAMERA_SENSOR_FLASH_CMD_TYPE_QUERYCURR 12
#define CAM_DBG(...) ((void)0)
#define CAM_ERR(...) ((void)0)
#define CAM_WARN(...) ((void)0)
#define CAM_INFO(...) ((void)0)
#define min(a,b) ((a)<(b)?(a):(b))
#define CAMERA_SENSOR_I2C_TYPE_BYTE 1
#define CAMERA_SENSOR_I2C_TYPE_WORD 2
#define CAMERA_SENSOR_I2C_OP_RNDM_WR 1
#define CAMERA_SENSOR_I2C_OP_CONT_WR_BRST 2
#define CAMERA_SENSOR_I2C_OP_CONT_WR_SEQN 3
#define CAM_SENSOR_I2C_WRITE_RANDOM 1
#define CAM_SENSOR_I2C_WRITE_BURST 2
#define CAM_SENSOR_I2C_WRITE_SEQ 3
#define CCI_MASTER 1
#define I2C_COMPARE_MATCH 0
#define I2C_COMPARE_MISMATCH 1
enum cam_endianness_type {CAM_ENDIANNESS_BIG=1,CAM_ENDIANNESS_LITTLE=2};
struct cam_flash_ctrl{void *pmic_lcdev[1];};
struct cam_flash_private_soc{int unused;};
static int flash_error,flash_current=1500;
static int qcom_flash_led_get_max_avail_current(void*p,int*out){*out=flash_current;return flash_error;}
struct cam_sensor_i2c_reg_array{uint32_t reg_addr,reg_data,delay,data_mask;};
struct cam_sensor_i2c_reg_setting{struct cam_sensor_i2c_reg_array *reg_setting;uint16_t size;uint32_t addr_type,data_type,delay;};
struct camera_io_master{int master_type;};
struct i2c_settings_array{int is_settings_valid;};
struct device{int unused;};struct platform_device{struct device dev;};
static int alloc_fail,allocs,calls,fail_call,applies,apply_error,requests,releases,request_error;
static uint32_t seen[300],seen_count;
static void *vmalloc(size_t n){if(alloc_fail)return NULL;void*p=malloc(n);assert(p);allocs++;return p;}
static void vfree(void*p){assert(p);allocs--;free(p);}
static int write_io(struct cam_sensor_i2c_reg_setting*s){calls++;if(fail_call==calls)return -EIO;assert(s->size>0);for(int i=0;i<s->size;i++){assert(seen_count<300);seen[seen_count++]=s->reg_setting[i].reg_data;}return 0;}
static int camera_io_dev_write(struct camera_io_master*m,struct cam_sensor_i2c_reg_setting*s){return write_io(s);}
static int camera_io_dev_write_continuous(struct camera_io_master*m,struct cam_sensor_i2c_reg_setting*s,int op){return write_io(s);}
struct firmware{size_t size;const uint8_t*data;};
static struct firmware image;
static int request_firmware(const struct firmware**f,const char*n,struct device*d){requests++;if(request_error)return request_error;*f=&image;return 0;}
static void release_firmware(const struct firmware*f){assert(f==&image);releases++;}
static void usleep_range(int a,int b){}
static int delete_request(struct i2c_settings_array*s){s->is_settings_valid=0;return 0;}
'''
post=r'''
struct cam_ois_ctrl_t {
 struct {uint8_t fw_count,endianness;struct cam_cmd_ois_fw_param *fw_param;}fw_info;
 struct i2c_settings_array i2c_fw_version_data,*i2c_fw_init_data,*i2c_fw_finalize_data;
 struct camera_io_master io_master_info;struct platform_device*pdev;
};
static int cam_ois_apply_settings(struct cam_ois_ctrl_t*c,struct i2c_settings_array*s){applies++;return apply_error;}
'''
test=r'''
static void reset(void){calls=fail_call=seen_count=applies=apply_error=requests=releases=request_error=0;}
int main(void){
 _Static_assert(sizeof(struct cam_flash_query_curr)==12,"generic ABI");
 _Static_assert(sizeof(struct cam_flash_query_curr_nezha)==8,"stock ABI");
 _Static_assert(offsetof(struct cam_flash_query_curr_nezha,cmd_type)==3,"stock type");
 _Static_assert(offsetof(struct cam_flash_query_curr_nezha,query_current_ma)==4,"stock current");
 _Static_assert(offsetof(struct cam_flash_query_curr,query_current_ma)==6,"generic current");
 struct cam_flash_ctrl fc={.pmic_lcdev={&fc}};struct cam_flash_private_soc sp={0};
 struct cam_flash_query_curr_nezha q={.reserved=0xabcd,.opcode=7,.cmd_type=CAMERA_SENSOR_FLASH_CMD_TYPE_QUERYCURR,.query_current_ma=99};
 struct cam_flash_query_curr g={.cmd_type=CAMERA_SENSOR_FLASH_CMD_TYPE_QUERYCURR,.query_current_ma=99};
 assert(cam_flash_is_nezha_query(&q,sizeof(q))==!!CONFIG_TARGET_PRODUCT_NEZHA);
 assert(cam_flash_query_current_buf(&fc,&q,sizeof(q),&sp)==(CONFIG_TARGET_PRODUCT_NEZHA?0:-EINVAL));
 if(CONFIG_TARGET_PRODUCT_NEZHA)assert(q.query_current_ma==1500&&q.reserved==0xabcd&&q.opcode==7);
 assert(!cam_flash_query_current_buf(&fc,&g,sizeof(g),&sp)&&g.query_current_ma==1500);
 flash_error=-EIO;g.query_current_ma=88;assert(cam_flash_query_current_buf(&fc,&g,sizeof(g),&sp)==-EIO&&g.query_current_ma==88);flash_error=0;
 fc.pmic_lcdev[0]=NULL;assert(cam_flash_query_current_buf(&fc,&g,sizeof(g),&sp)==-ENODEV&&g.query_current_ma==88);fc.pmic_lcdev[0]=&fc;
 flash_current=-1;assert(cam_flash_query_current_buf(&fc,&g,sizeof(g),&sp)==-ERANGE);flash_current=1500;
 for(size_t n=0;n<8;n++){void*b=calloc(1,n?n:1);assert(cam_flash_query_current_buf(&fc,b,n,&sp)==-EINVAL);free(b);}
 /* Truncation uses exact allocations so ASan detects pre-validation reads. */
 size_t fixed=sizeof(struct cam_cmd_ois_fw_info_v2), full=fixed+sizeof(struct cam_cmd_ois_fw_param);
 for(size_t n=0;n<full;n++) {void*b=calloc(1,n?n:1);if(n>=fixed)((struct cam_cmd_ois_fw_info_v2*)b)->fw_count=255;assert(cam_ois_fw_info_input_check(b,n)==-EINVAL);free(b);}
 struct cam_cmd_ois_fw_info_v2 *info=calloc(1,full+7);info->fw_count=1;
 assert(!cam_ois_fw_info_input_check((void*)info,full));
 info->param_mask=1;info->params[0]=3;info->fw_param[0].fw_init_size=2;info->fw_param[0].fw_finalize_size=2;
 assert(!cam_ois_fw_info_input_check((void*)info,full+7));
 info->fw_param[0].fw_init_size=UINT32_MAX;assert(cam_ois_fw_info_input_check((void*)info,full+7)==-EINVAL);free(info);
 struct cam_cmd_ois_fw_param p={.fw_name="test.bin",.fw_size=7,.fw_len_per_write=3,.fw_data_type=1,.fw_operation=1};
 uint8_t*data=malloc(7);for(int i=0;i<7;i++)data[i]=i+1;
 struct camera_io_master io={0};
 assert(!write_ois_fw(data,CAM_ENDIANNESS_LITTLE,&p,io,CAM_SENSOR_I2C_WRITE_RANDOM));assert(calls==3&&seen_count==7&&seen[6]==7&&!allocs);
 for(int i=1;i<=3;i++){reset();fail_call=i;assert(write_ois_fw(data,CAM_ENDIANNESS_LITTLE,&p,io,1)==-EIO);assert(calls==i&&!allocs);}
 reset();p.fw_data_type=0;assert(write_ois_fw(data,2,&p,io,1)==-EINVAL&&!calls);p.fw_data_type=1;
 p.fw_len_per_write=0;assert(write_ois_fw(data,2,&p,io,1)==-EINVAL);p.fw_len_per_write=3;
 p.fw_reg_addr=UINT32_MAX;assert(write_ois_fw(data,2,&p,io,1)==-EINVAL);p.fw_reg_addr=0;
 alloc_fail=1;assert(write_ois_fw(data,2,&p,io,1)==-ENOMEM);alloc_fail=0;
 p.fw_data_type=2;p.fw_size=6;p.fw_len_per_write=4;reset();assert(!write_ois_fw(data+1,2,&p,io,1));assert(seen_count==3&&seen[0]==0x0302&&seen[2]==0x0706);
 reset();assert(!write_ois_fw(data+1,1,&p,io,1));assert(seen[0]==0x0203&&seen[2]==0x0607);
 p.fw_data_type=1;p.fw_size=7;p.fw_len_per_write=3;
 struct i2c_settings_array init={.is_settings_valid=1},final={.is_settings_valid=1};struct platform_device dev={0};
 struct cam_ois_ctrl_t c={.fw_info={.fw_count=1,.endianness=2,.fw_param=&p},.i2c_fw_init_data=&init,.i2c_fw_finalize_data=&final,.pdev=&dev};
 image.data=data;image.size=7;reset();assert(!cam_ois_fw_download_v2(&c));assert(applies==2&&requests==1&&releases==1&&calls==3);
 reset();fail_call=1;assert(cam_ois_fw_download_v2(&c)==-EIO);assert(applies==1&&releases==1&&calls==1);
 reset();p.fw_start_pos=8;assert(cam_ois_fw_download_v2(&c)==-EINVAL&&!calls&&releases==1);p.fw_start_pos=0;
 reset();p.fw_data_type=0;assert(cam_ois_fw_download_v2(&c)==-EINVAL&&!requests);p.fw_data_type=1;
 reset();c.i2c_fw_version_data.is_settings_valid=1;apply_error=-EIO;assert(cam_ois_fw_download_v2(&c)==-EIO&&!requests);
 reset();request_error=-ENOENT;assert(cam_ois_fw_download_v2(&c)==-ENOENT&&!calls&&!releases);
 free(data);assert(!allocs);
 puts("PASS: generic/Nezha flash ABI, OIS table truncation, partial/unaligned firmware chunks, I/O/allocation errors and download cleanup");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 c=Path(tmp)/'test.c';exe=Path(tmp)/'test';c.write_text(pre+structs+post+check+body+flash+test)
 for nezha in (0,1):
  subprocess.run([os.getenv('CC','cc'),'-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',f'-DCONFIG_TARGET_PRODUCT_NEZHA={nezha}',str(c),'-o',str(exe)],check=True)
  env=dict(os.environ);env.setdefault('ASAN_OPTIONS','detect_leaks=0');subprocess.run([str(exe)],check=True,env=env,timeout=30)
