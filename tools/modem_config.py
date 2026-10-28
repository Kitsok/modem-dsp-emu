"""Validated INI configuration for the Analog modem service launcher."""
from __future__ import annotations

import configparser
import ipaddress
from pathlib import Path

DEFAULT_CONFIG = Path('/etc/modem-emu.conf')
DEFAULTS = {
    'network': dict(bind='0.0.0.0', advertise='0.0.0.0', sip_port='5072',
                    rtp_port='4012', dial_target=''),
    'modem': dict(role='auto', law='pcmu', rtp_packet_ms='30', compression='v42bis'),
    'terminal': dict(link='/run/modem-emu/tty'),
    'logging': dict(level='info'),
    'compatibility': dict(codec_mailbox='1', tx_consumption='1', data_ready='1',
                          ordered_establish='1', xid_octets='3', detect='1', detect_timeout='3600'),
}
ENV_NAMES = dict(codec_mailbox='EICON_CODEC_MAILBOX', tx_consumption='EICON_V34_TX_CONSUMPTION',
                 data_ready='EICON_V34_DATA_READY', ordered_establish='EICON_V42_ORDERED_ESTABLISH',
                 xid_octets='EICON_V42_XID_OPT_OCTETS', detect='EICON_V42_DETECT',
                 detect_timeout='EICON_V42_DETECT_TIMEOUT')


def load_config(path: Path = DEFAULT_CONFIG, *, required: bool = False):
    values = {section: dict(items) for section, items in DEFAULTS.items()}
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with path.open() as stream:
            parser.read_file(stream)
    except FileNotFoundError:
        if required:
            raise ValueError(f'configuration file does not exist: {path}')
    except (OSError, configparser.Error) as exc:
        raise ValueError(f'cannot read configuration {path}: {exc}') from exc
    if parser.defaults():
        raise ValueError('[DEFAULT] entries are not supported')
    for section in parser.sections():
        if section not in DEFAULTS:
            raise ValueError(f'unknown configuration section: {section}')
        for key, value in parser.items(section):
            if key not in DEFAULTS[section]:
                raise ValueError(f'unknown configuration option: {section}.{key}')
            values[section][key] = value.strip()
    try:
        for key in ('bind', 'advertise'):
            ipaddress.IPv4Address(values['network'][key])
        for key in ('sip_port', 'rtp_port'):
            if not 1 <= int(values['network'][key]) <= 65535:
                raise ValueError(f'network.{key} must be in 1..65535')
        if int(values['modem']['rtp_packet_ms']) not in (10, 20, 30, 40, 60):
            raise ValueError('modem.rtp_packet_ms must be 10, 20, 30, 40 or 60')
        choices = [('modem', 'role', ('auto', 'calling', 'answer')),
                   ('modem', 'law', ('pcmu', 'pcma')),
                   ('modem', 'compression', ('none', 'v42bis', 'v44')),
                   ('logging', 'level', ('info', 'debug'))]
        for section, key, allowed in choices:
            if values[section][key] not in allowed:
                raise ValueError(f'{section}.{key} must be one of {", ".join(allowed)}')
        if not Path(values['terminal']['link']).is_absolute():
            raise ValueError('terminal.link must be an absolute path')
        for key in ENV_NAMES:
            number = int(values['compatibility'][key])
            allowed = range(1, 5) if key == 'xid_octets' else (range(1, 1000001) if key == 'detect_timeout' else (0, 1))
            if number not in allowed:
                raise ValueError(f'invalid compatibility.{key}')
    except (ValueError, ipaddress.AddressValueError) as exc:
        raise ValueError(f'invalid configuration: {exc}') from exc
    return values


def runtime_options(values):
    args = ['--firmware-set', 'analog109', '--kernel-dispatch', '--tx-v42', '--v42-pty', '--at']
    fields = [('network', 'bind', '--bind'), ('network', 'advertise', '--advertise'),
              ('network', 'sip_port', '--sip-port'), ('network', 'rtp_port', '--rtp-port'),
              ('modem', 'role', '--modem-role'), ('modem', 'law', '--law'),
              ('modem', 'rtp_packet_ms', '--rtp-packet-ms'), ('terminal', 'link', '--pty-link'),
              ('logging', 'level', '--log-level')]
    for section, key, option in fields:
        args.extend((option, values[section][key]))
    if values['network']['dial_target']:
        args.extend(('--dial-target', values['network']['dial_target']))
    compression = values['modem']['compression']
    if compression != 'none':
        args.append('--tx-' + compression)
    env = {ENV_NAMES[key]: value for key, value in values['compatibility'].items()}
    return args, env
