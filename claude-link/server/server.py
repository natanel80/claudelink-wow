"""ClaudeLink MCP server: lets Claude see your WoW Forever character while you play.

Read-only. It reads a strip of colored squares that the ClaudeLink addon draws
in a corner of the game window, the addon's saved report, and the game's combat
log file. It never sends keys or clicks to the game.
"""
from __future__ import annotations

import json
import shutil
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from wowlink.capture import Capturer, CaptureError  # noqa: E402
from wowlink.combatlog import newest_log, recent_lines  # noqa: E402
from wowlink.describe import Names, describe  # noqa: E402
from wowlink.monitor import Monitor  # noqa: E402
from wowlink.savedvars import SnapshotStore  # noqa: E402

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"


def load_config() -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    env = os.environ.get("WOW_DIR", "")
    if env and "${" not in env:  # an unfilled plugin setting looks like ${user_config.x}
        cfg["wow_dir"] = env
    return cfg


def find_wow_dir(configured: Optional[str]) -> Optional[Path]:
    """The _forever_ folder: the configured one if it exists, else the usual install places."""
    candidates = []
    if configured:
        p = Path(configured)
        candidates += [p, p / "_forever_"]
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), "C:\\", "D:\\"):
        if base:
            candidates.append(Path(base) / "World of Warcraft" / "_forever_")
    for c in candidates:
        if (c / "Interface").is_dir() or (c / "WTF").is_dir() or (c / "Wow.exe").exists():
            return c
    return Path(configured) if configured else None


def data_dir() -> Path:
    value = os.environ.get("CLAUDELINK_DATA", "")
    if value and "${" not in value:
        d = Path(value)
    else:
        d = APP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


ADDON_SOURCE = APP_DIR.parent / "addon" / "ClaudeLink"


def toc_version(folder: Path) -> Optional[str]:
    toc = folder / "ClaudeLink.toc"
    if not toc.exists():
        return None
    for line in toc.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("## Version:"):
            return line.split(":", 1)[1].strip()
    return None


def install_addon(wow_dir: Optional[Path]) -> str:
    """Copy the bundled addon into the game if it is missing or a different version."""
    if wow_dir is None or not ADDON_SOURCE.is_dir():
        return "skipped (WoW folder not found)" if wow_dir is None else "skipped (no bundled addon)"
    target = wow_dir / "Interface" / "AddOns" / "ClaudeLink"
    want, have = toc_version(ADDON_SOURCE), toc_version(target)
    if want and want == have:
        return f"up to date ({have})"
    try:
        target.mkdir(parents=True, exist_ok=True)
        for f in ADDON_SOURCE.iterdir():
            if f.is_file():
                shutil.copy2(f, target / f.name)
    except OSError as exc:
        return f"could not copy the addon into {target}: {exc}"
    return f"installed version {want} in {target}" + (f" (was {have})" if have else "") + \
        " (restart WoW or /reload to load it)"


CONFIG = load_config()
WOW_DIR: Optional[Path] = find_wow_dir(CONFIG.get("wow_dir"))
WINDOW_TITLE = CONFIG.get("window_title", "World of Warcraft")
ADDON_STATUS = "not checked"
if os.environ.get("CLAUDELINK_INSTALL_ADDON", "true").lower() not in ("false", "0", "no"):
    try:
        ADDON_STATUS = install_addon(WOW_DIR)
    except Exception as exc:  # never stop the server because of this
        ADDON_STATUS = f"error: {exc}"

store = SnapshotStore(WOW_DIR)
_names_cache: dict = {"at": 0.0, "value": ({}, {})}


def names() -> tuple[dict, dict]:
    if time.time() - _names_cache["at"] > 5:
        try:
            spells, items = store.names()
            n = Names(spells, items)
            _names_cache["value"] = (n.spells, n.items)
        except Exception:
            pass
        _names_cache["at"] = time.time()
    return _names_cache["value"]


def action_keys() -> dict:
    """Action slot -> key binding, from the saved report (bindings rarely change)."""
    try:
        snap = store.latest()
    except Exception:
        return {}
    keys = {}
    for a in (snap or {}).get("actionBars") or []:
        if isinstance(a, dict) and a.get("slot") and a.get("key"):
            keys[int(a["slot"])] = a["key"]
    return keys


NOTES_PATH = data_dir() / "notes.md"

monitor = Monitor(lambda: Capturer(WINDOW_TITLE), interval=float(CONFIG.get("interval", 0.25)), names_fn=names)

mcp = FastMCP(
    "wow-forever",
    instructions=(
        "Live link to the user's World of Warcraft Forever character (a Classic-style game). "
        "When the user asks about what is happening right now in the game, call get_live_state first; "
        "use get_recent_events to see what just happened (combat, deaths, errors), get_full_report for "
        "spellbook, bags, quests, gear, talents and past fights, get_combat_log for exact hit-by-hit detail, "
        "get_quest_guide for where to go for each quest (from Questie), "
        "and take_screenshot when you need to see the screen. Live state also includes what the Hekili addon "
        "recommends next and Deadly Boss Mods timers, when those addons are installed; action bar entries "
        "include the key to press. At the start of a conversation, read get_notes: it holds what you and the "
        "player decided in earlier chats; use save_note to remember new decisions or plans. "
        "The data is read-only: give the player advice, never suggest automating key presses (that is botting "
        "and can get the account banned). Keep in-game advice short: the player is often in the middle of a fight."
    ),
)


def _live() -> dict:
    state, at, seq_at, status = monitor.snapshot()
    if state is None:
        return {"ok": False, "problem": status}
    spells, items = names()
    out = describe(state, Names(spells, items), action_keys())
    age = time.time() - at
    frozen = time.time() - seq_at
    out["_freshness"] = {
        "read_seconds_ago": round(age, 1),
        "game_updated_seconds_ago": round(frozen, 1),
    }
    if age > 3 or frozen > 3:
        out["_freshness"]["warning"] = (
            f"Data may be old. Reader status: {status}. The game may be minimized, covered by another "
            "window, or on a loading screen."
        )
    return out


@mcp.tool()
def get_live_state() -> dict:
    """The character's state right now: health, mana/focus, target (name, level, health, who it is
    attacking, debuffs), pet (health, happiness), buffs, action bar abilities with cooldowns and whether
    each is ready / in range, current fight damage, money, bags, ammo, zone and map coordinates."""
    return _live()


@mcp.tool()
def get_recent_events(seconds: int = 120) -> list[str]:
    """What happened in the last `seconds` (default 120): entering/leaving combat with fight totals,
    deaths and who killed the player, pet death, low health or mana, new targets, level ups, zone changes,
    red game error messages such as "Out of range" or "Target too close"."""
    events = monitor.recent_events(seconds)
    return events or ["Nothing notable happened in that time."]


@mcp.tool()
def get_health_timeline(seconds: int = 60) -> list[dict]:
    """Second-by-second health %, power %, target and target health %, and pet health % for the last
    `seconds` (default 60). Useful to understand how a fight went."""
    return monitor.recent_history(seconds, step=1.0)


@mcp.tool()
def get_full_report(section: Optional[str] = None) -> dict:
    """The full report the addon saved at the last /reload, logout or /claudesync. Sections: character,
    stats, spellbook, actionBars, pet, talents, skills, gear, bags, quests, reputation, fights (last 30
    fight summaries), deaths (last 20 deaths with the hits before each), addons (installed addons), questGuide
    (Questie quest locations). Bag items include auction prices (Auctionator) and Pawn upgrade %. Pass `section`
    to get only one."""
    if WOW_DIR is None:
        return {"ok": False, "problem": "The WoW folder is not set. Run setup.ps1 again."}
    snap = store.latest()
    if snap is None:
        return {"ok": False, "problem": "No saved report yet. In the game, type /claudesync (it reloads the UI)."}
    age_min = (time.time() - (snap.get("savedAt") or 0)) / 60
    meta = {"saved_at": snap.get("savedAtText"), "minutes_ago": round(age_min)}
    if section:
        key = next((k for k in snap if k.lower() == section.lower()), None)
        if key is None:
            return {"ok": False, "problem": f"Unknown section {section!r}", "sections": sorted(snap)}
        return {"_saved": meta, key: snap[key]}
    full = {k: v for k, v in snap.items() if k not in ("spellNames", "itemNames")}
    full["_saved"] = meta
    return full


@mcp.tool()
def get_quest_guide() -> dict:
    """For each quest in the log (from the Questie addon, as of the last /reload): who gives it, where to
    turn it in, and for each objective which mob, object or item it needs and where they are (zone and
    map coordinates of the spawn area, centre of the spawn points). Combine with get_live_state's location."""
    if WOW_DIR is None:
        return {"ok": False, "problem": "The WoW folder is not set. Run setup.ps1 again."}
    snap = store.latest()
    if snap is None:
        return {"ok": False, "problem": "No saved report yet. In the game type /claudesync and then /reload."}
    guide = snap.get("questGuide")
    if not guide:
        return {"ok": False, "problem": "No Questie data in the report. Is Questie installed and enabled?",
                "quests": snap.get("quests")}
    return {"_saved": snap.get("savedAtText"), "quests": guide}


@mcp.tool()
def get_notes() -> str:
    """Notes saved in earlier conversations: plans, decisions, things the player wants remembered."""
    if not NOTES_PATH.exists():
        return "No notes yet."
    return NOTES_PATH.read_text(encoding="utf-8", errors="replace")


@mcp.tool()
def save_note(text: str) -> str:
    """Add a short note to remember in later conversations (a plan, a decision, a preference)."""
    text = " ".join(text.split())
    if not text:
        return "Empty note, nothing saved."
    with NOTES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"- {time.strftime('%Y-%m-%d %H:%M')}: {text}\n")
    return "Saved."


@mcp.tool()
def get_combat_log(seconds: int = 30, max_lines: int = 150, only_name: Optional[str] = None) -> list[str]:
    """Raw lines from the game's combat log file for the last `seconds` of logged time, with ids removed.
    Each line: time, event, source, target, spell, amounts. Use `only_name` to keep lines that mention a
    name (for example the player's or a mob's name). The game writes this file with a few seconds' delay."""
    if WOW_DIR is None:
        return ["The WoW folder is not set. Run setup.ps1 again."]
    path = newest_log(WOW_DIR)
    if path is None:
        return ["No combat log file yet. In the game type /combatlog (it turns the combat log file on)"]
    lines = recent_lines(path, seconds=seconds, max_lines=max_lines, only_name=only_name)
    return lines or ["No combat log lines in that time."]


@mcp.tool()
def take_screenshot() -> Image:
    """A picture of the game window right now (resized to 1280 pixels wide)."""
    try:
        data = Capturer(WINDOW_TITLE).screenshot_jpeg()
    except CaptureError as exc:
        raise RuntimeError(str(exc)) from exc
    return Image(data=data, format="jpeg")


@mcp.tool()
def get_link_status() -> dict:
    """Diagnostics: whether the game window and the addon strip are found, read errors, and file paths."""
    state, at, seq_at, status = monitor.snapshot()
    log = newest_log(WOW_DIR) if WOW_DIR else None
    snap = store.latest() if WOW_DIR else None
    return {
        "reader_status": status,
        "frames_read": monitor.decoded,
        "read_errors": monitor.errors,
        "strip_position": (
            None if monitor.grid is None else
            {"x": round(monitor.grid.x), "y": round(monitor.grid.y),
             "square_px": round(monitor.grid.cell_w, 2)}
        ),
        "last_read_seconds_ago": round(time.time() - at, 1) if at else None,
        "wow_dir": str(WOW_DIR) if WOW_DIR else None,
        "addon_install": ADDON_STATUS,
        "addon_version_in_game_folder": toc_version(WOW_DIR / "Interface" / "AddOns" / "ClaudeLink") if WOW_DIR else None,
        "blocked_actions": (snap or {}).get("blockedActions"),
        "saved_report": {"file": str(store.path) if store.path else None,
                         "saved_at": snap.get("savedAtText") if snap else None},
        "combat_log_file": str(log) if log else None,
    }


def main() -> None:
    monitor.start()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
