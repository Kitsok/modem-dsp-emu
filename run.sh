#!/bin/bash
export EICON_CODEC_MAILBOX=1
export EICON_V34_TX_CONSUMPTION=1
export EICON_V34_DATA_READY=1
export EICON_V42_ORDERED_ESTABLISH=1
export EICON_V42_XID_OPT_OCTETS=3
export EICON_V42_DETECT=1
export EICON_V42_DETECT_TIMEOUT=3600
# The development launcher must not depend on systemd RuntimeDirectory.
mkdir -p artifacts || exit 1
exec /usr/bin/python3 -u tools/eicon_adsp_sip.py \
  --firmware-set analog109 \
  --kernel-dispatch \
  --audio-monitor \
  --tx-v42 \
  --tx-v42bis \
  --modem-role auto \
  --bind 0.0.0.0 \
  --advertise 0.0.0.0 \
  --sip-port 5072 \
  --rtp-port 4012 \
  --law pcmu \
  --rtp-packet-ms 30 \
  --dial-target 192.168.196.254:5060 \
  --registrar 192.168.196.254:5060 \
  --username 200 \
  --v42-pty --pty-link "$PWD/artifacts/modem-emu.tty" --at "$@"
