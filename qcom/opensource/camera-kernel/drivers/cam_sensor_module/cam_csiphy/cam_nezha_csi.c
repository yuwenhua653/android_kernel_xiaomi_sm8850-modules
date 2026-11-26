// SPDX-License-Identifier: GPL-2.0-only
/* Nezha OS4 CSI control protocol from MiCode songyuan-w-oss.
 * Keep the UMD path/command encoding; serialize IRQ and userspace updates.
 */
#include <linux/errno.h>
#include <linux/kobject.h>
#include <linux/slab.h>
#include <linux/spinlock.h>
#include <linux/sysfs.h>
#include "cam_nezha_csi.h"
#include "cam_isp_hw_mgr_intf.h"

#define NEZHA_PHY_COUNT 8
#define CSI_CRC_DIVISOR 0x1000
#define CSI_FULL_RECOVERY 0x1001
#define CSI_AUTO_EQ 0x1002
#define CSI_RESET_EQ 0x1003
#define CSI_BACKUP_EQ 0x1004
#define CSI_ERROR_MASKS 0x1005

static DEFINE_SPINLOCK(csi_lock);
static struct kobject *csi_kobj;
/* Bits 56..63: retry flags; bits 0..31: per-PHY four-bit choices. */
static u64 eq_state;
static u32 crc_divisor;
static u32 backup_eq;
static bool auto_eq;
static bool full_recovery;
static u64 error_policy;

#define NEZHA_CSID_ERROR_BITS (CAM_ISP_HW_ERROR_CSID_FATAL | \
 CAM_ISP_HW_ERROR_CSID_OUTPUT_FIFO_OVERFLOW | CAM_ISP_HW_ERROR_CSID_FRAME_SIZE | \
 CAM_ISP_HW_ERROR_CSID_LANE_FIFO_OVERFLOW | CAM_ISP_HW_ERROR_CSID_PKT_HDR_CORRUPTED | \
 CAM_ISP_HW_ERROR_CSID_MISSING_PKT_HDR_DATA | CAM_ISP_HW_ERROR_CSID_SENSOR_SWITCH_ERROR | \
 CAM_ISP_HW_ERROR_CSID_UNBOUNDED_FRAME | CAM_ISP_HW_ERROR_CSID_SENSOR_FRAME_DROP | \
 CAM_ISP_HW_ERROR_CSID_MISSING_EOT | CAM_ISP_HW_ERROR_CSID_PKT_PAYLOAD_CORRUPTED | \
 CAM_ISP_HW_ERROR_CSID_CAMIF_FRAME_DROP | CAM_ISP_HW_ERROR_CSID_MISSING_SOT | \
 CAM_ISP_HW_ERROR_CSID_ILLEGAL_DT_SWITCH | CAM_ISP_HW_ERROR_CSID_RUP_MISS)

u8 cam_nezha_csi_choice(u32 phy, u8 choices)
{
	unsigned long flags;
	u8 choice = 0;
	u64 retry, mask;

	if (phy >= NEZHA_PHY_COUNT || !choices)
		return 0;
	spin_lock_irqsave(&csi_lock, flags);
	if (backup_eq) {
		choice = min_t(u8, (backup_eq >> (phy * 2)) & 3, choices - 1);
	} else if (auto_eq) {
		retry = BIT_ULL(56 + phy);
		mask = 0xfULL << (phy * 4);
		choice = ((eq_state >> (phy * 4)) & 0xf) % choices;
		if (eq_state & retry)
			choice = (choice + 1) % choices;
		eq_state = (eq_state & ~(retry | mask)) | ((u64)choice << (phy * 4));
	}
	spin_unlock_irqrestore(&csi_lock, flags);
	return choice;
}

void cam_nezha_csi_crc(u32 phy)
{
	unsigned long flags;

	if (phy >= NEZHA_PHY_COUNT)
		return;
	spin_lock_irqsave(&csi_lock, flags);
	eq_state |= BIT_ULL(56 + phy);
	spin_unlock_irqrestore(&csi_lock, flags);
}

u32 cam_nezha_csi_crc_divisor(u32 fallback)
{
	u32 divisor = READ_ONCE(crc_divisor);

	return divisor ? divisor : fallback;
}

bool cam_nezha_csi_full_recovery(void)
{
	return READ_ONCE(full_recovery);
}

/* Apply one coherent UMD snapshot. Unspecified errors keep their defaults. */
bool cam_nezha_csi_error_policy(u32 *fatal, u32 *recoverable)
{
	unsigned long flags;
	u64 policy;
	u32 f, r;

	spin_lock_irqsave(&csi_lock, flags);
	policy = error_policy;
	spin_unlock_irqrestore(&csi_lock, flags);
	if (!policy)
		return false;
	f = policy >> 32;
	r = policy;
	*fatal = (*fatal & ~r) | f;
	*recoverable = (*recoverable & ~f) | r;
	return true;
}

static int cam_nezha_csi_command(u64 cmd, u64 value)
{
	unsigned long flags;
	int rc = 0;

	spin_lock_irqsave(&csi_lock, flags);
	switch (cmd) {
	case CSI_CRC_DIVISOR:
		if (!value || value > 65535)
			rc = -ERANGE;
		else
			WRITE_ONCE(crc_divisor, value);
		break;
	case CSI_FULL_RECOVERY:
	case CSI_AUTO_EQ:
		if (value > 1) {
			rc = -ERANGE;
			break;
		}
		if (cmd == CSI_FULL_RECOVERY)
			WRITE_ONCE(full_recovery, value);
		else
			auto_eq = value;
		break;
	case CSI_RESET_EQ:
		if (value & 0x00ffffff00000000ULL)
			rc = -ERANGE;
		else
			eq_state = value;
		break;
	case CSI_BACKUP_EQ:
		if (value > 0xffff)
			rc = -ERANGE;
		else
			backup_eq = value;
		break;
	case CSI_ERROR_MASKS:
		if (!value || ((u32)value & (u32)(value >> 32)) ||
		    (((u32)value | (u32)(value >> 32)) & ~NEZHA_CSID_ERROR_BITS))
			rc = -EINVAL;
		else
			error_policy = value;
		break;
	default:
		rc = -EINVAL;
	}
	spin_unlock_irqrestore(&csi_lock, flags);
	return rc;
}

static ssize_t csiphy_umd_paras_show(struct kobject *kobj,
	struct kobj_attribute *attr, char *buf)
{
	unsigned long flags;
	u64 value;

	spin_lock_irqsave(&csi_lock, flags);
	value = eq_state;
	spin_unlock_irqrestore(&csi_lock, flags);
	return sysfs_emit(buf, "%llx", value);
}

static ssize_t csiphy_umd_paras_store(struct kobject *kobj,
	struct kobj_attribute *attr, const char *buf, size_t count)
{
	char *copy, *cursor, *cmd_str, *value_str;
	u64 cmd, value;
	int rc = -EINVAL;

	if (!count || count > 63 || memchr(buf, '\0', count))
		return -EINVAL;
	copy = kmemdup_nul(buf, count, GFP_KERNEL);
	if (!copy)
		return -ENOMEM;
	cursor = copy;
	cmd_str = strsep(&cursor, ",");
	value_str = strsep(&cursor, ",");
	if (!value_str || cursor || kstrtou64(cmd_str, 0, &cmd) ||
		kstrtou64(value_str, 0, &value))
		goto out;
	rc = cam_nezha_csi_command(cmd, value);
out:
	kfree(copy);
	return rc ? rc : count;
}

static struct kobj_attribute csi_attr =
	__ATTR(csiphy_umd_paras, 0644, csiphy_umd_paras_show, csiphy_umd_paras_store);

int cam_nezha_csi_init(void)
{
	int rc;

	csi_kobj = kobject_create_and_add("csiphy_umd_paras", NULL);
	if (!csi_kobj)
		return -ENOMEM;
	rc = sysfs_create_file(csi_kobj, &csi_attr.attr);
	if (rc) {
		kobject_put(csi_kobj);
		csi_kobj = NULL;
	}
	return rc;
}

void cam_nezha_csi_exit(void)
{
	if (csi_kobj) {
		sysfs_remove_file(csi_kobj, &csi_attr.attr);
		kobject_put(csi_kobj);
		csi_kobj = NULL;
	}
}
