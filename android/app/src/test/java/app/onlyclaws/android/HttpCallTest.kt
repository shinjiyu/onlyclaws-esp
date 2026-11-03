package app.onlyclaws.android

import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class HttpCallTest {
    private lateinit var server: MockWebServer
    private lateinit var client: OkHttpClient

    @Before
    fun setUp() {
        val held = HeldCertificate.Builder()
            .commonName("localhost")
            .addSubjectAlternativeName("localhost")
            .build()
        val serverCerts = HandshakeCertificates.Builder().heldCertificate(held).build()
        val clientCerts = HandshakeCertificates.Builder().addTrustedCertificate(held.certificate).build()
        server = MockWebServer()
        server.useHttps(serverCerts.sslSocketFactory(), false)
        server.start()
        client = OkHttpClient.Builder()
            .sslSocketFactory(clientCerts.sslSocketFactory(), clientCerts.trustManager)
            .hostnameVerifier { _, _ -> true }
            .onlyHttps()
            .build()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun postReturnsStatusBodyAndLowerCaseHeaders() {
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .addHeader("Retry-After", "3")
                .setBody("{\"ok\":true}"),
        )
        val outcome = HttpCall(client).perform(
            HttpSpec(
                url = server.url("/v1").toString(),
                method = "post",
                headers = mapOf("Content-Type" to "application/json"),
                body = "{\"a\":1}",
                timeoutMs = 5_000,
            ),
        )
        assertEquals(200, outcome.status)
        assertEquals("", outcome.error)
        assertEquals("{\"ok\":true}", outcome.body)
        assertEquals("3", outcome.headers["retry-after"])
        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("{\"a\":1}", recorded.body.readUtf8())
    }

    @Test
    fun httpUrlIsRejected() {
        val outcome = HttpCall(OkHttpClient()).perform(HttpSpec(url = "http://example.com/"))
        assertEquals(0, outcome.status)
        assertEquals("只接受 https", outcome.error)
    }

    @Test
    fun redirectToHttpIsRejected() {
        server.enqueue(MockResponse().setResponseCode(302).addHeader("Location", "http://example.com/x"))
        val outcome = HttpCall(client).perform(HttpSpec(url = server.url("/go").toString(), timeoutMs = 5_000))
        assertEquals(0, outcome.status)
        assertEquals("只接受 https", outcome.error)
    }

    @Test
    fun longResponseIsCut() {
        server.enqueue(MockResponse().setBody("abcdef"))
        val outcome = HttpCall(client, maxBytes = 4).perform(
            HttpSpec(url = server.url("/big").toString(), timeoutMs = 5_000),
        )
        assertEquals(200, outcome.status)
        assertEquals("abcd", outcome.body)
        assertEquals("响应过长", outcome.error)
    }

    @Test
    fun hugeRequestIsNotSent() {
        val outcome = HttpCall(client, maxBytes = 4).perform(
            HttpSpec(url = "https://example.com/big", method = "POST", body = "abcde"),
        )
        assertEquals("请求过大", outcome.error)
        assertEquals(0, server.requestCount)
    }

    @Test
    fun missingUrlAndBadMethod() {
        assertEquals("缺少 url", HttpCall(client).perform(HttpSpec(url = "  ")).error)
        assertEquals("方法无效", HttpCall(client).perform(HttpSpec(url = "https://example.com/", method = "TRACE")).error)
        assertEquals(
            "这个方法不能带 body",
            HttpCall(client).perform(HttpSpec(url = "https://example.com/", method = "GET", body = "x")).error,
        )
    }

    @Test
    fun refusedPortIsAConnectFailure() {
        val outcome = HttpCall(
            OkHttpClient.Builder()
                .connectTimeout(2, TimeUnit.SECONDS)
                .onlyHttps()
                .build(),
        ).perform(HttpSpec(url = "https://127.0.0.1:1/", timeoutMs = 2_000))
        assertEquals(0, outcome.status)
        assertEquals("连接失败", outcome.error)
    }
}
