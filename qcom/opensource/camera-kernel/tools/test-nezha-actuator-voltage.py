#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production actuator voltage transaction: descriptor ownership and rollback.
Kernel buffers and regulators are modeled; no physical rail is programmed.
"""
from pathlib import Path
import re,os,subprocess,tempfile
r=Path(__file__).resolve().parents[1];s=(r/'drivers/cam_sensor_module/cam_actuator/cam_actuator_core.c').read_text()
a=s.index('static int cam_actuator_set_voltage(');p=s.index('{',a)+1;d=1
while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
fn=s[a:p]
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#define MAX_POWER_CONFIG 12
#define CAM_SOC_MAX_REGULATOR 4
#define CAM_ACTUATOR_CONFIG 2
#define SENSOR_BOB 8
#define SENSOR_VAF 4
#define CAMERA_SENSOR_POWER_CMD_TYPE_SET_VOLTAGE 19
#define GFP_KERNEL 0
#define CAM_ERR(...) ((void)0)
#define IS_ERR_OR_NULL(x) (!(x)||(uintptr_t)(x)>=(uintptr_t)-4095)
struct regulator {int uv;};
struct cam_hw_soc_info {int num_rgltr;struct regulator *rgltr[4];const char *rgltr_name[4];};
struct cam_actuator_ctrl_t {int cam_act_state;struct cam_hw_soc_info soc_info;};
struct cam_cmd_buf_desc {int mem_handle;uint32_t offset,length;};
struct cam_cmd_set_power_voltage {uint32_t voltage;uint8_t pin_type,cmd_type;uint16_t delay_ms;} __attribute__((packed));
static void *buffer;static size_t buffer_size;static int refs,allocs,alloc_fail,get_fail,support_error,read_error,sets,set_fail,rollback_fail,delay_calls;
static int cam_mem_get_cpu_buf(int h,uintptr_t *p,size_t *s){(void)h;if(get_fail)return -EIO;*p=(uintptr_t)buffer;*s=buffer_size;refs++;return 0;}
static void cam_mem_put_cpu_buf(int h){(void)h;assert(refs==1);refs--;}
static void *kmemdup(const void *p,size_t n,int f){(void)f;if(alloc_fail)return NULL;void *v=malloc(n);assert(v);memcpy(v,p,n);allocs++;return v;}
static void kfree(void *p){if(p){allocs--;free(p);}}
static int regulator_is_supported_voltage(struct regulator *r,int lo,int hi){(void)r;assert(lo==hi);return support_error?support_error:lo>=1000000&&lo<=4000000;}
static int regulator_get_voltage(struct regulator *r){return read_error?read_error:r->uv;}
static int regulator_set_voltage(struct regulator *r,int lo,int hi){assert(!refs&&lo==hi);r->uv=lo;sets++;if(sets==set_fail)return -EIO;if(sets==rollback_fail)return -EBUSY;return 0;}
static void msleep(int ms){assert(!refs&&ms>0);delay_calls++;}
'''
main=r'''
int main(void){
 _Static_assert(sizeof(struct cam_cmd_set_power_voltage)==8,"voltage ABI");
 struct regulator bob={3000000},vaf={2800000};struct cam_actuator_ctrl_t ctrl={.cam_act_state=2,.soc_info={.num_rgltr=2,.rgltr={&bob,&vaf},.rgltr_name={"cam_bob","cam_vaf"}}};
 struct cam_cmd_set_power_voltage commands[2]={{3100000,SENSOR_BOB,19,1},{2900000,SENSOR_VAF,19,0}};
 struct cam_cmd_buf_desc d={.mem_handle=1,.length=sizeof(commands)};
 buffer=commands;buffer_size=sizeof(commands);assert(!cam_actuator_set_voltage(&ctrl,&d));assert(bob.uv==3100000&&vaf.uv==2900000&&sets==2&&!refs&&!allocs&&delay_calls==1);
 for(int f=1;f<=2;f++){bob.uv=3000000;vaf.uv=2800000;sets=0;set_fail=f;assert(cam_actuator_set_voltage(&ctrl,&d)==-EIO);assert(bob.uv==3000000&&vaf.uv==2800000&&!refs&&!allocs);}
 sets=0;set_fail=1;rollback_fail=2;assert(cam_actuator_set_voltage(&ctrl,&d)==-EIO&&!refs&&!allocs);set_fail=rollback_fail=0;
 for(int n=0;n<16;n++){void *shortbuf=malloc(n?n:1);memcpy(shortbuf,commands,n);buffer=shortbuf;buffer_size=n;sets=0;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL&&!sets&&!refs&&!allocs);free(shortbuf);}
 buffer=commands;buffer_size=sizeof(commands);sets=0;d.offset=UINT_MAX;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL&&!refs);d.offset=0;d.length=9;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL);d.length=16;
 alloc_fail=1;assert(cam_actuator_set_voltage(&ctrl,&d)==-ENOMEM&&!refs&&!allocs);alloc_fail=0;get_fail=1;assert(cam_actuator_set_voltage(&ctrl,&d)==-EIO&&!refs);get_fail=0;
 commands[1].cmd_type=18;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL&&!sets&&!refs&&!allocs);commands[1].cmd_type=19;commands[1].pin_type=99;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL&&!sets);commands[1].pin_type=SENSOR_VAF;commands[1].voltage=5000000;assert(cam_actuator_set_voltage(&ctrl,&d)==-ERANGE&&!sets);commands[1].voltage=2900000;
 support_error=-EIO;assert(cam_actuator_set_voltage(&ctrl,&d)==-EIO&&!sets&&!refs);support_error=0;read_error=-ENODEV;assert(cam_actuator_set_voltage(&ctrl,&d)==-ENODEV&&!sets&&!refs);read_error=0;
 ctrl.cam_act_state=0;assert(cam_actuator_set_voltage(&ctrl,&d)==-EINVAL);assert(cam_actuator_set_voltage(NULL,&d)==-EINVAL);
 puts("PASS: 8-byte voltage ABI, exact descriptor bounds, buffer/allocation ownership, full prevalidation, regulator rollback and original errno");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+fn+main)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
