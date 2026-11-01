package app.onlyclaws.android

import android.annotation.SuppressLint
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.util.Log
import android.widget.ArrayAdapter
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject

/**
 * A system overlay: a draggable ball that expands into the agent chat.
 * Collapsed it does not take focus, so it does not steal touches from the app underneath.
 */
class ChatOverlay(private val app: OcApp) {
    private val main = Handler(Looper.getMainLooper())
    private val wm = app.getSystemService(WindowManager::class.java)
    private val density = app.resources.displayMetrics.density
    private val ball = TextView(app)
    private val panel = LinearLayout(app)
    private val messages = LinearLayout(app)
    private val scroll = ScrollView(app)
    private val chatPane = LinearLayout(app)
    private val settingsPane = ScrollView(app)
    private val tabChat = TextView(app)
    private val tabSettings = TextView(app)
    private val input = EditText(app)
    private val status = TextView(app)
    private val talk = TextView(app)
    private val send = TextView(app)
    private val keyFields = LinkedHashMap<String, EditText>()
    private var providerSpin: Spinner? = null
    private var modelSpin: Spinner? = null
    private var customName: EditText? = null
    private var customUrl: EditText? = null
    private var customModel: EditText? = null
    private var customKey: EditText? = null
    private var onChat = true
    private var added = false
    private var open = false
    private var streaming: TextView? = null
    private var streamText = ""
    private var listening = false
    private var ballX = 0
    private var ballY = 0

    fun attach() {
        if (!Settings.canDrawOverlays(app)) {
            app.append("聊天在悬浮窗里。先允许「在其他应用上层显示」。")
            return
        }
        if (added) return
        build()
        addBall()
        app.agent.watch(::onEvent)
        if (app.agent.ready && app.agent.info.isNotBlank()) {
            status.text = readyLabel(app.agent.info)
        }
        added = true
    }

    fun detach() {
        if (!added) return
        app.agent.unwatch(::onEvent)
        runCatching { wm.removeView(if (open) panel else ball) }
        added = false
        open = false
    }

    private fun build() {
        ball.text = "爪"
        ball.textSize = 18f
        ball.setTextColor(Color.WHITE)
        ball.gravity = Gravity.CENTER
        ball.typeface = Typeface.DEFAULT_BOLD
        ball.background = round(ACCENT, 28)
        ball.setOnTouchListener(ballTouch())

        panel.orientation = LinearLayout.VERTICAL
        panel.background = round(0xF2FFFFFF.toInt(), 16)
        panel.setPadding(dp(12), dp(10), dp(12), dp(10))
        panel.elevation = dp(8).toFloat()

        val top = LinearLayout(app).apply { orientation = LinearLayout.HORIZONTAL }
        top.addView(tab("聊天", tabChat) { showTab(true) })
        top.addView(tab("设置", tabSettings) { showTab(false) })
        top.addView(LinearLayout(app), LinearLayout.LayoutParams(0, 1, 1f))
        top.addView(chip("收起") { collapse() })
        panel.addView(top)

        status.textSize = 12f
        status.setTextColor(MUTED)
        status.setPadding(0, dp(4), 0, dp(4))
        panel.addView(status)

        chatPane.orientation = LinearLayout.VERTICAL
        messages.orientation = LinearLayout.VERTICAL
        scroll.addView(messages)
        chatPane.addView(scroll, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        settingsPane.addView(buildSettings())
        val body = FrameLayout(app)
        body.addView(chatPane, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        body.addView(settingsPane, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        panel.addView(body, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        showTab(true)

        val row = LinearLayout(app).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        input.hint = "说一句，或打字"
        input.setHintTextColor(MUTED)
        input.setTextColor(INK)
        input.textSize = 15f
        input.setBackgroundColor(0xFFF3F3F3.toInt())
        input.setPadding(dp(10), dp(8), dp(10), dp(8))
        input.maxLines = 4
        input.imeOptions = EditorInfo.IME_ACTION_SEND
        input.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_SEND) {
                submit()
                true
            } else false
        }
        row.addView(input, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        talk.text = "说"
        talk.setTextColor(INK)
        talk.gravity = Gravity.CENTER
        talk.setPadding(dp(12), dp(8), dp(12), dp(8))
        talk.setOnTouchListener { v, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    v.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                    startTalk()
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> stopTalk()
            }
            true
        }
        send.text = "发"
        send.setTextColor(Color.WHITE)
        send.gravity = Gravity.CENTER
        send.background = round(ACCENT, 8)
        send.setPadding(dp(14), dp(8), dp(14), dp(8))
        send.setOnClickListener { submit() }
        row.addView(talk)
        row.addView(send, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            marginStart = dp(6)
        })
        chatPane.addView(row, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(8)
        })
    }

    private fun showTab(chat: Boolean) {
        onChat = chat
        chatPane.visibility = if (chat) View.VISIBLE else View.GONE
        settingsPane.visibility = if (chat) View.GONE else View.VISIBLE
        tabChat.setTextColor(if (chat) ACCENT else MUTED)
        tabSettings.setTextColor(if (chat) MUTED else ACCENT)
        tabChat.typeface = if (chat) Typeface.DEFAULT_BOLD else Typeface.DEFAULT
        tabSettings.typeface = if (chat) Typeface.DEFAULT else Typeface.DEFAULT_BOLD
        if (!chat) {
            hideKeyboard()
            refreshSettings()
        }
    }

    private fun refreshSettings() {
        settingsPane.removeAllViews()
        settingsPane.addView(buildSettings())
    }

    private fun tab(text: String, view: TextView, click: () -> Unit) = view.apply {
        this.text = text
        textSize = 16f
        setPadding(dp(8), dp(4), dp(14), dp(4))
        setOnClickListener { click() }
    }

    private fun buildSettings(): LinearLayout {
        val store = app.agent.store
        val catalog = catalog()
        val settings = store.settings()
        val root = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, dp(4), 0, dp(12))
        }
        root.addView(hint("密钥按 pi-ai 的 auth.json 存，默认模型交给 pi。"))
        val providers = catalog.map { it.id }.ifEmpty { listOf("deepseek") }
        val pSpin = Spinner(app)
        pSpin.adapter = ArrayAdapter(app, android.R.layout.simple_spinner_dropdown_item, providers)
        pSpin.setSelection(providers.indexOf(settings.provider).coerceAtLeast(0))
        val mSpin = Spinner(app)
        fun fillModels(providerId: String, selected: String) {
            val models = catalog.firstOrNull { it.id == providerId }?.models ?: listOf(selected)
            mSpin.adapter = ArrayAdapter(app, android.R.layout.simple_spinner_dropdown_item, models)
            val i = models.indexOf(selected)
            if (i >= 0) mSpin.setSelection(i)
        }
        fillModels(settings.provider, settings.model)
        pSpin.onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: View?, position: Int, id: Long) {
                fillModels(providers[position], store.settings().model)
            }
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
        }
        providerSpin = pSpin
        modelSpin = mSpin
        root.addView(settingLabel("默认后端"))
        root.addView(pSpin)
        root.addView(settingLabel("默认模型"))
        root.addView(mSpin)
        root.addView(settingLabel("各家 API key"))
        keyFields.clear()
        for (p in catalog) {
            root.addView(settingLabel(p.name + "  ·  " + p.id))
            val field = EditText(app).apply {
                hint = "sk-…"
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                setText(store.key(p.id))
                setTextColor(INK)
                setHintTextColor(MUTED)
            }
            keyFields[p.id] = field
            root.addView(field)
        }
        val custom = settings.custom
        root.addView(settingLabel("自定义端点"))
        customName = field("显示名", custom?.name ?: "自定义")
        customUrl = field("https://…/v1", custom?.baseUrl ?: "")
        customModel = field("模型 id", custom?.model ?: "")
        customKey = EditText(app).apply {
            hint = "这家的 key"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(store.key(custom?.id ?: "custom"))
            setTextColor(INK)
            setHintTextColor(MUTED)
        }
        root.addView(customName)
        root.addView(customUrl)
        root.addView(customModel)
        root.addView(customKey)
        val save = TextView(app).apply {
            text = "保存并重载"
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            background = round(ACCENT, 8)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setOnClickListener { saveSettings() }
        }
        root.addView(save, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(12)
        })
        return root
    }

    private fun saveSettings() {
        val store = app.agent.store
        val provider = providerSpin?.selectedItem?.toString() ?: "deepseek"
        val model = modelSpin?.selectedItem?.toString() ?: "deepseek-flash"
        for ((id, field) in keyFields) store.writeKey(id, field.text.toString().trim())
        val url = customUrl?.text?.toString()?.trim().orEmpty()
        val mid = customModel?.text?.toString()?.trim().orEmpty()
        val next = if (url.isNotEmpty() && mid.isNotEmpty()) {
            AgentStore.Custom(name = customName?.text?.toString()?.ifBlank { "自定义" } ?: "自定义", baseUrl = url, model = mid)
        } else null
        store.writeKey(next?.id ?: "custom", customKey?.text?.toString()?.trim().orEmpty())
        store.writeSettings(AgentStore.Settings(provider, model, next))
        app.agent.reload()
        status.text = "已保存，正在重载 pi"
        showTab(true)
    }

    private fun field(hint: String, value: String) = EditText(app).apply {
        this.hint = hint
        setText(value)
        setTextColor(INK)
        setHintTextColor(MUTED)
    }

    private fun settingLabel(text: String) = TextView(app).apply {
        this.text = text
        textSize = 12f
        setTextColor(MUTED)
        setPadding(0, dp(8), 0, dp(2))
    }

    private fun hint(text: String) = TextView(app).apply {
        this.text = text
        textSize = 12f
        setTextColor(MUTED)
    }

    private data class Prov(val id: String, val name: String, val models: List<String>)

    private fun catalog(): List<Prov> {
        val raw = app.agent.info.ifBlank {
            java.io.File(app.filesDir, "agent/catalog.json").takeIf { it.isFile }?.readText().orEmpty()
        }
        val obj = runCatching { JSONObject(raw) }.getOrNull() ?: return listOf(Prov("deepseek", "DeepSeek", listOf("deepseek-flash")))
        val arr = obj.optJSONArray("catalog") ?: JSONArray()
        val out = ArrayList<Prov>()
        for (i in 0 until arr.length()) {
            val p = arr.optJSONObject(i) ?: continue
            val models = ArrayList<String>()
            val ms = p.optJSONArray("models") ?: JSONArray()
            for (j in 0 until ms.length()) models += ms.optJSONObject(j)?.optString("id").orEmpty()
            out += Prov(p.optString("id"), p.optString("name"), models.filter { it.isNotBlank() })
        }
        return out.ifEmpty { listOf(Prov("deepseek", "DeepSeek", listOf("deepseek-flash"))) }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun ballTouch() = View.OnTouchListener { v, e ->
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                v.tag = floatArrayOf(e.rawX, e.rawY, ballX.toFloat(), ballY.toFloat(), 0f)
            }
            MotionEvent.ACTION_MOVE -> {
                val t = v.tag as FloatArray
                val dx = e.rawX - t[0]
                val dy = e.rawY - t[1]
                if (dx * dx + dy * dy > 36) t[4] = 1f
                ballX = (t[2] + dx).toInt()
                ballY = (t[3] + dy).toInt()
                updateBall()
            }
            MotionEvent.ACTION_UP -> {
                val dragged = (v.tag as? FloatArray)?.get(4) == 1f
                if (!dragged) expand()
            }
        }
        true
    }

    private fun addBall() {
        val dm = app.resources.displayMetrics
        ballX = dm.widthPixels - dp(72)
        ballY = dm.heightPixels - dp(160)
        wm.addView(ball, ballParams())
    }

    private fun expand() {
        if (open) return
        runCatching { wm.removeView(ball) }
        wm.addView(panel, panelParams())
        open = true
        asrWarm()
    }

    private fun collapse() {
        if (!open) return
        hideKeyboard()
        runCatching { wm.removeView(panel) }
        wm.addView(ball, ballParams())
        open = false
    }

    /** Keep the chat window above the gfx overlay after that overlay is added. */
    fun raise() {
        if (!added) return
        try {
            if (open) {
                wm.removeView(panel)
                wm.addView(panel, panelParams())
            } else if (ball.parent != null) {
                wm.removeView(ball)
                wm.addView(ball, ballParams())
            }
        } catch (_: Throwable) {
        }
    }

    private fun submit() {
        val text = input.text.toString().trim()
        if (text.isEmpty()) return
        input.setText("")
        hideKeyboard()
        addBubble(text, mine = true)
        status.text = "在想…"
        app.agent.prompt(text)
    }

    private fun startTalk() {
        val asr = app.asr
        if (!asr.ready) {
            status.text = "语音模型还在加载，稍等"
            asr.warm { error -> status.text = error ?: "语音模型好了，再按住说" }
            return
        }
        val started = asr.start(
            owner = AsrOwner.Chat,
            onPartial = { input.setText(it) },
            onFinal = { text ->
                listening = false
                talk.text = "说"
                if (AsrText.filler(text)) {
                    input.setText("")
                    status.text = "没听清，再说一次"
                } else {
                    input.setText(text)
                    submit()
                }
            },
            onError = {
                listening = false
                talk.text = "说"
                status.text = it
            },
        )
        if (started) {
            listening = true
            talk.text = "松开"
            status.text = "在听…松开发送"
        }
    }

    private fun stopTalk() {
        if (!listening) return
        app.asr.stop(AsrOwner.Chat)
        status.text = "识别中…"
    }

    private fun asrWarm() {
        app.asr.warm { error -> if (error != null) status.text = error }
    }

    private fun onEvent(event: AgentEvent) {
        Log.i("OCA-CHAT", "${event.type} ${event.payload.take(160)}")
        when (event.type) {
            "ready" -> {
                status.text = readyLabel(event.payload)
                refreshSettings()
            }
            "error" -> {
                status.text = jsonText(event.payload) ?: "出错了"
                addBubble(status.text.toString(), mine = false)
                streaming = null
            }
            "message_start" -> {
                if (role(event.payload) == "assistant") {
                    streamText = ""
                    streaming = addBubble("", mine = false)
                }
            }
            "message_update" -> {
                if (role(event.payload) != "assistant") return
                val delta = delta(event.payload)
                if (delta != null) {
                    streamText += delta
                    (streaming ?: addBubble("", mine = false).also { streaming = it }).text = streamText
                    scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
                }
            }
            "message_end" -> {
                if (role(event.payload) != "assistant") return
                val text = assistantText(event.payload)
                val err = jsonError(event.payload)
                val shown = text ?: err
                if (!shown.isNullOrBlank()) {
                    streamText = shown
                    (streaming ?: addBubble("", mine = false).also { streaming = it }).text = shown
                    if (err != null) status.text = err
                }
                streaming = null
            }
            "tool_execution_start" -> status.text = "在用工具 ${jsonName(event.payload)}"
            "tool_execution_end" -> status.text = "工具好了"
            "agent_end" -> status.text = " "
            else -> {}
        }
    }

    private fun addBubble(text: String, mine: Boolean): TextView {
        val view = TextView(app).apply {
            this.text = text
            textSize = 15f
            setTextColor(if (mine) Color.WHITE else INK)
            setTextIsSelectable(true)
            background = round(if (mine) ACCENT else 0xFFF0F0F0.toInt(), 10)
            setPadding(dp(10), dp(8), dp(10), dp(8))
        }
        messages.addView(
            view,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                gravity = if (mine) Gravity.END else Gravity.START
                topMargin = dp(8)
                if (mine) leftMargin = dp(36) else rightMargin = dp(36)
            },
        )
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
        return view
    }

    private fun chip(text: String, click: () -> Unit) = TextView(app).apply {
        this.text = text
        textSize = 13f
        setTextColor(ACCENT)
        setPadding(dp(10), dp(4), dp(10), dp(4))
        setOnClickListener { click() }
    }

    private fun ballParams() = WindowManager.LayoutParams(
        dp(56), dp(56),
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
            WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.TOP or Gravity.START
        x = ballX
        y = ballY
        if (Build.VERSION.SDK_INT >= 28) layoutInDisplayCutoutMode =
            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
    }

    private fun panelParams() = WindowManager.LayoutParams(
        app.resources.displayMetrics.widthPixels - dp(24),
        (app.resources.displayMetrics.heightPixels * 0.62).toInt(),
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
            WindowManager.LayoutParams.FLAG_HARDWARE_ACCELERATED,
        PixelFormat.TRANSLUCENT,
    ).apply {
        gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
        y = dp(16)
        softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
    }

    private fun updateBall() {
        if (open) return
        val p = ballParams()
        runCatching { wm.updateViewLayout(ball, p) }
    }

    private fun hideKeyboard() {
        app.getSystemService(InputMethodManager::class.java)
            ?.hideSoftInputFromWindow(input.windowToken, 0)
    }

    private fun round(color: Int, radiusDp: Int) = GradientDrawable().apply {
        setColor(color)
        cornerRadius = dp(radiusDp).toFloat()
    }

    private fun dp(v: Int) = (v * density).toInt()

    companion object {
        private const val ACCENT = 0xFFE85D04.toInt()
        private const val INK = 0xFF191919.toInt()
        private const val MUTED = 0xFF8C8C8C.toInt()

        private fun jsonText(payload: String) =
            runCatching { JSONObject(payload).optString("text").ifBlank { null } }.getOrNull()

        private fun jsonError(payload: String) =
            runCatching { JSONObject(payload).optString("error").ifBlank { null } }.getOrNull()

        private fun jsonName(payload: String) =
            runCatching { JSONObject(payload).optString("toolName") }.getOrDefault("")

        private fun role(payload: String): String? {
            val obj = runCatching { JSONObject(payload) }.getOrNull() ?: return null
            return obj.optString("role").ifBlank {
                obj.optJSONObject("message")?.optString("role").orEmpty()
            }.ifBlank { null }
        }

        private fun delta(payload: String): String? {
            val obj = runCatching { JSONObject(payload) }.getOrNull() ?: return null
            obj.optString("delta").ifBlank { null }?.let { return it }
            val ev = obj.optJSONObject("assistantMessageEvent") ?: return null
            return ev.optString("delta").ifBlank { ev.optString("text") }.ifBlank { null }
        }

        private fun assistantText(payload: String): String? {
            val obj = runCatching { JSONObject(payload) }.getOrNull() ?: return null
            obj.optString("text").ifBlank { null }?.let { return it }
            val message = obj.optJSONObject("message") ?: return null
            val content = message.optJSONArray("content") ?: return message.optString("content").ifBlank { null }
            val out = StringBuilder()
            for (i in 0 until content.length()) {
                val block = content.optJSONObject(i) ?: continue
                if (block.optString("type") == "text") out.append(block.optString("text"))
            }
            return out.toString().ifBlank { null }
        }

        private fun readyLabel(payload: String): String {
            val obj = runCatching { JSONObject(payload) }.getOrNull() ?: return "agent 已就绪"
            val name = obj.optString("name")
            val model = obj.optString("model")
            return if (name.isNotBlank()) "pi · $name" else "pi · $model"
        }
    }
}
