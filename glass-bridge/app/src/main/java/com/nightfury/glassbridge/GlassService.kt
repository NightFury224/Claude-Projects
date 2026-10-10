package com.nightfury.glassbridge

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.os.SystemClock
import android.service.quicksettings.TileService
import android.util.Log
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo

/**
 * Drives the RDGlass app: taps its buttons for us and watches its pop-up messages
 * to learn whether the glasses really started/stopped recording or took a photo.
 */
class GlassService : AccessibilityService() {

    companion object {
        private const val TAG = "GlassBridge"

        @Volatile
        var instance: GlassService? = null
            private set

        @Volatile
        var recording = false
            private set

        /** Package name of the RDGlass app, found by its launcher label. */
        fun findRdGlass(ctx: Context): String? {
            val launcher = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            return ctx.packageManager.queryIntentActivities(launcher, 0).firstOrNull { info ->
                val label = info.loadLabel(ctx.packageManager).toString().replace(" ", "").lowercase()
                label.contains("rdglass") || info.activityInfo.packageName.lowercase().contains("rdglass")
            }?.activityInfo?.packageName
        }
    }

    /** Pop-ups RDGlass shows, matched by a short lowercase fragment of their text. */
    private enum class Popup(val needle: String) {
        STARTED("start recording"),
        FINISHED("finished recording"),
        PHOTO("taking pictures"),
        BUSY("recording in progress"),
    }

    private class Step(
        val desc: String,
        val delayMs: Long = 0,
        val timeoutMs: Long = 6_000,
        val pollMs: Long = 400,
        val action: () -> Boolean,
    )

    private val handler = Handler(Looper.getMainLooper())
    private var rdPackage: String? = null
    private var flow: Flow? = null
    private var queuedImport = false
    private var unlockThen: String? = null
    private var awaitingAck = false
    private var lastRemoteAt = 0L
    private val lastPopupAt = HashMap<Popup, Long>()
    private var scanScheduled = false

    private val scanRunnable = Runnable {
        scanScheduled = false
        val texts = ArrayList<String>()
        rdRoots().forEach { collectTexts(it, texts) }
        matchPopups(texts)
    }
    private val importRunnable = Runnable { if (!recording) handleCommand(Commands.IMPORT) }
    private val unlockTimeout = Runnable { onUnlockResult(false) }

    override fun onServiceConnected() {
        instance = this
        Notifier.createChannel(this)
        rdPackage = findRdGlass(this)
    }

    override fun onUnbind(intent: Intent?): Boolean {
        instance = null
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        instance = null
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    override fun onInterrupt() {}

    // ---- Watching RDGlass pop-ups ----

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        val rd = rdPackage ?: findRdGlass(this).also { rdPackage = it } ?: return
        if (event.packageName?.toString() != rd) return

        // Toasts carry their text on the event itself.
        val texts = event.text.mapNotNull { it?.toString() }
        if (texts.isNotEmpty()) matchPopups(texts)

        // In-app pop-ups: rescan the screen shortly after it changes (coalesced).
        if (!scanScheduled) {
            scanScheduled = true
            handler.postDelayed(scanRunnable, 150)
        }
    }

    private fun matchPopups(texts: List<String>) {
        val now = SystemClock.uptimeMillis()
        for (text in texts) {
            val lower = text.lowercase()
            for (popup in Popup.values()) {
                if (!lower.contains(popup.needle)) continue
                // The same pop-up stays on screen for a couple of seconds; handle it once.
                if (now - (lastPopupAt[popup] ?: 0L) < 3_000) continue
                lastPopupAt[popup] = now
                onPopup(popup)
            }
        }
    }

    private fun onPopup(popup: Popup) {
        Log.i(TAG, "Pop-up: $popup")
        awaitingAck = false
        val autoImport = Prefs.get(this, Prefs.AUTO_IMPORT, true)
        when (popup) {
            Popup.STARTED -> {
                recording = true
                Notifier.recording(this)
            }
            Popup.FINISHED -> {
                recording = false
                Notifier.stoppedRecording(this)
                Notifier.status(this, "✅ Video saved",
                    if (autoImport) "Importing to your phone…" else "Tap Import to copy it to your phone")
                scheduleImport()
            }
            Popup.PHOTO -> {
                Notifier.status(this, "📸 Photo taken", if (autoImport) "Importing to your phone…" else "")
                scheduleImport()
            }
            Popup.BUSY -> {
                recording = true
                Notifier.status(this, "⚠️ Still recording", "Stop the video first")
            }
        }
        TileService.requestListeningState(this, ComponentName(this, VideoTile::class.java))
    }

    /** Waits a few seconds so several photos in a row are imported in one go. */
    private fun scheduleImport() {
        if (!Prefs.get(this, Prefs.AUTO_IMPORT, true)) return
        handler.removeCallbacks(importRunnable)
        handler.postDelayed(importRunnable, 6_000)
    }

    // ---- Bluetooth remote buttons ----

    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (!Prefs.get(this, Prefs.REMOTE_KEYS, false)) return false
        // Only keys from external devices (selfie remotes), never the phone's own volume buttons.
        val device = event.device ?: return false
        if (!device.isExternal) return false
        val command = when (event.keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP -> Commands.VIDEO
            KeyEvent.KEYCODE_VOLUME_DOWN, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_CAMERA -> Commands.PHOTO
            else -> return false
        }
        if (event.action == KeyEvent.ACTION_UP) {
            // Many remotes send two keys per press; treat them as one.
            val now = SystemClock.uptimeMillis()
            if (now - lastRemoteAt > 1_500) {
                lastRemoteAt = now
                handleCommand(command)
            }
        }
        return true
    }

    // ---- Commands ----

    fun handleCommand(command: String) {
        if (flow != null) {
            if (command == Commands.IMPORT) queuedImport = true
            else Notifier.status(this, "⏳ Busy", "Still finishing the last command, try again in a moment")
            return
        }
        val power = getSystemService(PowerManager::class.java)
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (!power.isInteractive || keyguard.isKeyguardLocked) {
            // Taps only work on an unlocked screen. With Smart Lock this needs no PIN.
            unlockThen = command
            handler.postDelayed(unlockTimeout, 20_000)
            startActivity(Intent(this, UnlockActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            return
        }
        startFlow(command)
    }

    fun onUnlockResult(unlocked: Boolean) {
        handler.removeCallbacks(unlockTimeout)
        val command = unlockThen ?: return
        unlockThen = null
        if (unlocked) {
            handler.postDelayed({ startFlow(command) }, 400)
        } else {
            Notifier.status(this, "🔒 Unlock your phone",
                "The phone must be unlocked to control the glasses. Add the glasses as a Smart Lock trusted device.")
        }
    }

    private fun startFlow(command: String) {
        val rd = rdPackage ?: findRdGlass(this).also { rdPackage = it }
        if (rd == null) {
            Notifier.status(this, "⚠️ RDGlass app not found", "Install RDGlass, then try again")
            return
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            performGlobalAction(GLOBAL_ACTION_DISMISS_NOTIFICATION_SHADE)
        }

        val steps = mutableListOf(
            Step("open RDGlass") { launch(rd) },
            Step("wait for RDGlass", timeoutMs = 10_000) { rootInActiveWindow?.packageName?.toString() == rd },
        )
        when (command) {
            Commands.VIDEO, Commands.PHOTO -> {
                val label = if (command == Commands.VIDEO) "Video" else "Take photo"
                steps += Step("open the Homepage tab", delayMs = 600) { click("Homepage") }
                steps += Step("press $label", delayMs = 800) {
                    click(label).also { if (it) awaitingAck = true }
                }
                steps += Step("hear back from the glasses", timeoutMs = 7_000) { !awaitingAck }
                steps += Step("go back", delayMs = 1_500) { performGlobalAction(GLOBAL_ACTION_HOME) }
            }
            Commands.IMPORT -> {
                var startedAt = 0L
                var sawImporting = false
                steps += Step("open the Photo album tab", delayMs = 600) { click("Photo album") }
                steps += Step("press Import", delayMs = 1_200, timeoutMs = 8_000) { click("Import") }
                steps += Step("import the files", delayMs = 1_500, timeoutMs = 15 * 60_000L, pollMs = 1_000) {
                    val now = SystemClock.uptimeMillis()
                    if (startedAt == 0L) startedAt = now
                    val busy = screenContains("importing")
                    if (busy) sawImporting = true
                    (sawImporting && !busy) || (!sawImporting && now - startedAt > 8_000)
                }
                steps += Step("finish") {
                    Notifier.status(this, "✅ Import finished", "Saved to your phone")
                    performGlobalAction(GLOBAL_ACTION_HOME)
                }
            }
            else -> return
        }
        Flow(steps).also { flow = it }.start()
    }

    private fun onFlowEnded() {
        flow = null
        if (queuedImport) {
            queuedImport = false
            handler.postDelayed(importRunnable, 1_000)
        }
    }

    private inner class Flow(private val steps: List<Step>) {
        private var index = 0
        private var stepStartedAt = 0L

        fun start() = next()

        private fun next() {
            if (index >= steps.size) {
                onFlowEnded()
                return
            }
            handler.postDelayed({
                stepStartedAt = SystemClock.uptimeMillis()
                attempt()
            }, steps[index].delayMs)
        }

        private fun attempt() {
            if (flow !== this) return
            val step = steps[index]
            val done = try {
                step.action()
            } catch (e: Exception) {
                Log.w(TAG, "Step '${step.desc}' threw", e)
                false
            }
            when {
                done -> {
                    index++
                    next()
                }
                SystemClock.uptimeMillis() - stepStartedAt >= step.timeoutMs -> fail(step)
                else -> handler.postDelayed({ attempt() }, step.pollMs)
            }
        }

        private fun fail(step: Step) {
            Log.w(TAG, "Failed to ${step.desc}")
            if (awaitingAck) {
                awaitingAck = false
                Notifier.status(this@GlassService, "⚠️ Glasses didn't respond",
                    "Check that the glasses are on and connected, then try again")
            } else {
                Notifier.status(this@GlassService, "⚠️ Couldn't ${step.desc}",
                    "Open RDGlass and check what's on screen")
            }
            performGlobalAction(GLOBAL_ACTION_HOME)
            onFlowEnded()
        }
    }

    // ---- Screen helpers ----

    private fun launch(pkg: String): Boolean {
        val intent = packageManager.getLaunchIntentForPackage(pkg) ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        startActivity(intent)
        return true
    }

    private fun rdRoots(): List<AccessibilityNodeInfo> {
        val rd = rdPackage
        val roots = windows.mapNotNull { it.root }.filter { rd == null || it.packageName?.toString() == rd }
        return roots.ifEmpty { listOfNotNull(rootInActiveWindow) }
    }

    /** Breadth-first walk over RDGlass's on-screen views. */
    private inline fun forEachNode(block: (AccessibilityNodeInfo) -> Boolean) {
        val queue = ArrayDeque(rdRoots())
        var budget = 1_500
        while (queue.isNotEmpty() && budget-- > 0) {
            val node = queue.removeFirst()
            if (block(node)) return
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.addLast(it) }
        }
    }

    private fun collectTexts(root: AccessibilityNodeInfo, out: MutableList<String>) {
        val queue = ArrayDeque(listOf(root))
        var budget = 1_500
        while (queue.isNotEmpty() && budget-- > 0) {
            val node = queue.removeFirst()
            node.text?.let { out.add(it.toString()) }
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.addLast(it) }
        }
    }

    private fun screenContains(fragment: String): Boolean {
        var found = false
        forEachNode { node ->
            found = node.text?.toString()?.lowercase()?.contains(fragment) == true
            found
        }
        return found
    }

    private fun findExact(label: String): AccessibilityNodeInfo? {
        var match: AccessibilityNodeInfo? = null
        forEachNode { node ->
            val text = (node.text ?: node.contentDescription)?.toString()?.trim()
            if (text.equals(label, ignoreCase = true) && node.isVisibleToUser) match = node
            match != null
        }
        return match
    }

    /** Clicks the view showing [label], or its nearest clickable parent; falls back to a screen tap. */
    private fun click(label: String): Boolean {
        val node = findExact(label) ?: return false
        var current: AccessibilityNodeInfo? = node
        while (current != null) {
            if (current.isClickable && current.isEnabled) {
                return current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            }
            current = current.parent
        }
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        if (bounds.isEmpty) return false
        val path = Path().apply { moveTo(bounds.exactCenterX(), bounds.exactCenterY()) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 60))
            .build()
        return dispatchGesture(gesture, null, null)
    }
}
