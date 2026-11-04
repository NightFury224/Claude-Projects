# Study Watch

Press a hotkey on your Windows laptop. Claude reads your screen and the answer arrives on your Galaxy Watch, step by step. Every question and answer is also saved to a revision log on the laptop.

```
Ctrl+Shift+Space → screenshot → Claude (OpenRouter) → ntfy → phone → Galaxy Watch
                                        └→ revision log (Documents\StudyWatch)
```

- Captures the **entire screen** (all monitors).
- Runs in the system tray. Your laptop stays usable: no answer window, no popups, no focus changes. The shortcut is swallowed, so it doesn't also type into the app you're in.
- The tray icon colour shows the state: 🔵 ready, 🟠 working, 🔴 last request failed (the error is also sent to the watch).
- On the watch you get the question and the final answer, with three buttons:
  - **Next step ▶** shows the solution one step at a time.
  - **All steps** sends the full worked solution as one scrollable message.
  - **Explain more** gives a simpler, more detailed explanation of the step you're on.
- Maths arrives as readable Unicode (x², √(x+1), ∫, π, ≤ and so on), never as LaTeX.
- **Revision log:** `Documents\StudyWatch\revision-YYYY-MM.md` holds every question, its screenshot, the answer, the steps and the extra explanations. It's written silently in the background *after* the answer is sent, so it never slows delivery. Open it from the tray menu whenever you want to revise.

**Why ntfy?** Answers reach the watch through the free [ntfy](https://ntfy.sh) app on your phone. Its notifications, buttons included, are mirrored to Wear OS like any other app's, and it uses instant push without polling, so it's light on battery. This avoids a custom watch app and a Firebase project, and works whether your phone and laptop share Wi-Fi or not.

---

## Setup

### 1. Phone: the ntfy app
1. Install **ntfy** from the Play Store.
2. Settings → turn on **Instant delivery**, and set Android's battery setting for ntfy to **Unrestricted**. On Realme: Settings → Apps → ntfy → Battery → **Allow background activity**.
3. You'll add your topic in step 3.

### 2. Watch: Galaxy Wearable
In the **Galaxy Wearable** app on the phone, go to **Watch settings → Notifications** and make sure **ntfy** is turned on.

### 3. Laptop: Study Watch
1. Download **StudyWatch.exe** from this repo's Releases → **Study Watch (latest Windows build)**.
2. Run it. If Windows SmartScreen warns about an unknown app, click **More info → Run anyway**.
3. The first time, `config.json` opens in Notepad:
   - Paste your OpenRouter key into `"openrouter_key"`. Get one at openrouter.ai → Keys. Claude is a paid model, so add a little credit; each question costs roughly ₹1–3.
   - Copy the `"ntfy_topic"` value (`studywatch-…`). In the ntfy phone app, tap **+** and subscribe to exactly that topic.
   - Save, then right-click the tray icon → **Reload settings**.
4. Right-click the tray icon → **Send a test to my watch**. A "✅ Study Watch connected" notification should appear on the watch.
5. Optional: tray icon → **Start with Windows**.

### 4. Use it
Press **Ctrl+Shift+Space**. The answer arrives on the watch in about 5–15 seconds.

## Capture method: GDI or Windows Graphics Capture
Tray icon → **Use Windows Graphics Capture** switches between the two (or set `"capture"` to `"gdi"` or `"wgc"`).

| | GDI (default) | Windows Graphics Capture |
|---|---|---|
| Speed | About 10–30 ms | About 50–150 ms (sets up a capture session each time) |
| GPU-drawn apps, video players | Sometimes black | ✅ |
| HDR screens | Washed-out colours | ✅ correct colours |
| Visible sign | None | A yellow border flashes briefly on Windows 10; hidden on Windows 11 |

If WGC fails for any reason, Study Watch uses GDI for that shot and notes it in `errors.log`. Both methods show windows that block screen capture (DRM video, secure apps) as black.

## Choosing a shortcut
Set `hotkey_screen` in Settings, then tray → **Reload settings**. Good choices that rarely clash with other apps:

| Shortcut | Notes |
|---|---|
| `ctrl+shift+space` | Default. Swallowed, so it won't trigger VS Code hints or Word's non-breaking space |
| `ctrl+alt+x` | Easy one-hand reach (avoid `ctrl+alt+` letters on keyboards that use AltGr) |
| `ctrl+shift+f9` … `f12` | Rarely used by apps. On many laptops the F-keys need **Fn**, unless Fn-lock is on |
| `alt+shift+z` | Left-hand only |
| `windows+shift+a` | Use with care: Windows owns many `windows+` shortcuts |
| `scroll lock`, `pause` or `insert` | One key, no clash, if your laptop has it |
| `right ctrl` | Single key; fine if you only use the left Ctrl |

Avoid `ctrl+shift+q` (closes Firefox), `ctrl+shift+s` (Save As), `ctrl+shift+t` (reopens a browser tab) and `windows+shift+s` (Snipping Tool).

Optional: set `hotkey_region` (e.g. `ctrl+shift+alt+space`) to also be able to drag a box around just one question.

## Settings (`config.json`)
| Setting | Default | |
|---|---|---|
| `hotkey_screen` | `ctrl+shift+space` | Whole-screen hotkey |
| `hotkey_region` | `""` (off) | Optional drag-a-box hotkey |
| `capture` | `gdi` | `gdi` or `wgc` (see above) |
| `model` | `auto` | `auto` picks OpenRouter's newest Claude Sonnet. You can also give an id, e.g. `anthropic/claude-opus-…`, for harder maths. |
| `ntfy_server` / `ntfy_token` | `https://ntfy.sh` / empty | For your own ntfy server, or an ntfy.sh account with a reserved topic |
| `save_screenshots` | `true` | Keep screenshots in the revision log |

After editing, use tray → **Reload settings**.

## Privacy
- Screenshots go to OpenRouter and on to Anthropic.
- Answers pass through the ntfy.sh server. Anyone who knows the random topic name could read them, so don't share it. For more privacy, reserve the topic with an ntfy account and put its token in `ntfy_token`, or run your own ntfy server.

## Troubleshooting
- **Nothing on the watch, but the phone gets it:** turn ntfy on in Galaxy Wearable → Notifications. By default the watch only shows phone notifications while the phone screen is off; turn on **Show phone notifications on watch → While using phone** if you want them always.
- **Buttons do nothing:** ntfy needs to run in the background on the phone (step 1.2). The laptop app must also be running, since it answers the buttons.
- **The hotkey doesn't work in one app:** some apps running as administrator block hotkeys from normal apps. Use a different hotkey, or the tray menu's **Ask about screen**.
- **Red tray icon:** the reason is sent to the watch and written to `%APPDATA%\StudyWatch\errors.log`.

## For developers
One Python file (`study_watch.py`), built into a single `.exe` with PyInstaller by GitHub Actions (`.github/workflows/build-study-watch.yml`). Run `python test_text.py` to check the maths and splitting helpers.
