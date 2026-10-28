package app.onlyclaws.android

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock
import androidx.core.content.ContextCompat

/**
 * Swiping recents removes the activity. The foreground service keeps the script.
 * Some phones then kill the process; this alarm starts the service again.
 * An exact alarm is what Android 12+ allows to start a foreground service from the background.
 */
fun scheduleOcRestart(context: Context) {
    val alarm = context.getSystemService(AlarmManager::class.java) ?: return
    val pending = PendingIntent.getBroadcast(
        context,
        RESTART_REQUEST,
        Intent(context, OcRestart::class.java),
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )
    val at = SystemClock.elapsedRealtime() + RESTART_DELAY_MS
    val exact = Build.VERSION.SDK_INT < 31 || alarm.canScheduleExactAlarms()
    val scheduled = if (exact) {
        runCatching {
            alarm.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pending)
        }.isSuccess
    } else {
        false
    }
    if (!scheduled) {
        alarm.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pending)
    }
}

class OcRestart : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        runCatching {
            ContextCompat.startForegroundService(context, Intent(context, OcService::class.java))
        }
    }
}

private const val RESTART_REQUEST = 0x0CA
private const val RESTART_DELAY_MS = 1_000L
