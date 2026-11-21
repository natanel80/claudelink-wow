---
name: wow-level-up
description: Help with a new level in WoW Forever: which spells to train, where to put talent points, gear, and what to do next. Use when the player levels up, visits a trainer, asks about talents, or asks how to get stronger.
---

# Level up

## Gather

1. `get_live_state`: level, money.
2. `get_full_report` with `section: "character"`, then `"spellbook"`, `"talents"` (including `unspent` points), `"gear"` and `"pet"` as needed.
3. `get_notes`: the plan and choices made earlier (talent build, spec, profession plans).

## Advise

- **Trainer:** which new ranks or spells are worth the money at this level, given the player's gold. Say which can wait.
- **Talents:** where to put the unspent points, following the build in the notes if there is one. If there is none, suggest a common leveling build for the class and spec, and offer to save it with `save_note`.
- **Gear:** weak slots (low item level, missing items, low durability). Look at the bags (`get_full_report` section `bags`, `pawnUpgradePercent`) for upgrades already owned.
- **Pet (hunters, warlocks):** pet level compared to the player, happiness, new pet abilities to train.
- **Action bars:** if a newly learned spell is not on the bars (`actionBars`), tell the player to drag it there.

## Answer

- A short checklist in order: train, talents, equip, bars.
- Use the player's language; English names in backticks.
- Save important decisions (talent build, chosen spec) with `save_note`.
