package app.onlyclaws.android

import android.opengl.GLES20
import android.util.Log
import android.view.Surface
import javax.microedition.khronos.egl.EGL10
import javax.microedition.khronos.egl.EGLConfig
import javax.microedition.khronos.egl.EGLContext
import javax.microedition.khronos.egl.EGLDisplay
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * Wallpaper-owned 3D clip. The script only selects the scene;
 * this thread keeps the clock and draws the crash.
 */
class CrashScene(private val surface: Surface) : Thread("oca-wallpaper-gl") {
    @Volatile
    var visible = true

    @Volatile
    private var running = true

    fun shutdown() {
        running = false
        interrupt()
        try {
            join(1500)
        } catch (_: InterruptedException) {
        }
    }

    override fun run() {
        val egl = EGLContext.getEGL() as EGL10
        val display = egl.eglGetDisplay(EGL10.EGL_DEFAULT_DISPLAY)
        egl.eglInitialize(display, IntArray(2))
        val config = choose(egl, display) ?: return
        val context = egl.eglCreateContext(display, config, EGL10.EGL_NO_CONTEXT, intArrayOf(0x3098, 2, EGL10.EGL_NONE))
        val window = egl.eglCreateWindowSurface(display, config, surface, null)
        if (window == null || window == EGL10.EGL_NO_SURFACE) return
        egl.eglMakeCurrent(display, window, window, context)
        val gl = SceneGl()
        val width = IntArray(1)
        val height = IntArray(1)
        val started = System.nanoTime()
        try {
            while (running) {
                if (!visible) {
                    sleep(40)
                    continue
                }
                egl.eglQuerySurface(display, window, EGL10.EGL_WIDTH, width)
                egl.eglQuerySurface(display, window, EGL10.EGL_HEIGHT, height)
                if (width[0] <= 0 || height[0] <= 0) {
                    sleep(30)
                    continue
                }
                val t = ((System.nanoTime() - started) / 1_000_000_000.0) % LOOP
                gl.draw(t.toFloat(), width[0], height[0])
                egl.eglSwapBuffers(display, window)
                sleep(12)
            }
        } catch (_: InterruptedException) {
        } finally {
            egl.eglMakeCurrent(display, EGL10.EGL_NO_SURFACE, EGL10.EGL_NO_SURFACE, EGL10.EGL_NO_CONTEXT)
            egl.eglDestroySurface(display, window)
            egl.eglDestroyContext(display, context)
            egl.eglTerminate(display)
        }
    }

    private fun choose(egl: EGL10, display: EGLDisplay): EGLConfig? {
        val want = intArrayOf(
            EGL10.EGL_RENDERABLE_TYPE, 4,
            EGL10.EGL_RED_SIZE, 8,
            EGL10.EGL_GREEN_SIZE, 8,
            EGL10.EGL_BLUE_SIZE, 8,
            EGL10.EGL_DEPTH_SIZE, 16,
            EGL10.EGL_NONE,
        )
        val count = IntArray(1)
        egl.eglChooseConfig(display, want, null, 0, count)
        if (count[0] <= 0) return null
        val configs = arrayOfNulls<EGLConfig>(count[0])
        egl.eglChooseConfig(display, want, configs, count[0], count)
        return configs[0]
    }

    private companion object {
        const val LOOP = 6.4
    }
}

private class SceneGl {
    private val program: Int
    private val pos: Int
    private val nrm: Int
    private val mvp: Int
    private val model: Int
    private val color: Int
    private val cube: Int
    private val bricks = Array(COLS * ROWS) { i ->
        val col = i % COLS
        val row = i / COLS
        Brick(
            (col - (COLS - 1) / 2f) * 0.50f,
            0.28f + row * 0.30f,
        )
    }
    private var launched = false
    private var lastTime = 0f

    init {
        val vs = compile(GLES20.GL_VERTEX_SHADER, VERT)
        val fs = compile(GLES20.GL_FRAGMENT_SHADER, FRAG)
        program = GLES20.glCreateProgram()
        GLES20.glAttachShader(program, vs)
        GLES20.glAttachShader(program, fs)
        GLES20.glLinkProgram(program)
        pos = GLES20.glGetAttribLocation(program, "aPos")
        nrm = GLES20.glGetAttribLocation(program, "aNrm")
        mvp = GLES20.glGetUniformLocation(program, "uMvp")
        model = GLES20.glGetUniformLocation(program, "uModel")
        color = GLES20.glGetUniformLocation(program, "uColor")
        cube = cubeBuffer()
        GLES20.glEnable(GLES20.GL_DEPTH_TEST)
        GLES20.glEnable(GLES20.GL_CULL_FACE)
    }

    fun draw(time: Float, width: Int, height: Int) {
        if (time < 0.05f) {
            launched = false
            bricks.forEach { it.reset() }
        }
        val impact = time >= 2.15f
        if (impact && !launched) {
            launched = true
            bricks.forEach { it.kick() }
        }
        val dt = if (time + 0.2f < lastTime) 0.016f else (time - lastTime).coerceIn(0f, 0.05f)
        lastTime = time
        if (impact) bricks.forEach { it.step(dt) }

        GLES20.glViewport(0, 0, width, height)
        GLES20.glClearColor(0.04f, 0.05f, 0.07f, 1f)
        GLES20.glClear(GLES20.GL_COLOR_BUFFER_BIT or GLES20.GL_DEPTH_BUFFER_BIT)
        GLES20.glUseProgram(program)
        GLES20.glBindBuffer(GLES20.GL_ARRAY_BUFFER, cube)
        GLES20.glEnableVertexAttribArray(pos)
        GLES20.glEnableVertexAttribArray(nrm)
        GLES20.glVertexAttribPointer(pos, 3, GLES20.GL_FLOAT, false, 24, 0)
        GLES20.glVertexAttribPointer(nrm, 3, GLES20.GL_FLOAT, false, 24, 12)

        val aspect = width.toFloat() / height.toFloat()
        val view = lookAt(0f, 1.35f, 5.6f, 0f, 1.15f, 0f)
        val proj = perspective(42f, aspect, 0.08f, 40f)
        val vp = mul(proj, view)

        box(vp, 0f, -0.02f, 0.4f, 8f, 0.08f, 8f, 0.10f, 0.11f, 0.12f)
        for (brick in bricks) {
            if (!brick.loose) {
                box(vp, brick.x, brick.y, 0f, 0.44f, 0.24f, 0.20f, brick.r, brick.g, brick.b)
            }
        }
        for (brick in bricks) {
            if (brick.loose) {
                val spin = brick.spin
                box(
                    vp, brick.px, brick.py, brick.pz,
                    0.44f, 0.24f, 0.20f,
                    brick.r, brick.g, brick.b,
                    spin, brick.axis,
                )
            }
        }
        beast(vp, time)
    }

    private fun beast(vp: FloatArray, time: Float) {
        val approach = (time / 2.15f).coerceIn(0f, 1f)
        val through = ((time - 2.15f) / 2.1f).coerceIn(0f, 1f)
        val z = if (time < 2.15f) lerp(-4.6f, -0.15f, approach) else lerp(-0.15f, 2.4f, through)
        val bob = if (time < 2.15f) sin(time * 14f) * 0.06f else 0f
        val swing = sin(time * 14f)
        val hide = 0.42f
        val g = 0.58f
        val b = 0.24f
        box(vp, 0f, 0.95f + bob, z, 1.15f, 0.78f, 0.82f, hide, g, b)
        box(vp, 0f, 1.55f + bob, z + 0.28f, 0.62f, 0.48f, 0.55f, hide, g, b)
        box(vp, 0f, 1.42f + bob, z + 0.62f, 0.36f, 0.22f, 0.42f, 0.33f, 0.46f, 0.18f)
        box(vp, -0.22f, 1.82f + bob, z + 0.22f, 0.10f, 0.28f, 0.10f, 0.25f, 0.32f, 0.14f)
        box(vp, 0.22f, 1.82f + bob, z + 0.22f, 0.10f, 0.28f, 0.10f, 0.25f, 0.32f, 0.14f)
        box(vp, -0.16f, 1.62f + bob, z + 0.52f, 0.10f, 0.10f, 0.08f, 0.05f, 0.05f, 0.05f)
        box(vp, 0.16f, 1.62f + bob, z + 0.52f, 0.10f, 0.10f, 0.08f, 0.05f, 0.05f, 0.05f)
        box(vp, -0.78f, 1.05f + bob + swing * 0.12f, z, 0.28f, 0.55f, 0.28f, hide, g, b)
        box(vp, 0.78f, 1.05f + bob - swing * 0.12f, z, 0.28f, 0.55f, 0.28f, hide, g, b)
        box(vp, -0.28f, 0.38f + bob * 0.2f, z - swing * 0.18f, 0.28f, 0.55f, 0.30f, hide, g, b)
        box(vp, 0.28f, 0.38f + bob * 0.2f, z + swing * 0.18f, 0.28f, 0.55f, 0.30f, hide, g, b)
    }

    private fun box(
        vp: FloatArray,
        x: Float,
        y: Float,
        z: Float,
        sx: Float,
        sy: Float,
        sz: Float,
        r: Float,
        g: Float,
        b: Float,
        spin: Float = 0f,
        axis: Int = 0,
    ) {
        val local = translateScale(x, y, z, sx, sy, sz, spin, axis)
        val mvpM = mul(vp, local)
        GLES20.glUniformMatrix4fv(model, 1, false, local, 0)
        GLES20.glUniformMatrix4fv(mvp, 1, false, mvpM, 0)
        GLES20.glUniform3f(color, r, g, b)
        GLES20.glDrawArrays(GLES20.GL_TRIANGLES, 0, 36)
    }

    private class Brick(val x: Float, val y: Float) {
        var px = x
        var py = y
        var pz = 0f
        var vx = 0f
        var vy = 0f
        var vz = 0f
        var spin = 0f
        var spinV = 0f
        var axis = 0
        var loose = false
        val r: Float
        val g: Float
        val b: Float

        init {
            val n = Random.nextFloat()
            r = 0.45f + n * 0.12f
            g = 0.24f + n * 0.06f
            b = 0.16f
        }

        fun reset() {
            px = x
            py = y
            pz = 0f
            loose = false
            spin = 0f
        }

        fun kick() {
            val dx = x
            val dy = y - 1.15f
            if (dx * dx + dy * dy > 1.7f) return
            loose = true
            vx = dx * 1.6f + (Random.nextFloat() - 0.5f)
            vy = 1.2f + Random.nextFloat() * 2.2f
            vz = 2.4f + Random.nextFloat() * 2.4f
            spinV = (Random.nextFloat() - 0.5f) * 8f
            axis = Random.nextInt(3)
        }

        fun step(dt: Float) {
            if (!loose) return
            vy -= 4.2f * dt
            px += vx * dt
            py += vy * dt
            pz += vz * dt
            spin += spinV * dt
            if (py < 0.12f) {
                py = 0.12f
                vy = -vy * 0.35f
                vx *= 0.8f
                vz *= 0.8f
            }
        }
    }

    companion object {
        private const val TAG = "CrashScene"
        private const val COLS = 8
        private const val ROWS = 9

        private const val VERT = """
            attribute vec3 aPos;
            attribute vec3 aNrm;
            uniform mat4 uMvp;
            uniform mat4 uModel;
            varying vec3 vNrm;
            void main() {
                vNrm = mat3(uModel[0].xyz, uModel[1].xyz, uModel[2].xyz) * aNrm;
                gl_Position = uMvp * vec4(aPos, 1.0);
            }
        """

        private const val FRAG = """
            precision mediump float;
            varying vec3 vNrm;
            uniform vec3 uColor;
            void main() {
                vec3 n = normalize(vNrm);
                vec3 light = normalize(vec3(0.35, 0.8, 0.45));
                float d = max(dot(n, light), 0.0);
                gl_FragColor = vec4(uColor * (0.22 + 0.78 * d), 1.0);
            }
        """

        private fun compile(type: Int, source: String): Int {
            val shader = GLES20.glCreateShader(type)
            GLES20.glShaderSource(shader, source)
            GLES20.glCompileShader(shader)
            val info = GLES20.glGetShaderInfoLog(shader)
            if (info.isNotBlank()) Log.e(TAG, info)
            return shader
        }

        private fun cubeBuffer(): Int {
            val faces = arrayOf(
                floatArrayOf(0f, 0f, 1f, -0.5f, -0.5f, 0.5f, 0.5f, -0.5f, 0.5f, 0.5f, 0.5f, 0.5f, -0.5f, 0.5f, 0.5f),
                floatArrayOf(0f, 0f, -1f, 0.5f, -0.5f, -0.5f, -0.5f, -0.5f, -0.5f, -0.5f, 0.5f, -0.5f, 0.5f, 0.5f, -0.5f),
                floatArrayOf(0f, 1f, 0f, -0.5f, 0.5f, 0.5f, 0.5f, 0.5f, 0.5f, 0.5f, 0.5f, -0.5f, -0.5f, 0.5f, -0.5f),
                floatArrayOf(0f, -1f, 0f, -0.5f, -0.5f, -0.5f, 0.5f, -0.5f, -0.5f, 0.5f, -0.5f, 0.5f, -0.5f, -0.5f, 0.5f),
                floatArrayOf(1f, 0f, 0f, 0.5f, -0.5f, 0.5f, 0.5f, -0.5f, -0.5f, 0.5f, 0.5f, -0.5f, 0.5f, 0.5f, 0.5f),
                floatArrayOf(-1f, 0f, 0f, -0.5f, -0.5f, -0.5f, -0.5f, -0.5f, 0.5f, -0.5f, 0.5f, 0.5f, -0.5f, 0.5f, -0.5f),
            )
            val data = FloatArray(36 * 6)
            var o = 0
            for (face in faces) {
                val order = intArrayOf(0, 1, 2, 0, 2, 3)
                for (tri in order) {
                    data[o++] = face[3 + tri * 3]
                    data[o++] = face[4 + tri * 3]
                    data[o++] = face[5 + tri * 3]
                    data[o++] = face[0]
                    data[o++] = face[1]
                    data[o++] = face[2]
                }
            }
            val buf = java.nio.ByteBuffer.allocateDirect(data.size * 4).order(java.nio.ByteOrder.nativeOrder()).asFloatBuffer()
            buf.put(data).position(0)
            val ids = IntArray(1)
            GLES20.glGenBuffers(1, ids, 0)
            GLES20.glBindBuffer(GLES20.GL_ARRAY_BUFFER, ids[0])
            GLES20.glBufferData(GLES20.GL_ARRAY_BUFFER, data.size * 4, buf, GLES20.GL_STATIC_DRAW)
            return ids[0]
        }
    }
}

private fun lerp(a: Float, b: Float, t: Float) = a + (b - a) * t

private fun perspective(fovyDeg: Float, aspect: Float, near: Float, far: Float): FloatArray {
    val out = FloatArray(16)
    val f = (1.0 / kotlin.math.tan(fovyDeg / 2.0 * PI / 180.0)).toFloat()
    out[0] = f / aspect
    out[5] = f
    out[10] = (far + near) / (near - far)
    out[11] = -1f
    out[14] = (2f * far * near) / (near - far)
    return out
}

private fun lookAt(ex: Float, ey: Float, ez: Float, cx: Float, cy: Float, cz: Float): FloatArray {
    var fx = cx - ex
    var fy = cy - ey
    var fz = cz - ez
    val fl = sqrt(fx * fx + fy * fy + fz * fz)
    fx /= fl
    fy /= fl
    fz /= fl
    var sx = fy * 0f - fz * 1f
    var sy = fz * 0f - fx * 0f
    var sz = fx * 1f - fy * 0f
    val sl = sqrt(sx * sx + sy * sy + sz * sz)
    sx /= sl
    sy /= sl
    sz /= sl
    val ux = sy * fz - sz * fy
    val uy = sz * fx - sx * fz
    val uz = sx * fy - sy * fx
    return floatArrayOf(
        sx, sy, sz, 0f,
        ux, uy, uz, 0f,
        -fx, -fy, -fz, 0f,
        -(sx * ex + sy * ey + sz * ez),
        -(ux * ex + uy * ey + uz * ez),
        fx * ex + fy * ey + fz * ez,
        1f,
    )
}

private fun translateScale(
    x: Float,
    y: Float,
    z: Float,
    sx: Float,
    sy: Float,
    sz: Float,
    spin: Float,
    axis: Int,
): FloatArray {
    val c = cos(spin)
    val s = sin(spin)
    val r = FloatArray(16)
    r[15] = 1f
    when (axis) {
        0 -> {
            r[0] = 1f
            r[5] = c
            r[6] = s
            r[9] = -s
            r[10] = c
        }
        1 -> {
            r[0] = c
            r[2] = -s
            r[5] = 1f
            r[8] = s
            r[10] = c
        }
        else -> {
            r[0] = c
            r[1] = s
            r[4] = -s
            r[5] = c
            r[10] = 1f
        }
    }
    val m = floatArrayOf(
        r[0] * sx, r[1] * sx, r[2] * sx, 0f,
        r[4] * sy, r[5] * sy, r[6] * sy, 0f,
        r[8] * sz, r[9] * sz, r[10] * sz, 0f,
        x, y, z, 1f,
    )
    return m
}

private fun mul(a: FloatArray, b: FloatArray): FloatArray {
    val o = FloatArray(16)
    for (c in 0..3) {
        for (r in 0..3) {
            o[c * 4 + r] =
                a[r] * b[c * 4] +
                a[4 + r] * b[c * 4 + 1] +
                a[8 + r] * b[c * 4 + 2] +
                a[12 + r] * b[c * 4 + 3]
        }
    }
    return o
}
