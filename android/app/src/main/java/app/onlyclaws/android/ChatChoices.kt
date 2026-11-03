package app.onlyclaws.android

/**
 * LLM choice cards for the chat overlay.
 *
 * Preferred form (taught in the agent system prompt):
 *
 *     <<<choices
 *     换代码雨
 *     换下雪
 *     >>>
 *
 * The block is stripped from the bubble text; each non-empty line becomes a chip.
 */
object ChatChoices {
    private val BLOCK = Regex(
        """<<<\s*(?:choices|选项)\s*\r?\n([\s\S]*?)>>>""",
        RegexOption.IGNORE_CASE,
    )

    data class Parsed(val text: String, val choices: List<String>)

    fun parse(raw: String): Parsed {
        val choices = mutableListOf<String>()
        val text = BLOCK.replace(raw) { match ->
            match.groupValues[1].lineSequence()
                .map { it.trim().trimStart('·', '-', '*', '•').trim() }
                .filter { it.isNotEmpty() }
                .forEach { line ->
                    val cleaned = line.replace(Regex("""^\d+[.)、]\s*"""), "")
                        .replace(Regex("""^[A-Za-z][.)、]\s*"""), "")
                        .trim()
                    if (cleaned.isNotEmpty()) choices += cleaned
                }
            ""
        }.trim()
        return Parsed(text = text, choices = choices.distinct().take(8))
    }

    /** While streaming, hide a half-written choices fence from the bubble. */
    fun displayWhileStreaming(raw: String): String {
        val parsed = parse(raw)
        if (parsed.choices.isNotEmpty()) return parsed.text
        val cut = raw.indexOf("<<<")
        return if (cut >= 0) raw.substring(0, cut).trimEnd() else raw
    }
}
