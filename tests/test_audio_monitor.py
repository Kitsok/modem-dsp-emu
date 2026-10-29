"""Speaker controls, exact monitor PCM and isolation from slow audio devices."""
import os
import math
import struct
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from audio_monitor import AudioMonitor, mix_pcm, progress_pcm
from eicon_at import AtParser
from eicon_adsp_sip import EiconSipEndpoint, Call, RtpCapture


class Player:
    def __init__(self, *, fill=False):
        self.read_fd, write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        os.set_blocking(write_fd, False)
        if fill:
            try:
                while True:
                    os.write(write_fd, b'\0' * 4096)
            except BlockingIOError:
                pass
        self.stdin = os.fdopen(write_fd, 'wb', buffering=0)
        self.returncode = None
        self.closed = threading.Event()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = 0
        self.closed.set()

    kill = terminate

    def wait(self, timeout=None):
        return self.returncode

    def read(self):
        try:
            return os.read(self.read_fd, 65536)
        except BlockingIOError:
            return b''

    def close(self):
        if not self.stdin.closed:
            self.stdin.close()
        os.close(self.read_fd)


def wait_for(predicate):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError('speaker worker did not respond')


class SpeakerTests(unittest.TestCase):
    def test_progress_frequencies_dtmf_and_ring_cadence(self):
        def energy(pcm, frequency):
            samples = struct.unpack('<160h', pcm)
            real = sum(value * math.cos(2 * math.pi * frequency * n / 8000)
                       for n, value in enumerate(samples))
            imag = sum(value * math.sin(2 * math.pi * frequency * n / 8000)
                       for n, value in enumerate(samples))
            return real * real + imag * imag

        tone = progress_pcm('100', 0, False, 2)
        self.assertGreater(energy(tone, 350), 10 * energy(tone, 1200))
        self.assertGreater(energy(tone, 440), 10 * energy(tone, 1200))
        digit = progress_pcm('100', .32, False, 2)
        self.assertGreater(energy(digit, 697), 10 * energy(digit, 2000))
        self.assertGreater(energy(digit, 1209), 10 * energy(digit, 2000))
        self.assertEqual(progress_pcm('100', .42, False, 2), bytes(320))
        self.assertEqual(progress_pcm('100', 1, False, 2), bytes(320))
        self.assertNotEqual(progress_pcm('100', 1, True, 2), bytes(320))
        self.assertEqual(progress_pcm('100', 3, True, 2), bytes(320))
        self.assertNotEqual(progress_pcm('100', 7, True, 2), bytes(320))

    def test_early_media_is_speaker_only_and_split_into_monitor_frames(self):
        from unittest.mock import Mock
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.call = None
        peer = ('192.0.2.1', 19000)
        endpoint.outgoing = {'early_media': peer}
        endpoint.audio_monitor = Mock()
        endpoint.payload_type = 0
        endpoint.silence = 255
        packet = bytes.fromhex('800000010000000100000001') + bytes([42]) * 240
        endpoint._on_rtp_packet(packet, ('192.0.2.2', 19000))
        endpoint.audio_monitor.feed.assert_not_called()
        endpoint._on_rtp_packet(packet, peer)
        self.assertIsNone(endpoint.call)
        self.assertTrue(endpoint.outgoing['early_audio'])
        endpoint.audio_monitor.reset_stream.assert_called_once()
        frames = endpoint.audio_monitor.feed.call_args_list
        self.assertEqual([len(item.args[1]) for item in frames], [160, 80])
        self.assertEqual(b''.join(item.args[1] for item in frames), bytes([42]) * 240)
        endpoint._on_rtp_packet(packet, peer)
        endpoint.audio_monitor.reset_stream.assert_called_once()

    def test_provisional_response_selects_ringback_and_early_media(self):
        from unittest.mock import Mock
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        peer = ('192.0.2.1', 5060)
        endpoint.outgoing = {'call_id': 'call', 'peer': peer}
        endpoint.cancelled_outgoing = {}
        endpoint.payload_type = 0
        endpoint.verbose = False
        endpoint.audio_monitor = Mock()
        headers = {'call-id': 'call'}
        endpoint.on_invite_response(180, headers, '', peer)
        endpoint.audio_monitor.ringback.assert_called_once()
        sdp = 'v=0\r\nc=IN IP4 192.0.2.1\r\nm=audio 19000 RTP/AVP 0\r\n'
        endpoint.on_invite_response(183, headers, sdp, peer)
        self.assertEqual(endpoint.outgoing['early_media'], ('192.0.2.1', 19000))
        self.assertFalse(endpoint.outgoing.get('early_audio', False))
        endpoint.outgoing['early_audio'] = True
        endpoint.on_invite_response(180, headers, '', peer)
        endpoint.audio_monitor.ringback.assert_called_once()

    def test_at_commands_and_profile_reset(self):
        parser = AtParser()
        self.assertEqual((parser.speaker_mode, parser.speaker_volume), (1, 2))
        for mode in range(3):
            for volume in range(4):
                self.assertIn(b'OK', parser.execute(f'ATM{mode}L{volume}'.encode()))
                self.assertEqual((parser.speaker_mode, parser.speaker_volume), (mode, volume))
        for command in (b'ATM3', b'ATL4'):
            self.assertIn(b'ERROR', parser.execute(command))
        parser.execute(b'AT&F')
        self.assertEqual((parser.speaker_mode, parser.speaker_volume), (1, 2))

    def test_pcmu_and_pcma_mix_both_directions_and_attenuate(self):
        for decode, silence in ((RtpCapture.decode_ulaw, 255), (RtpCapture.decode_alaw, 213)):
            table = tuple(decode(i) for i in range(256))
            tx, rx = bytes([0, 128, silence]), bytes([128, 0, silence])
            result = struct.unpack('<3h', mix_pcm(tx, rx, table, 3))
            self.assertEqual(result, tuple(round((table[a] + table[b]) * .25) for a, b in zip(tx, rx)))
            levels = [abs(struct.unpack('<h', mix_pcm(b'\0', b'\0', table, level))[0]) for level in range(4)]
            self.assertEqual(levels, sorted(set(levels)))

    def test_missing_player_disables_only_the_speaker(self):
        warnings = []
        with patch('audio_monitor.shutil.which', return_value=None):
            monitor = AudioMonitor(range(256), log=warnings.append)
        try:
            monitor.update();monitor.feed(b'\0' * 160, b'\0' * 160)
            self.assertTrue(monitor.disabled)
            self.assertEqual(len(warnings), 1)
        finally:
            monitor.close()

    def test_unavailable_audio_server_disables_only_the_speaker(self):
        warnings = []
        with patch('audio_monitor.subprocess.Popen', side_effect=OSError('audio server unavailable')):
            monitor = AudioMonitor(range(256), player='paplay', log=warnings.append)
            try:
                monitor.update();monitor.feed(b'\0' * 160, b'\0' * 160)
                wait_for(lambda: monitor.disabled)
                self.assertEqual(len(warnings), 1)
            finally:
                monitor.close()

    def test_default_mode_mutes_on_connect_and_flushes_the_player(self):
        players = []
        def factory(*args, **kwargs):
            player = Player();players.append(player);return player
        with patch('audio_monitor.subprocess.Popen', side_effect=factory):
            monitor = AudioMonitor(range(256), player='paplay')
            try:
                monitor.update();monitor.feed(bytes([64]) * 160, bytes([32]) * 160)
                wait_for(lambda: len(players) == 1)
                monitor.update(connected=True)
                wait_for(lambda: players[0].closed.is_set())
                monitor.feed(b'\0' * 160, b'\0' * 160)
                self.assertFalse(monitor.audible)
                monitor.update(mode=2, connected=True)
                monitor.feed(b'\0' * 160, b'\0' * 160)
                wait_for(lambda: len(players) == 2)
                monitor.update(mode=0)
                wait_for(lambda: players[1].closed.is_set())
            finally:
                monitor.close()
                for player in players:player.close()

    def test_blocked_player_cannot_block_producer_and_queue_stays_bounded(self):
        player = Player(fill=True)
        with patch('audio_monitor.subprocess.Popen', return_value=player):
            monitor = AudioMonitor(range(256), player='paplay')
            try:
                monitor.update()
                start = time.monotonic()
                for _ in range(2000):monitor.feed(b'\0' * 160, b'\0' * 160)
                self.assertLess(time.monotonic() - start, .5)
                self.assertLessEqual(monitor.frames.qsize(), 10)
                monitor.close()
                self.assertFalse(monitor.thread.is_alive())
            finally:
                monitor.close();player.close()

    def test_monitor_tracks_carrier_without_an_at_terminal(self):
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.at = None;endpoint.pty = None;endpoint.audio_monitor = object()
        card = SimpleNamespace(dm={0x3ee1: 1})
        call = Call(None, None, 'test', 'tag', card)
        endpoint.at_watch(call)
        self.assertTrue(call.at_connected)

    def test_hangup_flushes_playback_before_the_next_call(self):
        player = Player()
        with patch('audio_monitor.subprocess.Popen', return_value=player):
            monitor = AudioMonitor(range(256), player='paplay')
            try:
                monitor.update(mode=2, connected=True)
                monitor.feed(b'\0' * 160, b'\0' * 160)
                wait_for(lambda: bool(player.read()))
                monitor.update(active=False)
                wait_for(lambda: player.closed.is_set())
                self.assertFalse(monitor.audible)
            finally:
                monitor.close();player.close()

    def test_monitor_does_not_modify_rtp_payload_or_packetization(self):
        endpoint = EiconSipEndpoint.__new__(EiconSipEndpoint)
        endpoint.law = 'pcma';endpoint.codec = SimpleNamespace(encode_g711=bytes)
        endpoint.silence = 213;endpoint.rtp_packet_samples = 240;endpoint.tx_target_quanta = 6
        endpoint.at = AtParser()
        call = Call(None, None, 'test', 'tag', None)
        call.rx_last_codes = [11] * 160
        from unittest.mock import Mock
        endpoint.audio_monitor = Mock()
        for connected, mode, volume in ((False, 1, 2), (True, 1, 2), (True, 2, 3)):
            call.at_connected = connected
            endpoint.at.execute(f'ATM{mode}L{volume}'.encode())
            endpoint._queue_rtp(call, list(range(160)))
            endpoint.audio_monitor.update.assert_called_with(mode=mode, volume=volume, connected=connected)
            endpoint.audio_monitor.feed.assert_called_with(bytes(range(160)), bytes([11]) * 160)
        self.assertEqual(b''.join(call.tx_queue) + bytes(call.tx_pending), bytes(range(160)) * 3)


if __name__ == '__main__':
    unittest.main()
