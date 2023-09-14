class PyUsbMuxException(Exception):
    pass


class NoIDeviceSelectedError(PyUsbMuxException):
    pass
