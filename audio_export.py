"""Slice a loaded AudioClip and export as mp3 (or wav).

Ported from src/utils/mp3Encoder.js (sliceAudioBuffer / encodeWAV /
encodeMP3). Encoding always goes through pydub + ffmpeg, which is
already a hard dependency for decoding, so mp3 export is always
available here — unlike the original's lamejs-or-WAV-fallback, there
is no fallback path needed.

Fade in/out was removed per project owner request; the export is now a
straight slice → re-encode.
"""

__version__ = "2.0"

import os
import re

import numpy as np
from pydub import AudioSegment

from audio_loader import AudioClip


def _slice(clip: AudioClip, start: float, end: float) -> np.ndarray:
    sr = clip.sample_rate
    start_sample = max(0, int(np.floor(start * sr)))
    end_sample = min(len(clip.samples), int(np.ceil(end * sr)))
    if end_sample - start_sample <= 0:
        raise ValueError("無效的音訊選取範圍")
    return clip.samples[start_sample:end_sample].copy()


def export_clip(clip: AudioClip, start: float, end: float, out_path: str) -> None:
    sliced = _slice(clip, start, end)

    int16 = np.clip(sliced * 32767, -32768, 32767).astype(np.int16)

    seg = AudioSegment(
        int16.tobytes(),
        frame_rate=clip.sample_rate,
        sample_width=2,
        channels=clip.channels,
    )

    ext = os.path.splitext(out_path)[1].lower().lstrip(".") or "mp3"
    if ext == "mp3":
        seg.export(out_path, format="mp3", bitrate="192k")
    else:
        seg.export(out_path, format=ext)


def build_filename(title: str, start: float, end: float, ext: str = "mp3") -> str:
    clean_title = re.sub(r"[^a-zA-Z0-9一-龥_-]", "_", title)

    def _mmssms(t: float) -> str:
        # Format: mm_ssCS where CS is centiseconds (2 digits, 00-99).
        # Route through int(round(t*100)) so float representations like
        # 2.09 → 208.9999… don't int-truncate to CS=08.
        total_cs = int(round(t * 100))
        mm = total_cs // 6000
        rem = total_cs % 6000
        ss = rem // 100
        cs = rem % 100
        return f"{mm:02d}_{ss:02d}{cs:02d}"

    return f"{clean_title}_from_{_mmssms(start)}_to_{_mmssms(end)}.{ext}"
