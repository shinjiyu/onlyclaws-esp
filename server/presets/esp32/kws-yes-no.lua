-- Say "yes" or "no": on-device keyword spotting with the micro_speech model
-- delivered through /api/ml/models (no reflash). Emits "heard" events.
local MODEL = "micro_speech"
local THRESH = 0.7
local last, n, ready = "-", 0, false

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
  show("Say yes / no", "arena " .. i.arena_used .. " B", "v" .. i.version)
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
  if r.score >= THRESH and (r.label == "yes" or r.label == "no") then
    last = r.label
    emit("heard", {word = r.label, score = r.score, ms = r.ms})
    audio.beep(r.label == "yes" and 1200 or 500, 80)
  elseif n % 10 == 1 then
    emit("ml_tick", {n = n, label = r.label, score = r.score, ms = r.ms, scores = r.scores})
  end
  show("Say yes / no", "heard: " .. last, string.format("%s %.2f %dms", r.label, r.score, r.ms))
end
