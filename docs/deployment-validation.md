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

## local3 automatic call/answer mode

Version 0.1.0+local3 selects the DSP and LAPM role for each call when
`[modem] role = auto`: ATDT originates and incoming SIP calls answer.
The configuration and CLI defaults now select auto mode. Explicit calling
and answer modes remain available. Manual ATA waits for the connection
result, autoanswer follows the SIP ring cadence, and overlapping call
attempts receive busy handling.

All 202 focused runtime tests passed under system Python without site
packages. `tests/integration_dual.py` passed incoming manual answer,
autoanswer, outgoing SIP setup, busy handling and another incoming call in
one process. This integration test exercises SIP/AT control, not a physical
modem data connection.

The following are observed lab results, not guarantees of call reliability.
The installed service on dev.ne-arch.online answered physical Courier calls
with both ATS0=1 and ATS0=0 followed by ATA. Both incoming tests verified the
complete deterministic payloads in both directions, with LAPM/V.42bis.
The permanent ATA route 9095551020 on both FXS lines targets
100@172.20.20.207:5072.

A subsequent outgoing call connected and then failed immediately after the
Courier sent DISC. Five additional ATDT100 attempts using the same installed
service produced these results:

| Attempt | Result | Observation |
| --- | --- | --- |
| 1 | Failed | DISC shortly after CONNECT; Courier reported Keypress Abort. |
| 2 | Failed | No modem CONNECT; remote BYE during training. |
| 3 | Passed | Exact payloads verified both ways; 45.27 seconds connected. |
| 4 | Passed | Exact payloads verified both ways; 45.48 seconds connected. |
| 5 | Passed | Exact payloads verified both ways; 45.41 seconds connected. |

Successful calls ended with an intentional ATH after the test window.
They used the same payload hashes recorded above. No service restart,
configuration change or code change occurred between the five attempts;
the process remained PID 3764. The two failures remain unresolved. The
requested threshold for further investigation was more than two failures
among these five attempts, so no additional investigation was performed.

A separate experimental emulator-to-emulator data test failed to establish
LAPM while repeatedly retraining V.34. Its script and log are retained as
diagnostic artifacts outside the committed test suite; this is not counted
as a passing integration test.

After testing, mgetty on nanovax was restored. The emulator was left active
with ATS0=1. No reboot or QEMU run was performed. Raw terminal traces,
per-attempt JSON results, service journals and Courier ATI6/ATI11 output
were saved in the operator workspace under ata-inspection/repeat-five.
