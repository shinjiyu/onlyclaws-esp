package app.onlyclaws.android

import android.content.Context
import android.content.Intent
import android.media.MediaPlayer
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.VideoView
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.a2ui.A2uiSurface
import androidx.compose.material3.a2ui.catalog.MaterialA2uiBasicCatalogV1Defaults
import androidx.compose.material3.a2ui.catalog.materialA2uiBasicCatalogV1
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONObject
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.NativeJSON
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined
import androidx.a2ui.compose.runtime.A2uiMessageParser
import androidx.a2ui.compose.ui.A2uiMessageProcessor
import androidx.a2ui.model.catalog.functions.A2uiLocaleProvider
import androidx.a2ui.model.processor.processInput
import androidx.a2ui.model.protocol.A2uiClientErrorMessage
import androidx.a2ui.model.protocol.A2uiClientEventMessage
import androidx.a2ui.model.protocol.A2uiClientToServerMessage

/**
 * App surface. The script sends A2UI protocol messages; the Material 3
 * Basic Catalog draws every component in that catalog.
 *
 *   a2ui.catalog
 *   a2ui.send({ version: "v0.9", createSurface: { surfaceId: "main", catalogId: a2ui.catalog } })
 *   a2ui.send({ version: "v0.9", updateComponents: { surfaceId: "main", components: [...] } })
 *   a2ui.clear()
 *
 * Button and field actions call `onAction({ id, action })` on the container thread.
 */
class A2uiPlugin(
    private val app: Context,
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    private var host: ViewGroup? = null
    private var empty: View? = null
    private var chrome: View? = null
    private var processor: androidx.a2ui.model.processor.A2uiMessageProcessor? = null
    private var parser: androidx.a2ui.model.processor.A2uiMessageParser<String>? = null
    private val pending = ArrayDeque<String>()
    private val surfaceIds = LinkedHashSet<String>()

    val catalogId: String = CATALOG

    fun attach(host: ViewGroup, empty: View, chrome: View? = null) {
        this.host = host
        this.empty = empty
        this.chrome = chrome
        main.post {
            host.removeAllViews()
            val compose = ComposeView(host.context).apply {
                setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed)
                setContent { CatalogHost(this@A2uiPlugin) }
            }
            host.addView(
                compose,
                ViewGroup.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
        }
    }

    fun detach() {
        host = null
        empty = null
        chrome = null
    }

    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "a2ui", api)
    }

    internal fun bind(
        processor: androidx.a2ui.model.processor.A2uiMessageProcessor,
        parser: androidx.a2ui.model.processor.A2uiMessageParser<String>,
        reportedCatalog: String,
    ) {
        this.processor = processor
        this.parser = parser
        if (reportedCatalog != catalogId) onLog("目录号是 $reportedCatalog")
        val queued = pending.toList()
        pending.clear()
        queued.forEach { deliver(it) }
    }

    internal fun onOutbound(event: A2uiClientToServerMessage) {
        when (event) {
            is A2uiClientEventMessage -> fire(event.componentId, event.type.ifEmpty { event.componentId })
            is A2uiClientErrorMessage -> onLog("界面错误 ${event.message}")
        }
    }

    internal fun onSurfaces(showing: Boolean) {
        main.post {
            val host = host ?: return@post
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
    }

    private fun send(payload: Any?) {
        val json = stringify(payload) ?: run {
            onLog("a2ui.send 需要一条协议消息")
            return
        }
        deliver(json)
    }

    private fun deliver(json: String) {
        note(json)
        val processor = processor
        val parser = parser
        if (processor == null || parser == null) {
            pending.add(json)
            return
        }
        processor.processInput(parser, json)
    }

    private fun clear() {
        val ids = surfaceIds.toList()
        if (ids.isEmpty()) return
        for (id in ids) {
            deliver(
                JSONObject()
                    .put("version", "v0.9")
                    .put("deleteSurface", JSONObject().put("surfaceId", id))
                    .toString(),
            )
        }
    }

    private fun note(json: String) {
        val obj = runCatching { JSONObject(json) }.getOrNull() ?: return
        obj.optJSONObject("createSurface")?.optString("surfaceId")?.takeIf { it.isNotEmpty() }?.let {
            surfaceIds += it
        }
        obj.optJSONObject("deleteSurface")?.optString("surfaceId")?.takeIf { it.isNotEmpty() }?.let {
            surfaceIds -= it
        }
    }

    private fun fire(id: String, action: String) {
        container.enter { cx, scope ->
            val fn = scope.get("onAction", scope)
            if (fn !is BaseFunction) return@enter
            val event = cx.newObject(scope)
            ScriptableObject.putProperty(event, "id", id)
            ScriptableObject.putProperty(event, "action", action)
            fn.call(cx, scope, scope, arrayOf(event))
        }
    }

    private fun stringify(payload: Any?): String? = when (payload) {
        null, is Undefined -> null
        is String -> payload
        is JSONObject -> payload.toString()
        else -> runCatching {
            NativeJSON.stringify(
                JsContext.getCurrentContext(),
                JsContext.getCurrentContext().initStandardObjects(),
                payload,
                null,
                null,
            ) as String
        }.getOrNull()
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "a2ui"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "send", "push" -> sendFn
            "clear" -> clearFn
            "catalog" -> catalogId
            else -> NOT_FOUND
        }

        private val sendFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                send(args?.firstOrNull())
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

    companion object {
        const val CATALOG = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
    }
}

@Composable
private fun CatalogHost(plugin: A2uiPlugin) {
    val context = LocalContext.current
    val catalog = remember(context) {
        materialA2uiBasicCatalogV1(
            image = MaterialA2uiBasicCatalogV1Defaults.image { url, description, scale, modifier, onError ->
                AsyncImage(
                    model = url,
                    contentDescription = description,
                    contentScale = scale,
                    modifier = modifier,
                    onError = { state -> onError(state.result.throwable) },
                )
            },
            video = MaterialA2uiBasicCatalogV1Defaults.video { url, modifier, onError ->
                AndroidView(
                    factory = { ctx ->
                        VideoView(ctx).apply {
                            setVideoURI(Uri.parse(url))
                            setOnPreparedListener { it.start() }
                            setOnErrorListener { _, what, extra ->
                                onError(IllegalStateException("video $what/$extra"))
                                true
                            }
                        }
                    },
                    modifier = modifier,
                )
            },
            audioPlayer = MaterialA2uiBasicCatalogV1Defaults.audioPlayer { url, description, modifier, onError ->
                AudioClip(url, description, modifier, onError)
            },
            urlOpener = { url ->
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            },
            messageFormatter = { pattern, locale, args ->
                java.text.MessageFormat(pattern, locale).format(args.values.toTypedArray())
            },
            localeProvider = A2uiLocaleProvider.Default,
        )
    }
    val parser = remember { A2uiMessageParser() }
    val processor = remember(catalog) { A2uiMessageProcessor(catalogs = listOf(catalog)) }
    LaunchedEffect(processor) {
        plugin.bind(processor, parser, catalog.id)
        launch(Dispatchers.Default) { processor.collectMessages() }
    }
    LaunchedEffect(processor) {
        processor.outboundEvents.collect { plugin.onOutbound(it) }
    }
    val surfaces by processor.activeSurfaces.collectAsStateWithLifecycle()
    LaunchedEffect(surfaces.isEmpty()) { plugin.onSurfaces(surfaces.isNotEmpty()) }
    MaterialTheme {
        Column(Modifier.fillMaxSize()) {
            for (surface in surfaces) {
                key(surface.id) {
                    A2uiSurface(
                        surfaceModel = surface,
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f),
                    )
                }
            }
        }
    }
}

@Composable
private fun AudioClip(
    url: String,
    description: String?,
    modifier: Modifier,
    onError: (Throwable) -> Unit,
) {
    androidx.compose.runtime.DisposableEffect(url) {
        val player = MediaPlayer()
        try {
            player.setDataSource(url)
            player.setOnPreparedListener { it.start() }
            player.setOnErrorListener { _, what, extra ->
                onError(IllegalStateException("audio $what/$extra"))
                true
            }
            player.prepareAsync()
        } catch (t: Throwable) {
            onError(t)
        }
        onDispose { player.release() }
    }
    Text(description.orEmpty(), modifier = modifier)
}
