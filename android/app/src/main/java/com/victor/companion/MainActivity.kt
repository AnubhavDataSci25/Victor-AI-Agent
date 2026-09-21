package com.victor.companion

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.provider.Settings
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.victor.companion.service.VictorCompanionService

class MainActivity : AppCompatActivity() {

    private lateinit var tvStatus: TextView
    private lateinit var etServerIp: EditText
    private lateinit var etServerPort: EditText
    private lateinit var etPairingPin: EditText
    private lateinit var btnConnect: Button
    private lateinit var btnUnpair: Button
    private lateinit var btnRequestPermissions: Button
    private lateinit var btnNotificationAccess: Button

    private var companionService: VictorCompanionService? = null
    private var isBound = false

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(className: ComponentName, service: IBinder) {
            val binder = service as VictorCompanionService.LocalBinder
            companionService = binder.getService()
            isBound = true

            companionService?.onStatusChanged = { status ->
                runOnUiThread {
                    tvStatus.text = status
                }
            }
        }

        override fun onServiceDisconnected(arg0: ComponentName) {
            isBound = false
            companionService = null
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvStatus = findViewById(R.id.tvStatus)
        etServerIp = findViewById(R.id.etServerIp)
        etServerPort = findViewById(R.id.etServerPort)
        etPairingPin = findViewById(R.id.etPairingPin)
        btnConnect = findViewById(R.id.btnConnect)
        btnUnpair = findViewById(R.id.btnUnpair)
        btnRequestPermissions = findViewById(R.id.btnRequestPermissions)
        btnNotificationAccess = findViewById(R.id.btnNotificationAccess)

        // Load saved server IP & port from SharedPreferences
        val prefs = getSharedPreferences("victor_companion_prefs", Context.MODE_PRIVATE)
        val savedIp = prefs.getString("server_ip", "")
        val savedPort = prefs.getInt("server_port", 8000)
        if (!savedIp.isNullOrBlank()) etServerIp.setText(savedIp)
        etServerPort.setText(savedPort.toString())

        btnConnect.setOnClickListener {
            val ip = etServerIp.text.toString().trim()
            val portStr = etServerPort.text.toString().trim()
            val pin = etPairingPin.text.toString().trim()

            if (ip.isBlank()) {
                Toast.makeText(this, "Please enter Victor PC IP address", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            val port = portStr.toIntOrNull() ?: 8000
            prefs.edit().putString("server_ip", ip).putInt("server_port", port).apply()

            val serviceIntent = Intent(this, VictorCompanionService::class.java).apply {
                action = VictorCompanionService.ACTION_START
                putExtra("host", ip)
                putExtra("port", port)
                putExtra("pin", pin)
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                startForegroundService(serviceIntent)
            } else {
                startService(serviceIntent)
            }

            bindService(serviceIntent, connection, Context.BIND_AUTO_CREATE)
            Toast.makeText(this, "Connecting to Victor PC...", Toast.LENGTH_SHORT).show()
        }

        btnUnpair.setOnClickListener {
            companionService?.webSocketClient?.unpair()
            tvStatus.text = "UNPAIRED"
            Toast.makeText(this, "Device unpaired and credentials wiped.", Toast.LENGTH_SHORT).show()
        }

        btnRequestPermissions.setOnClickListener {
            requestRequiredPermissions()
        }

        btnNotificationAccess.setOnClickListener {
            startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
    }

    private fun requestRequiredPermissions() {
        val permissions = mutableListOf(
            Manifest.permission.READ_CONTACTS,
            Manifest.permission.CALL_PHONE,
            Manifest.permission.READ_PHONE_STATE
        )

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            permissions.add(Manifest.permission.ANSWER_PHONE_CALLS)
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            permissions.add(Manifest.permission.POST_NOTIFICATIONS)
        }

        val needed = permissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (needed.isNotEmpty()) {
            ActivityCompat.requestPermissions(this, needed.toTypedArray(), 1001)
        } else {
            Toast.makeText(this, "All runtime permissions already granted.", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onDestroy() {
        if (isBound) {
            unbindService(connection)
            isBound = false
        }
        super.onDestroy()
    }
}
