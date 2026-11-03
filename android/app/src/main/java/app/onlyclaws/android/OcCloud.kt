package app.onlyclaws.android

/**
 * Public HTTPS surface on onlyclaws.world. OCA pulls presets and other
 * resources from here without holding a device session open.
 */
object OcCloud {
    const val HTTP_BASE = "https://onlyclaws.world/epaper"
    const val WS_BASE = "wss://onlyclaws.world/epaper"

    fun presetsListUrl(kind: String = "oca"): String =
        "$HTTP_BASE/api/presets?kind=${kind.trim()}"

    fun presetSourceUrl(id: String): String =
        "$HTTP_BASE/api/presets/${id.trim()}/source?inline=1"

    fun deviceSessionUrl(deviceId: String): String =
        "$WS_BASE/api/v1/device/${deviceId.trim().lowercase()}/session"
}
