"""Read the full snapshot that the addon saves in WTF/.../SavedVariables/ClaudeLink.lua."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Optional

B64_RE = re.compile(r'\["snapshotB64"\]\s*=\s*"([A-Za-z0-9+/=]+)"')


def find_savedvars(wow_dir: Path) -> list[Path]:
    return sorted(
        wow_dir.glob("WTF/Account/*/SavedVariables/ClaudeLink.lua"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


def read_snapshots(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    snaps = []
    for m in B64_RE.finditer(text):
        try:
            snaps.append(json.loads(base64.b64decode(m.group(1)).decode("utf-8", errors="replace")))
        except (ValueError, json.JSONDecodeError):
            continue
    return snaps


def _as_map(v) -> dict:
    """Lua tables with keys 1..n are saved as JSON lists; turn both forms into {id: name}."""
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return {i + 1: name for i, name in enumerate(v) if name}
    return {}


class SnapshotStore:
    """Caches the newest snapshot and reloads it when the file changes."""

    def __init__(self, wow_dir: Optional[Path]):
        self.wow_dir = wow_dir
        self._key: Optional[tuple] = None
        self._snaps: list[dict] = []
        self.path: Optional[Path] = None

    def _refresh(self) -> None:
        if not self.wow_dir:
            return
        files = find_savedvars(self.wow_dir)
        key = tuple((str(p), p.stat().st_mtime) for p in files)
        if key == self._key:
            return
        self._key = key
        snaps = []
        for p in files:
            snaps.extend(read_snapshots(p))
        snaps.sort(key=lambda s: s.get("savedAt") or 0, reverse=True)
        self._snaps = snaps
        self.path = files[0] if files else None

    def latest(self, character: Optional[str] = None) -> Optional[dict]:
        self._refresh()
        for s in self._snaps:
            name = (s.get("character") or {}).get("name")
            if character is None or (name and name.lower() == character.lower()):
                return s
        return None

    def names(self) -> tuple[dict, dict]:
        """Spell and item names from all saved snapshots (newest wins)."""
        self._refresh()
        spells: dict = {}
        items: dict = {}
        for s in reversed(self._snaps):
            spells.update(_as_map(s.get("spellNames")))
            items.update(_as_map(s.get("itemNames")))
        return spells, items
