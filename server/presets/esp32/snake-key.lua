-- KEY-only snake for hot-deploy smoke test (no custom control server).
-- KEY = turn left; after game over KEY = restart.
-- Device: a4cb8fdf8440 RLCD 400x300

local CELL = 10
local COLS = math.floor(gfx.W / CELL)
local ROWS = math.floor(gfx.H / CELL)

local snake, dir, food, score, alive
local keyWas = false

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
  if key_edge() then
    if not alive then
      reset()
      return
    end
    local order = { U = "L", L = "D", D = "R", R = "U" }
    dir = order[dir]
  end
  if not alive then return end

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
  math.randomseed(millis() % 2147483647)
  reset()
  draw()
  emit("snake_started", { device = "a4cb8fdf8440" })
end

function on_loop()
  step()
  draw()
  return 180
end
