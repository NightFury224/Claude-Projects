package com.nightfury.glassbridge

import android.content.Context
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Talks to OpenRouter (one key, many models). Keeps a short conversation so follow-up questions work. */
object AiClient {
    /** OpenRouter picks a suitable model; the user can choose a specific one in settings. */
    const val DEFAULT_MODEL = "openrouter/auto"

    private const val BASE = "https://openrouter.ai/api/v1"
    private const val FORGET_AFTER_MS = 10 * 60_000L
    private const val MAX_HISTORY = 10

    private val history = ArrayList<JSONObject>()
    private var lastAskedAt = 0L

    fun model(ctx: Context) =
        Prefs.getString(ctx, Prefs.AI_MODEL)?.trim()?.takeIf { it.isNotEmpty() } ?: DEFAULT_MODEL

    /** Blocking; call from a background thread. */
    fun ask(ctx: Context, question: String): String {
        val key = Prefs.getString(ctx, Prefs.AI_KEY)?.trim().orEmpty()
        if (key.isEmpty()) throw IOException("Add your OpenRouter API key in the Glass Bridge app")

        val now = SystemClock.elapsedRealtime()
        val earlier = synchronized(history) {
            if (now - lastAskedAt > FORGET_AFTER_MS) history.clear()
            history.toList()
        }
        val userMessage = JSONObject().put("role", "user").put("content", question)
        val messages = JSONArray().put(JSONObject().put("role", "system").put("content", systemPrompt()))
        earlier.forEach { messages.put(it) }
        messages.put(userMessage)

        val body = JSONObject()
            .put("model", model(ctx))
            .put("messages", messages)
            .put("max_tokens", 600)
        val response = request("POST", "$BASE/chat/completions", key, body.toString())
        val answer = JSONObject(response).getJSONArray("choices").getJSONObject(0)
            .getJSONObject("message").optString("content").trim()
        if (answer.isEmpty()) throw IOException("The model returned an empty answer")

        synchronized(history) {
            history += userMessage
            history += JSONObject().put("role", "assistant").put("content", answer)
            while (history.size > MAX_HISTORY) history.removeAt(0)
            lastAskedAt = now
        }
        return answer
    }

    fun forget() = synchronized(history) { history.clear() }

    /** Model ids available on OpenRouter, for the picker. Blocking. */
    fun models(): List<String> {
        val data = JSONObject(request("GET", "$BASE/models", null, null)).getJSONArray("data")
        return (0 until data.length()).map { data.getJSONObject(it).getString("id") }.sorted()
    }

    private fun systemPrompt(): String {
        val now = SimpleDateFormat("EEEE d MMMM yyyy, h:mm a", Locale.ENGLISH).format(Date())
        return "You are a voice assistant used through smart glasses. The user's words come from " +
            "speech recognition and may contain mistakes; infer what they meant. Your answer is either " +
            "spoken aloud or shown on a small smartwatch screen, so reply in plain text without markdown, " +
            "lists or emoji, and keep it short (one to three sentences) unless the user asks for detail. " +
            "Current date and time: $now."
    }

    private fun request(method: String, url: String, key: String?, body: String?): String {
        val connection = URL(url).openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = 15_000
            connection.readTimeout = 60_000
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("X-Title", "Glass Bridge")
            if (key != null) connection.setRequestProperty("Authorization", "Bearer $key")
            if (body != null) {
                connection.doOutput = true
                connection.outputStream.use { it.write(body.toByteArray()) }
            }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (code !in 200..299) {
                val message = runCatching { JSONObject(text).getJSONObject("error").getString("message") }
                    .getOrNull() ?: "HTTP $code"
                throw IOException(message)
            }
            return text
        } finally {
            connection.disconnect()
        }
    }
}
