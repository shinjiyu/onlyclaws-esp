-- Snake: phone D-pad via board LAN page (any browser) or BLE.
-- Game Over shows Wi-Fi SSID + QR to http://<ip>/

local CELL = 10
local COLS = math.floor(gfx.W / CELL)
local ROWS = math.floor(gfx.H / CELL)

local snake, dir, food, score, alive
local keyWas = false
local ipShown, ssidShown, ctrlUrl = "", "", ""

local function spawn_food()
  while true do
    local fx, fy = math.random(0, COLS - 1), math.random(0, ROWS - 1)
    local hit = false
    for _, p in ipairs(snake) do
      if p.x == fx and p.y == fy then hit = true break end
    end
    if not hit then return { x = fx, y = fy } end
  end
end

local function reset()
  snake = { { x = math.floor(COLS / 2), y = math.floor(ROWS / 2) } }
  dir = "R"
  food = spawn_food()
  score = 0
  alive = true
  keyWas = false
end

local function key_edge()
  local down = input.key()
  local edge = down and not keyWas
  keyWas = down
  return edge
end

local function apply_pad()
  if ble.restart and ble.restart() then
    reset()
    return
  end
  local d = ble.dir and ble.dir() or nil
  if not d then return end
  if (d == "U" and dir ~= "D") or (d == "D" and dir ~= "U")
      or (d == "L" and dir ~= "R") or (d == "R" and dir ~= "L") then
    dir = d
  end
end

local function draw_game_over()
  gfx.clear(0)
  -- Compact header; large centered QR for WeChat / camera scanners.
  gfx.text(4, 16, "GAME OVER sc " .. tostring(score), 1)
  local wifiLine = "WiFi:" .. (ssidShown ~= "" and ssidShown or "?")
  gfx.text(4, 34, wifiLine, 1)
  if ctrlUrl ~= "" then
    gfx.text(4, 52, ctrlUrl, 1)
  end

  if ctrlUrl ~= "" and gfx.qr then
    -- version2=25 + quiet4*2 => 33 modules. Fit ~240px box under text.
    local box = 240
    local modules_est = 33  -- 25 + 8 quiet
    local scale = math.floor(box / modules_est)
    if scale < 6 then scale = 6 end
    if scale > 8 then scale = 8 end
    local side = modules_est * scale
    local qx = math.floor((gfx.W - side) / 2)
    local qy = 64
    if qy + side > gfx.H - 4 then qy = gfx.H - side - 4 end
    local modules = gfx.qr(qx, qy, scale, ctrlUrl, 1)
    if not modules or modules == 0 then
      gfx.text(qx, qy + 40, "QR fail", 1)
    end
  end
  gfx.flush()
end

local function draw()
  if not alive then
    draw_game_over()
    return
  end
  gfx.clear(0)
  gfx.fill_rect(food.x * CELL, food.y * CELL, CELL, CELL, 1)
  for _, p in ipairs(snake) do
    gfx.fill_rect(p.x * CELL, p.y * CELL, CELL - 1, CELL - 1, 1)
  end
  local link = (ble.connected and ble.connected()) and "PAD" or ".."
  gfx.text(4, 14, "sc " .. tostring(score) .. " " .. link, 1)
  if ssidShown ~= "" then gfx.text(4, 30, ssidShown, 1) end
  if ipShown ~= "" then gfx.text(4, 46, ipShown, 1) end
  gfx.flush()
end

local function step()
  apply_pad()

  if not alive then
    if key_edge() then reset() end
    return
  end

  if key_edge() then
    local order = { U = "L", L = "D", D = "R", R = "U" }
    dir = order[dir]
  end

  local head = snake[1]
  local nx, ny = head.x, head.y
  if dir == "U" then ny = ny - 1
  elseif dir == "D" then ny = ny + 1
  elseif dir == "L" then nx = nx - 1
  else nx = nx + 1 end

  if nx < 0 or ny < 0 or nx >= COLS or ny >= ROWS then
    alive = false
    audio.beep(200, 120)
    return
  end
  for _, p in ipairs(snake) do
    if p.x == nx and p.y == ny then
      alive = false
      audio.beep(200, 120)
      return
    end
  end

  table.insert(snake, 1, { x = nx, y = ny })
  if nx == food.x and ny == food.y then
    score = score + 1
    audio.beep(1200, 40)
    food = spawn_food()
  else
    table.remove(snake)
  end
end

function on_start()
  math.randomseed(millis())
  ipShown = (net.ip and net.ip()) or ""
  ssidShown = (net.ssid and net.ssid()) or ""
  if ipShown ~= "" then
    -- No trailing slash — slightly shorter payload, same page.
    ctrlUrl = "http://" .. ipShown
  else
    ctrlUrl = ""
  end
  reset()
  draw()
end

function on_loop()
  step()
  draw()
  return 140
end
