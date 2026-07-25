"""Tests for audio_export.

`build_filename` and `_slice` are pure — no I/O. `export_clip` shells
out to ffmpeg (already a hard dep of the project), so it's tested
end-to-end against tmp_path.

Fade in/out was removed from the export pipeline per project owner
request; there are no fade tests here.
"""

__version__ = "2.0"

import numpy as np
import pytest

from audio_export import _slice, build_filename, export_clip


# ---- build_filename ---------------------------------------------------

def test_build_filename_default_extension_is_mp3():
    assert build_filename("song", 0.0, 1.0).endswith(".mp3")


def test_build_filename_custom_extension_used():
    assert build_filename("song", 0.0, 1.0, ext="wav").endswith(".wav")


def test_build_filename_time_formatted_as_mm_ss_cs():
    """Format: {title}_from_{mm}_{ss}{cs}_to_{mm}_{ss}{cs}.{ext}
    cs is centiseconds (0-99), int-truncated from the fractional part
    to match App._format_time's centisecond display."""
    name = build_filename("song", 12.345, 67.89)
    # 12.345 → mm=00 ss=12 cs=34;   67.89 → mm=01 ss=07 cs=89
    assert "from_00_1234_to_01_0789" in name


def test_build_filename_centiseconds_zero_padded():
    """cs<10 must render with a leading zero so the field is always 2 chars."""
    name = build_filename("s", 1.05, 2.09)
    # 1.05 → mm=00 ss=01 cs=5 → 05;   2.09 → mm=00 ss=02 cs=9 → 09
    assert "from_00_0105_to_00_0209" in name


def test_build_filename_ascii_title_preserved():
    assert build_filename("MySong", 0.0, 1.0).startswith("MySong_from_")


def test_build_filename_cjk_title_preserved():
    """CLAUDE.md contract: filename sanitize must keep CJK characters
    (regex range 一-龥). If this breaks, Chinese titles get mangled."""
    name = build_filename("我的歌曲", 0.0, 1.0)
    assert name.startswith("我的歌曲_from_")


def test_build_filename_spaces_replaced_with_underscore():
    name = build_filename("hello world", 0.0, 1.0)
    assert name.startswith("hello_world_from_")


def test_build_filename_minutes_carry_over_correctly():
    name = build_filename("s", 125.7, 3661.0)
    # 125.7 → mm=02 ss=05 cs=70;   3661.0 → mm=61 ss=01 cs=00
    assert "from_02_0570" in name
    assert "to_61_0100" in name


def test_build_filename_special_chars_replaced():
    name = build_filename("a/b\\c:d?e*f", 0.0, 1.0)
    assert "/" not in name and "\\" not in name and ":" not in name


# ---- _slice ----------------------------------------------------------

def _flat_clip(sr=8000, duration=1.0, value=0.5, channels=2):
    from audio_loader import AudioClip

    n = int(sr * duration)
    samples = np.full((n, channels), value, dtype=np.float32)
    return AudioClip(samples=samples, sample_rate=sr, channels=channels, title="flat")


def test_slice_returns_expected_frame_count():
    clip = _flat_clip()
    sliced = _slice(clip, 0.25, 0.75)
    assert sliced.shape[0] == int(8000 * 0.5)


def test_slice_preserves_amplitude():
    clip = _flat_clip(value=0.5)
    sliced = _slice(clip, 0.0, 0.5)
    assert np.allclose(sliced, 0.5)


def test_slice_zero_length_selection_raises():
    clip = _flat_clip()
    with pytest.raises(ValueError):
        _slice(clip, 0.5, 0.5)


def test_slice_start_clamped_to_zero():
    clip = _flat_clip()
    sliced = _slice(clip, -1.0, 0.5)
    assert sliced.shape[0] == int(8000 * 0.5)


def test_slice_end_clamped_to_duration():
    clip = _flat_clip(duration=1.0)
    sliced = _slice(clip, 0.5, 5.0)
    assert sliced.shape[0] == int(8000 * 0.5)


def test_slice_returns_a_copy_not_a_view():
    """Mutating the slice must not corrupt the source clip."""
    clip = _flat_clip(value=0.5)
    sliced = _slice(clip, 0.0, 0.5)
    sliced.fill(0.0)
    assert clip.samples[0, 0] == 0.5


# ---- export_clip (ffmpeg integration) ---------------------------------

def test_export_clip_writes_mp3_file(tiny_clip, tmp_path):
    out = tmp_path / "out.mp3"
    export_clip(tiny_clip, 0.0, 0.5, str(out))
    assert out.exists()
    assert out.stat().st_size > 0
    header = out.read_bytes()[:4]
    assert header[:3] == b"ID3" or header[0] == 0xFF


def test_export_clip_writes_wav_file(tiny_clip, tmp_path):
    out = tmp_path / "out.wav"
    export_clip(tiny_clip, 0.0, 0.5, str(out))
    assert out.exists()
    assert out.read_bytes()[:4] == b"RIFF"


def test_export_clip_extension_defaults_to_mp3_when_missing(tiny_clip, tmp_path):
    out = tmp_path / "noext"
    export_clip(tiny_clip, 0.0, 0.5, str(out))
    assert out.exists() and out.stat().st_size > 0
