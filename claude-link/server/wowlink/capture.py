"""Find the WoW window on Windows and capture pixels from it."""
from __future__ import annotations

import ctypes
import io
import sys
from dataclasses import dataclass
from typing import Optional

from .protocol import COLS, TOTAL_ROWS, PixelSource

IS_WINDOWS = sys.platform == "win32"


@dataclass
class Rect:
    left: int
    top: int
    width: int
    height: int


class CaptureError(Exception):
    pass


if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass

    EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _window_title(hwnd) -> str:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def find_wow_window(title_hint: str = "World of Warcraft"):
        found = []

        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                title = _window_title(hwnd)
                if title_hint.lower() in title.lower() and "launcher" not in title.lower():
                    found.append(hwnd)
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return found[0] if found else None

    def client_rect(hwnd) -> Optional[Rect]:
        if user32.IsIconic(hwnd):
            return None
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        pt = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))
        if rect.right <= 0 or rect.bottom <= 0:
            return None
        return Rect(pt.x, pt.y, rect.right, rect.bottom)
else:
    def find_wow_window(title_hint: str = "World of Warcraft"):
        return None

    def client_rect(hwnd) -> Optional[Rect]:
        return None


class Capturer:
    """Grabs screen regions with mss. Create it in the thread that uses it."""

    def __init__(self, title_hint: str = "World of Warcraft"):
        self.title_hint = title_hint
        self._mss = None

    def _sct(self):
        if self._mss is None:
            import mss
            self._mss = mss.mss()
        return self._mss

    def window(self) -> Rect:
        if not IS_WINDOWS:
            raise CaptureError("Screen capture only works on Windows.")
        hwnd = find_wow_window(self.title_hint)
        if not hwnd:
            raise CaptureError("The World of Warcraft window was not found. Is the game running?")
        rect = client_rect(hwnd)
        if rect is None:
            raise CaptureError("The World of Warcraft window is minimized.")
        return rect

    def grab(self, rect: Rect) -> PixelSource:
        shot = self._sct().grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
        return PixelSource.from_bgra(shot.width, shot.height, bytes(shot.bgra))

    def grab_window(self) -> tuple[Rect, PixelSource]:
        rect = self.window()
        return rect, self.grab(rect)

    def screenshot_jpeg(self, max_width: int = 1280, quality: int = 70) -> bytes:
        from PIL import Image

        rect = self.window()
        shot = self._sct().grab({"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height})
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        if img.width > max_width:
            img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        return buf.getvalue()


def strip_region(rect: Rect, gx: float, gy: float, cell_w: float, cell_h: float) -> Rect:
    """The part of the window that holds the strip, with a small margin."""
    margin = 4
    left = max(0, int(gx) - margin)
    top = max(0, int(gy) - margin)
    width = min(rect.width - left, int(COLS * cell_w) + 2 * margin)
    height = min(rect.height - top, int(TOTAL_ROWS * cell_h) + 2 * margin)
    return Rect(rect.left + left, rect.top + top, width, height)
