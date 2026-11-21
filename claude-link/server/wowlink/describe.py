"""Turn the decoded payload into a readable description for Claude."""
from __future__ import annotations

POWER = {0: "mana", 1: "rage", 2: "focus", 3: "energy", 6: "runic power"}
CLASSIFICATION = {0: "normal", 1: "elite", 2: "rare", 3: "rare elite", 4: "boss", 5: "trivial"}
HAPPINESS = {0: None, 1: "unhappy", 2: "content", 3: "happy"}
KIND = {1: "spell", 2: "item", 3: "macro (spell)", 4: "macro (item)", 5: "macro", 6: "other"}


def reaction_text(r: int) -> str | None:
    if r == 0:
        return None
    if r <= 2:
        return "hostile"
    if r == 3:
        return "unfriendly"
    if r == 4:
        return "neutral"
    return "friendly"


def money_text(copper: int) -> str:
    g, rest = divmod(copper, 10000)
    s, c = divmod(rest, 100)
    return f"{g}g {s}s {c}c"


def pct(cur: int, mx: int) -> float | None:
    return round(cur / mx * 100, 1) if mx else None


def secs(ds: int) -> float | None:
    return None if ds == 65535 else round(ds / 10, 1)


class Names:
    def __init__(self, spells: dict | None = None, items: dict | None = None):
        self.spells = {int(k): v for k, v in (spells or {}).items()}
        self.items = {int(k): v for k, v in (items or {}).items()}

    def spell(self, i: int) -> str | None:
        return self.spells.get(i) if i else None

    def item(self, i: int) -> str | None:
        return self.items.get(i) if i else None


def describe(s: dict, names: Names, keys: dict | None = None) -> dict:
    """`keys` maps action slot number -> bound key, from the saved report."""
    keys = keys or {}
    f = s["flags"]
    bars = s.get("bars") or {}
    out: dict = {}
    # In combat the game hides exact numbers from addons; the bars still show percentages.
    hidden_hp = not s["health_max"] or f.get("player_health_hidden", False)
    hidden_pw = not s["power_max"] or f.get("player_power_hidden", False)
    player = {
        "level": s["level"],
        "xp_pct": round(s["xp_permille"] / 10, 1),
        "rested_xp_pct": round(s["rested_permille"] / 10, 1),
        "health": None if hidden_hp else f'{s["health"]}/{s["health_max"]}',
        "health_pct": bars.get("player_health") if hidden_hp else pct(s["health"], s["health_max"]),
        POWER.get(s["power_type"], "power"): None if hidden_pw else f'{s["power"]}/{s["power_max"]}',
        "power_pct": bars.get("player_power") if hidden_pw else pct(s["power"], s["power_max"]),
        "in_combat": f["in_combat"],
        "dead": f["dead"], "ghost": f["ghost"],
        "resting": f["resting"], "mounted": f["mounted"], "swimming": f["swimming"],
        "on_flight_path": f["on_flight_path"], "in_group": f["in_group"],
        "auto_shot_on": f["auto_shot_on"],
    }
    if s["cast_spell_id"]:
        player["casting"] = {
            "spell": names.spell(s["cast_spell_id"]) or s["cast_spell_id"],
            "remaining_s": secs(s["cast_remaining_ds"]),
        }
    gcd = secs(s["gcd_remaining_ds"])
    if gcd:
        player["global_cooldown_s"] = gcd
    player["buffs"] = [
        {
            "name": names.spell(b["id"]) or f'spell {b["id"]}',
            "remaining_s": secs(b["remaining_ds"]),
            **({"stacks": b["stacks"]} if b["stacks"] > 1 else {}),
        }
        for b in s["buffs"]
    ]
    out["player"] = player

    out["location"] = {
        "zone": s["zone"], "sub_zone": s["sub_zone"] or None, "map_id": s["map_id"] or None,
        "coords": (f'{s["map_x"] / 100:.1f}, {s["map_y"] / 100:.1f}' if s["map_x"] or s["map_y"] else None),
    }
    out["inventory"] = {
        "money": money_text(s["money_copper"]),
        "free_bag_slots": s["free_bag_slots"],
        "ammo": s["ammo"],
        "lowest_durability_pct": None if s["lowest_durability_pct"] == 255 else s["lowest_durability_pct"],
    }

    if f["has_pet"]:
        p = s["pet"]
        out["pet"] = {
            "dead": f["pet_dead"],
            "health_pct": bars.get("pet_health") if p["health_pct"] == 255 or f.get("pet_health_hidden")
            else p["health_pct"],
            "focus_pct": None if p["power_pct"] == 255 else p["power_pct"],
            "level": p["level"] or None,
            "happiness": HAPPINESS.get(p["happiness"]),
            "in_combat": f["pet_in_combat"],
        }
    else:
        out["pet"] = None

    if f["has_target"]:
        t = s["target"]
        target = {
            "name": t["name"],
            "level": t["level"] or "?? (much higher than you)",
            "type": CLASSIFICATION.get(t["classification"], "normal"),
            "reaction": reaction_text(t["reaction"]),
            "health_pct": bars.get("target_health") if t["health_pct"] == 255 or f.get("target_health_hidden")
            else t["health_pct"],
            "dead": f["target_dead"], "is_player": f["target_is_player"],
            "attackable": f["target_attackable"],
            "tapped_by_someone_else": f["target_tapped_by_others"],
            "attacking": t["target_name"] or None,
            "attacking_me": f["target_targeting_me"], "attacking_my_pet": f["target_targeting_pet"],
        }
        if t["cast_spell_id"]:
            target["casting"] = names.spell(t["cast_spell_id"]) or t["cast_spell_id"]
        target["debuffs"] = [
            {
                "name": names.spell(d["id"]) or f'spell {d["id"]}',
                "remaining_s": secs(d["remaining_ds"]),
                "mine": d["mine"],
                **({"stacks": d["stacks"]} if d["stacks"] > 1 else {}),
            }
            for d in s["target_debuffs"]
        ]
        out["target"] = target
    else:
        out["target"] = None

    actions = []
    for a in s["actions"]:
        st = a["state"]
        if a["kind"] in (2, 4):
            name = names.item(a["id"]) or f'item {a["id"]}'
        elif a["kind"] in (1, 3):
            name = names.spell(a["id"]) or f'spell {a["id"]}'
        else:
            name = KIND[a["kind"]]
        cd = secs(a["cooldown_ds"]) or 0
        entry = {
            "slot": a["slot"], "name": name,
            **({"key": keys[a["slot"]]} if keys.get(a["slot"]) else {}),
            "ready": bool(st & 1) and cd <= (gcd or 0) + 0.05 and not (st & 4),
            "cooldown_s": cd,
        }
        if st & 2:
            entry["not_enough_power"] = True
        if st & 8:
            entry["in_range"] = not bool(st & 4)
        if st & 16:
            entry["active"] = True
        if st & 32:
            entry["auto_repeat"] = True
        actions.append(entry)
    out["action_bars"] = actions

    fight = s["fight"]
    if fight["active"] or fight["duration_ds"] or fight["damage_done"] or fight["damage_taken"]:
        dur = fight["duration_ds"] / 10
        out["fight"] = {
            "status": "in progress" if fight["active"] else "last fight (ended)",
            "duration_s": dur,
        }
        if fight["damage_done"] or fight["damage_taken"]:
            out["fight"].update({
                "damage_done": fight["damage_done"],
                "dps": round(fight["damage_done"] / dur, 1) if dur > 0 else None,
                "damage_taken": fight["damage_taken"],
                "top_damage": [
                    {"spell": names.spell(t["id"]) or f'spell {t["id"]}', "damage": t["damage"], "hits": t["hits"]}
                    for t in fight["top_spells"]
                ],
            })
        else:
            out["fight"]["damage"] = ("WoW Forever doesn't let addons read combat damage; "
                                      "use get_combat_log (the player turns it on with /combatlog)")
    if s["last_error"] and s["last_error_age_ds"] != 65535:
        out["last_error_message"] = {"text": s["last_error"], "seconds_ago": secs(s["last_error_age_ds"])}
    if s["last_killer"]:
        out["last_killed_by"] = s["last_killer"]
    if s.get("hekili"):
        out["hekili_recommends"] = [
            (names.item(h["id"]) or f'item {h["id"]}') if h["kind"] == 2 else (names.spell(h["id"]) or f'spell {h["id"]}')
            for h in s["hekili"]
        ]
    if s.get("dbm_timers"):
        out["boss_timers"] = [{"text": t["text"], "in_s": secs(t["remaining_ds"])} for t in s["dbm_timers"]]
    if s.get("dbm_alert") and s.get("dbm_alert_age_ds", 65535) != 65535:
        out["boss_warning"] = {"text": s["dbm_alert"], "seconds_ago": secs(s["dbm_alert_age_ds"])}
    if f["hidden_values"]:
        out["note"] = ("The game hides some values from addons in combat (WoW Forever rules). Health and power "
                       "percentages then come from bars measured on screen; other hidden values are missing.")
    return out
