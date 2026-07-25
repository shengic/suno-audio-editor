"""Realtime playback engine backed by sounddevice.

No speed/rate control — that feature was dropped per explicit request,
so there is no resampling logic here at all.

Position/finished-state is exposed via get_time()/is_playing() for the
UI to poll on a Tk `.after()` timer, rather than pushing callbacks out
of the audio thread. sounddevice's callback runs on PortAudio's own
real-time thread, and Tkinter widgets are not safe to touch from a
non-main thread — polling from the main loop sidesteps that entirely
and is simple enough for this app's needs (no extra queue/dispatcher).
"""

__version__ = "2.0"

import threading

import sounddevice as sd

from audio_loader import AudioClip


class AudioPlayer:
    def __init__(self):
        self._clip: AudioClip | None = None
        self._pos = 0  # frame index
        self._volume = 0.8
        self._region = None  # (start_frame, end_frame, loop) or None
        self._playing = False
        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()

    def load(self, clip: AudioClip) -> None:
        self.stop()
        with self._lock:
            self._clip = clip
            self._pos = 0
            self._region = None

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))

    def seek(self, time_sec: float) -> None:
        if not self._clip:
            return
        with self._lock:
            self._pos = int(max(0, min(len(self._clip.samples), time_sec * self._clip.sample_rate)))

    def get_time(self) -> float:
        if not self._clip:
            return 0.0
        return self._pos / self._clip.sample_rate

    def play(self) -> None:
        if not self._clip:
            return
        with self._lock:
            self._region = None
            # If a previous playthrough left _pos at (or past) the end,
            # the next callback would see n=0 and immediately stop —
            # visible bug: "click 播放 does nothing". Rewind to start.
            if self._pos >= len(self._clip.samples):
                self._pos = 0
        self._start_stream()

    def play_region(self, start: float, end: float, loop: bool = False) -> None:
        if not self._clip:
            return
        sr = self._clip.sample_rate
        with self._lock:
            start_frame = int(max(0, start * sr))
            end_frame = int(min(len(self._clip.samples), end * sr))
            self._region = (start_frame, end_frame, loop)
            self._pos = start_frame
        self._start_stream()

    def pause(self) -> None:
        self._playing = False

    def stop(self) -> None:
        self._playing = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def is_playing(self) -> bool:
        return self._playing

    def clear_region_bound(self) -> None:
        """Drop the region boundary without touching playback state.

        Matches the original's handleClearRegion, which clears the
        selection but never calls pause() — if a region loop is mid-flight
        when the user hits Esc, playback keeps going past the old boundary
        instead of stopping.
        """
        with self._lock:
            self._region = None

    def _start_stream(self) -> None:
        # Set the playing flag BEFORE .start() so the very first
        # callback invocation (which PortAudio can fire immediately on
        # start) sees _playing=True and emits samples instead of
        # silencing.
        self._playing = True
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=self._clip.sample_rate,
                channels=self._clip.channels,
                callback=self._callback,
                dtype="float32",
            )
            self._stream.start()

    def _callback(self, outdata, frames, time_info, status):
        if not self._playing or self._clip is None:
            outdata.fill(0)
            return

        with self._lock:
            samples = self._clip.samples
            pos = self._pos
            region = self._region

        end_limit = region[1] if region else len(samples)
        n = min(frames, max(end_limit - pos, 0))

        if n <= 0:
            # Region end reached. Looping resets the read position but this
            # callback still outputs silence for this buffer — a single
            # buffer's worth of gap at the loop point (a few ms). The
            # original's region.play()-on-region-out restart is likewise
            # event-driven rather than sample-accurate, so this is at parity
            # rather than a regression.
            outdata.fill(0)
            if region and region[2]:
                with self._lock:
                    self._pos = region[0]
            else:
                self._playing = False
            return

        outdata[:n] = samples[pos:pos + n] * self._volume
        if n < frames:
            outdata[n:] = 0

        with self._lock:
            self._pos = pos + n
