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

        // Strictly emit notification event with title and text preview
        val extras = sbn.notification?.extras
        val title = extras?.getCharSequence("android.title")?.toString() ?: ""
        val text = extras?.getCharSequence("android.text")?.toString() ?: ""

        if (source == null && (title.isNotBlank() || text.isNotBlank())) {
            if (pkg.contains("telegram", ignoreCase = true)) source = "telegram"
            else if (pkg.contains("instagram", ignoreCase = true)) source = "instagram"
            else if (pkg.contains("gmail", ignoreCase = true)) source = "gmail"
            else source = pkg.substringAfterLast('.')
        }

        if (source != null) {
            val event = JSONObject()
            event.put("source", source)
            event.put("title", title)
            event.put("text", text)
            event.put("package", pkg)
            event.put("post_time", sbn.postTime)
            notificationCallback?.invoke(event)
        }
    }
}
