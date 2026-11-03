package app.onlyclaws.android

import android.app.ActivityManager
import android.app.AlarmManager
import android.app.PendingIntent
import android.app.WallpaperManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.Process

/**
 * Sticky service + overlay + live wallpaper keep this process alive by design.
 * [exit] tears those down and refuses [OcRestart] until the user opens the app again.
 */
object OcLifecycle {
    private const val PREFS = "oca_lifecycle"
    private const val KEY_STAY_DOWN = "stay_down"

    fun stayDown(context: Context): Boolean =
        prefs(context).getBoolean(KEY_STAY_DOWN, false)

    fun clearStayDown(context: Context) {
        prefs(context).edit().putBoolean(KEY_STAY_DOWN, false).apply()
    }

    fun cancelRestart(context: Context) {
        val alarm = context.getSystemService(AlarmManager::class.java) ?: return
        alarm.cancel(restartPending(context))
    }

    /**
     * Drop the float ball, stop foreground services, clear our live wallpaper if
     * set, then kill the process. Opening the launcher icon clears [stayDown].
     */
    fun exit(app: OcApp) {
        prefs(app).edit().putBoolean(KEY_STAY_DOWN, true).commit()
        cancelRestart(app)
        val main = Handler(Looper.getMainLooper())
        main.post {
            runCatching { app.chat.detach() }
            runCatching { app.overlay.detachPage() }
            runCatching { ScreenGrab.release() }
            runCatching { app.stopService(Intent(app, ScreenGrabService::class.java)) }
            clearOurWallpaper(app)
            runCatching { app.stopService(Intent(app, OcService::class.java)) }
            runCatching {
                val am = app.getSystemService(ActivityManager::class.java)
                am?.appTasks?.forEach { it.finishAndRemoveTask() }
            }
            main.postDelayed({
                Process.killProcess(Process.myPid())
            }, 500)
        }
    }

    private fun clearOurWallpaper(context: Context) {
        val manager = WallpaperManager.getInstance(context)
        val ours = ComponentName(context, OcWallpaperService::class.java)
        if (manager.wallpaperInfo?.component != ours) return
        runCatching {
            if (android.os.Build.VERSION.SDK_INT >= 28) {
                manager.clearWallpaper()
            } else {
                @Suppress("DEPRECATION")
                manager.clear()
            }
        }
    }

    private fun restartPending(context: Context): PendingIntent =
        PendingIntent.getBroadcast(
            context,
            OC_RESTART_REQUEST,
            Intent(context, OcRestart::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )

    private fun prefs(context: Context) =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
