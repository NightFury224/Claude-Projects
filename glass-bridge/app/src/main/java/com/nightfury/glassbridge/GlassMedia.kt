package com.nightfury.glassbridge

import android.content.ContentUris
import android.content.Context
import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.MediaStore
import android.util.Base64
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.min

/** Finds photos/videos the glasses just imported, and turns them into images the AI can read. */
object GlassMedia {
    private const val MAX_SIDE = 1280

    /** Newest photo or video added to the gallery since [sinceMs] (wall-clock), or null. */
    fun newest(ctx: Context, video: Boolean, sinceMs: Long): Uri? {
        val collection = if (video) MediaStore.Video.Media.EXTERNAL_CONTENT_URI else MediaStore.Images.Media.EXTERNAL_CONTENT_URI
        val projection = arrayOf(MediaStore.MediaColumns._ID)
        val selection = "${MediaStore.MediaColumns.DATE_ADDED} >= ?"
        val args = arrayOf((sinceMs / 1000 - 5).toString())
        ctx.contentResolver.query(
            collection, projection, selection, args, "${MediaStore.MediaColumns.DATE_ADDED} DESC",
        )?.use { cursor ->
            if (cursor.moveToFirst()) return ContentUris.withAppendedId(collection, cursor.getLong(0))
        }
        return null
    }

    /** The photo, shrunk to at most 1280 px, as base64 JPEG. */
    fun photo(ctx: Context, uri: Uri): String {
        val source = ImageDecoder.createSource(ctx.contentResolver, uri)
        val bitmap = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
            val scale = min(1f, MAX_SIDE.toFloat() / max(info.size.width, info.size.height))
            decoder.setTargetSize((info.size.width * scale).toInt(), (info.size.height * scale).toInt())
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        }
        return encode(bitmap, 80)
    }

    /** [count] frames spread evenly through the video, as base64 JPEGs. */
    fun videoFrames(ctx: Context, uri: Uri, count: Int = 6): List<String> {
        val retriever = MediaMetadataRetriever()
        try {
            retriever.setDataSource(ctx, uri)
            val durationMs = retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            val frames = (0 until count).mapNotNull { i ->
                val timeUs = durationMs * 1000 * (2 * i + 1) / (2 * count)
                retriever.getScaledFrameAtTime(timeUs, MediaMetadataRetriever.OPTION_CLOSEST_SYNC, 768, 768)
                    ?.let { encode(it, 70) }
            }
            if (frames.isEmpty()) throw IllegalStateException("Couldn't read frames from the video")
            return frames
        } finally {
            retriever.release()
        }
    }

    private fun encode(bitmap: Bitmap, quality: Int): String {
        val out = ByteArrayOutputStream()
        bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
        bitmap.recycle()
        return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }
}
