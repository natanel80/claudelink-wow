---
name: wow-live-coach
description: Live coaching while the player is in a WoW Forever fight or about to pull. Use when the player asks what to do now, what to press next, whether to pull, why an ability isn't working, or asks for help mid-fight.
---

# Live coach

The player is playing right now, often in combat. Every second you spend reading is a second they are not looking at the game.

## Steps

1. Call `get_live_state`. If it reports a problem or old data, follow the `wow-link-check` skill instead.
2. If the question is about something that just happened ("why did that fail", "what was that"), also call `get_recent_events` with `seconds: 30`.
3. Answer.

In combat WoW Forever hides exact numbers from addons: health and power then show only as percentages (measured from bars on screen), and some cooldowns, ranges or buffs can be missing. Don't treat a missing value as zero.

## How to answer

- **One to three short lines.** Lead with the action, then the reason in a few words.
- **Name the key to press** when the action bar entry has a `key` ("press `3` (Serpent Sting)"). Otherwise name the ability.
- Use the player's language. Put English game names (spells, items, mobs) in backticks.
- Base everything on the live state, not on general guides:
  - `ready: false` with a `cooldown_s` means it is not available yet: say when it will be.
  - `in_range: false` or a recent `last_error_message` like "Target too close" or "Out of range" explains failed casts.
  - `not_enough_power` means out of mana/focus/rage.
  - `target.attacking` tells you who has aggro: if it is the player and they have a pet, tell them to get the pet to taunt or back off.
  - Health below ~35% with the target still high: say so first (drink a potion, bandage, Feign Death, run).
- If `hekili_recommends` is present, it is what the Hekili addon suggests next. Agree with it unless the state clearly says otherwise (low health, wrong range, about to die).
- If `boss_timers` or `boss_warning` is present, mention the closest timer under 10 seconds.
- Before a pull: compare the target's level and type (elite, rare) with the player's level, health, mana and the pet's health, and say "go" or "wait, because ...".

## Never

- Never suggest macros or tools that press keys or play for the player (that is botting and can get the account banned).
- Don't dump the whole state back to the player.
