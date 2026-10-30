package app.onlyclaws.android

import android.os.Bundle
import android.text.InputType
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject

/** Backends and keys for the bundled pi-ai. Format matches pi's auth.json / current model. */
class SettingsActivity : AppCompatActivity() {
    private lateinit var store: AgentStore
    private val keyFields = LinkedHashMap<String, EditText>()
    private var catalog: List<Provider> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val app = application as OcApp
        store = app.agent.store
        catalog = readCatalog(
            app.agent.info.ifBlank {
                java.io.File(filesDir, "agent/catalog.json").takeIf { it.isFile }?.readText().orEmpty()
            },
        ).ifEmpty {
            listOf(Provider("deepseek", "DeepSeek", listOf(Model("deepseek-flash", "DeepSeek Flash"))))
        }
        val settings = store.settings()

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(20), dp(16), dp(24))
        }
        root.addView(title("Agent 设置"))
        root.addView(hint("密钥按 pi-ai 的 auth.json 存。默认模型会交给 pi。"))

        val providers = catalog.map { it.id }.ifEmpty { listOf("deepseek") }
        val providerSpin = spinner(providers, providers.indexOf(settings.provider).coerceAtLeast(0))
        val modelSpin = Spinner(this)
        fun fillModels(providerId: String, selected: String) {
            val models = catalog.firstOrNull { it.id == providerId }?.models?.map { it.id } ?: listOf(selected)
            modelSpin.adapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, models)
            val i = models.indexOf(selected)
            if (i >= 0) modelSpin.setSelection(i)
        }
        fillModels(settings.provider, settings.model)
        providerSpin.setOnItemSelectedListener { id -> fillModels(id, store.settings().model) }

        root.addView(label("默认后端"))
        root.addView(providerSpin)
        root.addView(label("默认模型"))
        root.addView(modelSpin)

        root.addView(title("各家 API key"))
        for (p in catalog) {
            root.addView(label(p.name + "  ·  " + p.id))
            val field = EditText(this).apply {
                hint = "sk-…"
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
                setText(store.key(p.id))
            }
            keyFields[p.id] = field
            root.addView(field)
        }

        root.addView(title("自定义端点"))
        val custom = settings.custom
        val customName = field("名字", custom?.name ?: "自定义")
        val customUrl = field("https://…/v1", custom?.baseUrl ?: "")
        val customModel = field("模型 id", custom?.model ?: "")
        val customKey = EditText(this).apply {
            hint = "这家的 key"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setText(store.key(custom?.id ?: "custom"))
        }
        root.addView(label("显示名"))
        root.addView(customName)
        root.addView(label("Base URL"))
        root.addView(customUrl)
        root.addView(label("模型 id"))
        root.addView(customModel)
        root.addView(label("Key"))
        root.addView(customKey)

        val save = Button(this).apply {
            text = "保存并重载 agent"
            setOnClickListener {
                val provider = providerSpin.selectedItem?.toString() ?: "deepseek"
                val model = modelSpin.selectedItem?.toString() ?: "deepseek-flash"
                for ((id, field) in keyFields) store.writeKey(id, field.text.toString().trim())
                val url = customUrl.text.toString().trim()
                val mid = customModel.text.toString().trim()
                val nextCustom = if (url.isNotEmpty() && mid.isNotEmpty()) {
                    AgentStore.Custom(name = customName.text.toString().ifBlank { "自定义" }, baseUrl = url, model = mid)
                } else null
                store.writeKey(nextCustom?.id ?: "custom", customKey.text.toString().trim())
                store.writeSettings(AgentStore.Settings(provider = provider, model = model, custom = nextCustom))
                app.agent.reload()
                Toast.makeText(this@SettingsActivity, "已保存，正在重载 pi", Toast.LENGTH_SHORT).show()
                finish()
            }
        }
        root.addView(save)

        setContentView(ScrollView(this).apply { addView(root) })
        title = "设置"
    }

    private fun title(text: String) = TextView(this).apply {
        this.text = text
        textSize = 18f
        setPadding(0, dp(16), 0, dp(6))
        setTextColor(0xFF191919.toInt())
    }

    private fun hint(text: String) = TextView(this).apply {
        this.text = text
        textSize = 13f
        setTextColor(0xFF8C8C8C.toInt())
    }

    private fun label(text: String) = TextView(this).apply {
        this.text = text
        textSize = 13f
        setPadding(0, dp(10), 0, dp(2))
    }

    private fun field(hint: String, value: String) = EditText(this).apply {
        this.hint = hint
        setText(value)
    }

    private fun spinner(items: List<String>, selected: Int) = Spinner(this).apply {
        adapter = ArrayAdapter(this@SettingsActivity, android.R.layout.simple_spinner_dropdown_item, items)
        setSelection(selected.coerceIn(0, items.lastIndex.coerceAtLeast(0)))
    }

    private fun Spinner.setOnItemSelectedListener(body: (String) -> Unit) {
        onItemSelectedListener = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: android.view.View?, position: Int, id: Long) {
                body(adapter.getItem(position).toString())
            }
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private data class Model(val id: String, val name: String)
    private data class Provider(val id: String, val name: String, val models: List<Model>)

    private fun readCatalog(info: String): List<Provider> {
        val obj = runCatching { JSONObject(info) }.getOrNull() ?: return emptyList()
        val arr = obj.optJSONArray("catalog") ?: JSONArray()
        val out = ArrayList<Provider>()
        for (i in 0 until arr.length()) {
            val p = arr.optJSONObject(i) ?: continue
            val models = ArrayList<Model>()
            val ms = p.optJSONArray("models") ?: JSONArray()
            for (j in 0 until ms.length()) {
                val m = ms.optJSONObject(j) ?: continue
                models += Model(m.optString("id"), m.optString("name"))
            }
            out += Provider(p.optString("id"), p.optString("name"), models)
        }
        return out
    }
}
