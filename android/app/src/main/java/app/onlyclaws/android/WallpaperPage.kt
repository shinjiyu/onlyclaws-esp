package app.onlyclaws.android

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.drawable.ColorDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.os.Build
import android.os.Bundle
import android.util.Log
import android.view.Surface
import android.view.ViewGroup
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.app.Presentation
import java.io.ByteArrayInputStream

/**
 * One document on a wallpaper surface: inline HTML or a remote https page.
 * The page's own JavaScript runs there, including WebGL. https subresources
 * are allowed. Inline pages cannot navigate away. Remote pages may follow
 * https redirects. The launcher still owns touches.
 */
@SuppressLint("SetJavaScriptEnabled")
internal class WallpaperPage(
    private val context: Context,
    private val readTiltX: () -> Double,
    private val readTiltY: () -> Double,
    private val readGyroX: () -> Double,
    private val readGyroY: () -> Double,
    private val readGyroZ: () -> Double,
    private val onLog: (String) -> Unit,
) {
    private var display: VirtualDisplay? = null
    private var presentation: Presentation? = null
    private var web: WebView? = null
    private var surface: Surface? = null
    private var document: String? = null
    private var href: String? = null
    private var pendingDocument: String? = null
    private var pendingHref: String? = null
    private var loadTries = 0
    private var width = 0
    private var height = 0

    fun show(target: Surface, width: Int, height: Int, dpi: Int, document: String? = null, href: String? = null) {
        if (!target.isValid || width <= 0 || height <= 0) return
        if (document.isNullOrEmpty() && href.isNullOrEmpty()) return
        if (this.surface !== target || display == null) {
            release()
            if (!open(target, width, height, dpi)) return
        } else if (width != this.width || height != this.height) {
            this.width = width
            this.height = height
            display?.resize(width, height, dpi)
            web?.layoutParams = FrameLayout.LayoutParams(width, height)
        }
        if (!href.isNullOrEmpty()) {
            pendingHref = href
            pendingDocument = null
            loadWhenReady()
        } else if (!document.isNullOrEmpty()) {
            pendingDocument = document
            pendingHref = null
            loadWhenReady()
        }
    }

    private var active = false

    /**
     * Run or freeze the page. Pause stops timers to save power; pages that listen
     * for `oca-wallpaper-resume` (see BOOT) restart their rAF loop. Pages that
     * ignore it may need a reload after a long pause.
     */
    fun setActive(running: Boolean) {
        val view = web ?: return
        if (running == active) {
            if (running) kick(view)
            return
        }
        active = running
        if (running) {
            view.onResume()
            view.resumeTimers()
            kick(view)
        } else {
            view.evaluateJavascript("window.dispatchEvent(new Event('oca-wallpaper-pause'))", null)
            view.post {
                if (active) return@post
                view.onPause()
                view.pauseTimers()
            }
        }
    }

    private fun kick(view: WebView) {
        view.evaluateJavascript(
            """
            window.dispatchEvent(new Event('oca-wallpaper-resume'));
            window.dispatchEvent(new Event('resize'));
            """.trimIndent(),
            null,
        )
    }

    private fun loadWhenReady() {
        val view = web ?: return
        if ((view.width <= 0 || view.height <= 0) && loadTries < 12) {
            loadTries++
            view.postDelayed({ loadWhenReady() }, 32)
            return
        }
        loadTries = 0
        view.onResume()
        view.resumeTimers()
        val remote = pendingHref
        if (!remote.isNullOrEmpty()) {
            pendingHref = null
            pendingDocument = null
            if (href == remote && document == null) return
            href = remote
            document = null
            view.loadUrl(remote)
            return
        }
        val source = pendingDocument ?: return
        pendingDocument = null
        if (document == source && href == null) return
        document = source
        href = null
        view.loadDataWithBaseURL(ORIGIN, BOOT + source, "text/html", "utf-8", null)
    }

    fun release() {
        active = false
        document = null
        href = null
        pendingDocument = null
        pendingHref = null
        loadTries = 0
        surface = null
        width = 0
        height = 0
        val view = web
        web = null
        val shown = presentation
        presentation = null
        val virtual = display
        display = null
        // Drop the wallpaper surface before the window is torn down, or the
        // launcher surface goes with it and every later wallpaper stays black.
        runCatching { virtual?.setSurface(null) }
        runCatching { shown?.dismiss() }
        runCatching {
            view?.let {
                (it.parent as? ViewGroup)?.removeView(it)
                it.destroy()
            }
        }
        runCatching { virtual?.release() }
    }

    private fun open(target: Surface, width: Int, height: Int, dpi: Int): Boolean {
        val manager = context.getSystemService(DisplayManager::class.java)
        val virtual = runCatching {
            @Suppress("DEPRECATION")
            manager.createVirtualDisplay(
                "oca-wallpaper",
                width,
                height,
                dpi,
                target,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_PRESENTATION or
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY,
            )
        }.getOrElse {
            Log.e(TAG, "virtual display", it)
            onLog("壁纸页面打不开")
            return false
        }
        if (virtual == null) {
            onLog("壁纸页面打不开")
            return false
        }
        val displayContext = context.createDisplayContext(virtual.display)
        val view = runCatching { createWeb(displayContext) }.getOrElse { createWeb(context) }
        val window = object : Presentation(displayContext, virtual.display) {
            override fun onCreate(savedInstanceState: Bundle?) {
                super.onCreate(savedInstanceState)
                this.window?.setBackgroundDrawable(ColorDrawable(Color.BLACK))
                val root = FrameLayout(context)
                root.setBackgroundColor(Color.BLACK)
                view.layoutParams = FrameLayout.LayoutParams(width, height)
                root.addView(view)
                setContentView(root)
            }
        }
        val shown = runCatching {
            window.show()
            true
        }.getOrElse {
            Log.e(TAG, "presentation", it)
            view.destroy()
            virtual.setSurface(null)
            virtual.release()
            onLog("壁纸页面打不开")
            false
        }
        if (!shown) return false
        display = virtual
        presentation = window
        web = view
        surface = target
        this.width = width
        this.height = height
        onLog("壁纸页面已装上")
        return true
    }

    private fun createWeb(host: Context): WebView = WebView(host).apply {
        setBackgroundColor(Color.BLACK)
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        settings.allowFileAccess = false
        settings.allowContentAccess = false
        @Suppress("DEPRECATION")
        settings.allowFileAccessFromFileURLs = false
        @Suppress("DEPRECATION")
        settings.allowUniversalAccessFromFileURLs = false
        settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
        settings.setGeolocationEnabled(false)
        settings.mediaPlaybackRequiresUserGesture = false
        if (Build.VERSION.SDK_INT >= 26) settings.safeBrowsingEnabled = true
        webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                if (url == "about:blank") return
                view?.onResume()
                view?.resumeTimers()
                view?.post {
                    view.evaluateJavascript("window.dispatchEvent(new Event('resize'))", null)
                }
            }

            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Inline documents stay put. A remote wallpaper may follow allowed redirects.
                if (href == null) return true
                return !wallUrlOk(request.url?.toString().orEmpty())
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                val url = request.url
                val path = url?.path.orEmpty()
                if (url?.host == "oca.wall" && path.startsWith("/castle/")) {
                    val name = path.removePrefix("/castle/")
                    if (!name.matches(Regex("[A-Za-z0-9_.-]+\\.glb"))) {
                        return WebResourceResponse("text/plain", "utf-8", ByteArrayInputStream(ByteArray(0)))
                    }
                    return runCatching {
                        WebResourceResponse(
                            "model/gltf-binary",
                            null,
                            context.assets.open("castle/$name"),
                        )
                    }.getOrElse {
                        onLog("壁纸模型缺失")
                        WebResourceResponse("text/plain", "utf-8", ByteArrayInputStream(ByteArray(0)))
                    }
                }
                val scheme = url?.scheme?.lowercase().orEmpty()
                if (scheme == "https" || scheme == "data" || scheme == "blob" || scheme == "about") return null
                if (scheme == "http" && href != null) return null
                return WebResourceResponse("text/plain", "utf-8", ByteArrayInputStream(ByteArray(0)))
            }
        }
        webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                val level = consoleMessage.messageLevel()
                if (level == ConsoleMessage.MessageLevel.ERROR || level == ConsoleMessage.MessageLevel.WARNING) {
                    onLog("壁纸页面: " + consoleMessage.message().take(180))
                }
                return true
            }
        }
        addJavascriptInterface(Bridge(), "OcaWallpaper")
    }

    private inner class Bridge {
        @JavascriptInterface fun tiltX(): Double = readTiltX()
        @JavascriptInterface fun tiltY(): Double = readTiltY()
        @JavascriptInterface fun gyroX(): Double = readGyroX()
        @JavascriptInterface fun gyroY(): Double = readGyroY()
        @JavascriptInterface fun gyroZ(): Double = readGyroZ()
    }

    private companion object {
        const val TAG = "OcaWall"
        const val ORIGIN = "https://oca.wall/page.html"

        // Pages often measure the canvas once, before the wallpaper view has a size.
        // A later resize is what lets that measurement run again.
        const val BOOT = """
            <script>
            (function () {
              var kicks = 0;
              function kick() {
                if (kicks++ > 8) return;
                window.dispatchEvent(new Event("resize"));
              }
              window.addEventListener("load", kick);
              document.addEventListener("visibilitychange", function () {
                if (!document.hidden) kick();
              });
              window.addEventListener("oca-wallpaper-resume", kick);
              if (window.ResizeObserver) new ResizeObserver(kick).observe(document.documentElement);
            })();
            </script>
        """
    }
}
