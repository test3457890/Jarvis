package com.jarvis.companion

import org.junit.Assert.assertEquals
import org.junit.Test

class JarvisApiClientTest {
    @Test
    fun allowsHttpsAndLoopbackDevOnly() {
        assertEquals("https://jarvis.ts.net:8443", EndpointPolicy.validate("https://jarvis.ts.net:8443/"))
        assertEquals("http://127.0.0.1:8765", EndpointPolicy.validate("http://127.0.0.1:8765/"))
        assertEquals("http://localhost:8765", EndpointPolicy.validate("http://localhost:8765"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsNonLoopbackCleartextHttp() {
        EndpointPolicy.validate("http://192.168.1.50:8765")
    }

    @Test(expected = IllegalArgumentException::class)
    fun rejectsEmbeddedCredentials() {
        EndpointPolicy.validate("https://user:pass@jarvis.ts.net")
    }
}
