package com.victor.companion.telecom

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.telecom.TelecomManager
import android.telephony.PhoneStateListener
import android.telephony.TelephonyManager
import androidx.core.content.ContextCompat
import com.victor.companion.contacts.ContactResolver
import org.json.JSONObject

class VictorCallManager(
    private val context: Context,
    private val onIncomingCallEvent: (JSONObject) -> Unit
) {
    private val telecomManager = context.getSystemService(Context.TELECOM_SERVICE) as? TelecomManager
    private val telephonyManager = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
    private val contactResolver = ContactResolver(context)

    init {
        setupCallStateListener()
    }

    @Suppress("DEPRECATION")
    private fun setupCallStateListener() {
        if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.READ_PHONE_STATE)
            == PackageManager.PERMISSION_GRANTED) {
            try {
                telephonyManager?.listen(object : PhoneStateListener() {
                    override fun onCallStateChanged(state: Int, incomingNumber: String?) {
                        super.onCallStateChanged(state, incomingNumber)
                        handleCallStateChange(state, incomingNumber)
                    }
                }, PhoneStateListener.LISTEN_CALL_STATE)
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    private fun handleCallStateChange(state: Int, incomingNumber: String?) {
        val number = incomingNumber ?: ""
        var callerName = "Unknown Caller"

        if (number.isNotBlank()) {
            val matches = contactResolver.searchContacts(number)
            if (matches.isNotEmpty()) {
                callerName = matches[0].name
            } else {
                callerName = number
            }
        }

        val event = JSONObject()
        event.put("caller_name", callerName)
        event.put("caller_number", number)
        event.put("call_type", "phone")

        when (state) {
            TelephonyManager.CALL_STATE_RINGING -> {
                event.put("status", "RINGING")
                onIncomingCallEvent(event)
            }
            TelephonyManager.CALL_STATE_OFFHOOK -> {
                event.put("status", "ANSWERED")
                onIncomingCallEvent(event)
            }
            TelephonyManager.CALL_STATE_IDLE -> {
                event.put("status", "IDLE")
                onIncomingCallEvent(event)
            }
        }
    }

    fun makeCall(phoneNumber: String): Boolean {
        if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.CALL_PHONE)
            != PackageManager.PERMISSION_GRANTED) {
            return false
        }

        return try {
            val intent = Intent(Intent.ACTION_CALL).apply {
                data = Uri.parse("tel:${Uri.encode(phoneNumber)}")
                flags = Intent.FLAG_ACTIVITY_NEW_TASK
            }
            context.startActivity(intent)
            true
        } catch (e: Exception) {
            e.printStackTrace()
            false
        }
    }

    fun answerCall(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.ANSWER_PHONE_CALLS)
                == PackageManager.PERMISSION_GRANTED) {
                return try {
                    telecomManager?.acceptRingingCall()
                    true
                } catch (e: Exception) {
                    e.printStackTrace()
                    false
                }
            }
        }
        return false
    }

    fun rejectCall(): Boolean {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.ANSWER_PHONE_CALLS)
                == PackageManager.PERMISSION_GRANTED) {
                return try {
                    telecomManager?.endCall()
                    true
                } catch (e: Exception) {
                    e.printStackTrace()
                    false
                }
            }
        }
        return false
    }
}
