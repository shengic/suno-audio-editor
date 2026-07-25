"""Load audio from a local file path or a URL (including Suno links).

Decoding always goes through pydub + ffmpeg, taking the place of the
browser's built-in decodeAudioData for whatever format Suno or a local
file provides (mp3/wav/m4a/ogg).

Cover art is best-effort: local files are inspected with mutagen for
embedded ID3 APIC / MP4 covr / FLAC picture blocks; Suno URLs fall
back to scraping the og:image tag from the public share page. Any
failure (missing tag, network hiccup, HTML shape change) just yields
`artwork=None` — the UI treats it as optional.
"""

__version__ = "2.0"

import html
import io
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Optional

import numpy as np
from pydub import AudioSegment

from suno_parser import parse_suno_url


@dataclass
class AudioClip:
    samples: np.ndarray  # shape (n_frames, n_channels), float32, range [-1, 1]
    sample_rate: int
    channels: int
    title: str
    artwork: Optional[bytes] = None

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def _segment_to_clip(
    seg: AudioSegment, title: str, artwork: Optional[bytes] = None
) -> AudioClip:
    raw = np.array(seg.get_array_of_samples())
    channels = seg.channels
    raw = raw.reshape((-1, channels)) if channels > 1 else raw.reshape((-1, 1))

    max_value = float(1 << (8 * seg.sample_width - 1))
    samples = raw.astype(np.float32) / max_value

    return AudioClip(
        samples=samples,
        sample_rate=seg.frame_rate,
        channels=channels,
        title=title,
        artwork=artwork,
    )


def _extract_local_artwork(path: str) -> Optional[bytes]:
    """Read embedded cover art from an audio file. Returns None if no
    picture is present or the file can't be parsed."""
    try:
        import mutagen
        from mutagen.id3 import APIC
    except ImportError:
        return None

    try:
        f = mutagen.File(path)
        if f is None:
            return None

        tags = getattr(f, "tags", None)
        if tags is not None and hasattr(tags, "values"):
            for tag in tags.values():
                if isinstance(tag, APIC):
                    return bytes(tag.data)

        if hasattr(f, "get") and f.get("covr"):
            covers = f["covr"]
            if covers:
                return bytes(covers[0])

        pictures = getattr(f, "pictures", None)
        if pictures:
            return bytes(pictures[0].data)
    except Exception:
        return None

    return None


_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _fetch_suno_metadata(song_id: str) -> tuple[Optional[str], Optional[bytes]]:
    """Scrape the real song title (og:title) and cover art (og:image)
    from suno.com/song/{id}. Returns (title, artwork_bytes). Any
    failure yields None for the affected field — best-effort only."""
    if not song_id or song_id == "external":
        return None, None
    try:
        page_url = f"https://suno.com/song/{song_id}"
        req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            page_html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None, None

    title = None
    title_match = _OG_TITLE_RE.search(page_html)
    if title_match:
        title = html.unescape(title_match.group(1)).strip() or None

    artwork = None
    img_match = _OG_IMAGE_RE.search(page_html)
    if img_match:
        try:
            img_url = img_match.group(1)
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                artwork = resp.read()
        except Exception:
            artwork = None

    return title, artwork


def load_from_path(path: str) -> AudioClip:
    seg = AudioSegment.from_file(path)
    artwork = _extract_local_artwork(path)
    title = os.path.splitext(os.path.basename(path))[0]
    return _segment_to_clip(seg, title, artwork=artwork)


def load_from_url(url: str) -> AudioClip:
    parsed = parse_suno_url(url)
    if "error" in parsed:
        raise ValueError(parsed["error"])

    req = urllib.request.Request(parsed["audio_url"], headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    seg = AudioSegment.from_file(io.BytesIO(data))
    fetched_title, artwork = _fetch_suno_metadata(parsed.get("song_id", ""))
    title = fetched_title or parsed["title"]
    return _segment_to_clip(seg, title, artwork=artwork)


def load_audio(source: str) -> AudioClip:
    """Load from a local file path, or a URL/Suno link string."""
    if os.path.isfile(source):
        return load_from_path(source)
    return load_from_url(source)
