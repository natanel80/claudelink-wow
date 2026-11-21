-- A fake WoW API, just enough to run the ClaudeLink addon outside the game in tests.
local T = 1000.0
local frames = {}

local function noop() end
local FrameMT = {}
FrameMT.__index = function(self, k)
    if k == "CreateTexture" then
        return function() return setmetatable({}, FrameMT) end
    end
    if k == "SetScript" then
        return function(s, name, fn) rawset(s, "_script_" .. name, fn) end
    end
    if k == "RegisterEvent" then
        return function(s, ev) rawget(s, "_events")[ev] = true end
    end
    return noop
end

function CreateFrame()
    local f = setmetatable({ _events = {} }, FrameMT)
    frames[#frames + 1] = f
    return f
end

function AllFrames() return frames end

function FireEvent(event, ...)
    for _, f in ipairs(frames) do
        local h = rawget(f, "_script_OnEvent")
        if h and f._events[event] then h(f, event, ...) end
    end
end

SlashCmdList = {}
DEFAULT_CHAT_FRAME = { AddMessage = noop }
function GetTime() return T end
function time() return 1763700000 end
function date(fmt) return "2026-11-21 20:15:03" end
function ReloadUI() end
function GetPhysicalScreenSize() return 1920, 1080 end

local unitData = {
    player = { name = "Testhunter", level = 11, hp = 180, hpMax = 240, power = 150, powerMax = 300, ptype = 0 },
    pet = { name = "Fleshripper", level = 11, hp = 50, hpMax = 200, power = 80, powerMax = 100 },
    target = { name = "Defias Bandit", level = 12, hp = 30, hpMax = 100 },
    targettarget = { name = "Fleshripper" },
}
function UnitExists(u) return unitData[u] ~= nil end
function UnitName(u) return unitData[u] and unitData[u].name end
function UnitLevel(u) return unitData[u] and unitData[u].level end
function UnitHealth(u) return unitData[u] and unitData[u].hp end
function UnitHealthMax(u) return unitData[u] and unitData[u].hpMax end
function UnitPower(u) return unitData[u] and unitData[u].power end
function UnitPowerMax(u) return unitData[u] and unitData[u].powerMax end
function UnitPowerType(u) return 0 end
function UnitGUID(u) return u == "player" and "Player-1-0001" or u == "pet" and "Pet-0-1-2-3-4-5" or nil end
function UnitAffectingCombat(u) return u == "player" end
function UnitIsDead() return false end
function UnitIsGhost() return false end
function UnitIsPlayer() return false end
function UnitCanAttack() return true end
function UnitIsFriend() return false end
function UnitIsUnit(a, b) return a == "targettarget" and b == "pet" end
function UnitIsTapDenied() return false end
function UnitClassification() return "normal" end
function UnitReaction() return 2 end
function UnitClass() return "Hunter", "HUNTER" end
function UnitRace() return "Human" end
function UnitXP() return 700 end
function UnitXPMax() return 1000 end
function GetXPExhaustion() return 250 end
function GetMoney() return 123456 end
function GetRealmName() return "Forever" end
function GetZoneText() return "Westfall" end
function GetSubZoneText() return "Moonbrook" end
function IsResting() return false end
function IsMounted() return false end
function IsInGroup() return true end
function IsSwimming() return false end
function UnitOnTaxi() return false end
function GetPetHappiness() return 3 end
function GetInventoryItemCount() return 812 end
function GetInventoryItemDurability(slot) if slot == 5 then return 30, 60 end return nil end
C_Container = { GetContainerNumFreeSlots = function(bag) return bag == 0 and 4 or 1, 0 end }
C_Map = {
    GetBestMapForUnit = function() return 1436 end,
    GetPlayerMapPosition = function() return { GetXY = function() return 0.4567, 0.7012 end } end,
}
C_Spell = {
    GetSpellName = function(id)
        local n = { [75] = "Auto Shot", [3044] = "Arcane Shot", [1978] = "Serpent Sting", [1130] = "Hunter's Mark",
                    [13165] = "Aspect of the Hawk" }
        return n[id]
    end,
    GetSpellCooldown = function(id) return { startTime = T - 0.5, duration = 1.5 } end,
}
function UnitCastingInfo() return nil end
function UnitChannelInfo() return nil end

local actions = { [1] = { "spell", 75 }, [2] = { "spell", 3044 }, [3] = { "spell", 1130 }, [4] = { "spell", 1978 },
                  [5] = { "item", 159 } }
function HasAction(s) return actions[s] ~= nil end
function GetActionInfo(s) local a = actions[s]; return a[1], a[2] end
function IsUsableAction(s) return s ~= 2, false end
function IsActionInRange(s) if s == 5 then return nil end return true end
function GetActionCooldown(s) if s == 2 then return T - 2, 6 end return 0, 0 end
function IsCurrentAction() return false end
function IsAutoRepeatAction(s) return s == 1 end
function IsAutoRepeatSpell() return true end

local buffs = { { "Aspect of the Hawk", 13165, 0, "player" } }
local debuffs = { { "Serpent Sting", 1978, T + 9.3, "player" }, { "Hunter's Mark", 1130, T + 100, "player" } }
function UnitAura(unit, i, filter)
    local list = unit == "player" and buffs or debuffs
    local a = list[i]
    if not a then return nil end
    return a[1], nil, 1, nil, 0, a[3], a[4], nil, nil, a[2]
end

local combatEvent
function CombatLogGetCurrentEventInfo() return unpack(combatEvent) end
function SetCombatEvent(...) combatEvent = { ... } end
function GetItemInfo(id) if id == 159 or id == "x" then return "Refreshing Spring Water" end return nil end

-- Other addons
function wipe(t) for k in pairs(t) do t[k] = nil end return t end
local loadedAddons = { Bartender4 = true, Questie = true, Hekili = true }
C_AddOns = {
    IsAddOnLoaded = function(n) return loadedAddons[n] == true or n == 1 or n == 2 end,
    GetNumAddOns = function() return 2 end,
    GetAddOnInfo = function(i) if i == 1 then return "Bartender4", "|cff33ff99Bartender4|r" end return "Questie", "Questie" end,
    GetAddOnMetadata = function(name) return name == "Questie" and "12.11.1" or "4.15" end,
}
function GetBindingKey(cmd)
    if cmd == "CLICK BT4Button2:Keyboard" then return "2" end
    if cmd == "ACTIONBUTTON1" then return "1" end
    return nil
end
function Hekili_GetRecommendedAbility(display, i)
    local recs = { 3044, 1978, -159 }
    return recs[i]
end
local dbmCallbacks = {}
DBM = { RegisterCallback = function(self, ev, fn) dbmCallbacks[ev] = fn end }
function FireDBM(ev, ...) if dbmCallbacks[ev] then dbmCallbacks[ev](ev, ...) end end
Auctionator = { API = { v1 = {
    GetAuctionPriceByItemID = function(caller, id) if id == 159 then return 25 end end,
    GetAuctionAgeByItemID = function(caller, id) if id == 159 then return 2 end end,
} } }
local QDB = {
    GetQuest = function(id)
        if id ~= 65 then return nil end
        return { Starts = { NPC = { 234 } }, Finisher = { NPC = { 234 } }, level = 12,
                 ObjectiveData = { { Type = "monster", Id = 116, Text = "Defias Bandit slain" },
                                   { Type = "item", Id = 1019 } } }
    end,
}
function QDB:GetNPC(id)
    if id == 234 then return { name = "Gryan Stoutmantle", spawns = { [40] = { { 56.3, 47.5 } } } } end
    if id == 116 then return { name = "Defias Bandit", spawns = { [40] = { { 50, 60 }, { 52, 62 }, { -1, -1 } } } } end
end
function QDB:GetItem(id) return { npcDrops = { 116 } } end
QuestieLoader = { ImportModule = function(self, name) if name == "QuestieDB" then return QDB end end }
C_Map.GetAreaInfo = function(id) return id == 40 and "Westfall" or nil end
function GetNumQuestLogEntries() return 1 end
function GetQuestLogTitle(i) return "The Defias Brotherhood", 14, nil, false, false, nil, nil, 65 end
function GetNumQuestLeaderBoards() return 0 end
function GetContainerNumSlots(bag) return bag == 0 and 2 or 0 end
C_Container.GetContainerNumSlots = function(bag) return bag == 0 and 2 or 0 end
C_Container.GetContainerItemInfo = function(bag, slot)
    if bag == 0 and slot == 1 then return { itemID = 159, stackCount = 5, quality = 1, hyperlink = "|Hitem:159|h[Refreshing Spring Water]|h" } end
end
