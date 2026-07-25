"""Tests for waveform_view.WaveformView.

Static helpers are tested directly. Instance methods that only touch
pure geometry (no canvas rendering) are tested with a real Frame
instance under a hidden Tk root — no mainloop, no visible window.
"""

__version__ = "2.0"

import pytest

from waveform_view import EDGE_GRAB_PX, WaveformView


# ---- static helpers ---------------------------------------------------

def test_format_ruler_time_zero():
    assert WaveformView._format_ruler_time(0) == "00:00"


def test_format_ruler_time_seconds_only():
    assert WaveformView._format_ruler_time(37) == "00:37"


def test_format_ruler_time_over_a_minute():
    assert WaveformView._format_ruler_time(125) == "02:05"


def test_pick_ruler_interval_returns_smallest_that_gives_80px():
    # At 1000 px/sec, even 0.1s * 1000 = 100 >= 80 → 0.1
    assert WaveformView._pick_ruler_interval(1000.0) == 0.1


def test_pick_ruler_interval_low_zoom_returns_large_interval():
    # At 1 px/sec, need 80s per tick → 120 is first candidate >= 80
    assert WaveformView._pick_ruler_interval(1.0) == 120


def test_pick_ruler_interval_extreme_low_zoom_returns_last_candidate():
    assert WaveformView._pick_ruler_interval(0.01) == 300


# ---- instance-level fixtures -----------------------------------------

@pytest.fixture
def view(tk_root, tiny_clip):
    v = WaveformView(tk_root)
    v.load(tiny_clip)
    v._pixels_per_sec = 100.0
    return v


# ---- geometry helpers -------------------------------------------------

def test_sec_to_x_and_back_roundtrip(view):
    assert view._x_to_sec(view._sec_to_x(0.5)) == pytest.approx(0.5, abs=1e-6)


def test_x_to_sec_clamps_negative_to_zero(view):
    assert view._x_to_sec(-50) == 0.0


def test_x_to_sec_clamps_beyond_duration(view, tiny_clip):
    assert view._x_to_sec(1e9) == tiny_clip.duration


# ---- _edge_at ---------------------------------------------------------

def test_edge_at_returns_none_when_no_region(view):
    view._region = None
    assert view._edge_at(50) is None


def test_edge_at_detects_left_edge_within_grab_range(view):
    view._region = (0.5, 0.8)  # x0 = 50, x1 = 80 at 100 px/sec
    assert view._edge_at(50 + EDGE_GRAB_PX - 1) == "left"


def test_edge_at_detects_right_edge_within_grab_range(view):
    view._region = (0.5, 0.8)
    assert view._edge_at(80 - EDGE_GRAB_PX + 1) == "right"


def test_edge_at_returns_inside_when_between_edges(view):
    view._region = (0.5, 0.8)
    assert view._edge_at(65) == "inside"


def test_edge_at_returns_none_when_outside(view):
    view._region = (0.5, 0.8)
    assert view._edge_at(200) is None


# ---- _compute_peaks --------------------------------------------------

def test_compute_peaks_returns_expected_column_count(view):
    mins, maxs = view._compute_peaks(100)
    assert len(mins) == 100
    assert len(maxs) == 100


def test_compute_peaks_min_never_exceeds_max(view):
    mins, maxs = view._compute_peaks(50)
    assert (mins <= maxs).all()


def test_compute_peaks_handles_more_columns_than_samples(view, tiny_clip):
    """When asked for more columns than there are samples, the helper
    clamps n_cols down rather than crashing."""
    n_cols = len(tiny_clip.samples) * 2
    mins, maxs = view._compute_peaks(n_cols)
    assert len(mins) == len(maxs)
    assert len(mins) <= len(tiny_clip.samples)


# ---- clear_region -----------------------------------------------------

def test_clear_region_drops_the_selection(view):
    view._region = (0.1, 0.4)
    view.clear_region()
    assert view.get_region() is None


def test_load_resets_region_and_playhead(view, tiny_clip):
    view._region = (0.1, 0.4)
    view._playhead_sec = 0.7
    view.load(tiny_clip)
    assert view.get_region() is None
    assert view._playhead_sec == 0.0
