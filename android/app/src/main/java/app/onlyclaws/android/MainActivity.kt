package app.onlyclaws.android

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat

class MainActivity : AppCompatActivity() {
    private val show: (String) -> Unit = { text ->
        findViewById<TextView>(R.id.log).text = text.ifEmpty { "启动中" }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        val app = application as OcApp
        app.a2ui.attach(
            findViewById(R.id.a2ui_host),
            findViewById(R.id.log_pane),
            findViewById(R.id.wallpaper),
        )
        findViewById<Button>(R.id.permit).setOnClickListener {
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:$packageName"),
                ),
            )
        }
        findViewById<Button>(R.id.wallpaper).setOnClickListener {
            startActivity(
                Intent(android.app.WallpaperManager.ACTION_CHANGE_LIVE_WALLPAPER).putExtra(
                    android.app.WallpaperManager.EXTRA_LIVE_WALLPAPER_COMPONENT,
                    android.content.ComponentName(this, OcWallpaperService::class.java),
                ),
            )
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        ViewCompat.setOnApplyWindowInsetsListener(window.decorView) { _, insets ->
            val density = resources.displayMetrics.density.toDouble()
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            app.overlay.metrics.top = bars.top / density
            app.overlay.metrics.right = bars.right / density
            app.overlay.metrics.bottom = bars.bottom / density
            app.overlay.metrics.left = bars.left / density
            app.overlay.metrics.keyboard = ime.bottom / density
            insets
        }
        ContextCompat.startForegroundService(this, Intent(this, OcService::class.java))
        maybeReload(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        maybeReload(intent)
    }

    private fun maybeReload(intent: Intent?) {
        if (intent?.action == ACTION_RELOAD || intent?.getBooleanExtra(EXTRA_RELOAD, false) == true) {
            (application as OcApp).reloadScript()
        }
    }

    override fun onStart() {
        super.onStart()
        (application as OcApp).watch(show)
        refreshPermit()
    }

    override fun onResume() {
        super.onResume()
        refreshPermit()
        if (Settings.canDrawOverlays(this)) {
            (application as OcApp).overlay.resumeIfNeeded()
        }
    }

    override fun onDestroy() {
        (application as OcApp).a2ui.detach()
        super.onDestroy()
    }

    override fun onStop() {
        (application as OcApp).unwatch(show)
        super.onStop()
    }

    private fun refreshPermit() {
        findViewById<Button>(R.id.permit).visibility =
            if (Settings.canDrawOverlays(this)) View.GONE else View.VISIBLE
    }

    companion object {
        const val ACTION_RELOAD = "app.onlyclaws.android.RELOAD"
        const val EXTRA_RELOAD = "reload"
    }
}
