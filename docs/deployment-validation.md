# Packaged deployment validation

The private `modem-emu` 0.1.0+local1 amd64 package was built and installed on
Ubuntu 24.04 on dev.ne-arch.online. Public redistribution rights remain
unverified. No QEMU execution or machine reboot was used.

## Build and automated checks

- Native ADSP C regression tests passed with Debian compiler/hardening flags.
- 188 focused Python runtime tests passed under system Python with site
  packages disabled.
- Archive checks passed for runtime inputs, conffiles, account/service helper
  ordering, purge cleanup and isolated runtime imports.
- The systemd integration test passed unprivileged startup, terminal group
  access, unrelated-user denial, crash recovery and stop cleanup.
- The installed-package lifecycle test passed installation, preservation of
  local configuration on upgrade, preservation of an explicitly disabled
  service, crash recovery, removal, purge and final reinstall.
- A failed lifecycle check exposed unmanaged bytecode from root CLI use.
  The installed launcher now disables bytecode generation; the check passes.
- A late-answer retransmission regression exposed duplicate BYE requests and
  mutation of the cancelled INVITE sequence. ACKs now retain the original
  sequence and only one BYE is sent; the regression passes.

## Real modem call

The installed systemd service called the Courier through Cisco SPA112 PHONE1
using ATDT100. It negotiated V.34/LAPM/V.42bis at 31200/16800 bit/s and later
changed its receive rate to 14400 bit/s. Both ends verified their complete
deterministic payloads by SHA-256:

- Emulator to Courier:
  `a50749285a7a23204979889bbfae3cdf8e34cab9678eeb7f97c8306b700fd162`
- Courier to emulator:
  `2750e3669e5de4180e3f9c574da74d1328f7992b2d3716daec82313ff0413529`

The caller recorded 70.15 seconds connected and did not lose carrier before
the deliberate service restart. The answering side recorded 73.74 seconds,
then NO CARRIER when the service hung up. The serial helper honored the
Courier's hardware flow control; the earlier direct tests did not.
The helper files retain payload traces and JSON results for review.

The answering mgetty service was stopped only for exclusive direct serial
testing and restored afterward. The emulator service was restarted and left
idle, active and enabled for boot. An actual reboot was explicitly declined;
boot enablement and restart/recovery were verified instead.

## Initial local1 state and reproduction

- `/etc/modem-emu.conf` targets `192.168.196.29:5060`, with wildcard listening
  and automatic advertised-address selection.
- `/dev/modem-emu` resolves to the current service PTY, owned by
  `modem-emu:modem-emu` with mode 0660.
- `kostik` belongs to the terminal group; existing sessions need a fresh login.
- The earlier manual tmpfiles definition was archived at
  `/var/backups/modem-emu/legacy-tmpfiles.conf` to avoid overriding the package.

`tests/integration_package.py` is a privileged, disruptive lifecycle test and
leaves the package installed. Supply `--terminal-user` and `--dial-target`
explicitly when preparing the final host configuration.
`tests/integration_call.py` verifies exact bidirectional data and fails if
connection, send completion or payload verification is missing. It requires
exclusive access to the physical serial port and a separately managed getty
stop/restore around the test.

## local2 dialout upgrade

Version 0.1.0+local2 changes the service's process group to standard `dialout`.
The PTY is now owned by `modem-emu:dialout`, mode 0660. The private service
account group remains for account identity, but is not a terminal-access
group. The local kostik account was added to dialout and removed from the
previous terminal group; existing sessions must refresh their group list.

The native tests, all 188 runtime tests, archive checks and systemd
permission/recovery integration passed. The installed upgrade preserved
`/etc/modem-emu.conf`. An AT exchange as kostik passed, while unrelated users
and a process with only the private service group were denied terminal
access. The service remained active and enabled. No reboot was performed.
