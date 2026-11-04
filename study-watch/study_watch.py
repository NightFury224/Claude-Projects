"""
Study Watch: press a hotkey, the screen goes to Claude (via OpenRouter), and the answer arrives on
your watch as a notification (via ntfy), split into steps with "Next step" / "Why?" buttons.
Every question and answer is also saved to a revision log on the laptop.

Runs in the Windows system tray. Settings live in %APPDATA%\\StudyWatch\\config.json.
"""
import base64
import io
import json
import os
import queue
import re
import secrets
import string
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

import requests

APP = "StudyWatch"
OPENROUTER = "https://openrouter.ai/api/v1"
FALLBACK_MODEL = "anthropic/claude-sonnet-4.5"
NTFY_LIMIT = 1300  # ntfy caps messages at 4096 bytes; maths symbols take up to 3 bytes each

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP
CONFIG_FILE = CONFIG_DIR / "config.json"
ERROR_LOG = CONFIG_DIR / "errors.log"
LOG_DIR = Path.home() / "Documents" / APP

DEFAULTS = {
    "openrouter_key": "",
    "model": "auto",
    "hotkey_screen": "right ctrl",
    "hotkey_region": "",
    "capture": "gdi",
    "ntfy_server": "https://ntfy.sh",
    "ntfy_topic": "",
    "ntfy_token": "",
    "save_screenshots": True,
}

SYSTEM_PROMPT = """You solve the question in a screenshot for someone reading the reply on a tiny smartwatch.
Be as short as possible. Every word must move toward the final answer.

Accuracy comes first:
- Solve it yourself from the question text. Ignore any option already selected, ticked, crossed or
  highlighted on screen, and any shown answer: they may be wrong.
- Work it out fully in "work" (private, never shown, any length), then check the result: substitute it back
  or re-derive it another way. For multiple choice, confirm exactly one option fits.

Rules for what is shown:
- No intro, no restating the question, no "Let's", "First, we", "So", "Therefore" or recap. No pleasantries.
- Plain text. No markdown or LaTeX. Maths in Unicode: x², √(x+1), π, θ, ≤, ≥, ≠, ≈, ±, ×, ÷, ∫, ∑, →, (a+b)/c, log₂, aₙ.
- Steps are terse working, like notes in a margin: an equation or a few words, at most about 80 characters each.
- Only the steps needed to reach the answer, at most 5. Skip arithmetic anyone can do in their head.
- Multiple choice: answer with the option letter and its value, e.g. "B) 42".
- Several questions on screen: answer every question that is fully visible (skip ones cut off at the edge).
  Put all answers in "answer", numbered as on screen and separated by " · ", e.g. "Q2: A) 39°C · Q3: B) 27".
  Start each step with its question number, e.g. "Q2: W+T+F = 120", and use at most 2 steps per question.

Reply with JSON only, with "work" first:
{"work": "your full private working and the check",
 "question": "the question in under 40 characters, or e.g. \"Q2–Q3: averages\" for several",
 "answer": "the final answer only, under 40 characters (about 25 more per extra question)",
 "steps": ["...", "..."]}
Facts and definitions need 0 or 1 step. If there is no question, give the single key idea on screen as the answer."""


# ---------------------------------------------------------------- settings

def load_config():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        config.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    if not config["ntfy_topic"]:
        # The topic name is the only thing protecting answers on the public ntfy server: keep it long and random.
        alphabet = string.ascii_lowercase + string.digits
        config["ntfy_topic"] = "studywatch-" + "".join(secrets.choice(alphabet) for _ in range(20))
    save_config(config)
    return config


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def log_error(text):
    with ERROR_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")


# ---------------------------------------------------------------- maths clean-up

SUPERSCRIPT = str.maketrans("0123456789+-=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ")
SUBSCRIPT = str.maketrans("0123456789+-=()", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎")
LATEX_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\leq": "≤", r"\le": "≤", r"\geq": "≥",
    r"\ge": "≥", r"\neq": "≠", r"\ne": "≠", r"\approx": "≈", r"\infty": "∞", r"\pi": "π", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\Delta": "Δ", r"\lambda": "λ",
    r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω", r"\phi": "φ", r"\int": "∫", r"\sum": "∑",
    r"\partial": "∂", r"\rightarrow": "→", r"\to": "→", r"\Rightarrow": "⇒", r"\degree": "°",
    r"\left": "", r"\right": "", r"\,": " ", r"\;": " ", r"\quad": " ",
}


def to_watch_text(text):
    """Turns any LaTeX or markdown that slipped through into plain Unicode the watch can show."""
    text = re.sub(r"\$+", "", text)
    text = re.sub(r"\\\(|\\\)|\\\[|\\\]", "", text)
    for _ in range(3):  # nested fractions and roots
        text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
        text = re.sub(r"\\sqrt\{([^{}]*)\}", r"√(\1)", text)
    for latex, symbol in sorted(LATEX_SYMBOLS.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(latex, symbol)
    text = re.sub(r"\^\{([0-9+\-=()n]+)\}", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"\^([0-9n])", lambda m: m.group(1).translate(SUPERSCRIPT), text)
    text = re.sub(r"_\{([0-9+\-=()]+)\}", lambda m: m.group(1).translate(SUBSCRIPT), text)
    text = re.sub(r"(?<=[A-Za-z])_([0-9])", lambda m: m.group(1).translate(SUBSCRIPT), text)
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    return text.strip()


def parse_answer(raw):
    """The model is asked for JSON. If it corrects itself and sends more than one JSON object, the last
    complete one wins. Code fences are fine; plain text is the fallback."""
    data = None
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _ = decoder.raw_decode(raw, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "answer" in candidate:
            data = candidate
    if data is not None:
        steps = [to_watch_text(str(s)) for s in data.get("steps") or [] if str(s).strip()]
        return {
            "question": to_watch_text(str(data.get("question") or "Your question")),
            "answer": to_watch_text(str(data.get("answer") or (steps[0] if steps else ""))),
            "steps": steps,
        }
    text = to_watch_text(raw)
    return {"question": "Your question", "answer": text[:300], "steps": split_text(text, 400)}


def split_text(text, size):
    """Splits on paragraph or sentence boundaries into pieces of at most [size] characters."""
    pieces, current = [], ""
    for sentence in re.split(r"(?<=[.!?\n])\s+", text):
        while len(sentence) > size:
            pieces.append(sentence[:size])
            sentence = sentence[size:]
        if current and len(current) + len(sentence) + 1 > size:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


# ---------------------------------------------------------------- screenshots

def capture_screen(method="gdi"):
    """The entire screen (every monitor). method is "gdi" or "wgc"; WGC falls back to GDI if it fails."""
    if method == "wgc":
        try:
            return capture_wgc()
        except Exception:  # noqa: BLE001 - WGC can be missing or blocked; GDI always works
            log_error("WGC capture failed, used GDI instead:\n" + traceback.format_exc())
    return capture_gdi()


def capture_gdi():
    """GDI (BitBlt) grab of the whole virtual screen. Fast and works everywhere."""
    import mss
    from PIL import Image

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])  # monitor 0 = all monitors together
        return Image.frombytes("RGB", shot.size, shot.rgb)


def monitor_count():
    import mss

    with mss.mss() as sct:
        return len(sct.monitors) - 1


def capture_wgc():
    """Windows Graphics Capture: one frame from each monitor, placed side by side. Handles GPU-drawn
    content and HDR better than GDI. Like GDI, it shows windows that opt out of capture as black."""
    from PIL import Image

    frames = [wgc_frame(index) for index in range(1, monitor_count() + 1)]
    if len(frames) == 1:
        return frames[0]
    canvas = Image.new("RGB", (sum(f.width for f in frames), max(f.height for f in frames)))
    x = 0
    for frame in frames:
        canvas.paste(frame, (x, 0))
        x += frame.width
    return canvas


def wgc_frame(monitor_index, timeout=3.0):
    from PIL import Image
    from windows_capture import WindowsCapture

    try:  # hiding the yellow capture border needs Windows 11
        capture = WindowsCapture(cursor_capture=False, draw_border=False, monitor_index=monitor_index)
    except Exception:  # noqa: BLE001
        capture = WindowsCapture(cursor_capture=False, draw_border=None, monitor_index=monitor_index)
    result = {}
    arrived = threading.Event()

    @capture.event
    def on_frame_arrived(frame, capture_control):
        # The buffer is mapped GPU memory, so copy it (BGRA → RGB) before stopping.
        result["image"] = Image.fromarray(frame.frame_buffer[:, :, [2, 1, 0]].copy())
        arrived.set()
        capture_control.stop()

    @capture.event
    def on_closed():
        arrived.set()

    control = capture.start_free_threaded()
    if not arrived.wait(timeout):
        control.stop()
        raise TimeoutError(f"No WGC frame from monitor {monitor_index} within {timeout:.0f} s")
    if "image" not in result:
        raise RuntimeError(f"WGC capture of monitor {monitor_index} closed without a frame")
    return result["image"]


def capture_region():
    """Dims the screen; drag a box around the question (Esc cancels). Returns an image or None."""
    import tkinter as tk
    from PIL import ImageGrab

    box = {}
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.3)
    root.configure(cursor="crosshair", bg="black")
    canvas = tk.Canvas(root, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    rect = None

    def press(event):
        nonlocal rect
        box["start"] = (event.x_root, event.y_root)
        rect = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="white", width=2)

    def drag(event):
        if rect:
            sx, sy = box["start"]
            canvas.coords(rect, sx - root.winfo_rootx(), sy - root.winfo_rooty(), event.x, event.y)

    def release(event):
        box["end"] = (event.x_root, event.y_root)
        root.destroy()

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", release)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    root.mainloop()

    if "end" not in box:
        return None
    time.sleep(0.2)  # let the dimmed overlay disappear before grabbing
    (x1, y1), (x2, y2) = box["start"], box["end"]
    left, top, right, bottom = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
    if right - left < 10 or bottom - top < 10:
        return capture_gdi()
    return ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)


def to_jpeg_base64(image, max_side=1600):
    image = image.convert("RGB")
    image.thumbnail((max_side, max_side))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


# ---------------------------------------------------------------- OpenRouter

class Claude:
    def __init__(self, config):
        self.config = config
        self._model = None

    def model(self):
        """'auto' picks OpenRouter's newest Claude Sonnet, so the app keeps up with new releases."""
        chosen = self.config.get("model", "auto").strip()
        if chosen and chosen != "auto":
            return chosen
        if self._model is None:
            try:
                data = requests.get(f"{OPENROUTER}/models", timeout=15).json()["data"]
                sonnets = [m for m in data if m["id"].startswith("anthropic/claude-sonnet")
                           and not m["id"].endswith(":beta")]
                self._model = max(sonnets, key=lambda m: m.get("created", 0))["id"] if sonnets else FALLBACK_MODEL
            except (requests.RequestException, KeyError, ValueError):
                return FALLBACK_MODEL
        return self._model

    def chat(self, messages, max_tokens=1500):
        key = self.config.get("openrouter_key", "").strip()
        if not key:
            raise RuntimeError("Add your OpenRouter key: tray icon → Settings")
        response = requests.post(
            f"{OPENROUTER}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "X-Title": APP},
            json={"model": self.model(), "messages": messages, "max_tokens": max_tokens},
            timeout=120,
        )
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = f"HTTP {response.status_code}"
            if response.status_code == 401:
                message = "OpenRouter rejected the key. Check it in Settings."
            elif response.status_code == 402:
                message = "OpenRouter needs credit on your account for Claude."
            raise RuntimeError(message)
        return response.json()["choices"][0]["message"]["content"] or ""

    def solve(self, image_b64):
        return self.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Solve it."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]},
        ], max_tokens=2000)  # room for the private working; only the short fields are shown


# ---------------------------------------------------------------- watch delivery (ntfy)

class Watch:
    """Sends notifications through ntfy. The ntfy phone app shows them, and Wear OS mirrors them,
    buttons included, to the watch. Buttons post back to a second topic that this app listens to."""

    def __init__(self, config):
        self.config = config

    @property
    def server(self):
        return self.config["ntfy_server"].rstrip("/")

    @property
    def control_topic(self):
        return self.config["ntfy_topic"] + "-ctl"

    def headers(self):
        token = self.config.get("ntfy_token", "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}

    def button(self, label, command, session):
        action = {"action": "http", "label": label, "url": f"{self.server}/{self.control_topic}",
                  "method": "POST", "body": f"{command}:{session}", "clear": False}
        if self.headers():
            action["headers"] = self.headers()
        return action

    def send(self, title, message, buttons=(), priority=4):
        for i, part in enumerate(split_text(message, NTFY_LIMIT) or [""]):
            body = {"topic": self.config["ntfy_topic"], "title": title if i == 0 else f"{title} (cont.)",
                    "message": part, "priority": priority, "tags": ["books"]}
            if buttons:
                body["actions"] = list(buttons)[:3]  # ntfy shows at most three buttons
            requests.post(self.server, json=body, headers=self.headers(), timeout=20).raise_for_status()

    def listen(self, on_command, stop):
        """Streams button presses. Reconnects forever; ntfy sends a keepalive every 45 s."""
        url = f"{self.server}/{self.control_topic}/json"
        while not stop.is_set():
            try:
                with requests.get(url, headers=self.headers(), stream=True, timeout=(10, 90)) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if stop.is_set():
                            return
                        if line:
                            event = json.loads(line)
                            if event.get("event") == "message":
                                on_command(event.get("message", ""))
            except (requests.RequestException, ValueError):
                stop.wait(5)


# ---------------------------------------------------------------- the pipeline

class StudyWatch:
    def __init__(self):
        self.config = load_config()
        self.claude = Claude(self.config)
        self.watch = Watch(self.config)
        self.busy = threading.Lock()
        self.session = None  # {"id", "question", "answer", "steps", "next", "log"}
        self.status_callback = lambda state: None
        self.stop = threading.Event()
        # The revision log is written by its own thread, after the answer is on its way to the watch.
        self.log_jobs = queue.Queue()
        threading.Thread(target=self._log_worker, daemon=True).start()

    def set_status(self, state):
        self.status_callback(state)

    def run(self, region=False):
        """Hotkey handler: captures, solves and delivers on a background thread."""
        if not self.busy.acquire(blocking=False):
            return  # already working on one; ignore repeated presses
        threading.Thread(target=self._run, args=(region,), daemon=True).start()

    def _run(self, region):
        try:
            image = capture_region() if region else capture_screen(self.config.get("capture", "gdi"))
            if image is None:
                return
            self.set_status("working")
            started = time.time()
            result = parse_answer(self.claude.solve(to_jpeg_base64(image)))
            session_id = secrets.token_hex(4)
            log_path = LOG_DIR / f"revision-{datetime.now():%Y-%m}.md"
            self.session = dict(result, id=session_id, next=0, log=log_path)
            self.send_overview()
            self.set_status("idle")
            self.log_jobs.put(lambda: self.write_log(log_path, image, result, session_id))
            print(f"Delivered in {time.time() - started:.1f}s")
        except Exception as error:  # noqa: BLE001 - anything that goes wrong should reach the watch
            log_error(traceback.format_exc())
            self.set_status("error")
            try:
                self.watch.send("⚠️ Study Watch", str(error)[:500], priority=3)
            except requests.RequestException:
                pass
        finally:
            self.busy.release()

    def send_overview(self):
        s = self.session
        message = s["answer"]
        if len(s["steps"]) > 1:
            message += f"\n({len(s['steps'])} steps)"
        buttons = [self.watch.button("Next step ▶", "next", s["id"]),
                   self.watch.button("All steps", "all", s["id"]),
                   self.watch.button("Why?", "more", s["id"])]
        self.watch.send(f"📘 {s['question']}", message, buttons)

    def handle_command(self, text):
        command, _, session_id = text.strip().partition(":")
        s = self.session
        if s is None or session_id != s["id"]:
            self.watch.send("Study Watch", "That question has expired. Press the hotkey again.", priority=2)
            return
        threading.Thread(target=self._handle, args=(command, s), daemon=True).start()

    def _handle(self, command, s):
        try:
            total = len(s["steps"])
            if command == "next":
                if s["next"] >= total:
                    self.watch.send("✅ Done", f"That was the last step.\n\nAnswer: {s['answer']}", priority=3)
                    return
                index = s["next"]
                s["next"] += 1
                buttons = [self.watch.button("Next step ▶", "next", s["id"]),
                           self.watch.button("Why?", "more", s["id"])]
                self.watch.send(f"Step {index + 1} of {total}", s["steps"][index], buttons, priority=3)
            elif command == "all":
                text = "\n\n".join(f"{i + 1}. {step}" for i, step in enumerate(s["steps"]))
                self.watch.send(f"📘 {s['question']}", f"{text}\n\nAnswer: {s['answer']}",
                                [self.watch.button("Why?", "more", s["id"])], priority=3)
            elif command == "more":
                self.set_status("working")
                step = max(s["next"] - 1, 0)
                focus = f"step {step + 1}" if s["next"] else "the whole solution"
                worked = "\n".join(f"Step {i + 1}: {t}" for i, t in enumerate(s["steps"]))
                reply = self.claude.chat([
                    {"role": "system", "content": SYSTEM_PROMPT.split("Reply with JSON")[0]
                     + "Reply in plain text, in at most 3 short lines (under 200 characters)."},
                    {"role": "user", "content": f"Question: {s['question']}\nWorked solution:\n{worked}\n"
                                                f"Answer: {s['answer']}\n\nWhy does {focus} work? Give the "
                                                "one key reason or rule, as briefly as possible."},
                ], max_tokens=300)
                explanation = to_watch_text(reply)
                self.watch.send(f"💡 Why ({focus})", explanation,
                                [self.watch.button("Next step ▶", "next", s["id"]),
                                 self.watch.button("Why?", "more", s["id"])], priority=3)
                self.log_jobs.put(lambda: self.append_log(s["log"], f"**Why ({focus}):** {explanation}"))
                self.set_status("idle")
        except Exception as error:  # noqa: BLE001
            log_error(traceback.format_exc())
            self.set_status("error")
            try:
                self.watch.send("⚠️ Study Watch", str(error)[:500], priority=3)
            except requests.RequestException:
                pass

    # ------------------------------------------------------------ revision log

    def _log_worker(self):
        while True:
            job = self.log_jobs.get()
            try:
                job()
            except Exception:  # noqa: BLE001 - a full disk must not stop answers reaching the watch
                log_error(traceback.format_exc())

    def write_log(self, log_path, image, result, session_id):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        lines = [f"\n## {datetime.now():%Y-%m-%d %H:%M} · {result['question']}\n"]
        if self.config.get("save_screenshots", True):
            shots = LOG_DIR / "screenshots"
            shots.mkdir(exist_ok=True)
            name = f"{datetime.now():%Y%m%d-%H%M%S}-{session_id}.jpg"
            image.convert("RGB").save(shots / name, "JPEG", quality=80)
            lines.append(f"![screenshot](screenshots/{name})\n")
        lines.append(f"**Answer:** {result['answer']}\n")
        lines += [f"{i + 1}. {step}" for i, step in enumerate(result["steps"])]
        with log_path.open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    @staticmethod
    def append_log(log_path, text):
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n{text}\n")


# ---------------------------------------------------------------- tray app (Windows)

def make_icon(colour):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, 60, 60), fill=colour)
    draw.rectangle((22, 18, 42, 46), fill="white")
    draw.line((26, 26, 38, 26), fill=colour, width=3)
    draw.line((26, 33, 38, 33), fill=colour, width=3)
    return image


ICON_COLOURS = {"idle": "#3b6fd8", "working": "#e0a020", "error": "#d03838"}
MODIFIER_KEYS = {"right ctrl", "left ctrl", "right shift", "left shift", "right alt", "left alt",
                 "alt gr", "right windows", "left windows"}
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def starts_with_windows():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP)
            return True
    except OSError:
        return False


def set_start_with_windows(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP, 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(key, APP)
            except OSError:
                pass


def main():
    import keyboard
    import pystray

    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: capture at real resolution
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()

    app = StudyWatch()
    icons = {state: make_icon(colour) for state, colour in ICON_COLOURS.items()}
    hotkeys = []

    def add_hotkey(combo, action):
        combo = combo.strip().lower()
        if "+" not in combo and combo in MODIFIER_KEYS:
            # A lone modifier (e.g. right ctrl) fires when tapped on its own, and isn't swallowed,
            # so shortcuts like right ctrl+c keep working.
            state = {"down": False, "other": False}

            def on_key(event):
                if event.name == combo:
                    if event.event_type == "down" and not state["down"]:
                        state.update(down=True, other=False)
                    elif event.event_type == "up" and state["down"]:
                        state["down"] = False
                        if not state["other"]:
                            action()
                elif event.event_type == "down":
                    state["other"] = True

            hotkeys.append(("hook", keyboard.hook(on_key)))
        else:
            # suppress=True keeps the shortcut from also reaching the app you're in.
            hotkeys.append(("hotkey", keyboard.add_hotkey(combo, action, suppress=True)))

    def register_hotkeys():
        for kind, handle in hotkeys:
            keyboard.unhook(handle) if kind == "hook" else keyboard.remove_hotkey(handle)
        hotkeys.clear()
        add_hotkey(app.config["hotkey_screen"], lambda: app.run(region=False))
        if app.config.get("hotkey_region"):
            add_hotkey(app.config["hotkey_region"], lambda: app.run(region=True))

    def settings(icon, item):
        os.startfile(CONFIG_FILE)  # opens in Notepad; "Reload settings" applies changes

    def reload_settings(icon, item):
        try:
            app.config.clear()
            app.config.update(load_config())
            app.claude._model = None
            register_hotkeys()
            icon.icon = icons["idle"]
        except Exception:  # noqa: BLE001
            log_error(traceback.format_exc())
            icon.icon = icons["error"]

    def test_watch(icon, item):
        try:
            app.watch.send("✅ Study Watch connected", "Answers will arrive here. Press "
                           f"{app.config['hotkey_screen']} on your laptop to try it.", priority=3)
        except requests.RequestException:
            log_error(traceback.format_exc())
            icon.icon = icons["error"]

    def open_log(icon, item):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(LOG_DIR)

    def toggle_wgc(icon, item):
        app.config["capture"] = "gdi" if app.config.get("capture") == "wgc" else "wgc"
        save_config(app.config)

    def toggle_startup(icon, item):
        set_start_with_windows(not starts_with_windows())

    def quit_app(icon, item):
        app.stop.set()
        keyboard.unhook_all()
        icon.stop()

    icon = pystray.Icon(APP, icons["idle"], "Study Watch", menu=pystray.Menu(
        pystray.MenuItem(lambda item: f"Ask about screen ({app.config['hotkey_screen']})",
                         lambda icon, item: app.run(region=False)),
        pystray.MenuItem("Send a test to my watch", test_watch),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open revision log", open_log),
        pystray.MenuItem("Settings (key, hotkeys, topic)", settings),
        pystray.MenuItem("Reload settings", reload_settings),
        pystray.MenuItem("Use Windows Graphics Capture", toggle_wgc,
                         checked=lambda item: app.config.get("capture") == "wgc"),
        pystray.MenuItem("Start with Windows", toggle_startup, checked=lambda item: starts_with_windows()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    ))

    def show_status(state):
        icon.icon = icons[state]
        icon.title = {"idle": "Study Watch", "working": "Study Watch: working…",
                      "error": "Study Watch: last request failed (see watch)"}[state]

    app.status_callback = show_status
    register_hotkeys()
    threading.Thread(target=app.watch.listen, args=(app.handle_command, app.stop), daemon=True).start()
    if not app.config["openrouter_key"]:
        icon.icon = icons["error"]
        os.startfile(CONFIG_FILE)
    icon.run()


if __name__ == "__main__":
    main()
