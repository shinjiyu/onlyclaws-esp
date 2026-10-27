package app.onlyclaws.android

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Handler
import android.os.Looper
import android.service.wallpaper.WallpaperService
import android.view.SurfaceHolder
import org.json.JSONObject
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.NativeJSON
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import java.io.File
import java.util.concurrent.atomic.AtomicReference

/**
 * Script loads a preset once. The wallpaper engine keeps its own clock.
 * `scene: "crash"` plays the 3D clip. Anything else is a flat color and one line of text.
 *
 *   wallpaper.load({ scene: "crash" })
 *   wallpaper.load({ color: 0x1C1B19, text: "OCA", x: 24, y: 80 })
 */
class WallpaperPlugin(
    private val app: Context,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "wallpaper", api)
    }

    private fun load(payload: Any?) {
        val json = when (payload) {
            null, is Undefined -> null
            is JSONObject -> payload
            is String -> runCatching { JSONObject(payload) }.getOrNull()
            else -> runCatching {
                JSONObject(
                    NativeJSON.stringify(
                        JsContext.getCurrentContext(),
                        JsContext.getCurrentContext().initStandardObjects(),
                        payload,
                        null,
                        null,
                    ) as String,
                )
            }.getOrNull()
        }
        if (json == null) {
            clear()
            return
        }
        PresetStore.write(app, json)
        onLog("壁纸预设已装上")
    }

    private fun clear() {
        PresetStore.clear(app)
        onLog("壁纸预设已清掉")
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "wallpaper"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "load" -> loadFn
            "clear" -> clearFn
            else -> NOT_FOUND
        }

        private val loadFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                load(args?.firstOrNull())
                return Undefined.instance
            }
        }

        private val clearFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                clear()
                return Undefined.instance
            }
        }
    }
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
        private val onChange = { sync() }
        private var visible = false
        private var crash: CrashScene? = null

        override fun onCreate(surfaceHolder: SurfaceHolder?) {
            super.onCreate(surfaceHolder)
            PresetStore.watch(onChange)
        }

        override fun onDestroy() {
            PresetStore.unwatch(onChange)
            stopCrash()
            super.onDestroy()
        }

        override fun onVisibilityChanged(visible: Boolean) {
            this.visible = visible
            crash?.visible = visible
            if (visible) sync()
        }

        override fun onSurfaceChanged(holder: SurfaceHolder?, format: Int, width: Int, height: Int) {
            super.onSurfaceChanged(holder, format, width, height)
            stopCrash()
            sync()
        }

        override fun onSurfaceDestroyed(holder: SurfaceHolder?) {
            stopCrash()
            super.onSurfaceDestroyed(holder)
        }

        private fun sceneName(): String =
            PresetStore.read(this@OcWallpaperService)?.optString("scene").orEmpty()

        private fun sync() {
            if (sceneName() == "crash") {
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
            stopCrash()
            drawFlat()
        }

        private fun stopCrash() {
            crash?.shutdown()
            crash = null
        }

        private fun drawFlat() {
            if (!visible) return
            val holder = surfaceHolder ?: return
            val canvas: Canvas = try {
                holder.lockCanvas() ?: return
            } catch (_: Throwable) {
                return
            }
            try {
                val preset = PresetStore.read(this@OcWallpaperService)
                val color = colorOf(preset?.opt("color"), Color.parseColor("#F4F1EA"))
                canvas.drawColor(color)
                val text = preset?.optString("text").orEmpty()
                if (text.isNotEmpty()) {
                    val density = resources.displayMetrics.density
                    paint.color = colorOf(preset?.opt("textColor"), Color.parseColor("#1C1B19"))
                    paint.textSize = (preset?.optDouble("size", 28.0) ?: 28.0).toFloat() * density
                    val x = (preset?.optDouble("x", 24.0) ?: 24.0).toFloat() * density
                    val y = (preset?.optDouble("y", 80.0) ?: 80.0).toFloat() * density
                    canvas.drawText(text, x, y, paint)
                }
            } finally {
                try {
                    holder.unlockCanvasAndPost(canvas)
                } catch (_: Throwable) {
                }
            }
        }

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
