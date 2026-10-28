import grp,os,pwd,select,shutil,signal,stat,subprocess,sys,time
from pathlib import Path
repo=Path(sys.argv[1]);root=Path('/opt/modem-emu-check-runtime');unit=Path('/run/systemd/system/modem-emu-check.service')
def run(*args): return subprocess.run(args,check=True,text=True,capture_output=True)
assert not root.exists() and not unit.exists(), 'Test fixture already exists'
try:
 run('systemd-sysusers',str(repo/'systemd/modem-emu.sysusers'))
 (root/'tools/adsp2181emu').mkdir(parents=True);(root/'bin').mkdir()
 for p in (repo/'tools').glob('*.py'):shutil.copy2(p,root/'tools'/p.name)
 shutil.copy2(repo/'tools/adsp2181emu/libadsp2181.dylib',root/'tools/adsp2181emu')
 shutil.copytree(repo/'artifacts/eicon-dsp/build-109-789-analog',root/'artifacts/eicon-dsp/build-109-789-analog')
 launcher=(repo/'bin/modem-emu').read_text().replace('/usr/lib/modem-emu/tools',str(root/'tools'))
 (root/'bin/modem-emu').write_text(launcher);(root/'bin/modem-emu').chmod(0o755)
 (root/'test.ini').write_text('[network]\nsip_port=5092\nrtp_port=4102\n[terminal]\nlink=/run/modem-emu-check/tty\n')
 content=(repo/'systemd/modem-emu.service').read_text().replace('/usr/bin/modem-emu',f'{root}/bin/modem-emu --config {root}/test.ini').replace('RuntimeDirectory=modem-emu','RuntimeDirectory=modem-emu-check').replace('StateDirectory=modem-emu','StateDirectory=modem-emu-check')
 unit.write_text(content)
 run('systemd-analyze','verify',str(unit));run('systemctl','daemon-reload');run('systemctl','start','modem-emu-check.service')
 def wait_link():
  deadline=time.monotonic()+6
  while not Path('/run/modem-emu-check/tty').exists():
   if time.monotonic()>deadline:raise RuntimeError(run('journalctl','-u','modem-emu-check','-n','25','--no-pager').stdout)
   time.sleep(.1)
 wait_link()
 path=Path('/run/modem-emu-check/tty');s=path.stat()
 assert s.st_uid==pwd.getpwnam('modem-emu').pw_uid
 assert s.st_gid==grp.getgrnam('modem-emu').gr_gid
 assert stat.S_IMODE(s.st_mode)==0o660
 code="import os,select; f=os.open('/run/modem-emu-check/tty',os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);os.write(f,b'AT\\r');assert select.select([f],[],[],3)[0];assert b'OK' in os.read(f,4096);os.close(f)"
 run('runuser','-u','nobody','-g','modem-emu','--','/usr/bin/python3','-c',code)
 denied=subprocess.run(['runuser','-u','nobody','--','/usr/bin/python3','-c',"open('/run/modem-emu-check/tty','rb')"],capture_output=True)
 assert denied.returncode!=0
 pid=int(run('systemctl','show','--property=MainPID','--value','modem-emu-check').stdout)
 os.kill(pid,signal.SIGKILL)
 deadline=time.monotonic()+10
 while time.monotonic()<deadline:
  new=int(run('systemctl','show','--property=MainPID','--value','modem-emu-check').stdout)
  if new and new!=pid and path.exists():break
  time.sleep(.2)
 else:raise RuntimeError('Service did not recover after crash')
 run('systemctl','stop','modem-emu-check.service')
 assert not path.exists() and not path.is_symlink()
 print('Systemd verification, unprivileged startup, group AT access, access denial, crash recovery and stop cleanup passed.')
finally:
 subprocess.run(['systemctl','stop','modem-emu-check.service'],capture_output=True)
 unit.unlink(missing_ok=True)
 subprocess.run(['systemctl','daemon-reload'],capture_output=True)
 shutil.rmtree(root,ignore_errors=True)
 shutil.rmtree('/var/lib/modem-emu-check',ignore_errors=True)
