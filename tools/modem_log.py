"""Service logging shared by the SIP endpoint and its runtime backends.

Standalone diagnostic tools keep their original output until configure() is
called. The SIP endpoint selects info (normal) or debug explicitly. No stdout
filter or process-wide print replacement is installed.
"""
from __future__ import annotations

import builtins
import logging
import sys

_logger = logging.getLogger('modem-emu')
_logger.propagate = False
_configured = False


def configure(level: str) -> None:
    global _configured
    if level not in ('info', 'debug'):
        raise ValueError('log level must be info or debug')
    for handler in _logger.handlers[:]:
        _logger.removeHandler(handler)
        handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
    _logger.addHandler(handler)
    _logger.setLevel(logging.DEBUG if level == 'debug' else logging.INFO)
    _configured = True


def debug_enabled() -> bool:
    return not _configured or _logger.isEnabledFor(logging.DEBUG)


def _print(level, *args, sep=' ', end='\n', file=None, flush=False):
    # Explicit trace files are artifacts, not service logs.
    if not _configured or (file is not None and file not in (sys.stdout, sys.stderr)):
        return builtins.print(*args, sep=sep, end=end, file=file, flush=flush)
    if _logger.isEnabledFor(level):
        message = (' ' if sep is None else sep).join(str(arg) for arg in args)
        _logger.log(level, '%s', message.rstrip('\n'))


def debug(*args, **kwargs):
    return _print(logging.DEBUG, *args, **kwargs)


def info(*args, **kwargs):
    return _print(logging.INFO, *args, **kwargs)


def warning(*args, **kwargs):
    return _print(logging.WARNING, *args, **kwargs)


def error(*args, **kwargs):
    return _print(logging.ERROR, *args, **kwargs)


def at_event(event: str, **fields) -> None:
    # repr prevents terminal control characters from forging log records.
    detail = ' '.join(f'{key}={value!r}' for key, value in fields.items())
    info(f'[at] {event}: {detail}')


def protocol(message: str) -> None:
    """Keep LAPM lifecycle events, not HDLC traces or payloads, at info."""
    if message.startswith(('[v42] LAPM connected', '[v42] disconnected:',
                           '[v42] line disturbed', '[v42] line back',
                           '[v42] non-error-corrected fallback',
                           '[v42bis] negotiated', '[v44] negotiated')) or 're-establishing the data link' in message:
        info(message)
    else:
        debug(message)


def compression_name(lapm) -> str:
    """Report active codecs, including asymmetric compression, not CLI intent."""
    codecs = (getattr(lapm, 'tx_compressor', None),
              getattr(lapm, 'rx_decompressor', None))
    names = {type(codec).__name__ for codec in codecs if codec is not None}
    if any(name.startswith('V44') for name in names):
        return 'V44'
    if any(name.startswith('V42bis') for name in names):
        return 'V42BIS'
    return 'NONE'
