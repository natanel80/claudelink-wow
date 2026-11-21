"""Background reader: samples the strip a few times a second and notes what changed."""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Optional

from .capture import Capturer, CaptureError, strip_region
from .protocol import DecodeError, Grid, PixelSource, find_grid, parse_payload, read_bars, read_frame


class Monitor:
    def __init__(self, capturer_factory: Callable[[], Capturer], interval: float = 0.25,
                 names_fn: Optional[Callable[[], tuple[dict, dict]]] = None):
        self.capturer_factory = capturer_factory
        self.interval = interval
        self.names_fn = names_fn
        self.lock = threading.Lock()
        self.latest: Optional[dict] = None
        self.latest_at = 0.0
        self.last_seq_change_at = 0.0
        self.last_seq: Optional[int] = None
        self.status = "starting"
        self.errors = 0
        self.decoded = 0
        self.grid: Optional[Grid] = None
        self.events: deque = deque(maxlen=300)
        self.history: deque = deque(maxlen=600)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self._thread:
            return
        self._thread = threading.Thread(target=self._run, name="wow-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        capturer = self.capturer_factory()
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.sample(capturer)
            except Exception as exc:  # keep the thread alive no matter what
                with self.lock:
                    self.status = f"error: {exc}"
            time.sleep(max(0.05, self.interval - (time.monotonic() - started)))

    # ---- one sample --------------------------------------------------------
    def sample(self, capturer: Capturer) -> None:
        try:
            rect = capturer.window()
        except CaptureError as exc:
            with self.lock:
                self.status = str(exc)
                self.grid = None
            return
        src: Optional[PixelSource] = None
        offset = (0, 0)
        grid = self.grid
        if grid is not None:
            region = strip_region(rect, grid.x, grid.y, grid.cell_w, grid.cell_h)
            src = capturer.grab(region)
            offset = (region.left - rect.left, region.top - rect.top)
            local = Grid(grid.x - offset[0], grid.y - offset[1], grid.cell_w, grid.cell_h)
            found = find_grid(src, hint=local, zone=max(src.width, src.height))
            if found is None:
                grid = None
            else:
                grid = Grid(found.x + offset[0], found.y + offset[1], found.cell_w, found.cell_h)
                local = found
        if grid is None:
            src = capturer.grab(rect)
            offset = (0, 0)
            local = find_grid(src)
            if local is None:
                with self.lock:
                    self.status = ("The ClaudeLink strip was not found in the corners of the game window. "
                                   "Is the addon on (/claudelink status) and is that corner visible?")
                    self.grid = None
                return
            grid = local
        try:
            frame = read_frame(src, local)
            state = parse_payload(frame.payload)
            state["bars"] = read_bars(src, local)
        except DecodeError as exc:
            with self.lock:
                self.errors += 1
                self.status = f"read error: {exc}"
                self.grid = grid
            return
        self.ingest(frame.seq, state, grid)

    def ingest(self, seq: int, state: dict, grid: Optional[Grid] = None) -> None:
        now = time.time()
        with self.lock:
            prev = self.latest
            self.grid = grid
            self.decoded += 1
            if seq != self.last_seq:
                self.last_seq = seq
                self.last_seq_change_at = now
            self.latest = state
            self.latest_at = now
            self.status = "ok"
            self.history.append((now, _compact(state)))
            if prev is not None:
                for text in diff_events(prev, state, self._names()):
                    self.events.append((now, text))

    def _names(self):
        if not self.names_fn:
            return {}, {}
        try:
            return self.names_fn()
        except Exception:
            return {}, {}

    # ---- reads ---------------------------------------------------------------
    def snapshot(self) -> tuple[Optional[dict], float, float, str]:
        with self.lock:
            return self.latest, self.latest_at, self.last_seq_change_at, self.status

    def recent_events(self, seconds: float) -> list[str]:
        cutoff = time.time() - seconds
        with self.lock:
            items = [(t, e) for t, e in self.events if t >= cutoff]
        now = time.time()
        return [f"{datetime.fromtimestamp(t):%H:%M:%S} ({now - t:.0f}s ago) {e}" for t, e in items]

    def recent_history(self, seconds: float, step: float = 1.0) -> list[dict]:
        cutoff = time.time() - seconds
        with self.lock:
            items = [(t, c) for t, c in self.history if t >= cutoff]
        out, last = [], 0.0
        now = time.time()
        for t, c in items:
            if t - last >= step:
                out.append({"seconds_ago": round(now - t, 1), **c})
                last = t
        return out


def _compact(s: dict) -> dict:
    f = s["flags"]
    bars = s.get("bars") or {}
    hp = (round(s["health"] / s["health_max"] * 100) if s["health_max"] and not f.get("player_health_hidden")
          else bars.get("player_health"))
    pw = (round(s["power"] / s["power_max"] * 100) if s["power_max"] and not f.get("player_power_hidden")
          else bars.get("player_power"))
    return {
        "hp_pct": hp, "power_pct": pw, "combat": f["in_combat"],
        "target": s["target"]["name"] if f["has_target"] else None,
        "target_hp_pct": (bars.get("target_health") if s["target"]["health_pct"] == 255 else s["target"]["health_pct"])
        if f["has_target"] else None,
        "pet_hp_pct": (bars.get("pet_health") if s["pet"]["health_pct"] == 255 else s["pet"]["health_pct"])
        if f["has_pet"] else None,
    }


def diff_events(a: dict, b: dict, names: tuple[dict, dict]) -> list[str]:
    spells = names[0] if names else {}
    fa, fb = a["flags"], b["flags"]
    ev = []
    if fb["in_combat"] and not fa["in_combat"]:
        ev.append("Entered combat" + (f' with {b["target"]["name"]}' if fb["has_target"] else ""))
    if fa["in_combat"] and not fb["in_combat"]:
        fight = b["fight"]
        dur = fight["duration_ds"] / 10
        dps = f', {fight["damage_done"] / dur:.1f} DPS' if dur > 0 else ""
        ev.append(f'Left combat: {dur:.1f}s, {fight["damage_done"]} damage done{dps}, {fight["damage_taken"]} taken')
    if fb["dead"] and not fa["dead"]:
        ev.append("You died" + (f' (killed by {b["last_killer"]})' if b["last_killer"] else ""))
    if fa["dead"] or fa["ghost"]:
        if not fb["dead"] and not fb["ghost"]:
            ev.append("You are alive again")
    if fa["has_pet"] and not fa["pet_dead"] and fb["has_pet"] and fb["pet_dead"]:
        ev.append("Your pet died")
    if fa["has_pet"] and not fb["has_pet"]:
        ev.append("Your pet is gone (dismissed, dead or stabled)")
    if fb["has_pet"] and not fa["has_pet"]:
        ev.append("Your pet is back")
    ta = a["target"]["name"] if fa["has_target"] else None
    tb = b["target"]["name"] if fb["has_target"] else None
    if tb and tb != ta:
        lvl = b["target"]["level"] or "??"
        ev.append(f"New target: {tb} (level {lvl})")
    if fb["has_target"] and fb["target_dead"] and not (fa["has_target"] and fa["target_dead"]) and tb == ta:
        ev.append(f"Target died: {tb}")
    ha, hb = _compact(a)["hp_pct"], _compact(b)["hp_pct"]
    if ha is not None and hb is not None and hb < 35 <= ha and not fb["dead"]:
        ev.append(f"Your health is low ({hb:.0f}%)")
    if b["power_type"] == 0 and b["power_max"] and a["power_max"]:
        pa, pb = a["power"] / a["power_max"], b["power"] / b["power_max"]
        if pb < 0.2 <= pa:
            ev.append(f"Your mana is low ({pb * 100:.0f}%)")
    pa_hp, pb_hp = a["pet"]["health_pct"], b["pet"]["health_pct"]
    if fb["has_pet"] and pb_hp != 255 and pa_hp != 255 and pb_hp < 30 <= pa_hp:
        ev.append(f"Your pet's health is low ({pb_hp}%)")
    if b["level"] > a["level"]:
        ev.append(f'Level up! You are now level {b["level"]}')
    if b["zone"] != a["zone"] and b["zone"]:
        ev.append(f'Entered {b["zone"]}')
    if b["last_error"] and b["last_error_age_ds"] < 10 and (
        b["last_error"] != a["last_error"] or a["last_error_age_ds"] > b["last_error_age_ds"]
    ):
        ev.append(f'Game error message: "{b["last_error"]}"')
    if 0 < b["ammo"] < 100 <= a["ammo"]:
        ev.append(f'Ammo is running out ({b["ammo"]} left)')
    if b["free_bag_slots"] == 0 and a["free_bag_slots"] > 0:
        ev.append("Your bags are full")
    if b["pet"]["happiness"] == 1 and a["pet"]["happiness"] != 1:
        ev.append("Your pet is unhappy: feed it")
    if b["cast_spell_id"] and b["cast_spell_id"] != a["cast_spell_id"]:
        ev.append(f'Casting {spells.get(b["cast_spell_id"]) or b["cast_spell_id"]}')
    return ev
