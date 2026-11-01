package app.onlyclaws.android

import android.app.Application
import android.os.FileObserver
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.io.File
import java.util.ArrayDeque
import java.util.concurrent.CopyOnWriteArraySet

class OcApp : Application() {
    val lines = ArrayDeque<String>()
    private val listeners = mutableSetOf<(String) -> Unit>()
    private val taps = CopyOnWriteArraySet<(String) -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private var lastSource = ""
    private var watcher: FileObserver? = null
    lateinit var container: JsContainer

    override fun onCreate() {
        super.onCreate()
        instance = this
        SessionSeed.fromAssets(this)
        container = JsContainer(onLog = { line -> append(line) })
        container.onError = { lastScriptError = ScriptError(it, System.currentTimeMillis()) }
        overlay = OverlayPlugin(this, container) { line -> append(line) }
        screen = ScreenPlugin(this, container) { line -> append(line) }
        desk = DeskPlugin(container) { line -> append(line) }
        tts = TtsPlugin(this, container, asr) { line -> append(line) }
        asr.onBargeIn = { tts.interrupt() }
        wallpaper = WallpaperPlugin(this) { line -> append(line) }
        http = HttpPlugin()
        sockets = SocketPlugin()
        ssh = SshPlugin(File(filesDir, "ssh-known.txt"))
        keys = KeysPlugin(filesDir)
        agent = AgentRuntime(this)
        asrPlugin = AsrPlugin(asr, container) { line -> append(line) }
        llm = LlmPlugin(agent.store)
        container.use(overlay)
        container.use(overlay.web)
        container.use(screen)
        container.use(desk)
        container.use(tts)
        container.use(wallpaper)
        container.use(http)
        container.use(sockets)
        container.use(ssh)
        container.use(keys)
        container.use(asrPlugin)
        container.use(llm)
        chat = ChatOverlay(this)
        reloadScript()
        watchActiveFile()
        agent.start()
    }

    lateinit var agent: AgentRuntime
        private set
    lateinit var chat: ChatOverlay
        private set
    val asr by lazy { LocalAsr(this) }
    @Volatile var lastScriptError: ScriptError? = null
        private set

    /** Generated scripts get the host surface, not keys, web, or the desk. */
    fun load(source: String, done: (Result<Unit>) -> Unit) {
        val generated = source.startsWith(HarnessText.MARK)
        val allow: (JsPlugin) -> Boolean = if (generated) {
            { it === overlay || it === screen || it === tts || it === http || it === sockets || it === ssh || it === wallpaper || it === asrPlugin || it === llm }
        } else {
            { true }
        }
        container.load(source, allow) { result ->
            if (result.isSuccess) main.post { lastSource = source }
            done(result)
        }
    }

    lateinit var overlay: OverlayPlugin
        private set
    lateinit var screen: ScreenPlugin
        private set
    lateinit var desk: DeskPlugin
        private set
    lateinit var tts: TtsPlugin
        private set
    lateinit var wallpaper: WallpaperPlugin
        private set
    lateinit var http: HttpPlugin
        private set
    lateinit var sockets: SocketPlugin
        private set
    lateinit var ssh: SshPlugin
        private set
    lateinit var keys: KeysPlugin
        private set
    lateinit var asrPlugin: AsrPlugin
        private set
    lateinit var llm: LlmPlugin
        private set

    fun reloadScript() {
        val boot = assets.open("boot.js").bufferedReader().readText()
        val saved = container.readActive(this)
        val source = saved ?: boot
        if (source == lastSource) return
        lastSource = source
        load(source) { result ->
            result.onFailure { err ->
                append("脚本未加载：${err.message}")
                main.post {
                    if (saved != null && boot != lastSource) {
                        lastSource = boot
                        load(boot) { }
                    }
                }
            }
        }
    }

    private fun watchActiveFile() {
        filesDir.mkdirs()
        val mask = FileObserver.CLOSE_WRITE or FileObserver.MODIFY or FileObserver.MOVED_TO or FileObserver.CREATE
        watcher = object : FileObserver(filesDir.absolutePath, mask) {
            override fun onEvent(event: Int, path: String?) {
                if (path != null && path != "active.js") return
                main.removeCallbacks(reloadRunnable)
                main.postDelayed(reloadRunnable, 250)
            }
        }.also { it.startWatching() }
    }

    private val reloadRunnable = Runnable { reloadScript() }

    /** [tap] sees every log line as it is written, on the writer's thread. */
    fun tap(tap: (String) -> Unit) {
        taps += tap
    }

    fun untap(tap: (String) -> Unit) {
        taps -= tap
    }

    fun append(line: String) {
        Log.i(TAG, line)
        taps.forEach { it(line) }
        main.post {
            lines.addLast(line)
            while (lines.size > 40) lines.removeFirst()
            val text = lines.joinToString("\n")
            listeners.forEach { it(text) }
        }
    }

    fun watch(listener: (String) -> Unit) {
        main.post {
            listeners += listener
            listener(lines.joinToString("\n"))
        }
    }

    fun unwatch(listener: (String) -> Unit) {
        main.post { listeners -= listener }
    }

    companion object {
        private const val TAG = "OCA"
        lateinit var instance: OcApp
    }
}

data class ScriptError(val text: String, val at: Long)
