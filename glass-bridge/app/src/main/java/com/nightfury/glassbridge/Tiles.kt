package com.nightfury.glassbridge

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
