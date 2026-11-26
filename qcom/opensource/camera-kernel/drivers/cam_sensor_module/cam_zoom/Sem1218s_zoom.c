#include <linux/module.h>
#include <linux/firmware.h>
#include <cam_sensor_cmn_header.h>
#include "cam_zoom_core.h"
#include "cam_zoom_soc.h"
#include "cam_sensor_util.h"
#include "cam_debug_util.h"
#include "cam_res_mgr_api.h"
#include "cam_common_util.h"
#include "cam_packet_util.h"
#include "Sem1218s_zoom.h"

uint32_t CalculateCRC32(uint8_t *data, uint32_t size) {
	uint32_t crc_table[256];
	uint32_t i, j, crc_accum;

	for (i = 0; i < 256; i++) {
		crc_accum = i << 24;
		for (j = 0; j < 8; j++)  {
			if (crc_accum & 0x80000000ul)
				crc_accum = (crc_accum << 1) ^ POLYNOMIAL;
			else
				crc_accum = (crc_accum << 1);
			}
		crc_table[i] = crc_accum;
	}

	crc_accum = 0;
	for (j = 0; j < size; j++) {
		i = ((uint32_t)(crc_accum >> 24) ^ *data ++) & 0xff;
		crc_accum = (crc_accum << 8) ^ crc_table[i];
	}
	return crc_accum;
}

int load_fw_buff(struct cam_zoom_ctrl_t *z_ctrl, char *firmware_name,
	uint8_t *read_data, uint32_t read_length)
{
	const struct firmware *fw;
	int rc;

	if (!z_ctrl || !z_ctrl->soc_info.dev || !firmware_name ||
		!read_data || !read_length)
		return -EINVAL;
	rc = request_firmware(&fw, firmware_name, z_ctrl->soc_info.dev);
	if (rc)
		return rc;
	if (fw->size < read_length)
		rc = -EINVAL;
	else
		memcpy(read_data, fw->data, read_length);
	release_firmware(fw);
	return rc;
}
