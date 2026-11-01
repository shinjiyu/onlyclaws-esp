package app.onlyclaws.android

import android.annotation.SuppressLint
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.LinearLayout
import java.io.ByteArrayInputStream

/**
 * Main screen inside the app. One inline HTML document, separate from [WebOverlay].
 *
 *   screen.show("<button data-action=\"go\">Go</button>")
 *   screen.clear()
 *
 * Clicks call `onAction({ action, context })`. No navigation, no network, no cookies.
 */
@SuppressLint("SetJavaScriptEnabled")
class ScreenPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    private var host: ViewGroup? = null
    private var empty: View? = null
    private var chrome: View? = null
    private var view: WebView? = null
    private var page: String? = null
    private var capturing = false
    private var staged: String? = null
    private var drawing = true

    override fun install(scope: JsScope) = scope.define("screen") {
        fn("show") { show(it.string(0)) }
        fn("clear") {
            show("")
            ""
        }
    }

    override fun beforeSwap() {
        capturing = true
        staged = null
    }

    override fun afterSwap(ok: Boolean, pumpsFrames: Boolean) {
        capturing = false
        if (!ok) {
            staged = null
            return
        }
        val next = staged
        staged = null
        apply(next.orEmpty())
    }

    override fun setDrawing(enabled: Boolean) {
        drawing = enabled
    }

    fun attach(host: ViewGroup, empty: View, chrome: View? = null) {
        this.host = host
        this.empty = empty
        this.chrome = chrome
        page?.let { present(it) }
    }

    fun detach() {
        host = null
        empty = null
        chrome = null
        main.post {
            view?.let { page ->
                (page.parent as? ViewGroup)?.removeView(page)
                page.destroy()
            }
            view = null
        }
    }

    private fun show(html: String): String {
        if (!drawing) return ""
        if (html.length > ScreenDoc.MAX_CHARS) return "页面太大"
        val doc = if (html.isBlank()) "" else ScreenDoc.document(html)
        if (capturing) {
            staged = doc
            return ""
        }
        apply(doc)
        return ""
    }

    private fun apply(doc: String) {
        if (doc.isEmpty()) {
            page = null
            main.post {
                view?.loadUrl("about:blank")
                reveal(false)
            }
            return
        }
        present(doc)
    }

    private fun present(doc: String) {
        page = doc
        main.post {
            val parent = host ?: return@post
            val page = ensure()
            if (page.parent != parent) {
                (page.parent as? ViewGroup)?.removeView(page)
                parent.addView(
                    page,
                    ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT,
                        ViewGroup.LayoutParams.MATCH_PARENT,
                    ),
                )
            }
            page.loadDataWithBaseURL(ScreenDoc.ORIGIN, doc, "text/html", "utf-8", null)
            reveal(true)
            onLog("界面已装上")
        }
    }

    private fun reveal(showing: Boolean) {
        val host = host ?: return
        chrome?.visibility = if (showing) View.GONE else View.VISIBLE
        host.visibility = if (showing) View.VISIBLE else View.GONE
        empty?.let { pane ->
            pane.visibility = if (showing) View.GONE else View.VISIBLE
            val lp = pane.layoutParams as? LinearLayout.LayoutParams ?: return@let
            lp.height = 0
            lp.weight = if (showing) 0f else 1f
            pane.layoutParams = lp
        }
    }

    private fun ensure(): WebView {
        view?.let { return it }
        val created = WebView(app).apply {
            setBackgroundColor(0xFF141210.toInt())
            settings.javaScriptEnabled = true
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            @Suppress("DEPRECATION")
            settings.allowFileAccessFromFileURLs = false
            @Suppress("DEPRECATION")
            settings.allowUniversalAccessFromFileURLs = false
            settings.domStorageEnabled = false
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            settings.setGeolocationEnabled(false)
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean = true

                override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                    val scheme = request.url?.scheme?.lowercase().orEmpty()
                    if (scheme == "data" || scheme == "about" || scheme == "blob") return null
                    if (request.isForMainFrame && scheme == "https") return null
                    return WebResourceResponse("text/plain", "utf-8", ByteArrayInputStream(ByteArray(0)))
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onJsAlert(view: WebView?, url: String?, message: String?, result: android.webkit.JsResult?): Boolean {
                    result?.confirm()
                    return true
                }
            }
            addJavascriptInterface(Bridge(), "OcaScreen")
        }
        view = created
        return created
    }

    private inner class Bridge {
        @JavascriptInterface
        fun action(name: String?, contextJson: String?) {
            val event = ScreenDoc.event(name.orEmpty(), contextJson) ?: return
            container.fire("onAction", JsJson(event))
        }
    }
}
