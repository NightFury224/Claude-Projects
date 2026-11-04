"""Checks the watch-formatting helpers (run: python test_text.py)."""
import study_watch as s

assert s.to_watch_text(r"$x^2 \leq \pi$") == "x² ≤ π"
assert s.to_watch_text(r"\frac{1}{\sqrt{x+1}}") == "(1)/(√(x+1))"
assert s.to_watch_text("a_1 and **bold**") == "a₁ and bold"

parsed = s.parse_answer('```json\n{"question": "Solve x^2=4", "answer": "x = ±2", "steps": ["a", "b"]}\n```')
assert parsed == {"question": "Solve x²=4", "answer": "x = ±2", "steps": ["a", "b"]}
assert s.parse_answer("No JSON here.")["steps"] == ["No JSON here."]
assert all(len(p) <= s.NTFY_LIMIT for p in s.split_text("word " * 2000, s.NTFY_LIMIT))
# The model corrected itself: the last complete JSON object wins.
corrected = ('{"question": "Avg", "answer": "B) 21", "steps": ["x"]} Wait, check: x = 20. '
             '{"work": "9x+100=10(x+8)", "question": "Avg", "answer": "C) 28", "steps": ["x = 20", "20 + 8 = 28"]}')
assert s.parse_answer(corrected)["answer"] == "C) 28"
# A cut-off second object falls back to the first complete one.
assert s.parse_answer('{"answer": "C) 28", "steps": []} {"answer": "C) 2')["answer"] == "C) 28"
print("ok")
