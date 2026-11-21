---
name: wow-link-check
description: Check and fix the live link to WoW Forever. Use when the player asks to check the connection, when a wow-forever tool reports a problem or old data, or when the game data looks wrong or missing.
---

# Link check

1. Call `get_link_status`.
2. Match what you see and give the player the one fix that applies:

| What you see | What to tell the player |
|---|---|
| `reader_status` says the window was not found | Start WoW Forever, or wait until it is past the loading screen. |
| `reader_status` says the window is minimized | Restore the game window. "Windowed (Fullscreen)" mode works best. |
| `reader_status` says the strip was not found | In the game type `/claudelink status`. If the strip is off: `/claudelink show`. If a window covers the top-left corner of the game, move it, or move the strip with `/claudelink corner tr` (top-right). Make sure ClaudeLink is enabled in the AddOns list on the character screen. |
| `read error: checksum mismatch` or many `read_errors` | Something changes the screen colors: turn off color filters, HDR, ReShade or night light for the game, or make the squares bigger with `/claudelink size 4`. |
| `read error: unknown protocol version` | The addon and the plugin are different versions. Restart the Claude app (it updates the addon), then `/reload` in the game. |
| `addon_install` says it could not copy | The plugin couldn't write to the AddOns folder. Copy the `addon/ClaudeLink` folder from the plugin into `_forever_\Interface\AddOns` by hand, or fix the WoW folder setting of the plugin. |
| `wow_dir` is empty or wrong | Set the WoW Forever folder (the `_forever_` folder) in the plugin's settings. |
| `saved_report.saved_at` is empty or old | In the game: `/claudesync`, then `/reload`. |
| `blocked_actions` lists entries, or the player sees "ClaudeLink has been blocked from an action only available to the Blizzard UI" | Tell the player to click **Ignore** (not Disable). Report the blocked function name (`fn`) and version to the developer: ClaudeLink should not call that function. If `addon_version_in_game_folder` is older than the plugin, restart the Claude app so it copies the new addon, then `/reload` in the game. |
| `combat_log_file` is empty | In the game type `/combatlog` (the game's own command; it toggles, so the chat says whether logging is now on). |

3. If `reader_status` is `ok` and `last_read_seconds_ago` is under 2, the link works: say so in one line, with the character's level and zone from `get_live_state` as proof.
