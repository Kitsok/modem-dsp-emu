# Packaged modem service

This guide describes the private `modem-emu` Debian package. It uses system
Python, the native ADSP library and extracted Analog build-109 firmware.
Unicorn and a virtual environment are not required. Public redistribution
rights for the project and firmware remain unverified; see `debian/copyright`.

## Build and install

Prepare the extracted Analog firmware at
`artifacts/eicon-dsp/build-109-789-analog`, containing `kernel`, `tikrnl` and
`overlays`. Running `./build.sh` from a Linux checkout prepares these inputs
and tests the source runtime without installing anything. Alternatively set
`MODEM_FIRMWARE_DIR` to an already extracted directory. From the repository
root, with the dependencies in `debian/control` installed:

```sh
dpkg-buildpackage -us -uc -b
python3 -S tests/check_deb.py ../modem-emu_0.1.0+local3_amd64.deb
sudo apt install ../modem-emu_0.1.0+local3_amd64.deb
```

The archive is architecture-specific and declares its native libc dependency.
Build on the target distribution or an appropriate build environment when
moving to another architecture/distribution. The command above names the
amd64 artifact; other architectures produce their corresponding suffix.

Installation creates the `modem-emu` service account and its private group,
runs the service with the standard `dialout` group, enables the service
at boot and starts it idle. The installed runtime is under
`/usr/lib/modem-emu`, with `/usr/bin/modem-emu` as its entrypoint. No files in
`/home/kostik/work/modem-dsp-emu` are required by the installed service.

If migrating from the earlier manual setup, inspect
`/etc/tmpfiles.d/modem-emu.conf`. A local file with that name overrides the
packaged `/usr/lib/tmpfiles.d/modem-emu.conf`. Remove or archive the old local
file only if it is the manual modem definition; keep unrelated administrator
customizations. Stop a manually running emulator before using the service
on the same SIP/RTP ports. Upgrades/restarts interrupt active modem calls.

## Configure the endpoint

```sh
sudoedit /etc/modem-emu.conf
```

For the current ATA, set:

```ini
[network]
bind = 0.0.0.0
advertise = 0.0.0.0
sip_port = 5072
rtp_port = 4012
dial_target = 192.168.196.29:5060
```

The shipped target is empty: configure it before dialing. The wildcard bind
listens on all IPv4 interfaces; wildcard advertise selects the routed local
source address for each peer. An explicit advertised IP overrides selection.
The default modem settings are automatic call/answer role selection, PCMU,
30 ms packets, LAPM and V.42bis. The INI also contains terminal, logging and
compatibility sections.
Unknown sections/options and invalid values fail validation.

```sh
modem-emu --check-config
sudo systemctl restart modem-emu.service
systemctl status modem-emu.service
```

`--config PATH` selects an explicit file; missing explicit files fail.
The implicit `/etc/modem-emu.conf` is optional for manual invocation, with
built-in defaults used when absent. CLI endpoint arguments override file
settings. Compatibility values are applied before DSP modules are imported.

## Open the terminal

Grant the intended user access, then start a fresh login session:

```sh
sudo usermod -aG dialout "$USER"
tio /dev/modem-emu
```

The PTY is owned by `modem-emu:dialout` with mode 0660. Membership in the
private `modem-emu` account group is not required for terminal access.
`/dev/modem-emu` points through `/run/modem-emu/tty` to the current PTY. The
path stays stable across service restarts, but an already open terminal must
reconnect after a restart. Only one terminal client should read it at a time.
Baud rate on this PTY does not set the modem's negotiated line rate.

Enter `AT` and expect `OK`. Enter `ATDT100` to call PHONE1 on the configured
ATA. Dialing has no initial OK: wait for CONNECT or failure. A keypress while
dialing/training aborts without Enter and returns NO CARRIER. After CONNECT,
ordinary keypresses carry modem data. To hang up, stop typing for the escape
guard interval, send `+++` without Enter, wait again, then enter `ATH`.
The default verbose result includes negotiated compression, for example
`CONNECT V34/LAPM/V42BIS/31200:TX/16800:RX`. LAPM indicates error correction;
NONE in the compression field indicates that compression was not negotiated.

With `[modem] role = auto`, incoming SIP calls use the answering role and
ATDT uses the calling role in the same running service. Use `ATS0=1` to
answer automatically, or `ATS0=0` and `ATA` after RING to answer manually.
An incoming caller must send its SIP INVITE to this host's SIP port (5072 by
default). In the current lab, the ATA route `9095551020` points to
`100@172.20.20.207:5072` on both FXS lines. A physical Courier can dial that
number to reach the service. Only one active/ringing call is supported.

For a source checkout on a desktop, pass `--audio-monitor` to the launcher
along with a writable `--pty-link`. `paplay` plays mixed RX/TX audio through
the user's PulseAudio/PipeWire session. ATM0 mutes, ATM1 mutes after modem
CONNECT, ATM2 plays throughout, and ATL0..3 selects low-to-high volume.
The defaults are M1 L2. The monitor is optional and never sends speaker
volume changes back to the modem line. It is intended for interactive
launches; the system service has no desktop audio-session access by default.

The answering Courier must be configured separately for autoanswer, error
correction and desired compression, with its serial application's DTR/RTS
and flow control set appropriately. If mgetty manages that port, do not open
another direct serial reader/writer at the same time.

## Logs and troubleshooting

```sh
journalctl -u modem-emu.service -f
journalctl -u modem-emu.service -b --no-pager
systemctl is-enabled modem-emu.service
```

Normal logs show AT commands/results, call events, negotiated rates,
modulation, protocol, compression, retrains and disconnect reasons. They do
not show data-mode payloads or routine DSP/media counters. Set
`[logging] level = debug` in the INI and restart to enable diagnostics, then
restore `info` after troubleshooting. Audio/packet capture is not enabled by
changing the logging level.

For terminal permission errors, check `id`, the fresh session's group list,
and the target of `readlink -f /dev/modem-emu`. For a dangling link, check
service status and journal output. For immediate NO CARRIER after ATDT,
check the configured target and SIP failure log. For training/retrains,
check both modem diagnostics and RTP delivery; SIP connection alone does not
prove a usable modem data connection.

## Service lifecycle and removal

```sh
sudo systemctl stop modem-emu.service
sudo systemctl start modem-emu.service
sudo systemctl restart modem-emu.service
sudo systemctl disable --now modem-emu.service
sudo systemctl enable --now modem-emu.service
```

The service starts idle after network-online, restarts on failure, and uses
SIGINT followed by systemd's stop timeout for orderly cleanup. Systemd owns
its runtime directory; `/var/lib/modem-emu` is available for persistent state.
The launcher has no dependency on its working directory or a user's home.

```sh
sudo apt remove modem-emu
sudo apt purge modem-emu
```

Removal stops the service. Purge removes package configuration, enablement
state and the public symlink if it still points to the package's target.
The service account/group and persistent state are deliberately retained to
avoid UID reuse and unintended data loss. Administrator-created overrides,
legacy tmpfiles definitions and terminal-user group memberships should be
reviewed separately when retiring the deployment.
