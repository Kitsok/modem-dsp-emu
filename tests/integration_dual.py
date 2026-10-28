"""Exercise incoming manual/automatic answers and outgoing dialing in one process."""
import os,select,signal,socket,subprocess,tempfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
peer=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);peer.bind(('127.0.0.1',0));peer.settimeout(5)
audio=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);audio.bind(('127.0.0.1',0))
SDP=f'v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio {audio.getsockname()[1]} RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n'
def headers(wire):
 return {line.split(':',1)[0].lower():line.split(':',1)[1].strip() for line in wire.decode().split('\r\n\r\n')[0].split('\r\n')[1:] if ':' in line}
def request(method,ident):
 return (f'{method} sip:eicon@127.0.0.1:5092 SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:{peer.getsockname()[1]};branch=z9hG4bK{ident}{method}\r\nFrom: <sip:caller@peer>;tag=remote\r\nTo: <sip:eicon@local>\r\nCall-ID: {ident}\r\nCSeq: 1 {method}\r\nContact: <sip:caller@127.0.0.1:{peer.getsockname()[1]}>\r\nContent-Type: application/sdp\r\nContent-Length: {len(SDP)}\r\n\r\n'+SDP).encode()
def response(invite,status):
 hs=[line for line in invite.decode().split('\r\n\r\n')[0].split('\r\n')[1:] if line.lower().startswith(('via:','from:','to:','call-id:','cseq:'))]
 return (f'SIP/2.0 {status}\r\n'+'\r\n'.join(hs)+f'\r\nContent-Type: application/sdp\r\nContent-Length: {len(SDP)}\r\n\r\n'+SDP).encode()
with tempfile.TemporaryDirectory() as d:
 cfg=Path(d)/'config';link=Path(d)/'tty';log=Path(d)/'log'
 cfg.write_text(f'[network]\nsip_port=5092\nrtp_port=4102\ndial_target=127.0.0.1:{peer.getsockname()[1]}\n[terminal]\nlink={link}\n')
 with log.open('w') as out:
  process=subprocess.Popen(['/usr/bin/python3','-S',str(ROOT/'tools/modem_service.py'),'--config',str(cfg)],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
  try:
   deadline=time.monotonic()+6
   while not link.exists():
    if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError(log.read_text())
    time.sleep(.05)
   fd=os.open(link,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
   def terminal(marker,timeout=5):
    data=b'';deadline=time.monotonic()+timeout
    while marker not in data and time.monotonic()<deadline:
     if select.select([fd],[],[],.1)[0]:data+=os.read(fd,65536)
    assert marker in data,repr(data)
    return data
   def command(text):
    os.write(fd,text.encode()+b'\r');return terminal(b'OK\r\n')
   def incoming(ident,manual):
    command('ATS0=0' if manual else 'ATS0=1')
    peer.sendto(request('INVITE',ident),('127.0.0.1',5092))
    ringing=terminal(b'RING\r\n');assert b'NO CARRIER' not in ringing
    first,_=peer.recvfrom(65535);second,_=peer.recvfrom(65535)
    assert first.startswith(b'SIP/2.0 100') and second.startswith(b'SIP/2.0 180')
    if manual:
     assert not select.select([peer],[],[],.2)[0], 'Manual call answered before ATA'
     os.write(fd,b'ATA\r\n')
    answer,_=peer.recvfrom(65535);assert answer.startswith(b'SIP/2.0 200'),answer
    assert 'NO CARRIER' not in log.read_text().split("[call] ringing from")[-1]
    peer.sendto(request('BYE',ident),('127.0.0.1',5092))
    ended,_=peer.recvfrom(65535);assert ended.startswith(b'SIP/2.0 200')
    reply=terminal(b'NO CARRIER');assert b'\r\nOK\r\n' not in reply,repr(reply)
   incoming('manual',True)
   incoming('automatic',False)
   os.write(fd,b'ATDT100\r\n');invite,destination=peer.recvfrom(65535)
   assert invite.startswith(b'INVITE '),invite
   peer.sendto(request('INVITE','busy'),('127.0.0.1',5092))
   busy,_=peer.recvfrom(65535);assert busy.startswith(b'SIP/2.0 486')
   peer.sendto(response(invite,'200 OK'),destination)
   ack,_=peer.recvfrom(65535);assert ack.startswith(b'ACK ')
   os.write(fd,b'\x1b');terminal(b'NO CARRIER')
   bye,_=peer.recvfrom(65535);assert bye.startswith(b'BYE ')
   incoming('manual-again',True)
   assert log.read_text().count('modem role answer')==3,log.read_text()
   assert 'modem role calling' in log.read_text(),log.read_text()
   assert process.poll() is None
   os.close(fd)
   print('One auto-mode process passed manual answer, autoanswer, outgoing dialing, busy handling and incoming-after-outgoing.')
  finally:
   os.killpg(process.pid,signal.SIGINT)
   try:process.wait(timeout=5)
   except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM);process.wait()
peer.close();audio.close()
