package com.victor.companion.crypto

import com.victor.companion.models.PhoneMessage
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.SecureRandom
import java.util.Collections
import java.util.Locale
import java.util.TreeSet
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec
import android.util.Base64

class CompanionCrypto {

    private val seenNonces = Collections.synchronizedMap(mutableMapOf<String, Double>())

    companion object {
        const val TIMESTAMP_TOLERANCE_SECONDS = 30.0
        const val NONCE_CACHE_TTL_SECONDS = 120.0

        fun hexStringToByteArray(s: String): ByteArray {
            val len = s.length
            val data = ByteArray(len / 2)
            var i = 0
            while (i < len) {
                data[i / 2] = ((Character.digit(s[i], 16) shl 4) + Character.digit(s[i + 1], 16)).toByte()
                i += 2
            }
            return data
        }

        fun byteArrayToHexString(bytes: ByteArray): String {
            val sb = StringBuilder()
            for (b in bytes) {
                sb.append(String.format("%02x", b))
            }
            return sb.toString()
        }

        /**
         * Sorts JSON keys deterministically to match Python json.dumps(sort_keys=True, separators=(',', ':'))
         */
        fun canonicalJson(json: JSONObject): String {
            val sortedKeys = TreeSet<String>()
            val iter = json.keys()
            while (iter.hasNext()) {
                sortedKeys.add(iter.next())
            }
            val sb = StringBuilder("{")
            var first = true
            for (key in sortedKeys) {
                if (!first) sb.append(",")
                first = false
                sb.append("\"").append(key).append("\":")
                val value = json.get(key)
                when (value) {
                    is JSONObject -> sb.append(canonicalJson(value))
                    is String -> sb.append("\"").append(value.replace("\"", "\\\"")).append("\"")
                    else -> sb.append(value.toString())
                }
            }
            sb.append("}")
            return sb.toString()
        }
    }

    fun verifyReplayProtection(nonce: String, timestamp: Double): Boolean {
        val now = System.currentTimeMillis() / 1000.0
        val drift = Math.abs(now - timestamp)
        if (drift > TIMESTAMP_TOLERANCE_SECONDS) {
            return false
        }

        val cutoff = now - NONCE_CACHE_TTL_SECONDS
        seenNonces.entries.removeIf { it.value < cutoff }

        if (seenNonces.containsKey(nonce)) {
            return false
        }

        seenNonces[nonce] = now
        return true
    }

    fun signMessage(message: PhoneMessage, sharedSecretHex: String): String {
        val keyBytes = hexStringToByteArray(sharedSecretHex)
        val secretKey = SecretKeySpec(keyBytes, "HmacSHA256")
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(secretKey)

        val payloadStr = canonicalJson(message.payload)
        val formattedTimestamp = String.format(Locale.US, "%.3f", message.timestamp)
        val raw = "${message.id}:$formattedTimestamp:${message.nonce}:${message.type}:${message.action}:$payloadStr"
        val rawBytes = raw.toByteArray(StandardCharsets.UTF_8)

        val signatureBytes = mac.doFinal(rawBytes)
        return byteArrayToHexString(signatureBytes)
    }

    fun verifySignature(message: PhoneMessage, sharedSecretHex: String): Boolean {
        if (message.signature.isBlank()) return false
        val expected = signMessage(message, sharedSecretHex)
        return expected.equals(message.signature, ignoreCase = true)
    }

    fun encryptPayload(payload: JSONObject, sharedSecretHex: String): String {
        val keyBytes = hexStringToByteArray(sharedSecretHex)
        val secretKey = SecretKeySpec(keyBytes, "AES")
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")

        val iv = ByteArray(12)
        SecureRandom().nextBytes(iv)
        val spec = GCMParameterSpec(128, iv)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey, spec)

        val data = canonicalJson(payload).toByteArray(StandardCharsets.UTF_8)
        val ciphertext = cipher.doFinal(data)

        val combined = ByteArray(iv.size + ciphertext.size)
        System.arraycopy(iv, 0, combined, 0, iv.size)
        System.arraycopy(ciphertext, 0, combined, iv.size, ciphertext.size)

        return Base64.encodeToString(combined, Base64.NO_WRAP)
    }

    fun decryptPayload(encryptedB64: String, sharedSecretHex: String): JSONObject {
        val keyBytes = hexStringToByteArray(sharedSecretHex)
        val secretKey = SecretKeySpec(keyBytes, "AES")
        val combined = Base64.decode(encryptedB64, Base64.NO_WRAP)

        if (combined.size < 28) {
            throw IllegalArgumentException("Encrypted payload too short")
        }

        val iv = ByteArray(12)
        System.arraycopy(combined, 0, iv, 0, 12)
        val ciphertext = ByteArray(combined.size - 12)
        System.arraycopy(combined, 12, ciphertext, 0, ciphertext.size)

        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        val spec = GCMParameterSpec(128, iv)
        cipher.init(Cipher.DECRYPT_MODE, secretKey, spec)

        val decryptedBytes = cipher.doFinal(ciphertext)
        val jsonStr = String(decryptedBytes, StandardCharsets.UTF_8)
        return JSONObject(jsonStr)
    }
}
