package com.nightfury.glassbridge

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Typeface
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
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

/**
 * Voice assistant: listens through the glasses' microphone, asks the AI (via OpenRouter),
 * then speaks the answer through the glasses and/or shows it on the watch.
 * Works over the lock screen, so it can be started from the watch or a quick tile.
 */
class AssistantActivity : Activity() {

    private val handler = Handler(Looper.getMainLooper())
    private val audio by lazy { getSystemService(AudioManager::class.java) }
    private lateinit var statusView: TextView
    private lateinit var questionView: TextView
    private lateinit var answerView: TextView

    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private var pendingSpeech: String? = null
    private var headsetMic = false
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
            if (ttsReady) {
                tts?.setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build(),
                )
                pendingSpeech?.let { speak(it) }
            }
        }

        if (Prefs.getString(this, Prefs.AI_KEY).isNullOrBlank()) {
            statusView.text = "⚠️ Add your OpenRouter API key in the Glass Bridge app first"
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        } else {
            startListening()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        // Asked again (tile/watch) while this screen is open: start a new question.
        restart()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startListening()
        else statusView.text = "⚠️ Microphone permission is needed to hear your question"
    }

    private fun buildUi() {
        val pad = (20 * resources.displayMetrics.density).toInt()
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad * 2, pad, pad)
        }
        statusView = TextView(this).apply { textSize = 24f; setTypeface(typeface, Typeface.BOLD) }
        questionView = TextView(this).apply { textSize = 17f; setTypeface(typeface, Typeface.ITALIC); setPadding(0, pad, 0, pad) }
        answerView = TextView(this).apply { textSize = 19f }
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(0, pad, 0, 0) }
        buttons.addView(Button(this).apply { text = "🎙 Ask again"; isAllCaps = false; setOnClickListener { restart() } })
        buttons.addView(Button(this).apply { text = "✕ Close"; isAllCaps = false; setOnClickListener { finish() } })
        column.addView(statusView)
        column.addView(questionView)
        column.addView(answerView)
        column.addView(buttons)
        setContentView(ScrollView(this).apply { addView(column) })
    }

    private fun restart() {
        handler.removeCallbacks(closeRunnable)
        tts?.stop()
        recognizer?.cancel()
        releaseHeadsetMic()
        questionView.text = ""
        answerView.text = ""
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) startListening()
    }

    // ---- Listening ----

    private fun startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            statusView.text = "⚠️ No speech recognition on this phone. Install or enable the Google app."
            return
        }
        statusView.text = "🎙 Listening…"
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
        }, if (headsetMic) 800 else 150)
    }

    private val listener = object : RecognitionListener {
        override fun onPartialResults(partialResults: Bundle) {
            partialResults.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                ?.let { questionView.text = "“$it”" }
        }

        override fun onResults(results: Bundle) {
            releaseHeadsetMic()
            val question = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()?.trim()
            if (question.isNullOrEmpty()) {
                notHeard()
            } else {
                questionView.text = "“$question”"
                ask(question)
            }
        }

        override fun onError(error: Int) {
            releaseHeadsetMic()
            when (error) {
                SpeechRecognizer.ERROR_NO_MATCH, SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> notHeard()
                SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
                    statusView.text = "⚠️ Microphone permission is needed"
                else -> statusView.text = "⚠️ Speech recognition error ($error). Tap Ask again."
            }
        }

        override fun onReadyForSpeech(params: Bundle?) {}
        override fun onBeginningOfSpeech() {}
        override fun onRmsChanged(rmsdB: Float) {}
        override fun onBufferReceived(buffer: ByteArray?) {}
        override fun onEndOfSpeech() { statusView.text = "💭 Thinking…" }
        override fun onEvent(eventType: Int, params: Bundle?) {}
    }

    private fun notHeard() {
        statusView.text = "🤷 Didn't catch that. Tap Ask again."
        handler.postDelayed(closeRunnable, 8_000)
    }

    /** Routes the microphone to the glasses (Bluetooth headset) when they're connected. */
    private fun useHeadsetMic() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return
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

    // ---- Asking and answering ----

    private fun ask(question: String) {
        statusView.text = "💭 Thinking…"
        Thread {
            val result = runCatching { AiClient.ask(applicationContext, question) }
            runOnUiThread { if (!isDestroyed) deliver(question, result) }
        }.start()
    }

    private fun deliver(question: String, result: Result<String>) {
        val mode = AnswerMode.current(this)
        result.onSuccess { answer ->
            statusView.text = "🤖 " + mode.label
            answerView.text = answer
            if (mode.watch) Notifier.answer(this, question, answer)
            if (mode.speak) {
                // Let the Bluetooth link switch back from "call" to "media" audio first.
                handler.postDelayed({ speak(answer) }, 600)
            } else {
                handler.postDelayed(closeRunnable, 6_000)
            }
        }.onFailure { error ->
            statusView.text = "⚠️ Couldn't get an answer"
            answerView.text = error.message ?: error.toString()
            if (mode.watch) Notifier.answer(this, question, "⚠️ " + (error.message ?: "Couldn't get an answer"))
            if (mode.speak) handler.postDelayed({ speak("Sorry, I couldn't get an answer.") }, 600)
        }
    }

    private fun speak(text: String) {
        val engine = tts
        if (engine == null || !ttsReady) {
            pendingSpeech = text
            return
        }
        pendingSpeech = null
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {}
            override fun onDone(utteranceId: String?) { handler.postDelayed(closeRunnable, 4_000) }
            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) {}
        })
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "answer")
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
        fun current(ctx: android.content.Context) =
            runCatching { valueOf(Prefs.getString(ctx, Prefs.AI_MODE) ?: "") }.getOrDefault(SPEAK)

        fun set(ctx: android.content.Context, mode: AnswerMode) = Prefs.setString(ctx, Prefs.AI_MODE, mode.name)
    }
}
