/* Fullscreen Destiny Child Live2D wallpaper (Cubism 2).
 * Model: Moa / 忧郁摩亞（魔方少女） m077_10 — assets from Pelom777/DestinyChildLive2D (non-commercial).
 */
var thisRef = this;

window.onerror = function (msg, url, line) {
  var el = document.getElementById("boot");
  if (el) el.textContent = "Live2D 出错: " + msg;
};

function startWallpaper(modelName) {
  this.platform = (window.navigator.platform || "").toLowerCase();
  this.live2DMgr = new LAppLive2DManager();
  this.isDrawStart = false;
  this.gl = null;
  this.canvas = null;
  this.dragMgr = null;
  this.viewMatrix = null;
  this.projMatrix = null;
  this.deviceToScreen = null;
  this.isModelShown = false;
  this._idleTapAt = 0;

  initCanvas("glcanvas");
  initGL(modelName || "m077_10");
}

function initCanvas(canvasId) {
  this.canvas = document.getElementById(canvasId);
  var dpr = Math.min(2.5, window.devicePixelRatio || 1);
  this.canvas.width = Math.floor(window.innerWidth * dpr);
  this.canvas.height = Math.floor(window.innerHeight * dpr);
  // Wallpaper WebView has no real touches; keep listeners for desktop preview.
  this.canvas.addEventListener("mousemove", followPointer, false);
  this.canvas.addEventListener("mouseout", lookFront, false);
  this.canvas.addEventListener("click", function () {
    if (thisRef.live2DMgr) thisRef.live2DMgr.tapEvent(0, 0);
  }, false);
  window.addEventListener("resize", onResize, false);
}

function onResize() {
  if (!thisRef.canvas || !thisRef.gl) return;
  var dpr = Math.min(2.5, window.devicePixelRatio || 1);
  thisRef.canvas.width = Math.floor(window.innerWidth * dpr);
  thisRef.canvas.height = Math.floor(window.innerHeight * dpr);
  thisRef.gl.viewport(0, 0, thisRef.canvas.width, thisRef.canvas.height);
  rebuildMatrices();
}

function rebuildMatrices() {
  var width = thisRef.canvas.width;
  var height = thisRef.canvas.height;

  var ratio = height / width;
  var left = LAppDefine.VIEW_LOGICAL_LEFT;
  var right = LAppDefine.VIEW_LOGICAL_RIGHT;
  var bottom = -ratio;
  var top = ratio;

  thisRef.viewMatrix = new L2DViewMatrix();
  thisRef.viewMatrix.setScreenRect(left, right, bottom, top);
  // Widen pan limits so wallpaper optical nudges are not clamped.
  thisRef.viewMatrix.setMaxScreenRect(-4, 4, -4, 4);
  thisRef.viewMatrix.setMaxScale(LAppDefine.VIEW_MAX_SCALE);
  thisRef.viewMatrix.setMinScale(LAppDefine.VIEW_MIN_SCALE);

  // Optical center for curled Moa: mesh origin ≠ face/cube focal point.
  // Do NOT use model.json layout.center_* — LAppModel already centers at (0,0).
  thisRef.viewMatrix.adjustTranslate(0.07, 0.16);

  thisRef.projMatrix = new L2DMatrix44();
  thisRef.projMatrix.multScale(height / width, 1);
  thisRef.projMatrix.multScale(0.78, 0.78);

  thisRef.deviceToScreen = new L2DMatrix44();
  thisRef.deviceToScreen.multTranslate(-width / 2.0, -height / 2.0);
  thisRef.deviceToScreen.multScale(2 / width, -2 / width);
}

function initGL(modelName) {
  this.dragMgr = new L2DTargetPoint();
  rebuildMatrices();

  this.gl = getWebGLContext();
  if (!this.gl) {
    l2dError("WebGL 不可用");
    return;
  }
  Live2D.setGL(this.gl);
  // Deep purple void — reads well behind launcher icons.
  this.gl.clearColor(0.07, 0.03, 0.11, 1.0);

  changeModel(modelName);
  startDraw();
}

var drawRaf = 0;

function startDraw() {
  if (drawRaf) return;
  function tick() {
    drawRaf = requestAnimationFrame(tick);
    draw();
  }
  drawRaf = requestAnimationFrame(tick);
}

function stopDraw() {
  if (drawRaf) cancelAnimationFrame(drawRaf);
  drawRaf = 0;
}

window.addEventListener("oca-wallpaper-pause", stopDraw);
window.addEventListener("oca-wallpaper-resume", startDraw);

function readGyroLook() {
  try {
    if (typeof OcaWallpaper !== "undefined" && OcaWallpaper) {
      var tx = OcaWallpaper.tiltX ? OcaWallpaper.tiltX() : 0;
      var ty = OcaWallpaper.tiltY ? OcaWallpaper.tiltY() : 0;
      // tilt radians → Live2D drag space (~[-1,1])
      var x = Math.max(-1, Math.min(1, ty * 1.4));
      var y = Math.max(-1, Math.min(1, -tx * 1.4));
      return { x: x, y: y };
    }
  } catch (e) {}
  return null;
}

function draw() {
  MatrixStack.reset();
  MatrixStack.loadIdentity();

  var look = readGyroLook();
  if (look) {
    this.dragMgr.setPoint(look.x, look.y);
  }
  this.dragMgr.update();
  this.live2DMgr.setDrag(this.dragMgr.getX(), this.dragMgr.getY());

  // Occasional idle hit so she doesn't feel frozen when gyro is flat.
  var now = Date.now();
  if (this.isModelShown && now - this._idleTapAt > 12000 + Math.random() * 8000) {
    this._idleTapAt = now;
    try { this.live2DMgr.tapEvent(0, 0); } catch (e) {}
  }

  this.gl.clear(this.gl.COLOR_BUFFER_BIT);

  MatrixStack.multMatrix(this.projMatrix.getArray());
  MatrixStack.multMatrix(this.viewMatrix.getArray());
  MatrixStack.push();

  for (var i = 0; i < this.live2DMgr.numModels(); i++) {
    var model = this.live2DMgr.getModel(i);
    if (model == null) return;
    if (model.initialized && !model.updating) {
      model.update();
      model.draw(this.gl);
      if (!this.isModelShown) {
        this.isModelShown = true;
        var boot = document.getElementById("boot");
        if (boot) boot.classList.add("hide");
      }
    }
  }
  MatrixStack.pop();
}

function changeModel(name) {
  this.isModelShown = false;
  this.live2DMgr.reloadFlg = true;
  this.live2DMgr.count++;
  this.live2DMgr.changeModel(this.gl, name);
}

function followPointer(event) {
  if (!thisRef.deviceToScreen || !thisRef.viewMatrix) return;
  var rect = thisRef.canvas.getBoundingClientRect();
  var sx = thisRef.deviceToScreen.transformX(
    (event.clientX - rect.left) * (thisRef.canvas.width / rect.width)
  );
  var sy = thisRef.deviceToScreen.transformY(
    (event.clientY - rect.top) * (thisRef.canvas.height / rect.height)
  );
  var vx = thisRef.viewMatrix.invertTransformX(sx);
  var vy = thisRef.viewMatrix.invertTransformY(sy);
  thisRef.dragMgr.setPoint(vx, vy);
}

function lookFront() {
  thisRef.dragMgr.setPoint(0, 0);
}

function getWebGLContext() {
  var NAMES = ["webgl", "experimental-webgl", "webkit-3d", "moz-webgl"];
  for (var i = 0; i < NAMES.length; i++) {
    try {
      var ctx = this.canvas.getContext(NAMES[i], {
        alpha: true,
        premultipliedAlpha: true,
        preserveDrawingBuffer: true,
      });
      if (ctx) return ctx;
    } catch (e) {}
  }
  return null;
}

function l2dLog(msg) {
  if (LAppDefine.DEBUG_LOG) console.log(msg);
}

function l2dError(msg) {
  console.error(msg);
  var el = document.getElementById("boot");
  if (el) {
    el.classList.remove("hide");
    el.textContent = String(msg);
  }
}
