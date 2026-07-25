# CLAUDE.md

**Version 2.0**

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Tkinter desktop port of a web-based "Suno Audio Trimmer & Editor" (originally React + wavesurfer.js + Node/Python/C# launcher shells, delivered as a zip). The web app let a user paste a Suno song link or drop a local file, drag-select a region on a waveform, preview it, apply fade in/out, and export the region as an MP3.

This repo is a from-scratch Python reimplementation, not a wrapper around the original web code. The port started as a strict feature-parity clone (see "Feature-parity contract") but has since diverged in specific, project-owner-approved ways (see "Explicitly added" / "Explicitly removed"). Before changing behavior — not just code style — check both sections.

There is no build step; this is a plain Python/Tkinter application.

## Commands

Install dependencies:
```
pip install -r requirements.txt        # runtime
pip install -r requirements-dev.txt    # runtime + pytest
```
ffmpeg must also be installed and on PATH (pydub shells out to it for both decoding and MP3 encoding — there is no fallback decoder). `tkinterdnd2` is optional; if it isn't installed, `main.py` falls back to a plain `tk.Tk()` root and the import panel silently drops native drag-and-drop, keeping click-to-browse only. Python 3.13 removed the stdlib `audioop` module that `pydub` still imports; `audioop-lts` is pinned as a conditional dependency to backfill it.

Run the app:
```
python main.py
```

Run tests:
```
pytest              # 84 tests, network tests excluded by default
pytest -m network   # opt-in network integration test (real HTTP fetch)
```
Tests live under `test/` and use pytest. Pure-logic modules (`suno_parser`, `audio_export._slice`, `audio_player._callback`, `waveform_view` static helpers and geometry) are tested directly. `audio_export.export_clip` is tested end-to-end against `tmp_path` (needs ffmpeg on PATH). `waveform_view` instance methods run under a hidden `tk.Tk()` fixture — no mainloop, no visible window. `audio_player._callback` is tested by manually setting `_playing`, `_pos`, and `_region` and calling `_callback` with a numpy buffer, so no PortAudio stream is opened.

## Architecture

Seven modules, each with one job. Reading `app.py` alongside the three audio modules is the fastest way to understand how a user action turns into sound or a file on disk:

- `suno_parser.py` — `parse_suno_url()`. Pure function, no I/O, no Tkinter. Resolves a Suno share link, a raw CDN mp3 URL, a generic audio URL, or a bare UUID into a direct `audio_url` + display `title`.
- `audio_loader.py` — `AudioClip` dataclass (`samples: np.ndarray` shaped `(n_frames, n_channels)` float32 in `[-1, 1]`, `sample_rate`, `channels`, `title`, `artwork: bytes | None`) plus `load_audio(source)`, which dispatches to a local-path loader or a URL loader (URL loader always goes through `parse_suno_url` first, so a plain mp3 link and a Suno share link both work). All decoding goes through `pydub.AudioSegment` (i.e. ffmpeg). Cover art: local files inspected via mutagen for ID3 APIC / MP4 covr / FLAC picture blocks; Suno URLs scrape `og:image` and `og:title` from `suno.com/song/{id}` (best-effort, `None` on any failure).
- `audio_player.py` — `AudioPlayer`, a realtime playback engine on top of `sounddevice.OutputStream`. Holds the read position and an optional `(start_frame, end_frame, loop)` region tuple; the stream callback advances the position, applies volume, and either loops or stops at the region boundary. **No rate/speed control exists here by design** — see "Explicitly removed" below. It exposes `get_time()`/`is_playing()` for polling rather than pushing callbacks off the audio thread, because Tkinter widgets aren't safe to touch from PortAudio's realtime thread — `app.py` polls this every `POLL_MS` via `root.after()` instead of wiring a cross-thread callback.
- `audio_export.py` — `export_clip()` and `build_filename()`. Straight slice → re-encode via pydub/ffmpeg (mp3 always available, no WAV-fallback branch needed since ffmpeg is already a hard dependency). Fade in/out was removed per project owner request — see "Explicitly removed".
- `waveform_view.py` — `WaveformView(tk.Frame)`. The one piece with no off-the-shelf equivalent (no wavesurfer.js for Tkinter): draws downsampled min/max peaks and a time ruler on a `tk.Canvas`, and implements create/move/resize-by-dragging a single selection region by hand. The selection tint rectangle is `tag_lower`ed after each draw so the waveform peaks stay visible on top (Tk canvas has no alpha; z-order is the only tool). Performance-sensitive: peaks and the ruler are cached as canvas items and only recomputed in `load()`/`set_zoom()`; `set_playhead()` (called every UI tick during playback) only repositions one line via `canvas.coords()` rather than clearing and redrawing everything.
- `lyrics.py` — SRT / LRC parsers into a common `Lyric` dataclass (`start`, `end: Optional[float]`, `text`). Pure functions, no Tk. `load_lyrics_file(path)` dispatches by extension. UTF-8 BOM tolerant.
- `app.py` — `App`, the composition root. Builds the import panel (URL entry + drop zone + cover art label + title), region-info panel, status banner, waveform card (waveform + zoom/volume sliders), lyrics panel (hidden until an SRT/LRC file is loaded), and transport bar (▶ 播放 / ⏸ 暫停 / ⏹ 停止 / 試聽選區 / ☑ 選區循環播放 / 儲存為 MP3 / 離開). Owns the single `AudioPlayer` and `WaveformView` instances; binds global keyboard shortcuts; registers global DND targets (root + drop_zone + url_entry so drops work anywhere in the UI); `_on_drop_file` dispatches by extension to `_load_path` (audio) or `_load_lyrics` (lyric file). Lyrics can be dropped before or after audio — new-audio-load clears lyrics unless they were the pending party. Runs the `_tick()` poll loop; when lyrics are loaded, tick also updates the currently-playing line highlight in the lyrics `Text` widget. State is plain attributes and `tk.Variable`s bound directly to widgets — there is intentionally no separate state/store module; Tk's own `Variable` mechanism is the only reactive layer used.
- `main.py` — picks `TkinterDnD.Tk` if `tkinterdnd2` is importable, else falls back to `tk.Tk`, sets geometry `820x540`, and constructs `App`.

## Feature-parity contract

This port must reproduce the original web app's behavior for the items below. Some look like bugs but are intentional carry-overs — do not "fix" them without asking first:

- **Esc/'C' (clear region) does not stop playback.** `App._on_clear_region()` calls `player.clear_region_bound()`, which only drops the region boundary — it never pauses. If a region loop is mid-flight when the user clears the selection, playback keeps going past the old boundary. This mirrors the original's `handleClearRegion`, which never calls `pause()`.
- **The "preview region" button/Shift+Space is not a real pause toggle.** Every click/press restarts playback from the region start (`player.play_region(...)`), the same as the original's `handlePlayHighlightedSection`, which always calls `region.play()` regardless of current state. Only the plain full-track Play/Pause button (Space) actually pauses.
- Filename sanitization must keep matching `[^a-zA-Z0-9一-龥_-]` → `_` (CJK-safe). The pattern itself changed in v2.0 — see "Explicitly added".
- Keyboard shortcuts (Space, Shift+Space, Ctrl+S, Esc, C) must keep no-opping when focus is in a text-entry widget (`App._focus_is_text_input()` checks `winfo_class()` against `Entry`/`TEntry`/`Spinbox`/`TSpinbox`).

### Explicitly removed vs. the original
- **Playback speed control (0.5x–2x) does not exist and should not be re-added without being asked.** It was in the original but was explicitly dropped in this port to avoid the pitch-preservation/resampling complexity (would need `pyrubberband` + a bundled `rubberband` binary to match the original's likely pitch-preserving behavior).
- **Fade in / fade out spinboxes** were removed in v2.0 per project owner request. `audio_export._slice_with_fade` is now `_slice`; `export_clip()` no longer takes fade params. Do not re-add without being asked.

### Explicitly added vs. the original
- **Real drag-and-drop of files onto the import panel.** The original's drop-zone copy ("拖放至此") was not backed by any working `onDrop` handler in the source — only click-to-browse worked. This port wires up `tkinterdnd2`.
- **Global DND: drops work anywhere in the window.** `App._register_global_dnd()` registers the root, the drop_zone, and the URL entry as drop targets. Registering the URL entry explicitly is necessary because `ttk.Entry`'s default DND behavior is to insert the dropped path as text; the explicit registration overrides that and routes to `_on_drop_file` instead.
- **Cover art auto-fetched.** Local files: mutagen extracts embedded ID3 APIC / MP4 covr / FLAC pictures. Suno URLs: `_fetch_suno_metadata()` scrapes `og:image` (and `og:title`) from `suno.com/song/{id}`. Failure at any step yields `None`; the UI shows "無封面" placeholder. Both paths are fragile against upstream tag/HTML changes; treat as best-effort enrichment, not core.
- **Real song title.** Local files use filename without extension (`song.mp3` → `song`); Suno URLs use scraped `og:title` (fallback: parser's `Suno Track (xxx)` label if network/parse fails).
- **Three explicit playback buttons: 播放 / 暫停 / 停止** replace the original's single toggle. Stop = pause + `seek(0)`. Space keyboard shortcut is retained as a play/pause toggle for keyboard convenience.
- **Exit button** (`離開`) at the right end of the transport row (`self.root.destroy`).
- **Copyright footer**: "© 2026 Albert Sheng" at the bottom of the window.
- **Dynamic fit-to-canvas zoom.** Zoom slider is a pure multiplier over `fit_pps = canvas_width / duration`; slider at 0 fits the whole song to the current canvas width, slider at 100 shows 1/20th of the song (`ZOOM_MAX_MULT = 20.0`). On window resize (`<Configure>`), `fit_pps` recomputes from `event.width` and the zoom multiplier is reapplied — so the *visible time window* (`canvas_width / pps`) is invariant across resizes at any given zoom setting. `WaveformView.set_zoom` floor is 0.1 pps (was 5.0), which mattered because long songs at wide canvases had `fit_pps < 5.0` and got clamped, breaking the "fit whole song" property.
- **Export filename pattern:** `{title}_from_{mm}_{ss}{cs}_to_{mm}_{ss}{cs}.{ext}` where `cs` is centiseconds (2 digits). Computed via `int(round(t * 100))` on the whole `t*100` value, not `int((t % 1) * 100)`, to avoid float-precision truncation (e.g. `2.09 * 100 = 208.9999...` int-truncates to `08`, not `09`).
- **Waveform peaks visible under selection tint.** `_redraw_region` ends with `tag_lower(self._region_rect_id)` so the peak lines float above the selection background. Tk canvas has no alpha, so z-order is the only lever.
- **SRT / LRC lyric-file support.** Drop a `.srt` or `.lrc` file anywhere in the window (in any order relative to the audio). The lyrics panel is `grid_remove`'d until a file is loaded — no empty placeholder. **All lyrics are shown** (not filtered by region — earlier iterations filtered, but that broke the bidirectional-selection feature by rewriting the widget mid-drag). Region membership is indicated via a `"region"` background tag; the currently-playing line via a `"current"` tag (LRC end-time inferred from the next line's start). Text selection inside the lyrics widget fires `<<Selection>>` → `_on_lyric_selection` → `waveform.set_region(first_line.start, last_line_end)`. `_syncing_from_lyric` guards against a re-entry loop with `on_region_change`.
- **Fixed window size 820x900.** Sized to fit all content including a loaded lyrics panel with breathing room — matches the reference snapshot the project owner authored. No auto-fit / auto-grow anymore (that approach was tried and rejected in an earlier iteration).
- **`AudioPlayer._start_stream` sets `_playing=True` before `stream.start()`** to avoid a race where PortAudio's very first callback fires and silences because our flag wasn't set yet.
- **`AudioPlayer.play` rewinds `_pos` to 0 if it's past the end.** After a playthrough finishes, `_pos` sits at `len(samples)`; without this reset, clicking 播放 again would produce silence (callback immediately hits `n=0` and stops). Not applicable to `play_region`, which explicitly seeks to `start_frame`.

## Coding rules for this repo

These were supplied by the project owner as standing rules for all development here (condensed from two uploaded guideline documents — restore the originals if you need the verbatim text):

- Minimal code: solve exactly what was asked, no speculative abstractions, no config/flexibility that wasn't requested.
- Surgical changes: touch only what the task requires; don't refactor or reformat adjacent code; match existing style; if you spot unrelated dead code, mention it instead of removing it.
- State assumptions and tradeoffs explicitly before implementing; if multiple interpretations exist, present them instead of silently picking one; stop and ask if something is genuinely unclear rather than guessing.
- Define a verifiable success criterion before starting a non-trivial change (what will be run/checked to confirm it works), and say plainly which parts were actually verified vs. not (e.g. this environment's inability to run a real Tk display or audio device — see "Commands" above).
- Responses to the project owner should be in Traditional Chinese unless he asks otherwise, at an expert level of depth, with no flattery/filler sentences.
