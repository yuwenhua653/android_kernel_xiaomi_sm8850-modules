#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Exercise the real camera acquire/release cases and CCI power-lock selection."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1] / "drivers/cam_sensor_module"
act = (root / "cam_actuator/cam_actuator_core.c").read_text()
ois = (root / "cam_ois/cam_ois_core.c").read_text()
util = (root / "cam_sensor_utils/cam_sensor_util.c").read_text()


def function(src, name):
    m = re.search(r"^static (?:int|void) " + name + r"\([^;]*?\)\s*\{", src, re.M)
    assert m, name
    return src[m.start():src.index("\n}", m.end()) + 2] + "\n"


def case(src, name):
    start = src.index("case " + name + ":")
    return src[start:src.index("\n\tcase ", start)]


pre = r"""
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <pthread.h>
typedef pthread_mutex_t pmutex;
#define mutex pmutex
#define DEFINE_MUTEX(x) pmutex x=PTHREAD_MUTEX_INITIALIZER
#define mutex_lock(p) pthread_mutex_lock((void *)(p))
#define mutex_unlock(p) pthread_mutex_unlock((void *)(p))
#define mutex_init(p) pthread_mutex_init((void *)(p),NULL)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define CCI_MASTER 1
struct cci{int cci_device,cci_i2c_master;};
struct camera_io_master{int master_type;struct cci *cci_client;};
#define CAM_ERR(...) ((void)0)
#define CAM_WARN(...) ((void)0)
#define CAM_DBG(...) ((void)0)
#define READ_ONCE(x) (x)
enum {CAM_ACTUATOR_INIT, CAM_ACTUATOR_ACQUIRE, CAM_ACTUATOR_CONFIG, CAM_ACTUATOR_START};
enum {CAM_OIS_INIT, CAM_OIS_ACQUIRE, CAM_OIS_CONFIG, CAM_OIS_START};
enum {CAM_ACQUIRE_DEV, CAM_RELEASE_DEV, CAM_ACTUATOR, CAM_OIS};
struct cam_control {int op_code;uintptr_t handle;};
struct cam_sensor_acquire_dev{int session_handle,device_handle;};
struct cam_create_dev_hdl{int session_hdl,v4l2_sub_dev_flag,media_entity_flag,dev_id;void *priv,*ops;};
struct bridge {int device_hdl,link_hdl,session_hdl,ops;};
struct cam_sensor_power_ctrl_t {void *power_setting,*power_down_setting;int power_setting_size,power_down_setting_size;};
struct cam_ois_soc_private{struct cam_sensor_power_ctrl_t power_info;};
struct devinfo {void *soc_private;};
struct settings {int is_settings_valid;};
struct cam_ois_ctrl_t {struct bridge bridge_intf;int cam_ois_state,ois_fw_flag,is_ois_calib;
 struct devinfo soc_info;struct settings i2c_fwinit_data,i2c_fw_version_data,i2c_mode_data,i2c_init_data,i2c_calib_data;
 struct settings *i2c_fw_init_data,*i2c_fw_finalize_data; struct {int fw_count;void *fw_param;}fw_info;};
struct cam_actuator_ctrl_t {struct bridge bridge_intf;int cam_act_state,is_deferred_park_lens,last_flush_req;pmutex actuator_park_mutex;};
static int live,fault_in,fault_out,fault_destroy,fault_down,shutdowns,deleted;
#define u64_to_user_ptr(h) ((void *)(h))
static int copy_from_user(void *dst,void *src,size_t n){if(fault_in)return 2;memcpy(dst,src,n);return 0;}
static int copy_to_user(void *dst,void *src,size_t n){if(fault_out)return 2;memcpy(dst,src,n);return 0;}
static int cam_create_device_hdl(struct cam_create_dev_hdl *p){assert(!live);live=7;return live;}
static int cam_destroy_device_hdl(int h){assert(h==live);if(fault_destroy)return -EIO;live=0;return 0;}
#define CAM_MEM_FREE(p) free(p)
static int delete_request(struct settings *s){assert(s->is_settings_valid);s->is_settings_valid=0;deleted++;return 0;}
static int cam_actuator_wait_for_park_done(struct cam_actuator_ctrl_t *a){return -ETIMEDOUT;}
static int cam_actuator_power_down(struct cam_actuator_ctrl_t *a){shutdowns++;return fault_down;}
static int cam_ois_power_down(struct cam_ois_ctrl_t *o){shutdowns++;return fault_down;}
"""
cci = util[util.index("static struct mutex nezha_cci_power"):util.index("#endif", util.index("static struct mutex nezha_cci_power"))]
# Model the kernel mutex type with a pthread mutex, preserving production indexing and lock scope.
cci = cci.replace("struct mutex", "pmutex")
code = pre + cci + function(ois, "cam_ois_get_dev_handle") + function(ois, "cam_ois_free_session")
code += """
static int act_cmd(struct cam_actuator_ctrl_t *a_ctrl,struct cam_control *cmd,struct cam_sensor_power_ctrl_t *power_info){
 int rc=0;switch(cmd->op_code){
""" + case(act, "CAM_ACQUIRE_DEV") + case(act, "CAM_RELEASE_DEV") + "}release_mutex:return rc;}\n"
code += """
static int ois_cmd(struct cam_ois_ctrl_t *o_ctrl,struct cam_control *cmd){int rc=0;void *arg=cmd;switch(cmd->op_code){
""" + case(ois, "CAM_ACQUIRE_DEV") + case(ois, "CAM_RELEASE_DEV") + "}release_mutex:return rc;}\n"
code += r"""
int main(void){
 struct cam_sensor_acquire_dev user={4,0};struct cam_control cmd={CAM_ACQUIRE_DEV,(uintptr_t)&user};
 struct cam_actuator_ctrl_t a={.bridge_intf={-1,-1,-1},.actuator_park_mutex=PTHREAD_MUTEX_INITIALIZER};
 struct cam_ois_soc_private soc={0};
 struct cam_ois_ctrl_t o={.bridge_intf={-1,-1,-1},.soc_info={&soc}};
 struct cam_sensor_power_ctrl_t *p=&soc.power_info;
 fault_in=1;assert(act_cmd(&a,&cmd,p)==-EFAULT&&!live);assert(ois_cmd(&o,&cmd)==-EFAULT&&!live);fault_in=0;
 fault_out=1;assert(act_cmd(&a,&cmd,p)==-EFAULT&&!live&&a.bridge_intf.device_hdl==-1);
 assert(ois_cmd(&o,&cmd)==-EFAULT&&!live&&o.bridge_intf.device_hdl==-1);fault_out=0;
 assert(!act_cmd(&a,&cmd,p)&&live);p->power_setting=malloc(8);p->power_down_setting=malloc(8);
 cmd.op_code=CAM_RELEASE_DEV;a.cam_act_state=CAM_ACTUATOR_CONFIG;a.bridge_intf.link_hdl=3;
 assert(act_cmd(&a,&cmd,p)==-EAGAIN&&!shutdowns&&p->power_setting);
 a.bridge_intf.link_hdl=-1;fault_down=-EREMOTEIO;assert(act_cmd(&a,&cmd,p)==-EREMOTEIO&&live&&p->power_setting);
 fault_down=0;fault_destroy=1;assert(act_cmd(&a,&cmd,p)==-EIO&&a.cam_act_state==CAM_ACTUATOR_ACQUIRE&&live);
 fault_destroy=0;assert(!act_cmd(&a,&cmd,p)&&!live&&!p->power_setting&&!p->power_down_setting&&shutdowns==2);
 cmd.op_code=CAM_ACQUIRE_DEV;assert(!act_cmd(&a,&cmd,p));cmd.op_code=CAM_RELEASE_DEV;assert(!act_cmd(&a,&cmd,p)&&!live);
 cmd.op_code=CAM_ACQUIRE_DEV;assert(!ois_cmd(&o,&cmd)&&live);o.cam_ois_state=CAM_OIS_ACQUIRE;
 o.i2c_fw_version_data.is_settings_valid=1;o.fw_info.fw_count=2;o.fw_info.fw_param=malloc(16);
 o.i2c_fw_init_data=calloc(2,sizeof(struct settings));o.i2c_fw_finalize_data=calloc(2,sizeof(struct settings));
 o.i2c_fw_init_data[1].is_settings_valid=1;o.i2c_fw_finalize_data[0].is_settings_valid=1;o.ois_fw_flag=1;
 cmd.op_code=CAM_RELEASE_DEV;assert(!ois_cmd(&o,&cmd)&&deleted==3&&!live&&!o.i2c_fw_init_data&&!o.i2c_fw_finalize_data);
 assert(!o.i2c_fw_version_data.is_settings_valid&&!o.fw_info.fw_count&&!o.fw_info.fw_param&&!o.ois_fw_flag);
 cmd.op_code=CAM_ACQUIRE_DEV;assert(!ois_cmd(&o,&cmd));cmd.op_code=CAM_RELEASE_DEV;assert(!ois_cmd(&o,&cmd)&&!live);
 cam_nezha_init_cci_power_locks();struct cci client={2,1};struct camera_io_master io={CCI_MASTER,&client};
 pmutex *first=cam_nezha_lock_cci_power(&io);assert(pthread_mutex_trylock(first)==EBUSY);
 client.cci_i2c_master=0;pmutex *second=cam_nezha_lock_cci_power(&io);assert(second!=first);mutex_unlock(second);mutex_unlock(first);
 client.cci_i2c_master=-1;first=cam_nezha_lock_cci_power(&io);assert(first==&nezha_unknown_cci_power);mutex_unlock(first);
 io.master_type=0;assert(!cam_nezha_lock_cci_power(&io));puts("PASS session reopen, partial user copies, power/handle retries, firmware release and separate CCI masters");
}
"""
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp)
    (path / "test.c").write_text(code)
    subprocess.run([os.environ.get("CC", "cc"), "-std=gnu11", "-pthread", "-fsanitize=address,undefined",
                    str(path / "test.c"), "-o", str(path / "test")], check=True)
    subprocess.run([str(path / "test")], check=True)
