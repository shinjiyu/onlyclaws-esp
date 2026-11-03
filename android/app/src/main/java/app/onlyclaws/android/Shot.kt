package app.onlyclaws.android

import android.graphics.Bitmap
import android.os.Handler
import android.os.Looper
import android.util.Base64
import java.io.ByteArrayOutputStream
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min

/**
 * The last wallpaper frame, small enough to send to a model.
 * This is the wallpaper surface only. Launcher icons are not in it.
 *
 *   shot.take() → { b64, mime, w, h, error }
 */
object WallpaperShots {
    private val main = Handler(Looper.getMainLooper())
    private var source: Bitmap? = null

    fun remember(bitmap: Bitmap) {
        source = bitmap
    }

    fun forget(bitmap: Bitmap?) {
        if (bitmap == null || source === bitmap) source = null
    }

    fun capture(): Map<String, Any> {
        if (Looper.myLooper() == Looper.getMainLooper()) return encode()
        val done = CompletableFuture<Map<String, Any>>()
        main.post { done.complete(encode()) }
        return runCatching { done.get(2, TimeUnit.SECONDS) }.getOrElse { miss("截图超时") }
    }

    private fun encode(): Map<String, Any> {
        val src = source
        if (src == null || src.isRecycled) return miss("还没有壁纸画面")
        val edge = max(src.width, src.height).coerceAtLeast(1)
        val scale = min(1f, 960f / edge)
        val width = (src.width * scale).toInt().coerceAtLeast(1)
        val height = (src.height * scale).toInt().coerceAtLeast(1)
        val scaled = if (width == src.width && height == src.height) src else Bitmap.createScaledBitmap(src, width, height, true)
        return try {
            val bytes = ByteArrayOutputStream()
            if (!scaled.compress(Bitmap.CompressFormat.JPEG, 72, bytes)) return miss("截图失败")
            mapOf(
                "b64" to Base64.encodeToString(bytes.toByteArray(), Base64.NO_WRAP),
                "mime" to "image/jpeg",
                "w" to width,
                "h" to height,
                "error" to "",
            )
        } finally {
            if (scaled !== src) scaled.recycle()
        }
    }

    private fun miss(error: String) = mapOf(
        "b64" to "",
        "mime" to "",
        "w" to 0,
        "h" to 0,
        "error" to error,
    )
}

class ShotPlugin : JsPlugin {
    override fun install(scope: JsScope) = scope.define("shot") {
        fn("take") { ScreenGrab.capture() }
    }
}
