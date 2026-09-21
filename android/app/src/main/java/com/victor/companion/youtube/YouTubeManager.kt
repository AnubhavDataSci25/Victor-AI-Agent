package com.victor.companion.youtube

import android.app.SearchManager
import android.content.Context
import android.content.Intent
import android.net.Uri

class YouTubeManager(private val context: Context) {

    fun openYouTube(query: String = ""): Boolean {
        val cleanQuery = query.trim()

        return try {
            if (cleanQuery.isNotBlank()) {
                // Search query targeting YouTube app directly
                val intent = Intent(Intent.ACTION_SEARCH).apply {
                    setPackage("com.google.android.youtube")
                    putExtra(SearchManager.QUERY, cleanQuery)
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                if (intent.resolveActivity(context.packageManager) != null) {
                    context.startActivity(intent)
                    return true
                }

                // Fallback to YouTube web URI targeting browser if app not installed
                val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com/results?search_query=${Uri.encode(cleanQuery)}")).apply {
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK
                }
                context.startActivity(webIntent)
                true
            } else {
                // Launch YouTube home
                val launchIntent = context.packageManager.getLaunchIntentForPackage("com.google.android.youtube")
                if (launchIntent != null) {
                    launchIntent.flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    context.startActivity(launchIntent)
                    true
                } else {
                    val webIntent = Intent(Intent.ACTION_VIEW, Uri.parse("https://www.youtube.com")).apply {
                        flags = Intent.FLAG_ACTIVITY_NEW_TASK
                    }
                    context.startActivity(webIntent)
                    true
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
            false
        }
    }
}
