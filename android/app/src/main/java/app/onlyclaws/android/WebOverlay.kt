package app.onlyclaws.android

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.CookieManager
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Login stays on screen. Every other page is loaded off to the side,
 * not touchable, so the phone can be used while the script browses.
 *
 *   web.load("<html>…</html>")
 *   web.url("https://…")
 *   web.eval("document.title")
 *   web.clear()
 *   web.loggedIn()
 *   web.showing()
 *
 * A Bilibili login URL stays up until SESSDATA is set, then the page is put away.
 * Leaving that login URL for the rest of Bilibili does not show the home page.
 */
@SuppressLint("SetJavaScriptEnabled")
class WebOverlay(
    private val app: Context,
    private val onLog: (String) -> Unit,
    private val onStop: () -> Unit = {},
) {
    private val main = Handler(Looper.getMainLooper())
    private var host: ViewGroup? = null
    private var view: WebView? = null
    private var chrome: LinearLayout? = null
    private var quietRoot: FrameLayout? = null
    private val wanted = AtomicBoolean(false)
    private val shown = AtomicBoolean(false)
    private var closeWhenLoggedIn = false

    private val watchLogin = object : Runnable {
        override fun run() {
            if (!closeWhenLoggedIn) return
            if (hasSession()) {
                dismiss("登录成功，页面已收起")
                return
            }
            main.postDelayed(this, 1000)
        }
    }

    fun attach(host: ViewGroup) {
        this.host = host
        val page = view ?: return
        if (!wanted.get()) return
        place(page)
    }

    fun detach() {
        chrome?.let { (it.parent as? ViewGroup)?.removeView(it) }
        host = null
        shown.set(false)
    }

    /** Puts the page away. History stays inside the page until then. */
    fun back(): Boolean {
        if (!shown.get()) return false
        dismiss()
        return true
    }

    fun load(html: String) = main.post {
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        wanted.set(true)
        val page = ensure()
        page.setBackgroundColor(Color.TRANSPARENT)
        page.loadDataWithBaseURL(ORIGIN, html, "text/html", "utf-8", null)
        place(page)
        onLog("页面已装上")
    }

    fun url(url: String) = main.post { open(url) }

    private fun open(url: String) {
        val login = loginForm(url)
        if (login && hasSession()) {
            closeWhenLoggedIn = false
            main.removeCallbacks(watchLogin)
            onLog("已经登录")
            return
        }
        val page = ensure()
        page.setBackgroundColor(Color.WHITE)
        if (login) {
            closeWhenLoggedIn = true
            main.removeCallbacks(watchLogin)
            main.postDelayed(watchLogin, 1000)
            page.visibility = View.VISIBLE
            page.isFocusable = true
            page.isFocusableInTouchMode = true
            wanted.set(true)
            page.loadUrl(url)
            place(page)
            onLog("打开 $url")
            return
        }
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        hideVisible()
        page.visibility = View.VISIBLE
        page.isFocusable = false
        page.isFocusableInTouchMode = false
        holdQuiet(page)
        page.loadUrl(url)
        OcService.updateNote(app, "正在后台逛 B 站")
        onLog("后台打开 $url")
    }

    /** Runs on the page and returns its result. Does not bring a closed page back. */
    fun eval(code: String): String {
        val latch = CountDownLatch(1)
        val out = AtomicReference("")
        main.post {
            val page = view
            if (page == null) {
                latch.countDown()
                return@post
            }
            if (page.parent == null) holdQuiet(page)
            try {
                page.evaluateJavascript(code) { value ->
                    out.set(value ?: "")
                    latch.countDown()
                }
            } catch (_: Throwable) {
                latch.countDown()
            }
        }
        latch.await(15, TimeUnit.SECONDS)
        return out.get()
    }

    fun loggedIn(): Boolean = hasSession()

    fun showing(): Boolean = shown.get()

    /** Kept so older scripts can call it. The page already receives touches. */
    fun touch(@Suppress("UNUSED_PARAMETER") on: Boolean) = Unit

    fun clear() = main.post { dismiss() }

    private fun hideVisible() {
        shown.set(false)
        wanted.set(false)
        host?.visibility = View.GONE
        chrome?.let { (it.parent as? ViewGroup)?.removeView(it) }
    }

    private fun dismiss(reason: String = "页面已收起") {
        val was = shown.getAndSet(false) || quietRoot != null
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        wanted.set(false)
        host?.visibility = View.GONE
        chrome?.let { (it.parent as? ViewGroup)?.removeView(it) }
        releaseQuiet()
        view?.stopLoading()
        view?.loadUrl("about:blank")
        OcService.updateNote(app, app.getString(R.string.note))
        if (was) onLog(reason)
    }

    private fun holdQuiet(page: WebView) {
        val root = ensureQuiet()
        if (root == null) {
            val parent = host ?: return
            if (page.parent != parent) {
                (page.parent as? ViewGroup)?.removeView(page)
                parent.addView(page, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            }
            page.visibility = View.INVISIBLE
            parent.isClickable = false
            parent.visibility = View.VISIBLE
            return
        }
        if (page.parent != root) {
            (page.parent as? ViewGroup)?.removeView(page)
            root.addView(page, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        }
        page.importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
    }

    private fun ensureQuiet(): FrameLayout? {
        quietRoot?.let { if (it.isAttachedToWindow) return it }
        if (!Settings.canDrawOverlays(app)) return null
        val wm = app.getSystemService(WindowManager::class.java) ?: return null
        val root = FrameLayout(app)
        val dm = app.resources.displayMetrics
        val params = WindowManager.LayoutParams(
            dm.widthPixels.coerceAtLeast(1),
            dm.heightPixels.coerceAtLeast(1),
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
                WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.START or Gravity.TOP
            x = dm.widthPixels + 80
            y = 0
        }
        return try {
            wm.addView(root, params)
            quietRoot = root
            root
        } catch (_: Throwable) {
            null
        }
    }

    private fun releaseQuiet() {
        val root = quietRoot ?: return
        val page = view
        if (page != null && page.parent == root) root.removeView(page)
        val wm = app.getSystemService(WindowManager::class.java)
        runCatching { wm?.removeView(root) }
        quietRoot = null
    }

    private fun mute(page: WebView) {
        page.evaluateJavascript(
            "(function(){try{if(!window.__ocaMute){window.__ocaMute=1;var play=HTMLMediaElement.prototype.play;HTMLMediaElement.prototype.play=function(){try{this.muted=true;this.volume=0;}catch(e){}return play.apply(this,arguments);};}var ms=document.querySelectorAll('video,audio');for(var i=0;i<ms.length;i++){ms[i].muted=true;ms[i].volume=0;}}catch(e){}})()",
            null,
        )
    }

    private fun ensure(): WebView {
        val existing = view
        if (existing != null) return existing
        val created = WebView(app).apply {
            setBackgroundColor(Color.WHITE)
            isFocusable = true
            isFocusableInTouchMode = true
            isVerticalScrollBarEnabled = true
            isHorizontalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val next = request.url?.toString().orEmpty()
                    if (closeWhenLoggedIn && !loginForm(next) && bilibili(next)) {
                        main.post { if (hasSession()) dismiss("登录成功，页面已收起") }
                        return true
                    }
                    if (!closeWhenLoggedIn && loginForm(next) && !hasSession()) {
                        main.post { open(next) }
                        return true
                    }
                    return false
                }

                override fun onPageFinished(view: WebView, url: String) {
                    if (quietRoot != null && view.parent == quietRoot) mute(view)
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(message: ConsoleMessage): Boolean {
                    onLog(message.message())
                    return true
                }
            }
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = true
            settings.allowFileAccess = false
            settings.useWideViewPort = true
            settings.loadWithOverviewMode = true
            addJavascriptInterface(LogBridge(), "Oca")
        }
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(created, true)
        view = created
        return created
    }

    private fun place(page: WebView) {
        if (!wanted.get()) return
        if (closeWhenLoggedIn && hasSession()) {
            dismiss("登录成功，页面已收起")
            return
        }
        val parent = host ?: return
        val box = chrome ?: buildChrome(page).also { chrome = it }
        if (page.parent != box) {
            (page.parent as? ViewGroup)?.removeView(page)
            box.addView(page, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
        }
        if (box.parent != parent) {
            (box.parent as? ViewGroup)?.removeView(box)
            parent.addView(
                box,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
        parent.visibility = View.VISIBLE
        shown.set(true)
        page.requestFocus()
    }

    private fun buildChrome(page: WebView): LinearLayout {
        val stop = TextView(app).apply {
            text = "结束"
            textSize = 16f
            setTextColor(Color.parseColor("#1C1B19"))
            gravity = Gravity.CENTER_VERTICAL or Gravity.START
            setOnClickListener {
                onStop()
                dismiss()
            }
        }
        val close = TextView(app).apply {
            text = "关闭"
            textSize = 16f
            setTextColor(Color.parseColor("#E85D04"))
            gravity = Gravity.CENTER_VERTICAL or Gravity.END
            setOnClickListener { dismiss() }
        }
        val bar = LinearLayout(app).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            val pad = dp(16)
            setPadding(pad, pad, pad, pad)
            addView(stop, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            addView(close, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        }
        return LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Color.WHITE)
            addView(bar, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
            addView(page, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f))
            ViewCompat.setOnApplyWindowInsetsListener(this) { _, insets ->
                val top = insets.getInsets(WindowInsetsCompat.Type.systemBars()).top
                val pad = dp(16)
                bar.setPadding(pad, pad + top, pad, pad)
                insets
            }
            ViewCompat.requestApplyInsets(this)
        }
    }

    private fun dp(value: Int): Int = (value * app.resources.displayMetrics.density).toInt()

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
            "eval" -> evalFn
            "clear" -> fn { clear() }
            "touch" -> fn { touch(it?.firstOrNull()?.let { v -> JsContext.toBoolean(v) } == true) }
            "loggedIn" -> boolFn { loggedIn() }
            "showing" -> boolFn { showing() }
            else -> NOT_FOUND
        }

        private val evalFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                return eval(text(args))
            }
        }

        private fun fn(body: (Array<out Any>?) -> Unit) = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                body(args)
                return Undefined.instance
            }
        }

        private fun boolFn(body: () -> Boolean) = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                return body()
            }
        }

        private fun text(args: Array<out Any>?): String =
            if (args.isNullOrEmpty()) "" else JsContext.toString(args[0])
    }

    companion object {
        private const val ORIGIN = "https://onlyclaws.local/"

        fun hasSession(): Boolean {
            val jar = CookieManager.getInstance().getCookie("https://www.bilibili.com") ?: return false
            return jar.split(';').any { part ->
                val item = part.trim()
                item.startsWith("SESSDATA=") && item.length > "SESSDATA=".length
            }
        }

        fun loginForm(url: String): Boolean {
            val uri = runCatching { Uri.parse(url) }.getOrNull() ?: return false
            val host = uri.host?.lowercase().orEmpty()
            if (host == "passport.bilibili.com") return true
            return host.endsWith(".bilibili.com") && uri.path?.contains("login") == true
        }

        fun bilibili(url: String): Boolean {
            val host = runCatching { Uri.parse(url).host }?.getOrNull()?.lowercase().orEmpty()
            return host == "bilibili.com" || host.endsWith(".bilibili.com")
        }
    }
}
