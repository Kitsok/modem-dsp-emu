#!/bin/bash
# Prepare an unprivileged Linux source checkout for ./run.sh.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ $(uname -s) != Linux ]]; then
    echo 'build.sh currently supports Linux.' >&2
    exit 1
fi

read -r -a compiler <<< "${CC:-gcc}"
missing=()
if command -v dpkg-query >/dev/null 2>&1; then
    required=(python3 libc6-dev)
    if [[ ${compiler[0]} == gcc || ${compiler[0]} == cc ]]; then
        required+=(gcc)
    fi
    for package in "${required[@]}"; do
        if [[ $(dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null || true) != installed ]]; then
            missing+=("$package")
        fi
    done
    if ((${#missing[@]})); then
        printf 'Missing required packages: %s\n' "${missing[*]}" >&2
        printf 'Install them, then rerun ./build.sh:\n  sudo apt install %s\n' "${missing[*]}" >&2
        exit 1
    fi
fi
if ! command -v "${compiler[0]}" >/dev/null 2>&1; then
    printf 'Missing C compiler: %s (install gcc or set CC).\n' "${compiler[0]}" >&2
    exit 1
fi
if [[ ! -x /usr/bin/python3 ]]; then
    echo 'Missing /usr/bin/python3; install Python 3.11 or newer.' >&2
    exit 1
fi
/usr/bin/python3 -S - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit('Python 3.11 or newer is required by run.sh.')
PY
if ! printf '#include <stdint.h>\n#include <stdlib.h>\n' |
    "${compiler[@]}" -x c -fsyntax-only -; then
    echo 'C development headers are missing or the compiler is unusable.' >&2
    echo 'On Debian/Ubuntu, install gcc and libc6-dev.' >&2
    exit 1
fi
if ! command -v paplay >/dev/null 2>&1; then
    echo 'Optional audio monitor unavailable: paplay is missing.' >&2
    echo 'For sound on Debian/Ubuntu: sudo apt install pulseaudio-utils' >&2
    echo 'The modem can still run without local sound.' >&2
fi

mkdir -p artifacts
stage=$(mktemp -d "$PWD/artifacts/.build.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
read -r -a flags <<< "${CFLAGS:--O3 -g}"
flags+=(-D_POSIX_C_SOURCE=200809L -std=c11 -Wall -Wextra -Wno-unused-parameter -Wno-sign-compare)
core=tools/adsp2181emu

echo 'Building the native ADSP core and regression test...'
"${compiler[@]}" "${flags[@]}" -fPIC -c "$core/adsp2181_core.c" -o "$stage/core.o"
"${compiler[@]}" -shared "$stage/core.o" -o "$stage/libadsp2181.dylib"
"${compiler[@]}" "${flags[@]}" "$core/eicon_adsp_run.c" "$stage/core.o" -o "$stage/eicon_adsp_run"
"${compiler[@]}" "${flags[@]}" "$core/adsp2181_core_test.c" "$stage/core.o" -o "$stage/adsp2181_core_test"
"$stage/adsp2181_core_test"
# Rename rather than overwrite a library that another emulator may have loaded.
for output in libadsp2181.dylib eicon_adsp_run adsp2181_core_test; do
    mv -f -- "$stage/$output" "$core/$output"
done

echo 'Extracting the bundled Analog build-109 firmware...'
/usr/bin/python3 -S - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, 'tools')
from eicon_dsp_extract import parse_combifile, write_download

firmware = parse_combifile(Path('docs/firmware/build-109/dspdload.bin'))
output = Path('artifacts/eicon-dsp/build-109-789-analog')
selected = []
for item in firmware['downloads']:
    description = item['description']
    category = None
    if item['download_id'] == 0x000d:
        category = 'kernel'
    elif item['download_id'] == 0x0258 and 'TIKRNL81.ANA' in description:
        category = 'tikrnl'
    elif 'Overlay' in description and ('.ANA' in description or '.A96' in description):
        category = 'overlays'
    if category:
        selected.append((item, category))
required = {0x000d, 0x0258, 0x025f, 0x0260, 0x0261, 0x0262, 0x0274}
if not required.issubset({item['download_id'] for item, _ in selected}):
    raise SystemExit('The bundled firmware is missing required Analog downloads.')
for item, category in selected:
    write_download(item, output / category)
print(f'Prepared {len(selected)} Analog firmware downloads.')
PY

echo 'Running the Python runtime tests...'
/usr/bin/python3 -S tests/run_runtime_tests.py

echo 'Build and tests passed. Flash/RAM usage: not reported by this host build.'
echo 'Ready: ./run.sh'
echo 'Then, in another terminal: tio artifacts/modem-emu.tty'
