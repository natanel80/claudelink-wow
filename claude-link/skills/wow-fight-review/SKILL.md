---
name: wow-fight-review
description: Review a WoW Forever fight or death after it happened. Use when the player asks why they died, how a fight went, how to do more damage, or how to improve their rotation.
---

# Fight and death review

## Gather (in this order, stop when you have enough)

1. `get_recent_events` with `seconds: 300`: entered/left combat, fight totals, deaths and the killer, errors.
2. `get_health_timeline` with `seconds: 60` (or longer) for how health, power and the target's health moved.
3. `get_live_state`: the last fight's length and the current action bars.
4. **Damage numbers come only from `get_combat_log`.** WoW Forever doesn't let addons read combat damage, so the live state has no damage totals. Call `get_combat_log` with `seconds` covering the fight and `only_name` set to the player's or the mob's name, and add up the amounts yourself. If it is empty, tell the player to type `/combatlog` once in the game.
5. For a death: `get_full_report` with `section: "deaths"` (time, zone, level, probable killer). For past fights: `section: "fights"`.

## What to look for

- **Deaths:** what did most of the damage in the last 10 seconds? Was health already low before the pull? Were there several mobs (more than one source)? Did the pet die first? Was there a big hit (crit, special attack)?
- **Damage:** which abilities did most damage (top_damage), and what is missing? An ability on the bars that never appears in the fight was not used. Long fights with low DPS often mean auto attacks only.
- **Errors:** repeated "Out of range", "Target too close", "Not enough mana" show a positioning or resource problem.
- **Pet:** pet health, whether it had aggro, whether the pet died.

## Answer

- Start with the one main reason, in one sentence.
- Then at most three concrete fixes, each tied to what you saw ("you cast `Arcane Shot` once in 40 seconds; press it whenever it is ready").
- Use the player's language and put English game names in backticks.
- If something the player could keep in mind next time came up, offer to save it with `save_note`.
