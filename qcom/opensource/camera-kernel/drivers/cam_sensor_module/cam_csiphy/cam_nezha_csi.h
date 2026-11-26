/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CAM_NEZHA_CSI_H
#define CAM_NEZHA_CSI_H

#include <linux/types.h>
#include <linux/kconfig.h>

#if IS_ENABLED(CONFIG_TARGET_PRODUCT_NEZHA)
int cam_nezha_csi_init(void);
void cam_nezha_csi_exit(void);
u8 cam_nezha_csi_choice(u32 phy, u8 choices);
void cam_nezha_csi_crc(u32 phy);
u32 cam_nezha_csi_crc_divisor(u32 fallback);
bool cam_nezha_csi_full_recovery(void);
#else
static inline u8 cam_nezha_csi_choice(u32 phy, u8 choices) { return 0; }
static inline void cam_nezha_csi_crc(u32 phy) { }
static inline u32 cam_nezha_csi_crc_divisor(u32 fallback) { return fallback; }
static inline bool cam_nezha_csi_full_recovery(void) { return false; }
#endif
#endif
