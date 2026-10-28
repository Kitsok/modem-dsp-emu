"""Two-way deterministic payload test against the installed modem service.

Usage: python3 tests/integration_call.py EMU unused /tmp/emu 90
Peer: python3 tests/integration_call.py COURIER unused /tmp/courier 110
Requires exclusive serial access; stop and restore its getty separately.
MODEM_TEST_SERIAL and MODEM_TEST_PTY may override the default device paths.
"""
import os,sys,termios,tty,fcntl,struct,select,time,re,json,hashlib,random
from pathlib import Path
role,runlog,stem,duration=sys.argv[1],sys.argv[2],sys.argv[3],float(sys.argv[4])
peer='COURIER' if role=='EMU' else 'EMU'
def payload(name):
    data=random.Random(1973 if name=='EMU' else 1974).randbytes(8192).hex().encode()
    return b'BEGIN-'+name.encode()+b'-PAYLOAD\n'+data+b'\nEND-'+name.encode()+b'-PAYLOAD\n'
outgoing,expected=payload(role),payload(peer)
if role=='COURIER':
    fd=os.open(os.environ.get('MODEM_TEST_SERIAL','/dev/ttyUSB0'),os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
    old=termios.tcgetattr(fd);tty.setraw(fd)
    a=termios.tcgetattr(fd);a[4]=a[5]=termios.B115200
    a[2]|=termios.CLOCAL|termios.CREAD;a[2]|=termios.CRTSCTS
    termios.tcsetattr(fd,termios.TCSANOW,a)
    fcntl.ioctl(fd,termios.TIOCMBIS,struct.pack('I',termios.TIOCM_DTR|termios.TIOCM_RTS))
    os.write(fd,b'AT&F1&M5&K1S0=1\r')
else:
    path=os.environ.get('MODEM_TEST_PTY','/dev/modem-emu')
    fd=os.open(path,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK);old=termios.tcgetattr(fd);tty.setraw(fd)
if role=='EMU': os.write(fd,b'ATDT100\r')
print(role,'READY',flush=True)
start=time.monotonic();connected_at=None;received=b'';sent=0;next_send=0;verified=False;lost=False
try:
    with open(stem+'.log','wb') as log:
        while time.monotonic()-start<duration:
            now=time.monotonic()
            if select.select([fd],[],[],.03)[0]:
                try:chunk=os.read(fd,65536)
                except BlockingIOError:continue
                except OSError as exc:
                    print("SERIAL READ ERROR",repr(exc),flush=True);break
                if not chunk:
                    print("SERIAL EOF",flush=True);break
                received+=chunk;log.write(chunk);log.flush()
                if connected_at is None and b'CONNECT ' in received:
                    connected_at=now;print(role,'CONNECTED',flush=True)
                if b'NO CARRIER' in chunk and connected_at is not None:
                    lost=True;print(role,'CARRIER ENDED',round(now-connected_at,1),flush=True);break
            if connected_at is not None and sent<len(outgoing) and now>=next_send:
                try:sent+=os.write(fd,outgoing[sent:sent+192])
                except BlockingIOError:pass
                next_send=now+.15
            if not verified and expected in received:
                verified=True;print(role,'VERIFIED PEER PAYLOAD SHA256',hashlib.sha256(expected).hexdigest(),flush=True)
            if verified and sent==len(outgoing) and now>=next_send+3:
                try:os.write(fd,b'HEARTBEAT-'+role.encode()+b'\n')
                except BlockingIOError:pass
                next_send=now
finally:
    elapsed=time.monotonic()-connected_at if connected_at is not None else 0
    result=dict(role=role,connected=connected_at is not None,peer_payload_verified=verified,
                sent_complete=sent==len(outgoing),sent_payload_sha256=hashlib.sha256(outgoing).hexdigest(),
                expected_peer_sha256=hashlib.sha256(expected).hexdigest(),connection_seconds=round(elapsed,2),
                carrier_ended=lost)
    Path(stem+'.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
    try: termios.tcsetattr(fd,termios.TCSANOW,old)
    except termios.error: pass
    os.close(fd)

if not (result["connected"] and result["peer_payload_verified"] and result["sent_complete"]):
    raise SystemExit("Bidirectional payload verification failed")
