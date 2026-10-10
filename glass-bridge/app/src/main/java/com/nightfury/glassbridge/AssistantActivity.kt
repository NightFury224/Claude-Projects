package com.nightfury.glassbridge

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.ToneGenerator
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** The assistant's modes. Each is its own tile / button. */
enum class AiMode(val title: String, val prompt: String) {
    ASK("🎙 Ask", "🎙 Listening…"),
    CHAT("💬 Chat", "🎙 Listening… (say \"stop\" to end)"),
    LOOK("👁 Look", "🎙 What do you want to know about what you see? (or stay quiet)"),
    VIDEO("🎥 Video", "🎙 What should I look for in the clip? (or stay quiet)");

    fun intent(ctx: Context): Intent = Intent(ctx, AssistantActivity::class.java)
        .putExtra(AssistantActivity.EXTRA_MODE, name)
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
}

/**
 * Voice assistant: listens through the glasses' microphone, optionally takes a photo or a short
 * clip with the glasses, asks the AI (via OpenRouter), then speaks the answer through the glasses
 * and/or shows it on the watch. Works over the lock screen.
 */
class AssistantActivity : Activity() {

    companion object {
        const val EXTRA_MODE = "mode"
        private const val EXTRA_RESUME = "resume"
        private const val REQUEST_MIC = 1
        private const val REQUEST_MEDIA = 3
        private val STOP_WORDS = setOf(
            "stop", "bye", "goodbye", "good bye", "bye bye", "end chat", "end", "exit", "that's all",
            "that is all", "thanks bye", "thank you bye", "stop chat",
        )

        fun mediaPermissions(): Array<String> =
            if (Build.VERSION.SDK_INT >= 33) arrayOf(Manifest.permission.READ_MEDIA_IMAGES, Manifest.permission.READ_MEDIA_VIDEO)
            else arrayOf(Manifest.permission.READ_EXTERNAL_STORAGE)
    }

    private val handler = Handler(Looper.getMainLooper())
    private val audio by lazy { getSystemService(AudioManager::class.java) }
    private lateinit var statusView: TextView
    private lateinit var transcriptView: TextView
    private val transcript = StringBuilder()

    private var mode = AiMode.ASK
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pendingSpeech: (() -> Unit)? = null
    private var headsetMic = false
    private var pendingCaptureQuestion: String? = null
    private val closeRunnable = Runnable { finish() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        Notifier.createChannel(this)
        buildUi()
        tts = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) pendingSpeech?.invoke()
            pendingSpeech = null
        }
        begin(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Brought back after the glasses finished a capture: carry on where we were.
        if (intent.getBooleanExtra(EXTRA_RESUME, false)) return
        begin(intent)
    }

    private fun begin(intent: Intent) {
        mode = runCatching { AiMode.valueOf(intent.getStringExtra(EXTRA_MODE) ?: "") }.getOrDefault(AiMode.ASK)
        handler.removeCallbacksAndMessages(null)
        tts?.stop()
        recognizer?.cancel()
        releaseHeadsetMic()
        transcript.clear()
        transcriptView.text = ""
        title = mode.title
        if (Prefs.getString(this, Prefs.AI_KEY).isNullOrBlank()) {
            statusView.text = "🔑 Add your OpenRouter API key to start"
            Dialogs.askForKey(this) {
                if (!Prefs.getString(this, Prefs.AI_KEY).isNullOrBlank()) begin(mode.intent(this))
            }
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQUEST_MIC)
        } else {
            listen()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        val granted = grantResults.isNotEmpty() && grantResults.all { it == PackageManager.PERMISSION_GRANTED }
        when (requestCode) {
            REQUEST_MIC -> if (granted) listen() else statusView.text = "⚠️ Microphone permission is needed"
            REQUEST_MEDIA -> {
                val question = pendingCaptureQuestion ?: return
                pendingCaptureQuestion = null
                if (granted) capture(question)
                else statusView.text = "⚠️ Photos & videos permission is needed to read what the glasses captured"
            }
        }
    }

    private fun buildUi() {
        val pad = (20 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        statusView = TextView(this).apply { textSize = 22f; setTypeface(typeface, Typeface.BOLD) }
        transcriptView = TextView(this).apply { textSize = 18f; setPadding(0, pad, 0, pad) }
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        buttons.addView(Button(this).apply {
            text = "🎙 Again"; isAllCaps = false
            setOnClickListener { begin(mode.intent(this@AssistantActivity)) }
        })
        buttons.addView(Button(this).apply { text = "✕ Close"; isAllCaps = false; setOnClickListener { finish() } })
        column.addView(statusView)
        column.addView(buttons)
        column.addView(transcriptView)
        setContentView(ScrollView(this).apply { addView(column) })
    }

    private fun addLine(line: String) {
        transcript.append(line).append("\n\n")
        transcriptView.text = transcript
    }

    // ---- Listening ----

    private fun listen() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            statusView.text = "⚠️ No speech recognition on this phone. Install or enable the Google app."
            return
        }
        statusView.text = mode.prompt
        val alreadyOn = headsetMic
        useHeadsetMic()
        // Give the Bluetooth headset link a moment to open before we beep and listen.
        handler.postDelayed({
            beep()
            val recognizer = recognizer ?: SpeechRecognizer.createSpeechRecognizer(this).also {
                it.setRecognitionListener(listener)
                recognizer = it
            }
            recognizer.startListening(
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
                    .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                    .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
                    .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1),
            )
        }, if (headsetMic && !alreadyOn) 800 else 200)
    }

    private val listener = object : RecognitionListener {
        override fun onPartialResults(partialResults: Bundle) {
            partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                ?.let { statusView.text = "🎙 “$it”" }
        }

        override fun onResults(results: Bundle) {
            heard(results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim().orEmpty())
        }

        override fun onError(error: Int) {
            when (error) {
                SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> heard("")
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> {
                    releaseHeadsetMic()
                    statusView.text = "⚠️ Microphone permission is needed"
                }
                else -> {
                    releaseHeadsetMic()
                    statusView.text = "⚠️ Speech recognition error ($error). Tap Again."
                }
            }
        }

        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() {}
        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    private fun heard(text: String) {
        // In chat mode the headset mic stays open between turns so replies are instant.
        if (mode != AiMode.CHAT) releaseHeadsetMic()
        when (mode) {
            AiMode.ASK -> if (text.isEmpty()) notHeard() else ask(text)
            AiMode.CHAT -> {
                val normalized = text.lowercase().trim(' ', '.', '!', ',', '?')
                if (text.isEmpty() || normalized in STOP_WORDS) endChat() else ask(text)
            }
            AiMode.LOOK -> capture(text.ifEmpty { "What am I looking at? Describe it briefly." })
            AiMode.VIDEO -> capture(text.ifEmpty { "What happened in this clip? Describe it briefly." })
        }
    }

    private fun notHeard() {
        statusView.text = "🤷 Didn't catch that. Tap Again."
        handler.postDelayed(closeRunnable, 8_000)
    }

    private fun endChat() {
        releaseHeadsetMic()
        statusView.text = "💬 Chat ended"
        handler.postDelayed(closeRunnable, 3_000)
    }

    // ---- Glasses camera ----

    private fun capture(question: String) {
        addLine("You: $question")
        if (mediaPermissions().any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            pendingCaptureQuestion = question
            requestPermissions(mediaPermissions(), REQUEST_MEDIA)
            return
        }
        val service = GlassService.instance
        if (service == null) {
            failed(question, "Glass Bridge's accessibility service is off")
            return
        }
        val video = mode == AiMode.VIDEO
        val seconds = Prefs.getInt(this, Prefs.AI_CLIP_SECONDS, 10)
        statusView.text = if (video) "🎥 Recording $seconds seconds, then importing…" else "📸 Taking a photo, then importing…"
        service.captureForAi(video, seconds) { result ->
            // The glasses app was on screen; bring this screen back.
            startActivity(Intent(this, AssistantActivity::class.java)
                .putExtra(EXTRA_RESUME, true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT))
            result.onSuccess { uri -> look(question, uri, video) }
                .onFailure { failed(question, it.message ?: "Capture failed") }
        }
    }

    private fun look(question: String, uri: Uri, video: Boolean) {
        statusView.text = "🔍 Looking…"
        Thread {
            val result = runCatching {
                val images = if (video) GlassMedia.videoFrames(this, uri) else listOf(GlassMedia.photo(this, uri))
                AiClient.ask(applicationContext, question, images, video)
            }
            runOnUiThread { if (!isDestroyed) deliver(question, result, logged = true) }
        }.start()
    }

    // ---- Asking and answering ----

    private fun ask(question: String) {
        addLine("You: $question")
        statusView.text = "💭 Thinking…"
        Thread {
            val result = runCatching { AiClient.ask(applicationContext, question) }
            runOnUiThread { if (!isDestroyed) deliver(question, result, logged = true) }
        }.start()
    }

    private fun failed(question: String, message: String) =
        deliver(question, Result.failure(Exception(message)), logged = true)

    private fun deliver(question: String, result: Result<String>, logged: Boolean) {
        if (!logged) addLine("You: $question")
        val output = AnswerMode.current(this)
        val answer = result.getOrNull()
        val text = answer ?: ("⚠️ " + (result.exceptionOrNull()?.message ?: "Couldn't get an answer"))
        addLine("AI: $text")
        statusView.text = if (answer != null) "🤖 " + output.label else "⚠️ Couldn't get an answer"
        if (output.watch) Notifier.answer(this, question, text)

        val spoken = answer ?: "Sorry, I couldn't get an answer."
        val next: () -> Unit = if (mode == AiMode.CHAT && answer != null) ({ listen() }) else ({
            releaseHeadsetMic()
            handler.postDelayed(closeRunnable, 5_000)
        })
        when {
            !output.speak -> next()
            mode == AiMode.CHAT && headsetMic -> speak(spoken, overCallLink = true, then = next)
            // After a photo/video import the glasses reconnect Bluetooth; wait for them before speaking.
            mode == AiMode.LOOK || mode == AiMode.VIDEO -> whenGlassesAudioBack { speak(spoken, false, next) }
            else -> handler.postDelayed({ speak(spoken, false, next) }, 600)
        }
    }

    private fun speak(text: String, overCallLink: Boolean, then: () -> Unit) {
        val engine = tts
        if (engine == null || !ttsReady) {
            pendingSpeech = { speak(text, overCallLink, then) }
            return
        }
        // Over the headset "call" link in chat mode (no switching delay), otherwise as normal media audio.
        engine.setAudioAttributes(
            AudioAttributes.Builder()
                .setUsage(if (overCallLink) AudioAttributes.USAGE_VOICE_COMMUNICATION else AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build(),
        )
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { handler.post { then() } }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) { handler.post { then() } }
        })
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "answer")
    }

    /** Runs [action] once the glasses' Bluetooth audio is connected again (or after 25 s). */
    private fun whenGlassesAudioBack(action: () -> Unit) {
        val deadline = SystemClock.uptimeMillis() + 25_000
        fun check() {
            val back = audio.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any {
                it.type == AudioDeviceInfo.TYPE_BLUETOOTH_A2DP || it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO
            }
            if (back || SystemClock.uptimeMillis() > deadline) {
                handler.postDelayed({ action() }, if (back) 1_000L else 0L)
            } else {
                statusView.text = "🔊 Waiting for the glasses to reconnect…"
                handler.postDelayed({ check() }, 1_000)
            }
        }
        check()
    }

    // ---- Headset microphone ----

    /** Routes the microphone to the glasses (Bluetooth headset) when they're connected. */
    private fun useHeadsetMic() {
        if (headsetMic || Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        val glasses = audio.availableCommunicationDevices.firstOrNull { it.type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO }
            ?: return
        audio.mode = AudioManager.MODE_IN_COMMUNICATION
        headsetMic = audio.setCommunicationDevice(glasses)
        if (!headsetMic) audio.mode = AudioManager.MODE_NORMAL
    }

    private fun releaseHeadsetMic() {
        if (!headsetMic || Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
        audio.clearCommunicationDevice()
        audio.mode = AudioManager.MODE_NORMAL
        headsetMic = false
    }

    private fun beep() {
        val stream = if (headsetMic) AudioManager.STREAM_VOICE_CALL else AudioManager.STREAM_MUSIC
        runCatching {
            val tone = ToneGenerator(stream, 80)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
            handler.postDelayed({ tone.release() }, 400)
        }
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        recognizer?.destroy()
        tts?.shutdown()
        releaseHeadsetMic()
        super.onDestroy()
    }
}

/** Where answers go: spoken through the glasses, shown on the watch, or both. */
enum class AnswerMode(val label: String, val speak: Boolean, val watch: Boolean) {
    SPEAK("Speaking the answer", true, false),
    WATCH("Answer sent to your watch", false, true),
    BOTH("Speaking + sent to your watch", true, true);

    val shortName get() = when (this) { SPEAK -> "🔊 Speak"; WATCH -> "⌚ Watch"; BOTH -> "🔊+⌚ Both" }

    fun next() = values()[(ordinal + 1) % values().size]

    companion object {
        fun current(ctx: Context) =
            runCatching { valueOf(Prefs.getString(ctx, Prefs.AI_MODE) ?: "") }.getOrDefault(SPEAK)

        fun set(ctx: Context, mode: AnswerMode) = Prefs.setString(ctx, Prefs.AI_MODE, mode.name)
    }
}
