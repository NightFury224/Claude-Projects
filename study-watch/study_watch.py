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
RULES_FILE = CONFIG_DIR / "rules.txt"
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
    "ready_message": True,
    "lights": False,
}

DEFAULT_RULES = """You answer whatever is asked in a screenshot, for someone reading on a tiny smartwatch.
This works for any kind of question: maths, reasoning, graphs, tables, diagrams, reading comprehension,
fill in the blank, true/false, match the following, odd one out, definitions, facts, anything.

Accuracy comes first:
- Solve it yourself. Ignore any option already selected, ticked, crossed or highlighted, and any shown
  answer: they may be wrong.
- Work it out fully in "work" (private, never shown, any length), then check it a second way.
  Read any values you need from graphs, tables or images carefully before using them.

What is shown must be as small as possible:
- "answer" is the shortest complete answer: one or two words, a number with its unit, a name, True/False,
  or the option letter with its value ("B) 42"). Only use more words when the answer truly needs them,
  and then at most one short line.
- "steps" are optional margin notes (at most 3, each under about 60 characters) showing the key working or
  the values read from a graph. Leave them empty when the answer needs no justification.
- No intro, no restating the question, no filler, no markdown or LaTeX. Maths in Unicode: x², √(x+1), π,
  ≤, ≥, ≠, ≈, ±, ×, ÷, →, (a+b)/c.
- Several questions visible: answer every fully visible one (skip any cut off), numbered as on screen
  (Q1, Q2… in reading order if unnumbered), in one line separated by " · ": "Q1: B) 27 · Q2: 39°C · Q3: True".
  Tag steps with their question: "Q2: T+F = 81".
- Writing code is out of scope (it won't fit on a watch). If asked to write code, answer "Needs code".
  Questions about code that have a short answer (its output, the bug's line, the complexity) are fine.
- If there is no question but the screen has shared material (charts, tables, directions, a passage), answer
  "Saved: <what>", e.g. "Saved: 2 pie charts (1990–91, 1991–92)". If there is nothing like that either,
  give the single key idea on screen as the answer.

Memory across screenshots (the user scrolls through question sets):
- In "context", record ALL shared material visible on this screen, not just what today's questions used:
  every chart, graph, table and diagram (title plus every value and label), directions, given totals or
  constants, and the key facts of any passage. Later questions may need a chart nobody has used yet.
  Copy numbers exactly. Label each item and say which questions it belongs to when the page says so
  ("Directions Q1–4, Chart 2 – Sales by year: 2019 40, 2020 55…"). Be complete but compact, up to about
  2500 characters. Leave it "" if there is nothing shared.
- You may be given notes and screenshots from earlier screens. They are NOT part of the current question by
  default. Use earlier material for a question only if (a) the question explicitly refers to something not
  visible ("the chart", "the table above", "the passage", "the given data", "as above"), or (b) its number
  falls in a range the material was given for ("Directions Q1–4" covers Q3). Otherwise solve the question
  on its own and never borrow numbers, names or facts from earlier material, even if that would fill a gap.
- When you do use earlier material, make the first step say so, e.g. "Q3: from chart 2 (earlier)".
- Set "new_set" to true when this screen is clearly a different question set or topic from the earlier
  notes (different directions, subject or chapter), so the old notes are dropped; otherwise false.
- If something a question needs is nowhere available, answer that question with "Need: <what>"
  (e.g. "Need: chart 3"). Never answer with a placeholder like "...".
"""

# Fixed: the app reads these fields, so this part is not in rules.txt.
REPLY_FORMAT = """Reply with JSON only, "work" first:
{"work": "<private working and check>", "question": "<topic, under 40 characters>",
 "answer": "<shortest answer>", "steps": ["<optional note>"], "context": "<shared material, or empty>",
 "new_set": false}"""


def load_rules():
    """The instructions for the AI, from rules.txt (created with the defaults if missing). Read on every
    question, so edits apply straight away."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_FILE.exists() or not RULES_FILE.read_text(encoding="utf-8").strip():
        RULES_FILE.write_text(DEFAULT_RULES, encoding="utf-8")
    return RULES_FILE.read_text(encoding="utf-8").strip()


def system_prompt():
    return load_rules() + "\n\n" + REPLY_FORMAT


# ---------------------------------------------------------------- settings

def load_config(problems=None):
    """Never fails: a broken config.json starts the app with what can be recovered, and each problem is
    added to [problems] so it can be sent to the watch. A broken file is left as it is for you to fix."""
    problems = [] if problems is None else problems
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = dict(DEFAULTS)
    broken = False
    if CONFIG_FILE.exists():
        text = CONFIG_FILE.read_text(encoding="utf-8-sig")  # Notepad may add a BOM
        try:
            saved = json.loads(text)
            if not isinstance(saved, dict):
                raise ValueError("not a { … } object")
            config.update(saved)
        except ValueError as error:
            broken = True
            problems.append(f"config.json has a mistake ({error}). Using what could be read; fix it and "
                            "Reload settings.")
            # Rescue the important values so answers (and this warning) still reach the watch.
            for key in DEFAULTS:
                found = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
                if found and isinstance(DEFAULTS[key], str):
                    config[key] = found.group(1)
    for key, default in DEFAULTS.items():
        if not isinstance(config.get(key), type(default)):
            problems.append(f'"{key}" should be {type(default).__name__}; using the default.')
            config[key] = default
    if config["capture"] not in ("gdi", "wgc"):
        problems.append(f'"capture" must be "gdi" or "wgc", not "{config["capture"]}"; using "gdi".')
        config["capture"] = "gdi"
    if not config["hotkey_screen"].strip():
        problems.append('"hotkey_screen" is empty; using "right ctrl".')
        config["hotkey_screen"] = DEFAULTS["hotkey_screen"]
    if not config["openrouter_key"].strip():
        problems.append("No OpenRouter key yet: tray icon → Settings.")
    if not config["ntfy_topic"]:
        # The topic name is the only thing protecting answers on the public ntfy server: keep it long and random.
        alphabet = string.ascii_lowercase + string.digits
        config["ntfy_topic"] = "studywatch-" + "".join(secrets.choice(alphabet) for _ in range(20))
    if not broken:
        save_config(config)
    return config


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")


def log_error(text):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
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
    decoder = json.JSONDecoder(strict=False)  # tolerate raw line breaks inside strings
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
            "answer": real_answer(to_watch_text(str(data.get("answer") or (steps[0] if steps else "")))),
            "steps": [step for step in steps if not is_placeholder(step)],
            "context": str(data.get("context") or "").strip(),
            "new_set": data.get("new_set") is True,
            "ok": True,
        }
    # Broken JSON (e.g. an unescaped quote): pull the fields out one by one, never show "work".
    fields = {key: re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
              for key in ("question", "answer", "context")}
    if fields["answer"]:
        steps_block = re.search(r'"steps"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
        steps = re.findall(r'"((?:[^"\\]|\\.)*)"', steps_block.group(1)) if steps_block else []
        clean = lambda t: to_watch_text(t.replace('\\"', '"').replace("\\n", " "))
        return {
            "question": clean(fields["question"].group(1)) if fields["question"] else "Your question",
            "answer": real_answer(clean(fields["answer"].group(1))),
            "steps": [clean(step) for step in steps if step.strip() and not is_placeholder(step)],
            "context": fields["context"].group(1).strip() if fields["context"] else "",
            "new_set": bool(re.search(r'"new_set"\s*:\s*true', raw)),
            "ok": True,
        }
    log_error("Couldn't read the model's reply:\n" + raw)
    text = to_watch_text(re.sub(r'"work"\s*:\s*"(?:[^"\\]|\\.)*"\s*,?', "", raw))
    return {"question": "Your question", "answer": text[:300], "steps": split_text(text, 400), "context": "",
            "new_set": False, "ok": False}


def is_placeholder(text):
    return not re.sub(r"[.…\s·<>-]", "", text)


def real_answer(answer):
    """A model that is stuck sometimes returns "..." as the answer; say so instead of showing dots."""
    return "No answer: the model couldn't work it out. Try again." if is_placeholder(answer) else answer


def option_letters(answer):
    """The option letter of each answer, in order: "Q1: B) 27 · Q2: 39°C · Q3: D) x" → ["B", "-", "D"].
    "-" marks a question without an option letter. Lone letters ("B") count too."""
    letters = []
    for part in answer.split(" · "):
        part = re.sub(r"^\s*Q\d+\s*:\s*", "", part.strip())
        found = re.match(r"\(?([A-Za-z])\)", part) or re.fullmatch(r"([A-Za-z])\.?", part)
        letters.append(found.group(1).upper() if found else "-")
    return letters


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
    """OpenRouter client. By default it uses the best *free* models that can read images, with automatic
    fallback to the next one when a model is busy or rate-limited."""

    FREE = "auto"       # best free image models (default, costs nothing)
    PAID = "claude"     # newest Claude Sonnet (needs OpenRouter credit)

    # Rough capability ranking for free image models: strong families first, then bigger models.
    FAMILIES = [
        ("google/gemini", 100), ("qwen/qwen3-vl", 92), ("meta-llama/llama-4-maverick", 88),
        ("qwen/qwen2.5-vl-72b", 85), ("moonshotai/kimi-vl", 80), ("meta-llama/llama-4-scout", 78),
        ("mistralai/mistral-medium", 76), ("mistralai/mistral-small-3", 72), ("qwen/qwen2.5-vl", 68),
        ("google/gemma-3", 64), ("nvidia/", 60), ("meta-llama/llama-3.2-90b-vision", 58),
    ]

    def __init__(self, config):
        self.config = config
        self._models = None
        self._fetched = 0.0

    @classmethod
    def quality(cls, model):
        lower = model["id"].lower()
        score = next((s for prefix, s in cls.FAMILIES if lower.startswith(prefix)), 50)
        size = re.search(r"(\d+)b\b", lower)
        if size:
            billions = int(size.group(1))
            score += -40 if billions < 8 else -10 if billions < 20 else min(billions // 10, 10)
        if "reasoning" in (model.get("supported_parameters") or []):
            score += 5  # models that can think are better at maths and logic
        return score

    @staticmethod
    def is_free(model):
        pricing = model.get("pricing") or {}
        try:
            return model["id"].endswith(":free") or (
                float(pricing.get("prompt", 1)) == 0 and float(pricing.get("completion", 1)) == 0)
        except (TypeError, ValueError):
            return False

    def models(self):
        """The models to try, best first. OpenRouter moves on to the next if one fails."""
        chosen = self.config.get("model", self.FREE).strip() or self.FREE
        if chosen not in (self.FREE, self.PAID, "auto-free"):
            return [chosen]
        if self._models is None or time.time() - self._fetched > 6 * 3600:  # free models come and go
            self._fetched = time.time()
            data = requests.get(f"{OPENROUTER}/models", timeout=15).json()["data"]
            if chosen == self.PAID:
                sonnets = [m for m in data if m["id"].startswith("anthropic/claude-sonnet")
                           and not m["id"].endswith(":beta")]
                self._models = [max(sonnets, key=lambda m: m.get("created", 0))["id"]] if sonnets \
                    else [FALLBACK_MODEL]
            else:
                vision = [m for m in data if self.is_free(m) and "image" in
                          ((m.get("architecture") or {}).get("input_modalities") or [])]
                self._models = [m["id"] for m in sorted(vision, key=self.quality, reverse=True)][:3]
                if not self._models:
                    raise RuntimeError("OpenRouter has no free image models right now. Try again later.")
        return self._models

    def chat(self, messages, max_tokens=1500, skip=0):
        """skip=1 starts from the second-best model, used to retry when the first gave an unusable reply."""
        key = self.config.get("openrouter_key", "").strip()
        if not key:
            raise RuntimeError("Add your OpenRouter key: tray icon → Settings")
        models = self.models()[skip:] or self.models()
        response = requests.post(
            f"{OPENROUTER}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "X-Title": APP},
            # Thinking models: moderate effort, and keep their thoughts out of the reply.
            json={"model": models[0], "models": models, "messages": messages, "max_tokens": max_tokens,
                  "reasoning": {"effort": "medium", "exclude": True}},
            timeout=120,
        )
        if response.status_code != 200:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = f"HTTP {response.status_code}"
            if response.status_code == 401:
                message = "OpenRouter rejected the key. Check it in Settings."
            elif "data policy" in message.lower() or "privacy" in message.lower():
                message = ("Free models are blocked by your OpenRouter privacy settings. On openrouter.ai → "
                           "Settings → Privacy, allow free endpoints.")
            elif response.status_code == 429:
                message = "Free-model limit reached. Try again in a minute, or tomorrow for the daily limit."
            elif response.status_code == 402:
                message = "OpenRouter says this needs credit. Set \"model\" to \"auto\" for free models."
            raise RuntimeError(message)
        # Only the final reply. A thinking model's raw thoughts ("reasoning") must never reach the watch;
        # if it ran out of room before replying, the caller retries with another model.
        return response.json()["choices"][0]["message"].get("content") or ""

    def solve(self, image_b64, notes=(), earlier_images=(), skip=0):
        content = []
        if notes:
            content.append({"type": "text", "text": "Notes from earlier screens, oldest first (use only if needed):\n"
                            + "\n".join(f"- {note}" for note in notes)})
        if earlier_images:
            content.append({"type": "text", "text": f"The {len(earlier_images)} earlier screenshot(s) below are "
                            "for reference only (charts, tables or passages the questions may need):"})
            content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        for b64 in earlier_images]
        content.append({"type": "text", "text": "Solve what is on this screen:" if content else "Solve it."})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
        return self.chat([
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": content},
        ], max_tokens=8000, skip=skip)  # room for thinking models; only the short fields are shown  # room for the private working (and thinking models); only short fields are shown


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

    @property
    def lights_topic(self):
        return self.config["ntfy_topic"] + "-lights"

    def lights(self, signal):
        """Tells the quiz-lights box what to show: "thinking", "B", "B,-,D", "none" or "error"."""
        if not self.config.get("lights"):
            return
        try:
            requests.post(f"{self.server}/{self.lights_topic}", data=signal.encode(), headers=self.headers(),
                          timeout=10).raise_for_status()
        except requests.RequestException:
            log_error(f"Couldn't reach the quiz lights ({signal}):\n" + traceback.format_exc())

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
        self.problems = []  # setup problems found while loading, reported in the ready message
        self.config = load_config(self.problems)
        self.claude = Claude(self.config)
        self.watch = Watch(self.config)
        self.busy = threading.Lock()
        self.session = None  # {"id", "question", "answer", "steps", "next", "log"}
        # Shared material (chart values, directions, passages) from recent screens, so a question
        # further down the page can still use the chart at the top. Text only: cheap and fast.
        self.memory = []  # [(time, note)], newest last
        self.screens = []  # [(time, jpeg base64)], newest last
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
            threading.Thread(target=self.watch.lights, args=("thinking",), daemon=True).start()  # drum roll
            current = to_jpeg_base64(image)
            notes, earlier = self.recent_notes(), self.recent_images()

            def ask(earlier_images=()):
                # A reply without the answer fields (e.g. a thinking model that ran out of room) is never
                # shown; the next-best model gets one try instead.
                for skip in (0, 1):
                    result = parse_answer(self.claude.solve(current, notes, earlier_images, skip=skip))
                    if result["ok"]:
                        return result
                raise RuntimeError("The AI didn't give a usable answer. Tap Right Ctrl to try again.")

            result = ask()
            if "Need:" in result["answer"] and earlier and not result["new_set"]:
                # The notes weren't enough (e.g. it needs a chart no earlier question used):
                # ask again with the last few screenshots themselves.
                retry = ask(earlier)
                result = dict(retry, context=retry["context"] or result["context"])
            if result["new_set"]:
                self.forget()  # a different question set: old charts and passages must not leak in
            self.remember(result["context"], current)
            session_id = secrets.token_hex(4)
            log_path = LOG_DIR / f"revision-{datetime.now():%Y-%m}.md"
            self.session = dict(result, id=session_id, next=0, log=log_path)
            letters = option_letters(result["answer"])
            self.watch.lights(",".join(letters) if any(l != "-" for l in letters) else "none")
            self.send_overview()
            self.set_status("idle")
            self.log_jobs.put(lambda: self.write_log(log_path, image, result, session_id))
            print(f"Delivered in {time.time() - started:.1f}s")
        except Exception as error:  # noqa: BLE001 - anything that goes wrong should reach the watch
            log_error(traceback.format_exc())
            self.set_status("error")
            self.watch.lights("error")
            try:
                self.watch.send("⚠️ Study Watch", str(error)[:500], priority=3)
            except requests.RequestException:
                pass
        finally:
            self.busy.release()

    MEMORY_SIZE = 4      # text notes of shared material
    IMAGE_MEMORY = 2     # screenshots kept for the rare retry when notes aren't enough
    MEMORY_MINUTES = 30

    def recent_notes(self):
        cutoff = time.time() - self.MEMORY_MINUTES * 60
        self.memory = [(t, note) for t, note in self.memory if t > cutoff]
        return [note for _, note in self.memory]

    def recent_images(self):
        cutoff = time.time() - self.MEMORY_MINUTES * 60
        self.screens = [(t, b64) for t, b64 in self.screens if t > cutoff]
        return [b64 for _, b64 in self.screens]

    def remember(self, note, image_b64=None):
        if note and (not self.memory or self.memory[-1][1] != note):
            self.memory.append((time.time(), note[:3000]))
            self.memory = self.memory[-self.MEMORY_SIZE:]
        if image_b64:
            self.screens = (self.screens + [(time.time(), image_b64)])[-self.IMAGE_MEMORY:]

    def forget(self):
        self.memory.clear()
        self.screens.clear()

    def send_ready(self, hotkey_ok=True):
        """Startup check of the whole chain: OpenRouter key → ntfy → phone → watch. Retries for a few
        minutes, because at Windows start-up the internet often isn't connected yet."""
        problems = list(self.problems)
        if not hotkey_ok:
            problems.append(f'The shortcut "{self.config["hotkey_screen"]}" isn\'t valid; using right ctrl.')
        for attempt in range(20):
            if self.stop.is_set():
                return
            try:
                key_problem = self.check_key()
                if key_problem:
                    problems.append(key_problem)
                if problems:
                    self.watch.send("⚠️ Study Watch started with problems", "\n".join(f"• {p}" for p in problems),
                                    priority=4)
                    self.set_status("error")
                elif self.config.get("ready_message", True):
                    self.watch.send("✅ Study Watch ready", f"Tap {self.config['hotkey_screen']} on the laptop.",
                                    priority=2)
                return
            except requests.RequestException:
                self.stop.wait(15)
        log_error("Couldn't send the ready message: no internet for 5 minutes.")
        self.set_status("error")

    def check_key(self):
        """Checks the OpenRouter key without using up a request. Returns a problem, or None."""
        key = self.config.get("openrouter_key", "").strip()
        if not key:
            return None  # already reported by load_config
        response = requests.get(f"{OPENROUTER}/key", headers={"Authorization": f"Bearer {key}"}, timeout=15)
        if response.status_code == 401:
            return "OpenRouter rejected the key. Check it in Settings."
        return None

    def send_overview(self):
        s = self.session
        message = s["answer"]
        if len(s["steps"]) > 1:
            message += f"\n({len(s['steps'])} steps)"
        buttons = []
        if s["steps"]:  # one-word answers with no working just get "Why?"
            buttons += [self.watch.button("Next step ▶", "next", s["id"]),
                        self.watch.button("All steps", "all", s["id"])]
        buttons.append(self.watch.button("Why?", "more", s["id"]))
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
                    {"role": "system", "content": load_rules() + "\n\n"
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
    load_rules()  # make sure rules.txt exists so it can be edited
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
        """Returns False if a configured shortcut was invalid (Right Ctrl is used instead)."""
        for kind, handle in hotkeys:
            keyboard.unhook(handle) if kind == "hook" else keyboard.remove_hotkey(handle)
        hotkeys.clear()
        ok = True
        try:
            add_hotkey(app.config["hotkey_screen"], lambda: app.run(region=False))
        except ValueError:
            ok = False
            log_error(f"Invalid hotkey {app.config['hotkey_screen']!r}, using right ctrl")
            add_hotkey(DEFAULTS["hotkey_screen"], lambda: app.run(region=False))
        if app.config.get("hotkey_region"):
            try:
                add_hotkey(app.config["hotkey_region"], lambda: app.run(region=True))
            except ValueError:
                ok = False
                log_error(f"Invalid region hotkey {app.config['hotkey_region']!r}, ignored")
        return ok

    def settings(icon, item):
        os.startfile(CONFIG_FILE)  # opens in Notepad; "Reload settings" applies changes

    def edit_rules(icon, item):
        load_rules()  # creates rules.txt if it doesn't exist yet
        os.startfile(RULES_FILE)  # changes apply to the next question, no reload needed

    def reload_settings(icon, item):
        try:
            app.problems = []
            app.config.clear()
            app.config.update(load_config(app.problems))
            app.claude._models = None
            icon.icon = icons["idle"]
            hotkey_ok = register_hotkeys()
            # Same check as at start-up, so a fix (or a new mistake) is confirmed on the watch.
            threading.Thread(target=app.send_ready, args=(hotkey_ok,), daemon=True).start()
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

    def toggle_lights(icon, item):
        app.config["lights"] = not app.config.get("lights")
        save_config(app.config)

    def lights_mode(mode):
        threading.Thread(target=app.watch.lights, args=(f"mode {mode}",), daemon=True).start()

    def test_lights(icon, item):
        def run():
            app.watch.lights("thinking")
            time.sleep(4)
            app.watch.lights(secrets.choice("ABCD"))
        threading.Thread(target=run, daemon=True).start()

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
        pystray.MenuItem("Forget earlier screens", lambda icon, item: app.forget()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open revision log", open_log),
        pystray.MenuItem("Settings (key, hotkeys, topic)", settings),
        pystray.MenuItem("Edit AI rules", edit_rules),
        pystray.MenuItem("Reload settings", reload_settings),
        pystray.MenuItem("Quiz lights", toggle_lights, checked=lambda item: app.config.get("lights")),
        pystray.MenuItem("Test quiz lights", test_lights, enabled=lambda item: app.config.get("lights")),
        pystray.MenuItem("Quiz lights mode", pystray.Menu(
            pystray.MenuItem("Zones (stand on A, B, C…)", lambda icon, item: lights_mode("zones")),
            pystray.MenuItem("Counting (B = 2 blinks)", lambda icon, item: lights_mode("count")),
            pystray.MenuItem("Binary (B = 010)", lambda icon, item: lights_mode("binary")),
        ), enabled=lambda item: app.config.get("lights")),
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
    hotkey_ok = register_hotkeys()
    threading.Thread(target=app.send_ready, args=(hotkey_ok,), daemon=True).start()
    threading.Thread(target=app.watch.listen, args=(app.handle_command, app.stop), daemon=True).start()
    if not app.config["openrouter_key"]:
        icon.icon = icons["error"]
        os.startfile(CONFIG_FILE)
    icon.run()


if __name__ == "__main__":
    main()
