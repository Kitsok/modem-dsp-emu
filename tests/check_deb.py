"""Check the built archive without installing or starting it."""
import subprocess
import sys
import tempfile
from pathlib import Path

package=Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory)
 subprocess.run(['dpkg-deb','-R',str(package),str(root)],check=True)
 required=('usr/bin/modem-emu','etc/modem-emu.conf',
           'usr/lib/systemd/system/modem-emu.service',
           'usr/lib/sysusers.d/modem-emu.conf','usr/lib/tmpfiles.d/modem-emu.conf',
           'usr/lib/modem-emu/tools/adsp2181emu/libadsp2181.dylib')
 for name in required:assert (root/name).is_file(),name
 assert '/etc/modem-emu.conf' in (root/'DEBIAN/conffiles').read_text()
 assert 'Group=dialout\n' in (root/'usr/lib/systemd/system/modem-emu.service').read_text()
 postinst=(root/'DEBIAN/postinst').read_text()
 assert 'systemd-sysusers' in postinst, 'Missing service-account initialization'
 assert postinst.index('systemd-sysusers')<postinst.index('deb-systemd-invoke')
 assert 'enable' in postinst and 'deb-systemd-invoke' in postinst
 postrm=(root/'DEBIAN/postrm').read_text()
 assert 'purge' in postrm and '/dev/modem-emu' in postrm
 for path in root.rglob('*'):
  assert '.venv' not in path.parts and '__pycache__' not in path.parts,str(path)
 assert not (root/'home').exists()
 runtime=root/'usr/lib/modem-emu/tools/modem_service.py'
 result=subprocess.run([sys.executable,'-S',str(runtime),'--config',str(root/'etc/modem-emu.conf'),'--help'],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 assert '--kernel-dispatch' in result.stdout
print('Package contents, conffile, account/service helpers, purge cleanup and isolated runtime import passed.')
