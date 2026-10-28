"""Wildcard listening must still advertise a usable address to each peer."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from eicon_adsp_sip import local_address_for


class SipAddressSelectionTests(unittest.TestCase):
    def test_explicit_advertised_address_overrides_binding(self):
        with patch('eicon_adsp_sip.socket.socket') as factory:
            self.assertEqual(local_address_for(('192.0.2.1', 5060), '0.0.0.0', '198.51.100.2'), '198.51.100.2')
            factory.assert_not_called()

    def test_wildcard_advertise_uses_explicit_binding(self):
        for advertised in (None, '0.0.0.0'):
            with patch('eicon_adsp_sip.socket.socket') as factory:
                self.assertEqual(local_address_for(('192.0.2.1', 5060), '192.0.2.2', advertised), '192.0.2.2')
                factory.assert_not_called()

    def test_wildcard_selects_source_address_for_each_peer_and_closes_probe(self):
        peers = [('192.0.2.1', 5060), ('198.51.100.1', 5060)]
        for peer, address in zip(peers, ('192.0.2.2', '198.51.100.2')):
            probe = Mock()
            probe.getsockname.return_value = (address, 12345)
            with patch('eicon_adsp_sip.socket.socket', return_value=probe):
                self.assertEqual(local_address_for(peer, '0.0.0.0', '0.0.0.0'), address)
            probe.connect.assert_called_once_with(peer)
            probe.close.assert_called_once()

    def test_routing_failure_closes_probe(self):
        probe = Mock()
        probe.connect.side_effect = OSError('no route')
        with patch('eicon_adsp_sip.socket.socket', return_value=probe):
            with self.assertRaises(OSError):
                local_address_for(('192.0.2.1', 5060), '0.0.0.0', '0.0.0.0')
        probe.close.assert_called_once()


if __name__ == '__main__': unittest.main()
