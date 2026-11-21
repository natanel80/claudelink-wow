---
name: wow-quest-route
description: Plan where to go next for quests in WoW Forever. Use when the player asks where to go, which quest to do next, where a quest mob or item is, or where to turn in a quest.
---

# Quest route

## Gather

1. `get_live_state`: current zone, coordinates (`location.coords` as "x, y"), level, free bag slots.
2. `get_quest_guide`: for each quest in the log, who gives it, where to turn it in, and for each objective the mob, object or item, with spawn areas (zone, x, y as map coordinates 0-100, number of spawn points). It comes from the Questie addon as of the last `/reload`.
   - If it says there is no report or no Questie data, tell the player to type `/claudesync` and then `/reload` in the game, and check that Questie is enabled.
3. If you need objective progress (for example 4/10 killed), `get_full_report` with `section: "quests"`.

## Plan

- Group work by zone. In the player's current zone, order stops by distance from the player's coordinates (straight-line distance on the 0-100 map is fine).
- Put quests that are already `complete` on the route to their turn-in NPC.
- Prefer objectives near each other that can be done together (kill mobs for two quests in one area).
- Warn about quests far above the player's level (more than 3 levels), and about elite quests that need a group.
- If bags are nearly full, plan a vendor stop first.

## Answer

- A short numbered route: "1. `Defias Bandit` at 51, 61 (Moonbrook), for `The Defias Brotherhood`. 2. ...", ending with where to turn in.
- Coordinates as "x, y" with the zone name.
- Use the player's language; English names in backticks.
