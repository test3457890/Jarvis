package com.jarvis.companion

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URI
import java.util.concurrent.TimeUnit

/**
 * Validates companion endpoints:
 * - Requires HTTPS for all non-loopback hosts (e.g. private VPN / Tailscale TLS proxy).
 * - Permits HTTP strictly for 127.0.0.1 / localhost (local ADB reverse development).
 * - Rejects embedded credentials and unsupported schemes.
 */
object EndpointPolicy {
    fun validate(rawUrl: String): String {
        val trimmed = rawUrl.trim().trimEnd('/')
        val uri = URI(trimmed)
        val scheme = uri.scheme?.lowercase() ?: ""
        val host = uri.host?.lowercase() ?: ""
        require(uri.userInfo == null) { "Embedded credentials in endpoint URL are forbidden." }
        require(host.isNotEmpty()) { "Endpoint host is required." }
        val isLoopback = host == "127.0.0.1" || host == "localhost"
        when (scheme) {
            "https" -> return trimmed
            "http" -> {
                require(isLoopback) { "Cleartext HTTP is only allowed for loopback (127.0.0.1/localhost). Use HTTPS for remote VPN endpoints." }
                return trimmed
            }
            else -> throw IllegalArgumentException("Unsupported URL scheme '$scheme'. Use HTTPS (or loopback HTTP for ADB dev).")
        }
    }
}

/**
 * Hardware-backed EncryptedSharedPreferences storage for the paired device bearer token.
 */
class SecureTokenStore(context: Context) {
    private val masterKey = MasterKey.Builder(context)
        .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
        .build()

    private val prefs = EncryptedSharedPreferences.create(
        context,
        "jarvis_companion_vault",
        masterKey,
        EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
        EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
    )

    fun saveToken(token: String) {
        prefs.edit().putString("device_token", token).apply()
    }

    fun loadToken(): String? = prefs.getString("device_token", null)

    fun clearToken() {
        prefs.edit().remove("device_token").apply()
    }
}

/**
 * Loopback / private-VPN HTTP client for the Jarvis 2.0 desktop server.
 */
class JarvisApiClient(
    private val baseUrl: String,
    private val deviceToken: String? = null,
) {
    private val jsonMedia = "application/json; charset=utf-8".toMediaType()
    private val client = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

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
                val safeBase = EndpointPolicy.validate(baseUrl)
                val reqBuilder = Request.Builder()
                    .url(safeBase + path)
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
