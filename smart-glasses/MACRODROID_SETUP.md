# AiMB-S2 Max glasses: hands-free automation (MacroDroid)

Phone: Realme GT 7T (Android) · Glasses app: **RDGlass** · Automation app: **MacroDroid** (free)

What you get:

- One button starts/stops video, another takes a photo. Use a phone quick tile for now, and your watch or a Bluetooth button later.
- A notification confirms whether it actually worked, and it shows on your watch.
- Media imports automatically after each recording or photo.
- Files upload to a shared Google Drive folder, and the phone copy is deleted afterwards.

---

## 0. Pop-up messages the macros look for

These are copied from your screenshots. We only match a short, unique part of each one, because the app's wording varies slightly.

| Glasses pop-up | Match text | Meaning |
|---|---|---|
| "(The) glasses start recording, please import…" | `start recording` | Video started ✅ |
| "The glasses have finished recording, please import…" | `finished recording` | Video stopped ✅ |
| "The glasses start taking pictures, please import…" | `taking pictures` | Photo taken ✅ |
| "Recording in progress, please end recording first" / "…try again later" | `Recording in progress` | Busy: a video is still running ⚠️ |

---

## 1. One-time phone setup

1. Install **MacroDroid** from the Play Store.
2. MacroDroid → Settings → turn on its **Accessibility service**. You need it for tapping buttons and reading pop-ups.
3. **Realme battery settings:** Settings → Apps → MacroDroid → Battery → **Allow background activity**, and turn off battery optimisation. Do the same for **RDGlass** and **FolderSync**. Also lock MacroDroid in Recents with a swipe-down on its card.
4. **The phone must be unlocked for the macros to tap buttons.** So the macros work while the phone is in your pocket, add the glasses as a trusted device: Settings → search "Smart Lock" / "Extend Unlock" → **Trusted devices** → add **AiMB-S2 Max**. The phone then stays unlocked while the glasses are connected. Add your watch later as well.
5. In RDGlass → **Photo album** → ⚙️, turn on saving imported media to the phone if that option exists.

---

## 2. Macros

Create these 3 macros. Three fits within MacroDroid's free-version macro limit.

### Macro A: "Glasses Control" (video and photo buttons)

**Triggers** (add both):
- *User Input → Quick Settings Tile* → Tile 1, label `🎥 Video`
- *User Input → Quick Settings Tile* → Tile 2, label `📸 Photo`

Later you'll add the watch or Bluetooth-button triggers here too (section 4).

**Actions:**
1. *Screen → Screen On* (and *Unlock screen*, if offered)
2. *Variables → Set Variable* `glasses_ack` (Boolean, global) = **false**
3. *Applications → Launch Application* → **RDGlass**
4. *Wait* **2 s**
5. *UI Interaction → Click* → Text content: `Homepage`
6. *Wait* **1 s**
7. **If** *Trigger Fired* = Tile 1 (Video):
   - *UI Interaction → Click* → Text content: `Video`

   **Else:**
   - *UI Interaction → Click* → Text content: `Take photo`

   **End If**
8. *Wait* **4 s**. This keeps RDGlass on screen so Macro B can read the pop-up.
9. **If** `glasses_ack` = **false**:
   - *Device → Vibrate* (pattern: 3 short)
   - *Notification → Display Notification*: title `⚠️ Glasses didn't respond`, text `Check Bluetooth and try again`

   **End If**
10. *Device Actions → Home Screen*

### Macro B: "Glasses Watcher" (reads the pop-ups)

**Triggers** (one per row; type *Device Events → Screen Content*, text match = *contains*, application = RDGlass if it asks):
- `start recording`
- `finished recording`
- `taking pictures`
- `Recording in progress`

**Actions:**
1. *Set Variable* `glasses_ack` = **true**
2. **If** *Trigger Fired* = `start recording`:
   - *Display Notification*: title `🔴 Recording`, text `Tap Video again to stop`. Set it as **ongoing** so it stays while recording.
   - *Vibrate* (1 short)
3. **Else If** *Trigger Fired* = `finished recording`:
   - *Clear Notifications* → the 🔴 Recording one
   - *Display Notification*: `✅ Video saved, importing…`
   - *Vibrate* (2 short)
   - *Macro → Run Macro* → **Glasses Import**
4. **Else If** *Trigger Fired* = `taking pictures`:
   - *Display Notification*: `📸 Photo taken, importing…`
   - *Vibrate* (1 short)
   - *Wait* **3 s**, then *Run Macro* → **Glasses Import**
5. **Else If** *Trigger Fired* = `Recording in progress`:
   - *Display Notification*: `⚠️ Still recording, stop the video first`
   - *Vibrate* (long)
6. **End If**

These notifications show up on your phone and on your watch, so you always know what state the glasses are in.

### Macro C: "Glasses Import"

**Triggers:**
- *Quick Settings Tile* → Tile 3, label `⬇️ Import`. Use it as a manual backup.

Macro B also runs this macro automatically.

**Actions:**
1. *Screen On* (and unlock)
2. *Launch Application* → **RDGlass**
3. *Wait* **2 s**
4. *UI Interaction → Click* → Text content: `Photo album`
5. *Wait* **2 s**
6. *UI Interaction → Click* → Text content: `Import`
7. *Wait* **90 s**. "Importing in progress" needs time; adjust to how long your imports usually take.
8. *Display Notification*: `✅ Import done`
9. *Home Screen*

> Import connects your phone to the glasses' Wi-Fi, which temporarily drops normal internet. That's fine: the Drive upload in section 3 waits for internet to come back.

---

## 3. Auto-upload to a shared Google Drive folder

Use **FolderSync** (free). Autosync for Google Drive's free version caps file size at 10 MB, which is too small for videos.

1. Find where RDGlass saves imported files: open the **Files** app and check `DCIM/`, `Pictures/` and `Movies/` for a folder like `RDGlass`.
2. FolderSync → **Accounts** → add **Google Drive** and sign in.
3. **Folderpairs → Add**:
   - Local folder: the RDGlass folder from step 1
   - Remote folder: create `Glasses` in Drive
   - Sync type: **To remote folder** (upload only)
   - Turn on **Delete source files after sync**. This frees your phone storage.
   - Schedule: **Instant sync** (watches for new files), plus a backup interval of every 15 minutes.
   - Use Wi-Fi **and** mobile data, or Wi-Fi only if you want to save data.
4. In Google Drive, share the `Glasses` folder with your friend (Viewer is enough).
5. To see the newest files first, open the folder on drive.google.com → **Sort → Last modified** (newest at top). Drive remembers this.

---

## 4. Adding the watch or a Bluetooth button later

Open **Macro A** → add a trigger, and add the same trigger to the matching **If** in step 7.

- **Bluetooth selfie remote or ring:** trigger *Device Events → Media Button Pressed*, with one key for Video and another for Photo.
- **Galaxy Watch:** use a watch tile that triggers a phone macro (MacroDroid's Wear OS support, or Tasker + AutoWear).

---

## 5. Testing checklist

- [ ] Tap 🎥 tile → glasses start → "🔴 Recording" notification appears
- [ ] Tap 🎥 again → "✅ Video saved, importing…" → RDGlass opens and imports by itself
- [ ] Tap 📸 → "📸 Photo taken, importing…"
- [ ] Tap 📸 while recording → "⚠️ Still recording" warning
- [ ] Turn glasses off and tap 🎥 → "⚠️ Glasses didn't respond"
- [ ] Within a few minutes, the files appear in Drive → `Glasses`, and are gone from the phone
- [ ] Repeat with the phone locked in your pocket (tests Smart Lock)

### If something doesn't work

| Problem | Fix |
|---|---|
| A tap does nothing | Increase the *Wait* before it (the app loads slowly), or switch the click to *Identifier* mode using MacroDroid's UI-interaction picker |
| Pop-up not detected (always "didn't respond") | In Macro B, try the *Notification / Toast* option of the trigger, or check that MacroDroid's accessibility service is still on (Realme sometimes turns it off) |
| Works only when the phone is unlocked | Smart Lock trusted device isn't set up (section 1, step 4) |
| Macros stop after a while | Realme battery settings (section 1, step 3) |
