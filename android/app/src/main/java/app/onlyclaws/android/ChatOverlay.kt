package app.onlyclaws.android

import android.annotation.SuppressLint
import android.animation.Animator
import android.animation.AnimatorListenerAdapter
import android.animation.ValueAnimator
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.Outline
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.text.InputType
import android.view.ContextThemeWrapper
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewOutlineProvider
import android.view.WindowManager
import android.view.animation.OvershootInterpolator
import android.content.Intent
import android.graphics.BitmapFactory
import android.widget.ImageView
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputMethodManager
import android.util.Log
import android.widget.ArrayAdapter
import android.widget.CheckBox
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
    private val ball = ImageView(app)
    private val panel = LinearLayout(app)
    private val messages = LinearLayout(app)
    private val scroll = ScrollView(app)
    private val chatPane = LinearLayout(app)
    private val settingsPane = ScrollView(app)
    private val tabChat = TextView(app)
    private val tabSettings = TextView(app)
    private val input = EditText(app)
    private val status = TextView(app)
    private val picture = TextView(app)
    private val preview = ImageView(app)
    private val talk = TextView(app)
    private val send = TextView(app)
    private var pendingJpeg: ByteArray? = null
    private var concealed = false
    private var picking = false
    private val keyFields = LinkedHashMap<String, EditText>()
    private var providerSpin: Spinner? = null
    private var modelSpin: Spinner? = null
    private var customName: EditText? = null
    private var customUrl: EditText? = null
    private var customModel: EditText? = null
    private var customKey: EditText? = null
    private var wallFpsSpin: Spinner? = null
    private var wallPowerSave: CheckBox? = null
    private var onChat = true
    private var added = false
    private var open = false
    private var streaming: TextView? = null
    private var streamText = ""
    private var listening = false
    private var ballX = 0
    private var ballY = 0
    private var ballSize = 0
    /** Stuck to left (−1) or right (+1) edge; 0 = free in the middle. */
    private var dockSide = 0
    private var anim: ValueAnimator? = null
    private var animToken = 0
    private val idle = Runnable { stickToEdge(fromIdle = true) }

    fun attach() {
        if (!Settings.canDrawOverlays(app)) {
            app.append("聊天在悬浮窗里。先允许「在其他应用上层显示」。")
            return
        }
        if (added) return
        build()
        added = true
        addBall()
        app.agent.watch(::onEvent)
        if (app.agent.ready && app.agent.info.isNotBlank()) {
            status.text = readyLabel(app.agent.info)
        }
    }

    fun detach() {
        if (!added) return
        app.agent.unwatch(::onEvent)
        main.removeCallbacks(idle)
        stopAnim()
        runCatching { wm.removeView(if (open) panel else ball) }
        added = false
        open = false
        dockSide = 0
    }

    private fun build() {
        ball.setImageResource(R.drawable.ic_launcher_foreground)
        ball.scaleType = ImageView.ScaleType.CENTER_CROP
        ball.clipToOutline = true
        ball.outlineProvider = object : ViewOutlineProvider() {
            override fun getOutline(view: View, outline: Outline) {
                outline.setOval(0, 0, view.width, view.height)
            }
        }
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
        preview.visibility = View.GONE
        preview.adjustViewBounds = true
        preview.scaleType = ImageView.ScaleType.CENTER_CROP
        preview.setOnClickListener { clearPending() }
        row.addView(preview, LinearLayout.LayoutParams(dp(40), dp(40)).apply { marginEnd = dp(6) })
        picture.text = "图"
        picture.setTextColor(INK)
        picture.gravity = Gravity.CENTER
        picture.setPadding(dp(10), dp(8), dp(10), dp(8))
        picture.setOnClickListener { pickImage() }
        row.addView(picture)
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
        root.addView(settingLabel("壁纸功耗"))
        root.addView(hint("跟 Wallpaper Engine 一样：限帧，系统省电时暂停。"))
        val fpsLabels = WallpaperPower.FPS_CHOICES.map { WallpaperPower.fpsLabel(it) }
        val fpsSpin = Spinner(app).apply {
            adapter = ArrayAdapter(app, android.R.layout.simple_spinner_dropdown_item, fpsLabels)
            val cur = WallpaperPower.fps(app)
            val i = WallpaperPower.FPS_CHOICES.indexOf(cur).let { if (it >= 0) it else 1 }
            setSelection(i)
        }
        wallFpsSpin = fpsSpin
        root.addView(settingLabel("动画帧率"))
        root.addView(fpsSpin)
        val powerBox = CheckBox(app).apply {
            text = "系统省电模式时暂停壁纸"
            isChecked = WallpaperPower.pauseOnPowerSave(app)
            setTextColor(INK)
        }
        wallPowerSave = powerBox
        root.addView(powerBox)
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
        root.addView(settingLabel("退出"))
        root.addView(hint("关掉悬浮球和前台服务，并取消 OnlyClaws 动态壁纸。再从桌面图标打开即可重新启动。"))
        val quit = TextView(app).apply {
            text = "退出 OnlyClaws"
            setTextColor(Color.WHITE)
            gravity = Gravity.CENTER
            background = round(0xffc45c26.toInt(), 8)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            setOnClickListener { confirmExit() }
        }
        root.addView(quit, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(8)
            bottomMargin = dp(8)
        })
        return root
    }

    private fun confirmExit() {
        val themed = ContextThemeWrapper(app, R.style.Theme_Oca)
        AlertDialog.Builder(themed)
            .setTitle("退出 OnlyClaws")
            .setMessage("会关掉悬浮球、前台服务，并取消当前动态壁纸。进程不再自动拉起。")
            .setNegativeButton("取消", null)
            .setPositiveButton("退出") { _, _ -> OcLifecycle.exit(app) }
            .show()
            .window?.setType(
                if (Build.VERSION.SDK_INT >= 26) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_SYSTEM_ALERT,
            )
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
        val fpsIndex = wallFpsSpin?.selectedItemPosition ?: 1
        WallpaperPower.setFps(app, WallpaperPower.FPS_CHOICES.getOrElse(fpsIndex) { 30 })
        WallpaperPower.setPauseOnPowerSave(app, wallPowerSave?.isChecked != false)
        app.wallpaper.applyPowerPrefs()
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
                stopAnim()
                main.removeCallbacks(idle)
                ball.scaleX = 1f
                ball.scaleY = 1f
                v.tag = floatArrayOf(e.rawX, e.rawY, ballX.toFloat(), ballY.toFloat(), 0f, dockSide.toFloat())
                if (dockSide != 0) {
                    // Pull off the sticky edge a little so the drag feels unstuck.
                    dockSide = 0
                }
            }
            MotionEvent.ACTION_MOVE -> {
                val t = v.tag as FloatArray
                val dx = e.rawX - t[0]
                val dy = e.rawY - t[1]
                if (dx * dx + dy * dy > 36) t[4] = 1f
                ballSize = dp(FULL)
                ballX = (t[2] + dx).toInt()
                ballY = (t[3] + dy).toInt()
                clampBall()
                // Near an edge while dragging: nudge toward it for a sticky feel.
                val magnet = magneticPullX(ballX)
                if (magnet != ballX) {
                    ballX = (ballX * 0.65f + magnet * 0.35f).toInt()
                }
                updateBall()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val dragged = (v.tag as? FloatArray)?.get(4) == 1f
                if (!dragged) expand()
                else stickToEdge(fromIdle = false)
            }
        }
        true
    }

    private fun addBall() {
        val dm = app.resources.displayMetrics
        ballSize = dp(FULL)
        ballX = dm.widthPixels - dp(72)
        ballY = dm.heightPixels - dp(160)
        dockSide = 0
        wm.addView(ball, ballParams())
        stickToEdge(fromIdle = false)
    }

    private fun expand() {
        if (open) return
        main.removeCallbacks(idle)
        stopAnim()
        dockSide = 0
        ballSize = dp(FULL)
        ball.scaleX = 1f
        ball.scaleY = 1f
        runCatching { wm.removeView(ball) }
        wm.addView(panel, panelParams())
        open = true
        asrWarm()
    }

    /** Types [text] into the input one character at a time, like a person would. */
    fun draft(text: String) {
        if (!added) return
        expand()
        showTab(true)
        main.removeCallbacks(typing)
        typed = 0
        typingText = text
        input.setText("")
        main.post(typing)
    }

    private var typingText = ""
    private var typed = 0
    private val typing = object : Runnable {
        override fun run() {
            if (typed >= typingText.length) return
            typed++
            input.setText(typingText.substring(0, typed))
            input.setSelection(typed)
            main.postDelayed(this, 90L + (Math.random() * 70).toLong())
        }
    }

    private fun collapse() {
        if (!open) return
        hideKeyboard()
        ballSize = dp(FULL)
        dockSide = 0
        ball.scaleX = 1f
        ball.scaleY = 1f
        runCatching { wm.removeView(panel) }
        wm.addView(ball, ballParams())
        open = false
        stickToEdge(fromIdle = false)
    }

    private fun bumpIdle() {
        main.removeCallbacks(idle)
        if (!added || open || dockSide != 0) return
        main.postDelayed(idle, IDLE_MS)
    }

    /** Snap the full-size ball to the nearer side with a springy overshoot. */
    private fun stickToEdge(fromIdle: Boolean) {
        if (!added || open || ball.parent == null) return
        ballSize = dp(FULL)
        clampBall()
        val dm = app.resources.displayMetrics
        val margin = dp(EDGE)
        val leftX = margin
        val rightX = dm.widthPixels - ballSize - margin
        val toRight = ballX + ballSize / 2f >= dm.widthPixels / 2f
        val targetX = if (toRight) rightX else leftX
        val targetY = ballY
        val side = if (toRight) 1 else -1
        if (fromIdle && dockSide == side && kotlin.math.abs(ballX - targetX) < dp(2)) {
            dockSide = side
            return
        }
        animateStick(ballX, ballY, targetX, targetY, side)
    }

    private fun magneticPullX(x: Int): Int {
        val dm = app.resources.displayMetrics
        val margin = dp(EDGE)
        val size = dp(FULL)
        val leftX = margin
        val rightX = dm.widthPixels - size - margin
        val zone = dp(MAGNET)
        return when {
            kotlin.math.abs(x - leftX) < zone -> leftX
            kotlin.math.abs(x - rightX) < zone -> rightX
            else -> x
        }
    }

    private fun clampBall() {
        val dm = app.resources.displayMetrics
        val size = ballSize.coerceAtLeast(1)
        ballX = ballX.coerceIn(-size / 2, dm.widthPixels - size / 2)
        ballY = ballY.coerceIn(dp(8), dm.heightPixels - size - dp(8))
    }

    private fun animateStick(fromX: Int, fromY: Int, toX: Int, toY: Int, side: Int) {
        stopAnim()
        val token = ++animToken
        val animator = ValueAnimator.ofFloat(0f, 1f)
        anim = animator
        animator.duration = 420
        animator.interpolator = OvershootInterpolator(1.35f)
        animator.addUpdateListener {
            val t = it.animatedValue as Float
            ballX = (fromX + (toX - fromX) * t).toInt()
            ballY = (fromY + (toY - fromY) * t).toInt()
            ballSize = dp(FULL)
            val pulse = 1f + 0.07f * overshootBump(t)
            ball.scaleX = pulse
            ball.scaleY = pulse
            updateBall()
        }
        animator.addListener(object : AnimatorListenerAdapter() {
            override fun onAnimationEnd(animation: Animator) {
                if (token != animToken) return
                ballX = toX
                ballY = toY
                ballSize = dp(FULL)
                ball.scaleX = 1f
                ball.scaleY = 1f
                dockSide = side
                updateBall()
            }
        })
        animator.start()
    }

    /** 0 at start/end, peaks near the overshoot. */
    private fun overshootBump(t: Float): Float {
        val x = (t - 0.72f).coerceIn(0f, 1f)
        return if (x <= 0f) 0f else (1f - x) * 4f * x
    }

    private fun stopAnim() {
        animToken++
        anim?.cancel()
        anim = null
    }

    /** Hide the ball or panel so a screen capture does not photograph the chat itself. */
    fun conceal(): Boolean {
        if (!added || concealed) return false
        (if (open) panel else ball).visibility = View.INVISIBLE
        concealed = true
        return true
    }

    fun reveal() {
        if (!concealed) return
        concealed = false
        (if (open) panel else ball).visibility = View.VISIBLE
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

    private fun pickImage() {
        ChatImages.onPicked = pick@{ bytes ->
            showAfterPick()
            if (bytes == null || bytes.isEmpty()) return@pick
            pendingJpeg = bytes
            preview.setImageBitmap(BitmapFactory.decodeByteArray(bytes, 0, bytes.size))
            preview.visibility = View.VISIBLE
        }
        hideForPick()
        runCatching {
            app.startActivity(
                Intent(app, ImagePickActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }.onFailure {
            ChatImages.onPicked = null
            showAfterPick()
        }
    }

    /** Take the overlay off the screen so the system picker can be used. */
    private fun hideForPick() {
        if (!added || picking) return
        picking = true
        hideKeyboard()
        main.removeCallbacks(idle)
        stopAnim()
        runCatching { wm.removeView(if (open) panel else ball) }
    }

    private fun showAfterPick() {
        if (!picking) return
        picking = false
        if (!added) return
        concealed = false
        if (open) {
            panel.visibility = View.VISIBLE
            if (panel.parent == null) runCatching { wm.addView(panel, panelParams()) }
        } else {
            ball.visibility = View.VISIBLE
            if (ball.parent == null) runCatching { wm.addView(ball, ballParams()) }
            bumpIdle()
        }
    }

    private fun clearPending() {
        pendingJpeg = null
        preview.setImageDrawable(null)
        preview.visibility = View.GONE
    }

    private fun submit() {
        val text = input.text.toString().trim()
        val jpeg = pendingJpeg
        if (text.isEmpty() && jpeg == null) return
        val say = text.ifBlank { "看这张图" }
        input.setText("")
        clearPending()
        hideKeyboard()
        addMine(say, jpeg)
        status.text = "在想…"
        app.agent.prompt(say, jpeg)
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
                    (streaming ?: addBubble("", mine = false).also { streaming = it }).text =
                        ChatChoices.displayWhileStreaming(streamText)
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
                    val bubble = streaming ?: addBubble("", mine = false).also { streaming = it }
                    finishAssistant(bubble, shown)
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

    private fun addMine(text: String, jpeg: ByteArray?) {
        if (jpeg == null) {
            addBubble(text, mine = true)
            return
        }
        val box = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.END
        }
        val bitmap = BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)
        if (bitmap != null) {
            val image = ImageView(app).apply {
                setImageBitmap(bitmap)
                adjustViewBounds = true
            }
            box.addView(
                image,
                LinearLayout.LayoutParams(dp(160), LinearLayout.LayoutParams.WRAP_CONTENT),
            )
        }
        if (text.isNotBlank()) {
            box.addView(
                TextView(app).apply {
                    this.text = text
                    textSize = 15f
                    setTextColor(Color.WHITE)
                    background = round(ACCENT, 10)
                    setPadding(dp(10), dp(8), dp(10), dp(8))
                },
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ).apply { topMargin = dp(4) },
            )
        }
        messages.addView(
            box,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.END
                topMargin = dp(8)
                leftMargin = dp(36)
            },
        )
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun finishAssistant(bubble: TextView, raw: String) {
        val parsed = ChatChoices.parse(raw)
        bubble.text = parsed.text.ifBlank { raw.trim() }
        val index = messages.indexOfChild(bubble)
        if (index >= 0) {
            // Drop a previous choice row attached to this bubble, if any.
            val next = messages.getChildAt(index + 1)
            if (next?.tag == CHOICE_ROW) messages.removeViewAt(index + 1)
        }
        if (parsed.choices.isEmpty()) {
            scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
            return
        }
        val row = LinearLayout(app).apply {
            orientation = LinearLayout.VERTICAL
            tag = CHOICE_ROW
        }
        for (choice in parsed.choices) {
            val chip = TextView(app).apply {
                text = choice
                textSize = 14f
                setTextColor(ACCENT)
                background = GradientDrawable().apply {
                    setColor(0xFFFFF4EC.toInt())
                    setStroke(dp(1), ACCENT)
                    cornerRadius = dp(10).toFloat()
                }
                setPadding(dp(12), dp(10), dp(12), dp(10))
                setOnClickListener {
                    if (tag == DISABLED) return@setOnClickListener
                    disableChoiceRows()
                    pickChoice(choice)
                }
            }
            row.addView(
                chip,
                LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT,
                    LinearLayout.LayoutParams.WRAP_CONTENT,
                ).apply { topMargin = dp(6) },
            )
        }
        val at = if (index >= 0) index + 1 else messages.childCount
        messages.addView(
            row,
            at,
            LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = Gravity.START
                rightMargin = dp(36)
                bottomMargin = dp(4)
            },
        )
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
    }

    private fun pickChoice(choice: String) {
        hideKeyboard()
        addMine(choice, null)
        status.text = "在想…"
        app.agent.prompt(choice, null)
    }

    private fun disableChoiceRows() {
        for (i in 0 until messages.childCount) {
            val row = messages.getChildAt(i) ?: continue
            if (row.tag != CHOICE_ROW || row !is LinearLayout) continue
            row.tag = DISABLED
            for (j in 0 until row.childCount) {
                val chip = row.getChildAt(j) as? TextView ?: continue
                chip.tag = DISABLED
                chip.alpha = 0.45f
                chip.isClickable = false
            }
        }
    }

    private fun addBubble(text: String, mine: Boolean): TextView {
        if (mine) disableChoiceRows()
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
        ballSize.coerceAtLeast(1), ballSize.coerceAtLeast(1),
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
        private const val FULL = 56
        private const val EDGE = 6
        private const val MAGNET = 36
        private const val IDLE_MS = 15_000L
        private const val ACCENT = 0xFFE85D04.toInt()
        private const val INK = 0xFF191919.toInt()
        private const val MUTED = 0xFF8C8C8C.toInt()
        private const val CHOICE_ROW = "oca-choice-row"
        private const val DISABLED = "oca-choice-disabled"

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
