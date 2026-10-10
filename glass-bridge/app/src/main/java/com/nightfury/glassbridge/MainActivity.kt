package com.nightfury.glassbridge

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

/** Setup checklist, options and test buttons. */
class MainActivity : Activity() {
    private lateinit var status: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifier.createChannel(this)

        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad, pad, pad)
        }
        status = TextView(this).apply { textSize = 15f }

        column.addView(heading("Glass Bridge", 26f))
        column.addView(status)

        column.addView(heading("Setup (do these in order)"))
        column.addView(button("1. Allow restricted settings") {
            // Sideloaded apps must be allowed here (App info → ⋮ → Allow restricted settings)
            // before Android lets you turn on their accessibility service.
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        })
        column.addView(button("2. Turn on the accessibility service") {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        })
        column.addView(button("3. Allow notifications") {
            if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        })
        column.addView(button("4. Don't restrict battery") {
            startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        })

        column.addView(heading("Options"))
        column.addView(toggle("Auto-import after every video or photo", Prefs.AUTO_IMPORT, true))
        column.addView(toggle("Bluetooth remote: volume-up = video, volume-down = photo", Prefs.REMOTE_KEYS, false))

        column.addView(heading("AI voice assistant"))
        column.addView(button("5. Allow microphone") {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 2)
        })
        column.addView(label("OpenRouter API key (openrouter.ai → Keys)"))
        column.addView(field(Prefs.AI_KEY, "sk-or-…", secret = true))
        column.addView(label("Model (openrouter/auto lets OpenRouter choose)"))
        val modelField = field(Prefs.AI_MODEL, AiClient.DEFAULT_MODEL, secret = false)
        column.addView(modelField)
        column.addView(button("Browse models…") { pickModel(modelField, imagesOnly = false) })
        column.addView(label("Model for Look / Video (must understand images; blank = same as above)"))
        val visionField = field(Prefs.AI_VISION_MODEL, "same as above", secret = false)
        column.addView(visionField)
        column.addView(button("Browse image models…") { pickModel(visionField, imagesOnly = true) })
        column.addView(button("6. Allow photos & videos (for Look / Video)") {
            requestPermissions(AssistantActivity.mediaPermissions(), 3)
        })
        val clipButton = Button(this).apply { isAllCaps = false }
        fun showClip() {
            clipButton.text = "Video clip length: ${Prefs.getInt(this, Prefs.AI_CLIP_SECONDS, 10)} s  (tap to change)"
        }
        showClip()
        clipButton.setOnClickListener {
            val options = listOf(5, 10, 20, 30)
            val current = Prefs.getInt(this, Prefs.AI_CLIP_SECONDS, 10)
            Prefs.setInt(this, Prefs.AI_CLIP_SECONDS, options[(options.indexOf(current) + 1) % options.size])
            showClip()
        }
        column.addView(clipButton)
        val modeButton = Button(this).apply { isAllCaps = false }
        fun showMode() { modeButton.text = "Answers: " + AnswerMode.current(this).shortName + "  (tap to change)" }
        showMode()
        modeButton.setOnClickListener {
            AnswerMode.set(this, AnswerMode.current(this).next())
            showMode()
        }
        column.addView(modeButton)
        column.addView(button("🎙 Ask (one question)") { startActivity(AiMode.ASK.intent(this)) })
        column.addView(button("💬 Chat (keeps listening; say \"stop\" to end)") { startActivity(AiMode.CHAT.intent(this)) })
        column.addView(button("👁 Look (photo from the glasses)") { startActivity(AiMode.LOOK.intent(this)) })
        column.addView(button("🎥 Video (short clip from the glasses)") { startActivity(AiMode.VIDEO.intent(this)) })

        column.addView(heading("Test"))
        column.addView(button("🎥 Start / stop video") { Commands.run(this, Commands.VIDEO) })
        column.addView(button("📸 Take photo") { Commands.run(this, Commands.PHOTO) })
        column.addView(button("⬇️ Import now") { Commands.run(this, Commands.IMPORT) })
        column.addView(heading("Troubleshooting"))
        column.addView(button("📋 Copy screen report (send it to Claude)") {
            val report = Prefs.getString(this, Prefs.SCREEN_REPORT)
            if (report == null) {
                Toast.makeText(this, "No report yet. It's saved when a command fails.", Toast.LENGTH_LONG).show()
            } else {
                getSystemService(ClipboardManager::class.java)
                    .setPrimaryClip(ClipData.newPlainText("Glass Bridge screen report", report))
                Toast.makeText(this, "Copied. Paste it in your chat with Claude.", Toast.LENGTH_LONG).show()
            }
        })
        column.addView(TextView(this).apply {
            textSize = 14f
            text = "\nTip: add the \"Glasses video\", \"Glasses photo\" and \"Glasses import\" tiles to your " +
                "Quick Settings (swipe down → edit ✏️). Every status notification also has Video/Photo buttons, " +
                "which show up on a paired smartwatch."
        })

        setContentView(ScrollView(this).apply { addView(column) })
    }

    override fun onResume() {
        super.onResume()
        val serviceOn = GlassService.instance != null
        val rd = GlassService.findRdGlass(this)
        val notifications = Build.VERSION.SDK_INT < 33 ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        val battery = getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)
        status.text = listOf(
            mark(rd != null) + " RDGlass app: " + (rd ?: "not found"),
            mark(serviceOn) + " Accessibility service",
            mark(notifications) + " Notifications",
            mark(battery) + " Battery unrestricted",
            mark(checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) +
                " Microphone",
            mark(!Prefs.getString(this, Prefs.AI_KEY).isNullOrBlank()) + " OpenRouter key",
            "Version " + runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull(),
        ).joinToString("\n")
    }

    private fun label(text: String) = TextView(this).apply {
        this.text = text
        textSize = 14f
        setPadding(0, 16, 0, 0)
    }

    private fun field(key: String, hint: String, secret: Boolean) = EditText(this).apply {
        this.hint = hint
        setText(Prefs.getString(this@MainActivity, key).orEmpty())
        isSingleLine = true
        inputType = if (secret) InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                Prefs.setString(this@MainActivity, key, s?.toString()?.trim().orEmpty())
            }
        })
    }

    /** Lists OpenRouter's models (popular providers first) and fills the model field. */
    private fun pickModel(target: EditText, imagesOnly: Boolean) {
        Toast.makeText(this, "Loading models…", Toast.LENGTH_SHORT).show()
        Thread {
            val result = runCatching { AiClient.models() }
            runOnUiThread {
                result.onSuccess { all ->
                    val preferred = listOf("anthropic/", "openai/", "google/", "x-ai/", "deepseek/", "meta-llama/")
                    val models = listOf(AiClient.DEFAULT_MODEL) +
                        all.filter { !imagesOnly || it.seesImages }.map { it.id }
                            .filter { id -> preferred.any { id.startsWith(it) } }
                            .sortedBy { id -> preferred.indexOfFirst { id.startsWith(it) } }
                    AlertDialog.Builder(this)
                        .setTitle("Choose a model")
                        .setItems(models.toTypedArray()) { _, which -> target.setText(models[which]) }
                        .setNegativeButton("Cancel", null)
                        .show()
                }.onFailure {
                    Toast.makeText(this, "Couldn't load models: ${it.message}", Toast.LENGTH_LONG).show()
                }
            }
        }.start()
    }

    private fun mark(ok: Boolean) = if (ok) "✅" else "❌"

    private fun heading(text: String, size: Float = 18f) = TextView(this).apply {
        this.text = text
        textSize = size
        setTypeface(typeface, Typeface.BOLD)
        setPadding(0, (16 * resources.displayMetrics.density).toInt(), 0, 8)
    }

    private fun button(text: String, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        isAllCaps = false
        setOnClickListener { onClick() }
    }

    private fun toggle(text: String, key: String, default: Boolean): View = Switch(this).apply {
        this.text = text
        isChecked = Prefs.get(this@MainActivity, key, default)
        setOnCheckedChangeListener { _, checked -> Prefs.set(this@MainActivity, key, checked) }
        setPadding(0, 12, 0, 12)
    }
}
