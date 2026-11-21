"""Decode the ClaudeLink pixel strip.

The layout must match addon/ClaudeLink/Live.lua: a grid of COLS x ROWS squares,
three marker squares with fixed colors, a two-square header, then the payload
packed three bytes (R, G, B) per square.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

PROTO = 2
COLS, ROWS = 48, 8
MAGIC = (0x57, 0x46, 0x4C)
END = (0x4C, 0x46, 0x57)
BOTTOM = (0x42, 0x54, 0x4D)
MARKERS = {0: MAGIC, COLS - 1: END, (ROWS - 1) * COLS: BOTTOM}
DATA = [i for i in range(COLS * ROWS) if i not in MARKERS]
MAX_PAYLOAD = (len(DATA) - 2) * 3

# Bars under the squares (see ns.updateBars in Live.lua). The game hides some
# numbers from addons in combat, but bars may still display them.
BARS = ["player_health", "player_power", "target_health", "pet_health"]
BAR_CELLS = 32
BAR_CAP = (0xFF, 0x00, 0xFF)
TOTAL_ROWS = ROWS + 1 + 2 * len(BARS)

Pixel = tuple[int, int, int]


class DecodeError(Exception):
    pass


class PixelSource:
    """Pixels of a captured image. `get(x, y)` returns (r, g, b)."""

    def __init__(self, width: int, height: int, get: Callable[[int, int], Pixel]):
        self.width, self.height, self.get = width, height, get

    @classmethod
    def from_bgra(cls, width: int, height: int, raw: bytes) -> "PixelSource":
        def get(x: int, y: int) -> Pixel:
            i = (y * width + x) * 4
            return raw[i + 2], raw[i + 1], raw[i]
        return cls(width, height, get)

    @classmethod
    def from_pil(cls, image) -> "PixelSource":
        rgb = image.convert("RGB")
        px = rgb.load()
        return cls(rgb.width, rgb.height, lambda x, y: px[x, y])


def _close(a: Pixel, b: Pixel, tol: int = 3) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@dataclass
class Grid:
    x: float
    y: float
    cell_w: float
    cell_h: float

    def center(self, index: int) -> tuple[int, int]:
        col, row = index % COLS, index // COLS
        return int(self.x + (col + 0.5) * self.cell_w), int(self.y + (row + 0.5) * self.cell_h)


def _grid_at(src: PixelSource, x: int, y: int) -> Optional[Grid]:
    """Given the top-left pixel of the start marker, measure the grid."""
    w = 0
    while x + w < src.width and _close(src.get(x + w, y), MAGIC):
        w += 1
    h = 0
    while y + h < src.height and _close(src.get(x, y + h), MAGIC):
        h += 1
    if not (1 <= w <= 12 and 1 <= h <= 12):
        return None
    # Find the end marker on the same row, and the bottom marker in the same column.
    mid_y = y + h // 2
    end_x = None
    lo, hi = x + (COLS - 1) * max(1, w - 1), min(src.width - 1, x + (COLS - 1) * (w + 1) + 2)
    for xx in range(lo, hi + 1):
        if _close(src.get(xx, mid_y), END):
            end_x = xx
            break
    mid_x = x + w // 2
    bottom_y = None
    lo, hi = y + (ROWS - 1) * max(1, h - 1), min(src.height - 1, y + (ROWS - 1) * (h + 1) + 2)
    for yy in range(lo, hi + 1):
        if _close(src.get(mid_x, yy), BOTTOM):
            bottom_y = yy
            break
    if end_x is None or bottom_y is None:
        return None
    return Grid(x, y, (end_x - x) / (COLS - 1), (bottom_y - y) / (ROWS - 1))


def find_grid(src: PixelSource, hint: Optional[Grid] = None, zone: int = 260) -> Optional[Grid]:
    """Look for the strip in the four corners of the image."""
    if hint is not None:
        gx, gy = int(round(hint.x)), int(round(hint.y))
        if 0 <= gx < src.width and 0 <= gy < src.height and _close(src.get(gx, gy), MAGIC):
            g = _grid_at(src, gx, gy)
            if g:
                return g
    zones = [
        (0, 0),
        (max(0, src.width - zone), 0),
        (0, max(0, src.height - zone)),
        (max(0, src.width - zone), max(0, src.height - zone)),
    ]
    for zx, zy in zones:
        for y in range(zy, min(src.height, zy + zone)):
            for x in range(zx, min(src.width, zx + zone)):
                if not _close(src.get(x, y), MAGIC):
                    continue
                if x > 0 and _close(src.get(x - 1, y), MAGIC):
                    continue
                if y > 0 and _close(src.get(x, y - 1), MAGIC):
                    continue
                g = _grid_at(src, x, y)
                if g:
                    return g
    return None


def fletcher16(data: bytes) -> int:
    s1 = s2 = 0
    for b in data:
        s1 = (s1 + b) % 255
        s2 = (s2 + s1) % 255
    return s2 * 256 + s1


@dataclass
class Frame:
    seq: int
    payload: bytes


def read_frame(src: PixelSource, grid: Grid) -> Frame:
    cells = [src.get(*grid.center(i)) for i in DATA]
    proto, len_hi, len_lo = cells[0]
    if proto != PROTO:
        raise DecodeError(f"unknown protocol version {proto} (addon and server versions differ?)")
    length = len_hi * 256 + len_lo
    if length > MAX_PAYLOAD:
        raise DecodeError(f"bad payload length {length}")
    seq, ck_hi, ck_lo = cells[1]
    data = bytearray()
    for c in cells[2:]:
        data.extend(c)
        if len(data) >= length:
            break
    payload = bytes(data[:length])
    if fletcher16(payload) != ck_hi * 256 + ck_lo:
        raise DecodeError("checksum mismatch (colors were changed on the way to the screen)")
    return Frame(seq, payload)


# ---------------------------------------------------------------------------
# Payload fields (order and sizes must match ns.buildLive in Live.lua)
# ---------------------------------------------------------------------------
class Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def u(self, n: int) -> int:
        if self.pos + n > len(self.data):
            raise DecodeError("payload ended early")
        v = int.from_bytes(self.data[self.pos:self.pos + n], "big")
        self.pos += n
        return v

    def s(self) -> str:
        n = self.u(1)
        if self.pos + n > len(self.data):
            raise DecodeError("payload ended early")
        v = self.data[self.pos:self.pos + n].decode("utf-8", errors="replace")
        self.pos += n
        return v


FLAG_NAMES = [
    "in_combat", "dead", "ghost", "resting", "mounted", "has_pet", "pet_dead", "has_target",
    "target_dead", "target_is_player", "target_attackable", "target_friendly",
    "target_targeting_me", "target_targeting_pet", "auto_shot_on", "pet_in_combat",
    "in_group", "hidden_values", "target_tapped_by_others", "swimming", "on_flight_path",
    "player_health_hidden", "player_power_hidden", "target_health_hidden", "pet_health_hidden",
]


def parse_payload(data: bytes) -> dict:
    r = Reader(data)
    flags_raw = r.u(4)
    flags = {name: bool(flags_raw >> i & 1) for i, name in enumerate(FLAG_NAMES)}
    s: dict = {"flags": flags}
    s["level"] = r.u(1)
    s["xp_permille"] = r.u(2)
    s["rested_permille"] = r.u(2)
    s["health"], s["health_max"] = r.u(3), r.u(3)
    s["power_type"], s["power"], s["power_max"] = r.u(1), r.u(3), r.u(3)
    s["money_copper"] = r.u(4)
    s["free_bag_slots"] = r.u(1)
    s["ammo"] = r.u(2)
    s["lowest_durability_pct"] = r.u(1)
    s["map_id"], s["map_x"], s["map_y"] = r.u(2), r.u(2), r.u(2)
    s["pet"] = {"health_pct": r.u(1), "happiness": r.u(1), "level": r.u(1), "power_pct": r.u(1)}
    s["target"] = {"health_pct": r.u(1), "level": r.u(1), "classification": r.u(1), "reaction": r.u(1)}
    s["cast_spell_id"], s["cast_remaining_ds"] = r.u(3), r.u(2)
    s["target"]["cast_spell_id"] = r.u(3)
    s["gcd_remaining_ds"] = r.u(2)
    fight = {"duration_ds": r.u(2), "damage_done": r.u(4), "damage_taken": r.u(4), "active": bool(r.u(1))}
    fight["top_spells"] = [{"id": r.u(3), "damage": r.u(4), "hits": r.u(2)} for _ in range(r.u(1))]
    s["fight"] = fight
    s["actions"] = [
        {"slot": r.u(1), "kind": r.u(1), "id": r.u(3), "state": r.u(1), "cooldown_ds": r.u(2)}
        for _ in range(r.u(1))
    ]
    s["buffs"] = [{"id": r.u(3), "remaining_ds": r.u(2), "stacks": r.u(1)} for _ in range(r.u(1))]
    s["target_debuffs"] = [
        {"id": r.u(3), "remaining_ds": r.u(2), "stacks": r.u(1), "mine": bool(r.u(1))}
        for _ in range(r.u(1))
    ]
    s["target"]["name"] = r.s()
    s["target"]["target_name"] = r.s()
    s["zone"], s["sub_zone"] = r.s(), r.s()
    s["last_error"] = r.s()
    s["last_error_age_ds"] = r.u(2)
    s["last_killer"] = r.s()
    # other addons (protocol 2)
    s["hekili"] = [{"kind": r.u(1), "id": r.u(3)} for _ in range(r.u(1))]
    s["dbm_timers"] = [{"text": r.s(), "remaining_ds": r.u(2)} for _ in range(r.u(1))]
    s["dbm_alert"] = r.s()
    s["dbm_alert_age_ds"] = r.u(2)
    return s


def read_bars(src: PixelSource, grid: Grid) -> dict:
    """Fill percentage of each bar, or None when the bar is not there (older addon)."""
    out: dict = {}
    for i, name in enumerate(BARS):
        y = int(grid.y + (ROWS + 1 + 2 * i + 0.5) * grid.cell_h)
        cap_x = int(grid.x + 0.5 * grid.cell_w)
        if not (0 <= y < src.height and 0 <= cap_x < src.width) or not _close(src.get(cap_x, y), BAR_CAP, 20):
            out[name] = None
            continue
        x0 = grid.x + grid.cell_w
        length = BAR_CELLS * grid.cell_w
        filled = 0
        for k in range(int(round(length))):
            x = int(x0 + k)
            if x >= src.width:
                break
            r, g, b = src.get(x, y)
            filled += min(r, g, b) / 255  # partly covered edge pixels count partly
        out[name] = round(min(100.0, filled / length * 100), 1)
    return out
