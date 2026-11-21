-- ClaudeLink: full character snapshot (spellbook, bags, quests, gear, talents,
-- fights, deaths). The game writes it to disk on /reload, logout or exit, so it
-- is refreshed at those moments and by /claudesync.
local ADDON, ns = ...

local floor = math.floor
local safe, num, str, truthy = ns.safe, ns.num, ns.str, ns.truthy

local function section(snap, name, fn)
    local ok, result = pcall(fn)
    if ok then
        snap[name] = result
    else
        snap.errors = snap.errors or {}
        snap.errors[name] = tostring(result)
    end
end

local function itemIdFromLink(link)
    link = str(link)
    return link and tonumber(link:match("item:(%d+)")) or nil
end

local function nameFromLink(link)
    link = str(link)
    return link and link:match("%[(.-)%]") or nil
end

local function character()
    local className, classFile = safe(UnitClass, "player")
    local race = safe(UnitRace, "player")
    local xp, xpMax = num(safe(UnitXP, "player"), 0), num(safe(UnitXPMax, "player"), 0)
    local c = {
        name = str(safe(UnitName, "player")),
        realm = str(safe(GetRealmName)),
        class = str(className), classFile = str(classFile),
        race = str(race),
        level = num(safe(UnitLevel, "player")),
        xp = xp, xpMax = xpMax,
        rested = num(safe(GetXPExhaustion), 0),
        money = num(safe(GetMoney), 0),
        guild = str(safe(GetGuildInfo, "player")),
        zone = str(safe(GetZoneText)), subZone = str(safe(GetSubZoneText)),
        health = num(safe(UnitHealthMax, "player")),
        power = num(safe(UnitPowerMax, "player")),
        powerType = num(safe(UnitPowerType, "player")),
    }
    return c
end

local STAT_NAMES = { "Strength", "Agility", "Stamina", "Intellect", "Spirit" }

local function stats()
    local s = {}
    for i, name in ipairs(STAT_NAMES) do
        local base, effective = safe(UnitStat, "player", i)
        s[name] = num(effective) or num(base)
    end
    local _, armor = safe(UnitArmor, "player")
    s.Armor = num(armor)
    local base, pos, neg = safe(UnitAttackPower, "player")
    s.MeleeAttackPower = num(base) and (num(base) + num(pos, 0) + num(neg, 0)) or nil
    base, pos, neg = safe(UnitRangedAttackPower, "player")
    s.RangedAttackPower = num(base) and (num(base) + num(pos, 0) + num(neg, 0)) or nil
    s.MeleeCrit = num(safe(GetCritChance))
    s.RangedCrit = num(safe(GetRangedCritChance))
    s.SpellCrit = num(safe(GetSpellCritChance, 2))
    s.Dodge = num(safe(GetDodgeChance))
    return s
end

local function spellbook()
    local list = {}
    if C_SpellBook and C_SpellBook.GetNumSpellBookSkillLines and C_SpellBook.GetSpellBookItemInfo then
        local bank = Enum and Enum.SpellBookSpellBank and Enum.SpellBookSpellBank.Player or 0
        local lines = num(safe(C_SpellBook.GetNumSpellBookSkillLines), 0)
        for l = 1, lines do
            local info = safe(C_SpellBook.GetSpellBookSkillLineInfo, l)
            if type(info) == "table" then
                local offset, count = num(info.itemIndexOffset, 0), num(info.numSpellBookItems, 0)
                for i = offset + 1, offset + count do
                    local item = safe(C_SpellBook.GetSpellBookItemInfo, i, bank)
                    if type(item) == "table" then
                        local id = num(item.spellID) or num(item.actionID)
                        ns.rememberSpell(id, item.name)
                        list[#list + 1] = {
                            tab = str(info.name), id = id, name = str(item.name),
                            rank = str(item.subName), passive = item.isPassive and true or nil,
                        }
                    end
                end
            end
        end
        if #list > 0 then return list end
    end
    local tabs = num(safe(GetNumSpellTabs), 0)
    for t = 1, tabs do
        local tabName, _, offset, count = safe(GetSpellTabInfo, t)
        offset, count = num(offset, 0), num(count, 0)
        for i = offset + 1, offset + count do
            local name, rank = safe(GetSpellBookItemName, i, "spell")
            local _, id = safe(GetSpellBookItemInfo, i, "spell")
            ns.rememberSpell(id, name)
            list[#list + 1] = { tab = str(tabName), id = num(id), name = str(name), rank = str(rank) }
        end
    end
    return list
end

local function actionBars()
    local list = {}
    for slot = 1, 120 do
        if truthy(safe(HasAction, slot)) then
            local aType, id = safe(GetActionInfo, slot)
            local e = { slot = slot, type = str(aType), id = num(id) }
            if aType == "spell" then
                e.name = ns.spellName(id)
            elseif aType == "item" then
                e.name = ns.itemName(id)
            elseif aType == "macro" then
                e.macro = str(safe(GetMacroInfo, id))
                local spellId = num(safe(GetMacroSpell, id))
                if spellId then e.castsSpell = spellId; e.name = ns.spellName(spellId) end
            end
            e.text = str(safe(GetActionText, slot))
            e.key = ns.actionKey(slot)
            list[#list + 1] = e
        end
    end
    return list
end

local function pet()
    if not truthy(safe(UnitExists, "pet")) then return { exists = false } end
    local p = {
        exists = true,
        name = str(safe(UnitName, "pet")),
        family = str(safe(UnitCreatureFamily, "pet")),
        level = num(safe(UnitLevel, "pet")),
        happiness = num(safe(GetPetHappiness)),
        loyalty = str(safe(GetPetLoyalty)),
        trainingPoints = num(safe(GetPetTrainingPoints)),
        dead = truthy(safe(UnitIsDead, "pet")),
        actions = {},
    }
    for i = 1, 10 do
        local name, _, isToken, isActive, autoCastAllowed, autoCastEnabled, spellId = safe(GetPetActionInfo, i)
        if name then
            if truthy(isToken) and _G[name] then name = _G[name] end
            p.actions[#p.actions + 1] = {
                slot = i, name = str(name), active = truthy(isActive) or nil,
                autoCastAllowed = truthy(autoCastAllowed) or nil,
                autoCastOn = truthy(autoCastEnabled) or nil,
                id = num(spellId),
            }
        end
    end
    return p
end

local function talents()
    local tabs = {}
    local n = num(safe(GetNumTalentTabs), 0)
    for t = 1, n do
        local r = { safe(GetTalentTabInfo, t) }
        local tabName, spent
        for _, v in ipairs(r) do
            if not tabName and type(v) == "string" then tabName = v end
        end
        -- Classic returns (name, icon, pointsSpent, ...); later clients add an id first.
        if type(r[1]) == "string" then spent = num(r[3]) else spent = num(r[5]) end
        local list = {}
        for i = 1, num(safe(GetNumTalents, t), 0) do
            local name, _, tier, column, rank, maxRank = safe(GetTalentInfo, t, i)
            if name then
                list[#list + 1] = { name = str(name), tier = num(tier), column = num(column), rank = num(rank), maxRank = num(maxRank) }
            end
        end
        tabs[#tabs + 1] = { name = tabName, pointsSpent = spent, talents = list }
    end
    return { unspent = num(safe(UnitCharacterPoints, "player")), tabs = tabs }
end

local function skills()
    local list = {}
    for i = 1, num(safe(GetNumSkillLines), 0) do
        local name, isHeader, _, rank, _, modifier, maxRank = safe(GetSkillLineInfo, i)
        if name and not truthy(isHeader) then
            list[#list + 1] = { name = str(name), rank = num(rank), bonus = num(modifier), max = num(maxRank) }
        end
    end
    return list
end

local SLOT_NAMES = {
    "Head", "Neck", "Shoulder", "Shirt", "Chest", "Waist", "Legs", "Feet", "Wrist", "Hands",
    "Finger1", "Finger2", "Trinket1", "Trinket2", "Back", "MainHand", "OffHand", "Ranged", "Tabard",
}

local function gear()
    local list = {}
    for slot = 0, 19 do
        local link = safe(GetInventoryItemLink, "player", slot)
        if link then
            local name, _, quality, ilvl, reqLevel, itemType, subType = safe(GetItemInfo, link)
            local cur, maxv = safe(GetInventoryItemDurability, slot)
            list[#list + 1] = {
                slot = slot == 0 and "Ammo" or SLOT_NAMES[slot] or tostring(slot),
                id = itemIdFromLink(link), name = str(name) or nameFromLink(link),
                quality = num(quality), itemLevel = num(ilvl), requiredLevel = num(reqLevel),
                type = str(itemType), subType = str(subType),
                durability = num(cur) and num(maxv) and (num(cur) .. "/" .. num(maxv)) or nil,
                count = slot == 0 and num(safe(GetInventoryItemCount, "player", 0)) or nil,
            }
        end
    end
    return list
end

local function containerSlots(bag)
    if C_Container and C_Container.GetContainerNumSlots then return num(safe(C_Container.GetContainerNumSlots, bag), 0) end
    return num(safe(GetContainerNumSlots, bag), 0)
end

local function containerItem(bag, slot)
    if C_Container and C_Container.GetContainerItemInfo then
        local info = safe(C_Container.GetContainerItemInfo, bag, slot)
        if type(info) == "table" then
            return num(info.itemID), num(info.stackCount, 1), num(info.quality), info.hyperlink, info.hasNoValue
        end
        return nil
    end
    local _, count, _, quality, _, _, link, _, noValue, itemId = safe(GetContainerItemInfo, bag, slot)
    return num(itemId) or itemIdFromLink(link), num(count, 1), num(quality), link, noValue
end

local function bags()
    local list, free, total = {}, 0, 0
    for bag = 0, 4 do
        for slot = 1, containerSlots(bag) do
            total = total + 1
            local id, count, quality, link, noValue = containerItem(bag, slot)
            if id then
                local name, _, _, ilvl, reqLevel, itemType, subType, _, equipLoc, _, sellPrice = safe(GetItemInfo, link or id)
                name = str(name) or nameFromLink(link) or ns.itemName(id)
                if name then ns.itemNames[id] = name end
                local ah, ahAge = ns.auctionPrice(id)
                list[#list + 1] = {
                    bag = bag, slot = slot, id = id, name = name, count = count, quality = num(quality),
                    itemLevel = num(ilvl), requiredLevel = num(reqLevel), type = str(itemType), subType = str(subType),
                    equipSlot = str(equipLoc) ~= "" and str(equipLoc) or nil,
                    vendorPrice = num(sellPrice), noValue = truthy(noValue) or nil,
                    auctionPrice = ah, auctionPriceAgeDays = ahAge,
                    pawnUpgradePercent = str(equipLoc) and str(equipLoc) ~= "" and ns.pawnUpgrade(link) or nil,
                }
            else
                free = free + 1
            end
        end
    end
    return { items = list, freeSlots = free, totalSlots = total }
end

local function quests()
    local list = {}
    if C_QuestLog and C_QuestLog.GetNumQuestLogEntries and C_QuestLog.GetInfo then
        local n = num(safe(C_QuestLog.GetNumQuestLogEntries), 0)
        for i = 1, n do
            local q = safe(C_QuestLog.GetInfo, i)
            if type(q) == "table" and not q.isHeader then
                local objectives = {}
                local objs = q.questID and safe(C_QuestLog.GetQuestObjectives, q.questID)
                if type(objs) == "table" then
                    for _, o in ipairs(objs) do
                        objectives[#objectives + 1] = { text = str(o.text), done = o.finished and true or false }
                    end
                end
                local complete = q.questID and C_QuestLog.IsComplete and safe(C_QuestLog.IsComplete, q.questID)
                list[#list + 1] = {
                    id = num(q.questID), title = str(q.title), level = num(q.level),
                    complete = truthy(complete) or nil, objectives = objectives,
                }
            end
        end
        if #list > 0 then return list end
    end
    local n = num(safe(GetNumQuestLogEntries), 0)
    for i = 1, n do
        local title, level, _, isHeader, _, isComplete, _, questId = safe(GetQuestLogTitle, i)
        if title and not truthy(isHeader) then
            local objectives = {}
            for j = 1, num(safe(GetNumQuestLeaderBoards, i), 0) do
                local text, _, done = safe(GetQuestLogLeaderBoard, j, i)
                objectives[#objectives + 1] = { text = str(text), done = truthy(done) }
            end
            list[#list + 1] = {
                id = num(questId), title = str(title), level = num(level),
                complete = (isComplete == 1 or isComplete == true) or nil,
                failed = (isComplete == -1) or nil,
                objectives = objectives,
            }
        end
    end
    return list
end

local function reputation()
    local list = {}
    for i = 1, num(safe(GetNumFactions), 0) do
        local name, _, standing, barMin, barMax, value, _, _, isHeader = safe(GetFactionInfo, i)
        if name and not truthy(isHeader) then
            list[#list + 1] = { name = str(name), standing = num(standing), value = num(value), min = num(barMin), max = num(barMax) }
        end
    end
    return list
end

function ns.buildSnapshot(reason)
    local snap = {
        addon = "ClaudeLink", version = ns.VERSION, reason = reason,
        savedAt = num(safe(time)), savedAtText = str(safe(date, "%Y-%m-%d %H:%M:%S")),
    }
    section(snap, "character", character)
    section(snap, "stats", stats)
    section(snap, "spellbook", spellbook)
    section(snap, "actionBars", actionBars)
    section(snap, "pet", pet)
    section(snap, "talents", talents)
    section(snap, "skills", skills)
    section(snap, "gear", gear)
    section(snap, "bags", bags)
    section(snap, "quests", quests)
    section(snap, "reputation", reputation)
    section(snap, "addons", ns.addonList)
    section(snap, "questGuide", function() return ns.questGuide(snap.quests) end)
    local c = ns.charDB()
    snap.fights = c.fights
    snap.deaths = c.deaths
    snap.blockedActions = ClaudeLinkDB and ClaudeLinkDB.blocked
    snap.spellNames = ns.spellNames
    snap.itemNames = ns.itemNames
    return snap
end

function ns.saveSnapshot(reason)
    local ok, err = pcall(function()
        local c = ns.charDB()
        local json = ns.toJSON(ns.buildSnapshot(reason))
        c.snapshotB64 = ns.base64(json)
        c.savedAt = num(safe(time))
        c.snapshotBytes = #json
    end)
    if not ok then
        ClaudeLinkDB = ClaudeLinkDB or {}
        ClaudeLinkDB.lastSnapshotError = tostring(err)
    end
    return ok, err
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_LOGOUT")
f:SetScript("OnEvent", function()
    ns.saveSnapshot("logout or reload")
end)
