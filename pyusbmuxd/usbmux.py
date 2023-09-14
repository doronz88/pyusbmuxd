import logging
from enum import IntEnum
from typing import Optional

from usb.core import find, Configuration, Device

INTERFACE_CLASS = 255
INTERFACE_SUBCLASS = 254
INTERFACE_PROTOCOL = 2

# libusb fragments packets larger than this (usbfs limitation)
# on input, this creates race conditions and other issues
USB_MRU = 16384

# max transmission packet size
# libusb fragments these too, but doesn't send ZLPs so we're safe
# but we need to send a ZLP ourselves at the end (see usb-linux.c)
# we're using 3 * 16384 to optimize for the fragmentation
# this results in three URBs per full transfer, 32 USB packets each
# if there are ZLP issues this should make them show up easily too
USB_MTU = (3 * 16384)

USB_PACKET_SIZE = 512

VID_APPLE = 0x5ac
PID_RANGE_LOW = 0x1290
PID_RANGE_MAX = 0x12af
PID_APPLE_T2_COPROCESSOR = 0x8600
PID_APPLE_SILICON_RESTORE_LOW = 0x1901
PID_APPLE_SILICON_RESTORE_MAX = 0x1905

ENV_DEVICE_MODE = 'USBMUXD_DEFAULT_DEVICE_MODE'
APPLE_VEND_SPECIFIC_GET_MODE = 0x45
APPLE_VEND_SPECIFIC_SET_MODE = 0x52


class LibUSBRequestType(IntEnum):
    STANDARD = 0x00 << 5
    CLASS = 0x01 << 5
    VENDOR = 0x02 << 5
    RESERVED = 0x03 << 5


class LibUSBEndpointDirection(IntEnum):
    IN = 0x80
    OUT = 0x00


class LibUSBRequestRecipient(IntEnum):
    DEVICE = 0x00
    INTERFACE = 0x01
    ENDPOINT = 0x02
    OTHER = 0x03


class USB:
    def __init__(self):
        self.devices = []
        self.logger = logging.getLogger(__name__)

    def discover(self) -> None:
        devices = find(find_all=True)
        if devices is None:
            return
        for device in devices:
            self._handle_device(device)

    def _handle_device(self, device: Device) -> None:
        if device.idVendor != VID_APPLE:
            return
        if ((device.idProduct != PID_APPLE_T2_COPROCESSOR) and
                ((device.idProduct < PID_APPLE_SILICON_RESTORE_LOW) or
                 (device.idProduct > PID_APPLE_SILICON_RESTORE_MAX)) and
                ((device.idProduct < PID_RANGE_LOW) or
                 (device.idProduct > PID_RANGE_MAX))):
            return

        self.logger.info(f'Found new device with v/p {device.idVendor:04x}:{device.idProduct:04x} '
                         f'at {device.bus}-{device.address}')
        a = self._submit_vendor_specific(device, APPLE_VEND_SPECIFIC_GET_MODE, data_or_wLength=4)
        print(a)

    def _submit_vendor_specific(self, device: Device, bRequest: int, wValue: int = 0, wIndex: int = 0,
                                data_or_wLength: Optional[bytes] = None, timeout: Optional[int] = None):
        request_type = LibUSBRequestType.VENDOR.value | LibUSBEndpointDirection.IN.value | \
                       LibUSBRequestRecipient.DEVICE.value
        return device.ctrl_transfer(request_type, bRequest, wValue, wIndex, data_or_wLength, timeout)
