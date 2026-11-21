"""Runs the real addon code against a fake game, draws the strip into an image,
and checks that the server decodes it. Needs `pip install lupa pillow pytest`."""
from __future__ import annotations

import base64
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server"))

lupa = pytest.importorskip("lupa")
from PIL import Image  # noqa: E402

from wowlink import protocol  # noqa: E402
from wowlink.combatlog import clean_line, recent_lines  # noqa: E402
from wowlink.describe import Names, describe  # noqa: E402
from wowlink.monitor import Monitor, diff_events  # noqa: E402
from wowlink.savedvars import SnapshotStore  # noqa: E402

ADDON = ROOT / "addon" / "ClaudeLink"
FILES = [line.strip() for line in (ADDON / "ClaudeLink.toc").read_text().splitlines()
         if line.strip().endswith(".lua")]


def load_addon():
    try:
        from lupa import luajit21 as runtime  # Lua 5.1 compatible, like WoW
    except ImportError:
        runtime = lupa
    lua = runtime.LuaRuntime(unpack_returned_tuples=True)
    lua.execute("unpack = unpack or table.unpack")
    lua.execute((Path(__file__).parent / "wow_stub.lua").read_text())
    lua.execute("ns = {}")
    for name in FILES:
        lua.execute(f'local f = assert(loadfile([[{ADDON / name}]])); f("ClaudeLink", ns)')
    g = lua.globals()
    g.FireEvent("ADDON_LOADED", "ClaudeLink")
    g.FireEvent("PLAYER_ENTERING_WORLD")
    g.FireEvent("PLAYER_REGEN_DISABLED")
    g.FireEvent("UI_ERROR_MESSAGE", 51, "Target too close")
    g.FireDBM("DBM_TimerBegin", "t1", "Cleave", 8)
    g.FireDBM("DBM_TimerBegin", "t2", "Enrage", 30)
    g.FireDBM("DBM_TimerStop", "t2")
    g.FireDBM("DBM_Announce", "Fear soon")
    return lua, g.ns


def lua_list(t) -> list[int]:
    return [int(t[i]) for i in range(1, len(t) + 1)]


BAR_FILL = {"player_health": 75, "player_power": 50, "target_health": 30, "pet_health": 25}


def render(colors, cell: float, corner: str, size=(1280, 720), seed=1, bars=BAR_FILL) -> Image.Image:
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(0, size[1], 8):  # noisy "game" background
        for x in range(0, size[0], 8):
            c = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
            for dy in range(8):
                for dx in range(8):
                    if x + dx < size[0] and y + dy < size[1]:
                        px[x + dx, y + dy] = c
    w, h = protocol.COLS * cell, protocol.TOTAL_ROWS * cell
    ox = 0 if "LEFT" in corner else size[0] - w
    oy = 0 if "TOP" in corner else size[1] - h
    for i in range(protocol.COLS * protocol.ROWS):
        c = colors[i]
        rgb = (int(c[1]), int(c[2]), int(c[3]))
        col, row = i % protocol.COLS, i // protocol.COLS
        x0, x1 = round(ox + col * cell), round(ox + (col + 1) * cell)
        y0, y1 = round(oy + row * cell), round(oy + (row + 1) * cell)
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = rgb
    for x in range(round(ox), round(ox + w)):  # black area under the squares, like the addon's background
        for y in range(round(oy + protocol.ROWS * cell), round(oy + h)):
            px[x, y] = (0, 0, 0)
    for i, name in enumerate(protocol.BARS):  # magenta cap, then a white fill
        y0, y1 = round(oy + (protocol.ROWS + 1 + 2 * i) * cell), round(oy + (protocol.ROWS + 2 + 2 * i) * cell)
        for y in range(y0, y1):
            for x in range(round(ox), round(ox + cell)):
                px[x, y] = protocol.BAR_CAP
            fill = bars[name] / 100 * protocol.BAR_CELLS * cell
            for x in range(round(ox + cell), round(ox + cell + fill)):
                px[x, y] = (255, 255, 255)
    return img


@pytest.fixture(scope="module")
def addon():
    return load_addon()


@pytest.mark.parametrize("cell,corner", [(3, "TOPLEFT"), (2, "TOPRIGHT"), (3.5, "BOTTOMLEFT"), (4, "BOTTOMRIGHT")])
def test_strip_round_trip(addon, cell, corner):
    lua, ns = addon
    payload = ns.buildLive()
    assert len(payload) <= protocol.MAX_PAYLOAD
    colors = ns.encodeCells(payload, 7)
    src = protocol.PixelSource.from_pil(render(colors, cell, corner))
    grid = protocol.find_grid(src)
    assert grid is not None
    frame = protocol.read_frame(src, grid)
    assert frame.seq == 7
    assert list(frame.payload) == lua_list(payload)

    s = protocol.parse_payload(frame.payload)
    assert s["level"] == 11 and s["health"] == 180 and s["health_max"] == 240
    assert s["money_copper"] == 123456 and s["ammo"] == 812 and s["free_bag_slots"] == 8
    assert s["lowest_durability_pct"] == 50
    assert s["map_id"] == 1436 and s["map_x"] == 4567
    assert s["flags"]["in_combat"] and s["flags"]["has_pet"] and s["flags"]["target_targeting_pet"]
    assert s["target"]["name"] == "Defias Bandit" and s["target"]["health_pct"] == 30
    assert s["target"]["target_name"] == "Fleshripper"
    assert s["pet"]["happiness"] == 3 and s["pet"]["health_pct"] == 25
    assert s["fight"]["active"] and s["fight"]["damage_done"] == 0  # no combat log in WoW Forever
    bars = protocol.read_bars(src, grid)
    for name, want in BAR_FILL.items():
        assert abs(bars[name] - want) <= 3, (name, bars[name])
    assert s["last_error"] == "Target too close"

    d = describe(s, Names({75: "Auto Shot", 3044: "Arcane Shot", 1978: "Serpent Sting", 1130: "Hunter's Mark",
                           13165: "Aspect of the Hawk"}, {159: "Refreshing Spring Water"}))
    by_name = {a["name"]: a for a in d["action_bars"]}
    assert by_name["Arcane Shot"]["cooldown_s"] == 4.0 and not by_name["Arcane Shot"]["ready"]
    assert by_name["Hunter's Mark"]["ready"]
    assert by_name["Refreshing Spring Water"]["slot"] == 5
    assert d["target"]["debuffs"][0]["name"] == "Serpent Sting" and d["target"]["debuffs"][0]["mine"]
    assert d["player"]["buffs"][0]["name"] == "Aspect of the Hawk"
    assert "get_combat_log" in d["fight"]["damage"]
    assert d["inventory"]["money"] == "12g 34s 56c"
    json.dumps(d)


def test_checksum_catches_bad_colors(addon):
    lua, ns = addon
    colors = ns.encodeCells(ns.buildLive(), 1)
    img = render(colors, 3, "TOPLEFT")
    img.putpixel((3 * 10 + 1, 1), (1, 2, 3))  # change one data square
    src = protocol.PixelSource.from_pil(img)
    with pytest.raises(protocol.DecodeError):
        protocol.read_frame(src, protocol.find_grid(src))


def test_snapshot_and_savedvariables(addon, tmp_path):
    lua, ns = addon
    snap_json = ns.toJSON(ns.buildSnapshot("test"))
    snap = json.loads(snap_json)
    assert snap["character"]["name"] == "Testhunter"
    assert snap["character"]["class"] == "Hunter"
    assert any(a.get("name") == "Arcane Shot" for a in snap["actionBars"])
    b64 = ns.base64(snap_json)
    assert base64.b64decode(b64).decode() == snap_json

    ns.saveSnapshot("test")
    sv = tmp_path / "WTF" / "Account" / "123#1" / "SavedVariables"
    sv.mkdir(parents=True)
    db = lua.globals().ClaudeLinkDB
    char = db.chars["Testhunter - Forever"]
    (sv / "ClaudeLink.lua").write_text(
        'ClaudeLinkDB = {\n["chars"] = {\n["Testhunter - Forever"] = {\n'
        f'["snapshotB64"] = "{char.snapshotB64}",\n["savedAt"] = {char.savedAt},\n'
        '},\n},\n}\n'
    )
    store = SnapshotStore(tmp_path)
    latest = store.latest()
    assert latest["character"]["level"] == 11
    spells, _ = store.names()
    assert Names(spells).spell(3044) == "Arcane Shot"


def test_events_from_state_changes(addon):
    lua, ns = addon
    s1 = protocol.parse_payload(bytes(lua_list(ns.buildLive())))
    g = lua.globals()
    lua.execute('UnitAffectingCombat = function() return false end')
    g.FireEvent("PLAYER_REGEN_ENABLED")
    s2 = protocol.parse_payload(bytes(lua_list(ns.buildLive())))
    events = diff_events(s1, s2, ({}, {}))
    assert any(e.startswith("Left combat") for e in events)

    m = Monitor(lambda: None)
    m.ingest(1, s1)
    m.ingest(2, s2)
    assert any("Left combat" in e for e in m.recent_events(60))
    assert len(m.recent_history(60, step=0)) == 2


def test_combat_log_lines(tmp_path):
    logs = tmp_path / "Logs"
    logs.mkdir()
    lines = [
        '11/21 20:15:01.100  SPELL_DAMAGE,Player-1-0001,"Testhunter",0x511,0x0,Creature-0-1-2-3-116-0000,'
        '"Defias Bandit",0x10a48,0x0,3044,"Arcane Shot",0x40,45,0,64,0,0,0,1,nil,nil',
        '11/21 20:15:40.000  SWING_DAMAGE,Creature-0-1-2-3-116-0000,"Defias Bandit",0x10a48,0x0,'
        'Player-1-0001,"Testhunter",0x511,0x0,15,0,1,0,0,0,nil,nil,nil',
    ]
    (logs / "WoWCombatLog.txt").write_text("\n".join(lines) + "\n")
    assert clean_line(lines[0]).startswith("20:15:01.1 SPELL_DAMAGE,Testhunter,Defias Bandit,3044,Arcane Shot")
    recent = recent_lines(logs / "WoWCombatLog.txt", seconds=10)
    assert len(recent) == 1 and "SWING_DAMAGE" in recent[0]


def test_other_addons(addon):
    lua, ns = addon
    s = protocol.parse_payload(bytes(lua_list(ns.buildLive())))
    assert [h["id"] for h in s["hekili"]] == [3044, 1978, 159] and s["hekili"][2]["kind"] == 2
    assert [t["text"] for t in s["dbm_timers"]] == ["Cleave"] and s["dbm_timers"][0]["remaining_ds"] == 80
    assert s["dbm_alert"] == "Fear soon"

    snap = json.loads(ns.toJSON(ns.buildSnapshot("test")))
    assert {a["name"] for a in snap["addons"]} == {"Bartender4", "Questie"}
    assert snap["addons"][0].get("title") is None  # color codes stripped, same as name
    keys = {a["slot"]: a.get("key") for a in snap["actionBars"]}
    assert keys[2] == "2" and keys[1] == "1"
    water = snap["bags"]["items"][0]
    assert water["auctionPrice"] == 25 and water["auctionPriceAgeDays"] == 2
    guide = snap["questGuide"][0]
    assert guide["title"] == "The Defias Brotherhood"
    assert guide["turnIn"]["name"] == "Gryan Stoutmantle"
    assert guide["turnIn"]["where"][0] == {"zone": "Westfall", "x": 56.3, "y": 47.5, "spawnPoints": 1}
    bandit = guide["objectives"][0]["target"]
    assert bandit["where"][0]["x"] == 51 and bandit["where"][0]["spawnPoints"] == 2
    assert guide["objectives"][1]["from"][0]["name"] == "Defias Bandit"

    names = Names({3044: "Arcane Shot", 1978: "Serpent Sting"}, {159: "Refreshing Spring Water"})
    d = describe(s, names, {2: "2", 1: "1"})
    assert d["hekili_recommends"] == ["Arcane Shot", "Serpent Sting", "Refreshing Spring Water"]
    assert d["boss_timers"] == [{"text": "Cleave", "in_s": 8.0}]
    assert d["boss_warning"]["text"] == "Fear soon"
    assert next(a for a in d["action_bars"] if a["slot"] == 2)["key"] == "2"


def test_never_listens_to_the_combat_log(addon):
    lua, ns = addon
    registered = lua.eval("""function()
        local found = false
        for _, f in ipairs(AllFrames()) do
            if f._events.COMBAT_LOG_EVENT_UNFILTERED then found = true end
        end
        return found
    end""")()
    assert registered is False


def test_hidden_values_in_combat(addon):
    """WoW Forever hides health and power in combat. The payload still builds,
    and the server falls back to the bars."""
    lua, ns = addon
    lua.execute("""
        SECRET = setmetatable({}, { __lt = function() error("secret") end, __le = function() error("secret") end,
                                    __add = function() error("secret") end, __concat = function() error("secret") end })
        issecretvalue = function(v) return v == SECRET end
        _real = { UnitHealth, UnitHealthMax, UnitAura, IsActionInRange }
        UnitHealth = function() return SECRET end
        UnitHealthMax = function() return SECRET end
        UnitAura = function() return SECRET, nil, SECRET, nil, 0, SECRET, SECRET, nil, nil, SECRET end
        IsActionInRange = function() return SECRET end
    """)
    try:
        s = protocol.parse_payload(bytes(lua_list(ns.buildLive())))
        assert s["health_max"] == 0 and s["flags"]["hidden_values"]
        assert s["target"]["health_pct"] == 255 and s["buffs"] == []
        assert len(s["actions"]) == 5
        ns.updateBars()  # passing hidden values to the bars must not fail
        s["bars"] = dict(BAR_FILL)
        d = describe(s, Names())
        assert d["player"]["health_pct"] == 75 and d["player"]["health"] is None
        assert d["target"]["health_pct"] == 30 and d["pet"]["health_pct"] == 25
    finally:
        lua.execute("""UnitHealth, UnitHealthMax, UnitAura, IsActionInRange = _real[1], _real[2], _real[3], _real[4]
                       issecretvalue = nil; ns.secretSeen = nil""")


def test_hidden_current_value_with_visible_maximum(addon):
    """Seen in WoW Forever out of combat: UnitHealth is hidden but UnitHealthMax is not.
    The server must use the bar, not report 0 health."""
    lua, ns = addon
    lua.execute("""
        SECRET2 = setmetatable({}, { __lt = function() error("secret") end, __add = function() error("secret") end })
        issecretvalue = function(v) return v == SECRET2 end
        _real2 = { UnitHealth, UnitPower }
        UnitHealth = function(u) if u == "player" then return SECRET2 end return _real2[1](u) end
        UnitPower = function() return SECRET2 end
    """)
    try:
        s = protocol.parse_payload(bytes(lua_list(ns.buildLive())))
        f = s["flags"]
        assert s["health"] == 0 and s["health_max"] == 240
        assert f["player_health_hidden"] and f["player_power_hidden"] and f["hidden_values"]
        assert not f["target_health_hidden"] and not f["pet_health_hidden"]
        s["bars"] = dict(BAR_FILL)
        d = describe(s, Names())
        assert d["player"]["health_pct"] == 75 and d["player"]["health"] is None
        assert d["player"]["power_pct"] == 50
    finally:
        lua.execute("UnitHealth, UnitPower = _real2[1], _real2[2]; issecretvalue = nil; ns.secretSeen = nil")
