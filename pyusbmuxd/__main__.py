import logging
from typing import List

import click
import coloredlogs
import inquirer3
from inquirer3.themes import GreenPassion

from pyusbmuxd.exceptions import NoIDeviceSelectedError
from pyusbmuxd.usb_manager import UsbManager, IDevice, Mode

coloredlogs.install(level=logging.DEBUG)


def set_verbosity(ctx, param, value):
    coloredlogs.set_level(logging.INFO - (value * 10))


def prompt_device_list(device_list: List):
    device_question = [inquirer3.List('device', message='choose device', choices=device_list, carousel=True)]
    try:
        result = inquirer3.prompt(device_question, theme=GreenPassion(), raise_keyboard_interrupt=True)
        return result['device']
    except KeyboardInterrupt:
        raise NoIDeviceSelectedError()


class Command(click.Command):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.params[:0] = [
            click.Option(('verbosity', '-v', '--verbose'), count=True, callback=set_verbosity, expose_value=False),
            click.Option(('device', '-s', '--serial'), callback=self.choose_device),
        ]
        self.service_provider = None

    @staticmethod
    def choose_device(ctx, param, value: str) -> IDevice:
        usb_manager = UsbManager()
        usb_manager.update_device_list()
        return prompt_device_list(usb_manager.devices.values())


@click.group()
def cli() -> None:
    pass


@cli.command('list')
def cli_list() -> None:
    usb_manager = UsbManager()
    usb_manager.update_device_list()

    for device in usb_manager.devices.values():
        print(device)


@cli.command('set-mode', cls=Command)
@click.argument('mode', type=click.Choice([k.name for k in Mode]))
def cli_set_mode(device: IDevice, mode: str) -> None:
    device.mode = Mode.create_from_name(mode)


if __name__ == '__main__':
    cli()
