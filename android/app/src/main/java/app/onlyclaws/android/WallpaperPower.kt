package app.onlyclaws.android

import android.content.Context

/**
 * Wallpaper Engine–style battery knobs: FPS cap and pause while the phone
 * is in system power-save mode. Defaults match a light daily use profile.
 */
object WallpaperPower {
    private const val PREFS = "wallpaper_power"
    private const val KEY_FPS = "fps"
    private const val KEY_PAUSE_POWER_SAVE = "pause_power_save"

    /** Common caps; 0 means follow the display refresh. */
    val FPS_CHOICES = intArrayOf(15, 30, 60, 0)

    fun fps(context: Context): Int =
        prefs(context).getInt(KEY_FPS, 30).let { if (it < 0) 30 else it }

    fun setFps(context: Context, fps: Int) {
        prefs(context).edit().putInt(KEY_FPS, fps.coerceAtLeast(0)).apply()
    }

    fun pauseOnPowerSave(context: Context): Boolean =
        prefs(context).getBoolean(KEY_PAUSE_POWER_SAVE, true)

    fun setPauseOnPowerSave(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_PAUSE_POWER_SAVE, enabled).apply()
    }

    fun fpsLabel(fps: Int): String = when (fps) {
        0 -> "不限（跟屏幕）"
        else -> "${fps} fps"
    }

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
