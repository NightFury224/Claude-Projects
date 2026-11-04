"""Checks the watch-formatting helpers (run: python test_text.py)."""
import study_watch as s

assert s.to_watch_text(r"$x^2 \leq \pi$") == "x² ≤ π"
assert s.to_watch_text(r"\frac{1}{\sqrt{x+1}}") == "(1)/(√(x+1))"
assert s.to_watch_text("a_1 and **bold**") == "a₁ and bold"

parsed = s.parse_answer('```json\n{"question": "Solve x^2=4", "answer": "x = ±2", "steps": ["a", "b"]}\n```')
assert parsed == {"question": "Solve x²=4", "answer": "x = ±2", "steps": ["a", "b"], "context": ""}
assert s.parse_answer("No JSON here.")["steps"] == ["No JSON here."]
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
assert chart["context"].startswith("Income Rs 33,650")

# Memory keeps the last few notes and skips empty or repeated ones.
app = s.StudyWatch.__new__(s.StudyWatch)
app.memory, app.screens = [], []
for note in ["a", "", "a", "b", "c", "d", "e"]:
    app.remember(note)
assert app.recent_notes() == ["b", "c", "d", "e"]
for shot in ["img1", "img2", "img3"]:
    app.remember("", shot)
assert app.recent_images() == ["img2", "img3"]
print("ok")
