package app.onlyclaws.android

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CompletableFuture
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

class JsContainerTest {
    private val logs = LinkedBlockingQueue<String>()
    private val errors = LinkedBlockingQueue<String>()
    private val container = JsContainer({ logs += it }, stuckMs = 300).apply {
        onError = { errors += it }
        use(TestPlugin())
    }

    @After
    fun drain() {
        logs.clear()
        errors.clear()
    }

    @Test
    fun onStartRunsAndLogs() {
        load("function onStart() { oca.log('hi'); }").getOrThrow()
        expectLog("hi")
    }

    @Test
    fun hostFunctionsGettersAndValues() {
        load(
            """
            function onStart() {
              const o = t.obj();
              oca.log(`${'$'}{t.add(2, 3)} ${'$'}{t.n} ${'$'}{t.label} ${'$'}{o.k} ${'$'}{o.list[1]} ${'$'}{t.json({ a: [1] })} ${'$'}{t.json('raw')}`);
            }
            """,
        ).getOrThrow()
        expectLog("5 7 tee v 2 {\"a\":[1]} raw")
    }

    @Test
    fun fireConvertsMapsAndJson() {
        load("function onStart() {}\nfunction onAction(e) { oca.log(e.id + ':' + (e.context ? e.context.v[1] : e.n)); }")
            .getOrThrow()
        container.fire("onAction", JsJson("{\"id\":\"x\",\"context\":{\"v\":[1,2]}}"))
        expectLog("x:2")
        container.fire("onAction", mapOf("id" to "y", "n" to 2.5))
        expectLog("y:2.5")
    }

    @Test
    fun fireWithoutHookIsSkipped() {
        load("function onStart() { oca.log('up'); }").getOrThrow()
        expectLog("up")
        container.fire("onDone")
        container.fire("onAction", mapOf("id" to "z"))
        load("function onStart() { oca.log('still'); }").getOrThrow()
        expectLog("still")
        assertTrue(errors.isEmpty())
    }

    @Test
    fun failedLoadKeepsThePreviousScript() {
        load("function onStart() {}\nfunction onAction() { oca.log('A'); }").getOrThrow()
        val bad = load("function onStart() { throw new Error('nope'); }")
        assertTrue(bad.isFailure)
        assertTrue(bad.exceptionOrNull()!!.message!!, bad.exceptionOrNull()!!.message!!.contains("nope"))
        container.fire("onAction")
        expectLog("A")
    }

    @Test
    fun previousScriptGetsOnStop() {
        load("function onStart() {}\nfunction onStop() { oca.log('bye'); }").getOrThrow()
        load("function onStart() {}").getOrThrow()
        expectLog("bye")
    }

    @Test
    fun syntaxErrorCarriesTheLine() {
        val bad = load("function onStart() {\n  var a = ;\n}")
        val message = bad.exceptionOrNull()?.message.orEmpty()
        assertTrue(message, message.contains("第 2 行"))
    }

    @Test
    fun runawayOnStartIsTerminatedAndTheContainerRecovers() {
        val bad = load("function onStart() { while (true) {} }")
        val message = bad.exceptionOrNull()?.message.orEmpty()
        assertTrue(message, message.contains("打断"))
        load("function onStart() { oca.log('after'); }").getOrThrow()
        expectLog("after")
    }

    @Test
    fun runawayHookIsTerminatedAndTheScriptStaysUsable() {
        load("function onStart() {}\nfunction onAction(e) { if (e.spin) { for (;;) {} } oca.log('alive'); }")
            .getOrThrow()
        container.fire("onAction", mapOf("spin" to true))
        val error = errors.poll(3, TimeUnit.SECONDS).orEmpty()
        assertTrue("no termination reported: $error", error.contains("打断"))
        container.fire("onAction", mapOf("spin" to false))
        expectLog("alive")
    }

    @Test
    fun blockingHostCallIsNotTerminated() {
        load("function onStart() { t.sleep(700); oca.log('woke'); }").getOrThrow()
        expectLog("woke")
    }

    @Test
    fun microtasksRunBeforeTheTurnEnds() {
        load(
            """
            async function later() { await null; oca.log('async'); }
            function onStart() { Promise.resolve().then(() => oca.log('micro')); later(); }
            """,
        ).getOrThrow()
        expectLog("micro")
        expectLog("async")
    }

    @Test
    fun hostErrorsAreCatchableInScript() {
        load("function onStart() { try { t.boom(); } catch (e) { oca.log('caught ' + e.message); } }").getOrThrow()
        val line = logs.poll(3, TimeUnit.SECONDS).orEmpty()
        assertTrue(line, line.startsWith("caught") && line.contains("bad"))
    }

    @Test
    fun scriptsSeeNoJava() {
        load("function onStart() { oca.log([typeof java, typeof Packages, typeof require].join(',')); }").getOrThrow()
        expectLog("undefined,undefined,undefined")
    }

    private fun load(source: String): Result<Unit> {
        val done = CompletableFuture<Result<Unit>>()
        container.load(source.trimIndent()) { done.complete(it) }
        return done.get(5, TimeUnit.SECONDS)
    }

    private fun expectLog(expected: String) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3)
        val seen = mutableListOf<String>()
        while (System.nanoTime() < deadline) {
            val line = logs.poll(50, TimeUnit.MILLISECONDS) ?: continue
            if (line == expected) return
            seen += line
        }
        assertEquals(expected, seen.joinToString("\n"))
    }

    private class TestPlugin : JsPlugin {
        override fun install(scope: JsScope) = scope.define("t") {
            fn("add") { it.number(0) + it.number(1) }
            getter("n") { 7 }
            value("label", "tee")
            fn("obj") { mapOf("k" to "v", "list" to listOf(1, 2)) }
            fn("json") { it.json(0) }
            fn("sleep") { Thread.sleep(it.number(0).toLong()) }
            fn("boom") { throw IllegalStateException("bad") }
        }
    }
}
