"""A media exception must end SIP/RTP and restore a usable AT terminal."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from eicon_adsp_sip import EiconSipEndpoint, Call
from eicon_at import AtParser, Mode


class MediaFaultTests(unittest.TestCase):
    def test_exception_tears_down_the_call_and_restores_at_commands(self):
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.bind = endpoint.advertised = '127.0.0.1'
        endpoint.sip_port = 5072
        endpoint.at = AtParser()
        endpoint.at.connected(31200, 14400, 'V34', 'LAPM', 'V42BIS')
        terminal = bytearray()
        endpoint.pty = SimpleNamespace(write_terminal=terminal.extend)
        endpoint.sip = SimpleNamespace(sendto=Mock())
        endpoint.audio_monitor = Mock()
        endpoint.close_ppp = Mock()
        endpoint.outgoing = None
        endpoint.link_failure_reported = True
        capture = endpoint.capture = object()
        card = SimpleNamespace(dm={0x3fb0: 8, 0x3fc2: 0xd0, 0x3fc1: 0x0402},
                               resident=0x0261, set_line_hook=Mock())
        call = Call(('127.0.0.1', 5060), ('127.0.0.1', 16400), 'fault', 'tag', card)
        call.samples = 353754
        call.remote_from = '<sip:100@peer>;tag=peer'
        call.local_to = '<sip:emu@local>'
        call.target = 'sip:100@127.0.0.1:5060'
        call.analog_line = SimpleNamespace(set_hook=Mock())
        call.reactive_engine = SimpleNamespace(close=Mock())
        call.tx_stop = threading.Event()
        thread = call.tx_thread = threading.Thread(target=call.tx_stop.wait)
        thread.start()
        self.addCleanup(lambda: (call.tx_stop.set(), thread.join(timeout=1)))
        endpoint.call = call
        with patch('eicon_adsp_sip.traceback.print_exc'):
            endpoint.fail_call()
        self.assertIsNone(endpoint.call)
        self.assertFalse(thread.is_alive())
        self.assertTrue(call.tx_stop.is_set())
        self.assertTrue(endpoint.sip.sendto.call_args.args[0].startswith(b'BYE '))
        self.assertIn(b'NO CARRIER', terminal)
        self.assertIs(endpoint.at.mode, Mode.COMMAND)
        self.assertFalse(endpoint.at.dial_pending)
        reply, to_link = endpoint.at.feed(b'AT\r')
        self.assertIn(b'OK', reply)
        self.assertEqual(to_link, b'')
        call.analog_line.set_hook.assert_called_with(False)
        card.set_line_hook.assert_called_with(False)
        call.reactive_engine.close.assert_called_once()
        endpoint.close_ppp.assert_called_once()
        self.assertIs(endpoint.capture, capture)
