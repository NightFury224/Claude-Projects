package com.nightfury.glassbridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView

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

        column.addView(heading("Test"))
        column.addView(button("🎥 Start / stop video") { Commands.run(this, Commands.VIDEO) })
        column.addView(button("📸 Take photo") { Commands.run(this, Commands.PHOTO) })
        column.addView(button("⬇️ Import now") { Commands.run(this, Commands.IMPORT) })
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
        ).joinToString("\n")
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
