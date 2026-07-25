"""Regression tests for suno_parser.parse_suno_url.

Locks the four match branches (CDN URL / suno.com/song / generic audio
URL / bare UUID) and the error path against the original web app's
behavior. Pure function, no fixtures needed.
"""

__version__ = "2.0"

from suno_parser import parse_suno_url

UUID = "aabbccdd-1122-3344-5566-77889900aabb"


# ---- CDN URL branch ----------------------------------------------------

def test_cdn_url_with_mp3_extension_returns_direct_audio_url():
    result = parse_suno_url(f"https://cdn1.suno.ai/{UUID}.mp3")
    assert result["audio_url"] == f"https://cdn1.suno.ai/{UUID}.mp3"
    assert result["song_id"] == UUID


def test_cdn_url_with_wav_extension_still_normalizes_to_mp3():
    result = parse_suno_url(f"https://cdn1.suno.ai/{UUID}.wav")
    assert result["audio_url"] == f"https://cdn1.suno.ai/{UUID}.mp3"


def test_cdn_url_without_extension_still_matches():
    result = parse_suno_url(f"https://cdn1.suno.ai/{UUID}")
    assert result["song_id"] == UUID


def test_cdn_url_title_uses_first_eight_chars_of_id():
    result = parse_suno_url(f"https://cdn1.suno.ai/{UUID}.mp3")
    assert result["title"] == f"Suno Track ({UUID[:8]})"


# ---- suno.com/song branch ---------------------------------------------

def test_suno_song_url_resolves_to_cdn_mp3():
    result = parse_suno_url(f"https://suno.com/song/{UUID}")
    assert result["audio_url"] == f"https://cdn1.suno.ai/{UUID}.mp3"
    assert result["song_id"] == UUID


def test_suno_song_url_with_trailing_path_still_matches():
    result = parse_suno_url(f"https://suno.com/song/{UUID}/extra")
    assert result["song_id"] == UUID


# ---- generic audio URL branch -----------------------------------------

def test_generic_mp3_url_marks_external():
    result = parse_suno_url("https://example.com/audio/song.mp3")
    assert result["song_id"] == "external"
    assert result["audio_url"] == "https://example.com/audio/song.mp3"
    assert result["title"] == "song.mp3"


def test_generic_audio_url_query_string_stripped_from_title():
    result = parse_suno_url("https://example.com/x/foo.mp3?token=xyz")
    assert result["title"] == "foo.mp3"


def test_generic_audio_url_supports_wav_ogg_m4a_aac():
    for ext in ("wav", "ogg", "m4a", "aac"):
        result = parse_suno_url(f"https://example.com/foo.{ext}")
        assert result["song_id"] == "external"
        assert result["title"] == f"foo.{ext}"


# ---- bare UUID branch -------------------------------------------------

def test_bare_uuid_resolves_to_cdn_mp3():
    result = parse_suno_url(UUID)
    assert result["audio_url"] == f"https://cdn1.suno.ai/{UUID}.mp3"
    assert result["song_id"] == UUID


def test_uuid_embedded_in_text_is_extracted():
    result = parse_suno_url(f"song id is {UUID} thanks")
    assert result["song_id"] == UUID


# ---- precedence -------------------------------------------------------

def test_cdn_pattern_takes_precedence_over_song_pattern():
    """A string containing both cdn1.suno.ai and suno.com/song must match
    the CDN branch first (it's checked first in the parser)."""
    weird = f"https://cdn1.suno.ai/{UUID}.mp3 (also see suno.com/song/{UUID})"
    result = parse_suno_url(weird)
    assert result["audio_url"] == f"https://cdn1.suno.ai/{UUID}.mp3"


# ---- normalization ----------------------------------------------------

def test_leading_and_trailing_whitespace_stripped():
    result = parse_suno_url(f"   https://suno.com/song/{UUID}   ")
    assert result["song_id"] == UUID


# ---- error path -------------------------------------------------------

def test_empty_string_returns_error():
    assert "error" in parse_suno_url("")


def test_none_input_returns_error():
    assert "error" in parse_suno_url(None)  # type: ignore[arg-type]


def test_non_string_input_returns_error():
    assert "error" in parse_suno_url(12345)  # type: ignore[arg-type]


def test_unrecognized_text_returns_error():
    result = parse_suno_url("hello world, not a suno link")
    assert "error" in result
