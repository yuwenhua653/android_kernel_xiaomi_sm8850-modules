#!/usr/bin/env python3
"""Host fault injection of the actual SEM1218S firmware routines (no hardware IO).
Requires a C compiler. Extracts source bodies, replaces kernel/device services
with test doubles, and checks error propagation, cleanup and update ordering.
"""
from pathlib import Path
import os, re, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
zoom = root / 'drivers/cam_sensor_module/cam_zoom'
core = (zoom / 'cam_zoom_core.c').read_text()
helper = (zoom / 'Sem1218s_zoom.c').read_text()
header = (zoom / 'Sem1218s_zoom.h').read_text()
def function(text, name):
    m = re.search(r'^(?:static )?(?:int32_t|int|uint32_t) '+name+r'\(', text, re.M)
    assert m, name
    start = text.index('{', m.start()); depth = 1; end = start + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}'); end += 1
    return text[m.start():end]
pre = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define CAM_ERR(...) ((void)0)
#define CAM_INFO(...) ((void)0)
#define CAM_DBG(...) ((void)0)
#define msleep(n) ((void)0)
#define ZOOM_NAME_LEN 64
#define CAMERA_SENSOR_I2C_TYPE_WORD 2
#define CAMERA_SENSOR_I2C_TYPE_BYTE 1
#define CAM_SENSOR_I2C_WRITE_SEQ 3
struct camera_io_master { int dummy; };
struct cam_sensor_i2c_reg_array { uint32_t reg_addr, reg_data, delay, data_mask; };
struct cam_sensor_i2c_reg_setting {
 struct cam_sensor_i2c_reg_array *reg_setting;
 uint32_t size, addr_type, data_type, delay;
};
struct device { int dummy; } dev;
struct cam_zoom_ctrl_t {
 struct { struct device *dev; } soc_info;
 struct camera_io_master io_master_info;
 uint32_t zoom_3polefw_version, zoom_5polefw_version, zoom_5poleP2fw_version;
 uint32_t zoom_5poleP2Recalfw_version, zoom_hw_version;
 uint8_t noupdate_fw_flash;
 char zoom_name[64];
};
struct firmware { size_t size; const uint8_t *data; };
static int zoomfwctrl;
static unsigned int zoomFwVersion, zoomHwVersion;
static int io_count, fail_io, allocations, alloc_count, fail_alloc;
static int fw_error, fw_releases, fw_active, crc_sent, reset_sent, bad_crc, bad_version;
static uint32_t current_version;
static unsigned char fake_data[APP_FW_SIZE];
static struct firmware fake_fw = {APP_FW_SIZE, fake_data};
static uint32_t get_unaligned_le32(const void *p) {
 const uint8_t *b=p; return b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);
}
static void put_unaligned_le32(uint32_t x, void *p) {
 uint8_t *b=p; for(int i=0;i<4;i++) b[i]=(x>>(i*8))&255;
}
static void *vmalloc(size_t n) {
 if (++alloc_count == fail_alloc) return NULL;
 void *p=malloc(n); assert(p); allocations++; return p;
}
static void vfree(void *p) { if(p){ allocations--; free(p); } }
static int request_firmware(const struct firmware **f, const char *n, struct device *d) {
 assert(d==&dev); assert(n); if(fw_error) return fw_error;
 *f=&fake_fw; fw_active++; return 0;
}
static void release_firmware(const struct firmware *f) {
 assert(f==&fake_fw); fw_releases++; fw_active--;
}
static int io_step(void) { return ++io_count == fail_io ? -EREMOTEIO : 0; }
static int i2c_read_data_seq(struct camera_io_master *m,uint32_t addr,uint32_t len,uint8_t *data) {
 int rc=io_step(); if(rc) return rc;
 memset(data,0,len);
 if(addr==REG_APP_VER) put_unaligned_le32(reset_sent ? (bad_version?3:2) : current_version,data);
 if(addr==REG_FWUP_ERR) data[0]=bad_crc;
 return 0;
}
static int i2c_write_data_seq(struct camera_io_master *m,uint32_t addr,uint32_t len,uint8_t *data,uint32_t delay) {
 int rc=io_step(); if(rc) return rc;
 if(addr==REG_FWUP_CRC) crc_sent++;
 if(addr==REG_FWUP_CTRL && data[0]==RESET_REQ) reset_sent++;
 return 0;
}
static int camera_io_dev_write_continuous(struct camera_io_master *m,struct cam_sensor_i2c_reg_setting *s,int mode) {
 assert(s->size==256); return io_step();
}
static void reset_test(void) {
 assert(allocations==0 && fw_active==0);
 io_count=fail_io=alloc_count=fail_alloc=fw_error=fw_releases=crc_sent=reset_sent=bad_crc=bad_version=0;
 current_version=1; zoomfwctrl=0; fake_fw.size=APP_FW_SIZE;
 memset(fake_data,0,sizeof(fake_data)); put_unaligned_le32(2,fake_data+APP_FW_SIZE-12);
}
'''
main = r'''
int main(void) {
 struct cam_zoom_ctrl_t z={.soc_info.dev=&dev,.zoom_3polefw_version=2,.zoom_hw_version=0};
 strcpy(z.zoom_name,"sem1218s");
 reset_test(); assert(cam_sem1218s_zoom_fw_download(&z)==0);
 int steps=io_count; assert(crc_sent==1 && reset_sent==1 && fw_releases==1);
 assert(allocations==0 && fw_active==0);
 for(int i=1;i<=steps;i++) {
  reset_test(); fail_io=i;
  assert(cam_sem1218s_zoom_fw_download(&z)==-EREMOTEIO);
  assert(io_count==i && allocations==0 && fw_active==0);
 }
 for(int i=1;i<=2;i++) {
  reset_test(); fail_alloc=i;
  assert(cam_sem1218s_zoom_fw_download(&z)==-ENOMEM);
  assert(io_count==1 && allocations==0 && fw_active==0);
 }
 reset_test(); fw_error=-ENOENT;
 assert(cam_sem1218s_zoom_fw_download(&z)==-ENOENT && io_count==1 && !allocations);
 reset_test(); fake_fw.size=APP_FW_SIZE-1;
 assert(cam_sem1218s_zoom_fw_download(&z)==-EINVAL && io_count==1 && fw_releases==1 && !allocations);
 reset_test(); bad_crc=1;
 assert(cam_sem1218s_zoom_fw_download(&z)==-EIO && !reset_sent && !allocations);
 reset_test(); bad_version=1;
 assert(cam_sem1218s_zoom_fw_download(&z)==-EIO && reset_sent && !allocations);
 reset_test(); current_version=2;
 assert(cam_sem1218s_zoom_fw_download(&z)==0 && io_count==1 && !alloc_count);
 reset_test(); z.noupdate_fw_flash=1;
 assert(cam_sem1218s_zoom_fw_download(&z)==0 && io_count==1 && !allocations);
 assert(!fw_active);
 printf("PASS: %d firmware IO failure points, allocation failures, missing/short firmware, CRC/version errors, success and skip paths\n", steps);
}
'''
defines = '\n'.join(l for l in header.splitlines() if l.startswith('#define '))
defines += '\n' + '\n'.join(l for l in core.splitlines() if l.startswith('#define ZOOM_HW_VERSION_'))
source = '#include <stdint.h>\n' + defines + '\n' + pre + '\n'
source += function(helper, 'CalculateCRC32') + '\n' + function(helper, 'load_fw_buff') + '\n'
source += function(core, 'cam_sem1218s_zoom_fw_download') + '\n' + main
abi_source = '#include <time.h>\n#include <stdint.h>\n#include <sys/types.h>\n#include <stddef.h>\n#include <media/cam_sensor.h>\n#include <media/cam_req_mgr.h>\n_Static_assert(sizeof(struct cam_sensor_query_cap) == 40, "generic ABI");\n_Static_assert(sizeof(struct cam_sensor_query_cap_nezha) == 44, "Nezha ABI");\n_Static_assert(offsetof(struct cam_sensor_query_cap_nezha, zoom_slot_id) == 40, "zoom slot");\n_Static_assert(sizeof(struct cam_zoom_query_cap) == 8, "zoom query ABI");\n_Static_assert(sizeof(struct cam_cmd_zoom_info) == 93, "stock zoom info ABI");\n_Static_assert(offsetof(struct cam_cmd_zoom_info, zoom_name) == 28, "zoom name");\n_Static_assert(offsetof(struct cam_cmd_zoom_info, noupdate_fw_flash) == 92, "flash flag");\n_Static_assert(CAM_ZOOM_PACKET_OPCODE_PROBE == 5, "probe opcode");\n_Static_assert(CAM_ZOOM_DEVICE_TYPE == CAM_DEVICE_TYPE_BASE + 20, "device type");\n'
with tempfile.TemporaryDirectory(prefix='nezha-zoom-test-') as temp:
    abi = Path(temp)/'abi.c'; abi.write_text(abi_source)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-fsyntax-only','-I',str(root/'include/uapi/camera'),str(abi)],check=True)
    print('PASS: generic 40-byte / Nezha 44-byte query and stock 93-byte zoom ABI', flush=True)
    c = Path(temp)/'test.c'; binary = Path(temp)/'test'; c.write_text(source)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O1','-g','-fsanitize=address,undefined',str(c),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
