#!/usr/bin/python3
"""Launch the Analog modem with configuration applied before backend imports."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from modem_config import DEFAULT_CONFIG, load_config, runtime_options


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--check-config', action='store_true')
    selected, remaining = parser.parse_known_args(argv)
    try:
        values = load_config(selected.config or DEFAULT_CONFIG,
                             required=selected.config is not None)
    except ValueError as exc:
        parser.error(str(exc))
    options, environment = runtime_options(values)
    if selected.check_config:
        print('Configuration OK')
        return 0
    # Several backend constants are read at import time.
    os.environ.update(environment)
    sys.argv = [sys.argv[0], *options, *remaining]
    from eicon_adsp_sip import main as run_endpoint
    return run_endpoint()


if __name__ == '__main__':
    raise SystemExit(main())
