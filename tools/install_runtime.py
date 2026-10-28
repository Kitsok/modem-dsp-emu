#!/usr/bin/python3
"""Stage only runtime modules, native ADSP library and Analog firmware."""
import argparse
import ast
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

def stage(destination, library, firmware):
    if not library.is_file():
        raise ValueError(f'missing native library: {library}')
    for item in ('kernel', 'tikrnl', 'overlays'):
        if not (firmware/item).is_dir():
            raise ValueError(f'missing extracted Analog firmware: {firmware/item}')
    runtime = destination/'usr/lib/modem-emu'
    tools = runtime/'tools'
    tools.mkdir(parents=True, exist_ok=True)
    pending = ['modem_service']; seen = set()
    while pending:
        name = pending.pop()
        source = REPO/'tools'/(name+'.py')
        if name in seen or not source.is_file():
            continue
        seen.add(name)
        shutil.copyfile(source, tools/source.name)
        for node in ast.walk(ast.parse(source.read_text())):
            if isinstance(node, ast.Import):
                pending.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                pending.append(node.module.split('.')[0])
    (tools/'adsp2181emu').mkdir(exist_ok=True)
    shutil.copyfile(library, tools/'adsp2181emu/libadsp2181.dylib')
    target = runtime/'artifacts/eicon-dsp/build-109-789-analog'
    shutil.copytree(firmware, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    files = [('bin/modem-emu','usr/bin/modem-emu'),
             ('config/modem-emu.ini','etc/modem-emu.conf'),
             ('systemd/modem-emu.service','usr/lib/systemd/system/modem-emu.service'),
             ('systemd/modem-emu.sysusers','usr/lib/sysusers.d/modem-emu.conf'),
             ('systemd/modem-emu.tmpfiles','usr/lib/tmpfiles.d/modem-emu.conf')]
    for source, name in files:
        target = destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(REPO/source,target)
        target.chmod(0o755 if name=='usr/bin/modem-emu' else 0o644)
    for path in runtime.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destdir',type=Path,required=True)
    parser.add_argument('--library',type=Path,required=True)
    parser.add_argument('--firmware',type=Path,default=Path(os.environ.get('MODEM_FIRMWARE_DIR',str(REPO/'artifacts/eicon-dsp/build-109-789-analog'))))
    args=parser.parse_args()
    try:stage(args.destdir,args.library,args.firmware)
    except ValueError as exc:parser.error(str(exc))
