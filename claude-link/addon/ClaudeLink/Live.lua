-- ClaudeLink: live state. Several times a second, the character's state is packed
-- into bytes and drawn as a small strip of colored squares in a corner of the
-- screen. The ClaudeLink server on the PC reads those colors back. The addon
-- only reads game information; it never presses keys or acts for the player.
local ADDON, ns = ...

local floor, max, min = math.floor, math.max, math.min
local safe, num, str, truthy = ns.safe, ns.num, ns.str, ns.truthy

---------------------------------------------------------------------------
-- Pixel strip layout (must match server/wowlink/protocol.py)
---------------------------------------------------------------------------
local PROTO = 2
local COLS, ROWS = 48, 8
local MARKERS = {
    [0] = { 0x57, 0x46, 0x4C },                 -- start (top-left)
    [COLS - 1] = { 0x4C, 0x46, 0x57 },          -- end of first row
    [(ROWS - 1) * COLS] = { 0x42, 0x54, 0x4D }, -- start of last row
}
local DATA = {}
for i = 0, COLS * ROWS - 1 do
    if not MARKERS[i] then DATA[#DATA + 1] = i end
end
ns.COLS, ns.ROWS, ns.PROTO = COLS, ROWS, PROTO
ns.MAX_PAYLOAD = (#DATA - 2) * 3

-- Returns a table: cell index (0-based) -> { r, g, b } with values 0-255.
function ns.encodeCells(payload, seq)
    local len = min(#payload, ns.MAX_PAYLOAD)
    local s1, s2 = 0, 0
    for i = 1, len do
        s1 = (s1 + payload[i]) % 255
        s2 = (s2 + s1) % 255
    end
    local colors = {}
    for i, c in pairs(MARKERS) do colors[i] = c end
    colors[DATA[1]] = { PROTO, floor(len / 256), len % 256 }
    colors[DATA[2]] = { seq % 256, s2, s1 }
    local p = 1
    for k = 3, #DATA do
        local r = p <= len and payload[p] or 0
        local g = p + 1 <= len and payload[p + 1] or 0
        local b = p + 2 <= len and payload[p + 2] or 0
        colors[DATA[k]] = { r, g, b }
        p = p + 3
    end
    return colors
end

---------------------------------------------------------------------------
-- Combat tracking (fight start/end, deaths)
---------------------------------------------------------------------------
ns.fight = nil        -- current fight, or the last one after it ended
ns.recentHits = {}    -- last hits the player took, for "what killed me"
ns.lastError = nil    -- last red error text, e.g. "Out of range."
ns.lastErrorAt = 0

local MELEE_ID, PET_MELEE_ID = 1, 2
ns.spellNames[MELEE_ID] = "Melee"
ns.spellNames[PET_MELEE_ID] = "Pet melee"

function ns.charDB()
    ClaudeLinkDB = ClaudeLinkDB or {}
    ClaudeLinkDB.chars = ClaudeLinkDB.chars or {}
    local name = str(safe(UnitName, "player")) or "?"
    local realm = str(safe(GetRealmName)) or "?"
    local key = name .. " - " .. realm
    local c = ClaudeLinkDB.chars[key]
    if not c then
        c = { fights = {}, deaths = {} }
        ClaudeLinkDB.chars[key] = c
    end
    c.fights = c.fights or {}
    c.deaths = c.deaths or {}
    return c, key
end

local function newFight()
    ns.fight = { start = ns.now(), done = 0, taken = 0, spells = {}, kills = {}, targets = {} }
    return ns.fight
end

local function pushLimited(list, item, limit)
    list[#list + 1] = item
    while #list > limit do table.remove(list, 1) end
end

function ns.topSpells(fight, limit)
    local list = {}
    for id, s in pairs(fight.spells) do
        list[#list + 1] = { id = id, name = ns.spellNames[id], damage = s.damage, hits = s.hits, crits = s.crits }
    end
    table.sort(list, function(a, b) return a.damage > b.damage end)
    while #list > limit do table.remove(list) end
    return list
end

local function archiveFight(f)
    if not f or f.archived then return end
    f.archived = true
    local duration = max(0, (f.stop or ns.now()) - f.start)
    if duration < 1 and f.done == 0 then return end
    local kills, targets = {}, {}
    for name, n in pairs(f.kills) do kills[#kills + 1] = { name = name, count = n } end
    for name in pairs(f.targets) do targets[#targets + 1] = name end
    local c = ns.charDB()
    pushLimited(c.fights, {
        endedAt = safe(date, "%Y-%m-%d %H:%M:%S"),
        duration = floor(duration * 10) / 10,
        damageDone = f.done,
        damageTaken = f.taken,
        dps = duration > 0 and floor(f.done / duration * 10) / 10 or 0,
        topSpells = ns.topSpells(f, 8),
        kills = kills,
        targets = targets,
        zone = str(safe(GetZoneText)),
    }, 30)
end

-- WoW Forever does not let addons listen to the combat log (COMBAT_LOG_EVENT_UNFILTERED):
-- registering it shows "blocked from an action only available to the Blizzard UI".
-- Damage per fight comes from the game's own combat log file instead (/combatlog).

function ns.onPlayerDied()
    local now = ns.now()
    local hits = {}
    for _, h in ipairs(ns.recentHits) do
        hits[#hits + 1] = {
            secondsBeforeDeath = floor((now - h.t) * 10) / 10,
            source = h.source, spell = h.spell, amount = h.amount, crit = h.crit,
        }
    end
    local last = ns.recentHits[#ns.recentHits]
    ns.lastKiller = last and (last.source .. " (" .. last.spell .. ")") or nil
    if not ns.lastKiller and truthy(safe(UnitExists, "target")) and truthy(safe(UnitIsUnit, "targettarget", "player")) then
        ns.lastKiller = str(safe(UnitName, "target"))
    end
    local c = ns.charDB()
    pushLimited(c.deaths, {
        at = safe(date, "%Y-%m-%d %H:%M:%S"),
        zone = str(safe(GetZoneText)),
        subZone = str(safe(GetSubZoneText)),
        level = num(safe(UnitLevel, "player")),
        killer = ns.lastKiller,
        lastHits = hits,
    }, 20)
end

---------------------------------------------------------------------------
-- Reading the game state
---------------------------------------------------------------------------
local function pct(cur, maxv)
    cur, maxv = num(cur), num(maxv)
    if not cur or not maxv or maxv <= 0 then return 255 end
    return floor(cur / maxv * 100 + 0.5)
end

local function cooldown(tableFn, globalFn, arg)
    if tableFn then
        local r = safe(tableFn, arg)
        if type(r) == "table" then return num(r.startTime, 0), num(r.duration, 0) end
    end
    if globalFn then
        local s, d = safe(globalFn, arg)
        return num(s, 0), num(d, 0)
    end
    return 0, 0
end

local function remaining(start, duration, now)
    if start > 0 and duration > 0 then return max(0, start + duration - now) end
    return 0
end

local function getAura(unit, i, filter)
    if C_UnitAuras and C_UnitAuras.GetAuraDataByIndex then
        local a = safe(C_UnitAuras.GetAuraDataByIndex, unit, i, filter)
        if type(a) == "table" then
            return a.spellId, a.expirationTime, a.applications, a.sourceUnit, a.name
        end
        if not UnitAura then return nil end
    end
    if UnitAura then
        local name, _, count, _, _, expirationTime, source, _, _, spellId = safe(UnitAura, unit, i, filter)
        if name then return spellId, expirationTime, count, source, name end
    end
    return nil
end

local function readAuras(unit, filter, limit, now)
    local list = {}
    for i = 1, 40 do
        -- In combat aura data can be hidden; touching it the wrong way raises an error,
        -- so each aura is read inside pcall and reading stops at the first problem.
        local ok, entry, done = pcall(function()
            local id, expires, stacks, source, name = getAura(unit, i, filter)
            id, name, source = num(id), str(name), str(source)
            if not id and not name then return nil, true end
            ns.rememberSpell(id, name)
            expires = num(expires, 0)
            return {
                id = id or 0,
                remaining = expires > 0 and max(0, expires - now) or nil,
                stacks = num(stacks, 0),
                mine = (source == "player" or source == "pet"),
            }, false
        end)
        if not ok or done or not entry then break end
        list[#list + 1] = entry
        if #list >= limit then break end
    end
    return list
end

local function itemIdFromLink(link)
    link = str(link)
    return link and tonumber(link:match("item:(%d+)")) or nil
end

local ACTION_SLOTS = {}
for s = 1, 72 do ACTION_SLOTS[#ACTION_SLOTS + 1] = s end

-- kind: 1 spell, 2 item, 3 macro casting a spell, 4 macro using an item, 5 other macro, 6 other
local function readAction(slot, now)
    if not truthy(safe(HasAction, slot)) then return nil end
    local aType, id = safe(GetActionInfo, slot)
    aType = str(aType)
    local kind, outId = 6, 0
    if aType == "spell" then
        kind, outId = 1, num(id, 0)
        ns.spellName(outId)
    elseif aType == "item" then
        kind, outId = 2, num(id, 0)
        ns.itemName(outId)
    elseif aType == "macro" then
        local spellId = num(safe(GetMacroSpell, id))
        if spellId then
            kind, outId = 3, spellId
            ns.spellName(outId)
        else
            local _, link = safe(GetMacroItem, id)
            local itemId = itemIdFromLink(link)
            if itemId then
                kind, outId = 4, itemId
                ns.itemName(outId)
            else
                kind, outId = 5, num(id, 0)
            end
        end
    end
    local usable, noMana = safe(IsUsableAction, slot)
    local inRange = safe(IsActionInRange, slot)
    if ns.isSecret(inRange) then inRange = nil end
    local start, duration = cooldown(C_ActionBar and C_ActionBar.GetActionCooldown, GetActionCooldown, slot)
    local cd = remaining(start, duration, now)
    local state = 0
    if truthy(usable) then state = state + 1 end
    if truthy(noMana) then state = state + 2 end
    if inRange == false or inRange == 0 then state = state + 4 end
    if inRange ~= nil and not ns.isSecret(inRange) then state = state + 8 end
    if truthy(safe(IsCurrentAction, slot)) then state = state + 16 end
    if truthy(safe(IsAutoRepeatAction, slot)) then state = state + 32 end
    if cd > 0 then state = state + 64 end
    return { slot = slot, kind = kind, id = outId, state = state, cd = cd }
end

local function freeBagSlots()
    local total = 0
    for bag = 0, 4 do
        local free, bagType
        if C_Container and C_Container.GetContainerNumFreeSlots then
            free, bagType = safe(C_Container.GetContainerNumFreeSlots, bag)
        else
            free, bagType = safe(GetContainerNumFreeSlots, bag)
        end
        if num(free) and num(bagType, 0) == 0 then total = total + free end
    end
    return total
end

local function minDurability()
    local lowest
    for slot = 1, 18 do
        local cur, maxv = safe(GetInventoryItemDurability, slot)
        cur, maxv = num(cur), num(maxv)
        if cur and maxv and maxv > 0 then
            local p = cur / maxv * 100
            if not lowest or p < lowest then lowest = p end
        end
    end
    return lowest and floor(lowest) or 255
end

local function mapPosition()
    if not C_Map then return 0, 0, 0 end
    local mapID = num(safe(C_Map.GetBestMapForUnit, "player"))
    if not mapID then return 0, 0, 0 end
    local pos = safe(C_Map.GetPlayerMapPosition, mapID, "player")
    if not pos then return mapID, 0, 0 end
    local x, y = safe(pos.GetXY, pos)
    return mapID, floor((num(x, 0)) * 10000), floor((num(y, 0)) * 10000)
end

local function castInfo(unit, now)
    local spellId, endMS = select(9, safe(UnitCastingInfo, unit)), select(5, safe(UnitCastingInfo, unit))
    if not num(spellId) then
        spellId = select(8, safe(UnitChannelInfo, unit))
        endMS = select(5, safe(UnitChannelInfo, unit))
    end
    spellId = num(spellId)
    if not spellId then return 0, 0 end
    ns.spellName(spellId)
    local rem = num(endMS) and max(0, endMS / 1000 - now) or 0
    return spellId, rem
end

local CLASSIFICATION = { normal = 0, elite = 1, rare = 2, rareelite = 3, worldboss = 4, trivial = 5, minus = 5 }

local function flag(bits, n, v) if v then return bits + 2 ^ n end return bits end

---------------------------------------------------------------------------
-- Build the payload (order and sizes must match server/wowlink/protocol.py)
---------------------------------------------------------------------------
function ns.buildLive()
    local w = ns.newWriter()
    local now = ns.now()
    ns.secretSeen = false -- set again by ns.isSecret if this frame meets a hidden value
    local hasTarget = truthy(safe(UnitExists, "target"))
    local hasPet = truthy(safe(UnitExists, "pet"))

    -- flags
    local f = 0
    f = flag(f, 0, truthy(safe(UnitAffectingCombat, "player")))
    f = flag(f, 1, truthy(safe(UnitIsDead, "player")))
    f = flag(f, 2, truthy(safe(UnitIsGhost, "player")))
    f = flag(f, 3, truthy(safe(IsResting)))
    f = flag(f, 4, truthy(safe(IsMounted)))
    f = flag(f, 5, hasPet)
    f = flag(f, 6, hasPet and truthy(safe(UnitIsDead, "pet")))
    f = flag(f, 7, hasTarget)
    f = flag(f, 8, hasTarget and truthy(safe(UnitIsDead, "target")))
    f = flag(f, 9, hasTarget and truthy(safe(UnitIsPlayer, "target")))
    f = flag(f, 10, hasTarget and truthy(safe(UnitCanAttack, "player", "target")))
    f = flag(f, 11, hasTarget and truthy(safe(UnitIsFriend, "player", "target")))
    f = flag(f, 12, hasTarget and truthy(safe(UnitIsUnit, "targettarget", "player")))
    f = flag(f, 13, hasTarget and hasPet and truthy(safe(UnitIsUnit, "targettarget", "pet")))
    f = flag(f, 14, truthy(safe(IsAutoRepeatSpell, "Auto Shot")) or ns.autoRepeating == true)
    f = flag(f, 15, hasPet and truthy(safe(UnitAffectingCombat, "pet")))
    f = flag(f, 16, truthy(safe(IsInGroup)))
    f = flag(f, 18, hasTarget and truthy(safe(UnitIsTapDenied, "target")))
    f = flag(f, 19, truthy(safe(IsSwimming)))
    f = flag(f, 20, truthy(safe(UnitOnTaxi, "player")))
    w:u32(f)

    -- player
    w:u8(num(safe(UnitLevel, "player"), 0))
    local xp, xpMax = num(safe(UnitXP, "player"), 0), num(safe(UnitXPMax, "player"), 0)
    local rested = num(safe(GetXPExhaustion), 0)
    w:u16(xpMax > 0 and floor(xp / xpMax * 1000) or 0)
    w:u16(xpMax > 0 and floor(rested / xpMax * 1000) or 0)
    -- WoW Forever can hide the current value while the maximum stays readable, so
    -- remember which ones were hidden (flags 21-24); the server then uses the bars.
    local hidden = {}
    local function read(bit, fn, unit)
        local v = safe(fn, unit)
        if ns.isSecret(v) then hidden[bit] = true end
        return num(v, 0)
    end
    w:u24(read(21, UnitHealth, "player"))
    w:u24(read(21, UnitHealthMax, "player"))
    w:u8(num(safe(UnitPowerType, "player"), 0))
    w:u24(read(22, UnitPower, "player"))
    w:u24(read(22, UnitPowerMax, "player"))
    w:u32(num(safe(GetMoney), 0))
    w:u8(freeBagSlots())
    w:u16(num(safe(GetInventoryItemCount, "player", 0), 0))
    w:u8(minDurability())
    local mapID, x, y = mapPosition()
    w:u16(mapID); w:u16(x); w:u16(y)

    -- pet
    if hasPet then
        if ns.isSecret(safe(UnitHealth, "pet")) then hidden[24] = true end
        w:u8(pct(safe(UnitHealth, "pet"), safe(UnitHealthMax, "pet")))
        w:u8(num(safe(GetPetHappiness), 0))
        w:u8(num(safe(UnitLevel, "pet"), 0))
        w:u8(pct(safe(UnitPower, "pet"), safe(UnitPowerMax, "pet")))
    else
        w:u8(255); w:u8(0); w:u8(0); w:u8(255)
    end

    -- target
    if hasTarget then
        if ns.isSecret(safe(UnitHealth, "target")) then hidden[23] = true end
        w:u8(pct(safe(UnitHealth, "target"), safe(UnitHealthMax, "target")))
        w:u8(max(0, num(safe(UnitLevel, "target"), 0)))
        w:u8(CLASSIFICATION[str(safe(UnitClassification, "target")) or "normal"] or 0)
        w:u8(num(safe(UnitReaction, "target", "player"), 0))
    else
        w:u8(255); w:u8(0); w:u8(0); w:u8(0)
    end

    -- casts and global cooldown
    local castId, castRem = castInfo("player", now)
    w:u24(castId); w:u16(floor(castRem * 10))
    local tCastId = hasTarget and castInfo("target", now) or 0
    w:u24(tCastId)
    local gs, gd = cooldown(C_Spell and C_Spell.GetSpellCooldown, GetSpellCooldown, 61304)
    w:u16(floor(remaining(gs, gd, now) * 10))

    -- current (or last) fight
    local fight = ns.fight
    if fight then
        local stop = fight.stop or now
        w:u16(floor((stop - fight.start) * 10))
        w:u32(fight.done); w:u32(fight.taken)
        w:u8(fight.stop and 0 or 1)
        local top = ns.topSpells(fight, 6)
        w:u8(#top)
        for _, s in ipairs(top) do w:u24(s.id); w:u32(s.damage); w:u16(s.hits) end
    else
        w:u16(0); w:u32(0); w:u32(0); w:u8(0); w:u8(0)
    end

    -- action bars
    local actions = {}
    for _, slot in ipairs(ACTION_SLOTS) do
        local ok, a = pcall(readAction, slot, now)
        if ok and a then actions[#actions + 1] = a end
        if #actions >= 48 then break end
    end
    w:u8(#actions)
    for _, a in ipairs(actions) do
        w:u8(a.slot); w:u8(a.kind); w:u24(a.id); w:u8(a.state); w:u16(floor(a.cd * 10))
    end

    -- auras: player buffs, then debuffs on the target
    local buffs = readAuras("player", "HELPFUL", 16, now)
    w:u8(#buffs)
    for _, a in ipairs(buffs) do
        w:u24(a.id); w:u16(a.remaining and floor(a.remaining * 10) or 65535); w:u8(a.stacks)
    end
    local debuffs = hasTarget and readAuras("target", "HARMFUL", 16, now) or {}
    w:u8(#debuffs)
    for _, a in ipairs(debuffs) do
        w:u24(a.id); w:u16(a.remaining and floor(a.remaining * 10) or 65535); w:u8(a.stacks); w:u8(a.mine and 1 or 0)
    end

    -- texts
    w:s(hasTarget and safe(UnitName, "target") or "", 32)
    w:s(hasTarget and safe(UnitName, "targettarget") or "", 32)
    w:s(safe(GetZoneText) or "", 40)
    w:s(safe(GetSubZoneText) or "", 40)
    w:s(ns.lastError or "", 60)
    w:u16(ns.lastError and floor(min(6553, now - ns.lastErrorAt) * 10) or 65535)
    w:s(ns.lastKiller or "", 60)

    -- other addons (protocol 2)
    local okRecs, recs = pcall(ns.hekiliRecommendations, 3)
    if not okRecs then recs = {} end
    w:u8(#recs)
    for _, r in ipairs(recs) do w:u8(r.kind); w:u24(r.id) end
    local okTimers, timers = pcall(ns.dbmActiveTimers, 4)
    if not okTimers then timers = {} end
    w:u8(#timers)
    for _, t in ipairs(timers) do w:s(t.text, 40); w:u16(floor(max(0, t.endsAt - now) * 10)) end
    local alert = ns.dbmAlert
    if alert and now - alert.at > 60 then alert = nil end
    w:s(alert and alert.text or "", 60)
    w:u16(alert and floor((now - alert.at) * 10) or 65535)

    -- Hidden values are only known after reading everything: set their flags in the first 4 bytes now.
    if ns.secretSeen then hidden[17] = true end
    local flags = w.buf[1] * 16777216 + w.buf[2] * 65536 + w.buf[3] * 256 + w.buf[4]
    for bit in pairs(hidden) do
        if floor(flags / 2 ^ bit) % 2 == 0 then flags = flags + 2 ^ bit end
    end
    w.buf[1], w.buf[2] = floor(flags / 16777216) % 256, floor(flags / 65536) % 256
    w.buf[3], w.buf[4] = floor(flags / 256) % 256, flags % 256
    return w.buf
end

---------------------------------------------------------------------------
-- The strip on screen
---------------------------------------------------------------------------
local strip, cells, shown = nil, {}, {}
ns.seq = 0

local function physicalHeight()
    local _, h = safe(GetPhysicalScreenSize)
    h = num(h)
    if h and h > 0 then return h end
    local res = str(safe(GetCVar, "gxWindowedResolution")) or str(safe(GetCVar, "gxFullscreenResolution"))
    h = res and tonumber(res:match("%d+x(%d+)"))
    return h or 1080
end

-- Bars under the squares. In combat the game hides numbers such as health from
-- addons ("secret values"), but a status bar may still display them. The server
-- measures how full each bar is. Order must match server/wowlink/protocol.py BARS.
local BARS = {
    { "player", "health" }, { "player", "power" }, { "target", "health" }, { "pet", "health" },
}
ns.BAR_CELLS = 32 -- bar length in squares
local bars = {}

local function barTop(i, cell) return -(ROWS + 1 + (i - 1) * 2) * cell end

function ns.applyLayout()
    if not strip then return end
    local db = ClaudeLinkDB or {}
    local cell = db.cell or 3
    -- Make one unit = one physical screen pixel, so each square is exactly `cell` pixels.
    strip:SetScale(768 / physicalHeight())
    strip:SetSize(COLS * cell, (ROWS + 1 + #BARS * 2) * cell)
    for i, b in ipairs(bars) do
        b.cap:ClearAllPoints()
        b.cap:SetSize(cell, cell)
        b.cap:SetPoint("TOPLEFT", strip, "TOPLEFT", 0, barTop(i, cell))
        b.bar:ClearAllPoints()
        b.bar:SetSize(ns.BAR_CELLS * cell, cell)
        b.bar:SetPoint("TOPLEFT", strip, "TOPLEFT", cell, barTop(i, cell))
    end
    for i = 0, COLS * ROWS - 1 do
        local t = cells[i]
        t:ClearAllPoints()
        t:SetSize(cell, cell)
        t:SetPoint("TOPLEFT", strip, "TOPLEFT", (i % COLS) * cell, -floor(i / COLS) * cell)
    end
    local corner = db.corner or "TOPLEFT"
    strip:ClearAllPoints()
    strip:SetPoint(corner, UIParent or nil, corner, 0, 0)
    if db.enabled == false then strip:Hide() else strip:Show() end
end

function ns.createStrip()
    if strip then return end
    strip = CreateFrame("Frame", "ClaudeLinkStrip", nil)
    strip:SetFrameStrata("TOOLTIP")
    strip:SetFrameLevel(9000)
    strip:SetClampedToScreen(true)
    local bg = strip:CreateTexture(nil, "BACKGROUND")
    bg:SetAllPoints(strip)
    bg:SetColorTexture(0, 0, 0, 1)
    for i = 0, COLS * ROWS - 1 do
        local t = strip:CreateTexture(nil, "OVERLAY")
        t:SetColorTexture(0, 0, 0, 1)
        cells[i] = t
    end
    for i = 1, #BARS do
        local cap = strip:CreateTexture(nil, "OVERLAY")
        cap:SetColorTexture(1, 0, 1, 1) -- magenta marks the start of a bar
        local bar = CreateFrame("StatusBar", nil, strip)
        bar:SetStatusBarTexture("Interface\\Buttons\\WHITE8X8")
        bar:SetStatusBarColor(1, 1, 1, 1)
        bar:SetMinMaxValues(0, 1)
        bar:SetValue(0)
        bars[i] = { cap = cap, bar = bar }
    end
    ns.applyLayout()

    local elapsed = 0
    strip:SetScript("OnUpdate", function(_, dt)
        elapsed = elapsed + dt
        if elapsed < 0.1 then return end
        elapsed = 0
        ns.update()
    end)
end

function ns.updateBars()
    for i, spec in ipairs(BARS) do
        local b = bars[i]
        if b then
            local unit, kind = spec[1], spec[2]
            -- Values go straight from the game to the bar, so hidden values still display.
            local ok = pcall(function()
                if UnitExists(unit) then
                    if kind == "health" then
                        b.bar:SetMinMaxValues(0, UnitHealthMax(unit))
                        b.bar:SetValue(UnitHealth(unit))
                    else
                        b.bar:SetMinMaxValues(0, UnitPowerMax(unit))
                        b.bar:SetValue(UnitPower(unit))
                    end
                else
                    b.bar:SetMinMaxValues(0, 1)
                    b.bar:SetValue(0)
                end
            end)
            if not ok then
                pcall(b.bar.SetMinMaxValues, b.bar, 0, 1)
                pcall(b.bar.SetValue, b.bar, 0)
            end
        end
    end
end

function ns.update()
    ns.updateBars()
    local ok, payload = pcall(ns.buildLive)
    if not ok then
        ns.lastBuildError = tostring(payload)
        return
    end
    ns.lastBuildError = nil
    ns.lastPayloadSize = #payload
    ns.seq = (ns.seq + 1) % 256
    local colors = ns.encodeCells(payload, ns.seq)
    for i = 0, COLS * ROWS - 1 do
        local c = colors[i]
        local key = c[1] * 65536 + c[2] * 256 + c[3]
        if shown[i] ~= key then
            shown[i] = key
            cells[i]:SetColorTexture(c[1] / 255, c[2] / 255, c[3] / 255, 1)
        end
    end
end

---------------------------------------------------------------------------
-- Events
---------------------------------------------------------------------------
local events = CreateFrame("Frame")
events:RegisterEvent("ADDON_LOADED")
events:RegisterEvent("PLAYER_ENTERING_WORLD")
events:RegisterEvent("PLAYER_REGEN_DISABLED")
events:RegisterEvent("PLAYER_REGEN_ENABLED")
events:RegisterEvent("PLAYER_DEAD")
events:RegisterEvent("UI_ERROR_MESSAGE")
events:RegisterEvent("DISPLAY_SIZE_CHANGED")
events:RegisterEvent("UI_SCALE_CHANGED")
events:RegisterEvent("START_AUTOREPEAT_SPELL")
events:RegisterEvent("STOP_AUTOREPEAT_SPELL")
events:RegisterEvent("ADDON_ACTION_BLOCKED")
events:RegisterEvent("ADDON_ACTION_FORBIDDEN")

events:SetScript("OnEvent", function(_, event, ...)
    if event == "ADDON_LOADED" then
        if ... ~= ADDON then return end
        ClaudeLinkDB = ClaudeLinkDB or {}
        local db = ClaudeLinkDB
        if db.enabled == nil then db.enabled = true end
        db.cell = db.cell or 3
        db.corner = db.corner or "TOPLEFT"
        db.spellNames = db.spellNames or {}
        db.itemNames = db.itemNames or {}
        for k, v in pairs(ns.spellNames) do db.spellNames[k] = v end
        for k, v in pairs(ns.itemNames) do db.itemNames[k] = v end
        ns.spellNames, ns.itemNames = db.spellNames, db.itemNames
        ns.createStrip()
        ns.hookDBM()
    elseif event == "PLAYER_ENTERING_WORLD" then
        ns.applyLayout()
        ns.hookDBM()
    elseif event == "PLAYER_REGEN_DISABLED" then
        if ns.fight and not ns.fight.stop then return end
        archiveFight(ns.fight)
        newFight()
    elseif event == "PLAYER_REGEN_ENABLED" then
        if ns.fight then
            ns.fight.stop = ns.now()
            archiveFight(ns.fight)
        end
    elseif event == "PLAYER_DEAD" then
        ns.onPlayerDied()
    elseif event == "UI_ERROR_MESSAGE" then
        local msg
        for i = select("#", ...), 1, -1 do
            local v = select(i, ...)
            if type(v) == "string" and not ns.isSecret(v) then msg = v; break end
        end
        if msg then
            ns.lastError = msg
            ns.lastErrorAt = ns.now()
        end
    elseif event == "DISPLAY_SIZE_CHANGED" or event == "UI_SCALE_CHANGED" then
        ns.applyLayout()
    elseif event == "START_AUTOREPEAT_SPELL" then
        ns.autoRepeating = true
    elseif event == "STOP_AUTOREPEAT_SPELL" then
        ns.autoRepeating = false
    elseif event == "ADDON_ACTION_BLOCKED" or event == "ADDON_ACTION_FORBIDDEN" then
        -- Record which function the game refused, so it can be fixed.
        local who, fn = ...
        if who == ADDON then
            fn = tostring(fn)
            ClaudeLinkDB = ClaudeLinkDB or {}
            ClaudeLinkDB.blocked = ClaudeLinkDB.blocked or {}
            local list = ClaudeLinkDB.blocked
            list[#list + 1] = { at = safe(date, "%Y-%m-%d %H:%M:%S"), event = event, fn = fn, version = ns.VERSION,
                                inCombat = truthy(safe(InCombatLockdown)) }
            while #list > 20 do table.remove(list, 1) end
            ns.lastBlocked = fn
            if DEFAULT_CHAT_FRAME then
                DEFAULT_CHAT_FRAME:AddMessage("|cffd97706ClaudeLink|r: the game blocked " .. fn .. " (version " .. ns.VERSION .. "). Please send this line to Claude.")
            end
        end
    end
end)
