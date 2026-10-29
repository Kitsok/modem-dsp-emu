"""Optional local speaker: bounded, best-effort playback outside modem timing."""
from __future__ import annotations

import os
import math
import queue
import select
import shutil
import struct
import subprocess
import threading
import time

# Attenuate both directions before summing, even at the loudest setting.
VOLUME_GAINS = (0.04, 0.08, 0.16, 0.25)
DTMF_ROWS = (697, 770, 852, 941)
DTMF_COLUMNS = (1209, 1336, 1477, 1633)
DTMF_KEYS = '123A456B789C*0#D'


def progress_pcm(number: str, elapsed: float, ringing: bool, volume: int) -> bytes:
    """Render 20 ms of speaker-only North American call-progress audio."""
    digits = [digit for digit in number.upper() if digit in DTMF_KEYS]
    start = int(elapsed * 8000)
    dial_end = 2400 + len(digits) * 1360  # 300 ms tone, 100/70 ms per digit.
    samples = []
    for sample in range(start, start + 160):
        frequencies = ()
        if sample < 2400:
            frequencies = (350, 440)
        elif sample < dial_end:
            index, offset = divmod(sample - 2400, 1360)
            if offset < 800:
                key = DTMF_KEYS.index(digits[index])
                frequencies = (DTMF_ROWS[key // 4], DTMF_COLUMNS[key % 4])
        elif ringing and (sample - dial_end) % 48000 < 16000:
            frequencies = (440, 480)  # Two seconds on, four seconds off.
        value = sum(math.sin(2 * math.pi * frequency * sample / 8000)
                    for frequency in frequencies)
        samples.append(round(value * 8000 * VOLUME_GAINS[volume]))
    return struct.pack('<160h', *samples)


def mix_pcm(tx: bytes, rx: bytes, table: tuple[int, ...], volume: int) -> bytes:
    """Mix equal-duration G.711 directions as 8 kHz signed little-endian PCM."""
    gain = VOLUME_GAINS[volume]
    return struct.pack('<' + 'h' * len(tx), *(
        max(-32768, min(32767, round((table[a] + table[b]) * gain)))
        for a, b in zip(tx, rx)))


class AudioMonitor:
    """Never wait for a sound server from the producer or RTP sender.

    The producer queues copies of already-produced G.711 frames. At most
    200 ms is queued; congestion drops monitor audio rather than modem audio.
    A generation change invalidates queued audio and closes the old playback
    stream, so mute, CONNECT and hangup cannot replay a previous call later.
    """

    def __init__(self, linear_table, *, log=lambda message: None, player=None):
        self.table = tuple(linear_table)
        self.log = log
        self.player = player if player is not None else shutil.which('paplay')
        self.frames = queue.Queue(maxsize=10)
        self.stopped = threading.Event()
        self.generation = 0
        self.audible = False
        self.volume = 2
        self.progress = None
        self.disabled = not bool(self.player)
        if self.disabled:
            self.log('[audio-monitor] paplay is unavailable; local speaker disabled')
        self.thread = threading.Thread(target=self._run, name='modem-speaker', daemon=True)
        self.thread.start()

    def update(self, *, mode=1, volume=2, connected=False, active=True):
        if not active:
            self.stop_progress()
        audible = active and mode != 0 and (mode != 1 or not connected)
        if audible != self.audible:
            self.generation += 1
            self.audible = audible
        self.volume = volume

    def start_dial(self, number: str):
        self.generation += 1
        self.progress = (number, time.monotonic(), False)

    def ringback(self):
        if self.progress is not None:
            number, started, _ = self.progress
            self.progress = (number, started, True)

    def stop_progress(self):
        if self.progress is not None:
            self.progress = None
            self.generation += 1

    def reset_stream(self):
        """Discard queued early media before the established modem takes over."""
        self.stop_progress()
        self.generation += 1

    def feed(self, tx: bytes, rx: bytes):
        if self.disabled or self.stopped.is_set() or not self.audible:
            return
        if len(tx) != len(rx) or len(tx) > 160:
            raise ValueError('monitor frames must have equal lengths, at most 160 samples')
        frame = (self.generation, bytes(tx), bytes(rx), self.volume)
        try:
            self.frames.put_nowait(frame)
        except queue.Full:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self.frames.put_nowait(frame)
            except queue.Full:
                pass

    @staticmethod
    def _close_player(process):
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        finally:
            process.stdin.close()

    def _run(self):
        process = None
        generation = -1
        next_progress = 0.0
        progress_started = None
        progress_samples = 0
        try:
            while not self.stopped.is_set():
                if process is not None and generation != self.generation:
                    self._close_player(process)
                    process = None
                try:
                    timeout = (max(0.0, min(.02, next_progress - time.monotonic()))
                               if self.progress is not None and self.audible else .02)
                    frame_generation, tx, rx, volume = self.frames.get(timeout=timeout)
                    pcm = mix_pcm(tx, rx, self.table, volume)
                except queue.Empty:
                    frame_generation = self.generation
                    progress = self.progress
                    now = time.monotonic()
                    if progress is None or not self.audible or now < next_progress:
                        continue
                    number, started, ringing = progress
                    if started != progress_started:
                        progress_started = started
                        progress_samples = 0
                    pcm = progress_pcm(number, progress_samples / 8000, ringing, self.volume)
                    progress_samples += 160
                    next_progress = now + .02
                if (not self.audible or frame_generation != self.generation):
                    continue
                if process is None:
                    process = subprocess.Popen(
                        [self.player, '--raw', '--format=s16le', '--rate=8000',
                         '--channels=1', '--latency-msec=60',
                         '--client-name=modem-emu', '--stream-name=modem-emu speaker'],
                        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, bufsize=0)
                    os.set_blocking(process.stdin.fileno(), False)
                    generation = frame_generation
                if process.poll() is not None:
                    raise OSError('paplay exited; check the desktop audio server')
                data = memoryview(pcm)
                deadline = time.monotonic() + 0.1
                while data and not self.stopped.is_set():
                    if generation != self.generation or time.monotonic() >= deadline:
                        break
                    if not select.select([], [process.stdin], [], 0.02)[1]:
                        continue
                    try:
                        data = data[os.write(process.stdin.fileno(), data):]
                    except BlockingIOError:
                        continue
                if data and generation == self.generation:
                    # A stuck device must not build an ever-growing pipe backlog.
                    self._close_player(process)
                    process = None
        except (OSError, ValueError) as exc:
            self.disabled = True
            self.log(f'[audio-monitor] playback unavailable: {exc}; modem continues')
        finally:
            self._close_player(process)

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)
