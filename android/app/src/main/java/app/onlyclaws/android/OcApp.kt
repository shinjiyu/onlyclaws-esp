package app.onlyclaws.android

import android.app.Application
import android.os.FileObserver
import android.os.Handler
import android.os.Looper
import java.io.File
import java.util.ArrayDeque

class OcApp : Application() {
    val lines = ArrayDeque<String>()
    private val listeners = mutableSetOf<(String) -> Unit>()
    private val main = Handler(Looper.getMainLooper())
    private var lastSource = ""
    private var watcher: FileObserver? = null
    lateinit var container: JsContainer

    override fun onCreate() {
        super.onCreate()
        instance = this
        SessionSeed.fromAssets(this)
        container = JsContainer { line -> append(line) }
        overlay = OverlayPlugin(this, container) { line -> append(line) }
        a2ui = A2uiPlugin(this, container) { line -> append(line) }
        desk = DeskPlugin(container) { line -> append(line) }
        tts = TtsPlugin(this, container) { line -> append(line) }
        wallpaper = WallpaperPlugin(this) { line -> append(line) }
        http = HttpPlugin()
        keys = KeysPlugin(filesDir)
        container.use(overlay)
        container.use(a2ui)
        container.use(desk)
        container.use(tts)
        container.use(wallpaper)
        container.use(http)
        container.use(keys)
        reloadScript()
        watchActiveFile()
    }

    lateinit var overlay: OverlayPlugin
        private set
    lateinit var a2ui: A2uiPlugin
        private set
    lateinit var desk: DeskPlugin
        private set
    lateinit var tts: TtsPlugin
        private set
    lateinit var wallpaper: WallpaperPlugin
        private set
    lateinit var http: HttpPlugin
        private set
    lateinit var keys: KeysPlugin
        private set

    fun reloadScript() {
        val boot = assets.open("boot.js").bufferedReader().readText()
        val saved = container.readActive(this)
        val source = saved ?: boot
        if (source == lastSource) return
        lastSource = source
        container.load(source) { result ->
            result.onFailure { err ->
                append("脚本未加载：${err.message}")
                if (saved != null && boot != lastSource) {
                    lastSource = boot
                    container.load(boot) { }
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

    fun append(line: String) {
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
        lateinit var instance: OcApp
    }
}
