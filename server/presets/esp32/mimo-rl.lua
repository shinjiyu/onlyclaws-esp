-- MiMo-V2.6 RL clock for OnlyClaws panels.
-- Layout scales to gfx.W/H (RLCD 400x300 or ePaper 800x480).
-- Face stays up. HTTP never paints a "loading" screen.
-- Cost ticks locally every second; network only refreshes baselines.

local BASE = "https://mimo.xiaomi.com/rl/api"
local TICK_MS = 1000
-- Status API is often 1.5–4s+ on TLS; keep pulls sparse so the clock stays smooth.
local FETCH_MS = 12000
local HTTP_MS = 4500
local cache = { at = 0, fetch_at = 0, turn = 0, fails = 0, last_ok = 0 }
local colon = true

local GLYPH = {
  ["0"] = { "01110", "10001", "10001", "10001", "10001", "10001", "01110" },
  ["1"] = { "00100", "01100", "00100", "00100", "00100", "00100", "01110" },
  ["2"] = { "01110", "10001", "00001", "00110", "01000", "10000", "11111" },
  ["3"] = { "01110", "10001", "00001", "00110", "00001", "10001", "01110" },
  ["4"] = { "00010", "00110", "01010", "10010", "11111", "00010", "00010" },
  ["5"] = { "11111", "10000", "11110", "00001", "00001", "10001", "01110" },
  ["6"] = { "01110", "10000", "11110", "10001", "10001", "10001", "01110" },
  ["7"] = { "11111", "00001", "00010", "00100", "01000", "01000", "01000" },
  ["8"] = { "01110", "10001", "10001", "01110", "10001", "10001", "01110" },
  ["9"] = { "01110", "10001", "10001", "01111", "00001", "00001", "01110" },
  [","] = { "00000", "00000", "00000", "00000", "00100", "00100", "01000" },
  ["$"] = { "00100", "01110", "10100", "01110", "00101", "01110", "00100" },
  ["-"] = { "00000", "00000", "00000", "11111", "00000", "00000", "00000" },
  [" "] = { "00000", "00000", "00000", "00000", "00000", "00000", "00000" },
}

local function layout()
  local W, H = gfx.W, gfx.H
  local small = (W < 600) or (H < 400)
  return {
    W = W,
    H = H,
    small = small,
    header_h = small and 28 or 48,
    gap = small and 8 or 20,
    margin = small and 6 or 12,
    pad = small and 8 or 16,
    digit = small and 2 or 5,
    box_top = small and 34 or 60,
    footer = small and false or true,
  }
end

local function draw_big(x, y, s, scale)
  for i = 1, #s do
    local g = GLYPH[s:sub(i, i)]
    if g then
      for r = 1, 7 do
        local row = g[r]
        for c = 1, 5 do
          if row:sub(c, c) == "1" then
            gfx.fill_rect(x + (c - 1) * scale, y + (r - 1) * scale, scale, scale, 1)
          end
        end
      end
    end
    x = x + 6 * scale
  end
end

local function jnum(s, key)
  return tonumber(s:match('"' .. key .. '"%s*:%s*(-?%d+%.?%d*[eE]?[%+%-]?%d*)'))
end

local function jstr(s, key)
  return s:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

local function jobj(s, key)
  return s:match('"' .. key .. '"%s*:(%b{})')
end

local function commas(n)
  if not n then return "$-,--" end
  n = math.floor(n + 0.5)
  if n < 0 then n = 0 end
  local s, out = tostring(n), ""
  while #s > 3 do
    out = "," .. s:sub(-3) .. out
    s = s:sub(1, #s - 3)
  end
  return "$" .. s .. out
end

-- Whole dollars so the glyph clock moves every second (~$3–6/s).
local function money(n)
  return commas(n)
end

local function tokens(n)
  if not n then return "--" end
  if n >= 1e9 then return string.format("%.1fB", n / 1e9) end
  if n >= 1e6 then return string.format("%.0fM", n / 1e6) end
  return tostring(math.floor(n))
end

local function samples(n)
  if not n then return "--" end
  if n >= 1000 then return string.format("%.0fk", n / 1000) end
  return tostring(math.floor(n))
end

local function get(path)
  local st, body = http.get(BASE .. path, HTTP_MS)
  if st ~= 200 or not body or body == "" then return nil end
  return body
end

local function parse_run(key, status)
  local run = jobj(status, "run") or ""
  local cost = jobj(status, "cost") or ""
  local step = jobj(status, "step") or ""
  local totals = jobj(status, "totals") or ""
  local head = jobj(status, "headline") or ""
  local score = jnum(head, "last")
  local first = jnum(head, "first")
  local prev = jnum(head, "prev")
  return {
    key = key,
    mode = jstr(run, "mode") or "?",
    last = jnum(step, "last"),
    phase = jstr(step, "phase") or "roll",
    progress = jnum(step, "progress") or 0,
    cost = jnum(cost, "so_far"),
    rate = jnum(cost, "rate_per_s") or 0,
    score = score,
    delta = (score and first) and (score - first) or nil,
    dstep = (score and prev) and (score - prev) or nil,
    tok = jnum(totals, "tokens_cum"),
    trained = jnum(totals, "trained_cum"),
  }
end

local function fetch_latest()
  local key = (cache.turn % 2 == 0) and "pro" or "flash"
  local body = get("/status?run=" .. key)
  cache.turn = cache.turn + 1
  if not body then return nil end
  local parsed = parse_run(key, body)
  parsed._at = millis()
  return key, parsed
end

-- Keep ticking forever between sparse fetches (old 30s cap froze the board).
local function live_cost(run)
  if not run or not run.cost then return nil end
  local t0 = run._at or cache.at or millis()
  local dt = (millis() - t0) / 1000
  if dt < 0 then dt = 0 end
  return run.cost + (run.rate or 0) * dt
end

local function bar(x, y, w, h, frac)
  gfx.rect(x, y, w, h, 1)
  local inner = math.floor((w - 4) * math.max(0, math.min(1, frac or 0)))
  if inner > 0 then gfx.fill_rect(x + 2, y + 2, inner, h - 4, 1) end
end

local function age_s()
  if not cache.last_ok or cache.last_ok == 0 then return nil end
  return math.floor((millis() - cache.last_ok) / 1000)
end

local function col(L, x, w, h, run)
  local pad = L.pad
  local name = (run and run.key == "flash") and "FLASH" or "PRO"
  local y = L.box_top + 10
  gfx.text(x + pad, y + 10, name, 1)
  if run and run.mode == "live" and colon then
    gfx.fill_circle(x + w - pad - 6, y + 4, L.small and 4 or 6, 1)
  else
    gfx.circle(x + w - pad - 6, y + 4, L.small and 4 or 6, 1)
  end

  y = y + (L.small and 14 or 18)
  draw_big(x + pad, y, money(live_cost(run)), L.digit)
  y = y + 7 * L.digit + (L.small and 6 or 12)

  local rate = (run and run.rate) and string.format("$%.2f/s", run.rate) or "--/s"
  local step = (run and run.last) and tostring(math.floor(run.last)) or "--"
  gfx.text(x + pad, y + 10, "step " .. step .. "  " .. rate, 1)
  y = y + (L.small and 18 or 28)

  if run and run.score then
    local d = ""
    if run.delta then d = string.format(" %+0.3f", run.delta) end
    gfx.text(x + pad, y + 10, string.format("%.3f%s", run.score, d), 1)
  else
    gfx.text(x + pad, y + 10, "--", 1)
  end
  y = y + (L.small and 18 or 28)

  local phase = (run and run.phase) or "roll"
  if phase == "rollout" then phase = "roll" end
  local pct = math.floor(((run and run.progress) or 0) * 100 + 0.5)
  if pct > 100 then pct = 100 end
  gfx.text(x + pad, y + 10, string.format("%s %d%%", phase, pct), 1)
  y = y + (L.small and 12 or 16)
  local bar_h = L.small and 10 or 14
  bar(x + pad, y, w - pad * 2, bar_h, (run and run.progress) or 0)
  y = y + bar_h + (L.small and 10 or 18)
  gfx.text(x + pad, y + 10, tokens(run and run.tok) .. " tok " .. samples(run and run.trained) .. " smp", 1)
end

local function clock_hhmmss()
  local s = math.floor(millis() / 1000)
  local hh = math.floor(s / 3600) % 24
  local mm = math.floor(s / 60) % 60
  local ss = s % 60
  if colon then
    return string.format("%02d:%02d:%02d", hh, mm, ss)
  end
  return string.format("%02d %02d %02d", hh, mm, ss)
end

local function paint()
  local L = layout()
  local W, H = L.W, L.H
  gfx.clear(0)
  gfx.fill_rect(0, 0, W, L.header_h, 1)
  gfx.text(L.pad, L.header_h - 6, "MiMo-V2.6 RL", 0)
  local age = age_s()
  local right = clock_hhmmss()
  if age and age >= 20 then
    right = string.format("stale %ds", age)
  end
  gfx.text(W - (L.small and 110 or 160), L.header_h - 6, right, 0)

  local footer_h = L.footer and 70 or 0
  local box_h = H - L.box_top - L.margin - footer_h
  if box_h < 120 then box_h = H - L.box_top - L.margin end
  local cw = math.floor((W - L.margin * 2 - L.gap) / 2)
  gfx.rect(L.margin, L.box_top, cw, box_h, 1)
  gfx.rect(L.margin + cw + L.gap, L.box_top, cw, box_h, 1)
  col(L, L.margin, cw, box_h, cache.pro)
  col(L, L.margin + cw + L.gap, cw, box_h, cache.flash)

  if L.footer then
    gfx.line(16, 380, W - 16, 380, 1)
    gfx.text(16, 412, "local tick 1s  fetch 12s", 1)
    gfx.text(16, 444, "cost keeps running offline", 1)
  end
  gfx.flush()
end

function on_start()
  paint()
end

function on_loop()
  colon = not colon
  local now = millis()
  local backoff = FETCH_MS
  if cache.fails > 0 then
    backoff = FETCH_MS + math.min(cache.fails, 4) * 4000
  end
  if (now - (cache.fetch_at or 0)) >= backoff then
    -- Mark attempt time first so a slow/failed GET cannot tight-loop.
    cache.fetch_at = now
    local key, parsed = fetch_latest()
    if key and parsed then
      cache[key] = parsed
      cache.at = parsed._at
      cache.last_ok = parsed._at
      cache.fails = 0
    else
      cache.fails = (cache.fails or 0) + 1
    end
  end
  paint()
  return TICK_MS
end
