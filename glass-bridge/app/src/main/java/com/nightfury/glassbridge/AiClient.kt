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
    /** Setting value meaning "use the best free image-capable model, with backups". */
    const val AUTO_FREE = "auto-free"

    private const val BASE = "https://openrouter.ai/api/v1"
    private const val FORGET_AFTER_MS = 10 * 60_000L
    private const val MAX_HISTORY = 10
    private const val MODEL_CACHE_MS = 12 * 60 * 60_000L

    private val history = ArrayList<JSONObject>()
    private var lastAskedAt = 0L

    /** The chosen model id, or [AUTO_FREE]. */
    fun chosenModel(ctx: Context) =
        Prefs.getString(ctx, Prefs.AI_MODEL)?.trim()?.takeIf { it.isNotEmpty() && !it.contains("openrouter/auto") }
            ?: AUTO_FREE

    class ModelInfo(val id: String, val name: String, val seesImages: Boolean, val free: Boolean)

    /**
     * Free models that understand images, best first. Free models come and go on OpenRouter, so the
     * list is fetched live (and cached for a few hours). Blocking.
     */
    fun freeVisionModels(ctx: Context, refresh: Boolean = false): List<ModelInfo> {
        val cachedAt = Prefs.getString(ctx, Prefs.AI_MODEL_CACHE_TIME)?.toLongOrNull() ?: 0L
        val cached = Prefs.getString(ctx, Prefs.AI_MODEL_CACHE)
        val fresh = System.currentTimeMillis() - cachedAt < MODEL_CACHE_MS
        val json = if (!refresh && fresh && cached != null) cached else {
            request("GET", "$BASE/models", null, null).also {
                Prefs.setString(ctx, Prefs.AI_MODEL_CACHE, it)
                Prefs.setString(ctx, Prefs.AI_MODEL_CACHE_TIME, System.currentTimeMillis().toString())
            }
        }
        return parseModels(json).filter { it.free && it.seesImages }.sortedByDescending { quality(it.id) }
    }

    /**
     * Rough "how capable" score for ranking free image models: well-known strong families first,
     * then bigger models. Tiny models are pushed to the bottom.
     */
    private fun quality(id: String): Int {
        val lower = id.lowercase()
        val family = listOf(
            "google/gemini" to 100, "meta-llama/llama-4-maverick" to 90, "qwen/qwen2.5-vl-72b" to 85,
            "qwen/qwen3-vl" to 85, "meta-llama/llama-4-scout" to 80, "mistralai/mistral-medium" to 78,
            "mistralai/mistral-small-3" to 72, "qwen/qwen2.5-vl" to 70, "google/gemma-3" to 65,
            "moonshotai/kimi-vl" to 60, "meta-llama/llama-3.2-90b-vision" to 60,
        ).firstOrNull { lower.startsWith(it.first) }?.second ?: 50
        val size = Regex("(\\d+)b\\b").find(lower)?.groupValues?.get(1)?.toIntOrNull()
        val sizeBonus = when {
            size == null -> 0
            size < 8 -> -40
            size < 20 -> -10
            else -> minOf(size / 10, 10)
        }
        return family + sizeBonus
    }

    private fun parseModels(json: String): List<ModelInfo> {
        val data = JSONObject(json).getJSONArray("data")
        return (0 until data.length()).map { i ->
            val model = data.getJSONObject(i)
            val id = model.getString("id")
            val inputs = model.optJSONObject("architecture")?.optJSONArray("input_modalities")
            val seesImages = inputs != null && (0 until inputs.length()).any { inputs.optString(it) == "image" }
            val pricing = model.optJSONObject("pricing")
            val free = id.endsWith(":free") || (pricing != null &&
                pricing.optString("prompt").toDoubleOrNull() == 0.0 &&
                pricing.optString("completion").toDoubleOrNull() == 0.0)
            ModelInfo(id, model.optString("name", id), seesImages, free)
        }
    }

    /** Chosen model first, then the best other free image models as automatic backups. */
    private fun modelsToTry(ctx: Context): List<String> {
        val ranked = runCatching { freeVisionModels(ctx).map { it.id } }.getOrDefault(emptyList())
        val chosen = chosenModel(ctx)
        val list = if (chosen == AUTO_FREE) ranked else listOf(chosen) + ranked.filter { it != chosen }
        if (list.isEmpty()) throw IOException("Couldn't load OpenRouter's list of free models. Check your internet.")
        return list.take(3)
    }

    /** Quick check that the key works. Blocking. */
    fun testKey(ctx: Context): String = ask(ctx, "Reply with just the word OK.", remember = false)

    /**
     * Blocking; call from a background thread. [images] are base64 JPEGs from the glasses camera
     * (one photo, or several frames of a video).
     */
    fun ask(
        ctx: Context, question: String, images: List<String> = emptyList(), video: Boolean = false,
        remember: Boolean = true,
    ): String {
        val key = Prefs.getString(ctx, Prefs.AI_KEY)?.trim().orEmpty()
        if (key.isEmpty()) throw IOException("Add your OpenRouter API key in the Glass Bridge app")

        val now = SystemClock.elapsedRealtime()
        val earlier = synchronized(history) {
            if (now - lastAskedAt > FORGET_AFTER_MS) history.clear()
            history.toList()
        }
        val content: Any = if (images.isEmpty()) question else JSONArray().apply {
            val intro = if (video) "These are ${images.size} frames, in order, from a short video my glasses just recorded. "
            else "This is a photo my glasses just took. "
            put(JSONObject().put("type", "text").put("text", intro + question))
            images.forEach {
                put(JSONObject().put("type", "image_url")
                    .put("image_url", JSONObject().put("url", "data:image/jpeg;base64,$it")))
            }
        }
        val userMessage = JSONObject().put("role", "user").put("content", content)
        val messages = JSONArray().put(JSONObject().put("role", "system").put("content", systemPrompt()))
        earlier.forEach { messages.put(it) }
        messages.put(userMessage)

        // OpenRouter tries these in order, so a busy or rate-limited free model falls back to the next.
        val models = modelsToTry(ctx)
        val body = JSONObject()
            .put("model", models.first())
            .put("models", JSONArray(models))
            .put("messages", messages)
            .put("max_tokens", 600)
        val response = request("POST", "$BASE/chat/completions", key, body.toString())
        val answer = JSONObject(response).getJSONArray("choices").getJSONObject(0)
            .getJSONObject("message").optString("content").trim()
        if (answer.isEmpty()) throw IOException("The model returned an empty answer")

        if (remember) synchronized(history) {
            // Remember only the words, not the (large) images, for follow-up questions.
            history += JSONObject().put("role", "user").put("content",
                if (images.isEmpty()) question
                else "[I showed you a ${if (video) "video" else "photo"} from my glasses] $question")
            history += JSONObject().put("role", "assistant").put("content", answer)
            while (history.size > MAX_HISTORY) history.removeAt(0)
            lastAskedAt = now
        }
        return answer
    }

    fun forget() = synchronized(history) { history.clear() }

    private fun systemPrompt(): String {
        val now = SimpleDateFormat("EEEE d MMMM yyyy, h:mm a", Locale.ENGLISH).format(Date())
        return "You are a voice assistant used through smart glasses. The user's words come from " +
            "speech recognition and may contain mistakes; infer what they meant. Your answer is either " +
            "spoken aloud or shown on a small smartwatch screen, so reply in plain text without markdown, " +
            "lists or emoji, and keep it short (one to three sentences) unless the user asks for detail. " +
            "Images, when included, come from the camera on the user's glasses, so they show what the " +
            "user is looking at; answer about them directly. " +
            "Current date and time: $now."
    }

    /** Turns OpenRouter's common errors into something actionable. */
    private fun explain(code: Int, message: String): String = when {
        code == 401 -> "OpenRouter rejected the API key. Set it again in Glass Bridge."
        message.contains("data policy", ignoreCase = true) ->
            "Your OpenRouter privacy settings block free models. On openrouter.ai → Settings → Privacy, " +
                "allow free model endpoints (they may use prompts for training)."
        code == 429 -> "Free-model limit reached for now. Try again in a minute, or later today."
        code == 402 -> "OpenRouter says the account needs credit for this model."
        else -> message
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
                throw IOException(explain(code, message))
            }
            return text
        } finally {
            connection.disconnect()
        }
    }
}
