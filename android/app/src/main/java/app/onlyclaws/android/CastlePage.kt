package app.onlyclaws.android

import android.content.Context

/** Bundled Infinity Castle fall. The blocks live in assets/castle. */
internal object CastlePage {
    const val SCENE = "castle"

    @Volatile
    private var cached: String? = null

    fun source(context: Context): String {
        cached?.let { return it }
        val text = context.assets.open("castle/page.html").bufferedReader().use { it.readText() }
        cached = text
        return text
    }
}
