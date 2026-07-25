"""SRT / LRC lyric-file parsers.

Both formats resolve to a common `Lyric` dataclass so the UI doesn't
have to know which format it came from. LRC only has line start times,
so `Lyric.end` is None for those; the UI treats a None-end as "runs
until the next line's start (or track end)".

Pure functions, no Tk / no I/O beyond reading the file bytes in
`load_lyrics_file`. Kept out of `audio_loader.py` because it's a
distinct concern with its own regex vocabulary.
"""

__version__ = "2.0"

import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Lyric:
    start: float  # seconds
    end: Optional[float]  # seconds, None for LRC (no end timestamp)
    text: str


_SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")
_SRT_BLOCK_RE = re.compile(
    r"\d+\s*\n"
    r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)\s*\n"
    r"(.*?)(?=\n\s*\n|\Z)",
    re.DOTALL,
)


def _srt_time_to_seconds(s: str) -> float:
    m = _SRT_TIME_RE.match(s)
    if not m:
        return 0.0
    h, mm, ss, frac = m.groups()
    # SRT millisecond field is conventionally 3 digits; be defensive
    # about parsers/exports that emit 2 or 4.
    frac_seconds = int(frac) / (10 ** len(frac))
    return int(h) * 3600 + int(mm) * 60 + int(ss) + frac_seconds


def parse_srt(text: str) -> list[Lyric]:
    """Parse SRT text into Lyrics. Accepts either `,` or `.` as the
    millisecond decimal separator; both are found in the wild."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n\n"
    lyrics: list[Lyric] = []
    for match in _SRT_BLOCK_RE.finditer(text):
        start_s, end_s, body = match.groups()
        line = " ".join(part.strip() for part in body.strip().splitlines() if part.strip())
        if not line:
            continue
        lyrics.append(
            Lyric(
                start=_srt_time_to_seconds(start_s),
                end=_srt_time_to_seconds(end_s),
                text=line,
            )
        )
    return lyrics


_LRC_TIMING_RE = re.compile(r"\[(\d+):(\d+)(?:\.(\d+))?\]")


def parse_lrc(text: str) -> list[Lyric]:
    """Parse LRC text into Lyrics. LRC lines can carry multiple
    timestamps on a single text (repeat-lyric marker). Metadata tags
    like [ti:...], [ar:...] have letters after `[`, so the timing
    regex naturally skips them."""
    lyrics: list[Lyric] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        stamps = list(_LRC_TIMING_RE.finditer(line))
        if not stamps:
            continue
        text_part = line[stamps[-1].end():].strip()
        if not text_part:
            continue
        for m in stamps:
            mm, ss, frac = m.groups()
            frac_val = int(frac) / (10 ** len(frac)) if frac else 0.0
            start = int(mm) * 60 + int(ss) + frac_val
            lyrics.append(Lyric(start=start, end=None, text=text_part))
    lyrics.sort(key=lambda l: l.start)
    return lyrics


def load_lyrics_file(path: str) -> list[Lyric]:
    """Read a .srt or .lrc file and return parsed Lyrics. UTF-8 with
    a BOM-tolerant fallback for hand-authored files on Windows."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="ignore")

    if ext == ".srt":
        return parse_srt(text)
    if ext == ".lrc":
        return parse_lrc(text)
    raise ValueError(f"不支援的歌詞檔格式: {ext}")
