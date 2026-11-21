"""Read the end of the game's combat log file (Logs/WoWCombatLog*.txt)."""
from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

TS_RE = re.compile(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d{1,2}):(\d{2}):(\d{2})\.(\d+)")
GUID_RE = re.compile(r"^(Player|Creature|Pet|Vehicle|GameObject|Item|Vignette|Cast|BattlePet)-[0-9A-Fa-f-]+$|^0{16}$")
FLAGS_RE = re.compile(r"^0x[0-9A-Fa-f]+$")


def newest_log(wow_dir: Path) -> Optional[Path]:
    logs = sorted((wow_dir / "Logs").glob("WoWCombatLog*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _parse_time(line: str) -> Optional[float]:
    m = TS_RE.match(line)
    if not m:
        return None
    month, day, year, h, mi, sec, frac = m.groups()
    year = int(year) if year else 2000
    if year < 100:
        year += 2000
    try:
        dt = datetime(year, int(month), int(day), int(h), int(mi), int(sec))
    except ValueError:
        return None
    return dt.timestamp() + float("0." + frac)


def clean_line(line: str) -> str:
    """Drop the long ids and bit flags so the line is short and readable."""
    m = TS_RE.match(line)
    if not m:
        return line.strip()
    clock = f"{int(m.group(4)):02d}:{m.group(5)}:{m.group(6)}.{m.group(7)[:1]}"
    rest = line[m.end():].strip()
    try:
        fields = next(csv.reader([rest]))
    except (csv.Error, StopIteration):
        return line.strip()
    kept = [f for f in fields if not GUID_RE.match(f) and not FLAGS_RE.match(f) and f not in ("nil", "-1")]
    return clock + " " + ",".join(kept)


def recent_lines(path: Path, seconds: float = 30, max_lines: int = 200,
                 only_name: Optional[str] = None, tail_bytes: int = 2_000_000) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - tail_bytes))
        data = fh.read().decode("utf-8", errors="replace")
    lines = data.splitlines()
    if size > tail_bytes and lines:
        lines = lines[1:]  # first line may be cut in the middle
    last_t = None
    for line in reversed(lines):
        last_t = _parse_time(line)
        if last_t is not None:
            break
    if last_t is None:
        return []
    picked = []
    for line in reversed(lines):
        t = _parse_time(line)
        if t is None:
            continue
        if last_t - t > seconds:
            break
        if only_name and only_name.lower() not in line.lower():
            continue
        picked.append(clean_line(line))
        if len(picked) >= max_lines:
            break
    picked.reverse()
    return picked
