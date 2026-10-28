"""Root integration test: package lifecycle, config preservation and service access.

This leaves the package installed and enabled with the supplied dial target.
"""
import argparse,grp,os,shutil,signal,subprocess,sys,time
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('package',type=Path)
parser.add_argument('--dial-target',default='')
parser.add_argument('--terminal-user')
args=parser.parse_args()
package=args.package.resolve()
assert os.geteuid()==0, 'Run as root'
def run(*args): return subprocess.run(args,check=True,text=True,capture_output=True)
def active(): return subprocess.run(['systemctl','is-active','--quiet','modem-emu.service']).returncode==0
def wait_terminal():
 deadline=time.monotonic()+10
 while not Path('/dev/modem-emu').exists():
  if time.monotonic()>deadline:raise RuntimeError(run('journalctl','-u','modem-emu','-n','20','--no-pager').stdout)
  time.sleep(.1)
def at_check():
 wait_terminal()
 code="import os,select;f=os.open('/dev/modem-emu',os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);os.write(f,b'AT\\r');assert select.select([f],[],[],3)[0];assert b'OK' in os.read(f,4096);os.close(f)"
 run('runuser','-u','nobody','-g','dialout','--','/usr/bin/python3','-c',code)

legacy=Path('/etc/tmpfiles.d/modem-emu.conf')
if legacy.exists() and legacy.read_text()=='d /run/modem-emu 0755 kostik kostik -\nL /dev/modem-emu - - - - /run/modem-emu/tty\n':
 backup=Path('/var/backups/modem-emu/legacy-tmpfiles.conf');backup.parent.mkdir(parents=True,exist_ok=True)
 if not backup.exists():shutil.copy2(legacy,backup)
 legacy.unlink()
run('dpkg','-i',str(package))
assert active()
assert run('systemctl','is-enabled','modem-emu.service').stdout.strip()=='enabled'
for path in Path('/usr/lib/modem-emu').rglob('__pycache__'):shutil.rmtree(path)
run('/usr/bin/modem-emu','--check-config')
assert not list(Path('/usr/lib/modem-emu').rglob('__pycache__')), 'Installed launcher created unmanaged bytecode'
at_check()
config=Path('/etc/modem-emu.conf')
config.write_text('# package-preservation-test\n'+config.read_text())
expected=config.read_bytes()
run('dpkg','-i',str(package))
assert config.read_bytes()==expected,'Upgrade replaced local configuration'
at_check()
run('systemctl','disable','--now','modem-emu.service')
run('dpkg','-i',str(package))
assert subprocess.run(['systemctl','is-enabled','--quiet','modem-emu.service']).returncode!=0
assert not active(),'Upgrade started an explicitly disabled service'
run('systemctl','enable','--now','modem-emu.service');at_check()
pid=int(run('systemctl','show','--property=MainPID','--value','modem-emu.service').stdout)
os.kill(pid,signal.SIGKILL)
deadline=time.monotonic()+10
while time.monotonic()<deadline:
 new=int(run('systemctl','show','--property=MainPID','--value','modem-emu.service').stdout)
 if new and new!=pid and Path('/dev/modem-emu').exists():break
 time.sleep(.2)
else:raise RuntimeError('Crash recovery failed')
at_check()
run('dpkg','--remove','modem-emu')
assert not active()
assert config.is_file(),'Removal deleted the conffile'
assert not Path('/run/modem-emu').exists(),'Runtime directory remained after removal'
run('dpkg','--purge','modem-emu')
assert not config.exists()
assert not Path('/dev/modem-emu').is_symlink(),'Public terminal link remained after purge'
run('dpkg','-i',str(package))
s=config.read_text().replace('dial_target =\n',f'dial_target = {args.dial_target}\n')
config.write_text(s)
if args.terminal_user:run('usermod','-aG','dialout',args.terminal_user)
run('systemctl','reset-failed','modem-emu.service')
run('systemctl','restart','modem-emu.service');at_check()
assert active()
if args.terminal_user:assert args.terminal_user in grp.getgrnam('dialout').gr_mem
run('systemd-analyze','verify','/usr/lib/systemd/system/modem-emu.service')
print('Install, upgrade preservation, disabled-service preservation, crash recovery, removal, purge and final reinstall passed.')
