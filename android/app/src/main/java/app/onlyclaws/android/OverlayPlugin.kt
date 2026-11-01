package app.onlyclaws.android

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.PorterDuff
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Choreographer
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import kotlin.math.hypot

/**
 * Transparent overlay. A script that defines `onFrame` is pumped by this
 * plugin. Scripts draw with `gfx` into a system overlay. `onFrame` is
 * pumped here. Pointer hits on drawn pixels call `onPointer`.
 * The page (`web`) is a separate plugin.
 */
class OverlayPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    val metrics = ScreenMetrics()
    private val buffer = SceneBuffer(onLog)
    private val window = OverlayWindow(app, onLog, ::onPointer)
    val web = WebOverlay(app, onLog, ::stopPage)
    private var saved = Frame.EMPTY
    private var pumping = false
    private var lastNanos = 0L
    private val choreographer by lazy { Choreographer.getInstance() }
    private val frameCallback: Choreographer.FrameCallback = object : Choreographer.FrameCallback {
        override fun doFrame(nanos: Long) {
            if (!pumping) return
            val dt = if (lastNanos == 0L) 0.016 else (nanos - lastNanos) / 1_000_000_000.0
            lastNanos = nanos
            choreographer.postFrameCallback(this)
            container.enterFrame(dt)
        }
    }

    override fun install(scope: JsScope) {
        scope.define("ui") {
            getter("w") { screenDp().first }
            getter("W") { screenDp().first }
            getter("h") { screenDp().second }
            getter("H") { screenDp().second }
            getter("keyboard") { metrics.keyboard }
            getter("safe") {
                mapOf(
                    "top" to metrics.top,
                    "right" to metrics.right,
                    "bottom" to metrics.bottom,
                    "left" to metrics.left,
                )
            }
        }
        val measure = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 16f }
        scope.define("gfx") {
            fn("clear") { args ->
                if (allowed()) buffer.fill(argb(args.number(0)))
            }
            fn("rect") { args ->
                require(args.size >= 5) { "gfx.rect(x, y, w, h, color)" }
                if (allowed()) {
                    buffer.add(
                        Op.Rect(
                            args.number(0).toFloat(),
                            args.number(1).toFloat(),
                            args.number(2).toFloat(),
                            args.number(3).toFloat(),
                            argb(args.number(4)),
                        ),
                    )
                }
            }
            fn("line") { args ->
                require(args.size >= 5) { "gfx.line(x1, y1, x2, y2, color)" }
                if (allowed()) {
                    buffer.add(
                        Op.Line(
                            args.number(0).toFloat(),
                            args.number(1).toFloat(),
                            args.number(2).toFloat(),
                            args.number(3).toFloat(),
                            argb(args.number(4)),
                        ),
                    )
                }
            }
            fn("circle") { args ->
                require(args.size >= 4) { "gfx.circle(x, y, r, color)" }
                if (allowed()) {
                    buffer.add(
                        Op.Circle(
                            args.number(0).toFloat(),
                            args.number(1).toFloat(),
                            args.number(2).toFloat(),
                            argb(args.number(3)),
                        ),
                    )
                }
            }
            fn("text") { args ->
                require(args.size >= 4) { "gfx.text(x, y, text, color)" }
                if (allowed()) {
                    buffer.add(
                        Op.Text(
                            args.number(0).toFloat(),
                            args.number(1).toFloat(),
                            args.string(2),
                            argb(args.number(3)),
                        ),
                    )
                }
            }
            fn("text_width") { args -> measure.measureText(args.string(0)).toDouble() }
        }
    }

    override fun beforeSwap() {
        saved = buffer.snapshot()
        buffer.clear()
    }

    override fun afterSwap(ok: Boolean, pumpsFrames: Boolean) {
        if (!ok) {
            buffer.restore(saved)
            return
        }
        main.post { if (pumpsFrames) startPump() else stopPump() }
    }

    override fun afterTurn() {
        val frame = buffer.snapshot()
        main.post { window.present(frame) }
    }

    override fun setDrawing(enabled: Boolean) {
        buffer.accepting = enabled
    }

    private fun startPump() {
        if (pumping) return
        pumping = true
        lastNanos = 0L
        choreographer.postFrameCallback(frameCallback)
    }

    private fun stopPump() {
        pumping = false
        choreographer.removeFrameCallback(frameCallback)
    }

    private var denied = false

    private fun allowed(): Boolean {
        if (Settings.canDrawOverlays(app)) {
            denied = false
            return true
        }
        if (!denied) {
            denied = true
            onLog("浮层未授权")
        }
        return false
    }

    fun attachPage(host: ViewGroup) = web.attach(host)

    fun detachPage() = web.detach()

    fun backPage(): Boolean = web.back()

    private fun stopPage() {
        container.fire("onAction", mapOf("id" to "stop", "action" to "stop"))
    }

    /** After the user grants overlay, load the saved script once. */
    fun resumeIfNeeded() {
        if (!denied || !Settings.canDrawOverlays(app)) return
        denied = false
        val source = container.readActive(app) ?: return
        container.load(source) { result ->
            result.onFailure { onLog("脚本未加载：${it.message}") }
        }
    }

    private fun screenDp(): Pair<Double, Double> {
        val (w, h) = screenPx(app.getSystemService(WindowManager::class.java))
        val d = app.resources.displayMetrics.density.toDouble()
        return w / d to h / d
    }

    private fun onPointer(action: String, x: Double, y: Double) {
        container.fire("onPointer", mapOf("action" to action, "x" to x, "y" to y))
    }
}

private data class Frame(val ops: List<Op>, val backdrop: Int) {
    val empty: Boolean get() = ops.isEmpty() && Color.alpha(backdrop) == 0

    fun hits(x: Double, y: Double, screenW: Float, screenH: Float): Boolean {
        val keep = chooseTouchBoxes(ops.map { it.span() }, screenW, screenH)
        val px = x.toFloat()
        val py = y.toFloat()
        for (i in ops.indices.reversed()) {
            if (!keep[i]) continue
            if (ops[i].contains(px, py)) return true
        }
        return false
    }

    companion object {
        val EMPTY = Frame(emptyList(), Color.TRANSPARENT)
    }
}

private sealed class Op {
    data class Rect(val x: Float, val y: Float, val w: Float, val h: Float, val color: Int) : Op()
    data class Line(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val color: Int) : Op()
    data class Circle(val x: Float, val y: Float, val r: Float, val color: Int) : Op()
    data class Text(val x: Float, val y: Float, val text: String, val color: Int) : Op()
}

private fun Op.span(): TouchBox = when (this) {
    is Op.Rect -> TouchBox(w, h)
    is Op.Line -> TouchBox(kotlin.math.abs(x2 - x1), kotlin.math.abs(y2 - y1))
    is Op.Circle -> TouchBox(r * 2f, r * 2f)
    is Op.Text -> TouchBox(16f, 16f)
}

/**
 * A wash that covers the screen is paint. Touches on it belong to the launcher,
 * otherwise a wallpaper drawn with gfx.clear and full-width bands cannot be swiped.
 * A few controls that together stay under half the screen keep their own hits.
 */
internal data class TouchBox(val w: Float, val h: Float)

internal fun chooseTouchBoxes(boxes: List<TouchBox>, screenW: Float, screenH: Float): BooleanArray {
    val keep = BooleanArray(boxes.size) { true }
    if (screenW <= 0f || screenH <= 0f) return keep
    val screen = screenW * screenH
    val cover = boxes.sumOf { (it.w.coerceAtLeast(0f) * it.h.coerceAtLeast(0f)).toDouble() }
    if (cover < screen * 0.45) return keep
    for (i in boxes.indices) {
        val box = boxes[i]
        val wide = box.w >= screenW * 0.8f
        val tall = box.h >= screenH * 0.8f
        val bulky = box.w * box.h >= screen * 0.06f
        keep[i] = !wide && !tall && !bulky
    }
    return keep
}

private class SceneBuffer(private val onLog: (String) -> Unit) {
    private val ops = mutableListOf<Op>()
    private var backdrop = Color.TRANSPARENT
    private var capped = false
    var accepting = true

    fun snapshot(): Frame = Frame(ops.toList(), backdrop)

    fun clear() {
        ops.clear()
        backdrop = Color.TRANSPARENT
        capped = false
    }

    fun restore(frame: Frame) {
        ops.clear()
        ops.addAll(frame.ops)
        backdrop = frame.backdrop
        capped = false
    }

    fun fill(color: Int) {
        if (!accepting) return
        ops.clear()
        backdrop = color
        capped = false
    }

    fun add(op: Op) {
        if (!accepting) return
        if (ops.size >= 2000) {
            if (!capped) {
                capped = true
                onLog("画面指令过多")
            }
            return
        }
        ops += op
    }
}

private fun Op.color(): Int = when (this) {
    is Op.Rect -> color
    is Op.Line -> color
    is Op.Circle -> color
    is Op.Text -> color
}

private fun Op.contains(x: Float, y: Float): Boolean = when (this) {
    is Op.Rect -> x >= this.x && y >= this.y && x < this.x + w && y < this.y + h
    is Op.Line -> {
        val dx = x2 - x1
        val dy = y2 - y1
        val len2 = dx * dx + dy * dy
        val t = if (len2 == 0f) 0f else (((x - x1) * dx + (y - y1) * dy) / len2).coerceIn(0f, 1f)
        hypot((x1 + t * dx - x).toDouble(), (y1 + t * dy - y).toDouble()) <= 8.0
    }
    is Op.Circle -> hypot((x - this.x).toDouble(), (y - this.y).toDouble()) <= r
    is Op.Text -> {
        val paint = Paint().apply { textSize = 16f }
        val w = paint.measureText(text)
        x >= this.x && x < this.x + w && y >= this.y - 16f && y < this.y
    }
}

private fun Op.boundsPx(density: Float): Rect = when (this) {
    is Op.Rect -> pxRect(x, y, x + w, y + h, density)
    is Op.Line -> pxRect(
        minOf(x1, x2) - 8f,
        minOf(y1, y2) - 8f,
        maxOf(x1, x2) + 8f,
        maxOf(y1, y2) + 8f,
        density,
    )
    is Op.Circle -> pxRect(x - r, y - r, x + r, y + r, density)
    is Op.Text -> {
        val paint = Paint().apply { textSize = 16f }
        pxRect(x, y - 16f, x + paint.measureText(text), y, density)
    }
}

private fun pxRect(l: Float, t: Float, r: Float, b: Float, density: Float): Rect {
    val left = (l * density).toInt()
    val top = (t * density).toInt()
    val right = (r * density).toInt().coerceAtLeast(left + 1)
    val bottom = (b * density).toInt().coerceAtLeast(top + 1)
    return Rect(left, top, right, bottom)
}

class ScreenMetrics {
    @Volatile var top = 0.0
    @Volatile var right = 0.0
    @Volatile var bottom = 0.0
    @Volatile var left = 0.0
    @Volatile var keyboard = 0.0
}

private class OverlayWindow(
    private val app: Context,
    private val onLog: (String) -> Unit,
    private val pointer: (String, Double, Double) -> Unit,
) {
    private val wm = app.getSystemService(WindowManager::class.java)
    private val density = app.resources.displayMetrics.density
    private val stage = StageView(app)
    private val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
        PixelFormat.TRANSLUCENT,
    ).apply { gravity = Gravity.TOP or Gravity.START }
    private var added = false
    private var tracking = false
    private var announced = false
    private var failed = false

    fun present(frame: Frame) {
        if (frame.empty) {
            clear()
            return
        }
        stage.frame = frame
        stage.originX = 0f
        stage.originY = 0f
        if (!added) {
            stage.setOnTouchListener { _, event -> onTouch(event) }
            try {
                wm.addView(stage, params)
                added = true
                (app as? OcApp)?.chat?.raise()
            } catch (_: Throwable) {
                if (!failed) {
                    failed = true
                    onLog("浮层打不开")
                }
                return
            }
        }
        // Keep the window full-screen; only redraw. Moving layout every frame stutters.
        applyTouchable(frame)
        stage.invalidate()
        if (!announced) {
            announced = true
            onLog("浮层已打开")
        }
    }

    private fun clear() {
        if (added) {
            wm.removeView(stage)
            added = false
        }
        tracking = false
        announced = false
    }

    private fun onTouch(event: MotionEvent): Boolean {
        val x = event.rawX / density.toDouble()
        val y = event.rawY / density.toDouble()
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                val (sw, sh) = screenPx(wm)
                tracking = stage.frame.hits(x, y, sw / density, sh / density)
                if (!tracking) return false
                pointer("down", x, y)
            }
            MotionEvent.ACTION_MOVE -> {
                if (!tracking) return false
                pointer("move", x, y)
            }
            MotionEvent.ACTION_UP -> {
                if (!tracking) return false
                tracking = false
                pointer("up", x, y)
            }
            MotionEvent.ACTION_CANCEL -> {
                if (!tracking) return false
                tracking = false
                pointer("cancel", x, y)
            }
            else -> return tracking
        }
        return true
    }

    private fun applyTouchable(frame: Frame) {
        val (sw, sh) = screenPx(wm)
        val screenW = sw / density
        val screenH = sh / density
        val opaque = frame.ops.filter { Color.alpha(it.color()) > 0 }
        val keep = chooseTouchBoxes(opaque.map { it.span() }, screenW, screenH)
        val washed = opaque.indices.any { !keep[it] } || Color.alpha(frame.backdrop) > 0 && opaque.isEmpty()
        val region = android.graphics.Region()
        for (i in opaque.indices) {
            if (!keep[i]) continue
            region.op(opaque[i].boundsPx(density), android.graphics.Region.Op.UNION)
        }
        val ok = runCatching {
            val getRoot = View::class.java.getDeclaredMethod("getViewRootImpl")
            getRoot.isAccessible = true
            val root = getRoot.invoke(stage) ?: return@runCatching false
            val method = root.javaClass.methods.firstOrNull {
                it.name == "setTouchableRegion" && it.parameterTypes.size == 1
            } ?: root.javaClass.declaredMethods.first {
                it.name == "setTouchableRegion" && it.parameterTypes.size == 1
            }.also { it.isAccessible = true }
            method.invoke(root, region)
            true
        }.getOrDefault(false)
        // Empty or a failed hole-punch on a full-screen wash: let the launcher swipe.
        val pass = region.isEmpty || (!ok && washed)
        val flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED or
            if (pass) WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE else 0
        if (params.flags != flags) {
            params.flags = flags
            if (added) {
                wm.updateViewLayout(stage, params)
                (app as? OcApp)?.chat?.raise()
            }
        }
        if (!ok && !region.isEmpty) {
            // keep receiving touches; onTouch still filters misses for gesture tracking
        }
    }

    private class StageView(context: Context) : View(context) {
        var frame: Frame = Frame.EMPTY
        var originX = 0f
        var originY = 0f
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)

        init {
            setBackgroundColor(Color.TRANSPARENT)
        }

        override fun onDraw(canvas: Canvas) {
            canvas.drawColor(Color.TRANSPARENT, PorterDuff.Mode.CLEAR)
            val d = resources.displayMetrics.density
            canvas.save()
            canvas.translate(-originX, -originY)
            canvas.scale(d, d)
            if (Color.alpha(frame.backdrop) > 0) canvas.drawColor(frame.backdrop)
            paint.style = Paint.Style.FILL
            paint.textSize = 16f
            for (op in frame.ops) {
                when (op) {
                    is Op.Rect -> {
                        paint.color = op.color
                        canvas.drawRect(op.x, op.y, op.x + op.w, op.y + op.h, paint)
                    }
                    is Op.Line -> {
                        paint.color = op.color
                        paint.style = Paint.Style.STROKE
                        paint.strokeWidth = 2f
                        canvas.drawLine(op.x1, op.y1, op.x2, op.y2, paint)
                        paint.style = Paint.Style.FILL
                    }
                    is Op.Circle -> {
                        paint.color = op.color
                        canvas.drawCircle(op.x, op.y, op.r, paint)
                    }
                    is Op.Text -> {
                        paint.color = op.color
                        canvas.drawText(op.text, op.x, op.y, paint)
                    }
                }
            }
            canvas.restore()
        }
    }
}

private fun argb(n: Double): Int {
    if (n.isNaN()) return Color.TRANSPARENT
    val bits = n.toLong() and 0xFFFFFFFFL
    if (bits == 0L) return Color.TRANSPARENT
    val color = if (bits <= 0xFFFFFFL) 0xFF000000L or bits else bits
    return color.toInt()
}

private fun screenPx(wm: WindowManager): Pair<Int, Int> {
    return if (Build.VERSION.SDK_INT >= 30) {
        val b = wm.maximumWindowMetrics.bounds
        b.width() to b.height()
    } else {
        val p = Point()
        @Suppress("DEPRECATION")
        wm.defaultDisplay.getRealSize(p)
        p.x to p.y
    }
}

