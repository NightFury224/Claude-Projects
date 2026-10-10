package com.nightfury.glassbridge

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.drawable.Icon

/** Status notifications. They are not "ongoing", so Wear OS mirrors them (and their buttons) to the watch. */
object Notifier {
    private const val CHANNEL = "glasses_status"
    private const val ID_RECORDING = 1
    private const val ID_STATUS = 2

    fun createChannel(ctx: Context) {
        val channel = NotificationChannel(CHANNEL, "Glasses status", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Recording started/stopped, photo taken, import finished, errors"
            enableVibration(true)
        }
        ctx.getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    fun recording(ctx: Context) {
        post(ctx, ID_RECORDING, "🔴 Recording", "Tap Stop (here or on your watch) to end the video",
            action(ctx, "⏹ Stop", Commands.VIDEO))
        cancel(ctx, ID_STATUS)
    }

    fun stoppedRecording(ctx: Context) = cancel(ctx, ID_RECORDING)

    /** Shown while RDGlass imports. No buttons: the glasses can't take commands until it's done. */
    fun importing(ctx: Context, detail: String) {
        post(ctx, ID_STATUS, "⬇️ Importing, glasses busy", detail, timeoutMs = 20 * 60_000L, silent = true)
    }

    fun status(ctx: Context, title: String, text: String = "") {
        post(ctx, ID_STATUS, title, text,
            action(ctx, "🎥 Video", Commands.VIDEO),
            action(ctx, "📸 Photo", Commands.PHOTO),
            timeoutMs = 2 * 60_000L)
    }

    private fun post(
        ctx: Context, id: Int, title: String, text: String,
        vararg actions: Notification.Action, timeoutMs: Long = 0, silent: Boolean = false,
    ) {
        val builder = Notification.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_glasses)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setCategory(Notification.CATEGORY_STATUS)
        actions.forEach { builder.addAction(it) }
        if (timeoutMs > 0) builder.setTimeoutAfter(timeoutMs)
        if (silent) builder.setOnlyAlertOnce(true)
        try {
            ctx.getSystemService(NotificationManager::class.java).notify(id, builder.build())
        } catch (_: SecurityException) {
            // Notification permission not granted yet; MainActivity asks for it.
        }
    }

    private fun cancel(ctx: Context, id: Int) =
        ctx.getSystemService(NotificationManager::class.java).cancel(id)

    private fun action(ctx: Context, label: String, command: String): Notification.Action {
        val intent = Intent(ctx, CommandReceiver::class.java).setAction(command)
        val pending = PendingIntent.getBroadcast(
            ctx, command.hashCode(), intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return Notification.Action.Builder(Icon.createWithResource(ctx, R.drawable.ic_glasses), label, pending).build()
    }
}
