package com.nightfury.glassbridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

object Commands {
    const val VIDEO = "com.nightfury.glassbridge.VIDEO"
    const val PHOTO = "com.nightfury.glassbridge.PHOTO"
    const val IMPORT = "com.nightfury.glassbridge.IMPORT"

    /** Single entry point used by tiles, notification buttons, remotes and the main screen. */
    fun run(ctx: Context, command: String) {
        val service = GlassService.instance
        if (service == null) {
            Notifier.status(ctx, "⚠️ Glass Bridge is off",
                "Open the Glass Bridge app and turn on its accessibility service")
            return
        }
        service.handleCommand(command)
    }
}

/** Receives taps on notification buttons (also works from the watch). Not exported. */
class CommandReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        intent.action?.let { Commands.run(context, it) }
    }
}

object Prefs {
    private const val FILE = "glass_bridge"
    const val AUTO_IMPORT = "auto_import"
    const val REMOTE_KEYS = "remote_keys"

    fun get(ctx: Context, key: String, default: Boolean) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).getBoolean(key, default)

    fun set(ctx: Context, key: String, value: Boolean) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putBoolean(key, value).apply()
}
