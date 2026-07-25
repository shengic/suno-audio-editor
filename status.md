# Suno Audio Editor — Status

**Version 2.0** · Python 3.13 · Tkinter desktop app · Windows

Desktop port of the "Suno Audio Trimmer & Editor" web app. Load a Suno share link / CDN URL / local mp3, drag a region on the waveform, preview or export it as mp3/wav.

## Quick start

```
pip install -r requirements.txt   # ffmpeg must be on PATH
python main.py
```

Optional dev setup:
```
pip install -r requirements-dev.txt
pytest              # 84 tests
pytest -m network   # +1 opt-in network integration test
```

## What v2.0 does

### Import
- Paste a Suno share link (`suno.com/song/{uuid}`), a raw CDN mp3 URL (`cdn1.suno.ai/{uuid}.mp3`), a generic https audio URL, or a bare UUID.
- Click the drop zone to browse, or **drop a file anywhere in the window** — the whole UI is a DND target (root + drop zone + URL entry all registered so `ttk.Entry`'s default "insert dropped path as text" behavior is overridden). File type is dispatched by extension: `.mp3/.wav/.m4a/.ogg/.aac/.flac` → audio; `.srt/.lrc` → lyrics.
- Cover art auto-fetched: local files via mutagen (ID3 APIC / MP4 covr / FLAC pictures); Suno URLs via `og:image` scraped from `suno.com/song/{id}`.
- Song title auto-detected: local files use filename minus extension; Suno URLs use `og:title` (fallback to parser label if scrape fails).

### Lyrics
- Drop a `.srt` or `.lrc` file; either format supported (SRT has start+end times, LRC has start-only).
- Drop order is flexible: lyrics before audio, lyrics after audio, or replace lyrics for the current audio all work. New audio resets pending lyrics.
- The lyrics panel appears **only** when a lyric file is loaded — no empty placeholder.
- All lyrics are shown; lines whose start time falls inside the current waveform selection get a blue background tint; the currently-playing line is highlighted in yellow bold (LRC end time inferred from next line's start).
- **Bidirectional selection**: dragging text in the lyrics panel programmatically sets the waveform region to `[first_line.start, last_line.end]` (LRC end inferred from next line). A re-entry guard prevents the resulting `on_region_change` from rewriting the text and blowing away the user's in-progress drag.

### Waveform
- Downsampled peaks drawn on a `tk.Canvas`, with a time ruler.
- Drag on empty area to create a region; drag its edges to resize; drag its interior to move.
- Selection tint sits **behind** the peaks (z-order via `tag_lower`) so the waveform inside the selection stays visible.
- Zoom slider at 0 = whole song fits the canvas; at 100 = 1/20th visible. On window resize, the visible time window is preserved at any zoom level.

### Playback
- Three explicit buttons: `▶ 播放`, `⏸ 暫停`, `⏹ 停止` (Stop = pause + rewind to 0).
- `試聽選區` (Shift+Space) always restarts region playback from the region start — never a pause toggle.
- `☑ 選區循環播放` checkbox loops the region.
- Volume slider (half-width, next to zoom slider).

### Export
- `儲存為 MP3` opens a save dialog; ffmpeg re-encodes the sliced range.
- Default filename: `{title}_from_{mm}_{ss}{cs}_to_{mm}_{ss}{cs}.mp3` where `cs` is centiseconds (2 digits, 00–99).
- Filename sanitize keeps CJK characters (`一-龥` range), replaces everything else with `_`.

### Keyboard shortcuts
| Key | Action |
|---|---|
| Space | Toggle play/pause (full track) |
| Shift+Space | Restart region playback |
| Ctrl+S | Save selection to MP3 |
| Esc / C | Clear selection (does **not** stop playback — this is intentional, matches the original web app's quirk) |

All shortcuts no-op when focus is in an Entry / Spinbox to avoid stealing typed keys.

### Exit
- `離開` button at the right end of the transport bar (`root.destroy`).

## Architecture

Eight single-responsibility modules. See [CLAUDE.md](CLAUDE.md) for the full breakdown.

| File | Role |
|---|---|
| `main.py` | Entry point; picks `TkinterDnD.Tk` or falls back to `tk.Tk`; fixed geometry `820x540` (never auto-grows) |
| `app.py` | Composition root, UI, event wiring, poll loop, DND dispatch (audio vs lyrics by extension) |
| `suno_parser.py` | Pure URL/UUID → audio_url + title resolver |
| `audio_loader.py` | `AudioClip` dataclass; decode via pydub/ffmpeg; extract cover art (mutagen + Suno og:image scrape) |
| `audio_player.py` | Realtime playback via `sounddevice.OutputStream`; UI polls `get_time()`/`is_playing()` |
| `audio_export.py` | Slice + re-encode |
| `waveform_view.py` | `tk.Canvas` peaks + ruler + draggable region |
| `lyrics.py` | SRT / LRC parsers + `Lyric` dataclass; UTF-8 BOM tolerant |

## Test suite

84 tests under `test/`, all green in the reference environment:

| File | Coverage |
|---|---|
| `test_suno_parser.py` | 17 tests — 4 match branches, precedence, error paths, whitespace |
| `test_audio_export.py` | 15 tests — `build_filename` (ASCII/CJK/special chars/centisecond edge cases), `_slice`, `export_clip` end-to-end via ffmpeg |
| `test_audio_loader.py` | 12 tests — `_segment_to_clip` shape/dtype/normalization, `load_from_path` filename-as-title, `_extract_local_artwork` with real APIC frame |
| `test_audio_player.py` | 18 tests — `_callback` behavior (silence/advance/loop/stop-at-region-end), seek clamps, volume clamps, `clear_region_bound` doesn't touch `_playing` (feature-parity contract) |
| `test_waveform_view.py` | 17 tests — static helpers + instance geometry under hidden Tk root |
| `test_integration_network.py` | 1 test, `@pytest.mark.network` — end-to-end `load_audio` on a public MP3, opt-in |
| `test_lyrics.py` | 16 tests — SRT (basic / dot ms sep / multiline / empty / CRLF), LRC (basic / metadata skip / multi-timestamp / no-ms / sorting / empty lines / cs vs ms), `load_lyrics_file` dispatch and UTF-8 BOM |

## v1 → v2 changelog

**Removed:**
- Fade in / fade out (UI + `audio_export._slice_with_fade`)
- The `_clip_{start:.1f}s-{end:.1f}s` filename pattern (replaced with `_from_{mm}_{ss}{cs}_to_{mm}_{ss}{cs}`)

**Added:**
- Three separate playback buttons (was single toggle)
- Exit button
- Cover art (local + Suno og:image scrape)
- Real song title (local: filename minus ext; Suno: og:title scrape)
- Global DND (drops anywhere in window, including URL entry)
- SRT/LRC lyric-file support (auto-hidden panel when no lyric file loaded; region-scoped display; currently-playing line highlight)
- Copyright footer
- pytest suite (100 tests, network integration opt-in)
- `audioop-lts` conditional dep for Python 3.13 (`pydub` still imports the removed stdlib module)

**Fixed:**
- Selection tint hid the waveform (Tk canvas z-order — `tag_lower` on the rectangle)
- Waveform didn't fit at min zoom (hardcoded 5.0 pps floor in `set_zoom`; lowered to 0.1)
- Waveform didn't scale on window resize (used `update_idletasks` in a `<Configure>` handler; switched to `event.width`)
- Filename centisecond field could be off-by-one for floats like `2.09` (routed through `int(round(t*100))` instead of `int((t%1)*100)`)
- `ttk.Entry` swallowed dropped files as text (explicit DND registration override)
- Artwork label sized in char units (`tk.Label(width=96, height=96)` = 96 chars × 96 lines); wrapped in a pixel-locked `tk.Frame`
- `pydub` broke on Python 3.13 (`audioop` stdlib removal; backported via `audioop-lts`)

## Dependencies

Runtime: `numpy`, `pydub`, `sounddevice`, `tkinterdnd2`, `mutagen`, `Pillow`, `audioop-lts` (Python 3.13+). Plus **ffmpeg on PATH** (hard requirement — no fallback decoder).

Dev: `pytest`.

## Known limitations

- Suno artwork/title scrape is fragile against upstream HTML changes — best-effort only, `None` fallback.
- No horizontal scrollbar on the waveform; at high zoom you only see the beginning of the song.
- No unit tests for `app.py`'s Tk event wiring (Space toggle, focus-in-Entry no-op, DND dispatch); those are UI integration, not covered.
- Windows-only tested. Should work on macOS/Linux with ffmpeg + PortAudio + Tk, but not verified.
