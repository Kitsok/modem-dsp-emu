# Calling a Courier through a SIP ATA

For the build-109 Analog kernel backend, use `--firmware-set analog109`,
`--kernel-dispatch`, `--modem-role calling`, `--tx-v42`, `--v42-pty` and `--at`.
Add `--tx-v42bis` to request compression; the peer must also enable it.
`--dial-target HOST:PORT` selects the SIP endpoint. Omit `--dial NUMBER` to
start idle, attach to the printed PTY and use `ATDT100` to originate a call.

## Build-109 Courier compatibility settings

```bash
export EICON_CODEC_MAILBOX=1
export EICON_V34_TX_CONSUMPTION=1
export EICON_V34_DATA_READY=1
export EICON_V42_ORDERED_ESTABLISH=1
export EICON_V42_XID_OPT_OCTETS=3
export EICON_V42_DETECT=1
export EICON_V42_DETECT_TIMEOUT=3600
```

Codec-boundary polling services every 9600 Hz codec frame rather than only
one poll per 8000 Hz bearer sample. Transmit-consumption tracking uses the
ADSP instruction coverage counter to detect a TXD0 read even when firmware
clears and reasserts the request flag within one frame. This option checks
the build-109 V.34 reader instruction at PM `0x3f82` and rejects an unexpected
layout. It is a firmware-specific compatibility path, not a general ABI.

Data-ready gating waits for training state `0x00d0` before servicing LAPM.
Ordered establishment sends a 16-flag preamble and XID, waits for a decoded
XID response, then sends SABME. The optional-functions field uses three
bytes for this peer; the default remains four. The detection timeout is
measured in data-pump service calls, not milliseconds; its default is 600.
The originator accepts ADP character separators of 8–16 mark bits.

When V.34 reaches data state and LAPM is connected, the AT terminal reports
CONNECT and accepts data. The current V.34 AT result labels compression as
NONE even when V.42bis is negotiated; inspect peer diagnostics to confirm
compression rather than relying on that label.

## Observed interoperability

A physical USRobotics Courier through a Cisco SPA112 connected using
V.34/LAPM at 31200/14400 bit/s. Deterministic payloads of more than 16,000
characters in each direction matched their expected SHA-256 hashes. The
call remained connected for about 88 seconds until deliberately stopped.
This was tested with compression disabled (`AT&K0` on the Courier).
Subsequently, with `--tx-v42bis` and Courier `AT&K1`, the peer reported
`V42BIS 512/32` and `LAPM 128/15`; that observation confirms negotiation,
not a repeat of the two-way integrity test with compression enabled.

Keep the Courier serial terminal open so DTR and RTS are asserted. Use
`AT&M5S0=1` to require error correction and enable autoanswer. These are
volatile settings unless explicitly saved on the modem.
