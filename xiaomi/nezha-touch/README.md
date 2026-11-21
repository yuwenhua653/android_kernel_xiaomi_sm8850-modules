# Xiaomi 17 Ultra touch modules

Source base: MiCode/vendor_xiaomi_proprietary_touch-driver, popsicle-w-oss,
commit c286ab85f4982c9b5967e18405f4e2da0332ce4d (p2 SPI/TouchCom, QTS and
the Xiaomi touch framework). The related 15 Ultra release, xuanyuan-v-oss
at 95341472108105b1aefa6d7eff4cd093a05f32b9, uses the same two-part
design. Build this directory as a single external Kbuild unit for nezha.
It provides xiaomi_touch.ko and synaptics_tcm2.ko.

On OS4.0.7.0.XPACNXM the controller is on SPI SE19. The stock module
reads TLMM GPIO201 to choose DDIC 1 (low) or 2 (high). The native port
uses the synaptics,ddic-id-gpios descriptor supplied by the paired board
DTS and reads the selected child node's firmware, THP and test filenames.
Use the corresponding factory files in the OS4 vendor/odm environment.

The paired Canoe board display overlay supplies the factory-ordered panel
list. The notifier searches all candidates for the registered DRM panel.
If DRM defers the lookup it retries on a deferrable timer, including after
a rebind. Removal unregisters the notifier before draining queued events.
Panel events, secure touch and firmware loading still need device testing.
