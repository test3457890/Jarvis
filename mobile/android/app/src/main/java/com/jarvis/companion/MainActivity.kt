package com.jarvis.companion

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme()) {
                Surface(modifier = Modifier.fillMaxSize()) {
                    JarvisCompanionScreen()
                }
            }
        }
    }
}

@Composable
fun JarvisCompanionScreen() {
    val context = LocalContext.current
    val tokenStore = remember { runCatching { SecureTokenStore(context) }.getOrNull() }
    val scope = rememberCoroutineScope()
    var baseUrl by remember { mutableStateOf("http://127.0.0.1:8765") }
    var pairCode by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf("Android Companion") }
    var token by remember { mutableStateOf(tokenStore?.loadToken()) }
    var statusText by remember {
        mutableStateOf(
            if (token != null) "Paired token loaded from EncryptedSharedPreferences."
            else "Not paired. Use ADB reverse (127.0.0.1) or an authenticated HTTPS VPN."
        )
    }
    var commandOutput by remember { mutableStateOf("") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("J.A.R.V.I.S. Companion", style = MaterialTheme.typography.headlineSmall)
        Text(
            "Local-first companion (ADB reverse / private VPN only). Never exposed to public internet.",
            style = MaterialTheme.typography.bodySmall,
        )

        OutlinedTextField(
            value = baseUrl,
            onValueChange = { baseUrl = it },
            label = { Text("Desktop Endpoint (Loopback / VPN)") },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
        )

        if (token == null) {
            OutlinedTextField(
                value = deviceName,
                onValueChange = { deviceName = it },
                label = { Text("Device Name") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            OutlinedTextField(
                value = pairCode,
                onValueChange = { pairCode = it },
                label = { Text("6-Digit Pairing Code (120s TTL)") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
            )
            Button(
                onClick = {
                    scope.launch {
                        statusText = "Pairing…"
                        val res = JarvisApiClient(baseUrl).completePairing(pairCode, deviceName)
                        res.onSuccess { obj ->
                            val newTok = obj.optString("token")
                            token = newTok
                            tokenStore?.saveToken(newTok)
                            statusText = "Paired as ${obj.optString("name")} (${obj.optString("device_id")})"
                            pairCode = ""
                        }.onFailure { err ->
                            statusText = "Pairing failed: ${err.message}"
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("Pair Device")
            }
        } else {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    scope.launch {
                        val res = JarvisApiClient(baseUrl, token).fetchStatus()
                        res.onSuccess { obj ->
                            commandOutput = obj.toString(2)
                            statusText = "Connected · Status refreshed"
                        }.onFailure { err ->
                            statusText = "Status error: ${err.message}"
                        }
                    }
                }) { Text("Monitor Tasks & Vitals") }

                OutlinedButton(onClick = {
                    token = null
                    tokenStore?.clearToken()
                    commandOutput = ""
                    statusText = "Disconnected and cleared encrypted token."
                }) { Text("Disconnect") }
            }

            Text("Approved Read-Only Commands", style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("system_status", "list_reminders", "briefing").forEach { tool ->
                    FilledTonalButton(onClick = {
                        scope.launch {
                            val res = JarvisApiClient(baseUrl, token).runApprovedCommand(tool)
                            res.onSuccess { obj ->
                                commandOutput = obj.optString("output")
                                statusText = "Ran approved command: $tool"
                            }.onFailure { err ->
                                statusText = "Blocked/Error: ${err.message}"
                            }
                        }
                    }) { Text(tool.replace("_", " ")) }
                }
            }
        }

        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("Status", style = MaterialTheme.typography.labelLarge)
                Text(statusText, style = MaterialTheme.typography.bodyMedium)
                if (commandOutput.isNotBlank()) {
                    HorizontalDivider()
                    Text(commandOutput, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
