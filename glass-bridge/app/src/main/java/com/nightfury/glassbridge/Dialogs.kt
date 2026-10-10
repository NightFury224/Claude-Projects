package com.nightfury.glassbridge

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Toast

/** Pop-up dialogs for the OpenRouter key and model, shared by the main screen and the assistant. */
object Dialogs {

    fun keyStatus(activity: Activity): String {
        val key = Prefs.getString(activity, Prefs.AI_KEY).orEmpty()
        return if (key.isBlank()) "🔑 Add OpenRouter API key" else "🔑 OpenRouter key: …${key.takeLast(4)}  (tap to change)"
    }

    /** Asks for the OpenRouter key, saves it, then checks it works. */
    fun askForKey(activity: Activity, onSaved: () -> Unit = {}) {
        val pad = (20 * activity.resources.displayMetrics.density).toInt()
        val input = EditText(activity).apply {
            hint = "sk-or-v1-…"
            isSingleLine = true
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
            setText(Prefs.getString(activity, Prefs.AI_KEY).orEmpty())
        }
        val box = LinearLayout(activity).apply {
            setPadding(pad, pad / 2, pad, 0)
            addView(input, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        }
        AlertDialog.Builder(activity)
            .setTitle("OpenRouter API key")
            .setMessage("Paste your key from openrouter.ai → Keys. One key works for every model.")
            .setView(box)
            .setPositiveButton("Save") { _, _ ->
                val key = input.text.toString().trim()
                Prefs.setString(activity, Prefs.AI_KEY, key)
                onSaved()
                if (key.isNotEmpty()) test(activity)
            }
            .setNeutralButton("Get a key") { _, _ ->
                activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://openrouter.ai/keys")))
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun test(activity: Activity) {
        Toast.makeText(activity, "Checking the key…", Toast.LENGTH_SHORT).show()
        Thread {
            val result = runCatching { AiClient.testKey(activity.applicationContext) }
            activity.runOnUiThread {
                val message = result.fold({ "✅ Key works" }, { "⚠️ ${it.message}" })
                Toast.makeText(activity, message, Toast.LENGTH_LONG).show()
            }
        }.start()
    }

    fun modelStatus(activity: Activity): String {
        val chosen = AiClient.chosenModel(activity)
        return "🤖 Model: " + (if (chosen == AiClient.AUTO_FREE) "Auto (best free)" else chosen) + "  (tap to change)"
    }

    /** Lets the user pick from OpenRouter's free models that understand images, best first. */
    fun pickModel(activity: Activity, onChosen: () -> Unit) {
        Toast.makeText(activity, "Loading free models…", Toast.LENGTH_SHORT).show()
        Thread {
            val result = runCatching { AiClient.freeVisionModels(activity.applicationContext, refresh = true) }
            activity.runOnUiThread {
                result.onSuccess { models ->
                    if (models.isEmpty()) {
                        Toast.makeText(activity, "OpenRouter has no free image models right now", Toast.LENGTH_LONG).show()
                        return@onSuccess
                    }
                    val ids = listOf(AiClient.AUTO_FREE) + models.map { it.id }
                    val labels = listOf("⭐ Auto: best free model, with backups (recommended)") +
                        models.mapIndexed { i, m -> "${i + 1}. ${m.name}" }
                    AlertDialog.Builder(activity)
                        .setTitle("Free models that understand images")
                        .setItems(labels.toTypedArray()) { _, which ->
                            Prefs.setString(activity, Prefs.AI_MODEL, ids[which])
                            onChosen()
                        }
                        .setNegativeButton("Cancel", null)
                        .show()
                }.onFailure {
                    Toast.makeText(activity, "Couldn't load models: ${it.message}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }
}
