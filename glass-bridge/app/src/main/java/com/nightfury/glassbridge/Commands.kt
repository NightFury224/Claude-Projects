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
    const val SCREEN_REPORT = "screen_report"
    const val AI_KEY = "ai_key"
    const val AI_MODEL = "ai_model"
    const val AI_MODE = "ai_mode"
    const val AI_MODEL_CACHE = "ai_model_cache"
    const val AI_MODEL_CACHE_TIME = "ai_model_cache_time"
    const val AI_CLIP_SECONDS = "ai_clip_seconds"

    fun get(ctx: Context, key: String, default: Boolean) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).getBoolean(key, default)

    fun set(ctx: Context, key: String, value: Boolean) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putBoolean(key, value).apply()

    fun getString(ctx: Context, key: String): String? =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).getString(key, null)

    fun setString(ctx: Context, key: String, value: String) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putString(key, value).apply()

    fun getInt(ctx: Context, key: String, default: Int) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).getInt(key, default)

    fun setInt(ctx: Context, key: String, value: Int) =
        ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE).edit().putInt(key, value).apply()
}
