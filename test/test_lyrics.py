"""Tests for lyrics.py.

Both parsers are pure — no I/O — so we feed strings directly.
load_lyrics_file's dispatch is covered with tmp_path.
"""

__version__ = "2.1"

import pytest

from lyrics import Lyric, load_lyrics_file, parse_lrc, parse_srt


# ---- SRT --------------------------------------------------------------

def test_parse_srt_basic():
    srt = (
        "1\n"
        "00:00:12,500 --> 00:00:15,000\n"
        "First line\n"
        "\n"
        "2\n"
        "00:00:15,500 --> 00:00:18,000\n"
        "Second line\n"
    )
    lyrics = parse_srt(srt)
    assert len(lyrics) == 2
    assert lyrics[0] == Lyric(start=12.5, end=15.0, text="First line")
    assert lyrics[1] == Lyric(start=15.5, end=18.0, text="Second line")


def test_parse_srt_dot_millisecond_separator_accepted():
    srt = "1\n00:00:01.250 --> 00:00:02.500\nHello\n"
    lyrics = parse_srt(srt)
    assert lyrics[0].start == pytest.approx(1.25)
    assert lyrics[0].end == pytest.approx(2.5)


def test_parse_srt_multiline_body_joined_with_space():
    srt = (
        "1\n"
        "00:00:00,000 --> 00:00:03,000\n"
        "line one\n"
        "line two\n"
    )
    lyrics = parse_srt(srt)
    assert lyrics[0].text == "line one line two"


def test_parse_srt_empty_input_returns_empty_list():
    assert parse_srt("") == []


def test_parse_srt_carriage_returns_tolerated():
    srt = "1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n"
    lyrics = parse_srt(srt)
    assert len(lyrics) == 1 and lyrics[0].text == "Hello"


# ---- LRC --------------------------------------------------------------

def test_parse_lrc_basic():
    lrc = (
        "[00:12.50]First line\n"
        "[00:15.00]Second line\n"
    )
    lyrics = parse_lrc(lrc)
    assert len(lyrics) == 2
    assert lyrics[0] == Lyric(start=12.5, end=None, text="First line")
    assert lyrics[1] == Lyric(start=15.0, end=None, text="Second line")


def test_parse_lrc_metadata_tags_are_skipped():
    """[ti:...], [ar:...] etc. have letters right after `[` so the
    numeric-timing regex naturally doesn't match them."""
    lrc = (
        "[ti:Song Title]\n"
        "[ar:Artist]\n"
        "[al:Album]\n"
        "[00:10.00]Real lyric line\n"
    )
    lyrics = parse_lrc(lrc)
    assert len(lyrics) == 1
    assert lyrics[0].text == "Real lyric line"


def test_parse_lrc_multiple_timestamps_per_line_expand():
    """A line prefixed by multiple `[mm:ss]` tags is a repeat marker;
    each timestamp becomes its own Lyric with the same text."""
    lrc = "[00:10.00][01:20.00]Chorus\n"
    lyrics = parse_lrc(lrc)
    assert len(lyrics) == 2
    assert lyrics[0] == Lyric(start=10.0, end=None, text="Chorus")
    assert lyrics[1] == Lyric(start=80.0, end=None, text="Chorus")


def test_parse_lrc_timestamps_without_fractional_seconds():
    lrc = "[00:30]Half a minute in\n"
    lyrics = parse_lrc(lrc)
    assert lyrics[0].start == 30.0


def test_parse_lrc_output_sorted_by_start():
    """Multi-timestamp lines can emit out-of-order entries;
    parse_lrc sorts before returning."""
    lrc = (
        "[01:00.00][00:10.00]Repeat me\n"
        "[00:30.00]Middle\n"
    )
    lyrics = parse_lrc(lrc)
    assert [round(l.start, 2) for l in lyrics] == [10.0, 30.0, 60.0]


def test_parse_lrc_ignores_empty_and_untimed_lines():
    lrc = "\n[00:05.00]Only real line\nno timestamp here\n\n"
    lyrics = parse_lrc(lrc)
    assert len(lyrics) == 1 and lyrics[0].text == "Only real line"


def test_parse_lrc_centiseconds_and_milliseconds_both_ok():
    lrc = "[00:01.05]cs\n[00:02.500]ms\n"
    lyrics = parse_lrc(lrc)
    assert lyrics[0].start == pytest.approx(1.05)
    assert lyrics[1].start == pytest.approx(2.5)


# ---- load_lyrics_file (dispatch) -------------------------------------

def test_load_lyrics_file_dispatches_srt(tmp_path):
    p = tmp_path / "song.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    lyrics = load_lyrics_file(str(p))
    assert lyrics[0].text == "Hello"


def test_load_lyrics_file_dispatches_lrc(tmp_path):
    p = tmp_path / "song.lrc"
    p.write_text("[00:05.00]Hi\n", encoding="utf-8")
    lyrics = load_lyrics_file(str(p))
    assert lyrics[0].text == "Hi"


def test_load_lyrics_file_rejects_unknown_extension(tmp_path):
    p = tmp_path / "song.txt"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        load_lyrics_file(str(p))


def test_load_lyrics_file_handles_utf8_bom(tmp_path):
    """Windows-authored SRT often carries a UTF-8 BOM; the loader
    strips it via utf-8-sig."""
    p = tmp_path / "bom.srt"
    p.write_bytes(b"\xef\xbb\xbf1\n00:00:00,500 --> 00:00:01,000\nHello\n")
    lyrics = load_lyrics_file(str(p))
    assert len(lyrics) == 1 and lyrics[0].text == "Hello"
