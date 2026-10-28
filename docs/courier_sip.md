# Calling a Courier through a SIP ATA

For the build-109 Analog kernel backend, use `--firmware-set analog109`,
`--kernel-dispatch`, `--modem-role calling`, `--tx-v42`, `--v42-pty` and `--at`.
Add `--tx-v42bis` to request compression; the peer must also enable it.
`--dial-target HOST:PORT` selects the SIP endpoint. Omit `--dial NUMBER` to
start idle, attach to the printed PTY and use `ATDT100` to originate a call.
Dial commands wait for CONNECT or a call failure; they do not return an
immediate OK. Command echo may still appear while the call is dialing.
Press any key while dialing or training to abort without pressing Enter;
the terminal returns NO CARRIER. The CRLF ending the dial command is not
an abort. Once CONNECT is reported, ordinary keypresses are modem data;
use the guarded escape sequence and ATH to hang up instead.

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
CONNECT and accepts data. Connection logging and the AT compression field
use active negotiated codecs (NONE, V42BIS or V44), rather than the requested
compression option. Normal connection logs always include compression even
when the terminal CONNECT format omits it.

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

## Stable terminal on dev

`--pty-link PATH` requires `--v42-pty` and creates a symlink to the allocated
terminal. Startup replaces a dangling symlink but refuses to replace a
regular file or a symlink to an existing target. Closing the terminal
removes the symlink only if it still points to that instance's PTY.
The parent directory must already exist and be writable by the process.

The included `run.sh` is the dev host launcher: it binds and advertises
`172.20.20.207`, sends calls to `192.168.196.29:5060`, enables V.42bis and
the compatibility settings above, and starts idle for `ATDT100`.
It publishes the PTY at `/run/modem-emu/tty`. Adjust the addresses for
another host and run the script from the repository root.

Install the supplied tmpfiles configuration once on dev:

```bash
sudo install -m 0644 config/modem-emu.conf /etc/tmpfiles.d/modem-emu.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/modem-emu.conf
```

This creates `/run/modem-emu` owned by `kostik` and a root-owned
`/dev/modem-emu` symlink pointing to `/run/modem-emu/tty`. Systemd tmpfiles
recreates these paths at boot. Change the owner and group in the supplied
configuration before installing it for another account. The emulator runs
without root privileges and updates only the symlink in its runtime directory.

```bash
./run.sh
# In another terminal on dev:
screen /dev/modem-emu
```

Type `AT` and expect `OK`, then type `ATDT100`. The public path stays the
same across emulator restarts even when Linux allocates a different PTY.
`/dev/modem-emu` is dangling while the emulator is stopped.

## Logging

The launcher defaults to normal (`info`) logging. AT commands, symbolic
results, connection rates/protocol/compression and call lifecycle events go
to standard output. Data-mode terminal payloads and routine DSP/media
telemetry stay out of normal logs. Use `./run.sh --log-level debug` to restore
detailed diagnostics. Captures remain separately controlled and disabled by
default. No systemd unit is installed by this logging change.
