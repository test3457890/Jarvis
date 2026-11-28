# Jarvis Mobile Companion Architecture (Android & Future iOS)

## Security-First Design
- **Disabled by Default:** `remote_companion_enabled` defaults to `false`.
- **No Public Internet Exposure:** Jarvis binds strictly to `127.0.0.1:<port>`. Mobile companions connect ONLY via:
  1. Local USB `adb reverse tcp:8765 tcp:8765` (Android developer/local testing), OR
  2. An authenticated, encrypted private mesh VPN (WireGuard / Tailscale) behind a local TLS reverse proxy.
- **Pairing Protocol (`jarvis/companion.py`):**
  1. Desktop user enables companion pairing in Setup and generates a single-use 6-digit pairing code (120-second TTL).
  2. Mobile app submits the pairing code + device name + platform (`android` / `ios`).
  3. Jarvis issues a 256-bit bearer token and stores ONLY its SHA-256 hash in `memory.db` (`paired_devices` table).
  4. Instant per-device revocation from Desktop HUD immediately invalidates the device token.
- **Least-Privilege Command Scope:**
  - Read-only task/vitals monitoring and push-notification polling.
  - Approval cards for pending desktop confirmations (explicit user review required).
  - Lockdown immediately disables all companion access.

## Client Architecture
- **Android Companion (Kotlin + Jetpack Compose + OkHttp):**
  - Connects to `/api/vitals`, `/api/bgtasks`, `/api/events` (SSE), and `/api/confirm` using `Authorization: Bearer <device-token>` stored in Android Keystore (`EncryptedSharedPreferences`).
- **Future iOS Companion (SwiftUI + URLSession):**
  - Identical REST + SSE contract; device token stored in iOS Keychain (`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`).
