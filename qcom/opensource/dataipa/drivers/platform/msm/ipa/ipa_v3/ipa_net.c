// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copyright (c) 2020, The Linux Foundation. All rights reserved.
 * Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
 */

/*
 * This module is dedicated for operations that must be performed at
 * init stage later than the main IPA driver and IPA clients manager init.
 *
 * E.g.:
 * Both net_dev driver and ipa driver are initialized during
 * the subsys_initcall, and the rmnet_ipa driver probe is called
 * by the ipa_pre_init or ipa_post_init or ipa_clients_manager_init,
 * the register_netdev() call will cause a kernel bug.
 *
 */

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include "ipa.h"
#include "ipa_i.h"
#include "ipa_qmi_service.h"
#include "rndis_ipa.h"
#include "ncm_ipa.h"

static int __init ipa_late_init(void)
{
	int rc;

	IPADBG("IPA late init\n");

	/* Set up USB client logging before publishing the WWAN driver. */
	rc = rndis_ipa_init_module();
	if (rc)
		return rc;

	rc = ncm_ipa_init_module();
	if (rc)
		goto err_rndis;

	rc = ipa3_wwan_platform_driver_register();
	if (rc) {
		IPAERR("WWAN driver registration failed: %d\n", rc);
		goto err_ncm;
	}

	return 0;

err_ncm:
	ncm_ipa_cleanup_module();
err_rndis:
	rndis_ipa_cleanup_module();
	return rc;
}
fs_initcall(ipa_late_init);

static void __exit ipa_late_exit(void)
{
	IPADBG("IPA late exit\n");
	ipa3_wwan_cleanup();
	ncm_ipa_cleanup_module();
	rndis_ipa_cleanup_module();
}
module_exit(ipa_late_exit);

MODULE_LICENSE("GPL v2");
MODULE_DESCRIPTION("IPA late init module");

