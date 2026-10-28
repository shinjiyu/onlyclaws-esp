package app.onlyclaws.android

import android.content.Context
import java.io.File
import java.io.IOException

/**
 * A package built by the console carries assets/session.json for one phone.
 * It replaces files/session.json only when it differs from the copy applied last
 * time (files/session.seed): a newly installed package takes over, and a
 * session.json placed by hand stays while the package is unchanged.
 */
object SessionSeed {
    private const val ASSET = "session.json"
    private const val SEED = "session.seed"

    fun fromAssets(context: Context): Boolean {
        val packaged = try {
            context.assets.open(ASSET).use { it.readBytes() }
        } catch (_: IOException) {
            null
        }
        return apply(packaged, context.filesDir)
    }

    fun apply(packaged: ByteArray?, dir: File): Boolean {
        if (packaged == null || packaged.isEmpty()) return false
        val seed = File(dir, SEED)
        if (seed.isFile && seed.readBytes().contentEquals(packaged)) return false
        dir.mkdirs()
        val tmp = File(dir, "$ASSET.tmp")
        tmp.writeBytes(packaged)
        if (!tmp.renameTo(File(dir, ASSET))) {
            tmp.delete()
            return false
        }
        seed.writeBytes(packaged)
        return true
    }
}
