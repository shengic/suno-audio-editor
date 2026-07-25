"""Shared pytest fixtures.

`tk_root` — a single hidden `tk.Tk()` reused across tests. Avoids
creating multiple root windows (Tk gets unhappy about that) and keeps
tests headless-adjacent (no mainloop, no visible window).

`tiny_clip` — a 1-second stereo synthetic AudioClip with a small sine
wave, cheap to build and enough to exercise slicing/callback logic.
"""

__version__ = "2.1"

import numpy as np
import pytest

from audio_loader import AudioClip


@pytest.fixture(scope="session")
def tk_root():
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def tiny_clip():
    sr = 8000
    duration = 1.0
    n = int(sr * duration)
    t = np.arange(n) / sr
    wave = 0.5 * np.sin(2 * np.pi * 440 * t).astype(np.float32)
    samples = np.stack([wave, wave], axis=1)
    return AudioClip(samples=samples, sample_rate=sr, channels=2, title="tiny")
