-- Snake: direction from OnlyClaws public control UI (not LAN).
-- Phone: https://onlyclaws.world/epaper/snake/
-- Poll infrequently: every-frame HTTPS stalls the game and fights cloud pending.

local CTRL = "https://onlyclaws.world/epaper/snake"
local CELL = 10
local COLS = math.floor(gfx.W / CELL)
local ROWS = math.floor(gfx.H / CELL)
local POLL_EVERY = 5   -- ticks between /dir polls (~0.9s)
local POLL_MS = 450    -- short timeout; miss is ok

local snake, dir, food, score, alive
local keyWas = false
local pollCd = 0

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
  pollCd = 0
end

local function key_edge()
  local down = input.key()
  local edge = down and not keyWas
  keyWas = down
  return edge
end

local function poll_ctrl()
  local code, body = http.get(CTRL .. "/dir", POLL_MS)
  if code ~= 200 or not body then return end
  if body:find('"restart"%s*:%s*true') then
    reset()
    return
  end
  local d = body:match('"dir"%s*:%s*"([UDLR])"')
  if not d then return end
  if (d == "U" and dir ~= "D") or (d == "D" and dir ~= "U")
      or (d == "L" and dir ~= "R") or (d == "R" and dir ~= "L") then
    dir = d
  end
end

local function draw()
  gfx.clear(0)
  gfx.fill_rect(food.x * CELL, food.y * CELL, CELL, CELL, 1)
  for _, p in ipairs(snake) do
    gfx.fill_rect(p.x * CELL, p.y * CELL, CELL - 1, CELL - 1, 1)
  end
  gfx.text(4, 16, "sc " .. tostring(score), 1)
  if not alive then gfx.text(4, 36, "GAME OVER", 1) end
  gfx.flush()
end

local function step()
  if pollCd <= 0 then
    poll_ctrl()
    pollCd = POLL_EVERY
  else
    pollCd = pollCd - 1
  end

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
  reset()
  draw()
end

function on_loop()
  step()
  draw()
  return 160
end
