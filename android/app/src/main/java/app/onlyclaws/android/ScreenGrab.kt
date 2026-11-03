package app.onlyclaws.android

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionConfig
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.util.Base64
import android.view.Display
import androidx.core.app.NotificationCompat
import java.io.ByteArrayOutputStream
import java.util.concurrent.CompletableFuture
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min

/**
 * One full-display capture. Android only exposes other apps' pixels through the
 * screen-capture consent. The first call asks once; later calls reuse that grant
 * until the user stops it. There is no accessibility service.
 *
 *   shot.take() → { b64, mime, w, h, error }
 */
object ScreenGrab {
    private val main = Handler(Looper.getMainLooper())
    private val images = LinkedBlockingQueue<Image>(1)
    private var thread: HandlerThread? = null
    private var handler: Handler? = null
    private var projection: MediaProjection? = null
    private var reader: ImageReader? = null
    private var display: VirtualDisplay? = null
    private var waiting: CompletableFuture<Boolean>? = null
    private var stopping = false
    private var lastError = "没有允许截图"

    @Volatile
    var ready: Boolean = false
        private set

    fun capture(): Map<String, Any> {
        if (Looper.myLooper() == Looper.getMainLooper()) return miss("截图要在后台进行")
        if (!awaitReady()) return miss(lastError)
        val app = OcApp.instance
        // A static screen produces no frames, so the queued one can be minutes old.
        val stale = images.poll()
        val hidden = CompletableFuture<Boolean>()
        main.post { hidden.complete(app.chat.conceal()) }
        val hid = runCatching { hidden.get(1, TimeUnit.SECONDS) }.getOrDefault(false)
        try {
            if (hid) Thread.sleep(200)
            val fresh = takeLatest(if (hid || stale == null) 1600 else 400)
            if (fresh != null) stale?.close()
            val image = fresh ?: stale ?: return miss("截不到这一帧")
            return try {
                jpeg(image)
            } finally {
                image.close()
            }
        } finally {
            if (hid) main.post { app.chat.reveal() }
        }
    }

    fun fail(message: String) {
        lastError = message
        waiting?.complete(false)
        waiting = null
    }

    fun attach(context: Context, code: Int, data: Intent) {
        if (ready) return
        val manager = context.getSystemService(MediaProjectionManager::class.java)
        val session = manager.getMediaProjection(code, data)
        if (session == null) {
            fail("截图开不了")
            return
        }
        session.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                release()
                context.stopService(Intent(context, ScreenGrabService::class.java))
            }
        }, callbackHandler())
        val mode = context.getSystemService(DisplayManager::class.java)
            .getDisplay(Display.DEFAULT_DISPLAY).mode
        val width = mode.physicalWidth
        val height = mode.physicalHeight
        if (width <= 0 || height <= 0) {
            session.stop()
            fail("读不到屏幕尺寸")
            return
        }
        val density = context.resources.displayMetrics.densityDpi
        val surface = ImageReader.newInstance(width, height, PixelFormat.RGBA_8888, 3)
        surface.setOnImageAvailableListener({ source ->
            val frame = runCatching { source.acquireLatestImage() }.getOrNull() ?: return@setOnImageAvailableListener
            images.poll()?.close()
            if (!images.offer(frame)) frame.close()
        }, callbackHandler())
        val virtual = session.createVirtualDisplay(
            "oca-shot",
            width,
            height,
            density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            surface.surface,
            null,
            callbackHandler(),
        )
        projection = session
        reader = surface
        display = virtual
        ready = true
        lastError = ""
        waiting?.complete(true)
        waiting = null
    }

    fun release() {
        if (stopping) return
        stopping = true
        try {
            ready = false
            display?.release()
            reader?.close()
            val session = projection
            projection = null
            display = null
            reader = null
            images.poll()?.close()
            session?.stop()
        } catch (_: Throwable) {
        } finally {
            stopping = false
        }
    }

    private fun awaitReady(): Boolean {
        if (ready) return true
        val (owner, pending) = synchronized(this) {
            if (ready) return true
            val existing = waiting
            if (existing != null) return@synchronized false to existing
            val created = CompletableFuture<Boolean>()
            waiting = created
            true to created
        }
        if (owner) {
            main.post {
                val app = OcApp.instance
                app.startActivity(
                    Intent(app, ScreenCaptureActivity::class.java)
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
        }
        runCatching { pending.get(30, TimeUnit.SECONDS) }
        if (!ready && lastError.isBlank()) lastError = "没有允许截图"
        return ready
    }

    private fun callbackHandler(): Handler {
        val current = handler
        if (current != null) return current
        val born = HandlerThread("oca-shot")
        born.start()
        thread = born
        return Handler(born.looper).also { handler = it }
    }

    private fun takeLatest(waitMs: Long): Image? {
        val first = images.poll(waitMs, TimeUnit.MILLISECONDS) ?: return null
        val newer = images.poll(80, TimeUnit.MILLISECONDS)
        return if (newer != null) {
            first.close()
            newer
        } else {
            first
        }
    }

    private fun jpeg(image: Image): Map<String, Any> {
        val full = bitmapOf(image)
        val edge = max(full.width, full.height).coerceAtLeast(1)
        val scale = min(1f, 960f / edge)
        val width = (full.width * scale).toInt().coerceAtLeast(1)
        val height = (full.height * scale).toInt().coerceAtLeast(1)
        val scaled = if (width == full.width && height == full.height) full else Bitmap.createScaledBitmap(full, width, height, true)
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
            if (scaled !== full) scaled.recycle()
            full.recycle()
        }
    }

    private fun bitmapOf(image: Image): Bitmap {
        val plane = image.planes[0]
        val buffer = plane.buffer
        buffer.rewind()
        val pixelStride = plane.pixelStride.coerceAtLeast(1)
        val rowPixels = plane.rowStride / pixelStride
        val full = Bitmap.createBitmap(rowPixels, image.height, Bitmap.Config.ARGB_8888)
        full.copyPixelsFromBuffer(buffer)
        if (rowPixels == image.width) return full
        val cropped = Bitmap.createBitmap(full, 0, 0, image.width, image.height)
        full.recycle()
        return cropped
    }

    private fun miss(error: String) = mapOf(
        "b64" to "",
        "mime" to "",
        "w" to 0,
        "h" to 0,
        "error" to error,
    )
}

class ScreenCaptureActivity : Activity() {
    override fun onCreate(savedInstanceState: android.os.Bundle?) {
        super.onCreate(savedInstanceState)
        if (ScreenGrab.ready) {
            finish()
            return
        }
        val manager = getSystemService(MediaProjectionManager::class.java)
        val intent = if (Build.VERSION.SDK_INT >= 34) {
            manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
        } else {
            manager.createScreenCaptureIntent()
        }
        @Suppress("DEPRECATION")
        startActivityForResult(intent, REQUEST)
    }

    @Deprecated("Platform consent still arrives here")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == REQUEST && resultCode == RESULT_OK && data != null) {
            val launch = Intent(this, ScreenGrabService::class.java)
                .putExtra(EXTRA_CODE, resultCode)
                .putExtra(EXTRA_DATA, data)
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(launch) else startService(launch)
        } else {
            ScreenGrab.fail("没有允许截图")
        }
        finish()
    }

    companion object {
        private const val REQUEST = 1
        const val EXTRA_CODE = "code"
        const val EXTRA_DATA = "data"
    }
}

class ScreenGrabService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        val code = intent?.getIntExtra(ScreenCaptureActivity.EXTRA_CODE, 0) ?: 0
        val data = if (Build.VERSION.SDK_INT >= 33) {
            intent?.getParcelableExtra(ScreenCaptureActivity.EXTRA_DATA, Intent::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent?.getParcelableExtra(ScreenCaptureActivity.EXTRA_DATA)
        }
        if (code != 0 && data != null && !ScreenGrab.ready) {
            runCatching { ScreenGrab.attach(this, code, data) }
                .onFailure {
                    ScreenGrab.fail(it.message ?: "截图开不了")
                    stopSelf()
                }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        ScreenGrab.release()
        super.onDestroy()
    }

    private fun startInForeground() {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "截图", NotificationManager.IMPORTANCE_LOW),
            )
        }
        val note: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_oca)
            .setContentTitle(getString(R.string.app_name))
            .setContentText("用来截当前屏幕")
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTE, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
        } else {
            startForeground(NOTE, note)
        }
    }

    companion object {
        private const val CHANNEL = "oca-shot"
        private const val NOTE = 2
    }
}
