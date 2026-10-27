package app.onlyclaws.android

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Region
import android.hardware.input.InputManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.WindowManager
import android.view.View
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined

/**
 * The overlay page is a WebView. Drawing is whatever that page can do:
 * canvas, WebGL, images. The host only loads, evaluates, and clears.
 *
 *   web.load("<html>…</html>")
 *   web.url("https://…")
 *   web.eval("document.title")
 *   web.touch(true)
 *   web.clear()
 */
@SuppressLint("SetJavaScriptEnabled")
class WebOverlay(
    private val app: Context,
    private val onLog: (String) -> Unit,
    private val allow: () -> Boolean,
) {
    private val main = Handler(Looper.getMainLooper())
    private val wm = app.getSystemService(WindowManager::class.java)
    private var view: WebView? = null
    private var added = false
    private var touch = false
    private val params = WindowManager.LayoutParams(
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.MATCH_PARENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        flags() or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        alpha = passThroughAlpha()
    }

    fun load(html: String) = main.post {
        if (!open()) return@post
        view?.loadDataWithBaseURL(ORIGIN, html, "text/html", "utf-8", null)
        onLog("浮层页面已装上")
    }

    fun url(url: String) = main.post {
        if (!open()) return@post
        view?.loadUrl(url)
        onLog("浮层打开 $url")
    }

    fun eval(code: String) = main.post {
        view?.evaluateJavascript(code, null)
    }

    fun touch(on: Boolean) = main.post {
        touch = on
        if (added) applyTouch()
    }

    fun clear() = main.post {
        view?.loadUrl("about:blank")
        if (added) {
            wm.removeView(view)
            added = false
        }
        onLog("浮层页面已清掉")
    }

    private fun open(): Boolean {
        if (!allow()) return false
        if (view == null) {
            view = WebView(app).apply {
                setBackgroundColor(Color.TRANSPARENT)
                setLayerType(View.LAYER_TYPE_HARDWARE, null)
                webChromeClient = object : WebChromeClient() {
                    override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                        onLog(message.message())
                        return true
                    }
                }
                isVerticalScrollBarEnabled = false
                isHorizontalScrollBarEnabled = false
                overScrollMode = WebView.OVER_SCROLL_NEVER
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                settings.mediaPlaybackRequiresUserGesture = false
                settings.allowFileAccess = false
                addJavascriptInterface(LogBridge(), "Oca")
            }
        }
        if (!added) {
            params.flags = flags()
            wm.addView(view, params)
            added = true
            view?.post { applyTouch() }
        }
        return true
    }

    /**
     * A fullscreen overlay that lets taps through cannot be fully opaque:
     * since Android 12 the system caps that case at
     * [InputManager.getMaximumObscuringOpacityForTouch] (0.8) and blocks the
     * touch otherwise, with a prompt to close the app. web.touch(true) takes
     * the screen and lifts the cap.
     */
    private fun applyTouch() {
        val target = view ?: return
        params.flags = flags() or if (touch) 0 else WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        params.alpha = if (touch) 1f else passThroughAlpha()
        wm.updateViewLayout(target, params)
        if (!touch) return
        val bounds = wm.maximumWindowMetrics.bounds
        val region = Region(0, 0, bounds.width(), bounds.height())
        runCatching {
            val getRoot = android.view.View::class.java.getDeclaredMethod("getViewRootImpl")
            getRoot.isAccessible = true
            val root = getRoot.invoke(target) ?: return
            val method = root.javaClass.methods.firstOrNull {
                it.name == "setTouchableRegion" && it.parameterTypes.size == 1
            } ?: return
            method.invoke(root, region)
        }
    }

    private fun passThroughAlpha(): Float =
        if (Build.VERSION.SDK_INT >= 31) {
            app.getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch
        } else {
            0.8f
        }

    private fun flags(): Int =
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED

    private inner class LogBridge {
        @JavascriptInterface
        fun log(line: String) {
            onLog(line)
        }
    }

    fun api(): ScriptableObject = Api()

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "web"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "load" -> fn { load(text(it)) }
            "url" -> fn { url(text(it)) }
            "eval" -> fn { eval(text(it)) }
            "clear" -> fn { clear() }
            "touch" -> fn { touch(it?.firstOrNull()?.let { v -> JsContext.toBoolean(v) } == true) }
            else -> NOT_FOUND
        }

        private fun fn(body: (Array<out Any>?) -> Unit) = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                body(args)
                return Undefined.instance
            }
        }

        private fun text(args: Array<out Any>?): String =
            if (args.isNullOrEmpty()) "" else JsContext.toString(args[0])
    }

    companion object {
        private const val ORIGIN = "https://onlyclaws.local/"
    }
}
