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
    "lights_link": "bluetooth",  # "bluetooth" (laptop → box directly) or "wifi" (through ntfy)
    "caps_lights": False,
    "point_answer": False,       # move the mouse pointer onto the correct option (you click it yourself)
    "label_size": 13,            # quiz number label text size, same scale as the code line
    "label_opacity": 0.2,        # quiz number label see-through level, same scale as the code line
    "caps_thinking": True,       # flash Caps Lock every 2 seconds while the AI is thinking
    "mode": "quiz",              # "quiz" (options and numbers) or "coding" (Python, one line at a time)
    "code_size": 13,             # coding mode: text size of the code line (10 small … 22 extra large)
    "code_opacity": 0.2,         # coding mode: how solid the code line is (0.12 very faint … 0.45 clear)
    "lights_address": "ac:27:6e:5d:f6:82",  # the box's Bluetooth address (your ESP32-C3); "" = scan for it
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
SPLIT_QUESTIONS = """A question cut across two screens:
- If this screen shows a question but its answer choices (A, B, C…) are cut off below, answer it as best you
  can, and also put the whole question in "context" as "Unfinished question: <full text>".
- If this screen shows answer choices with no question above them, they belong to the question just before them,
  in the earlier notes or earlier screenshots. Answer that question by picking the matching choice: give its letter and value, e.g.
  "C) 54,080". Never invent a question to fit the choices. If no earlier note or screenshot has that question,
  answer "Question not visible"."""

CODING_RULES = """A teacher is showing a class of beginners how to solve the Python 3 problem on this screen, one
line at a time. Read the problem statement and any starter code, and write a complete, correct solution.

Use BASIC Python 3 only, the most obvious beginner approach, as short and simple as possible:
- Allowed: variables, input(), print(), int(), float(), str(), if/elif/else, for with range(), while, len(),
  lists (indexing, append), looping over a string or list, string indexing, def/return, and/or/not, %, //.
- Never use: list comprehensions, lambda, map, filter, sorted, sum, min, max, enumerate, zip, any, all, imports,
  string methods (lower, upper, split, join, count, replace, strip, find, isdigit…), f-strings, try/except,
  with, classes, or dictionaries and sets unless the problem truly needs them.
- Exception: if the problem asks for something specific (a method such as split() or sort(), a dictionary,
  a list comprehension, a module to import, try/except, a class, recursion…), you MUST use it exactly as asked,
  because an answer without it is marked wrong. Use only what it asks for; keep everything else basic.
- Write counters as "count = count + 1", never "+=" (unless the problem asks for +=).
- If starter code is given, keep its exact names, parameters and lines, and include them in order.
- If the problem says how input arrives, read it exactly that way; print exactly what it asks for.
- 4 spaces per indent. No comments and no blank lines.
- Check it privately by tracing the example by hand before answering.

Reply with JSON only:
{"work": "<private check: trace the example>", "title": "<the problem in under 40 characters>",
 "lines": ["<line 1>", "<line 2>", "..."]}
If there is no coding problem on screen, give "lines": []."""


def parse_code(raw):
    """The coding reply → (title, lines). Falls back to a ```python block if the JSON is broken."""
    decoder = json.JSONDecoder(strict=False)
    data = None
    for match in re.finditer(r"\{", raw):
        try:
            candidate, _ = decoder.raw_decode(raw, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "lines" in candidate:
            data = candidate
    if data is not None:
        lines = data.get("lines") or []
        if isinstance(lines, str):
            lines = lines.split("\n")
        title = str(data.get("title") or "Python")
    else:
        block = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
        lines, title = (block.group(1).split("\n") if block else []), "Python"
    lines = [str(line).replace("\t", "    ").rstrip() for line in lines]
    return title.strip(), [line for line in lines if line.strip()]


REPLY_FORMAT = """Reply with JSON only, "work" first:
{"work": "<private working and check>", "question": "<topic, under 40 characters>",
 "answer": "<shortest answer>", "steps": ["<optional note>"], "context": "<shared material, or empty>",
 "new_set": false, "options": "<letters>", "numbers": "<numbers>", "point": "<x,y>"}
"options": the letter of the ONE CORRECT option for each question answered, in the same order as "answer",
comma-separated, with "-" for a question that has no lettered options: one letter per question, never a list
of all the choices. One question whose answer is C → "C". Two questions → e.g. "C,B". Always fill it when options are labelled
A, B, C… (or 1, 2, 3… — then give A for 1, B for 2), even if "answer" only shows the value. Options with no
labels at all (just tick boxes or buttons) count as A, B, C… in reading order. Empty if no
question has options.
"point": for EACH question, in the same order as "answer", separated by ";", a spot in the LAST image (the
current screen) as fractions of the image width and height: for a question with options, the centre of the
correct option (its letter label, or its text if the options have no labels); for a question answered by
typing into a box, the centre of that box; "-" otherwise. E.g. "0.18,0.42; -; 0.30,0.77".
"numbers": for each question in the same order, its answer as a plain number with at most 2 decimals
(12, 0.33, 54080, -4.5; round, no units or commas) when no lettered options are visible for it on this screen
(none at all, or cut off below) and the answer is one number; "-" otherwise. Comma-separated, e.g. "12" or "-,4.25". Empty if no question qualifies."""


def load_rules():
    """The instructions for the AI, from rules.txt (created with the defaults if missing). Read on every
    question, so edits apply straight away."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not RULES_FILE.exists() or not RULES_FILE.read_text(encoding="utf-8").strip():
        RULES_FILE.write_text(DEFAULT_RULES, encoding="utf-8")
    return RULES_FILE.read_text(encoding="utf-8").strip()


def system_prompt():
    return load_rules() + "\n\n" + SPLIT_QUESTIONS + "\n\n" + REPLY_FORMAT


# ---------------------------------------------------------------- settings

CODE_SIZES = {"small": 10, "medium": 13, "large": 17, "extra large": 22}
CODE_OPACITIES = {"very faint": 0.12, "faint": 0.2, "medium": 0.3, "clear": 0.45}
LABEL_SIZES, LABEL_OPACITIES = CODE_SIZES, CODE_OPACITIES  # the quiz number uses the same scale as the code line
LABEL_LOOK = {"size": 13, "opacity": 0.2}  # quiz number label; set from the config at start-up and from the tray


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
    # Older builds saved bigger sizes and stronger see-through levels; move them onto the new scale.
    if config.get("code_size") not in CODE_SIZES.values():
        config["code_size"] = DEFAULTS["code_size"]
    if config.get("code_opacity") not in CODE_OPACITIES.values():
        config["code_opacity"] = DEFAULTS["code_opacity"]
    if config.get("label_size") not in LABEL_SIZES.values():
        config["label_size"] = DEFAULTS["label_size"]
    if config.get("label_opacity") not in LABEL_OPACITIES.values():
        config["label_opacity"] = DEFAULTS["label_opacity"]
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
            "options": option_list(data.get("options")),
            "numbers": number_list(data.get("numbers")),
            "point": point_value(data.get("point")),
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
            "options": option_list((re.search(r'"options"\s*:\s*"([^"]*)"', raw) or [None, ""])[1]),
            "numbers": number_list((re.search(r'"numbers"\s*:\s*"([^"]*)"', raw) or [None, ""])[1]),
            "point": point_value((re.search(r'"point"\s*:\s*"([^"]*)"', raw) or [None, ""])[1]),
            "ok": True,
        }
    log_error("Couldn't read the model's reply:\n" + raw)
    text = to_watch_text(re.sub(r'"work"\s*:\s*"(?:[^"\\]|\\.)*"\s*,?', "", raw))
    return {"question": "Your question", "answer": text[:300], "steps": split_text(text, 400), "context": "",
            "new_set": False, "options": [], "numbers": [], "point": None, "ok": False}


def is_placeholder(text):
    return not re.sub(r"[.…\s·<>-]", "", text)


def real_answer(answer):
    """A model that is stuck sometimes returns "..." as the answer; say so instead of showing dots."""
    return "No answer: the model couldn't work it out. Try again." if is_placeholder(answer) else answer


def option_list(value):
    """The model's "options" field ("C,B", "B,-,D", ["C", "B"]) → ["C", "B"]. [] if missing or unusable."""
    items = value if isinstance(value, list) else re.split(r"[,\s·]+", str(value or ""))
    letters = []
    for item in (str(i).strip().strip("()").upper() for i in items):
        if not item:
            continue
        letters.append(item if re.fullmatch(r"[A-Z]", item) else "-")
    return letters if any(l != "-" for l in letters) else []


def point_value(value):
    """The model's "point" ("0.18,0.42; 0.18,0.81", [[0.18, 0.42]]) → [(0.18, 0.42), (0.18, 0.81)] as fractions
    of the image. None if there's no usable spot."""
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple, type(None), str)):
        groups = [list(v) if isinstance(v, (list, tuple)) else re.findall(r"\d+(?:\.\d+)?", str(v or ""))
                  for v in value]
    elif isinstance(value, (list, tuple)):
        groups = [list(value)]
    else:
        groups = [re.findall(r"\d+(?:\.\d+)?", g) for g in str(value or "").split(";")]
    points = []  # one per question; None where there's no spot
    for items in groups:
        try:
            x, y = (float(v) for v in items[:2])
        except (TypeError, ValueError):
            points.append(None)
            continue
        if x > 1 or y > 1:  # percentages, e.g. "18,62"
            x, y = x / 100, y / 100
        points.append((x, y) if 0 <= x <= 1 and 0 <= y <= 1 else None)
    return points if any(points) else None


def number_list(value):
    """The model's "numbers" field ("12", "-,4.25", [12, 0.5]) → ["12", "-", "4.25"]: plain numbers rounded to
    at most 2 decimals, "-" for anything else. [] if there's no number at all."""
    items = value if isinstance(value, list) else str(value or "").split(",")
    numbers = []
    for item in (str(i).strip().replace(" ", "") for i in items):
        if not item:
            continue
        try:
            number = round(float(item), 2) if re.fullmatch(r"-?\d+(\.\d+)?", item) else None
        except ValueError:
            number = None
        if number is None or abs(number) >= 1_000_000:
            numbers.append("-")
        else:
            numbers.append(f"{number:.2f}".rstrip("0").rstrip(".") if number != int(number) else str(int(number)))
    return numbers if any(n != "-" for n in numbers) else []


def answer_numbers(answer):
    """Plain-number answers read from the answer text ("Q1: 12 · Q2: x = 4.25 cm" → ["12", "4.25"]), for
    when the model leaves "numbers" empty. "-" for anything that isn't one number."""
    numbers = []
    for part in answer_parts(answer):
        part = re.sub(r"^\s*(?:Q\.?\s*\d+|\d+[.)])\s*[:.)-]?\s*", "", part.strip())
        found = re.fullmatch(r"(?:[A-Za-z]\s*=\s*)?(-?[\d,]*\.?\d+)\s*(?:[A-Za-z°%²³]{1,6})?", part)
        numbers.append((number_list(found.group(1).replace(",", "")) or ["-"])[0] if found else "-")
    return numbers


def lights_message(result):
    """What the quiz lights get, one token per question: "C" for an option, ":12.5" for a number (shown by the
    binary mode; counting shows nothing for it), "-" for neither. None when there's nothing to show."""
    letters = lights_letters(result)
    numbers = result.get("numbers") or []
    if not numbers:
        numbers = answer_numbers(result["answer"])
    if len(numbers) != len(letters):
        numbers = numbers if len(letters) == 1 and len(numbers) == 1 else []
    tokens = []
    for i, letter in enumerate(letters):
        number = numbers[i] if i < len(numbers) else "-"
        tokens.append(letter if letter != "-" else f":{number}" if number != "-" else "-")
    return ",".join(tokens) if any(t != "-" for t in tokens) else None


def answer_parts(answer):
    """The separate answers in an answer line ("Q1: B) 27 · Q2: 39°C" → two parts)."""
    return [p for p in re.split(r"\s·\s|\n|;\s+|\s\|\s", answer) if p.strip()]


def lights_letters(result):
    """The letters for the quiz lights: one per answered question. The model's "options" field is used only
    when it has exactly one letter per answer, so a list of every choice ("A,B,C,D" for one question) is
    never shown; otherwise the letters are read from the answer text."""
    options = result.get("options") or []
    if options and len(options) == len(answer_parts(result["answer"])):
        return options
    return option_letters(result["answer"])


def option_letters(answer):
    """The option letter of each answer, in order: "Q1: B) 27 · Q2: 39°C · Q3: D) x" → ["B", "-", "D"].
    "-" marks a question without an option letter. Lone letters ("B") count too."""
    letters = []
    for part in answer_parts(answer):
        part = re.sub(r"^\s*(?:Q\.?\s*\d+|\d+[.)])\s*[:.)-]?\s*", "", part.strip())
        part = re.sub(r"^(?:option|ans(?:wer)?)\s*[:.-]?\s*", "", part, flags=re.I)
        found = (re.match(r"\(?([A-Za-z])\)", part)                      # "B) 27", "(B) 27"
                 or re.fullmatch(r"([A-Za-z])\.?", part)                 # "B"
                 or re.match(r"([A-H])(?:[.:]\s|\s+[-–—=]\s*|\s+(?=[\d(√π⅓¼½⅔¾-]))", part)  # "B. 27", "B - 27", "B 27"
                 or re.search(r"\(([A-H])\)\s*$", part)                 # "27 (B)"
                 or re.search(r"\boption\s+([A-H])\b", part, re.I))    # "… option B"
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

LAST_LAYOUT = None  # [(image x, image y, width, height, screen left, screen top)] of the last whole-screen shot


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

    global LAST_LAYOUT
    with mss.mss() as sct:
        whole = sct.monitors[0]  # monitor 0 = all monitors together
        shot = sct.grab(whole)
        LAST_LAYOUT = [(0, 0, shot.width, shot.height, whole["left"], whole["top"])]
        return Image.frombytes("RGB", shot.size, shot.rgb)


def monitor_count():
    import mss

    with mss.mss() as sct:
        return len(sct.monitors) - 1


def capture_wgc():
    """Windows Graphics Capture: one frame from each monitor, placed side by side. Handles GPU-drawn
    content and HDR better than GDI. Like GDI, it shows windows that opt out of capture as black."""
    from PIL import Image

    global LAST_LAYOUT
    import mss

    frames = [wgc_frame(index) for index in range(1, monitor_count() + 1)]
    with mss.mss() as sct:
        monitors = sct.monitors[1:]
    LAST_LAYOUT, x = [], 0
    for frame, monitor in zip(frames, monitors):
        LAST_LAYOUT.append((x, 0, frame.width, frame.height, monitor["left"], monitor["top"]))
        x += frame.width
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
                            "for reference only (charts, tables or passages the questions may need, or the question "
                            "whose answer choices continue on this screen):"})
            content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        for b64 in earlier_images]
        content.append({"type": "text", "text": "Solve what is on this screen:" if content else "Solve it."})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
        return self.chat([
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": content},
        ], max_tokens=8000, skip=skip)  # room for thinking models; only the short fields are shown  # room for the private working (and thinking models); only short fields are shown


# ---------------------------------------------------------------- point at the answer (the teacher clicks)

def ocr_lines(image):
    """Windows' built-in text recognition: [(text, x, y, width, height)] per line, in image pixels."""
    import asyncio

    async def run():
        from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter

        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return []
        r, g, b = image.convert("RGB").split()
        from PIL import Image
        bgra = Image.merge("RGBA", (b, g, r, Image.new("L", image.size, 255)))
        writer = DataWriter()
        writer.write_bytes(bgra.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.BGRA8, image.width, image.height, BitmapAlphaMode.PREMULTIPLIED)
        result = await engine.recognize_async(bitmap)
        lines = []
        for line in result.lines:
            rects = [w.bounding_rect for w in line.words]
            if not rects:
                continue
            x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
            x1, y1 = max(r.x + r.width for r in rects), max(r.y + r.height for r in rects)
            first = rects[0]
            lines.append((line.text, x0, y0, x1 - x0, y1 - y0, first))
        return lines

    return asyncio.run(run())


def option_value(answer_part):
    """The option's text from one answer ("Q2: C) 70 kg" → "70 kg", "70" → "70"), for finding unlabelled options."""
    part = re.sub(r"^\s*(?:Q\.?\s*\d+|\d+[.)])\s*[:.)-]?\s*", "", answer_part.strip())
    return re.sub(r"^\(?[A-Za-z]\)\s*|^[A-Za-z]\.\s+", "", part).strip()


def find_option(lines, letter, near, max_distance, value=""):
    """The on-screen spot of the correct option closest to [near], or None: its letter label ("C)", "(C)", "C."),
    or, for options without labels, the line whose text is the option's [value] ("70")."""
    label = re.compile(rf"^\(?{letter}\s*[).:]", re.I)
    squash = lambda t: re.sub(r"[\s,]", "", t).lower()
    wanted = squash(value)
    best = None
    for text, x, y, w, h, first in lines:
        if label.match(text.strip()):
            spot = (first.x + first.width / 2, first.y + first.height / 2)  # the letter label itself
        elif wanted and (squash(text) == wanted or squash(text).endswith(wanted) and len(squash(text)) <= len(wanted) + 3):
            spot = (x + w / 2, y + h / 2)  # e.g. "☐ 70": the option's text
        else:
            continue
        distance = ((spot[0] - near[0]) ** 2 + (spot[1] - near[1]) ** 2) ** 0.5
        if distance <= max_distance and (best is None or distance < best[0]):
            best = (distance, spot)
    return best[1] if best else None


def image_to_screen(x, y):
    for ix, iy, w, h, left, top in LAST_LAYOUT or []:
        if ix <= x < ix + w and iy <= y < iy + h:
            return int(left + x - ix), int(top + y - iy)
    return None


def glide_pointer(target, seconds=0.5):
    """Moves the mouse smoothly to [target] (screen pixels), so the class can follow it. Never clicks."""
    import ctypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.windll.user32
    start = POINT()
    user32.GetCursorPos(ctypes.byref(start))
    steps = 25
    for i in range(1, steps + 1):
        t = i / steps
        t = t * t * (3 - 2 * t)  # ease in and out
        user32.SetCursorPos(int(start.x + (target[0] - start.x) * t), int(start.y + (target[1] - start.y) * t))
        time.sleep(seconds / steps)


POINT_HOLD_S = 5.0  # how long the pointer stays on each answer before moving to the next question's


def show_label(target, text, seconds=8, style=None):
    """The see-through number by the mouse pointer (e.g. "12" by an answer box). It is drawn by the one shared
    overlay window (CodeLine), never by a window of its own: two window loops on different threads can make
    Windows close the whole app."""
    if OVERLAY is not None:
        OVERLAY.label(target, text, seconds)


OVERLAY = None  # the shared CodeLine overlay, set up in main()


class CodeLine:
    """Coding mode: one line of code floating near the bottom of the screen, in faint see-through grey.
    Page Down / Page Up show the next / previous line, Insert hides / shows it. Clicks pass through and it never takes focus.
    It runs its own small window loop; other threads talk to it through a queue."""

    def __init__(self, config, on_done=lambda: None):
        self.config = config
        self.on_done = on_done  # called after the last line, so the next press starts a new problem
        self.commands = queue.Queue()
        self.lines, self.index, self.hidden = [], 0, False
        threading.Thread(target=self._thread, daemon=True).start()

    def show(self, lines):
        self.commands.put(("show", list(lines)))

    def next(self):
        self.commands.put(("next", None))

    def previous(self):
        self.commands.put(("previous", None))

    def toggle(self):
        self.commands.put(("toggle", None))

    def restyle(self):
        self.commands.put(("style", None))

    def label(self, target, text, seconds):
        """Quiz mode: the number in see-through letters beside the mouse pointer for [seconds]."""
        self.commands.put(("label", (target, str(text), seconds)))

    def close(self):
        self.commands.put(("close", None))

    def _thread(self):
        if sys.platform != "win32":
            return
        import ctypes
        import tkinter as tk
        import tkinter.font as tkfont

        key = "#9aa0a9"  # see-through colour: nearly the text colour, so the letters' edges blend in cleanly
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg=key)
        root.attributes("-topmost", True, "-transparentcolor", key)
        counter = tk.Label(root, font=("Segoe UI", 11), fg="#9ba1aa", bg=key, width=6, anchor="e")
        counter.pack(side="left", padx=(0, 12))
        code = tk.Label(root, font=("Consolas", 24), fg="#9ba1aa", bg=key, anchor="w", justify="left")
        code.pack(side="left")
        state = {"left": 0}

        def click_through():
            try:
                hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
                bits = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                # layered, click-through, never activated, not in the taskbar
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, bits | 0x80000 | 0x20 | 0x8000000 | 0x80)
            except Exception:  # noqa: BLE001
                pass

        def layout():
            size = int(self.config.get("code_size", 13))
            font = tkfont.Font(family="Consolas", size=size)
            code.configure(font=font)
            counter.configure(font=("Segoe UI", max(6, round(size * 0.6))))  # always smaller than the code
            root.attributes("-alpha", max(0.05, min(1.0, float(self.config.get("code_opacity", 0.2)))))
            # A fixed left edge for the whole program, so indentation shows as a real shift to the right.
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            state["left"] = 30  # bottom-left corner, just above the taskbar
            state["top"] = int(screen_h * 0.86)

        def render():
            if not self.lines:
                root.withdraw()
                return
            if self.index >= len(self.lines):
                code.configure(text="✓ done")
                counter.configure(text="")
                root.after(2500, finish)
            else:
                code.configure(text=self.lines[self.index])
                counter.configure(text=f"{self.index + 1} / {len(self.lines)}")
            root.geometry(f"+{state['left']}+{state['top']}")
            if self.hidden:
                root.withdraw()
            else:
                root.deiconify()
                root.attributes("-topmost", True)
                root.update_idletasks()
                click_through()

        def finish():
            if self.index >= len(self.lines):
                self.lines, self.index = [], 0
                root.withdraw()
                self.on_done()

        def poll():
            try:
                while True:
                    command, value = self.commands.get_nowait()
                    if command == "show":
                        self.lines, self.index, self.hidden = value, 0, False
                        layout()
                        render()
                    elif command == "next" and self.lines and self.index < len(self.lines):
                        self.index += 1
                        render()  # while hidden it moves on quietly; Insert shows the new line
                    elif command == "previous" and self.lines and self.index > 0:
                        self.index -= 1
                        render()
                    elif command == "toggle" and self.lines:
                        self.hidden = not self.hidden
                        render()
                    elif command == "style":
                        layout()
                        render()
                    elif command == "label":
                        number_label(*value)
                    elif command == "close":
                        self.lines, self.index = [], 0
                        root.withdraw()
            except queue.Empty:
                pass
            root.after(40, poll)

        def number_label(target, text, seconds):
            """A see-through number that follows the mouse pointer, then fades out; clicks pass through it."""
            window = tk.Toplevel(root)
            window.overrideredirect(True)
            window.configure(bg=key)
            window.attributes("-topmost", True, "-alpha", 0.0, "-transparentcolor", key)
            tk.Label(window, text=text, font=("Consolas", LABEL_LOOK["size"]), fg="#9ba1aa", bg=key).pack()
            peak = LABEL_LOOK["opacity"]
            window.geometry(f"+{target[0] + 28}+{target[1] - 28}")
            window.update_idletasks()
            try:
                hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
                bits = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
                ctypes.windll.user32.SetWindowLongW(hwnd, -20, bits | 0x80000 | 0x20 | 0x8000000 | 0x80)
            except Exception:  # noqa: BLE001
                pass

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            cursor = POINT()

            def follow():  # stays beside the pointer wherever it moves
                try:
                    ctypes.windll.user32.GetCursorPos(ctypes.byref(cursor))
                    window.geometry(f"+{cursor.x + 28}+{cursor.y - 28}")
                    window.after(16, follow)
                except tk.TclError:
                    pass  # the label has closed

            steps, fade_ms = 12, 250

            def fade(i, direction):
                try:
                    window.attributes("-alpha", peak * i / steps)
                    if direction > 0 and i < steps:
                        window.after(fade_ms // steps, fade, i + 1, 1)
                    elif direction < 0 and i > 0:
                        window.after(fade_ms // steps, fade, i - 1, -1)
                    elif direction < 0:
                        window.destroy()
                except tk.TclError:
                    pass

            follow()
            fade(0, 1)
            window.after(int(seconds * 1000), fade, steps, -1)

        poll()
        root.mainloop()


def show_label_at_pointer(text, seconds, style):
    import ctypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    where = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(where))
    show_label((where.x, where.y), text, seconds)


def point_at_answer(image, result, label_style=None):
    """Visits each question's answer in turn, staying a few seconds on each (it ends on the last one):
    - a question with options: the pointer goes onto the correct option (never clicks);
    - a number answer: the pointer goes to the answer box and a label beside it shows the number (nothing typed).
    The AI gives rough spots; Windows text recognition snaps options onto their label or text when it can."""
    if sys.platform != "win32" or LAST_LAYOUT is None:
        return
    letters = lights_letters(result)
    numbers = result.get("numbers") or answer_numbers(result["answer"])
    parts = answer_parts(result["answer"])
    points = result.get("point") or []
    points = points + [None] * (len(letters) - len(points))
    if len(points) == 1 and len(letters) > 1:  # a single spot: it belongs to the first question with an answer
        first = next((i for i, l in enumerate(letters) if l != "-" or i < len(numbers) and numbers[i] != "-"), 0)
        points = [None] * first + points
    try:
        lines = ocr_lines(image) if any(l != "-" for l in letters) else []
    except Exception:  # noqa: BLE001 - text recognition is only a refinement; the AI's spots still work
        lines = []
        log_error("Pointer: text recognition failed, using the AI's position\n" + traceback.format_exc(limit=2))
    moved = False
    for i, point in enumerate(points):
        if i >= len(letters):
            continue
        letter = letters[i]
        number = numbers[i] if i < len(numbers) else "-"
        if letter == "-" and number == "-":
            continue
        if point is None:
            if letter == "-":  # a number with no box to point at: show it on the pointer where it is now
                if moved:
                    time.sleep(POINT_HOLD_S)
                show_label_at_pointer(number, POINT_HOLD_S + 3, label_style)
                moved = True
            continue
        x, y = point[0] * image.width, point[1] * image.height
        if letter != "-":
            value = option_value(parts[i]) if i < len(parts) else ""
            spot = find_option(lines, letter, (x, y), max_distance=image.height * 0.2, value=value)
            if spot:
                x, y = spot
        target = image_to_screen(x, y)
        if not target:
            continue
        if moved:
            time.sleep(POINT_HOLD_S)
        glide_pointer(target)
        moved = True
        if letter == "-":  # a number answer: show it beside the box
            show_label(target, number, POINT_HOLD_S + 3)


# ---------------------------------------------------------------- Caps Lock light (counting)

CAPS_BLINK_S = 0.4          # on and off time of each blink
CAPS_BETWEEN_S = 3.0        # pause between answers when one screen has several questions
caps_lock = threading.Lock()


def caps_thinking(stop):
    """While the AI is thinking: one short Caps Lock flash every 2 seconds until [stop] is set.
    Caps Lock is always put back the way it was."""
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32

    def toggle():
        user32.keybd_event(0x14, 0x3A, 0, 0)
        user32.keybd_event(0x14, 0x3A, 0x0002, 0)
        time.sleep(0.02)

    while not stop.wait(2.0):
        with caps_lock:
            toggle()
            time.sleep(0.3)
            toggle()


def caps_count(letters):
    """Counts each answer on the Caps Lock light: A = 1 blink, B = 2 … Number answers and "-" show nothing.
    Caps Lock is put back the way it was afterwards."""
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    VK_CAPITAL, KEYUP = 0x14, 0x0002

    def is_on():
        return bool(user32.GetKeyState(VK_CAPITAL) & 1)

    def toggle():
        user32.keybd_event(VK_CAPITAL, 0x3A, 0, 0)
        user32.keybd_event(VK_CAPITAL, 0x3A, KEYUP, 0)
        time.sleep(0.02)

    counts = [ord(l) - ord("A") + 1 if len(l) == 1 and "A" <= l <= "Z" else 0 for l in letters]
    if not any(counts):
        return
    with caps_lock:  # one answer at a time
        was_on = is_on()
        try:
            if was_on:
                toggle()
                time.sleep(1.0)  # dark first, so the first blink is clear
            for i, count in enumerate(counts):
                if i:
                    time.sleep(CAPS_BETWEEN_S)
                for _ in range(count):
                    toggle()
                    time.sleep(CAPS_BLINK_S)
                    toggle()
                    time.sleep(CAPS_BLINK_S)
        finally:
            if is_on() != was_on:
                toggle()


# ---------------------------------------------------------------- quiz lights over Bluetooth

LIGHTS_SERVICE = "7a3c0001-5f1e-4e8a-9b6d-2c4f1e0b7a10"
LIGHTS_CHAR = "7a3c0002-5f1e-4e8a-9b6d-2c4f1e0b7a10"


class BleLights:
    """Keeps a Bluetooth Low Energy link to the quiz-lights box (advertised as "QuizLights") and
    reconnects by itself. Messages are the same text as over Wi-Fi: "B", "B,-,D", "none", "mode binary"."""

    def __init__(self, wanted, on_change, config=None, on_message=None):
        self.config = config if config is not None else {}
        self.on_message = on_message or (lambda text: None)  # e.g. "SOLVE" when the box's button is pressed
        self.wanted = wanted          # () -> bool: only search while quiz lights over Bluetooth is on
        self.on_change = on_change    # called with True/False when the link comes up or drops
        self.connected = False
        self.reason = "searching…"   # shown in the tray tooltip while not connected
        self.loop = None
        self.queue = None
        threading.Thread(target=self._thread, daemon=True).start()

    def _set(self, connected):
        if connected != self.connected:
            self.connected = connected
            self.on_change(connected)

    def send(self, message):
        """Queues a message. If the link is down for a moment (Windows drops idle Bluetooth links), it's
        sent as soon as it reconnects, unless that takes more than 30 seconds. False if Bluetooth isn't running."""
        if not self.loop:
            return False
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (time.time(), message))
        return True

    def _thread(self):
        import asyncio
        try:
            asyncio.run(self._main())
        except Exception:  # noqa: BLE001
            log_error("Bluetooth for quiz lights stopped:\n" + traceback.format_exc())

    async def _main(self):
        import asyncio
        from bleak import BleakClient, BleakScanner

        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()

        def is_box(device, adv):
            return (device.name == "QuizLights" or adv.local_name == "QuizLights"
                    or LIGHTS_SERVICE in [u.lower() for u in adv.service_uuids])

        last_error = None
        while True:
            if not self.wanted():
                await asyncio.sleep(2)
                continue
            wait = 2
            try:
                # A known address connects directly, without scanning. Some laptops' Bluetooth can
                # connect but refuses to scan ("device not ready"), so this also works around that.
                # An empty value saved by an older version still uses the built-in address.
                target = (self.config.get("lights_address") or DEFAULTS["lights_address"]).strip()
                if target:
                    # Given a plain address string, bleak scans first anyway. Wrapping the address as a
                    # BLEDevice makes it connect straight to it (BluetoothLEDevice.FromBluetoothAddressAsync).
                    from types import SimpleNamespace
                    from bleak.backends.device import BLEDevice
                    number = int(target.replace(":", "").replace("-", ""), 16)
                    details = SimpleNamespace(adv=SimpleNamespace(bluetooth_address=number), scan=None)
                    target = BLEDevice(target.upper(), "QuizLights", details, 0)
                else:
                    device = await BleakScanner.find_device_by_filter(is_box, timeout=8)
                    last_error = None
                    if device is None:
                        self._reason("box not found (is it powered and within ~10 m?)")
                        continue
                    target = device
                async with BleakClient(target, timeout=15) as client:
                    if not self.config.get("lights_address"):  # found by scanning: remember it for next time
                        self.config["lights_address"] = client.address
                        try:
                            save_config(self.config)
                        except Exception:  # noqa: BLE001
                            log_error(traceback.format_exc())
                    try:  # the box's BOOT button works as a remote: it notifies "SOLVE"
                        await client.start_notify(
                            LIGHTS_CHAR, lambda _, data: self.on_message(bytes(data).decode(errors="ignore")))
                    except Exception:  # noqa: BLE001 - older firmware without the button: lights still work
                        log_error("Quiz lights: the box's button isn't available (older firmware?)\n"
                                  + traceback.format_exc(limit=1))
                    self.reason = "connected"
                    self._set(True)
                    while client.is_connected and self.wanted():
                        try:
                            sent_at, message = await asyncio.wait_for(self.queue.get(), 2)
                        except asyncio.TimeoutError:
                            continue
                        if time.time() - sent_at > 30:
                            continue  # stale: the class has moved on
                        try:
                            await client.write_gatt_char(LIGHTS_CHAR, message.encode(), response=True)
                        except Exception:
                            self.queue.put_nowait((sent_at, message))  # retry after reconnecting
                            raise
            except Exception as error:  # noqa: BLE001 - out of range, switched off, Bluetooth off: just retry
                text = str(error)
                if "not ready" in text.lower() or getattr(error, "winerror", None) == -2147020577:
                    self._reason("Windows won't scan for Bluetooth. Put the box's address in Settings "
                                 "(\"lights_address\")")
                    wait = 5
                else:
                    self._reason("couldn't connect, retrying")
                if text != last_error:  # log each new problem once, not every 2 seconds
                    log_error("Quiz lights Bluetooth link:\n" + traceback.format_exc(limit=2))
                    last_error = text
            finally:
                self._set(False)
            await asyncio.sleep(wait)

    def _reason(self, reason):
        if reason != self.reason:
            self.reason = reason
            self.on_change(self.connected)  # refreshes the tray tooltip


# ---------------------------------------------------------------- watch delivery (ntfy)

class Watch:
    """Sends notifications through ntfy. The ntfy phone app shows them, and Wear OS mirrors them,
    buttons included, to the watch. Buttons post back to a second topic that this app listens to."""

    def __init__(self, config):
        self.config = config
        self.ble = None  # BleLights, set up by the tray app on Windows

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
        if self.config.get("lights_link", "bluetooth") == "bluetooth":
            if not (self.ble and self.ble.send(signal)):
                log_error(f"Quiz lights: Bluetooth isn't running; skipped {signal!r}")
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
        self.code_line = None  # CodeLine, set up by the tray app on Windows
        self.thinking = None   # set while the Caps Lock "thinking" flash runs
        self.code_shots = []   # coding mode: (time, screenshot) parts of the current long problem
        self.stop = threading.Event()
        # The revision log is written by its own thread, after the answer is on its way to the watch.
        self.log_jobs = queue.Queue()
        threading.Thread(target=self._log_worker, daemon=True).start()

    def set_status(self, state):
        if state == "working" and self.config.get("caps_thinking", True) and self.thinking is None:
            self.thinking = threading.Event()
            threading.Thread(target=caps_thinking, args=(self.thinking,), daemon=True).start()
        elif state != "working":
            self.stop_thinking()
        self.status_callback(state)

    def stop_thinking(self):
        if self.thinking is not None:
            self.thinking.set()
            self.thinking = None

    def run(self, region=False):
        """Hotkey handler: captures, solves and delivers on a background thread."""
        if not self.busy.acquire(blocking=False):
            return  # already working on one; ignore repeated presses
        threading.Thread(target=self._run, args=(region,), daemon=True).start()

    def _run(self, region):
        if self.config.get("mode") == "coding":
            return self._run_code(region)
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
                # shown; the next two models get a try instead.
                for skip in (0, 1, 2):
                    result = parse_answer(self.claude.solve(current, notes, earlier_images, skip=skip))
                    if result["ok"]:
                        return result
                raise RuntimeError("The AI didn't give a usable answer. Tap Right Ctrl to try again.")

            result = ask()
            not_visible = "question not visible" in result["answer"].lower()
            if earlier and (not_visible or ("Need:" in result["answer"] and not result["new_set"])):
                # The notes weren't enough (e.g. it needs a chart no earlier question used):
                # ask again with the last few screenshots themselves.
                # Also for bare answer choices whose question was on the previous screen.
                retry = ask(earlier)
                result = dict(retry, context=retry["context"] or result["context"])
                if not_visible and "question not visible" not in result["answer"].lower():
                    result["new_set"] = False  # it continued the previous question: keep the memory
            if result["new_set"]:
                self.forget()  # a different question set: old charts and passages must not leak in
            self.remember(result["context"], current)
            session_id = secrets.token_hex(4)
            log_path = LOG_DIR / f"revision-{datetime.now():%Y-%m}.md"
            self.session = dict(result, id=session_id, next=0, log=log_path)
            self.stop_thinking()  # before the Caps Lock count, so the two never mix
            message = lights_message(result)
            if message:  # a letter, or a number (even for a question whose options are on the next screen)
                self.watch.lights(message)
            elif "unfinished question" in result["context"].lower():
                pass  # nothing to show yet: its options are on the next screen
            else:
                self.watch.lights("none")
            if self.config.get("caps_lights"):
                threading.Thread(target=caps_count, args=(lights_letters(result),), daemon=True).start()
            if self.config.get("point_answer") and not region:
                threading.Thread(target=point_at_answer, args=(image, result, self.config.get("label_style", "light")),
                                 daemon=True).start()
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

    def _run_code(self, region):
        """Coding mode: reads the problem (and any starter code) and shows the solution one line at a time."""
        try:
            image = capture_region() if region else capture_screen(self.config.get("capture", "gdi"))
            if image is None:
                return
            self.set_status("working")
            # A long question can take two or three screenshots: each press within a few minutes adds
            # the new screenshot to the earlier ones and solves using all of them together.
            now = time.time()
            self.code_shots = [(at, shot) for at, shot in self.code_shots if now - at < self.CODE_SHOTS_WINDOW]
            self.code_shots = (self.code_shots + [(now, image)])[-self.CODE_SHOTS_MAX:]
            shots = [shot for _, shot in self.code_shots]
            if len(shots) == 1:
                content = [{"type": "text", "text": "Solve the Python problem on this screen:"}]
            else:
                content = [{"type": "text", "text": (
                    f"These {len(shots)} screenshots were taken in order while scrolling. Together they are usually "
                    "ONE long problem: join them (ignore overlap). If the last screenshot shows a different, new "
                    "problem, solve only that one and ignore the earlier screenshots.")}]
            content += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{to_jpeg_base64(shot)}"}}
                        for shot in shots]
            title, lines = "", []
            for skip in (0, 1, 2):  # a reply without usable code gets tries with the next two models
                raw = self.claude.chat([{"role": "system", "content": CODING_RULES},
                                        {"role": "user", "content": content}], max_tokens=8000, skip=skip)
                title, lines = parse_code(raw)
                if lines:
                    break
            if not lines:
                raise RuntimeError("No Python problem found on screen. Tap Right Ctrl to try again.")
            if self.code_line:
                self.code_line.show(lines)
            self.set_status("idle")
            try:  # the whole program on your phone too, for reference
                self.watch.send(f"💻 {title}", "\n".join(lines), priority=3)
            except requests.RequestException:
                log_error(traceback.format_exc())
        except Exception as error:  # noqa: BLE001
            log_error(traceback.format_exc())
            self.set_status("error")
            try:
                self.watch.send("⚠️ Study Watch", str(error)[:500], priority=3)
            except requests.RequestException:
                pass
        finally:
            self.busy.release()

    CODE_SHOTS_WINDOW = 300  # coding mode: screenshots this recent (seconds) count as parts of one problem
    CODE_SHOTS_MAX = 3

    def new_code_problem(self):
        """Forget the earlier coding screenshots, so the next press starts a fresh problem."""
        self.code_shots = []

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


ICON_COLOURS = {"idle": "#3b6fd8", "working": "#e0a020", "error": "#d03838", "nobox": "#8a4fd0"}
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
    import faulthandler

    import keyboard
    import pystray

    try:  # a sudden crash (no Python error) still leaves a note in crash.log
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        faulthandler.enable(file=(CONFIG_DIR / "crash.log").open("a", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass

    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor: capture at real resolution
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()

    app = StudyWatch()
    LABEL_LOOK.update(size=int(app.config.get("label_size", 13)), opacity=float(app.config.get("label_opacity", 0.2)))
    global OVERLAY
    app.code_line = OVERLAY = CodeLine(app.config, on_done=app.new_code_problem)
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
        if app.config.get("mode") == "coding":  # only in coding mode, so these keys work normally otherwise
            add_hotkey("page down", app.code_line.next)      # these two keys are taken over in coding mode
            add_hotkey("page up", app.code_line.previous)
            add_hotkey("insert", app.code_line.toggle)
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
            show_status("idle")
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
        show_status(status["state"])

    def set_link(link):
        app.config["lights_link"] = link
        save_config(app.config)
        show_status(status["state"])

    def lights_mode(mode):
        threading.Thread(target=app.watch.lights, args=(f"mode {mode}",), daemon=True).start()

    def toggle_point(icon, item):
        app.config["point_answer"] = not app.config.get("point_answer")
        save_config(app.config)

    def set_mode(mode):
        app.config["mode"] = mode
        save_config(app.config)
        if mode != "coding":
            app.code_line.close()
        app.new_code_problem()
        register_hotkeys()

    def set_label_look(key, value):
        app.config[key] = value
        save_config(app.config)
        LABEL_LOOK.update(size=int(app.config.get("label_size", 13)), opacity=float(app.config.get("label_opacity", 0.2)))
        preview_label()

    def set_code(key, value):
        app.config[key] = value
        save_config(app.config)
        app.code_line.restyle()

    def preview_label():
        """Shows the label by the mouse pointer, so the class can compare the styles without a question."""
        import ctypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        where = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(where))
        show_label((where.x, where.y), "12", 5)

    def toggle_caps_thinking(icon, item):
        app.config["caps_thinking"] = not app.config.get("caps_thinking", True)
        save_config(app.config)

    def toggle_caps(icon, item):
        app.config["caps_lights"] = not app.config.get("caps_lights")
        save_config(app.config)

    def test_lights(icon, item):
        def run():
            app.watch.lights("thinking")
            time.sleep(4)
            letter = secrets.choice("ABCD")
            app.watch.lights(letter)
            if app.config.get("caps_lights"):
                caps_count([letter])
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
        pystray.MenuItem("Mode", pystray.Menu(
            pystray.MenuItem("Quiz (options and numbers)", lambda icon, item: set_mode("quiz"),
                             checked=lambda item: app.config.get("mode", "quiz") != "coding", radio=True),
            pystray.MenuItem("Coding (Python, line by line)", lambda icon, item: set_mode("coding"),
                             checked=lambda item: app.config.get("mode") == "coding", radio=True),
        )),
        pystray.MenuItem("Code line", pystray.Menu(
            *[pystray.MenuItem(f"Size: {name}", (lambda v: lambda icon, item: set_code("code_size", v))(size),
                               checked=(lambda v: lambda item: int(app.config.get("code_size", 13)) == v)(size),
                               radio=True)
              for name, size in CODE_SIZES.items()],
            pystray.Menu.SEPARATOR,
            *[pystray.MenuItem(f"See-through: {name}",
                               (lambda v: lambda icon, item: set_code("code_opacity", v))(opacity),
                               checked=(lambda v: lambda item: abs(float(app.config.get("code_opacity", 0.2)) - v)
                                        < 0.01)(opacity), radio=True)
              for name, opacity in CODE_OPACITIES.items()],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Next line (Page Down)", lambda icon, item: app.code_line.next()),
            pystray.MenuItem("Previous line (Page Up)", lambda icon, item: app.code_line.previous()),
            pystray.MenuItem("Hide / show (Insert)", lambda icon, item: app.code_line.toggle()),
            pystray.MenuItem("Close", lambda icon, item: (app.code_line.close(), app.new_code_problem())),
            pystray.MenuItem("Start a new problem (forget earlier screenshots)",
                             lambda icon, item: app.new_code_problem()),
        ), enabled=lambda item: app.config.get("mode") == "coding"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quiz lights", toggle_lights, checked=lambda item: app.config.get("lights")),
        pystray.MenuItem("Point the mouse at the answer", toggle_point,
                         checked=lambda item: app.config.get("point_answer")),
        pystray.MenuItem("Number label", pystray.Menu(
            *[pystray.MenuItem(f"Size: {name}", (lambda v: lambda icon, item: set_label_look("label_size", v))(size),
                               checked=(lambda v: lambda item: int(app.config.get("label_size", 13)) == v)(size),
                               radio=True)
              for name, size in LABEL_SIZES.items()],
            pystray.Menu.SEPARATOR,
            *[pystray.MenuItem(f"See-through: {name}",
                               (lambda v: lambda icon, item: set_label_look("label_opacity", v))(opacity),
                               checked=(lambda v: lambda item: abs(float(app.config.get("label_opacity", 0.2)) - v)
                                        < 0.01)(opacity), radio=True)
              for name, opacity in LABEL_OPACITIES.items()],
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Preview it", lambda icon, item: preview_label()),
        ), enabled=lambda item: app.config.get("point_answer")),
        pystray.MenuItem("Caps Lock light (counting)", toggle_caps,
                         checked=lambda item: app.config.get("caps_lights")),
        pystray.MenuItem("Flash Caps Lock while thinking", toggle_caps_thinking,
                         checked=lambda item: app.config.get("caps_thinking", True)),
        pystray.MenuItem("Test quiz lights", test_lights,
                         enabled=lambda item: app.config.get("lights") or app.config.get("caps_lights")),
        pystray.MenuItem("Quiz lights connection", pystray.Menu(
            pystray.MenuItem("Bluetooth (laptop → box)", lambda icon, item: set_link("bluetooth"),
                             checked=lambda item: app.config.get("lights_link", "bluetooth") == "bluetooth",
                             radio=True),
            pystray.MenuItem("Wi-Fi (through ntfy)", lambda icon, item: set_link("wifi"),
                             checked=lambda item: app.config.get("lights_link") == "wifi", radio=True),
        ), enabled=lambda item: app.config.get("lights")),
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

    status = {"state": "idle"}

    def show_status(state):
        status["state"] = state
        title = {"idle": "Study Watch", "working": "Study Watch: working…",
                 "error": "Study Watch: last request failed (see watch)"}[state]
        if app.config.get("lights") and app.config.get("lights_link", "bluetooth") == "bluetooth":
            box = app.watch.ble is not None and app.watch.ble.connected
            title += " · light box: " + ("connected" if box else app.watch.ble.reason if app.watch.ble else "starting…")
            if state == "idle" and not box:
                state = "nobox"
        icon.icon = icons[state]
        icon.title = title

    app.status_callback = show_status
    app.watch.ble = BleLights(
        lambda: bool(app.config.get("lights")) and app.config.get("lights_link", "bluetooth") == "bluetooth",
        lambda connected: show_status(status["state"]), app.config,
        lambda text: app.run(region=False) if text.strip().upper() == "SOLVE" else None)
    hotkey_ok = register_hotkeys()
    threading.Thread(target=app.send_ready, args=(hotkey_ok,), daemon=True).start()
    threading.Thread(target=app.watch.listen, args=(app.handle_command, app.stop), daemon=True).start()
    show_status("idle")
    if not app.config["openrouter_key"]:
        icon.icon = icons["error"]
        os.startfile(CONFIG_FILE)
    icon.run()


if __name__ == "__main__":
    main()
