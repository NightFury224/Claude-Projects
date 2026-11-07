"""Checks the watch-formatting helpers (run: python test_text.py)."""
import study_watch as s

assert s.to_watch_text(r"$x^2 \leq \pi$") == "x² ≤ π"
assert s.to_watch_text(r"\frac{1}{\sqrt{x+1}}") == "(1)/(√(x+1))"
assert s.to_watch_text("a_1 and **bold**") == "a₁ and bold"

parsed = s.parse_answer('```json\n{"question": "Solve x^2=4", "answer": "x = ±2", "steps": ["a", "b"]}\n```')
assert parsed == {"question": "Solve x²=4", "answer": "x = ±2", "steps": ["a", "b"], "context": "",
                  "new_set": False, "options": [], "numbers": [], "point": None, "ok": True}
# Plain text (like a thinking model's raw thoughts) is marked unusable, so it's retried, never shown.
assert s.parse_answer("We need to solve the MCQs. Let's parse: ...")["ok"] is False
assert all(len(p) <= s.NTFY_LIMIT for p in s.split_text("word " * 2000, s.NTFY_LIMIT))
# The model corrected itself: the last complete JSON object wins.
corrected = ('{"question": "Avg", "answer": "B) 21", "steps": ["x"]} Wait, check: x = 20. '
             '{"work": "9x+100=10(x+8)", "question": "Avg", "answer": "C) 28", "steps": ["x = 20", "20 + 8 = 28"]}')
assert s.parse_answer(corrected)["answer"] == "C) 28"
# A cut-off second object falls back to the first complete one.
assert s.parse_answer('{"answer": "C) 28", "steps": []} {"answer": "C) 2')["answer"] == "C) 28"
# Raw line breaks inside strings (what Claude sent for a two-question screen).
two = ('{"work":"Q2: T+F=81, W=39. Q3: 27.","question":"Q2\nQ3: averages",'
       '"answer":"Q2: A) 39°C · Q3: B) 27","steps":["Q2: T+F = 81","Q3: middle = 27"]}')
assert s.parse_answer(two)["answer"] == "Q2: A) 39°C · Q3: B) 27"
# An unescaped quote breaks JSON; fields are still recovered and "work" is never shown.
broken = '{"work": "12" ruler", "question": "Length", "answer": "C) 12 in", "steps": ["read scale"]}'
parsed = s.parse_answer(broken)
assert parsed["answer"] == "C) 12 in" and parsed["steps"] == ["read scale"], parsed
# Free image models are ranked best first; paid and text-only models are left out.
models = [
    {"id": "google/gemma-3-4b-it:free", "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"input_modalities": ["text", "image"]}},
    {"id": "qwen/qwen2.5-vl-72b-instruct:free", "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"input_modalities": ["text", "image"]}},
    {"id": "openai/gpt-5", "pricing": {"prompt": "0.00001", "completion": "0.00003"},
     "architecture": {"input_modalities": ["text", "image"]}},
    {"id": "deepseek/deepseek-r1:free", "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"input_modalities": ["text"]}},
]
ai = s.Claude({"model": "auto"})
s.requests.get = lambda *a, **k: type("R", (), {"json": lambda self: {"data": models}})()
assert ai.models() == ["qwen/qwen2.5-vl-72b-instruct:free", "google/gemma-3-4b-it:free"], ai.models()
# A stuck model's "..." never reaches the watch, and shared chart data is kept as context.
stuck = s.parse_answer('{"work": "no chart", "question": "Q2–Q4", "answer": "...", "steps": ["..."], '
                       '"context": ""}')
assert stuck["answer"].startswith("No answer") and stuck["steps"] == []
chart = s.parse_answer('{"question": "Pie chart Q1", "answer": "C) Rs. 6057", "steps": [], '
                       '"context": "Income Rs 33,650. Food 25%, Rent 18%, PF 12%"}')
assert chart["context"].startswith("Income Rs 33,650") and chart["new_set"] is False
assert s.parse_answer('{"answer": "B) 3", "context": "", "new_set": true}')["new_set"] is True

# Memory keeps the last few notes and skips empty or repeated ones.
app = s.StudyWatch.__new__(s.StudyWatch)
app.memory, app.screens = [], []
for note in ["a", "", "a", "b", "c", "d", "e"]:
    app.remember(note)
assert app.recent_notes() == ["b", "c", "d", "e"]
for shot in ["img1", "img2", "img3"]:
    app.remember("", shot)
assert app.recent_images() == ["img2", "img3"]
# rules.txt is created with the defaults, edits are picked up, and the reply format is always appended.
import tempfile
from pathlib import Path
s.CONFIG_DIR = Path(tempfile.mkdtemp())
s.RULES_FILE = s.CONFIG_DIR / "rules.txt"
assert s.system_prompt().startswith(s.DEFAULT_RULES.strip()) and s.system_prompt().endswith(s.REPLY_FORMAT)
s.RULES_FILE.write_text("Answer in French.", encoding="utf-8")
assert s.system_prompt() == "Answer in French.\n\n" + s.SPLIT_QUESTIONS + "\n\n" + s.REPLY_FORMAT
s.RULES_FILE.write_text("  ", encoding="utf-8")  # emptied file falls back to the defaults
assert s.load_rules() == s.DEFAULT_RULES.strip()
# A broken config.json still loads: key and topic are rescued, problems are listed, the file is kept.
s.CONFIG_FILE = s.CONFIG_DIR / "config.json"
broken_json = '{"openrouter_key": "sk-or-123", "ntfy_topic": "studywatch-abc" "capture": "wgc",}'
s.CONFIG_FILE.write_text(broken_json, encoding="utf-8")
problems = []
config = s.load_config(problems)
assert config["openrouter_key"] == "sk-or-123" and config["ntfy_topic"] == "studywatch-abc", config
assert config["capture"] == "wgc" and problems and "mistake" in problems[0], problems
assert s.CONFIG_FILE.read_text(encoding="utf-8") == broken_json
# Wrong types and values fall back to defaults with a note.
s.CONFIG_FILE.write_text('{"openrouter_key": "k", "ntfy_topic": "t", "capture": "gpu", "save_screenshots": "yes"}',
                         encoding="utf-8")
problems = []
config = s.load_config(problems)
assert config["capture"] == "gdi" and config["save_screenshots"] is True and len(problems) == 2, problems
# Option letters for the quiz lights.
assert s.option_letters("B) 27") == ["B"]
assert s.option_letters("Q1: B) 27 · Q2: 39°C · Q3: d) True") == ["B", "-", "D"]
assert s.option_letters("(C) Paris") == ["C"] and s.option_letters("E") == ["E"]
assert s.option_letters("Rs. 6057") == ["-"]
print("ok")

# The model's own option letters are used even when the answer shows only values.
_r = s.parse_answer('{"work":"x","question":"q","answer":"0.005 · 1/3","steps":[],"context":"","new_set":false,"options":"C,B"}')
assert _r["options"] == ["C", "B"], _r
assert s.option_list("B,-,D") == ["B", "-", "D"] and s.option_list("") == [] and s.option_list("-,-") == []
assert s.option_letters("Q3: C 0.005 · Q4: B 1/3") == ["C", "B"]
assert s.option_letters("Q3: 0.005 (C)\nQ4: ⅓ (B)") == ["C", "B"]
assert s.option_letters("Q2: A big dog") == ["-"]
print("options ok")

# One question: a list of every choice is ignored; the answer text decides.
assert s.lights_letters({"answer": "C) 54,080", "options": ["A", "B", "C", "D"]}) == ["C"]
assert s.lights_letters({"answer": "54,080", "options": ["A", "B", "C", "D"]}) == ["-"]
assert s.lights_letters({"answer": "54,080", "options": ["C"]}) == ["C"]
assert s.lights_letters({"answer": "Q3: 0.005 · Q4: 1/3", "options": ["C", "B"]}) == ["C", "B"]
print("lights letters ok")

# Numbers for the binary mode.
assert s.number_list("12") == ["12"] and s.number_list("-,4.25") == ["-", "4.25"]
assert s.number_list("0.333") == ["0.33"] and s.number_list("12.50") == ["12.5"] and s.number_list("x") == []
assert s.lights_message({"answer": "12", "numbers": ["12"]}) == ":12"
assert s.lights_message({"answer": "C) 54,080", "options": ["C"], "numbers": []}) == "C"
assert s.lights_message({"answer": "Q1: B) 27 · Q2: 4.25", "options": ["B", "-"], "numbers": ["-", "4.25"]}) == "B,:4.25"
assert s.lights_message({"answer": "Paris", "numbers": []}) is None
print("numbers ok")

# Caps Lock counting is Windows-only; elsewhere it does nothing (and never raises).
s.caps_count(["C", "-"])
print("caps ok")

# Pointing at the answer.
from types import SimpleNamespace as _R
assert s.point_value("0.18,0.62") == [(0.18, 0.62)] and s.point_value("18, 62") == [(0.18, 0.62)]
assert s.point_value("0.18,0.42; 0.2,0.81") == [(0.18, 0.42), (0.2, 0.81)] and s.point_value([[0.1, 0.2]]) == [(0.1, 0.2)]
assert s.point_value("") is None and s.point_value("x") is None and s.point_value("150,20") is None
_lines = [("C) 0.005", 100, 400, 80, 20, _R(x=100, y=400, width=20, height=20)),
          ("C) 1/3", 100, 900, 80, 20, _R(x=100, y=900, width=20, height=20)),
          ("B) 0.02", 100, 350, 80, 20, _R(x=100, y=350, width=20, height=20))]
assert s.find_option(_lines, "C", (300, 420), 300) == (110, 410)   # nearest C), not the B) above it
assert s.find_option(_lines, "C", (300, 880), 300) == (110, 910)
assert s.find_option(_lines, "D", (300, 420), 300) == (110, 460)  # worked out from B) and C)
assert s.find_option(_lines[:1], "D", (300, 420), 300) is None
s.LAST_LAYOUT = [(0, 0, 1920, 1080, 0, 0), (1920, 0, 1920, 1080, -1920, 0)]
assert s.image_to_screen(110, 410) == (110, 410) and s.image_to_screen(2000, 10) == (-1840, 10)
print("pointer ok")

# Number answers are found even when the model leaves "numbers" empty.
assert s.answer_numbers("12") == ["12"] and s.answer_numbers("Q1: x = 4.25 cm · Q2: B) 3") == ["4.25", "-"]
assert s.answer_numbers("54,080") == ["54080"] and s.answer_numbers("Paris") == ["-"]
assert s.lights_message({"answer": "12", "numbers": []}) == ":12"
assert s.lights_message({"answer": "Q1: C) 0.005 · Q2: 7", "options": ["C", "-"], "numbers": []}) == "C,:7"
print("numbers fallback ok")

# Unlabelled options and number boxes.
assert s.point_value("0.2,0.4; -; 0.3,0.8") == [(0.2, 0.4), None, (0.3, 0.8)]
assert s.option_value("Q2: C) 70 kg") == "70 kg" and s.option_value("70") == "70" and s.option_value("B. 60") == "60"
_boxes = [("☐ 50", 100, 300, 60, 20, _R(x=100, y=300, width=12, height=20)),
          ("☐ 70", 100, 360, 60, 20, _R(x=100, y=360, width=12, height=20)),
          ("☐ 170", 100, 420, 60, 20, _R(x=100, y=420, width=12, height=20))]
assert s.find_option(_boxes, "B", (120, 365), 200, value="70") == (106, 370)  # its tick box
assert s.find_option(_boxes, "B", (120, 365), 200, value="7O") == (106, 370)  # O read for 0
assert s.text_matches("B) The train is faster than the car by 20 km", "The train is faster than the car by 20 km/h")
assert not s.text_matches("☐ 170", "70")
assert s.snap_to_line(_boxes, 120, 335, 25) == (120, 310)
assert s.find_option(_boxes, "B", (120, 365), 200, value="") is None
print("unlabelled ok")

# A question whose options are cut off, with a number answer, still shows the number.
assert s.lights_message({"answer": "54080", "options": [], "numbers": [], "context": "Unfinished question: …"}) == ":54080"
print("unfinished number ok")

title, lines = s.parse_code('{"work":"x","title":"Evens","lines":["n = int(input())","if n % 2 == 0:","\tprint(1)",""]}')
assert title == "Evens" and lines == ["n = int(input())", "if n % 2 == 0:", "    print(1)"], lines
assert s.parse_code("```python\nx = 1\n\nprint(x)\n```")[1] == ["x = 1", "print(x)"]
assert s.parse_code("no code here")[1] == []
print("coding mode ok")

assert s.load_config()["code_size"] in s.CODE_SIZES.values()
print("code sizes ok")
