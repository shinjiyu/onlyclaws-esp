package app.onlyclaws.android

import android.app.WallpaperManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.service.wallpaper.WallpaperService
import android.view.Choreographer
import android.view.SurfaceHolder
import org.json.JSONObject
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference
import kotlin.math.atan2

/**
 * Wallpaper sits behind the launcher icons and does not take touches.
 *
 * A preset is a flat color, one line of text, the built-in `crash` clip, or an
 * HTML page. The page runs its own JavaScript behind the icons, including WebGL,
 * and may load an https 3D renderer. A script that declares `onWallpaper(dt)`
 * draws flat animation on that surface instead. [wallpaper.tilt] is smoothed
 * roll/pitch. [wallpaper.gyro] is rad/s.
 *
 *   wallpaper.load({ html: "<canvas id=\"c\"></canvas><script>/* WebGL */</script>" })
 *   wallpaper.load({ url: "https://example.com/wall.html" })
 *   wallpaper.load({ scene: "crash" })
 *   wallpaper.load({ scene: "castle" })
 *   wallpaper.load({ color: 0x1C1B19, text: "OCA", x: 24, y: 80 })
 *   function onWallpaper(dt) { wallpaper.clear(0x05060e); wallpaper.circle(ui.w / 2, ui.h / 2, 4, 0xFFFFFF) }
 */
class WallpaperPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    private val buffer = WallBuffer(onLog)
    private val motion = WallpaperMotion(app, onLog)
    private val presenters = CopyOnWriteArrayList<(WallFrame) -> Unit>()
    private val presetters = CopyOnWriteArrayList<() -> Unit>()
    private var drawing = true
    private var inFrame = false
    private var htmlThisScript = false

    @Volatile
    var animating: Boolean = false
        private set
    private var visibleEngines = 0
    private var pageEngines = 0
    private var pumping = false
    private var powerSaveHeld = false
    private var lastNanos = 0L
    private var lastDrawnNanos = 0L
    private val runGates = CopyOnWriteArrayList<() -> Unit>()
    private val choreographer by lazy { Choreographer.getInstance() }
    private val frameCallback: Choreographer.FrameCallback = object : Choreographer.FrameCallback {
        override fun doFrame(nanos: Long) {
            if (!pumping) return
            choreographer.postFrameCallback(this)
            val fps = WallpaperPower.fps(app)
            if (fps > 0 && lastDrawnNanos != 0L) {
                val minGap = 1_000_000_000.0 / fps
                if (nanos - lastDrawnNanos < minGap) return
            }
            val dt = if (lastNanos == 0L) 0.016 else (nanos - lastNanos) / 1_000_000_000.0
            lastNanos = nanos
            lastDrawnNanos = nanos
            container.enterWallpaper(dt)
        }
    }
    private val powerReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            refreshPowerSave()
        }
    }

    init {
        refreshPowerSave()
        val filter = IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED)
        if (Build.VERSION.SDK_INT >= 33) {
            app.registerReceiver(powerReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("DEPRECATION")
            app.registerReceiver(powerReceiver, filter)
        }
    }

    override fun install(scope: JsScope) = scope.define("wallpaper") {
        fn("load") { load(it.json(0)) }
        fn("clear") { args ->
            if (args.size >= 1) {
                fill(argb(args.number(0)))
            } else {
                clearPreset()
            }
        }
        fn("rect") { args ->
            require(args.size >= 5) { "wallpaper.rect(x, y, w, h, color)" }
            add(WallOp.Rect(args.number(0).toFloat(), args.number(1).toFloat(), args.number(2).toFloat(), args.number(3).toFloat(), argb(args.number(4))))
        }
        fn("line") { args ->
            require(args.size >= 5) { "wallpaper.line(x1, y1, x2, y2, color)" }
            add(WallOp.Line(args.number(0).toFloat(), args.number(1).toFloat(), args.number(2).toFloat(), args.number(3).toFloat(), argb(args.number(4))))
        }
        fn("circle") { args ->
            require(args.size >= 4) { "wallpaper.circle(x, y, r, color)" }
            add(WallOp.Circle(args.number(0).toFloat(), args.number(1).toFloat(), args.number(2).toFloat(), argb(args.number(3))))
        }
        fn("tri") { args ->
            require(args.size >= 7) { "wallpaper.tri(x1, y1, x2, y2, x3, y3, color)" }
            add(
                WallOp.Tri(
                    args.number(0).toFloat(),
                    args.number(1).toFloat(),
                    args.number(2).toFloat(),
                    args.number(3).toFloat(),
                    args.number(4).toFloat(),
                    args.number(5).toFloat(),
                    argb(args.number(6)),
                ),
            )
        }
        fn("text") { args ->
            require(args.size >= 4) { "wallpaper.text(x, y, text, color)" }
            val size = if (args.size >= 5) args.number(4).toFloat() else 16f
            add(WallOp.Text(args.number(0).toFloat(), args.number(1).toFloat(), args.string(2), argb(args.number(3)), size))
        }
        fn("text_width") { args ->
            Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 16f }.measureText(args.string(0)).toDouble()
        }
        getter("tilt") { mapOf("x" to motion.roll, "y" to motion.pitch) }
        getter("gyro") { mapOf("x" to motion.gx, "y" to motion.gy, "z" to motion.gz) }
    }

    /** Off while the outgoing script runs onStop, so it cannot wipe the preset just loaded. */
    override fun setDrawing(enabled: Boolean) {
        drawing = enabled
    }

    override fun beforeSwap() {
        buffer.clear()
        htmlThisScript = false
    }

    override fun afterTurn() {
        if (!inFrame) buffer.clear()
    }

    override fun wallpaperHook(enabled: Boolean) {
        animating = enabled
        if (!enabled) buffer.clear()
        if (enabled && !htmlThisScript) releaseStalePage()
        main.post {
            syncPump()
            if (!enabled) presetters.forEach { it() }
        }
    }

    override fun beforeWallpaper() {
        inFrame = true
        buffer.clear()
    }

    override fun afterWallpaper() {
        val frame = buffer.snapshot()
        inFrame = false
        buffer.clear()
        main.post { presenters.forEach { it(frame) } }
    }

    /** Home and preview engines share one pump. [shown] is an edge, not a level. */
    fun engineShown(shown: Boolean) {
        main.post {
            visibleEngines = (visibleEngines + if (shown) 1 else -1).coerceAtLeast(0)
            syncPump()
        }
    }

    /** An HTML wallpaper is showing, so tilt stays live for the page. */
    fun pageShown(shown: Boolean) {
        main.post {
            pageEngines = (pageEngines + if (shown) 1 else -1).coerceAtLeast(0)
            syncPump()
        }
    }

    /** True when system battery saver should freeze wallpaper animation. */
    fun powerSavePaused(): Boolean = powerSaveHeld

    /**
     * Engines re-check page active state when FPS / power-save prefs change.
     * Returns an unbind.
     */
    fun watchRunGate(onChange: () -> Unit): () -> Unit {
        runGates += onChange
        return { runGates -= onChange }
    }

    /** Call after the user changes FPS or power-save prefs in settings. */
    fun applyPowerPrefs() {
        main.post {
            refreshPowerSave()
            motion.setRate(sensorRate())
            syncPump()
        }
    }

    fun tiltX(): Double = motion.roll
    fun tiltY(): Double = motion.pitch
    fun gyroX(): Double = motion.gx
    fun gyroY(): Double = motion.gy
    fun gyroZ(): Double = motion.gz

    internal fun bind(present: (WallFrame) -> Unit, preset: () -> Unit): () -> Unit {
        presenters += present
        presetters += preset
        return {
            presenters -= present
            presetters -= preset
        }
    }

    private fun refreshPowerSave() {
        val want = WallpaperPower.pauseOnPowerSave(app)
        val saving = app.getSystemService(PowerManager::class.java)?.isPowerSaveMode == true
        val held = want && saving
        if (held == powerSaveHeld) return
        powerSaveHeld = held
        syncPump()
    }

    private fun syncPump() {
        val show = visibleEngines > 0 && !powerSaveHeld
        motion.setListening(show && (animating || pageEngines > 0))
        motion.setRate(sensorRate())
        if (animating && show) startPump() else stopPump()
        runGates.forEach { it() }
    }

    private fun sensorRate(): Int {
        val fps = WallpaperPower.fps(app)
        return if (fps in 1..30) SensorManager.SENSOR_DELAY_UI else SensorManager.SENSOR_DELAY_GAME
    }

    private fun startPump() {
        if (pumping) return
        pumping = true
        lastNanos = 0L
        lastDrawnNanos = 0L
        choreographer.postFrameCallback(frameCallback)
    }

    private fun stopPump() {
        pumping = false
        choreographer.removeFrameCallback(frameCallback)
    }

    private fun add(op: WallOp) {
        if (!drawing) return
        buffer.add(op)
    }

    private fun fill(color: Int) {
        if (!drawing) return
        buffer.fill(color)
    }

    private fun load(payload: String?): String {
        if (!drawing) return ""
        val json = payload?.let { runCatching { JSONObject(it) }.getOrNull() }
        if (json == null) {
            clearPreset()
            return ""
        }
        val html = json.optString("html")
        if (html.length > MAX_HTML) {
            onLog("壁纸页面太大")
            return "壁纸页面太大"
        }
        val url = json.optString("url").trim()
        if (url.isNotEmpty()) {
            if (!wallUrlOk(url)) {
                onLog("壁纸网址要用 https，局域网可用 http")
                return "壁纸网址要用 https，局域网可用 http"
            }
            json.put("url", url)
        } else {
            json.remove("url")
        }
        htmlThisScript = html.isNotEmpty() || url.isNotEmpty()
        PresetStore.write(app, json)
        onLog(
            when {
                url.isNotEmpty() -> "壁纸网址已写入"
                html.isNotEmpty() -> "壁纸页面已写入"
                else -> "壁纸预设已装上"
            },
        )
        showEngine()
        return ""
    }

    private fun clearPreset() {
        if (!drawing || inFrame) return
        PresetStore.clear(app)
        onLog("壁纸预设已清掉")
    }

    /** A drawing script did not load a page, so the previous HTML/url must leave the surface. */
    private fun releaseStalePage() {
        val json = PresetStore.read(app) ?: return
        val hadHtml = json.optString("html").isNotEmpty()
        val hadUrl = json.optString("url").isNotEmpty()
        if (!hadHtml && !hadUrl) return
        json.remove("html")
        json.remove("url")
        if (json.length() == 0) PresetStore.clear(app) else PresetStore.write(app, json)
        onLog("壁纸页面已让出")
    }

    private fun showEngine() {
        val name = ComponentName(app, OcWallpaperService::class.java)
        val manager = WallpaperManager.getInstance(app)
        if (manager.wallpaperInfo?.component == name) return
        main.post {
            val opened = runCatching {
                app.startActivity(
                    Intent(WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER)
                        .putExtra(WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT, name)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }.isSuccess
            onLog(if (opened) "请在系统预览里确认壁纸" else "请到应用里点一次「设为动态壁纸」")
        }
    }
}

internal object Tilt {
    fun step(current: Double, sample: Double, alpha: Double = 0.2): Double =
        current + (sample - current) * alpha

    /** Roll (x, left/right) and pitch (y, toward/away) from a gravity vector, radians. */
    fun fromGravity(x: Float, y: Float, z: Float): Pair<Double, Double> {
        val roll = atan2(x.toDouble(), z.toDouble())
        val pitch = atan2(y.toDouble(), z.toDouble())
        return roll to pitch
    }
}

private class WallpaperMotion(
    context: Context,
    private val onLog: (String) -> Unit,
) : SensorEventListener {
    private val sensors = context.getSystemService(SensorManager::class.java)
    private val rotation = sensors?.getDefaultSensor(Sensor.TYPE_GAME_ROTATION_VECTOR)
        ?: sensors?.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)
    private val gravity = if (rotation == null) {
        sensors?.getDefaultSensor(Sensor.TYPE_GRAVITY) ?: sensors?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    } else {
        null
    }
    private val gyro = sensors?.getDefaultSensor(Sensor.TYPE_GYROSCOPE)

    @Volatile var roll = 0.0
    @Volatile var pitch = 0.0
    @Volatile var gx = 0.0
    @Volatile var gy = 0.0
    @Volatile var gz = 0.0

    private var listening = false
    private var primed = false
    private var warned = false
    private val matrix = FloatArray(9)
    private val orientation = FloatArray(3)

    private var rate = SensorManager.SENSOR_DELAY_UI

    fun setRate(next: Int) {
        if (next == rate) return
        rate = next
        if (listening) {
            sensors?.unregisterListener(this)
            register()
        }
    }

    fun setListening(on: Boolean) {
        if (on == listening) return
        listening = on
        if (!on) {
            sensors?.unregisterListener(this)
            return
        }
        register()
    }

    private fun register() {
        if (rotation == null && gravity == null && gyro == null) {
            if (!warned) {
                warned = true
                onLog("这台手机没有陀螺仪")
            }
            return
        }
        rotation?.let { sensors?.registerListener(this, it, rate) }
        gravity?.let { sensors?.registerListener(this, it, rate) }
        gyro?.let { sensors?.registerListener(this, it, rate) }
    }

    override fun onSensorChanged(event: SensorEvent) {
        val v = event.values
        when (event.sensor.type) {
            Sensor.TYPE_GYROSCOPE -> {
                gx = v[0].toDouble()
                gy = v[1].toDouble()
                gz = v[2].toDouble()
            }
            Sensor.TYPE_GAME_ROTATION_VECTOR, Sensor.TYPE_ROTATION_VECTOR -> {
                val vector = if (event.sensor.type == Sensor.TYPE_GAME_ROTATION_VECTOR || v.size < 4) {
                    floatArrayOf(v[0], v[1], v[2])
                } else {
                    floatArrayOf(v[0], v[1], v[2], v[3])
                }
                val ok = runCatching {
                    SensorManager.getRotationMatrixFromVector(matrix, vector)
                    SensorManager.getOrientation(matrix, orientation)
                }.isSuccess
                if (!ok) return
                sample(orientation[2].toDouble(), orientation[1].toDouble())
            }
            Sensor.TYPE_GRAVITY, Sensor.TYPE_ACCELEROMETER -> {
                val (r, p) = Tilt.fromGravity(v[0], v[1], v[2])
                sample(r, p)
            }
        }
    }

    private fun sample(nextRoll: Double, nextPitch: Double) {
        if (!primed) {
            roll = nextRoll
            pitch = nextPitch
            primed = true
            return
        }
        roll = Tilt.step(roll, nextRoll)
        pitch = Tilt.step(pitch, nextPitch)
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
}

internal data class WallFrame(val ops: List<WallOp>, val backdrop: Int) {
    companion object {
        val EMPTY = WallFrame(emptyList(), Color.TRANSPARENT)
    }
}

internal sealed class WallOp {
    data class Rect(val x: Float, val y: Float, val w: Float, val h: Float, val color: Int) : WallOp()
    data class Line(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val color: Int) : WallOp()
    data class Circle(val x: Float, val y: Float, val r: Float, val color: Int) : WallOp()
    data class Tri(
        val x1: Float,
        val y1: Float,
        val x2: Float,
        val y2: Float,
        val x3: Float,
        val y3: Float,
        val color: Int,
    ) : WallOp()
    data class Text(val x: Float, val y: Float, val text: String, val color: Int, val size: Float) : WallOp()
}

private class WallBuffer(private val onLog: (String) -> Unit) {
    private val ops = mutableListOf<WallOp>()
    private var backdrop = Color.TRANSPARENT
    private var capped = false

    fun snapshot(): WallFrame = WallFrame(ops.toList(), backdrop)

    fun clear() {
        ops.clear()
        backdrop = Color.TRANSPARENT
        capped = false
    }

    fun fill(color: Int) {
        ops.clear()
        backdrop = color
        capped = false
    }

    fun add(op: WallOp) {
        if (ops.size >= 2000) {
            if (!capped) {
                capped = true
                onLog("壁纸画面指令过多")
            }
            return
        }
        ops += op
    }
}

private const val MAX_HTML = 1_500_000
private const val MAX_URL = 2048

/** A script string often keeps the backslash that was only meant to hide a closing tag. */
private fun tidyHtml(html: String): String =
    if (html.contains("<\\/")) html.replace("<\\/", "</") else html

/** https anywhere, or http on this machine / a private LAN address. */
internal fun wallUrlOk(url: String): Boolean {
    if (url.length > MAX_URL) return false
    val uri = runCatching { android.net.Uri.parse(url) }.getOrNull() ?: return false
    val scheme = uri.scheme?.lowercase().orEmpty()
    val host = uri.host?.lowercase().orEmpty()
    if (host.isEmpty()) return false
    if (scheme == "https") return true
    if (scheme != "http") return false
    if (host == "localhost" || host == "127.0.0.1" || host == "[::1]" || host == "::1") return true
    val parts = host.split('.')
    if (parts.size != 4) return false
    val nums = parts.map { it.toIntOrNull() ?: return false }
    if (nums.any { it !in 0..255 }) return false
    val a = nums[0]
    val b = nums[1]
    return a == 10 || (a == 192 && b == 168) || (a == 172 && b in 16..31)
}

private fun argb(n: Double): Int {
    if (n.isNaN()) return Color.TRANSPARENT
    val bits = n.toLong() and 0xFFFFFFFFL
    if (bits == 0L) return Color.TRANSPARENT
    val color = if (bits <= 0xFFFFFFL) 0xFF000000L or bits else bits
    return color.toInt()
}

object PresetStore {
    private val live = AtomicReference<JSONObject?>(null)
    private val listeners = mutableSetOf<() -> Unit>()
    private val main = Handler(Looper.getMainLooper())

    fun write(context: Context, json: JSONObject) {
        File(context.filesDir, "wallpaper.json").writeText(json.toString())
        live.set(json)
        notifyChanged()
    }

    fun clear(context: Context) {
        File(context.filesDir, "wallpaper.json").delete()
        live.set(null)
        notifyChanged()
    }

    fun read(context: Context): JSONObject? {
        live.get()?.let { return it }
        val file = File(context.filesDir, "wallpaper.json")
        if (!file.exists()) return null
        return runCatching { JSONObject(file.readText()) }.getOrNull()?.also { live.set(it) }
    }

    fun watch(listener: () -> Unit) {
        main.post { listeners += listener }
    }

    fun unwatch(listener: () -> Unit) {
        main.post { listeners -= listener }
    }

    private fun notifyChanged() {
        main.post { listeners.toList().forEach { it() } }
    }
}

class OcWallpaperService : WallpaperService() {
    override fun onCreateEngine(): Engine = Stage()

    private inner class Stage : Engine() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private val path = Path()
        private var pixels: Bitmap? = null
        private val main = Handler(Looper.getMainLooper())
        private val drawLater = Runnable { sync() }
        private val onChange = { sync() }
        private var plugin: WallpaperPlugin? = null
        private var page: WallpaperPage? = null
        private var pageOn = false
        private var unbind: (() -> Unit)? = null
        private var unwatchGate: (() -> Unit)? = null
        private var visible = false
        private var crash: CrashScene? = null
        private var pending: WallFrame? = null
        private var waiting = false
        private var handoff = 0

        override fun onCreate(surfaceHolder: SurfaceHolder?) {
            super.onCreate(surfaceHolder)
            // Page swipes belong to the launcher. Taking offset or touch here,
            // or drawing before this callback returns, freezes screen changes.
            setTouchEventsEnabled(false)
            setOffsetNotificationsEnabled(false)
            PresetStore.watch(onChange)
            plugin = (application as? OcApp)?.wallpaper
            plugin?.let { plug ->
                unbind = plug.bind(::presentScript, ::postDraw)
                unwatchGate = plug.watchRunGate { applyPageActive() }
            }
            val host = this@OcWallpaperService
            page = WallpaperPage(
                host,
                readTiltX = { plugin?.tiltX() ?: 0.0 },
                readTiltY = { plugin?.tiltY() ?: 0.0 },
                readGyroX = { plugin?.gyroX() ?: 0.0 },
                readGyroY = { plugin?.gyroY() ?: 0.0 },
                readGyroZ = { plugin?.gyroZ() ?: 0.0 },
                onLog = { (application as? OcApp)?.append(it) },
            )
        }

        override fun onDestroy() {
            main.removeCallbacks(drawLater)
            if (visible) plugin?.engineShown(false)
            visible = false
            WallpaperShots.forget(pixels)
            pixels?.recycle()
            pixels = null
            unwatchGate?.invoke()
            unwatchGate = null
            unbind?.invoke()
            unbind = null
            PresetStore.unwatch(onChange)
            setPage(false)
            page?.release()
            page = null
            stopCrash()
            super.onDestroy()
        }

        override fun onVisibilityChanged(visible: Boolean) {
            val was = this.visible
            this.visible = visible
            crash?.visible = visible && plugin?.powerSavePaused() != true
            applyPageActive()
            if (hasPage()) setPage(visible && plugin?.powerSavePaused() != true)
            if (was != visible) plugin?.engineShown(visible)
            if (visible && plugin?.animating != true && plugin?.powerSavePaused() != true) postDraw()
        }

        private fun applyPageActive() {
            val active = visible && plugin?.powerSavePaused() != true
            page?.setActive(active)
            crash?.visible = active
        }

        override fun onSurfaceChanged(holder: SurfaceHolder?, format: Int, width: Int, height: Int) {
            super.onSurfaceChanged(holder, format, width, height)
            if (hasPage() || (crash == null && plugin?.animating != true)) postDraw()
        }

        override fun onSurfaceDestroyed(holder: SurfaceHolder?) {
            main.removeCallbacks(drawLater)
            setPage(false)
            page?.release()
            stopCrash()
            super.onSurfaceDestroyed(holder)
        }

        private fun postDraw() {
            pending = null
            main.removeCallbacks(drawLater)
            main.post(drawLater)
        }

        private fun sceneName(): String =
            PresetStore.read(this@OcWallpaperService)?.optString("scene").orEmpty()

        private fun pageHtml(): String =
            tidyHtml(PresetStore.read(this@OcWallpaperService)?.optString("html").orEmpty())

        private fun pageUrl(): String {
            val url = PresetStore.read(this@OcWallpaperService)?.optString("url").orEmpty().trim()
            return if (wallUrlOk(url)) url else ""
        }

        private fun pageSource(): String {
            val html = pageHtml()
            if (html.isNotEmpty()) return html
            return if (sceneName() == CastlePage.SCENE) CastlePage.source(this@OcWallpaperService) else ""
        }

        private fun hasPage(): Boolean = pageUrl().isNotEmpty() || pageSource().isNotEmpty()

        private fun setPage(on: Boolean) {
            if (pageOn == on) return
            pageOn = on
            plugin?.pageShown(on)
        }

        private fun sync() {
            val url = pageUrl()
            val html = pageSource()
            if (url.isNotEmpty() || html.isNotEmpty()) {
                if (!releaseCrash()) return
                val holder = surfaceHolder
                val target = holder?.surface
                val frame = holder?.surfaceFrame
                val width = frame?.width() ?: 0
                val height = frame?.height() ?: 0
                if (target != null && target.isValid && width > 0 && height > 0) {
                    if (url.isNotEmpty()) {
                        page?.show(target, width, height, resources.displayMetrics.densityDpi, href = url)
                    } else {
                        page?.show(target, width, height, resources.displayMetrics.densityDpi, document = html)
                    }
                    applyPageActive()
                    setPage(visible && plugin?.powerSavePaused() != true)
                }
                return
            }
            setPage(false)
            page?.release()
            if (!releaseCrash()) return
            if (plugin?.animating == true) return
            if (sceneName() == "crash" && pending == null) {
                WallpaperShots.forget(pixels)
                val holder = surfaceHolder
                if (crash == null && holder.surface?.isValid == true) {
                    crash = CrashScene(holder.surface).also {
                        it.visible = visible
                        it.start()
                    }
                } else {
                    crash?.visible = visible
                }
                return
            }
            if (pending != null) return
            drawFlat()
        }

        /** The GL clip has to leave the surface before a page or a flat frame can use it. */
        private fun releaseCrash(): Boolean {
            val dying = crash ?: return true
            dying.shutdown()
            crash = null
            val token = ++handoff
            waiting = true
            main.post(object : Runnable {
                override fun run() {
                    if (token != handoff) return
                    if (dying.isAlive) {
                        main.postDelayed(this, 16)
                        return
                    }
                    waiting = false
                    sync()
                }
            })
            return false
        }

        private fun presentScript(frame: WallFrame) {
            if (hasPage()) return
            if (!visible || plugin?.animating != true) return
            pending = frame
            if (!releaseCrash()) return
            drawScript(frame)
        }

        private fun stopCrash() {
            crash?.shutdown()
            crash = null
        }

        private fun drawFlat() {
            paintFrame { drawPreset(it) }
        }

        private fun drawScript(frame: WallFrame) {
            paintFrame { canvas ->
                drawPreset(canvas)
                val density = resources.displayMetrics.density
                canvas.save()
                canvas.scale(density, density)
                if (Color.alpha(frame.backdrop) > 0) canvas.drawColor(frame.backdrop)
                paint.style = Paint.Style.FILL
                paint.textAlign = Paint.Align.LEFT
                paint.textSize = 16f
                for (op in frame.ops) {
                    when (op) {
                        is WallOp.Rect -> {
                            paint.color = op.color
                            canvas.drawRect(op.x, op.y, op.x + op.w, op.y + op.h, paint)
                        }
                        is WallOp.Line -> {
                            paint.color = op.color
                            paint.style = Paint.Style.STROKE
                            paint.strokeWidth = 2f
                            canvas.drawLine(op.x1, op.y1, op.x2, op.y2, paint)
                            paint.style = Paint.Style.FILL
                        }
                        is WallOp.Circle -> {
                            paint.color = op.color
                            canvas.drawCircle(op.x, op.y, op.r, paint)
                        }
                        is WallOp.Tri -> {
                            paint.color = op.color
                            paint.style = Paint.Style.FILL
                            path.rewind()
                            path.moveTo(op.x1, op.y1)
                            path.lineTo(op.x2, op.y2)
                            path.lineTo(op.x3, op.y3)
                            path.close()
                            canvas.drawPath(path, paint)
                        }
                        is WallOp.Text -> {
                            paint.color = op.color
                            paint.textSize = if (op.size > 0f) op.size else 16f
                            canvas.drawText(op.text, op.x, op.y, paint)
                        }
                    }
                }
                canvas.restore()
            }
        }

        /** Draw into a bitmap we can hand to the model, then blit it to the wallpaper surface. */
        private fun paintFrame(draw: (Canvas) -> Unit) {
            if (!visible) return
            val holder = surfaceHolder ?: return
            if (holder.surface?.isValid != true) return
            val frame = holder.surfaceFrame
            val width = frame.width()
            val height = frame.height()
            val buffer = if (width > 0 && height > 0) bitmapCanvas(width, height) else null
            if (buffer == null) {
                val canvas = lock(holder) ?: return
                try {
                    draw(canvas)
                } finally {
                    unlock(holder, canvas)
                }
                return
            }
            draw(buffer)
            pixels?.let { WallpaperShots.remember(it) }
            val canvas = lock(holder) ?: return
            try {
                canvas.drawBitmap(pixels!!, 0f, 0f, null)
            } finally {
                unlock(holder, canvas)
            }
        }

        private fun bitmapCanvas(width: Int, height: Int): Canvas {
            val current = pixels
            if (current == null || current.width != width || current.height != height) {
                WallpaperShots.forget(current)
                current?.recycle()
                pixels = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            }
            return Canvas(pixels!!)
        }

        private fun lock(holder: SurfaceHolder): Canvas? = try {
            holder.lockCanvas()
        } catch (_: Throwable) {
            null
        }

        private fun unlock(holder: SurfaceHolder, canvas: Canvas) {
            try {
                holder.unlockCanvasAndPost(canvas)
            } catch (_: Throwable) {
            }
        }

        private fun drawPreset(canvas: Canvas) {
            val preset = PresetStore.read(this@OcWallpaperService)
            val color = colorOf(preset?.opt("color"), Color.parseColor("#F4F1EA"))
            canvas.drawColor(color)
            val text = preset?.optString("text").orEmpty()
            if (text.isEmpty()) return
            val density = resources.displayMetrics.density
            paint.color = colorOf(preset?.opt("textColor"), Color.parseColor("#1C1B19"))
            paint.textSize = (preset?.optDouble("size", 28.0) ?: 28.0).toFloat() * density
            val xRaw = preset?.optDouble("x", 24.0) ?: 24.0
            val yRaw = preset?.optDouble("y", 80.0) ?: 80.0
            paint.textAlign = if (xRaw in 0.0..1.0) Paint.Align.CENTER else Paint.Align.LEFT
            paint.style = Paint.Style.FILL
            canvas.drawText(text, place(xRaw, canvas.width.toFloat(), density), place(yRaw, canvas.height.toFloat(), density), paint)
        }

        /** A value from 0 to 1 is a fraction of the screen. Anything larger is dp. */
        private fun place(raw: Double, spanPx: Float, density: Float): Float =
            if (raw in 0.0..1.0) (raw * spanPx).toFloat() else raw.toFloat() * density

        private fun colorOf(raw: Any?, fallback: Int): Int {
            val n = when (raw) {
                is Number -> raw.toLong()
                is String -> raw.removePrefix("#").toLongOrNull(16) ?: return fallback
                else -> return fallback
            }
            val bits = n and 0xFFFFFFFFL
            val color = if (bits <= 0xFFFFFFL) 0xFF000000L or bits else bits
            return color.toInt()
        }
    }
}
