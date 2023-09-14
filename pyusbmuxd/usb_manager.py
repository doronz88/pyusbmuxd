import logging
from enum import IntEnum
from typing import Optional, Union, Mapping

from usb.core import find, Device

from pyusbmuxd.exceptions import PyUsbMuxException

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

LIBUSB_ENDPOINT_IN = 0x80
LIBUSB_ENDPOINT_OUT = 0x00

logger = logging.getLogger(__name__)


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


class Mode(IntEnum):
    """
    On top of configurations, Apple have multiple "modes" for devices, namely:
    1: An "initial" mode with 4 configurations
    2: "Valeria" mode, where configuration 5 is included with interface for
        H.265 video capture (activated when recording screen with QuickTime in macOS)
    3: "CDC NCM" mode, where configuration 5 is included with interface for
        Ethernet/USB (activated using internet-sharing feature in macOS)
    """
    INITIAL = 1
    VALERIA = 2
    CDC_NCM = 3

    @classmethod
    def create_from_name(cls, name: str) -> 'Mode':
        for k in cls:
            if k.name == name:
                return k
        raise ValueError('invalid mode name')


class IDevice:
    def __init__(self, usb_device: Device):
        self.usb_device = usb_device
        self._set_valid_configuration()

    @property
    def mode(self) -> Optional[Mode]:
        num_configurations = len(self.usb_device.configurations())
        if num_configurations <= 4:
            # Assume this is initial mode
            return Mode.INITIAL

        if num_configurations != 5:
            # Assume this is initial mode
            return None

        config = self.usb_device.configurations()[4]

        has_valeria = False
        has_cdc_ncm = False
        has_usbmux = False

        # Require both usbmux and one of the other interfaces to determine this is a valid configuration
        for interface in config.interfaces():
            if (interface.bInterfaceClass == INTERFACE_CLASS and interface.bInterfaceSubClass == 42 and
                    interface.bInterfaceProtocol == 255):
                has_valeria = True

            # https://github.com/torvalds/linux/blob/72a85e2b0a1e1e6fb4ee51ae902730212b2de25c/include/uapi/linux/usb/cdc.h#L22
            # 2 for Communication class, 0xd for CDC NCM subclass
            if (interface.bInterfaceClass == 2 and interface.bInterfaceSubClass == 0xd):
                has_cdc_ncm = True

            if (interface.bInterfaceClass == INTERFACE_CLASS and interface.bInterfaceSubClass == INTERFACE_SUBCLASS and
                    interface.bInterfaceProtocol == INTERFACE_PROTOCOL):
                has_usbmux = True

        if has_valeria and has_usbmux:
            return Mode.VALERIA

        if has_cdc_ncm and has_usbmux:
            return Mode.CDC_NCM

    @mode.setter
    def mode(self, value: Union[Mode, int]) -> None:
        self._submit_vendor_specific(APPLE_VEND_SPECIFIC_SET_MODE, w_index=int(value), data_or_w_length=1)

    @property
    def serial(self) -> str:
        return self.usb_device.serial_number

    def send(self, data: bytes) -> None:
        self.usb_device.write(self.usb_device.backend)

    def __repr__(self) -> str:
        if self.mode is not None:
            mode = self.mode.name
        else:
            mode = 'Unknown'

        return f'<{self.__class__.__name__} SERIAL:{self.serial} MODE:{mode}>'

    def _set_valid_configuration(self) -> None:
        """ Finds and sets the valid configuration, interface and endpoints on the usb_device """
        # TODO: uncomment to debug
        return

        found = False
        current_config = self.usb_device.get_active_configuration()
        for config in self.usb_device.configurations():
            for interface in config.interfaces():
                if (interface.bInterfaceClass == INTERFACE_CLASS or
                        interface.bInterfaceSubClass == INTERFACE_SUBCLASS and
                        interface.bInterfaceProtocol == INTERFACE_PROTOCOL):
                    logger.info(f'Found usbmux interface for device {self.usb_device.bus}-{self.usb_device.address}: '
                                f'{interface.bInterfaceNumber}')
                    if interface.bNumEndpoints != 2:
                        logger.warning(
                            f'Endpoint count mismatch for interface {interface.bInterfaceNumber} of device '
                            f'{self.usb_device.bus}-{self.usb_device.address}')
                        continue
                    endpoints = interface.endpoints()
                    if ((endpoints[0].bEndpointAddress & 0x80) == LIBUSB_ENDPOINT_OUT) and \
                            ((endpoints[1].bEndpointAddress & 0x80) == LIBUSB_ENDPOINT_IN):
                        self.interface = interface
                        self.ep_out = endpoints[0].bEndpointAddress
                        self.ep_in = endpoints[1].bEndpointAddress
                        logger.info(f'Found interface {interface.bInterfaceNumber} with endpoints '
                                    f'{self.ep_out:02x}/{self.ep_in:02x} for device '
                                    f'{self.usb_device.bus}-{self.usb_device.address}')
                        found = True
                    elif ((endpoints[1].bEndpointAddress & 0x80) == LIBUSB_ENDPOINT_OUT) and \
                            ((endpoints[0].bEndpointAddress & 0x80) == LIBUSB_ENDPOINT_IN):
                        self.interface = interface
                        self.ep_out = endpoints[0].bEndpointAddress
                        self.ep_in = endpoints[1].bEndpointAddress
                        logger.info(f'Found interface {interface.bInterfaceNumber} with swapped endpoints '
                                    f'{self.ep_out:02x}/{self.ep_in:02x} for device '
                                    f'{self.usb_device.bus}-{self.usb_device.address}')
                        found = True
                    else:
                        logger.warning(f'Endpoint type mismatch for interface {interface.bInterfaceNumber} of device '
                                       f'{self.usb_device.bus}-{self.usb_device.address}')
            if not found:
                continue

            # If set configuration is required, try to first detach all kernel drivers
            if current_config is None:
                logger.debug(f'Device {self.usb_device.bus}-{self.usb_device.address} is unconfigured')

            if (current_config is None) or (config.bConfigurationValue != current_config.bConfigurationValue):
                logger.info(f'Changing configuration of device {self.usb_device.bus}-{self.usb_device.address}')

                for interface in config.interfaces():
                    if self.usb_device.is_kernel_driver_active(interface.bInterfaceNumber):
                        logger.info(
                            f'Detaching kernel driver for device {self.usb_device.bus}-{self.usb_device.address}'
                            f', interface {interface.bInterfaceNumber}')
                        self.usb_device.detach_kernel_driver(interface)

            self.usb_device.set_configuration(config)

        if not found:
            raise PyUsbMuxException(f'Could not find a suitable USB interface for device '
                                    f'{self.usb_device.bus}-{self.usb_device.address}')

    def _submit_vendor_specific(self, b_request: int, w_value: int = 0, w_index: int = 0,
                                data_or_w_length: Union[bytes, int] = 0, timeout: Optional[int] = None
                                ) -> Optional[bytearray]:
        request_type = LibUSBRequestType.VENDOR.value | LibUSBEndpointDirection.IN.value | \
                       LibUSBRequestRecipient.DEVICE.value
        return self.usb_device.ctrl_transfer(request_type, b_request, w_value, w_index, data_or_w_length, timeout)


class UsbManager:
    def __init__(self):
        self.devices: Mapping[str, IDevice] = dict()

    def update_device_list(self) -> None:
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

        logger.info(f'Found new device with v/p {device.idVendor:04x}:{device.idProduct:04x} '
                    f'at {device.bus}-{device.address}')

        self.devices[device.serial_number] = IDevice(device)
