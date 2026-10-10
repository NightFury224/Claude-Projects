package com.nightfury.glassbridge

import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Quick Settings tiles: swipe down and tap to control the glasses. */
abstract class GlassTile(private val command: String) : TileService() {
    override fun onClick() {
        if (isLocked) unlockAndRun { Commands.run(this, command) } else Commands.run(this, command)
    }

    override fun onStartListening() {
        qsTile?.let {
            it.state = tileState()
            it.updateTile()
        }
    }

    protected open fun tileState() = Tile.STATE_INACTIVE
}

class VideoTile : GlassTile(Commands.VIDEO) {
    override fun tileState() = if (GlassService.recording) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
}

class PhotoTile : GlassTile(Commands.PHOTO)

class ImportTile : GlassTile(Commands.IMPORT)

/** Starts the voice assistant. */
class AskTile : TileService() {
    override fun onClick() {
        val intent = Intent(this, AssistantActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(
                PendingIntent.getActivity(this, 0, intent, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT),
            )
        } else {
            @Suppress("DEPRECATION")
            startActivityAndCollapse(intent)
        }
    }
}

/** Switches where AI answers go: spoken, watch, or both. */
class AiModeTile : TileService() {
    override fun onClick() {
        AnswerMode.set(this, AnswerMode.current(this).next())
        refresh()
    }

    override fun onStartListening() = refresh()

    private fun refresh() {
        qsTile?.let {
            it.label = "AI answers"
            it.subtitle = AnswerMode.current(this).shortName
            it.state = Tile.STATE_ACTIVE
            it.updateTile()
        }
    }
}
