#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compile the actual public header in generic and Nezha configurations."""
from pathlib import Path
import os, subprocess, tempfile
root = Path(__file__).resolve().parents[1]
source = r'''
#include <time.h>
#include <stdint.h>
#include <sys/types.h>
#include <stddef.h>
#include <media/cam_sensor.h>
_Static_assert(sizeof(struct cam_sensor_query_cap) == 40, "generic sensor ABI");
_Static_assert(sizeof(struct cam_cmd_set_power_voltage) == 8, "voltage ABI");
_Static_assert(offsetof(struct cam_cmd_set_power_voltage, delay_ms) == 6, "delay offset");
_Static_assert(CAM_OIS_PACKET_OPCODE_OIS_PARKLENS == 4, "OIS park opcode");
_Static_assert(CAM_ACTUATOR_PACKET_OPCODE_MIPARK_LENS == 5, "MI park opcode");
_Static_assert(CAM_ACTUATOR_PACKET_OPCODE_SET_VOLTAGE == 6, "voltage opcode");
_Static_assert(CAMERA_SENSOR_POWER_CMD_TYPE_SET_VOLTAGE == 19, "voltage type");
#if CONFIG_TARGET_PRODUCT_NEZHA
_Static_assert(MAX_OIS_NAME_SIZE == 64, "OEM name");
_Static_assert(sizeof(struct cam_ois_opcode) == 29, "OEM opcode ABI");
_Static_assert(sizeof(struct cam_cmd_ois_info) == 101, "OEM slave info ABI");
_Static_assert(offsetof(struct cam_cmd_ois_info, opcode) == 72, "OEM opcode offset");
_Static_assert(offsetof(struct cam_ois_opcode, is_ois_fw_update) == 28, "update flag offset");
#else
_Static_assert(MAX_OIS_NAME_SIZE == 32, "generic name");
_Static_assert(sizeof(struct cam_ois_opcode) == 16, "generic opcode ABI");
_Static_assert(sizeof(struct cam_cmd_ois_info) == 56, "generic slave info ABI");
_Static_assert(offsetof(struct cam_cmd_ois_info, opcode) == 40, "generic opcode offset");
#endif
'''
with tempfile.TemporaryDirectory() as d:
    path = Path(d) / 'abi.c'
    path.write_text(source)
    for mode in [0, 1]:
        subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-fsyntax-only',
                        f'-DCONFIG_TARGET_PRODUCT_NEZHA={mode}', '-I',
                        str(root / 'include/uapi/camera'), str(path)], check=True)
print('PASS: actual generic/OEM OIS UAPI sizes, field offsets, park and voltage command values')
