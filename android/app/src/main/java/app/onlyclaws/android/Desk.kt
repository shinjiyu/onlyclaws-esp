package app.onlyclaws.android

import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.platform.ViewCompositionStrategy
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.math.roundToInt
import android.os.Handler
import android.os.Looper
import org.json.JSONArray
import org.json.JSONObject
import org.mozilla.javascript.BaseFunction
import org.mozilla.javascript.Context as JsContext
import org.mozilla.javascript.NativeJSON
import org.mozilla.javascript.Scriptable
import org.mozilla.javascript.ScriptableObject
import org.mozilla.javascript.Undefined

/**
 * The screen the person actually sees. A script fills it with `desk.show({...})`.
 * The wallpaper button stays underneath.
 */
class DeskPlugin(
    private val container: JsContainer,
    private val onLog: (String) -> Unit,
) : JsPlugin {
    private val main = Handler(Looper.getMainLooper())
    private var host: ViewGroup? = null
    internal var model by mutableStateOf(opening())
        private set
    internal var logText by mutableStateOf("")
        private set
    private var logWatch: ((String) -> Unit)? = null

    fun attach(host: ViewGroup) {
        this.host = host
        main.post {
            host.removeAllViews()
            val compose = ComposeView(host.context).apply {
                setViewCompositionStrategy(ViewCompositionStrategy.DisposeOnViewTreeLifecycleDestroyed)
                setContent {
                    DeskScreen(
                        this@DeskPlugin,
                        ::toggle,
                        ::login,
                        ::begin,
                        ::finish,
                        ::saveKey,
                        ::saveGap,
                        ::pickPrompt,
                        ::savePrompt,
                    )
                }
            }
            host.addView(
                compose,
                FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                ),
            )
            host.visibility = View.VISIBLE
        }
    }

    fun watchLogs(app: OcApp) {
        val listener: (String) -> Unit = { text -> logText = text }
        logWatch = listener
        app.watch(listener)
    }

    fun unwatchLogs(app: OcApp) {
        logWatch?.let { app.unwatch(it) }
        logWatch = null
    }

    fun detach() {
        host?.removeAllViews()
        host = null
    }

    override fun install(cx: JsContext, scope: Scriptable) {
        val api = Api()
        api.parentScope = scope
        ScriptableObject.putProperty(scope, "desk", api)
    }

    private fun show(cx: JsContext, scope: Scriptable, arg: Any?) {
        val text = when (arg) {
            null, is Undefined -> return
            is String -> arg
            else -> runCatching {
                NativeJSON.stringify(cx, scope, arg, null, null) as? String
            }.getOrNull()
        }
        if (text.isNullOrBlank()) {
            onLog("界面内容无效")
            return
        }
        val next = runCatching { readModel(text) }.getOrNull()
        if (next == null) {
            onLog("界面内容无效")
            return
        }
        main.post {
            model = next
            host?.visibility = View.VISIBLE
        }
    }

    private fun toggle(id: String) = fire(id, "toggle")

    private fun login() = fire("login", "login")

    private fun begin() = fire("start", "start")

    private fun finish() = fire("stop", "stop")

    private fun saveKey(value: String) = fire("key", "save", value)

    private fun saveGap(seconds: Int) = fire("gap", "gap", seconds.toString())

    private fun pickPrompt(id: String) = fire(id, "prompt")

    private fun savePrompt(value: String) = fire("promptText", "prompt", value)

    private fun fire(id: String, action: String, value: String = "") {
        container.enter { cx, scope ->
            val fn = scope.get("onAction", scope)
            if (fn !is BaseFunction) return@enter
            val event = cx.newObject(scope)
            ScriptableObject.putProperty(event, "id", id)
            ScriptableObject.putProperty(event, "action", action)
            if (value.isNotEmpty()) ScriptableObject.putProperty(event, "value", value)
            fn.call(cx, scope, scope, arrayOf(event))
        }
    }

    private inner class Api : ScriptableObject() {
        override fun getClassName(): String = "desk"

        override fun get(name: String, start: Scriptable?): Any = when (name) {
            "show" -> showFn
            else -> NOT_FOUND
        }

        private val showFn = object : BaseFunction() {
            override fun call(cx: JsContext, scope: Scriptable, thisObj: Scriptable, args: Array<out Any>?): Any {
                show(cx, scope, args?.firstOrNull())
                return Undefined.instance
            }
        }
    }
}

private fun opening() = DeskModel(
    title = "逛 B 站",
    status = "正在装上",
    login = "",
    running = false,
    keyReady = false,
    error = "",
    checking = false,
    open = "",
    tokens = 0,
    tokenCap = 20000,
        gap = 60,
        gapMin = 30,
        gapMax = 600,
        gapStep = 30,
        prompts = builtinPrompts,
        prompt = "curious",
        custom = "",
        rows = emptyList(),
        stats = emptyList(),
        events = emptyList(),
    )

private fun readModel(text: String): DeskModel {
    val obj = JSONObject(text)
    val gapMin = obj.optInt("gapMin", 30).coerceAtLeast(1)
    val gapMax = obj.optInt("gapMax", 600).coerceAtLeast(gapMin)
    val gapStep = obj.optInt("gapStep", 30).coerceAtLeast(1)
    val gap = obj.optInt("gap", 60).coerceIn(gapMin, gapMax)
    val prompts = readPrompts(obj.optJSONArray("prompts")).ifEmpty { builtinPrompts }
    return DeskModel(
        title = obj.optString("title", "逛 B 站").ifBlank { "逛 B 站" },
        status = obj.optString("status"),
        login = obj.optString("login"),
        running = obj.optBoolean("running"),
        keyReady = obj.optBoolean("keyReady"),
        error = obj.optString("error"),
        checking = obj.optBoolean("checking"),
        open = obj.optString("open"),
        tokens = obj.optInt("tokens"),
        tokenCap = obj.optInt("tokenCap", 20000).coerceAtLeast(1),
        gap = gap,
        gapMin = gapMin,
        gapMax = gapMax,
        gapStep = gapStep,
        prompts = prompts,
        prompt = obj.optString("prompt", "curious").ifBlank { "curious" },
        custom = obj.optString("custom"),
        rows = readRows(obj.optJSONArray("rows")),
        stats = readStats(obj.optJSONArray("stats")),
        events = readEvents(obj.optJSONArray("events")),
    )
}

private fun readPrompts(array: JSONArray?): List<DeskPrompt> {
    if (array == null) return emptyList()
    return buildList {
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id")
            val text = item.optString("text")
            if (id.isBlank() || text.isBlank() || id == "custom") continue
            add(DeskPrompt(id, text))
        }
    }
}

private fun readRows(array: JSONArray?): List<DeskRow> {
    if (array == null) return emptyList()
    return buildList {
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val id = item.optString("id")
            if (id.isBlank()) continue
            add(
                DeskRow(
                    id = id,
                    name = item.optString("name", id),
                    group = item.optString("group"),
                    on = item.optBoolean("on"),
                    used = item.optInt("used"),
                    cap = item.optInt("cap"),
                ),
            )
        }
    }
}

private fun readStats(array: JSONArray?): List<DeskStat> {
    if (array == null) return emptyList()
    return buildList {
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val name = item.optString("name")
            if (name.isBlank()) continue
            add(DeskStat(name, item.optString("value", "0")))
        }
    }
}

private fun readEvents(array: JSONArray?): List<DeskEvent> {
    if (array == null) return emptyList()
    return buildList {
        for (i in 0 until array.length()) {
            val item = array.optJSONObject(i) ?: continue
            val text = item.optString("text")
            if (text.isBlank()) continue
            add(DeskEvent(item.optString("time"), text))
        }
    }
}

internal data class DeskModel(
    val title: String,
    val status: String,
    val login: String,
    val running: Boolean,
    val keyReady: Boolean,
    val error: String,
    val checking: Boolean,
    val open: String,
    val tokens: Int,
    val tokenCap: Int,
    val gap: Int,
    val gapMin: Int,
    val gapMax: Int,
    val gapStep: Int,
    val prompts: List<DeskPrompt>,
    val prompt: String,
    val custom: String,
    val rows: List<DeskRow>,
    val stats: List<DeskStat>,
    val events: List<DeskEvent>,
)

internal data class DeskPrompt(val id: String, val text: String)

private val builtinPrompts = listOf(
    DeskPrompt("curious", "你天生好奇"),
    DeskPrompt("stay", "你喜欢看完再走"),
    DeskPrompt("skim", "你只是随便看看"),
)

internal data class DeskRow(
    val id: String,
    val name: String,
    val group: String,
    val on: Boolean,
    val used: Int,
    val cap: Int,
)

internal data class DeskStat(val name: String, val value: String)

internal data class DeskEvent(val time: String, val text: String)

private val Paper = Color(0xFFF3EEE6)
private val Ink = Color(0xFF1C1B19)
private val Muted = Color(0xFF6F6A62)
private val Accent = Color(0xFFE85D04)
private val Card = Color(0xFFFFFCF8)
private val Track = Color(0xFFE4DDD2)
private val Line = Color(0xFFD9D1C5)

@Composable
private fun DeskScreen(
    plugin: DeskPlugin,
    onToggle: (String) -> Unit,
    onLogin: () -> Unit,
    onBegin: () -> Unit,
    onFinish: () -> Unit,
    onSave: (String) -> Unit,
    onGap: (Int) -> Unit,
    onPrompt: (String) -> Unit,
    onPromptText: (String) -> Unit,
) {
    val model = plugin.model
    var screen by remember { mutableIntStateOf(0) }
    LaunchedEffect(model.open) {
        when (model.open) {
            "运行" -> screen = 0
            "配置" -> screen = 1
            "日志" -> screen = 2
        }
    }
    val pages = listOf("运行", "配置", "日志")
    MaterialTheme(colorScheme = lightColorScheme(primary = Accent)) {
        Column(
            Modifier
                .fillMaxSize()
                .background(Paper)
                .padding(horizontal = 20.dp),
        ) {
            Spacer(Modifier.height(24.dp))
            Text(model.title, color = Ink, fontSize = 28.sp, fontWeight = FontWeight.Medium)
            if (model.status.isNotBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(model.status, color = Muted, fontSize = 14.sp)
            }
            Spacer(Modifier.height(14.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                pages.forEachIndexed { index, name ->
                    val selected = screen == index
                    Button(
                        onClick = { screen = index },
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (selected) Ink else Card,
                            contentColor = if (selected) Color.White else Ink,
                        ),
                    ) { Text(name) }
                }
            }
            if (model.error.isNotBlank()) {
                Spacer(Modifier.height(12.dp))
                Text(
                    model.error,
                    color = Color(0xFF8A2E12),
                    fontSize = 15.sp,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(Color(0xFFF8E4D8))
                        .padding(12.dp),
                )
            }
            Spacer(Modifier.height(8.dp))
            key(screen) {
                Column(
                    Modifier
                        .weight(1f)
                        .verticalScroll(rememberScrollState())
                        .padding(bottom = 24.dp),
                ) {
                    when (screen) {
                        0 -> RunPage(model, onBegin, onFinish, onLogin)
                        1 -> ConfigPage(model, onToggle, onSave, onGap, onPrompt, onPromptText)
                        else -> LogPage(plugin, model)
                    }
                }
            }
        }
    }
}

@Composable
private fun RunPage(
    model: DeskModel,
    onBegin: () -> Unit,
    onFinish: () -> Unit,
    onLogin: () -> Unit,
) {
    Spacer(Modifier.height(8.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Button(
            onClick = onBegin,
            enabled = !model.checking,
            modifier = Modifier.weight(1f),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (model.running) Card else Accent,
                contentColor = if (model.running) Ink else Color.White,
            ),
        ) { Text(if (model.checking) "正在检查" else "开始") }
        Button(
            onClick = onFinish,
            modifier = Modifier.weight(1f),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (model.running) Accent else Card,
                contentColor = if (model.running) Color.White else Ink,
            ),
        ) { Text("结束") }
    }
    if (model.login.isNotBlank()) {
        Spacer(Modifier.height(12.dp))
        Button(
            onClick = onLogin,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Accent, contentColor = Color.White),
        ) { Text(model.login) }
    }
    Spacer(Modifier.height(18.dp))
    Text("每隔 ${gapWords(model.gap)}", color = Ink, fontSize = 16.sp)
    Text(
        activePrompt(model),
        color = Muted,
        fontSize = 14.sp,
        maxLines = 2,
        overflow = TextOverflow.Ellipsis,
    )
    Spacer(Modifier.height(22.dp))
    Text("累计", color = Muted, fontSize = 13.sp)
    Spacer(Modifier.height(4.dp))
    Text("${model.tokens}", color = Ink, fontSize = 36.sp, fontWeight = FontWeight.Medium)
    Text("用掉的 token", color = Muted, fontSize = 13.sp)
    if (model.stats.isNotEmpty()) {
        Spacer(Modifier.height(18.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            model.stats.forEach { stat ->
                Column(
                    Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(Card)
                        .padding(horizontal = 12.dp, vertical = 12.dp),
                ) {
                    Text(stat.value, color = Ink, fontSize = 20.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(2.dp))
                    Text(stat.name, color = Muted, fontSize = 12.sp)
                }
            }
        }
    }
}

@Composable
private fun ConfigPage(
    model: DeskModel,
    onToggle: (String) -> Unit,
    onSave: (String) -> Unit,
    onGap: (Int) -> Unit,
    onPrompt: (String) -> Unit,
    onPromptText: (String) -> Unit,
) {
    var draft by remember { mutableStateOf("") }
    Spacer(Modifier.height(8.dp))
    Text(if (model.keyReady) "API Key 已保存" else "API Key", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    Spacer(Modifier.height(8.dp))
    OutlinedTextField(
        value = draft,
        onValueChange = { draft = it },
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        placeholder = { Text("DeepSeek API Key", color = Muted) },
        shape = RoundedCornerShape(12.dp),
    )
    Spacer(Modifier.height(8.dp))
    Button(
        onClick = {
            val typed = draft.trim()
            draft = ""
            if (typed.isNotEmpty()) onSave(typed)
        },
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(containerColor = Ink, contentColor = Color.White),
    ) { Text("保存") }
    Text(
        if (model.keyReady) "再填一次会换掉现在这份" else "还没保存",
        color = Muted,
        fontSize = 12.sp,
        modifier = Modifier.padding(top = 6.dp),
    )
    Spacer(Modifier.height(22.dp))
    Text("外层间隔", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    Spacer(Modifier.height(4.dp))
    Text("上一轮做完，再等这么久，才问下一次模型", color = Muted, fontSize = 13.sp)
    GapSlider(model, onGap)
    Spacer(Modifier.height(22.dp))
    Text("提示词", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    Spacer(Modifier.height(8.dp))
    model.prompts.forEach { item ->
        PromptButton(item.text, model.prompt == item.id) { onPrompt(item.id) }
        Spacer(Modifier.height(8.dp))
    }
    PromptButton("自定义", model.prompt == "custom") { onPrompt("custom") }
    if (model.prompt == "custom") {
        var customDraft by remember(model.custom) { mutableStateOf(model.custom) }
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = customDraft,
            onValueChange = { customDraft = it.take(400) },
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
            maxLines = 4,
            placeholder = { Text("写一句给模型的提示", color = Muted) },
            shape = RoundedCornerShape(12.dp),
        )
        Spacer(Modifier.height(8.dp))
        Button(
            onClick = {
                val typed = customDraft.trim()
                if (typed.isNotEmpty()) onPromptText(typed)
            },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Ink, contentColor = Color.White),
        ) { Text("保存提示词") }
        Text(
            if (model.custom.isBlank()) "还没写的时候，用「你天生好奇」" else "最多 400 字",
            color = Muted,
            fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp),
        )
    }
    var lastGroup = ""
    model.rows.forEach { row ->
        if (row.group.isNotBlank() && row.group != lastGroup) {
            lastGroup = row.group
            Spacer(Modifier.height(22.dp))
            Text(row.group, color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(6.dp))
        }
        Row(
            Modifier
                .fillMaxWidth()
                .padding(vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(row.name, color = Ink, fontSize = 16.sp)
                Text("${row.used}/${row.cap} 这一小时", color = Muted, fontSize = 12.sp)
            }
            Switch(
                checked = row.on,
                onCheckedChange = { onToggle(row.id) },
                colors = SwitchDefaults.colors(
                    checkedTrackColor = Accent,
                    checkedThumbColor = Color.White,
                    uncheckedTrackColor = Track,
                    uncheckedThumbColor = Color.White,
                    uncheckedBorderColor = Line,
                ),
            )
        }
    }
}

@Composable
private fun GapSlider(model: DeskModel, onGap: (Int) -> Unit) {
    val min = model.gapMin.toFloat()
    val max = model.gapMax.toFloat().coerceAtLeast(min)
    val step = model.gapStep.coerceAtLeast(1)
    var sliding by remember { mutableStateOf(false) }
    var slide by remember { mutableFloatStateOf(model.gap.toFloat()) }
    val shown = (if (sliding) slide else model.gap.toFloat()).coerceIn(min, max)
    val steps = (((max - min) / step).toInt() - 1).coerceAtLeast(0)
    Text(gapWords(shown.toInt()), color = Ink, fontSize = 28.sp, fontWeight = FontWeight.Medium)
    Slider(
        value = shown,
        onValueChange = { raw ->
            sliding = true
            val snapped = (raw / step).roundToInt() * step
            slide = snapped.toFloat().coerceIn(min, max)
        },
        onValueChangeFinished = {
            val chosen = slide.roundToInt().coerceIn(model.gapMin, model.gapMax)
            sliding = false
            if (chosen != model.gap) onGap(chosen)
        },
        valueRange = min..max,
        steps = steps,
        colors = SliderDefaults.colors(
            thumbColor = Accent,
            activeTrackColor = Accent,
            inactiveTrackColor = Track,
        ),
    )
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(gapWords(model.gapMin), color = Muted, fontSize = 12.sp)
        Text(gapWords(model.gapMax), color = Muted, fontSize = 12.sp)
    }
}

@Composable
private fun PromptButton(label: String, selected: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = ButtonDefaults.buttonColors(
            containerColor = if (selected) Ink else Card,
            contentColor = if (selected) Color.White else Ink,
        ),
    ) { Text(label) }
}

private fun gapWords(seconds: Int): String {
    if (seconds < 60) return "$seconds 秒"
    val minutes = seconds / 60
    val rest = seconds % 60
    if (rest == 0) return "$minutes 分钟"
    return "$minutes 分 $rest 秒"
}

private fun activePrompt(model: DeskModel): String {
    if (model.prompt == "custom" && model.custom.isNotBlank()) return model.custom.trim()
    return model.prompts.firstOrNull { it.id == model.prompt }?.text ?: "你天生好奇"
}

@Composable
private fun LogPage(plugin: DeskPlugin, model: DeskModel) {
    val lines = plugin.logText.lineSequence().map { it.trimEnd() }.filter { it.isNotEmpty() }.toList()
    Spacer(Modifier.height(8.dp))
    Text("日志", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    Spacer(Modifier.height(8.dp))
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Card)
            .padding(12.dp),
    ) {
        if (lines.isEmpty()) {
            Text("还没有日志", color = Muted, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
        } else {
            lines.takeLast(40).forEach { line ->
                Text(line, color = Ink, fontSize = 12.sp, fontFamily = FontFamily.Monospace, modifier = Modifier.padding(bottom = 4.dp))
            }
        }
    }
    Spacer(Modifier.height(22.dp))
    Text("记录", color = Ink, fontSize = 15.sp, fontWeight = FontWeight.Medium)
    Spacer(Modifier.height(10.dp))
    if (model.events.isEmpty()) {
        Text("还没有动作", color = Muted, fontSize = 14.sp)
    } else {
        model.events.forEach { event ->
            Row(Modifier.padding(bottom = 12.dp)) {
                Box(
                    Modifier
                        .padding(top = 6.dp)
                        .width(8.dp)
                        .height(8.dp)
                        .clip(CircleShape)
                        .background(Accent),
                )
                Spacer(Modifier.width(10.dp))
                Column {
                    if (event.time.isNotBlank()) {
                        Text(event.time, color = Muted, fontSize = 12.sp)
                    }
                    Text(event.text, color = Ink, fontSize = 15.sp)
                }
            }
        }
    }
}
