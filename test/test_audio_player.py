"""Tests for audio_player.AudioPlayer.

We never call `_start_stream()` here — that would open a real
`sounddevice.OutputStream` (touch the sound card). Instead we exercise
`_callback` directly with a numpy buffer, after setting `_playing`,
`_pos`, and `_region` on the instance manually. This is the pattern
CLAUDE.md's "Commands" section calls out for testing playback logic
without sound hardware.
"""

__version__ = "2.1"

import numpy as np
import pytest

from audio_player import AudioPlayer


@pytest.fixture
def player(tiny_clip):
    p = AudioPlayer()
    p.load(tiny_clip)
    return p


def _run_callback(player, frames, channels=2):
    buf = np.zeros((frames, channels), dtype=np.float32)
    player._callback(buf, frames, None, None)
    return buf


# ---- load / seek / volume --------------------------------------------

def test_load_resets_position_and_region(player):
    assert player._pos == 0
    assert player._region is None


def test_seek_within_bounds(player, tiny_clip):
    player.seek(0.5)
    assert player._pos == int(0.5 * tiny_clip.sample_rate)


def test_seek_negative_clamped_to_zero(player):
    player.seek(-10.0)
    assert player._pos == 0


def test_seek_past_end_clamped_to_frame_count(player, tiny_clip):
    player.seek(999.0)
    assert player._pos == len(tiny_clip.samples)


def test_get_time_derived_from_position(player, tiny_clip):
    player.seek(0.25)
    assert player.get_time() == pytest.approx(0.25, abs=1e-6)


def test_set_volume_clamps_below_zero(player):
    player.set_volume(-1.0)
    assert player._volume == 0.0


def test_set_volume_clamps_above_one(player):
    player.set_volume(2.5)
    assert player._volume == 1.0


# ---- clear_region_bound (feature-parity contract) --------------------

def test_clear_region_bound_drops_region_but_leaves_playing_state_alone(player):
    """CLAUDE.md contract: Esc/'C' clears the region but must NOT stop
    playback. If a region loop is mid-flight when the user clears, it
    must keep going. Mirrors the original web app's handleClearRegion,
    which never calls pause()."""
    player._region = (0, 100, True)
    player._playing = True

    player.clear_region_bound()

    assert player._region is None
    assert player._playing is True  # <-- the important assertion


# ---- _callback: silence path -----------------------------------------

def test_callback_writes_silence_when_not_playing(player):
    player._playing = False
    buf = _run_callback(player, frames=64)
    assert np.all(buf == 0)


def test_callback_writes_silence_when_no_clip():
    p = AudioPlayer()
    p._playing = True
    buf = _run_callback(p, frames=64)
    assert np.all(buf == 0)


# ---- _callback: normal advance ---------------------------------------

def test_callback_writes_samples_and_advances_position(player, tiny_clip):
    player._playing = True
    player._pos = 0
    buf = _run_callback(player, frames=128)

    expected = tiny_clip.samples[:128] * player._volume
    assert np.allclose(buf, expected)
    assert player._pos == 128


def test_callback_applies_current_volume(player, tiny_clip):
    player._playing = True
    player._pos = 0
    player.set_volume(0.25)
    buf = _run_callback(player, frames=64)

    expected = tiny_clip.samples[:64] * 0.25
    assert np.allclose(buf, expected)


# ---- _callback: region behavior --------------------------------------

def test_callback_stops_playback_at_region_end_when_not_looping(player, tiny_clip):
    player._playing = True
    player._region = (0, 100, False)
    player._pos = 100  # already at end

    buf = _run_callback(player, frames=64)
    assert np.all(buf == 0)
    assert player._playing is False


def test_callback_loops_to_region_start_when_loop_is_true(player):
    player._playing = True
    player._region = (200, 300, True)
    player._pos = 300  # at end

    _run_callback(player, frames=64)
    assert player._playing is True  # loop keeps it alive
    assert player._pos == 200  # rewound to start


def test_callback_partial_read_at_region_boundary(player, tiny_clip):
    """When fewer frames remain in the region than the callback asked
    for, the callback should fill up to end_limit and pad the rest with
    zeros (single-buffer silence gap at the boundary — documented in
    _callback's inline comment)."""
    player._playing = True
    player._region = (0, 50, False)
    player._pos = 0

    buf = _run_callback(player, frames=128)
    assert not np.all(buf[:50] == 0)  # first 50 frames have signal
    assert np.all(buf[50:] == 0)  # rest is padded silence
    assert player._pos == 50


# ---- pause / stop ----------------------------------------------------

def test_pause_flips_playing_flag_without_touching_stream(player):
    player._playing = True
    player.pause()
    assert player._playing is False
    assert player._stream is None  # no stream was ever opened


def test_stop_when_no_stream_is_a_noop(player):
    player._playing = True
    player.stop()
    assert player._playing is False
