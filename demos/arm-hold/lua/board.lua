-- RoArm: report pose once, then hold. No gfx (headless product).

function on_start()
  local name = arm.name and arm.name() or "?"
  log("arm-hold start", name)
  local p = arm.feedback()
  if not p then
    emit("arm_hold_fail", { reason = "feedback" })
    stop()
    return
  end
  emit("arm_hold", {
    driver = name,
    q = p.q,
    base = p.base,
    shoulder = p.shoulder,
    elbow = p.elbow,
    hand = p.hand,
  })
  -- Soft re-command current pose (hold).
  arm.stream({ q = p.q, spd = 200 })
end

function on_loop()
  return 5000
end
