"""Waveform display with a single draggable/resizable selection region.

No Tkinter equivalent of wavesurfer.js + its regions/timeline plugins
exists, so this draws downsampled peaks and a time ruler on a plain
tk.Canvas, and implements create/move/resize-by-dragging by hand.

Performance note: peaks and the ruler are only recomputed on load() and
set_zoom() (cached as canvas items). set_playhead(), which is called on
every UI tick during playback, only repositions the single playhead
line via canvas.coords() rather than clearing and redrawing everything.
"""

__version__ = "2.0"

import tkinter as tk

import numpy as np

RULER_HEIGHT = 20
EDGE_GRAB_PX = 6
MIN_REGION_SEC = 0.02


class WaveformView(tk.Frame):
    def __init__(self, master, on_region_change=None, **kwargs):
        super().__init__(master, **kwargs)
        self.on_region_change = on_region_change  # callback(start_sec, end_sec) or None

        self.canvas = tk.Canvas(self, height=170, bg="#111827", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self._clip = None
        self._duration = 0.0
        self._pixels_per_sec = 80.0
        self._region = None  # (start_sec, end_sec) or None
        self._playhead_sec = 0.0

        self._peak_ids = []
        self._ruler_ids = []
        self._region_rect_id = None
        self._region_left_id = None
        self._region_right_id = None
        self._playhead_id = None

        self._drag_mode = None
        self._drag_anchor = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_hover)

    # -- public API --

    def load(self, clip) -> None:
        self._clip = clip
        self._duration = clip.duration
        self._region = None
        self._playhead_sec = 0.0
        self._redraw_waveform()
        if self.on_region_change:
            self.on_region_change(None)

    def set_zoom(self, pixels_per_sec: float) -> None:
        # Floor at 0.1 (not 5.0) so a 4-minute song in an 800px canvas
        # (fit_pps ≈ 3.3) can actually fit; anything lower is just a
        # divide-by-zero guard.
        self._pixels_per_sec = max(0.1, pixels_per_sec)
        self._redraw_waveform()

    def set_playhead(self, sec: float) -> None:
        self._playhead_sec = sec
        self._update_playhead()

    def clear_region(self) -> None:
        self._region = None
        self._redraw_region()
        if self.on_region_change:
            self.on_region_change(None)

    def get_region(self):
        return self._region

    # -- geometry helpers (pure; no canvas access) --

    def _sec_to_x(self, sec: float) -> float:
        return sec * self._pixels_per_sec

    def _x_to_sec(self, x: float) -> float:
        return max(0.0, min(self._duration, x / self._pixels_per_sec))

    def _compute_peaks(self, n_cols: int):
        mono = self._clip.samples.mean(axis=1)
        n = len(mono)
        n_cols = max(1, min(n_cols, n))
        step = max(1, n // n_cols)
        usable = mono[: step * n_cols]
        chunks = usable.reshape(n_cols, step)
        return chunks.min(axis=1), chunks.max(axis=1)

    def _edge_at(self, x: float):
        if self._region is None:
            return None
        x0 = self._sec_to_x(self._region[0])
        x1 = self._sec_to_x(self._region[1])
        if abs(x - x0) <= EDGE_GRAB_PX:
            return "left"
        if abs(x - x1) <= EDGE_GRAB_PX:
            return "right"
        if x0 < x < x1:
            return "inside"
        return None

    @staticmethod
    def _format_ruler_time(sec: float) -> str:
        m = int(sec // 60)
        s = int(sec % 60)
        return f"{m:02d}:{s:02d}"

    @staticmethod
    def _pick_ruler_interval(pixels_per_sec: float) -> float:
        candidates = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300]
        for c in candidates:
            if c * pixels_per_sec >= 80:
                return c
        return candidates[-1]

    # -- rendering --

    def _redraw_waveform(self) -> None:
        c = self.canvas
        for item in self._peak_ids:
            c.delete(item)
        self._peak_ids = []
        for item in self._ruler_ids:
            c.delete(item)
        self._ruler_ids = []

        if self._clip is None:
            c.configure(scrollregion=(0, 0, 1, 1))
            return

        height = self.canvas.winfo_height() or 170
        wave_top = RULER_HEIGHT
        wave_mid = wave_top + (height - wave_top) / 2
        wave_half = (height - wave_top) / 2 * 0.9

        width = max(1, int(self._duration * self._pixels_per_sec))
        n_cols = min(width, 6000)
        mins, maxs = self._compute_peaks(n_cols)

        for i in range(n_cols):
            x = i / n_cols * width
            y0 = wave_mid - maxs[i] * wave_half
            y1 = wave_mid - mins[i] * wave_half
            self._peak_ids.append(c.create_line(x, y0, x, y1, fill="#3b82f6"))

        interval = self._pick_ruler_interval(self._pixels_per_sec)
        t = 0.0
        while t <= self._duration:
            x = self._sec_to_x(t)
            self._ruler_ids.append(c.create_line(x, RULER_HEIGHT - 6, x, RULER_HEIGHT, fill="#64748b"))
            self._ruler_ids.append(
                c.create_text(
                    x + 3, RULER_HEIGHT - 8, text=self._format_ruler_time(t),
                    anchor="sw", fill="#94a3b8", font=("Consolas", 8),
                )
            )
            t += interval

        c.configure(scrollregion=(0, 0, width, height))
        self._redraw_region()
        self._update_playhead()

    def _redraw_region(self) -> None:
        c = self.canvas
        height = self.canvas.winfo_height() or 170

        if self._region is None:
            for item_id in (self._region_rect_id, self._region_left_id, self._region_right_id):
                if item_id is not None:
                    c.itemconfigure(item_id, state="hidden")
            return

        x0 = self._sec_to_x(self._region[0])
        x1 = self._sec_to_x(self._region[1])

        if self._region_rect_id is None:
            self._region_rect_id = c.create_rectangle(x0, RULER_HEIGHT, x1, height, fill="#1e3a5f", outline="")
            self._region_left_id = c.create_line(x0, 0, x0, height, fill="#38bdf8", width=2)
            self._region_right_id = c.create_line(x1, 0, x1, height, fill="#38bdf8", width=2)
        else:
            c.coords(self._region_rect_id, x0, RULER_HEIGHT, x1, height)
            c.coords(self._region_left_id, x0, 0, x0, height)
            c.coords(self._region_right_id, x1, 0, x1, height)
            for item_id in (self._region_rect_id, self._region_left_id, self._region_right_id):
                c.itemconfigure(item_id, state="normal")

        # Push the selection tint below the peak lines so the waveform
        # inside the selection stays visible. Tk canvas has no alpha —
        # z-order is the only way to achieve this.
        c.tag_lower(self._region_rect_id)
        c.tag_raise(self._region_left_id)
        c.tag_raise(self._region_right_id)
        if self._playhead_id is not None:
            c.tag_raise(self._playhead_id)

    def _update_playhead(self) -> None:
        c = self.canvas
        height = self.canvas.winfo_height() or 170
        x = self._sec_to_x(self._playhead_sec)
        if self._playhead_id is None:
            self._playhead_id = c.create_line(x, 0, x, height, fill="#ec4899", width=1)
        else:
            c.coords(self._playhead_id, x, 0, x, height)
        c.tag_raise(self._playhead_id)

    # -- mouse interaction --

    def _on_press(self, event) -> None:
        if self._clip is None:
            return
        x = self.canvas.canvasx(event.x)
        hit = self._edge_at(x)
        sec = self._x_to_sec(x)

        if hit == "left":
            self._drag_mode = "resize-left"
        elif hit == "right":
            self._drag_mode = "resize-right"
        elif hit == "inside":
            self._drag_mode = "move"
            self._drag_anchor = (sec, self._region[0], self._region[1])
        else:
            self._drag_mode = "create"
            self._region = (sec, sec)
            self._redraw_region()

    def _on_drag(self, event) -> None:
        if self._drag_mode is None or self._clip is None:
            return
        x = self.canvas.canvasx(event.x)
        sec = self._x_to_sec(x)

        if self._drag_mode == "create":
            start = self._region[0]
            self._region = (min(start, sec), max(start, sec))
        elif self._drag_mode == "resize-left":
            self._region = (min(sec, self._region[1]), self._region[1])
        elif self._drag_mode == "resize-right":
            self._region = (self._region[0], max(sec, self._region[0]))
        elif self._drag_mode == "move":
            anchor_sec, orig_start, orig_end = self._drag_anchor
            delta = sec - anchor_sec
            span = orig_end - orig_start
            new_start = max(0.0, min(self._duration - span, orig_start + delta))
            self._region = (new_start, new_start + span)

        self._redraw_region()
        # Live-update the region-info readout while dragging, matching the
        # original's region-updated event firing continuously during drag.
        if self.on_region_change and self._region:
            self.on_region_change(self._region)

    def _on_release(self, event) -> None:
        if self._drag_mode and self._region:
            start, end = self._region
            if end - start < MIN_REGION_SEC:
                self._region = None
                self._redraw_region()
                if self.on_region_change:
                    self.on_region_change(None)
        self._drag_mode = None
        self._drag_anchor = None

    def _on_hover(self, event) -> None:
        if self._drag_mode is not None:
            return
        x = self.canvas.canvasx(event.x)
        hit = self._edge_at(x)
        cursor = {"left": "sb_h_double_arrow", "right": "sb_h_double_arrow", "inside": "fleur"}.get(hit, "")
        self.canvas.configure(cursor=cursor)
