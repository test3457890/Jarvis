package com.jarvis.companion

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Loopback / private-VPN HTTP client for the Jarvis 2.0 desktop server.
 * Connects via ADB reverse (http://127.0.0.1:8765) or an authenticated private VPN proxy.
 * Never exposes Jarvis directly to the public internet.
 */
class JarvisApiClient(
    private val baseUrl: String,
    private val deviceToken: String? = null,
) {
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private fun cleanBase(): String = baseUrl.trim().trimEnd('/')

    suspend fun completePairing(code: String, deviceName: String): Result<JSONObject> =
        postJson("/api/companion", JSONObject().apply {
            put("action", "complete_pair")
            put("code", code.trim())
            put("device_name", deviceName.trim())
            put("platform", "android")
        })

    suspend fun fetchStatus(): Result<JSONObject> =
        postJson("/api/companion", JSONObject().apply {
            put("action", "device_status")
            put("token", deviceToken.orEmpty())
        })

    suspend fun runApprovedCommand(tool: String): Result<JSONObject> =
        postJson("/api/companion", JSONObject().apply {
            put("action", "command")
            put("token", deviceToken.orEmpty())
            put("tool", tool)
        })

    private suspend fun postJson(path: String, payload: JSONObject): Result<JSONObject> =
        withContext(Dispatchers.IO) {
            runCatching {
                val reqBuilder = Request.Builder()
                    .url(cleanBase() + path)
                    .post(payload.toString().toRequestBody(jsonMedia))
                if (!deviceToken.isNullOrBlank()) {
                    reqBuilder.header("Authorization", "Bearer $deviceToken")
                }
                client.newCall(reqBuilder.build()).execute().use { resp ->
                    val text = resp.body?.string().orEmpty()
                    val obj = if (text.isNotBlank()) JSONObject(text) else JSONObject()
                    if (!resp.isSuccessful) {
                        error(obj.optString("error", "HTTP ${resp.code}"))
                    }
                    obj
                }
            }
        }
}
