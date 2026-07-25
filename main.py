"""Entry point for the Suno audio editor desktop app."""

__version__ = "2.0"

try:
    from tkinterdnd2 import TkinterDnD

    _RootClass = TkinterDnD.Tk
    _DND_AVAILABLE = True
except ImportError:
    import tkinter as tk

    _RootClass = tk.Tk
    _DND_AVAILABLE = False

from app import App


def main():
    root = _RootClass()
    root.title("Suno 音訊剪輯工具")
    root.geometry("820x900")
    App(root, dnd_available=_DND_AVAILABLE)
    root.mainloop()


if __name__ == "__main__":
    main()
