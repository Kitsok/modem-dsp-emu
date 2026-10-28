import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from v34_mailbox import V34Mailbox
from v42_lapm import (LapmEndpoint, ADP_E, ADP_C, FLAG_BITS, HdlcDecoder,
                      encode_frame, encode_xid_parameters)


class CourierDetectionTests(unittest.TestCase):
    def test_adp_accepts_every_allowed_separator_length_across_chunks(self):
        for ec_gap in range(8, 17):
            for ce_gap in range(8, 17):
                with self.subTest(ec_gap=ec_gap, ce_gap=ce_gap):
                    ep = LapmEndpoint(role='originator', log=lambda _: None)
                    bits = (ADP_E + (1,) * ec_gap + ADP_C +
                            (1,) * ce_gap) * 2
                    for start in range(0, len(bits), 7):
                        ep.feed(list(bits[start:start + 7]))
                    self.assertEqual(ep.detection, 'protocol')
                    self.assertEqual(ep.stats.adp_rx, 2)
                    self.assertNotIn('no bits reached', ep.detection_summary())

    def test_invalid_separator_does_not_establish_protocol(self):
        for gap in (7, 17):
            ep = LapmEndpoint(role='originator', log=lambda _: None)
            ep.feed(list((ADP_E + (1,) * gap + ADP_C + (1,) * 12) * 3))
            self.assertEqual(ep.detection, 'odp')

    def test_ordered_establishment_waits_for_xid_before_sabme(self):
        with patch.dict(os.environ, {'EICON_V42_ORDERED_ESTABLISH': '1',
                                    'EICON_V42_XID_OPT_OCTETS': '3'}):
            ep = LapmEndpoint(role='originator', detect=False,
                              log=lambda _: None)
        self.assertEqual(ep.take(128, service=False), list(FLAG_BITS * 16))
        frames = HdlcDecoder().feed(ep.take(4096, service=False))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][1], ep.XID)
        self.assertIn(b'\x03\x03\x8a\x89\x00', frames[0])
        ep.feed(encode_frame(bytes((0x03, ep.XID)) +
                             encode_xid_parameters(ep.xid)))
        frames = HdlcDecoder().feed(ep.take(4096, service=False))
        self.assertEqual([f[1] for f in frames], [ep.SABME_MASKED | 0x10])


class CourierTransmitTests(unittest.TestCase):
    def test_read_ack_releases_word_when_request_flag_stays_high(self):
        counter = [0]
        adsp = SimpleNamespace(adsp2181_coverage_count=lambda *_: counter[0])
        card = SimpleNamespace(dm=[0] * 0x4000, pm={0x3F82: 0x83F05A},
                               resident=0x0261, cpu=object())
        link = Mock()
        link.take.side_effect = lambda count: [1] * count
        with patch.dict(os.environ, {'EICON_V34_TX_CONSUMPTION': '1'}), \
             patch.dict(sys.modules, {'dial_tikrnl_drive': SimpleNamespace(ADSP=adsp)}):
            pump = V34Mailbox(card, link)
        card.dm[0x3FC2] = 0xD0
        card.dm[0x3F61], card.dm[0x3F62] = 0x13, 0x110D
        card.dm[0x3FAD] = 0x8000
        pump.before_sample()
        pump.after_sample()
        self.assertTrue(pump.pending)
        self.assertEqual(pump.tx_accepted, 0)
        counter[0] += 1
        pump.after_sample()
        self.assertFalse(pump.pending)
        self.assertEqual(pump.tx_accepted, 1)
        pump.before_sample()
        self.assertEqual(link.take.call_count, 2)


if __name__ == '__main__':
    unittest.main()
