-- Bird or not: listens in ~3 s windows with the bird_detect model (trained on
-- DCASE 2018 warblr + freefield) delivered through /api/ml/models.
-- Emits "bird" events when a window scores above THRESH.
local MODEL = "bird_detect"
local THRESH = 0.7
local n, hits, last, ready = 0, 0, "-", false

local function show(l1, l2, l3)
  gfx.clear(0)
  gfx.text(16, 60, l1)
  if l2 then gfx.text(16, 120, l2) end
  if l3 then gfx.text(16, 180, l3) end
  gfx.flush()
end

function on_start()
  show("ml: loading " .. MODEL)
  local ok, err = ml.load(MODEL)
  if not ok then
    show("ml load failed", tostring(err))
    emit("ml_error", {err = tostring(err)})
    return
  end
  local i = ml.info(MODEL)
  ready = true
  show("Listening for birds", "arena " .. i.arena_used .. " B", "v" .. i.version)
  emit("ml_ready", {version = i.version, arena = i.arena_used, inputs = i.inputs})
end

function on_loop()
  if not ready then return end
  local r, err = ml.listen(MODEL)
  if not r then
    emit("ml_error", {err = tostring(err)})
    return
  end
  n = n + 1
  local p = r.scores[2]
  if p >= THRESH then
    hits = hits + 1
    last = string.format("#%d %.2f", n, p)
    emit("bird", {score = p, n = n, ms = r.ms})
    audio.beep(1800, 60)
  elseif n % 5 == 1 then
    emit("ml_tick", {n = n, bird = p, ms = r.ms})
  end
  show("Bird? " .. (p >= THRESH and "YES" or "no"),
       string.format("p=%.2f  %dms", p, r.ms),
       "hits " .. hits .. "  last " .. last)
end
