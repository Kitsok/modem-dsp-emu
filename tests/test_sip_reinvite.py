"""A media target refresh must not rebuild the modem or reset its clock."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))

from eicon_adsp_sip import Call, EiconSipEndpoint, parse_g711_sdp


class ReinviteTests(unittest.TestCase):
    def setUp(self):
        self.endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        self.endpoint.sip = Mock()
        self.endpoint.outgoing = None
        self.endpoint.bind = self.endpoint.advertised = '127.0.0.1'
        self.endpoint.sip_port = 5072
        self.endpoint.rtp_port = 4012
        self.endpoint.payload_type = 0
        self.endpoint.codec_name = 'PCMU'
        self.endpoint.rtp_packet_ms = 30
        self.endpoint.verbose = False
        self.peer = ('127.0.0.1', 5060)
        self.call = Call(self.peer, ('127.0.0.1', 19000), 'existing', 'local', Mock())
        self.call.remote_from = '<sip:peer@127.0.0.1>;tag=remote'
        self.call.samples = 123456
        self.call.rx.extend([1, 2, 3])
        self.endpoint.call = self.call
        self.headers = {'call-id': 'existing', 'cseq': '8 INVITE',
                        'from': self.call.remote_from,
                        'to': '<sip:emu@127.0.0.1>;tag=local',
                        'via': 'SIP/2.0/UDP 127.0.0.1;branch=z9hG4bK8'}

    @staticmethod
    def offer(port=20000, payload=0):
        return f'v=0\r\nc=IN IP4 127.0.0.1\r\nm=audio {port} RTP/AVP {payload}\r\n'

    def response(self):
        return self.endpoint.sip.sendto.call_args.args[0]

    def test_refresh_and_retransmission_preserve_modem(self):
        card = self.call.card
        self.endpoint._reinvite(self.headers, self.offer(), self.peer)
        response = self.response()
        self.assertTrue(response.startswith(b'SIP/2.0 200 '))
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 20000))
        self.assertIs(self.call.card, card)
        self.assertEqual(self.call.samples, 123456)
        self.assertEqual(list(self.call.rx), [1, 2, 3])
        self.endpoint._reinvite(self.headers, self.offer(), self.peer)
        self.assertEqual(self.response(), response)
        ack = ('ACK sip:emu@127.0.0.1 SIP/2.0\r\n'
               'From: <sip:peer@127.0.0.1>;tag=remote\r\n'
               'To: <sip:emu@127.0.0.1>;tag=local\r\n'
               'Call-ID: existing\r\nCSeq: 8 ACK\r\n'
               'Content-Length: 0\r\n\r\n').encode()
        self.endpoint.sip.recvfrom.return_value = (ack, self.peer)
        self.endpoint.on_sip()
        self.assertTrue(self.call.media_update['acked'])
        self.headers.update(cseq='9 INVITE', via='new-branch')
        self.endpoint._reinvite(self.headers, self.offer(19000), self.peer)
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 19000))
        self.assertNotIn(self.call.rtp_peer, self.call.retired_rtp_peers)

    def test_rejected_offer_leaves_media_unchanged(self):
        self.endpoint._reinvite(self.headers, self.offer(payload=8), self.peer)
        self.assertTrue(self.response().startswith(b'SIP/2.0 488 '))
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 19000))

    def test_wrong_dialog_cannot_change_media(self):
        self.headers['to'] = '<sip:emu@127.0.0.1>;tag=wrong'
        self.endpoint._reinvite(self.headers, self.offer(), self.peer)
        self.assertTrue(self.response().startswith(b'SIP/2.0 481 '))
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 19000))

    def test_stale_sequence_cannot_change_media(self):
        self.call.remote_cseq = 9
        self.endpoint._reinvite(self.headers, self.offer(), self.peer)
        self.assertTrue(self.response().startswith(b'SIP/2.0 500 '))
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 19000))

    def test_delayed_rtp_from_old_bridge_cannot_steal_destination(self):
        self.endpoint._reinvite(self.headers, self.offer(), self.peer)
        self.endpoint.capture = None
        packet = bytes.fromhex('800000010000000100000001') + b'\xff' * 160
        self.endpoint._on_rtp_packet(packet, ('127.0.0.1', 19000))
        self.assertEqual(self.call.rtp_peer, ('127.0.0.1', 20000))
        self.assertEqual(list(self.call.rx), [1, 2, 3])

    def test_unusable_sdp_is_rejected(self):
        for body in (self.offer(0), self.offer(70000),
                     self.offer() + 'a=inactive\r\n',
                     self.offer() + 'a=rtpmap:0 PCMA/8000\r\n'):
            with self.subTest(body=body):
                self.assertIsNone(parse_g711_sdp(body, self.peer, 0))


if __name__ == '__main__':
    unittest.main()
