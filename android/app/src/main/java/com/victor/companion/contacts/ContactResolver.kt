package com.victor.companion.contacts

import android.content.Context
import android.content.pm.PackageManager
import android.provider.ContactsContract
import androidx.core.content.ContextCompat
import com.victor.companion.models.ContactItem

class ContactResolver(private val context: Context) {

    fun searchContacts(query: String): List<ContactItem> {
        val cleanQuery = query.trim()
        if (cleanQuery.isBlank()) return emptyList()

        if (ContextCompat.checkSelfPermission(context, android.Manifest.permission.READ_CONTACTS)
            != PackageManager.PERMISSION_GRANTED) {
            return emptyList()
        }

        val results = mutableListOf<ContactItem>()

        val uri = ContactsContract.CommonDataKinds.Phone.CONTENT_URI
        // Least-privilege projection: only contact name, phone number, and phone label type
        val projection = arrayOf(
            ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
            ContactsContract.CommonDataKinds.Phone.NUMBER,
            ContactsContract.CommonDataKinds.Phone.TYPE
        )

        val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
        val selectionArgs = arrayOf("%$cleanQuery%")
        val sortOrder = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} ASC LIMIT 5"

        try {
            context.contentResolver.query(uri, projection, selection, selectionArgs, sortOrder)?.use { cursor ->
                val nameIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME)
                val numberIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.NUMBER)
                val typeIdx = cursor.getColumnIndex(ContactsContract.CommonDataKinds.Phone.TYPE)

                while (cursor.moveToNext()) {
                    val name = if (nameIdx != -1) cursor.getString(nameIdx) else "Unknown"
                    val number = if (numberIdx != -1) cursor.getString(numberIdx) else ""
                    val typeCode = if (typeIdx != -1) cursor.getInt(typeIdx) else ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE

                    val typeLabel = when (typeCode) {
                        ContactsContract.CommonDataKinds.Phone.TYPE_HOME -> "Home"
                        ContactsContract.CommonDataKinds.Phone.TYPE_WORK -> "Work"
                        ContactsContract.CommonDataKinds.Phone.TYPE_MOBILE -> "Mobile"
                        else -> "Other"
                    }

                    if (number.isNotBlank()) {
                        results.add(ContactItem(name = name, number = number, type = typeLabel))
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }

        return results
    }
}
