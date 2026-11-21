-- ClaudeLink: information from other addons, when they are installed.
-- Every call is protected: a missing or changed addon is simply skipped.
--   Hekili / Hekili Forever: the next abilities it recommends (live)
--   Deadly Boss Mods: boss timers and warnings (live)
--   Questie: where to go for each quest objective and turn-in (full report)
--   Auctionator: auction house prices of bag items (full report)
--   Pawn: which bag items are upgrades (full report)
--   Bartender4 / default bars: the key bound to each action button (full report)
local ADDON, ns = ...

local floor, max = math.floor, math.max
local safe, num, str, truthy = ns.safe, ns.num, ns.str, ns.truthy

function ns.isLoaded(name)
    if C_AddOns and C_AddOns.IsAddOnLoaded then return truthy(safe(C_AddOns.IsAddOnLoaded, name)) end
    return truthy(safe(IsAddOnLoaded, name))
end

---------------------------------------------------------------------------
-- Installed addons
---------------------------------------------------------------------------
function ns.addonList()
    local list = {}
    local count = (C_AddOns and C_AddOns.GetNumAddOns and num(safe(C_AddOns.GetNumAddOns)))
        or num(safe(GetNumAddOns), 0)
    local getInfo = (C_AddOns and C_AddOns.GetAddOnInfo) or GetAddOnInfo
    local getMeta = (C_AddOns and C_AddOns.GetAddOnMetadata) or GetAddOnMetadata
    for i = 1, count do
        local name, title = safe(getInfo, i)
        name = str(name)
        if name and ns.isLoaded(name) then
            local t = str(title)
            if t then t = t:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "") end
            list[#list + 1] = { name = name, title = t ~= name and t or nil, version = str(safe(getMeta, name, "Version")) }
        end
    end
    return list
end

---------------------------------------------------------------------------
-- Hekili: next recommended abilities
---------------------------------------------------------------------------
function ns.hekiliRecommendations(limit)
    local recs = {}
    if type(Hekili_GetRecommendedAbility) ~= "function" then return recs end
    local display = (ClaudeLinkDB and ClaudeLinkDB.hekiliDisplay) or "Primary"
    for i = 1, limit do
        local id = num(safe(Hekili_GetRecommendedAbility, display, i))
        if not id or id == 0 then break end
        if id < 0 then
            recs[#recs + 1] = { kind = 2, id = -id }
            ns.itemName(-id)
        else
            recs[#recs + 1] = { kind = 1, id = id }
            ns.spellName(id)
        end
    end
    return recs
end

---------------------------------------------------------------------------
-- Deadly Boss Mods: timers and warnings
---------------------------------------------------------------------------
ns.dbmTimers = {}
ns.dbmAlert = nil

local function dbmTimerStart(_, id, msg, timer)
    timer = num(timer)
    if id and timer then ns.dbmTimers[id] = { text = str(msg) or "?", endsAt = ns.now() + timer } end
end

function ns.hookDBM()
    if ns.dbmHooked or type(DBM) ~= "table" or type(DBM.RegisterCallback) ~= "function" then return end
    ns.dbmHooked = true
    local function on(event, fn) pcall(DBM.RegisterCallback, DBM, event, fn) end
    on("DBM_TimerBegin", dbmTimerStart)
    on("DBM_TimerStart", dbmTimerStart) -- older DBM versions
    on("DBM_TimerStop", function(_, id) if id then ns.dbmTimers[id] = nil end end)
    on("DBM_TimerUpdate", function(_, id, elapsed, total)
        local t = id and ns.dbmTimers[id]
        elapsed, total = num(elapsed), num(total)
        if t and elapsed and total then t.endsAt = ns.now() + total - elapsed end
    end)
    on("DBM_Announce", function(_, message)
        message = str(message)
        if message then ns.dbmAlert = { text = message, at = ns.now() } end
    end)
    local function clear() wipe(ns.dbmTimers) end
    on("DBM_Kill", clear)
    on("DBM_Wipe", clear)
end

function ns.dbmActiveTimers(limit)
    local now, list = ns.now(), {}
    for id, t in pairs(ns.dbmTimers) do
        if t.endsAt < now - 1 then
            ns.dbmTimers[id] = nil
        else
            list[#list + 1] = t
        end
    end
    table.sort(list, function(a, b) return a.endsAt < b.endsAt end)
    while #list > limit do table.remove(list) end
    return list
end

---------------------------------------------------------------------------
-- Key bindings of action buttons (Bartender4 or the default bars)
---------------------------------------------------------------------------
local DEFAULT_BARS = {
    { 1, 12, "ACTIONBUTTON" },
    { 25, 36, "MULTIACTIONBAR3BUTTON" },
    { 37, 48, "MULTIACTIONBAR4BUTTON" },
    { 49, 60, "MULTIACTIONBAR2BUTTON" },
    { 61, 72, "MULTIACTIONBAR1BUTTON" },
}

function ns.actionKey(slot)
    if ns.isLoaded("Bartender4") then
        for _, suffix in ipairs({ ":Keyboard", ":LeftButton" }) do
            local key = str(safe(GetBindingKey, "CLICK BT4Button" .. slot .. suffix))
            if key then return key end
        end
    end
    for _, bar in ipairs(DEFAULT_BARS) do
        if slot >= bar[1] and slot <= bar[2] then
            return str(safe(GetBindingKey, bar[3] .. (slot - bar[1] + 1)))
        end
    end
    return nil
end

---------------------------------------------------------------------------
-- Auctionator prices and Pawn upgrades
---------------------------------------------------------------------------
function ns.auctionPrice(itemId)
    local api = type(Auctionator) == "table" and type(Auctionator.API) == "table" and Auctionator.API.v1
    if type(api) ~= "table" or type(api.GetAuctionPriceByItemID) ~= "function" then return nil end
    local price = num(safe(api.GetAuctionPriceByItemID, "ClaudeLink", itemId))
    local age = type(api.GetAuctionAgeByItemID) == "function" and num(safe(api.GetAuctionAgeByItemID, "ClaudeLink", itemId)) or nil
    return price, age
end

function ns.pawnUpgrade(link)
    if not link or type(PawnGetItemData) ~= "function" or type(PawnIsItemAnUpgrade) ~= "function" then return nil end
    local item = safe(PawnGetItemData, link)
    if type(item) ~= "table" then return nil end
    local upgrades = safe(PawnIsItemAnUpgrade, item)
    if type(upgrades) ~= "table" or next(upgrades) == nil then return nil end
    local best
    for _, u in pairs(upgrades) do
        local p = type(u) == "table" and num(u.PercentUpgrade)
        if p and (not best or p > best) then best = p end
    end
    return best and floor(best * 1000 + 0.5) / 10 or true
end

---------------------------------------------------------------------------
-- Questie: where to find quest objectives and where to turn quests in
---------------------------------------------------------------------------
local function zoneName(areaId)
    if C_Map and C_Map.GetAreaInfo then
        local n = str(safe(C_Map.GetAreaInfo, areaId))
        if n then return n end
    end
    return "zone " .. tostring(areaId)
end

-- Questie spawns: { [areaId] = { {x, y}, ... } } with x, y from 0 to 100.
local function spawnSummary(spawns, limit)
    if type(spawns) ~= "table" then return nil end
    local zones = {}
    for areaId, points in pairs(spawns) do
        if type(points) == "table" then
            local sx, sy, n = 0, 0, 0
            for _, p in ipairs(points) do
                local x, y = num(p[1]), num(p[2])
                if x and y and x >= 0 and y >= 0 then
                    sx, sy, n = sx + x, sy + y, n + 1
                end
            end
            if n > 0 then
                zones[#zones + 1] = {
                    zone = zoneName(areaId),
                    x = floor(sx / n * 10) / 10, y = floor(sy / n * 10) / 10,
                    spawnPoints = n,
                }
            end
        end
    end
    table.sort(zones, function(a, b) return a.spawnPoints > b.spawnPoints end)
    while #zones > (limit or 3) do table.remove(zones) end
    return #zones > 0 and zones or nil
end

local function npcInfo(QDB, id)
    local npc = id and safe(QDB.GetNPC, QDB, id)
    if type(npc) ~= "table" then return id and { id = id } or nil end
    return { name = str(npc.name), where = spawnSummary(npc.spawns) }
end

local function objectInfo(QDB, id)
    local obj = id and safe(QDB.GetObject, QDB, id)
    if type(obj) ~= "table" then return id and { id = id } or nil end
    return { name = str(obj.name), where = spawnSummary(obj.spawns) }
end

local function itemSources(QDB, id)
    local item = id and safe(QDB.GetItem, QDB, id)
    if type(item) ~= "table" then return nil end
    local out = {}
    if type(item.npcDrops) == "table" then
        for i = 1, math.min(3, #item.npcDrops) do out[#out + 1] = npcInfo(QDB, item.npcDrops[i]) end
    end
    if type(item.objectDrops) == "table" then
        for i = 1, math.min(2, #item.objectDrops) do out[#out + 1] = objectInfo(QDB, item.objectDrops[i]) end
    end
    if type(item.vendors) == "table" and #item.vendors > 0 then
        local v = npcInfo(QDB, item.vendors[1])
        if v then v.vendor = true; out[#out + 1] = v end
    end
    return #out > 0 and out or nil
end

function ns.questGuide(quests)
    if type(QuestieLoader) ~= "table" or type(QuestieLoader.ImportModule) ~= "function" then return nil end
    local ok, QDB = pcall(QuestieLoader.ImportModule, QuestieLoader, "QuestieDB")
    if not ok or type(QDB) ~= "table" or type(QDB.GetQuest) ~= "function" then return nil end
    local guide = {}
    for _, q in ipairs(quests or {}) do
        local quest = q.id and safe(QDB.GetQuest, q.id)
        if type(quest) == "table" then
            local g = { id = q.id, title = q.title, complete = q.complete, objectives = {} }
            if type(quest.Starts) == "table" and type(quest.Starts.NPC) == "table" and quest.Starts.NPC[1] then
                g.startedBy = npcInfo(QDB, quest.Starts.NPC[1])
            end
            if type(quest.Finisher) == "table" then
                if type(quest.Finisher.NPC) == "table" and quest.Finisher.NPC[1] then
                    g.turnIn = npcInfo(QDB, quest.Finisher.NPC[1])
                elseif type(quest.Finisher.GameObject) == "table" and quest.Finisher.GameObject[1] then
                    g.turnIn = objectInfo(QDB, quest.Finisher.GameObject[1])
                end
            end
            for _, o in ipairs(type(quest.ObjectiveData) == "table" and quest.ObjectiveData or {}) do
                local e = { type = str(o.Type), text = str(o.Text) }
                if o.Type == "monster" then
                    e.target = npcInfo(QDB, o.Id)
                elseif o.Type == "object" then
                    e.target = objectInfo(QDB, o.Id)
                elseif o.Type == "item" then
                    e.item = ns.itemName(o.Id)
                    e.from = itemSources(QDB, o.Id)
                end
                g.objectives[#g.objectives + 1] = e
            end
            if type(quest.triggerEnd) == "table" then
                g.objectives[#g.objectives + 1] = {
                    type = "explore", text = str(quest.triggerEnd[1]), where = spawnSummary(quest.triggerEnd[2]),
                }
            end
            local level = num(quest.level)
            if level then g.questLevel = level end
            guide[#guide + 1] = g
        end
    end
    return guide
end
