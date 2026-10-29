# Calling a Courier through a SIP ATA

For the build-109 Analog kernel backend, use `--firmware-set analog109`,
`--kernel-dispatch`, `--modem-role auto`, `--tx-v42`, `--v42-pty` and `--at`.
Add `--tx-v42bis` to request compression; the peer must also enable it.
`--dial-target HOST:PORT` selects the SIP endpoint. Omit `--dial NUMBER` to
start idle, attach to the printed PTY and use `ATDT100` to originate a call.
Dial commands wait for CONNECT or a call failure; they do not return an
immediate OK. Command echo may still appear while the call is dialing.
Press any key while dialing or training to abort without pressing Enter;
the terminal returns NO CARRIER. The CRLF ending the dial command is not
an abort. Once CONNECT is reported, ordinary keypresses are modem data;
use the guarded escape sequence and ATH to hang up instead.

Cancelled SIP calls may still receive late answers. The endpoint ACKs each
late answer with the original INVITE sequence and sends only one BYE, without
starting modem media or disturbing a subsequent dial attempt.

## In-call media updates

The endpoint accepts SDP-bearing re-INVITEs in an established incoming or
outgoing dialog. A supported IPv4 G.711 `sendrecv` offer updates the RTP
destination without rebuilding the DSP, resetting its sample clock or
clearing audio queues. A PBX can therefore request direct media and later
move media back through itself. The configured PCMU or PCMA payload must
remain available in the offer; no codec conversion is introduced.

The endpoint checks dialog tags and remote CSeq, caches responses to duplicate
requests, and retransmits 200 OK until ACK. Missing ACK for 32 seconds releases
the call. Unsupported offers, including hold and offers without SDP, receive
488 while existing media settings remain active; separate calls still receive
486 Busy Here. Late RTP from the previous destination cannot undo the update
through symmetric RTP learning. Target refreshes also update the Contact used
for subsequent BYE requests. Normal logs show `[sip] re-INVITE: RTP -> ...`.

`tests/test_sip_reinvite.py` covers target refreshes, replay, ACK, modem state
preservation, rejected offers, wrong dialogs, stale CSeq values and late RTP.
These new tests and live PBX direct-media calls have not been run for this
change.

## System Python

`run.sh` uses `exec /usr/bin/python3 -u` and does not depend on `.venv`.
The Analog kernel-dispatch path uses Python's standard library plus the
compiled native ADSP library and extracted build-109 Analog firmware.
Unicorn is required only when selecting the optional native MIPS backend.
DSP assertions and PC histograms also work without that backend installed.

A subsequent system-Python call test negotiated V.34/LAPM/V.42bis. The
Courier verified the complete outgoing deterministic payload, and the
emulator received an exact 13,783-byte prefix of the reverse payload.
Retraining prevented the full reverse payload from completing before the
test timeout. This validates bidirectional data on system Python, not a
sustained-transfer qualification of the connection. The serial-side mgetty
service was temporarily stopped for the direct test and restored afterward.

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
compression option. The default verbose terminal result includes modulation,
error correction, compression and directional rates, for example:

```text
CONNECT V34/LAPM/V42BIS/31200:TX/16800:RX
```

The compression field is NONE when no codec was negotiated. Numeric and
minimal CONNECT modes keep their shorter results; normal connection logs
still include the negotiated compression.

V.42bis can switch between compressed and transparent transmission during
a call. After ETM, the decoder terminates the old match and treats the next
character as unmatched before restarting transparent string matching.
Keeping that boundary aligned with the peer prevents dictionary divergence,
garbled output and later invalid-codeword errors. The runtime suite includes
a SpanDSP-produced transition vector, tested with fragmented codec input
and across LAPM information frames; SpanDSP is not a runtime dependency.

## Observed interoperability

A physical USRobotics Courier through a Cisco SPA112 connected using
V.34/LAPM at 31200/14400 bit/s. Deterministic payloads of more than 16,000
characters in each direction matched their expected SHA-256 hashes. The
call remained connected for about 88 seconds until deliberately stopped.
This was tested with compression disabled (`AT&K0` on the Courier).
Subsequently, with `--tx-v42bis` and Courier `AT&K1`, the peer reported
`V42BIS 512/32` and `LAPM 128/15`; that observation confirms negotiation,
not a repeat of the two-way integrity test with compression enabled. A later
packaged-service validation did verify complete payloads in both directions
with V.42bis and maintained the connection for about 70 seconds.

Keep the Courier serial terminal open so DTR and RTS are asserted. Use
`AT&M5S0=1` to require error correction and enable autoanswer. These are
volatile settings unless explicitly saved on the modem.

## V.34 speed limits

Before dialing, set the receive and transmit windows with the AT terminal:

```text
AT+MS=v34,0,2400,14400,2400,14400
ATDT100
```

The argument order is modulation, automode, minimum RX, maximum RX,
minimum TX, maximum TX. This example selects V.34 only (automode 0),
with 2400..14400 bit/s in both directions. For a fixed 9600-bit/s attempt:

```text
AT+MS=v34,0,9600,9600,9600,9600
ATDT100
```

AT+IE accepts the same arguments; AT+MS? displays the current selection.
Set commands before the next call; changes do not reconfigure an active
call. ATZ resets the modem profile. With no explicit rate selection the
existing unrestricted defaults are retained.

The direct Analog and Analog kernel backends pass the AT selection into
the next card's modulation menu and V.34 write database before training.
The shared capability mask covers the union of TX/RX windows, and separate
maximum-rate words cap each direction in 2400-bit/s units. Since the DSP
has no separate TX/RX minimum words, the host also checks negotiated
V.34 rates against both complete windows. An out-of-window rate ends the
call with NO CARRIER, including after retraining. A prebooted card with
older settings is not reused for the new selection.

These changes implement V.34 rate limits; they do not add Analog-backend
rate control for other modulations. Native MIPS retains its existing CAI
configuration path. This implementation has not been tested; validation
was explicitly left to the user.

## Stable terminal

For the packaged service, open `tio /dev/modem-emu` from a login session
that belongs to the standard `dialout` group. The service owns the runtime directory
and publishes the current PTY through the public symlink. See
[the service guide](service.md) for installation and permissions.

`--pty-link PATH` requires `--v42-pty`. Startup replaces a dangling symlink
but refuses to replace a regular file or live target. On close, it removes
the symlink only if it still points to that instance. The parent directory
must already exist and be writable by the process.

For an isolated development session alongside the installed service:

```bash
./run.sh --sip-port 5092 --rtp-port 4102 --pty-link /tmp/modem-emu-dev
# In another terminal on dev:
tio /tmp/modem-emu-dev
```

Do not install the earlier kostik-owned manual tmpfiles definition over the
packaged service's definition. The development launcher uses the same
compatibility settings and V.42bis, starts idle for ATDT100, and uses the
current ATA target. Its default terminal/ports are reserved by the installed
service, so use overrides as above when running both.

## Logging

The launcher defaults to normal (`info`) logging. AT commands, symbolic
results, connection rates/protocol/compression and call lifecycle events go
to standard output. Data-mode terminal payloads and routine DSP/media
telemetry stay out of normal logs. Use `./run.sh --log-level debug` to restore
detailed diagnostics. Captures remain separately controlled and disabled by
default. No systemd unit is installed by this logging change.
