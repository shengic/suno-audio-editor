"""Tests for audio_loader.

_segment_to_clip is pure and covered directly. load_from_path is
exercised by first writing a real wav via pydub (so ffmpeg is not
strictly needed for input — but pydub still uses ffmpeg to decode
non-wav formats). load_audio's dispatch is covered by feeding it a
real file path vs a URL-shaped string.
"""

__version__ = "2.0"

import io

import numpy as np
import pytest
from pydub import AudioSegment

from audio_loader import (
    _extract_local_artwork,
    _segment_to_clip,
    load_audio,
    load_from_path,
)


def _tiny_png_bytes():
    """Generate a valid 1x1 PNG via PIL (already a runtime dep)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _make_segment(sr=8000, duration_ms=200, channels=1, sample_width=2):
    n_samples = int(sr * duration_ms / 1000) * channels
    raw = (np.zeros(n_samples, dtype=np.int16)).tobytes()
    return AudioSegment(
        raw, frame_rate=sr, sample_width=sample_width, channels=channels
    )


def test_segment_to_clip_mono_shape():
    seg = _make_segment(channels=1)
    clip = _segment_to_clip(seg, "mono")
    assert clip.samples.shape == (len(seg.get_array_of_samples()), 1)
    assert clip.channels == 1


def test_segment_to_clip_stereo_shape():
    seg = _make_segment(channels=2)
    clip = _segment_to_clip(seg, "stereo")
    assert clip.samples.shape[1] == 2
    assert clip.channels == 2


def test_segment_to_clip_dtype_is_float32():
    clip = _segment_to_clip(_make_segment(), "x")
    assert clip.samples.dtype == np.float32


def test_segment_to_clip_normalization_within_unit_range():
    """Loudest possible int16 sample must map to ~1.0 (or ~-1.0), not
    overflow. Uses full-scale sine so we hit the edge of the range."""
    sr = 8000
    n = 800
    peak = np.iinfo(np.int16).max
    raw = (peak * np.ones(n, dtype=np.int16)).tobytes()
    seg = AudioSegment(raw, frame_rate=sr, sample_width=2, channels=1)
    clip = _segment_to_clip(seg, "peak")
    assert clip.samples.max() == pytest.approx(1.0, abs=1e-3)
    assert clip.samples.min() >= -1.0


def test_segment_to_clip_title_and_sample_rate_carried_through():
    seg = _make_segment(sr=16000)
    clip = _segment_to_clip(seg, "hello")
    assert clip.title == "hello"
    assert clip.sample_rate == 16000


def test_audio_clip_duration_matches_frame_count(tiny_clip):
    assert tiny_clip.duration == pytest.approx(1.0, abs=1e-6)


def test_load_from_path_uses_filename_without_extension_as_title(tmp_path):
    wav_path = tmp_path / "sample.wav"
    _make_segment(duration_ms=300, channels=2).export(str(wav_path), format="wav")

    clip = load_from_path(str(wav_path))
    assert clip.title == "sample"  # extension stripped
    assert clip.channels == 2
    assert clip.duration == pytest.approx(0.3, abs=0.01)


def test_load_audio_dispatches_to_file_loader_when_path_exists(tmp_path):
    wav_path = tmp_path / "dispatch.wav"
    _make_segment(duration_ms=100).export(str(wav_path), format="wav")

    clip = load_audio(str(wav_path))
    assert clip.title == "dispatch"


def test_load_audio_dispatches_to_url_loader_when_path_missing(monkeypatch):
    """If the source isn't a real file, load_audio must fall through to
    load_from_url. We stub load_from_url to verify dispatch without
    hitting the network."""
    called = {}

    def fake_url_loader(source):
        called["source"] = source
        return "fake_clip"

    monkeypatch.setattr("audio_loader.load_from_url", fake_url_loader)

    result = load_audio("https://cdn1.suno.ai/deadbeef.mp3")
    assert result == "fake_clip"
    assert called["source"] == "https://cdn1.suno.ai/deadbeef.mp3"


# ---- artwork ----------------------------------------------------------

def test_audio_clip_artwork_defaults_to_none():
    """New field added for the cover-art feature; existing loaders that
    don't populate it must still yield a valid AudioClip."""
    from audio_loader import AudioClip

    clip = AudioClip(
        samples=np.zeros((10, 1), dtype=np.float32),
        sample_rate=8000,
        channels=1,
        title="x",
    )
    assert clip.artwork is None


def test_extract_local_artwork_returns_none_for_file_without_tags(tmp_path):
    wav = tmp_path / "plain.wav"
    _make_segment(duration_ms=100).export(str(wav), format="wav")
    assert _extract_local_artwork(str(wav)) is None


def test_extract_local_artwork_reads_embedded_apic_from_mp3(tmp_path):
    """Write an mp3, attach an APIC frame with a known PNG payload,
    then verify _extract_local_artwork returns exactly those bytes."""
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    from mutagen.mp3 import MP3

    mp3_path = tmp_path / "with_cover.mp3"
    _make_segment(duration_ms=200).export(str(mp3_path), format="mp3")

    png = _tiny_png_bytes()

    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=png))
    tags.save(str(mp3_path))

    extracted = _extract_local_artwork(str(mp3_path))
    assert extracted == png


def test_extract_local_artwork_swallows_errors_on_missing_file(tmp_path):
    assert _extract_local_artwork(str(tmp_path / "does_not_exist.mp3")) is None
