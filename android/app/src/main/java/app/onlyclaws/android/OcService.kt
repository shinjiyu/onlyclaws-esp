package app.onlyclaws.android

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

class OcService : Service() {
    private var wire: SessionWire? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startInForeground()
        if (wire == null) {
            val app = application as OcApp
            val session = SessionWire(
                this,
                onScript = { source, reply ->
                    app.container.load(source) { result ->
                        result.onSuccess {
                            app.container.writeActive(this, source)
                            app.append("脚本已换上")
                        }
                        result.onFailure { app.append("脚本未换上：${it.message}") }
                        reply(result.isSuccess)
                    }
                },
                onState = { app.append(it) },
            )
            wire = session
            session.start()
        }
        return START_STICKY
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        scheduleOcRestart(this)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        wire?.stop()
        wire = null
        super.onDestroy()
    }

    private fun startInForeground() {
        val manager = getSystemService(NotificationManager::class.java)
        if (manager.getNotificationChannel(CHANNEL) == null) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.channel), NotificationManager.IMPORTANCE_LOW),
            )
        }
        val note: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_oca)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.note))
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        } else {
            startForeground(1, note)
        }
    }

    companion object {
        private const val CHANNEL = "oca"
    }
}
