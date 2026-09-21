package com.victor.companion.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.victor.companion.command.CommandDispatcher
import com.victor.companion.crypto.CompanionCrypto
import com.victor.companion.network.PhoneWebSocketClient
import com.victor.companion.notifications.VictorNotificationListener
import com.victor.companion.telecom.VictorCallManager

class VictorCompanionService : Service() {

    private val binder = LocalBinder()
    private lateinit var crypto: CompanionCrypto
    private lateinit var callManager: VictorCallManager
    private lateinit var commandDispatcher: CommandDispatcher
    lateinit var webSocketClient: PhoneWebSocketClient

    var onStatusChanged: ((String) -> Unit)? = null

    companion object {
        const val CHANNEL_ID = "victor_companion_channel"
        const val NOTIFICATION_ID = 101

        const val ACTION_START = "ACTION_START"
        const val ACTION_STOP = "ACTION_STOP"
    }

    inner class LocalBinder : Binder() {
        fun getService(): VictorCompanionService = this@VictorCompanionService
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()

        crypto = CompanionCrypto()

        callManager = VictorCallManager(this) { callEvent ->
            webSocketClient.sendEvent("incoming_call", callEvent)
        }

        commandDispatcher = CommandDispatcher(this, callManager)

        webSocketClient = PhoneWebSocketClient(this, crypto, commandDispatcher) { status ->
            onStatusChanged?.invoke(status)
            updateNotification(status)
        }

        VictorNotificationListener.setNotificationCallback { notifEvent ->
            webSocketClient.sendEvent("notification", notifEvent)
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        if (action == ACTION_STOP) {
            webSocketClient.disconnect()
            stopForeground(true)
            stopSelf()
            return START_NOT_STICKY
        }

        startForeground(NOTIFICATION_ID, buildNotification("Service Active"))

        val host = intent?.getStringExtra("host") ?: ""
        val port = intent?.getIntExtra("port", 8000) ?: 8000
        val pin = intent?.getStringExtra("pin") ?: ""

        if (host.isNotBlank()) {
            webSocketClient.connect(host, port, pin)
        }

        return START_STICKY
    }

    override fun onDestroy() {
        VictorNotificationListener.clearNotificationCallback()
        webSocketClient.disconnect()
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Victor Companion Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Maintains secure communication with Victor PC"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(status: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Victor Companion")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.sym_def_app_icon)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun updateNotification(status: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification("Status: $status"))
    }
}
