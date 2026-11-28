#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Production OEM park transactions and generic actuator completion/error paths.
I2C/power/workqueue services are host models; mechanical movement is not tested.
"""
from pathlib import Path
import os,re,subprocess,tempfile
r=Path(__file__).resolve().parents[1]
def fn(s,n):
 m=re.search(r'static\s+(?:int|int32_t)\s+' +n+r'\([^;]*?\)\s*\{',s);assert m,n
 p=m.end();d=1
 while d:d+=(s[p]=='{')-(s[p]=='}');p+=1
 return s[m.start():p]+'\n'
pre=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#define CAM_OIS_CONFIG 2
#define CAM_OIS_ACQUIRE 1
#define CAM_ACTUATOR_CONFIG 2
#define CAM_ACTUATOR_ACQUIRE 1
#define CAM_ACTUATOR_INIT 0
#define WRITE_ONCE(x,v) ((x)=(v))
struct list_head {int initialized;};struct i2c_settings_array {struct list_head list_head;int is_settings_valid,allocated;};
struct cam_cmd_buf_desc {int length;};struct camera_io_master {int unused;};
struct cam_sensor_power_ctrl_t {void *power_setting,*power_down_setting;int power_setting_size,power_down_setting_size;};
struct cam_actuator_soc_private {struct cam_sensor_power_ctrl_t power_info;};struct soc_info {void *soc_private;};
struct cam_actuator_ctrl_t {int cam_act_state,actuator_park_mutex,park_lens_complete;bool is_deferred_park_lens;struct camera_io_master io_master_info;struct soc_info soc_info;struct {struct i2c_settings_array config_settings;}i2c_data;};
struct cam_ois_ctrl_t {int cam_ois_state;struct camera_io_master io_master_info;};
static int parse_error,apply_error,power_error,delete_error,parsed,applied,powered,deleted,allocs,freed,completed;
static void INIT_LIST_HEAD(struct list_head *l){l->initialized=1;}
static void mutex_lock(int *m){assert(!*m);*m=1;}static void mutex_unlock(int *m){assert(*m);*m=0;}
static void complete_all(int *c){*c=1;completed++;}
static void cam_mem_free(void *p){if(p)freed++;}
#define CAM_MEM_FREE(p) cam_mem_free(p)
static int cam_sensor_i2c_command_parser(struct camera_io_master *io,struct i2c_settings_array *s,struct cam_cmd_buf_desc *d,int n,void *unused){(void)io;(void)d;(void)unused;assert(n==1&&s->list_head.initialized&&s->is_settings_valid);parsed++;s->allocated=1;allocs++;return parse_error;}
static int apply(void){applied++;return apply_error;}static int power(void){powered++;return power_error;}
static int cam_actuator_apply_settings(struct cam_actuator_ctrl_t *c,struct i2c_settings_array *s){(void)c;assert(s->allocated);return apply();}
static int cam_ois_apply_settings(struct cam_ois_ctrl_t *c,struct i2c_settings_array *s){(void)c;assert(s->allocated);return apply();}
static int cam_actuator_power_down(struct cam_actuator_ctrl_t *c){(void)c;return power();}
static int cam_ois_power_down(struct cam_ois_ctrl_t *c){(void)c;return power();}
static int delete_request(struct i2c_settings_array *s){deleted++;if(s->allocated){s->allocated=0;allocs--;}return delete_error;}
static void reset(void){assert(!allocs);parse_error=apply_error=power_error=delete_error=parsed=applied=powered=deleted=freed=completed=0;}
'''
s=(r/'drivers/cam_sensor_module/cam_actuator/cam_actuator_core.c').read_text();body=fn(s,'cam_actuator_nezha_park')+fn(s,'cam_actuator_park_lens_cb')
s=(r/'drivers/cam_sensor_module/cam_ois/cam_ois_core.c').read_text();body+=fn(s,'cam_ois_nezha_park')
main=r'''
int main(void){
 struct cam_cmd_buf_desc d={1};
 for(int which=0;which<2;which++)for(int failure=0;failure<4;failure++){
  reset();struct cam_actuator_ctrl_t a={.cam_act_state=2};struct cam_ois_ctrl_t o={.cam_ois_state=2};
  if(failure==1)parse_error=-ENOMEM;if(failure==2)apply_error=-EIO;if(failure==3)power_error=-EREMOTEIO;
  int ret=which?cam_ois_nezha_park(&o,&d):cam_actuator_nezha_park(&a,&d);
  assert(ret==(failure==1?-ENOMEM:failure==2?-EIO:failure==3?-EREMOTEIO:0));assert(deleted==1&&!allocs&&!a.actuator_park_mutex);
  assert(powered==(failure==1?0:1));assert(applied==(failure==1?0:1));assert((which?o.cam_ois_state:a.cam_act_state)==((failure==0||failure==2)?1:2));
 }
 reset();struct cam_actuator_ctrl_t a={.cam_act_state=2,.is_deferred_park_lens=true};assert(cam_actuator_nezha_park(&a,&d)==-EBUSY&&!parsed&&!a.actuator_park_mutex);assert(cam_actuator_nezha_park(NULL,&d)==-EINVAL);struct cam_ois_ctrl_t o={0};assert(cam_ois_nezha_park(&o,&d)==-EINVAL);
 for(int failure=0;failure<4;failure++){
  reset();struct cam_actuator_soc_private sp={.power_info={.power_setting=(void*)1,.power_down_setting=(void*)2,.power_setting_size=1,.power_down_setting_size=1}};
  a=(struct cam_actuator_ctrl_t){.cam_act_state=2,.is_deferred_park_lens=true,.soc_info={&sp},.i2c_data.config_settings={.allocated=1}};allocs=1;
  if(failure==1)apply_error=-EIO;if(failure==2)power_error=-EREMOTEIO;if(failure==3){apply_error=-EIO;power_error=-EREMOTEIO;delete_error=-EINVAL;}
  int ret=cam_actuator_park_lens_cb(&a,NULL);assert(ret==((failure==1||failure==3)?-EIO:failure==2?-EREMOTEIO:0));assert(completed==1&&!allocs&&!a.is_deferred_park_lens&&!a.actuator_park_mutex&&powered==1);
  if(power_error){assert(!freed&&sp.power_info.power_setting&&sp.power_info.power_down_setting&&a.cam_act_state==2);}else{assert(freed==2&&!sp.power_info.power_setting&&!sp.power_info.power_down_setting&&a.cam_act_state==0);}
 }
 puts("PASS: OEM OIS/actuator park, partial parse cleanup, movement/power errors, state acknowledgment, generic park completion and retained retry resources");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+main)
 subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-g','-fsanitize=address,undefined',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
