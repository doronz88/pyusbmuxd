import logging

import click
import coloredlogs

from pyusbmuxd.usbmux import USB

coloredlogs.install(level=logging.DEBUG)

@click.command()
def cli() -> None:
    usb = USB()
    usb.discover()


if __name__ == '__main__':
    cli()
