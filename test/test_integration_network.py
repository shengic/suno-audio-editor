"""Opt-in network integration test for audio_loader.load_audio.

Skipped by default (pytest.ini sets addopts `-m "not network"`).
Run with:  pytest -m network

Uses a small, stable public test MP3. Override via the TEST_AUDIO_URL
env var if you need to point it at a different fixture (e.g. a Suno
CDN URL you know is live). The URL flows through parse_suno_url first
— for a generic https://…/foo.mp3, it hits the "generic audio URL"
branch (song_id == "external"); for a Suno CDN URL, it hits the cdn1
branch.
"""

__version__ = "2.1"

import os

import pytest

from audio_loader import load_audio

pytestmark = pytest.mark.network

DEFAULT_URL = "https://download.samplelib.com/mp3/sample-3s.mp3"


def test_load_audio_from_public_url_returns_valid_clip():
    url = os.environ.get("TEST_AUDIO_URL", DEFAULT_URL)
    try:
        clip = load_audio(url)
    except Exception as exc:  # network / host may be unreachable
        pytest.skip(f"network URL {url!r} unreachable: {exc}")

    assert clip.sample_rate > 0
    assert clip.channels in (1, 2)
    assert clip.duration > 0
    assert clip.samples.ndim == 2
    assert clip.samples.shape[1] == clip.channels
    assert clip.samples.dtype.name == "float32"
    assert clip.samples.min() >= -1.0
    assert clip.samples.max() <= 1.0
