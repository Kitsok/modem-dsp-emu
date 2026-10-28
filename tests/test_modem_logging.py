"""Normal service logs retain control events without recording modem payloads."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import modem_log
from eicon_at import AtParser
from logcap import emit, reset, throttled


class ModemLoggingTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = redirect_stdout(self.output)
        self.redirect.__enter__()
        modem_log.configure('info')
        self.addCleanup(self.redirect.__exit__, None, None, None)
        self.addCleanup(setattr, modem_log, '_configured', False)

    def test_normal_mode_retains_events_and_warnings_without_diagnostics(self):
        modem_log.debug('[adsp] diagnostic')
        modem_log.info('[call] ringing')
        modem_log.warning('[media] WARNING: stalled')
        modem_log.error('[call] failed')
        modem_log.protocol('[v42] TX I frame: secret-payload')
        modem_log.protocol('[v42] LAPM connected (UA), link 1')
        output = self.output.getvalue()
        self.assertNotIn('diagnostic', output)
        self.assertNotIn('secret-payload', output)
        for event in ('ringing', 'WARNING: stalled', 'failed', 'LAPM connected'):
            self.assertIn(event, output)

    def test_debug_mode_includes_diagnostics(self):
        modem_log.configure('debug')
        modem_log.debug('[adsp] diagnostic')
        self.assertIn('[DEBUG] [adsp] diagnostic', self.output.getvalue())

    def test_split_commands_quiet_results_and_data_privacy(self):
        parser = AtParser(event_logger=modem_log.at_event)
        parser.feed(b'ATE')
        self.assertEqual(self.output.getvalue(), '')
        parser.feed(b'0\rATQ1\rATV0\r')
        parser.connected(31200, 14400, 'V34', 'LAPM', 'V42BIS')
        _, payload = parser.feed(b'PAYLOAD-DO-NOT-LOG\rATSECRET\r')
        self.assertEqual(payload, b'PAYLOAD-DO-NOT-LOG\rATSECRET\r')
        output = self.output.getvalue()
        self.assertIn("command='ATE0'", output)
        self.assertIn("result='OK'", output)
        self.assertIn('suppressed=True', output)
        for detail in ('31200', '14400', 'LAPM', 'V42BIS'):
            self.assertIn(detail, output)
        self.assertNotIn('PAYLOAD', output)
        self.assertNotIn('ATSECRET', output)

    def test_terminal_controls_cannot_forge_records(self):
        modem_log.at_event('command', command='AT\x1b[2J\nFORGED')
        self.assertEqual(len(self.output.getvalue().splitlines()), 1)
        self.assertNotIn('\x1b', self.output.getvalue())

    def test_diagnostics_do_not_spend_cap_budget_in_normal_mode(self):
        reset()
        for _ in range(10): emit('[adsp] diagnostic', limit=2)
        self.assertFalse(throttled())
        self.assertEqual(self.output.getvalue(), '')
        reset()

    def test_kernel_connect_logs_and_reports_negotiated_compression(self):
        from eicon_adsp_sip import EiconSipEndpoint
        from unittest.mock import Mock
        from v42bis import V42bisEncoder
        parser = AtParser(event_logger=modem_log.at_event)
        card = SimpleNamespace(dm=[0] * 0x4000, resident=0x0261,
                               negotiated_downstream_bps=31200,
                               negotiated_upstream_bps=14400,
                               lapm=SimpleNamespace(connected=True,
                                   tx_compressor=V42bisEncoder(512, 32),
                                   rx_decompressor=None))
        card.dm[0x3FC2] = 0xD0
        call = SimpleNamespace(card=card, at_connected=False,
                               v34_mailbox=object())
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.at, endpoint.pty = parser, Mock()
        parser.connect_format = 2
        endpoint.at_watch(call)
        self.assertTrue(call.at_connected)
        response = endpoint.pty.write_terminal.call_args[0][0]
        self.assertIn(b'COMPRESSION V42BIS', response)
        output = self.output.getvalue()
        for detail in ('31200', '14400', 'LAPM', 'V42BIS'):
            self.assertIn(detail, output)

    def test_compression_uses_active_codecs_not_configuration(self):
        self.assertEqual(modem_log.compression_name(None), 'NONE')
        for name, expected in (('V42bisEncoder', 'V42BIS'), ('V44Decoder', 'V44')):
            link = SimpleNamespace(tx_compressor=type(name, (), {})(), rx_decompressor=None)
            self.assertEqual(modem_log.compression_name(link), expected)


if __name__ == '__main__': unittest.main()
