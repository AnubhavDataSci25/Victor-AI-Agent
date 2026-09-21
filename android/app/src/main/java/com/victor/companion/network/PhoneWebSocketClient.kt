package com.victor.companion.network

import android.content.Context
import android.content.SharedPreferences
import android.os.BatteryManager
import com.victor.companion.command.CommandDispatcher
import com.victor.companion.crypto.CompanionCrypto
import com.victor.companion.models.PhoneMessage
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit

class PhoneWebSocketClient(
    private val context: Context,
    private val crypto: CompanionCrypto,
    private val commandDispatcher: CommandDispatcher,
    private val onStatusChange: (String) -> Unit
) {
    private val client = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private val prefs: SharedPreferences = context.getSharedPreferences("victor_companion_prefs", Context.MODE_PRIVATE)
    private val executor = Executors.newSingleThreadScheduledExecutor()
    private var heartbeatTask: ScheduledFuture<*>? = null

    private var currentHost: String = ""
    private var currentPort: Int = 8000
    private var currentPin: String = ""

    fun isPaired(): Boolean {
        return prefs.getString("shared_secret_hex", null) != null
    }

    fun getSharedSecret(): String? {
        return prefs.getString("shared_secret_hex", null)
    }

    fun unpair() {
        prefs.edit().clear().apply()
        disconnect()
        onStatusChange("UNPAIRED")
    }

    fun connect(host: String, port: Int, pin: String = "") {
        currentHost = host
        currentPort = port
        currentPin = pin

        disconnect()

        val url = "ws://$host:$port/ws/phone"
        val request = Request.Builder().url(url).build()

        onStatusChange("CONNECTING...")

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                onStatusChange("CONNECTED")
                startHeartbeat()

                if (!isPaired() && currentPin.isNotBlank()) {
                    // Send pairing request
                    sendPairingRequest(currentPin)
                }
            }

            override fun onMessage(ws: WebSocket, text: String) {
                handleIncomingMessage(text)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                stopHeartbeat()
                onStatusChange("DISCONNECTED")
            }

            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                stopHeartbeat()
                onStatusChange("CONNECTION FAILED: ${t.message}")
            }
        })
    }

    fun disconnect() {
        stopHeartbeat()
        webSocket?.close(1000, "User disconnected")
        webSocket = null
        onStatusChange("DISCONNECTED")
    }

    private fun sendPairingRequest(pin: String) {
        val deviceId = prefs.getString("device_id", null) ?: java.util.UUID.randomUUID().toString().also {
            prefs.edit().putString("device_id", it).apply()
        }
        val deviceName = "${android.os.Build.MANUFACTURER} ${android.os.Build.MODEL}"

        val payload = JSONObject().apply {
            put("token", pin)
            put("device_id", deviceId)
            put("device_name", deviceName)
        }

        val msg = PhoneMessage(
            type = "pair_request",
            action = "pair",
            payload = payload
        )
        webSocket?.send(msg.toJson().toString())
    }

    private fun handleIncomingMessage(text: String) {
        try {
            val json = JSONObject(text)
            val type = json.optString("type")
            val action = json.optString("action")

            if (type == "pair_response") {
                val payload = json.optJSONObject("payload")
                val secret = payload?.optString("shared_secret_hex")
                if (!secret.isNullOrBlank()) {
                    prefs.edit().putString("shared_secret_hex", secret).apply()
                    onStatusChange("PAIRED & ONLINE")
                }
                return
            }

            val secret = getSharedSecret()
            if (secret == null) return

            val msg = PhoneMessage.fromJson(json)

            // Verify replay protection & signature
            if (!crypto.verifyReplayProtection(msg.nonce, msg.timestamp)) return
            if (!crypto.verifySignature(msg, secret)) return

            if (msg.type == "command") {
                val result = commandDispatcher.dispatch(msg)
                val responseMsg = PhoneMessage(
                    id = msg.id,
                    type = "command_response",
                    action = msg.action,
                    payload = result
                )
                responseMsg.signature = crypto.signMessage(responseMsg, secret)
                webSocket?.send(responseMsg.toJson().toString())
            }

        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    fun sendEvent(action: String, payload: JSONObject) {
        val secret = getSharedSecret() ?: return
        val msg = PhoneMessage(
            type = "event",
            action = action,
            payload = payload
        )
        msg.signature = crypto.signMessage(msg, secret)
        webSocket?.send(msg.toJson().toString())
    }

    private fun startHeartbeat() {
        stopHeartbeat()
        heartbeatTask = executor.scheduleWithFixedDelay({
            try {
                val secret = getSharedSecret() ?: return@scheduleWithFixedDelay
                val bm = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
                val batteryLevel = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
                val isCharging = bm?.isCharging ?: false

                val payload = JSONObject().apply {
                    put("battery_level", batteryLevel)
                    put("is_charging", isCharging)
                }

                val msg = PhoneMessage(
                    type = "heartbeat",
                    action = "ping",
                    payload = payload
                )
                msg.signature = crypto.signMessage(msg, secret)
                webSocket?.send(msg.toJson().toString())
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }, 5, 15, TimeUnit.SECONDS)
    }

    private fun stopHeartbeat() {
        heartbeatTask?.cancel(true)
        heartbeatTask = null
    }
}
