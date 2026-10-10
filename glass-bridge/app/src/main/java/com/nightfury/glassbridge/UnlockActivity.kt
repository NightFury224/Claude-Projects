package com.nightfury.glassbridge

import android.app.Activity
import android.app.KeyguardManager
import android.os.Bundle

/** Invisible screen that wakes the phone and dismisses the lock screen (no PIN needed with Smart Lock). */
class UnlockActivity : Activity() {
    private var reported = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)
        val keyguard = getSystemService(KeyguardManager::class.java)
        if (!keyguard.isKeyguardLocked) {
            done(true)
            return
        }
        keyguard.requestDismissKeyguard(this, object : KeyguardManager.KeyguardDismissCallback() {
            override fun onDismissSucceeded() = done(true)
            override fun onDismissCancelled() = done(false)
            override fun onDismissError() = done(false)
        })
    }

    private fun done(unlocked: Boolean) {
        if (reported) return
        reported = true
        GlassService.instance?.onUnlockResult(unlocked)
        finish()
    }
}
