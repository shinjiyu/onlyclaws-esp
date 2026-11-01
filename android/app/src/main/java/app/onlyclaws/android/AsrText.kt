package app.onlyclaws.android

/** SenseVoice / sherpa result cleanup. No Android here. */
object AsrText {
    private val TAGS = Regex("<\\|[^|]*\\|>")
    private val FILLER = Regex("[\\s\\p{P}嗯啊呃哦噢唔额哈嘿]*")

    fun clean(raw: String): String =
        raw.replace(TAGS, "").replace(Regex("\\s+"), " ").trim()

    fun filler(text: String): Boolean = text.isEmpty() || FILLER.matches(text)
}
