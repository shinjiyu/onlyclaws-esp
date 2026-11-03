package app.onlyclaws.android

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.KeyEvent
import android.view.MotionEvent
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
import android.content.Intent
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Login stays on screen. Scripted web.url calls sit off-screen and muted.
 * The agent browser shows the page and reads its text.
 * `web.float` puts a transparent WebView on the system overlay so a page
 * (or a video) can play over other apps.
 *
 *   web.load("<html>…</html>")
 *   web.float("<html>…</html>")  // or https://…
 *   web.url("https://…")
 *   web.eval("document.title")
 *   web.touch(true)
 *   web.clear()
 *   web.loggedIn()
 *   web.showing()
 *
 * A Bilibili login URL stays up until SESSDATA is set, then the page is put away.
 * Leaving that login URL for the rest of Bilibili does not show the home page.
 * Float needs overlay permission. It is not muted. Touches pass through until
 * `web.touch(true)`.
 */
@SuppressLint("SetJavaScriptEnabled")
class WebOverlay(
    private val app: Context,
    private val onLog: (String) -> Unit,
    private val onStop: () -> Unit = {},
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    private var host: ViewGroup? = null
    private var view: WebView? = null
    private var chrome: LinearLayout? = null
    private var quietRoot: FrameLayout? = null
    private var floatRoot: FrameLayout? = null
    private var floatParams: WindowManager.LayoutParams? = null
    private var floatTouchable = false
    private val wanted = AtomicBoolean(false)
    private val shown = AtomicBoolean(false)
    private var closeWhenLoggedIn = false
    private var loadToken = 0
    private var pending: Pair<Int, CompletableFuture<String>>? = null
    private var afterAction: CompletableFuture<String>? = null
    private var afterNote = ""
    private var pageLoading = false

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
        releaseFloat()
        releaseQuiet()
        val page = ensure()
        page.setBackgroundColor(Color.TRANSPARENT)
        page.loadDataWithBaseURL(ORIGIN, html, "text/html", "utf-8", null)
        place(page)
        onLog("页面已装上")
    }

    fun url(url: String) = main.post { open(url) }

    /** Open an https page on screen and return its title plus visible text. */
    fun browse(raw: String): String {
        val url = https(raw) ?: return "只打开 https 网址"
        val done = CompletableFuture<String>()
        main.post { begin(url, done) }
        return runCatching { done.get(20, TimeUnit.SECONDS) }.getOrElse { "页面打开超时" }
    }

    /** Click, type, scroll, press a key, pick an option, or go back. Returns the page afterwards. */
    fun act(specJson: String): String {
        val spec = runCatching { JSONObject(specJson) }.getOrElse { return "操作格式不对" }
        val done = CompletableFuture<String>()
        main.post { perform(spec, done) }
        return runCatching { done.get(15, TimeUnit.SECONDS) }.getOrElse { "操作超时" }
    }

    /** Read the page already open. Does not navigate. */
    fun readPage(): String {
        val done = CompletableFuture<String>()
        main.post {
            val page = view
            val current = page?.url.orEmpty()
            if (page == null || current.isBlank() || current == "about:blank" || !shown.get()) {
                done.complete("浏览器关着")
                return@post
            }
            snapshot(page, done)
        }
        return runCatching { done.get(8, TimeUnit.SECONDS) }.getOrElse { "读不到页面" }
    }

    /** Run a script in the open page and return its value. The page stays on screen. */
    fun run(code: String): String {
        val trimmed = code.trim()
        if (trimmed.isEmpty()) return "没有脚本"
        if (trimmed.length > 20_000) return "脚本太长"
        val lower = trimmed.lowercase()
        if (lower.contains("document.cookie") || lower.contains("localstorage") || lower.contains("sessionstorage")) {
            return "不要用脚本读取登录凭证"
        }
        val done = CompletableFuture<String>()
        main.post {
            val page = view
            val current = page?.url.orEmpty()
            if (page == null || current.isBlank() || current == "about:blank" || !shown.get()) {
                done.complete("浏览器关着")
                return@post
            }
            bringPage()
            page.evaluateJavascript("(function(code){$RUN})(${JSONObject.quote(trimmed)})") { value ->
                val text = unwrap(value)
                done.complete(if (text.length > 8000) text.take(8000) + "\n…" else text)
            }
        }
        return runCatching { done.get(15, TimeUnit.SECONDS) }.getOrElse { "脚本超时" }
    }

    /** Transparent page on the system overlay. HTML, or an http(s) URL. */
    fun float(src: String) = main.post { openFloat(src) }

    private fun begin(url: String, done: CompletableFuture<String>) {
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        releaseFloat()
        releaseQuiet()
        val page = ensure()
        page.setBackgroundColor(Color.WHITE)
        wanted.set(true)
        pending?.second?.complete("被新的页面打断")
        val token = ++loadToken
        pending = token to done
        present(page)
        page.stopLoading()
        if (page.url == url) page.reload() else page.loadUrl(url)
        main.post { if (wanted.get()) present(page) }
        onLog("打开 $url")
    }

    private fun perform(spec: JSONObject, done: CompletableFuture<String>) {
        val page = view
        val current = page?.url.orEmpty()
        if (page == null || current.isBlank() || current == "about:blank" || !shown.get()) {
            done.complete("浏览器关着")
            return
        }
        bringPage()
        val action = spec.optString("action").trim().lowercase()
        if (action == "back") {
            if (!page.canGoBack()) {
                done.complete("没有上一页")
                return
            }
            page.goBack()
            onLog("网页返回")
            settle(page, "已返回上一页", done, 2500)
            return
        }
        page.evaluateJavascript(actionScript(spec)) { raw ->
            val payload = unwrap(raw)
            val result = runCatching { JSONObject(payload) }.getOrNull()
            if (result == null || !result.optBoolean("ok")) {
                val err = result?.optString("error").orEmpty().ifBlank { "没点到" }
                done.complete(err)
                return@evaluateJavascript
            }
            when (action) {
                "click" -> {
                    tap(page, result)
                    val label = result.optString("label").ifBlank { spec.optString("target") }
                    onLog("点击 $label")
                    settle(page, "已点击「$label」", done, 2200)
                }
                "type" -> {
                    tap(page, result)
                    val text = spec.optString("text")
                    main.postDelayed({
                        page.evaluateJavascript(typeScript(text)) {
                            onLog("输入")
                            settle(page, "已输入", done, 800)
                        }
                    }, 180)
                }
                "key" -> {
                    val name = spec.optString("key").ifBlank { spec.optString("text") }
                    if (!press(page, name)) {
                        done.complete("不认识这个键")
                        return@evaluateJavascript
                    }
                    onLog("按键 $name")
                    settle(page, "已按 $name", done, 1500)
                }
                "scroll" -> settle(page, "已滚动", done, 500)
                "select" -> {
                    val label = result.optString("label").ifBlank { spec.optString("text") }
                    onLog("选择 $label")
                    settle(page, "已选择「$label」", done, 800)
                }
                else -> done.complete("不认识的操作")
            }
        }
    }

    private fun bringPage() {
        val page = view ?: return
        wanted.set(true)
        present(page)
    }

    /** Put the page back on screen. A closed WebView still has a document, so this must run before any read. */
    private fun present(page: WebView) {
        page.onResume()
        page.resumeTimers()
        bringActivity()
        if (host != null) place(page)
    }

    private fun bringActivity() {
        runCatching {
            app.startActivity(
                Intent(app, MainActivity::class.java)
                    .addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK or
                            Intent.FLAG_ACTIVITY_SINGLE_TOP or
                            Intent.FLAG_ACTIVITY_REORDER_TO_FRONT,
                    ),
            )
        }
    }

    private fun settle(page: WebView, note: String, done: CompletableFuture<String>, delayMs: Long) {
        afterNote = note
        afterAction = done
        main.postDelayed({
            if (afterAction !== done || done.isDone || pageLoading) return@postDelayed
            afterAction = null
            snapshot(page, done, note)
        }, delayMs)
        main.postDelayed({
            if (afterAction !== done || done.isDone) return@postDelayed
            afterAction = null
            snapshot(page, done, note)
        }, 12000)
    }

    private fun tap(page: WebView, result: JSONObject) {
        if (!result.has("x") || !result.has("y")) return
        val density = page.resources.displayMetrics.density
        val scale = result.optDouble("scale", 1.0).toFloat().coerceAtLeast(0.1f)
        val x = result.optDouble("x").toFloat() * scale * density
        val y = result.optDouble("y").toFloat() * scale * density
        val now = SystemClock.uptimeMillis()
        val down = MotionEvent.obtain(now, now, MotionEvent.ACTION_DOWN, x, y, 0)
        val up = MotionEvent.obtain(now, now + 60, MotionEvent.ACTION_UP, x, y, 0)
        page.dispatchTouchEvent(down)
        page.dispatchTouchEvent(up)
        down.recycle()
        up.recycle()
    }

    private fun press(page: WebView, name: String): Boolean {
        val code = when (name.trim().lowercase()) {
            "enter", "return" -> KeyEvent.KEYCODE_ENTER
            "tab" -> KeyEvent.KEYCODE_TAB
            "escape", "esc" -> KeyEvent.KEYCODE_ESCAPE
            "backspace", "delete" -> KeyEvent.KEYCODE_DEL
            "arrowdown", "down" -> KeyEvent.KEYCODE_DPAD_DOWN
            "arrowup", "up" -> KeyEvent.KEYCODE_DPAD_UP
            else -> return false
        }
        val now = SystemClock.uptimeMillis()
        page.dispatchKeyEvent(KeyEvent(now, now, KeyEvent.ACTION_DOWN, code, 0))
        page.dispatchKeyEvent(KeyEvent(now, now + 30, KeyEvent.ACTION_UP, code, 0))
        return true
    }

    private fun actionScript(spec: JSONObject): String = "(function(spec){$ACT})(${spec})"

    private fun typeScript(text: String): String = "(function(text){$TYPE})(${JSONObject.quote(text)})"

    private fun snapshot(page: WebView, done: CompletableFuture<String>, note: String = "") {
        if (done.isDone) return
        page.evaluateJavascript(SNAPSHOT) { value ->
            if (done.isDone) return@evaluateJavascript
            val body = unwrap(value)
            done.complete(if (note.isBlank()) body else "$note\n\n$body")
        }
    }

    private fun https(raw: String): String? {
        val trimmed = raw.trim()
        if (trimmed.isEmpty()) return null
        if (trimmed.startsWith("http://")) return null
        val url = if (trimmed.startsWith("https://")) trimmed else "https://$trimmed"
        val uri = runCatching { Uri.parse(url) }.getOrNull() ?: return null
        if (uri.scheme != "https" || uri.host.isNullOrBlank()) return null
        return url
    }

    private fun unwrap(value: String?): String {
        if (value.isNullOrBlank() || value == "null") return "页面是空的"
        return runCatching {
            val text = org.json.JSONArray("[$value]").getString(0)
            text.ifBlank { "页面是空的" }
        }.getOrElse { value.trim('"').ifBlank { "页面是空的" } }
    }

    private fun open(url: String) {
        releaseFloat()
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

    private fun openFloat(src: String) {
        if (!Settings.canDrawOverlays(app)) {
            onLog("浮层未授权")
            return
        }
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        wanted.set(true)
        hideChrome()
        releaseQuiet()
        val page = ensure()
        page.setBackgroundColor(Color.TRANSPARENT)
        page.setLayerType(View.LAYER_TYPE_HARDWARE, null)
        page.settings.mediaPlaybackRequiresUserGesture = false
        page.visibility = View.VISIBLE
        holdFloat(page)
        applyFloatInput()
        if (src.startsWith("https://") || src.startsWith("http://")) {
            page.loadUrl(src)
        } else {
            page.loadDataWithBaseURL(ORIGIN, src, "text/html", "utf-8", null)
        }
        shown.set(true)
        OcService.updateNote(app, "浮层页面在播")
        onLog("浮层页面已打开")
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

    /** When floating, true takes touches; false lets them pass through to apps below. */
    fun touch(on: Boolean) = main.post {
        floatTouchable = on
        applyFloatInput()
    }

    fun clear() = main.post { dismiss() }

    private fun hideVisible() {
        shown.set(false)
        wanted.set(false)
        hideChrome()
        releaseFloat()
    }

    private fun hideChrome() {
        host?.visibility = View.GONE
        chrome?.let { (it.parent as? ViewGroup)?.removeView(it) }
    }

    private fun dismiss(reason: String = "页面已收起") {
        val was = shown.getAndSet(false) || quietRoot != null || floatRoot != null
        closeWhenLoggedIn = false
        main.removeCallbacks(watchLogin)
        wanted.set(false)
        hideChrome()
        releaseQuiet()
        releaseFloat()
        view?.stopLoading()
        view?.onPause()
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

    private fun holdFloat(page: WebView) {
        val root = ensureFloat() ?: return
        if (page.parent != root) {
            (page.parent as? ViewGroup)?.removeView(page)
            root.addView(
                page,
                FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT),
            )
        }
    }

    private fun ensureFloat(): FrameLayout? {
        floatRoot?.let { if (it.isAttachedToWindow) return it }
        if (!Settings.canDrawOverlays(app)) return null
        val wm = app.getSystemService(WindowManager::class.java) ?: return null
        val root = FrameLayout(app).apply { setBackgroundColor(Color.TRANSPARENT) }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            floatFlags(),
            PixelFormat.TRANSLUCENT,
        ).apply { gravity = Gravity.START or Gravity.TOP }
        return try {
            wm.addView(root, params)
            floatRoot = root
            floatParams = params
            root
        } catch (_: Throwable) {
            onLog("浮层打不开")
            null
        }
    }

    private fun floatFlags(): Int {
        var flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED
        if (!floatTouchable) flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        return flags
    }

    private fun applyFloatInput() {
        val page = view
        val focus = floatTouchable
        page?.isFocusable = focus
        page?.isFocusableInTouchMode = focus
        val root = floatRoot ?: return
        val params = floatParams ?: return
        val next = floatFlags()
        if (params.flags == next) return
        params.flags = next
        if (root.isAttachedToWindow) {
            runCatching { app.getSystemService(WindowManager::class.java)?.updateViewLayout(root, params) }
        }
    }

    private fun releaseFloat() {
        val root = floatRoot ?: return
        val page = view
        if (page != null && page.parent == root) root.removeView(page)
        val wm = app.getSystemService(WindowManager::class.java)
        runCatching { wm?.removeView(root) }
        floatRoot = null
        floatParams = null
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

                override fun onPageStarted(view: WebView, url: String, favicon: android.graphics.Bitmap?) {
                    pageLoading = true
                }

                override fun onPageFinished(view: WebView, url: String) {
                    pageLoading = false
                    if (url == "about:blank") return
                    if (quietRoot != null && view.parent == quietRoot) mute(view)
                    val token = ++loadToken
                    val waiting = pending
                    if (waiting != null) {
                        main.postDelayed({
                            val current = pending
                            if (current == null || current.first != waiting.first || loadToken != token) return@postDelayed
                            if (!shown.get() || !view.isAttachedToWindow) {
                                if (wanted.get()) place(view)
                                main.postDelayed({
                                    val again = pending
                                    if (again == null || again.first != waiting.first) return@postDelayed
                                    pending = null
                                    if (!shown.get() || !view.isAttachedToWindow) {
                                        again.second.complete("页面没有显示出来")
                                    } else {
                                        snapshot(view, again.second)
                                    }
                                }, 400)
                                return@postDelayed
                            }
                            pending = null
                            snapshot(view, current.second)
                        }, 700)
                    }
                    val actionWait = afterAction
                    val note = afterNote
                    if (actionWait != null && !actionWait.isDone) {
                        main.postDelayed({
                            if (afterAction !== actionWait || actionWait.isDone) return@postDelayed
                            afterAction = null
                            snapshot(view, actionWait, note)
                        }, 700)
                    }
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

    override fun install(scope: JsScope) = scope.define("web") {
        fn("load") { load(it.string(0)); Unit }
        fn("float") { float(it.string(0)); Unit }
        fn("url") { url(it.string(0)); Unit }
        fn("eval") { eval(it.string(0)) }
        fn("clear") { clear(); Unit }
        fn("touch") { touch(it.bool(0)) }
        fn("loggedIn") { loggedIn() }
        fn("showing") { showing() }
    }

    companion object {
        private const val ORIGIN = "https://onlyclaws.local/"
        private const val ACT = """
          function textOf(el) {
            if (!el) return "";
            var raw = el.innerText || el.value || "";
            var aria = el.getAttribute ? (el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") || "") : "";
            return String(raw || aria).replace(/\s+/g, " ").trim();
          }
          function visible(el) {
            if (!el || !el.getBoundingClientRect) return false;
            var r = el.getBoundingClientRect();
            if (r.width < 1 || r.height < 1) return false;
            var st = el.ownerDocument.defaultView.getComputedStyle(el);
            return st.visibility !== "hidden" && st.display !== "none";
          }
          function docs(root) {
            var out = [root];
            var frames = root.querySelectorAll ? root.querySelectorAll("iframe") : [];
            for (var i = 0; i < frames.length; i++) {
              try { if (frames[i].contentDocument) out = out.concat(docs(frames[i].contentDocument)); } catch (e) {}
            }
            return out;
          }
          function point(el) {
            el.scrollIntoView({ block: "center", inline: "center" });
            var r = el.getBoundingClientRect();
            var x = r.left + r.width / 2;
            var y = r.top + r.height / 2;
            var win = el.ownerDocument.defaultView;
            while (win && win.frameElement) {
              var fr = win.frameElement.getBoundingClientRect();
              x += fr.left;
              y += fr.top;
              win = win.frameElement.ownerDocument.defaultView;
            }
            var scale = window.visualViewport ? window.visualViewport.scale : 1;
            var pages = docs(document);
            for (var i = 0; i < pages.length; i++) {
              var marked = pages[i].querySelectorAll("[data-oca-focus]");
              for (var j = 0; j < marked.length; j++) marked[j].removeAttribute("data-oca-focus");
            }
            el.setAttribute("data-oca-focus", "1");
            return { ok: true, x: x, y: y, scale: scale, label: textOf(el).slice(0, 80) };
          }
          function find(target) {
            target = String(target || "").trim();
            if (!target) return null;
            var pages = docs(document);
            var sel = null;
            if (/^[#.[]/.test(target) || /^[a-zA-Z][\w-]*[\[.#\s:>]/.test(target)) {
              for (var i = 0; i < pages.length && !sel; i++) {
                try { sel = pages[i].querySelector(target); } catch (e) {}
              }
            }
            if (sel) return sel;
            var want = target.replace(/\s+/g, " ").toLowerCase();
            var loose = null;
            for (var p = 0; p < pages.length; p++) {
              var nodes = pages[p].querySelectorAll("a,button,input,textarea,select,label,summary,[role=button],[role=link],[role=tab],[role=menuitem]");
              for (var n = 0; n < nodes.length; n++) {
                var el = nodes[n];
                var label = textOf(el).toLowerCase();
                if (!label || !visible(el)) continue;
                if (label === want) return el;
                if (!loose && label.indexOf(want) >= 0) loose = el;
              }
            }
            return loose;
          }
          if (spec.action === "scroll") {
            var dy = Number(spec.dy || 640);
            var box = spec.target ? find(spec.target) : null;
            if (box && box.scrollHeight > box.clientHeight + 8) box.scrollBy(0, dy);
            else window.scrollBy(0, dy);
            return JSON.stringify({ ok: true, scrolled: dy });
          }
          if (spec.action === "select") {
            var menu = find(spec.target || "");
            if (!menu || !menu.options) return JSON.stringify({ ok: false, error: "找不到下拉框" });
            var want = String(spec.text || "").replace(/\s+/g, " ").trim().toLowerCase();
            var chosen = "";
            for (var i = 0; i < menu.options.length; i++) {
              var opt = menu.options[i];
              var name = String(opt.text || opt.value || "").replace(/\s+/g, " ").trim().toLowerCase();
              if (name === want || name.indexOf(want) >= 0) {
                menu.value = opt.value;
                chosen = opt.text || opt.value;
                break;
              }
            }
            if (!chosen) return JSON.stringify({ ok: false, error: "没有这个选项" });
            menu.dispatchEvent(new Event("input", { bubbles: true }));
            menu.dispatchEvent(new Event("change", { bubbles: true }));
            return JSON.stringify({ ok: true, label: chosen });
          }
          if (spec.action === "key") return JSON.stringify({ ok: true });
          var hit = find(spec.target || "");
          if (!hit) return JSON.stringify({ ok: false, error: "找不到「" + (spec.target || "") + "」" });
          return JSON.stringify(point(hit));
        """

        private const val TYPE = """
          function marked(root) {
            var hit = root.querySelector ? root.querySelector("[data-oca-focus='1']") : null;
            if (hit) return hit;
            var frames = root.querySelectorAll ? root.querySelectorAll("iframe") : [];
            for (var i = 0; i < frames.length; i++) {
              try {
                if (frames[i].contentDocument) {
                  var inner = marked(frames[i].contentDocument);
                  if (inner) return inner;
                }
              } catch (e) {}
            }
            return null;
          }
          var el = marked(document) || document.activeElement;
          if (!el || el === document.body || el === document.documentElement) return "找不到输入框";
          if (el.removeAttribute) el.removeAttribute("data-oca-focus");
          el.focus();
          if (el.isContentEditable) {
            document.execCommand("selectAll", false, null);
            document.execCommand("insertText", false, text);
            return "已输入";
          }
          var proto = window.HTMLTextAreaElement && el instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
          var desc = Object.getOwnPropertyDescriptor(proto, "value");
          if (desc && desc.set) desc.set.call(el, text);
          else el.value = text;
          try {
            el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
          } catch (e) {
            el.dispatchEvent(new Event("input", { bubbles: true }));
          }
          el.dispatchEvent(new Event("change", { bubbles: true }));
          return "已输入";
        """

        private const val RUN = """
          try {
            var value = (0, eval)(code);
            if (typeof value === "undefined") return "完成";
            if (typeof value === "string") return value;
            return JSON.stringify(value);
          } catch (e) {
            return "脚本出错：" + (e && e.message ? e.message : String(e));
          }
        """

        private const val SNAPSHOT = """
            (function(){
              function label(el) {
                return String(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "")
                  .replace(/\s+/g, " ").trim().slice(0, 40);
              }
              function sel(el) {
                var tag = el.tagName.toLowerCase();
                if (el.id) return "#" + el.id;
                var name = el.getAttribute("name");
                if (name) return tag + "[name='" + name.replace(/'/g, "\\'") + "']";
                return "";
              }
              var title = document.title || "";
              var text = (document.body && document.body.innerText) || "";
              text = text.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
              if (text.length > 4000) text = text.slice(0, 4000) + "\n…";
              var lines = [];
              var nodes = document.querySelectorAll("a,button,input,textarea,select,[role=button],[role=link]");
              for (var i = 0; i < nodes.length && lines.length < 40; i++) {
                var el = nodes[i];
                var r = el.getBoundingClientRect();
                if (r.width < 1 || r.height < 1) continue;
                var tag = el.tagName.toLowerCase();
                var kind = tag === "input" && el.type ? tag + ":" + el.type : tag;
                lines.push(kind + " 「" + label(el) + "」 " + sel(el));
              }
              return "网址 " + location.href + "\n标题 " + title + "\n\n" + text + "\n\n可操作\n" + lines.join("\n");
            })()
        """

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
