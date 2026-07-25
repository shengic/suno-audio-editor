"""Parse Suno links and extract a direct audio URL.

Ported from the original web app's src/utils/sunoParser.js — same four
match patterns, same precedence order, same title format.
"""

__version__ = "2.1"

import re
from typing import TypedDict


class ParsedSuno(TypedDict, total=False):
    song_id: str
    audio_url: str
    title: str
    error: str


_CDN_RE = re.compile(r"cdn1\.suno\.ai/([a-f0-9\-]+)(\.mp3|\.wav)?", re.IGNORECASE)
_SONG_RE = re.compile(r"suno\.com/song/([a-f0-9\-]+)", re.IGNORECASE)
_AUDIO_URL_RE = re.compile(r"^https?://.*\.(mp3|wav|ogg|m4a|aac)(\?.*)?$", re.IGNORECASE)
_UUID_RE = re.compile(
    r"([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})", re.IGNORECASE
)


def parse_suno_url(input_url: str) -> ParsedSuno:
    if not input_url or not isinstance(input_url, str):
        return {"error": "請輸入有效的網址或路徑"}

    trimmed = input_url.strip()

    cdn_match = _CDN_RE.search(trimmed)
    if cdn_match:
        song_id = cdn_match.group(1)
        return {
            "song_id": song_id,
            "audio_url": f"https://cdn1.suno.ai/{song_id}.mp3",
            "title": f"Suno Track ({song_id[:8]})",
        }

    song_match = _SONG_RE.search(trimmed)
    if song_match:
        song_id = song_match.group(1)
        return {
            "song_id": song_id,
            "audio_url": f"https://cdn1.suno.ai/{song_id}.mp3",
            "title": f"Suno Track ({song_id[:8]})",
        }

    if _AUDIO_URL_RE.match(trimmed):
        filename = trimmed.split("/")[-1].split("?")[0]
        return {
            "song_id": "external",
            "audio_url": trimmed,
            "title": filename or "線上音訊",
        }

    uuid_match = _UUID_RE.search(trimmed)
    if uuid_match:
        song_id = uuid_match.group(1)
        return {
            "song_id": song_id,
            "audio_url": f"https://cdn1.suno.ai/{song_id}.mp3",
            "title": f"Suno Track ({song_id[:8]})",
        }

    return {
        "error": "無法識別 Suno 歌曲連結。請確認格式如：https://suno.com/song/... 或 https://cdn1.suno.ai/....mp3"
    }
