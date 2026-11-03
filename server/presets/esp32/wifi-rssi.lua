-- Local Wi-Fi quality, human-readable. No HTTP / emit.
-- RSSI is translated to bars + what the link is good for.

local SAMPLE_MS = 4000
local PAINT_FAST_MS = 12000
local PAINT_SLOW_MS = 30000
local CAP = 90
local RSSI_HI = -35
local RSSI_LO = -90

local buf, len, head = {}, 0, 0
local last_paint = 0
local last_rssi = nil
local drops = 0

local function push(v)
  head = (head % CAP) + 1
  buf[head] = v
  if len < CAP then len = len + 1 end
end

local function at(i)
  return buf[(head - len + i - 1) % CAP + 1]
end

-- Cisco-style usable thresholds, in plain language.
-- -30..-50  5/5  video/calls fine
-- -51..-60  4/5  video OK
-- -61..-67  3/5  web OK, video may lag   (-67 = min for stable data)
-- -68..-75  2/5  slow pages, stalls
-- -76..-89  1/5  often drops
-- else      0/5  no link
local function grade(rssi)
  if not rssi or rssi == 0 then
    return 0, "NO WIFI", "not connected"
  end
  if rssi >= -50 then return 5, "STRONG", "video and calls OK" end
  if rssi >= -60 then return 4, "GOOD", "video OK" end
  if rssi >= -67 then return 3, "OK", "web OK, video lag" end
  if rssi >= -75 then return 2, "WEAK", "slow, may stall" end
  return 1, "POOR", "often drops"
end

local function clip(s, n)
  s = s or ""
  if #s <= n then return s end
  return s:sub(1, n - 1) .. "~"
end

local function stats()
  if len == 0 then return nil, nil, nil end
  local mn, mx, sum, n = 0, -200, 0, 0
  for i = 1, len do
    local v = at(i)
    if v and v < 0 then
      if n == 0 or v < mn then mn = v end
      if n == 0 or v > mx then mx = v end
      sum = sum + v
      n = n + 1
    end
  end
  if n == 0 then return nil, nil, nil end
  return mn, math.floor(sum / n + 0.5), mx
end

local function y_of(rssi, y, h)
  local v = rssi or RSSI_LO
  if v > RSSI_HI then v = RSSI_HI end
  if v < RSSI_LO then v = RSSI_LO end
  local t = (v - RSSI_LO) / (RSSI_HI - RSSI_LO)
  return math.floor(y + h - t * h)
end

local function bars(x, y, filled)
  for i = 1, 5 do
    local bw, gap = 14, 5
    local bh = 6 + i * 7
    local bx = x + (i - 1) * (bw + gap)
    local by = y - bh
    gfx.rect(bx, by, bw, bh, 1)
    if i <= filled then
      gfx.fill_rect(bx + 2, by + 2, bw - 4, bh - 4, 1)
    end
  end
end

local function chart(x, y, w, h)
  gfx.rect(x, y, w, h, 1)
  -- "OK" floor (-67) and "GOOD" (-50)
  gfx.line(x, y_of(-50, y, h), x + w, y_of(-50, y, h), 1)
  gfx.line(x, y_of(-67, y, h), x + w, y_of(-67, y, h), 1)
  if len < 2 then return end
  local inner = w - 2
  local prevx, prevy
  for i = 1, len do
    local px = x + 1 + math.floor((i - 1) * inner / (CAP - 1))
    local py = y_of(at(i), y, h)
    if prevx then gfx.line(prevx, prevy, px, py, 1) end
    prevx, prevy = px, py
  end
end

local function sample()
  local r = net.rssi and net.rssi() or wifi_rssi()
  if type(r) ~= "number" then r = 0 end
  if r == 0 then
    drops = drops + 1
    r = nil
  end
  last_rssi = r
  push(r)
end

local function paint()
  local W, H = gfx.W, gfx.H
  local small = W < 600
  local ssid = (net.ssid and net.ssid() or wifi_ssid() or "")
  local nbar, word, meaning = grade(last_rssi)
  local mn, avg, mx = stats()
  local span_m = math.floor(len * SAMPLE_MS / 60000)

  gfx.clear(0)
  gfx.fill_rect(0, 0, W, small and 26 or 36, 1)
  gfx.text(6, small and 18 or 26, string.format("%s  %d/5", word, nbar), 0)

  bars(8, small and 78 or 96, nbar)
  gfx.text(110, small and 70 or 88, meaning, 1)
  gfx.text(6, small and 96 or 118, clip(ssid, small and 26 or 40), 1)

  local top = small and 108 or 132
  local bot = small and 40 or 56
  local x, y = 8, top
  local w, h = W - 16, H - top - bot
  if h < 70 then h = 70 end
  chart(x, y, w, h)
  gfx.text(x + 2, y + 14, "strong", 1)
  gfx.text(x + 2, y + h - 4, "weak", 1)

  local _, avg_word = grade(avg)
  local foot = string.format("%dmin  usually %s", span_m, avg_word or "--")
  if drops > 0 then foot = foot .. "  drop " .. tostring(drops) end
  gfx.text(6, H - (small and 12 or 16), clip(foot, small and 28 or 48), 1)
  gfx.flush()
  last_paint = millis()
end

function on_start()
  sample()
  paint()
end

function on_loop()
  sample()
  local slow = gfx.slow and gfx.slow()
  local every = slow and PAINT_SLOW_MS or PAINT_FAST_MS
  if (millis() - last_paint) >= every then
    paint()
  end
  return SAMPLE_MS
end
