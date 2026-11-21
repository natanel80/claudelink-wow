-- ClaudeLink: slash commands.
local ADDON, ns = ...

local function say(msg)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffd97706ClaudeLink|r: " .. msg) end
end

local CORNERS = { tl = "TOPLEFT", tr = "TOPRIGHT", bl = "BOTTOMLEFT", br = "BOTTOMRIGHT" }

local function help()
    say("/claudelink status - show whether the link works")
    say("/claudelink show | hide - turn the corner strip on or off")
    say("/claudelink corner tl|tr|bl|br - move the strip to another corner")
    say("/claudelink size 2-6 - size of each square in pixels (default 3)")
    say("/combatlog - turn the game's combat log file on or off (a game command; addons are not allowed to do it)")
    say("/claudesync - save the full report now (reloads the UI)")
end

SLASH_CLAUDELINK1 = "/claudelink"
SlashCmdList.CLAUDELINK = function(msg)
    local cmd, arg = (msg or ""):lower():match("^%s*(%S*)%s*(.-)%s*$")
    local db = ClaudeLinkDB
    if cmd == "" or cmd == "help" then
        help()
    elseif cmd == "status" then
        say(("version %s, strip %s, corner %s, square %dpx, payload %s of %d bytes"):format(
            ns.VERSION, db.enabled and "on" or "off", db.corner, db.cell,
            tostring(ns.lastPayloadSize or "?"), ns.MAX_PAYLOAD))
        if ns.lastBuildError then say("last error: " .. ns.lastBuildError) end
        if ns.secretSeen then say("note: the game hid some values from addons") end
        local blocked = db.blocked and db.blocked[#db.blocked]
        if blocked then say(("last blocked action: %s at %s (version %s)"):format(blocked.fn, blocked.at or "?", blocked.version or "?")) end
        local c = ns.charDB()
        say(("full report saved: %s"):format(c.savedAt and date("%Y-%m-%d %H:%M", c.savedAt) or "never (use /claudesync)"))
    elseif cmd == "show" or cmd == "hide" then
        db.enabled = cmd == "show"
        ns.applyLayout()
        say("strip " .. (db.enabled and "on" or "off"))
    elseif cmd == "corner" and CORNERS[arg] then
        db.corner = CORNERS[arg]
        ns.applyLayout()
        say("strip moved to " .. db.corner)
    elseif cmd == "size" and tonumber(arg) and tonumber(arg) >= 2 and tonumber(arg) <= 6 then
        db.cell = math.floor(tonumber(arg))
        ns.applyLayout()
        say("square size " .. db.cell .. "px")
    elseif cmd == "combatlog" then
        -- WoW Forever blocks addons from calling LoggingCombat, so the player uses the game's own command.
        say("type /combatlog to turn the combat log file on or off")
    else
        help()
    end
end

SLASH_CLAUDESYNC1 = "/claudesync"
-- WoW Forever blocks addons from reloading the UI themselves, so the player types /reload.
-- The report is rebuilt and written to disk automatically during the reload.
SlashCmdList.CLAUDESYNC = function()
    local ok = ns.saveSnapshot("claudesync")
    say(ok and "report prepared. Now type /reload to save it to disk." or "could not build the report (see /claudelink status).")
end
