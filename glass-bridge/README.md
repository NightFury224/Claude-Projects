# Glass Bridge

An Android app that runs the RDGlass app for you, so you never have to open it.

- **Start/stop video** and **take photos** from a Quick Settings tile, a notification button (which also appears on your smartwatch) or a cheap Bluetooth selfie remote.
- **It confirms the result:** it reads RDGlass's pop-ups ("start recording", "finished recording", "taking pictures", "Recording in progress") and shows you 🔴 Recording / ✅ Saved / 📸 Photo taken / ⚠️ didn't respond.
- **Auto-import:** after each video or photo, it opens RDGlass → Photo album → Import, waits for the import to finish, and goes back to the home screen.

Uploading to Google Drive is handled by FolderSync (step 4 below).

---

## Install on your phone (Realme GT 7T)

### 1. Download the APK
On your phone, open **github.com/NightFury224/Claude-Projects → Releases → "Glass Bridge (latest build)"** and download **GlassBridge.apk**.

(You need to be signed in to GitHub if the repo is private.)

### 2. Install it
1. Open the downloaded file.
2. When Android asks, allow your browser or Files app to **install unknown apps**.
3. Tap **Install**. If Play Protect warns about an unknown app, choose **Install anyway**. This is expected for any app that isn't from the Play Store.

### 3. Set it up
Open **Glass Bridge** and work through the buttons in order:

1. **Allow restricted settings.** This opens App info. Tap **⋮** (top right) → **Allow restricted settings**. Android blocks accessibility for side-loaded apps until you do this. If you don't see the ⋮ option yet, do step 2 first, get the "restricted setting" message, then come back.
2. **Turn on the accessibility service:** Accessibility → Downloaded apps → **Glass Bridge** → On.
3. **Allow notifications.**
4. **Don't restrict battery** → Allow.
5. Realme also needs: Settings → Apps → Glass Bridge → Battery → **Allow background activity**.
6. Make sure the top of the app shows ✅ for everything.

Then:

- **Quick tiles:** swipe down twice → ✏️ Edit → drag **Glasses video**, **Glasses photo** and **Glasses import** into your tiles.
- **Pocket use:** Settings → search **Smart Lock** (or "Trusted devices") → add **AiMB-S2 Max** (and your watch later). Glass Bridge has to tap buttons on an unlocked screen. With Smart Lock, it can wake and unlock the phone by itself while the glasses are connected; without it, you'll get a "🔒 Unlock your phone" notification.

### 4. Upload to Google Drive (FolderSync)
1. Install **FolderSync** from the Play Store and add your Google account.
2. Create a folderpair:
   - Local: the folder RDGlass imports into (check `DCIM/` or `Pictures/` in the Files app)
   - Remote: a `Glasses` folder in Drive
   - Sync type: **To remote folder**
   - Turn on **Delete source files after sync**
   - Turn on **Instant sync**
3. Share the Drive `Glasses` folder with your friend. In Drive, sort by **Last modified** to see the newest files first.

### 5. Test it
- [ ] Tap **🎥 Start / stop video** in the app → glasses start → "🔴 Recording" notification
- [ ] Tap again → "✅ Video saved" → RDGlass imports by itself → "✅ Import finished"
- [ ] **📸 Take photo** → "📸 Photo taken"
- [ ] Glasses off → "⚠️ Glasses didn't respond"

---

## AI voice assistant
There are four modes, each with its own quick tile and app button. Answers are **spoken through the glasses**, **shown on your watch**, or both; switch with the **AI answers** tile.

| Mode | What it does |
|---|---|
| 🎙 **Ask** | One question, one answer. |
| 💬 **Chat** | Keeps listening after each answer so you can reply right away. Say "stop" or "bye", or stay silent, to end it. |
| 👁 **Look** | Ask a question (or stay quiet). The glasses take a photo, it's imported straight away, and the AI answers about it. |
| 🎥 **Video** | Same, but with a short clip (5, 10, 20 or 30 s). The AI sees frames spread across the clip; it doesn't hear the clip's sound. |

Look and Video take about 20–60 seconds, because the photo or clip has to be imported over the glasses' Wi-Fi. Bluetooth drops during the import, so the spoken answer waits until the glasses reconnect.

**Setup**
1. Tap **🔑 Add OpenRouter API key**, paste your key from openrouter.ai → Keys, and tap **Save**. The app checks that the key works. One key works for every model.
2. Tap **🤖 Model**. The list only shows **free models that understand images**, best first. **⭐ Auto** (the default) uses the best one and falls back to the next if it's busy or rate-limited.
3. If you get a "privacy settings" error: on openrouter.ai → Settings → Privacy, allow free model endpoints. Free providers may use prompts for training, which includes your glasses' photos.
4. Free models have daily request limits; OpenRouter raises them if you've bought a little credit.
5. Tap **5. Allow microphone**, and for Look and Video tap **6. Allow photos & videos** and choose **Allow all**. Make sure RDGlass saves imports to the gallery (Photo album → ⚙️).
6. Add the tiles: **Ask AI**, **AI chat**, **AI look**, **AI video**, **AI answers**.

Answer notifications have 🎙 Ask / 💬 Chat / 👁 Look buttons, so you can start the next one from your watch. Follow-ups within 10 minutes remember the conversation.

## Bluetooth selfie remote (optional)
Pair the remote with your phone. In Glass Bridge, turn on **Bluetooth remote**. Then **volume-up = video** and **volume-down / enter = photo**.

Only keys from external Bluetooth devices are captured, never the phone's own volume buttons. If swiping on the glasses' trackpad starts triggering it, turn this option off.

## When something doesn't work
Tell Claude which notification you got:

- **"⚠️ Couldn't press Video"** (or another button): RDGlass's layout differs from what the app expects. Send a screenshot.
- **"⚠️ Glasses didn't respond":** the button was pressed, but no pop-up came back. Check the Bluetooth connection.
- **Nothing happens:** the accessibility service got switched off. Realme does this sometimes; turn it back on.

## Updating
Each change pushed to this repo builds a new APK into the same release. Download it and install it over the old one; your settings are kept.

## For developers
The app is plain Kotlin with no libraries, built by GitHub Actions (`.github/workflows/build-apk.yml`). The signing key in `keystore/` is committed on purpose so that updates install over each other. It's only for this personal side-loaded app.
