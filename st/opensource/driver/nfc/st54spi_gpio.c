// SPDX-License-Identifier: GPL-2.0-only
/* ST54 secure element reset GPIO, Nezha Android userspace ABI. */
#include <linux/cdev.h>
#include <linux/delay.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/gpio.h>
#include <linux/gpio/consumer.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of_gpio.h>
#include <linux/platform_device.h>
#include <linux/slab.h>

#define ST54_NAME "st54spi_gpio"
#define ST54_GET   _IOW(0xeb, 1, unsigned int)
#define ST54_SET   _IOW(0xeb, 2, unsigned int)
#define ST54_RESET _IOW(0xeb, 3, unsigned int)

struct st54_gpio {
	struct device dev;
	struct cdev cdev;
	struct mutex lock;
	struct gpio_desc *reset;
};

static const struct class st54_class = { .name = ST54_NAME };

static void st54_free(struct device *dev)
{
	kfree(container_of(dev, struct st54_gpio, dev));
}

static int st54_open(struct inode *inode, struct file *file)
{
	struct st54_gpio *st = container_of(inode->i_cdev, struct st54_gpio, cdev);

	get_device(&st->dev);
	file->private_data = st;
	return 0;
}

static int st54_release(struct inode *inode, struct file *file)
{
	struct st54_gpio *st = file->private_data;

	put_device(&st->dev);
	return 0;
}

static long st54_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
	struct st54_gpio *st = file->private_data;
	int ret = 0;

	mutex_lock(&st->lock);
	if (!st->reset) {
		ret = -ENODEV;
		goto out;
	}
	switch (cmd) {
	case ST54_GET:
		ret = gpiod_get_raw_value_cansleep(st->reset);
		break;
	case ST54_SET:
		/* The vendor HAL passes an immediate value. Zero leaves reset alone. */
		if (arg > 1) {
			ret = -ENOIOCTLCMD;
		} else if (arg) {
			ret = gpiod_get_raw_value_cansleep(st->reset);
			if (ret == 0) {
				gpiod_set_raw_value_cansleep(st->reset, 1);
				msleep(10);
			} else if (ret > 0) {
				ret = 0;
			}
		}
		break;
	case ST54_RESET:
		gpiod_set_raw_value_cansleep(st->reset, 0);
		msleep(10);
		gpiod_set_raw_value_cansleep(st->reset, 1);
		break;
	default:
		ret = -ENOIOCTLCMD;
	}
out:
	mutex_unlock(&st->lock);
	return ret;
}

static const struct file_operations st54_fops = {
	.owner = THIS_MODULE,
	.open = st54_open,
	.release = st54_release,
	.unlocked_ioctl = st54_ioctl,
#ifdef CONFIG_COMPAT
	.compat_ioctl = st54_ioctl,
#endif
};

static void st54_disconnect(struct st54_gpio *st)
{
	mutex_lock(&st->lock);
	st->reset = NULL;
	mutex_unlock(&st->lock);
}

static int st54_probe(struct platform_device *pdev)
{
	struct device *parent = &pdev->dev;
	struct st54_gpio *st;
	int gpio, ret;

	gpio = of_get_named_gpio(parent->of_node, "gpio-power_nreset", 0);
	if (gpio < 0)
		return dev_err_probe(parent, gpio, "missing reset GPIO\n");
	ret = devm_gpio_request_one(parent, gpio, GPIOF_OUT_INIT_HIGH, ST54_NAME);
	if (ret)
		return dev_err_probe(parent, ret, "requesting reset GPIO\n");

	st = kzalloc(sizeof(*st), GFP_KERNEL);
	if (!st)
		return -ENOMEM;
	device_initialize(&st->dev);
	st->dev.class = &st54_class;
	st->dev.parent = parent;
	st->dev.release = st54_free;
	mutex_init(&st->lock);
	st->reset = gpio_to_desc(gpio);
	ret = dev_set_name(&st->dev, ST54_NAME);
	if (ret)
		goto put;
	ret = alloc_chrdev_region(&st->dev.devt, 0, 1, ST54_NAME);
	if (ret)
		goto put;
	cdev_init(&st->cdev, &st54_fops);
	st->cdev.owner = THIS_MODULE;
	ret = cdev_device_add(&st->cdev, &st->dev);
	if (ret) {
		st54_disconnect(st);
		unregister_chrdev_region(st->dev.devt, 1);
		goto put;
	}
	platform_set_drvdata(pdev, st);
	return 0;
put:
	put_device(&st->dev);
	return ret;
}

static void st54_remove(struct platform_device *pdev)
{
	struct st54_gpio *st = platform_get_drvdata(pdev);

	cdev_device_del(&st->cdev, &st->dev);
	st54_disconnect(st);
	unregister_chrdev_region(st->dev.devt, 1);
	put_device(&st->dev);
}

static const struct of_device_id st54_match[] = {
	{ .compatible = "st,st54spi_gpio" },
	{}
};
MODULE_DEVICE_TABLE(of, st54_match);

static struct platform_driver st54_driver = {
	.driver = { .name = ST54_NAME, .of_match_table = st54_match },
	.probe = st54_probe,
	.remove = st54_remove,
};

static int __init st54_init(void)
{
	int ret = class_register(&st54_class);

	if (ret)
		return ret;
	ret = platform_driver_register(&st54_driver);
	if (ret)
		class_unregister(&st54_class);
	return ret;
}
module_init(st54_init);

static void __exit st54_exit(void)
{
	platform_driver_unregister(&st54_driver);
	class_unregister(&st54_class);
}
module_exit(st54_exit);

MODULE_ALIAS("st54spi_gpio");
MODULE_DESCRIPTION("ST54 secure element reset GPIO");
MODULE_LICENSE("GPL");
