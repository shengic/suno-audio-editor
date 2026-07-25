"""Main application window.

Wires the import panel, waveform view, transport controls and
region/export panel together. State lives directly on this object as
tk.Variables bound straight to widgets, or plain attributes — there is
no separate state/observer module. Tk's own Variable mechanism already
is the reactive layer this app needs.
"""

__version__ = "2.0"

import io
import os
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from audio_export import build_filename, export_clip
from audio_loader import AudioClip, load_audio
from audio_player import AudioPlayer
from lyrics import Lyric, load_lyrics_file
from waveform_view import WaveformView

try:
    from tkinterdnd2 import DND_FILES
except ImportError:
    DND_FILES = None

POLL_MS = 50
ZOOM_MAX_MULT = 20.0  # slider at 100% shows 1/20 of the fit-to-canvas width
SLIDER_LENGTH = 220
ARTWORK_SIZE = 96
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}
LYRIC_EXTS = {".srt", ".lrc"}


class App:
    def __init__(self, root, dnd_available: bool = False):
        self.root = root
        self.dnd_available = dnd_available and DND_FILES is not None

        self.clip: AudioClip | None = None
        self.player = AudioPlayer()
        self.is_playing_region = False  # mirrors the original's isPlayingRegion
        self.region = None  # (start, end) or None
        self._artwork_photo = None  # keep PhotoImage alive (Tk GC gotcha)
        self._fit_pps = 20.0  # recomputed on load / resize
        self.lyrics: list[Lyric] | None = None
        self._current_lyric_idx: int = -1
        self._syncing_from_lyric: bool = False  # re-entry guard for lyric→region sync

        self.title_var = tk.StringVar(value="未載入音訊")
        self.url_var = tk.StringVar()
        self.status_var = tk.StringVar()
        self.time_var = tk.StringVar(value="00:00.00 / 00:00.00")
        self.region_duration_var = tk.StringVar(value="")
        self.region_start_var = tk.StringVar(value="")
        self.region_end_var = tk.StringVar(value="")
        self.volume_var = tk.DoubleVar(value=0.8)
        self.zoom_var = tk.DoubleVar(value=0.0)
        self.loop_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._bind_shortcuts()
        self._register_global_dnd()
        self._tick()

    # ---------- UI construction ----------

    def _build_ui(self):
        root = self.root
        root.columnconfigure(0, weight=1)

        top = ttk.Frame(root, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=2)
        top.columnconfigure(1, weight=1)

        self._build_import_panel(top)
        self._build_region_panel(top)

        self.status_label = ttk.Label(root, textvariable=self.status_var, padding=6, anchor="w")
        self.status_label.grid(row=1, column=0, sticky="ew", padx=8)
        self.status_label.grid_remove()

        wave_card = ttk.Frame(root, padding=8)
        wave_card.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        wave_card.columnconfigure(0, weight=1)

        header = ttk.Frame(wave_card)
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="音訊波形").pack(side="left")
        ttk.Label(header, textvariable=self.time_var, font=("Consolas", 9)).pack(side="right")

        self.waveform = WaveformView(wave_card, on_region_change=self._on_region_change)
        self.waveform.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        self.waveform.canvas.bind("<Configure>", self._on_waveform_resize)

        sliders = ttk.Frame(wave_card)
        sliders.grid(row=2, column=0, sticky="w")
        ttk.Label(sliders, text="縮放").pack(side="left")
        ttk.Scale(
            sliders, from_=0, to=100, variable=self.zoom_var,
            command=self._on_zoom_change, length=SLIDER_LENGTH,
        ).pack(side="left", padx=(4, 16))
        ttk.Label(sliders, text="音量").pack(side="left")
        ttk.Scale(
            sliders, from_=0, to=1, variable=self.volume_var,
            command=self._on_volume_change, length=SLIDER_LENGTH,
        ).pack(side="left", padx=(4, 0))

        self._build_lyrics_panel(root)
        self._build_transport_panel(root)

        footer = ttk.Label(
            root,
            text="Space 播放/暫停全曲    Shift+Space 試聽選區    Ctrl+S 匯出    Esc/C 清除選區",
            foreground="#6b7280",
            padding=6,
            anchor="center",
        )
        footer.grid(row=5, column=0, sticky="ew")

        copyright_label = ttk.Label(
            root,
            text="© 2026 Albert Sheng",
            foreground="#9ca3af",
            padding=4,
            anchor="center",
        )
        copyright_label.grid(row=6, column=0, sticky="ew")

    def _build_import_panel(self, parent):
        panel = ttk.LabelFrame(parent, text="1. 匯入音訊", padding=8)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        panel.columnconfigure(0, weight=1)

        url_row = ttk.Frame(panel)
        url_row.grid(row=0, column=0, columnspan=2, sticky="ew")
        url_row.columnconfigure(0, weight=1)
        self.url_entry = ttk.Entry(url_row, textvariable=self.url_var)
        self.url_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            url_row, text="載入 suno 連結", command=self._on_load_url, takefocus=0
        ).grid(row=0, column=1, padx=(6, 0))

        drop_text = (
            "點擊選擇檔案，或將 mp3/wav 拖放至此"
            if self.dnd_available
            else "點擊選擇音訊檔案 (mp3/wav)"
        )
        self.drop_zone = tk.Label(
            panel, text=drop_text, relief="groove", bd=2, padx=12, pady=16, cursor="hand2"
        )
        self.drop_zone.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.drop_zone.bind("<Button-1>", lambda e: self._on_browse_file())

        artwork_frame = tk.Frame(panel, width=ARTWORK_SIZE, height=ARTWORK_SIZE)
        artwork_frame.grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(8, 8))
        artwork_frame.grid_propagate(False)  # tk.Label(width=..) is char-units; lock pixels here
        self.artwork_label = tk.Label(
            artwork_frame, bg="#e5e7eb", text="無封面",
            fg="#9ca3af", relief="groove", bd=1,
        )
        self.artwork_label.pack(expand=True, fill="both")

        ttk.Label(panel, textvariable=self.title_var).grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

    def _build_region_panel(self, parent):
        panel = ttk.LabelFrame(parent, text="2. 選取區資訊", padding=8)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.columnconfigure(0, weight=1)

        ttk.Label(panel, textvariable=self.region_duration_var, font=("Consolas", 14, "bold")).grid(
            row=0, column=0, sticky="w"
        )

        info = ttk.Frame(panel)
        info.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        info.columnconfigure(1, weight=1)
        ttk.Label(info, text="起點").grid(row=0, column=0, sticky="w")
        ttk.Label(info, textvariable=self.region_start_var, font=("Consolas", 9)).grid(row=0, column=1, sticky="e")
        ttk.Label(info, text="終點").grid(row=1, column=0, sticky="w")
        ttk.Label(info, textvariable=self.region_end_var, font=("Consolas", 9)).grid(row=1, column=1, sticky="e")

        ttk.Button(
            panel, text="清除選區 (Esc)", command=self._on_clear_region, takefocus=0
        ).grid(row=2, column=0, sticky="ew")

    def _build_lyrics_panel(self, root):
        self.lyrics_panel = ttk.LabelFrame(
            root, text="歌詞（拖選以設定波形選區）", padding=6
        )
        self.lyrics_panel.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.lyrics_panel.columnconfigure(0, weight=1)

        self.lyrics_text = tk.Text(
            self.lyrics_panel, height=12, wrap="word", state="disabled",
            bg="#f9fafb", fg="#111827", relief="flat",
            font=("Segoe UI", 10),
            # Override Tk's default selection style (blue bg + white fg)
            # so selected lyric text stays readable in black.
            selectbackground="#93c5fd", selectforeground="#111827",
            inactiveselectbackground="#bfdbfe",
        )
        scroll = ttk.Scrollbar(
            self.lyrics_panel, orient="vertical", command=self.lyrics_text.yview
        )
        self.lyrics_text.configure(yscrollcommand=scroll.set)
        self.lyrics_text.grid(row=0, column=0, sticky="ew")
        scroll.grid(row=0, column=1, sticky="ns")

        # "region" tag tints lines whose start falls inside the current
        # waveform selection. "current" tag highlights the line being
        # sung right now. Explicit foreground on both so a bold or
        # highlighted line never picks up a themed white fg.
        self.lyrics_text.tag_configure(
            "region", background="#dbeafe", foreground="#111827",
        )
        self.lyrics_text.tag_configure(
            "current", background="#fde68a", foreground="#111827",
            font=("Segoe UI", 10, "bold"),
        )

        # Bidirectional link: dragging a text selection here becomes
        # the waveform selection. `<<Selection>>` fires on every
        # selection change; the handler debounces via _syncing_from_lyric
        # so the waveform's on_region_change echo doesn't rewrite the
        # text and blow away the user's selection mid-drag.
        self.lyrics_text.bind("<<Selection>>", self._on_lyric_selection)

        # Hidden until a lyric file is loaded.
        self.lyrics_panel.grid_remove()

    def _build_transport_panel(self, root):
        panel = ttk.Frame(root, padding=8)
        panel.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))

        ttk.Button(panel, text="▶ 播放", command=self._on_play, takefocus=0, width=10).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(panel, text="⏸ 暫停", command=self._on_pause, takefocus=0, width=10).pack(
            side="left", padx=(0, 4)
        )
        ttk.Button(panel, text="⏹ 停止", command=self._on_stop, takefocus=0, width=10).pack(
            side="left", padx=(0, 12)
        )
        self.region_play_btn = ttk.Button(
            panel, text="試聽選區 (Shift+Space)", command=self._on_play_region, takefocus=0
        )
        self.region_play_btn.pack(side="left", padx=(0, 6))
        ttk.Checkbutton(panel, text="選區循環播放", variable=self.loop_var, takefocus=0).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(panel, text="儲存為 MP3 (Ctrl+S)", command=self._on_export, takefocus=0).pack(
            side="left"
        )
        ttk.Button(panel, text="離開", command=self.root.destroy, takefocus=0).pack(
            side="left", padx=(6, 0)
        )

    # ---------- shortcuts ----------

    def _bind_shortcuts(self):
        self.root.bind_all("<space>", self._guarded(self._on_toggle_play))
        self.root.bind_all("<Shift-space>", self._guarded(self._on_play_region))
        self.root.bind_all("<Control-s>", self._guarded(self._on_export))
        self.root.bind_all("<Escape>", self._guarded(self._on_clear_region))
        self.root.bind_all("c", self._guarded(self._on_clear_region))
        self.root.bind_all("C", self._guarded(self._on_clear_region))

    def _guarded(self, handler):
        def wrapped(event):
            if self._focus_is_text_input():
                return
            handler()
            return "break"

        return wrapped

    def _focus_is_text_input(self) -> bool:
        widget = self.root.focus_get()
        return widget is not None and widget.winfo_class() in ("Entry", "TEntry", "Spinbox", "TSpinbox")

    # ---------- drag-and-drop (global) ----------

    def _register_global_dnd(self):
        """Register drop targets so files dropped anywhere in the UI go
        through _on_drop_file:
          - root: covers empty areas, buttons, canvas, labels
          - drop_zone: explicit visual target (also registered so its
            child-level registration takes precedence over root's)
          - url_entry: ttk.Entry's default drop behavior is to INSERT
            the path as text; we override that here so a dropped file
            loads instead."""
        if not self.dnd_available:
            return
        try:
            for target in (self.root, self.drop_zone, self.url_entry):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self._on_drop_file)
        except Exception:
            pass

    # ---------- loading ----------

    def _on_browse_file(self):
        path = filedialog.askopenfilename(
            title="選擇音訊檔案",
            filetypes=[("音訊檔案", "*.mp3 *.wav *.m4a *.ogg *.aac"), ("所有檔案", "*.*")],
        )
        if path:
            self._load_path(path)

    def _on_drop_file(self, event):
        path = event.data.strip("{}")
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in AUDIO_EXTS:
            self._load_path(path)
        elif ext in LYRIC_EXTS:
            self._load_lyrics(path)
        else:
            self._set_status(f"不支援的檔案類型：{ext}（audio: {sorted(AUDIO_EXTS)}, lyrics: {sorted(LYRIC_EXTS)}）", "error")

    def _load_lyrics(self, path):
        try:
            lyrics = load_lyrics_file(path)
        except Exception as exc:
            self._set_status(f"歌詞檔載入失敗: {exc}", "error")
            return
        if not lyrics:
            self._set_status(f"歌詞檔內容為空或格式無法解析: {os.path.basename(path)}", "error")
            return
        self.lyrics = lyrics
        name = os.path.basename(path)
        if self.clip is None:
            self._set_status(f"已載入歌詞 {name}（等待音訊）", "success")
        else:
            self._show_lyrics_panel()
            self._refresh_lyrics_display()
            self._set_status(f"已載入歌詞 {name}（{len(lyrics)} 行）", "success")

    def _on_load_url(self):
        url = self.url_var.get().strip()
        if not url:
            return
        self._set_status("載入中...", "success")
        self._load_async(lambda: load_audio(url))

    def _load_path(self, path):
        self._set_status("載入中...", "success")
        self._load_async(lambda: load_audio(path))

    def _load_async(self, loader_fn):
        def worker():
            try:
                clip = loader_fn()
                self.root.after(0, lambda: self._on_loaded(clip))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda: self._set_status(f"載入音訊失敗，請檢查網址或改用本地檔案: {message}", "error"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_loaded(self, clip: AudioClip):
        # Lyrics are per-song. If new audio is loaded WITHOUT a pending
        # lyrics-first drop, clear any lingering lyrics from the previous
        # song. If lyrics were dropped before this audio (the "SRT then
        # MP3" order option-c we agreed on), keep them and show the
        # panel now.
        had_pending_lyrics = self.lyrics is not None and self.clip is None
        if not had_pending_lyrics:
            self.lyrics = None
            self._hide_lyrics_panel()

        self.clip = clip
        self.title_var.set(clip.title)
        self.player.load(clip)
        self.waveform.load(clip)
        self._update_artwork(clip.artwork)
        self._recompute_fit_pps()
        self._on_zoom_change(self.zoom_var.get())
        self._on_region_change(None)

        if had_pending_lyrics:
            self._show_lyrics_panel()
            self._refresh_lyrics_display()

        self._set_status(f"已成功載入音訊: {clip.title}", "success")

    def _update_artwork(self, artwork_bytes):
        if not artwork_bytes:
            self.artwork_label.configure(image="", text="無封面")
            self._artwork_photo = None
            return
        try:
            img = Image.open(io.BytesIO(artwork_bytes)).convert("RGB")
            img.thumbnail((ARTWORK_SIZE, ARTWORK_SIZE))
            self._artwork_photo = ImageTk.PhotoImage(img)
            self.artwork_label.configure(image=self._artwork_photo, text="")
        except Exception:
            self.artwork_label.configure(image="", text="封面解碼失敗")
            self._artwork_photo = None

    # ---------- region ----------

    def _on_region_change(self, region):
        self.region = region
        if region is None:
            self.region_duration_var.set("")
            self.region_start_var.set("")
            self.region_end_var.set("")
        else:
            start, end = region
            self.region_duration_var.set(f"{end - start:.2f} 秒")
            self.region_start_var.set(self._format_time(start))
            self.region_end_var.set(self._format_time(end))
        # Only refresh region *highlight*, not the full text — a full
        # refresh would clear any in-progress lyric selection.
        if self.lyrics is not None:
            self._update_region_highlight()

    def _on_clear_region(self):
        self.waveform.clear_region()
        self.player.clear_region_bound()
        self.is_playing_region = False

    # ---------- playback ----------

    def _on_play(self):
        if self.clip is None:
            return
        self.player.play()
        self.is_playing_region = False

    def _on_pause(self):
        self.player.pause()

    def _on_stop(self):
        self.player.pause()
        self.player.seek(0.0)
        self.is_playing_region = False

    def _on_toggle_play(self):
        """Space keyboard shortcut — kept as a toggle for keyboard
        convenience even though the UI now has explicit buttons."""
        if self.clip is None:
            return
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()
        self.is_playing_region = False

    def _on_play_region(self):
        if self.region is None:
            self._set_status("請先於波形圖上滑鼠拖曳選取欲試聽的區間！", "error")
            return
        self._set_status("", "success")
        start, end = self.region
        self.player.play_region(start, end, loop=self.loop_var.get())
        self.is_playing_region = True

    def _on_volume_change(self, _value):
        self.player.set_volume(self.volume_var.get())

    def _on_waveform_resize(self, event):
        if self.clip is None or self.clip.duration <= 0:
            return
        width = event.width
        if width <= 1:
            return
        self._fit_pps = width / self.clip.duration
        self._on_zoom_change(self.zoom_var.get())

    def _recompute_fit_pps(self):
        if self.clip is None or self.clip.duration <= 0:
            return
        self.root.update_idletasks()
        width = self.waveform.canvas.winfo_width()
        if width <= 1:
            return
        self._fit_pps = width / self.clip.duration

    def _on_zoom_change(self, _value):
        if self.clip is None:
            return
        # Pure multiplier over fit_pps so the visible time window
        # (canvas_width / pps) stays constant across window resizes for
        # any given zoom slider position.
        mult = 1.0 + (self.zoom_var.get() / 100.0) * (ZOOM_MAX_MULT - 1.0)
        self.waveform.set_zoom(self._fit_pps * mult)

    # ---------- export ----------

    def _on_export(self):
        if self.clip is None or self.region is None:
            self._set_status("請先於波形圖上拖曳選取要匯出的區間！", "error")
            return

        start, end = self.region
        default_name = build_filename(self.clip.title, start, end)
        path = filedialog.asksaveasfilename(
            initialfile=default_name,
            defaultextension=".mp3",
            filetypes=[("MP3 音訊", "*.mp3"), ("WAV 音訊", "*.wav")],
        )
        if not path:
            return

        clip = self.clip

        def worker():
            try:
                export_clip(clip, start, end, path)
                name = os.path.basename(path)
                self.root.after(0, lambda: self._set_status(f"已成功導出區間: {name}", "success"))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda: self._set_status(f"匯出 MP3 失敗: {message}", "error"))

        threading.Thread(target=worker, daemon=True).start()

    # ---------- lyrics ----------

    def _show_lyrics_panel(self):
        self.lyrics_panel.grid()

    def _hide_lyrics_panel(self):
        self.lyrics_panel.grid_remove()
        self._current_lyric_idx = -1

    def _lyric_end(self, index: int) -> float:
        """End time for a lyric. LRC lines have no explicit end, so use
        the next lyric's start (or the track end) as an implicit end."""
        lyric = self.lyrics[index]
        if lyric.end is not None:
            return lyric.end
        if index + 1 < len(self.lyrics):
            return self.lyrics[index + 1].start
        if self.clip is not None:
            return self.clip.duration
        return lyric.start + 3600

    def _refresh_lyrics_display(self):
        """Rebuild the lyrics Text widget contents. Shows ALL lyrics
        (not filtered by region) so the user can freely select any
        range; region membership is indicated via a background tag."""
        if self.lyrics is None:
            return

        self.lyrics_text.configure(state="normal")
        self.lyrics_text.delete("1.0", "end")
        for lyric in self.lyrics:
            ts = self._format_time(lyric.start)
            self.lyrics_text.insert("end", f"[{ts}] {lyric.text}\n")
        self.lyrics_text.configure(state="disabled")

        self._current_lyric_idx = -1
        self._update_region_highlight()
        self._update_current_lyric_highlight(self.player.get_time())

    def _update_region_highlight(self):
        """Apply the 'region' background tag to lines whose start time
        falls in the current selection. Called from _on_region_change,
        not per-tick."""
        if self.lyrics is None:
            return
        self.lyrics_text.tag_remove("region", "1.0", "end")
        if self.region is None:
            return
        r_start, r_end = self.region
        for i, lyric in enumerate(self.lyrics):
            if r_start <= lyric.start <= r_end:
                line = i + 1
                self.lyrics_text.tag_add("region", f"{line}.0", f"{line}.end+1c")

    def _update_current_lyric_highlight(self, t: float):
        """Move the 'current' tag to whichever lyric line is active at
        time `t`. LRC end times inferred from next-line start."""
        if not self.lyrics:
            return

        active_idx = -1
        for i in range(len(self.lyrics)):
            if self.lyrics[i].start <= t < self._lyric_end(i):
                active_idx = i
                break

        if active_idx == self._current_lyric_idx:
            return

        self.lyrics_text.tag_remove("current", "1.0", "end")
        if active_idx >= 0:
            line_no = active_idx + 1  # Tk Text lines are 1-indexed
            self.lyrics_text.tag_add("current", f"{line_no}.0", f"{line_no}.end+1c")
            self.lyrics_text.see(f"{line_no}.0")
        self._current_lyric_idx = active_idx

    def _on_lyric_selection(self, _event):
        """Translate a text selection in the lyrics widget into a
        waveform region. First selected line's start → region start;
        last selected line's end (or implicit end for LRC) → region end.
        Guarded so the resulting on_region_change echo doesn't rewrite
        the text and destroy the user's in-progress selection."""
        if self.clip is None or not self.lyrics:
            return
        try:
            sel_first = self.lyrics_text.index("sel.first")
            sel_last = self.lyrics_text.index("sel.last")
        except tk.TclError:
            return  # no selection

        start_line = int(sel_first.split(".")[0]) - 1
        end_line = int(sel_last.split(".")[0]) - 1
        # If selection ends at column 0 of a line, that line isn't
        # actually included — exclude it, matching text-editor convention.
        if int(sel_last.split(".")[1]) == 0 and end_line > start_line:
            end_line -= 1

        n = len(self.lyrics)
        start_line = max(0, min(n - 1, start_line))
        end_line = max(0, min(n - 1, end_line))

        region_start = self.lyrics[start_line].start
        region_end = self._lyric_end(end_line)

        self._syncing_from_lyric = True
        try:
            self.waveform.set_region(region_start, region_end)
        finally:
            self._syncing_from_lyric = False

    # ---------- status / polling ----------

    def _set_status(self, message, kind):
        self.status_var.set(message)
        if message:
            self.status_label.configure(foreground="#b91c1c" if kind == "error" else "#15803d")
            self.status_label.grid()
        else:
            self.status_label.grid_remove()

    @staticmethod
    def _format_time(seconds) -> str:
        if seconds is None:
            return "00:00.00"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        centis = int((seconds % 1) * 100)
        return f"{minutes:02d}:{secs:02d}.{centis:02d}"

    def _tick(self):
        if self.clip is not None:
            t = self.player.get_time()
            self.waveform.set_playhead(t)
            self.time_var.set(f"{self._format_time(t)} / {self._format_time(self.clip.duration)}")
            if self.lyrics is not None:
                self._update_current_lyric_highlight(t)
        self.root.after(POLL_MS, self._tick)
