"""Terminal dialing aborts end signaling without creating a second command."""
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from eicon_at import AtParser, ActionKind
from eicon_adsp_sip import EiconSipEndpoint


class DialAbortTests(unittest.TestCase):
    def endpoint(self):
        ep = EiconSipEndpoint.__new__(EiconSipEndpoint)
        ep.at = AtParser()
        ep.bind, ep.advertised, ep.sip_port = '127.0.0.1', '127.0.0.1', 5072
        ep.username, ep.verbose = '', False
        ep.sip = Mock()
        ep.call = None
        ep.outgoing = dict(number='100', host='127.0.0.1:5060', peer=('127.0.0.1', 5060),
                           call_id='test-call', cseq=1, branch='z9hG4bKoriginal', tag='local')
        ep.cancelled_outgoing = {}
        ep.dialed_card, ep.pending_analog_line = object(), object()
        return ep

    def test_any_key_aborts_without_enter(self):
        for key in (b'x', b'\r', b'\x1b', b'\x08', b' '):
            with self.subTest(key=key):
                parser = AtParser()
                reply, _ = parser.feed(b'ATDT100\r')
                self.assertNotIn(b'OK', reply)
                parser.feed(key)
                self.assertEqual([a.kind for a in parser.actions],
                                 [ActionKind.DIAL, ActionKind.ABORT_DIAL])
                self.assertFalse(parser.dial_pending)

    def test_split_crlf_does_not_abort_but_following_key_does(self):
        parser = AtParser()
        parser.feed(b'ATDT100\r')
        parser.feed(b'\n')
        self.assertTrue(parser.dial_pending)
        self.assertEqual(len(parser.actions), 1)
        parser.feed(b'\r')
        self.assertEqual(parser.actions[-1].kind, ActionKind.ABORT_DIAL)

    def test_abort_discards_key_burst_and_clears_command_buffer(self):
        parser = AtParser()
        parser.feed(b'ATDT100\r\n')
        parser.feed(b'xxxx\r\n')
        self.assertEqual(len(parser.actions), 2)
        parser.no_carrier()
        reply, _ = parser.feed(b'AT\r')
        self.assertIn(b'OK', reply)
        self.assertNotIn(b'ERROR', reply)

    def test_connected_input_is_payload_instead_of_abort(self):
        parser = AtParser()
        parser.feed(b'ATDT100\r')
        parser.connected(31200, 14400, 'V34', 'LAPM')
        _, payload = parser.feed(b'hello')
        self.assertEqual(payload, b'hello')
        self.assertEqual(len(parser.actions), 1)

    def test_ringing_abort_sends_cancel_with_original_transaction(self):
        ep = self.endpoint()
        ep.outgoing['provisional'] = True
        self.assertEqual(ep.abort_dial(), b'\r\nNO CARRIER\r\n')
        self.assertIsNone(ep.outgoing)
        self.assertIsNone(ep.dialed_card)
        wire = ep.sip.sendto.call_args[0][0]
        for value in (b'CANCEL sip:100@127.0.0.1:5060 SIP/2.0',
                      b'branch=z9hG4bKoriginal', b'CSeq: 1 CANCEL'):
            self.assertIn(value, wire)
        ep.on_invite_response(487, {'call-id':'test-call', 'to':'<sip:100@peer>'}, '', ('127.0.0.1',5060))
        self.assertIn(b'CSeq: 1 ACK', ep.sip.sendto.call_args[0][0])

    def test_early_abort_waits_for_provisional_response_before_cancel(self):
        ep = self.endpoint()
        ep.abort_dial()
        ep.sip.sendto.assert_not_called()
        ep.on_invite_response(180, {'call-id':'test-call'}, '', ('127.0.0.1',5060))
        self.assertIn(b'CANCEL ', ep.sip.sendto.call_args[0][0])
        self.assertIsNone(ep.outgoing)

    def test_late_answer_is_acked_and_hung_up_without_starting_media(self):
        ep = self.endpoint()
        ep.abort_dial()
        ep.on_invite_response(200, {'call-id':'test-call','to':'<sip:100@peer>;tag=remote'}, '', ('127.0.0.1',5060))
        wires = [call.args[0] for call in ep.sip.sendto.call_args_list]
        self.assertTrue(wires[0].startswith(b'ACK '))
        self.assertTrue(wires[1].startswith(b'BYE '))
        self.assertIsNone(ep.call)

    def test_repeated_late_answer_keeps_invite_cseq_and_sends_one_bye(self):
        ep = self.endpoint()
        ep.abort_dial()
        headers = {'call-id':'test-call','to':'<sip:100@peer>;tag=remote'}
        for _ in range(2):
            ep.on_invite_response(200, headers, '', ('127.0.0.1',5060))
        wires = [call.args[0] for call in ep.sip.sendto.call_args_list]
        acks = [wire for wire in wires if wire.startswith(b'ACK ')]
        byes = [wire for wire in wires if wire.startswith(b'BYE ')]
        self.assertEqual(len(acks), 2)
        self.assertEqual(len(byes), 1)
        self.assertTrue(all(b'CSeq: 1 ACK' in wire for wire in acks))
        self.assertIn(b'CSeq: 2 BYE', byes[0])

    def test_old_cancelled_transaction_does_not_replace_a_new_dial(self):
        ep = self.endpoint()
        ep.abort_dial()
        new = dict(ep.cancelled_outgoing['test-call'], call_id='new-call')
        ep.outgoing = new
        ep.on_invite_response(487, {'call-id':'test-call'}, '', ('127.0.0.1',5060))
        self.assertIs(ep.outgoing, new)

    def test_abort_during_training_hangs_up_established_sip_call(self):
        ep = self.endpoint()
        ep.call = object()
        ep.hangup_call = Mock()
        self.assertEqual(ep.abort_dial(), b'')
        ep.hangup_call.assert_called_once_with('dial aborted by terminal input')

    def test_hangup_of_originated_training_call_sends_bye(self):
        ep = self.endpoint()
        ep.call = SimpleNamespace(remote_from='', local_to='')
        ep.end_call = Mock()
        ep.hangup_call('dial aborted by terminal input')
        self.assertTrue(ep.sip.sendto.call_args[0][0].startswith(b'BYE '))
        ep.end_call.assert_called_once_with('dial aborted by terminal input')

    def test_expired_cancel_contexts_are_removed(self):
        ep = self.endpoint()
        ep.cancelled_outgoing['old'] = dict(expires=time.monotonic()-1)
        ep.prune_cancelled_outgoing()
        self.assertFalse(ep.cancelled_outgoing)


if __name__ == '__main__': unittest.main()
