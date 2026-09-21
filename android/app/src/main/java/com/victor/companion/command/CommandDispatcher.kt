package com.victor.companion.command

import android.content.Context
import android.os.BatteryManager
import com.victor.companion.contacts.ContactResolver
import com.victor.companion.models.PhoneMessage
import com.victor.companion.telecom.VictorCallManager
import com.victor.companion.youtube.YouTubeManager
import org.json.JSONArray
import org.json.JSONObject

class CommandDispatcher(
    private val context: Context,
    private val callManager: VictorCallManager
) {
    private val contactResolver = ContactResolver(context)
    private val youTubeManager = YouTubeManager(context)

    companion object {
        val ALLOWLIST = setOf(
            "resolve_contact",
            "initiate_call",
            "answer_call",
            "reject_call",
            "launch_youtube",
            "get_status"
        )
    }

    fun dispatch(message: PhoneMessage): JSONObject {
        val action = message.action
        val payload = message.payload
        val response = JSONObject()

        if (!ALLOWLIST.contains(action)) {
            response.put("success", false)
            response.put("error", "Action '$action' is not permitted by companion capability allowlist.")
            return response
        }

        when (action) {
            "resolve_contact" -> {
                val query = payload.optString("query", "")
                val matches = contactResolver.searchContacts(query)
                val matchesArray = JSONArray()
                for (m in matches) {
                    matchesArray.put(m.toJson())
                }
                response.put("success", true)
                response.put("matches", matchesArray)
            }

            "initiate_call" -> {
                val phoneNumber = payload.optString("phone_number", "")
                if (phoneNumber.isBlank()) {
                    response.put("success", false)
                    response.put("error", "No phone number provided.")
                } else {
                    val ok = callManager.makeCall(phoneNumber)
                    response.put("success", ok)
                    if (!ok) response.put("error", "Failed to initiate call on device (check permissions).")
                }
            }

            "answer_call" -> {
                val ok = callManager.answerCall()
                response.put("success", ok)
                if (!ok) response.put("error", "Failed to answer call (check Android version/permissions).")
            }

            "reject_call" -> {
                val ok = callManager.rejectCall()
                response.put("success", ok)
                if (!ok) response.put("error", "Failed to reject call.")
            }

            "launch_youtube" -> {
                val query = payload.optString("query", "")
                val ok = youTubeManager.openYouTube(query)
                response.put("success", ok)
                if (!ok) response.put("error", "Failed to launch YouTube intent.")
            }

            "get_status" -> {
                val bm = context.getSystemService(Context.BATTERY_SERVICE) as? BatteryManager
                val batteryLevel = bm?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY) ?: -1
                val isCharging = bm?.isCharging ?: false

                response.put("success", true)
                response.put("battery_level", batteryLevel)
                response.put("is_charging", isCharging)
            }

            else -> {
                response.put("success", false)
                response.put("error", "Unhandled allowlist action.")
            }
        }

        return response
    }
}
