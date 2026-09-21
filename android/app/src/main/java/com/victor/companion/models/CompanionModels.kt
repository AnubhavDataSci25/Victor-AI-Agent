package com.victor.companion.models

import org.json.JSONObject
import java.util.UUID

data class PhoneMessage(
    val id: String = UUID.randomUUID().toString(),
    val timestamp: Double = System.currentTimeMillis() / 1000.0,
    val nonce: String = UUID.randomUUID().toString().replace("-", ""),
    val type: String,
    val action: String = "",
    val payload: JSONObject = JSONObject(),
    var signature: String = ""
) {
    fun toJson(): JSONObject {
        val json = JSONObject()
        json.put("id", id)
        json.put("timestamp", timestamp)
        json.put("nonce", nonce)
        json.put("type", type)
        json.put("action", action)
        json.put("payload", payload)
        json.put("signature", signature)
        return json
    }

    companion object {
        fun fromJson(json: JSONObject): PhoneMessage {
            return PhoneMessage(
                id = json.optString("id", UUID.randomUUID().toString()),
                timestamp = json.optDouble("timestamp", System.currentTimeMillis() / 1000.0),
                nonce = json.optString("nonce", ""),
                type = json.optString("type", ""),
                action = json.optString("action", ""),
                payload = json.optJSONObject("payload") ?: JSONObject(),
                signature = json.optString("signature", "")
            )
        }
    }
}

data class ContactItem(
    val name: String,
    val number: String,
    val type: String = "Mobile"
) {
    fun toJson(): JSONObject {
        val json = JSONObject()
        json.put("name", name)
        json.put("number", number)
        json.put("type", type)
        return json
    }
}
