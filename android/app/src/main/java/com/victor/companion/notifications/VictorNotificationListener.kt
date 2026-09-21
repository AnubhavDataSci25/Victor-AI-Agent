package com.victor.companion.notifications

import android.provider.Telephony
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import org.json.JSONObject

class VictorNotificationListener : NotificationListenerService() {

    companion object {
        private var notificationCallback: ((JSONObject) -> Unit)? = null

        fun setNotificationCallback(callback: (JSONObject) -> Unit) {
            notificationCallback = callback
        }

        fun clearNotificationCallback() {
            notificationCallback = null
        }
    }

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        super.onNotificationPosted(sbn)
        if (sbn == null) return

        val pkg = sbn.packageName ?: ""
        var source: String? = null

        // 1. WhatsApp Notifications
        if (pkg.equals("com.whatsapp", ignoreCase = true) || pkg.equals("com.whatsapp.w4b", ignoreCase = true)) {
            source = "whatsapp"
        }

        // 2. Default SMS Provider
        val defaultSmsPkg = Telephony.Sms.getDefaultSmsPackage(this)
        if (pkg.equals(defaultSmsPkg, ignoreCase = true) || pkg.contains("messaging", ignoreCase = true)) {
            source = "sms"
        }

        // Strictly emit minimal notification event without transferring message contents
        if (source != null) {
            val event = JSONObject()
            event.put("source", source)
            event.put("post_time", sbn.postTime)
            notificationCallback?.invoke(event)
        }
    }
}
