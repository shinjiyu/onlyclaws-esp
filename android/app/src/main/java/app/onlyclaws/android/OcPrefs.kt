package app.onlyclaws.android

import android.content.Context

/**
 * Host prefs outside any script. [remoteControl] is off by default: OCA
 * downloads resources over HTTPS and runs locally; turn it on only when
 * the phone should accept `js` invokes over the device session wire.
 */
object OcPrefs {
    private const val PREFS = "oca_host"
    private const val KEY_REMOTE = "remote_control"

    fun remoteControl(context: Context): Boolean =
        prefs(context).getBoolean(KEY_REMOTE, false)

    fun setRemoteControl(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_REMOTE, enabled).apply()
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
