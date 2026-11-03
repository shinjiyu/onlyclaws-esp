package app.onlyclaws.android

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import java.io.ByteArrayOutputStream
import kotlin.math.max

/** One picked picture, already a small JPEG, handed back to the chat overlay. */
object ChatImages {
    var onPicked: ((ByteArray?) -> Unit)? = null

    fun offer(bytes: ByteArray?) {
        val listener = onPicked
        onPicked = null
        Handler(Looper.getMainLooper()).post { listener?.invoke(bytes) }
    }
}

class ImagePickActivity : Activity() {
    private var delivered = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState != null) {
            finish()
            return
        }
        val pick = Intent(Intent.ACTION_GET_CONTENT).apply {
            type = "image/*"
            addCategory(Intent.CATEGORY_OPENABLE)
        }
        @Suppress("DEPRECATION")
        startActivityForResult(Intent.createChooser(pick, "选一张图"), REQUEST)
    }

    @Deprecated("The system picker still arrives here")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        val uri = data?.data
        val bytes = if (requestCode == REQUEST && resultCode == RESULT_OK && uri != null) {
            ImageBytes.jpeg(this, uri)
        } else {
            null
        }
        deliver(bytes)
        finish()
    }

    override fun onDestroy() {
        deliver(null)
        super.onDestroy()
    }

    private fun deliver(bytes: ByteArray?) {
        if (delivered) return
        delivered = true
        ChatImages.offer(bytes)
    }

    companion object {
        private const val REQUEST = 1
    }
}

object ImageBytes {
    /** Longest side at most 1280, JPEG, so a chat message stays under the request cap. */
    fun jpeg(context: android.content.Context, uri: Uri): ByteArray? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, bounds)
        }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        val edge = max(bounds.outWidth, bounds.outHeight)
        while (edge / sample > 1280) sample *= 2
        val opts = BitmapFactory.Options().apply { inSampleSize = sample }
        val bitmap = context.contentResolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, opts)
        } ?: return null
        return try {
            val out = ByteArrayOutputStream()
            if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 80, out)) null else out.toByteArray()
        } finally {
            bitmap.recycle()
        }
    }
}
