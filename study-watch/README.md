# Study Watch

Press a hotkey on your Windows laptop. An AI model reads your screen and the answer arrives on your Galaxy Watch, step by step. Every question and answer is also saved to a revision log on the laptop.

```
Right Ctrl → screenshot → free AI model (OpenRouter) → ntfy → phone → Galaxy Watch
                                        └→ revision log (Documents\StudyWatch)
```

- Captures the **entire screen** (all monitors).
- Runs in the system tray. Your laptop stays usable: no answer window, no popups, no focus changes. The shortcut is swallowed, so it doesn't also type into the app you're in.
- The tray icon colour shows the state: 🔵 ready, 🟠 working, 🔴 last request failed (the error is also sent to the watch).
- On the watch you get the question and the final answer, with three buttons:
  - **Next step ▶** shows the solution one step at a time.
  - **All steps** sends the full worked solution as one scrollable message.
  - **Why?** gives the one key reason behind the step you're on, in a line or two.
- Maths arrives as readable Unicode (x², √(x+1), ∫, π, ≤ and so on), never as LaTeX.
- **Revision log:** `Documents\StudyWatch\revision-YYYY-MM.md` holds every question, its screenshot, the answer, the steps and the extra explanations. It's written silently in the background *after* the answer is sent, so it never slows delivery. Open it from the tray menu whenever you want to revise.

**Why ntfy?** Answers reach the watch through the free [ntfy](https://ntfy.sh) app on your phone. Its notifications, buttons included, are mirrored to Wear OS like any other app's, and it uses instant push without polling, so it's light on battery. This avoids a custom watch app and a Firebase project, and works whether your phone and laptop share Wi-Fi or not.

---

## Setup

### 1. Phone: the ntfy app
1. Install **ntfy** from the Play Store.
2. Settings → turn on **Instant delivery**, and set Android's battery setting for ntfy to **Unrestricted**. On Realme: Settings → Apps → ntfy → Battery → **Allow background activity**.
3. You'll add your topic in step 3.

### 2. Watch: Galaxy Wearable (skip until you have one; answers and buttons work on the phone too)
In the **Galaxy Wearable** app on the phone, go to **Watch settings → Notifications** and make sure **ntfy** is turned on.

### 3. Laptop: Study Watch
1. Download **StudyWatch.exe** from this repo's Releases → **Study Watch (latest Windows build)**.
2. Run it. If Windows SmartScreen warns about an unknown app, click **More info → Run anyway**.
3. The first time, `config.json` opens in Notepad:
   - Paste your OpenRouter key into `"openrouter_key"`. Get one at openrouter.ai → Keys. By default Study Watch uses **free** models, so no credit is needed.
   - On openrouter.ai → Settings → **Privacy**, allow free model endpoints. Free providers may log prompts, screenshots included.
   - Copy the `"ntfy_topic"` value (`studywatch-…`). In the ntfy phone app, tap **+** and subscribe to exactly that topic.
   - Save, then right-click the tray icon → **Reload settings**.
4. Right-click the tray icon → **Send a test to my watch**. A "✅ Study Watch connected" notification should appear on the watch.
5. Optional: tray icon → **Start with Windows**.

### 4. Use it
Tap **Right Ctrl** on its own. The answer arrives on the watch in about 5–15 seconds.

## Questions that refer to earlier screens
Question sets often put charts, tables, a passage or "Directions" at the top and the questions further down. Study Watch handles this in two layers:

1. **Notes.** After every screenshot, the model writes down *all* shared material on screen: every chart and table with all its values, the directions, the given totals, the key facts of a passage. That includes charts no question has used yet. The last 4 notes from the past 30 minutes go along with the next screenshot. They're text, so they add almost no time.
2. **Earlier screenshots.** The last 2 screenshots are also kept. If the notes still aren't enough, the app automatically asks again with those screenshots attached. This only happens when needed, and uses one extra request.

**Keeping unrelated questions separate:**
- Earlier material is used for a question only if it **explicitly refers** to something off screen ("the chart", "the passage", "as above"), or its number falls in a range the material was given for ("Directions Q1–4" covers Q3).
- Otherwise the question is solved on its own. Numbers or facts are never borrowed from earlier screens to fill a gap.
- When earlier material is used, the first step says so (e.g. `Q3: from chart 2 (earlier)`), so you can spot a wrong link at a glance.
- When a screen is clearly a **different question set or topic**, the old notes and screenshots are dropped automatically. Tray → **Forget earlier screens** clears everything when you switch topics, and it also expires on its own after 30 minutes.

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
| `right ctrl` | **Default.** Tap it on its own. Right Ctrl+C and other combos still work normally |
| `ctrl+shift+space` | Swallowed, so it won't trigger VS Code hints or Word's non-breaking space |
| `ctrl+alt+x` | Easy one-hand reach (avoid `ctrl+alt+` letters on keyboards that use AltGr) |
| `ctrl+shift+f9` … `f12` | Rarely used by apps. On many laptops the F-keys need **Fn**, unless Fn-lock is on |
| `alt+shift+z` | Left-hand only |
| `windows+shift+a` | Use with care: Windows owns many `windows+` shortcuts |
| `scroll lock`, `pause` or `insert` | One key, no clash, if your laptop has it |

Avoid `ctrl+shift+q` (closes Firefox), `ctrl+shift+s` (Save As), `ctrl+shift+t` (reopens a browser tab) and `windows+shift+s` (Snipping Tool).

Optional: set `hotkey_region` (e.g. `ctrl+shift+alt+space`) to also be able to drag a box around just one question.

## Changing how the AI answers (`rules.txt`)
Tray icon → **Edit AI rules** opens `%APPDATA%\StudyWatch\rules.txt` in Notepad. It holds every instruction the AI gets: answer length, accuracy checks, multi-question format, memory rules and so on. Edit it in plain English and save. **The next question uses the new rules**; there's no need to reload or restart.

- The reply format the app reads (the JSON fields) is kept in the app, not in `rules.txt`, so editing can't break the answers reaching your watch.
- To go back to the original rules, delete `rules.txt` (or empty it). It's recreated with the defaults.
- Updates to Study Watch don't overwrite your `rules.txt`. To get newer default rules after an update, delete it.

## Settings (`config.json`)
| Setting | Default | |
|---|---|---|
| `hotkey_screen` | `right ctrl` | Whole-screen hotkey (a lone modifier fires when tapped by itself) |
| `hotkey_region` | `""` (off) | Optional drag-a-box hotkey |
| `capture` | `gdi` | `gdi` or `wgc` (see above) |
| `model` | `auto` | `auto` uses the best **free** image models, falling back to the next if one is busy. `claude` uses the newest Claude Sonnet (needs credit, most accurate). Or give any OpenRouter model id. |
| `ntfy_server` / `ntfy_token` | `https://ntfy.sh` / empty | For your own ntfy server, or an ntfy.sh account with a reserved topic |
| `save_screenshots` | `true` | Keep screenshots in the revision log |
| `ready_message` | `true` | Send "✅ Study Watch ready" when the app starts. Problems are always sent, even when this is off |

After editing, use tray → **Reload settings**.

## Free models: limits
- Without any credit, OpenRouter allows about **50 free requests a day**. Each answer is one request, and so is each **Why?**. Buying $10 of credit once raises this to about 1,000 a day, and free models still cost nothing.
- Free models are a little less accurate than Claude, but they still work each answer out privately and check it. If a hard question comes back wrong, set `"model": "claude"` for that study session.

## Privacy
- Screenshots go to OpenRouter and on to Anthropic.
- Answers pass through the ntfy.sh server. Anyone who knows the random topic name could read them, so don't share it. For more privacy, reserve the topic with an ntfy account and put its token in `ntfy_token`, or run your own ntfy server.

## Quiz lights (classroom game)
Tray → **Quiz lights** sends each answer's option letter to an ESP32 light box. **Quiz lights connection** picks **Bluetooth** (default: straight from the laptop, no Wi-Fi) or **Wi-Fi** (through ntfy). With Bluetooth the tray icon turns 🟣 purple while the box isn't connected. See [`quiz-lights/README.md`](../quiz-lights/README.md).

## Point the mouse at the answer (classroom)
While the AI is thinking, the Caps Lock light gives a short flash every 5 seconds (tray → **Flash Caps Lock while thinking** turns it off). It stops as soon as the answer arrives, before any Caps Lock count.

Tray → **Point the mouse at the answer**: after each answer, the mouse glides onto the correct option of each question with options in turn (5 seconds on each, ending on the last), so the class sees it on the projector. It never clicks; you click it yourself if you want. The AI gives a rough position and Windows' built-in text recognition snaps it onto the option's letter label ("C)"). Options without labels (just tick boxes) are found by their text. For a number answer typed into a box, the pointer goes to the box and a label beside it shows the number ("12"); nothing is typed for you. The number is shown in light see-through letters (it follows the mouse pointer, and clicks pass through it). Tray → **Number label**: **Size** (small / medium / large / extra large) and **See-through** (very faint / faint / medium / clear) adjust it, with a preview each time, and **Preview it** shows it by the mouse. Whole-screen shots only.

## Start-up check
Every time Study Watch starts (and after **Reload settings**), it checks the whole chain: your OpenRouter key, ntfy, phone and watch. Then it sends one notification:
- **✅ Study Watch ready.** Everything works. If this arrives on your watch, you're set for the session.
- **⚠️ Study Watch started with problems,** with a list such as a mistake in `config.json`, an invalid shortcut, or a rejected key.
- **No message at all:** the laptop has no internet, or ntfy on the phone isn't running. The tray icon turns 🔴 if it couldn't send for 5 minutes. At Windows start-up it keeps retrying while the internet connects.

A mistake in `config.json` never stops the app. It starts with the values it can still read (your key and topic are rescued), leaves the file untouched for you to fix, and tells you on the watch. An invalid shortcut falls back to Right Ctrl.

## Troubleshooting
- **Nothing on the watch, but the phone gets it:** turn ntfy on in Galaxy Wearable → Notifications. By default the watch only shows phone notifications while the phone screen is off; turn on **Show phone notifications on watch → While using phone** if you want them always.
- **Buttons do nothing:** ntfy needs to run in the background on the phone (step 1.2). The laptop app must also be running, since it answers the buttons.
- **The hotkey doesn't work in one app:** some apps running as administrator block hotkeys from normal apps. Use a different hotkey, or the tray menu's **Ask about screen**.
- **Red tray icon:** the reason is sent to the watch and written to `%APPDATA%\StudyWatch\errors.log`.

## For developers
One Python file (`study_watch.py`), built into a single `.exe` with PyInstaller by GitHub Actions (`.github/workflows/build-study-watch.yml`). Run `python test_text.py` to check the maths and splitting helpers.

## Coding mode (Python, one line at a time)

Tray → **Mode → Coding (Python, line by line)**, or **hold Right Ctrl for 3 seconds** to swap between Quiz and Coding mode (Caps Lock flashes 2 times for Quiz, 4 times for Coding; a quick tap still solves). It is separate from the quiz mode: quiz lights, pointer
and number labels are not used while it is on, and switching back to **Quiz** restores them unchanged.

- **Right Ctrl** (or a tap on the light box BOOT button) reads the problem and any starter code and
  works out a solution in basic Python 3 (no comprehensions, lambda, sum/sorted, string methods, f-strings or `+=`, unless the question asks for one, then it is used).
- The first line appears as one faint see-through line in the bottom-left corner of the screen, with a small `1 / 8` counter.
  Indentation shows as a shift to the right. Clicks pass through it.
- **Page Down** = next line, **Page Up** = previous line (both work only in coding mode). **Insert** = hide the line (ask the class what comes next); **Insert** again = show it.
  Page Down / Up while hidden moves on quietly.
- The whole program is also sent to your phone.
- **Long question?** Press Right Ctrl, scroll, press again (up to 3 screenshots within 5 minutes). Each press solves
  using all of them together. After the last line, or with tray → Code line → Start a new problem, it starts fresh.
- Tray → **Code line**: text size (small / medium / large / extra large; default medium) and see-through level
  (very faint / faint / medium / clear; default faint), plus Next, Hide / show and Close.

## AI: Claude Code on your laptop (no API key)

By default Study Watch asks **Claude Code** on the laptop, signed in with your own Claude account, so no
OpenRouter key or credit is needed. One-time setup on Windows:

1. Open PowerShell and run: `irm https://claude.ai/install.ps1 | iex`
   (or install Node.js from nodejs.org and run `npm install -g @anthropic-ai/claude-code`).
2. In a new PowerShell window run `claude`, sign in with your Claude account, then type `/exit`.
3. Restart Study Watch.

Tray → **AI**: *Claude Code – Sonnet* (smarter, default), *Claude Code – Haiku* (faster), or *OpenRouter (free models)*.
Each question takes about 10–20 seconds and uses your Claude plan's limits. If Claude Code is missing,
not signed in or at its limit, the free OpenRouter models are used instead (when an OpenRouter key is set).

## Saved screenshots

Every screenshot sent to the AI (and only those) is kept, exactly as sent, in
`Documents\StudyWatch\Screenshots\<date>\<time>-quiz.jpg` (or `-coding.jpg`). No extra screenshots are taken.

## Pointer accuracy

The pointer lands on the middle of the option's letter, or on its tick box / first word for options without
letters. Option text is matched loosely (O/0, l/1, spacing, long options by their first words), and a misread
letter is worked out from the other options of the same question. If the option still can't be found, the AI's
spot is used, moved onto the nearest line of text, and the miss is noted in `errors.log`.
