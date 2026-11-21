-- ClaudeLink: shared helpers (safe API calls, byte writer, JSON, Base64).
local ADDON, ns = ...

ns.VERSION = "0.4.1"

local floor, select, type, tostring, tonumber = math.floor, select, type, tostring, tonumber
local unpack = unpack or table.unpack

-- Values the game hides from addons ("secret values") can't be used in math.
function ns.isSecret(v)
    if type(issecretvalue) == "function" then
        local ok, r = pcall(issecretvalue, v)
        if ok and r then
            ns.secretSeen = true
            return true
        end
    end
    return false
end

local function pack(...) return { n = select("#", ...), ... } end

-- Call a game API that may not exist in this client; never throws.
function ns.safe(fn, ...)
    if type(fn) ~= "function" then return nil end
    local r = pack(pcall(fn, ...))
    if not r[1] then return nil end
    return unpack(r, 2, r.n)
end

function ns.num(v, fallback)
    if type(v) == "number" and not ns.isSecret(v) and v == v then return v end
    if type(v) == "boolean" and not ns.isSecret(v) then return v and 1 or 0 end
    return fallback
end

function ns.str(v)
    if v == nil or ns.isSecret(v) then return nil end
    local t = type(v)
    if t == "string" then return v end
    if t == "number" or t == "boolean" then return tostring(v) end
    return nil
end

function ns.truthy(v)
    if v == nil or ns.isSecret(v) then return false end
    return v ~= false and v ~= 0
end

---------------------------------------------------------------------------
-- Byte writer for the live pixel payload (big-endian unsigned integers).
---------------------------------------------------------------------------
local Writer = {}
Writer.__index = Writer

function ns.newWriter() return setmetatable({ n = 0, buf = {} }, Writer) end

function Writer:u(v, bytes)
    v = floor(tonumber(v) or 0)
    local max = 256 ^ bytes - 1
    if v < 0 then v = 0 elseif v > max then v = max end
    for i = bytes - 1, 0, -1 do
        self.n = self.n + 1
        self.buf[self.n] = floor(v / 256 ^ i) % 256
    end
end

function Writer:u8(v) self:u(v, 1) end
function Writer:u16(v) self:u(v, 2) end
function Writer:u24(v) self:u(v, 3) end
function Writer:u32(v) self:u(v, 4) end

-- Length-prefixed string, cut to maxLen bytes.
function Writer:s(v, maxLen)
    v = ns.str(v) or ""
    if #v > maxLen then v = v:sub(1, maxLen) end
    self:u8(#v)
    for i = 1, #v do
        self.n = self.n + 1
        self.buf[self.n] = v:byte(i)
    end
end

---------------------------------------------------------------------------
-- JSON encoder (for the full snapshot stored in SavedVariables).
---------------------------------------------------------------------------
local escapes = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }

local function escape(s)
    return (s:gsub('[%c"\\]', function(c)
        return escapes[c] or string.format("\\u%04x", c:byte())
    end))
end

local function isArray(t)
    local n = #t
    if n == 0 then return next(t) == nil end
    local count = 0
    for _ in pairs(t) do count = count + 1 end
    return count == n
end

local function encode(v, depth, out)
    if depth > 24 or ns.isSecret(v) then out[#out + 1] = "null"; return end
    local t = type(v)
    if t == "nil" then
        out[#out + 1] = "null"
    elseif t == "boolean" then
        out[#out + 1] = v and "true" or "false"
    elseif t == "number" then
        if v ~= v or v == math.huge or v == -math.huge then
            out[#out + 1] = "null"
        elseif v == floor(v) and math.abs(v) < 1e15 then
            out[#out + 1] = string.format("%.0f", v)
        else
            out[#out + 1] = string.format("%.4f", v)
        end
    elseif t == "string" then
        out[#out + 1] = '"' .. escape(v) .. '"'
    elseif t == "table" then
        if isArray(v) then
            out[#out + 1] = "["
            for i = 1, #v do
                if i > 1 then out[#out + 1] = "," end
                encode(v[i], depth + 1, out)
            end
            out[#out + 1] = "]"
        else
            local keys = {}
            for k in pairs(v) do
                if type(k) == "string" or type(k) == "number" then keys[#keys + 1] = k end
            end
            table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
            out[#out + 1] = "{"
            for i, k in ipairs(keys) do
                if i > 1 then out[#out + 1] = "," end
                out[#out + 1] = '"' .. escape(tostring(k)) .. '":'
                encode(v[k], depth + 1, out)
            end
            out[#out + 1] = "}"
        end
    else
        out[#out + 1] = "null"
    end
end

function ns.toJSON(v)
    local out = {}
    encode(v, 0, out)
    return table.concat(out)
end

---------------------------------------------------------------------------
-- Base64 (pure arithmetic, works without the bit library).
---------------------------------------------------------------------------
local B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

function ns.base64(data)
    local out = {}
    for i = 1, #data, 3 do
        local a, b, c = data:byte(i, i + 2)
        local n = a * 65536 + (b or 0) * 256 + (c or 0)
        local c1 = floor(n / 262144) % 64
        local c2 = floor(n / 4096) % 64
        local c3 = floor(n / 64) % 64
        local c4 = n % 64
        out[#out + 1] = B64:sub(c1 + 1, c1 + 1) .. B64:sub(c2 + 1, c2 + 1)
            .. (b and B64:sub(c3 + 1, c3 + 1) or "=")
            .. (c and B64:sub(c4 + 1, c4 + 1) or "=")
    end
    return table.concat(out)
end

---------------------------------------------------------------------------
-- Names of spells and items, remembered so the server can show names
-- instead of numbers. Saved with the snapshot.
---------------------------------------------------------------------------
ns.spellNames = {}
ns.itemNames = {}

function ns.spellName(id)
    id = ns.num(id)
    if not id or id <= 0 then return nil end
    local cached = ns.spellNames[id]
    if cached then return cached end
    local name
    if C_Spell and C_Spell.GetSpellName then name = ns.safe(C_Spell.GetSpellName, id) end
    if not name and GetSpellInfo then
        local r = ns.safe(GetSpellInfo, id)
        if type(r) == "table" then name = r.name else name = r end
    end
    name = ns.str(name)
    if name then ns.spellNames[id] = name end
    return name
end

function ns.rememberSpell(id, name)
    id = ns.num(id); name = ns.str(name)
    if id and id > 0 and name then ns.spellNames[id] = name end
end

function ns.itemName(id)
    id = ns.num(id)
    if not id or id <= 0 then return nil end
    local cached = ns.itemNames[id]
    if cached then return cached end
    local name
    if C_Item and C_Item.GetItemNameByID then name = ns.safe(C_Item.GetItemNameByID, id) end
    if not name and GetItemInfo then name = ns.safe(GetItemInfo, id) end
    name = ns.str(name)
    if name then ns.itemNames[id] = name end
    return name
end

function ns.now() return ns.safe(GetTime) or 0 end
