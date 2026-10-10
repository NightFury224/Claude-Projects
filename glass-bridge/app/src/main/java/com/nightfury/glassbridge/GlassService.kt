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
import android.view.WindowManager
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
    private var flowCommand: String? = null
    private val trace = ArrayList<String>()
    private var flowStartedAt = 0L
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
            when {
                command == Commands.IMPORT -> queuedImport = true
                flowCommand == Commands.IMPORT -> Notifier.importing(this,
                    "Glasses are on Wi-Fi for the import. Try again after ✅ Import finished.")
                else -> Notifier.status(this, "⏳ Busy", "Still finishing the last command, try again in a moment")
            }
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
                val (x, y) = if (command == Commands.VIDEO) 0.26f to 0.458f else 0.785f to 0.458f
                steps += Step("open the Homepage tab", delayMs = 600) { press("Homepage", 0.125f, 0.925f) }
                steps += Step("press $label", delayMs = 1_000) {
                    press(label, x, y).also { if (it) awaitingAck = true }
                }
                steps += Step("hear back from the glasses", timeoutMs = 7_000) { !awaitingAck }
                steps += Step("go back", delayMs = 1_500) { performGlobalAction(GLOBAL_ACTION_HOME) }
            }
            Commands.IMPORT -> {
                var startedAt = 0L
                var sawImporting = false
                steps += Step("open the Photo album tab", delayMs = 600) { press("Photo album", 0.624f, 0.925f) }
                steps += Step("press Import", delayMs = 1_500, timeoutMs = 8_000) { press("Import", 0.82f, 0.156f) }
                var lastStatus: String? = null
                // RDGlass must stay open while it imports; the glasses are on Wi-Fi (no Bluetooth) meanwhile.
                steps += Step("import the files", delayMs = 1_000, timeoutMs = 20 * 60_000L, pollMs = 1_000) {
                    val now = SystemClock.uptimeMillis()
                    if (startedAt == 0L) startedAt = now
                    val inFront = rootInActiveWindow?.packageName?.toString() == rd
                    val status = if (inFront) importStatus() else null
                    if (!inFront) {
                        // Someone switched away; bring RDGlass back so the import keeps going.
                        trace("RDGlass left the screen during import, reopening it")
                        launch(rd)
                    } else if (status != null) {
                        sawImporting = true
                        if (status != lastStatus) {
                            lastStatus = status
                            trace("Import status: $status")
                            Notifier.importing(this, status)
                        }
                    }
                    inFront && ((sawImporting && status == null) || (!sawImporting && now - startedAt > 10_000))
                }
                steps += Step("finish", delayMs = 1_500) {
                    Notifier.status(this,
                        if (sawImporting) "✅ Import finished" else "ℹ️ Nothing to import",
                        "Glasses are ready again")
                    performGlobalAction(GLOBAL_ACTION_HOME)
                }
            }
            else -> return
        }
        trace.clear()
        flowStartedAt = SystemClock.uptimeMillis()
        trace("Command: ${command.substringAfterLast('.')}, RDGlass package: $rd")
        flowCommand = command
        Flow(steps).also { flow = it }.start()
    }

    private fun onFlowEnded() {
        flow = null
        flowCommand = null
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
                trace("Done")
                Prefs.setString(this@GlassService, Prefs.SCREEN_REPORT, screenReport())
                onFlowEnded()
                return
            }
            handler.postDelayed({
                stepStartedAt = SystemClock.uptimeMillis()
                trace("Step: ${steps[index].desc}")
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
            trace("FAILED: ${step.desc}")
            Prefs.setString(this@GlassService, Prefs.SCREEN_REPORT, screenReport())
            if (awaitingAck) {
                awaitingAck = false
                Notifier.status(this@GlassService, "⚠️ Glasses didn't respond",
                    "Check that the glasses are on and connected, then try again")
            } else {
                Notifier.status(this@GlassService, "⚠️ Couldn't ${step.desc}",
                    "Open Glass Bridge → Copy screen report, and send it to Claude")
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
            node.contentDescription?.let { out.add(it.toString()) }
            for (i in 0 until node.childCount) node.getChild(i)?.let { queue.addLast(it) }
        }
    }

    /**
     * While RDGlass imports, its Import button reads "Importing" and a status line such as
     * "Connecting to Wi-Fi, please wait..." appears. Returns that status, or null when idle.
     */
    private fun importStatus(): String? {
        var importing = false
        var status: String? = null
        forEachNode { node ->
            for (raw in listOf(node.text, node.contentDescription)) {
                val value = raw?.toString()?.trim() ?: continue
                val lower = value.lowercase()
                if (lower.contains("importing")) importing = true
                if (lower.contains("wi-fi") || lower.contains("wifi") || lower.contains("%") ||
                    (lower.contains("import") && lower.contains("/"))
                ) status = value
            }
            false
        }
        if (!importing) return null
        return status ?: "Importing…"
    }

    /** True if [raw] (a view's text or description) is [label], ignoring case and extra parts like "Tab 1 of 4". */
    private fun matches(raw: CharSequence?, label: String): Boolean {
        if (raw == null) return false
        val wanted = label.lowercase()
        return raw.toString().lowercase().split('\n', ',', '|').any { it.trim() == wanted }
    }

    private fun findExact(label: String): AccessibilityNodeInfo? {
        var match: AccessibilityNodeInfo? = null
        forEachNode { node ->
            if ((matches(node.text, label) || matches(node.contentDescription, label)) && node.isVisibleToUser) {
                match = node
            }
            match != null
        }
        return match
    }

    private val pressStartedAt = HashMap<String, Long>()

    /**
     * Presses the button labelled [label]. If RDGlass doesn't expose that label, falls back after
     * a couple of seconds to tapping where the button sits on screen ([fx], [fy] as screen fractions).
     */
    private fun press(label: String, fx: Float, fy: Float): Boolean {
        val rd = rdPackage ?: return false
        val front = rootInActiveWindow?.packageName?.toString()
        if (front != rd) {
            trace("RDGlass not in front (front: $front), reopening it")
            launch(rd)
            return false
        }
        if (click(label)) {
            trace("Pressed '$label' by its label")
            pressStartedAt.remove(label)
            return true
        }
        val now = SystemClock.uptimeMillis()
        val started = pressStartedAt.getOrPut(label) { now }
        if (now - started < 2_500) return false
        pressStartedAt.remove(label)
        Log.i(TAG, "'$label' not found, tapping its usual position")
        trace("'$label' not found by label, tapping its usual position")
        return tapAt(fx, fy)
    }

    private fun trace(message: String) {
        val seconds = (SystemClock.uptimeMillis() - flowStartedAt) / 1000.0
        val line = "+%.1fs  %s".format(seconds, message)
        Log.i(TAG, line)
        if (trace.size < 60) trace += line
    }

    private fun tapAt(fx: Float, fy: Float): Boolean {
        val (width, height) = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            val bounds = getSystemService(WindowManager::class.java).currentWindowMetrics.bounds
            bounds.width() to bounds.height()
        } else {
            resources.displayMetrics.widthPixels to resources.displayMetrics.heightPixels
        }
        return tapPoint(width * fx, height * fy)
    }

    private fun tapPoint(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val gesture = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, 60))
            .build()
        return dispatchGesture(gesture, null, null)
    }

    /** Lists what RDGlass shows to accessibility, so a failed step can be diagnosed. */
    private fun screenReport(): String {
        val out = StringBuilder()
        val version = runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull()
        out.append("Glass Bridge report (v").append(version).append(")\n\n")
        trace.forEach { out.append(it).append('\n') }
        out.append("\nFront app: ").append(rootInActiveWindow?.packageName).append('\n')
        out.append("Windows: ").append(windows.joinToString { "${it.root?.packageName}(${it.type})" }).append("\n\n")
        val bounds = Rect()
        var count = 0
        forEachNode { node ->
            val text = node.text?.toString()?.replace('\n', ' ')
            val desc = node.contentDescription?.toString()?.replace('\n', ' ')
            if (!text.isNullOrBlank() || !desc.isNullOrBlank() || node.isClickable) {
                node.getBoundsInScreen(bounds)
                out.append(node.packageName?.toString()?.substringAfterLast('.')).append(": ")
                out.append(node.className?.toString()?.substringAfterLast('.') ?: "?")
                if (!text.isNullOrBlank()) out.append(" text=\"").append(text).append('"')
                if (!desc.isNullOrBlank()) out.append(" desc=\"").append(desc).append('"')
                if (node.isClickable) out.append(" [clickable]")
                out.append(" @").append(bounds.toShortString()).append('\n')
                count++
            }
            count > 120
        }
        return out.toString()
    }

    /** Clicks the view showing [label], or its nearest clickable parent; falls back to tapping its centre. */
    private fun click(label: String): Boolean {
        val node = findExact(label) ?: return false
        var current: AccessibilityNodeInfo? = node
        while (current != null) {
            if (current.isClickable && current.isEnabled &&
                current.performAction(AccessibilityNodeInfo.ACTION_CLICK)
            ) return true
            current = current.parent
        }
        val bounds = Rect().also { node.getBoundsInScreen(it) }
        if (bounds.isEmpty) return false
        return tapPoint(bounds.exactCenterX(), bounds.exactCenterY())
    }
}
